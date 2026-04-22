#!/usr/bin/env python3
"""
Memory MCP Server — Two-tier search over Claude Code conversation history.

Tier 1: ChromaDB vector search (semantic — "what did we try for belt tension?")
Tier 2: SQLite FTS5 keyword search (exact — "192.168.87.52", error messages)

Both indexes share the same chunks from .jsonl conversation transcripts.
"""

import fcntl
import json
import os
import re
import sqlite3
import sys
import time
from datetime import datetime
from glob import glob
from pathlib import Path

import chromadb
from fastmcp import FastMCP

# --- Config ---
DATA_DIR = Path.home() / "code" / "memory_server_data"
CHROMA_DIR = DATA_DIR / "chroma"
SQLITE_PATH = DATA_DIR / "fts.db"
LOCK_FILE = DATA_DIR / "memory_server.lock"
TRANSCRIPTS_DIR = Path.home() / ".claude" / "projects"
CHUNK_SIZE = 500
CHUNK_OVERLAP = 50

# --- Initialize ---
DATA_DIR.mkdir(parents=True, exist_ok=True)

# --- Single-instance lock ---
# fcntl.flock uses OS-level advisory locks that are automatically released
# when the process exits (even on crash), so stale locks are never an issue.
_lock_fd = open(LOCK_FILE, "w")
try:
    fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
except OSError:
    print(
        f"memory_server: another instance is already running (lock: {LOCK_FILE}). Exiting.",
        file=sys.stderr,
    )
    sys.exit(1)

mcp = FastMCP(
    "memory",
    instructions="Search Tim's Claude Code conversation history. Use search_memory for semantic questions, search_exact for keywords/IPs/error messages.",
)

# --- ChromaDB setup ---
chroma_client = chromadb.PersistentClient(path=str(CHROMA_DIR))
collection = chroma_client.get_or_create_collection(
    name="conversations",
    metadata={"hnsw:space": "cosine"},
)

# --- SQLite FTS5 setup ---
def get_fts_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(SQLITE_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(
            chunk_id, conv_id, date, topic, role, chunk_text,
            tokenize='porter unicode61'
        )
    """)
    # Metadata table to track indexed conversations
    conn.execute("""
        CREATE TABLE IF NOT EXISTS indexed_convs(
            conv_id TEXT PRIMARY KEY,
            file_path TEXT,
            indexed_at TEXT,
            chunk_count INTEGER,
            file_size INTEGER
        )
    """)
    # Add file_size column if upgrading from older schema
    try:
        conn.execute("ALTER TABLE indexed_convs ADD COLUMN file_size INTEGER")
    except sqlite3.OperationalError:
        pass  # Column already exists
    conn.commit()
    return conn


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into chunks with overlap."""
    if len(text) <= size:
        return [text] if text.strip() else []
    chunks = []
    start = 0
    while start < len(text):
        end = start + size
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk)
        start = end - overlap
    return chunks


def extract_messages(jsonl_path: str) -> list[dict]:
    """Extract user and assistant text messages from a .jsonl transcript."""
    messages = []
    with open(jsonl_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            msg = obj.get("message", {})
            role = msg.get("role")
            if role not in ("user", "assistant"):
                continue

            content = msg.get("content", "")
            text = ""
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                parts = []
                for block in content:
                    if block.get("type") == "text":
                        parts.append(block.get("text", ""))
                text = "\n".join(parts)

            text = text.strip()
            if not text or len(text) < 20:
                continue

            timestamp = obj.get("timestamp", "")
            messages.append({
                "role": role,
                "text": text,
                "timestamp": timestamp,
            })
    return messages


def guess_topic(file_path: str, messages: list[dict]) -> str:
    """Guess conversation topic from first few messages."""
    path = Path(file_path)
    # Check parent directory name for hints
    parent = path.parent.name
    if parent != "projects" and not parent.startswith("-"):
        return parent

    # Sample first few user messages
    for msg in messages[:3]:
        if msg["role"] == "user":
            text = msg["text"][:200].lower()
            if any(w in text for w in ["printerpilot", "controlview", "dashboardview", "swiftui", "xcodeproj"]):
                return "printerpilot"
            if any(w in text for w in ["printer", "sv08", "klipper", "filament", "nozzle", "orca"]):
                return "printer"
            if any(w in text for w in ["ups", "cyberpower", "watchdog", "power cut", "battery"]):
                return "ups"
            if any(w in text for w in ["merchant", "faizal", "risk", "model", "databricks"]):
                return "<proprietary_model>"
            if any(w in text for w in ["ofsted", "governor", "school", "castle", "victoria"]):
                return "school-governors"
            if any(w in text for w in ["migration", "mac mini", "migrate", "ownership"]):
                return "migration"
            if any(w in text for w in ["memory", "chromadb", "fts5", "index_all", "search_memory"]):
                return "memory"
            if any(w in text for w in ["auction", "silent auction", "dragon"]):
                return "auction"
            if any(w in text for w in ["wrapper", "claude-mobile", "app.py"]):
                return "claude-mobile"
            break
    return "general"


def index_single_conversation(
    conv_id: str,
    file_path: str,
    messages: list[dict],
    topic: str,
    date: str,
    fts_conn: sqlite3.Connection,
) -> int:
    """Index one conversation into both ChromaDB and FTS5. Returns chunk count."""
    # Build full transcript text grouped by message
    all_chunks_ids = []
    all_chunks_docs = []
    all_chunks_meta = []
    fts_rows = []

    for msg_idx, msg in enumerate(messages):
        chunks = chunk_text(msg["text"])
        for chunk_idx, chunk in enumerate(chunks):
            chunk_id = f"{conv_id}_{msg_idx}_{chunk_idx}"
            meta = {
                "conv_id": conv_id,
                "date": date,
                "topic": topic,
                "role": msg["role"],
                "chunk_idx": chunk_idx,
                "msg_idx": msg_idx,
            }
            all_chunks_ids.append(chunk_id)
            all_chunks_docs.append(chunk)
            all_chunks_meta.append(meta)
            fts_rows.append((chunk_id, conv_id, date, topic, msg["role"], chunk))

    if not all_chunks_ids:
        return 0

    # ChromaDB — batch upsert (max 5461 per batch)
    batch_size = 5000
    for i in range(0, len(all_chunks_ids), batch_size):
        end = i + batch_size
        collection.upsert(
            ids=all_chunks_ids[i:end],
            documents=all_chunks_docs[i:end],
            metadatas=all_chunks_meta[i:end],
        )

    # FTS5 — batch insert
    fts_conn.executemany(
        "INSERT OR REPLACE INTO chunks(chunk_id, conv_id, date, topic, role, chunk_text) VALUES (?, ?, ?, ?, ?, ?)",
        fts_rows,
    )
    file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
    fts_conn.execute(
        "INSERT OR REPLACE INTO indexed_convs(conv_id, file_path, indexed_at, chunk_count, file_size) VALUES (?, ?, ?, ?, ?)",
        (conv_id, file_path, datetime.now().isoformat(), len(all_chunks_ids), file_size),
    )
    fts_conn.commit()

    return len(all_chunks_ids)


# --- MCP Tools ---

@mcp.tool()
def search_memory(query: str, n_results: int = 5, topic: str | None = None, compact: bool = False) -> str:
    """Semantic vector search over conversation history.

    Good for questions like "what did we try when belt tension was wrong?"
    or "how did we fix the SSH timeout issue?"

    Args:
        query: Natural language search query
        n_results: Number of results to return (default 5, max 20)
        topic: Optional topic filter (printer, <proprietary_model>, school-governors, etc.)
        compact: If True, return only metadata + first 80 chars (saves tokens)
    """
    n_results = min(n_results, 20)
    where = {"topic": topic} if topic else None

    try:
        results = collection.query(
            query_texts=[query],
            n_results=n_results,
            where=where,
            include=["documents", "metadatas", "distances"],
        )
    except Exception as e:
        return f"Search error: {e}"

    if not results["ids"] or not results["ids"][0]:
        return "No results found."

    output = []
    for i, (doc, meta, dist) in enumerate(
        zip(results["documents"][0], results["metadatas"][0], results["distances"][0])
    ):
        similarity = 1 - dist  # cosine distance → similarity
        if compact:
            preview = doc[:80].replace("\n", " ") + ("..." if len(doc) > 80 else "")
            output.append(
                f"{i+1}. [{similarity:.2f}] {meta.get('conv_id', '?')[:12]} | "
                f"{meta.get('date', '?')} | {meta.get('topic', '?')} | "
                f"{meta.get('role', '?')}: {preview}"
            )
        else:
            output.append(
                f"### Result {i+1} (similarity: {similarity:.2f})\n"
                f"**Conv**: {meta.get('conv_id', 'unknown')[:12]}... | "
                f"**Date**: {meta.get('date', '?')} | "
                f"**Topic**: {meta.get('topic', '?')} | "
                f"**Role**: {meta.get('role', '?')}\n\n"
                f"{doc}\n"
            )
    return "\n---\n".join(output) if not compact else "\n".join(output)


@mcp.tool()
def search_exact(query: str, n_results: int = 5, topic: str | None = None, compact: bool = False) -> str:
    """Keyword/exact search over conversation history using FTS5.

    Good for IPs, error messages, specific terms: "192.168.87.52", "belt tension Hz".
    Supports boolean operators (AND, OR, NOT), phrases ("exact phrase"), prefix (term*).

    Args:
        query: Search query (supports FTS5 syntax)
        n_results: Number of results to return (default 5, max 20)
        topic: Optional topic filter
        compact: If True, return only metadata + first 80 chars (saves tokens)
    """
    n_results = min(n_results, 20)
    conn = get_fts_db()

    # Build query — search in chunk_text column
    where_clause = ""
    params: list = []
    if topic:
        where_clause = "AND topic = ?"
        params.append(topic)

    try:
        # Try FTS5 match first
        rows = conn.execute(
            f"""
            SELECT chunk_id, conv_id, date, topic, role,
                   snippet(chunks, 5, '>>>', '<<<', '...', 40) as snippet,
                   rank
            FROM chunks
            WHERE chunks MATCH ? {where_clause}
            ORDER BY rank
            LIMIT ?
            """,
            [query] + params + [n_results],
        ).fetchall()
    except sqlite3.OperationalError:
        # If FTS5 syntax fails, wrap in quotes for literal search
        escaped = query.replace('"', '""')
        rows = conn.execute(
            f"""
            SELECT chunk_id, conv_id, date, topic, role,
                   snippet(chunks, 5, '>>>', '<<<', '...', 40) as snippet,
                   rank
            FROM chunks
            WHERE chunks MATCH ? {where_clause}
            ORDER BY rank
            LIMIT ?
            """,
            [f'"{escaped}"'] + params + [n_results],
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return "No results found."

    output = []
    for i, row in enumerate(rows):
        chunk_id, conv_id, date, topic_val, role, snippet, rank = row
        if compact:
            preview = snippet[:80].replace("\n", " ") + ("..." if len(snippet) > 80 else "")
            output.append(
                f"{i+1}. [{rank:.1f}] {conv_id[:12]} | "
                f"{date} | {topic_val} | {role}: {preview}"
            )
        else:
            output.append(
                f"### Result {i+1} (rank: {rank:.2f})\n"
                f"**Conv**: {conv_id[:12]}... | "
                f"**Date**: {date} | "
                f"**Topic**: {topic_val} | "
                f"**Role**: {role}\n\n"
                f"{snippet}\n"
            )
    return "\n---\n".join(output) if not compact else "\n".join(output)


@mcp.tool()
def index_conversation(conv_id: str, file_path: str, topic: str | None = None) -> str:
    """Index a single conversation transcript into the memory database.

    Args:
        conv_id: Conversation/session ID
        file_path: Absolute path to the .jsonl transcript file
        topic: Optional topic override (auto-detected if not provided)
    """
    if not os.path.exists(file_path):
        return f"File not found: {file_path}"

    messages = extract_messages(file_path)
    if not messages:
        return f"No indexable messages found in {file_path}"

    if not topic:
        topic = guess_topic(file_path, messages)

    # Extract date from first timestamp
    date = "unknown"
    for msg in messages:
        ts = msg.get("timestamp", "")
        if ts:
            date = ts[:10]  # YYYY-MM-DD
            break

    fts_conn = get_fts_db()
    try:
        chunk_count = index_single_conversation(conv_id, file_path, messages, topic, date, fts_conn)
    finally:
        fts_conn.close()

    return f"Indexed {conv_id}: {len(messages)} messages -> {chunk_count} chunks (topic: {topic}, date: {date})"


@mcp.tool()
def index_all_transcripts(force_reindex: bool = False) -> str:
    """Bulk-index all .jsonl conversation transcripts.

    Scans ~/.claude/projects/ for .jsonl files and indexes any that haven't been indexed yet.

    Args:
        force_reindex: If True, re-index all conversations even if already indexed
    """
    # Find all .jsonl files (recursively across all project dirs)
    jsonl_files = []
    for root, dirs, files in os.walk(str(TRANSCRIPTS_DIR)):
        for f in files:
            if f.endswith(".jsonl"):
                jsonl_files.append(os.path.join(root, f))

    if not jsonl_files:
        return "No .jsonl transcript files found."

    # Check what's already indexed (with file sizes for stale detection)
    fts_conn = get_fts_db()
    already_indexed = {}  # conv_id -> file_size
    if not force_reindex:
        rows = fts_conn.execute("SELECT conv_id, file_size FROM indexed_convs").fetchall()
        already_indexed = {r[0]: r[1] for r in rows}

    indexed = 0
    skipped = 0
    reindexed = 0
    errors = 0
    total_chunks = 0

    for fp in sorted(jsonl_files):
        conv_id = Path(fp).stem
        if conv_id in already_indexed:
            stored_size = already_indexed[conv_id]
            current_size = os.path.getsize(fp)
            if stored_size is None:
                # Migration: backfill file_size without re-indexing
                fts_conn.execute(
                    "UPDATE indexed_convs SET file_size = ? WHERE conv_id = ?",
                    (current_size, conv_id),
                )
                skipped += 1
                continue
            if current_size <= stored_size * 1.1:
                skipped += 1
                continue
            # File has grown by >10% — re-index it
            reindexed += 1

        try:
            messages = extract_messages(fp)
            if not messages:
                skipped += 1
                continue

            topic = guess_topic(fp, messages)
            date = "unknown"
            for msg in messages:
                ts = msg.get("timestamp", "")
                if ts:
                    date = ts[:10]
                    break

            chunk_count = index_single_conversation(conv_id, fp, messages, topic, date, fts_conn)
            total_chunks += chunk_count
            indexed += 1
        except Exception as e:
            errors += 1

    fts_conn.commit()  # Persist any backfilled file_size updates
    fts_conn.close()

    return (
        f"Indexing complete.\n"
        f"- New: {indexed} conversations ({total_chunks} chunks)\n"
        f"- Re-indexed: {reindexed} (file grew >10%)\n"
        f"- Skipped: {skipped} (already indexed or empty)\n"
        f"- Errors: {errors}\n"
        f"- Total files scanned: {len(jsonl_files)}"
    )


@mcp.tool()
def get_memory_stats() -> str:
    """Show memory database statistics — DB sizes, chunk counts, last indexed."""
    stats = []

    # ChromaDB stats
    try:
        count = collection.count()
        chroma_size = sum(
            f.stat().st_size for f in CHROMA_DIR.rglob("*") if f.is_file()
        )
        stats.append(f"**ChromaDB**: {count:,} chunks, {chroma_size / 1024 / 1024:.1f} MB")
    except Exception as e:
        stats.append(f"**ChromaDB**: error — {e}")

    # SQLite FTS5 stats
    try:
        conn = get_fts_db()
        row = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()
        conv_row = conn.execute("SELECT COUNT(*) FROM indexed_convs").fetchone()
        last_row = conn.execute(
            "SELECT indexed_at FROM indexed_convs ORDER BY indexed_at DESC LIMIT 1"
        ).fetchone()
        conn.close()

        fts_size = SQLITE_PATH.stat().st_size if SQLITE_PATH.exists() else 0
        stats.append(
            f"**SQLite FTS5**: {row[0]:,} chunks, {conv_row[0]:,} conversations, "
            f"{fts_size / 1024 / 1024:.1f} MB"
        )
        if last_row:
            stats.append(f"**Last indexed**: {last_row[0]}")
    except Exception as e:
        stats.append(f"**SQLite FTS5**: error — {e}")

    # Transcript count (recursive)
    jsonl_count = sum(
        1 for _ , _, files in os.walk(str(TRANSCRIPTS_DIR))
        for f in files if f.endswith(".jsonl")
    )
    stats.append(f"**Available transcripts**: {jsonl_count} .jsonl files")

    return "\n".join(stats)


if __name__ == "__main__":
    mcp.run(transport="stdio")
