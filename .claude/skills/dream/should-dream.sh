#!/usr/bin/env bash
# should-dream.sh — Check if memory consolidation should run.
# Returns 0 if dream should run, 1 if not.
# Adapted for Tim's memory system (native Claude Code + custom topics).

set -euo pipefail

MEMORY_DIR="$HOME/.claude/projects/-Users-<user>-code/memory"
LAST_DREAM_FILE="$MEMORY_DIR/.last-dream"

# First run — dream has never happened
if [[ ! -f "$LAST_DREAM_FILE" ]]; then
    echo "Dream conditions met: first-run (no .last-dream found)"
    exit 0
fi

# Check: 24+ hours since last consolidation
LAST_DREAM=$(cat "$LAST_DREAM_FILE")
NOW=$(date +%s)
ELAPSED=$(( NOW - LAST_DREAM ))
HOURS_ELAPSED=$(( ELAPSED / 3600 ))

if (( HOURS_ELAPSED < 24 )); then
    exit 1  # Too soon
fi

echo "Dream conditions met: ${HOURS_ELAPSED}h since last dream"
exit 0
