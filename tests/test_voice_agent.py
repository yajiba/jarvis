import unittest
from unittest.mock import Mock

from main import voice_agent_loop


class VoiceAgentTests(unittest.TestCase):
    def test_wake_commands_use_agent_and_speaker_until_stop(self) -> None:
        wake_input = Mock()
        wake_input.listen_and_transcribe.side_effect = ["What time is it?", "stop listening"]
        agent = Mock()
        agent.messages = [{"role": "assistant", "content": "It is noon."}]
        speaker = Mock()

        voice_agent_loop(agent, speaker, wake_input)

        agent.respond_stream.assert_called_once()
        speaker.speak.assert_called_once_with("It is noon.")
        self.assertEqual(wake_input.listen_and_transcribe.call_count, 2)

    def test_voice_agent_reset_does_not_call_model(self) -> None:
        wake_input = Mock()
        wake_input.listen_and_transcribe.side_effect = ["/reset", "quit"]
        agent = Mock()

        voice_agent_loop(agent, None, wake_input)

        agent.reset.assert_called_once()
        agent.respond_stream.assert_not_called()


if __name__ == "__main__":
    unittest.main()
