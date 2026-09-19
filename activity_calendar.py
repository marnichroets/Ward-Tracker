"""Ntsikana Canvassing Calendar — a read-only reporting view generated
purely from data Ward Tracker already stores. Never writes anything back to
Mongo; never invents a municipality, ward, or time.

Scope: this calendar mirrors the Eastern Cape provincial constituency
canvassing calendars, which are built from the Canvassing Activities
reporting scope only — not every Ward Tracker activity type. It therefore
reuses the exact same classifier the existing "Canvassing Activities"
Coordinator report already uses (`smartsheet_reporting.classify_activity_text`
/ `classification_for_entry` + the `CANVASSING` bucket) rather than
inventing a second classification of its own. An activity that the
Canvassing report would count belongs here; one it wouldn't, doesn't — the
two totals always reconcile for the same period. Non-canvassing activities
are never deleted or hidden anywhere else in the app — they simply aren't
part of this specific calendar's scope (they remain fully visible in
Leadership reporting, Activity history, and the Public/Street and Presence
reports where classified).

No Eastern Cape reference workbook was available in this project for
Claude Code to inspect directly (see CLAUDE.md); the block layout below
follows the structure described directly in the brief (Time / Ward +
Municipality / Venue + Activity, stacked per activity) rather than copying
an unseen file.

Two distinct concepts, deliberately kept separate and labelled:
- LOGGED: a normal (or campaign) `entries` document — actual, completed,
  candidate-submitted work. Uses the exact same `is_reportable_activity`
  exclusion rule as every other report (confirmed duplicates never appear).
- PLANNED: one row of a campaign's own `planned_activities` list — future/
  intended campaign work, not yet a real logged activity.

Deduplication: a PLANNED row and a LOGGED activity are never linked at the
individual-row level anywhere in this application (a campaign's
`planned_activities` items carry no reference to the `entries` document a
candidate eventually logs for that work — only the campaign as a whole is
ever marked with a trusted link, via `campaign_link_source`). Because no
reliable explicit link exists at the granularity a calendar needs, this
module never attempts to merge/hide a PLANNED row against a LOGGED one —
both are always shown, clearly labelled. Guessing a match from date/activity/
venue text alone would be exactly the "risky fuzzy matching" this feature is
required to avoid.

Every scheduled activity is always shown in full on the Calendar sheet —
busy days grow the row and wrap text; nothing is ever summarized away, per
the brief's explicit requirement to match the provincial calendars' level
of detail.
"""

import io
import os
import re
from datetime import date, timedelta
from datetime import time as time_cls
from typing import Iterable, Optional

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.drawing.image import Image as XLImage
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from activity_records import activity_time_label, has_trusted_campaign_link, is_reportable_activity
from smartsheet_reporting import (
    CANVASSING,
    classification_for_entry,
    classify_activity_text,
    smartsheet_bucket,
    spreadsheet_safe_text,
    ward_export_text,
)
from week_dates import FULL_MONTHS, month_bounds, month_label
# Reuse the app's one established DA/Ntsikana Excel palette + logo (already
# safely used by the Coordinator/Leadership weekly report workbook) rather
# than inventing a second one — see leadership_reporting.py's own note on
# why LOGO_PATH is a local constant there instead of imported from main.py.
from leadership_reporting import DA_BLUE, DA_NAVY, HEADER_FILL, HEADER_FONT, LOGO_PATH, SHADE_FILL, THIN_BORDER

PLANNED = "PLANNED"
LOGGED = "LOGGED"
STATUSES = (PLANNED, LOGGED)

MUNICIPALITY_NOT_RECORDED = "Municipality not recorded"
WARD_NOT_RECORDED = "Ward not recorded"

CANVASSING_CALENDAR_TITLE = "Ntsikana Constituency Canvassing Calendar"

ACTIVITY_LIST_HEADERS = [
    "DATE", "TIME START", "TIME END", "MUNICIPALITY", "WARD", "VENUE",
    "ACTIVITY", "CANDIDATE", "CAMPAIGN", "STATUS",
]

# Only PLANNED entries are marked — a normal logged canvassing activity
# needs no status clutter at all (per the brief: "do not make status text
# dominate the calendar").
PLANNED_MARK = "○"

# Lone (unpaired) UTF-16 surrogates — never valid in well-formed XML, but not
# covered by openpyxl's own ILLEGAL_CHARACTERS_RE below.
_LONE_SURROGATE_RE = re.compile("[\ud800-\udfff]")


def _xml_safe_text(value: object) -> str:
    """Strip characters Excel's worksheet XML cannot legally contain, before
    any candidate/coordinator-entered text (activity, venue, ward, name,
    campaign) is written into a cell. Reuses openpyxl's own
    `ILLEGAL_CHARACTERS_RE` — the exact pattern openpyxl itself raises
    `IllegalCharacterError` against — rather than inventing new regex logic,
    plus a lone-surrogate strip for malformed Unicode. Export-only: this
    never touches the stored database value, only what gets written to the
    generated workbook."""
    text = str(value or "")
    text = ILLEGAL_CHARACTERS_RE.sub("", text)
    return _LONE_SURROGATE_RE.sub("", text)


def _truncate_for_calendar(text: str, limit: int = 40) -> str:
    """A safety net for the rare long free-text activity (e.g. a
    candidate's custom "Other" entry) that has no confident canonical
    classification — the Calendar grid must stay scannable; the Activity
    List always keeps the untouched full wording regardless. Never called
    on an already-short canonical activity label."""
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def calendar_filename(month_key: str) -> str:
    """"Ntsikana_Canvassing_Calendar_September_2026.xlsx" — always names the
    actual selected month, never a generic "current"."""
    year, month = (int(p) for p in month_key.split("-"))
    return f"Ntsikana_Canvassing_Calendar_{FULL_MONTHS[month - 1]}_{year}.xlsx"


def municipality_ward_label(municipality: object, wards: object) -> str:
    """Canonical calendar display text: "Raymond Mhlaba Ward 7", "Amahlathi
    Ward 2, Amahlathi Ward 14" for a multi-ward campaign, or the bare
    municipality when no ward is on record. Only ever reads the supplied
    municipality/ward values (already resolved from the roster/campaign by
    the caller) — never infers anything from venue, name, or notes text.
    Reuses `ward_export_text` (the same combiner the SmartSheet exports use)
    so the two features can never drift on what "combined" means."""
    municipality = str(municipality or "").strip()
    if not municipality:
        return MUNICIPALITY_NOT_RECORDED
    if isinstance(wards, (list, tuple, set)):
        ward_list = [str(w or "").strip() for w in wards if str(w or "").strip()]
    else:
        single = str(wards or "").strip()
        ward_list = [single] if single else []
    if not ward_list:
        return municipality
    return ", ".join(ward_export_text(ward, municipality) for ward in ward_list)


def resolve_logged_activity_geography(
    doc: dict,
    municipality_by_person: dict,
    actual_wards_by_person: Optional[dict] = None,
    trusted_campaign_geography: Optional[dict] = None,
) -> tuple[str, str]:
    """(municipality, ward) for a LOGGED activity — display/export
    enrichment only, never written back to Mongo, never guessed across
    ambiguity. Safe precedence:

    A. The activity's own stored `municipality`, if any (`entries`
       documents don't currently persist one, but this is checked first in
       case a future write path ever adds it — never overridden if present).
    B. If the activity is explicitly, *trust*-linked to a campaign
       (`has_trusted_campaign_link` — the same shared rule Campaign
       Administration's "confirmed" vs "needs review" split already uses)
       and that campaign has its own municipality, use it. A legacy/
       unverified campaign link is never trusted for this.
    C. The candidate's own canonical roster municipality (the pre-existing
       lookup this calendar already used).
    D. If the activity's own `ward` text is blank, fill it in only when the
       candidate has *exactly one* confirmed canonical ward on the
       roster — never guessed for a multi-ward candidate. The activity's
       own non-blank ward text is always used verbatim, never overridden.
    """
    actual_wards_by_person = actual_wards_by_person or {}
    trusted_campaign_geography = trusted_campaign_geography or {}
    person_id = str(doc.get("person_id") or "")

    municipality = str(doc.get("municipality") or "").strip()  # A
    if not municipality and doc.get("campaign_id") and has_trusted_campaign_link(doc):
        campaign_municipality, _campaign_wards = trusted_campaign_geography.get(str(doc["campaign_id"]), ("", []))
        municipality = str(campaign_municipality or "").strip()  # B
    if not municipality:
        municipality = str(municipality_by_person.get(person_id, "") or "").strip()  # C

    ward = str(doc.get("ward") or "").strip()
    if not ward and municipality:
        confirmed_wards = [str(w).strip() for w in (actual_wards_by_person.get(person_id) or []) if str(w).strip()]
        if len(confirmed_wards) == 1:
            ward = confirmed_wards[0]  # D — single confirmed ward only, never a guess among several

    return municipality, ward


def logged_calendar_rows(
    entries: Iterable[dict],
    campaign_names: dict,
    municipality_by_person: dict,
    month_start: date,
    month_end: date,
    entry_date_fn,
    actual_wards_by_person: Optional[dict] = None,
    trusted_campaign_geography: Optional[dict] = None,
) -> list[dict]:
    """One calendar row per reportable `entries` document falling inside the
    given month AND classified CANVASSING by the exact same shared
    classifier the "Canvassing Activities" Coordinator report uses — never
    a separate/duplicated classification. `entry_date_fn` is injected
    (rather than imported directly) to avoid a circular import between this
    module and leadership_reporting, which itself imports from
    smartsheet_reporting."""
    rows = []
    for doc in entries:
        if not is_reportable_activity(doc):
            continue
        d = entry_date_fn(doc)
        if not d or not (month_start <= d <= month_end):
            continue
        classification = classification_for_entry(doc)
        if smartsheet_bucket(classification) != CANVASSING:
            continue
        municipality, ward = resolve_logged_activity_geography(
            doc, municipality_by_person, actual_wards_by_person, trusted_campaign_geography,
        )
        raw_activity = str(doc.get("type_display") or doc.get("type") or "").strip()
        # The Calendar grid prefers the normalized/canonical activity label
        # (the same one the SmartSheet Canvassing export uses, e.g. "Door
        # to Door") over a candidate's raw free text, so long custom
        # wording never overwhelms the grid. `row["activity"]` itself is
        # untouched — the Activity List always shows the exact original
        # wording, never this normalized/truncated form.
        calendar_activity = classification.canonical_activity or _truncate_for_calendar(raw_activity or "Activity")
        rows.append({
            "date": d,
            "start_time": str(doc.get("start_time") or "").strip(),
            "end_time": str(doc.get("end_time") or "").strip(),
            "time_label": activity_time_label(doc.get("start_time"), doc.get("end_time")),
            "activity": raw_activity,
            "calendar_activity": calendar_activity,
            "municipality": municipality,
            "ward": ward,
            "municipality_ward": municipality_ward_label(municipality, ward),
            "venue": str(doc.get("venue") or "").strip(),
            "candidate": str(doc.get("name") or "").strip(),
            "campaign_name": campaign_names.get(str(doc.get("campaign_id") or ""), ""),
            "status": LOGGED,
        })
    return rows


def planned_calendar_rows(
    campaigns: Iterable[dict],
    roster_names: dict,
    month_start: date,
    month_end: date,
) -> list[dict]:
    """One calendar row per campaign `planned_activities` item falling
    inside the given month. Draft campaigns are excluded — a draft is not
    yet committed campaign information, matching the same
    `submission_status != "draft"` rule every other campaign-facing report
    already applies (e.g. `admin_campaigns`, `filtered_campaigns`)."""
    rows = []
    for campaign in campaigns:
        if campaign.get("submission_status") == "draft":
            continue
        municipality = str(campaign.get("municipality") or "").strip()
        wards = list(campaign.get("wards") or [])
        campaign_name = str(campaign.get("name") or "").strip() or "Untitled campaign"
        candidate = roster_names.get(str(campaign.get("person_id") or ""), "")
        for item in campaign.get("planned_activities") or []:
            raw_date = str(item.get("date") or "").strip()
            try:
                d = date.fromisoformat(raw_date)
            except (TypeError, ValueError):
                continue
            if not (month_start <= d <= month_end):
                continue
            raw_activity = str(item.get("activity_type") or "").strip()
            # Same shared classifier as logged rows, applied to the raw
            # planned activity_type text (a planned item carries no stored
            # smartsheet_category — there is nothing to submit into
            # SmartSheet until it becomes a real logged activity).
            if smartsheet_bucket(classify_activity_text(raw_activity)) != CANVASSING:
                continue
            time_value = str(item.get("time") or "").strip()
            rows.append({
                "date": d,
                "start_time": time_value,
                "end_time": "",
                "time_label": activity_time_label(time_value or None),
                "activity": raw_activity,
                # Planned activity_type is already chosen from the fixed
                # official activity list (see main.py's
                # _planned_activity_required_gaps) — already short/
                # canonical, but still passed through the same truncation
                # safety net for consistency with logged rows.
                "calendar_activity": _truncate_for_calendar(raw_activity or "Activity"),
                "municipality": municipality,
                "ward": ", ".join(wards),
                "municipality_ward": municipality_ward_label(municipality, wards),
                "venue": str(item.get("area") or "").strip(),
                "candidate": candidate,
                "campaign_name": campaign_name,
                "status": PLANNED,
            })
    return rows


def build_calendar_entries(
    entries: Iterable[dict],
    campaigns: Iterable[dict],
    campaign_names: dict,
    municipality_by_person: dict,
    roster_names: dict,
    month_start: date,
    month_end: date,
    entry_date_fn,
    status_filter: Optional[str] = None,
    actual_wards_by_person: Optional[dict] = None,
    trusted_campaign_geography: Optional[dict] = None,
) -> list[dict]:
    rows = logged_calendar_rows(
        entries, campaign_names, municipality_by_person, month_start, month_end, entry_date_fn,
        actual_wards_by_person, trusted_campaign_geography,
    )
    rows += planned_calendar_rows(campaigns, roster_names, month_start, month_end)
    if status_filter and status_filter != "all":
        status_filter = status_filter.upper()
        rows = [r for r in rows if r["status"] == status_filter]
    rows.sort(key=lambda r: (r["date"], r["start_time"] or "", r["status"], r["candidate"]))
    return rows


def group_by_day(rows: Iterable[dict]) -> dict[date, list[dict]]:
    grouped: dict[date, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["date"], []).append(row)
    return grouped


def calendar_summary_counts(rows: list[dict]) -> tuple[int, int, int]:
    """(total, logged, planned) computed directly from the same `rows` list
    the grid and Activity List are built from, so the summary line can
    never drift from what the sheet actually shows."""
    total = len(rows)
    logged = sum(1 for r in rows if r["status"] == LOGGED)
    return total, logged, total - logged


# --- Excel workbook ---------------------------------------------------------

_TITLE_FONT = Font(bold=True, size=16, color=DA_NAVY)
_ORG_FONT = Font(bold=True, size=11, color=DA_NAVY)
_MONTH_FONT = Font(bold=True, size=13, color=DA_BLUE)
_SUMMARY_FONT = Font(size=10, color="5B6472")
_LEGEND_FONT = Font(size=9, italic=True, color="5B6472")
_WRAP_TOP = Alignment(wrap_text=True, vertical="top")
_CENTER = Alignment(horizontal="center", vertical="center")
_OUTSIDE_MONTH_FILL = PatternFill("solid", fgColor="F6F8FB")
# A subtle whole-cell tint for a Planned activity cell — additive to the
# "○" mark on the cell's own time/status line, never the only signal
# (status is still legible with colour off, e.g. printed in greyscale).
_PLANNED_CELL_FILL = PatternFill("solid", fgColor="EAF2FB")
_DATE_NUMBER_FORMAT = "dd/mm/yyyy"
_TIME_NUMBER_FORMAT = "HH:MM"
# One plain, whole-cell font for every day cell — deliberately NOT openpyxl
# rich text (CellRichText/TextBlock/InlineFont). Mixed per-run colouring
# inside a single inline string was producing a run consisting solely of a
# "\n" separator with no `xml:space="preserve"` attribute, which Excel's
# strict OOXML validator rejects — triggering "We found a problem with some
# content..." and repairing (silently dropping) the whole cell value. A
# single plain Python string assigned as a cell's `.value` is openpyxl's
# ordinary, extensively-proven write path (used by every other export in
# this app) and always serializes as one well-formed <is><t>...</t></is>
# element, newlines included, with no separate runs. Reliability over
# per-line colour — the ○ Planned mark already carries that distinction.
_DAY_CELL_FONT = Font(size=10, color=DA_NAVY)


def _as_time_cell(value: object) -> Optional[time_cls]:
    if not value:
        return None
    try:
        return time_cls.fromisoformat(str(value))
    except ValueError:
        return None


def _write_activity_list_sheet(ws, rows: list[dict]) -> None:
    # Separate MUNICIPALITY/WARD columns (not the combined "Raymond Mhlaba
    # Ward 7" text used on the Calendar grid) — this sheet exists so the
    # data can be copied straight into another system, matching the same
    # separate-columns convention the Official Capture export already uses.
    ws.append(ACTIVITY_LIST_HEADERS)
    for cell in ws[1]:
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = THIN_BORDER
    for offset, row in enumerate(rows):
        ws.append([
            row["date"],
            _as_time_cell(row["start_time"]),
            _as_time_cell(row["end_time"]),
            spreadsheet_safe_text(_xml_safe_text(row["municipality"] or MUNICIPALITY_NOT_RECORDED)),
            spreadsheet_safe_text(_xml_safe_text(row["ward"])),
            spreadsheet_safe_text(_xml_safe_text(row["venue"])),
            spreadsheet_safe_text(_xml_safe_text(row["activity"])),
            spreadsheet_safe_text(_xml_safe_text(row["candidate"])),
            spreadsheet_safe_text(_xml_safe_text(row["campaign_name"])),
            row["status"],
        ])
        r = ws.max_row
        row_fill = SHADE_FILL if offset % 2 == 1 else None
        for col_idx in range(1, len(ACTIVITY_LIST_HEADERS) + 1):
            cell = ws.cell(row=r, column=col_idx)
            cell.border = THIN_BORDER
            if row_fill:
                cell.fill = row_fill
        ws.cell(row=r, column=1).number_format = _DATE_NUMBER_FORMAT
        for col in (2, 3):
            if ws.cell(row=r, column=col).value is not None:
                ws.cell(row=r, column=col).number_format = _TIME_NUMBER_FORMAT
        ws.cell(row=r, column=6).alignment = _WRAP_TOP  # VENUE
        ws.cell(row=r, column=7).alignment = _WRAP_TOP  # ACTIVITY

    ws.freeze_panes = "A2"
    last_row = max(1, len(rows) + 1)
    ws.auto_filter.ref = f"A1:{get_column_letter(len(ACTIVITY_LIST_HEADERS))}{last_row}"

    # Fixed, sensible widths (Venue/Activity/Campaign a little wider since
    # they wrap) rather than a content-length scan — this sheet's columns
    # are narrow/uniform enough that auto-sizing adds nothing.
    width_caps = {6: 40, 7: 34, 9: 28}
    for col_idx in range(1, len(ACTIVITY_LIST_HEADERS) + 1):
        ws.column_dimensions[get_column_letter(col_idx)].width = width_caps.get(col_idx, 22)


_WARD_WORD_RE = re.compile(r"\bWard\b", re.IGNORECASE)


def _ward_municipality_block_line(municipality: object, ward_text: object) -> str:
    """The provincial-style ward-first block line: "Wrd 7 · Raymond Mhlaba",
    "Wrd 14 · Amahlathi", or "Wrd 2, Wrd 14 · Amahlathi" for a multi-ward
    campaign — ward numbers repeat between municipalities, so both are
    always shown together. A known municipality with a genuinely unresolved
    ward shows "Amahlathi · Ward not recorded" — the known fact leads,
    never a guessed ward. Reuses `ward_export_text` (the exact combiner the
    SmartSheet exports use) per ward to decide whether a legacy ward value
    already spells out its own municipality, so this can never duplicate
    the municipality name — canonical stored data only, never a guess.
    `MUNICIPALITY_NOT_RECORDED` when genuinely unknown."""
    municipality = str(municipality or "").strip()
    if not municipality:
        return MUNICIPALITY_NOT_RECORDED
    ward_parts = [w.strip() for w in str(ward_text or "").split(",") if w.strip()]
    if not ward_parts:
        return f"{municipality} · {WARD_NOT_RECORDED}"
    formatted_wards = []
    for ward_raw in ward_parts:
        combined = ward_export_text(ward_raw, municipality)
        match = re.match(rf"^{re.escape(municipality)}\s+Ward\s+(\d+)$", combined, re.IGNORECASE)
        if match:
            formatted_wards.append(f"Wrd {match.group(1)}")
        elif combined.lower() != municipality.lower():
            formatted_wards.append(_WARD_WORD_RE.sub("Wrd", combined))
    if not formatted_wards:
        # The ward text existed but was itself just the municipality name
        # (legacy data) — already fully represented by the municipality
        # alone; not the "genuinely unresolved" case, so no "not recorded".
        return municipality
    return f"{', '.join(formatted_wards)} · {municipality}"


def _venue_activity_block_line(row: dict) -> str:
    """"Bedford · Door to Door", or just "Door to Door" when no venue was
    recorded — never a literal "None"/blank placeholder. Uses the
    normalized/canonical activity label; the Activity List always keeps
    the original wording untouched."""
    venue = _xml_safe_text(row["venue"]).strip()
    activity = _xml_safe_text(row["calendar_activity"]).strip() or "Activity"
    return f"{venue} · {activity}" if venue else activity


def _calendar_activity_block(row: dict) -> list[str]:
    """The provincial-style 3-line activity block — Time / Ward + Municipality
    / Venue + Activity — matching the Eastern Cape constituency calendars'
    own layout. A normal logged canvassing activity carries no status text
    at all (per the brief: status must never dominate the calendar); a
    planned campaign activity is marked with a single subtle "○" on its
    time line (or, with no recorded time, its own short line) so it stays
    clearly but quietly distinguishable. Never invents a missing time —
    the time line is simply omitted when neither start nor end is stored."""
    lines: list[str] = []
    time_line = row["time_label"] if row["start_time"] else ""
    if row["status"] == PLANNED:
        lines.append(f"{PLANNED_MARK} {time_line}" if time_line else f"{PLANNED_MARK} Planned")
    elif time_line:
        lines.append(time_line)
    lines.append(_ward_municipality_block_line(row["municipality"], row["ward"]))
    lines.append(_venue_activity_block_line(row))
    return lines


ACTIVITY_ROW_HEIGHT = 54  # within the required ~42-60pt range for every normal body row
_MAX_ACTIVITY_ROW_HEIGHT = 60
_MIN_ACTIVITY_ROW_HEIGHT = 42

DAY_ABBREVIATIONS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]

_WEEK_LABEL_FONT = Font(bold=True, size=10, color="5B6472")
_DAY_HEADER_FILL = HEADER_FILL
_WEEKEND_HEADER_FILL = PatternFill("solid", fgColor=DA_NAVY)
_OUTSIDE_MONTH_HEADER_FILL = PatternFill("solid", fgColor="C9D3DE")


def _week_starts(start: date, end: date) -> list[date]:
    """Every Monday whose Mon-Sun week overlaps [start, end] — i.e. one
    entry per weekly section the sheet will render."""
    first_monday = start - timedelta(days=start.weekday())
    weeks = []
    cursor = first_monday
    while cursor <= end:
        weeks.append(cursor)
        cursor += timedelta(days=7)
    return weeks


def _week_section_label(week_start: date) -> str:
    """"WEEK 14–20 SEPTEMBER" for a week inside one month, or
    "WEEK 31 AUG – 6 SEP" when a week spans a month boundary."""
    week_end = week_start + timedelta(days=6)
    if week_start.month == week_end.month:
        return f"WEEK {week_start.day}–{week_end.day} {FULL_MONTHS[week_start.month - 1].upper()}"
    start_label = f"{week_start.day} {FULL_MONTHS[week_start.month - 1][:3].upper()}"
    end_label = f"{week_end.day} {FULL_MONTHS[week_end.month - 1][:3].upper()}"
    return f"WEEK {start_label} – {end_label}"


def _write_calendar_sheet(ws, month_key: str, rows: list[dict]) -> None:
    """A clean, restrained monthly grid built with the app's one
    established DA/Ntsikana Excel palette and logo (the same one the
    Coordinator/Leadership weekly report workbook already uses safely) —
    no separate provincial reference workbook was available to Claude Code
    to inspect/copy a specific layout from (see module docstring).

    Rendered as 4-6 independent weekly sections (a week-period label, a
    Mon..Sun day/date header, then one NORMAL-height Excel row per activity
    slot that week) rather than one giant multi-line row per week — see the
    module docstring for why: a single ~300pt row was making Excel's
    on-screen scrolling jump across nearly half a week's worth of content
    at once. No body activity cell is ever merged vertically."""
    start, end = month_bounds(month_key)
    total, logged, planned = calendar_summary_counts(rows)

    if LOGO_PATH and os.path.exists(LOGO_PATH):
        logo_img = XLImage(LOGO_PATH)
        logo_img.width = 40
        logo_img.height = 48
        ws.add_image(logo_img, "A1")
    ws.row_dimensions[1].height = 36

    def header_line(row_idx: int, text: str, font: Font) -> None:
        ws.merge_cells(start_row=row_idx, start_column=1, end_row=row_idx, end_column=7)
        ws.cell(row=row_idx, column=1, value=text).font = font

    header_line(2, "Democratic Alliance", _ORG_FONT)
    header_line(3, "Ntsikana Constituency", _ORG_FONT)
    header_line(4, "Canvassing Calendar", _TITLE_FONT)
    header_line(5, month_label(month_key), _MONTH_FONT)
    if not total:
        summary_text = "No canvassing activities scheduled for this month."
    elif planned:
        summary_text = f"Logged: {logged}  |  Planned: {planned}"
    else:
        summary_text = f"Canvassing Activities: {total}"
    header_line(6, summary_text, _SUMMARY_FONT)
    # A planned campaign activity is the only thing ever marked on this
    # calendar (a normal logged canvassing activity carries no status text
    # at all) — the legend only needs to exist when there's something to
    # explain.
    header_line(7, f"{PLANNED_MARK} Planned (future campaign activity)" if planned else "", _LEGEND_FONT)
    ws.row_dimensions[8].height = 6  # thin spacer before the weekly sections

    grouped = group_by_day(rows)
    row_idx = 9
    first_week_row = row_idx

    for week_start in _week_starts(start, end):
        week_dates = [week_start + timedelta(days=i) for i in range(7)]

        # Week-period label, e.g. "WEEK 14-20 SEPTEMBER" — subtle, not a
        # second loud header competing with the day row below it.
        ws.merge_cells(start_row=row_idx, start_column=1, end_row=row_idx, end_column=7)
        ws.cell(row=row_idx, column=1, value=_week_section_label(week_start)).font = _WEEK_LABEL_FONT
        ws.row_dimensions[row_idx].height = 18
        row_idx += 1

        # Strong day/date header — weekends get a subtly different (still
        # on-brand navy, not a different colour family) fill so Sat/Sun
        # read as visually distinct without being loud about it.
        day_header_row = row_idx
        for col_idx, d in enumerate(week_dates, start=1):
            in_month = start <= d <= end
            cell = ws.cell(row=day_header_row, column=col_idx, value=f"{DAY_ABBREVIATIONS[col_idx - 1]} {d.day}")
            cell.font = HEADER_FONT
            if not in_month:
                cell.fill = _OUTSIDE_MONTH_HEADER_FILL
            elif col_idx >= 6:  # Saturday, Sunday
                cell.fill = _WEEKEND_HEADER_FILL
            else:
                cell.fill = _DAY_HEADER_FILL
            cell.alignment = _CENTER
            cell.border = THIN_BORDER
        ws.row_dimensions[day_header_row].height = 20
        row_idx += 1

        day_entries_this_week = [grouped.get(d, []) if (start <= d <= end) else [] for d in week_dates]
        activity_row_count = max(1, max((len(e) for e in day_entries_this_week), default=1))

        for slot in range(activity_row_count):
            for col_idx, d in enumerate(week_dates, start=1):
                cell = ws.cell(row=row_idx, column=col_idx)
                in_month = start <= d <= end
                entries_today = day_entries_this_week[col_idx - 1]
                if slot < len(entries_today):
                    cell.value = "\n".join(_calendar_activity_block(entries_today[slot]))
                    if entries_today[slot]["status"] == PLANNED:
                        cell.fill = _PLANNED_CELL_FILL
                else:
                    cell.value = ""
                    if not in_month:
                        cell.fill = _OUTSIDE_MONTH_FILL
                cell.font = _DAY_CELL_FONT
                cell.alignment = _WRAP_TOP
                cell.border = THIN_BORDER
            # Every normal body row stays within the required ~42-60pt
            # range — never the several-hundred-point rows the old one-
            # row-per-week layout produced. Three block lines fit
            # comfortably at this height even with modest text wrapping.
            ws.row_dimensions[row_idx].height = min(_MAX_ACTIVITY_ROW_HEIGHT, max(_MIN_ACTIVITY_ROW_HEIGHT, ACTIVITY_ROW_HEIGHT))
            row_idx += 1

        row_idx += 1  # one blank spacer row between weekly sections

    last_row = row_idx - 1
    for c in range(1, 8):
        ws.column_dimensions[get_column_letter(c)].width = 26

    # Freeze only the constituency header block — the useful top area —
    # never an entire week's worth of rows, so Week 1 -> Week 2 -> ... ->
    # Week 5 scrolls the same way any ordinary Excel sheet does.
    ws.freeze_panes = f"A{first_week_row}"

    # Print setup: landscape, fit the 7-column grid to one page wide (never
    # shrunk to an unreadable size — height is left to flow across as many
    # pages as a busy month needs), the DA/constituency header block
    # repeated on every printed page.
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_margins.left = 0.4
    ws.page_margins.right = 0.4
    ws.page_margins.top = 0.5
    ws.page_margins.bottom = 0.5
    ws.page_margins.header = 0.2
    ws.page_margins.footer = 0.2
    ws.print_title_rows = "1:8"


def calendar_xlsx_bytes(rows: list[dict], month_key: str, include_activity_list: bool = True) -> bytes:
    """Two worksheets: a visual "Calendar" month grid (Canvassing-scoped
    only) and a flat "Canvassing Activity List" (DATE/TIME START/TIME END/
    MUNICIPALITY/WARD/VENUE/ACTIVITY/CANDIDATE/CAMPAIGN/STATUS) suitable
    for copying into another system — every row the Calendar sheet draws
    from, and nothing else. Real Excel date cells (dd/mm/yyyy) and time
    cells (HH:MM) throughout — never plain text that merely looks like a
    date/time."""
    wb = Workbook()
    ws_calendar = wb.active
    ws_calendar.title = "Calendar"
    _write_calendar_sheet(ws_calendar, month_key, rows)

    if include_activity_list:
        ws_list = wb.create_sheet("Canvassing Activity List")
        _write_activity_list_sheet(ws_list, rows)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
