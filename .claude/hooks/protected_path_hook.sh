#!/bin/bash
# Claude Code pre-command hook: for risky operations, request explicit user
# approval via permissionDecision: "ask" rather than hard-blocking with exit 2.
#
# Protected targets: ~/Library/LaunchAgents, ~/Library/LaunchDaemons,
# /Library/, /etc/, launchctl state changes, sudo reboot/shutdown, chflags,
# dangerous printer gcode via SSH/curl, pushes to public repos.
#
# Emits a PreToolUse JSON decision ("ask") so Claude Code prompts Tim to
# approve or deny. Exit 0 with no JSON = pass through to default handling.

INPUT=$(cat)

COMMAND=$(echo "$INPUT" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    print(data.get('tool_input', {}).get('command', ''))
except:
    print('')
" 2>/dev/null)

if [ -z "$COMMAND" ]; then
    exit 0
fi

ask() {
    python3 -c "
import json, sys
print(json.dumps({
    'hookSpecificOutput': {
        'hookEventName': 'PreToolUse',
        'permissionDecision': 'ask',
        'permissionDecisionReason': sys.argv[1]
    }
}))" "$1"
    exit 0
}

# Pattern 1: Commands touching LaunchAgent/LaunchDaemon plist files
if echo "$COMMAND" | grep -qE '(Library/LaunchAgents|Library/LaunchDaemons)'; then
    # Allow read-only commands straight through
    if echo "$COMMAND" | grep -qE '^(cat |ls |plutil -p |plutil -lint |head |tail |wc |file |stat |md5 |shasum )'; then
        exit 0
    fi
    ask "Command writes to LaunchAgent/LaunchDaemon plist. Approve to proceed."
fi

# Pattern 1b: launchctl read-only (list, print) — always allowed
if echo "$COMMAND" | grep -qE 'launchctl\s+(list|print)'; then
    exit 0
fi

# Pattern 2: launchctl state-changing commands
if echo "$COMMAND" | grep -qE 'launchctl\s+(bootstrap|bootout|kickstart|load|unload|enable|disable)'; then
    ask "launchctl state-changing command. Approve to proceed."
fi

# Pattern 3: plutil -extract without -o (destructive — overwrites source file)
if echo "$COMMAND" | grep -qE 'plutil\s+-extract' && ! echo "$COMMAND" | grep -qE '\-o\s'; then
    ask "plutil -extract without -o overwrites the source file. Approve to proceed."
fi

# Pattern 4: sudo reboot / shutdown / halt / init
if echo "$COMMAND" | grep -qE 'sudo\s+(-n\s+)?(reboot|shutdown|halt|init)'; then
    ask "System reboot/shutdown. Approve to proceed."
fi

# Pattern 5: writes into /etc/ or /Library/
if echo "$COMMAND" | grep -qE '(>[> ]*|tee\s+|cp\s+.*|mv\s+.*|rm\s+.*)(/etc/|/Library/)'; then
    ask "Modifies /etc or /Library system path. Approve to proceed."
fi

# Pattern 6: chflags (immutability changes)
if echo "$COMMAND" | grep -qE 'chflags\s+(no)?uchg'; then
    ask "Immutability flag change (chflags uchg/nouchg). Approve to proceed."
fi

# Pattern 7: Dangerous printer gcode via SSH or direct curl to Moonraker
# Bypasses the Moonraker allowlist — can kill an active print.
if echo "$COMMAND" | grep -qE 'ssh.*192\.168\.0\.108' || echo "$COMMAND" | grep -qE 'curl.*192\.168\.0\.108.*gcode/script'; then
    if echo "$COMMAND" | grep -qiE '(FIRMWARE_RESTART|RESTART[^_]|G28|PROBE|QUAD_GANTRY_LEVEL|BED_MESH_CALIBRATE|SAVE_CONFIG)'; then
        ask "Dangerous printer gcode can destroy an active print. Confirm print_stats.state first, then approve to proceed."
    fi
fi

# Pattern 8: git push to known public repos
if echo "$COMMAND" | grep -qE 'git\s+push.*(sv08-print-tools|ClaudeCode|claude-mobile|castle-ofsted-agent)'; then
    ask "Push to public GitHub repo. Approve to proceed."
fi

exit 0
