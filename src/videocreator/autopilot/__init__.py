"""Channel Autopilot Engine package (`sources`, `rules`)."""
from __future__ import annotations

from videocreator.autopilot.rules import (
    VALID_AUTOPILOT_MODES,
    create_autopilot_rule,
    delete_autopilot_rule,
    get_autopilot_rule,
    hydrate_rule,
    list_autopilot_rules,
    list_autopilot_runs,
    run_autopilot_tick,
    update_autopilot_rule,
    validate_autopilot_policy,
)
from videocreator.autopilot.sources import parse_rss_or_atom_items, strip_html

__all__ = [
    "VALID_AUTOPILOT_MODES",
    "create_autopilot_rule",
    "delete_autopilot_rule",
    "get_autopilot_rule",
    "hydrate_rule",
    "list_autopilot_rules",
    "list_autopilot_runs",
    "parse_rss_or_atom_items",
    "run_autopilot_tick",
    "strip_html",
    "update_autopilot_rule",
    "validate_autopilot_policy",
]
