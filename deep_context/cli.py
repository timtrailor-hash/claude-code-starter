"""CLI entry points for the deep-context pipeline."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def cmd_compress(args):
    from . import compress
    result = compress.compress_session(Path(args.jsonl), force=args.force, dry_run=args.dry_run)
    print(json.dumps(result, indent=2))
    if result.get("status") == "invalid":
        return 2
    return 0


def cmd_index(args):
    from . import index
    if args.reindex_all:
        result = index.reindex_all()
    else:
        result = index.index_file(Path(args.md))
    print(json.dumps(result, indent=2))
    return 0


def cmd_prefilter(args):
    from . import filter as dc_filter
    result = dc_filter.prefilter(args.brief, window_days=args.window)
    if args.paths:
        result["paths"] = dc_filter.paths_for(result["candidates"])
    print(json.dumps(result, indent=2))
    return 0


def cmd_aggregate(args):
    from . import aggregate
    raw_ids = args.raw_reread.split(",") if args.raw_reread else None
    result = aggregate.write_context(
        brief=args.brief,
        fanout_path=Path(args.fanout),
        out_path=Path(args.out),
        raw_reread_session_ids=raw_ids,
    )
    print(json.dumps(result, indent=2))
    return 0


def cmd_validate(args):
    from . import schema
    text = Path(args.path).read_text()
    try:
        fm = schema.validate(text)
    except schema.ValidationError as e:
        print(json.dumps({"valid": False, "reason": str(e)}, indent=2))
        return 2
    print(json.dumps({"valid": True, "frontmatter": {k: fm[k] for k in sorted(fm)}}, indent=2))
    return 0


def cmd_emit_schema(args):
    from . import schema, compress as _c
    out = Path(args.out) if args.out else _c.SESSIONS_ROOT / "_schema.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    schema.write_schema_json(out)
    print(f"wrote {out}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="dc", description="deep-context pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("compress", help="compress one session JSONL")
    c.add_argument("jsonl")
    c.add_argument("--force", action="store_true")
    c.add_argument("--dry-run", action="store_true")
    c.set_defaults(func=cmd_compress)

    c = sub.add_parser("index", help="index a compressed-session MD into Chroma+FTS")
    c.add_argument("md", nargs="?")
    c.add_argument("--reindex-all", action="store_true")
    c.set_defaults(func=cmd_index)

    c = sub.add_parser("prefilter", help="brief → candidate session_ids")
    c.add_argument("brief")
    c.add_argument("--window", type=int, default=90)
    c.add_argument("--paths", action="store_true", help="include file paths")
    c.set_defaults(func=cmd_prefilter)

    c = sub.add_parser("aggregate", help="fan-out JSON → context.md")
    c.add_argument("--brief", required=True)
    c.add_argument("--fanout", required=True)
    c.add_argument("--out", required=True)
    c.add_argument("--raw-reread", default="", help="comma-separated session_ids re-read from raw")
    c.set_defaults(func=cmd_aggregate)

    c = sub.add_parser("validate", help="validate a compressed-session MD file")
    c.add_argument("path")
    c.set_defaults(func=cmd_validate)

    c = sub.add_parser("emit-schema", help="write JSON-schema document")
    c.add_argument("--out")
    c.set_defaults(func=cmd_emit_schema)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
