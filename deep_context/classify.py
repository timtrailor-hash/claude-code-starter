"""Complex-session classifier.

Routes sessions to Sonnet (bulk) or Opus (rationale-heavy) at pre-strip time.
Expected split: ~10-15% Opus.
"""
from __future__ import annotations

import re

KEYWORD_RE = re.compile(
    r"(incident|outage|rebuild|migration|rca|debug|architect|plan)",
    re.IGNORECASE,
)
RETRY_RE = re.compile(
    r"(try again|didn't work|let me try|that failed|doesn't work|not working)",
    re.IGNORECASE,
)
MEMORY_TAG_RE = re.compile(
    r"(save this|remember this|write to memory|add to memory|save to memory)",
    re.IGNORECASE,
)


def classify(stripped: dict, topics_created: list[str] | None = None,
             topics_updated: list[str] | None = None) -> tuple[str, list[str]]:
    """Return (model, flags).

    model: "sonnet" | "opus"
    flags: list of complexity flags that triggered opus routing.
    """
    flags: list[str] = []
    topics_created = topics_created or []
    topics_updated = topics_updated or []

    # Duration (minutes) — guard against None, not truthiness (0 is a valid ts)
    duration_min = 0
    if stripped.get("started_ts_ms") is not None and stripped.get("ended_ts_ms") is not None:
        duration_min = (stripped["ended_ts_ms"] - stripped["started_ts_ms"]) / 60000.0
    if duration_min > 120:
        flags.append("duration")

    if stripped.get("tool_call_count", 0) > 150:
        flags.append("activity")

    if len(stripped.get("files_touched") or []) > 10:
        flags.append("scope")

    slug = (stripped.get("slug") or "")
    if KEYWORD_RE.search(slug):
        flags.append(f"keyword:{slug}")

    retry_hits = 0
    memory_tagged = False
    for t in stripped.get("turns", []):
        if t["role"] in ("assistant", "model"):
            retry_hits += len(RETRY_RE.findall(t["text"]))
        if t["role"] in ("user", "human"):
            if MEMORY_TAG_RE.search(t["text"]):
                memory_tagged = True
    if retry_hits > 5:
        flags.append("recovery")
    if memory_tagged:
        flags.append("tagged")

    if topics_created or len(topics_updated) > 3:
        flags.append("topic_change")

    model = "opus" if flags else "sonnet"
    return model, flags
