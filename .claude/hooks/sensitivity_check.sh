#!/bin/bash
# Sensitivity classifier for /review and /chatgpt and /debate skills.
#
# Usage:
#   bash sensitivity_check.sh <file_or_diff_paths...>
#
# Reads file paths and (if available) diff content from stdin or arguments.
# Returns:
#   exit 0 + prints "tier=mini" if change is routine
#   exit 0 + prints "tier=full reason=<why>" if change is sensitive
#
# This is a heuristic, not a perfect detector. False positives (treating
# something as sensitive when it isn't) are fine — they just waste a few
# cents on a more careful review. False negatives are NOT fine — they let
# dangerous changes ship under-reviewed.
#
# Sensitivity triggers (any one matches → full tier):
#   1. Path patterns: printer/<printer_firmware>/Moonraker, credentials, settings.json,
#      hooks, LaunchAgents, mcp-launchers, .github/workflows, daemons, cron
#   2. Diff content: dangerous gcode, sudo, rm -rf, drop table, FIRMWARE_RESTART,
#      SAVE_CONFIG, KeepAlive, launchctl bootstrap/bootout, secret patterns
#   3. File-count: ≥10 files changed → architectural

set -uo pipefail

INPUT="${*:-}"
if [ -z "$INPUT" ]; then
    INPUT=$(cat 2>/dev/null || true)
fi

# 1. Sensitive PATH patterns (case-insensitive regex)
SENSITIVE_PATHS_RE='(printer|klipper|moonraker|credentials\.py|settings\.json|\.claude/hooks/|\.claude/agents/|LaunchAgents/|\.plist|mcp-launcher|\.github/workflows/|daemon|crontab|sv08|bambu|snapmaker|sudo|firmware)'

if printf '%s\n' "$INPUT" | grep -qiE "$SENSITIVE_PATHS_RE"; then
    HIT=$(printf '%s\n' "$INPUT" | grep -iE "$SENSITIVE_PATHS_RE" | head -1)
    echo "tier=full reason=path:$HIT"
    exit 0
fi

# 2. Sensitive CONTENT patterns — need actual diff text via git
# If we have file paths and a git repo, fetch the diff
DIFF=""
if [ -d .git ] || git rev-parse --git-dir >/dev/null 2>&1; then
    # Check staged + unstaged diff content
    DIFF=$(git diff HEAD 2>/dev/null; git diff --cached 2>/dev/null)
fi

DANGEROUS_CONTENT_RE='(FIRMWARE_RESTART|RESTART[^_a-zA-Z]|SAVE_CONFIG|G28|BED_MESH_CALIBRATE|QUAD_GANTRY_LEVEL|PROBE\b|sudo |rm -rf|DROP TABLE|TRUNCATE|KeepAlive|launchctl (bootstrap|bootout|kickstart|load|unload)|sk-[a-zA-Z0-9]{20}|BEGIN (RSA |EC )?PRIVATE KEY|ANTHROPIC_API_KEY\s*=\s*["'"'"'][^"'"'"']{20})'

if [ -n "$DIFF" ] && printf '%s' "$DIFF" | grep -qE "$DANGEROUS_CONTENT_RE"; then
    HIT=$(printf '%s' "$DIFF" | grep -E "$DANGEROUS_CONTENT_RE" | head -1 | cut -c1-80)
    echo "tier=full reason=content:$HIT"
    exit 0
fi

# 3. File count ≥10
FILE_COUNT=$(printf '%s\n' "$INPUT" | wc -l | tr -d ' ')
if [ "$FILE_COUNT" -ge 10 ] 2>/dev/null; then
    echo "tier=full reason=files:$FILE_COUNT"
    exit 0
fi

echo "tier=mini"
exit 0
