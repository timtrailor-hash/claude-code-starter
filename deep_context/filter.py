"""Pre-filter for /deep-context fan-out.

Given a brief, return a candidate list of session IDs (20-80 typical)
by unioning: time window, topic overlap, file overlap, FTS keyword match,
and ChromaDB semantic match.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import index as dc_index

DEFAULT_WINDOW_DAYS = 90
MAX_CANDIDATES = 120  # hard cap before aggregator


def _iso_window_start(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds").replace("+00:00", "Z")


def _fts_query(conn: sqlite3.Connection, brief: str, limit: int = 60) -> list[str]:
    # Extract words of length >= 4; join with OR for FTS
    words = re.findall(r"[A-Za-z0-9_/.]{4,}", brief)
    if not words:
        return []
    query = " OR ".join(f'"{w}"' for w in words[:20])
    try:
        rows = conn.execute(
            "SELECT session_id FROM compressed WHERE compressed MATCH ? LIMIT ?",
            (query, limit),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [r[0] for r in rows]


def _time_window(conn: sqlite3.Connection, days: int, limit: int = 5000) -> list[str]:
    """Sessions started within the last `days` days. Default limit is high
    enough that a full corpus fits — the intent of this filter is a date range,
    not a top-N cap. If you have >5000 sessions, raise the limit."""
    cutoff = _iso_window_start(days)
    rows = conn.execute(
        "SELECT session_id FROM meta WHERE started >= ? ORDER BY started DESC LIMIT ?",
        (cutoff, limit),
    ).fetchall()
    return [r[0] for r in rows]


def _topic_overlap(conn: sqlite3.Connection, topics: list[str]) -> list[str]:
    if not topics:
        return []
    out: set[str] = set()
    for t in topics:
        rows = conn.execute(
            "SELECT session_id FROM meta WHERE topics LIKE ?",
            (f"%{t}%",),
        ).fetchall()
        out.update(r[0] for r in rows)
    return list(out)


def _file_overlap(conn: sqlite3.Connection, files: list[str]) -> list[str]:
    if not files:
        return []
    out: set[str] = set()
    for f in files:
        rows = conn.execute(
            "SELECT session_id FROM meta WHERE files LIKE ?",
            (f"%{f}%",),
        ).fetchall()
        out.update(r[0] for r in rows)
    return list(out)


def _semantic(brief: str, limit: int = 40) -> list[str]:
    try:
        col = dc_index._get_collection()
        res = col.query(query_texts=[brief], n_results=limit)
        ids = res.get("ids") or []
        return ids[0] if ids else []
    except Exception:
        return []


def _extract_topic_hints(brief: str) -> list[str]:
    # Short lowercase words likely to be topic tags
    words = re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", brief.lower())
    # Prefer multi-char hyphenated (e.g. "memory-system")
    return [w for w in words if len(w) >= 4][:10]


def _extract_file_hints(brief: str) -> list[str]:
    return re.findall(r"(?:/[A-Za-z0-9_.-]+)+\.[A-Za-z0-9]+", brief)


def prefilter(brief: str,
              window_days: int = DEFAULT_WINDOW_DAYS,
              max_candidates: int = MAX_CANDIDATES) -> dict:
    """Return {candidates: [session_id], by_source: {...}, counts: {...}}."""
    conn = dc_index._ensure_fts()
    try:
        time_ids = set(_time_window(conn, window_days))
        topic_ids = set(_topic_overlap(conn, _extract_topic_hints(brief)))
        file_ids = set(_file_overlap(conn, _extract_file_hints(brief)))
        fts_ids = set(_fts_query(conn, brief))
    finally:
        conn.close()
    sem_ids = set(_semantic(brief))

    # Trust relevance hits unconditionally — a session flagged by FTS,
    # semantic, topic, or file overlap is relevant regardless of recency.
    # Time window only acts as the fallback for briefs with no relevance hits.
    relevance = fts_ids | sem_ids | topic_ids | file_ids
    if relevance:
        union = relevance
        # Pad with recent sessions if the relevance set is small, so the
        # aggregator has some contextual ballast even on narrow briefs.
        if len(union) < 20 and time_ids:
            union = union | set(list(time_ids)[:20])
    else:
        union = time_ids

    # Rank candidates: relevance-hit sessions first (by how many sources
    # surfaced them), then fill with recent ones.
    def _rank(sid: str) -> int:
        score = 0
        if sid in fts_ids: score += 3
        if sid in sem_ids: score += 3
        if sid in topic_ids: score += 2
        if sid in file_ids: score += 4
        return -score  # negative for descending sort

    candidates = sorted(union, key=_rank)[:max_candidates]
    return {
        "brief": brief,
        "window_days": window_days,
        "candidates": candidates,
        "by_source": {
            "fts": sorted(fts_ids & set(candidates))[:30],
            "semantic": sorted(sem_ids & set(candidates))[:30],
            "topic": sorted(topic_ids & set(candidates))[:30],
            "file": sorted(file_ids & set(candidates))[:30],
            "time": sorted(time_ids & set(candidates))[:30],
        },
        "counts": {
            "fts": len(fts_ids), "semantic": len(sem_ids),
            "topic": len(topic_ids), "file": len(file_ids),
            "time": len(time_ids), "total": len(candidates),
        },
    }


def paths_for(session_ids: list[str]) -> list[str]:
    conn = dc_index._ensure_fts()
    try:
        out = []
        for sid in session_ids:
            row = conn.execute("SELECT path FROM meta WHERE session_id = ?", (sid,)).fetchone()
            if row and row[0]:
                out.append(row[0])
        return out
    finally:
        conn.close()
