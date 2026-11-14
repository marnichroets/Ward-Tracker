"""Leadership Meeting Pack — a one-click 16:9 presentation (PDF and
editable PowerPoint) for the Constituency Leader.

Three layers, so the two formats can never disagree:
  1. build_meeting_pack(): every figure comes from leadership_reporting.
     build_dashboard() for the chosen period (plus one more build_dashboard()
     call for the next 14 days of planned activities). Nothing here
     recomputes a total; it only selects, orders and words those figures.
  2. _compose(): lays out the eight slides once, in inches, against a tiny
     drawing interface. Text is wrapped/shortened here with one set of font
     metrics, so both formats show exactly the same words.
  3. _PdfWriter (reportlab) and _PptxWriter (python-pptx) draw that layout.
     PowerPoint keeps text, tables and charts editable.

Completed vs planned uses the activity DATE, independent of the retired
Campaign Manager capture flags. Historical records remain untouched.
"""

import io
import math
import os
from datetime import date, datetime, timedelta
from typing import Iterable, Optional

from reportlab.pdfbase.pdfmetrics import stringWidth

import leadership_reporting as lr
from week_dates import FULL_MONTHS, MONTHS, sast_today

LOGO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "logo.png")
MAX_WEEKS = 26
UPCOMING_DAYS = 14
SLIDE_W, SLIDE_H = 13.333, 7.5  # inches, 16:9

NAVY = "153B63"
BLUE = "2568AE"
GOLD = "D89B3C"
GOLD_LIGHT = "FCF3E3"
INK = "13202F"
INK2 = "3B4859"
INK3 = "5E6B7C"
LINE = "DCE2EA"
PAPER = "F3F5F8"
WHITE = "FFFFFF"
TEAL = "1F8A70"      # completed
AMBER = "C2862C"
PLANNED = "A9C4E6"   # future planned activity
GOOD = "2F7A4B"
BAD = "B0473A"


# ---------------------------------------------------------------- dates

def long_date(d: date) -> str:
    return f"{d.strftime('%A')}, {d.day} {FULL_MONTHS[d.month - 1]} {d.year}"


def short_date(d: date) -> str:
    return f"{d.day} {MONTHS[d.month - 1]}"


def period_long_label(start: date, end: date) -> str:
    left = f"{start.strftime('%A')} {start.day} {FULL_MONTHS[start.month - 1]}"
    if start.year != end.year:
        left += f" {start.year}"
    return f"{left} – {end.strftime('%A')} {end.day} {FULL_MONTHS[end.month - 1]} {end.year}"


def period_short_label(start: date, end: date) -> str:
    if start.year != end.year:
        return f"{short_date(start)} {start.year} – {short_date(end)} {end.year}"
    if start.month == end.month:
        return f"{start.day}–{end.day} {MONTHS[end.month - 1]} {end.year}"
    return f"{short_date(start)} – {short_date(end)} {end.year}"


def default_period(now=None) -> tuple[date, date]:
    """The latest COMPLETED Monday-Sunday week (the current week only ends
    after Sunday, so it never counts as completed)."""
    today = sast_today(now)
    monday = today - timedelta(days=today.weekday())
    return monday - timedelta(days=7), monday - timedelta(days=1)


def resolve_meeting_period(date_from: Optional[str], date_to: Optional[str], now=None) -> tuple[date, date]:
    if not date_from and not date_to:
        return default_period(now)
    if not date_from or not date_to:
        raise ValueError("Choose both the first and the last day of the reporting period.")
    start, end = lr.parse_iso_date(date_from, "date_from"), lr.parse_iso_date(date_to, "date_to")
    if start.weekday() != 0 or end.weekday() != 6:
        raise ValueError("A meeting pack covers whole Monday–Sunday reporting weeks.")
    if end < start:
        raise ValueError("The reporting period ends before it starts.")
    weeks = ((end - start).days + 1) // 7
    if weeks > MAX_WEEKS:
        raise ValueError(f"A meeting pack can cover at most {MAX_WEEKS} weeks; choose a shorter period.")
    return start, end


# ---------------------------------------------------------------- data

def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def build_meeting_pack(
    entries: Iterable[dict],
    roster: Iterable[dict],
    campaigns: Iterable[dict],
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    now: datetime | date | None = None,
) -> dict:
    entries, roster, campaigns = list(entries), list(roster), list(campaigns)
    today = sast_today(now)
    start, end = resolve_meeting_period(date_from, date_to, now)
    d = lr.build_dashboard(entries, roster, campaigns, preset="custom",
                           date_from=start.isoformat(), date_to=end.isoformat(), now=now)
    up_from, up_to = today + timedelta(days=1), today + timedelta(days=UPCOMING_DAYS)
    upcoming = lr.build_dashboard(entries, roster, campaigns, preset="custom",
                                  date_from=up_from.isoformat(), date_to=up_to.isoformat(), now=now)

    kpis, cmp = d["kpis"], d["comparison"]
    total = kpis["total_activities"]
    # An activity's date — never an old manual capture flag — determines
    # whether the work has happened.
    planned = sum(1 for row in d["weekly_activity"]
                  if (dt := lr.maybe_date(row.get("activity_date"))) and dt > today)
    completed = total - planned
    previous_end = start - timedelta(days=1)
    # A zero in an entirely unobserved earlier period is not evidence of a
    # genuine zero. Make the baseline unavailable if the tracker contains
    # no records on/before the comparison period's end.
    comparable_history = any((dt := lr.entry_date(row)) and dt <= previous_end
                             for row in lr.reportable_activities(entries))
    part, wards = kpis["candidate_participation"], kpis["wards_active"]
    state = "completed" if end < today else ("not_started" if start > today else "in_progress")

    period = {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "label": period_long_label(start, end),
        "short_label": period_short_label(start, end),
        "weeks": ((end - start).days + 1) // 7,
        "state": state,
        "state_label": {
            "completed": "Completed reporting period",
            "in_progress": "Period in progress — includes planned activities",
            "not_started": "Period not started — all activities are planned",
        }[state],
    }

    # ---- executive summary: factual and explicitly dated
    summary = []
    if not total:
        summary.append("No activities were recorded for the selected period.")
    elif state == "completed":
        summary.append(f"{_plural(total, 'activity was', 'activities were')} recorded by {part['submitted']} of "
                       f"{part['expected']} candidates across {wards['active']} of {wards['total']} wards.")
    elif state == "in_progress":
        summary.append(f"{completed} activities are dated on or before the report date and {planned} are planned for future dates; "
                       f"{part['submitted']} of {part['expected']} candidates have recorded activities or plans.")
    else:
        summary.append(f"{planned} activities are planned by {part['submitted']} of "
                       f"{part['expected']} candidates; none has taken place yet.")
    if state != "not_started" and comparable_history:
        a = cmp["activities"]
        summary.append(f"{a['label']} ({cmp['period_label']}): {a['previous']} → {a['current']} activities.")
    elif state != "not_started":
        summary.append("No comparable earlier activity history is available in Ward Tracker.")
    if total:
        summary.append(f"{kpis['total_canvassing']} canvassing activities recorded"
                       f"{' (including future plans)' if planned else ''}.")

    def comparison_note(metric, fallback):
        return cmp[metric]["label"] if comparable_history and state != "not_started" else fallback

    tiles = [
        {"label": "Recorded activities", "value": str(total),
         "note": f"{completed} completed · {planned} planned" if planned else comparison_note("activities", "Selected reporting period")},
        {"label": "Canvassing", "value": str(kpis["total_canvassing"]),
         "note": "Includes future plans" if planned else comparison_note("canvassing", "Selected reporting period")},
        {"label": "Candidates planned" if state == "not_started" else "Candidates logged",
         "value": f"{part['submitted']} of {part['expected']}",
         "note": cmp["participation"]["label"] if comparable_history and state == "completed" else ("Includes plans" if state == "in_progress" else "In this reporting period")},
        {"label": "Wards planned" if state == "not_started" else "Wards recorded",
         "value": f"{wards['active']} of {wards['total']}",
         "note": cmp["active_wards"]["label"] if comparable_history and state == "completed" else ("Includes plans" if state == "in_progress" else "In this reporting period")},
        {"label": "Completed activities", "value": str(completed), "note": "Dated on or before report generation"},
        {"label": "Future planned", "value": str(planned), "note": "Dated after report generation"},
    ]

    # ---- weekly trend (includes the full window the dashboard displays)
    report_dates = [dt for row in lr.reportable_activities(entries) if (dt := lr.entry_date(row))]
    trend = []
    for row in d["operational_trend"]:
        wstart, wend = lr.maybe_date(row["start_date"]), lr.maybe_date(row["end_date"])
        future = sum(1 for dt in report_dates if wstart <= dt <= wend and dt > today)
        trend.append({
            "label": short_date(wstart), "range": row["label"],
            "total": row["total_activities"], "completed": row["total_activities"] - future,
            "planned": future, "canvassing": row["total_canvassing"],
            "in_period": start <= wstart <= end,
        })

    # ---- municipalities and wards
    statuses = ["Strong", "Active", "Needs Attention", "No Activity"]
    municipalities = []
    for m in d["municipality_summary"]:
        rows = [w for w in d["ward_performance"] if w.get("municipality") == m["municipality"]]
        completed_wards = {r["ward"] for r in d["weekly_activity"] if r.get("municipality") == m["municipality"]
                           and lr.maybe_date(r.get("activity_date")) <= today}
        planned_wards = {r["ward"] for r in d["weekly_activity"] if r.get("municipality") == m["municipality"]
                         and lr.maybe_date(r.get("activity_date")) > today}
        known = {w["ward"] for w in rows}
        completed_wards &= known
        planned_wards &= known
        municipalities.append({
            **m,
            "status_counts": {s: sum(1 for w in rows if w["status"] == s) for s in statuses},
            "coverage": {"completed": len(completed_wards), "planned": len(planned_wards),
                         "no_entries": len(known - completed_wards - planned_wards)},
        })

    # ---- attention / planning notes — do not penalize future dates
    attention = []
    idle = [w for w in d["ward_performance"] if w["activities"] == 0]
    if idle and (total or comparable_history):
        title = (f"{len(idle)} wards with no activities planned for this period" if state == "not_started"
                 else f"{len(idle)} wards with no recorded activity in this period")
        attention.append({"title": title, "detail": _group_wards(idle)})
    if state == "completed" and total:
        no_canvass = [w for w in d["ward_performance"] if w["activities"] > 0 and w["canvassing"] == 0]
        if no_canvass:
            attention.append({"title": f"{len(no_canvass)} wards recorded activity but no canvassing",
                              "detail": _group_wards(no_canvass)})
    not_logged = d["candidate_activity"]["not_logged"]
    if not_logged and (total or comparable_history):
        title = (f"{len(not_logged)} candidates have not planned activity for this period" if state == "not_started"
                 else f"{len(not_logged)} candidates have no recorded activities in this period")
        attention.append({"title": title,
                          "items": [f"{r['name']} ({r['municipality'] or 'municipality not recorded'})" for r in not_logged]})
    if not total and not comparable_history:
        attention.append({"title": "No activity records available for this reporting period",
                          "detail": "The tracker has no recorded activity history on or before the selected period. No performance conclusion can be drawn."})
    unassigned = d["ward_model"]["unassigned_period_activities"]
    if unassigned:
        attention.append({"title": f"{unassigned} activities not attributed to a ward",
                          "detail": "Recorded by multi-ward candidates without a specific ward."})

    # ---- upcoming: planned activities in the next 14 days + current/planned campaigns
    roster_ctx = lr.build_roster_context(roster, lr.reportable_activities(entries))
    linked = lr.linked_entries_by_campaign(lr.reportable_activities(entries))
    planned_campaigns = []
    for c in lr.filtered_campaigns(campaigns, roster_ctx["by_person_id"]):
        if lr.derive_campaign_status(c, today) == "planned":
            cid = str(c.get("id") or c.get("_id") or "")
            planned_campaigns.append(lr.campaign_for_report(c, roster_ctx["by_person_id"], linked.get(cid, []), today))
    planned_campaigns.sort(key=lambda c: (c["start_date"], c["name"].lower()))
    campaign_rows = [{
        "name": c["name"], "candidate": c["candidate"], "municipality": c["municipality"],
        "dates": f"{short_date(lr.maybe_date(c['start_date']))} – {short_date(lr.maybe_date(c['end_date']))}",
        "status": (c["week_progress"] or {}).get("label", "Active") if c["status"] == "active"
                  else f"Starts {short_date(lr.maybe_date(c['start_date']))}",
        "activities": c["activities"],
    } for c in d["active_campaigns"] + planned_campaigns]

    upcoming_rows = [{
        "date": f"{lr.maybe_date(r['activity_date']).strftime('%a')} {short_date(lr.maybe_date(r['activity_date']))}",
        "candidate": r["candidate"], "activity": r["activity"], "venue": r["venue"] or "–",
        "municipality": r["municipality"],
    } for r in upcoming["weekly_activity"]]

    return {
        "title": "Leadership Meeting Pack",
        "constituency": "Ntsikana Constituency",
        "scope": "All municipalities",
        "generated_on": today.isoformat(),
        "generated_label": long_date(today),
        "period": period,
        "kpis": {"total": total, "completed": completed, "planned": planned,
                 "canvassing": kpis["total_canvassing"], "participation": part, "wards_active": wards,
                 "active_campaigns": kpis["active_campaigns"]},
        "tiles": tiles,
        "summary": summary,
        "comparison": {"period_label": cmp["period_label"], "activities": cmp["activities"],
                       "canvassing": cmp["canvassing"], "noun": cmp["noun"],
                       "available": comparable_history and state != "not_started"},
        "trend": trend,
        "municipalities": municipalities,
        "participation": {
            "submitted": part["submitted"], "expected": part["expected"],
            "not_logged": len(not_logged),
        },
        "activity_mix": d["activity_mix"],
        "attention": attention,
        "upcoming": {
            "as_of": long_date(today), "historical_update": end < today - timedelta(days=14),
            "window_label": f"{long_date(up_from)} – {long_date(up_to)}",
            "activities": upcoming_rows,
            "campaigns": campaign_rows,
        },
    }


def _group_wards(rows: list[dict]) -> str:
    by_muni: dict[str, list[str]] = {}
    for w in rows:
        by_muni.setdefault(w.get("municipality") or "Municipality not recorded", []).append(w["ward"].replace("Ward ", ""))
    return "; ".join(f"{m}: Ward {', '.join(ws)}" if len(ws) == 1 else f"{m}: Wards {', '.join(ws)}"
                     for m, ws in by_muni.items())


# ---------------------------------------------------------------- text fitting (shared by both formats)

def _font(bold: bool) -> str:
    return "Helvetica-Bold" if bold else "Helvetica"


def text_width(text: str, size: float, bold: bool = False) -> float:
    """Width in inches. Helvetica metrics == Arial (the PowerPoint font)."""
    return stringWidth(text, _font(bold), size) / 72


SLACK = 0.94  # leave room for small renderer differences, so PowerPoint never re-wraps


def ellipsize(text: str, width: float, size: float, bold: bool = False) -> str:
    text = str(text)
    if text_width(text, size, bold) <= width * SLACK:
        return text
    while text and text_width(text + "…", size, bold) > width * SLACK:
        text = text[:-1]
    return text.rstrip() + "…"


def wrap(text: str, width: float, size: float, bold: bool = False, max_lines: Optional[int] = None) -> list[str]:
    lines: list[str] = []
    for para in str(text).split("\n"):
        line = ""
        for word in para.split(" "):
            trial = f"{line} {word}".strip()
            if text_width(trial, size, bold) <= width * SLACK or not line:
                line = trial
            else:
                lines.append(line)
                line = word
        lines.append(line)
    lines = [ellipsize(line, width, size, bold) for line in lines]
    if max_lines is not None and len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = ellipsize(lines[-1] + " …", width, size, bold) if not lines[-1].endswith("…") else lines[-1]
    return lines


def nice_axis(max_value: float) -> tuple[float, float]:
    """Axis maximum and step: 4-6 gridlines on round numbers."""
    if max_value <= 0:
        return 5, 1
    raw = max_value / 5
    magnitude = 10 ** math.floor(math.log10(raw))
    step = next(m * magnitude for m in (1, 2, 2.5, 5, 10) if m * magnitude >= raw)
    step = max(1, step)
    return math.ceil(max_value / step) * step, step


# ---------------------------------------------------------------- slide composition

MARGIN = 0.6
TOP = 1.45
CONTENT_W = SLIDE_W - 2 * MARGIN
SLIDE_COUNT = 8


def _frame(w, pack: dict, n: int, title: str, subtitle: str = "") -> None:
    w.slide()
    w.rect(0, 0, SLIDE_W, 0.12, NAVY)
    w.text(MARGIN, 0.42, CONTENT_W - 1.2, 0.6, title, 28, NAVY, bold=True)
    if subtitle:
        w.text(MARGIN, 0.98, CONTENT_W - 1.2, 0.35, subtitle, 14, INK3)
    if os.path.exists(LOGO_PATH):
        w.image(LOGO_PATH, SLIDE_W - MARGIN - 0.5, 0.38, 0.5, 0.61)
    w.rect(MARGIN, 7.0, CONTENT_W, 0.01, LINE)
    w.text(MARGIN, 7.07, 9, 0.3,
           f"{pack['constituency']} · {pack['title']} · {pack['period']['short_label']}", 10, INK3)
    w.text(SLIDE_W - MARGIN - 1.5, 7.07, 1.5, 0.3, f"{n} / {SLIDE_COUNT}", 10, INK3, align="right")


def _legend(w, x, y, items, size=12) -> None:
    for color, label in items:
        w.rect(x, y + 0.04, 0.18, 0.18, color)
        w.text(x + 0.26, y, 3, 0.3, label, size, INK2)
        x += 0.26 + text_width(label, size) / SLACK + 0.45


def _empty(w, x, y, wdt, h, message) -> None:
    w.rect(x, y, wdt, h, PAPER)
    w.text(x + 0.3, y, wdt - 0.6, h, message, 16, INK3, align="center", valign="middle")


def _slide_title(w, p):
    w.slide()
    w.rect(0, 0, SLIDE_W, SLIDE_H, NAVY)
    w.rect(0, 5.55, SLIDE_W, 0.06, GOLD)
    if os.path.exists(LOGO_PATH):
        w.image(LOGO_PATH, MARGIN, 0.7, 0.95, 1.16)
    w.text(MARGIN + 1.2, 0.85, 8, 0.45, "Democratic Alliance", 20, WHITE, bold=True)
    w.text(MARGIN + 1.2, 1.3, 8, 0.4, p["constituency"], 18, "C9DAEE")
    w.text(MARGIN, 2.35, CONTENT_W, 0.9, p["title"], 44, WHITE, bold=True)
    w.text(MARGIN, 3.35, CONTENT_W, 0.55, p["period"]["label"], 24, WHITE)
    chip = p["period"]["state_label"]
    chip_w = text_width(chip, 15, True) / SLACK + 0.5
    w.rect(MARGIN, 4.2, chip_w, 0.5, GOLD if p["period"]["state"] != "completed" else "2F5D8C")
    w.text(MARGIN + 0.25, 4.2, chip_w - 0.3, 0.5, chip, 15, NAVY if p["period"]["state"] != "completed" else WHITE,
           bold=True, valign="middle")
    w.text(MARGIN, 5.9, CONTENT_W, 0.4, f"Prepared {p['generated_label']} from Ward Tracker records · {p['scope']}",
           14, "C9DAEE")
    w.text(MARGIN, 6.35, CONTENT_W, 0.4,
           "Figures are the same as the Leadership Dashboard and weekly reports for this period.", 12, "9FB4CC")


def _slide_summary(w, p):
    _frame(w, p, 2, "Executive summary", p["period"]["label"])
    tile_w, tile_h, gap = (CONTENT_W - 2 * 0.25) / 3, 1.45, 0.25
    for i, t in enumerate(p["tiles"]):
        x = MARGIN + (i % 3) * (tile_w + gap)
        y = TOP + (i // 3) * (tile_h + 0.2)
        w.rect(x, y, tile_w, tile_h, PAPER, line=LINE)
        w.rect(x, y, 0.07, tile_h, BLUE)
        w.text(x + 0.3, y + 0.14, tile_w - 0.45, 0.3, t["label"].upper(), 12, INK3, bold=True)
        w.text(x + 0.3, y + 0.42, tile_w - 0.45, 0.6, t["value"], 30, NAVY, bold=True)
        w.text(x + 0.3, y + 1.03, tile_w - 0.45, 0.3, t["note"], 12, INK2)
    y = TOP + 2 * tile_h + 0.2 + 0.35
    for line in p["summary"][:4]:
        lines = wrap(line, CONTENT_W - 0.35, 16, max_lines=2)
        w.rect(MARGIN, y + 0.1, 0.1, 0.1, GOLD)
        w.text(MARGIN + 0.3, y, CONTENT_W - 0.35, 0.3 * len(lines) + 0.05, "\n".join(lines), 16, INK)
        y += 0.3 * len(lines) + 0.14


def _slide_trend(w, p):
    trend = p["trend"]
    in_period = sum(1 for r in trend if r["in_period"])
    _frame(w, p, 3, "Activity trend",
           f"{len(trend)} Monday–Sunday weeks · the last {_plural(in_period, 'week is', 'weeks are')} the reporting period")
    chart_w = 8.55
    if not any(r["total"] for r in trend):
        _empty(w, MARGIN, TOP, chart_w, 5.3, "No activities recorded in these weeks.")
    else:
        _legend(w, MARGIN, TOP, [(BLUE, "Completed activities"), (PLANNED, "Planned (future date)")])
        every = math.ceil(len(trend) / 12)
        # Counted back from the latest week, so the reporting week is always labelled.
        cats = [r["label"] if (len(trend) - 1 - i) % every == 0 else "" for i, r in enumerate(trend)]
        w.bars(MARGIN, TOP + 0.45, chart_w, 4.85, cats,
               [("Completed activities", [r["completed"] for r in trend], BLUE),
                ("Planned (future date)", [r["planned"] for r in trend], PLANNED)], stacked=True)
        w.text(MARGIN, TOP + 5.33, chart_w, 0.3, "Week starting (Monday)", 11, INK3, align="center")
    # Facts panel
    x, pw = MARGIN + chart_w + 0.35, CONTENT_W - chart_w - 0.35
    k, c = p["kpis"], p["comparison"]
    cards = [("This period", str(k["total"]),
              f"{k['completed']} completed · {k['planned']} planned" if k["planned"] else
              (c["activities"]["label"] if c["available"] else "No earlier baseline")),
             ("Previous period", str(c["activities"]["previous"]) if c["available"] else "–",
              c["period_label"] if c["available"] else "No comparison available"),
             ("Canvassing this period", str(k["canvassing"]),
              "includes planned" if k["planned"] else
              (c["canvassing"]["label"] if c["available"] else "Recorded in selected period"))]
    y = TOP
    for label, value, note in cards:
        w.rect(x, y, pw, 1.62, PAPER, line=LINE)
        w.text(x + 0.25, y + 0.15, pw - 0.4, 0.3, label, 12, INK3, bold=True)
        w.text(x + 0.25, y + 0.45, pw - 0.4, 0.6, value, 30, NAVY, bold=True)
        w.text(x + 0.25, y + 1.08, pw - 0.4, 0.45, note, 12, INK2)
        y += 1.82


def _slide_municipalities(w, p):
    state = p["period"]["state"]
    _frame(w, p, 4, "Municipality and ward overview", p["period"]["label"])
    rows = p["municipalities"]
    if not rows:
        _empty(w, MARGIN, TOP, CONTENT_W, 5.2, "No municipality data for this period.")
        return
    w.text(MARGIN, TOP, CONTENT_W, 0.35, "Activities and plans by municipality" if state != "completed" else "Recorded activities by municipality", 16, NAVY, bold=True)
    w.table(MARGIN, TOP + 0.45, CONTENT_W, [3.2, 1.7, 2.0, 2.6, 2.63],
            ["Municipality", "Activities", "Canvassing", "Wards", "Candidates"],
            [[r["municipality"], r["activities"], r["canvassing"],
              f"{r['wards_active']} of {r['wards_total']}", f"{r['candidates_reporting']} of {r['candidates_expected']}"]
             for r in rows], size=15, row_h=0.5)
    y = TOP + 0.45 + 0.5 * (len(rows) + 1) + 0.45
    if state == "completed":
        w.text(MARGIN, y, CONTENT_W, 0.35, "Ward status for completed period", 16, NAVY, bold=True)
        w.table(MARGIN, y + 0.45, CONTENT_W, [2.75, 1.75, 1.75, 2.2, 1.85, 1.83],
                ["Municipality", "Strong", "Active", "Needs attention", "No activity", "Wards"],
                [[r["municipality"], r["status_counts"]["Strong"], r["status_counts"]["Active"],
                  r["status_counts"]["Needs Attention"], r["status_counts"]["No Activity"], r["wards_total"]]
                 for r in rows if r["wards_total"]], size=15, row_h=0.5)
        w.text(MARGIN, 6.45, CONTENT_W, 0.45,
               "Strong: at least two activities per week incl. canvassing · Active: some activity · "
               "Needs attention: activity recorded before this period but none during it.", 11, INK3)
    else:
        w.text(MARGIN, y, CONTENT_W, 0.35, "Activity coverage by date (not a performance ranking)", 16, NAVY, bold=True)
        w.table(MARGIN, y + 0.45, CONTENT_W, [3.05, 2.35, 2.25, 2.38, 2.1],
                ["Municipality", "Wards completed", "Wards planned", "No entries", "Total wards"],
                [[r["municipality"], r["coverage"]["completed"], r["coverage"]["planned"],
                  r["coverage"]["no_entries"], r["wards_total"]] for r in rows if r["wards_total"]],
                size=15, row_h=0.5)
        w.text(MARGIN, 6.45, CONTENT_W, 0.45,
               "A ward may have completed and future activities. Planned work is not counted as completed.", 11, INK3)


def _meter(w, x, y, wdt, done, total, color=BLUE, h=0.22):
    w.rect(x, y, wdt, h, "E3E8EF")
    if total and done:
        w.rect(x, y, wdt * min(1, done / total), h, color)


def _slide_participation(w, p):
    part = p["participation"]
    state = p["period"]["state"]
    label = ("Candidates with activities planned" if state == "not_started"
             else "Candidates with activity or plans" if state == "in_progress"
             else "Candidates with recorded activity")
    _frame(w, p, 5, "Candidate participation", p["period"]["label"])
    lw = 4.3
    w.text(MARGIN, TOP, lw, 0.35, label, 14, INK3, bold=True)
    w.text(MARGIN, TOP + 0.35, lw, 0.8, f"{part['submitted']} of {part['expected']}", 40, NAVY, bold=True)
    _meter(w, MARGIN, TOP + 1.25, lw, part["submitted"], part["expected"], h=0.28)
    y = TOP + 1.85
    w.text(MARGIN, y, lw, 0.35, "By municipality", 14, INK3, bold=True)
    y += 0.45
    for m in p["municipalities"]:
        if not m["candidates_expected"]:
            continue
        w.text(MARGIN, y, lw - 1.2, 0.3, m["municipality"], 15, INK)
        w.text(MARGIN + lw - 1.2, y, 1.2, 0.3, f"{m['candidates_reporting']} of {m['candidates_expected']}", 15, INK,
               bold=True, align="right")
        _meter(w, MARGIN, y + 0.38, lw, m["candidates_reporting"], m["candidates_expected"], h=0.16)
        y += 0.8
    if part["not_logged"]:
        suffix = "have no recorded plans for this period" if state == "not_started" else "have no entries in this period"
        w.text(MARGIN, y + 0.05, lw, 0.6, f"{part['not_logged']} candidates {suffix}.", 12, INK2)
    x, rw = MARGIN + lw + 0.6, CONTENT_W - lw - 0.6
    w.text(x, TOP, rw, 0.35, "Activity types recorded", 14, INK3, bold=True)
    mix = p["activity_mix"][:6]
    if not mix:
        _empty(w, x, TOP + 0.5, rw, 4.75, "No activities recorded for this period.")
        return
    total = max(1, p["kpis"]["total"])
    y = TOP + 0.56
    for row in mix:
        w.text(x, y, rw - 0.9, 0.36, row["activity"], 15, INK)
        w.text(x + rw - 0.85, y, 0.85, 0.36, str(row["activities"]), 17, NAVY, bold=True, align="right")
        _meter(w, x, y + 0.41, rw, row["activities"], total, BLUE, h=0.16)
        y += 0.84


def _slide_activity_overview(w, p):
    _frame(w, p, 6, "Completed and planned activities", "Based on actual activity dates, not manual capture status")
    k = p["kpis"]
    lw = 4.6
    total = max(1, k["total"])
    w.text(MARGIN, TOP, lw, 0.35, "Recorded activities", 14, INK3, bold=True)
    w.text(MARGIN, TOP + 0.33, lw, 0.8, str(k["total"]), 40, NAVY, bold=True)
    y = TOP + 1.45
    for color, label, value in ((TEAL, "Completed (date reached)", k["completed"]),
                                (PLANNED, "Planned (future date)", k["planned"])):
        w.rect(MARGIN, y, lw, 0.82, PAPER, line=LINE)
        w.rect(MARGIN, y, 0.09, 0.82, color)
        w.text(MARGIN + 0.3, y, lw - 1.4, 0.82, label, 14, INK, valign="middle")
        w.text(MARGIN + lw - 1.1, y, 0.95, 0.82, str(value), 23, NAVY, bold=True, align="right", valign="middle")
        y += 1.0
    w.text(MARGIN, y + 0.16, lw, 0.65,
           "Future plans are not evidence that an activity has happened.", 13, INK2)
    x, cw = MARGIN + lw + 0.5, CONTENT_W - lw - 0.5
    weeks = p["trend"][-8:]
    w.text(x, TOP, cw, 0.35, "Completed vs planned by week", 14, INK3, bold=True)
    if any(r["total"] for r in weeks):
        _legend(w, x, TOP + 0.42, [(TEAL, "Completed"), (PLANNED, "Planned")])
        w.bars(x, TOP + 0.85, cw, 4.45, [r["label"] for r in weeks],
               [("Completed", [r["completed"] for r in weeks], TEAL),
                ("Planned", [r["planned"] for r in weeks], PLANNED)], stacked=True)
    else:
        _empty(w, x, TOP + 0.45, cw, 4.85, "No activities recorded in these weeks.")


def fit_list(items: list[str], width: float, size: float, max_lines: int) -> str:
    """As many whole items as fit in `max_lines`, then "and N more" — never
    an item cut off half-way."""
    for n in range(len(items), 0, -1):
        text = "; ".join(items[:n]) + (f"; and {len(items) - n} more" if n < len(items) else "")
        if len(wrap(text, width, size)) <= max_lines:
            return text
    return f"{len(items)} in total — see the Leadership Dashboard"


ATTENTION_SIZE = 13


def _attention_text(item: dict, width: float, max_lines: int) -> str:
    if "items" in item:
        return fit_list(item["items"], width, ATTENTION_SIZE, max_lines)
    return item["detail"]


def _slide_attention(w, p):
    _frame(w, p, 7, "Planning coverage" if p["period"]["state"] == "not_started" else "Records to review",
           f"From the recorded data for {p['period']['short_label']}")
    items = p["attention"]
    if not items:
        _empty(w, MARGIN, TOP, CONTENT_W, 5.2, "No outstanding matters were found in the recorded data for this period.")
        return
    tw = CONTENT_W - 0.6
    lh = ATTENTION_SIZE * LEADING / 72
    gap, available = 0.16, 6.85 - TOP
    # Give each card the lines it needs (up to 3); shrink the allowance until all fit.
    for max_lines in (3, 2, 1):
        texts = [_attention_text(it, tw, max_lines) for it in items]
        lines = [min(max_lines, len(wrap(t, tw, ATTENTION_SIZE))) for t in texts]
        heights = [0.14 + 0.4 + n * lh + 0.16 for n in lines]
        if sum(heights) + gap * (len(items) - 1) <= available:
            break
    y = TOP
    for item, text, n, h in zip(items, texts, lines, heights):
        w.rect(MARGIN, y, CONTENT_W, h, PAPER, line=LINE)
        w.rect(MARGIN, y, 0.09, h, GOLD)
        w.text(MARGIN + 0.35, y + 0.14, tw, 0.38, item["title"], 17, NAVY, bold=True)
        w.text(MARGIN + 0.35, y + 0.54, tw, n * lh + 0.02, text, ATTENTION_SIZE, INK2)
        y += h + gap


UPCOMING_ROWS = 6
UPCOMING_CAMPAIGNS = 3


def _slide_upcoming(w, p):
    up = p["upcoming"]
    _frame(w, p, 8, "Current planning update", f"As of {up['as_of']} · next {UPCOMING_DAYS} days: {up['window_label']}")
    acts = up["activities"]
    w.text(MARGIN, TOP, CONTENT_W, 0.35, _plural(len(acts), "planned activity", "planned activities"), 16, NAVY, bold=True)
    row_h = 0.42
    if acts:
        shown = acts[:UPCOMING_ROWS]
        w.table(MARGIN, TOP + 0.42, CONTENT_W, [1.35, 2.75, 3.3, 4.73], ["Date", "Candidate", "Activity", "Place"],
                [[r["date"], r["candidate"], r["activity"], r["venue"]] for r in shown], size=13, row_h=row_h)
        if len(acts) > len(shown):
            w.text(MARGIN, TOP + 0.42 + row_h * (len(shown) + 1) + 0.06, CONTENT_W, 0.3,
                   f"and {_plural(len(acts) - len(shown), 'more planned activity', 'more planned activities')} "
                   "in the Leadership Dashboard", 12, INK3)
    else:
        _empty(w, MARGIN, TOP + 0.42, CONTENT_W, row_h * (UPCOMING_ROWS + 1), "No activities are planned for the next 14 days yet.")
    camps = up["campaigns"]
    y = TOP + 0.42 + row_h * (UPCOMING_ROWS + 1) + 0.45
    w.text(MARGIN, y, CONTENT_W, 0.35, f"Active and planned campaigns ({len(camps)})", 16, NAVY, bold=True)
    y += 0.42
    if not camps:
        _empty(w, MARGIN, y, CONTENT_W, 0.92, "No active or planned campaigns.")
        return
    gap = 0.25
    cw = (CONTENT_W - gap * (UPCOMING_CAMPAIGNS - 1)) / UPCOMING_CAMPAIGNS
    for i, c in enumerate(camps[:UPCOMING_CAMPAIGNS]):
        x = MARGIN + i * (cw + gap)
        w.rect(x, y, cw, 0.92, PAPER, line=LINE)
        w.rect(x, y, 0.07, 0.92, BLUE)
        w.text(x + 0.25, y + 0.08, cw - 0.35, 0.3, c["name"], 14, NAVY, bold=True)
        w.text(x + 0.25, y + 0.36, cw - 0.35, 0.25, f"{c['candidate']} · {c['municipality']}", 12, INK2)
        w.text(x + 0.25, y + 0.6, cw - 0.35, 0.25, f"{c['dates']} · {c['status']} · "
               f"{_plural(c['activities'], 'activity', 'activities')}", 12, INK3)
    if len(camps) > UPCOMING_CAMPAIGNS:
        w.text(MARGIN, y + 0.98, CONTENT_W, 0.3,
               f"and {len(camps) - UPCOMING_CAMPAIGNS} more in the Leadership Dashboard", 12, INK3)


def _compose(w, pack: dict) -> None:
    for fn in (_slide_title, _slide_summary, _slide_trend, _slide_municipalities,
               _slide_participation, _slide_activity_overview, _slide_attention, _slide_upcoming):
        fn(w, pack)


# ---------------------------------------------------------------- writers

def _rgb(hex_: str):
    return tuple(int(hex_[i:i + 2], 16) / 255 for i in (0, 2, 4))


class _PdfWriter:
    def __init__(self):
        from reportlab.pdfgen import canvas
        self.buf = io.BytesIO()
        self.c = canvas.Canvas(self.buf, pagesize=(SLIDE_W * 72, SLIDE_H * 72))
        self.c.setTitle("Leadership Meeting Pack")
        self.started = False

    def _y(self, y, h=0):
        return (SLIDE_H - y - h) * 72

    def slide(self):
        if self.started:
            self.c.showPage()
        self.started = True
        self.c.setFillColorRGB(1, 1, 1)
        self.c.rect(0, 0, SLIDE_W * 72, SLIDE_H * 72, stroke=0, fill=1)

    def rect(self, x, y, w, h, fill, line=None):
        self.c.setFillColorRGB(*_rgb(fill))
        if line:
            self.c.setStrokeColorRGB(*_rgb(line))
            self.c.setLineWidth(0.75)
        self.c.rect(x * 72, self._y(y, h), w * 72, h * 72, stroke=1 if line else 0, fill=1)

    def image(self, path, x, y, w, h):
        self.c.drawImage(path, x * 72, self._y(y, h), w * 72, h * 72, mask="auto")

    def text(self, x, y, w, h, text, size, color=INK, bold=False, align="left", valign="top"):
        lines = _fit_lines(text, w, h, size, bold)
        leading = size * LEADING
        block = leading * (len(lines) - 1) + size
        top = y * 72 + ((h * 72 - block) / 2 if valign == "middle" else 0)
        self.c.setFillColorRGB(*_rgb(color))
        self.c.setFont(_font(bold), size)
        for i, line in enumerate(lines):
            base = SLIDE_H * 72 - (top + size * 0.82 + i * leading)
            if align == "right":
                self.c.drawRightString((x + w) * 72, base, line)
            elif align == "center":
                self.c.drawCentredString((x + w / 2) * 72, base, line)
            else:
                self.c.drawString(x * 72, base, line)

    def table(self, x, y, width, weights, header, rows, size=14, row_h=0.45):
        cols, aligns, cells = _table_layout(width, weights, header, rows, size)
        for r, row in enumerate(cells):
            ry = y + r * row_h
            fill = BLUE if r == 0 else (PAPER if r % 2 == 0 else WHITE)
            self.rect(x, ry, sum(cols), row_h, fill)
            cx = x
            for cell, cw, align in zip(row, cols, aligns):
                self.text(cx + 0.12, ry, cw - 0.24, row_h, cell, size, WHITE if r == 0 else INK, bold=r == 0,
                          align=align, valign="middle")
                cx += cw
        self.c.setStrokeColorRGB(*_rgb(LINE))
        self.c.setLineWidth(0.6)
        self.c.rect(x * 72, self._y(y, row_h * len(cells)), sum(cols) * 72, row_h * len(cells) * 72, stroke=1, fill=0)

    def bars(self, x, y, w, h, categories, series, stacked=True):
        from reportlab.graphics import renderPDF
        from reportlab.graphics.charts.barcharts import VerticalBarChart
        from reportlab.graphics.shapes import Drawing
        from reportlab.lib import colors

        top, step = _axis_for(series, stacked)
        d = Drawing(w * 72, h * 72)
        ch = VerticalBarChart()
        ch.x, ch.y = 40, 26
        ch.width, ch.height = w * 72 - 50, h * 72 - 36
        ch.data = [vals for _name, vals, _c in series]
        ch.categoryAxis.categoryNames = categories
        ch.categoryAxis.style = "stacked" if stacked else "parallel"
        for axis in (ch.categoryAxis.labels, ch.valueAxis.labels):
            axis.fontName, axis.fontSize, axis.fillColor = "Helvetica", CHART_FONT, colors.HexColor("#" + INK2)
        ch.categoryAxis.labels.dy = -5
        ch.categoryAxis.strokeColor = colors.HexColor("#" + INK3)
        ch.valueAxis.strokeColor = None
        ch.valueAxis.valueMin, ch.valueAxis.valueMax, ch.valueAxis.valueStep = 0, top, step
        ch.valueAxis.visibleGrid = True
        ch.valueAxis.gridStrokeColor = colors.HexColor("#" + LINE)
        ch.valueAxis.labelTextFormat = lambda v: f"{v:g}"
        ch.groupSpacing = 12
        ch.bars.strokeColor = None
        for i, (_n, _v, color) in enumerate(series):
            ch.bars[i].fillColor = colors.HexColor("#" + color)
        d.add(ch)
        renderPDF.draw(d, self.c, x * 72, self._y(y, h))

    def finish(self) -> bytes:
        self.c.showPage()
        self.c.save()
        return self.buf.getvalue()


LEADING = 1.22
CHART_FONT = 12


def _fit_lines(text, w, h, size, bold) -> list[str]:
    max_lines = max(1, int((h * 72 - size) / (size * LEADING)) + 1)
    return wrap(text, w, size, bold, max_lines=max_lines)


def _numeric(value) -> bool:
    return isinstance(value, (int, float)) or (isinstance(value, str) and value[:1].isdigit() and " of " in value)


def _table_layout(width, weights, header, rows, size):
    """Column widths scaled to exactly `width`, the shortened cell text and
    each column's alignment (right for counts, applied to the header too)."""
    cols = [width * wt / sum(weights) for wt in weights]
    aligns = ["right" if rows and ci > 0 and all(_numeric(r[ci]) for r in rows) else "left" for ci in range(len(cols))]
    cells = [[ellipsize(str(v), cw - 0.24, size, r == 0) for v, cw in zip(row, cols)]
             for r, row in enumerate([header] + [[str(v) for v in row] for row in rows])]
    return cols, aligns, cells


def _axis_for(series, stacked) -> tuple[float, float]:
    columns = list(zip(*[vals for _n, vals, _c in series]))
    peak = max((sum(c) if stacked else max(c)) for c in columns) if columns else 0
    return nice_axis(peak)


class _PptxWriter:
    def __init__(self):
        from pptx import Presentation
        from pptx.util import Inches
        self.prs = Presentation()
        self.prs.slide_width, self.prs.slide_height = Inches(SLIDE_W), Inches(SLIDE_H)
        self.prs.core_properties.title = "Leadership Meeting Pack"
        self.blank = self.prs.slide_layouts[6]
        self.s = None

    def slide(self):
        self.s = self.prs.slides.add_slide(self.blank)

    def rect(self, x, y, w, h, fill, line=None):
        from pptx.dml.color import RGBColor
        from pptx.enum.shapes import MSO_SHAPE
        from pptx.util import Inches, Pt
        shape = self.s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
        shape.fill.solid()
        shape.fill.fore_color.rgb = RGBColor.from_string(fill)
        if line:
            shape.line.color.rgb = RGBColor.from_string(line)
            shape.line.width = Pt(0.75)
        else:
            shape.line.fill.background()
        shape.shadow.inherit = False
        return shape

    def image(self, path, x, y, w, h):
        from pptx.util import Inches
        self.s.shapes.add_picture(path, Inches(x), Inches(y), Inches(w), Inches(h))

    def _fill_frame(self, tf, lines, size, color, bold, align):
        from pptx.dml.color import RGBColor
        from pptx.enum.text import PP_ALIGN
        from pptx.util import Pt
        for i, line in enumerate(lines):
            para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
            para.alignment = {"left": PP_ALIGN.LEFT, "right": PP_ALIGN.RIGHT, "center": PP_ALIGN.CENTER}[align]
            para.line_spacing = Pt(size * LEADING)
            para.space_before = para.space_after = Pt(0)
            run = para.add_run()
            run.text = line
            run.font.size = Pt(size)
            run.font.bold = bold
            run.font.name = "Arial"
            run.font.color.rgb = RGBColor.from_string(color)

    def text(self, x, y, w, h, text, size, color=INK, bold=False, align="left", valign="top"):
        from pptx.enum.text import MSO_ANCHOR
        from pptx.util import Inches
        box = self.s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
        tf = box.text_frame
        tf.word_wrap = True
        tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
        tf.vertical_anchor = MSO_ANCHOR.MIDDLE if valign == "middle" else MSO_ANCHOR.TOP
        self._fill_frame(tf, _fit_lines(text, w, h, size, bold), size, color, bold, align)

    def table(self, x, y, width, weights, header, rows, size=14, row_h=0.45):
        from pptx.dml.color import RGBColor
        from pptx.enum.text import MSO_ANCHOR
        from pptx.util import Inches
        cols, aligns, cells = _table_layout(width, weights, header, rows, size)
        shape = self.s.shapes.add_table(len(cells), len(cols), Inches(x), Inches(y), Inches(sum(cols)),
                                        Inches(row_h * len(cells)))
        tbl = shape.table
        tbl.first_row = True
        tbl.horz_banding = False
        for ci, cw in enumerate(cols):
            tbl.columns[ci].width = Inches(cw)
        for r, row in enumerate(cells):
            tbl.rows[r].height = Inches(row_h)
            for ci, value in enumerate(row):
                cell = tbl.cell(r, ci)
                cell.fill.solid()
                cell.fill.fore_color.rgb = RGBColor.from_string(BLUE if r == 0 else (PAPER if r % 2 == 0 else WHITE))
                cell.margin_left = cell.margin_right = Inches(0.12)
                cell.margin_top = cell.margin_bottom = Inches(0.02)
                cell.vertical_anchor = MSO_ANCHOR.MIDDLE
                tf = cell.text_frame
                tf.word_wrap = False
                self._fill_frame(tf, [value], size, WHITE if r == 0 else INK, r == 0, aligns[ci])

    def bars(self, x, y, w, h, categories, series, stacked=True):
        from pptx.chart.data import CategoryChartData
        from pptx.dml.color import RGBColor
        from pptx.enum.chart import XL_CHART_TYPE
        from pptx.util import Inches, Pt
        data = CategoryChartData()
        data.categories = categories
        for name, values, _color in series:
            data.add_series(name, values)
        kind = XL_CHART_TYPE.COLUMN_STACKED if stacked else XL_CHART_TYPE.COLUMN_CLUSTERED
        chart = self.s.shapes.add_chart(kind, Inches(x), Inches(y), Inches(w), Inches(h), data).chart
        chart.has_legend = False  # drawn as shapes above the chart, identical to the PDF
        chart.font.size = Pt(CHART_FONT)
        chart.font.name = "Arial"
        chart.font.color.rgb = RGBColor.from_string(INK2)
        top, step = _axis_for(series, stacked)
        va = chart.value_axis
        va.minimum_scale, va.maximum_scale, va.major_unit = 0, top, step
        va.has_major_gridlines = True
        va.major_gridlines.format.line.color.rgb = RGBColor.from_string(LINE)
        va.format.line.fill.background()
        va.tick_labels.font.size = Pt(CHART_FONT)
        ca = chart.category_axis
        ca.tick_labels.font.size = Pt(CHART_FONT)
        ca.format.line.color.rgb = RGBColor.from_string(INK3)
        plot = chart.plots[0]
        plot.gap_width = 60
        if stacked:
            plot.overlap = 100
        for i, (_n, _v, color) in enumerate(series):
            fmt = plot.series[i].format
            fmt.fill.solid()
            fmt.fill.fore_color.rgb = RGBColor.from_string(color)
            fmt.line.fill.background()

    def finish(self) -> bytes:
        buf = io.BytesIO()
        self.prs.save(buf)
        return buf.getvalue()


def meeting_pack_pdf_bytes(pack: dict) -> bytes:
    w = _PdfWriter()
    _compose(w, pack)
    return w.finish()


def meeting_pack_pptx_bytes(pack: dict) -> bytes:
    w = _PptxWriter()
    _compose(w, pack)
    return w.finish()


def meeting_pack_filename(pack: dict, ext: str) -> str:
    return f"Ntsikana_Meeting_Pack_{pack['period']['start_date']}_to_{pack['period']['end_date']}.{ext}"
