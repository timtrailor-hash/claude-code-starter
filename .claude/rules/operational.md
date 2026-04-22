# Operational Rules

## Plan Mode Triggers
Enter plan mode (write out the plan, confirm before implementing) for:
- Any change to daemons, LaunchAgents, or automated processes
- Any change to printer configuration or macros
- Any new infrastructure (services, scheduled tasks, monitoring)
- Any refactor touching 3+ files or architectural decisions
- Any task where getting it wrong has blast radius (data loss, print kill, service outage)

Skip plan mode for: reading/researching, simple file edits, iOS UI changes, memory updates.

**If something goes wrong mid-execution: STOP and re-plan. Don't push forward.**

## Before Saying "I Can't" — Mandatory Checklist
Before telling Tim something can't be done, or asking him to do something himself, run this checklist:
1. Check `memory/topics/` for prior work on this topic
2. Search session JSONL logs for keywords (memory MCP `search_exact`)
3. Check if the tool/file/path actually exists right now (don't assume from memory)
4. Attempt the simplest version first
5. Can I SSH to Mac Mini and do it there? (`ssh <user>@<HOST_TAILSCALE_IP>`)
6. Can I use a tool I haven't tried yet?

If still stuck after the checklist: say "I tried X and got Y" — never just "I can't".

This checklist is the only piece of "default to action" preserved from the prior version of this file. It exists because the old "default to action" rule was being misinterpreted as licence to act without thinking. Plan mode is the new default; this checklist is the safety valve against learned helplessness.

## Pre-Flight Checklist (before shipping any daemon/automation)
1. What commands can this code send to external systems? List every one.
2. Does it check state before every action? (print_stats.state for printer, health for services)
3. What happens on network drop, error state, or unexpected input?
4. Can Tim stop it with a single command?
5. Has this category of fix been attempted before? (check `lessons.md`)
If ANY answer is "I don't know" — don't ship it.

## Verification Standard
Never mark a task complete without proving it works END-TO-END:
- Don't just check "is the process running?" — check "does the feature actually work?"
- For API features: make an actual API call and verify the response
- For printer features: query actual printer state via Moonraker
- For iOS builds: verify the .app was produced and signed
- For daemon changes: check logs show correct behaviour, not just "running"

## Plan Mode Review Agents
When in plan mode, spawn at least one independent review agent to challenge the plan before implementation. The review agent's job: verify factual claims against memory files and live system state.

## Network/Infrastructure Change Verification
Before any commit that changes an IP address, hostname, port, or network configuration:
1. Verify the current working value by querying the live system (not from memory alone)
2. Check MEMORY.md and user_profile.md for device capabilities
3. Test from the AFFECTED context — if the change affects remote access, verify remotely
4. Spawn a review agent to fact-check the change against memory files and live state
5. If the change reverts a previous value, find the commit that set it and understand WHY

## RCA Depth Standard
When conducting any Root Cause Analysis, ALWAYS analyse all layers:
1. **What happened** — sequence of events, immediate cause
2. **What controls existed** — list every rule, check, or enforcement that should have prevented it
3. **Why each control failed** — for each, explain specifically why it didn't fire
4. **Fix classification** — is the proposed fix technical enforcement or another text rule? If text rule, explain why it will succeed where previous rules didn't
5. **Control class** — known-known (agent knew but skipped), unknown-known (rule exists but unconsulted), or unknown-unknown (nobody knew the action was dangerous)
An RCA that only covers layer 1 is incomplete.
