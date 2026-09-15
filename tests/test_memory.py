from pathlib import Path
from tempfile import TemporaryDirectory
import sqlite3
import unittest

from jarvis.memory import MemoryStore
from jarvis.tools import create_local_tools


class MemoryStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "data" / "jarvis.db"

    def test_schema_and_records_persist_across_connections(self) -> None:
        with MemoryStore(self.path) as memory:
            conversation_id = memory.start_conversation()
            memory.add_message(conversation_id, "user", "My editor is VS Code.")
            memory.remember("The preferred editor is VS Code.", "preference")
            memory.set_preference("editor", "VS Code")
            task_id = memory.add_task("Check the deployment")
            memory.add_tool_history(
                conversation_id, "set_preference", {"key": "editor"}, {"ok": True}
            )

        with MemoryStore(self.path) as reopened:
            self.assertEqual(reopened.get_preference("editor"), "VS Code")
            self.assertEqual(reopened.list_memories("preference")[0]["content"],
                             "The preferred editor is VS Code.")
            self.assertEqual(reopened.list_tasks()[0]["id"], task_id)
            connection = sqlite3.connect(self.path)
            try:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
            finally:
                connection.close()
            self.assertTrue({
                "conversations", "conversation_messages", "memories", "preferences",
                "tasks", "tool_history",
            }.issubset(tables))

    def test_memory_tools_save_and_retrieve_preferences(self) -> None:
        with MemoryStore(self.path) as memory:
            tools = create_local_tools(Path(self.directory.name), memory=memory)
            saved = tools.execute("set_preference", {"key": "editor", "value": "VS Code"})
            result = tools.execute("get_preference", {"key": "editor"})

        self.assertTrue(saved["ok"])
        self.assertEqual(result, {"ok": True, "result": {"key": "editor", "value": "VS Code"}})

    def test_conversations_can_be_listed_and_restored(self) -> None:
        with MemoryStore(self.path) as memory:
            conversation_id = memory.start_conversation()
            memory.add_message(conversation_id, 'user', 'Remember this discussion')
            memory.add_message(conversation_id, 'assistant', 'I remember it')
            conversations = memory.list_conversations()
            messages = memory.conversation_messages(conversation_id)
        self.assertEqual(conversations[0]['id'], conversation_id)
        self.assertEqual(conversations[0]['message_count'], 2)
        self.assertEqual([item['role'] for item in messages], ['user', 'assistant'])


if __name__ == "__main__":
    unittest.main()
