"""A small in-process scheduler for local reminder tasks."""

from datetime import datetime, timedelta, timezone
import threading

from jarvis.memory import MemoryStore


class TaskScheduler:
    def __init__(self, memory: MemoryStore, notify, interval_seconds: float = 5.0) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self.memory = memory
        self.notify = notify
        self.interval_seconds = interval_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="jarvis-scheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(1.0, self.interval_seconds + 1))
        self._thread = None

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            self.run_due_once()

    def run_due_once(self) -> int:
        now = datetime.now(timezone.utc)
        completed = 0
        for task in self.memory.list_tasks("open"):
            if not task.get("due_at"):
                continue
            try:
                due_at = datetime.fromisoformat(task["due_at"].replace("Z", "+00:00"))
            except (TypeError, ValueError):
                continue
            if due_at.tzinfo is None:
                due_at = due_at.replace(tzinfo=timezone.utc)
            if due_at <= now:
                recurrence = task.get("recurrence")
                if recurrence == "daily":
                    self.memory.reschedule_task(int(task["id"]), (due_at + timedelta(days=1)).isoformat())
                elif recurrence == "weekly":
                    self.memory.reschedule_task(int(task["id"]), (due_at + timedelta(days=7)).isoformat())
                else:
                    self.memory.complete_task(int(task["id"]))
                self.notify(task)
                completed += 1
        return completed
