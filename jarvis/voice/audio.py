"""Microphone recording primitives for local speech recognition."""

from collections.abc import Callable
import threading


class VoiceInputError(RuntimeError):
    """Raised when microphone capture cannot be completed."""


class MicrophoneRecorder:
    def __init__(self, sample_rate: int = 16_000, channels: int = 1) -> None:
        self.sample_rate = sample_rate
        self.channels = channels
        self._chunks: list[object] = []
        self._lock = threading.Lock()
        self._stream = None

    def start(self) -> None:
        try:
            import sounddevice as sd
        except ImportError as error:
            raise VoiceInputError(
                "Voice dependencies are missing. Install with: pip install -e \".[voice]\""
            ) from error

        with self._lock:
            if self._stream is not None:
                raise VoiceInputError("Microphone recording is already active")
            self._chunks = []

        def capture(data, frames, timing, status) -> None:
            if status:
                return
            with self._lock:
                self._chunks.append(data.copy())

        stream = None
        try:
            stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                dtype="float32",
                callback=capture,
            )
            stream.start()
        except Exception as error:
            if stream is not None:
                stream.close()
            raise VoiceInputError(f"Could not start microphone: {error}") from error
        with self._lock:
            self._stream = stream

    def stop(self):
        with self._lock:
            stream = self._stream
            self._stream = None
        if stream is None:
            raise VoiceInputError("Microphone recording is not active")
        try:
            try:
                stream.stop()
            finally:
                stream.close()
            with self._lock:
                chunks = list(self._chunks)
                self._chunks = []
            import numpy as np
            if not chunks:
                raise VoiceInputError("No microphone audio was captured")
            return np.concatenate(chunks, axis=0).reshape(-1)
        except VoiceInputError:
            raise
        except Exception as error:
            raise VoiceInputError(f"Could not finish microphone recording: {error}") from error

    def cancel(self) -> None:
        """Release microphone resources without attempting transcription."""
        with self._lock:
            stream = self._stream
            self._stream = None
            self._chunks = []
        if stream is not None:
            try:
                stream.abort()
            finally:
                stream.close()
