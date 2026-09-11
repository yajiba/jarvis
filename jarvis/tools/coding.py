"""Bounded coding tools for approved local project roots."""

from collections.abc import Callable
import fnmatch
import os
from pathlib import Path
import shutil
import subprocess

from jarvis.tools.projects import ProjectManager
from jarvis.tools.registry import Tool, ToolRegistry


CODE_EXTENSIONS = {
    ".c", ".cpp", ".css", ".go", ".h", ".html", ".java", ".js", ".json",
    ".jsx", ".md", ".php", ".py", ".rs", ".sql", ".ts", ".tsx", ".vue", ".yaml", ".yml",
}
MAX_SOURCE_BYTES = 256 * 1024


def _string(name: str) -> dict:
    return {
        "type": "object",
        "properties": {name: {"type": "string"}},
        "required": [name],
        "additionalProperties": False,
    }


def _strings(*names: str) -> dict:
    return {
        "type": "object",
        "properties": {name: {"type": "string"} for name in names},
        "required": list(names),
        "additionalProperties": False,
    }


def create_coding_tools(
    roots: tuple[Path, ...],
    projects: ProjectManager,
    confirm: Callable[[str, dict], bool] | None = None,
) -> ToolRegistry:
    approved_roots = tuple(path.resolve(strict=True) for path in roots)

    def resolve_existing(path: str, directory: bool | None = None) -> Path:
        requested = Path(path).expanduser()
        candidates = [requested] if requested.is_absolute() else [approved_roots[0] / requested]
        for candidate in candidates:
            try:
                target = candidate.resolve(strict=True)
            except OSError:
                continue
            if not any(target.is_relative_to(root) for root in approved_roots):
                continue
            owner = next(root for root in approved_roots if target.is_relative_to(root))
            relative_parts = target.relative_to(owner).parts
            if any(part.startswith(".") or part.lower() in {"__pycache__", "node_modules"}
                   for part in relative_parts):
                raise ValueError("Hidden and internal paths are not available to coding tools")
            if target.suffix.lower() in {".pem", ".key", ".pfx", ".p12"}:
                raise ValueError("Credential files are not available to coding tools")
            if directory is True and not target.is_dir():
                raise ValueError("Path must be a directory")
            if directory is False and not target.is_file():
                raise ValueError("Path must be a file")
            return target
        raise ValueError("Path is outside the approved project roots or unavailable")

    def resolve_new_file(path: str) -> tuple[Path, Path]:
        requested = Path(path).expanduser()
        if requested.is_absolute():
            target = requested
        else:
            target = approved_roots[0] / requested
        parent = resolve_existing(str(target.parent), directory=True)
        if any(part.startswith(".") or part.lower() in {"__pycache__", "node_modules"}
               for part in target.relative_to(parent).parts):
            raise ValueError("Hidden and internal paths are not available to coding tools")
        if target.suffix.lower() in {".pem", ".key", ".pfx", ".p12"}:
            raise ValueError("Credential files are not available to coding tools")
        return target, parent

    def read_source_file(path: str) -> str:
        target = resolve_existing(path, directory=False)
        if target.suffix.lower() not in CODE_EXTENSIONS:
            raise ValueError("Only recognized source and documentation files are available")
        data = target.read_bytes()
        if len(data) > MAX_SOURCE_BYTES:
            raise ValueError("Source file exceeds the 256 KiB read limit")
        if b"\x00" in data:
            raise ValueError("Binary files are not source files")
        return data.decode("utf-8-sig")

    def search_code(query: str, path: str) -> dict:
        if len(query) > 256:
            raise ValueError("Search query exceeds 256 characters")
        directory = resolve_existing(path, directory=True)
        matches: list[dict[str, object]] = []
        scanned = 0
        for current, directories, files in os.walk(directory):
            directories[:] = [name for name in directories
                              if not name.startswith(".") and name not in {"__pycache__", "node_modules"}]
            for name in files:
                if Path(name).suffix.lower() not in CODE_EXTENSIONS:
                    continue
                scanned += 1
                if scanned > 2000 or len(matches) >= 100:
                    return {"matches": matches, "truncated": True}
                file_path = Path(current) / name
                try:
                    content = file_path.read_text(encoding="utf-8-sig")
                except (OSError, UnicodeError):
                    continue
                for line_number, line in enumerate(content.splitlines(), 1):
                    if query.casefold() in line.casefold():
                        matches.append({"path": str(file_path), "line": line_number,
                                        "text": line[:500]})
                        if len(matches) >= 100:
                            return {"matches": matches, "truncated": True}
        return {"matches": matches, "truncated": False}

    def analyze_project(path: str) -> dict:
        directory = resolve_existing(path, directory=True)
        counts: dict[str, int] = {}
        files: list[str] = []
        for current, directories, names in os.walk(directory):
            directories[:] = [name for name in directories
                              if not name.startswith(".") and name not in {"__pycache__", "node_modules"}]
            for name in names:
                suffix = Path(name).suffix.lower()
                if suffix not in CODE_EXTENSIONS:
                    continue
                counts[suffix or "[no extension]"] = counts.get(suffix or "[no extension]", 0) + 1
                if len(files) < 200:
                    files.append(str((Path(current) / name).relative_to(directory).as_posix()))
        return {"directory": str(directory), "file_counts": counts, "sample_files": files,
                "truncated": sum(counts.values()) > len(files)}

    def git_command(path: str, arguments: list[str]) -> str:
        directory = resolve_existing(path, directory=True)
        git = shutil.which("git")
        if git is None:
            raise ValueError("Git is not installed or not available on PATH")
        try:
            result = subprocess.run(
                [git, *arguments], cwd=directory, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=20, check=False, shell=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise RuntimeError(f"Git operation failed: {type(error).__name__}") from error
        output = (result.stdout + result.stderr)[:64 * 1024]
        return output if output else f"Git exited with code {result.returncode}"

    def git_status(path: str) -> str:
        return git_command(path, ["status", "--short", "--branch"])

    def git_diff(path: str) -> str:
        return git_command(path, ["diff", "--stat", "--no-ext-diff"])

    def create_file(path: str, content: str) -> str:
        target, _ = resolve_new_file(path)
        if target.exists():
            raise ValueError("File already exists; use edit_file instead")
        if len(content.encode("utf-8")) > MAX_SOURCE_BYTES:
            raise ValueError("New file exceeds the 256 KiB limit")
        target.write_text(content, encoding="utf-8", newline="")
        return f"Created {target}"

    def edit_file(path: str, content: str) -> str:
        target = resolve_existing(path, directory=False)
        if len(content.encode("utf-8")) > MAX_SOURCE_BYTES:
            raise ValueError("Edited file exceeds the 256 KiB limit")
        target.write_text(content, encoding="utf-8", newline="")
        return f"Updated {target}"

    def run_tests(project: str) -> dict:
        if "tests" not in projects.command_names:
            raise ValueError("No approved tests command is configured")
        return projects.run_command(project, "tests")

    def run_project(project: str) -> dict:
        return projects.start_project(project)

    project_args = _string("project")
    return ToolRegistry([
        Tool("search_code", "Search source files for a text query within an approved project folder.",
             _strings("query", "path"), search_code),
        Tool("read_source_file", "Read a bounded UTF-8 source or documentation file.",
             _string("path"), read_source_file),
        Tool("analyze_project", "Summarize recognized source files and extensions in an approved project.",
             _string("path"), analyze_project),
        Tool("git_status", "Read Git branch and working-tree status for an approved project.",
             _string("path"), git_status),
        Tool("git_diff", "Read a bounded Git diff summary for an approved project.",
             _string("path"), git_diff),
        Tool("create_file", "Create a new source file after explicit confirmation.",
             _strings("path", "content"), create_file, "confirm", lambda path, content: {
                 "path": path, "bytes": len(content.encode("utf-8")), "effect": "Create a new file"
             }),
        Tool("edit_file", "Replace an existing source file after explicit confirmation.",
             _strings("path", "content"), edit_file, "confirm", lambda path, content: {
                 "path": path, "bytes": len(content.encode("utf-8")), "effect": "Replace file contents"
             }),
        Tool("run_tests", "Run the approved tests command for a configured project after confirmation.",
             project_args, run_tests, "confirm", lambda project: {
                 "project": project, "effect": "Run the configured tests command"
             }),
        Tool("run_project", "Start a configured project after confirmation.",
             project_args, run_project, "confirm", lambda project: {
                 "project": project, "effect": "Start the configured project process"
             }),
    ], confirm=confirm)
