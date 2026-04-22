#!/bin/bash
# rollback.sh — revert to previous commit and redeploy, or restore a snapshot
#
# Usage:
#   ./rollback.sh              # interactive — confirm before reverting HEAD
#   ./rollback.sh --yes        # non-interactive — skip prompts
#   ./rollback.sh -y           # alias for --yes
#   ./rollback.sh --snapshot PATH  # restore from a specific deploy snapshot
#   ./rollback.sh --yes --snapshot PATH  # non-interactive snapshot restore

set -euo pipefail
REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
LA_SUBDIR="$HOME/Library/LaunchAgents"
cd "$REPO_DIR"

YES=0
SNAPSHOT=""

for arg in "$@"; do
    case "$arg" in
        --yes|-y) YES=1 ;;
        --snapshot)
            # Next arg is the path — handled below
            ;;
        *)
            # If previous arg was --snapshot, this is the path
            if [ "${PREV_ARG:-}" = "--snapshot" ]; then
                SNAPSHOT="$arg"
            fi
            ;;
    esac
    PREV_ARG="$arg"
done

# If --snapshot not given but positional looks like a snapshot dir, use it
if [ -z "$SNAPSHOT" ] && [ "${1:-}" != "--yes" ] && [ "${1:-}" != "-y" ] && [ -d "${1:-}" ]; then
    SNAPSHOT="$1"
fi

if [ -n "$SNAPSHOT" ]; then
    # ── Snapshot-based rollback ──
    if [ ! -d "$SNAPSHOT" ]; then
        echo "ERROR: Snapshot directory not found: $SNAPSHOT"
        exit 1
    fi

    if [ "$YES" = "0" ]; then
        echo "Will restore from snapshot: $SNAPSHOT"
        read -p "Proceed? (y/n) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "Cancelled"
            exit 0
        fi
    fi

    echo "Restoring from snapshot: $SNAPSHOT"
    RESTORED=0

    for sub in hooks rules agents mcp-launchers skills; do
        if [ -d "$SNAPSHOT/$sub" ]; then
            rm -rf "$HOME/.claude/$sub"
            cp -R "$SNAPSHOT/$sub" "$HOME/.claude/$sub"
            echo "  restored: ~/.claude/$sub"
            RESTORED=$((RESTORED + 1))
        fi
    done

    if [ -f "$SNAPSHOT/settings.json" ]; then
        cp "$SNAPSHOT/settings.json" "$HOME/.claude/settings.json"
        echo "  restored: ~/.claude/settings.json"
        RESTORED=$((RESTORED + 1))
    fi

    if [ -d "$SNAPSHOT/launchagents" ]; then
        for plist in "$SNAPSHOT/launchagents"/*.plist; do
            [ -f "$plist" ] || continue
            name=$(basename "$plist")
            if cp "$plist" "$LA_SUBDIR/$name" 2>/dev/null; then
                label="${name%.plist}"
                launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
                launchctl bootstrap "gui/$(id -u)" "$LA_SUBDIR/$name" 2>/dev/null || true
                echo "  restored+reloaded: $name"
                RESTORED=$((RESTORED + 1))
            else
                echo "  WARN: could not restore $name (permission denied)"
            fi
        done
    fi

    if [ "$YES" = "1" ]; then
        echo "status=success restored=$RESTORED snapshot=$SNAPSHOT"
    else
        echo "Restored $RESTORED items from $SNAPSHOT"
    fi
    exit 0
fi

# ── Git-based rollback ──
echo "Current HEAD: $(git log --oneline -1)"
echo "Will revert to: $(git log --oneline -1 HEAD~1)"

if [ "$YES" = "0" ]; then
    read -p "Proceed? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Cancelled"
        exit 0
    fi
fi

git revert HEAD --no-edit
bash "$REPO_DIR/deploy.sh"

if [ "$YES" = "1" ]; then
    echo "status=success method=git-revert"
else
    echo "Rolled back and redeployed"
fi
