---
name: debate
description: "Iterative three-way debate — Claude, Gemini, and ChatGPT all participate as equals, seeing each other's reasoning and updating positions each round until convergence or max rounds. Use for high-stakes decisions where you want a single, reasoned verdict from three independent perspectives."
user-invocable: true
disable-model-invocation: false
---

# /debate — iterative three-way debate until convergence

Where `/review` runs Gemini and ChatGPT in parallel ONCE and presents both verdicts, `/debate` runs **all three models** (Claude Opus, Gemini, ChatGPT) through **multiple rounds**, where each sees the other two's previous reasoning and updates their position, until they converge on a single verdict (or hit the max-rounds cap).

**Claude Opus participates directly** — the orchestrating session (which is already Opus on subscription) forms and defends its own position each round. No Opus API credits are spent. Gemini and ChatGPT are called via API in the Python script.

This is the right tool for irreversible decisions: architecture changes, daemon designs, deployments to production, anything where being wrong is expensive.

## Arguments

`$ARGUMENTS`:
- The scope to review (file path, diff range, "the last commit", "the printer hook plan", etc.)
- `+full` — force full models (Opus + gpt-5.4 + gemini-2.5-pro). Default for `/debate`.
- `+mini` — use mini models (Opus + gpt-5.4-mini + gemini-2.5-flash). Claude is always Opus regardless.
- `+rounds=N` — max rounds before forced termination (default 4)

Note: `/debate` defaults to **full models** because the whole point is high-stakes decisions. Use `+mini` only if you're testing the workflow itself.

## MANDATORY INPUT GATE — change impact map for live-system changes

**Added 2026-04-11 after the retro debate on the 7-phase rebuild.** The rebuild was unanimously blessed by a prior /debate, then produced four red flags on Tim's iOS app within hours of the first real check. Root cause: **/debate reviewed the design in isolation from its operational blast radius**. All three reviewers (Claude, Gemini, GPT-5.4) converged on this fix.

Before running `/debate` on anything that touches a live system (existing services, files on running machines, cross-host state, monitors, memory repos, settings.json), the orchestrating session MUST produce a `change_impact_map.md` and attach it to the context. The impact map declares every downstream consumer of every surface the change touches. `/debate` refuses to start if the map is obviously incomplete.

### What counts as "live-system impact"
Any of the following triggers the requirement:
- Editing or deleting files on Mac Mini
- Renaming paths, moving directories, refactoring file locations
- Modifying any `~/.claude/` file on either machine
- Touching `machines/<host>/settings.json`, `system_map.yaml`, `services.yaml`, `launchagents/*.plist`
- Changing any LaunchAgent script (referenced by any plist)
- Modifying `health_check.py`, `verify.sh`, `drift_check.sh`, `deploy.sh`
- Memory topic file merges or deletions

### change_impact_map.md format

Minimal acceptable format (inline in debate context, no separate file needed if short):

```markdown
## Change Impact Map

### Changed surfaces
- path/to/file1 — what's changing
- path/to/file2 — what's changing

### Downstream consumers (per surface)
For each changed surface, list every file/service/monitor that references it.
Run `grep -rl '<surface>' ~/code ~/.claude` on BOTH machines. Paste the output here.

- path/to/file1 references found:
  - consumer A (file:line) — nature of reference
  - consumer B (file:line) — nature of reference
- path/to/file2 references found: (none)

### Atomicity plan
How each consumer is updated alongside the surface change, or explicitly marked as intentionally broken.

### Rollback
Single command to revert the whole change in case of failure.
```

### Enforcement
`/debate` Step 1 (Gather context) now verifies the impact map is present and non-trivially populated. If missing or if the "Downstream consumers" section is empty for non-greenfield changes, the orchestrating session MUST stop and either (a) produce the map, or (b) explicitly justify why this is a greenfield change with no live-system impact.

This does NOT apply to pure design-review debates ("should we decompose conversation_server.py?") — those are concept-level and have no impact map until a concrete plan exists. It applies to IMPLEMENTATION debates.

## REVIEWER ROLES — one seat is "runtime / blast-radius"

**Added 2026-04-11.** In a 3-model debate, the natural bias of all three reviewers is toward critiquing the design. This leaves the operational blast radius unexamined — exactly the gap that produced tonight's failures.

From Round 1+ onward (after blind Round 0 has established independent positions), the orchestrating Claude session assigns ONE reviewer (itself or Gemini) the explicit role of **runtime / blast-radius reviewer**. That reviewer's job for the round:

1. Do NOT critique the architecture or design choices.
2. Walk the dependency graph out from every changed surface.
3. Ask: "What consumes this? What's the staleness horizon of every consumer? What's the first user-visible symptom if this change is wrong? Which existing tests would catch that symptom, and which would not?"
4. List explicitly unchecked consumers.
5. Approve only if the set of unchecked consumers is empty OR each unchecked item is explicitly risk-accepted.

The other two reviewers critique design, security, correctness as normal. The blast-radius seat is added, not substituted.

The orchestrator should rotate which model plays the blast-radius seat across debates so no single model's blind spots dominate.

## Pipeline

```
ROUND 0 (blind — anti-anchoring):
  All three form positions independently. NO model sees any other's response.
  claude  → verdict_cl0, reasoning_cl0  (Opus writes to file)
  gemini  → verdict_g0, reasoning_g0    (API, context only — no other positions)
  chatgpt → verdict_c0, reasoning_c0   (API, context only — no other positions)
  
  All positions revealed simultaneously.

if all 3 agree: DONE — unanimous on round 0 (true independent convergence)
if 2/3 agree: DONE — majority verdict (note the dissent)
else continue:

ROUND 1 (informed — the debate begins):
  Each model sees ALL THREE round-0 positions and must engage with them.
  claude  → verdict_cl1 (sees Gemini R0 + ChatGPT R0)
  gemini  → verdict_g1  (sees Claude R0 + ChatGPT R0)
  chatgpt → verdict_c1  (sees Claude R0 + Gemini R0)

if all 3 agree: DONE — unanimous
if 2/3 agree: DONE — majority verdict (note dissent)
else round 2, round 3, ...

If max rounds hit without convergence:
  Return ALL THREE final positions, mark as STUCK, escalate to Tim
```

**Anti-anchoring design**: Round 0 is blind. Gemini and ChatGPT receive ONLY the context — not Claude's position. Claude writes its position to file but the script does NOT read it. All three positions are revealed simultaneously after Round 0 completes. The debate (with cross-model visibility) starts at Round 1.

## Steps

### 1. Gather context once

Read the artifacts. Build a base prompt that includes:
- What the work is and why
- The actual diff / code / decision

Save to `/tmp/debate_context.md`.

### 2. Round 0 — blind independent positions (anti-anchoring)

All three models form positions from context alone. No model sees any other's response.

**2a. Run Gemini + ChatGPT FIRST** (via the script with `DEBATE_ROUND=0`). They receive ONLY the context — no Claude position.

**2b. Form YOUR position** — write to `/tmp/debate_claude_r0.md`. You must NOT read Gemini's or ChatGPT's Round 0 responses before writing yours. Form your view from the context alone:
- Identify the most important issues (security, correctness, drift, printer-safety)
- Defend your position with 1-3 specific technical points
- End with: `VERDICT: APPROVE | CHANGES REQUESTED | BLOCK`
- Aim for 200-400 words

**2c. NOW read all three positions** — reveal simultaneously. Check convergence.

### 3. Run Gemini + ChatGPT rounds

Save and run `/tmp/debate_round.py`. In Round 0, the script sends ONLY context (no Claude position). In Round 1+, it sends all previous positions.

```python
#!/usr/bin/env python3
"""Run one round of /debate for Gemini + ChatGPT.
Claude (Opus) participates directly from the orchestrating session — not via API.
This script handles only the two external API calls.

Round 0 (blind): Gemini and ChatGPT see ONLY context — no Claude position.
Round 1+: Each model sees all others' previous positions."""

import json, urllib.request, sys, os, threading, re, time
from collections import Counter

# Machine-aware credentials
for cand in ("~/code", "~/Documents/Claude code"):
    p = os.path.expanduser(cand)
    if os.path.exists(os.path.join(p, "credentials.py")):
        sys.path.insert(0, p)
        break
from credentials import GEMINI_API_KEY, OPENAI_API_KEY

ROUND = int(os.environ.get("DEBATE_ROUND", "0"))
TIER = os.environ.get("DEBATE_TIER", "full")

GEMINI_MODEL = "gemini-2.5-pro" if TIER == "full" else "gemini-2.5-flash"
CHATGPT_MODEL = "gpt-5.4" if TIER == "full" else "gpt-5.4-mini"

CONTEXT = open("/tmp/debate_context.md").read()

SYSTEM_PROMPT = "You are an independent technical reviewer in a multi-round three-way debate with two other AI reviewers (Claude Opus and one other). Be skeptical, specific, and willing to update your position when another reviewer makes a strong point. Always end your response with a line: 'VERDICT: APPROVE' or 'VERDICT: CHANGES REQUESTED' or 'VERDICT: BLOCK'."

VERDICT_RE = re.compile(r"VERDICT[:\s]+(APPROVE|CHANGES(?:\s+REQUESTED)?|BLOCK|AGREE|PARTIAL(?:LY\s+AGREE)?|DISAGREE)", re.I)


def read_file(path):
    try:
        return open(path).read()
    except FileNotFoundError:
        return ""


def call_gemini(prompt):
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 4096},
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=240) as r:
        d = json.loads(r.read())
        return d["candidates"][0]["content"]["parts"][0]["text"]


def call_chatgpt(prompt):
    payload = {
        "model": CHATGPT_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "max_completion_tokens": 4096,
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {OPENAI_API_KEY}"},
    )
    with urllib.request.urlopen(req, timeout=240) as r:
        d = json.loads(r.read())
        return d["choices"][0]["message"]["content"]


def extract_verdict(text):
    m = VERDICT_RE.search(text or "")
    if not m:
        return "?"
    v = m.group(1).upper()
    if "AGREE" in v and "DISAGREE" not in v and "PARTIAL" not in v:
        return "APPROVE"
    if "DISAGREE" in v:
        return "BLOCK"
    if "PARTIAL" in v or "CHANGES" in v:
        return "CHANGES"
    return v


# Build prompts based on round
BASE_PROMPT = f"""You are an independent technical reviewer. Be skeptical, specific, and concise.

This is a multi-round THREE-WAY debate with Claude Opus and one other AI reviewer. After this round, all three reviewers will see each other's reasoning.

CONTEXT:
{CONTEXT}

YOUR JOB this round:
1. Identify the most important issues (security, correctness, drift, printer-safety)
2. Rate the work — end with a line: VERDICT: APPROVE | CHANGES REQUESTED | BLOCK
3. Defend your verdict with 1-3 specific technical points

Be terse. Aim for 200-400 words. The verdict line MUST be the last line.
"""

if ROUND == 0:
    # BLIND round: context only, NO other model's position
    gp = BASE_PROMPT
    cp = BASE_PROMPT
else:
    # Informed round: each sees the other two from previous round
    cl_prev = read_file(f"/tmp/debate_claude_r{ROUND - 1}.md")
    g_prev = read_file(f"/tmp/debate_gemini_r{ROUND - 1}.md")
    c_prev = read_file(f"/tmp/debate_chatgpt_r{ROUND - 1}.md")

    gp = f"""You are continuing a multi-round THREE-WAY technical debate.

ORIGINAL CONTEXT:
{CONTEXT}

YOUR PREVIOUS RESPONSE (round {ROUND - 1}):
{g_prev}

CLAUDE OPUS (round {ROUND - 1}) PREVIOUS RESPONSE:
{cl_prev}

CHATGPT (round {ROUND - 1}) PREVIOUS RESPONSE:
{c_prev}

NOW: consider BOTH other reviewers' points carefully. Where do you agree? Where do you disagree?
- If either reviewer made a valid point you missed, UPDATE your verdict honestly.
- If your position is still correct, defend it with NEW evidence — don't just repeat yourself.

End your response with a line: VERDICT: APPROVE | CHANGES REQUESTED | BLOCK
"""
    cp = f"""You are continuing a multi-round THREE-WAY technical debate.

ORIGINAL CONTEXT:
{CONTEXT}

YOUR PREVIOUS RESPONSE (round {ROUND - 1}):
{c_prev}

CLAUDE OPUS (round {ROUND - 1}) PREVIOUS RESPONSE:
{cl_prev}

GEMINI (round {ROUND - 1}) PREVIOUS RESPONSE:
{g_prev}

NOW: consider BOTH other reviewers' points carefully. Where do you agree? Where do you disagree?
- If either reviewer made a valid point you missed, UPDATE your verdict honestly.
- If your position is still correct, defend it with NEW evidence — don't just repeat yourself.

End your response with a line: VERDICT: APPROVE | CHANGES REQUESTED | BLOCK
"""

# Call both in parallel
results = {}
errors = {}

def run_g():
    try:
        results["g"] = call_gemini(gp)
    except Exception as e:
        errors["g"] = str(e)
        results["g"] = f"GEMINI ERROR: {e}"

def run_c():
    try:
        results["c"] = call_chatgpt(cp)
    except Exception as e:
        errors["c"] = str(e)
        results["c"] = f"CHATGPT ERROR: {e}"

t1 = threading.Thread(target=run_g)
t2 = threading.Thread(target=run_c)
start = time.time()
t1.start(); t2.start(); t1.join(); t2.join()
elapsed = time.time() - start

# Write responses to files
with open(f"/tmp/debate_gemini_r{ROUND}.md", "w") as f:
    f.write(results["g"])
with open(f"/tmp/debate_chatgpt_r{ROUND}.md", "w") as f:
    f.write(results["c"])

# Read Claude's position for this round (written by orchestrating session)
cl_text = read_file(f"/tmp/debate_claude_r{ROUND}.md")
cl_v = extract_verdict(cl_text) if cl_text else "?"
g_v = extract_verdict(results["g"])
c_v = extract_verdict(results["c"])

round_label = f"Round {ROUND}" + (" (BLIND)" if ROUND == 0 else "")
print(f"{round_label} complete ({elapsed:.1f}s)")
print(f"  Claude Opus: VERDICT={cl_v}")
print(f"  Gemini ({GEMINI_MODEL}): VERDICT={g_v}")
print(f"  ChatGPT ({CHATGPT_MODEL}): VERDICT={c_v}")

if errors:
    for model, err in errors.items():
        print(f"  WARNING: {model} error: {err}")

# Check convergence
verdicts = [cl_v, g_v, c_v]
labels = ["Claude", "Gemini", "ChatGPT"]
if "?" not in verdicts:
    counts = Counter(verdicts)
    top, top_count = counts.most_common(1)[0]
    if top_count == 3:
        print(f"\n*** UNANIMOUS: {top} ***")
    elif top_count == 2:
        dissenter = labels[verdicts.index([v for v in verdicts if v != top][0])]
        print(f"\n*** MAJORITY: {top} (dissent from {dissenter}) ***")
    else:
        print("\n*** NO CONVERGENCE — all three differ ***")
else:
    print("\n*** INCOMPLETE — at least one verdict could not be parsed ***")
```

### 4. Debate loop (orchestrated by you, the Opus session)

Run this loop manually — YOU are the third debater, not a passive orchestrator:

**Round 0 (blind — all three independent):**
1. Run Gemini + ChatGPT blind: `DEBATE_ROUND=0 DEBATE_TIER=full python3 /tmp/debate_round.py`
2. Write YOUR blind position to `/tmp/debate_claude_r0.md` — do NOT read the Gemini/ChatGPT files first
3. NOW read all three Round 0 positions. Check convergence.

**Round 1+ (informed — the actual debate):**
1. Read all three previous-round positions. Genuinely consider their arguments.
2. Write your updated position to `/tmp/debate_claude_r{N}.md`. If others raised valid points, change your verdict.
3. Run: `DEBATE_ROUND={N} DEBATE_TIER=full python3 /tmp/debate_round.py`
4. Read results. Check convergence. If unanimous or 2/3 majority, stop.
5. If max rounds hit without convergence: present all three final positions and escalate to Tim.

### 5. Synthesize for Tim

After the script finishes, present:
```
=== /debate report ===
Scope: <files>
Tier: full | mini
Rounds: <N>

UNANIMOUS on round <N>: APPROVE | CHANGES REQUESTED | BLOCK
  -- or --
MAJORITY on round <N>: <verdict> (dissent from <model>)
  -- or --
NOT CONVERGED after <N> rounds — escalating to Tim
  Claude final:  <X>
  Gemini final:  <Y>
  ChatGPT final: <Z>

KEY POINTS (from final round):
- <bullet from Claude>
- <bullet from Gemini>
- <bullet from ChatGPT>

ACTION: <what to do next>
```

## Cost notes

`/debate` costs less than you'd expect because Claude Opus participates for free (subscription):
- mini, 2 rounds: ~$0.10 (only Gemini Flash + GPT-5.4-mini via API)
- mini, 4 rounds: ~$0.20
- full, 2 rounds: ~$0.30 (only Gemini Pro + GPT-5.4 via API)
- full, 4 rounds: ~$0.60

Use it for decisions worth that. For routine pre-commit checks, stick with `/review`.

## Termination conditions

The loop terminates when:
1. **Unanimous**: all three reviewers return the same verdict
2. **Majority**: two of three agree (the dissenter's reasoning is noted)
3. **Max rounds**: hit `MAX_ROUNDS` without even a majority — escalate to Tim with all three final positions
4. **API failure**: if any API errors twice in a row, terminate and report

## Important

- This is a THREE-WAY DEBATE, not a vote. All three models (Claude Opus, Gemini, ChatGPT) see each other's reasoning and update accordingly. The output is a converged verdict (unanimous or 2/3 majority) or escalation.
- **Claude Opus participates DIRECTLY** — you (the orchestrating session) ARE the Claude debater. You form your own position, write it to file, read the others' responses, and genuinely update your view each round. This gives the best possible Claude reasoning at zero API cost.
- **Round 0 is BLIND** — you must write your position BEFORE reading Gemini's or ChatGPT's. This eliminates anchoring bias. The debate (with visibility) starts at Round 1.
- Be honest in the debate. If Gemini or ChatGPT raise a valid point, change your verdict. The whole point is that three perspectives are better than one.
- Use VERDICT lines so convergence detection works. The system prompt instructs Gemini and ChatGPT to end with one. You must also end your response file with one.
- Three different training regimes (Anthropic RLHF, Google RLHF, OpenAI RLHF) means genuinely independent perspectives.
- Pair with `/review` not as replacement: `/review` for every commit, `/debate` for the once-a-week architectural decisions.
