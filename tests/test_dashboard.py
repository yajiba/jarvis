from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from jarvis.api.server import create_app
from jarvis.memory import MemoryStore


class DashboardTests(unittest.TestCase):
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
