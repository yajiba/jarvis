"""Local tools with bounded file access and fixed application launch targets."""

from datetime import datetime
from itertools import islice
import os
from pathlib import Path
import platform
import subprocess
import fnmatch
import time
from collections.abc import Callable

from jarvis.tools.registry import Tool, ToolRegistry
from jarvis.tools.projects import ProjectManager
from jarvis.tools.windows import hardware_info, request_application_close
from jarvis.memory import MemoryStore
from jarvis.tools.web import WebClient, create_web_tools
from jarvis.tools.coding import create_coding_tools
from jarvis.rag import KnowledgeStore


def _parameters(name: str | None = None, enum: list[str] | None = None) -> dict:
    properties = {} if name is None else {name: {"type": "string"}}
    if enum is not None:
        properties[name]["enum"] = enum
    return {"type": "object", "properties": properties,
            "required": list(properties), "additionalProperties": False}


def create_local_tools(root: Path, confirm: Callable[[str, dict], bool] | None = None,
                       projects: ProjectManager | None = None,
                       memory: MemoryStore | None = None,
                       web: WebClient | None = None,
                       allowed_roots: tuple[Path, ...] | None = None,
                       knowledge: KnowledgeStore | None = None,
                       automation=None, vision=None, presentations=None) -> ToolRegistry:
    root = root.resolve(strict=True)
    roots = tuple(dict.fromkeys((root, *(allowed_roots or ()))))
    roots = tuple(path.resolve(strict=True) for path in roots)
    projects = projects if projects is not None else ProjectManager(root)
    applications: dict[str, subprocess.Popen] = {}

    def resolve(path: str) -> Path:
        requested = Path(path).expanduser()
        candidates = [root / requested] if not requested.is_absolute() else [requested]
        target = None
        for candidate in candidates:
            if any(':' in part for part in candidate.parts if part not in {candidate.anchor}):
                raise ValueError("Alternate data streams are not available to tools")
            try:
                resolved = candidate.resolve(strict=True)
            except OSError:
                continue
            if any(resolved.is_relative_to(allowed_root) for allowed_root in roots):
                target = resolved
                break
        if target is None:
            raise ValueError("Path is outside the allowed roots or unavailable")
        parts = next(target.relative_to(allowed_root).parts for allowed_root in roots
                     if target.is_relative_to(allowed_root))
        if any(part.startswith('.') or part.lower() in {'__pycache__', 'node_modules'} for part in parts):
            raise ValueError("Hidden and internal paths are not available to tools")
        if target.suffix.lower() in {'.pem', '.key', '.pfx', '.p12'}:
            raise ValueError("Credential files are not available to tools")
        return target

    def list_files(path: str) -> dict:
        directory = resolve(path)
        entries = []
        for child in islice(directory.iterdir(), 201):
            try:
                safe = resolve(str(child))
            except (ValueError, OSError):
                continue
            entries.append({"name": child.name, "directory": safe.is_dir()})
        return {"entries": entries[:200], "limit": 200}

    def read_file(path: str) -> str:
        target = resolve(path)
        if not target.is_file():
            raise ValueError("Path must be a regular file")
        with target.open('rb') as source:
            data = source.read(32769)
        if len(data) > 32768:
            raise ValueError("File exceeds the 32 KiB read limit")
        if b'\x00' in data:
            raise ValueError("Only UTF-8 text files are supported")
        return data.decode('utf-8-sig')

    def open_folder(path: str) -> str:
        target = resolve(path)
        if not target.is_dir():
            raise ValueError("Path must be a folder")
        if os.name != 'nt':
            raise ValueError("Opening folders requires Windows")
        os.startfile(str(target))
        return "Folder open request sent"

    def open_application(name: str) -> str:
        if os.name != 'nt':
            raise ValueError("Opening applications requires Windows")
        if name in applications and applications[name].poll() is None:
            raise ValueError('An application process with this name is already managed')
        windows = Path(os.environ.get('SystemRoot', 'C:/Windows'))
        local = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData/Local')))
        programs = Path(os.environ.get('ProgramFiles', 'C:/Program Files'))
        candidates = {
            'notepad': [windows / 'System32/notepad.exe'],
            'calculator': [windows / 'System32/calc.exe'],
            'vscode': [local / 'Programs/Microsoft VS Code/Code.exe', programs / 'Microsoft VS Code/Code.exe'],
        }
        executable = next((path for path in candidates[name] if path.is_file()), None)
        if executable is None:
            raise ValueError(f"Approved application {name} was not found")
        applications[name] = subprocess.Popen([str(executable)], shell=False)
        return f"Launch request sent for {name}"

    def close_preview(name: str) -> dict:
        if name not in applications or applications[name].poll() is not None:
            raise ValueError('No running application process owned by this Jean session')
        return {'application': name, 'pid': applications[name].pid,
                'effect': 'Ask its windows to close; save dialogs may require your attention'}

    def close_application(name: str) -> str:
        close_preview(name)
        return request_application_close(applications[name])

    def search_files(pattern: str) -> dict:
        if len(pattern) > 256:
            raise ValueError('Search pattern exceeds 256 characters')
        pending = [(allowed_root, 0) for allowed_root in roots]
        visited = set()
        matches = []
        scanned = 0
        deadline = time.monotonic() + 3
        truncated = False
        while pending:
            directory, depth = pending.pop()
            if directory in visited:
                continue
            visited.add(directory)
            try:
                with os.scandir(directory) as entries:
                    for entry in entries:
                        scanned += 1
                        if scanned > 5000 or time.monotonic() > deadline or len(matches) >= 200:
                            return {'matches': matches, 'truncated': True}
                        try:
                            if entry.is_symlink():
                                continue
                            target = resolve(entry.path)
                            if target.is_dir():
                                if depth < 16:
                                    pending.append((target, depth + 1))
                                else:
                                    truncated = True
                            elif target.is_file():
                                owner = next(allowed_root for allowed_root in roots
                                              if target.is_relative_to(allowed_root))
                                relative = target.relative_to(owner).as_posix()
                                if fnmatch.fnmatch(relative.lower(), pattern.lower()) or fnmatch.fnmatch(target.name.lower(), pattern.lower()):
                                    matches.append(relative)
                        except (OSError, ValueError):
                            continue
            except OSError:
                truncated = True
        return {'matches': matches, 'truncated': truncated}

    def list_allowed_roots() -> list[str]:
        return [str(allowed_root) for allowed_root in roots]

    def require_memory() -> MemoryStore:
        if memory is None:
            raise RuntimeError('Persistent memory is not configured')
        return memory

    def remember_memory(content: str) -> str:
        memory_store = require_memory()
        memory_store.remember(content)
        return 'Memory saved'

    def set_preference(key: str, value: str) -> str:
        memory_store = require_memory()
        memory_store.set_preference(key, value)
        return f'Preference saved: {key}'

    def get_preference(key: str) -> dict:
        value = require_memory().get_preference(key)
        return {'key': key, 'value': value}

    def list_memory() -> dict:
        memory_store = require_memory()
        return {
            'preferences': memory_store.list_preferences(),
            'memories': memory_store.list_memories(),
            'tasks': memory_store.list_tasks(),
        }

    def add_task(title: str) -> str:
        task_id = require_memory().add_task(title)
        return f'Task saved with id {task_id}'

    def schedule_task(title: str, due_at: str, recurrence: str) -> str:
        task_id = require_memory().add_task(title, due_at, None if recurrence == "none" else recurrence)
        return f'Task scheduled with id {task_id}'

    def index_knowledge(path: str) -> dict:
        if knowledge is None:
            raise RuntimeError('Local knowledge store is not configured')
        return knowledge.index_directory(resolve(path))

    def search_knowledge(query: str) -> list[dict]:
        if knowledge is None:
            raise RuntimeError('Local knowledge store is not configured')
        return knowledge.search(query)

    project_args = _parameters('project', projects.names)
    command_args = _parameters('project', projects.names)
    command_args['properties']['command'] = {'type': 'string', 'enum': projects.command_names}
    command_args['required'].append('command')
    return ToolRegistry([
        Tool('get_time', 'Get the current local date, time, and UTC offset.', _parameters(),
             lambda: datetime.now().astimezone().isoformat(timespec='seconds')),
        Tool('get_system_info', 'Get operating system, architecture, and CPU count.', _parameters(),
             lambda: {'os': platform.system(), 'release': platform.release(),
                      'architecture': platform.machine(), 'cpu_count': os.cpu_count()}),
        Tool('open_application', 'Launch an approved application by name.',
             _parameters('name', ['vscode', 'notepad', 'calculator']), open_application),
        Tool('open_folder', 'Open a project folder. Use . for the project root.', _parameters('path'), open_folder),
        Tool('list_files', 'List up to 200 entries in a project folder. Use . for the root.', _parameters('path'), list_files),
        Tool('read_file', 'Read a UTF-8 project file up to 32 KiB. Hidden and credential paths are blocked.', _parameters('path'), read_file),
        Tool('search_files', 'Search project filenames using a glob such as *.py. Returns up to 200 matches.', _parameters('pattern'), search_files),
        Tool('list_allowed_roots', 'List the approved local folders Jean may inspect.', _parameters(), list_allowed_roots),
          Tool('remember_memory', 'Save an important user fact for future conversations.', _parameters('content'), remember_memory),
          Tool('set_preference', 'Save a named user preference for future conversations.',
             {'type': 'object', 'properties': {'key': {'type': 'string'}, 'value': {'type': 'string'}},
              'required': ['key', 'value'], 'additionalProperties': False}, set_preference),
          Tool('get_preference', 'Retrieve one saved user preference by key.', _parameters('key'), get_preference),
          Tool('list_memory', 'List saved preferences, memories, and open tasks.', _parameters(), list_memory),
          Tool('add_task', 'Save a task for later follow-up.', _parameters('title'), add_task),
          Tool('schedule_task', 'Schedule a local reminder using an ISO-8601 due time; recurrence may be none, daily, or weekly.',
               {'type': 'object', 'properties': {'title': {'type': 'string'}, 'due_at': {'type': 'string'},
              'recurrence': {'type': 'string', 'enum': ['none', 'daily', 'weekly']}},
                'required': ['title', 'due_at', 'recurrence'], 'additionalProperties': False}, schedule_task),
        Tool('index_knowledge', 'Index approved local text and source documents for private retrieval.', _parameters('path'), index_knowledge),
        Tool('search_knowledge', 'Search indexed local documents and return relevant passages.', _parameters('query'), search_knowledge),
        Tool('get_hardware_info', 'Get Windows CPU load, RAM capacity and free memory, and available GPU metrics.', _parameters(), hardware_info),
        Tool('close_application', 'Request closing only an application launched in this session. Requires confirmation.',
             _parameters('name', ['vscode', 'notepad', 'calculator']), close_application, 'confirm', close_preview),
        Tool('list_projects', 'List approved projects, command names, and managed process status.', _parameters(), projects.list_projects),
        Tool('get_project_status', 'Get a managed project process status and bounded recent output.', project_args, projects.status),
        Tool('start_project', 'Start the configured foreground project in the background after confirmation.', project_args,
             projects.start_project, 'confirm', projects.preview_start),
        Tool('stop_project', 'Terminate the session-owned project process and children after confirmation.', project_args,
             projects.stop_project, 'confirm', projects.preview_stop),
        Tool('run_project_command', 'Run an approved command alias after confirmation, with a 60-second timeout.', command_args,
             projects.run_command, 'confirm', projects.preview),
        *create_web_tools(web if web is not None else WebClient()),
        *create_coding_tools(roots, projects, confirm=confirm).tools,
        *(automation.tools() if automation is not None else []),
        *(vision.tools() if vision is not None else []),
        *(presentations.tools() if presentations is not None else []),
    ], confirm=confirm)
