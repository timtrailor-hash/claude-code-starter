"""Compress a single session JSONL into a validated compressed-session markdown file.

Invokes the Claude CLI in non-interactive mode. By default uses subscription
OAuth inherited from the parent Claude Code session; set ANTHROPIC_API_KEY
in the environment to use API-key auth instead (routes compression to paid
API tokens).
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from . import prestrip, classify, schema  # noqa: E402


def _deep_context_home() -> Path:
    return Path(os.environ.get("DEEP_CONTEXT_HOME") or (Path.home() / ".claude" / "deep-context"))


def _env_for_cli() -> dict:
    """Env for claude CLI subprocess.

    Inherits the parent's env so subscription OAuth propagates from an
    authenticated Claude Code session or a GUI login. Keeps CLAUDECODE /
    CLAUDE_CODE_ENTRYPOINT so the CLI recognises the parent context.

    If you want compression to go through the paid API instead of your
    subscription, set ANTHROPIC_API_KEY in the environment before running.
    The CLI will pick it up automatically.
    """
    env = os.environ.copy()
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + env.get("PATH", "")
    env.setdefault("HOME", str(Path.home()))
    return env


PROMPT_PATH = Path(__file__).parent / "prompts" / "compress.md"
SESSIONS_ROOT = _deep_context_home() / "sessions"
MANIFEST_PATH = SESSIONS_ROOT / "_manifest.jsonl"

SLUG_RE = re.compile(r"[^a-z0-9]+")


def _iso(ms: int | None) -> str:
    if not ms:
        return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _slugify(s: str) -> str:
    return SLUG_RE.sub("-", (s or "").lower()).strip("-") or "session"


def _project_name(cwd: str | None) -> str:
    if not cwd:
        return "unknown"
    parts = Path(cwd).parts
    return parts[-1] if parts else "unknown"


def _target_path(started_iso: str, slug: str, session_id: str) -> Path:
    dt = datetime.fromisoformat(started_iso.replace("Z", "+00:00"))
    year = dt.strftime("%Y")
    stamp = dt.strftime("%Y-%m-%d-%H%M")
    short_id = (session_id or "unknown")[:8]
    name = f"{stamp}-{_slugify(slug)[:40]}-{short_id}.md"
    return SESSIONS_ROOT / year / name


def _already_compressed(session_id: str) -> Path | None:
    if not MANIFEST_PATH.exists():
        return None
    with MANIFEST_PATH.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                import json
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("session_id") == session_id and rec.get("status") == "ok":
                p = rec.get("path")
                return Path(p) if p else None
    return None


def _render_trivial(meta: dict, stripped: dict) -> str:
    """Build a compressed-session entry for a trivially short session.

    No model call. Captures what little content there is as the Goal, all
    other sections as `- none`. Deliberately bland but schema-valid so the
    session remains discoverable via session_id and date.
    """
    import yaml  # local import to keep top-of-file slim
    # Meta needs to serialise cleanly. Convert to primitives only.
    fm = {k: v for k, v in meta.items()}
    if fm["compression_model"] == "opus":
        fm["compression_model"] = "sonnet"  # trivial short-circuit forces sonnet marker
    fm["complexity_flags"] = list(fm.get("complexity_flags", [])) + ["trivial"]
    # Fill the topics_* fields the model would normally produce.
    fm.setdefault("topics_touched", [])
    fm.setdefault("topics_created", [])
    fm.setdefault("topics_updated", [])

    first_user = next(
        (t["text"] for t in stripped["turns"] if t["role"] in ("user", "human")),
        "",
    )
    goal = (first_user[:200].replace("\n", " ").strip() or "Trivial session (no user turn).")
    body = (
        f"## Goal\n{goal}\n\n"
        "## Decisions\n- none\n\n"
        "## Outcome\nshipped\n\n"
        "## Failed attempts\n- none\n\n"
        "## Unresolved\n- none\n\n"
        "## Links\n"
        f"- sessions: [{meta['session_id']}]\n"
        "- topics: []\n"
        "- prs: []\n"
    )
    fm_yaml = yaml.safe_dump(fm, default_flow_style=False, sort_keys=False)
    return f"---\n{fm_yaml}---\n{body}"


def _append_manifest(entry: dict) -> None:
    import json
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST_PATH.open("a") as f:
        f.write(json.dumps(entry) + "\n")


CLAUDE_BIN_CANDIDATES = (
    "/opt/homebrew/bin/claude",
    "/usr/local/bin/claude",
    str(Path.home() / ".local" / "bin" / "claude"),
)


def _claude_bin() -> str:
    import shutil
    on_path = shutil.which("claude")
    if on_path:
        return on_path
    for c in CLAUDE_BIN_CANDIDATES:
        if Path(c).exists():
            return c
    return "claude"


def _run_claude(model: str, prompt: str, transcript: str, timeout: int = 600) -> str:
    """Invoke Claude CLI in non-interactive mode.

    Uses whatever auth the parent session has: subscription OAuth by default,
    API key if ANTHROPIC_API_KEY is set. --bare is deliberately NOT used — it
    disables keychain reads and forces API-key auth, which breaks subscription
    compression.

    --tools "" disables all tools so the model only emits text.
    --disable-slash-commands blocks accidental skill invocation.
    """
    env = _env_for_cli()
    full_prompt = prompt + "\n\n---\n\nTRANSCRIPT:\n\n" + transcript
    proc = subprocess.run(
        [
            _claude_bin(),
            "--print",
            "--model", model,
            "--tools", "",
            "--disable-slash-commands",
        ],
        input=full_prompt,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"claude CLI exit={proc.returncode}\n"
            f"STDOUT: {proc.stdout[:500]}\n"
            f"STDERR: {proc.stderr[:2000]}"
        )
    return proc.stdout


def compress_session(jsonl_path: Path, force: bool = False, dry_run: bool = False) -> dict:
    """Compress one session JSONL to a validated markdown file.

    Returns: manifest entry dict.
    """
    stripped = prestrip.prestrip(jsonl_path)
    session_id = stripped["session_id"] or jsonl_path.stem
    if stripped["is_sidechain"]:
        return {
            "session_id": session_id,
            "status": "skipped",
            "reason": "sidechain",
            "path": str(jsonl_path),
        }

    if not force:
        existing = _already_compressed(session_id)
        if existing and existing.exists():
            return {
                "session_id": session_id,
                "status": "skipped",
                "reason": "already_compressed",
                "path": str(existing),
            }

    started_iso = _iso(stripped["started_ts_ms"])
    ended_iso = _iso(stripped["ended_ts_ms"])
    duration_minutes = 0.0
    if stripped["started_ts_ms"] and stripped["ended_ts_ms"]:
        duration_minutes = round(
            (stripped["ended_ts_ms"] - stripped["started_ts_ms"]) / 60000.0, 2
        )

    model, flags = classify.classify(stripped)

    meta = {
        "schema_version": schema.SCHEMA_VERSION,
        "session_id": session_id,
        "started": started_iso,
        "ended": ended_iso,
        "duration_minutes": duration_minutes,
        "project": _project_name(stripped["cwd"]),
        "files_touched": stripped["files_touched"],
        "tool_call_count": stripped["tool_call_count"],
        "compression_model": model,
        "compression_timestamp": datetime.now(timezone.utc)
        .isoformat(timespec="seconds").replace("+00:00", "Z"),
        "complexity_flags": flags,
    }

    target = _target_path(started_iso, stripped["slug"] or "session", session_id)

    if dry_run:
        return {
            "session_id": session_id,
            "status": "dry_run",
            "model": model,
            "flags": flags,
            "path": str(target),
            "stripped_bytes": stripped["stripped_bytes"],
        }

    # Trivial session short-circuit — skip model call for 1-turn / tiny sessions.
    # These are task-title generators, connectivity pings, etc. The compressed
    # entry carries the session_id so it's still discoverable, but we don't
    # pay tokens or risk schema errors on content that can't be summarised.
    if stripped["stripped_bytes"] < 500 or len(stripped["turns"]) < 3:
        trivial = _render_trivial(meta, stripped)
        try:
            schema.validate(trivial)
        except schema.ValidationError:
            pass  # fall through to normal compression
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(trivial)
            entry = {
                "session_id": session_id, "status": "ok", "model": "trivial",
                "flags": ["trivial"], "path": str(target),
                "source_jsonl": str(jsonl_path),
                "duration_minutes": duration_minutes,
                "stripped_bytes": stripped["stripped_bytes"],
                "raw_bytes": stripped["raw_bytes"],
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            _append_manifest(entry)
            return entry

    prompt = PROMPT_PATH.read_text()
    # Inject the "as provided" metadata directly into the prompt to reduce hallucination
    meta_block = "\n".join(f"- {k}: {v}" for k, v in meta.items())
    prompt = prompt + f"\n\n## Metadata to copy verbatim into frontmatter\n{meta_block}\n"
    transcript = prestrip.format_for_compression(stripped)

    out = _run_claude(model, prompt, transcript)
    out = out.strip()
    # Strip accidental code-fence wrapper
    if out.startswith("```") and out.endswith("```"):
        lines = out.splitlines()
        out = "\n".join(lines[1:-1]).strip()
    # Find the real frontmatter by locating `---\n*schema_version:` — works
    # whether or not there's preamble, and skips spurious leading `---` blocks.
    sv_idx = out.find("schema_version:")
    if sv_idx != -1:
        # Back up to the preceding `---\n`
        prefix = out[:sv_idx]
        delim = prefix.rfind("---")
        if delim != -1:
            out = out[delim:]
    debug_path = target.with_suffix(".raw.txt")
    out = out.strip() + "\n"

    try:
        fm = schema.validate(out)
    except schema.ValidationError as e:
        # Preserve raw model output so we can see what went wrong
        target.parent.mkdir(parents=True, exist_ok=True)
        debug_path.write_text(out)
        entry = {
            "session_id": session_id,
            "status": "invalid",
            "reason": str(e),
            "model": model,
            "path": str(target),
            "raw_output": str(debug_path),
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        _append_manifest(entry)
        return entry

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(out)

    entry = {
        "session_id": session_id,
        "status": "ok",
        "model": model,
        "flags": flags,
        "path": str(target),
        "source_jsonl": str(jsonl_path),
        "duration_minutes": duration_minutes,
        "stripped_bytes": stripped["stripped_bytes"],
        "raw_bytes": stripped["raw_bytes"],
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    _append_manifest(entry)
    return entry
