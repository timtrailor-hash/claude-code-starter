---
name: deep-context
description: "Pre-assemble a task-specific context.md before a high-stakes task. Fan-out over topics + compressed-sessions + code, re-read raw JSONL for flagged sessions, write a single dense context file. Use when a task would warrant plan mode."
user-invocable: true
disable-model-invocation: false
---

# /deep-context — pre-task context assembly

This skill produces a single `context.md` (<50K tokens) that gives the *next* session everything it needs to do a high-stakes task well, without that session having to hunt for context mid-work.

**Invoke only when the task warrants plan mode.** Architectural changes, migrations, multi-file refactors, anything with blast radius. Not for simple edits, reading, or one-off questions.

## Prerequisites

- `deep-context/` Python package installed (see `deep-context/README.md`).
- Backfill run at least once (`python3 -m deep_context.backfill`) so the compressed-session layer has content.
- `DEEP_CONTEXT_HOME` env var set (default: `~/.claude/deep-context/`).

## Arguments

`$ARGUMENTS` is the brief — a short paragraph describing what the downstream session is going to do. Be specific. "Fix the bug" is weak; "Investigate why the nightly ETL regressed after commit abc123, propose a fix, roll it out with a feature flag" is strong. Feed the brief exactly as you'd feed it to a new session.

## Pipeline (5 stages)

### 1. Prefilter — narrow the compressed-session corpus → candidate list

```
python3 -m deep_context.cli prefilter "$BRIEF" --window 90 --paths
```

Output JSON: `{candidates: [session_id], by_source: {...}, counts: {...}, paths: [md_path]}`. Typical count: 20-80. If empty, either the backfill hasn't run or the brief is entirely greenfield.

Write the prefilter JSON to `/tmp/dc_$RUNID/prefilter.json`.

### 2. Fan-out — three independent agents read different layers

Generate `$RUNID=$(date +%s)-$RANDOM` once. Create `/tmp/dc_$RUNID/`.

Spawn three agents **in parallel** via the Agent tool:

- **Agent A — topics reader.**
  `subagent_type: Explore`
  Prompt: "Read the topic files at your memory directory (e.g. `memory/topics/`). Filter to files relevant to this brief: `$BRIEF`. Extract the claims that would be load-bearing for this task. Output JSON to /tmp/dc_$RUNID/topics.json with shape `{summary: str, claims: [{claim, source}], flagged_sessions: [], unresolved: [], files_likely: []}`. Use `topic:<path>` as the source tag for every claim."

- **Agent B — compressed-sessions reader.**
  `subagent_type: Explore`
  Prompt: "Read the compressed session files whose paths are in /tmp/dc_$RUNID/prefilter.json (under `paths`). Filter to ones relevant to this brief: `$BRIEF`. Extract decisions, rationale, failed attempts, and unresolved threads that would matter. For any session where the compressed summary looks thin or ambiguous and raw detail would genuinely help, include its session_id in `flagged_sessions` so raw is re-read. Output JSON to /tmp/dc_$RUNID/sessions.json with shape `{summary: str, claims: [{claim, source}], flagged_sessions: [session_id], unresolved: []}`. Use `session:<id>` as the source tag."

- **Agent C — code-layer reader.**
  `subagent_type: Explore`
  Prompt: "For the brief `$BRIEF`, use Glob and Grep over the project directories to find files likely to be touched. DO NOT read whole files — grep for patterns, then read only the surrounding lines. Output JSON to /tmp/dc_$RUNID/code.json with shape `{summary: str, claims: [{claim, source}], files_likely: [absolute_path]}`. Use `code:<path>` (optionally with `:line`) as the source tag."

Wait for all three to complete. If any returns no JSON, log and continue with what we have.

### 3. Raw re-read — fidelity where the compressed layer was thin

Read `sessions.json`. For each `flagged_sessions` entry, find the raw JSONL via the `source_jsonl` field in `$DEEP_CONTEXT_HOME/sessions/_manifest.jsonl`, or by searching `~/.claude/projects/`. Pre-strip via the prestrip utility and read the result into context for the aggregator step.

**Do not fan this out further.** Read sequentially; these are the sessions already flagged as high-value.

### 4. Aggregate — build the context.md

Combine the three fan-out JSONs:

```
jq -s '{topics: .[0], sessions: .[1], code: .[2]}' \
  /tmp/dc_$RUNID/topics.json \
  /tmp/dc_$RUNID/sessions.json \
  /tmp/dc_$RUNID/code.json \
  > /tmp/dc_$RUNID/fanout.json
```

Run the aggregator:

```
python3 -m deep_context.cli aggregate \
  --brief "$BRIEF" \
  --fanout /tmp/dc_$RUNID/fanout.json \
  --raw-reread "$(jq -r '.flagged_sessions | join(",")' /tmp/dc_$RUNID/sessions.json)" \
  --out /tmp/dc_$RUNID/context.md
```

The aggregator dedupes claims, structures the output (Recent state / Relevant history / Unresolved / Files likely), and caps at 50K tokens.

### 5. Instrumentation — log this run

Append one line to `~/.claude/logs/deep-context.jsonl`:

```json
{"timestamp": "<ISO>", "run_id": "$RUNID", "task_brief": "$BRIEF",
 "filter_output_count": <from prefilter counts.total>,
 "sessions_flagged_for_raw": [...],
 "context_tokens": <from aggregate stats.rough_tokens>}
```

## Handoff

Present `/tmp/dc_$RUNID/context.md` to the user. Ask: "Context assembled. Spawn a new session with this, or review first?"

If they say "spawn it", start a new Claude session with the context.md prepended to the brief. If they say "review", print the path and the first 40 lines.

## Memory precedence (reminder)

- Topics = curated truth (wins).
- Compressed sessions = routing/recall (not authoritative on facts).
- Raw JSONL = arbitration when compressed and topic disagree.
- Never write back from compressed into raw. Session-close consolidation (e.g. `/dream`) is the only path compressed → topics.

## Troubleshooting

- **Prefilter returns 0 candidates.** Either the backfill hasn't run yet (`ls $DEEP_CONTEXT_HOME/sessions/ | wc -l` should show >0) or the brief is greenfield. Proceed with topics + code only; skip the sessions agent.
- **Agent times out.** Most likely the topic list or compressed-session list is too long. Pass only the top 30 paths to the agent.
- **Validator rejects a compressed file.** Check `$DEEP_CONTEXT_HOME/sessions/_manifest.jsonl` for the `invalid` entry and its `reason` field. Re-run compression with `--force`.

## What NOT to do

- Do not run `/deep-context` in the same session that's going to execute the task. The whole point is to spawn a *fresh* session with only the brief + context.md — keeps the task session uncluttered.
- Do not edit the generated context.md by hand. If it's wrong, fix the aggregator or the source data, then re-run.
- Do not commit context.md files — they're per-task ephemera, not canonical memory.
