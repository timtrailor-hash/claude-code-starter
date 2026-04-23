"""Compressed-session schema + validator.

JSON-schema enforcement at write time prevents the compressed layer
from drifting into unqueryable prose sludge. Invalid entries are
rejected and logged; the run continues.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

SCHEMA_VERSION = 1

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

REQUIRED_SECTIONS = ["Goal", "Decisions", "Outcome", "Failed attempts", "Unresolved", "Links"]

VALID_OUTCOMES = {"shipped", "abandoned", "partial", "ongoing"}
VALID_MODELS = {"sonnet", "opus"}

ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$")


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


def validate(text: str) -> dict:
    """Validate a compressed-session document. Returns frontmatter on success.

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
            # YAML auto-parses ISO timestamps. Normalise to string.
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

    # Outcome value check — find the line immediately after "## Outcome"
    m = re.search(r"## Outcome\s*\n+\s*([^\n]+)", body)
    if not m:
        raise ValidationError("Outcome section has no value")
    outcome = m.group(1).strip().lower()
    if outcome not in VALID_OUTCOMES:
        raise ValidationError(f"Outcome must be one of {VALID_OUTCOMES}, got {outcome!r}")

    # Size cap
    total_tokens_rough = len(text) / 4  # 4 chars/token heuristic
    if total_tokens_rough > 2000:
        raise ValidationError(f"document exceeds 2000-token cap (~{int(total_tokens_rough)})")

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
    }
    out_path.write_text(json.dumps(schema, indent=2))
