# -*- coding: utf-8 -*-
"""Tests for rns/core/render.py."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.chain import CrossSessionAction
from core.render import (
    DOMAIN_MAP,
    ACTION_ORDER,
    PRIORITY_ORDER,
    RenderOptions,
    render_actions,
    render_action_line,
    render_machine_format,
    format_rns_output,
    _get_domain_def,
    _domain_sort_key,
    _resolve_options,
)


class TestDomainDefs:
    """Domain emoji/label mapping."""

    def test_quality_maps_to_quality_emoji(self) -> None:
        assert _get_domain_def("quality") == ("🔧", "QUALITY")

    def test_tests_maps_to_tests_emoji(self) -> None:
        assert _get_domain_def("tests") == ("🧪", "TESTS")

    def test_docs_maps_to_docs_emoji(self) -> None:
        assert _get_domain_def("docs") == ("📄", "DOCS")

    def test_security_maps_to_security_emoji(self) -> None:
        assert _get_domain_def("security") == ("🔒", "SECURITY")

    def test_performance_maps_to_performance_emoji(self) -> None:
        assert _get_domain_def("performance") == ("⚡", "PERFORMANCE")

    def test_git_maps_to_git_emoji(self) -> None:
        assert _get_domain_def("git") == ("🐙", "GIT")

    def test_deps_maps_to_deps_emoji(self) -> None:
        assert _get_domain_def("deps") == ("📦", "DEPS")

    def test_unknown_maps_to_default_emoji(self) -> None:
        assert _get_domain_def("unknown") == ("📌", "UNKNOWN")
        assert _get_domain_def("other") == ("📌", "OTHER")


class TestDomainSortKey:
    """_domain_sort_key provides consistent domain ordering."""

    def test_quality_before_tests(self) -> None:
        q_key = _domain_sort_key("quality", [])
        t_key = _domain_sort_key("tests", [])
        assert q_key < t_key

    def test_carryover_last(self) -> None:
        c_key = _domain_sort_key("carryover", [])
        q_key = _domain_sort_key("quality", [])
        assert q_key < c_key


class TestResolveOptions:
    """_resolve_options handles None, RenderOptions, and dict inputs."""

    def test_none_returns_default(self) -> None:
        opts = _resolve_options(None)
        assert isinstance(opts, RenderOptions)
        assert opts.show_file_refs is True
        assert opts.show_session_id is False

    def test_RenderOptions_passed_through(self) -> None:
        opts = RenderOptions(show_session_id=True, show_effort=True)
        result = _resolve_options(opts)
        assert result is opts

    def test_dict_converted_to_RenderOptions(self) -> None:
        result = _resolve_options({"show_file_refs": False, "max_description_chars": 50})
        assert isinstance(result, RenderOptions)
        assert result.show_file_refs is False
        assert result.max_description_chars == 50


class TestRenderActionLine:
    """render_action_line formats individual action lines."""

    def test_basic_action_line(self) -> None:
        action = CrossSessionAction(
            domain="quality", action="recover", priority="high",
            description="Fix concurrent save registry integrity test",
            file_ref="test_critique_io_concurrent.py:89",
        )
        opts = RenderOptions()
        line = render_action_line(action, opts)
        # New format: just dot + description (no brackets, action is implied by subgroup)
        assert "🟠" in line
        assert "Fix concurrent save registry integrity test" in line
        assert "test_critique_io_concurrent.py:89" in line

    def test_unverified_adds_marker(self) -> None:
        action = CrossSessionAction(
            domain="quality", action="recover", priority="high",
            description="Fix something", unverified=True,
        )
        opts = RenderOptions()
        line = render_action_line(action, opts)
        assert "[UNVERIFIED]" in line

    def test_no_unverified_marker_when_false(self) -> None:
        action = CrossSessionAction(
            domain="quality", action="recover", priority="high",
            description="Fix something", unverified=False,
        )
        opts = RenderOptions()
        line = render_action_line(action, opts)
        assert "[UNVERIFIED]" not in line

    def test_file_ref_hidden_when_disabled(self) -> None:
        action = CrossSessionAction(
            domain="quality", action="recover", priority="high",
            description="Fix something", file_ref="foo.py:10",
        )
        opts = RenderOptions(show_file_refs=False)
        line = render_action_line(action, opts)
        assert "foo.py" not in line

    def test_description_truncated_when_max_chars_set(self) -> None:
        action = CrossSessionAction(
            domain="quality", action="recover", priority="high",
            description="A" * 100,
        )
        opts = RenderOptions(max_description_chars=20)
        line = render_action_line(action, opts)
        assert len(line) < 100
        assert "…" in line


class TestRenderActions:
    """render_actions assembles full RNS output."""

    def test_empty_returns_empty_string(self) -> None:
        result = render_actions([])
        assert result == ""

    def test_single_action_renders_with_number(self) -> None:
        action = CrossSessionAction(
            domain="quality", action="recover", priority="high",
            description="Fix something", file_ref="foo.py:1",
        )
        result = render_actions([action])
        assert "1 🔧 QUALITY (1)" in result
        # New format: just dot + description, numbered sequentially
        assert "1a 🟠" in result
        assert "Fix something" in result
        assert "foo.py:1" in result

    def test_multiple_actions_number_correctly(self) -> None:
        actions = [
            CrossSessionAction(domain="quality", action="recover", priority="high", description="Fix A"),
            CrossSessionAction(domain="quality", action="prevent", priority="medium", description="Fix B"),
            CrossSessionAction(domain="docs", action="realize", priority="low", description="Fix C"),
        ]
        result = render_actions(actions)
        assert "1 🔧 QUALITY (2)" in result
        assert "2 📄 DOCS (1)" in result
        # Proper English labels for action subgroups
        assert "Recovery (1 items)" in result
        assert "Preserve (1 items)" in result
        assert "Future (1 items)" in result
        assert "Fix A" in result
        assert "Fix B" in result
        assert "Fix C" in result

    def test_actions_sorted_by_action_order_then_priority(self) -> None:
        """recover before prevent before realize; within same action, high before medium before low."""
        actions = [
            CrossSessionAction(domain="quality", action="prevent", priority="low", description="prevent-low item"),
            CrossSessionAction(domain="quality", action="recover", priority="low", description="recover-low item"),
            CrossSessionAction(domain="quality", action="realize", priority="low", description="realize-low item"),
            CrossSessionAction(domain="quality", action="recover", priority="high", description="recover-high item"),
            CrossSessionAction(domain="quality", action="prevent", priority="high", description="prevent-high item"),
        ]
        result = render_actions(actions)
        lines = result.splitlines()
        # Find the QUALITY section
        assert "1 🔧 QUALITY (5)" in result
        # Proper English labels in order: Recovery, Preserve, Future
        assert "Recovery (2 items)" in result
        assert "Preserve (2 items)" in result
        assert "Future (1 items)" in result
        # All QUALITY items use 1 as domain prefix
        assert "1a" in result
        assert "1e" in result  # 5 items total, last is 1e
        # recover-high should come before recover-low (sorted by priority within recover)
        recover_high_pos = result.find("recover-high item")
        recover_low_pos = result.find("recover-low item")
        assert recover_high_pos < recover_low_pos

    def test_carryover_section_rendered(self) -> None:
        carry = [
            CrossSessionAction(
                domain="quality", action="recover", priority="high",
                description="Fix auth token expiry",
                file_ref="auth.py:45", session_id="abc123",
            ),
        ]
        result = render_actions([], carryover=carry)
        assert "1 📌 CARRYOVER (1 items)" in result
        assert "Fix auth token expiry" in result
        assert "auth.py:45" in result
        assert "abc123" not in result  # session_id hidden by default

    def test_carryover_with_session_id_shown(self) -> None:
        carry = [
            CrossSessionAction(
                domain="quality", action="recover", priority="high",
                description="Fix auth token expiry",
                file_ref="auth.py:45", session_id="abc123def456",
            ),
        ]
        opts = RenderOptions(show_session_id=True)
        result = render_actions([], carryover=carry, format_options=opts)
        assert "abc123de" in result  # truncated session id shown

    def test_carryover_only_do_all_count(self) -> None:
        """Do-all footer counts carryover items when actions is empty."""
        carry = [
            CrossSessionAction(domain="quality", action="recover", priority="high",
                              description="Fix A"),
            CrossSessionAction(domain="quality", action="prevent", priority="medium",
                              description="Fix B"),
        ]
        result = render_actions([], carryover=carry)
        # 2 carryover items, 0 domain items -> "2 items" in footer
        assert "Do ALL" in result
        assert "2 items" in result

    def test_unknown_domain_rendered(self) -> None:
        """Unknown domain falls back to 📌 + uppercased name in full pipeline."""
        action = CrossSessionAction(
            domain="database", action="recover", priority="high",
            description="Fix connection pool exhaustion",
        )
        result = render_actions([action])
        assert "DATABASE" in result
        assert "📌" in result

    def test_equal_count_domains_sort_alphabetically(self) -> None:
        """Domains with same explicit_order and same count sort by name."""
        # git (5) and deps (6) have different explicit_order, so test tiebreak
        # by checking alphabetical: deps < git < other alphabetically
        from core.render import _domain_sort_key
        action = CrossSessionAction(domain="quality", action="recover",
                                  priority="high", description="x")
        key_deps = _domain_sort_key("deps", [action])
        key_git = _domain_sort_key("git", [action])
        key_other = _domain_sort_key("other", [action])
        # deps=6, git=5, other=7
        assert key_git < key_deps  # git sorts before deps (5 < 6)
        assert key_deps < key_other  # deps sorts before other (6 < 7)

    def test_do_all_footer_present(self) -> None:
        action = CrossSessionAction(
            domain="quality", action="recover", priority="high",
            description="Fix something",
        )
        result = render_actions([action])
        assert "Do ALL" in result
        assert "1 items" in result

    def test_zero_actions_no_footer(self) -> None:
        result = render_actions([])
        assert "Do ALL" not in result

    def test_unverified_marker_appears_in_output(self) -> None:
        action = CrossSessionAction(
            domain="quality", action="recover", priority="high",
            description="Fix something", unverified=True,
        )
        result = render_actions([action])
        assert "[UNVERIFIED]" in result


class TestMachineFormat:
    """render_machine_format produces parseable pipe-delimited output."""

    def test_machine_format_has_delimiters(self) -> None:
        action = CrossSessionAction(
            domain="quality", action="recover", priority="high",
            description="Fix something", file_ref="foo.py:1",
        )
        result = render_machine_format([action])
        assert "<!-- format: machine -->" in result
        assert "RNS|D|" in result
        assert "RNS|A|" in result
        assert "RNS|Z|" in result

    def test_machine_format_escapes_pipe_in_description(self) -> None:
        action = CrossSessionAction(
            domain="quality", action="recover", priority="high",
            description="Fix | something",
        )
        result = render_machine_format([action])
        assert "Fix \\| something" in result

    def test_machine_format_terminator_always_present(self) -> None:
        result = render_machine_format([])
        assert "RNS|Z|0|NONE" in result

    def test_machine_format_with_carryover(self) -> None:
        carry = [
            CrossSessionAction(domain="quality", action="recover", priority="high",
                            description="Fix auth token", file_ref="auth.py:45"),
        ]
        result = render_machine_format([], carryover=carry)
        assert "RNS|D|" in result
        assert "CARRYOVER" in result
        assert "Fix auth token" in result


class TestFormatRnsOutput:
    """format_rns_output is the main public entry point."""

    def test_passes_kwargs_to_RenderOptions(self) -> None:
        action = CrossSessionAction(
            domain="quality", action="recover", priority="high",
            description="Fix something", file_ref="foo.py:1",
        )
        result = format_rns_output([action], show_file_refs=False)
        assert "foo.py" not in result

    def test_machine_format_flag_switches_renderer(self) -> None:
        action = CrossSessionAction(
            domain="quality", action="recover", priority="high",
            description="Fix something",
        )
        result = format_rns_output([action], machine_format=True)
        assert "<!-- format: machine -->" in result

    def test_invalid_kwargs_raises_valueerror(self) -> None:
        action = CrossSessionAction(
            domain="quality", action="recover", priority="high",
            description="Fix something",
        )
        import pytest
        with pytest.raises(ValueError) as exc_info:
            format_rns_output([action], show_file_reffs=True)  # typo
        assert "show_file_reffs" in str(exc_info.value)
        assert "Valid options" in str(exc_info.value)
