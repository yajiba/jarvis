from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from jarvis.tools import create_local_tools


class CodingToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "app.py").write_text("def greet():\n    return 'hello'\n", encoding="utf-8")
        (self.root / "README.md").write_text("Sentrix service\n", encoding="utf-8")

    def test_search_read_and_analyze_project(self) -> None:
        tools = create_local_tools(self.root)

        search = tools.execute("search_code", {"query": "hello", "path": "."})
        source = tools.execute("read_source_file", {"path": "app.py"})
        analysis = tools.execute("analyze_project", {"path": "."})

        self.assertEqual(search["result"]["matches"][0]["line"], 2)
        self.assertIn("def greet", source["result"])
        self.assertEqual(analysis["result"]["file_counts"][".py"], 1)

    def test_writes_require_confirmation(self) -> None:
        denied = create_local_tools(self.root, confirm=lambda name, details: False)
        allowed = create_local_tools(self.root, confirm=lambda name, details: True)

        self.assertFalse(denied.execute("create_file", {
            "path": "new.py", "content": "print('new')\n"
        })["ok"])
        self.assertTrue(allowed.execute("create_file", {
            "path": "new.py", "content": "print('new')\n"
        })["ok"])
        self.assertTrue(allowed.execute("edit_file", {
            "path": "app.py", "content": "print('edited')\n"
        })["ok"])
        self.assertEqual((self.root / "app.py").read_text(encoding="utf-8"), "print('edited')\n")

    def test_coding_paths_cannot_escape_approved_root(self) -> None:
        tools = create_local_tools(self.root)

        result = tools.execute("read_source_file", {"path": "../outside.py"})

        self.assertFalse(result["ok"])
        self.assertIn("approved project roots", result["error"])


if __name__ == "__main__":
    unittest.main()
