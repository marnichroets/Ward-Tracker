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
from typing import Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image as RLImage,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.graphics.shapes import Drawing
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.legends import Legend

# Same palette used throughout the Excel workbooks (leadership_reporting.py)
# and the frontend's own DA brand variables — every export/report in this
# app reads as one consistent document, not a different look per format.
DA_NAVY = colors.HexColor("#153B63")
DA_BLUE = colors.HexColor("#2568AE")
DA_LINE = colors.HexColor("#DCD6C9")
DA_SHADE = colors.HexColor("#F3F1EC")
DA_RED = colors.HexColor("#B0473A")

LOGO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "logo.png")

_styles = getSampleStyleSheet()
TITLE_STYLE = ParagraphStyle(
    "DATitle", parent=_styles["Title"], textColor=DA_NAVY, fontSize=16, leading=20, spaceAfter=2,
)
SUBTITLE_STYLE = ParagraphStyle(
    "DASubtitle", parent=_styles["Normal"], textColor=DA_NAVY, fontSize=11, leading=14, spaceAfter=2,
)
META_STYLE = ParagraphStyle(
    "DAMeta", parent=_styles["Normal"], textColor=colors.HexColor("#6B7280"), fontSize=9.5, leading=13,
)
SECTION_STYLE = ParagraphStyle(
    "DASection", parent=_styles["Heading2"], textColor=DA_NAVY, fontSize=12.5, spaceBefore=14, spaceAfter=6,
)
BODY_STYLE = ParagraphStyle("DABody", parent=_styles["Normal"], fontSize=10, leading=14)
FOOTER_STYLE = ParagraphStyle(
    "DAFooter", parent=_styles["Normal"], textColor=colors.HexColor("#6B7280"), fontSize=9, leading=12,
    spaceBefore=12,
)


def _header_flowables(report_title: str, meta_lines: list[str]) -> list:
    flow = []
    if os.path.exists(LOGO_PATH):
        img = RLImage(LOGO_PATH, width=14 * mm, height=17 * mm)
        flow.append(img)
        flow.append(Spacer(1, 2 * mm))
    flow.append(Paragraph("Democratic Alliance", SUBTITLE_STYLE))
    flow.append(Paragraph("Ntsikana Constituency", META_STYLE))
    flow.append(Spacer(1, 3 * mm))
    flow.append(Paragraph(report_title, TITLE_STYLE))
    for line in meta_lines:
        flow.append(Paragraph(line, META_STYLE))
    flow.append(Spacer(1, 4 * mm))
    return flow


def _summary_table(rows: list[tuple[str, object]]) -> Table:
    data = [[Paragraph(f"<b>{label}</b>", BODY_STYLE), Paragraph(str(value), BODY_STYLE)] for label, value in rows]
    table = Table(data, colWidths=[70 * mm, 90 * mm])
    table.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.75, DA_LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, DA_LINE),
        ("BACKGROUND", (0, 0), (0, -1), DA_SHADE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return table


def _data_table(headers: list[str], rows: list[list[str]], col_widths: Optional[list[float]] = None) -> Table:
    header_row = [Paragraph(f"<b>{h}</b>", ParagraphStyle("th", parent=BODY_STYLE, textColor=colors.white)) for h in headers]
    body_rows = [[Paragraph(str(cell), BODY_STYLE) for cell in row] for row in rows]
    table = Table([header_row] + body_rows, colWidths=col_widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), DA_BLUE),
        ("BOX", (0, 0), (-1, -1), 0.75, DA_LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, DA_LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ]
    for i in range(1, len(body_rows) + 1):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (-1, i), DA_SHADE))
    table.setStyle(TableStyle(style))
    return table


def _build_pdf(flowables: list) -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        topMargin=16 * mm, bottomMargin=14 * mm, leftMargin=16 * mm, rightMargin=16 * mm,
        title="Ntsikana Constituency Report",
    )
    doc.build(flowables)
    return buf.getvalue()


def weekly_report_pdf_bytes(dashboard: dict, scope_label: str) -> bytes:
    """The Weekly PDF Report / Municipality Activity Report PDF — same
    dashboard dict the Excel export and the live dashboard both already
    use; this only lays it out on a page."""
    kpis = dashboard["kpis"]
    period = dashboard["period"]
    participation = kpis.get("candidate_participation", {})
    candidate_activity = dashboard.get("candidate_activity") or {"logged": [], "not_logged": []}

    meta = [f"Reporting Period: {period['label']}"]
    if scope_label and scope_label != "All municipalities":
        meta.append(f"Municipality: {scope_label}")
    flow = _header_flowables("Weekly Activity Report", meta)

    flow.append(_summary_table([
        ("Total Activities", kpis.get("total_activities", 0)),
        ("Canvassing Activities", kpis.get("total_canvassing", 0)),
        ("Candidates Reporting", f"{participation.get('submitted', 0)} / {participation.get('expected', 0)}"),
        ("Active Campaigns", kpis.get("active_campaigns", 0)),
    ]))

    flow.append(Paragraph("Weekly Activity Summary", SECTION_STYLE))
    daily = dashboard.get("daily_activities") or []
    if daily:
        flow.append(_data_table(
            ["Day", "Activities"],
            [[d.get("label", ""), d.get("total", 0)] for d in daily],
            col_widths=[110 * mm, 50 * mm],
        ))
    else:
        flow.append(Paragraph("No day-by-day breakdown available for this selection.", BODY_STYLE))

    flow.append(Paragraph("Candidates Who Logged", SECTION_STYLE))
    logged = candidate_activity.get("logged") or []
    if logged:
        flow.append(_data_table(
            ["Candidate", "Municipality", "Activities"],
            [[r.get("name", ""), r.get("municipality", ""), r.get("activities", 0)] for r in logged],
            col_widths=[80 * mm, 50 * mm, 30 * mm],
        ))
    else:
        flow.append(Paragraph("No candidates have logged an activity for this selection yet.", BODY_STYLE))

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

    flow.append(Paragraph("Activity Logged", SECTION_STYLE))
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


def trend_report_pdf_bytes(weeks: list[dict], scope_label: str) -> bytes:
    """Activity Trend Report — a chart plus the exact same numbers in a
    table, both built from the same `weeks` rows (leadership_reporting.
    trend_report_weeks) so the chart can never show a different total than
    the table next to it."""
    meta = [f"Weeks shown: {weeks[0]['label']} to {weeks[-1]['label']}"] if weeks else []
    if scope_label and scope_label != "All municipalities":
        meta.append(f"Municipality: {scope_label}")
    flow = _header_flowables("Activity Trend", meta)

    if weeks:
        drawing = Drawing(480, 190)
        chart = VerticalBarChart()
        chart.x = 40
        chart.y = 30
        chart.width = 400
        chart.height = 130
        chart.data = [
            [w["total_activities"] for w in weeks],
            [w["total_canvassing"] for w in weeks],
        ]
        chart.categoryAxis.categoryNames = [w["label"] for w in weeks]
        chart.categoryAxis.labels.angle = 30
        chart.categoryAxis.labels.dx = -6
        chart.categoryAxis.labels.fontSize = 6.5
        chart.valueAxis.valueMin = 0
        max_value = max((max(w["total_activities"], w["total_canvassing"]) for w in weeks), default=0)
        chart.valueAxis.valueMax = max(max_value + 1, 1)
        chart.bars[0].fillColor = DA_BLUE
        chart.bars[1].fillColor = DA_NAVY
        drawing.add(chart)

        legend = Legend()
        legend.x = 40
        legend.y = 175
        legend.dx = 8
        legend.dy = 8
        legend.fontSize = 8
        legend.alignment = "right"
        legend.colorNamePairs = [(DA_BLUE, "Total Activities"), (DA_NAVY, "Canvassing Activities")]
        drawing.add(legend)

        flow.append(drawing)
        flow.append(Spacer(1, 4 * mm))
        flow.append(_data_table(
            ["Week", "Total Activities", "Canvassing Activities"],
            [[w["label"], w["total_activities"], w["total_canvassing"]] for w in weeks],
            col_widths=[80 * mm, 50 * mm, 50 * mm],
        ))
    else:
        flow.append(Paragraph("No reporting weeks available yet.", BODY_STYLE))

    flow.append(Paragraph(
        "Each point represents one full Monday-Sunday reporting week, never a single date.", FOOTER_STYLE,
    ))
    return _build_pdf(flow)
