from pathlib import Path
from tempfile import TemporaryDirectory
from io import BytesIO
import unittest
from unittest.mock import Mock, patch
from zipfile import ZipFile

from jarvis.api.server import create_app
from jarvis.memory import MemoryStore


class DashboardTests(unittest.TestCase):
    @staticmethod
    def _pptx_bytes():
        data = BytesIO()
        with ZipFile(data, 'w') as archive:
            archive.writestr('ppt/presentation.xml', '''<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><p:sldIdLst><p:sldId id="256" r:id="rId1"/></p:sldIdLst></p:presentation>''')
            archive.writestr('ppt/_rels/presentation.xml.rels', '''<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="slides/slide1.xml"/></Relationships>''')
            archive.writestr('ppt/slides/slide1.xml', '''<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:t>Lesson title</a:t><a:t>Important point</a:t></p:sld>''')
        return data.getvalue()

    def test_static_avatar_assets_are_served(self) -> None:
        from fastapi.testclient import TestClient
        with TemporaryDirectory() as directory, MemoryStore(Path(directory) / 'jarvis.db') as memory:
            agent = Mock(messages=[])
            with TestClient(create_app(agent, memory)) as client:
                page = client.get('/')
                asset = client.get('/ui/portrait-clean.png')
                self.assertEqual(page.status_code, 200)
                self.assertIn('Jean animated avatar', page.text)
                self.assertEqual(asset.status_code, 200)
                self.assertEqual(asset.headers['content-type'], 'image/png')

    def test_dashboard_rejects_cross_origin_and_non_json_actions(self) -> None:
        from fastapi.testclient import TestClient
        with TemporaryDirectory() as directory, MemoryStore(Path(directory) / 'jarvis.db') as memory:
            agent = Mock(messages=[])
            with TestClient(create_app(agent, memory)) as client:
                self.assertEqual(client.post('/chat', content='message=hello').status_code, 415)
                self.assertEqual(client.post('/chat', json={'message':'hello'},
                                             headers={'Origin':'https://example.com'}).status_code, 403)
                self.assertEqual(client.post('/analyze-upload', content=b'hello', headers={
                    'Content-Type':'application/octet-stream', 'X-Filename':'notes.txt',
                    'X-Question':'Summarize', 'Origin':'https://example.com'}).status_code, 403)

    def test_dashboard_analyzes_dropped_text_and_images(self) -> None:
        from fastapi.testclient import TestClient
        with TemporaryDirectory() as directory, MemoryStore(Path(directory) / 'jarvis.db') as memory:
            agent = Mock(messages=[])
            agent.client.host = 'http://127.0.0.1:11434'
            agent.client.chat.return_value = 'These are lesson notes.'
            vision = Mock()
            vision.analyze_image_bytes.return_value = {
                'filename':'diagram.png', 'kind':'image', 'answer':'A labeled diagram.'}
            with TestClient(create_app(agent, memory, vision=vision)) as client:
                headers = {'Content-Type':'application/octet-stream',
                           'X-Filename':'lesson%20notes.txt',
                           'X-Question':'What%20should%20I%20study%3F'}
                response = client.post('/analyze-upload', content=b'Important concept', headers=headers)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()['answer'], 'These are lesson notes.')
                prompt = agent.client.chat.call_args.args[0]
                self.assertIn('UNTRUSTED FILE CONTENT', prompt[1]['content'])
                image_headers = {**headers, 'X-Filename':'diagram.png'}
                response = client.post('/analyze-upload', content=b'png bytes', headers=image_headers)
                self.assertEqual(response.json()['kind'], 'image')
                vision.analyze_image_bytes.assert_called_once()

    def test_dashboard_rejects_unsupported_or_oversized_uploads(self) -> None:
        from fastapi.testclient import TestClient
        with TemporaryDirectory() as directory, MemoryStore(Path(directory) / 'jarvis.db') as memory:
            agent = Mock(messages=[])
            headers = {'Content-Type':'application/octet-stream', 'X-Filename':'unsafe.exe',
                       'X-Question':'Analyze'}
            with TestClient(create_app(agent, memory)) as client:
                self.assertEqual(client.post('/analyze-upload', content=b'x', headers=headers).status_code, 400)
                headers['X-Filename'] = 'large.txt'
                headers['Content-Length'] = str(20 * 1024 * 1024 + 1)
                self.assertEqual(client.post('/analyze-upload', content=b'x', headers=headers).status_code, 413)

    def test_dashboard_analyzes_powerpoint_with_slide_metadata(self) -> None:
        from fastapi.testclient import TestClient
        with TemporaryDirectory() as directory, MemoryStore(Path(directory) / 'jarvis.db') as memory:
            agent = Mock(messages=[])
            agent.client.host = 'http://127.0.0.1:11434'
            agent.client.chat.return_value = 'A quick lesson overview.'
            headers = {'Content-Type':'application/octet-stream', 'X-Filename':'lesson.pptx',
                       'X-Question':'Give%20me%20a%20quick%20overview'}
            with TestClient(create_app(agent, memory)) as client:
                response = client.post('/analyze-upload', content=self._pptx_bytes(), headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['slide_count'], 1)
            self.assertFalse(response.json()['content_truncated'])
            self.assertIn('Slide 1: Lesson title', agent.client.chat.call_args.args[0][1]['content'])

    def test_dashboard_routes_documents_to_document_model(self) -> None:
        from fastapi.testclient import TestClient
        with TemporaryDirectory() as directory, MemoryStore(Path(directory) / 'jarvis.db') as memory:
            agent = Mock(messages=[])
            agent.client.host = 'http://127.0.0.1:11434'
            document_client = Mock(host='http://127.0.0.1:11434', model='document-test')
            document_client.chat.return_value = 'Specialized analysis.'
            headers = {'Content-Type':'application/octet-stream', 'X-Filename':'notes.txt',
                       'X-Question':'Analyze'}
            with TestClient(create_app(agent, memory, document_client=document_client)) as client:
                response = client.post('/analyze-upload', content=b'important notes', headers=headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['model'], 'document-test')
            document_client.chat.assert_called_once()
            agent.client.chat.assert_not_called()

    def test_uploaded_document_supports_follow_up_without_reupload(self) -> None:
        from fastapi.testclient import TestClient
        with TemporaryDirectory() as directory, MemoryStore(Path(directory) / 'jarvis.db') as memory:
            agent = Mock(messages=[])
            agent.client.host = 'http://127.0.0.1:11434'
            agent.client.model = 'test-model'
            agent.client.chat.side_effect = ['Initial review.', 'Three-question quiz.']
            headers = {'Content-Type':'application/octet-stream', 'X-Filename':'slides.txt',
                       'X-Question':'Review%20this'}
            with TestClient(create_app(agent, memory)) as client:
                first = client.post('/analyze-upload', content=b'Key fact about biology', headers=headers)
                context_id = first.json()['context_id']
                follow_up = client.post('/analyze-context', json={
                    'context_id': context_id, 'question': 'Create a short quiz'})
            self.assertEqual(follow_up.status_code, 200)
            self.assertEqual(follow_up.json()['answer'], 'Three-question quiz.')
            self.assertEqual(follow_up.json()['context_id'], context_id)
            self.assertIn('Key fact about biology', agent.client.chat.call_args.args[0][1]['content'])
            self.assertEqual(agent.client.chat.call_count, 2)

    def test_specific_slide_follow_up_sends_only_requested_slide(self) -> None:
        from jarvis.api.uploads import analyze_prepared_document
        client = Mock(host='http://127.0.0.1:11434', model='document-test')
        client.chat.return_value = 'Slide two explained.'
        prepared = {'filename':'lesson.pptx', 'slide_count':2, 'content_truncated':False,
                    'text':'Slide 1: Alpha details\n\nSlide 2: Beta details'}
        analyze_prepared_document(client, prepared, 'Explain slide 2')
        prompt = client.chat.call_args.args[0][1]['content']
        self.assertIn('Slide 2: Beta details', prompt)
        self.assertNotIn('Slide 1: Alpha details', prompt)

    def test_specific_slide_follow_up_rejects_missing_slide(self) -> None:
        from jarvis.api.uploads import analyze_prepared_document
        client = Mock(host='http://127.0.0.1:11434')
        prepared = {'filename':'lesson.pptx', 'slide_count':2, 'content_truncated':False,
                    'text':'Slide 1: Alpha\n\nSlide 2: Beta'}
        with self.assertRaisesRegex(ValueError, 'slide 3 is unavailable'):
            analyze_prepared_document(client, prepared, 'Review slide 3')
        client.chat.assert_not_called()

    def test_topic_follow_up_retrieves_only_relevant_slides(self) -> None:
        from jarvis.api.uploads import analyze_prepared_document
        client = Mock(host='http://127.0.0.1:11434', model='document-test')
        client.chat.return_value = 'Topic explained.'
        prepared = {'filename':'lesson.pptx', 'slide_count':3, 'content_truncated':False,
                    'text':'Slide 1: History\n\nSlide 2: Photosynthesis uses chlorophyll\n\nSlide 3: Algebra'}
        analyze_prepared_document(client, prepared, 'Explain chlorophyll')
        prompt = client.chat.call_args.args[0][1]['content']
        self.assertIn('Slide 2:', prompt)
        self.assertNotIn('Slide 1:', prompt)
        self.assertNotIn('Slide 3:', prompt)

    def test_dashboard_rejects_malformed_powerpoint_cleanly(self) -> None:
        from fastapi.testclient import TestClient
        with TemporaryDirectory() as directory, MemoryStore(Path(directory) / 'jarvis.db') as memory:
            agent = Mock(messages=[])
            agent.client.host = 'http://127.0.0.1:11434'
            headers = {'Content-Type':'application/octet-stream', 'X-Filename':'broken.pptx',
                       'X-Question':'Summarize'}
            with TestClient(create_app(agent, memory)) as client:
                response = client.post('/analyze-upload', content=b'not-a-zip', headers=headers)
            self.assertEqual(response.status_code, 400)
            self.assertIn('damaged', response.json()['detail'])

    def test_activity_is_reset_after_failed_chat(self) -> None:
        agent = Mock()
        app = create_app(agent, Mock())
        routes = {getattr(r, "path", ""): r.endpoint for r in app.routes if hasattr(r, 'endpoint')}
        def fail(*args):
            agent.on_activity("Searching the web")
            self.assertEqual(routes["/activity"]()["state"], "Searching the web")
            raise RuntimeError("Generation failed")
        agent.respond_stream.side_effect = fail
        with self.assertRaises(RuntimeError):
            routes["/chat"]({"message": "Hello"})
        self.assertEqual(routes["/activity"]()["state"], "Ready")
        agent.respond_stream.side_effect = None
        agent.respond_stream.return_value = "Hello"
        self.assertEqual(routes["/chat"]({"message": "Hello"}), {"response": "Hello"})

    def test_runtime_reports_model_and_voice(self) -> None:
        from types import SimpleNamespace
        from io import BytesIO
        settings = SimpleNamespace(model="test", ollama_host="http://localhost:11434",
                                   piper_model="models/piper/en_US-amy-medium.onnx", tts_enabled=True,
                                   timeout_seconds=600)
        app = create_app(Mock(), Mock(), settings)
        endpoint = next(r.endpoint for r in app.routes if getattr(r, "path", None) == "/runtime")
        with patch("jarvis.api.server.urlopen", return_value=BytesIO(b'{"models":[{"name":"test"}]}')):
            result = endpoint()
            self.assertEqual(result["connection"], "ready")
            self.assertEqual(result["voice"], "en_US-amy-medium")
            self.assertEqual(result["timeout_seconds"], 600.0)
        with patch("jarvis.api.server.urlopen", side_effect=OSError("Unavailable")):
            self.assertEqual(endpoint()["connection"], "offline")

    def test_speech_uses_configured_piper_voice(self) -> None:
        from types import SimpleNamespace
        from fastapi import HTTPException
        settings = SimpleNamespace(tts_enabled=True, piper_model="models/piper/en_US-amy-medium.onnx")
        with patch("jarvis.voice.tts.PiperSpeaker") as speaker:
            speaker.return_value.synthesize_wav.return_value = b"RIFF-test-audio"
            app = create_app(Mock(), Mock(), settings)
            endpoint = next(r.endpoint for r in app.routes if getattr(r, "path", None) == "/speech")
            response = endpoint({"text": "Hello"})
            self.assertEqual(response.media_type, "audio/wav")
            self.assertEqual(response.body, b"RIFF-test-audio")
            self.assertEqual(speaker.call_args.args[0].name, "en_US-amy-medium.onnx")
            speaker.return_value.synthesize_wav.assert_called_once_with("Hello")
            with self.assertRaises(HTTPException) as invalid:
                endpoint({"text": " "})
            self.assertEqual(invalid.exception.status_code, 400)
            settings.tts_enabled = False
            with self.assertRaises(HTTPException) as disabled:
                endpoint({"text": "Hello"})
            self.assertEqual(disabled.exception.status_code, 503)

    def test_dashboard_reports_missing_optional_dependency_clearly(self) -> None:
        with TemporaryDirectory() as directory, MemoryStore(Path(directory) / "jarvis.db") as memory:
            agent = Mock()
            try:
                app = create_app(agent, memory)
            except RuntimeError as error:
                self.assertIn("dashboard", str(error).lower())
            else:
                self.assertIsNotNone(app)

    def test_status_includes_runtime_fields(self) -> None:
        with TemporaryDirectory() as directory, MemoryStore(Path(directory) / "jarvis.db") as memory:
            agent = Mock()
            agent.messages = []
            settings = Mock(model="qwen3:8b", web_enabled=True, tts_enabled=True,
                            piper_model="voice.onnx")
            tools = Mock()
            tools.execute.return_value = {"result": {"available": False}}
            app = create_app(agent, memory, settings, tools)
            route = next(route for route in app.routes if getattr(route, "path", None) == "/status")
            payload = route.endpoint()
            self.assertIn("hardware", payload)
            self.assertIn("voice_ready", payload)

    def test_chat_stream_emits_tokens_and_completion(self) -> None:
        from fastapi.testclient import TestClient
        class StreamingAgent:
            messages = []
            diagnostics = {'model':'test', 'metrics':{'tokens_per_second':12.5}}
            on_activity = None
            def respond_stream(self, text, callback):
                callback('Hello')
                callback(' Jean')
                return 'Hello Jean'
        with TemporaryDirectory() as directory, MemoryStore(Path(directory) / 'jarvis.db') as memory:
            with TestClient(create_app(StreamingAgent(), memory)) as client:
                response = client.post('/chat-stream', json={'message':'Hello'})
        events = [__import__('json').loads(line) for line in response.text.splitlines()]
        self.assertEqual([event['type'] for event in events], ['token','token','done'])
        self.assertEqual(events[-1]['diagnostics']['model'], 'test')

    def test_dashboard_can_restore_a_saved_conversation(self) -> None:
        from fastapi.testclient import TestClient
        from jarvis.brain import Agent
        class Client:
            def chat_stream(self, messages, callback):
                return 'unused'
        with TemporaryDirectory() as directory, MemoryStore(Path(directory) / 'jarvis.db') as memory:
            conversation_id = memory.start_conversation()
            memory.add_message(conversation_id, 'user', 'Saved question')
            memory.add_message(conversation_id, 'assistant', 'Saved answer')
            agent = Agent(Client())
            with TestClient(create_app(agent, memory)) as client:
                listed = client.get('/conversations').json()['conversations']
                restored = client.post(f'/conversations/{conversation_id}/restore', json={})
        self.assertTrue(any(item['id'] == conversation_id for item in listed))
        self.assertEqual(restored.status_code, 200)
        self.assertEqual(agent.conversation_id, conversation_id)


if __name__ == "__main__":
    unittest.main()
