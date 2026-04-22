#!/bin/bash
# SessionStart hook: validate that every hook script and MCP launcher
# referenced in settings.json actually exists and is executable.
#
# Why: today's review found 3 hook scripts referenced in settings.json that
# didn't exist on disk (pre-existing drift). This catches that class of bug
# at session start, before broken hooks fail silently for weeks.
#
# Behaviour: writes a report to /tmp/claude_hook_validation.log and to
# ~/.claude/hook_validation.log on every session start. Sends an ntfy
# notification if anything is missing. Exits 0 always — advisory.

set -uo pipefail

SETTINGS=~/.claude/settings.json
LOG=~/.claude/hook_validation.log
TS=$(date "+%Y-%m-%d %H:%M:%S")

[ -f "$SETTINGS" ] || exit 0

# Extract every command path referenced in settings.json
# (top-level "command" fields under hooks AND under mcpServers)
PATHS=$(python3 - "$SETTINGS" <<'PYEOF'
import json, sys, re
data = json.load(open(sys.argv[1]))
seen = set()

# Hook commands
for stage in data.get("hooks", {}).values():
    for entry in stage:
        for h in entry.get("hooks", []):
            cmd = h.get("command", "")
            # Extract first non-flag token that looks like a path
            for tok in cmd.split():
                if tok.startswith("/") and ("/" in tok):
                    seen.add(tok)
                    break

# MCP server commands
for name, srv in data.get("mcpServers", {}).items():
    cmd = srv.get("command", "")
    if cmd.startswith("/"):
        seen.add(cmd)
    for arg in srv.get("args", []):
        if arg.startswith("/") and "/" in arg:
            seen.add(arg)

for p in sorted(seen):
    print(p)
PYEOF
)

MISSING=()
while IFS= read -r p; do
    [ -z "$p" ] && continue
    if [ ! -e "$p" ]; then
        MISSING+=("$p")
    fi
done <<< "$PATHS"

if [ ${#MISSING[@]} -eq 0 ]; then
    echo "[$TS] OK — all referenced paths exist" >> "$LOG"
    exit 0
fi

# Write report
{
    echo "[$TS] VALIDATION FAILED — ${#MISSING[@]} missing path(s):"
    for p in "${MISSING[@]}"; do
        echo "  MISSING: $p"
    done
    echo "---"
} | tee -a "$LOG" >&2

# Notify (ntfy is fire-and-forget, won't block)
{
    echo "Claude hook validation failed: ${#MISSING[@]} missing paths"
    for p in "${MISSING[@]}"; do echo "- $(basename "$p")"; done
} | curl -s --max-time 3 -d @- ntfy.sh/<user>-claude >/dev/null 2>&1 || true

exit 0
