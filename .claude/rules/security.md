# Security Rules

## Code & Repos
- NEVER put private info in code, commits, or public repos
- Memory files are private (fine for secrets). Code files may be pushed public.
- All printer secrets live in `credentials.py` (gitignored). Public code uses `[REDACTED]` placeholders.

## Public GitHub Repos
- `<user>-hash/sv08-print-tools` — speed tools ONLY
- `<user>-hash/ClaudeCode` — native iOS app (NO hardcoded IPs or secrets)
- `<user>-hash/claude-mobile` — conversation server (credentials.py gitignored)
- `<user>-hash/castle-ofsted-agent` — governors Streamlit app

## API Key Rules
- Use `shared_utils.env_for_claude_cli()` when spawning Claude CLI — strips API key, forces subscription auth
- Use `shared_utils.get_api_key()` for direct API calls (Haiku, ofsted-agent)
- NEVER manually build env for Claude CLI — always use the shared utility
- Only Haiku/Sonnet/Gemini Flash should use API credits — never Opus via API
- Always set a spending limit on console.anthropic.com before adding credits
