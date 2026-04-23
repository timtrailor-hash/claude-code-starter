"""Aggregator: assemble the task-specific context.md from fan-out outputs.

Input: the brief, fan-out agent outputs (JSON), and optional raw re-reads.
Output: a single context.md with citations.

v2: the raw-reread stage is no longer a stub. For each flagged session,
the aggregator invokes Claude with the pre-stripped transcript and extracts
brief-relevant claims that the compressed summary may have missed.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

from . import prestrip, filter as dc_filter


def _norm_claim(c: str) -> str:
    return re.sub(r"\s+", " ", c.strip()).rstrip(".").lower()


def _dedupe_claims(claims: list[dict]) -> list[dict]:
    """claims: [{claim: str, source: str}]. Merge duplicates, preserve multiple sources."""
    buckets: dict[str, dict] = {}
    for c in claims:
        key = _norm_claim(c["claim"])
        if not key:
            continue
        if key in buckets:
            sources = buckets[key].get("sources") or [buckets[key].get("source")]
            if c.get("source") not in sources:
                sources.append(c.get("source"))
            buckets[key]["sources"] = sources
        else:
            buckets[key] = {"claim": c["claim"].strip(), "sources": [c.get("source", "?")]}
    return list(buckets.values())


def _cite(sources: list[str]) -> str:
    return " ".join(f"[{s}]" for s in sources if s)


def _find_raw_jsonl(session_id: str) -> Path | None:
    """Find the raw JSONL for a session id under ~/.claude/projects/."""
    projects = Path.home() / ".claude" / "projects"
    if not projects.exists():
        return None
    for cand in projects.rglob(f"{session_id}*.jsonl"):
        if cand.is_file():
            return cand
    # Try first-8 prefix match if full id is given
    if len(session_id) >= 8:
        short = session_id[:8]
        for cand in projects.rglob(f"{short}*.jsonl"):
            if cand.is_file():
                return cand
    return None


def _extract_from_raw(brief: str, session_id: str, max_claims: int = 10) -> list[dict]:
    """Targeted retrieval from a raw session JSONL.

    Pre-strips the transcript, asks Claude for claims that are both
    relevant to the brief AND likely missing from a short compressed summary.
    Returns [{claim, source}] tagged with raw:<id>.
    """
    raw = _find_raw_jsonl(session_id)
    if not raw:
        return []
    try:
        stripped = prestrip.prestrip(raw)
        transcript = prestrip.format_for_compression(stripped, max_chars=300_000)
    except Exception:
        return []

    # Invoke the Claude CLI — reuse the compress._run_claude-style env to pick up
    # whichever auth the parent session has.
    prompt = (
        f"You are extracting claims from a session transcript that are RELEVANT to a specific brief.\n\n"
        f"BRIEF: {brief}\n\n"
        f"Read the transcript. Extract up to {max_claims} claims that:\n"
        f"1. Are directly relevant to the brief.\n"
        f"2. Are SPECIFIC — include exact identifiers (file paths, line numbers, commit SHAs, error strings, commands).\n"
        f"3. Are load-bearing — a future session doing this work would genuinely want them.\n\n"
        f"Return ONLY a JSON array: [{{\"claim\": \"...\"}}, ...]. No preamble, no explanation.\n\n"
        f"TRANSCRIPT:\n{transcript}\n"
    )

    env = os.environ.copy()
    env.pop("ANTHROPIC_API_KEY", None)
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + env.get("PATH", "")
    env.setdefault("HOME", str(Path.home()))
    claude_bin = "/opt/homebrew/bin/claude"
    if not Path(claude_bin).exists():
        claude_bin = str(Path.home() / ".local" / "bin" / "claude")
    try:
        proc = subprocess.run(
            [claude_bin, "--print", "--model", "sonnet", "--tools", "",
             "--disable-slash-commands"],
            input=prompt, env=env, capture_output=True, text=True, timeout=300,
        )
        if proc.returncode != 0:
            return []
        out = proc.stdout.strip()
    except Exception:
        return []

    # Strip fences and find JSON array
    if out.startswith("```"):
        out = "\n".join(out.splitlines()[1:-1])
    start = out.find("[")
    end = out.rfind("]") + 1
    if start == -1 or end <= start:
        return []
    try:
        items = json.loads(out[start:end])
    except Exception:
        return []

    short = session_id[:8]
    return [
        {"claim": it["claim"].strip(), "source": f"raw:{short}"}
        for it in items
        if isinstance(it, dict) and it.get("claim")
    ][:max_claims]


def aggregate(brief: str,
              fanout_path: Path,
              raw_reread_session_ids: list[str] | None = None,
              max_context_tokens: int = 50_000) -> dict:
    """Build context.md.

    fanout_path points to a JSON file with shape:
    {
      "topics": {"summary": str, "claims": [{claim, source}], "flagged_sessions": []},
      "sessions": {"summary": str, "claims": [{claim, source}], "flagged_sessions": []},
      "code": {"summary": str, "claims": [{claim, source}]}
    }

    Returns: {"context": str, "stats": {...}}.
    """
    with fanout_path.open() as f:
        fanout = json.load(f)

    sections = {"topics": [], "sessions": [], "code": [], "unresolved": [], "files": []}

    for layer in ("topics", "sessions", "code"):
        data = fanout.get(layer) or {}
        claims = data.get("claims") or []
        sections[layer] = _dedupe_claims(claims)

    # Collect unresolved + files if fanout includes them separately
    for layer in ("sessions", "topics"):
        data = fanout.get(layer) or {}
        unresolved = data.get("unresolved") or []
        for u in unresolved:
            sections["unresolved"].append({"claim": u.get("claim", str(u)),
                                            "sources": [u.get("source", layer)]})
        files = data.get("files_likely") or []
        for ff in files:
            sections["files"].append({"claim": str(ff), "sources": [layer]})

    # v2: real raw-reread — targeted extraction from the raw JSONL for each
    # flagged session. The compressed summary is lossy by design; this stage
    # recovers specifics (error strings, exact commands, line-level detail)
    # when the fan-out flagged a session as worth deeper reading.
    raw_claims: list[dict] = []
    for sid in (raw_reread_session_ids or []):
        sid = sid.strip()
        if not sid:
            continue
        claims = _extract_from_raw(brief, sid)
        if claims:
            raw_claims.extend(claims)
        else:
            # Fall back to a placeholder so the citation link is at least present
            raw_claims.append({
                "claim": f"Raw transcript re-read for session {sid} did not surface additional claims.",
                "source": f"raw:{sid[:8]}",
            })
    sections["sessions"] += _dedupe_claims(raw_claims)

    # Assemble markdown
    lines: list[str] = []
    lines.append(f"# Context for: {brief}")
    lines.append("")
    lines.append("_Generated by /deep-context. Claims tagged with provenance._")
    lines.append("")

    lines.append("## Recent state")
    lines.append("_From curated topic files — the canonical current truth._")
    lines.append("")
    if fanout.get("topics", {}).get("summary"):
        lines.append(fanout["topics"]["summary"].strip())
        lines.append("")
    for c in sections["topics"]:
        lines.append(f"- {c['claim']} {_cite(c['sources'])}")
    lines.append("")

    lines.append("## Relevant history")
    lines.append("_From compressed session summaries + raw re-reads — how we got here, what we tried, what failed._")
    lines.append("")
    if fanout.get("sessions", {}).get("summary"):
        lines.append(fanout["sessions"]["summary"].strip())
        lines.append("")
    for c in sections["sessions"]:
        lines.append(f"- {c['claim']} {_cite(c['sources'])}")
    lines.append("")

    lines.append("## Unresolved threads")
    if sections["unresolved"]:
        for c in sections["unresolved"]:
            lines.append(f"- {c['claim']} {_cite(c['sources'])}")
    else:
        lines.append("_None surfaced by fan-out._")
    lines.append("")

    lines.append("## Files likely to touch")
    if sections["files"] or sections["code"]:
        for c in sections["files"]:
            lines.append(f"- {c['claim']} {_cite(c['sources'])}")
        if fanout.get("code", {}).get("summary"):
            lines.append("")
            lines.append(fanout["code"]["summary"].strip())
        for c in sections["code"]:
            lines.append(f"- {c['claim']} {_cite(c['sources'])}")
    else:
        lines.append("_No code-layer output supplied._")
    lines.append("")

    lines.append("## Citations")
    lines.append("_Provenance tags used above:_ `topic:<path>` | `session:<id>` | `raw:<id>` | `code:<path>`")
    lines.append("")

    context = "\n".join(lines).rstrip() + "\n"

    # Rough token cap enforcement
    rough_tokens = int(len(context) / 4)
    truncated = False
    if rough_tokens > max_context_tokens:
        # Truncate by character proportion
        target_chars = max_context_tokens * 4
        context = context[:target_chars] + f"\n\n_[truncated at {max_context_tokens} tokens]_\n"
        truncated = True

    stats = {
        "claim_counts": {k: len(v) for k, v in sections.items()},
        "rough_tokens": rough_tokens,
        "truncated": truncated,
        "raw_reread_count": len(raw_reread_session_ids or []),
    }
    return {"context": context, "stats": stats}


def write_context(brief: str, fanout_path: Path, out_path: Path,
                  raw_reread_session_ids: list[str] | None = None) -> dict:
    result = aggregate(brief, fanout_path, raw_reread_session_ids)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(result["context"])
    return {"path": str(out_path), **result["stats"]}
