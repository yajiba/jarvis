from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

from jarvis.voice.tts import PiperSpeaker
from jarvis.voice import VoiceInputError


class TtsTests(unittest.TestCase):
    def test_missing_model_is_reported_before_loading_piper(self) -> None:
        speaker = PiperSpeaker(Path("missing-voice.onnx"))

        with patch('pathlib.Path.is_file', return_value=False), patch.dict(
            sys.modules, {'piper': None, 'numpy': None, 'sounddevice': None}
        ):
            with self.assertRaisesRegex(VoiceInputError, "model was not found"):
                speaker.speak("Hello")

    def test_missing_playback_dependency_is_reported_with_loaded_voice(self) -> None:
        speaker = PiperSpeaker(Path('voice.onnx'))
        speaker._voice = Mock()
        with patch.dict(sys.modules, {'sounddevice': None}):
            with self.assertRaisesRegex(VoiceInputError, 'Audio playback is missing'):
                speaker.speak('Hello')
        speaker._voice.synthesize_wav.assert_not_called()

    def test_empty_text_does_not_load_model(self) -> None:
        speaker = PiperSpeaker(Path("missing-voice.onnx"))

        speaker.speak("   ")
        self.assertIsNone(speaker._voice)

    def test_speaker_loads_voice_lazily(self) -> None:
        model = Path("voice.onnx")
        speaker = PiperSpeaker(model)
        fake_voice = Mock()
        fake_piper = types.ModuleType("piper")
        fake_piper.PiperVoice = Mock(load=Mock(return_value=fake_voice))

        with patch("pathlib.Path.is_file", return_value=True), patch.dict(
            sys.modules, {"piper": fake_piper}
        ):
            self.assertIs(speaker._get_voice(), fake_voice)
            self.assertIs(speaker._get_voice(), fake_voice)
            fake_piper.PiperVoice.load.assert_called_once_with(str(model))


if __name__ == "__main__":
    unittest.main()
