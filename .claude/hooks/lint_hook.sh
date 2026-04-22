#!/bin/bash
# PostToolUse lint hook — fast, offline, no semgrep.
# Wired into settings.json for matchers: Edit, Write.
#
# Runs ONLY fast offline tools per file:
#   - .py     → ruff check (offline, ~50ms)
#   - .sh     → shellcheck (offline, ~20ms)
#   - .swift  → swiftlint lint --quiet (offline, ~200ms)
#
# Semgrep was deliberately REMOVED from this hook because --config=auto
# makes a network call on every Edit/Write, adding 1-5s latency and
# breaking offline. Semgrep now lives in the /review skill where it runs
# on demand against staged changes only.
#
# Behaviour:
# - Reads tool input safely from stdin (NO shell interpolation — pipe to python via stdin)
# - Skips non-source files and venv/build/cache directories
# - Logs findings to ~/.claude/lint_findings.log
# - Currently advisory (exit 0). Flip last line to `[ -n "$FINDINGS" ] && exit 2 || exit 0`
#   to make it blocking once tuned.

set -uo pipefail

LOG=~/.claude/lint_findings.log
mkdir -p "$(dirname "$LOG")"

# Read hook input safely — pipe to python via stdin, do NOT interpolate
INPUT=$(cat 2>/dev/null || printf '{}')

FILE=$(printf '%s' "$INPUT" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
    ti = data.get("tool_input", {})
    print(ti.get("file_path") or ti.get("filePath") or "")
except Exception:
    print("")
' 2>/dev/null)

[ -z "$FILE" ] && exit 0
[ ! -f "$FILE" ] && exit 0

# Skip non-source files and noisy paths
case "$FILE" in
    *.md|*.json|*.txt|*.yml|*.yaml|*.toml|*.lock|*.log|*.csv|*.png|*.jpg|*.jpeg|*.pdf|*.docx|*.svg|*.ico|*.pyc|*.so|*.dylib|*.o|*.a|*.zip|*.gz|*.tar)
        exit 0 ;;
    */venv/*|*/.venv/*|*/node_modules/*|*/.git/*|*/__pycache__/*|*/build/*|*/.build/*|*/DerivedData/*|*/Pods/*)
        exit 0 ;;
esac

FINDINGS=""
TS=$(date "+%Y-%m-%d %H:%M:%S")

# Ruff (Python only) — fast, offline
if [[ "$FILE" == *.py ]] && command -v ruff >/dev/null 2>&1; then
    RUFF_OUT=$(ruff check --quiet "$FILE" 2>&1 || true)
    if [ -n "$RUFF_OUT" ]; then
        FINDINGS+="--- ruff ---
$RUFF_OUT
"
    fi
fi

# Shellcheck (Bash) — fast, offline
if [[ "$FILE" == *.sh ]] && command -v shellcheck >/dev/null 2>&1; then
    SC_OUT=$(shellcheck -f gcc "$FILE" 2>&1 || true)
    if [ -n "$SC_OUT" ]; then
        FINDINGS+="--- shellcheck ---
$SC_OUT
"
    fi
fi

# SwiftLint (Swift) — fast, offline (no analyzer rules in lint mode)
if [[ "$FILE" == *.swift ]] && command -v swiftlint >/dev/null 2>&1; then
    SL_OUT=$(swiftlint lint --quiet --reporter emoji "$FILE" 2>&1 || true)
    if [ -n "$SL_OUT" ]; then
        FINDINGS+="--- swiftlint ---
$SL_OUT
"
    fi
fi

if [ -n "$FINDINGS" ]; then
    {
        echo "[$TS] $FILE"
        printf '%s\n' "$FINDINGS"
        echo "---"
    } >> "$LOG"

    # Surface to Claude via stderr
    echo "lint findings for $FILE (full log: ~/.claude/lint_findings.log):" >&2
    printf '%s\n' "$FINDINGS" >&2
fi

exit 0
