"""Precompute prestripped text for every session JSONL under ~/.claude/projects/.

v3 architecture reads ALL sessions at task time, sharded across parallel
agents. This one-time script ensures the prestripped representation is on
disk so task-time sharding is a no-model-call file-copy, not a fresh parse.

No model calls. Pure text transform. Idempotent — re-running updates only
files whose source mtime is newer than the prestripped output.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import prestrip

PRESTRIPPED_ROOT = Path.home() / "code" / "memory_server_data" / "prestripped"


def _default_roots() -> list[Path]:
    projects = Path.home() / ".claude" / "projects"
    return sorted(p for p in projects.iterdir() if p.is_dir()) if projects.exists() else []


def _discover(roots: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    out: list[Path] = []
    for r in roots:
        if not r.exists():
            continue
        for p in r.rglob("*.jsonl"):
            if p in seen or "subagents" in p.parts:
                continue
            seen.add(p)
            out.append(p)
    return sorted(out)


def _target_path(session_id: str, started_ms: int | None) -> Path:
    from datetime import datetime, timezone
    if started_ms is not None:
        dt = datetime.fromtimestamp(started_ms / 1000, tz=timezone.utc)
        year = dt.strftime("%Y")
    else:
        year = "unknown"
    return PRESTRIPPED_ROOT / year / f"{session_id}.txt"


def prestrip_one(jsonl: Path, force: bool = False) -> dict:
    try:
        stripped = prestrip.prestrip(jsonl)
    except Exception as e:
        return {"source": str(jsonl), "status": "error", "reason": f"prestrip: {e}"}

    sid = stripped.get("session_id") or jsonl.stem
    if stripped.get("is_sidechain"):
        return {"source": str(jsonl), "session_id": sid, "status": "skipped", "reason": "sidechain"}

    target = _target_path(sid, stripped.get("started_ts_ms"))
    target.parent.mkdir(parents=True, exist_ok=True)

    if not force and target.exists():
        if target.stat().st_mtime >= jsonl.stat().st_mtime:
            return {"source": str(jsonl), "session_id": sid, "status": "skipped", "reason": "up_to_date", "path": str(target)}

    text = prestrip.format_for_compression(stripped, max_chars=800_000)
    header = (
        f"SESSION_ID: {sid}\n"
        f"STARTED_MS: {stripped.get('started_ts_ms') or 'unknown'}\n"
        f"ENDED_MS: {stripped.get('ended_ts_ms') or 'unknown'}\n"
        f"PROJECT: {stripped.get('cwd') or 'unknown'}\n"
        f"SLUG: {stripped.get('slug') or 'session'}\n"
        f"TOOL_CALLS: {stripped.get('tool_call_count', 0)}\n"
        f"FILES_TOUCHED: {json.dumps(stripped.get('files_touched', [])[:50])}\n"
        f"---\n"
    )
    target.write_text(header + text)
    return {
        "source": str(jsonl),
        "session_id": sid,
        "status": "ok",
        "path": str(target),
        "raw_bytes": stripped.get("raw_bytes", 0),
        "stripped_bytes": len(header) + len(text),
    }


def run(args):
    roots = [Path(r) for r in args.roots] if args.roots else _default_roots()
    jsonls = _discover(roots)
    if args.limit:
        jsonls = jsonls[: args.limit]
    print(f"discovered {len(jsonls)} candidate JSONLs", file=sys.stderr)

    counts = {"ok": 0, "skipped": 0, "error": 0}
    start = time.time()
    for i, jsonl in enumerate(jsonls, 1):
        result = prestrip_one(jsonl, force=args.force)
        counts[result["status"]] = counts.get(result["status"], 0) + 1
        if result["status"] == "error":
            print(f"ERROR {jsonl}: {result.get('reason')}", file=sys.stderr)
        if i % 50 == 0:
            print(f"  processed {i}/{len(jsonls)} ({int(time.time()-start)}s)", file=sys.stderr)

    elapsed = time.time() - start
    print(json.dumps({
        "total": len(jsonls),
        "elapsed_seconds": round(elapsed, 1),
        **counts,
        "output_dir": str(PRESTRIPPED_ROOT),
    }, indent=2))


def main(argv=None):
    p = argparse.ArgumentParser(prog="dc-prestrip-all")
    p.add_argument("--roots", nargs="*")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--force", action="store_true", help="regenerate even if up-to-date")
    args = p.parse_args(argv)
    run(args)


if __name__ == "__main__":
    main()
