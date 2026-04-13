"""RNS Session Chain — cross-session action item retrieval."""

from __future__ import annotations

import json
import logging
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class CrossSessionAction:
    """An action item extracted from a prior session's RNS output."""
    domain: str
    action: str  # recover | prevent | realize
    priority: str  # critical | high | medium | low
    description: str
    file_ref: str | None = None
    session_id: str | None = None
    effort: str | None = None  # e.g. "~2min", "~5min", "~15min", "~30min", "~1hr"
    unverified: bool = False  # True for Path B (heuristic) items
    owner: str | None = None  # Who should execute this (solo dev = "me" or context name)
    done: bool = False  # True = completed (shown in DONE section with strikethrough)
    caused_by: str | None = None  # ID of action this is caused-by (dependency ordering)
    blocks: str | None = None  # ID of action this blocks (dependency ordering)


@dataclass
class ChainRNSResult:
    """RNS results augmented with cross-session carryover items."""
    # Actions from current session's last LLM output
    current_items: list[CrossSessionAction] = field(default_factory=list)
    # Actions from prior sessions (carryover from handoff chain)
    carryover_items: list[CrossSessionAction] = field(default_factory=list)
    chain_depth: int = 0


# ---------------------------------------------------------------------------
# Pattern matching for RNS action items
# ---------------------------------------------------------------------------

# Matches lines like: 1a [recover/high] Fix something @ file:line
# Also matches the shorter format: [recover/high] Fix something @ file:line
RNS_LINE_RE = re.compile(
    r'^\s*(?:(\d+[a-z])\s+)?\[([^\]]+)\]\s+(.+?)(?:\s+@\s+([^@\s]+))?\s*$'
)

# Matches domain emoji headers like: 🔧 QUALITY
DOMAIN_HEADER_RE = re.compile(r'^([🔧🧪📄🔒⚡🐙📦📌])\s+([A-Z_]+)\s*$')

# Matches "0 — Do ALL" directive
DO_ALL_RE = re.compile(r'^0\s*[-—]\s*Do ALL')


def _get_rns_skill_examples() -> set[str]:
    """Load and cache example lines from RNS SKILL.md to filter them out.

    Returns a set of line texts that are known to be examples, not real findings.
    Only filters RNS output format lines (action items, domain headers), not code examples.
    """
    if hasattr(_get_rns_skill_examples, "_cache"):
        return _get_rns_skill_examples._cache

    examples: set[str] = set()
    try:
        skill_path = Path(__file__).parent.parent.parent / ".claude" / "skills" / "rns" / "SKILL.md"
        if skill_path.exists():
            content = skill_path.read_text(encoding="utf-8")
            for line in content.splitlines():
                stripped = line.strip()
                # Only match RNS output format lines, not Python code or usage syntax
                # Domain headers: "1 🔧 QUALITY (2)" or "🔧 QUALITY"
                if re.match(r'^\d*\s*[🔧🧪📄🔒⚡🐙📦📌]\s+', stripped):
                    examples.add(stripped)
                # Separator lines
                if stripped.startswith('━━━━━━━━━━━━━━━━━━━━━━━━━━━━'):
                    examples.add(stripped)
                # Do-all directive
                if DO_ALL_RE.match(stripped):
                    examples.add(stripped)
                # Gap coverage lines
                if 'GAP COVERAGE' in stripped or 'MAPPED →' in stripped:
                    examples.add(stripped)
                # RNS machine-parseable format lines
                if stripped.startswith('RNS|'):
                    examples.add(stripped)
    except Exception:
        pass  # Fail open - if we can't read the skill file, don't filter

    _get_rns_skill_examples._cache = examples
    return examples


DEP_ANNOTATION_RE = re.compile(r'\[caused-by:\s*([^\]]+)\]')
BLOCK_ANNOTATION_RE = re.compile(r'\[blocks:\s*([^\]]+)\]')


def _extract_actions_from_text(text: str, session_id: str | None = None) -> list[CrossSessionAction]:
    """Extract RNS-formatted action items from text.

    Dual-path extraction:
    - Path A (primary): RNS-tagged lines ([recover/high] etc.)
    - Path B (fallback): Heuristic pattern extraction when Path A finds nothing,
      AND text contains signal keywords OR text is longer than 200 chars.

    Filters out example content from the RNS skill's own SKILL.md to avoid
    treating documentation examples as real findings.
    """
    # Load known examples to filter out
    rns_examples = _get_rns_skill_examples()

    # Path A: RNS-tagged extraction
    actions: list[CrossSessionAction] = []
    current_domain = "other"
    current_priority = "medium"

    for line in text.splitlines():
        # Check for domain header
        header_match = DOMAIN_HEADER_RE.match(line)
        if header_match:
            current_domain = header_match.group(2).lower()
            continue

        # Check for "0 — Do ALL" directive (carryover signal)
        if DO_ALL_RE.match(line):
            continue

        # Check for action item
        item_match = RNS_LINE_RE.match(line)
        if item_match:
            # item_match.group(1) = number (e.g., "1a") - not used
            tag = item_match.group(2)  # tag (e.g., "recover/high")
            domain = current_domain
            # Parse tag: e.g. "recover/high" or "prevent/med"
            if '/' in tag:
                action_part, priority_part = tag.split('/', 1)
                action = action_part.strip()
                priority = priority_part.strip().replace('med', 'medium')
            else:
                action = "recover"
                priority = "medium"

            # Parse priority
            priority_map = {'crit': 'critical', 'high': 'high', 'med': 'medium', 'low': 'low'}
            priority = priority_map.get(priority.lower(), priority.lower())

            desc = item_match.group(3).strip()
            file_ref = item_match.group(4)

            # Strip common ID prefixes from description (e.g., "QUAL-001 Fix this" → "Fix this")
            id_prefix_re = re.compile(r'^[A-Z_]+-\d+\s+', re.IGNORECASE)
            desc = id_prefix_re.sub('', desc)

            # Filter out examples from RNS SKILL.md documentation
            line_stripped = line.strip()
            # Normalize priority abbreviations for matching
            normalized_line = line_stripped.replace('med', 'medium').replace('crit', 'critical')
            if normalized_line in rns_examples or line_stripped in rns_examples:
                continue

            # Filter out items from previous RNS output (description starts with [UNVERIFIED])
            if desc.startswith('[UNVERIFIED]'):
                continue

            # Filter out RNS documentation template placeholders
            if desc.startswith('DOC-N Update {doc file}'):
                continue

            # Extract dependency annotations [caused-by: ID] and [blocks: ID]
            caused_by = None
            blocks = None
            caused_match = DEP_ANNOTATION_RE.search(line)
            if caused_match:
                caused_by = caused_match.group(1).strip()
            blocks_match = BLOCK_ANNOTATION_RE.search(line)
            if blocks_match:
                blocks = blocks_match.group(1).strip()

            # Strip dependency annotations from the description
            desc = DEP_ANNOTATION_RE.sub('', desc).strip()
            desc = BLOCK_ANNOTATION_RE.sub('', desc).strip()

            actions.append(CrossSessionAction(
                domain=domain,
                action=action,
                priority=priority,
                description=desc,
                file_ref=file_ref,
                session_id=session_id,
                unverified=False,
                caused_by=caused_by,
                blocks=blocks,
            ))

    # Path B: Heuristic extraction (fallback)
    # Run Path B when Path A found nothing AND text has signal keywords OR text > 200 chars.
    # This prevents Path B from extracting random prose from short, low-signal text.
    if len(actions) == 0 and (_has_signal_keywords(text) or len(text) > 200):
        path_b_results = _heuristic_extract(text, session_id)
        # Filter out RNS SKILL.md examples from Path B results
        filtered_path_b = []
        for action in path_b_results:
            # Check if the description matches any known example
            desc = action.description
            normalized_desc = desc.replace('med', 'medium').replace('crit', 'critical')
            if normalized_desc in rns_examples or desc in rns_examples:
                continue
            filtered_path_b.append(action)
        # Within-path dedup for Path B
        path_b_results = _dedupe_actions(filtered_path_b)
        actions.extend(path_b_results)

    # Quality filter: Remove low-quality items
    actions = [a for a in actions if _is_actionable(a)]

    return actions


# ---------------------------------------------------------------------------
# Path B: Heuristic extraction for unstructured text
# ---------------------------------------------------------------------------

# Quality thresholds for action items
MIN_DESCRIPTION_LENGTH = 8
MIN_WORDS = 2
MAX_DESCRIPTION_LENGTH = 500

# Meta-directive patterns that don't represent actionable items
META_DIRECTIVE_PREFIXES = (
    "MANDATORY:", "FORMAT:", "ID reference:", "NOTE:", "WARNING:",
    "TODO:", "FIXME:", "HACK:", "XXX:", "TEMP:",
)

# Patterns that indicate non-actionable content (documentation, dialogue, etc.)
DOCUMENTATION_PATTERNS = [
    r'^#+\s+\w',  # Markdown headers: ##, ###, etc.
    r'^\|',  # Markdown table rows
    r'^(assistant|user|system):',  # Transcript dialogue prefixes
    r'^\s*-\s+\*\*',  # Markdown list items with bold (documentation format)
    r'^\s*\d+\.\s+',  # Numbered list items (documentation)
    r'See `.*` for',  # Documentation references: "See `references/foo.md` for"
    r'^\s*```\s*$',  # Markdown code fence markers
    r'^\*\*[^*]+\*\*:\s*',  # Bold headers like "**Role:**", "**Your role is**"
    r'^You are (?:a|an|the)',  # Role definitions: "You are a specialist..."
    r'^Your role (?:is|as)',  # Role definitions
    r'^\*\*Your (?:role|identity)',  # Bold role/identity headers
    r'^\*\*Only',  # "**Only implement if..." - documentation constraint
    r'^(?:When|If|Before|After) \w+,.*should',  # Generic prescription statements
    r'^- (?:Run|Use|Dispatch|Record)',  # Documentation step instructions
    r'^\s*\|.*\|.*\|',  # Multi-column markdown tables
    r'^--\w+',  # Command-line flags: --root-cause, --fix, etc.
    r'must be (?:true|false|set)',  # Documentation field requirements
    r'^\w+ claims must include',  # Documentation rules: "All claims must include..."
    r'Your (?:first|next) action must be',  # Workflow documentation
    r'^Would you like me to',  # Assistant dialogue offering to help
    r'Every recommended fix gets classified',  # Documentation description
]

# Signal keywords that indicate substantive content regardless of length
SIGNAL_KEYWORDS = [
    "CRITICAL", "HIGH", "MEDIUM", "LOW",
    "bug", "broken", "fails", "crash", "error",
    "missing", "not found", "doesn't handle", "no support for",
    "should", "ought to", "needs to", "has to", "must",
    "to-do", "fix", "update", "add", "change",
    "COMP-", "ID-",  # ID reference patterns
    "gap", "not implemented", "not yet",
    "investigat", "diagnos", "root cause", "found that",
]


def _is_actionable(action: CrossSessionAction) -> bool:
    """Check if action is actionable enough to keep.

    Filters out:
    - Items too short to be meaningful
    - Meta-directives (MANDATORY, FORMAT, etc.)
    - ID-only references with no action
    - Truncated descriptions
    - Documentation patterns (headers, tables, dialogue)
    """
    desc = action.description.strip()

    # Length threshold
    if len(desc) < MIN_DESCRIPTION_LENGTH:
        return False

    # Word count threshold
    if len(desc.split()) < MIN_WORDS:
        return False

    # Meta-directive filter
    if desc.startswith(META_DIRECTIVE_PREFIXES):
        return False

    # ID-only reference filter - filters any description that starts with ID reference
    if desc.startswith('ID reference:'):
        return False

    # Truncated description filter (ends with ...)
    if desc.endswith('...') and len(desc) < MAX_DESCRIPTION_LENGTH:
        return False

    # Documentation pattern filter - exclude markdown headers, tables, dialogue, etc.
    for pattern in DOCUMENTATION_PATTERNS:
        if re.match(pattern, desc, re.IGNORECASE | re.MULTILINE):
            return False

    return True


def _has_signal_keywords(text: str) -> bool:
    """Check if text contains any signal keywords."""
    upper = text.upper()
    return any(kw.upper() in upper for kw in SIGNAL_KEYWORDS)


def _heuristic_extract(text: str, session_id: str | None = None) -> list[CrossSessionAction]:
    """Extract action items from unstructured text using heuristic patterns.

    All returned items have unverified=True since they are inferred, not confirmed.
    """
    actions: list[CrossSessionAction] = []
    seen_hashes: set[str] = set()

    # Compile regex patterns
    patterns: list[tuple[str, re.Pattern, str, str, str]] = [
        # (signal_name, compiled_regex, domain, default_action, default_priority)
        (
            "severity_label",
            re.compile(r"\b(CRITICAL|HIGH|MEDIUM|LOW)\b", re.IGNORECASE),
            "derived", "recover", "from_label",
        ),
        (
            "bug_statement",
            re.compile(r"\b(bug|broken|fails|crash|error)\b.*when", re.IGNORECASE),
            "quality", "recover", "medium",
        ),
        (
            "missing_thing",
            re.compile(r"\b(missing|not found|doesn.?t handle|no support for)\b", re.IGNORECASE),
            "quality", "recover", "medium",
        ),
        (
            "recommendation",
            re.compile(r"\b(should|ought to|needs? to|has to|must)\b", re.IGNORECASE),
            "other", "prevent", "low",
        ),
        (
            "action_item",
            re.compile(r"\b(to-do|fix|update|add|change)\b", re.IGNORECASE),
            "other", "realize", "medium",
        ),
        (
            "file_reference",
            re.compile(r"@[\s]+(\S+:\d+)", re.IGNORECASE),
            "quality", "recover", "high",
        ),
        (
            "id_reference",
            re.compile(r"\b([A-Z]{2,}-[0-9]+)\b"),
            "other", "realize", "low",
        ),
        (
            "gap_phrase",
            re.compile(r"\b(missing|gap|not implemented|not yet)\b", re.IGNORECASE),
            "quality", "prevent", "medium",
        ),
        (
            "investigation_result",
            re.compile(r"(investigat|diagnos|found that|root cause)", re.IGNORECASE),
            "quality", "recover", "high",
        ),
    ]

    # File reference path pattern (matches both Unix and Windows paths)
    FILE_PATH_RE = re.compile(r"([\w/\\.-]+\.py:\d+)")

    for line in text.splitlines():
        # Skip RNS-formatted lines - they're handled by Path A
        if RNS_LINE_RE.match(line):
            continue
        # Skip lines from previous RNS output (contain [UNVERIFIED] marker)
        if '[UNVERIFIED]' in line:
            continue
        for signal_name, pattern, domain, default_action, default_priority in patterns:
            match = pattern.search(line)
            if not match:
                continue

            # Determine domain
            inferred_domain = domain
            if signal_name == "severity_label" and inferred_domain == "derived":
                # Try to derive domain from context
                inferred_domain = "other"

            # Determine priority
            file_ref = None
            priority = default_priority
            if signal_name == "severity_label":
                label = match.group(1).upper()
                priority_map = {"CRITICAL": "critical", "HIGH": "high", "MEDIUM": "medium", "LOW": "low"}
                priority = priority_map.get(label, "medium")
            elif signal_name == "bug_statement":
                # Check if line also has CRITICAL for higher priority
                if re.search(r"\bCRITICAL\b", line, re.IGNORECASE):
                    priority = "high"
            elif signal_name == "file_reference":
                # Extract file path from line
                path_match = FILE_PATH_RE.search(line)
                file_ref = path_match.group(1) if path_match else match.group(1) if match.groups() else None

            # Build description from matched text
            if signal_name == "file_reference":
                desc = f"File reference: {file_ref}" if file_ref else match.group(0)
            elif signal_name == "id_reference":
                desc = f"ID reference: {match.group(1)}"
            else:
                # Use the matched sentence/clause
                desc = line.strip()[:200]

            # Compute dedupe hash
            dedupe_hash = f"{inferred_domain}|{default_action}|{desc[:50]}"
            if dedupe_hash in seen_hashes:
                continue
            seen_hashes.add(dedupe_hash)

            actions.append(CrossSessionAction(
                domain=inferred_domain,
                action=default_action,
                priority=priority,
                description=desc,
                file_ref=file_ref,
                session_id=session_id,
                unverified=True,
            ))

    return actions


def _dedupe_actions(actions: list[CrossSessionAction]) -> list[CrossSessionAction]:
    """Deduplicate actions by (domain, action, first_50_chars_of_description).

    This is a within-path deduplication — call separately for Path A and Path B
    results before merging.
    """
    seen: set[str] = set()
    result: list[CrossSessionAction] = []
    for action in actions:
        key = f"{action.domain}|{action.action}|{action.description[:50]}"
        if key not in seen:
            seen.add(key)
            result.append(action)
    return result


def _get_current_session_id(transcript_path: Path | None) -> str | None:
    """Extract session ID from current transcript JSONL."""
    if not transcript_path or not transcript_path.exists():
        return None
    try:
        with open(transcript_path, encoding="utf-8", errors="ignore") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    if entry.get("sessionId"):
                        return entry["sessionId"]
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return None


def get_session_transcript_text() -> str:
    """Return all user+assistant message text from the current session transcript.

    Falls back to compact-restore context if transcript unavailable.
    Returns empty string if nothing found.
    """
    transcript_path = get_current_transcript_path()
    if transcript_path and transcript_path.exists():
        return _read_transcript_text(transcript_path)

    # Fallback: check for compact-restore state via environment or session context
    # This is a last-resort path when transcript compaction has removed content
    try:
        import os

        # Check for transcript path hint in environment (set by Claude Code hooks)
        for key in ("CLAUDE_TRANSCRIPT_PATH", "TRANSCRIPT_PATH"):
            if key in os.environ:
                fallback = Path(os.environ[key])
                if fallback.exists():
                    return _read_transcript_text(fallback)
    except Exception:
        pass

    return ""


def _resolve_current_transcript_via_chain_miner() -> tuple[Path | None, str | None]:
    """Find current transcript path and session ID using claude-chain-miner.

    Uses the miner's reverse-lookup strategy: find newest .jsonl in projects dir.
    This works even when no handoff file exists for the current session
    (PreCompact hasn't run yet).
    """
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[3] / ".." / ".." / "packages" / "claude-chain-miner"))
        from scripts.walker import _resolve_current_transcript, _session_id_from_path
    except ImportError:
        return None, None

    try:
        tpath = _resolve_current_transcript()
        if tpath and tpath.exists():
            sid = _session_id_from_path(tpath)
            return tpath, sid
    except Exception:
        pass
    return None, None


def get_current_transcript_path() -> Path | None:
    """Find the current session's transcript path.

    Strategy:
    1. Query the session harness via SESSION_REVERSION_INPROCESS state
       (set during session restore/compact - harness knows the transcript path)
    2. Fall back to WT_SESSION terminal ID → handoff → transcript_path
    3. Last resort: env vars for current transcript
    4. Chain-miner fallback: newest .jsonl by mtime (works when no handoff exists yet)

    This avoids the problem of using mtime-based selection which can
    pick wrong files when multiple terminals or pytest runs exist.
    """
    try:
        from pathlib import Path as PPath

        import os

        # 1. Query the session harness for transcript path
        # SESSION_REVERSION_INPROCESS is set during session restore/compact
        # The harness writes transcript_path into the compact/restore state
        for key in ("CLAUDE_RESTORE_TRANSCRIPT", "CLAUDE_TRANSCRIPT_PATH",
                   "SESSION_TRANSCRIPT_PATH"):
            val = os.environ.get(key)
            if val:
                path = PPath(val)
                if path.exists():
                    return path

        # 2. Use WT_SESSION to find the current terminal's handoff file
        wt_session = os.environ.get("WT_SESSION", "")
        if wt_session:
            handoff_dir = PPath.home() / ".claude" / "state" / "handoff"
            if handoff_dir.exists():
                # Look for handoff file matching current WT_SESSION
                handoff_pattern = f"console_{wt_session}*_handoff.json"
                matches = list(handoff_dir.glob(handoff_pattern))
                if matches:
                    try:
                        content = json.loads(matches[0].read_text(encoding="utf-8"))
                        # Check both resume_snapshot and direct transcript_path
                        tpath = (content.get("resume_snapshot", {})
                                 .get("transcript_path"))
                        if not tpath:
                            tpath = content.get("transcript_path")
                        if tpath:
                            tp = PPath(tpath)
                            if tp.exists():
                                return tp
                    except (json.JSONDecodeError, OSError):
                        pass

        # 3. Fallback: use Claude Code's own transcript path env var
        # This is set during session start and is more reliable than mtime selection
        for key in ("CLAUDE_CURRENT_TRANSCRIPT", "CLAUDE_SESSION_TRANSCRIPT"):
            val = os.environ.get(key)
            if val:
                path = PPath(val)
                if path.exists():
                    return path

        # mtime-based fallback is UNRELIABLE — it picks wrong transcripts when
        # multiple terminals/sessions are active. Return None instead and let
        # the caller handle gracefully (empty RNS, not wrong RNS).
        # NOTE: This return is inside the try block. We do NOT return here so
        # that the except below can run. The chain-miner fallback at step 4
        # runs OUTSIDE the try/except to avoid being swallowed by a return.
        transcript_path = None

    except Exception:
        return None

    # 4. Chain-miner fallback: use claude-chain-miner's _resolve_current_transcript
    # This finds the newest .jsonl in the projects dir via mtime,
    # which is the correct current session transcript when no handoff exists yet.
    # This runs OUTSIDE the try/except so it is NOT swallowed by the exception handler.
    tpath, sid = _resolve_current_transcript_via_chain_miner()
    if tpath and tpath.exists():
        return tpath
    return None


def _get_last_assistant_message(transcript_path: Path | None) -> str | None:
    """Extract the last assistant message content from a transcript."""
    if not transcript_path or not transcript_path.exists():
        return None
    try:
        with open(transcript_path, encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        # Read backwards to find last assistant message
        for line in reversed(lines):
            try:
                entry = json.loads(line)
                # Type 100 = assistant message in Claude Code transcript format
                if entry.get("type") == 100 or (entry.get("sender") == "assistant"):
                    return entry.get("content", "") or entry.get("text", "")
            except json.JSONDecodeError:
                continue
    except OSError:
        pass
    return None


def _read_transcript_text(transcript_path: Path) -> str:
    """Read all text content from a transcript (all user + assistant messages).

    Handles two transcript formats:
    - Old: entries with 'sender' + 'text' fields
    - New: entries with 'type' ('user'/'assistant') + 'message.content' (str or list)
    """
    if not transcript_path.exists():
        return ""
    try:
        with open(transcript_path, encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        content = []
        for line in lines:
            try:
                entry = json.loads(line)
                etype = entry.get("type", "")

                # New format: type == 'user' or 'assistant'
                if etype in ("user", "assistant"):
                    msg = entry.get("message", {})
                    if isinstance(msg, dict):
                        text = msg.get("content", "")
                    else:
                        text = ""
                    # content may be a string or a list of content blocks
                    if isinstance(text, list):
                        text = " ".join(
                            block.get("text", "")
                            for block in text
                            if isinstance(block, dict)
                        )
                    if text:
                        content.append(f"{etype}: {text}")

                # Old format: sender field
                elif "sender" in entry:
                    sender = entry.get("sender", "")
                    if sender in ("user", "assistant"):
                        text = entry.get("text", "") or entry.get("content", "")
                        if text:
                            content.append(f"{sender}: {text}")

            except json.JSONDecodeError:
                continue
        return "\n".join(content)
    except OSError:
        return ""


def get_rns_from_session_chain(session_id: str) -> ChainRNSResult:
    """Walk the session chain and extract RNS action items from all sessions.

    Args:
        session_id: Current session UUID

    Returns:
        ChainRNSResult with current and carryover action items
    """
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[3] / ".." / ".." / "packages" / "claude-chain-miner"))
        from scripts.walker import walk_handoff_chain
    except ImportError:
        logger.debug("claude-chain-miner not available, skipping chain traversal")
        return ChainRNSResult()

    try:
        chain_entries, origin = walk_handoff_chain(max_depth=20)
    except Exception as e:
        logger.warning("Failed to walk session chain: %s", e)
        return ChainRNSResult()

    result = ChainRNSResult(chain_depth=len(chain_entries))

    if not chain_entries:
        return result

    # Staleness filter settings
    STALE_CUTOFF_DAYS = 7

    # Process all sessions in the chain (oldest to newest)
    for entry in chain_entries:
        sid = entry.session_id
        tpath = entry.transcript_path

        if not tpath or not tpath.exists():
            continue

        # Check for staleness - skip old sessions
        if entry.created:
            try:
                # created may be a string (ISO format) or a datetime
                if isinstance(entry.created, str):
                    created_dt = datetime.fromisoformat(entry.created)
                elif isinstance(entry.created, datetime):
                    created_dt = entry.created
                else:
                    created_dt = None
                if created_dt:
                    age = datetime.now() - created_dt
                    if age > timedelta(days=STALE_CUTOFF_DAYS):
                        logger.debug("Skipping stale session %s... (%d days old)", sid[:8], age.days)
                        continue
            except (ValueError, TypeError):
                pass

        # Read full transcript text
        text = _read_transcript_text(tpath)

        # Extract RNS items from this session's transcript
        actions = _extract_actions_from_text(text, session_id=sid)

        # The last session in the chain is the "current" one for RNS purposes
        is_current = (entry == chain_entries[-1])

        if is_current:
            result.current_items = actions
        else:
            # Prior session — these are carryover items
            result.carryover_items.extend(actions)

    return result


def get_current_rns_items() -> tuple[list[CrossSessionAction], list[CrossSessionAction]]:
    """Get RNS action items from the current session chain.

    Returns:
        Tuple of (current_items, carryover_items)
    """
    transcript_path = get_current_transcript_path()
    session_id = _get_current_session_id(transcript_path)

    if not session_id:
        return [], []

    chain_result = get_rns_from_session_chain(session_id)
    return chain_result.current_items, chain_result.carryover_items
