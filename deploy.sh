#!/bin/bash
# deploy.sh — atomic control-plane deployment with auto-rollback
#
# Usage:
#   ./deploy.sh           # deploy to current machine
#   ./deploy.sh --dry-run # show what would change without applying
#   ./deploy.sh --force   # skip verify gate (DANGEROUS — use only for recovery)
#
# Flow:
#   1. Pre-deploy verify (unless --force)
#   2. Snapshot current state to /tmp/deploy_snapshot_<timestamp>/
#   3. Apply symlinks, settings, LaunchAgents, crontab
#   4. Reload touched LaunchAgents (bootout + bootstrap)
#   5. Post-deploy verify — auto-rollback on failure
#   6. Inventory reconciliation + live-acceptance gate
#   7. Report

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
SHARED="$REPO_DIR/shared"
DRY_RUN=0
FORCE=0
DEPLOY_START_TS=$(date +%s)
SNAPSHOT_DIR=""
TOUCHED_PLISTS=()

for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        --force) FORCE=1 ;;
    esac
done

# Detect machine
HOSTNAME_SHORT=$(hostname -s)
case "$HOSTNAME_SHORT" in
    *mini*|*Mini*) MACHINE="mac-mini" ;;
    *)             MACHINE="laptop" ;;
esac
MACHINE_DIR="$REPO_DIR/machines/$MACHINE"
LA_SUBDIR="$HOME/Library/LaunchAgents"

echo "=== deploy.sh ==="
echo "Machine: $MACHINE ($HOSTNAME_SHORT)"
echo "Repo: $REPO_DIR"
echo "Dry run: $DRY_RUN"
echo

# ── Auto-rollback function ──
auto_rollback() {
    echo
    echo "!!! AUTO-ROLLBACK triggered !!!"
    if [ -z "$SNAPSHOT_DIR" ] || [ ! -d "$SNAPSHOT_DIR" ]; then
        echo "ERROR: No snapshot available for rollback."
        exit 1
    fi
    echo "Restoring from: $SNAPSHOT_DIR"

    for sub in hooks rules agents mcp-launchers skills; do
        if [ -d "$SNAPSHOT_DIR/$sub" ]; then
            rm -rf "$HOME/.claude/$sub"
            cp -R "$SNAPSHOT_DIR/$sub" "$HOME/.claude/$sub"
            echo "  Restored: ~/.claude/$sub"
        fi
    done

    if [ -f "$SNAPSHOT_DIR/settings.json" ]; then
        cp "$SNAPSHOT_DIR/settings.json" "$HOME/.claude/settings.json"
        echo "  Restored: ~/.claude/settings.json"
    fi

    if [ -d "$SNAPSHOT_DIR/launchagents" ]; then
        for plist in "$SNAPSHOT_DIR/launchagents"/*.plist; do
            [ -f "$plist" ] || continue
            name=$(basename "$plist")
            if cp "$plist" "$LA_SUBDIR/$name" 2>/dev/null; then
                echo "  Restored: $name"
                label="${name%.plist}"
                launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
                launchctl bootstrap "gui/$(id -u)" "$LA_SUBDIR/$name" 2>/dev/null || true
            else
                echo "  WARN: Could not restore $name (permission denied)"
            fi
        done
    fi

    echo "Rollback complete."
    exit 1
}

# ── Pre-deploy verification (unless --force) ──
if [ "$FORCE" = "0" ] && [ -f "$REPO_DIR/verify.sh" ]; then
    echo "--- Pre-deploy verify ---"
    if ! bash "$REPO_DIR/verify.sh" --quick; then
        echo "ABORT: pre-deploy verification failed. Fix issues or use --force."
        exit 1
    fi
fi

# ── Step 1: Snapshot current state ──
if [ "$DRY_RUN" = "0" ]; then
    SNAPSHOT_DIR="/tmp/deploy_snapshot_$(date +%Y%m%d_%H%M%S)"
    mkdir -p "$SNAPSHOT_DIR"
    echo "--- Snapshot: $SNAPSHOT_DIR ---"

    for sub in hooks rules agents mcp-launchers skills; do
        if [ -e "$HOME/.claude/$sub" ]; then
            if [ -L "$HOME/.claude/$sub" ]; then
                cp -RL "$HOME/.claude/$sub" "$SNAPSHOT_DIR/$sub"
            else
                cp -R "$HOME/.claude/$sub" "$SNAPSHOT_DIR/$sub"
            fi
        fi
    done

    if [ -f "$HOME/.claude/settings.json" ]; then
        cp "$HOME/.claude/settings.json" "$SNAPSHOT_DIR/settings.json"
    fi

    if [ "$MACHINE" = "mac-mini" ] && [ -d "$LA_SUBDIR" ]; then
        mkdir -p "$SNAPSHOT_DIR/launchagents"
        for plist in "$LA_SUBDIR"/com.example.*.plist; do
            [ -f "$plist" ] && cp "$plist" "$SNAPSHOT_DIR/launchagents/"
        done
    fi

    echo "  Snapshot complete"
fi

CHANGES=0

BACKUP_DIR="$HOME/.claude/.deploy-backups"
mkdir -p "$BACKUP_DIR"

# ── Step 2: Apply — Symlink shared directories ──
for sub in rules hooks agents mcp-launchers; do
    SRC="$SHARED/$sub"
    DST="$HOME/.claude/$sub"
    [ -d "$SRC" ] || continue

    if [ -L "$DST" ] && [ "$(readlink "$DST")" = "$SRC" ]; then
        echo "  $sub: already linked"
    elif [ -d "$DST" ] && [ ! -L "$DST" ]; then
        if [ "$DRY_RUN" = "1" ]; then
            echo "  $sub: WOULD replace directory with symlink → $SRC"
        else
            mv "$DST" "$BACKUP_DIR/${sub}.pre-deploy-$(date +%s)"
            ln -s "$SRC" "$DST"
            echo "  $sub: replaced with symlink (old backed up)"
            CHANGES=1
        fi
    else
        if [ "$DRY_RUN" = "1" ]; then
            echo "  $sub: WOULD create symlink → $SRC"
        else
            mkdir -p "$(dirname "$DST")"
            ln -sf "$SRC" "$DST"
            echo "  $sub: linked"
            CHANGES=1
        fi
    fi
done

# Skills: symlink each skill dir individually
if [ -d "$SHARED/skills" ]; then
    mkdir -p "$HOME/.claude/skills"
    for skill_dir in "$SHARED/skills"/*/; do
        skill_name=$(basename "$skill_dir")
        DST="$HOME/.claude/skills/$skill_name"
        if [ -L "$DST" ] && [ "$(readlink "$DST")" = "$skill_dir" ]; then
            : # already linked
        elif [ -d "$DST" ] && [ ! -L "$DST" ]; then
            if [ "$DRY_RUN" = "1" ]; then
                echo "  skill/$skill_name: WOULD replace with symlink"
            else
                mv "$DST" "$BACKUP_DIR/skill-${skill_name}.pre-deploy-$(date +%s)"
                ln -s "$skill_dir" "$DST"
                echo "  skill/$skill_name: replaced with symlink"
                CHANGES=1
            fi
        else
            if [ "$DRY_RUN" = "1" ]; then
                echo "  skill/$skill_name: WOULD link"
            else
                ln -sf "$skill_dir" "$DST"
                CHANGES=1
            fi
        fi
    done
    echo "  skills: $(ls "$SHARED/skills" | wc -l | xargs) linked"
fi

# Apply machine-specific settings.json
if [ -f "$MACHINE_DIR/settings.json" ]; then
    SETTINGS_DST="$HOME/.claude/settings.json"
    if diff -q "$MACHINE_DIR/settings.json" "$SETTINGS_DST" >/dev/null 2>&1; then
        echo "  settings.json: unchanged"
    else
        if [ "$DRY_RUN" = "1" ]; then
            echo "  settings.json: WOULD update"
            diff "$SETTINGS_DST" "$MACHINE_DIR/settings.json" | head -20
        else
            cp "$MACHINE_DIR/settings.json" "$SETTINGS_DST"
            echo "  settings.json: updated"
            CHANGES=1
        fi
    fi
fi

# Deploy printer_config.toml
if [ -f "$SHARED/config/printer_config.toml" ]; then
    PRINTER_CFG_DST="$HOME/.claude/printer_config.toml"
    if diff -q "$SHARED/config/printer_config.toml" "$PRINTER_CFG_DST" >/dev/null 2>&1; then
        echo "  printer_config.toml: unchanged"
    else
        if [ "$DRY_RUN" = "1" ]; then
            echo "  printer_config.toml: WOULD update"
        else
            cp "$SHARED/config/printer_config.toml" "$PRINTER_CFG_DST"
            echo "  printer_config.toml: updated"
            CHANGES=1
        fi
    fi
fi

# Mac Mini only: apply LaunchAgents
if [ "$MACHINE" = "mac-mini" ] && [ -d "$MACHINE_DIR/launchagents" ]; then
    for plist in "$MACHINE_DIR/launchagents"/*.plist; do
        name=$(basename "$plist")
        if diff -q "$plist" "$LA_SUBDIR/$name" >/dev/null 2>&1; then
            : # unchanged
        else
            if [ "$DRY_RUN" = "1" ]; then
                echo "  launchagent/$name: WOULD update"
            else
                # Pattern 12 hardening: plists are chflags uchg. Toggle.
                chflags nouchg "$LA_SUBDIR/$name" 2>/dev/null || true
                cp "$plist" "$LA_SUBDIR/$name"
                chflags uchg "$LA_SUBDIR/$name" 2>/dev/null || true
                echo "  launchagent/$name: updated"
                TOUCHED_PLISTS+=("$name")
                CHANGES=1
            fi
        fi
    done
    echo "  launchagents: $(ls "$MACHINE_DIR/launchagents" | wc -l | xargs) managed"
fi

# ── Step 3: Reload touched LaunchAgents ──
if [ "$DRY_RUN" = "0" ] && [ "${#TOUCHED_PLISTS[@]}" -gt 0 ]; then
    echo
    echo "--- Reloading ${#TOUCHED_PLISTS[@]} touched LaunchAgent(s) ---"
    GUI_DOMAIN="gui/$(id -u)"
    for plist_name in "${TOUCHED_PLISTS[@]}"; do
        label="${plist_name%.plist}"
        plist_path="$LA_SUBDIR/$plist_name"
        echo "  Reloading: $label"
        launchctl bootout "$GUI_DOMAIN/$label" 2>/dev/null || true
        sleep 1
        launchctl bootstrap "$GUI_DOMAIN" "$plist_path" 2>/dev/null || true
    done
fi

# Mac Mini only: apply crontab
if [ "$MACHINE" = "mac-mini" ] && [ -f "$MACHINE_DIR/crontab.txt" ]; then
    CURRENT=$(crontab -l 2>/dev/null || true)
    DESIRED=$(cat "$MACHINE_DIR/crontab.txt")
    if [ "$CURRENT" = "$DESIRED" ]; then
        echo "  crontab: unchanged"
    else
        if [ "$DRY_RUN" = "1" ]; then
            echo "  crontab: WOULD update"
        else
            echo "$DESIRED" | crontab -
            echo "  crontab: updated"
            CHANGES=1
        fi
    fi
fi

echo
if [ "$DRY_RUN" = "1" ]; then
    echo "DRY RUN — no changes applied"
    exit 0
fi

# ── Step 4: Post-deploy verification with auto-rollback ──
if [ "$CHANGES" -gt "0" ]; then
    echo "Changes applied. Running post-deploy verify..."
    if [ -f "$REPO_DIR/verify.sh" ]; then
        if ! bash "$REPO_DIR/verify.sh" --quick; then
            echo
            echo "FAIL: Post-deploy verify failed!"
            auto_rollback
        fi
    fi
else
    echo "No changes needed — system matches repo"
fi

# Post-deploy system inventory reconciliation
if [ -f "$REPO_DIR/shared/lib/system_inventory.sh" ] && [ "$MACHINE" = "mac-mini" ]; then
    echo
    echo "--- Post-deploy inventory reconciliation ---"
    if ! bash "$REPO_DIR/shared/lib/system_inventory.sh" 2>&1 | tail -30; then
        echo
        echo "WARN: deploy applied but inventory reconciliation found drift."
        echo "  Investigate declared-vs-live differences above."
    fi
fi

# Post-deploy live-acceptance gate (only rollback if we made changes)
if [ -f "$REPO_DIR/shared/lib/live_acceptance.sh" ]; then
    echo
    echo "--- Post-deploy live-acceptance gate ---"
    if ! bash "$REPO_DIR/shared/lib/live_acceptance.sh" "$DEPLOY_START_TS"; then
        if [ "$CHANGES" -gt "0" ]; then
            echo
            echo "FAIL: Live-acceptance gate failed after changes!"
            auto_rollback
        else
            echo
            echo "WARN: Live-acceptance gate failed but no changes were made — skipping rollback."
        fi
    fi
fi

echo
echo "Deploy successful. Snapshot preserved at: ${SNAPSHOT_DIR:-N/A}"
