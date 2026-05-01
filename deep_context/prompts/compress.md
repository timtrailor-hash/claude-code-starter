You are compressing a Claude Code session transcript into a structured summary for future retrieval by the `/deep-context` pipeline.

Output MUST be a single markdown document with YAML frontmatter matching the schema below. Output ONLY the document — no preamble, no explanation, no code fence around it.

## Schema

```
---
schema_version: 2
session_id: <as provided>
started: <ISO-8601 — as provided>
ended: <ISO-8601 — as provided>
duration_minutes: <as provided>
project: <as provided>
topics_touched: [<short tags>]
topics_created: [<memory topic files created, if any>]
topics_updated: [<memory topic files modified, if any>]
files_touched: <as provided>
tool_call_count: <as provided>
compression_model: <as provided>
compression_timestamp: <as provided>
complexity_flags: <as provided>
---
## Goal
<One line — what the user asked for in this session.>

## Decisions
- **<decision>**: <rationale — the WHY, not just the what>
<repeat; only the meaningful ones that would be load-bearing in future work>

## Outcome
<One word: shipped | abandoned | partial | ongoing>

## Superseded approaches
- **<what was tried — be specific, quote the exact command/config>**: <why it failed — quote the exact error or observation>
<repeat for each meaningful dead end. If none, write exactly: `- none`>

## Unresolved
- <thing flagged for later>
<If none, write exactly: `- none`>

## Identifiers
<Verbatim table of every load-bearing identifier from the transcript. Each entry is a single bullet. DO NOT paraphrase — copy exact strings.>
- File paths: `<path>` (one per bullet if many)
- Commit SHAs: `<sha>` (one per bullet)
- IPs / hosts / ports: `<ip:port>` (one per bullet)
- URLs: `<url>` (one per bullet)
- Error strings: `"<exact error text>"` (one per bullet)
- Specific commands: `<cmd --flag value>` (one per bullet)
- Timestamps / dates: `<ISO date>` (one per bullet)
<If the transcript contains no load-bearing identifiers of a given type, omit that type. If it contains none at all, write: `- none`>

## Key exchanges
<0-5 verbatim quotes of user or assistant turns that defined a direction, rule, or constraint. Only where paraphrase would lose load-bearing detail. One line of context before each quote.>
- <context>: "<verbatim quote>"
<If none, write: `- none`>

## Links
- sessions: [<uuid>, ...]
- topics: [<topic file path>, ...]
- prs: [<url>, ...]
```

## Hard rules

1. **Every identifier appears verbatim.** File paths, commit SHAs, IP addresses, port numbers, URLs, error strings, specific tool commands, timestamps — every one of these that appears in the transcript MUST appear verbatim in the Identifiers section. Paraphrasing an identifier is a failure mode. The validator rejects compressed entries where too many identifiers are missing.
2. **Decisions capture the WHY.** "We renamed X" is an action. "We renamed X because Y" is a decision.
3. **Superseded approaches quote the exact failure.** "Tried X; it didn't work" is useless. "Tried `launchctl bootstrap gui/501 plist`; got error `Bootstrap failed: 125: Domain does not support specified action`" is load-bearing.
4. **Key exchanges are verbatim.** When a user or assistant turn established a rule or direction, quote it exactly. Do not summarise load-bearing turns.
5. **Budget is dynamic.** You will be given a target token budget in the metadata. Use it. Short sessions produce short entries; complex sessions need room.
6. **Do not invent.** If the transcript doesn't contain a rationale, leave the rationale clause blank — do not guess. If the transcript has no Key exchanges worth quoting, write `- none`.
7. **Metadata fields marked `<as provided>` come from the caller — copy verbatim.** Do not modify dates, IDs, paths, or counts.
8. **Outcome is a single word** on its own line. One of: shipped | abandoned | partial | ongoing.

## Judgment calls

- `topics_touched`: short inferred tags (e.g. `printer`, `memory-system`, `terminal-app`). Don't invent categories.
- `topics_created` / `topics_updated`: infer from the transcript — list files under `memory/topics/` that were created or modified.
- If a session had NO decisions (pure research, one-off question), use `Decisions: - none` and focus on Goal + Identifiers.
- If a session had no meaningful superseded approaches, `Superseded approaches: - none`. Don't pad.

Now compress the following session.
