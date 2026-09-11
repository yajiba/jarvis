from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from jarvis.memory import MemoryStore
from jarvis.scheduler import TaskScheduler


class SchedulerTests(unittest.TestCase):
    def test_due_task_is_completed_and_notified(self) -> None:
        with TemporaryDirectory() as directory:
            with MemoryStore(Path(directory) / "jarvis.db") as memory:
                due = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
                task_id = memory.add_task("Check deployment", due)
                notifications = []
                scheduler = TaskScheduler(memory, notifications.append)

                self.assertEqual(scheduler.run_due_once(), 1)
                self.assertEqual(notifications[0]["id"], task_id)
                self.assertEqual(memory.list_tasks("completed")[0]["id"], task_id)
                self.assertEqual(scheduler.run_due_once(), 0)

    def test_invalid_interval_is_rejected(self) -> None:
        with TemporaryDirectory() as directory, MemoryStore(Path(directory) / "jarvis.db") as memory:
            with self.assertRaises(ValueError):
                TaskScheduler(memory, lambda task: None, interval_seconds=0)

    def test_daily_task_is_rescheduled(self) -> None:
        with TemporaryDirectory() as directory, MemoryStore(Path(directory) / "jarvis.db") as memory:
            due = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
            task_id = memory.add_task("Daily check", due, "daily")
            TaskScheduler(memory, lambda task: None).run_due_once()
            task = next(task for task in memory.list_tasks() if task["id"] == task_id)
            self.assertEqual(task["recurrence"], "daily")
            self.assertEqual(task["status"], "open")


if __name__ == "__main__":
    unittest.main()
