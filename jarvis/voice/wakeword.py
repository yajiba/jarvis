"""Local wake-word detection followed by a short spoken command capture."""

import queue

from .audio import VoiceInputError
from .stt import WhisperTranscriber


class WakeWordTranscriber:
    def __init__(
        self,
        wakeword: str = "hey_jarvis",
        model_name: str = "base.en",
        sample_rate: int = 16_000,
        device: str = "cpu",
        threshold: float = 0.5,
        command_seconds: float = 6.0,
    ) -> None:
        if not 0 < threshold <= 1:
            raise ValueError("wake-word threshold must be between 0 and 1")
        if command_seconds <= 0:
            raise ValueError("command_seconds must be positive")
        self.wakeword = wakeword
        self.sample_rate = sample_rate
        self.threshold = threshold
        self.command_seconds = command_seconds
        self.transcriber = WhisperTranscriber(model_name=model_name, device=device)
        self._model = None

    def _get_model(self):
        if self._model is not None:
            return self._model
        try:
            from openwakeword.model import Model
        except ImportError as error:
            raise VoiceInputError(
                "Wake-word dependencies are missing. Install with: "
                "pip install -e \".[wake-word]\""
            ) from error
        try:
            self._model = Model(
                wakeword_models=[self.wakeword],
                inference_framework="onnx",
            )
        except Exception as error:
            raise VoiceInputError(f"Could not load wake-word model {self.wakeword}: {error}") from error
        return self._model

    def _detected(self, audio) -> bool:
        prediction = self._get_model().predict(audio)
        if not isinstance(prediction, dict):
            return False
        score = prediction.get(self.wakeword, 0.0)
        return isinstance(score, (int, float)) and score >= self.threshold

    def listen_and_transcribe(self) -> str:
        try:
            import numpy as np
            import sounddevice as sd
        except ImportError as error:
            raise VoiceInputError(
                "Wake-word dependencies are missing. Install with: "
                "pip install -e \".[wake-word]\""
            ) from error

        model = self._get_model()
        model.reset()
        frames: queue.Queue = queue.Queue(maxsize=32)

        def capture(data, frame_count, timing, status) -> None:
            if not status:
                try:
                    frames.put_nowait(data.copy())
                except queue.Full:
                    pass

        print(f"Listening for {self.wakeword.replace('_', ' ').title()}...")
        try:
            with sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="int16",
                blocksize=1280,
                callback=capture,
            ):
                while True:
                    try:
                        audio = frames.get(timeout=0.2)
                    except queue.Empty:
                        continue
                    if self._detected(np.asarray(audio).reshape(-1)):
                        break
        except VoiceInputError:
            raise
        except Exception as error:
            raise VoiceInputError(f"Wake-word detection failed: {error}") from error

        print("Wake word detected. Speak now.")
        try:
            command = sd.rec(
                int(self.command_seconds * self.sample_rate),
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                blocking=True,
            )
            return self.transcriber.transcribe(np.asarray(command).reshape(-1))
        except VoiceInputError:
            raise
        except Exception as error:
            raise VoiceInputError(f"Wake-word command capture failed: {error}") from error
        finally:
            sd.stop()
