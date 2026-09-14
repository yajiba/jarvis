"""A small in-process scheduler for local reminder tasks."""

from datetime import datetime, timezone
import threading
import logging
import math

from jarvis.memory import MemoryStore


class TaskScheduler:
    def __init__(self, memory: MemoryStore, notify, interval_seconds: float = 5.0, automation=None) -> None:
        if not math.isfinite(interval_seconds) or interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self.memory = memory
        self.notify = notify
        self.interval_seconds = interval_seconds
        self.automation = automation
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
            self._thread.join()
        self._thread = None

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            try:
                self.run_due_once()
            except Exception:
                logging.exception('Reminder scheduler tick failed')
            if self.automation is not None:
                try:
                    self.automation.run_due_once()
                except Exception:
                    logging.exception('Automation scheduler tick failed')

    def run_due_once(self) -> int:
        now = datetime.now(timezone.utc)
        tasks = self.memory.claim_due_tasks(now)
        for task in tasks:
            try:
                self.notify(task)
            except Exception:
                logging.exception('Reminder notification failed')
        return len(tasks)
