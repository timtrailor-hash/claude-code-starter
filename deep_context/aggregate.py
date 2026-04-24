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


def _dedupe_claims(claims: list) -> list[dict]:
    """claims: list of {claim: str, source: str} or plain strings. Merge dups."""
    buckets: dict[str, dict] = {}
    for c in claims:
        if isinstance(c, str):
            c = {"claim": c, "source": "?"}
        elif not isinstance(c, dict) or "claim" not in c:
            continue
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


def _invoke_synthesizer(brief: str, structured_md: str, fanout_path: Path,
                         model: str = "opus", timeout: int = 900) -> str | None:
    """Run a synthesis pass: feed the brief + the deduplicated claims to an Opus
    agent that produces a coherent root-cause narrative with named cross-cutting
    patterns. The fan-out dedup is the raw material; synthesis is the deliverable.

    Returns the synthesized markdown or None on failure.
    """
    synth_prompt = f"""You are the SYNTHESIS stage of /deep-context. A fan-out of parallel agents has produced a deduplicated claim set. Your job: turn it into a coherent root-cause synthesis that is directly actionable for a fresh session.

BRIEF:
{brief}

DEDUPLICATED FAN-OUT (structured markdown with every claim preserved and provenance tagged):
<<<FANOUT
{structured_md}
FANOUT>>>

Produce a single markdown document with this structure:

# Context for: {brief[:80]}...

## Verdict on the brief's premise
(2-4 sentences. Where the brief is right, where it needs correcting, the actual shape of the problem. Be direct.)

## Root-cause synthesis — cross-cutting patterns
(5-10 numbered patterns. Each: a memorable named insight, evidence (cite claims and session IDs that establish it), and why fixes keep failing because of it.)

## Architecture as it actually is
(Specific file:line, routes, hook names, flags. Distinguish layers if permission behaviour differs across them.)

## Past fix timeline (chronological)
(Commits with SHAs grouped into generations. What was tried, why it failed.)

## Unresolved threads and contradictions
(Flagged gaps, agent disagreements, drift between memory and current state.)

## Files likely to touch
(Deduplicated with line ranges.)

## Methodology note
(One paragraph on how this was produced.)

## Citations
_Provenance: [topic:<path>] | [session:<id>] | [code:<path>:<line>] | [settings:<path>]_

QUALITY RULES:
- Be direct. Correct the brief where evidence contradicts it.
- Name patterns usefully and specifically.
- Preserve every load-bearing commit SHA, file:line, error string, session ID.
- Cap at 12K tokens (synthesis is the deliverable, not the raw source).

Output only the document. No preamble."""

    env = os.environ.copy()
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + env.get("PATH", "")
    env.setdefault("HOME", str(Path.home()))
    claude_bin = "/opt/homebrew/bin/claude"
    if not Path(claude_bin).exists():
        claude_bin = str(Path.home() / ".local" / "bin" / "claude")
    try:
        proc = subprocess.run(
            [claude_bin, "--print", "--model", model, "--tools", "",
             "--disable-slash-commands"],
            input=synth_prompt, env=env, capture_output=True, text=True, timeout=timeout,
        )
        if proc.returncode != 0:
            return None
        out = proc.stdout.strip()
        if out.startswith("```"):
            out = "\n".join(out.splitlines()[1:-1])
        return out if out else None
    except Exception:
        return None


def aggregate(brief: str,
              fanout_path: Path,
              raw_reread_session_ids: list[str] | None = None,
              max_context_tokens: int = 50_000,
              synthesise: bool = False,
              synthesise_model: str = "opus") -> dict:
    """Build context.md.

    fanout_path points to a JSON file with shape:
    {
      "topics":    {"summary": str, "claims": [...], "unresolved": [...], "files_likely": [...]},
      "code":      {"summary": str, "claims": [...], "files_likely": [...]},
      "sessions":  [                                 # v3: list, one entry per shard
        {"summary": str, "claims": [...], "unresolved": [...]},
        ...
      ]
    }

    Legacy v1/v2 form (sessions as a single object) is also accepted.

    Returns: {"context": str, "stats": {...}}.
    """
    with fanout_path.open() as f:
        fanout = json.load(f)

    sections = {"topics": [], "sessions": [], "code": [], "unresolved": [], "files": []}

    # Topics + code — single agents
    for layer in ("topics", "code"):
        data = fanout.get(layer) or {}
        claims = data.get("claims") or []
        sections[layer] = _dedupe_claims(claims)

    # Sessions — v3 accepts a list of shard outputs; v1/v2 kept as single dict
    sessions_raw = fanout.get("sessions") or {}
    session_shards = sessions_raw if isinstance(sessions_raw, list) else [sessions_raw]
    all_session_claims: list[dict] = []
    all_session_unresolved: list[dict] = []
    session_summaries: list[str] = []
    for sh in session_shards:
        if not isinstance(sh, dict):
            continue
        if sh.get("summary"):
            session_summaries.append(sh["summary"].strip())
        all_session_claims.extend(sh.get("claims") or [])
        for u in sh.get("unresolved") or []:
            if isinstance(u, dict):
                all_session_unresolved.append({"claim": u.get("claim", str(u)),
                                                "sources": [u.get("source", "sessions")]})
            else:
                all_session_unresolved.append({"claim": str(u), "sources": ["sessions"]})
    sections["sessions"] = _dedupe_claims(all_session_claims)

    # Unresolved + files from any layer
    for u in all_session_unresolved:
        sections["unresolved"].append(u)
    topics_data = fanout.get("topics") or {}
    for u in topics_data.get("unresolved") or []:
        if isinstance(u, dict):
            sections["unresolved"].append({"claim": u.get("claim", str(u)),
                                            "sources": [u.get("source", "topics")]})
        else:
            sections["unresolved"].append({"claim": str(u), "sources": ["topics"]})
    for layer in ("topics", "code"):
        data = fanout.get(layer) or {}
        for ff in data.get("files_likely") or []:
            sections["files"].append({"claim": str(ff), "sources": [layer]})

    # v2-style raw-reread is vestigial in v3 (session agents already read raw).
    # Keep the hook for back-compat: if the caller supplies flagged IDs, run it.
    raw_claims: list[dict] = []
    for sid in (raw_reread_session_ids or []):
        sid = sid.strip()
        if not sid:
            continue
        claims = _extract_from_raw(brief, sid)
        if claims:
            raw_claims.extend(claims)
    if raw_claims:
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
    lines.append("_From raw session transcripts read across shards — how we got here, what we tried, what failed._")
    lines.append("")
    if session_summaries:
        lines.append(" ".join(session_summaries))
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

    # Rough token cap enforcement (raw deduplicated form)
    rough_tokens = int(len(context) / 4)
    truncated = False
    if rough_tokens > max_context_tokens:
        target_chars = max_context_tokens * 4
        context = context[:target_chars] + f"\n\n_[truncated at {max_context_tokens} tokens]_\n"
        truncated = True

    synthesised_context: str | None = None
    if synthesise:
        synthesised_context = _invoke_synthesizer(brief, context, fanout_path, model=synthesise_model)

    stats = {
        "claim_counts": {k: len(v) for k, v in sections.items()},
        "rough_tokens": rough_tokens,
        "truncated": truncated,
        "raw_reread_count": len(raw_reread_session_ids or []),
        "synthesised": synthesised_context is not None,
    }
    return {"context": context, "synthesised_context": synthesised_context, "stats": stats}


def write_context(brief: str, fanout_path: Path, out_path: Path,
                  raw_reread_session_ids: list[str] | None = None,
                  synthesise: bool = False, synthesise_model: str = "opus") -> dict:
    result = aggregate(brief, fanout_path, raw_reread_session_ids,
                       synthesise=synthesise, synthesise_model=synthesise_model)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # When synthesise is True, the synthesised file is the primary deliverable.
    # Raw dedup is still written alongside as `<name>.raw.md` for audit trail.
    if result.get("synthesised_context"):
        out_path.write_text(result["synthesised_context"])
        raw_path = out_path.with_suffix(".raw.md")
        raw_path.write_text(result["context"])
        return {"path": str(out_path), "raw_path": str(raw_path), **result["stats"]}
    else:
        out_path.write_text(result["context"])
        return {"path": str(out_path), **result["stats"]}
