# /dream — Memory Consolidation

> Consolidate memory files: prune stale content, merge related insights,
> convert relative dates, resolve contradictions, keep MEMORY.md lean.

## Trigger

- Manual: `/dream`
- Auto: Stop hook checks 24h elapsed → sets `.dream-pending` flag →
  next session sees flag in CLAUDE.md and runs `/dream` as subagent.

## Tim's memory system (DO NOT use generic paths)

- **MEMORY.md**: `~/.claude/projects/-Users-<user>-code/memory/MEMORY.md`
- **Topic files**: `~/.claude/projects/-Users-<user>-code/memory/topics/`
- **Archive**: `~/.claude/projects/-Users-<user>-code/memory/topics/archive/`
- **Session transcripts**: `~/.claude/projects/-Users-<user>-code/*.jsonl`
- **Feedback files**: `topics/feedback_*.md` (16+ files, behavioural rules)
- **Lessons**: `topics/lessons.md` (17+ error patterns)
- **Git repo**: `origin git@github-memory:<user>-hash/tim-memory.git`

MEMORY.md is loaded into every session's system prompt. Keep it under 200 lines.

## Phase 1: ORIENT

1. Read `MEMORY.md` — note line count, topic file references, staleness.
2. Run `~/code/tim-claude-controlplane/shared/hooks/memory_index_diff.sh --strict`
   to verify index integrity BEFORE making changes.
3. `ls topics/` — count files, note any not in the index.
4. Check `.last-dream` timestamp: `cat topics/../.last-dream 2>/dev/null`

Output: mental map of what exists, what's stale, what's missing.

## Phase 2: GATHER SIGNAL

Scan recent sessions (last 7 days) for consolidation signals:

```bash
find ~/.claude/projects/-Users-<user>-code/ -name "*.jsonl" -mtime -7 2>/dev/null | sort -r | head -20
```

For each recent session, grep (not full-read) for:

- **Corrections**: `"actually|no,|wrong|stop doing|don't do|correction"`
- **Preferences**: `"I prefer|always use|never use|from now on|remember that"`
- **Decisions**: `"let's go with|decided|we're using|the plan is|switch to"`
- **Recurring patterns**: `"again|every time|keep forgetting|as usual"`

Read ONLY the matching lines + surrounding context. Extract:
- The fact (what was said)
- The date (from file mtime, converted to absolute ISO 8601)
- Confidence (explicit instruction = high, implied = medium)
- Contradictions with existing memory

## Phase 3: CONSOLIDATE

Rules (in priority order):

1. **Never duplicate.** Check existing topic files before adding. Update, don't duplicate.
2. **Convert relative dates to absolute.** "yesterday" in a March 15 session → "2026-03-14".
3. **Delete contradicted facts.** Add note: `(Updated YYYY-MM-DD, previously: X)`.
4. **Preserve source.** `(from session YYYY-MM-DD)` on new entries.
5. **Respect topic file structure.** Tim uses specific topic files (printer.md,
   <proprietary_model>.md, school-governors.md, etc.) — route findings to the RIGHT file.
   Don't create generic "preferences.md" or "decisions.md" — those belong in the
   specific topic files. New feedback → `topics/feedback_*.md` with proper frontmatter.
6. **Don't touch feedback_claudecode_deprecated.md.** It's a HARD RULE file.

### Feedback file format (if creating new feedback):
```markdown
---
name: Short descriptive name
description: One-line description — used to decide relevance
type: feedback
---

The rule itself.

**Why:** The reason.
**How to apply:** When/where this kicks in.
```

## Phase 4: PRUNE & INDEX

1. **MEMORY.md must stay under 200 lines.** If over, move inline content to topic files.
2. **Each index entry = one line.** Format: `| \`topics/file.md\` | One-line summary |`
3. **Remove entries for files that don't exist.** Run memory_index_diff.sh to verify.
4. **Archive stale topics.** If a topic file hasn't been referenced in 90+ days
   and has no recent session matches, move to `topics/archive/`.
5. **Update feedback count** in the `topics/feedback_*.md` row if files were added.

### Record the dream:
```bash
date +%s > ~/.claude/projects/-Users-<user>-code/memory/.last-dream
rm -f ~/.claude/.dream-pending
```

### Commit if changes were made:
```bash
cd ~/.claude/projects/-Users-<user>-code/memory
git add -A
git diff --cached --quiet || git commit -m "Dream consolidation $(date +%Y-%m-%d)"
git push origin main 2>/dev/null || true
```

## Verification

After running, verify:
1. `wc -l MEMORY.md` — must be under 200 lines
2. `memory_index_diff.sh --strict` — must exit 0
3. No relative dates remain in any topic file
4. No duplicate entries across topic files
5. Print summary: entries added, updated, archived, contradictions resolved

## Safety

- **Back up before first run:** `tar -czf /tmp/memory-pre-dream-$(date +%s).tar.gz -C ~/.claude/projects/-Users-<user>-code memory`
- **Dry run on first use:** Read all 4 phases, print what you WOULD change, confirm before applying.
- **Never delete without replacement.** Removed entries must be either contradicted (replaced) or archived (moved).
