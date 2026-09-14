"""SQLite-backed conversation, preference, task, and tool memory."""

from pathlib import Path
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from functools import wraps
from threading import RLock
from typing import Any
import uuid


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def synchronized(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return call


class MemoryStore:
    """Own the local JARVIS SQLite database and its small application API."""

    def __init__(self, path: Path) -> None:
        self._lock = RLock()
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._initialize()

    @synchronized
    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "MemoryStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _initialize(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                started_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'fact',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS preferences (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                due_at TEXT,
                status TEXT NOT NULL DEFAULT 'open',
                recurrence TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tool_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT,
                tool_name TEXT NOT NULL,
                arguments TEXT NOT NULL,
                result TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id)
            );
            CREATE TABLE IF NOT EXISTS conversation_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                tool_name TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id)
            );
            """
        )
        columns = {row[1] for row in self._connection.execute("PRAGMA table_info(tasks)")}
        if "recurrence" not in columns:
            self._connection.execute("ALTER TABLE tasks ADD COLUMN recurrence TEXT")
        self._connection.commit()

    @synchronized
    def start_conversation(self) -> str:
        conversation_id = str(uuid.uuid4())
        self._connection.execute(
            "INSERT INTO conversations (id, started_at) VALUES (?, ?)",
            (conversation_id, _timestamp()),
        )
        self._connection.commit()
        return conversation_id

    @synchronized
    def add_message(
        self, conversation_id: str, role: str, content: str, tool_name: str | None = None
    ) -> None:
        self._connection.execute(
            "INSERT INTO conversation_messages "
            "(conversation_id, role, content, tool_name, created_at) VALUES (?, ?, ?, ?, ?)",
            (conversation_id, role, content, tool_name, _timestamp()),
        )
        self._connection.commit()

    @synchronized
    def remember(self, content: str, category: str = "fact") -> int:
        if not content.strip() or not category.strip():
            raise ValueError("Memory content and category are required")
        cursor = self._connection.execute(
            "INSERT INTO memories (content, category, created_at) VALUES (?, ?, ?)",
            (content.strip(), category.strip(), _timestamp()),
        )
        self._connection.commit()
        return int(cursor.lastrowid)

    @synchronized
    def list_memories(self, category: str | None = None) -> list[dict[str, Any]]:
        if category:
            rows = self._connection.execute(
                "SELECT id, content, category, created_at FROM memories "
                "WHERE category = ? ORDER BY id DESC LIMIT 100",
                (category,),
            ).fetchall()
        else:
            rows = self._connection.execute(
                "SELECT id, content, category, created_at FROM memories "
                "ORDER BY id DESC LIMIT 100"
            ).fetchall()
        return [dict(row) for row in rows]

    @synchronized
    def set_preference(self, key: str, value: str) -> None:
        if not key.strip() or not value.strip():
            raise ValueError("Preference key and value are required")
        self._connection.execute(
            "INSERT INTO preferences (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key.strip(), value.strip(), _timestamp()),
        )
        self._connection.commit()

    @synchronized
    def get_preference(self, key: str) -> str | None:
        row = self._connection.execute(
            "SELECT value FROM preferences WHERE key = ?", (key.strip(),)
        ).fetchone()
        return None if row is None else str(row["value"])

    @synchronized
    def list_preferences(self) -> dict[str, str]:
        rows = self._connection.execute(
            "SELECT key, value FROM preferences ORDER BY key"
        ).fetchall()
        return {str(row["key"]): str(row["value"]) for row in rows}

    @synchronized
    def add_task(self, title: str, due_at: str | None = None, recurrence: str | None = None) -> int:
        if not title.strip():
            raise ValueError("Task title is required")
        if recurrence not in {None, 'daily', 'weekly'}:
            raise ValueError('Recurrence must be daily or weekly')
        if recurrence and not due_at:
            raise ValueError('Recurring tasks require a due time')
        if due_at:
            from jarvis.scheduler.automation import due_time
            due_at = due_time(due_at).isoformat()
        cursor = self._connection.execute(
            "INSERT INTO tasks (title, due_at, status, recurrence, created_at) VALUES (?, ?, 'open', ?, ?)",
            (title.strip(), due_at.strip() if due_at else None, recurrence, _timestamp()),
        )
        self._connection.commit()
        return int(cursor.lastrowid)

    @synchronized
    def list_tasks(self, status: str = "open") -> list[dict[str, Any]]:
        rows = self._connection.execute(
            "SELECT id, title, due_at, status, recurrence, created_at FROM tasks "
            "WHERE status = ? ORDER BY id DESC LIMIT 100",
            (status,),
        ).fetchall()
        return [dict(row) for row in rows]

    @synchronized
    def claim_due_tasks(self, now: datetime) -> list[dict[str, Any]]:
        """Advance due reminders atomically across terminal/dashboard workers."""
        due = []
        with self._connection:
            self._connection.execute('BEGIN IMMEDIATE')
            rows = self._connection.execute("SELECT * FROM tasks WHERE status='open' AND due_at IS NOT NULL").fetchall()
            for row in rows:
                try:
                    when = datetime.fromisoformat(row['due_at'].replace('Z', '+00:00'))
                    if when.tzinfo is None:  # Compatibility for reminders saved by older releases.
                        when = when.replace(tzinfo=timezone.utc)
                except (ValueError, TypeError):
                    continue
                if when > now:
                    continue
                due.append(dict(row))
                interval = {'daily': 1, 'weekly': 7}.get(row['recurrence'])
                if interval:
                    next_due = when + timedelta(days=((now-when).days//interval+1)*interval)
                    self._connection.execute('UPDATE tasks SET due_at=? WHERE id=?', (next_due.isoformat(),row['id']))
                else:
                    self._connection.execute("UPDATE tasks SET status='completed' WHERE id=?", (row['id'],))
        return due

    @synchronized
    def reschedule_task(self, task_id: int, due_at: str) -> None:
        self._connection.execute(
            "UPDATE tasks SET due_at = ?, status = 'open' WHERE id = ?", (due_at, task_id)
        )
        self._connection.commit()

    @synchronized
    def complete_task(self, task_id: int) -> None:
        self._connection.execute(
            "UPDATE tasks SET status = 'completed' WHERE id = ?", (task_id,)
        )
        self._connection.commit()

    @synchronized
    def add_tool_history(
        self,
        conversation_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
    ) -> None:
        self._connection.execute(
            "INSERT INTO tool_history "
            "(conversation_id, tool_name, arguments, result, created_at) VALUES (?, ?, ?, ?, ?)",
            (
                conversation_id,
                tool_name,
                json.dumps(arguments, ensure_ascii=False),
                json.dumps(result, ensure_ascii=False),
                _timestamp(),
            ),
        )
        self._connection.commit()
