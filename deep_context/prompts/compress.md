You are compressing a Claude Code session transcript into a structured summary for future retrieval by the `/deep-context` pipeline.

Output MUST be a single markdown document with YAML frontmatter matching the schema below. Output ONLY the document — no preamble, no explanation, no code fence around it.

## Schema

```
---
schema_version: 1
session_id: <as provided>
started: <ISO-8601 — as provided>
ended: <ISO-8601 — as provided>
duration_minutes: <as provided>
project: <as provided>
topics_touched: [<short tags you identify from content>]
topics_created: [<memory topic files newly created, if any>]
topics_updated: [<memory topic files modified, if any>]
files_touched: <as provided>
tool_call_count: <as provided>
compression_model: <as provided>
compression_timestamp: <as provided>
complexity_flags: <as provided>
---
## Goal
<One line — what Tim asked for in this session.>

## Decisions
- **<decision>**: <rationale — the WHY, not just the what>
<repeat; keep to the meaningful ones, not every edit>

## Outcome
<One word on its own line: shipped | abandoned | partial | ongoing>

## Failed attempts
- **<what was tried>**: <why it failed>
<REQUIRED SECTION. If there were no failed attempts, write exactly this line: `- none`>

## Unresolved
- <thing flagged for later>
<REQUIRED SECTION. If there are no unresolved threads, write exactly this line: `- none`>

## Links
- sessions: [<uuid>, ...]
- topics: [<topic file path>, ...]
- prs: [<url>, ...]
```

## Hard rules

1. **Decisions capture the WHY.** "We renamed X" is an action. "We renamed X because Y" is a decision. Do not record actions without rationale.
2. **Capture WHY-NOT.** Alternatives considered and rejected, with reason.
3. **Failed attempts with failure mode.** These drive lessons.md. "Tried X; it didn't work because Y." Not "tried X".
4. **Use exact identifiers.** File paths, commit SHAs, error strings — verbatim in Links or in the relevant section.
5. **Trivial sessions stay short.** Do not pad. A 5-minute simple edit becomes a 5-line entry. That is fine.
6. **Target 500-1500 tokens. Hard cap 2000.** Over-long entries will be rejected by the validator.
7. **Do not invent rationale.** If the transcript doesn't express WHY a decision was made, leave the rationale clause blank — do not guess.
8. **The frontmatter values marked `<as provided>` come from the caller — copy them verbatim.** Do not modify dates, IDs, paths, or counts.
9. **Outcome value is a single word.** One of the four values listed. On its own line.

## Judgment calls

- `topics_touched`: short tags inferred from the session subject matter (e.g. `printer`, `memory-system`, `terminal-app`). Do not invent new categories if an existing one fits.
- `topics_created` / `topics_updated`: infer from the transcript — if the assistant edited or created files under `memory/topics/`, list them.
- If the session had NO decisions (pure research, reading, one-off question), use `Decisions: - none` and focus on Goal + Outcome.

Now compress the following session.
