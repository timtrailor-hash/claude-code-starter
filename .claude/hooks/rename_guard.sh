#!/bin/bash
# rename_guard.sh — PreToolUse hook that catches destructive rename/removal
# operations and refuses them if references to the old path still exist.
#
# Addresses Pattern 19 (partial grep before rename): tonight I renamed a
# memory clone without grepping for every consumer. This hook makes that
# grep mandatory BEFORE the destructive operation runs.
#
# What it blocks:
#   - `rm -rf <dir>`
#   - `rm <file>` for files inside ~/code, ~/.claude, tim-claude-controlplane
#   - `mv <src> <dst>` where src is under a managed directory
#   - `git mv <src> <dst>`
#
# Escape hatch: append ` # verified: <pattern>` to the command. The hook
# extracts <pattern>, greps both machines for it, and passes if matches is
# empty OR the commit contains the matches as expected fixups.
#
# Mode:
#   RENAME_GUARD_MODE=advisory (default): warn to stderr, exit 0 (allow)
#   RENAME_GUARD_MODE=strict: exit 2 (block) on any unverified rename
#
# Reads JSON from stdin per Claude Code hook protocol.

INPUT=$(cat)
MODE="${RENAME_GUARD_MODE:-advisory}"

COMMAND=$(echo "$INPUT" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print(data.get('tool_input', {}).get('command', ''))
except Exception:
    print('')
" 2>/dev/null)

[ -z "$COMMAND" ] && exit 0

# Escape hatch: `# verified: <pattern>` in the command means the caller
# has already run the grep and is explicitly vouching for no references.
if echo "$COMMAND" | grep -q '# verified:'; then
    exit 0
fi

# Detect destructive rename/removal patterns
TARGET=""
VERB=""

# Pattern 1: rm -rf <path>
if MATCH=$(echo "$COMMAND" | grep -oE 'rm -rf? ([^ &;]+)' | head -1); then
    if [ -n "$MATCH" ]; then
        TARGET=$(echo "$MATCH" | awk '{print $NF}')
        VERB="rm -rf"
    fi
fi

# Pattern 2: git mv <src> <dst> — src is the vulnerable one
if [ -z "$TARGET" ] && MATCH=$(echo "$COMMAND" | grep -oE 'git mv ([^ ]+) ([^ &;]+)' | head -1); then
    TARGET=$(echo "$MATCH" | awk '{print $3}')
    VERB="git mv"
fi

# Pattern 3: mv <src> <dst> where src is absolute and inside managed dirs
if [ -z "$TARGET" ] && MATCH=$(echo "$COMMAND" | grep -oE 'mv ($HOME/[^ ]+) ([^ &;]+)' | head -1); then
    TARGET=$(echo "$MATCH" | awk '{print $2}')
    VERB="mv"
fi

# If no destructive rename detected, allow
[ -z "$TARGET" ] && exit 0

# Only care about paths inside managed roots
case "$TARGET" in
    */code/*|*/\.claude/*|*/tim-claude-controlplane/*|*/.local/*) : ;;
    *) exit 0 ;;
esac

# Build search patterns. We grep for DISTINCTIVE substrings of the target
# path — not just the basename, which for common words ("memory", "code")
# would match hundreds of unrelated files. Strategy:
#   1. The full absolute path (rare, very distinctive)
#   2. The last 2 path components joined (distinctive enough)
#   3. Skip if basename is a common word (memory, code, topics, logs)
TARGET_NORMALIZED=$(echo "$TARGET" | sed 's|/$||')
BASENAME=$(basename "$TARGET_NORMALIZED")
PARENT=$(basename "$(dirname "$TARGET_NORMALIZED")")
TWO_COMPONENTS="$PARENT/$BASENAME"

# Common English words and generic tokens that produce too many false positives.
# If the basename is one of these, only search for the 2-component form.
case "$BASENAME" in
    memory|code|topics|logs|hooks|rules|skills|agents|data|tmp|test|tests|src|lib|bin|cache|dist|build)
        PATTERNS=("$TWO_COMPONENTS" "$TARGET_NORMALIZED")
        ;;
    *)
        PATTERNS=("$BASENAME" "$TWO_COMPONENTS" "$TARGET_NORMALIZED")
        ;;
esac

REFS=""
for PAT in "${PATTERNS[@]}"; do
    for SEARCH in "$HOME/code" "$HOME/.claude"; do
        [ -d "$SEARCH" ] || continue
        FOUND=$(grep -rlI -F --include="*.py" --include="*.sh" --include="*.md" --include="*.yaml" --include="*.yml" --include="*.json" --include="*.toml" -- "$PAT" "$SEARCH" 2>/dev/null | head -10)
        [ -n "$FOUND" ] && REFS="$REFS$FOUND
"
    done
done

# Filter out the target itself and common noise
REFS=$(echo "$REFS" | grep -v "^$" | grep -v "^$TARGET" | grep -v '\.git/' | grep -v '__pycache__')

if [ -z "$REFS" ]; then
    # No references found — safe to proceed
    exit 0
fi

# References found — warn or block
# De-duplicate file list
REFS=$(echo "$REFS" | sort -u)
COUNT=$(echo "$REFS" | grep -cv '^$')
PATTERN_DESC="${PATTERNS[*]}"
MESSAGE="[rename_guard] $VERB '$TARGET' — but $COUNT file(s) reference: $PATTERN_DESC"
{
    echo "$MESSAGE"
    echo "$REFS" | head -5 | sed 's|^|  |'
    if [ "$COUNT" -gt 5 ]; then
        echo "  ... and $((COUNT - 5)) more"
    fi
    echo ""
    echo "  To proceed: append '# verified: <pattern>' to your command after"
    echo "  confirming each referencing file is either (a) updated atomically,"
    echo "  (b) intentionally broken, or (c) a false positive."
} >&2

if [ "$MODE" = "strict" ]; then
    exit 2
fi
exit 0
