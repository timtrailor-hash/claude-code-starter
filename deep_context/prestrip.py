"""Pre-strip a session JSONL transcript for compression input.

Goal: ~10x reduction. Keep everything a human reviewer would look at
to reconstruct what happened. Drop scaffolding (tool definitions,
repeated system content, bulky tool outputs).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator

TOOL_OUTPUT_BYTES_CAP = 2048
TOOL_OUTPUT_HEAD_BYTES = 200


def _stringify_content(content) -> str:
    """Flatten message.content into plain text for compression input."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for block in content:
            if not isinstance(block, dict):
                out.append(str(block))
                continue
            btype = block.get("type")
            if btype == "text":
                out.append(block.get("text", ""))
            elif btype == "thinking":
                pass  # drop internal thinking — noise for compression
            elif btype == "tool_use":
                name = block.get("name", "?")
                inp = block.get("input", {})
                try:
                    inp_s = json.dumps(inp, separators=(",", ":"))
                except (TypeError, ValueError):
                    inp_s = str(inp)
                if len(inp_s) > 800:
                    inp_s = inp_s[:800] + f"...[+{len(inp_s) - 800}B input elided]"
                out.append(f"[tool_call {name}: {inp_s}]")
            elif btype == "tool_result":
                raw = block.get("content", "")
                if isinstance(raw, list):
                    raw = "".join(r.get("text", "") if isinstance(r, dict) else str(r) for r in raw)
                raw = raw if isinstance(raw, str) else str(raw)
                if len(raw) > TOOL_OUTPUT_BYTES_CAP:
                    elided = len(raw) - TOOL_OUTPUT_HEAD_BYTES
                    raw = raw[:TOOL_OUTPUT_HEAD_BYTES] + f"...[{elided}B tool-output elided]"
                out.append(f"[tool_result: {raw}]")
            else:
                out.append(f"[{btype}]")
        return "\n".join(x for x in out if x)
    return str(content)


def iter_records(jsonl_path: Path) -> Iterator[dict]:
    with jsonl_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def prestrip(jsonl_path: Path) -> dict:
    """Parse a session JSONL into a compact representation.

    Returns:
      {
        "session_id": str,
        "cwd": str,
        "slug": str,
        "is_sidechain": bool,           # True → subagent log, skip in backfill
        "started_ts_ms": int | None,
        "ended_ts_ms": int | None,
        "tool_call_count": int,
        "files_touched": [str],         # from tool inputs
        "turns": [ {role, text} ],      # flattened
        "raw_bytes": int,
        "stripped_bytes": int,
      }
    """
    session_id = None
    cwd = None
    slug = None
    is_sidechain = False
    started_ms = None
    ended_ms = None
    tool_calls = 0
    files_touched: set[str] = set()
    turns: list[dict] = []
    raw_bytes = 0
    for rec in iter_records(jsonl_path):
        raw_bytes += len(json.dumps(rec))
        if session_id is None:
            session_id = rec.get("sessionId") or rec.get("session_id")
            cwd = rec.get("cwd")
            slug = rec.get("slug")
            is_sidechain = bool(rec.get("isSidechain", False))
        ts = rec.get("timestamp") or rec.get("created_at")
        if isinstance(ts, int):
            if started_ms is None or ts < started_ms:
                started_ms = ts
            if ended_ms is None or ts > ended_ms:
                ended_ms = ts
        msg = rec.get("message") or {}
        role = msg.get("role") or rec.get("type") or "unknown"
        content = msg.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "tool_use":
                        tool_calls += 1
                        inp = block.get("input") or {}
                        fp = inp.get("file_path") or inp.get("path") or inp.get("notebook_path")
                        if isinstance(fp, str):
                            files_touched.add(fp)
        text = _stringify_content(content)
        if text:
            turns.append({"role": role, "text": text})

    stripped_bytes = sum(len(t["text"]) for t in turns)
    return {
        "session_id": session_id,
        "cwd": cwd,
        "slug": slug,
        "is_sidechain": is_sidechain,
        "started_ts_ms": started_ms,
        "ended_ts_ms": ended_ms,
        "tool_call_count": tool_calls,
        "files_touched": sorted(files_touched),
        "turns": turns,
        "raw_bytes": raw_bytes,
        "stripped_bytes": stripped_bytes,
    }


def format_for_compression(stripped: dict, max_chars: int = 400_000) -> str:
    """Render the stripped session into a single prompt-ready string.

    Hard cap at max_chars so a runaway session can't blow the model context.
    """
    header = f"SESSION {stripped['session_id']} (cwd={stripped['cwd']}, slug={stripped['slug']})\n\n"
    body_parts = []
    for t in stripped["turns"]:
        body_parts.append(f"## {t['role'].upper()}\n{t['text']}\n")
    body = "\n".join(body_parts)
    full = header + body
    if len(full) > max_chars:
        head = full[: max_chars // 2]
        tail = full[-max_chars // 2:]
        elided = len(full) - max_chars
        full = head + f"\n\n...[{elided} chars elided — session exceeded prestrip cap]\n\n" + tail
    return full
