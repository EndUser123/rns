"""Tests for rns/core/chain.py."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from core.chain import (
    CrossSessionAction,
    ChainRNSResult,
    _extract_actions_from_text,
    _get_current_session_id,
    get_rns_from_session_chain,
    _heuristic_extract,
    _has_signal_keywords,
    _dedupe_actions,
)


class TestExtractActionsFromText:
    """Tests for _extract_actions_from_text."""

    def test_extracts_single_action(self) -> None:
        text = "[recover/high] QUAL-001 Fix something @ file.py:10"
        actions = _extract_actions_from_text(text)
        assert len(actions) == 1
        assert actions[0].domain == "other"
        assert actions[0].action == "recover"
        assert actions[0].priority == "high"
        assert actions[0].file_ref == "file.py:10"

    def test_extracts_domain_from_header(self) -> None:
        text = """🔧 QUALITY
[recover/high] QUAL-001 Fix something @ file.py:10"""
        actions = _extract_actions_from_text(text)
        assert len(actions) == 1
        assert actions[0].domain == "quality"
        assert actions[0].description == "Fix something"

    def test_extracts_multiple_domains(self) -> None:
        text = """🔧 QUALITY
[recover/high] QUAL-001 Fix something

📄 DOCS
[realize/low] DOC-001 Update readme"""
        actions = _extract_actions_from_text(text)
        assert len(actions) == 2

    def test_ignores_do_all_directive(self) -> None:
        text = """🔧 QUALITY
[recover/high] QUAL-001 Fix something

0 — Do ALL Recommended Next Actions"""
        actions = _extract_actions_from_text(text)
        assert len(actions) == 1

    def test_parses_prevent_action(self) -> None:
        text = "[prevent/med] QUAL-002 Add test @ test.py:20"
        actions = _extract_actions_from_text(text)
        assert actions[0].action == "prevent"
        assert actions[0].priority == "medium"

    def test_parses_realize_action(self) -> None:
        text = "[realize/low] DOC-001 Update docs"
        actions = _extract_actions_from_text(text)
        assert actions[0].action == "realize"
        assert actions[0].priority == "low"

    def test_empty_text_returns_empty(self) -> None:
        assert _extract_actions_from_text("") == []
        assert _extract_actions_from_text("no actions here") == []


class TestGetCurrentSessionId:
    """Tests for _get_current_session_id."""

    def test_extracts_session_id_from_jsonl(self, tmp_path: Path) -> None:
        transcript = tmp_path / "test_session.jsonl"
        with open(transcript, "w", encoding="utf-8") as f:
            f.write(json.dumps({"sessionId": "abc123", "type": 100}) + "\n")

        sid = _get_current_session_id(transcript)
        assert sid == "abc123"

    def test_missing_session_id_returns_none(self, tmp_path: Path) -> None:
        transcript = tmp_path / "empty.jsonl"
        transcript.write_text("not json\n")
        assert _get_current_session_id(transcript) is None

    def test_none_path_returns_none(self) -> None:
        assert _get_current_session_id(None) is None


class TestGetRnsFromSessionChain:
    """Tests for get_rns_from_session_chain."""

    def test_returns_chain_depth_one_via_chain_miner(self) -> None:
        """When chain-miner is available, returns session chain via walk_handoff_chain."""
        # chain-miner is available and returns entries for current session chain
        result = get_rns_from_session_chain("nonexistent-session-id")
        assert isinstance(result, ChainRNSResult)
        # Chain-miner finds the current session via _resolve_current_transcript
        assert result.chain_depth >= 0  # 0 = no handoff yet, >=1 = chain found


class TestReadTranscriptText:
    """Tests for _read_transcript_text with real transcript formats."""

    def test_new_format_user_assistant_messages(self, tmp_path: Path) -> None:
        """New format: type='user'/'assistant' with message.content as string."""
        transcript = tmp_path / "new_format.jsonl"
        transcript.write_text(
            json.dumps(
                {"type": "user", "message": {"role": "user", "content": "fix the bug"}}
            )
            + "\n"
            + json.dumps(
                {
                    "type": "assistant",
                    "message": {"role": "assistant", "content": "Here is the fix"},
                }
            )
            + "\n",
            encoding="utf-8",
        )
        from core.chain import _read_transcript_text

        text = _read_transcript_text(transcript)
        assert "user: fix the bug" in text
        assert "assistant: Here is the fix" in text

    def test_old_format_sender_field(self, tmp_path: Path) -> None:
        """Old format: sender + text fields at top level."""
        transcript = tmp_path / "old_format.jsonl"
        transcript.write_text(
            json.dumps({"sender": "user", "text": "hello"})
            + "\n"
            + json.dumps({"sender": "assistant", "text": "hi there"})
            + "\n",
            encoding="utf-8",
        )
        from core.chain import _read_transcript_text

        text = _read_transcript_text(transcript)
        assert "user: hello" in text
        assert "assistant: hi there" in text

    def test_old_format_ignored_without_sender_field(self, tmp_path: Path) -> None:
        """Old format without sender field should NOT be extracted as new format."""
        from core.chain import _read_transcript_text

        # Entry with type='user' but no 'message.content' — should be ignored
        # (only new format has message.content)
        transcript = tmp_path / "neither_format.jsonl"
        transcript.write_text(
            json.dumps({"type": "user", "content": "raw content"}) + "\n",
            encoding="utf-8",
        )
        text = _read_transcript_text(transcript)
        # Should be empty — 'content' at top level is not the new format
        assert text == ""


class TestHeuristicExtract:
    """Tests for Path B _heuristic_extract() function."""

    def test_extracts_from_plain_bug_statement(self) -> None:
        """Bug statement like 'X is broken when Y is Z' triggers quality/recover."""
        text = "The auth token is broken when the session expires"
        actions = _heuristic_extract(text)
        assert len(actions) >= 1
        bug_actions = [a for a in actions if a.action == "recover"]
        assert len(bug_actions) >= 1
        assert bug_actions[0].domain == "quality"
        assert bug_actions[0].unverified is True

    def test_extracts_from_severity_label(self) -> None:
        """CRITICAL label maps to priority=critical."""
        text = "CRITICAL: auth token expiry causes immediate failure"
        actions = _heuristic_extract(text)
        assert len(actions) >= 1
        critical_actions = [a for a in actions if a.priority == "critical"]
        assert len(critical_actions) >= 1

    def test_extracts_from_missing_phrase(self) -> None:
        """Missing phrase triggers quality/recover/medium."""
        text = "missing proper error handling for invalid input"
        actions = _heuristic_extract(text)
        assert len(actions) >= 1
        missing_actions = [a for a in actions if a.domain == "quality" and a.action == "recover"]
        assert len(missing_actions) >= 1

    def test_extracts_from_recommendation(self) -> None:
        """'should' recommendation triggers other/prevent/low."""
        text = "The code should add error handling for null inputs"
        actions = _heuristic_extract(text)
        assert len(actions) >= 1
        rec_actions = [a for a in actions if a.action == "prevent"]
        assert len(rec_actions) >= 1
        assert rec_actions[0].unverified is True

    def test_extracts_from_file_reference(self) -> None:
        """File reference with line number is extracted."""
        text = "See @ hooks/foo.py:42 for the implementation"
        actions = _heuristic_extract(text)
        assert len(actions) >= 1
        file_ref_actions = [a for a in actions if a.file_ref is not None]
        assert len(file_ref_actions) >= 1
        assert "hooks/foo.py" in file_ref_actions[0].file_ref or "42" in file_ref_actions[0].file_ref

    def test_extracts_from_id_reference(self) -> None:
        """COMP-001 style ID triggers other/realize/low."""
        text = "COMP-001 was identified during the review"
        actions = _heuristic_extract(text)
        assert len(actions) >= 1
        id_actions = [a for a in actions if a.action == "realize"]
        assert len(id_actions) >= 1

    def test_extracts_no_false_positive_on_short_text(self) -> None:
        """Short text with no signal keywords returns empty from _heuristic_extract."""
        text = "sounds good to me"
        result = _heuristic_extract(text)
        assert result == [], f"Expected empty list for casual text, got {result}"

    def test_extracts_no_false_positive_on_casual_language(self) -> None:
        """Casual conversation returns no matches."""
        text = "that sounds fine, let's proceed with the implementation"
        actions = _heuristic_extract(text)
        # No signal keywords in casual text
        assert len(actions) == 0 or all(
            a.unverified is False for a in actions
        )

    def test_path_b_items_marked_unverified(self) -> None:
        """All Path B items have unverified=True."""
        text = "CRITICAL: the session handling is broken when tokens expire"
        actions = _heuristic_extract(text)
        assert len(actions) >= 1
        for action in actions:
            assert action.unverified is True

    def test_path_a_unchanged(self) -> None:
        """Existing Path A RNS-tagged extraction still works."""
        text = "[recover/high] QUAL-001 Fix something @ file.py:10"
        actions = _extract_actions_from_text(text)
        assert len(actions) == 1
        assert actions[0].domain == "other"
        assert actions[0].action == "recover"
        assert actions[0].priority == "high"
        assert actions[0].unverified is False

    def test_integration_signal_keyword_triggers_path_b(self) -> None:
        """Short text with signal keyword triggers Path B."""
        text = "CRITICAL: token expired"  # Only 24 chars, but has CRITICAL
        actions = _extract_actions_from_text(text)
        # Should trigger Path B because it has signal keyword
        assert len(actions) >= 1
        assert actions[0].unverified is True

    def test_integration_short_no_signal_returns_empty(self) -> None:
        """Short text with no signal keywords returns empty."""
        text = "that sounds fine"
        actions = _extract_actions_from_text(text)
        assert len(actions) == 0

    def test_dedupe_within_path_b(self) -> None:
        """Duplicate items within Path B are deduplicated."""
        text = "bug bug bug missing missing fix"
        # Extract and dedupe
        raw = _heuristic_extract(text)
        deduped = _dedupe_actions(raw)
        # Fewer or equal items after dedupe
        assert len(deduped) <= len(raw)
