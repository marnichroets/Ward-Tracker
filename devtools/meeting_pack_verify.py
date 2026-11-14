"""Verify Leadership Meeting Packs against the existing leadership reports —
LOCAL ONLY, synthetic data, frozen clock (see devtools/golden_reports.py).

    python devtools/meeting_pack_verify.py [OUT.txt]

For every scenario in devtools/meeting_pack_samples.py:
  1. the pack's figures equal the Leadership Dashboard JSON for that period,
     the leadership Excel workbook (Activity Timing, Municipality Summary,
     12-Week Trend sheets) and, for single weeks, the weekly PDF summary;
  2. every line of text PowerPoint shows on each slide appears on the same
     page of the PDF, and the PowerPoint chart series equal the pack.
Needs python-pptx, openpyxl and PyMuPDF (pymupdf) installed locally.
"""
import asyncio
import io
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import golden_reports as g  # noqa: E402  (isolation + frozen clock)
import meeting_pack  # noqa: E402
from meeting_pack_samples import SCENARIOS  # noqa: E402

main = g.main
results: list[str] = []
checks = failures = 0


def check(label, actual, expected):
    global checks, failures
    checks += 1
    if actual != expected:
        failures += 1
        results.append(f"  MISMATCH {label}: {actual!r} != {expected!r}")


def pptx_slides(data: bytes) -> list[dict]:
    from pptx import Presentation
    slides = []
    for slide in Presentation(io.BytesIO(data)).slides:
        lines, series = [], []
        for shape in slide.shapes:
            if shape.has_text_frame:
                lines += [p.text for p in shape.text_frame.paragraphs if p.text.strip()]
            if shape.has_table:
                lines += [c.text for row in shape.table.rows for c in row.cells if c.text.strip()]
            if shape.has_chart:
                series += [list(s.values) for s in shape.chart.plots[0].series]
        slides.append({"lines": lines, "series": series})
    return slides


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


async def verify(name: str, args: dict) -> None:
    entries, roster, campaigns = await main.leadership_dataset()
    pack = meeting_pack.build_meeting_pack(entries, roster, campaigns, args.get("date_from"), args.get("date_to"))
    p = pack["period"]
    q = dict(preset="custom", date_from=p["start_date"], date_to=p["end_date"], ward=None, person_id=None, municipality=None, _=True)
    before = (checks, failures)

    # 1a. Leadership Dashboard JSON (the live dashboard's own endpoint)
    d = await main.leader_dashboard(**q)
    k = d["kpis"]
    check(f"{name} total", pack["kpis"]["total"], k["total_activities"])
    check(f"{name} canvassing", pack["kpis"]["canvassing"], k["total_canvassing"])
    check(f"{name} participation", pack["kpis"]["participation"], k["candidate_participation"])
    check(f"{name} wards active", pack["kpis"]["wards_active"], k["wards_active"])
    check(f"{name} campaigns", pack["kpis"]["active_campaigns"], k["active_campaigns"])
    check(f"{name} no manual capture slide data", "capture" in pack, False)
    check(f"{name} no candidate leaderboard", "top" in pack["participation"], False)
    check(f"{name} completed+planned", pack["kpis"]["completed"] + pack["kpis"]["planned"], k["total_activities"])
    check(f"{name} trend totals", [w["total"] for w in pack["trend"]], [w["total_activities"] for w in d["operational_trend"]])

    # 1b. Leadership Excel workbook for the same period
    xlsx = g.xlsx_cells(await g.body_bytes(await main.leader_export_xlsx(**q)))
    timing_sheet = {r[0]: r[1] for r in xlsx["Activity Timing"]["rows"][1:]}
    check(f"{name} xlsx completed", timing_sheet["Completed (date reached)"], str(pack["kpis"]["completed"]))
    check(f"{name} xlsx planned", timing_sheet["Planned (future dates)"], str(pack["kpis"]["planned"]))
    check(f"{name} xlsx total", timing_sheet["Total recorded"], str(pack["kpis"]["total"]))
    muni_rows = xlsx["Municipality Summary"]["rows"][1:]
    check(f"{name} xlsx municipalities", muni_rows, [[
        m["municipality"], str(m["activities"]), str(m["canvassing"]), str(m["wards_active"]),
        str(m["wards_total"]), str(m["candidates_reporting"]), str(m["candidates_expected"])] for m in pack["municipalities"]])
    trend_rows = xlsx["12-Week Trend"]["rows"][1:]
    check(f"{name} xlsx trend", [(r[2], int(r[3]), int(r[5])) for r in trend_rows],
          [(w["range"], w["total"], w["planned"]) for w in pack["trend"]])

    # 1c. Weekly PDF summary (single weeks only — the Reports page's weekly report)
    if p["weeks"] == 1:
        import pymupdf
        pdf = await g.body_bytes(await main.leader_weekly_report_pdf(preset="custom", date_from=p["start_date"],
                                                                     date_to=p["end_date"], municipality=None, _=True))
        rows = {}
        for page in pymupdf.open(stream=pdf, filetype="pdf"):
            for t in page.find_tables().tables:
                for r in t.extract():
                    if len(r) == 2 and r[0]:
                        rows[norm(r[0])] = norm(r[1] or "")
        total_key = next(key for key in rows if key.startswith("Total Activities"))
        check(f"{name} weekly pdf total", rows[total_key], str(pack["kpis"]["total"]))
        check(f"{name} weekly pdf reporting", rows["Candidates Reporting"],
              f"{pack['participation']['submitted']} / {pack['participation']['expected']}")
        check(f"{name} weekly pdf excludes manual capture", "Captured in Campaign Manager" in rows, False)
        if pack["kpis"]["planned"]:
            check(f"{name} weekly pdf completed", rows["Completed (date reached)"], str(pack["kpis"]["completed"]))
            check(f"{name} weekly pdf planned", rows["Planned (future date)"], str(pack["kpis"]["planned"]))

    # 2. PDF <-> PowerPoint parity, slide by slide
    import pymupdf
    pdf_pages = [norm(page.get_text()) for page in pymupdf.open(stream=meeting_pack.meeting_pack_pdf_bytes(pack), filetype="pdf")]
    slides = pptx_slides(meeting_pack.meeting_pack_pptx_bytes(pack))
    check(f"{name} slide count", (len(pdf_pages), len(slides)), (8, 8))
    for n, (page_text, slide) in enumerate(zip(pdf_pages, slides), 1):
        missing = [line for line in slide["lines"] if norm(line) not in page_text]
        check(f"{name} slide {n} text in PDF", missing, [])
    check(f"{name} pptx trend series", slides[2]["series"][:2] if slides[2]["series"] else [],
          [[w["completed"] for w in pack["trend"]], [w["planned"] for w in pack["trend"]]] if any(w["total"] for w in pack["trend"]) else [])
    results.append(f"{name}: {checks - before[0]} checks, {failures - before[1]} mismatches "
                   f"({p['label']}; {p['state']}; {pack['kpis']['total']} activities = "
                   f"{pack['kpis']['completed']} completed + {pack['kpis']['planned']} planned)")


async def run() -> None:
    for name, args in SCENARIOS.items():
        await verify(name, args)


if __name__ == "__main__":
    g.install_store()
    asyncio.run(run())
    summary = f"{checks} checks across {len(SCENARIOS)} scenarios: {failures} mismatches"
    text = "\n".join(results + [summary])
    print(text)
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(text + "\n", encoding="utf-8")
    sys.exit(1 if failures else 0)
