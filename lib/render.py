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
PRIORITY_ORDER = ("critical", "high", "medium", "low")


# ---------------------------------------------------------------------------
# Format options
# ---------------------------------------------------------------------------

@dataclass
class RenderOptions:
    """Formatting options for the RNS renderer."""
    show_file_refs: bool = True
    show_session_id: bool = False
    show_effort: bool = False
    unverified_marker: str = "[UNVERIFIED]"
    domain_group_order: list[str] | None = None  # None = auto-sort by findings count
    max_description_chars: int | None = None


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

    # Group by domain
    groups: dict[str, list[CrossSessionAction]] = {}
    for action in actions:
        groups.setdefault(action.domain, []).append(action)

    # Build output lines
    lines: list[str] = []
    domain_num = 0

    # Render each domain group in priority order (recover → prevent → realize)
    for domain_key, domain_actions in sorted(
        groups.items(),
        key=lambda kv: _domain_sort_key(kv[0], kv[1]),
    ):
        domain_num += 1
        emoji, label = _get_domain_def(domain_key)
        lines.append(f"{domain_num} {emoji} {label} ({len(domain_actions)})")

        # Sort actions: by action order then priority order
        sorted_actions = sorted(
            domain_actions,
            key=lambda a: (
                ACTION_ORDER.index(a.action) if a.action in ACTION_ORDER else len(ACTION_ORDER),
                PRIORITY_ORDER.index(a.priority) if a.priority in PRIORITY_ORDER else len(PRIORITY_ORDER),
            ),
        )

        for idx, action in enumerate(sorted_actions, start=1):
            subletter = _subletter(idx)
            line = f"  {domain_num}{subletter} {render_action_line(action, opts)}"
            lines.append(line)

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

    # Do-all footer
    total = len(actions) + len(carryover)
    if total > 0:
        lines.append(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"0 — Do ALL Recommended Next Actions ({total} items)")

    return "\n".join(lines).strip()


def render_action_line(action: CrossSessionAction, opts: RenderOptions) -> str:
    """Render a single action as a compact line string."""
    parts = [f"[{action.action}/{action.priority}]"]

    # Description
    desc = action.description
    if opts.max_description_chars and len(desc) > opts.max_description_chars:
        desc = _visual_truncate(desc, opts.max_description_chars)
    parts.append(desc)

    # Unverified marker
    if action.unverified:
        parts.append(opts.unverified_marker)

    # File reference
    if opts.show_file_refs and action.file_ref:
        parts.append(f"@ {action.file_ref}")

    return " ".join(parts)


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
        RNS|A|{num}{sub}|{domain}|E:{effort}|{action}/{priority}|{desc}|{file_ref}
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
            lines.append(
                f"RNS|A|{domain_num}{subletter}|{action.domain}|"
                f"E:{effort}|{action.action}/{action.priority}|"
                f"{desc}|{file_ref}|unverified={unverified}"
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
            lines.append(
                f"RNS|A|{domain_num}{subletter}|carryover|"
                f"E:{effort}|{action.action}/{action.priority}|"
                f"{desc}|{file_ref}|unverified={unverified}"
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
