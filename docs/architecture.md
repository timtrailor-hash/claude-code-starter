# Architecture

An overview of what this scaffold assembles, and why each piece is here.

## The basic idea

Claude Code is a terminal-native tool. This repository builds an operating environment around it so that Claude can work with:

1. **Memory** that persists across sessions.
2. **Hooks** that enforce safety rules structurally, so that text instructions are not the only line of defence.
3. **Skills** that encode repeatable workflows: pre-commit review, three-way multi-model debate, autonomous retry loops for long-running work, and memory consolidation.
4. **A control plane** that treats the Claude Code configuration itself as versioned infrastructure, with atomic deploys, automated rollback, and scenario tests that actually exercise the hooks.

The pattern across all four is the same: treat text rules as requests the agent can ignore under pressure, and build structural enforcement that holds regardless of what the agent is optimising for.

## The four skills

**`/review`** is the pre-commit gate. It runs a lint pass, a static-analysis pass, an internal code-review subagent that checks the change against your own lessons-learned database (if you have one), and, optionally, a one-shot review by a second-provider model. The intent is that you never push a significant change without `/review` having seen it.

**`/debate`** is for high-stakes decisions. Three models run in parallel: Claude (the orchestrating session), Gemini 2.5 Pro, and Generative Pre-trained Transformer version 5.4 (GPT-5.4). Round zero is blind: each writes a position without seeing the others. Round one onward each sees the others and must engage with their arguments. One seat per round is explicitly the "runtime blast-radius" reviewer whose job is to walk the dependency graph of what is changing and name what is not being checked. The protocol typically converges in one to three rounds.

**`/autonomous`** is a retry-loop runner. When you say "email me when done" or leave a task in flight, `/autonomous` takes the work, runs to completion with conservative decisions at ambiguous points, and emails you a report when it is done or blocked. It knows what requires human approval (anything irreversible, anything printer-side, any commit to a public repository) and will not cross those lines on its own.

**`/dream`** is periodic memory consolidation. It runs between sessions on a schedule. It reads recent session transcripts, proposes updates to the topic files that hold persistent knowledge, and flags anything contradictory. It is the mechanism that prevents memory from becoming a pile of unconnected observations.

## The hooks

Hooks are shell scripts that Claude Code executes at well-defined lifecycle points: before a tool call, after a tool call, at session start, at session end. If a hook exits non-zero, the operation it is gating can be blocked. This lets you convert a text rule like "do not commit anything containing an Application Programming Interface (API) key" into a structural guarantee: a PreToolUse hook greps the incoming file-write content, finds the key, returns a deny decision, and the tool call never runs.

The hooks shipped here cover:

- **Credential leak** on file writes and edits.
- **Protected path** blocking dangerous launchctl and plist operations.
- **Rename guard** warning when a path rename would leave dangling references elsewhere in the codebase.
- **Session manifest** tracking which files a session has touched for easier review.
- **Configuration integrity** verifying that referenced hooks and scripts actually exist on disk.
- **Lint on file write** running language-appropriate linters and logging findings.
- **Audit log** recording every Bash invocation for forensics.
- **Memory and Model Context Protocol (MCP) health** as cheap liveness probes.

You will edit these. That is the point. The versions here are starting points.

## The memory system

Two-tier search over your session history:

- **Semantic**: a vector store (Chroma Database — ChromaDB — with local embeddings, so no Application Programming Interface key required) indexes conversation chunks so you can ask questions like "what did we try when the deploy kept failing last month."
- **Keyword**: Structured Query Language (SQL) Lite Full-Text Search version 5 (FTS5) indexes the same corpus for exact-match queries where you need a specific Internet Protocol (IP) address, error string, or date.

Both are needed. Semantic search misses exact strings. Keyword search misses conceptual questions. Having both means you can find what you need regardless of how you phrase the query.

Canonical facts (not conversation history) live in per-topic Markdown files under a `topics/` directory. These are curated by you, not by the indexer, and they are version-controlled. The `/dream` skill proposes updates to these but does not write to them directly without approval.

## The control plane

`deploy.sh`, `verify.sh`, `rollback.sh`, and `diff-live.sh` together make your Claude Code configuration behave like a deployed system rather than a pile of files in `~/.claude/`.

`deploy.sh` snapshots the current state, copies the new state from the repository, runs `verify.sh`, and if verify fails, automatically invokes `rollback.sh` to restore the snapshot. This means you can edit hooks and skills in this repository, deploy with one command, and trust that a broken deploy does not leave the system in a half-working state.

`verify.sh` runs two layers of check: a cheap hook-wiring pass (does each hook referenced in `settings.json` exist on disk and is it executable) and a pytest scenario suite that feeds real Claude Code JavaScript Object Notation (JSON) payloads into the hooks and asserts the correct allow/deny behaviour. This matters because a hook that looks present but silently passes everything through is worse than no hook at all. The scenario tests catch that.

`rollback.sh` restores the last known good state from the `.deploy-backups/` directory. `diff-live.sh` shows the drift between the repository and the installed state, which you run before any deploy and after any manual change.

## The scenarios

`scenarios/` is a pytest suite that does not test code — it tests that the enforcement layer behaves correctly.

- `ai_safety/` tests that retrieval content is not routed into the system-prompt role (the class of vulnerability Cisco documented against Claude Code's own memory system in early 2026), that MCP servers installed from package registries are version-pinned, and that retrieved-content metadata is visible enough to spot injection.
- `credentials/` tests that credential patterns in file writes are caught.
- `drift/` tests for configuration drift between what is declared and what is deployed.
- `hooks/` exercises each hook with real payloads.

If `verify.sh` returns green, these tests passed. If it returns red, you have a specific failure to fix.

## What is not here

- **Printer safety.** Hardware-specific and varies by device. If you have a Klipper printer and want the pattern, read the matching blog post and adapt.
- **Subject-matter-specific skills.** Anything that is about my particular work context is not portable.
- **Memory content.** You start with an empty memory. You fill it.
- **iOS companion app.** Separate repository; the Claude Code side does not depend on it.

## The pattern to take away

If you take only one thing from this repository, take the principle that **text rules fail under pressure and structural enforcement is the fix.** The specific hooks here are examples of that pattern applied to specific cases I cared about. Your own hooks will look different because your priorities are different. What should survive is the commitment to turn every repeated failure into a piece of code, a macro, a test, or a hook that makes the failure structurally impossible the next time.

That commitment, run over months, is what distinguishes a Claude Code setup that gets better from one that ossifies.
