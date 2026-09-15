"""Small dependency-free local RAG index using SQLite and lexical retrieval."""

from collections import Counter
from pathlib import Path
import re
import sqlite3
from typing import Any


SUPPORTED_EXTENSIONS = {".md", ".txt", ".py", ".js", ".ts", ".json", ".yaml", ".yml", ".html", ".css", ".pdf", ".docx", ".pptx"}
TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9_]{2,}")


def _tokens(text: str) -> list[str]:
    return TOKEN_PATTERN.findall(text.casefold())


class KnowledgeStore:
    def __init__(self, path: Path, semantic: bool = False) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # FastAPI runs synchronous tool handlers in worker threads. The agent's
        # request lock serializes access, so permit that bounded thread handoff.
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute('PRAGMA foreign_keys = ON')
        self._semantic = semantic
        self._collection = None
        self._encoder = None
        if semantic:
            try:
                import chromadb
                self._chroma = chromadb.PersistentClient(path=str(path.parent / "chroma"))
                self._collection = self._chroma.get_or_create_collection("jarvis_knowledge")
            except ImportError as error:
                raise RuntimeError('Semantic RAG requires: pip install -e ".[rag]"') from error
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS documents (
                path TEXT PRIMARY KEY,
                modified_ns INTEGER NOT NULL,
                indexed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                content TEXT NOT NULL,
                FOREIGN KEY (path) REFERENCES documents(path) ON DELETE CASCADE
            );
            """
        )
        self.connection.commit()

    @staticmethod
    def _extract_text(path: Path) -> str:
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            try:
                from pypdf import PdfReader
            except ImportError as error:
                raise RuntimeError('PDF support requires: pip install -e ".[rag]"') from error
            return "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
        if suffix == ".docx":
            try:
                from docx import Document
            except ImportError as error:
                raise RuntimeError('DOCX support requires: pip install -e ".[rag]"') from error
            return "\n".join(paragraph.text for paragraph in Document(str(path)).paragraphs)
        if suffix == ".pptx":
            from jarvis.api.uploads import extract_text
            return extract_text(path.name, path.read_bytes())
        return path.read_text(encoding="utf-8-sig")

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "KnowledgeStore":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def index_directory(self, directory: Path, chunk_size: int = 1200, overlap: int = 150) -> dict[str, int]:
        if chunk_size <= overlap or overlap < 0:
            raise ValueError("chunk_size must be greater than overlap")
        indexed = skipped = removed = 0
        directory = directory.resolve(strict=True)
        seen = set()
        for path in directory.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            if any(part.startswith(".") or part in {"node_modules", "__pycache__"} for part in path.parts):
                continue
            try:
                path = path.resolve(strict=True)
                seen.add(str(path))
                stat = path.stat()
                text = self._extract_text(path)
            except (OSError, UnicodeError, RuntimeError):
                skipped += 1
                continue
            existing = self.connection.execute(
                "SELECT modified_ns FROM documents WHERE path = ?", (str(path),)
            ).fetchone()
            if existing is not None and existing["modified_ns"] == stat.st_mtime_ns:
                continue
            self.connection.execute("DELETE FROM chunks WHERE path = ?", (str(path),))
            self.connection.execute(
                "INSERT INTO documents(path, modified_ns) VALUES(?, ?) "
                "ON CONFLICT(path) DO UPDATE SET modified_ns=excluded.modified_ns, indexed_at=CURRENT_TIMESTAMP",
                (str(path), stat.st_mtime_ns),
            )
            step = chunk_size - overlap
            chunks = [text[start:start + chunk_size] for start in range(0, max(len(text), 1), step)]
            self.connection.executemany(
                "INSERT INTO chunks(path, chunk_index, content) VALUES(?, ?, ?)",
                [(str(path), index, chunk) for index, chunk in enumerate(chunks) if chunk.strip()],
            )
            if self._collection is not None:
                self._collection.delete(where={'path': str(path)})
                ids = [f"{path}:{index}" for index, chunk in enumerate(chunks) if chunk.strip()]
                documents = [chunk for chunk in chunks if chunk.strip()]
                if ids:
                    self._collection.upsert(ids=ids, documents=documents,
                                            metadatas=[{"path": str(path), "chunk_index": index}
                                                       for index, chunk in enumerate(chunks) if chunk.strip()])
            indexed += 1
        stale = []
        for row in self.connection.execute("SELECT path FROM documents").fetchall():
            indexed_path = Path(row['path'])
            if indexed_path.is_relative_to(directory) and row['path'] not in seen:
                stale.append(row['path'])
        for path in stale:
            self.connection.execute("DELETE FROM documents WHERE path = ?", (path,))
            if self._collection is not None:
                self._collection.delete(where={'path': path})
            removed += 1
        self.connection.commit()
        return {"indexed": indexed, "skipped": skipped, "removed": removed}

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        if self._collection is not None and query.strip():
            result = self._collection.query(query_texts=[query], n_results=limit)
            documents = result.get("documents", [[]])[0]
            metadatas = result.get("metadatas", [[]])[0]
            distances = result.get("distances", [[]])[0]
            return [{"path": metadata.get("path"), "chunk_index": metadata.get("chunk_index"),
                     "content": document, "score": round(1 - distance, 4)}
                    for document, metadata, distance in zip(documents, metadatas, distances)]
        query_tokens = Counter(_tokens(query))
        if not query_tokens:
            return []
        rows = self.connection.execute("SELECT path, chunk_index, content FROM chunks").fetchall()
        scored = []
        for row in rows:
            content_tokens = Counter(_tokens(row["content"]))
            score = sum(min(count, content_tokens[token]) for token, count in query_tokens.items())
            if score:
                scored.append({"path": row["path"], "chunk_index": row["chunk_index"],
                               "content": row["content"], "score": score})
        return sorted(scored, key=lambda item: (-item["score"], item["path"], item["chunk_index"]))[:limit]
