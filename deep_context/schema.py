"""Session card schema + validator (v3).

v3 architecture: minimal cards, no compression of decisions/rationale/identifiers.
Cards are navigation aids. The raw JSONL is the authoritative source; fan-out
agents read prestripped raw at task time. See deep_context/README.md.

A v3 card is a short markdown document with:
- YAML frontmatter: session_id, slug, started, ended, duration_minutes, project,
  topics_touched, files_touched, tool_call_count, outcome, card_version,
  card_generated_at.
- A single body section: ## Goal (one line, what the user asked for)
- A single body section: ## Outcome (one word)

Hard cap: 400 tokens. Validator is light — no identifier regex, no compression
fidelity check. The only failure mode is "card violates the shape" which is
rare because the shape is simple.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

CARD_VERSION = 3
# Kept for backward-compat readers. When someone imports SCHEMA_VERSION expecting
# the old semantic, they get v3's version number.
SCHEMA_VERSION = CARD_VERSION

REQUIRED_FRONTMATTER_KEYS = {
    "card_version",
    "session_id",
    "slug",
    "started",
    "ended",
    "duration_minutes",
    "project",
    "topics_touched",
    "files_touched",
    "tool_call_count",
    "outcome",
    "card_generated_at",
}

REQUIRED_SECTIONS = ["Goal", "Outcome"]

VALID_OUTCOMES = {"shipped", "abandoned", "partial", "ongoing", "unknown"}
TOKEN_CAP = 400

ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$")


class ValidationError(Exception):
    pass


def parse(text: str) -> tuple[dict, str]:
    """Split a card markdown file into (frontmatter, body)."""
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


def validate(text: str, **_ignored) -> dict:
    """Validate a v3 session card. Returns frontmatter on success.

    Kept kwarg-tolerant so legacy callers that pass source_text or thresholds
    don't break — those arguments are silently ignored in v3 (no identifier
    coverage check; raw fidelity is preserved by not compressing).
    """
    fm, body = parse(text)

    missing = REQUIRED_FRONTMATTER_KEYS - set(fm.keys())
    if missing:
        raise ValidationError(f"missing frontmatter keys: {sorted(missing)}")

    if fm["card_version"] != CARD_VERSION:
        raise ValidationError(f"card_version must be {CARD_VERSION}, got {fm['card_version']}")

    from datetime import datetime, date
    for ts_key in ("started", "ended", "card_generated_at"):
        val = fm[ts_key]
        if isinstance(val, (datetime, date)):
            fm[ts_key] = val.isoformat().replace("+00:00", "Z")
            continue
        if not isinstance(val, str) or not ISO_RE.match(val):
            raise ValidationError(f"{ts_key} must be ISO-8601 string, got {val!r}")

    for list_key in ("topics_touched", "files_touched"):
        if not isinstance(fm[list_key], list):
            raise ValidationError(f"{list_key} must be a list")

    if not isinstance(fm["duration_minutes"], (int, float)):
        raise ValidationError("duration_minutes must be numeric")
    if not isinstance(fm["tool_call_count"], int):
        raise ValidationError("tool_call_count must be int")

    outcome = str(fm.get("outcome", "")).strip().lower()
    if outcome not in VALID_OUTCOMES:
        raise ValidationError(f"outcome must be one of {VALID_OUTCOMES}, got {outcome!r}")

    for section in REQUIRED_SECTIONS:
        if f"## {section}" not in body:
            raise ValidationError(f"missing required section: ## {section}")

    if len(text) / 4 > TOKEN_CAP:
        raise ValidationError(f"card exceeds {TOKEN_CAP}-token cap")

    return fm


def write_schema_json(out_path: Path) -> None:
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Session Card (v3)",
        "type": "object",
        "version": CARD_VERSION,
        "required": sorted(REQUIRED_FRONTMATTER_KEYS),
        "properties": {
            "card_version": {"const": CARD_VERSION},
            "session_id": {"type": "string"},
            "slug": {"type": "string"},
            "started": {"type": "string", "format": "date-time"},
            "ended": {"type": "string", "format": "date-time"},
            "duration_minutes": {"type": "number", "minimum": 0},
            "project": {"type": "string"},
            "topics_touched": {"type": "array", "items": {"type": "string"}},
            "files_touched": {"type": "array", "items": {"type": "string"}},
            "tool_call_count": {"type": "integer", "minimum": 0},
            "outcome": {"enum": sorted(VALID_OUTCOMES)},
            "card_generated_at": {"type": "string", "format": "date-time"},
        },
        "required_body_sections": REQUIRED_SECTIONS,
        "valid_outcomes": sorted(VALID_OUTCOMES),
        "token_cap": TOKEN_CAP,
    }
    out_path.write_text(json.dumps(schema, indent=2))
