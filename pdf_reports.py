"""Reports hub — PDF generation only. Every number in every PDF here comes
from the exact same dashboard dict (leadership_reporting.build_dashboard)
or the exact same trend rows (leadership_reporting.trend_report_weeks) that
already power the Leadership Dashboard and the Excel export — this module
never recomputes a total, count, or filter independently. It only lays out
already-computed numbers on a page.

Kept deliberately separate from leadership_reporting.py (Excel/dashboard
data) and official_capture.py (capture workflow) — a third module purely
for PDF presentation, matching this codebase's existing convention of one
small neutral module per concern.
"""

import io
import os
from datetime import date
from typing import Optional
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdf_canvas
from reportlab.platypus import (
    CondPageBreak,
    Image as RLImage,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.graphics.shapes import Drawing, String
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.legends import Legend

from leadership_reporting import activity_mix_with_other, maybe_date
from week_dates import FULL_MONTHS, MONTHS, sast_today

# Same palette used throughout the Excel workbooks (leadership_reporting.py)
# and the frontend's own DA brand variables — every export/report in this
# app reads as one consistent document, not a different look per format.
DA_NAVY = colors.HexColor("#153B63")
DA_BLUE = colors.HexColor("#2568AE")
DA_LINE = colors.HexColor("#DCD6C9")
DA_SHADE = colors.HexColor("#F3F1EC")
DA_RED = colors.HexColor("#B0473A")
DA_GREY = colors.HexColor("#6B7280")
# Planned (future-dated) work: a warm tint, never the "done" styling.
PLANNED_FILL = colors.HexColor("#FBF3E4")
PLANNED_LINE = colors.HexColor("#E3C48D")

LOGO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "logo.png")
CONTENT_WIDTH = A4[0] - 32 * mm

_styles = getSampleStyleSheet()
TITLE_STYLE = ParagraphStyle(
    "DATitle", parent=_styles["Title"], textColor=DA_NAVY, fontSize=16, leading=20, spaceBefore=2, spaceAfter=2,
)
SUBTITLE_STYLE = ParagraphStyle(
    "DASubtitle", parent=_styles["Normal"], textColor=DA_NAVY, fontSize=11, leading=14,
)
META_STYLE = ParagraphStyle(
    "DAMeta", parent=_styles["Normal"], textColor=DA_GREY, fontSize=9.5, leading=13, alignment=1,
)
ORG_STYLE = ParagraphStyle("DAOrg", parent=META_STYLE, alignment=0)
SECTION_STYLE = ParagraphStyle(
    "DASection", parent=_styles["Heading2"], textColor=DA_NAVY, fontSize=12.5, spaceBefore=10, spaceAfter=5,
)
BODY_STYLE = ParagraphStyle("DABody", parent=_styles["Normal"], fontSize=9.5, leading=12)
HEAD_CELL_STYLE = ParagraphStyle("DATh", parent=BODY_STYLE, textColor=colors.white)
NOTE_STYLE = ParagraphStyle("DANote", parent=BODY_STYLE, fontSize=9.5, leading=13)
FOOTER_STYLE = ParagraphStyle(
    "DAFooter", parent=_styles["Normal"], textColor=DA_GREY, fontSize=9, leading=12, spaceBefore=10,
)
# Leave room for at least a heading and a few table rows before starting a
# section, so a heading is never stranded at the foot of a page.
SECTION_MIN_SPACE = 40 * mm


def long_date(d: date) -> str:
    return f"{d.strftime('%A')}, {d.day} {FULL_MONTHS[d.month - 1]} {d.year}"


def short_date(d: date) -> str:
    return f"{d.day} {MONTHS[d.month - 1]}"


def _header_flowables(report_title: str, meta_lines: list[str]) -> list:
    org = [Paragraph("Democratic Alliance", SUBTITLE_STYLE), Paragraph("Ntsikana Constituency", ORG_STYLE)]
    if os.path.exists(LOGO_PATH):
        brand = Table([[RLImage(LOGO_PATH, width=11 * mm, height=13.4 * mm), org]], colWidths=[15 * mm, None])
        brand.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0),
        ]))
        flow = [brand]
    else:
        flow = list(org)
    flow.append(Spacer(1, 2 * mm))
    flow.append(Paragraph(report_title, TITLE_STYLE))
    for line in meta_lines:
        flow.append(Paragraph(escape(line), META_STYLE))
    flow.append(Spacer(1, 3 * mm))
    return flow


def _section(title: str) -> list:
    return [CondPageBreak(SECTION_MIN_SPACE), Paragraph(title, SECTION_STYLE)]


def _note_box(html: str) -> Table:
    """A tinted callout for planned/in-progress explanations."""
    box = Table([[Paragraph(html, NOTE_STYLE)]], colWidths=[CONTENT_WIDTH])
    box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PLANNED_FILL),
        ("BOX", (0, 0), (-1, -1), 0.75, PLANNED_LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return box


def _summary_table(rows: list[tuple[str, object]], planned_rows: Optional[set[int]] = None) -> Table:
    data = [[Paragraph(f"<b>{escape(label)}</b>", BODY_STYLE), Paragraph(escape(str(value)), BODY_STYLE)] for label, value in rows]
    table = Table(data, colWidths=[88 * mm, CONTENT_WIDTH - 88 * mm])
    style = [
        ("BOX", (0, 0), (-1, -1), 0.75, DA_LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, DA_LINE),
        ("BACKGROUND", (0, 0), (0, -1), DA_SHADE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]
    for i in planned_rows or ():
        style.append(("BACKGROUND", (0, i), (-1, i), PLANNED_FILL))
    table.setStyle(TableStyle(style))
    return table


def _data_table(headers: list[str], rows: list[list[str]], col_widths: Optional[list[float]] = None) -> Table:
    header_row = [Paragraph(f"<b>{escape(h)}</b>", HEAD_CELL_STYLE) for h in headers]
    # Cells hold candidate-entered text (names, activity types): escape it so
    # "<" or "&" print literally instead of breaking the paragraph markup.
    body_rows = [[Paragraph(escape(str(cell)), BODY_STYLE) for cell in row] for row in rows]
    table = Table([header_row] + body_rows, colWidths=col_widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), DA_BLUE),
        ("BOX", (0, 0), (-1, -1), 0.75, DA_LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, DA_LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]
    for i in range(1, len(body_rows) + 1):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), DA_SHADE))
    table.setStyle(TableStyle(style))
    return table


class _NumberedCanvas(pdf_canvas.Canvas):
    """Adds "Page N of M" to every page (needs the total, so pages are
    buffered and stamped when the document is saved)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._pages = []

    def showPage(self):
        self._pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._pages)
        for state in self._pages:
            self.__dict__.update(state)
            self.setFont("Helvetica", 8)
            self.setFillColor(DA_GREY)
            self.drawRightString(A4[0] - 16 * mm, 8 * mm, f"Page {self._pageNumber} of {total}")
            super().showPage()
        super().save()


def _build_pdf(flowables: list) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        topMargin=14 * mm, bottomMargin=14 * mm, leftMargin=16 * mm, rightMargin=16 * mm,
        title="Ntsikana Constituency Report",
    )
    doc.build(flowables, canvasmaker=_NumberedCanvas)
    return buf.getvalue()


PDF_MIX_ROWS = 10


def _overview_flowables(dashboard: dict, generated_on: date) -> list:
    """Activity timing, municipality summary and activity mix.

    Uses recorded dates only. Historical capture-status fields stay stored
    for compatibility but no longer appear in user-facing reports.
    """
    rows = dashboard.get("weekly_activity") or []
    planned = sum(1 for row in rows if (d := maybe_date(row.get("activity_date"))) and d > generated_on)
    flow = [KeepTogether(_section("Completed and Planned Activities") + [
        _summary_table([
            ("Completed (date reached)", len(rows) - planned),
            ("Planned (future date)", planned),
            ("Total recorded", len(rows)),
        ]),
    ])]

    municipalities = dashboard.get("municipality_summary") or []
    if municipalities:
        body = _data_table(
            ["Municipality", "Activities", "Canvassing", "Wards active", "Candidates reporting"],
            [[
                row["municipality"],
                row["activities"],
                row["canvassing"],
                f"{row['wards_active']} / {row['wards_total']}",
                f"{row['candidates_reporting']} / {row['candidates_expected']}",
            ] for row in municipalities],
            col_widths=[50 * mm, 29 * mm, 30 * mm, 29 * mm, 40 * mm],
        )
    else:
        body = Paragraph("No municipality data for this selection.", BODY_STYLE)
    flow.append(KeepTogether(_section("Municipality Summary") + [body]))

    mix = dashboard.get("activity_mix") or []
    if mix:
        body = _data_table(
            ["Activity type", "Activities", "Share"],
            [[row["activity"], row["activities"], f"{row['percent']}%"] for row in activity_mix_with_other(mix, PDF_MIX_ROWS)],
            col_widths=[118 * mm, 30 * mm, 30 * mm],
        )
    else:
        body = Paragraph("No activities in this selection.", BODY_STYLE)
    flow.append(KeepTogether(_section("Activity Mix") + [body]))
    return flow


def _day_strip(daily: list[dict], today: date) -> Table:
    """The week's seven days side by side. When any day is still ahead of
    the generation date a Status row marks it Planned (tinted), so planned
    activities never read as work already done."""
    any_planned = any(d.get("is_future") for d in daily)
    rows = [
        # "Mon 9 Nov" -> "Mon" over "9 Nov": every header wraps the same way.
        [Paragraph("<b>Day</b>", HEAD_CELL_STYLE)]
        + [Paragraph("<b>" + "<br/>".join(escape(part) for part in d.get("label", "").split(" ", 1)) + "</b>", HEAD_CELL_STYLE)
           for d in daily],
        [Paragraph("<b>Activities</b>", BODY_STYLE)] + [Paragraph(str(d.get("total", 0)), BODY_STYLE) for d in daily],
    ]
    if any_planned:
        def status(d):
            if d.get("is_future"):
                return "Planned"
            return "Today" if d.get("date") == today.isoformat() else "Completed"
        rows.append([Paragraph("<b>Status</b>", BODY_STYLE)] + [Paragraph(status(d), BODY_STYLE) for d in daily])
    label_width = 24 * mm
    day_width = (CONTENT_WIDTH - label_width) / max(len(daily), 1)
    table = Table(rows, colWidths=[label_width] + [day_width] * len(daily))
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), DA_BLUE),
        ("BACKGROUND", (0, 1), (0, -1), DA_SHADE),
        ("BOX", (0, 0), (-1, -1), 0.75, DA_LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, DA_LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
    ]
    for col, d in enumerate(daily, start=1):
        if d.get("is_future"):
            style.append(("BACKGROUND", (col, 1), (col, -1), PLANNED_FILL))
    table.setStyle(TableStyle(style))
    return table


def weekly_report_pdf_bytes(dashboard: dict, scope_label: str, generated_on: Optional[date] = None) -> bytes:
    """The Weekly PDF Report / Municipality Activity Report PDF — same
    dashboard dict the Excel export and the live dashboard both already
    use; this only lays it out on a page. When the period still has
    future-dated (planned) activities, they are shown separately by date,
    never by the now-retired Campaign Manager capture-status field."""
    generated_on = generated_on or sast_today()
    kpis = dashboard["kpis"]
    period = dashboard["period"]
    participation = kpis.get("candidate_participation", {})
    candidate_activity = dashboard.get("candidate_activity") or {"logged": [], "not_logged": []}
    total = kpis.get("total_activities", 0)
    planned = sum(1 for row in dashboard.get("weekly_activity") or []
                  if (d := maybe_date(row.get("activity_date"))) and d > generated_on)
    completed = total - planned

    meta = [f"Reporting Period: {period['label']}", f"Generated: {long_date(generated_on)}"]
    if scope_label and scope_label != "All municipalities":
        meta.append(f"Municipality: {scope_label}")
    flow = _header_flowables("Weekly Activity Report", meta)

    if planned:
        if date.fromisoformat(period["start_date"]) > generated_on:
            note = (f"<b>This period has not started yet.</b> All {planned} activities below are planned "
                    f"and have not taken place yet.")
        else:
            note = (f"<b>This period is still in progress.</b> {planned} of the {total} activities are planned "
                    f"for after {escape(long_date(generated_on))} and have not taken place yet. They are shown as "
                    f"<b>Planned</b> and are not counted as completed.")
        flow.append(_note_box(note))
        flow.append(Spacer(1, 3 * mm))
        flow.append(_summary_table([
            ("Total Activities (completed + planned)", total),
            ("Completed (date has passed)", completed),
            ("Planned (not yet taken place)", planned),
            ("Canvassing Activities (incl. planned)", kpis.get("total_canvassing", 0)),
            ("Candidates Reporting", f"{participation.get('submitted', 0)} / {participation.get('expected', 0)}"),
            ("Active Campaigns", kpis.get("active_campaigns", 0)),
        ], planned_rows={2}))
    else:
        flow.append(_summary_table([
            ("Total Activities", total),
            ("Canvassing Activities", kpis.get("total_canvassing", 0)),
            ("Candidates Reporting", f"{participation.get('submitted', 0)} / {participation.get('expected', 0)}"),
            ("Active Campaigns", kpis.get("active_campaigns", 0)),
        ]))

    flow.extend(_section("Weekly Activity Summary"))
    daily = dashboard.get("daily_activities") or []
    if daily:
        flow.append(_day_strip(daily, generated_on))
    else:
        flow.append(Paragraph("No day-by-day breakdown available for this selection.", BODY_STYLE))

    flow.extend(_section("Candidates Who Logged"))
    logged = candidate_activity.get("logged") or []
    if logged:
        flow.append(_data_table(
            ["Candidate", "Municipality", "Activities (incl. planned)" if planned else "Activities"],
            [[r.get("name", ""), r.get("municipality", ""), r.get("activities", 0)] for r in logged],
            col_widths=[80 * mm, 48 * mm, 50 * mm],
        ))
    else:
        flow.append(Paragraph("No candidates have logged an activity for this selection yet.", BODY_STYLE))

    flow.extend(_overview_flowables(dashboard, generated_on))

    flow.append(Paragraph(
        "This report is generated directly from the Ward Tracker Leadership Dashboard.", FOOTER_STYLE,
    ))
    return _build_pdf(flow)


def wednesday_report_pdf_bytes(dashboard: dict, updated_label: str) -> bytes:
    """Weekly Activity Submission Update — deliberately shows ONLY
    candidates who have logged something so far; never lists or names
    anyone who hasn't. dashboard must already be scoped Monday -> the
    report date (see main.py's wednesday-report endpoint)."""
    period = dashboard["period"]
    participation = dashboard["kpis"].get("candidate_participation", {})
    logged = (dashboard.get("candidate_activity") or {}).get("logged") or []
    submitted = participation.get("submitted", len(logged))
    expected = participation.get("expected", 0)

    flow = _header_flowables("Weekly Activity Submission Update", [f"Week: {period['label']}", f"Updated: {updated_label}"])
    flow.append(Paragraph(f"<b>{submitted} of {expected} candidates have logged activity so far this week.</b>", BODY_STYLE))
    flow.append(Spacer(1, 4 * mm))

    flow.extend(_section("Activity Logged"))
    if logged:
        flow.append(_data_table(
            ["Candidate", "Municipality", "Activities"],
            [[r.get("name", ""), r.get("municipality", ""), r.get("activities", 0)] for r in logged],
            col_widths=[80 * mm, 50 * mm, 30 * mm],
        ))
    else:
        flow.append(Paragraph("No candidates have logged an activity yet this week.", BODY_STYLE))

    flow.append(Paragraph("Activity reporting remains open for the rest of the week.", FOOTER_STYLE))
    return _build_pdf(flow)


def _week_in_progress(week: dict, today: date) -> bool:
    return date.fromisoformat(week["start_date"]) <= today < date.fromisoformat(week["end_date"])


def _trend_chart(weeks: list[dict], today: date) -> Drawing:
    """Grouped bars per week; the x-axis names each week by its Monday
    ("21 Sep"), horizontal and readable — the table below keeps the full
    week ranges. The plotted values are exactly the rows' own totals."""
    width, height = CONTENT_WIDTH, 215
    drawing = Drawing(width, height)
    chart = VerticalBarChart()
    chart.x = 34
    chart.y = 42
    chart.width = width - 44
    chart.height = 130
    chart.data = [
        [w["total_activities"] for w in weeks],
        [w["total_canvassing"] for w in weeks],
    ]
    chart.categoryAxis.categoryNames = [
        short_date(date.fromisoformat(w["start_date"])) + ("*" if _week_in_progress(w, today) else "")
        for w in weeks
    ]
    chart.categoryAxis.labels.fontName = "Helvetica"
    chart.categoryAxis.labels.fontSize = 8.5 if len(weeks) <= 10 else 7.5
    chart.categoryAxis.labels.dy = -4
    chart.categoryAxis.strokeColor = DA_GREY
    chart.valueAxis.labels.fontName = "Helvetica"
    chart.valueAxis.labels.fontSize = 8
    chart.valueAxis.strokeColor = DA_GREY
    chart.valueAxis.gridStrokeColor = DA_LINE
    chart.valueAxis.visibleGrid = True
    chart.valueAxis.valueMin = 0
    max_value = max((max(w["total_activities"], w["total_canvassing"]) for w in weeks), default=0)
    chart.valueAxis.valueMax = max(max_value + 1, 1)
    chart.groupSpacing = 8
    chart.barSpacing = 1
    chart.bars.strokeColor = None
    chart.bars[0].fillColor = DA_BLUE
    chart.bars[1].fillColor = DA_NAVY
    drawing.add(chart)

    drawing.add(String(chart.x + chart.width / 2, 12, "Week starting (Monday)",
                       fontName="Helvetica", fontSize=8, fillColor=DA_GREY, textAnchor="middle"))

    legend = Legend()
    legend.x = chart.x
    legend.y = height - 6
    legend.dx = 8
    legend.dy = 8
    legend.fontName = "Helvetica"
    legend.fontSize = 8.5
    legend.alignment = "right"
    legend.columnMaximum = 1
    legend.deltax = 140
    legend.colorNamePairs = [(DA_BLUE, "Total Activities"), (DA_NAVY, "Canvassing Activities")]
    drawing.add(legend)
    return drawing


def trend_report_pdf_bytes(weeks: list[dict], scope_label: str, generated_on: Optional[date] = None) -> bytes:
    """Activity Trend Report — a chart plus the exact same numbers in a
    table, both built from the same `weeks` rows (leadership_reporting.
    trend_report_weeks) so the chart can never show a different total than
    the table next to it."""
    generated_on = generated_on or sast_today()
    meta = [f"Weeks shown: {weeks[0]['label']} to {weeks[-1]['label']}"] if weeks else []
    meta.append(f"Generated: {long_date(generated_on)}")
    if scope_label and scope_label != "All municipalities":
        meta.append(f"Municipality: {scope_label}")
    flow = _header_flowables("Activity Trend", meta)

    in_progress = [w for w in weeks if _week_in_progress(w, generated_on)]
    if weeks:
        flow.append(_trend_chart(weeks, generated_on))
        flow.append(Spacer(1, 3 * mm))
        flow.append(_data_table(
            ["Week", "Total Activities", "Canvassing Activities", "Candidates Reporting"],
            [[
                w["label"] + (" (in progress)" if w in in_progress else ""),
                w["total_activities"],
                w["total_canvassing"],
                f"{w['candidates_reporting']} / {w['candidates_expected']}",
            ] for w in weeks],
            col_widths=[54 * mm, 36 * mm, 44 * mm, 44 * mm],
        ))
    else:
        flow.append(Paragraph("No reporting weeks available yet.", BODY_STYLE))

    flow.append(Paragraph(
        "Each point represents one full Monday-Sunday reporting week, never a single date.", FOOTER_STYLE,
    ))
    for w in in_progress:
        flow.append(Paragraph(
            f"* The week of {escape(w['label'])} was still in progress on {escape(long_date(generated_on))}: "
            "its figures include planned activities that have not taken place yet.",
            ParagraphStyle("DAFootnote", parent=FOOTER_STYLE, spaceBefore=2),
        ))
    return _build_pdf(flow)
