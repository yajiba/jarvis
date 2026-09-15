"""Optional FastAPI dashboard for the local Jean runtime."""

from pathlib import Path
from typing import Any
from threading import Lock
from threading import Event, Thread
from urllib.request import urlopen
from urllib.parse import unquote
import json
import time
import uuid
import asyncio
from contextlib import asynccontextmanager

from jarvis.memory import MemoryStore


def create_app(agent: Any, memory: MemoryStore, settings: Any = None, tools: Any = None,
               scheduler=None, automation=None, approvals=None, vision=None, document_client=None):
    try:
        from fastapi import FastAPI, HTTPException, Request
        from fastapi.responses import FileResponse, Response, StreamingResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError as error:
        raise RuntimeError(
            'Dashboard dependencies are missing. Install with: pip install -e ".[dashboard]"'
        ) from error

    @asynccontextmanager
    async def lifespan(_app):
        if scheduler is not None:
            scheduler.start()
        try:
            yield
        finally:
            if approvals is not None:
                approvals.close()
            if scheduler is not None:
                from starlette.concurrency import run_in_threadpool
                await run_in_threadpool(scheduler.stop)

    app = FastAPI(title="Jean Dashboard", version="2.0", lifespan=lifespan)
    from starlette.middleware.trustedhost import TrustedHostMiddleware
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['localhost','127.0.0.1','[::1]','testserver'])

    @app.middleware('http')
    async def local_mutations(request, call_next):
        if request.method not in {'GET','HEAD','OPTIONS'}:
            origin = request.headers.get('origin')
            if origin and origin != str(request.base_url).rstrip('/'):
                return Response('Cross-origin actions are not allowed', status_code=403)
            content_type = request.headers.get('content-type','').lower()
            upload = request.url.path == '/analyze-upload' and content_type.startswith('application/octet-stream')
            if not upload and not content_type.startswith('application/json'):
                return Response('JSON is required', status_code=415)
        return await call_next(request)
    app.mount("/ui", StaticFiles(directory=Path(__file__).parent / "ui"), name="ui")
    ui_path = Path(__file__).parent / "ui" / "index.html"
    from jarvis.voice.tts import PiperSpeaker
    from jarvis.voice.audio import VoiceInputError

    model_path = Path(getattr(settings, "piper_model", None) or "models/piper/en_US-amy-medium.onnx")
    if not model_path.is_absolute():
        model_path = Path(__file__).resolve().parents[2] / model_path
    speaker = PiperSpeaker(model_path)
    activity = {"state": "Ready"}
    chat_lock = Lock()
    document_contexts = {}
    document_context_ttl = 30 * 60
    agent.on_activity = lambda value: activity.update(state=value)

    def remember_document(prepared):
        now = time.monotonic()
        for key, value in list(document_contexts.items()):
            if now - value['created_at'] > document_context_ttl:
                document_contexts.pop(key, None)
        while len(document_contexts) >= 4:
            oldest = min(document_contexts, key=lambda key: document_contexts[key]['created_at'])
            document_contexts.pop(oldest, None)
        context_id = uuid.uuid4().hex
        document_contexts[context_id] = {**prepared, 'created_at': now}
        return context_id

    @app.get("/activity")
    def get_activity():
        return activity.copy()

    @app.get("/runtime")
    def runtime():
        connection = "offline"
        model = getattr(settings, "model", None)
        installed = set()
        try:
            host = getattr(settings, "ollama_host", "http://127.0.0.1:11434")
            with urlopen(f"{host}/api/tags", timeout=2) as response:
            models = json.load(response).get("models", [])
            installed = {item.get('name') for item in models if isinstance(item, dict)}
            connection = "ready" if model in installed else "model missing"
        except (OSError, ValueError, TypeError):
            pass
        roles = {"general": model,
                 "fast": getattr(settings, 'fast_model', None),
                 "coding": getattr(settings, 'coding_model', None),
                 "document": getattr(settings, 'document_model', None),
                 "vision": getattr(settings, 'vision_model', None)}
        return {"connection": connection, "model": model,
                "assistant_name": getattr(settings, 'assistant_name', 'Jean'),
                "models": roles,
                "model_status": {role: ('disabled' if not name else
                                         'installed' if name in installed else 'missing')
                                 for role, name in roles.items()},
                "voice": model_path.stem, "engine": "Piper",
                "voice_enabled": bool(getattr(settings, "tts_enabled", False)),
                "timeout_seconds": float(getattr(settings, "timeout_seconds", 120.0))}

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
            "assistant_name": getattr(settings, 'assistant_name', 'Jean'),
            "model": getattr(settings, "model", None),
            "models": {role: getattr(settings, attribute, None) for role, attribute in {
                'general': 'model', 'fast': 'fast_model', 'coding': 'coding_model',
                'document': 'document_model', 'vision': 'vision_model'}.items()},
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

    @app.get('/conversations')
    def conversations():
        return {'conversations': memory.list_conversations()}

    @app.post('/conversations/{conversation_id}/restore')
    def restore_conversation(conversation_id: str):
        if not chat_lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail='Jean is handling another message. Please wait.')
        try:
            messages = memory.conversation_messages(conversation_id)
            agent.restore(conversation_id, messages)
            return {'conversation_id': conversation_id, 'messages': messages}
        except ValueError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        finally:
            chat_lock.release()

    @app.get("/tasks")
    def get_tasks() -> list[dict[str, Any]]:
        return memory.list_tasks()

    @app.get('/automations')
    def automations():
        return {'jobs': automation.list_jobs(), 'events': automation.events()} if automation is not None else {'jobs': [], 'events': []}

    @app.get('/approvals')
    def pending_approvals():
        return approvals.pending() if approvals is not None else []

    @app.post('/approvals/{approval_id}')
    def answer_approval(approval_id: str, payload: dict[str, Any]):
        if approvals is None:
            raise HTTPException(status_code=503, detail='Approvals are unavailable')
        try:
            approvals.answer(approval_id, payload.get('approved'))
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {'status': 'answered'}

    @app.post("/chat")
    def chat(payload: dict[str, Any]) -> dict[str, str]:
        message = payload.get("message")
        if not isinstance(message, str) or not message.strip():
            raise HTTPException(status_code=400, detail="message must be a nonempty string")
        tokens: list[str] = []
        if not chat_lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail="Jean is handling another message. Please wait.")
        try:
            activity["state"] = "Thinking"
            response = agent.respond_stream(message, tokens.append)
        finally:
            activity["state"] = "Ready"
            chat_lock.release()
        diagnostics = getattr(agent, 'diagnostics', {})
        result = {"response": response}
        if isinstance(diagnostics, dict):
            result['diagnostics'] = diagnostics
        return result

    @app.post('/chat-stream')
    async def chat_stream(request: Request):
        try:
            payload = await request.json()
        except (ValueError, TypeError) as error:
            raise HTTPException(status_code=400, detail='A JSON message is required') from error
        message = payload.get('message') if isinstance(payload, dict) else None
        if not isinstance(message, str) or not message.strip():
            raise HTTPException(status_code=400, detail='message must be a nonempty string')
        if not chat_lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail='Jean is handling another message. Please wait.')
        loop = asyncio.get_running_loop()
        events = asyncio.Queue()
        cancelled = Event()

        def emit(kind, **values):
            if not loop.is_closed():
                loop.call_soon_threadsafe(events.put_nowait, {'type': kind, **values})

        def worker():
            try:
                activity['state'] = 'Thinking'
                def token(value):
                    if cancelled.is_set():
                        raise RuntimeError('Generation cancelled')
                    emit('token', value=value)
                response = agent.respond_stream(message, token)
                emit('done', response=response, diagnostics=getattr(agent, 'diagnostics', {}))
            except Exception as error:
                emit('error', error=str(error))
            finally:
                activity['state'] = 'Ready'
                chat_lock.release()

        Thread(target=worker, name='jean-chat-stream', daemon=True).start()

        async def stream():
            try:
                while True:
                    try:
                        event = await asyncio.wait_for(events.get(), timeout=.25)
                    except asyncio.TimeoutError:
                        if await request.is_disconnected():
                            break
                        continue
                    yield json.dumps(event, ensure_ascii=False) + '\n'
                    if event['type'] in {'done', 'error'}:
                        break
            finally:
                cancelled.set()
        return StreamingResponse(stream(), media_type='application/x-ndjson',
                                 headers={'Cache-Control':'no-store', 'X-Accel-Buffering':'no'})

    @app.post('/analyze-upload')
    async def analyze_upload(request: Request):
        from starlette.concurrency import run_in_threadpool
        from jarvis.api.uploads import (IMAGE_EXTENSIONS, MAX_EXTRACTED_CHARACTERS, MAX_UPLOAD_BYTES,
                                        analyze_prepared_document, prepare_document, safe_filename)
        try:
            length = int(request.headers.get('content-length', '0'))
        except ValueError as error:
            raise HTTPException(status_code=400, detail='Invalid upload length') from error
        if length < 1 or length > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail='Uploads must contain 1 byte to 20 MiB')
        try:
            name = safe_filename(unquote(request.headers.get('x-filename', '')))
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        question = unquote(request.headers.get('x-question', '')).strip()
        if not question or len(question) > 1000:
            raise HTTPException(status_code=400, detail='Upload question must contain 1 to 1000 characters')
        data = await request.body()
        if not data or len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail='Uploads must contain 1 byte to 20 MiB')
        if not chat_lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail='Jean is handling another message. Please wait.')
        try:
            activity['state'] = 'Analyzing upload'
            if Path(name).suffix.lower() in IMAGE_EXTENSIONS:
                if vision is None:
                    raise HTTPException(status_code=503, detail='Image analysis is unavailable')
                result = await run_in_threadpool(vision.analyze_image_bytes, name, data, question)
            else:
                prepared = await run_in_threadpool(prepare_document, name, data, question)
                result = await run_in_threadpool(
                    analyze_prepared_document, document_client or agent.client, prepared, question)
                cached = (await run_in_threadpool(
                    prepare_document, name, data, '', MAX_EXTRACTED_CHARACTERS)
                          if Path(name).suffix.lower() == '.pptx' else prepared)
                result['context_id'] = remember_document(cached)
                result['context_expires_seconds'] = document_context_ttl
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except RuntimeError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        finally:
            activity['state'] = 'Ready'
            chat_lock.release()
        return result

    @app.post('/analyze-context')
    async def analyze_context(payload: dict[str, Any]):
        from starlette.concurrency import run_in_threadpool
        from jarvis.api.uploads import analyze_prepared_document
        context_id = payload.get('context_id')
        question = payload.get('question')
        if not isinstance(context_id, str) or not isinstance(question, str) or not question.strip() or len(question) > 1000:
            raise HTTPException(status_code=400, detail='A valid document context and question are required')
        prepared = document_contexts.get(context_id)
        if prepared is None or time.monotonic() - prepared['created_at'] > document_context_ttl:
            document_contexts.pop(context_id, None)
            raise HTTPException(status_code=404, detail='Document context expired; attach the file again')
        if not chat_lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail='Jean is handling another message. Please wait.')
        try:
            activity['state'] = 'Reviewing ' + prepared['filename']
            result = await run_in_threadpool(
                analyze_prepared_document, document_client or agent.client, prepared, question.strip())
            prepared['created_at'] = time.monotonic()
            result['context_id'] = context_id
            result['context_expires_seconds'] = document_context_ttl
            return result
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except RuntimeError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        finally:
            activity['state'] = 'Ready'
            chat_lock.release()

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
    from jarvis.prompts import system_prompt

    settings = Settings.from_environment()
    from jarvis.tools import create_local_tools
    from jarvis.tools.projects import ProjectManager
    from jarvis.tools.web import WebClient
    from jarvis.rag import KnowledgeStore
    root = Path(__file__).resolve().parents[2]
    memory = MemoryStore(root / 'data' / 'jarvis.db')
    knowledge = KnowledgeStore(root / 'data' / 'knowledge.db',
                               semantic=settings.rag_semantic_enabled)
    from jarvis.scheduler import TaskScheduler
    from jarvis.scheduler.automation import Automation
    from jarvis.tools.vision import Vision
    from jarvis.api.approvals import ApprovalQueue
    approvals = ApprovalQueue()
    projects = ProjectManager(root)
    automation = Automation(root / 'data' / 'automation.db', projects)
    vision = Vision(settings, (root, *settings.allowed_roots))
    from jarvis.tools.presentations import Presentations
    presentations = Presentations((root, *settings.allowed_roots))
    tools = create_local_tools(root, projects=projects, memory=memory,
                               web=WebClient(enabled=settings.web_enabled,
                                             search_url=settings.search_url),
                               allowed_roots=settings.allowed_roots, knowledge=knowledge,
                               automation=automation,
                               vision=vision, presentations=presentations,
                               confirm=approvals.confirm)
    coding_client = (OllamaClient(settings.ollama_host, settings.coding_model,
                                  settings.timeout_seconds)
                     if settings.coding_model else None)
    fast_client = (OllamaClient(settings.ollama_host, settings.fast_model,
                                settings.timeout_seconds)
                   if settings.fast_model else None)
    document_client = (OllamaClient(settings.ollama_host, settings.document_model,
                                    settings.timeout_seconds)
                       if settings.document_model else None)
    agent = Agent(OllamaClient(settings.ollama_host, settings.model, settings.timeout_seconds),
                  coding_client=coding_client, fast_client=fast_client,
                  system_prompt=system_prompt(settings.assistant_name), tools=tools, memory=memory)
    try:
        scheduler = TaskScheduler(memory, lambda task: print('Jean reminder: ' + task['title']), automation=automation)
        uvicorn.run(create_app(agent, memory, settings, tools, scheduler, automation, approvals,
                               vision, document_client), host="127.0.0.1", port=8765)
    finally:
        knowledge.close()
        memory.close()


if __name__ == "__main__":
    main()
