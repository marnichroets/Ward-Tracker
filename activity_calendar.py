"""Ntsikana Activity Calendar — a read-only reporting view generated purely
from data Ward Tracker already stores. Never writes anything back to Mongo;
never invents a municipality, ward, or time.

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

from activity_records import activity_time_label, is_reportable_activity
from smartsheet_reporting import classification_for_entry, spreadsheet_safe_text, ward_export_text
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

CALENDAR_TITLE = "Ntsikana Constituency Activity Calendar"

ACTIVITY_LIST_HEADERS = [
    "DATE", "TIME START", "TIME END", "MUNICIPALITY", "WARD", "VENUE",
    "ACTIVITY", "CANDIDATE", "CAMPAIGN", "STATUS",
]

STATUS_SYMBOL = {LOGGED: "✓", PLANNED: "○"}  # checkmark / open circle
STATUS_LEGEND = f"{STATUS_SYMBOL[LOGGED]} Logged    {STATUS_SYMBOL[PLANNED]} Planned"

_WARD_ABBREVIATION_RE = re.compile(r"\bWard\s+(\d+)\b", re.IGNORECASE)
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


_TRAILING_COMPACT_WARD_RE = re.compile(r"^(.*?)\s*(W\d+)$")


def municipality_ward_compact(municipality_ward: str) -> str:
    """"Raymond Mhlaba Ward 7" -> "Raymond Mhlaba W7"; a multi-ward label
    like "Amahlathi Ward 2, Amahlathi Ward 14" collapses to the still fully
    legible "Amahlathi W2, W14" instead of repeating the municipality name
    per ward. Only for the space-constrained Calendar grid — the Activity
    List keeps the full "Ward 7" text. Pure text formatting on the already-
    resolved combined label, so it can never disagree with
    `municipality_ward_label` on what the canonical municipality/ward
    actually is, and never guesses/rewrites a stored value."""
    if not municipality_ward or municipality_ward == MUNICIPALITY_NOT_RECORDED:
        return municipality_ward
    segments = [_WARD_ABBREVIATION_RE.sub(r"W\1", s.strip()) for s in municipality_ward.split(",")]
    if len(segments) == 1:
        return segments[0]
    parsed = [_TRAILING_COMPACT_WARD_RE.match(s) for s in segments]
    if all(parsed):
        prefixes = {m.group(1).strip() for m in parsed}
        if len(prefixes) == 1:
            wards = ", ".join(m.group(2) for m in parsed)
            return f"{prefixes.pop()} {wards}"
    return ", ".join(segments)


def _truncate_for_calendar(text: str, limit: int = 40) -> str:
    """A safety net for the rare long free-text activity (e.g. a
    candidate's custom "Other" entry) that has no confident canonical
    classification — the Calendar grid must stay scannable; the Activity
    List always keeps the untouched full wording regardless. Never called
    on an already-short canonical activity label."""
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def calendar_filename(month_key: str) -> str:
    """"Ntsikana_Activity_Calendar_September_2026.xlsx" — always names the
    actual selected month, never a generic "current"."""
    year, month = (int(p) for p in month_key.split("-"))
    return f"Ntsikana_Activity_Calendar_{FULL_MONTHS[month - 1]}_{year}.xlsx"


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


def logged_calendar_rows(
    entries: Iterable[dict],
    campaign_names: dict,
    municipality_by_person: dict,
    month_start: date,
    month_end: date,
    entry_date_fn,
) -> list[dict]:
    """One calendar row per reportable `entries` document falling inside the
    given month. `entry_date_fn` is injected (rather than imported directly)
    to avoid a circular import between this module and leadership_reporting,
    which itself imports from smartsheet_reporting."""
    rows = []
    for doc in entries:
        if not is_reportable_activity(doc):
            continue
        d = entry_date_fn(doc)
        if not d or not (month_start <= d <= month_end):
            continue
        municipality = municipality_by_person.get(str(doc.get("person_id") or ""), "")
        raw_activity = str(doc.get("type_display") or doc.get("type") or "").strip()
        # The Calendar grid prefers the normalized/canonical activity label
        # (the same one SmartSheet exports use, e.g. "Door to Door") over a
        # candidate's raw free text, so busy-day summaries group correctly
        # and long custom text never overwhelms the grid. `row["activity"]`
        # itself is untouched — the Activity List always shows the exact
        # original wording, never this normalized/truncated form.
        canonical = classification_for_entry(doc).canonical_activity
        calendar_activity = canonical or _truncate_for_calendar(raw_activity or "Activity")
        rows.append({
            "date": d,
            "start_time": str(doc.get("start_time") or "").strip(),
            "end_time": str(doc.get("end_time") or "").strip(),
            "time_label": activity_time_label(doc.get("start_time"), doc.get("end_time")),
            "activity": raw_activity,
            "calendar_activity": calendar_activity,
            "municipality": municipality,
            "ward": str(doc.get("ward") or "").strip(),
            "municipality_ward": municipality_ward_label(municipality, doc.get("ward")),
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
            time_value = str(item.get("time") or "").strip()
            raw_activity = str(item.get("activity_type") or "").strip()
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
) -> list[dict]:
    rows = logged_calendar_rows(entries, campaign_names, municipality_by_person, month_start, month_end, entry_date_fn)
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
# per-line colour — the ✓/○ status symbol already carries that distinction.
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


# 1-4 activities on a day: show each individually. 5+: a busy day becomes a
# wall of text (the exact problem reported for a 119-activity September) —
# switch to a compact per-type count summary instead. The Activity List is
# completely unaffected either way; every activity always stays there.
BUSY_DAY_THRESHOLD = 5


def _calendar_entry_text(row: dict) -> str:
    """Compact, single-line, print-safe entry text: a status symbol (never
    colour alone), the real stored time if there is one (never invented),
    the normalized/canonical activity label, and the compact
    "Municipality Wx" ward form — e.g. "✓ 09:00 Door to Door · Raymond
    Mhlaba W7" or, with no recorded time, "○ Info Table · Amahlathi W4".
    Text is passed through `_xml_safe_text` since it ultimately comes from
    candidate/coordinator-entered data — never from a value Ward Tracker
    generated itself."""
    bits = [STATUS_SYMBOL[row["status"]]]
    if row["start_time"]:
        bits.append(row["start_time"])
    bits.append(_xml_safe_text(row["calendar_activity"]) or "Activity")
    ward = municipality_ward_compact(_xml_safe_text(row["municipality_ward"]))
    return f"{' '.join(bits)} · {ward}" if ward else " ".join(bits)


def _day_summary_lines(day_entries: list[dict]) -> list[str]:
    """A busy day's clean executive summary: total (+ a logged/planned
    split only when the day actually mixes the two), then one line per
    distinct activity type ordered by how common it is that day — e.g.
    "11 activities" / "9 logged · 2 planned" / "5 Door to Door" /
    "2 Canvassing" / "2 Info Table" / "1 Public Meeting" / "1 Meeting"."""
    total = len(day_entries)
    planned = sum(1 for e in day_entries if e["status"] == PLANNED)
    lines = [f"{total} activities"]
    if planned:
        lines.append(f"{total - planned} logged · {planned} planned")
    counts: dict[str, int] = {}
    for e in day_entries:
        label = _xml_safe_text(e["calendar_activity"]) or "Activity"
        counts[label] = counts.get(label, 0) + 1
    for label, n in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"{n} {label}")
    return lines


def _day_content_lines(day_entries: list[dict]) -> list[str]:
    if len(day_entries) >= BUSY_DAY_THRESHOLD:
        return _day_summary_lines(day_entries)
    return [_calendar_entry_text(entry) for entry in day_entries]


def _day_cell_text(day: int, day_entries: list[dict]) -> str:
    """The day number followed by its compact content (individual entries,
    or a busy-day summary), as a single plain string (see `_DAY_CELL_FONT`
    for why this is deliberately not rich text)."""
    lines = [str(day)] + _day_content_lines(day_entries)
    return "\n".join(lines)


def _write_calendar_sheet(ws, month_key: str, rows: list[dict]) -> None:
    """A clean, restrained monthly grid (7 columns, Mon..Sun) built with the
    app's one established DA/Ntsikana Excel palette and logo (the same one
    the Coordinator/Leadership weekly report workbook already uses safely)
    — no separate provincial reference workbook was available to Claude
    Code to inspect/copy a specific layout from (see module docstring)."""
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
    header_line(4, "Activity Calendar", _TITLE_FONT)
    header_line(5, month_label(month_key), _MONTH_FONT)
    summary_text = (
        f"Total Activities: {total}  |  Logged: {logged}  |  Planned: {planned}"
        if total else "No activities scheduled for this month."
    )
    header_line(6, summary_text, _SUMMARY_FONT)
    header_line(7, STATUS_LEGEND, _LEGEND_FONT)
    ws.row_dimensions[8].height = 6  # thin spacer before the grid

    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    header_row = 9
    for col_idx, name in enumerate(day_names, start=1):
        cell = ws.cell(row=header_row, column=col_idx, value=name)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = _CENTER
        cell.border = THIN_BORDER
    ws.row_dimensions[header_row].height = 20

    grouped = group_by_day(rows)
    first_grid_row = header_row + 1
    lead_blanks = start.weekday()
    grid_row = first_grid_row
    col = lead_blanks + 1
    for c in range(1, lead_blanks + 1):
        cell = ws.cell(row=grid_row, column=c, value="")
        cell.fill = _OUTSIDE_MONTH_FILL
        cell.border = THIN_BORDER

    row_line_counts: dict[int, int] = {}
    cursor = start
    while cursor <= end:
        day_entries = grouped.get(cursor, [])
        cell = ws.cell(row=grid_row, column=col)
        cell.value = _day_cell_text(cursor.day, day_entries)
        cell.font = _DAY_CELL_FONT
        cell.alignment = _WRAP_TOP
        cell.border = THIN_BORDER
        row_line_counts[grid_row] = max(row_line_counts.get(grid_row, 0), 1 + len(_day_content_lines(day_entries)))
        cursor += timedelta(days=1)
        col += 1
        if col > 7:
            col = 1
            grid_row += 1

    # Trailing cells so the final week row is visually complete — subtly
    # shaded as outside the selected month, never showing another month's
    # real activities (which this endpoint was never asked to fetch).
    if col != 1:
        for c in range(col, 8):
            cell = ws.cell(row=grid_row, column=c, value="")
            cell.fill = _OUTSIDE_MONTH_FILL
            cell.border = THIN_BORDER
    last_grid_row = grid_row

    for row_idx in range(first_grid_row, last_grid_row + 1):
        # The busy-day summary bounds line count to roughly
        # 2 + (distinct activity types that day), so even a 100-activity
        # day stays compact — no separate "extreme day" cap is needed to
        # keep the sheet from blowing out, but one stays as a last resort.
        line_count = row_line_counts.get(row_idx, 0)
        ws.row_dimensions[row_idx].height = min(220, max(60, 18 + line_count * 15))
    for c in range(1, 8):
        ws.column_dimensions[get_column_letter(c)].width = 24
    ws.freeze_panes = f"A{first_grid_row}"

    # Print setup: landscape, fit the 7-column grid to one page wide (never
    # shrunk to an unreadable size — height is left to flow across as many
    # pages as a busy month needs), the header block repeated on every
    # printed page.
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
    ws.print_title_rows = f"1:{header_row}"


def calendar_xlsx_bytes(rows: list[dict], month_key: str, include_activity_list: bool = True) -> bytes:
    """Two worksheets: a visual "Calendar" month grid and a flat "Activity
    List" (DATE/TIME START/TIME END/MUNICIPALITY/WARD/VENUE/ACTIVITY/
    CANDIDATE/CAMPAIGN/STATUS) suitable for copying into another system.
    Real Excel date cells (dd/mm/yyyy) and time cells (HH:MM) throughout —
    never plain text that merely looks like a date/time."""
    wb = Workbook()
    ws_calendar = wb.active
    ws_calendar.title = "Calendar"
    _write_calendar_sheet(ws_calendar, month_key, rows)

    if include_activity_list:
        ws_list = wb.create_sheet("Activity List")
        _write_activity_list_sheet(ws_list, rows)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
