"""Basic sanity tests — not a replacement for end-to-end."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from deep_context import schema, prestrip, classify


def test_schema_rejects_missing_frontmatter():
    try:
        schema.validate("no frontmatter here")
    except schema.ValidationError as e:
        assert "frontmatter" in str(e).lower()
        return
    raise AssertionError("expected ValidationError")


def test_schema_rejects_missing_sections():
    bad = (
        "---\n"
        "schema_version: 1\n"
        "session_id: abc\n"
        "started: 2026-04-23T12:00:00Z\n"
        "ended: 2026-04-23T12:30:00Z\n"
        "duration_minutes: 30\n"
        "project: test\n"
        "topics_touched: []\n"
        "topics_created: []\n"
        "topics_updated: []\n"
        "files_touched: []\n"
        "tool_call_count: 0\n"
        "compression_model: sonnet\n"
        "compression_timestamp: 2026-04-23T13:00:00Z\n"
        "complexity_flags: []\n"
        "---\n"
        "body with no sections\n"
    )
    try:
        schema.validate(bad)
    except schema.ValidationError as e:
        assert "section" in str(e).lower()
        return
    raise AssertionError("expected ValidationError")


def test_schema_accepts_valid():
    good = (
        "---\n"
        "schema_version: 1\n"
        "session_id: abc\n"
        "started: 2026-04-23T12:00:00Z\n"
        "ended: 2026-04-23T12:30:00Z\n"
        "duration_minutes: 30\n"
        "project: test\n"
        "topics_touched: [test]\n"
        "topics_created: []\n"
        "topics_updated: []\n"
        "files_touched: []\n"
        "tool_call_count: 5\n"
        "compression_model: sonnet\n"
        "compression_timestamp: 2026-04-23T13:00:00Z\n"
        "complexity_flags: []\n"
        "---\n"
        "## Goal\nTest.\n\n"
        "## Decisions\n- none\n\n"
        "## Outcome\nshipped\n\n"
        "## Failed attempts\n- none\n\n"
        "## Unresolved\n- none\n\n"
        "## Links\n- none\n"
    )
    fm = schema.validate(good)
    assert fm["session_id"] == "abc"


def test_classify_simple():
    stripped = {
        "session_id": "a", "cwd": "/x", "slug": "simple",
        "is_sidechain": False, "started_ts_ms": 1000, "ended_ts_ms": 60_000,
        "tool_call_count": 5, "files_touched": ["/x/y.py"], "turns": [
            {"role": "user", "text": "hi"},
            {"role": "assistant", "text": "done"},
        ],
        "raw_bytes": 100, "stripped_bytes": 30,
    }
    model, flags = classify.classify(stripped)
    assert model == "sonnet"
    assert flags == []


def test_classify_complex_by_duration():
    stripped = {
        "session_id": "a", "cwd": "/x", "slug": "simple",
        "is_sidechain": False, "started_ts_ms": 0, "ended_ts_ms": 3 * 3600 * 1000,
        "tool_call_count": 5, "files_touched": [], "turns": [],
        "raw_bytes": 0, "stripped_bytes": 0,
    }
    model, flags = classify.classify(stripped)
    assert model == "opus"
    assert "duration" in flags


def test_classify_complex_by_keyword():
    stripped = {
        "session_id": "a", "cwd": "/x", "slug": "printer-incident-rca",
        "is_sidechain": False, "started_ts_ms": 0, "ended_ts_ms": 60_000,
        "tool_call_count": 5, "files_touched": [], "turns": [],
        "raw_bytes": 0, "stripped_bytes": 0,
    }
    model, flags = classify.classify(stripped)
    assert model == "opus"
    assert any(f.startswith("keyword") for f in flags)


def test_prestrip_handles_empty(tmp_path=None):
    tmp_path = tmp_path or Path(tempfile.mkdtemp())
    empty = tmp_path / "empty.jsonl"
    empty.write_text("")
    result = prestrip.prestrip(empty)
    assert result["turns"] == []


if __name__ == "__main__":
    test_schema_rejects_missing_frontmatter()
    test_schema_rejects_missing_sections()
    test_schema_accepts_valid()
    test_classify_simple()
    test_classify_complex_by_duration()
    test_classify_complex_by_keyword()
    test_prestrip_handles_empty()
    print("all basic tests passed")
