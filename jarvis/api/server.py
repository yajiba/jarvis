"""Optional FastAPI dashboard for the local JARVIS runtime."""

from pathlib import Path
from typing import Any
from threading import Lock
from urllib.request import urlopen
import json

from jarvis.memory import MemoryStore


def create_app(agent: Any, memory: MemoryStore, settings: Any = None, tools: Any = None):
    try:
        from fastapi import FastAPI, HTTPException
        from fastapi.responses import FileResponse, Response
    except ImportError as error:
        raise RuntimeError(
            'Dashboard dependencies are missing. Install with: pip install -e ".[dashboard]"'
        ) from error

    app = FastAPI(title="JARVIS Dashboard", version="1.0")
    ui_path = Path(__file__).parent / "ui" / "index.html"
    from jarvis.voice.tts import PiperSpeaker
    from jarvis.voice.audio import VoiceInputError

    model_path = Path(getattr(settings, "piper_model", None) or "models/piper/en_US-amy-medium.onnx")
    if not model_path.is_absolute():
        model_path = Path(__file__).resolve().parents[2] / model_path
    speaker = PiperSpeaker(model_path)
    activity = {"state": "Ready"}
    chat_lock = Lock()
    agent.on_activity = lambda value: activity.update(state=value)

    @app.get("/activity")
    def get_activity():
        return activity.copy()

    @app.get("/runtime")
    def runtime():
        connection = "offline"
        model = getattr(settings, "model", None)
        try:
            host = getattr(settings, "ollama_host", "http://127.0.0.1:11434")
            with urlopen(f"{host}/api/tags", timeout=2) as response:
                models = json.load(response).get("models", [])
            connection = "ready" if any(item.get("name") == model for item in models) else "model missing"
        except (OSError, ValueError, TypeError):
            pass
        return {"connection": connection, "model": model,
                "voice": model_path.stem, "engine": "Piper",
                "voice_enabled": bool(getattr(settings, "tts_enabled", False))}

    @app.post("/speech")
    def speech(payload: dict[str, Any]):
        if not getattr(settings, "tts_enabled", False):
            raise HTTPException(status_code=503, detail="Piper speech is disabled. Set JARVIS_TTS_ENABLED=true and restart the server.")
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip() or len(text) > 16000:
            raise HTTPException(status_code=400, detail="Speech text must contain 1 to 16000 characters.")
        try:
            return Response(speaker.synthesize_wav(text), media_type="audio/wav",
                            headers={"Cache-Control": "no-store"})
        except VoiceInputError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "online"}

    @app.get("/status")
    def status() -> dict[str, Any]:
        hardware = tools.execute("get_hardware_info", {}).get("result", {}) if tools else {}
        return {
            "status": "online",
            "model": getattr(settings, "model", None),
            "web_enabled": getattr(settings, "web_enabled", False),
            "conversation_messages": len(agent.messages),
            "hardware": hardware,
            "voice_ready": bool(getattr(settings, "tts_enabled", False)) and bool(
                getattr(settings, "piper_model", None)
            ) and Path(getattr(settings, "piper_model")).is_file(),
        }

    @app.get("/memory")
    def get_memory() -> dict[str, Any]:
        return {
            "preferences": memory.list_preferences(),
            "memories": memory.list_memories(),
            "tasks": memory.list_tasks(),
        }

    @app.get("/tasks")
    def get_tasks() -> list[dict[str, Any]]:
        return memory.list_tasks()

    @app.post("/chat")
    def chat(payload: dict[str, Any]) -> dict[str, str]:
        message = payload.get("message")
        if not isinstance(message, str) or not message.strip():
            raise HTTPException(status_code=400, detail="message must be a nonempty string")
        tokens: list[str] = []
        if not chat_lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail="JARVIS is handling another message. Please wait.")
        try:
            activity["state"] = "Thinking"
            response = agent.respond_stream(message, tokens.append)
        finally:
            activity["state"] = "Ready"
            chat_lock.release()
        return {"response": response}

    @app.get("/")
    def index():
        return FileResponse(ui_path)

    return app


def main() -> None:
    try:
        import uvicorn
    except ImportError as error:
        raise SystemExit('Install dashboard support with: pip install -e ".[dashboard]"') from error
    from jarvis.brain import Agent
    from jarvis.brain.llm import OllamaClient
    from jarvis.config import Settings

    settings = Settings.from_environment()
    memory = MemoryStore(Path("data") / "jarvis.db")
    from jarvis.tools import create_local_tools
    from jarvis.tools.projects import ProjectManager
    from jarvis.tools.web import WebClient
    root = Path(__file__).resolve().parents[2]
    projects = ProjectManager(root)
    tools = create_local_tools(root, projects=projects, memory=memory,
                               web=WebClient(enabled=settings.web_enabled),
                               allowed_roots=settings.allowed_roots)
    agent = Agent(OllamaClient(settings.ollama_host, settings.model, settings.timeout_seconds),
                  tools=tools, memory=memory)
    try:
        uvicorn.run(create_app(agent, memory, settings, tools), host="127.0.0.1", port=8765)
    finally:
        memory.close()


if __name__ == "__main__":
    main()
