# Claude Code Starter Kit

A snapshot of the control-plane, hooks, skills, and memory system I run around Anthropic's Claude Code. Published so you can copy what is useful and ignore what is not.

This is not a product. There is no support. Expect to edit things.

## What this gives you

A working scaffold for treating Claude Code as a personal operating environment, not just a coding assistant. Specifically:

- **Four core skills**: `/review`, `/debate`, `/autonomous`, `/dream`. Pre-commit reviews, three-way multi-model debates for high-stakes decisions, retry-loop runners for work that needs to complete while you are away, and periodic memory consolidation.
- **A set of generic hooks** that convert text rules into enforcement: credential-leak detection on file writes, protected-path guards, rename-guard, session-manifest tracking, config-integrity checks, a lint hook, and an audit log. These fire at the Claude Code lifecycle stages that matter.
- **A memory server** with dual-tier semantic plus keyword search over your own session history. Empty on first run. Indexes as you use it.
- **Control-plane shell**: `deploy.sh` with atomic deploys and auto-rollback, `verify.sh` with pytest scenarios that feed real Claude Code JavaScript Object Notation (JSON) payloads into hooks and assert correct allow/deny behaviour, plus `rollback.sh` and `diff-live.sh` for deployment hygiene.
- **Scenario tests** covering Artificial Intelligence (AI) safety classes (memory injection, supply-chain), credential safety, and cross-machine drift.
- **Two rule templates** (operational, security) you can adapt to your own setup.

## What you need first

Before the setup assistant can do anything useful:

- **macOS**. Parts of this assume macOS launchd, macOS Keychain, and Homebrew. Linux users can adapt but will do real work.
- **Python 3.11+** and **Node.js 20+**.
- **A Claude Code Pro or Max subscription** (for the orchestrating Claude that will walk you through setup and that runs day to day).
- **API keys** for at least: Anthropic (if you want API calls beyond your subscription), Gemini, OpenAI, Perplexity. The `/debate` skill in particular needs Gemini and OpenAI for the multi-model pattern to work.
- **Optional: an Apple Developer account** if you want to build the companion Transport-Layer Security (TLS)-secured iOS terminal app (separate repository, linked below).
- **Optional: Cloudflare** for a custom domain plus Pages hosting if you want your own writing home.

## How to use this repo

The intended workflow is that your own Claude Code session reads the `docs/setup-for-claude.md` file and walks you through setup interactively. It should ask you the right questions, put credentials into your keychain rather than files, create the directory structure, and configure the hooks and skills.

**To start:**

1. Clone this repository.
2. In your terminal, open Claude Code in the cloned directory.
3. Say: `read docs/setup-for-claude.md and walk me through the setup`.
4. Answer the questions it asks.

The setup assistant will:
- Check prerequisites (Python, Node, macOS).
- Create macOS Keychain entries for your Application Programming Interface (API) keys.
- Install Python dependencies for the memory server.
- Copy hooks into your `~/.claude/` directory.
- Write a starter `CLAUDE.md` for your project.
- Run `verify.sh` to confirm everything is wired.

If you would rather read and do the setup yourself, start with `docs/architecture.md` for an overview, then `docs/setup-for-claude.md` for the step list, then `docs/first-use.md` for what to do once you are running.

## What is NOT in this repo

By design:

- **No credentials.** Nothing in this repository is secret. Your keys stay in your Keychain or environment.
- **No personal content.** My memory history, writing, and private notes are not here. The memory system ships empty.
- **No hardware-specific skills.** Printer safety hooks, Computer Aided Manufacturing (CAM) workflows, and similar hardware integrations are stripped out because they need custom work anyway.
- **No proprietary logic.** Anything tied to specific employer work is excluded.
- **No iOS app source code.** That is a separate repository, linked below.

If you want to see the full version of this setup, complete with my own content and the bits that are too specific to share here, there is a Google Docs technical manual linked from my [personal site](https://timtrailor.com/posts/a-personal-ai-operating-environment).

## Companion repositories

- **iOS terminal app**: a Secure Shell (SSH) and Claude Code chat client for iPhone. Fresh version without my bundle identifier and push credentials. *(separate release — link here when published)*
- **Example personal skills**: small working examples of skills that do real work (not in this repo because they are opinionated).

## Project layout

```
├── README.md                   You are here
├── deploy.sh                   Atomic deploy with auto-rollback
├── verify.sh                   Runs scenarios, hook validation, drift checks
├── rollback.sh                 Revert last deploy
├── diff-live.sh                Show drift between repo and installed state
├── .claude/
│   ├── hooks/                  Generic enforcement hooks
│   ├── rules/                  Templates for operational and security rules
│   ├── skills/                 /review /debate /autonomous /dream
│   ├── mcp-launchers/          Keychain-backed Model Context Protocol (MCP) launchers
│   └── agents/                 (empty, for your own subagents)
├── memory-server/              Dual-tier search memory system
│   ├── memory_server.py
│   ├── requirements.txt
│   └── README.md
├── machines/
│   └── example-mac/
│       ├── services.yaml       Declare LaunchAgents here
│       ├── hosts-manifest.yaml
│       └── launchagents/       (empty, you add .plist files)
├── scenarios/                  pytest tests that exercise the hooks
│   ├── ai_safety/
│   ├── credentials/
│   ├── drift/
│   └── hooks/
├── credentials.example.py      Keychain loader pattern
├── docs/
│   ├── architecture.md
│   ├── setup-for-claude.md     ← your Claude reads this
│   └── first-use.md
└── LICENSE                     MIT
```

## Honest warnings

- **This is a snapshot.** It reflects how my setup looked when I published it. I am not maintaining it as a project. Issues are not likely to be fixed.
- **It is opinionated.** Everything here reflects specific decisions I made for specific reasons. You will disagree with some of them. Good. Change them.
- **It is macOS-shaped.** Some of it will not work on Linux without real effort.
- **The interesting bits are the patterns, not the code.** If you take only one thing, take the principle that text rules fail under pressure and structural enforcement is the fix. The specific hooks in this repository are examples of that principle; your own hooks will look different because your priorities are different.

## Credits

Built collaboratively with Claude. The architectural patterns and the receipt-driven mindset were the Claude sessions writing back their own lessons. This document was written that way too.

## License

MIT. Use it, fork it, strip it, ignore it.
