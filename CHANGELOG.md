# Changelog

All notable changes to RNS are documented here.

## [1.2.1] — 2026-04-07

### Fixed
- **LOW**: Documented background command double-display behavior — added "Background Command Display Behavior" section to SKILL.md explaining the Claude Code platform behavior where RNS output appears twice when generated while a background command is running. Includes avoidance patterns for synchronous execution and result capture.

---

## [1.2.0] — 2026-04-06

### Fixed
- **BLOCKER**: Subletter overflow at 27+ items per domain — replaced `chr(ord('a') + idx - 1)` with Excel-style base-26 `_subletter()` function (1→a, 26→z, 27→ba, 52→bz, 702→baz)
- **HIGH**: Path B `file_ref` unconditionally overwritten to `None` — removed duplicate overwrite blocks in `_heuristic_extract()`
- **HIGH**: `seen: set[str] = []` used as set — changed to `seen: set[str] = set()` with `.add()` for O(1) dedup
- **MEDIUM**: No-op `.replace('high', 'high')` in priority normalization chain removed
- **MEDIUM**: Carryover section now uses consistent `2a`/`2b` numbering matching domain items, with inline `@ file:line`
- **MEDIUM**: `render_machine_format` now includes carryover section (was silently dropped)
- **MEDIUM**: kwargs validation in `format_rns_output` raises `ValueError` with valid options list on typos
- **MEDIUM**: Unicode truncation via `wcwidth` library for visual column-accurate `max_description_chars`

### Added
- `_subletter(idx)` helper: Excel-style column labels for unlimited domain items
- `_visual_truncate(text, max_width)` helper: Unicode-aware text truncation
- `test_carryover_only_do_all_count`, `test_unknown_domain_rendered`, `test_equal_count_domains_sort_alphabetically`, `test_machine_format_with_carryover`, `test_invalid_kwargs_raises_valueerror`

### Tests
- 64/64 passing (chain: 27, render: 37)

---

## [1.1.0] — Prior versions

See git history for earlier changes.
