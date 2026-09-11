"""Local speech-to-text adapter using faster-whisper."""

from pathlib import Path

from .audio import VoiceInputError


class WhisperTranscriber:
    def __init__(
        self,
        model_name: str = "base.en",
        device: str = "cpu",
        compute_type: str = "int8",
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self._model = None

    def _get_model(self):
        if self._model is not None:
            return self._model
        try:
            from faster_whisper import WhisperModel
        except ImportError as error:
            raise VoiceInputError(
                "faster-whisper is missing. Install with: pip install -e \".[voice]\""
            ) from error
        try:
            self._model = WhisperModel(
                self.model_name,
                device=self.device,
                compute_type=self.compute_type,
            )
        except Exception as error:
            raise VoiceInputError(f"Could not load Whisper model {self.model_name}: {error}") from error
        return self._model

    def transcribe(self, audio) -> str:
        if getattr(audio, "size", 0) == 0:
            raise VoiceInputError("No microphone audio was captured")
        try:
            segments, _ = self._get_model().transcribe(audio, beam_size=5)
            text = " ".join(segment.text.strip() for segment in segments).strip()
        except Exception as error:
            raise VoiceInputError(f"Speech transcription failed: {error}") from error
        if not text:
            raise VoiceInputError("No speech was recognized")
        return text
