#!/bin/bash
# Launcher for the GitHub MCP server.
# Reads GITHUB_TOKEN from macOS Keychain (service: tim-credentials, account: GITHUB_TOKEN)
# and exports it as GITHUB_PERSONAL_ACCESS_TOKEN before exec'ing the server.
#
# Why a launcher: secrets stay in keychain, not in settings.json.

set -euo pipefail

# Try to unlock keychain if running headless (matches credentials.py pattern)
if [ -f "$HOME/.keychain_pass" ]; then
    security unlock-keychain -p "$(cat "$HOME/.keychain_pass")" \
        "$HOME/Library/Keychains/login.keychain-db" 2>/dev/null || true
fi

TOKEN=$(security find-generic-password -a "GITHUB_TOKEN" -s "tim-credentials" -w 2>/dev/null || true)

if [ -z "$TOKEN" ]; then
    echo "github-mcp launcher: GITHUB_TOKEN not in keychain (service=tim-credentials)" >&2
    echo "Run: security add-generic-password -a GITHUB_TOKEN -s tim-credentials -w <token> -U" >&2
    exit 1
fi

export GITHUB_PERSONAL_ACCESS_TOKEN="$TOKEN"
exec /opt/homebrew/bin/github-mcp-server stdio
