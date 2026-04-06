---
name: rns
description: Dynamic actions from findings w/ recover/prevent/realize tags, priority, file:line. Converts unstructured LLM output to selectable RNS actions.
version: 1.2.0
triggers:
  - "/rns"
  - "/rns {text}"
  - "turn this into actions"
  - "extract action items"
  - "what should I do about"
  - "RNS"
supports_multiple: true  # multiple findings per input; simultaneous invocations deduplicate by (description_hash, domain, action)
enforcement: advisory
persistence: none
scope: session
---

# RNS — Recommended Next Steps from Arbitrary Output

## Purpose

Convert any LLM output into a structured Recommended Next Steps (RNS) format with selectable actions. When you get output you don't like — or that has implicit actions buried in it — use `/rns` to extract and enumerate them.

## When to Use

- Output contains findings, recommendations, or implied actions
- User says "turn this into actions" or "what should I do about X"
- Long output with multiple distinct action items
- Post-mortem, critique, review, or analysis output with gaps to fix

## How to Use

```
/rns {optional pasted text or @reference}
```

If no text is provided, RNS will analyze the most recent LLM output in the conversation.

## Output Format

RNS outputs a **dynamic-domain, flat-numbered** action list:

```
1 🔧 QUALITY (2)
  1a [recover/high] Fix concurrent save registry integrity test @ test_critique_io_concurrent.py:89
  1b [prevent/med] Add Phase 2/3 filename round-trip tests @ test_critique_io.py

2 📄 DOCS (1)
  2a [realize/low] Update SKILL.md with Phase 1 completion gate @ SKILL.md

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

0 — Do ALL Recommended Next Actions (N items)
```

### Format Rules

| Aspect | Rule |
|--------|------|
| **Domain grouping** | Dynamic — only domains with findings appear |
| **Section headers** | Emoji + domain name + domain number (e.g. "🔧 QUALITY (1)") — rendered as text, no fences |
| **Item numbering** | Domain-numbered — 1a, 1b, 2a, 3a within domain groups |
| **Item format** | `{domain-num}{sub-letter} [effort] [R:reversibility] Description @ file:line` (e.g. 1a, 1b, 2a) |
| **File references** | `@ file:line` suffix when available |
| **Do All directive** | 0 — Do ALL Recommended Next Actions (N items) |

### Domain Emoji Mapping

| Domain | Emoji |
|--------|-------|
| quality / code_quality | 🔧 |
| tests / testing | 🧪 |
| docs / documentation | 📄 |
| security | 🔒 |
| performance | ⚡ |
| git | 🐙 |
| deps / dependencies | 📦 |
| other | 📌 |

## Step 1 — Collect Input

RNS tries three sources in order, stopping at the first that yields content:

### Source A — Inline text (if provided)
If `/rns {text}` was called with inline text, use that directly.

### Source B — Session transcript (if no inline text)
If called alone (`/rns`), read the **full session transcript** to extract action items from all assistant messages. Do not limit to the last message only.

**Transcript source** (`lib/chain.py`):
```python
from lib.chain import get_session_transcript_text
text = get_session_transcript_text()  # returns all user+assistant messages
```

If the transcript is unavailable or empty, log a warning and proceed to Source C.

### Source C — Compact-restore state (fallback)
If both inline text and transcript are empty, read the compact-restore context directly:
1. Check for `compact_restore` in the session environment
2. If found, extract action items from the pending state (5 pending operations, active files, investigation context)
3. If no compact-restore state exists, return the empty-input error

**Do not ask the user to re-run commands or paste content** — if you can read it, read it.

### Source D — File reference (if @file provided)
If a file path is provided (e.g., `@p3.md`), read that file.

### Session Chain Integration (carryover items)

When no inline text is provided, also walk the session handoff chain to extract RNS-formatted action items from prior sessions:

```python
from lib.chain import get_current_rns_items
current_items, carryover_items = get_current_rns_items()
```

- `current_items` = action items extracted from the current session's transcript
- `carryover_items` = action items from prior sessions in the handoff chain

**Input signals to extract actions from:**
- Explicit recommendations ("you should X", "consider Y")
- Implicit gaps ("missing Z", "doesn't handle W")
- Problem statements ("X is broken", "Y fails when Z")
- Severity ratings (CRITICAL, HIGH, MEDIUM, LOW)
- Findings labeled with IDs (COMP-001, TEST-001, etc.)
- Anything the user has expressed dissatisfaction with

## Step 2 — Classify Each Finding

For each action item extracted, classify:

| Field | Values | How to Determine |
|-------|--------|------------------|
| **Domain** | quality, tests, docs, security, performance, git, deps, other | What type of work is needed |
| **Action** | recover, prevent, realize | recover=fix something broken; prevent=guard against future failure; realize=capture opportunity/extension |
| **Priority** | critical > high > medium > low | Explicit label or implied severity |
| **Effort** | ~2min, ~5min, ~15min, ~30min, ~1hr | Estimated from scope |
| **Reversibility** | 1.0–2.0 score | See Reversibility Scale below |
| **Verified** | [UNVERIFIED] marker | Path B (heuristic extraction) items are marked `[UNVERIFIED]` since they are inferred, not confirmed. Path A items (explicit RNS tags) have no marker. |

## Action-Extraction Prompts

Before emitting RNS output, `/rns` should run a short internal action-extraction check:

- What item here is still a finding or complaint rather than an actionable next step?
- What actions are duplicates, symptoms, or consequences of the same root issue?
- What action would become unsafe or misleading if the transcript, compact state, or cited artifact is stale?
- What recommendation is too vague to select and execute without guesswork?
- What dependency, ordering rule, or ownership boundary is still implicit?
- What action should be split because "0 — do all" would otherwise bundle unrelated work?
- What severity or effort estimate am I inferring too confidently from weak evidence?
- What recommendation belongs to a different owning skill, not the current executor?
- What would a weaker model over-extract here and turn into noisy action spam?
- What part of this output would be hard to reverse if the action is wrong?

These are internal self-check prompts. They are not default user-facing questions and should only surface to the user when `/rns` is genuinely blocked and cannot proceed safely without clarification.

## Step 3 — Check for Dependencies

Some findings may be related. Look for:
- `[caused-by: ID]` — finding is a consequence of another (use singular form)
- `[blocks: ID]` — finding prevents another from being resolved

When dependencies exist, order them so cause-before-effect.

## Step 4 — Render RNS

Group findings by domain. Sort each domain by action (recover → prevent → realize), then by priority (critical → high → medium → low).

If a finding has dependencies, render dependency annotation on the line after the finding.

**Carryover items from prior sessions:** If `carryover_items` is non-empty, render them under a `📌 CARRYOVER` section grouped by domain. These are action items extracted from the handoff chain's prior sessions that may need to be re-acknowledged in the current session.

Example carryover rendering:
```
2 📌 CARRYOVER (2 sessions in chain)
  2a [recover/high] QUAL-003 Fix auth token expiry @ auth.py:45 (from session a1b2c...)
```

## Step 5 — Present with Selection Semantics

Selection is handled by the renderer (`lib/render.py`). The output ends with `0 — Do ALL Recommended Next Actions (N items)` — nothing follows after that line.

## Step 6 — Completeness Check

After all selected actions are executed, check whether documentation needs updating:

**For DOCS domain items**: Already self-documenting — no further action needed.

**For implementation items (🔧 QUALITY, 🧪 TESTS, etc.)**: Before marking complete, ask:
- Were docstrings updated if the function/class contract changed?
- Were README files updated if user-facing behavior changed?
- Were related documentation files updated?

If any documentation gaps exist and they would not be addressed in the current session, emit a follow-up DOCS item:
```
📄 DOCS
  [realize/low] DOC-N Update {doc file} with {change description}
```

**Rule**: Documentation updates done in the same session as implementation are strongly preferred. If implementation and docs are split across sessions, flag the doc gap explicitly.

### Machine-Parseable Format (Optional)

For downstream skill chaining, append `<!-- format: machine -->` to the output to render pipe-delimited records:

```
RNS|D|1|domain-label|emoji
RNS|A|1a|domain|E:5|recover/high|action description|file:line
RNS|Z|0|NONE
```

Where: `RNS|D|` = domain header, `RNS|A|` = action item, `RNS|Z|` = terminator. Fields: `domain-num|action-num|[domain|E:effort|action/priority|description|file:line]`.

## Error Handling

| Scenario | Behavior |
|---------|----------|
| Empty input (no text, no file, transcript empty, no compact-restore) | Return: "Nothing to analyze. Pass inline text, a @file path, or ensure the session transcript is available." |
| No extractable findings | Return: "No actionable findings found. Try `/rns {pasted text}` with output that contains recommendations or gaps." |
| No RNS tags but substantive text (signal keywords or >200 chars) | Path B heuristic extraction activates — items marked `[UNVERIFIED]` since inferred, not confirmed |
| Referenced file does not exist | Log as warning, skip item, include in RNS as orphaned with warning tag |
| Unresolved dependency ID | Report as orphaned dependency note below the affected item |
| Duplicate findings (same description, domain, action) | Deduplicate — keep the one with higher priority or severity |
| Transcript unreadable | Fall back to compact-restore state. If that also fails, return the empty-input error above. |

## Constraints

- Do NOT fabricate file paths or line numbers. Only cite where evidence supports it.
- If a finding cannot be made concrete (no file, no scope), phrase it generically but still include it.
- Do NOT skip findings because they're "obvious" — include everything.
- Do NOT invent severity ratings not present in the source. Infer only when the source implies but doesn't label.
