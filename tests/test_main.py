import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import main
from jarvis.config import Settings


class TerminalTests(unittest.TestCase):
    def test_interrupt_during_generation_ends_session_cleanly(self):
        output = io.StringIO()
        with patch.object(main.Settings, 'from_environment', return_value=Settings()), \
                patch('builtins.input', return_value='Hello'), \
                patch.object(main.OllamaClient, 'chat_message_stream', side_effect=KeyboardInterrupt), \
                redirect_stdout(output):
            main.run()
        self.assertIn('Session ended.', output.getvalue())

    def test_invalid_configuration_stops_before_chat(self):
        output = io.StringIO()
        with patch.object(main.Settings, 'from_environment', side_effect=ValueError('OLLAMA_HOST must be a valid HTTP or HTTPS URL')), \
                patch('builtins.input') as user_input, redirect_stdout(output):
            main.run()
        user_input.assert_not_called()
        self.assertIn('Jean configuration error: OLLAMA_HOST', output.getvalue())
