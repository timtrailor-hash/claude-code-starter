"""Backfill runner — compress all session JSONLs with checkpointing + pacing.

Scans ~/.claude/projects/ for JSONLs, filters out subagent logs (isSidechain),
compresses + indexes each, writes to the manifest, skips already-done.

Pacing: caller-specified sessions-per-batch with sleep between. Default is
conservative; tune after first batch.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import compress, index, prestrip

DEFAULT_ROOTS = [
    Path.home() / ".claude" / "projects" / "-Users-timtrailor-Documents-Claude-code",
    Path.home() / ".claude" / "projects" / "-Users-timtrailor-code",
    Path.home() / ".claude" / "projects" / "-Users-timtrailor-code-claude-mobile",
    Path.home() / ".claude" / "projects" / "-Users-timtrailor",
]


def _discover(roots: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    out: list[Path] = []
    for r in roots:
        if not r.exists():
            continue
        for p in r.rglob("*.jsonl"):
            if p in seen:
                continue
            seen.add(p)
            # Quick pre-check: skip if obviously a subagent log (path contains subagents/)
            if "subagents" in p.parts:
                continue
            out.append(p)
    return sorted(out)


def _is_main_session(p: Path) -> bool:
    try:
        stripped = prestrip.prestrip(p)
        return not stripped["is_sidechain"] and bool(stripped["session_id"])
    except Exception:
        return False


def run(args):
    roots = [Path(r) for r in args.roots] if args.roots else DEFAULT_ROOTS
    jsonls = _discover(roots)
    if args.limit:
        jsonls = jsonls[: args.limit]
    print(f"discovered {len(jsonls)} candidate JSONLs", file=sys.stderr)

    processed = 0
    ok = 0
    skipped = 0
    invalid = 0
    errors = 0
    start = time.time()

    for jsonl in jsonls:
        try:
            if not _is_main_session(jsonl):
                skipped += 1
                continue
            result = compress.compress_session(jsonl, dry_run=args.dry_run)
            if result.get("status") == "ok":
                ok += 1
                try:
                    index.index_file(Path(result["path"]))
                except Exception as e:
                    print(f"INDEX FAIL {jsonl}: {e}", file=sys.stderr)
            elif result.get("status") == "skipped":
                skipped += 1
            elif result.get("status") == "invalid":
                invalid += 1
                print(f"INVALID {jsonl}: {result.get('reason')}", file=sys.stderr)
            elif result.get("status") == "dry_run":
                ok += 1
            processed += 1
        except Exception as e:
            errors += 1
            print(f"ERROR {jsonl}: {e}", file=sys.stderr)
        # Pacing
        if args.sleep_every and processed and processed % args.sleep_every == 0:
            print(f"  paced sleep {args.sleep}s after {processed} processed",
                  file=sys.stderr)
            time.sleep(args.sleep)
        if args.batch_size and ok and ok % args.batch_size == 0:
            break

    elapsed = time.time() - start
    print(json.dumps({
        "processed": processed,
        "ok": ok,
        "skipped": skipped,
        "invalid": invalid,
        "errors": errors,
        "elapsed_seconds": round(elapsed, 1),
    }, indent=2))


def main(argv=None):
    p = argparse.ArgumentParser(prog="dc-backfill")
    p.add_argument("--roots", nargs="*", help="override discovery roots")
    p.add_argument("--limit", type=int, default=0, help="max JSONLs to scan")
    p.add_argument("--batch-size", type=int, default=0, help="stop after N successful compressions")
    p.add_argument("--sleep-every", type=int, default=0, help="sleep every N sessions")
    p.add_argument("--sleep", type=float, default=30.0, help="sleep duration seconds")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    run(args)


if __name__ == "__main__":
    main()
