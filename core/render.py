"""RNS Action Renderer — consistent formatted output for RNS action items."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .chain import CrossSessionAction

# ---------------------------------------------------------------------------
# Domain definitions
# ---------------------------------------------------------------------------

DomainDef = tuple[str, str]  # (emoji, label)


DOMAIN_MAP: dict[str, DomainDef] = {
    "quality":      ("🔧", "QUALITY"),
    "code_quality": ("🔧", "QUALITY"),
    "tests":        ("🧪", "TESTS"),
    "testing":      ("🧪", "TESTS"),
    "docs":         ("📄", "DOCS"),
    "documentation": ("📄", "DOCS"),
    "security":     ("🔒", "SECURITY"),
    "performance":  ("⚡", "PERFORMANCE"),
    "git":          ("🐙", "GIT"),
    "deps":         ("📦", "DEPS"),
    "dependencies": ("📦", "DEPS"),
    "carryover":    ("📌", "CARRYOVER"),
    "other":        ("📌", "OTHER"),
}


ACTION_ORDER = ("recover", "prevent", "realize")
ACTION_LABELS: dict[str, str] = {
    "recover": "Recovery",
    "prevent": "Preserve",
    "realize": "Future",
}
PRIORITY_ORDER = ("critical", "high", "medium", "low")


# ---------------------------------------------------------------------------
# Format constants
# ---------------------------------------------------------------------------

# Max tag width: just the dot emoji + space (🔴 + space = 2)
ACTION_TAG_MAX_WIDTH = 2

# Priority dot mapping — replaces priority text in tags
# critical=red, high=orange, medium=yellow, low=blue
PRIORITY_DOT_MAP: dict[str, str] = {
    "critical": "🔴",
    "high":     "🟠",
    "medium":   "🟡",
    "low":      "🔵",
}


# ---------------------------------------------------------------------------
# Format options
# ---------------------------------------------------------------------------

@dataclass
class RenderOptions:
    """Formatting options for the RNS renderer."""
    show_file_refs: bool = True
    show_session_id: bool = False
    show_effort: bool = True  # Show effort estimate in item line (e.g. "[E:~5min]")
    show_owner: bool = True  # Show owner annotation (e.g. "{owner}")
    unverified_marker: str = "[UNVERIFIED]"
    domain_group_order: list[str] | None = None  # None = auto-sort by findings count
    max_description_chars: int | None = None
    align_tags: bool = True  # Pad action tags to consistent width
    # Filtering: None = show all, list = show only matching
    domains: list[str] | None = None  # e.g. ["quality", "tests"] — None = all
    priorities: list[str] | None = None  # e.g. ["critical", "high"] — None = all
    show_done: bool = True  # Show DONE section for completed items
    done_marker: str = "✓"


DEFAULT_OPTIONS = RenderOptions()


# ---------------------------------------------------------------------------
# Core renderer
# ---------------------------------------------------------------------------

def _visual_truncate(text: str, max_width: int) -> str:
    """Truncate text to max visual column width using wcwidth."""
    try:
        import wcwidth
    except ImportError:
        return text[:max_width].rstrip() + "…"
    if wcwidth.wcswidth(text) <= max_width:
        return text
    result: list[str] = []
    width = 0
    for char in text:
        w = wcwidth.wcwidth(char)
        if w < 0:  # control char
            continue
        if width + w > max_width:
            break
        result.append(char)
        width += w
    return ''.join(result).rstrip() + "…"


def _subletter(idx: int) -> str:
    """Return Excel-style column label for 1-based index: 1→a, 26→z, 27→ba, 52→bz."""
    result: list[str] = []
    n = idx - 1
    while True:
        n, rem = divmod(n, 26)
        result.append(chr(ord('a') + rem))
        if n == 0:
            break
    return ''.join(reversed(result))


def _filter_actions(
    actions: list[CrossSessionAction],
    domains: list[str] | None,
    priorities: list[str] | None,
) -> list[CrossSessionAction]:
    """Filter actions by domain and priority."""
    result = actions
    if domains:
        result = [a for a in result if a.domain in domains]
    if priorities:
        result = [a for a in result if a.priority in priorities]
    return result


def render_actions(
    actions: list[CrossSessionAction],
    carryover: list[CrossSessionAction] | None = None,
    format_options: RenderOptions | dict | None = None,
) -> str:
    """Render a list of CrossSessionAction items as a formatted RNS output string.

    Args:
        actions: Current session action items to render.
        carryover: Carryover items from prior sessions (optional).
        format_options: RenderOptions instance or dict of options.

    Returns:
        Formatted RNS output string with domain sections, numbered items,
        and a selection footer.
    """
    opts = _resolve_options(format_options)
    carryover = carryover or []

    # Separate done and pending items
    done_items = [a for a in actions if a.done] if opts.show_done else []
    pending_items = [a for a in actions if not a.done]

    # Apply filters to pending items
    pending_items = _filter_actions(pending_items, opts.domains, opts.priorities)

    # Group by domain
    groups: dict[str, list[CrossSessionAction]] = {}
    for action in pending_items:
        groups.setdefault(action.domain, []).append(action)

    # Build output lines
    lines: list[str] = []
    domain_num = 0

    # Render each domain group
    for domain_key, domain_actions in sorted(
        groups.items(),
        key=lambda kv: _domain_sort_key(kv[0], kv[1]),
    ):
        domain_num += 1
        emoji, label = _get_domain_def(domain_key)
        lines.append(f"{domain_num} {emoji} {label} ({len(domain_actions)})")

        # Group by action type (recover, prevent, realize)
        action_groups: dict[str, list[CrossSessionAction]] = {}
        for action in domain_actions:
            action_groups.setdefault(action.action, []).append(action)

        # Render each action subgroup in order
        # Item counter per domain (all items in QUALITY use 1 as prefix: 1a, 1b, 1c...)
        item_counter = 0
        for action_key in ACTION_ORDER:
            if action_key not in action_groups:
                continue
            subgroup = action_groups[action_key]
            # Sort by priority within action group
            sorted_subgroup = sorted(
                subgroup,
                key=lambda a: (
                    PRIORITY_ORDER.index(a.priority) if a.priority in PRIORITY_ORDER else len(PRIORITY_ORDER),
                ),
            )
            label = ACTION_LABELS.get(action_key, action_key.title())
            lines.append(f"  {label} ({len(sorted_subgroup)} items)")

            prev_priority = None
            for action in sorted_subgroup:
                # Add blank line between priority bands
                if prev_priority is not None and action.priority != prev_priority:
                    lines.append("")
                item_counter += 1
                subletter = _subletter(item_counter)
                line = f"    {domain_num}{subletter} {render_action_line(action, opts)}"
                lines.append(line)
                prev_priority = action.priority

        lines.append("")  # blank line after domain group

    # Carryover section
    if carryover:
        carryover_num = domain_num + 1
        lines.append(f"{carryover_num} 📌 CARRYOVER ({len(carryover)} items)")
        for idx, action in enumerate(carryover, start=1):
            subletter = _subletter(idx)
            action_line = render_action_line(action, opts)
            lines.append(f"  {carryover_num}{subletter} {action_line}")
            if opts.show_session_id and action.session_id:
                lines.append(f"  (from session {action.session_id[:8]}...)")
        lines.append("")

    # Done section
    if done_items and opts.show_done:
        done_num = domain_num + 1
        lines.append(f"{done_num} ✓ DONE ({len(done_items)} items)")
        for idx, action in enumerate(done_items, start=1):
            subletter = _subletter(idx)
            action_line = _render_action_line_done(action, opts)
            lines.append(f"  {done_num}{subletter} {action_line}")
        lines.append("")

    # Do-all footer
    total = len(pending_items) + len(carryover)
    if total > 0:
        lines.append(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"0 — Do ALL Recommended Next Actions ({total} items)")

    return "\n".join(lines).strip()


def render_action_line(action: CrossSessionAction, opts: RenderOptions) -> str:
    """Render a single action as a compact line string with all annotations."""
    # Tag is just the priority dot (action is implied by subgroup header)
    dot = PRIORITY_DOT_MAP.get(action.priority, "⚪")
    tag = f"{dot} "

    # Pad tag to fixed width for vertical alignment of descriptions across all items
    if opts.align_tags:
        tag = tag.ljust(ACTION_TAG_MAX_WIDTH)

    parts = [tag]

    # Description
    desc = action.description
    if opts.max_description_chars and len(desc) > opts.max_description_chars:
        desc = _visual_truncate(desc, opts.max_description_chars)
    parts.append(desc)

    # Effort estimate
    if opts.show_effort and action.effort:
        parts.append(f"[E:{action.effort}]")

    # Unverified marker
    if action.unverified:
        parts.append(opts.unverified_marker)

    # Owner annotation
    if opts.show_owner and action.owner:
        parts.append(f"{{{action.owner}}}")

    # File reference
    if opts.show_file_refs and action.file_ref:
        parts.append(f"@ {action.file_ref}")

    line = " ".join(parts)

    # Dependency annotations (rendered below the item)
    deps = []
    if action.blocks:
        deps.append(f"[blocks: {action.blocks}]")
    if action.caused_by:
        deps.append(f"[caused-by: {action.caused_by}]")
    if deps:
        line += "\n    " + " ".join(deps)

    return line


def _render_action_line_done(action: CrossSessionAction, opts: RenderOptions) -> str:
    """Render a completed action with strikethrough."""
    line = render_action_line(action, opts)
    # Strikethrough the description (everything between first space after priority dot and first @ or annotation)
    parts = line.split(" ", 1)
    if len(parts) > 1:
        return parts[0] + " ~~" + parts[1].replace(" @ ", "~~ @ ") + "~~"
    return line


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _resolve_options(opts: RenderOptions | dict | None) -> RenderOptions:
    if opts is None:
        return DEFAULT_OPTIONS
    if isinstance(opts, RenderOptions):
        return opts
    if isinstance(opts, dict):
        return RenderOptions(**opts)
    return DEFAULT_OPTIONS


def _get_domain_def(domain: str) -> DomainDef:
    return DOMAIN_MAP.get(domain, ("📌", domain.upper()))


def _domain_sort_key(domain: str, actions: list[CrossSessionAction]) -> tuple[int, str]:
    """Sort domains: explicit domains first, then by number of items."""
    explicit_order = {
        "quality": 0, "code_quality": 0,
        "tests": 1, "testing": 1,
        "docs": 2, "documentation": 2,
        "security": 3,
        "performance": 4,
        "git": 5,
        "deps": 6, "dependencies": 6,
        "other": 7,
        "carryover": 8,
    }
    return (explicit_order.get(domain, 99), -len(actions), domain)


def render_machine_format(
    actions: list[CrossSessionAction],
    carryover: list[CrossSessionAction] | None = None,
) -> str:
    """Render actions in machine-parseable pipe-delimited format.

    Format:
        RNS|D|{num}|{emoji}|{label}
        RNS|A|{num}{sub}|{domain}|E:{effort}|{action}/{priority}|{desc}|{file_ref}|owner={owner}|done={done}|caused_by={caused_by}|blocks={blocks}|unverified={unverified}
        RNS|Z|0|NONE
    """
    carryover = carryover or []
    lines: list[str] = ["<!-- format: machine -->"]

    groups: dict[str, list[CrossSessionAction]] = {}
    for action in actions:
        groups.setdefault(action.domain, []).append(action)

    domain_num = 0
    for domain_key, domain_actions in groups.items():
        domain_num += 1
        emoji, label = _get_domain_def(domain_key)
        lines.append(f"RNS|D|{domain_num}|{emoji}|{label}")

        sorted_actions = sorted(
            domain_actions,
            key=lambda a: (
                ACTION_ORDER.index(a.action) if a.action in ACTION_ORDER else len(ACTION_ORDER),
                PRIORITY_ORDER.index(a.priority) if a.priority in PRIORITY_ORDER else len(PRIORITY_ORDER),
            ),
        )

        for idx, action in enumerate(sorted_actions, start=1):
            subletter = _subletter(idx)
            effort = action.effort or "?"
            desc = action.description.replace("|", "\\|")
            file_ref = action.file_ref or ""
            unverified = "1" if action.unverified else "0"
            owner = action.owner or ""
            done = "1" if action.done else "0"
            caused_by = action.caused_by or ""
            blocks = action.blocks or ""
            lines.append(
                f"RNS|A|{domain_num}{subletter}|{action.domain}|"
                f"E:{effort}|{action.action}/{action.priority}|"
                f"{desc}|{file_ref}|owner={owner}|done={done}|"
                f"caused_by={caused_by}|blocks={blocks}|unverified={unverified}"
            )

    if carryover:
        domain_num += 1
        lines.append(f"RNS|D|{domain_num}|📌|CARRYOVER")
        for idx, action in enumerate(carryover, start=1):
            subletter = _subletter(idx)
            effort = action.effort or "?"
            desc = action.description.replace("|", "\\|")
            file_ref = action.file_ref or ""
            unverified = "1" if action.unverified else "0"
            owner = action.owner or ""
            done = "1" if action.done else "0"
            caused_by = action.caused_by or ""
            blocks = action.blocks or ""
            lines.append(
                f"RNS|A|{domain_num}{subletter}|carryover|"
                f"E:{effort}|{action.action}/{action.priority}|"
                f"{desc}|{file_ref}|owner={owner}|done={done}|"
                f"caused_by={caused_by}|blocks={blocks}|unverified={unverified}"
            )

    lines.append("RNS|Z|0|NONE")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public entry point used by the skill
# ---------------------------------------------------------------------------

def format_rns_output(
    actions: list[CrossSessionAction],
    carryover: list[CrossSessionAction] | None = None,
    machine_format: bool = False,
    **kwargs,
) -> str:
    """Main entry point. Renders RNS actions with consistent formatting.

    Args:
        actions: List of action items from current session.
        carryover: Carryover items from prior sessions.
        machine_format: If True, return machine-parseable format instead.
        **kwargs: Passed through to RenderOptions.

    Returns:
        Formatted RNS output string.

    Raises:
        ValueError: If any kwarg is not a valid RenderOptions field.
    """
    if kwargs:
        valid_fields = {f.name for f in RenderOptions.__dataclass_fields__.values()}
        invalid = set(kwargs.keys()) - valid_fields
        if invalid:
            raise ValueError(
                f"Unknown render options: {sorted(invalid)}. "
                f"Valid options: {sorted(valid_fields)}"
            )
    if machine_format:
        return render_machine_format(actions, carryover)
    opts = RenderOptions(**kwargs) if kwargs else DEFAULT_OPTIONS
    return render_actions(actions, carryover, opts)
