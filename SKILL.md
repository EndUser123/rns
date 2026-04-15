---
name: rns
description: Dynamic actions from findings w/ recover/prevent/realize tags, priority, file:line. Converts unstructured LLM output to selectable RNS actions.
version: 1.3.0
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
suggest: []
workflow_steps:
  - collect_input: Gather text from session transcript or inline input
  - extract_actions: Parse recommendations, findings, gaps
  - verify_gates: Run mandatory pre-emission gates (verifiability, no over-extraction, completeness, no fabrication)
  - classify_findings: Assign domain, action, priority, effort
  - check_dependencies: Identify causal relationships
  - render_rns: Format as domain-grouped selectable actions
  - present_selection: Display with "0 — do all" footer
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

If no text is provided, RNS will analyze the full session transcript (current session plus any carryover items from the session chain).

> **Implementation note**: `/rns` is LLM-executed only — it has no CLI or standalone Python script. The skill reads the session transcript via `lib/chain.py` and renders RNS output directly.

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

### Gap Coverage (for structured inputs like gap tables)

When processing structured inputs (skill-audit gap tables, pre-mortem findings), each row must receive an explicit **disposition**:

| Disposition | Meaning | When to Use |
|-------------|---------|-------------|
| **MAPPED** | Gap has a corresponding RNS action item | Default — if the gap needs action |
| **REJECTED** | Gap is valid but intentionally not acted on | Out of scope, already handled elsewhere, or risk accepted with rationale |
| **DEFERRED** | Gap is valid but deferred to future session | Named owner + trigger condition required |

Render gap coverage as a `📋 GAP COVERAGE` section after domain groups and before the do-all footer:
```
📋 GAP COVERAGE (7 items)
  5 MAPPED → see actions above
  1 REJECTED — "MECHANISM_LEAKAGE: hardcoded @gitready is low-risk branding, not a functional issue"
  1 DEFERRED — "ASSURANCE: AGENTS.template.md deferred to /skill-ship (owns skill wiring)"
```

**Rule**: Severity alone is NOT a valid exclusion. MEDIUM/LOW items require explicit REJECTED or DEFERRED disposition, not silence.

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

### Source B — Current session context (if no inline text)
If called alone (`/rns`), extract action items from the **current conversation context** (the LLM already has all user/assistant messages in context). Process the full conversation for action items — do not limit to the last message only.

Only fall back to transcript file reading when the conversation context is insufficient (e.g., session restored from compact with limited context).

**Transcript fallback** (`lib/chain.py`):
```python
import sys
from pathlib import Path
# Resolve skill-root-relative to avoid CWD-dependency import failures
sys.path.insert(0, str(Path(__file__).parent))
from lib.chain import get_session_transcript_text
text = get_session_transcript_text()  # Use only when context-first approach fails
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

## Step 2 — Mandatory Pre-Emission Verification Gates

Every action item must pass these gates before it appears in RNS output. An item that fails a gate is either: (a) verified and emitted, (b) marked `[UNVERIFIED]` and emitted, or (c) dropped. It is **never emitted as a verified-sounding item without passing a gate**.

### Gate A — Verifiability Check

For every action item, one of:

- **VERIFIED**: You personally confirmed the file, symbol, line number, or behavior exists in the current codebase this session (via Read, Grep, Glob, or Bash with actual output).
- **[UNVERIFIED]**: The item is plausible but you did not confirm it. Mark it `[UNVERIFIED]` in the action line. The `[UNVERIFIED]` tag is a safety net, not a license to skip Gate B.

**Required verification for gap claims**: Any item that claims something is "missing", "doesn't exist", "not implemented", or "no helper for X" requires a concrete existence check (grep, glob, or file read) before emission. A gap claim without a check is automatically `[UNVERIFIED]`.

**Required verification for file:line citations**: If you cite `@ file:line`, you must have seen the relevant code in this session. If you cite a line number, the number must come from actual tool output, not from memory or assumption.

### Gate B — No Over-Extraction Check

Ask: "What would a weaker model over-extract here and turn into noisy action spam?"

Before each item:
- Is this a genuine gap or a speculative extrapolation?
- Would this item survive if I re-read the source material?
- Could this item be a false positive from the analysis?

Drop any item that is primarily inferred rather than derived from the source material.

### Gate C — Completeness Check

[COMPLETENESS] Have **all** input rows/items been accounted for? Each must have exactly one disposition: MAPPED (has an action above), REJECTED (explicit rationale), or DEFERRED (named owner + trigger). Severity alone is NOT a valid exclusion criterion.

### Gate D — No Fabrication Check

Do NOT emit an item that claims:
- A specific file or symbol exists without grep/glob confirming it
- A gap exists without checking for existing code that might fill it
- A line number you did not personally see in tool output this session

If a finding cannot be verified or made concrete, phrase it generically with `[UNVERIFIED]` rather than inventing specifics.

---

**When all gates fail**: If you cannot verify a finding and cannot phrase it safely, drop the item rather than emit it as verified noise.

### Self-Check Prompts (reference)

These prompts inform the gates above — use them to pressure-test each item:

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

- **Do NOT fabricate file paths or line numbers.** Only cite where evidence supports it. A `@ file:line` without personal tool confirmation is a gate violation.
- **Gap claims require verification.** Any item claiming something is "missing", "doesn't exist", or "not implemented" must pass Gate A before emission. If unverified, mark `[UNVERIFIED]` or drop — never emit as verified.
- If a finding cannot be made concrete (no file, no scope), phrase it generically but still include it with `[UNVERIFIED]`.
- Do NOT skip findings because they're "obvious" — include everything.
- Do NOT invent severity ratings not present in the source. Infer only when the source implies but doesn't label.

### Background Command Display Behavior

**Known Issue**: When RNS generates output while a background command is running, Claude Code may re-display the assistant's message when the background command completes. This can cause the RNS output to appear twice.

**Avoidance Pattern**: To prevent double-display:
1. Complete all background operations BEFORE generating RNS output
2. Avoid using `run_in_background=true` for commands that analyze the current session's transcript
3. If background commands are necessary for session chain analysis, run them synchronously or capture results to a file before rendering

**Example pattern**:
```python
# BAD - causes double display
background_cmd = Bash(..., run_in_background=True)
render_rns_output()  # Generates output while background runs
# Background completion → re-displays output

# GOOD - no double display
result = Bash(...)  # Run synchronously
render_rns_output()  # Output after everything completes
```
