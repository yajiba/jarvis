import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from jarvis.config import Settings


class SettingsTests(unittest.TestCase):
    def test_web_can_be_disabled_and_invalid_flag_is_rejected(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            path = Path(directory) / '.env'
            os.environ['JARVIS_WEB_ENABLED'] = 'false'
            self.assertFalse(Settings.from_environment(path).web_enabled)
            os.environ['JARVIS_WEB_ENABLED'] = 'invalid'
            with self.assertRaisesRegex(ValueError, 'JARVIS_WEB_ENABLED'):
                Settings.from_environment(path)

    def test_invalid_hosts_are_rejected(self):
        with TemporaryDirectory() as directory:
            for host in ['', 'localhost:11434', 'ftp://localhost', 'http://',
                         'http://localhost:bad', 'http://localhost:70000',
                         'http://local host', 'http://[broken', 'http://localhost?x=1']:
                with self.subTest(host=host), patch.dict(os.environ, {'OLLAMA_HOST': host}):
                    with self.assertRaisesRegex(ValueError, 'OLLAMA_HOST'):
                        Settings.from_environment(Path(directory) / '.env')

    def test_http_and_https_hosts_are_supported(self):
        with TemporaryDirectory() as directory:
            for host in ['http://127.0.0.1:11434', 'https://localhost', 'http://[::1]:11434']:
                with self.subTest(host=host), patch.dict(os.environ, {}, clear=True):
                    os.environ['OLLAMA_HOST'] = host
                    self.assertEqual(Settings.from_environment(Path(directory) / '.env').ollama_host, host)

    def test_file_values_and_environment_precedence(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            path = Path(directory) / '.env'
            path.write_text(
                '\ufeff# Configuration\n\nOLLAMA_HOST=http://localhost:11434/\n'
                'JARVIS_MODEL="file-model"\nJARVIS_TIMEOUT_SECONDS=30.5\n',
                encoding='utf-8',
            )
            settings = Settings.from_environment(path)
            self.assertEqual(settings.model, 'file-model')
            self.assertEqual(settings.ollama_host, 'http://localhost:11434')
            self.assertEqual(settings.timeout_seconds, 30.5)
            self.assertNotIn('JARVIS_MODEL', os.environ)
            with patch.dict(os.environ, {'JARVIS_MODEL': 'shell-model'}):
                self.assertEqual(Settings.from_environment(path).model, 'shell-model')

    def test_optional_model_roles_are_loaded(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ, {
                'JARVIS_FAST_MODEL': 'fast', 'JARVIS_CODING_MODEL': 'coder',
                'JARVIS_DOCUMENT_MODEL': 'long-context', 'JARVIS_VISION_MODEL': 'vision'}, clear=True):
            settings = Settings.from_environment(Path(directory) / '.env')
            self.assertEqual(settings.fast_model, 'fast')
            self.assertEqual(settings.coding_model, 'coder')
            self.assertEqual(settings.document_model, 'long-context')
            self.assertEqual(settings.vision_model, 'vision')

    def test_missing_file_uses_defaults(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            self.assertEqual(Settings.from_environment(Path(directory) / '.env'), Settings())

    def test_allowed_roots_are_loaded_and_missing_roots_rejected(self):
        with TemporaryDirectory() as directory, TemporaryDirectory() as allowed:
            path = Path(directory) / '.env'
            path.write_text(f'JARVIS_ALLOWED_ROOTS={allowed};{directory}\n', encoding='utf-8')
            settings = Settings.from_environment(path)
            self.assertEqual(settings.allowed_roots, (Path(allowed).resolve(), Path(directory).resolve()))
            path.write_text('JARVIS_ALLOWED_ROOTS=missing-folder\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'JARVIS_ALLOWED_ROOTS'):
                Settings.from_environment(path)

    def test_invalid_timeouts_are_rejected(self):
        with TemporaryDirectory() as directory:
            for value in ['0', '-1', 'nan', 'inf', '-inf', 'abc', '']:
                with self.subTest(value=value), patch.dict(os.environ, {'JARVIS_TIMEOUT_SECONDS': value}):
                    with self.assertRaisesRegex(ValueError, 'JARVIS_TIMEOUT_SECONDS'):
                        Settings.from_environment(Path(directory) / '.env')

    def test_malformed_file_reports_line_without_value(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / '.env'
            for entry in ['invalid-entry', 'JARVIS_MODEL="unclosed']:
                path.write_text(entry, encoding='utf-8')
                with self.subTest(entry=entry), self.assertRaisesRegex(ValueError, 'line 1'):
                    Settings.from_environment(path)

    def test_voice_vision_and_rag_settings_are_validated(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            path = Path(directory) / '.env'
            invalid = {
                'JARVIS_TTS_ENABLED': 'perhaps',
                'JARVIS_VOICE_AGENT_ENABLED': 'sometimes',
                'JARVIS_RAG_SEMANTIC_ENABLED': 'maybe',
                'JARVIS_AUDIO_SAMPLE_RATE': '100',
                'JARVIS_WAKEWORD_THRESHOLD': '1.5',
                'JARVIS_WAKEWORD_COMMAND_SECONDS': '0',
                'JARVIS_CAMERA_INDEX': 'camera',
            }
            for name, value in invalid.items():
                with self.subTest(name=name), patch.dict(os.environ, {name: value}):
                    with self.assertRaisesRegex(ValueError, name):
                        Settings.from_environment(path)
