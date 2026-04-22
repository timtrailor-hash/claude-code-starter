---
name: autonomous
description: "MANDATORY AUTO-TRIGGER: Launch persistent autonomous task runner whenever Tim says any of: 'email me', 'email me when done', 'ping me', 'let me know', 'send me', 'I'm stepping away', 'I'm going to bed', 'going out', 'back later', 'logging off', 'heading off', 'do this independently', 'work on this while I'm away', or /autonomous. Guarantees email delivery of actual results via retry loop."
disable-model-invocation: false
---

# Autonomous Task Runner

## MANDATORY TRIGGER — READ THIS FIRST

**You MUST use this runner whenever Tim says ANY of these (or similar):**
- "email me" / "email me when done" / "send me an email" / "ping me" / "let me know"
- "I'm stepping away" / "I'm going to bed" / "going out" / "back later" / "logging off" / "heading off"
- "do this independently" / "work on this while I'm away"
- /autonomous

**Do NOT just do the work inline and send a simple email.** The runner guarantees delivery even if this session dies. Every autonomous task MUST go through this runner.

**The runner emails the ACTUAL RESULT — not "task complete".** Tim gets the real answer in his inbox.

## How It Works

1. You reformulate Tim's request into a self-contained prompt
2. The runner script launches with `nohup` — completely independent of this session
3. It runs `claude -p "prompt"` non-interactively (same tools, same CLAUDE.md, same memory)
4. If Claude fails, times out, or produces garbage → it retries with exponential backoff (up to 5 times)
5. On success → emails the ACTUAL RESULT
6. On all retries exhausted → emails failure report with all attempt outputs
7. Email delivery itself retries 5 times — the email ALWAYS arrives

## Instructions

When Tim triggers autonomous mode:

### Step 1: Reformulate the prompt

Turn Tim's conversational request into a **complete, self-contained prompt** that a fresh Claude session can execute without any conversation context. Include:
- What to do (specific, actionable)
- What tools/files/paths to use
- What format the output should be in
- Any constraints or preferences from this conversation

**Critical:** The prompt must be self-contained. The runner launches a FRESH Claude session — it has CLAUDE.md and memory but NOT this conversation's context.

### Step 2: Write and launch the runner

**CRITICAL — keychain-capable launch only.** Subscription auth lives in the macOS login keychain (`security find-generic-password -s "Claude Code-credentials"`). That keychain is unlocked for the GUI user session and anything spawned from it (claude-mobile LaunchAgent → your current Claude session). It is NOT unlocked for fresh non-interactive SSH sessions — so wrapping the launch in `ssh user@host '...'` on the same Mac Mini will make `claude -p` fail with "Not logged in" on every retry even though login is fine. (2026-04-14 incident.)

**Rule: launch the runner directly from your current session. Never wrap in an SSH call to the same host.** You are already on the Mac Mini (`hostname` = `Tims-Mac-mini.local`); there is nowhere to SSH to. The runner now pre-flight-checks keychain reachability and will hard-abort with exit code 2 before the retry loop if you violate this rule.

Use the Bash tool with `run_in_background: true`:

```bash
nohup python3 ~/.claude/skills/autonomous/autonomous_runner.py \
  --prompt "THE COMPLETE SELF-CONTAINED PROMPT HERE" \
  --email "<YOUR_EMAIL>" \
  --max-retries 5 \
  --timeout 600 \
  > /tmp/autonomous_runner_stdout.log 2>&1 &
```

### Step 3: Confirm to Tim

Tell Tim:
- The task is running independently (PID shown in log)
- It will retry up to 5 times if needed
- He WILL get an email with the actual result
- Log file: `/tmp/autonomous_runner.log`
- If something goes catastrophically wrong, result saved to `/tmp/autonomous_result.txt`

## Example

Tim says: "Review all our printer configs and email me a summary of what needs fixing. I'm going to bed."

You would run:
```bash
nohup python3 ~/.claude/skills/autonomous/autonomous_runner.py \
  --prompt "You are reviewing the 3D printer setup for Tim. SSH to the <VENDOR> <DEVICE_MODEL> Max at <PRINTER_IP> (user: sovol, password: sovol) and review the <printer_firmware> config files in /home/sovol/printer_data/config/. Also check the Moonraker API at http://<PRINTER_IP>:7125/printer/objects/query?print_stats&extruder&heater_bed for current state. Compare configs against best practices. Check for: deprecated settings, missing safety guards, calibration issues, unused includes. Format your response as a clear summary with sections: Current State, Issues Found, Recommended Fixes. Be specific — include file paths and line numbers." \
  --email "<YOUR_EMAIL>" \
  --max-retries 5 \
  --timeout 600 \
  > /tmp/autonomous_runner_stdout.log 2>&1 &
```

## Monitoring

The runner creates `/tmp/autonomous_task_active` while running (contains PID, start time, prompt preview).
Check progress: `tail -f /tmp/autonomous_runner.log`
Check if running: `cat /tmp/autonomous_task_active 2>/dev/null`

## Important Notes

- The runner uses `claude -p` (non-interactive) — same model, same tools, same CLAUDE.md/memory
- It strips ANTHROPIC_API_KEY from the environment (uses subscription auth, no API costs)
- Each retry gets a fresh Claude session with full context budget
- Exponential backoff: 30s → 60s → 120s → 240s → 300s between retries
- Default timeout: 10 minutes per attempt. For very long tasks, use `--timeout 1800` (30 min)
- The RESULT is emailed, not just "done" — Tim gets the actual answer
