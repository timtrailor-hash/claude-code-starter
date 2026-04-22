#!/bin/bash
# PreToolUse hook: Detect unexpected modifications to safety config files.
#
# Design: After each tool call, we update checksums. Before the NEXT tool call,
# we compare. If files changed between calls without Claude editing them,
# something external modified our safety config — block and alert.
#
# This means Claude CAN modify config files (it updates checksums after),
# but an external process or prompt injection that modifies files between
# Claude's own tool calls will be caught.

CACHE="/tmp/claude-config-checksums.txt"
LOCK="/tmp/claude-config-checksums.lock"

# Files to protect
FILES=(
    "$HOME/.claude/rules/printer-safety.md"
    "$HOME/.claude/rules/operational.md"
    "$HOME/.claude/rules/infrastructure.md"
    "$HOME/.claude/rules/security.md"
    "$HOME/.claude/settings.json"
    "$HOME/.claude/hooks/printer_safety.py"
)

# Calculate current checksums
current_checksums() {
    for f in "${FILES[@]}"; do
        if [ -f "$f" ]; then
            shasum -a 256 "$f" 2>/dev/null
        fi
    done | sort
}

CURRENT=$(current_checksums)

# First run — no cache exists, create it and allow
if [ ! -f "$CACHE" ]; then
    echo "$CURRENT" > "$CACHE"
    exit 0
fi

CACHED=$(cat "$CACHE")

# Compare
if [ "$CURRENT" = "$CACHED" ]; then
    # No changes — allow
    exit 0
fi

# Files changed. Check if THIS tool call is an Edit/Write to one of the protected files.
# Read the hook input to see what tool is being called.
INPUT=$(cat)
TOOL=$(echo "$INPUT" | python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('tool_name',''))" 2>/dev/null)
FILE_PATH=$(echo "$INPUT" | python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('tool_input',{}).get('file_path',''))" 2>/dev/null)

# If Claude is about to Edit/Write a protected file, that's expected — update cache and allow
if [ "$TOOL" = "Edit" ] || [ "$TOOL" = "Write" ]; then
    for f in "${FILES[@]}"; do
        if [ "$FILE_PATH" = "$f" ]; then
            # Claude is intentionally modifying this file — update cache after and allow
            echo "$CURRENT" > "$CACHE"
            exit 0
        fi
    done
fi

# If we're here and it's a Bash call that modifies config (sed, cp, mv, etc.)
# we can't easily tell if it's targeting our files, so update cache and allow.
# The real protection is against EXTERNAL changes between tool calls.
if [ "$TOOL" = "Bash" ]; then
    # Update cache to current state — Claude is making changes
    echo "$CURRENT" > "$CACHE"
    exit 0
fi

# Files changed AND this isn't a Claude tool modifying them — external modification!
# Find which files changed
CHANGED=""
while IFS= read -r line; do
    file=$(echo "$line" | awk '{print $2}')
    if ! echo "$CACHED" | grep -q "$(echo "$line" | awk '{print $1}')"; then
        CHANGED="$CHANGED\n  $file"
    fi
done <<< "$CURRENT"

if [ -n "$CHANGED" ]; then
    # Block with deny decision
    cat >&2 <<DENY
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "ALERT: Safety config files were modified externally (not by Claude tool calls). Changed:$CHANGED\nThis may indicate unauthorized modification. Review the changes and restart the session."
  }
}
DENY
    exit 2
fi

# Update cache and allow
echo "$CURRENT" > "$CACHE"
exit 0
