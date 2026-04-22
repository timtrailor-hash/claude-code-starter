# Setup instructions for Claude Code

**This document is written for a Claude Code session to read and execute interactively with a human user.** Not a checklist for the human to work through alone. The Claude session is expected to pause for input at each decision point, write files on the user's behalf, and verify that each step succeeded before moving on.

If you are the human and you want to do this by hand, the same information is in `docs/setup-manual.md` (if present) or walk the same sequence yourself.

---

## Role for Claude

You are setting up a Claude Code operating environment on the user's machine using this repository as the template. Your job is:

1. Check prerequisites.
2. Ask the user which components they want installed.
3. Set up Keychain entries for secrets (never write secrets to files).
4. Copy the selected hooks, skills, rules, and Model Context Protocol (MCP) launchers into the user's `~/.claude/` directory.
5. Install Python dependencies for the memory server.
6. Run `verify.sh` to confirm the install is clean.
7. Point the user at `docs/first-use.md` to start actually using it.

Work methodically. After each stage, state what you just did and what is next. Do not batch multiple stages silently.

---

## Stage 1: Prerequisites check

Before doing anything, check the user's machine:

```bash
# macOS version and architecture
sw_vers
uname -m

# Python 3.11+ — required for memory server and scenarios
python3 --version
/opt/homebrew/bin/python3.11 --version 2>/dev/null || echo "No Homebrew python 3.11 installed"

# Node 20+ — required if user wants custom MCP launchers or Astro blog
node --version

# Homebrew — required for most of the above
which brew

# macOS Keychain CLI — always present on macOS
which security
```

If any of these are missing:
- Python 3.11+: `brew install python@3.11`
- Node 20+: `brew install node`
- Homebrew: https://brew.sh

Ask the user to install them and come back. Do not proceed with anything missing.

---

## Stage 2: Ask the user what they want

Present a short menu and get their picks:

1. **Core (always installed)**: the four skills (`/review`, `/debate`, `/autonomous`, `/dream`), the generic hooks, the rule templates, the memory server.
2. **Optional components**:
   - GitHub MCP integration (if they want Claude to read/write GitHub issues and repos)
   - Cloudflare integration (if they want to manage DNS or deploy a blog later)
   - Scenario tests (recommended — they are the verification layer)

Default to installing everything unless the user says otherwise.

Also ask:
- **What name prefix should LaunchAgents use?** The default in this repo is `com.example.*`. Most people use their reverse-domain (e.g. `com.johndoe.*`). Record the answer; you will substitute it into `machines/example-mac/services.yaml` and the verify.sh pattern.
- **Which directory should become the user's project root?** Common choice: `~/code`. Remember this; subsequent steps reference it.

---

## Stage 3: Keychain setup

Secrets live in the user's login Keychain, not in files. Do **not** accept secrets as arguments to bash commands (they would end up in shell history).

Create the Keychain service:

```bash
# One-time: seed the keychain service. Service name is up to the user; default "my-credentials".
# Then for each API key, prompt the user to paste it into an `add-generic-password` invocation THEY run,
# not one you run with the value in the command line.
```

Tell the user to run each of these themselves (substituting real keys):

```bash
security add-generic-password -a ANTHROPIC_API_KEY -s my-credentials -w 'PASTE_HERE' -U
security add-generic-password -a GEMINI_API_KEY    -s my-credentials -w 'PASTE_HERE' -U
security add-generic-password -a OPENAI_API_KEY    -s my-credentials -w 'PASTE_HERE' -U
security add-generic-password -a PERPLEXITY_API_KEY -s my-credentials -w 'PASTE_HERE' -U
```

If they do not have all four keys, the core setup still works but the `/debate` skill requires at least Gemini and OpenAI, and the `/perplexity` integration requires Perplexity.

Verify after each: `security find-generic-password -a ANTHROPIC_API_KEY -s my-credentials -w > /dev/null && echo ok`.

---

## Stage 4: Copy the configuration into the user's home directory

The user's Claude Code configuration lives in `~/.claude/`. This repository holds the template version. Copy the relevant pieces:

```bash
mkdir -p ~/.claude/{hooks,rules,skills,agents,mcp-launchers}

# Hooks
cp .claude/hooks/*.sh ~/.claude/hooks/
chmod +x ~/.claude/hooks/*.sh

# Rules
cp .claude/rules/*.md ~/.claude/rules/

# Skills
cp -r .claude/skills/* ~/.claude/skills/

# MCP launchers (if selected in Stage 2)
cp .claude/mcp-launchers/*.sh ~/.claude/mcp-launchers/
chmod +x ~/.claude/mcp-launchers/*.sh
```

After copying:
- Open `~/.claude/rules/operational.md` and `~/.claude/rules/security.md` and let the user edit them for their own preferences. These are the default rules Claude Code loads globally, so treat changes here seriously.

---

## Stage 5: Memory server

The memory server indexes your Claude Code session transcripts so you can search your own history.

```bash
cd memory-server
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Tell the user where their JavaScript Object Notation Lines (JSONL) transcripts live.
# Typically: ~/.claude/projects/-Users-<username>-<projectname>/
ls ~/.claude/projects/ 2>/dev/null
```

Ask the user to pick which projects' transcripts the memory server should index. Add that as an environment variable or configuration entry in `memory_server.py`'s constants.

Start the server once manually to confirm it runs, then ctrl-C. It will be added to the user's Claude Code Model Context Protocol (MCP) config in Stage 7.

---

## Stage 6: Settings file

Write a `~/.claude/settings.json` with the MCP launchers the user selected. Example content:

```json
{
  "permissions": {
    "allow": ["Bash", "Read", "Write", "Edit", "Glob", "Grep"]
  },
  "mcpServers": {
    "memory": {
      "type": "stdio",
      "command": "/opt/homebrew/bin/python3.11",
      "args": ["<PATH_TO>/memory-server/memory_server.py"]
    }
  },
  "hooks": {
    "SessionStart": [
      { "hooks": [
        { "type": "command", "command": "bash ~/.claude/hooks/validate_hooks.sh", "timeout": 10 }
      ]}
    ],
    "PreToolUse": [
      { "hooks": [
        { "type": "command", "command": "bash ~/.claude/hooks/credential_leak_hook.sh", "timeout": 5 }
      ]}
    ]
  }
}
```

Tailor the hooks listed here based on what the user wants enforced. Everything is additive — start minimal, add more later.

---

## Stage 7: Verify

Run the scenario suite to confirm hooks are wired correctly:

```bash
cd <PATH_TO_THIS_REPO>
/opt/homebrew/bin/python3.11 -m pytest scenarios/ -v
```

Expect: pytest reports all passed (typically around ten to thirty tests depending on which components are installed). If anything fails, report the specific failure to the user and fix it before calling the setup complete.

Run `bash verify.sh --quick` as a second-layer check on the hooks-wiring.

---

## Stage 8: Hand off

Report to the user:
- What was installed where.
- What was skipped and why.
- Any tests that failed and what it means.
- Point them at `docs/first-use.md`.

Do not declare setup complete if any verification step failed.

---

## What not to do

- **Never write a secret to a file.** Keychain only.
- **Never commit `credentials.py`.** The `.gitignore` already excludes it but do not let the user add the file to a repository manually.
- **Do not install printer-safety or hardware-specific hooks.** Those live elsewhere because they need careful per-device configuration.
- **Do not auto-load LaunchAgents.** Creating the `.plist` files is fine; `launchctl bootstrap` requires explicit user approval in operational.md rules.
- **Do not run `sudo` anywhere during setup.** Nothing here requires root.
