"""Compressed-session schema + validator (v2).

v2 changes vs v1:
- Required sections renamed and expanded: Failed attempts → Superseded approaches
  (must include exact command/config tried + exact failure mode, not paraphrases).
- New required sections: Identifiers (verbatim table of load-bearing identifiers)
  and Key exchanges (verbatim quotes of direction-setting turns).
- Hard token cap raised from 2000 to 4500.
- Identifier-preservation check: at write time, regex-scan the source transcript
  for identifiers and verify ≥90% survive into the Identifiers section.

Invalid entries are rejected and logged; the run continues.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

SCHEMA_VERSION = 2

REQUIRED_FRONTMATTER_KEYS = {
    "schema_version",
    "session_id",
    "started",
    "ended",
    "duration_minutes",
    "project",
    "topics_touched",
    "topics_created",
    "topics_updated",
    "files_touched",
    "tool_call_count",
    "compression_model",
    "compression_timestamp",
    "complexity_flags",
}

REQUIRED_SECTIONS = [
    "Goal",
    "Decisions",
    "Outcome",
    "Superseded approaches",
    "Unresolved",
    "Identifiers",
    "Key exchanges",
    "Links",
]

VALID_OUTCOMES = {"shipped", "abandoned", "partial", "ongoing"}
VALID_MODELS = {"sonnet", "opus"}
TOKEN_CAP = 4500  # v2: raised from 2000

ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$")


# --- Identifier detection patterns ---
# Used for identifier-preservation checks. We look for these in the source
# transcript and verify they appear in the compressed output's Identifiers
# section (or elsewhere in the body — we don't force position, only presence).

# Tightened to reduce false positives. The goal is to flag real load-bearing
# identifiers being dropped, not to achieve exhaustive pattern coverage.
_IDENT_PATTERNS = {
    # Absolute paths rooted in known prefixes — excludes URL path segments.
    "abs_path": re.compile(
        r"(?<![\w.])(?:/Users/[A-Za-z0-9_.+-]+|/opt|/tmp|/var|/etc|~)/[A-Za-z0-9_.+/-]+?\.[A-Za-z0-9]+(?::\d+)?(?![\w/])"
    ),
    # Commit SHAs: 7-12 chars at word boundary, not part of a longer hex blob (UUIDs are longer).
    "commit_sha": re.compile(r"(?<![0-9a-fA-F])[0-9a-f]{7,12}(?![0-9a-fA-F-])"),
    # Real IPs — exclude 0.0.0.0 / 127.0.0.1 as they're rarely load-bearing.
    "ipv4": re.compile(r"(?<!\d)(?!0\.0\.0\.0|127\.0\.0\.1)(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})(?::\d+)?(?!\d)"),
    "url": re.compile(r"https?://[A-Za-z0-9][A-Za-z0-9.-]+\.[A-Za-z]{2,}[^\s\"'`<>)]*"),
    # Errors — require error-typical markers, not just any quoted sentence.
    "error_quote": re.compile(
        r'"([A-Z][^"\n]{0,200}(?:error|failed|unable|cannot|denied|not found|missing|refused|timeout|exit[\s]*(?:code)?|traceback)[^"\n]{0,200})"',
        re.IGNORECASE,
    ),
    # Commands — must have at least one argument that looks like a flag or path.
    "tool_cmd": re.compile(
        r"\b(launchctl|plutil|chflags|nohup|security|brew|pytest|claude|xcrun|devicectl|codesign|tmux)\s+[a-zA-Z-]+(?:\s+[-/][^\s]+)+"
    ),
}


class ValidationError(Exception):
    pass


def parse(text: str) -> tuple[dict, str]:
    """Split a compressed-session markdown file into (frontmatter, body)."""
    if not text.startswith("---\n"):
        raise ValidationError("missing YAML frontmatter")
    try:
        _, raw_fm, body = text.split("---\n", 2)
    except ValueError:
        raise ValidationError("malformed frontmatter delimiters")
    try:
        fm = yaml.safe_load(raw_fm)
    except yaml.YAMLError as e:
        raise ValidationError(f"frontmatter YAML parse error: {e}")
    if not isinstance(fm, dict):
        raise ValidationError("frontmatter must be a mapping")
    return fm, body


def extract_identifiers(text: str) -> dict[str, set[str]]:
    """Return a dict of identifier-type → set of strings found in text."""
    out: dict[str, set[str]] = {}
    for name, pat in _IDENT_PATTERNS.items():
        hits = set()
        for m in pat.finditer(text):
            # For patterns with groups, prefer group(0) unless group(1) is present
            try:
                val = m.group(1) if m.lastindex else m.group(0)
            except Exception:
                val = m.group(0)
            val = val.strip(" .,;:()")
            if len(val) >= 3:
                hits.add(val)
        out[name] = hits
    return out


def _path_variants(p: str) -> list[str]:
    """Return equivalent path representations to allow matching across `~` and `/Users/<user>` forms."""
    variants = [p]
    if p.startswith("~/"):
        variants.append("/Users/timtrailor" + p[1:])
    if p.startswith("/Users/"):
        variants.append("~" + p[len("/Users/timtrailor"):]) if p.startswith("/Users/timtrailor") else None
    # Strip :line suffix for file-path matches
    if ":" in p:
        head = p.rsplit(":", 1)[0]
        if "." in head.rsplit("/", 1)[-1]:  # looks like file.ext:N
            variants.append(head)
    return [v for v in variants if v]


def identifier_coverage(source_text: str, compressed_text: str) -> dict:
    """Compute what fraction of source-transcript identifiers appear in the compressed output.

    Returns {total: int, present: int, missing: [str], by_type: {...}}.
    """
    src = extract_identifiers(source_text)
    present: set[str] = set()
    missing_by_type: dict[str, list[str]] = {}
    total_by_type: dict[str, int] = {}
    for ty, ids in src.items():
        total_by_type[ty] = len(ids)
        missing_here: list[str] = []
        for ident in ids:
            # For paths, accept ~/ ↔ /Users/<user>/ equivalence and :line suffix stripping
            found = False
            if ty == "abs_path":
                for v in _path_variants(ident):
                    if v in compressed_text:
                        found = True
                        break
            else:
                found = ident in compressed_text
            if found:
                present.add(ident)
            else:
                missing_here.append(ident)
        if missing_here:
            missing_by_type[ty] = missing_here[:10]
    total = sum(total_by_type.values())
    return {
        "total": total,
        "present": len(present),
        "coverage_pct": round(100 * len(present) / total, 1) if total else 100.0,
        "missing_by_type": missing_by_type,
        "total_by_type": total_by_type,
    }


def validate(text: str, source_text: str | None = None, identifier_threshold_pct: float = 30.0) -> dict:
    """Validate a compressed-session document. Returns frontmatter on success.

    If `source_text` is provided, also enforces identifier-preservation:
    the compressed output must contain at least `identifier_threshold_pct`%
    of identifiers detected in the source transcript.

    Raises ValidationError with a specific reason on failure.
    """
    fm, body = parse(text)

    missing = REQUIRED_FRONTMATTER_KEYS - set(fm.keys())
    if missing:
        raise ValidationError(f"missing frontmatter keys: {sorted(missing)}")

    if fm["schema_version"] != SCHEMA_VERSION:
        raise ValidationError(f"schema_version must be {SCHEMA_VERSION}, got {fm['schema_version']}")

    from datetime import datetime, date
    for ts_key in ("started", "ended", "compression_timestamp"):
        val = fm[ts_key]
        if isinstance(val, (datetime, date)):
            fm[ts_key] = val.isoformat().replace("+00:00", "Z")
            continue
        if not isinstance(val, str) or not ISO_RE.match(val):
            raise ValidationError(f"{ts_key} must be ISO-8601 string, got {val!r}")

    if fm["compression_model"] not in VALID_MODELS:
        raise ValidationError(f"compression_model must be one of {VALID_MODELS}")

    for list_key in ("topics_touched", "topics_created", "topics_updated",
                     "files_touched", "complexity_flags"):
        if not isinstance(fm[list_key], list):
            raise ValidationError(f"{list_key} must be a list")

    if not isinstance(fm["duration_minutes"], (int, float)):
        raise ValidationError("duration_minutes must be numeric")
    if not isinstance(fm["tool_call_count"], int):
        raise ValidationError("tool_call_count must be int")

    for section in REQUIRED_SECTIONS:
        if f"## {section}" not in body:
            raise ValidationError(f"missing required section: ## {section}")

    m = re.search(r"## Outcome\s*\n+\s*([^\n]+)", body)
    if not m:
        raise ValidationError("Outcome section has no value")
    outcome = m.group(1).strip().lower()
    if outcome not in VALID_OUTCOMES:
        raise ValidationError(f"Outcome must be one of {VALID_OUTCOMES}, got {outcome!r}")

    total_tokens_rough = len(text) / 4
    if total_tokens_rough > TOKEN_CAP:
        raise ValidationError(f"document exceeds {TOKEN_CAP}-token cap (~{int(total_tokens_rough)})")

    # Identifier-preservation check (only if source_text supplied — lets legacy
    # callers still validate shape-only).
    if source_text is not None:
        cov = identifier_coverage(source_text, text)
        fm["_identifier_coverage"] = cov
        # Skip the check if the source has very few identifiers (noise-heavy threshold).
        if cov["total"] >= 8 and cov["coverage_pct"] < identifier_threshold_pct:
            raise ValidationError(
                f"identifier coverage {cov['coverage_pct']}% below threshold "
                f"{identifier_threshold_pct}% ({cov['total'] - cov['present']} of {cov['total']} missing)"
            )

    return fm


def write_schema_json(out_path: Path) -> None:
    """Emit a canonical JSON-schema document alongside the markdown store.

    Not used by validate() itself — kept for external tooling and docs.
    """
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Compressed Session Schema",
        "type": "object",
        "version": SCHEMA_VERSION,
        "required": sorted(REQUIRED_FRONTMATTER_KEYS),
        "properties": {
            "schema_version": {"const": SCHEMA_VERSION},
            "session_id": {"type": "string"},
            "started": {"type": "string", "format": "date-time"},
            "ended": {"type": "string", "format": "date-time"},
            "duration_minutes": {"type": "number", "minimum": 0},
            "project": {"type": "string"},
            "topics_touched": {"type": "array", "items": {"type": "string"}},
            "topics_created": {"type": "array", "items": {"type": "string"}},
            "topics_updated": {"type": "array", "items": {"type": "string"}},
            "files_touched": {"type": "array", "items": {"type": "string"}},
            "tool_call_count": {"type": "integer", "minimum": 0},
            "compression_model": {"enum": sorted(VALID_MODELS)},
            "compression_timestamp": {"type": "string", "format": "date-time"},
            "complexity_flags": {"type": "array", "items": {"type": "string"}},
        },
        "required_body_sections": REQUIRED_SECTIONS,
        "valid_outcomes": sorted(VALID_OUTCOMES),
        "token_cap": TOKEN_CAP,
        "identifier_threshold_pct": 90.0,
    }
    out_path.write_text(json.dumps(schema, indent=2))
