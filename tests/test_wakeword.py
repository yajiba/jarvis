import unittest
from unittest.mock import Mock, patch

from jarvis.voice.wakeword import WakeWordTranscriber


class WakeWordTests(unittest.TestCase):
    def test_threshold_and_duration_are_validated(self) -> None:
        with self.assertRaises(ValueError):
            WakeWordTranscriber(threshold=0)
        with self.assertRaises(ValueError):
            WakeWordTranscriber(threshold=1.1)
        with self.assertRaises(ValueError):
            WakeWordTranscriber(command_seconds=0)

    def test_prediction_threshold(self) -> None:
        listener = WakeWordTranscriber(threshold=0.6)
        listener._model = Mock()
        listener._model.predict.side_effect = [
            {"hey_jarvis": 0.59},
            {"hey_jarvis": 0.6},
        ]

        self.assertFalse(listener._detected([1, 2]))
        self.assertTrue(listener._detected([1, 2]))

    @patch.dict("sys.modules", {"openwakeword": None, "openwakeword.model": None})
    def test_missing_dependency_is_explained(self) -> None:
        listener = WakeWordTranscriber()

        with self.assertRaisesRegex(Exception, "Wake-word dependencies are missing"):
            listener._get_model()


if __name__ == "__main__":
    unittest.main()
