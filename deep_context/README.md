# deep_context — pre-task context assembly pipeline

Compresses past Claude Code sessions into structured markdown summaries, then assembles a task-specific `context.md` by fanning out over topics + compressed sessions + code before a high-stakes task starts. The generated file is what you pass to a fresh sub-session instead of hoping the default context load covers everything.

Pairs with the `/deep-context` skill at `.claude/skills/deep-context/SKILL.md`.

## Why this exists

Default context loading is fine for small tasks. For architectural changes, migrations, or anything with blast radius, relevant context is scattered across topic files, hundreds of past sessions, and the codebase. Semantic and FTS search help, but they rely on the model formulating the right query mid-task. This package does the search ahead of time — once, deliberately, with citations — and hands the result to the session that's going to do the work.

## Architecture

Three layers. The pipeline respects precedence between them when they conflict.

```
1. Topics (memory/topics/*.md) — CURATED CURRENT TRUTH. Wins.
2. Compressed sessions — one markdown file per closed session. RECALL/ROUTING.
3. Raw session JSONL (~/.claude/projects/*.jsonl) — ARBITRATION on conflict.
```

Derived indexes (ChromaDB, FTS5) are regenerated from source, never authoritative.

Pipeline stages: **prefilter** (narrow ~hundreds of sessions → ~20-80 candidates) → **fan-out** (three parallel agents read topics / compressed sessions / code) → **raw re-read** (only for sessions the fan-out flagged) → **aggregate** (deduplicate, cite, cap at 50K tokens) → **handoff** (fresh sub-session with brief + context.md).

## Install

```bash
cd claude-code-starter
pip install chromadb pyyaml
```

Python 3.11+. Requires a working `claude` CLI on your PATH.

## Configure

One environment variable. Default works for most:

```bash
export DEEP_CONTEXT_HOME="$HOME/.claude/deep-context"  # default
```

The compressed markdown corpus, the manifest, the FTS5 database, and the ChromaDB collection all live under this directory.

## Run the backfill

First-time setup. Compresses every non-sidechain session under `~/.claude/projects/`.

```bash
python3 -m deep_context.backfill --sleep-every 10 --sleep 90
```

Paced to avoid hammering your subscription quota. Resumable — already-compressed sessions are skipped via the manifest. Expect 100-150 sessions per hour depending on session size.

Useful flags:
- `--limit 20` — cap to N sessions for a small pilot run.
- `--dry-run` — classify + plan but don't call the model.
- `--roots /path/to/project_dir` — restrict to specific project subdirs.

## Invoke /deep-context

Once the backfill has produced content, invoke the skill with a specific brief:

```
/deep-context "Investigate why the nightly ETL regressed after commit abc123, propose a fix"
```

The skill runs the full pipeline, writes `context.md` to `/tmp/dc_<runid>/`, and hands off to a fresh sub-session.

## Compressed-session schema

```yaml
---
schema_version: 1
session_id: <uuid>
started: <ISO-8601>
ended: <ISO-8601>
duration_minutes: <number>
project: <string>
topics_touched: [<tag>]
topics_created: [<path>]
topics_updated: [<path>]
files_touched: [<absolute path>]
tool_call_count: <int>
compression_model: sonnet | opus
compression_timestamp: <ISO-8601>
complexity_flags: [<tag>]
---
## Goal
<one line>

## Decisions
- **<decision>**: <rationale>

## Outcome
shipped | abandoned | partial | ongoing

## Failed attempts
- **<what>**: <why it failed>

## Unresolved
- <thing flagged for later>

## Links
- sessions: [<uuid>]
- topics: [<path>]
- prs: [<url>]
```

Target 500-1500 tokens per entry. Hard cap 2000 — validator rejects larger. Schema validation runs at write time; invalid entries are logged and skipped rather than breaking the run.

## Complex-session routing

A 7-factor heuristic decides Sonnet or Opus per session. Opus triggers on any of:
- duration > 120 min
- tool-call count > 150
- files touched > 10
- slug matches `incident|outage|rebuild|migration|rca|debug|architect|plan`
- assistant retry markers > 5 ("try again", "didn't work", etc.)
- user memory-tag ("save this", "remember this")
- session produced new topic files or edited >3 existing ones

Expected split: ~10-15% Opus, ~85-90% Sonnet. Trivial sessions (under 500 stripped bytes or fewer than 3 turns) short-circuit without a model call.

## Module layout

```
deep_context/
  schema.py      JSON-schema + validator
  prestrip.py    JSONL → compact prompt representation (~10x reduction)
  classify.py    Sonnet/Opus routing
  compress.py    Single-session compression; calls the CLI, validates output
  index.py       Unified writes to ChromaDB + FTS5
  filter.py      Pre-filter union: time + topic + file + FTS + semantic
  aggregate.py   Fan-out outputs → context.md with provenance citations
  backfill.py    Paced batch compression with checkpointing
  cli.py         Entry points: compress, index, prefilter, aggregate, validate, emit-schema
  prompts/
    compress.md  Compression prompt
  tests/
    test_basic.py
```

## Auth

The compression subprocess inherits your parent environment, so it picks up whichever auth your Claude Code session uses: subscription OAuth (via the macOS Keychain) if that's how you're logged in, or `ANTHROPIC_API_KEY` if you've set one. If you want to force API-key auth without changing your session, set the env var before running the backfill.

**Note on subscription auth:** fresh non-interactive SSH sessions can't read the macOS Keychain, so the subscription path fails with "Not logged in". Run the backfill from a terminal that's part of your login session, or from inside a Claude Code session. This is a macOS constraint, not a bug in this package.

## Limits

- **Coverage is the coverage of the written record.** Decisions made verbally and never written don't appear anywhere for the pipeline to find.
- **Doesn't help on small tasks.** Running the pipeline takes a few minutes and some quota. For a three-minute edit, it's not worth it.
- **Doesn't help on greenfield work.** If there's no history, there's nothing to retrieve.
- **Doesn't replace judgement.** The output is a context file, not a decision. The sub-session that runs against it can still get the work wrong.

## What to inherit if you're adapting this

Three things are load-bearing and worth keeping if you build something similar:

1. **The precedence rule** (topics > compressed > raw > derived).
2. **Golden-context benchmarking** — pick 3 past tasks with known-right context, hand-curate the ideal output, score the generated aggregator output against it before shipping. Non-negotiable for trust.
3. **Explicit invocation** — no auto-trigger from plan mode. The pipeline is for tasks worth the overhead, not every turn.

Everything else is tunable.
