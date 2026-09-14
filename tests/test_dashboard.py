from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from jarvis.api.server import create_app
from jarvis.memory import MemoryStore


class DashboardTests(unittest.TestCase):
    def test_static_avatar_assets_are_served(self) -> None:
        from fastapi.testclient import TestClient
        with TemporaryDirectory() as directory, MemoryStore(Path(directory) / 'jarvis.db') as memory:
            agent = Mock(messages=[])
            with TestClient(create_app(agent, memory)) as client:
                page = client.get('/')
                asset = client.get('/ui/portrait-clean.png')
                self.assertEqual(page.status_code, 200)
                self.assertIn('JARVIS animated avatar', page.text)
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


if __name__ == "__main__":
    unittest.main()
