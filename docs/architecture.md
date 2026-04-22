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

### Feedback memory files

A specific usage pattern worth calling out: keep a set of `topics/feedback_*.md` files that record behavioural corrections you give Claude. "Don't ever give me a time estimate." "Translate git vocabulary into plain English before asking me to make a decision." "School docs backups are by design not mirrored to Drive, stop flagging them." Each one is a single file with a rule, a reason, and a "how to apply" line.

The reason this matters: corrections given inline in a session are forgotten the moment the session closes. A file in `topics/` is loaded into the system context at session start, so the rule survives. The rule of thumb is: if you catch yourself giving Claude the same correction twice, save it as a feedback memory the second time. Over a few months you end up with twenty or thirty of these, and they shape the agent's default behaviour without you having to re-state your preferences every session.

The starter kit ships zero of these by design. They are inherently personal. What it ships is the pattern — a `topics/` directory, a memory server that loads it, and a `/dream` skill that proposes updates.

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

## If you build a UI layer on top of a terminal session

A specific lesson worth repeating if you end up, as I did, building a mobile or desktop app that relays taps into a tmux or terminal-backed session. The surface failure mode looks innocuous. Your app shows "Allow / Deny" buttons above the keyboard. The user taps Allow. A keystroke goes down the wire into the terminal. Claude Code reads the keystroke and proceeds.

Then Claude issues a new permission prompt with identical choices immediately after. Your app re-renders the same three buttons for the new prompt. To the user, nothing appears to have changed since the last tap. They tap Allow again, thinking the first tap did not register. The keystroke arrives at a point where the new prompt is not yet the focused input, so it lands in the terminal as a literal character. Now the user's message box contains a stray digit they did not type. Trust in the UI collapses.

The fix is a monotonic prompt id the server assigns each time a fresh prompt opens. The app sends the id along with the tap. The server rejects any tap carrying a stale id. The app hides the buttons optimistically on tap and only shows a bar again when the server announces a new id. Three small pieces, each one structural:

1. Monotonic id generator on the server, bumped on the transition from "no prompt" to "prompt open."
2. Client includes the current id in every action.
3. Server validates the id and returns a 409 on mismatch. Client reverts its optimistic hide on 409.

This pattern generalises to any UI that relays user intent into a system whose state is changing faster than the user can perceive. The specific code lives in my conversation server (not in this starter kit because the plumbing is tightly coupled to my SwiftUI app), but the pattern itself is cheap, standard, and worth reaching for the moment you notice your users tapping twice because they are not sure the first tap landed.

## If your hooks write to an audit log

If a hook records to a shared audit file (`~/.claude/printer_audit.log` is my example), and your scenario test suite exercises the hook with malicious-looking payloads to verify the blocks fire, you have a second problem to solve: keep test-generated entries out of the production log.

Today's concrete failure mode: every `git commit` in my control-plane repo triggered pre-commit pytest, which ran the printer-safety scenario tests, which invoked the real hook against fake `FIRMWARE_RESTART` URLs. The hook correctly blocked them, and correctly logged `BLOCKED_ALWAYS` to the production audit file. Result: the production log filled with entries indistinguishable from a real attacker attempting to kill active prints.

The fix is one line on each side. In the hook, read the log file path from an environment variable with a default:

```python
LOG_FILE = os.environ.get("AUDIT_LOG_PATH", os.path.expanduser("~/.claude/audit.log"))
```

In the test runner, set the override to a scratch path:

```python
test_env["AUDIT_LOG_PATH"] = "/tmp/test_audit.log"
proc = subprocess.run(["bash", hook_path], env=test_env, ...)
```

Now test runs leave zero trace in the production log. Any real entry is a real attempt. If you skip this and rely on "the test is rare, the noise is fine," you lose the signal the log exists to provide.

## If your local hooks fire on SSH commands

If you have pre-flight hooks that grep the command text for risky patterns (paths to `~/Library/LaunchAgents`, writes to `/etc/`, and so on), add a clause at the top that short-circuits on `ssh ` and `scp ` prefixes. A local hook has no jurisdiction over a remote machine, and scanning the SSH payload for local-path names generates false positives that silently break workflows.

Concrete example from today: installing a LaunchAgent on a second machine via `ssh host "launchctl load ~/Library/LaunchAgents/foo.plist"` kept hitting the Mac Mini's local safety hook because the command text mentions the LaunchAgents path. The remote machine has its own hooks; the local machine was not going to be touched by that command. The fix is three lines:

```bash
if echo "$COMMAND" | grep -qE '^(ssh |scp )'; then
    # Printer-IP-specific patterns still fire here (dangerous gcode over SSH),
    # but everything else defers to the remote's own hooks.
    exit 0
fi
```

The principle: a safety hook should match its own machine's risk surface, not string-match arbitrary text that happens to mention a sensitive path.

## The pattern to take away

If you take only one thing from this repository, take the principle that **text rules fail under pressure and structural enforcement is the fix.** The specific hooks here are examples of that pattern applied to specific cases I cared about. Your own hooks will look different because your priorities are different. What should survive is the commitment to turn every repeated failure into a piece of code, a macro, a test, or a hook that makes the failure structurally impossible the next time.

That commitment, run over months, is what distinguishes a Claude Code setup that gets better from one that ossifies.
