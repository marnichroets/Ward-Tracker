import re
from typing import Optional

# Phase 5.1: candidate activity/location validation lives here, deliberately
# separate from smartsheet_reporting.py — that module is a frozen, external
# legacy export format (see CLAUDE.md's SmartSheet hard boundary) and must
# never accumulate unrelated shared logic just because it also happens to
# touch venue/ward text.

_WARD_NUMBER_RE = re.compile(r"^ward\s+(\d+)$", re.IGNORECASE)


def location_is_ward_only(venue: Optional[str], ward: Optional[str]) -> bool:
    """True when a candidate-entered location is just the ward restated
    rather than an actual place ("Ward 13", "ward 13", or "13" for a ward
    named "Ward 13"; "Amahlathi" for a ward named "Amahlathi"). Deliberately
    conservative — trimmed, case-insensitive exact-match only, never fuzzy —
    so a real location that merely mentions the ward ("Mlungisi Community
    Hall, Ward 13") is never rejected. A blank ward (some roster entries are
    intentionally blank) always returns False; the caller separately
    enforces that the location itself is non-blank."""
    v = (venue or "").strip().lower()
    w = (ward or "").strip().lower()
    if not v or not w:
        return False
    if v == w:
        return True
    match = _WARD_NUMBER_RE.match(w)
    if match and v == match.group(1):
        return True
    return False
