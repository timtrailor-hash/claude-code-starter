"""Unified index for compressed-session markdown files.

One compressed session → one row in a dedicated FTS5 table + one embedding
in a dedicated ChromaDB collection. Kept separate from the memory_server's
raw-JSONL index so /deep-context queries don't compete with /search_memory.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import chromadb

from . import schema

DATA_DIR = Path.home() / "code" / "memory_server_data"
CHROMA_DIR = DATA_DIR / "chroma"
FTS_PATH = DATA_DIR / "compressed_fts.db"
COLLECTION_NAME = "compressed_sessions_v2"  # v2 uses fresh collection; v1 retained for rollback

_client = None
_collection = None


def _get_collection():
    global _client, _collection
    if _collection is None:
        CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(path=str(CHROMA_DIR))
        _collection = _client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"description": "compressed session summaries"},
        )
    return _collection


def _ensure_fts() -> sqlite3.Connection:
    FTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(FTS_PATH)
    conn.executescript(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS compressed USING fts5(
            session_id UNINDEXED,
            started UNINDEXED,
            project UNINDEXED,
            topics,
            body,
            path UNINDEXED
        );
        CREATE TABLE IF NOT EXISTS meta(
            session_id TEXT PRIMARY KEY,
            started TEXT,
            ended TEXT,
            project TEXT,
            model TEXT,
            files TEXT,
            topics TEXT,
            complexity TEXT,
            path TEXT,
            indexed_at TEXT
        );
        """
    )
    conn.commit()
    return conn


def _body_only(text: str) -> str:
    if text.startswith("---\n"):
        parts = text.split("---\n", 2)
        if len(parts) == 3:
            return parts[2]
    return text


def index_file(md_path: Path) -> dict:
    """Read a compressed-session markdown file and write to both indexes.

    Validates on load; never indexes an invalid entry.
    """
    text = md_path.read_text()
    fm = schema.validate(text)

    session_id = fm["session_id"]
    body = _body_only(text)
    topics = ", ".join(fm.get("topics_touched", []) or [])

    # ChromaDB — whole-document embedding (not chunked; docs are already small)
    col = _get_collection()
    col.upsert(
        ids=[session_id],
        documents=[body],
        metadatas=[{
            "session_id": session_id,
            "started": fm["started"],
            "project": fm.get("project", ""),
            "topics": topics,
            "model": fm["compression_model"],
            "path": str(md_path),
        }],
    )

    # FTS5 — session_id is UNINDEXED; delete-then-insert for idempotency
    conn = _ensure_fts()
    conn.execute("DELETE FROM compressed WHERE session_id = ?", (session_id,))
    conn.execute(
        "INSERT INTO compressed(session_id, started, project, topics, body, path) VALUES (?, ?, ?, ?, ?, ?)",
        (session_id, fm["started"], fm.get("project", ""), topics, body, str(md_path)),
    )
    from datetime import datetime, timezone
    conn.execute(
        """INSERT OR REPLACE INTO meta(session_id, started, ended, project, model, files, topics, complexity, path, indexed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            session_id,
            fm["started"],
            fm["ended"],
            fm.get("project", ""),
            fm["compression_model"],
            json.dumps(fm.get("files_touched", [])),
            topics,
            json.dumps(fm.get("complexity_flags", [])),
            str(md_path),
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
    conn.close()

    return {"session_id": session_id, "path": str(md_path), "indexed": True}


def reindex_all(sessions_root: Path | None = None) -> dict:
    sessions_root = sessions_root or DATA_DIR / "sessions"
    ok = 0
    fail = 0
    errors: list[str] = []
    for md in sorted(sessions_root.rglob("*.md")):
        if md.name.startswith("_"):
            continue
        try:
            index_file(md)
            ok += 1
        except Exception as e:
            fail += 1
            errors.append(f"{md}: {e}")
    return {"indexed": ok, "failed": fail, "errors": errors[:10]}
