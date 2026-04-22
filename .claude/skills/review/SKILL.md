---
name: review
description: "Run the full pre-commit review pipeline — ruff + semgrep + code-reviewer subagent + dual independent reviewers (Gemini + ChatGPT). Use before any commit, after any non-trivial edit, and as the standard quality gate."
user-invocable: true
disable-model-invocation: false
---

# /review — pre-commit quality gate (triple-reviewer)

You are running Tim's standard code review pipeline. This is the gate that should run before every commit.

## Pipeline

Three independent reviewers run on every `/review`:

1. **Static analysis** — ruff + semgrep + shellcheck on the changed files
2. **Claude code-reviewer subagent** — applies the lessons.md 8-point checklist
3. **Dual independent reviewers** — Gemini 2.5 Pro AND ChatGPT (GPT-5.4 family) called in parallel for true cross-model review

The combined output is a consolidated APPROVE / CHANGES REQUESTED / BLOCK verdict.

## Arguments

`$ARGUMENTS` controls scope and depth:
- empty / `staged` — review `git diff --cached`
- `unstaged` — review `git diff`
- `head` — review `git show HEAD`
- `<path>` — review a specific file or directory
- `+mini` — force the cheaper model variants (gemini-2.5-flash + gpt-5.4-mini) for both reviewers
- `+full` — force the expensive variants (gemini-2.5-pro + gpt-5.4) for both reviewers
- `+claude-only` — skip Gemini and ChatGPT (cheap mode)

By default, model selection is auto:
- **<200 changed lines AND not sensitive** → mini variants
- **≥200 changed lines** → full variants
- **Sensitive change** (any line count) → full variants — overrides line count

A change is "sensitive" if `~/.claude/hooks/sensitivity_check.sh` flags it. The classifier looks at:
1. **File paths**: anything matching printer/<printer_firmware>/Moonraker, credentials.py, settings.json, ~/.claude/hooks/, ~/.claude/agents/, LaunchAgents/, .plist, mcp-launchers, .github/workflows/, daemons, crontab, sv08/bambu/snapmaker, firmware
2. **Diff content**: dangerous gcode (FIRMWARE_RESTART, SAVE_CONFIG, G28, BED_MESH_CALIBRATE, QUAD_GANTRY_LEVEL, PROBE), `sudo`, `rm -rf`, `DROP TABLE`, `KeepAlive`, `launchctl bootstrap/bootout/load/unload`, hardcoded API keys, BEGIN PRIVATE KEY
3. **File count**: ≥10 files changed → architectural

If any of those match, the review uses full models regardless of line count. False positives are fine — wasting a few cents on a careful review beats missing a real bug.

## Steps

### 1. Determine scope and tier

Run `git status` and `git diff --stat` (or matching command for the requested scope). If nothing to review, stop and say so.

Pick the tier in this order (first match wins):
1. If `+full` flag: tier=full
2. If `+mini` flag: tier=mini
3. Run sensitivity classifier: `git diff --name-only HEAD | bash ~/.claude/hooks/sensitivity_check.sh`. If it returns `tier=full reason=...`, use full and surface the reason in the report.
4. Otherwise: count changed lines. ≥200 → full, else mini.

Always print the chosen tier and the reason in the final report so Tim can see why.

### 2. Run static analysis

For Python files in scope:
```bash
ruff check <files>
ruff format --check <files>
```

For shell scripts in scope:
```bash
shellcheck -f gcc <files>
```

For Swift files:
```bash
swiftlint lint --quiet <files>
```

For multi-language SAST (only if you have time and the diff is non-trivial):
```bash
semgrep --config=auto --error <files>
```

Collect all findings.

### 3. Run the code-reviewer subagent

Launch the `code-reviewer` subagent via the Agent tool with a clear prompt that includes:
- The scope being reviewed
- The git diff
- A request for the standard verdict format

### 4. Run BOTH independent reviewers in parallel (unless +claude-only)

Launch BOTH reviewers concurrently via two parallel tool calls in a single message:

**Reviewer A — Gemini** (use the `/gemini` skill or call directly):
- Model: `gemini-2.5-pro` (full) or `gemini-2.5-flash` (mini)
- Same context document, same review prompt

**Reviewer B — ChatGPT** (use the `/chatgpt` skill or call directly):
- Model: `gpt-5.4` (full) or `gpt-5.4-mini` (mini)
- Same context document, same review prompt

Use the same review prompt for both so their verdicts are comparable. Write the context once to `/tmp/review_context.md` and reference it from both calls.

### 5. Synthesize all four reviews

Combine into a single report:
```
=== /review report ===
Scope: <files>
Model tier: mini | full
Lines changed: <N>

LINTERS:
  ruff:       <pass | N issues>
  shellcheck: <pass | N issues>
  swiftlint:  <pass | N issues>
  semgrep:    <pass | N issues>

CLAUDE CODE-REVIEWER:  <APPROVE | CHANGES | BLOCK>
  <top findings>

GEMINI 2.5 (model):    <AGREE | PARTIAL | DISAGREE>
  <top findings>

CHATGPT GPT-5.4 (model): <AGREE | PARTIAL | DISAGREE>
  <top findings>

CONVERGENT findings (multiple reviewers flagged):
  <list>

DIVERGENT findings (only one reviewer flagged):
  <list>

OVERALL: APPROVE | CHANGES REQUESTED | BLOCK
Reasoning: <one paragraph synthesis>
```

### 6. Decision rule

- **BLOCK** if ≥2 reviewers say BLOCK, or if any reviewer flags a printer-safety/credential-leak issue
- **CHANGES REQUESTED** if ≥2 reviewers say CHANGES, or if any single reviewer says BLOCK
- **APPROVE** only if all reviewers APPROVE/AGREE

Convergent findings (≥2 reviewers flag the same thing) carry more weight than divergent ones — but a single reviewer flagging a real bug is still a real bug, so don't dismiss divergent findings.

## Cost notes

- `+claude-only`: free (your Claude session)
- mini (default for small diffs): ~$0.06 per review (Gemini Flash + GPT-5.4-mini)
- full (default for big diffs): ~$0.15 per review (Gemini Pro + GPT-5.4)
- `+full` on small diffs: same as full

If Tim is reviewing a one-line fix, use `+mini` or `+claude-only`. If reviewing today's quality-toolchain remediation work, full is correct.

## Important

- This skill is invoked by Tim before committing. Be terse — no preamble.
- Never auto-fix linter issues without showing Tim first.
- ALWAYS run both Gemini and ChatGPT in parallel (two tool calls in a single message). Sequential is wasteful.
- If either reviewer's API fails, continue with the other and note the failure in the synthesis.
- If both reviewers fail, return CHANGES REQUESTED with the failure noted — never APPROVE without at least one independent reviewer.
