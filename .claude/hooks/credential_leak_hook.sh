#!/bin/bash
# Claude Code pre-command hook for Write/Edit: warns if content looks like it contains credentials
# and the target file is in a git-tracked directory.
# Exit 0 = allow, Exit 2 = block with message.

INPUT=$(cat)

# Extract file_path and content from the JSON input
FILE_PATH=$(echo "$INPUT" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print(data.get('tool_input', {}).get('file_path', ''))
except:
    print('')
" 2>/dev/null)

if [ -z "$FILE_PATH" ]; then
    exit 0
fi

# Skip non-code files (memory files, plans, etc.)
if echo "$FILE_PATH" | grep -qE '(memory/|\.claude/plans/|\.claude/commands/|\.claude/rules/)'; then
    exit 0
fi

# Check if file is in a git repo
FILE_DIR=$(dirname "$FILE_PATH")
if ! git -C "$FILE_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    exit 0  # Not in a git repo, allow
fi

# Check if file is gitignored
if git -C "$FILE_DIR" check-ignore -q "$FILE_PATH" 2>/dev/null; then
    exit 0  # File is gitignored, allow
fi

# Extract content to check for credential patterns
CONTENT=$(echo "$INPUT" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    content = data.get('tool_input', {}).get('content', '') or data.get('new_string', '')
    print(content[:5000])  # Check first 5K chars only
except:
    print('')
" 2>/dev/null)

if [ -z "$CONTENT" ]; then
    exit 0
fi

# Check for credential-like patterns
if echo "$CONTENT" | grep -qiE '(sk-[a-zA-Z0-9]{20,}|ANTHROPIC_API_KEY|api[_-]?key\s*[=:]\s*["\x27][a-zA-Z0-9]{20,}|password\s*[=:]\s*["\x27][^\s]{8,}|BEGIN (RSA |EC )?PRIVATE KEY|access_code\s*[=:]\s*["\x27][0-9]{6,})'; then
    echo "WARNING: Content appears to contain credentials or API keys."
    echo "File: $FILE_PATH"
    echo "This file is tracked by git and may be pushed to a public repo."
    echo "Use credentials.py (gitignored) for secrets instead."
    exit 2
fi

exit 0
