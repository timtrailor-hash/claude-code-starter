#!/bin/bash
# diff-live.sh — show delta between repo state and live system
set -uo pipefail
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== diff-live.sh ==="
echo "Comparing repo state to live ~/.claude/ on $(hostname -s)"
echo

DIFFS=0
for sub in rules hooks agents mcp-launchers; do
    REPO="$REPO_DIR/shared/$sub"
    LIVE="$HOME/.claude/$sub"
    [ -d "$REPO" ] || continue
    if [ -L "$LIVE" ]; then
        TARGET=$(readlink "$LIVE")
        if [ "$TARGET" = "$REPO" ]; then
            echo "$sub: symlinked ✓"
        else
            echo "$sub: WRONG symlink → $TARGET (expected $REPO)"
            DIFFS=1
        fi
    elif [ -d "$LIVE" ]; then
        RESULT=$(diff -rq "$REPO" "$LIVE" 2>/dev/null | head -20)
        if [ -n "$RESULT" ]; then
            echo "$sub: DIVERGED"
            echo "$RESULT" | sed "s/^/  /"
            DIFFS=1
        else
            echo "$sub: content matches (not symlinked but identical)"
        fi
    else
        echo "$sub: MISSING from live"
        DIFFS=1
    fi
done

echo
[ "$DIFFS" = "0" ] && echo "CLEAN — live matches repo" || echo "DRIFT DETECTED — run deploy.sh to fix"
