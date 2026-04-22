#!/bin/bash
# PostToolUse hook for Write/Edit: appends touched file paths to a per-session manifest.
# Used by /secure-delete to know what this session created so it can be wiped.
# Safe to fail — hook is informational, should never block a tool call.

set +e

INPUT=$(cat)

SESSION_ID=$(printf '%s' "$INPUT" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("session_id") or d.get("sessionId") or "unknown")' 2>/dev/null)
FILE_PATH=$(printf '%s' "$INPUT" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("tool_input",{}).get("file_path",""))' 2>/dev/null)
TOOL_NAME=$(printf '%s' "$INPUT" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("tool_name",""))' 2>/dev/null)

[ -z "$FILE_PATH" ] && exit 0

case "$FILE_PATH" in
    /tmp/session-*-manifest.txt) exit 0 ;;
esac

MANIFEST="/tmp/session-${SESSION_ID}-manifest.txt"
TS=$(date '+%Y-%m-%dT%H:%M:%S')

{
    umask 077
    printf '%s|%s|%s\n' "$TS" "$TOOL_NAME" "$FILE_PATH" >> "$MANIFEST"
} 2>/dev/null

exit 0
