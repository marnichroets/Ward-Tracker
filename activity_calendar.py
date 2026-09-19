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
from datetime import date, timedelta
from datetime import time as time_cls
from typing import Iterable, Optional

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from activity_records import activity_time_label, is_reportable_activity
from smartsheet_reporting import spreadsheet_safe_text, ward_export_text
from week_dates import month_bounds, month_label

PLANNED = "PLANNED"
LOGGED = "LOGGED"
STATUSES = (PLANNED, LOGGED)

MUNICIPALITY_NOT_RECORDED = "Municipality not recorded"

CALENDAR_TITLE = "Ntsikana Constituency Activity Calendar"

ACTIVITY_LIST_HEADERS = [
    "DATE", "TIME START", "TIME END", "MUNICIPALITY", "WARD", "VENUE",
    "ACTIVITY", "CANDIDATE", "CAMPAIGN", "STATUS",
]


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
        rows.append({
            "date": d,
            "start_time": str(doc.get("start_time") or "").strip(),
            "end_time": str(doc.get("end_time") or "").strip(),
            "time_label": activity_time_label(doc.get("start_time"), doc.get("end_time")),
            "activity": str(doc.get("type_display") or doc.get("type") or "").strip(),
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
            rows.append({
                "date": d,
                "start_time": time_value,
                "end_time": "",
                "time_label": activity_time_label(time_value or None),
                "activity": str(item.get("activity_type") or "").strip(),
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


# --- Excel workbook ---------------------------------------------------------

_HEADER_FILL = PatternFill("solid", fgColor="1F3B57")
_HEADER_FONT = Font(bold=True, color="FFFFFF")
_TITLE_FONT = Font(bold=True, size=14)
_WRAP_TOP = Alignment(wrap_text=True, vertical="top")
_DATE_NUMBER_FORMAT = "dd/mm/yyyy"
_TIME_NUMBER_FORMAT = "HH:MM"


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
        cell.font = Font(bold=True)
    for row in rows:
        ws.append([
            row["date"],
            _as_time_cell(row["start_time"]),
            _as_time_cell(row["end_time"]),
            spreadsheet_safe_text(row["municipality"] or MUNICIPALITY_NOT_RECORDED),
            spreadsheet_safe_text(row["ward"]),
            spreadsheet_safe_text(row["venue"]),
            spreadsheet_safe_text(row["activity"]),
            spreadsheet_safe_text(row["candidate"]),
            spreadsheet_safe_text(row["campaign_name"]),
            row["status"],
        ])
        r = ws.max_row
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


def _entry_line(row: dict) -> str:
    time_part = row["time_label"]
    return f"{time_part} · {row['activity'] or 'Activity'} ({row['status']})"


def _write_calendar_sheet(ws, month_key: str, rows: list[dict]) -> None:
    """A readable monthly grid (7 columns, Mon..Sun) — the Ward Tracker
    house style (no provincial reference workbook was available to copy a
    specific layout from; see module docstring / CLAUDE.md)."""
    start, end = month_bounds(month_key)
    ws.merge_cells("A1:G1")
    ws["A1"] = f"{CALENDAR_TITLE} — {month_label(month_key)}"
    ws["A1"].font = _TITLE_FONT
    ws.row_dimensions[1].height = 22

    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    ws.append([])
    ws.append(day_names)
    header_row = 3
    for cell in ws[header_row]:
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = Alignment(horizontal="center")

    grouped = group_by_day(rows)

    # Leading blank cells so day 1 lands under its real weekday (Mon=0..Sun=6).
    lead_blanks = start.weekday()
    first_grid_row = header_row + 1
    cursor = start
    grid_row = first_grid_row
    col = lead_blanks + 1
    for c in range(1, lead_blanks + 1):
        ws.cell(row=grid_row, column=c, value="")
    while cursor <= end:
        cell = ws.cell(row=grid_row, column=col)
        day_entries = grouped.get(cursor, [])
        lines = [str(cursor.day)] + [_entry_line(r) for r in day_entries]
        cell.value = "\n".join(lines)
        cell.alignment = _WRAP_TOP
        cursor += timedelta(days=1)
        col += 1
        if col > 7:
            col = 1
            grid_row += 1

    for row_idx in range(first_grid_row, grid_row + 1):
        ws.row_dimensions[row_idx].height = 90
    for c in range(1, 8):
        ws.column_dimensions[get_column_letter(c)].width = 24
    ws.freeze_panes = f"A{first_grid_row}"


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
