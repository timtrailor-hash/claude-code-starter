# First use

You have finished setup. Here is what to do next.

## Open a Claude Code session in your project

```bash
cd ~/code   # or wherever your project root is
claude       # or however you launch Claude Code
```

At session start, the hooks should fire. You will see a small line in the session start output about validation. If the session refuses to start, the `validate_hooks.sh` hook has found a missing file and you need to fix it before continuing.

## Try the core skills

`/review` — ask it to review the last commit. Expect lint output, a summary from the review subagent, and (if you enabled external models) a short second-opinion paragraph.

`/debate` — give it a concrete decision. Example: "should I decompose my API server module before or after adding the new billing endpoints?". Expect it to run three rounds typically, and return either a unanimous verdict or a majority plus the dissenter's reasoning.

`/autonomous` — say "email me when done" followed by a task description. It will work, retry on failure, and send you an email report.

`/dream` — this one runs on a schedule, not on demand. You should not need to invoke it manually.

## Check your memory

Try a memory search from inside Claude Code. Ask something like "when did I last hit the issue with X?". If the memory is empty (because you just set this up) you will get "no results". That is correct. The memory indexer picks up your session transcripts as you use Claude Code. Give it a week or two of normal use before expecting useful retrievals.

## Write your first CLAUDE.md

`CLAUDE.md` is the file Claude reads at session start to understand your project context. Put in it:
- What the project is.
- Any hard rules specific to this project (e.g. "never write to the production database from this session").
- Common commands you use.
- Pointers to where relevant context lives (e.g. "memory is in `~/.claude/projects/<yours>/memory/topics/`").

Keep it under about 200 lines. Longer CLAUDE.md files consume context budget and reduce how well Claude follows the rules.

## Start a lessons-learned file

Whenever something goes wrong, write it down. Not in a vague "I should do better" way. In this shape:

- **What happened** — one sentence.
- **What controls existed** — the rules, hooks, or tests that should have prevented it.
- **Why each control failed** — specifically, for each control, why it did not fire or was not enough.
- **The fix** — technical enforcement where possible, a rule where not, with a note explaining why the rule will succeed where the previous one did not.

After a few months you will have a file that, reviewed at the start of each session, actually changes Claude's behaviour because the patterns are specific to your incidents.

This repository does not ship a lessons file because your lessons will be different from mine.

## Deploy your first change

Edit a hook or add a skill in the repository. Run `./verify.sh`. When it passes, run `./deploy.sh`. The system copies the new state into `~/.claude/`, runs the verify suite against the deployed state, and rolls back if anything breaks.

The first time this feels like ceremony. After a week it feels like a seatbelt.

## When things go wrong

- **A hook is blocking something it should not.** Check `~/.claude/printer_audit.log` (if you kept the audit hook) or `/tmp/*.log` for the hook's own log. Fix the hook logic, re-deploy, re-verify.
- **A skill is not triggering.** Check `~/.claude/skills/<name>/SKILL.md` to confirm the description and trigger patterns match what you are saying.
- **Memory searches return nothing relevant.** Check the indexer is running and pointing at the correct project directory. First indexing can take several minutes.
- **`verify.sh` fails on a deploy.** The rollback script has already run. Look at the pytest output to see what failed, fix it, deploy again.

## Reducing permission prompts once you trust your hooks

Claude Code asks for approval before many tool calls. That is the right default for a fresh setup because your hooks have not been exercised yet. After a few weeks of real use, when you have seen your hooks block the things they should and allow the things they should, the prompts become noise rather than safety.

When you reach that point, open `~/.claude/settings.json` and add inside the `permissions` block:

```json
"defaultMode": "bypassPermissions"
```

This changes the default for tool calls from "prompt the user" to "proceed automatically." Crucially, it does NOT disable your hooks. A hook that returns a `deny` decision still blocks the operation. A hook that returns `ask` is what becomes automatic. Your printer-safety hook continues to block `FIRMWARE_RESTART` no matter what your default mode says.

The trust curve matters here. Start in the default mode. Watch what your hooks do. When you have a month of logs showing the hooks catching the right things, flip the setting. If you notice Claude doing things you did not authorise, flip it back and add a new hook.

## If you run Claude Code on more than one machine

Your memory folder (`topics/` and `MEMORY.md`) is version-controlled, which means two machines can stay in sync via `git pull`. The starter kit's SessionStart hook pulls memory on every session start, but if you want fresher sync (say, you save a feedback memory on the desktop and want it live on the laptop within minutes rather than "the next time you open Claude Code there"), add a LaunchAgent to pull every 15 minutes.

A sketch of the script:

```bash
#!/bin/bash
# memory_git_pull.sh
set -uo pipefail
MEM="$HOME/.claude/projects/<your-project>/memory"
cd "$MEM" || exit 0
git fetch --quiet 2>/dev/null || exit 0
BEHIND=$(git rev-list --count HEAD..@{upstream} 2>/dev/null || echo 0)
AHEAD=$(git rev-list --count @{upstream}..HEAD 2>/dev/null || echo 0)
DIRTY=$(git status --porcelain | wc -l | tr -d ' ')
if [ "$BEHIND" -gt 0 ] && [ "$AHEAD" -eq 0 ] && [ "$DIRTY" -eq 0 ]; then
    git pull --ff-only --quiet
fi
```

Run it every 15 minutes via a LaunchAgent with `StartInterval: 900`. Only pulls on a clean fast-forwardable state — never touches your in-progress edits. If you have a real merge conflict, it sits out and lets you resolve it manually at the next session start.

## What to build next

Look at what you do repeatedly in Claude Code sessions. If you find yourself typing the same multi-step instruction more than three times, that is a skill waiting to be written. Put it in `~/.claude/skills/<yourname>/SKILL.md`. The file format is a YAML-headed Markdown document; look at `/review` or `/debate` in this repository for the shape.

Look at what you have got wrong more than twice. That is a hook waiting to be written. Put it in `~/.claude/hooks/<yourname>.sh`. The file format is a shell script that reads JSON from stdin and exits zero or two.

## A word on the pace

You will not get value from this setup in the first day. The compounding is slow for the first two or three weeks while memory is sparse and you have not built your own skills yet. It is worth the investment.

If after a month you are still not using it, that is a signal the scaffold is wrong for your workflow. Strip out what does not work. The patterns are the point, not the specific files.
