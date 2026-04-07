"""RNS Session Chain — cross-session action item retrieval."""

from __future__ import annotations

import json
import logging
import re
import sys
from dataclasses import dataclass, field
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
    effort: str | None = None
    unverified: bool = False  # True for Path B (heuristic) items


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

# Matches lines like: [recover/high] QUAL-001 Fix something @ file:line
RNS_LINE_RE = re.compile(
    r'^\s*\[([^\]]+)\]\s+([A-Z]+-\d+)\s+(.+?)(?:\s+@\s+([^@\s]+))?\s*$'
)

# Matches domain emoji headers like: 🔧 QUALITY
DOMAIN_HEADER_RE = re.compile(r'^([🔧🧪📄🔒⚡🐙📦📌])\s+([A-Z_]+)\s*$')

# Matches "0 — Do ALL" directive
DO_ALL_RE = re.compile(r'^0\s*[-—]\s*Do ALL')


def _get_rns_skill_examples() -> set[str]:
    """Load and cache example lines from RNS SKILL.md to filter them out.

    Returns a set of line texts that are known to be examples, not real findings.
    """
    if hasattr(_get_rns_skill_examples, "_cache"):
        return _get_rns_skill_examples._cache

    examples: set[str] = set()
    try:
        skill_path = Path(__file__).parent.parent / "SKILL.md"
        if skill_path.exists():
            content = skill_path.read_text(encoding="utf-8")
            # Extract lines that look like RNS action examples from the skill file
            for line in content.splitlines():
                line_stripped = line.strip()
                # Match action item lines: both "NUM[tag]" and "[tag] ID" formats
                if RNS_LINE_RE.match(line_stripped):
                    examples.add(line_stripped)
                # Match numbered format: "1a [recover/high] description"
                if re.match(r'^\s*\d+[a-z]\s+\[[^\]]+\]', line_stripped):
                    examples.add(line_stripped)
                # Also match domain headers in examples
                if DOMAIN_HEADER_RE.match(line_stripped):
                    examples.add(line_stripped)
    except Exception:
        pass  # Fail open - if we can't read the skill file, don't filter

    _get_rns_skill_examples._cache = examples
    return examples


def _extract_actions_from_text(text: str, session_id: str | None = None) -> list[CrossSessionAction]:
    """Extract RNS-formatted action items from text.

    Dual-path extraction:
    - Path A (primary): RNS-tagged lines ([recover/high] etc.)
    - Path B (fallback): Heuristic pattern extraction when Path A finds nothing
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
            tag = item_match.group(1)
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

            # Filter out examples from RNS SKILL.md documentation
            line_stripped = line.strip()
            if line_stripped in rns_examples:
                continue

            actions.append(CrossSessionAction(
                domain=domain,
                action=action,
                priority=priority,
                description=desc,
                file_ref=file_ref,
                session_id=session_id,
                unverified=False,
            ))

    # Path B: Heuristic extraction (fallback)
    if len(actions) == 0:
        if _has_signal_keywords(text) or len(text) > 200:
            path_b_results = _heuristic_extract(text, session_id)
            # Within-path dedup for Path B
            path_b_results = _dedupe_actions(path_b_results)
            actions.extend(path_b_results)

    return actions


# ---------------------------------------------------------------------------
# Path B: Heuristic extraction for unstructured text
# ---------------------------------------------------------------------------

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


def get_current_transcript_path() -> Path | None:
    """Find the current session's transcript path via Claude Code internals."""
    try:
        from pathlib import Path as PPath
        import os
        # Claude Code stores transcripts in the projects directory
        # Use forward slashes for cross-platform compatibility in bash
        base = PPath.home() / ".claude" / "projects"
        if not base.exists():
            return None
        candidates = list(base.rglob("*.jsonl"))
        if not candidates:
            return None
        # Return the most recently modified
        return max(candidates, key=lambda p: p.stat().st_mtime)
    except Exception:
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
        from search_research.session_chain import walk_session_chain
    except ImportError:
        logger.debug("search_research not available, skipping chain traversal")
        return ChainRNSResult()

    try:
        chain_result = walk_session_chain(session_id, newest_first=False)
    except Exception as e:
        logger.warning("Failed to walk session chain: %s", e)
        return ChainRNSResult()

    result = ChainRNSResult(chain_depth=len(chain_result.entries))

    if not chain_result.entries:
        return result

    # Process all sessions in the chain (oldest to newest)
    for entry in chain_result.entries:
        sid = entry.session_id
        tpath = entry.transcript_path

        if not tpath or not tpath.exists():
            continue

        # Read full transcript text
        text = _read_transcript_text(tpath)

        # Extract RNS items from this session's transcript
        actions = _extract_actions_from_text(text, session_id=sid)

        # The last session in the chain is the "current" one for RNS purposes
        is_current = (entry == chain_result.entries[-1])

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
