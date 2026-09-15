"""Named, locally configured commands and session-owned project processes."""

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading

from jarvis.tools.windows import hidden_process_options, stop_process_tree


@dataclass(frozen=True)
class Project:
    directory: Path
    commands: dict[str, tuple[str, ...]]
    start: str | None = None


@dataclass
class ManagedProcess:
    process: subprocess.Popen
    output: bytearray = field(default_factory=bytearray)
    lock: threading.Lock = field(default_factory=threading.Lock)
    reader: threading.Thread | None = None

    def capture(self):
        try:
            with self.process.stdout as stream:
                while chunk := os.read(stream.fileno(), 4096):
                    with self.lock:
                        self.output.extend(chunk)
                        del self.output[:-16384]
        except (OSError, ValueError):
            pass

    def text(self):
        with self.lock:
            return bytes(self.output).decode('utf-8', errors='replace')


class ProjectManager:
    def __init__(self, root: Path, config_path: Path | None = None):
        self.root = root.resolve()
        self._running: dict[str, ManagedProcess] = {}
        path = config_path if config_path is not None else self.root / '.jarvis-projects.json'
        if path.exists():
            if path.stat().st_size > 65536:
                raise ValueError('Project configuration exceeds 64 KiB')
            data = json.loads(path.read_text(encoding='utf-8-sig'))
        else:
            data = {'jarvis': {'directory': '.', 'commands': {
                'tests': ['{python}', '-m', 'unittest', 'discover', '-s', 'tests', '-v']}}}
        if not isinstance(data, dict):
            raise ValueError('Project configuration must be an object')
        self._projects: dict[str, Project] = {}
        for name, spec in data.items():
            self._validate_name(name)
            if not isinstance(spec, dict) or set(spec) - {'directory', 'commands', 'start'}:
                raise ValueError(f'Invalid project definition: {name}')
            directory = spec.get('directory')
            commands = spec.get('commands')
            if not isinstance(directory, str) or not directory.strip() or not isinstance(commands, dict) or not commands:
                raise ValueError(f'Project {name} requires a directory and commands')
            frozen = {}
            for command, argv in commands.items():
                self._validate_name(command)
                if not isinstance(argv, list) or not argv or not all(isinstance(arg, str) and '\x00' not in arg for arg in argv):
                    raise ValueError(f'Invalid command array: {name}/{command}')
                argv = list(argv)
                if argv[0] == '{python}':
                    argv[0] = sys.executable
                executable = Path(argv[0])
                if not executable.is_absolute() or executable.suffix.lower() in {'.bat', '.cmd', '.ps1'}:
                    raise ValueError('Commands require an absolute executable path or {python}; no shell scripts')
                if executable.stem.lower() in {'cmd', 'powershell', 'pwsh', 'sh', 'bash', 'wscript', 'cscript', 'mshta'}:
                    raise ValueError('Shell interpreters are not approved project executables')
                frozen[command] = tuple(argv)
            start = spec.get('start')
            if start is not None and (not isinstance(start, str) or start not in frozen):
                raise ValueError(f'Unknown start command for {name}')
            self._projects[name] = Project((self.root / directory).resolve(), frozen, start)

    @staticmethod
    def _validate_name(name):
        if not isinstance(name, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', name):
            raise ValueError('Project and command names must contain only letters, numbers, underscores, or hyphens')

    @property
    def names(self):
        return list(self._projects)

    @property
    def command_names(self):
        return sorted({command for project in self._projects.values() for command in project.commands})

    def list_projects(self):
        return [{'name': name, 'directory': str(project.directory),
                 'commands': list(project.commands), 'start_command': project.start,
                 **self.status(name)} for name, project in self._projects.items()]

    def _project(self, project: str) -> Project:
        if project not in self._projects:
            raise ValueError('Unknown approved project')
        return self._projects[project]

    def preview(self, project: str, command: str | None = None) -> dict:
        spec = self._project(project)
        alias = command if command is not None else spec.start
        if alias is None or alias not in spec.commands:
            raise ValueError('No approved command configured for this request')
        if not spec.directory.is_dir():
            raise ValueError('Configured project directory is unavailable')
        argv = spec.commands[alias]
        if not Path(argv[0]).is_file():
            raise ValueError('Configured executable is unavailable')
        return {'project': project, 'command': alias, 'directory': str(spec.directory),
                'argv': list(argv), 'effect': 'Execute the fixed command; project code may change files or start child processes'}

    def preview_start(self, project: str) -> dict:
        if self.status(project)['running']:
            raise ValueError('Project already has a running managed command')
        details = self.preview(project)
        details['effect'] = 'Start this foreground project in the background; it remains managed in this Jean session'
        return details

    def preview_stop(self, project: str) -> dict:
        state = self.status(project)
        if not state['running']:
            raise ValueError('No running process owned by this session for the project')
        return {'project': project, 'pid': state['pid'],
                'effect': 'Terminate this managed process and its children; unsaved work may be lost'}

    def _launch(self, project: str, command: str | None = None) -> ManagedProcess:
        if self.status(project)['running']:
            raise ValueError('Project already has a running managed command')
        details = self.preview(project, command)
        process = subprocess.Popen(details['argv'], cwd=details['directory'], shell=False,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   start_new_session=os.name != 'nt', **hidden_process_options())
        managed = ManagedProcess(process)
        self._running[project] = managed
        managed.reader = threading.Thread(target=managed.capture, daemon=True)
        managed.reader.start()
        return managed

    def start_project(self, project: str) -> dict:
        self._launch(project)
        return {**self.status(project), 'note': 'Process started; readiness is not verified'}

    def status(self, project: str) -> dict:
        self._project(project)
        managed = self._running.get(project)
        if managed is None:
            return {'running': False, 'pid': None, 'exit_code': None, 'output_tail': ''}
        code = managed.process.poll()
        if code is not None and managed.reader:
            managed.reader.join(timeout=0.1)
        return {'running': code is None, 'pid': managed.process.pid,
                'exit_code': code, 'output_tail': managed.text()}

    def stop_project(self, project: str) -> dict:
        self.preview_stop(project)
        managed = self._running[project]
        try:
            stop_process_tree(managed.process)
        except (OSError, subprocess.SubprocessError) as error:
            raise RuntimeError(f'Could not stop managed project: {type(error).__name__}') from error
        if managed.reader:
            managed.reader.join(timeout=1)
        return self.status(project)

    def run_command(self, project: str, command: str, timeout: float = 60) -> dict:
        managed = self._launch(project, command)
        timed_out = False
        try:
            managed.process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            self.stop_project(project)
        except BaseException:
            self.stop_project(project)
            raise
        if managed.reader:
            managed.reader.join(timeout=1)
        return {**self.status(project), 'timed_out': timed_out}
