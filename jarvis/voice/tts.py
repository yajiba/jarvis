"""Local Piper text-to-speech output."""

from pathlib import Path
from io import BytesIO
from threading import Lock
import tempfile
import wave

from .audio import VoiceInputError


class PiperSpeaker:
    """Load a local Piper voice on first use and play synthesized WAV audio."""

    def __init__(self, model_path: Path, speaker: int | None = None) -> None:
        self.model_path = model_path
        self.speaker = speaker
        self._voice = None
        self._synthesis_lock = Lock()

    def synthesize_wav(self, text: str) -> bytes:
        """Generate WAV bytes for browser playback without using local speakers."""
        with self._synthesis_lock:
            try:
                buffer = BytesIO()
                with wave.open(buffer, "wb") as output:
                    self._get_voice().synthesize_wav(text.strip(), output)
                return buffer.getvalue()
            except VoiceInputError:
                raise
            except Exception as error:
                raise VoiceInputError(f"Speech output failed: {error}") from error

    def _get_voice(self):
        if self._voice is not None:
            return self._voice
        if not self.model_path.is_file():
            raise VoiceInputError(
                f"Piper voice model was not found: {self.model_path}. "
                "Download a Piper .onnx voice model and set JARVIS_PIPER_MODEL."
            )
        try:
            from piper import PiperVoice
        except ImportError as error:
            raise VoiceInputError(
                "Piper is missing. Install with: pip install -e \".[voice-output]\""
            ) from error
        try:
            self._voice = PiperVoice.load(str(self.model_path))
        except Exception as error:
            raise VoiceInputError(f"Could not load Piper voice: {error}") from error
        return self._voice

    def speak(self, text: str) -> None:
        cleaned_text = text.strip()
        if not cleaned_text:
            return
        voice = self._get_voice()
        try:
            import numpy as np
            import sounddevice as sd
        except ImportError as error:
            raise VoiceInputError(
                "Audio playback is missing. Install with: pip install -e \".[voice-output]\""
            ) from error

        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temporary:
                wav_path = Path(temporary.name)
            try:
                with wave.open(str(wav_path), "wb") as wav_file:
                    voice.synthesize_wav(cleaned_text, wav_file)
                with wave.open(str(wav_path), "rb") as wav_file:
                    audio = np.frombuffer(wav_file.readframes(wav_file.getnframes()), dtype=np.int16)
                    sample_rate = wav_file.getframerate()
                    channels = wav_file.getnchannels()
                if channels > 1:
                    audio = audio.reshape(-1, channels)
                try:
                    sd.play(audio, sample_rate)
                    sd.wait()
                finally:
                    sd.stop()
            finally:
                wav_path.unlink(missing_ok=True)
        except VoiceInputError:
            raise
        except Exception as error:
            raise VoiceInputError(f"Speech output failed: {error}") from error
