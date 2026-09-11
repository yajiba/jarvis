"""Push-to-talk microphone controller."""

from .audio import MicrophoneRecorder, VoiceInputError
from .stt import WhisperTranscriber


class PushToTalkTranscriber:
    def __init__(
        self,
        model_name: str = "base.en",
        sample_rate: int = 16_000,
        device: str = "cpu",
    ) -> None:
        self.recorder = MicrophoneRecorder(sample_rate=sample_rate)
        self.transcriber = WhisperTranscriber(model_name=model_name, device=device)

    def listen_and_transcribe(self) -> str:
        try:
            from pynput import keyboard
        except ImportError as error:
            raise VoiceInputError(
                "Push-to-talk dependencies are missing. Install with: pip install -e \".[voice]\""
            ) from error

        pressed = False
        audio = None

        def on_press(key) -> None:
            nonlocal pressed
            if key == keyboard.Key.space and not pressed:
                pressed = True
                self.recorder.start()

        def on_release(key):
            nonlocal audio
            if key == keyboard.Key.space and pressed:
                audio = self.recorder.stop()
                return False
            return True

        print("Hold Space to speak, then release Space.")
        try:
            with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
                listener.join()
        except VoiceInputError:
            raise
        except Exception as error:
            raise VoiceInputError(f"Push-to-talk failed: {error}") from error
        finally:
            self.recorder.cancel()
        if audio is None:
            raise VoiceInputError("No push-to-talk recording was captured")
        return self.transcriber.transcribe(audio)
