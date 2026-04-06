# RNS — Recommended Next Steps from Arbitrary Output

[![Claude Code](https://img.shields.io/badge/Claude%20Code-Ready-purple)](https://claude.com/claude-code)
[![Version](https://img.shields.io/badge/Version-1.2.0-blue)](.claude/skills/rns/SKILL.md)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

**RNS** extracts actionable recommendations from any LLM output — post-mortems, critiques, reviews, analysis, or plain text — and renders them as a selectable, numbered action list.

## Quick Start

```
/rns {optional pasted text or @reference}
```

If no text is provided, RNS analyzes the most recent LLM output in the conversation.

**Example output:**
```
1 🔧 QUALITY (2)
  1a [recover/high] Fix concurrent save registry integrity test @ test_critique_io_concurrent.py:89
  1b [prevent/med] Add Phase 2/3 filename round-trip tests @ test_critique_io.py

2 📄 DOCS (1)
  2a [realize/low] Update SKILL.md with Phase 1 completion gate @ SKILL.md

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

0 — Do ALL Recommended Next Actions (3 items)
```

## See The Transformation

| Before RNS | After RNS |
|-----------|-----------|
| Buried implicit actions in long text | Numbered, domain-grouped actions (1a, 1b, 2a…) |
| No severity or domain clarity | recover/prevent/realize × critical/high/medium/low |
| Unstructured findings | File refs (@ file:line) attached automatically |
| No carryover across sessions | Prior session items surface as CARRYOVER |

## What RNS Does

**Input → Structured Actions.** RNS parses LLM output through two extraction paths:

- **Path A** — Explicit RNS tags (`[recover/high] QUAL-001 Fix something @ file:89`)
- **Path B** — Heuristic fallback when no tags found; extracts from signal keywords and severity labels, marks items `[UNVERIFIED]`

**Output formats:**
- Text (human-readable, selectable)
- Machine (pipe-delimited, `<!-- format: machine -->`, for downstream skills)

**Domain grouping:** 🔧 quality | 🧪 tests | 📄 docs | 🔒 security | ⚡ performance | 🐙 git | 📦 deps | 📌 other

## What Gets Created

```
skill/
  SKILL.md              ← Skill definition + usage guide
lib/
  chain.py              ← Session chain traversal, action extraction
  render.py             ← Formatting engine
tests/
  test_chain.py         ← 27 tests
  test_render.py        ← 37 tests
references/
  self-rns-example.md   ← Built output example
```

## Development and Deployment

**Local installation (skill dev):**
```powershell
# Junction to skill directory (no admin required on Windows)
New-Item -ItemType Junction -Path "$env:USERPROFILE/.claude/skills/rns" -Target "P:/.claude/skills/rns"
```

**Running tests:**
```bash
python -m pytest tests/ --tb=short -q
# → 64 passed (0.89s)
```

## Changelog

See [CHANGELOG](CHANGELOG.md) for version history.

## License

MIT License. See [LICENSE](LICENSE).
