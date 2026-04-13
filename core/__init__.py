"""RNS — Recommended Next Steps from Arbitrary Output.

Public API:
    from rns import extract_actions, format_rns_output, CrossSessionAction

Or import specific components:
    from rns.chain import extract_actions, get_current_rns_items, ChainRNSResult
    from rns.render import format_rns_output
"""

from __future__ import annotations

from .chain import (
    CrossSessionAction,
    ChainRNSResult,
    _extract_actions_from_text as extract_actions,
    get_current_rns_items,
    get_session_transcript_text,
)
from .render import format_rns_output

__all__ = [
    "CrossSessionAction",
    "ChainRNSResult",
    "extract_actions",
    "format_rns_output",
    "get_current_rns_items",
    "get_session_transcript_text",
]
