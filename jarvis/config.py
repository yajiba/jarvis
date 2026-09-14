"""Runtime configuration from the project .env file and environment."""

from dataclasses import dataclass
import os
import math
from pathlib import Path
from urllib.parse import urlsplit


def _read_env(path: Path) -> dict[str, str]:
    """Read simple KEY=value entries without modifying the process environment."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not key.strip().isidentifier():
            raise ValueError(f"Invalid .env entry on line {number}")
        value = value.strip()
        if value.startswith(("'", '"')):
            if len(value) < 2 or value[-1] != value[0]:
                raise ValueError(f"Invalid .env quoting on line {number}")
            value = value[1:-1]
        values[key.strip()] = value
    return values


@dataclass(frozen=True)
class Settings:
    ollama_host: str = "http://127.0.0.1:11434"
    model: str = "qwen3:8b"
    coding_model: str | None = None
    vision_model: str | None = None
    gui_enabled: bool = False
    camera_index: int = 0
    timeout_seconds: float = 120.0
    whisper_model: str = "base.en"
    audio_sample_rate: int = 16_000
    whisper_device: str = "cpu"
    tts_enabled: bool = False
    piper_model: str = "models/piper/en_US-lessac-medium.onnx"
    wakeword_model: str = "hey_jarvis"
    wakeword_threshold: float = 0.5
    wakeword_command_seconds: float = 6.0
    web_enabled: bool = True
    voice_agent_enabled: bool = False
    rag_semantic_enabled: bool = False
    allowed_roots: tuple[Path, ...] = ()

    @classmethod
    def from_environment(cls, env_path: Path | None = None) -> "Settings":
        values = _read_env(env_path if env_path is not None else Path(__file__).resolve().parent.parent / ".env")
        values.update(os.environ)
        timeout_value = values.get("JARVIS_TIMEOUT_SECONDS", "120")
        try:
            timeout_seconds = float(timeout_value)
        except ValueError as error:
            raise ValueError("JARVIS_TIMEOUT_SECONDS must be a number") from error
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("JARVIS_TIMEOUT_SECONDS must be a finite positive number")

        host = values.get("OLLAMA_HOST", cls.ollama_host).strip().rstrip("/")
        try:
            parsed = urlsplit(host)
            port = parsed.port
            valid = (
                parsed.scheme in {"http", "https"}
                and bool(parsed.hostname)
                and not any(character.isspace() for character in host)
                and parsed.username is None
                and parsed.password is None
                and not parsed.query
                and not parsed.fragment
                and (port is None or port > 0)
            )
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("OLLAMA_HOST must be a valid HTTP or HTTPS URL")

        web_value = values.get('JARVIS_WEB_ENABLED', 'true').strip().lower()
        if web_value not in {'1', 'true', 'yes', 'on', '0', 'false', 'no', 'off'}:
            raise ValueError('JARVIS_WEB_ENABLED must be true or false')
        allowed_roots: list[Path] = []
        gui_value = values.get('JARVIS_GUI_ENABLED', 'false').strip().lower()
        if gui_value not in {'1','true','yes','on','0','false','no','off'}:
            raise ValueError('JARVIS_GUI_ENABLED must be true or false')
        camera_index = int(values.get('JARVIS_CAMERA_INDEX', '0'))
        if not 0 <= camera_index <= 16:
            raise ValueError('JARVIS_CAMERA_INDEX must be between 0 and 16')
        for raw_root in values.get('JARVIS_ALLOWED_ROOTS', '').split(';'):
            if not raw_root.strip():
                continue
            allowed_root = Path(raw_root.strip()).expanduser().resolve()
            if not allowed_root.is_dir():
                raise ValueError(f'JARVIS_ALLOWED_ROOTS directory is unavailable: {allowed_root}')
            allowed_roots.append(allowed_root)
        return cls(
            ollama_host=host,
            model=values.get("JARVIS_MODEL", cls.model),
            coding_model=values.get("JARVIS_CODING_MODEL") or None,
            vision_model=values.get('JARVIS_VISION_MODEL') or None,
            gui_enabled=gui_value in {'1','true','yes','on'},
            camera_index=camera_index,
            timeout_seconds=timeout_seconds,
            whisper_model=values.get("JARVIS_WHISPER_MODEL", cls.whisper_model),
            audio_sample_rate=int(values.get("JARVIS_AUDIO_SAMPLE_RATE", cls.audio_sample_rate)),
            whisper_device=values.get("JARVIS_WHISPER_DEVICE", cls.whisper_device),
            tts_enabled=values.get("JARVIS_TTS_ENABLED", "false").lower() in {"1", "true", "yes", "on"},
            piper_model=values.get("JARVIS_PIPER_MODEL", cls.piper_model),
            wakeword_model=values.get("JARVIS_WAKEWORD_MODEL", cls.wakeword_model),
            wakeword_threshold=float(values.get("JARVIS_WAKEWORD_THRESHOLD", cls.wakeword_threshold)),
            wakeword_command_seconds=float(values.get("JARVIS_WAKEWORD_COMMAND_SECONDS", cls.wakeword_command_seconds)),
            web_enabled=web_value in {'1', 'true', 'yes', 'on'},
            voice_agent_enabled=values.get('JARVIS_VOICE_AGENT_ENABLED', 'false').strip().lower()
            in {'1', 'true', 'yes', 'on'},
            rag_semantic_enabled=values.get('JARVIS_RAG_SEMANTIC_ENABLED', 'false').strip().lower()
            in {'1', 'true', 'yes', 'on'},
            allowed_roots=tuple(dict.fromkeys(allowed_roots)),
        )
