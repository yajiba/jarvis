import unittest
from unittest.mock import Mock, patch

from jarvis.voice.stt import WhisperTranscriber


class Segment:
    def __init__(self, text: str) -> None:
        self.text = text


class Model:
    def transcribe(self, audio, beam_size):
        return iter([Segment(" hello "), Segment("JARVIS")]), {"language": "en"}


class VoiceTests(unittest.TestCase):
    def test_transcriber_combines_segments(self) -> None:
        transcriber = WhisperTranscriber()
        transcriber._model = Model()
        audio = Mock(size=16000)

        self.assertEqual(transcriber.transcribe(audio), "hello JARVIS")

    def test_empty_audio_is_rejected(self) -> None:
        with self.assertRaisesRegex(Exception, "No microphone audio"):
            WhisperTranscriber().transcribe(Mock(size=0))

    @patch.dict("sys.modules", {"faster_whisper": None})
    def test_missing_whisper_dependency_is_explained(self) -> None:
        with self.assertRaisesRegex(Exception, "faster-whisper is missing"):
            WhisperTranscriber()._get_model()


if __name__ == "__main__":
    unittest.main()
