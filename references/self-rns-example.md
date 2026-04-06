# RNS Self-Reference Example

This document demonstrates the `/rns` skill's own output format.

## Before: Unstructured LLM Output

```
I reviewed the session and found several issues:
1. The concurrent save registry test is failing intermittently
2. Phase 2 filename verification tests are missing
3. SKILL.md needs a Phase 1 completion gate
4. Path handling uses a fragile startswith check that could break on Windows
5. The exception handler at line 324 has no explanatory comment
6. The get_recent_sessions sort has no explicit key function
```

## After: /rns Extraction

```
🔧 QUALITY
  QUAL-001 [~15min] [R:1.5] Fix concurrent save registry integrity test @ test_critique_io_concurrent.py
  QUAL-002 [~15min] [R:1.5] Add Phase 2/3 filename round-trip tests @ test_critique_io.py
  QUAL-003 [~5min] [R:1.25] Replace startswith path check with is_relative_to() @ lib/critique_io.py:493
  QUAL-004 [~2min] [R:1.0] Add comment to bare except block @ lib/critique_io.py:324
  QUAL-005 [~2min] [R:1.0] Add explicit key= to get_recent_sessions sort @ lib/critique_io.py

📄 DOCS
  DOC-001 [~5min] [R:1.25] Add Phase 1 completion gate to SKILL.md @ SKILL.md

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

0 — Do ALL Recommended Next Actions (N items)
```

## Usage

```
/rns {paste unstructured output here}

/rns @path/to/file.md

/rns  (analyzes last LLM output in conversation)
```
