"""Run the JARVIS terminal chat."""

from jarvis.config import Settings
from jarvis.brain import Agent
from jarvis.brain.llm import OllamaClient, OllamaError
from jarvis.tools import create_local_tools
from pathlib import Path
import json
import importlib.util
import sqlite3
from jarvis.tools.projects import ProjectManager
from jarvis.tools.web import WebClient
from jarvis.memory import MemoryStore
from jarvis.voice import (
    PiperSpeaker,
    PushToTalkTranscriber,
    VoiceInputError,
    WakeWordTranscriber,
)
from jarvis.rag import KnowledgeStore
from jarvis.scheduler import TaskScheduler


def confirm_action(name: str, details: dict) -> bool:
    print(f"\nApproval required: {name}")
    print(json.dumps(details, ensure_ascii=True, indent=2))
    try:
        return input('Allow this action? [y/N]: ').strip().lower() in {'y', 'yes'}
    except (EOFError, KeyboardInterrupt):
        print('\nAction denied.')
        return False


def confirm_voice_action(name: str, details: dict, voice_input, speaker) -> bool:
    prompt = f"Approval required for {name}. Say yes or no."
    print(f"\n{prompt}")
    if speaker is not None:
        try:
            speaker.speak(prompt)
        except VoiceInputError:
            pass
    try:
        answer = voice_input.listen_and_transcribe().strip().casefold()
    except (VoiceInputError, KeyboardInterrupt):
        return False
    return answer in {"yes", "yes please", "allow", "approved", "okay", "ok"}


def finish_session(projects: ProjectManager, tools) -> None:
    for state in projects.list_projects():
        if state['running']:
            result = tools.execute('stop_project', {'project': state['name']})
            if not result['ok']:
                print(f"Project {state['name']} (PID {state['pid']}) remains running after exit. "
                      'This session will no longer manage it.')


def respond(agent: Agent, speaker: PiperSpeaker | None, user_input: str) -> None:
    print("\nJARVIS: ", end="", flush=True)
    agent.respond_stream(
        user_input,
        on_token=lambda token: print(token, end="", flush=True),
    )
    print()
    if speaker is not None:
        try:
            speaker.speak(agent.messages[-1].get("content", ""))
        except VoiceInputError as error:
            print(f"JARVIS voice output error: {error}")


def voice_agent_loop(agent: Agent, speaker, wake_input) -> None:
    """Run the complete wake-word -> speech -> agent -> speech loop."""
    print("Voice agent active. Say the wake word, or press Ctrl+C to return to text.")
    while True:
        try:
            wake_text = wake_input.listen_and_transcribe()
        except KeyboardInterrupt:
            print("\nJARVIS: Voice agent stopped; returning to text.")
            return
        except VoiceInputError as error:
            print(f"JARVIS voice error: {error}")
            return
        print(f"You (wake word): {wake_text}")
        normalized = wake_text.strip().lower()
        if normalized in {"/exit", "/quit", "exit", "quit", "stop listening"}:
            return
        if normalized == "/reset":
            agent.reset()
            print("JARVIS: Conversation reset.")
            continue
        try:
            respond(agent, speaker, wake_text)
        except OllamaError as error:
            print(f"JARVIS error: {error}")
        except VoiceInputError as error:
            print(f"JARVIS voice error: {error}")


def show_status(settings: Settings, root: Path) -> None:
    dependencies = {name: importlib.util.find_spec(name) is not None for name in
                    ['faster_whisper', 'sounddevice', 'pynput', 'piper', 'openwakeword']}
    print(json.dumps({'web_enabled': settings.web_enabled, 'speech_enabled': settings.tts_enabled,
                      'piper_model_present': (root / settings.piper_model).is_file(),
                      'dependencies': dependencies,
                      'note': 'Dependency presence does not verify microphones, speakers, or model readiness.'}, indent=2))


def run() -> None:
    try:
        settings = Settings.from_environment()
        root = Path(__file__).resolve().parent
        projects = ProjectManager(root)
        memory = MemoryStore(root / 'data' / 'jarvis.db')
        knowledge = KnowledgeStore(root / 'data' / 'knowledge.db', semantic=settings.rag_semantic_enabled)
    except (ValueError, OSError, RuntimeError, sqlite3.Error) as error:
        print(f"JARVIS configuration error: {error}")
        return
    try:
        run_session(settings, root, projects, memory, knowledge)
    finally:
        memory.close()
        knowledge.close()

def run_session(settings, root, projects, memory, knowledge) -> None:
    client = OllamaClient(
        host=settings.ollama_host,
        model=settings.model,
        timeout_seconds=settings.timeout_seconds,
    )
    coding_client = (
        OllamaClient(settings.ollama_host, settings.coding_model, settings.timeout_seconds)
        if settings.coding_model else None
    )
    voice_input = PushToTalkTranscriber(
        model_name=settings.whisper_model,
        sample_rate=settings.audio_sample_rate,
        device=settings.whisper_device,
    )
    wake_input = WakeWordTranscriber(
        wakeword=settings.wakeword_model,
        model_name=settings.whisper_model,
        sample_rate=settings.audio_sample_rate,
        device=settings.whisper_device,
        threshold=settings.wakeword_threshold,
        command_seconds=settings.wakeword_command_seconds,
    )
    speaker = PiperSpeaker(root / settings.piper_model) if settings.tts_enabled else None
    confirm = lambda name, details: confirm_voice_action(name, details, voice_input, speaker)
    tools = create_local_tools(root, confirm=confirm, projects=projects, memory=memory,
                               web=WebClient(enabled=settings.web_enabled),
                               allowed_roots=settings.allowed_roots,
                               knowledge=knowledge)
    agent = Agent(client, coding_client=coding_client, tools=tools, memory=memory)
    scheduler = TaskScheduler(memory, lambda task: print(f"\nJARVIS reminder: {task['title']}"))
    scheduler.start()

    print(f"JARVIS v1.4 voice-only | model: {settings.model} | web: {'on' if settings.web_enabled else 'off'}")
    print("Say Hey Jarvis to speak. Say stop listening or press Ctrl+C to exit.")

    try:
        if settings.voice_agent_enabled:
            voice_agent_loop(agent, speaker, wake_input)
            return
        chat_loop(agent, speaker, voice_input, wake_input, settings, root)
    finally:
        scheduler.stop()
        finish_session(projects, tools)


def chat_loop(agent, speaker, voice_input, wake_input, settings, root) -> None:
    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nJARVIS: Session ended.")
            return

        if not user_input:
            continue
        if user_input.lower() in {"/exit", "/quit"}:
            print("JARVIS: Goodbye.")
            return
        if user_input.lower() == "/reset":
            agent.reset()
            print("JARVIS: Conversation reset.")
            continue
        if user_input.lower() == '/status':
            show_status(settings, root)
            continue
        if user_input.lower() == "/voice":
            try:
                user_input = voice_input.listen_and_transcribe()
                print(f"You (voice): {user_input}")
            except VoiceInputError as error:
                print(f"JARVIS voice error: {error}")
                continue
            except KeyboardInterrupt:
                print('\nJARVIS: Voice input cancelled; returning to text.')
                continue
            if user_input.lower() in {'/exit', '/quit', 'exit', 'quit'}:
                return
            if user_input.lower() == '/reset':
                agent.reset()
                continue
        if user_input.lower() in {"/wake", "/agent"}:
            voice_agent_loop(agent, speaker, wake_input)
            continue

        try:
            respond(agent, speaker, user_input)
        except OllamaError as error:
            print(f"\nJARVIS error: {error}")
            continue
        except KeyboardInterrupt:
            print("\nJARVIS: Session ended.")
            return


if __name__ == "__main__":
    run()
