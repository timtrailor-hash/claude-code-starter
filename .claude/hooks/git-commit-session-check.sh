#!/bin/bash
# PreToolUse hook: Enforce Session trailer in git commit messages.
# Exit 0 = allow, Exit 2 = deny (JSON on stderr).

INPUT=$(cat)

COMMAND=$(echo "$INPUT" | python3 -c "import sys,json; print(json.loads(sys.stdin.read()).get('tool_input',{}).get('command',''))" 2>/dev/null)

# Only check git commit commands
if ! echo "$COMMAND" | grep -qE 'git\s+commit\b'; then
    exit 0
fi

# Skip if no message provided (editor-based, or non-commit git commands)
if ! echo "$COMMAND" | grep -qE '(-m\s|<<)'; then
    exit 0
fi

# Check for Session: trailer
if echo "$COMMAND" | grep -qE 'Session:\s*[0-9]{4}-[0-9]{2}-[0-9]{2}'; then
    exit 0
fi

# Deny — missing Session trailer
cat >&2 <<'DENY'
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "BLOCKED: git commit missing required 'Session: YYYY-MM-DD (session-id)' trailer. Add it to the commit message."
  }
}
DENY
exit 2
