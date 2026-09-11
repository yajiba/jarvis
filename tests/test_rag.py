from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from jarvis.rag import KnowledgeStore


class KnowledgeStoreTests(unittest.TestCase):
    def test_index_and_search_local_documents(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "notes.md").write_text("Sentrix attendance workflow uses a service log.", encoding="utf-8")
            (root / "ignored.bin").write_bytes(b"attendance")
            with KnowledgeStore(root / "knowledge.db") as store:
                result = store.index_directory(root)
                matches = store.search("attendance service log")

            self.assertEqual(result["indexed"], 1)
            self.assertEqual(len(matches), 1)
            self.assertIn("attendance", matches[0]["content"])

    def test_reindex_skips_unchanged_files_and_empty_queries(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "app.py"
            source.write_text("def health_check(): pass", encoding="utf-8")
            with KnowledgeStore(root / "knowledge.db") as store:
                self.assertEqual(store.index_directory(root)["indexed"], 1)
                self.assertEqual(store.index_directory(root)["indexed"], 0)
                self.assertEqual(store.search("!!!"), [])

    def test_docx_text_is_indexed_when_parser_is_available(self) -> None:
        from docx import Document

        with TemporaryDirectory() as directory:
            root = Path(directory)
            document = Document()
            document.add_paragraph("Sentrix attendance workflow")
            document.save(root / "notes.docx")
            with KnowledgeStore(root / "knowledge.db") as store:
                store.index_directory(root)
                matches = store.search("attendance workflow")

            self.assertTrue(matches)


if __name__ == "__main__":
    unittest.main()
