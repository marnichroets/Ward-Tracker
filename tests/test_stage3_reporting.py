"""PHO Stage 3: report additions (activity mix, capture / municipality /
trend sheets, weekly PDF sections, per-week participation in the trend
report), dashboard performance work that must not change any number, and
gzip-compressed API responses."""
import asyncio
import io
import os
import sys
import unittest
from datetime import date

os.environ.setdefault("MONGO_URI", "mongodb://127.0.0.1:1")
os.environ.setdefault("ADMIN_PIN", "1234")
os.environ.setdefault("JWT_SECRET", "local-test-secret")

import leadership_reporting as lr
from test_leadership_reporting import entry_doc

DEVTOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "devtools")
if DEVTOOLS not in sys.path:
    sys.path.insert(0, DEVTOOLS)

import synthetic_data  # noqa: E402

try:
    from bson import ObjectId
    from fastapi.testclient import TestClient

    HAS_API_DEPS = True
except ImportError:
    HAS_API_DEPS = False

try:
    from openpyxl import load_workbook
    from pypdf import PdfReader

    HAS_REPORT_DEPS = True
except ImportError:
    HAS_REPORT_DEPS = False

NOW = date(2026, 9, 10)  # Thursday of the 2026-09-07..13 week
ORIGINAL_LEADER_SHEETS = ["Weekly Summary", "Ward Performance", "Activities", "Campaigns", "Weekly Canvassing Activities"]


def synthetic():
    return synthetic_data.generate(today=NOW)


def pdf_text(pdf_bytes: bytes) -> str:
    return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf_bytes)).pages)


def reference_ward_rows(entries, period_entries, context, ward_keys, person_id):
    """The pre-Stage-3 per-ward scan, kept here only to prove the grouped
    implementation attributes every activity to exactly the same ward."""
    out = {}
    for wk in ward_keys:
        out[wk] = (
            sum(1 for doc in period_entries if lr.assigned_ward_for_entry(doc, context) == wk),
            sum(1 for doc in entries if lr.assigned_ward_for_entry(doc, context) == wk and lr.person_matches_filter(doc, person_id)),
        )
    return out


class WardRowPerformanceTests(unittest.TestCase):
    def test_grouped_ward_rows_match_a_per_ward_rescan_for_every_filter(self):
        data = synthetic()
        entries = lr.reportable_activities(data["entries"])
        context = lr.build_roster_context(data["roster"], entries)
        person = next(iter(context["by_person_id"]))
        scenarios = [
            {"preset": "this_week"},
            {"preset": "last_4_weeks"},
            {"preset": "this_week", "municipality": "Amahlathi"},
            {"preset": "this_week", "person_id": person},
        ]
        for scenario in scenarios:
            with self.subTest(**scenario):
                dash = lr.build_dashboard(data["entries"], data["roster"], data["campaigns"], now=NOW, **scenario)
                start, end = lr.period_dates(dash["period"])
                person_id = scenario.get("person_id")
                period_entries = lr.filter_entries(entries, start, end, None, person_id, context, scenario.get("municipality"))
                expected = reference_ward_rows(entries, period_entries, context, [r["ward_key"] for r in dash["ward_performance"]], person_id)
                for row in dash["ward_performance"]:
                    self.assertEqual(row["activities"], expected[row["ward_key"]][0], row["ward_key"])
                    if expected[row["ward_key"]][1] == 0:
                        self.assertEqual(row["status"], "No Activity" if not row["activities"] else row["status"])

    def test_cached_text_parsers_behave_like_plain_functions(self):
        for value, expected in [("Ward 7", "Ward 7"), (" ward 07 ", "Ward 7"), (7, "Ward 7"), (None, None),
                                ("Amahlathi", None), ("14, Amahlathi", "Ward 14"), ("Ward 1 and Ward 2", None)]:
            self.assertEqual(lr.actual_ward_from_text(value), expected, value)
            self.assertEqual(lr.actual_ward_from_text(value), expected, value)  # second call is served from the cache
        self.assertTrue(lr.names_match("Alice Candidate", "alice candidate (Ward 1)"))
        self.assertFalse(lr.names_match("", "Alice"))
        self.assertFalse(lr.names_match(None, "Alice"))


class ActivityMixTests(unittest.TestCase):
    def test_mix_sorts_by_count_then_name_and_rounds_half_up_like_the_dashboard(self):
        rows = [{"activity": a} for a in ["Door to Door"] * 3 + ["blue Wave", "Area Walk", "House Meeting", "House Meeting", "Oversight"]]
        mix = lr.activity_mix(rows)
        self.assertEqual([m["activity"] for m in mix], ["Door to Door", "House Meeting", "Area Walk", "blue Wave", "Oversight"])
        self.assertEqual([m["activities"] for m in mix], [3, 2, 1, 1, 1])
        # 1 of 8 = 12.5% -> 13% (JavaScript Math.round), never banker's rounding to 12%.
        self.assertEqual(mix[-1]["percent"], 13)
        self.assertEqual(lr.activity_mix([]), [])

    def test_dashboard_mix_reconciles_with_total_activities(self):
        data = synthetic()
        for preset in ("this_week", "last_4_weeks"):
            dash = lr.build_dashboard(data["entries"], data["roster"], data["campaigns"], preset=preset, now=NOW)
            self.assertEqual(sum(m["activities"] for m in dash["activity_mix"]), dash["kpis"]["total_activities"])
            self.assertEqual(dash["activity_mix"], lr.activity_mix(dash["weekly_activity"]))


class TrendParticipationTests(unittest.TestCase):
    def test_trend_weeks_carry_the_same_participation_as_the_dashboard(self):
        data = synthetic()
        weeks = lr.trend_report_weeks(data["entries"], data["roster"], weeks_back=4, now=NOW)
        for week in weeks:
            dash = lr.build_dashboard(
                data["entries"], data["roster"], data["campaigns"], preset="custom",
                date_from=week["start_date"], date_to=week["end_date"], now=NOW,
            )
            participation = dash["kpis"]["candidate_participation"]
            self.assertEqual(week["candidates_reporting"], participation["submitted"], week["label"])
            self.assertEqual(week["candidates_expected"], participation["expected"], week["label"])

    def test_participation_respects_the_municipality_filter(self):
        roster = [
            {"name": "Alice Candidate", "ward": "Ward 1", "name_slug": "alice-candidate", "municipality": "Amahlathi", "actual_ward": "Ward 1"},
            {"name": "Cara Candidate", "ward": "Ward 7", "name_slug": "cara-candidate", "municipality": "Raymond Mhlaba", "actual_ward": "Ward 7"},
        ]
        entries = [entry_doc("alice-candidate", "Alice Candidate", "Ward 1", "Door to Door", "2026-09-06", "mon", "2026-09-07")]
        current = lr.trend_report_weeks(entries, roster, weeks_back=1, now=NOW)[-1]
        self.assertEqual((current["candidates_reporting"], current["candidates_expected"]), (1, 2))
        raymond = lr.trend_report_weeks(entries, roster, municipality="Raymond Mhlaba", weeks_back=1, now=NOW)[-1]
        self.assertEqual((raymond["candidates_reporting"], raymond["candidates_expected"]), (0, 1))


@unittest.skipUnless(HAS_REPORT_DEPS, "openpyxl/pypdf are not installed")
class ReportOutputTests(unittest.TestCase):
    def setUp(self):
        self.data = synthetic()
        self.dash = lr.build_dashboard(self.data["entries"], self.data["roster"], self.data["campaigns"], now=NOW)

    def workbook(self):
        return load_workbook(io.BytesIO(lr.leadership_workbook_bytes(
            self.data["entries"], self.data["roster"], self.data["campaigns"], self.dash)))

    def test_new_sheets_are_appended_after_the_original_five(self):
        wb = self.workbook()
        self.assertEqual(wb.sheetnames[:5], ORIGINAL_LEADER_SHEETS)
        self.assertEqual(wb.sheetnames[5:], ["Official Capture", "Municipality Summary", "Activity Mix", "12-Week Trend"])

    def test_new_sheets_reconcile_with_the_dashboard(self):
        wb = self.workbook()
        capture = dict((r[0], r[1]) for r in wb["Official Capture"].iter_rows(min_row=2, values_only=True))
        summary = self.dash["capture_summary"]
        self.assertEqual(capture["Captured in Campaign Manager"], summary["captured"])
        self.assertEqual(capture["Waiting for capture (date has passed)"], summary["awaiting_due"])
        self.assertEqual(capture["Planned (future date)"], summary["awaiting_upcoming"])
        self.assertEqual(capture["Total activities"], self.dash["kpis"]["total_activities"])

        municipalities = list(wb["Municipality Summary"].iter_rows(min_row=2, values_only=True))
        self.assertEqual(sum(r[1] for r in municipalities), self.dash["kpis"]["total_activities"])
        self.assertEqual([r[0] for r in municipalities], [r["municipality"] for r in self.dash["municipality_summary"]])

        mix = list(wb["Activity Mix"].iter_rows(min_row=2, values_only=True))
        self.assertEqual([(r[0], r[1]) for r in mix], [(m["activity"], m["activities"]) for m in self.dash["activity_mix"]])

        trend = list(wb["12-Week Trend"].iter_rows(min_row=2, values_only=True))
        self.assertEqual(len(trend), 12)
        last = self.dash["operational_trend"][-1]
        self.assertEqual(trend[-1][3:], (last["total_activities"], last["total_canvassing"], last["captured"],
                                         last["awaiting_due"], last["planned"], last["candidates_reporting"],
                                         last["candidates_expected"]))
        self.assertEqual(trend[-1][3], self.dash["kpis"]["total_activities"])

    def test_activity_text_is_formula_safe_in_the_mix_sheet(self):
        self.dash["activity_mix"] = [{"activity": "=HYPERLINK(\"x\")", "activities": 1, "percent": 100}]
        cell = self.workbook()["Activity Mix"]["A2"].value
        self.assertFalse(str(cell).startswith("="))

    def test_weekly_pdf_keeps_its_sections_and_adds_capture_municipality_and_mix(self):
        import pdf_reports

        text = pdf_text(pdf_reports.weekly_report_pdf_bytes(self.dash, "All municipalities"))
        order = ["Weekly Activity Report", "Weekly Activity Summary", "Candidates Who Logged",
                 "Official Capture Progress", "Municipality Summary", "Activity Mix",
                 "generated directly from the Ward Tracker Leadership Dashboard"]
        positions = [text.index(heading) for heading in order]
        self.assertEqual(positions, sorted(positions))
        self.assertIn(f"{self.dash['capture_summary']['captured_percent_of_due']}%", text)

    def test_pdf_tables_print_markup_like_text_literally(self):
        import pdf_reports

        self.dash["activity_mix"] = [{"activity": "Rally <b>big & loud", "activities": 1, "percent": 100}]
        text = pdf_text(pdf_reports.weekly_report_pdf_bytes(self.dash, "All municipalities"))
        self.assertIn("Rally <b>big & loud", text)

    def test_weekly_pdf_fits_on_two_pages(self):
        import pdf_reports

        pdf = pdf_reports.weekly_report_pdf_bytes(self.dash, "All municipalities", generated_on=NOW)
        self.assertLessEqual(len(PdfReader(io.BytesIO(pdf)).pages), 2)

    def test_in_progress_week_separates_completed_from_planned(self):
        import pdf_reports

        capture = self.dash["capture_summary"]
        self.assertGreater(capture["awaiting_upcoming"], 0, "fixture week must contain planned activities")
        text = pdf_text(pdf_reports.weekly_report_pdf_bytes(self.dash, "All municipalities", generated_on=NOW))
        self.assertIn("Generated: Thursday, 10 September 2026", text)
        self.assertIn("This period is still in progress", text)
        self.assertRegex(text, rf"Completed \(date has passed\)\s+{capture['due_total']}\b")
        self.assertRegex(text, rf"Planned \(not yet taken place\)\s+{capture['awaiting_upcoming']}\b")
        self.assertEqual(capture["due_total"] + capture["awaiting_upcoming"], self.dash["kpis"]["total_activities"])
        # Fri-Sun are after the generation date: marked Planned, never Completed.
        self.assertEqual(text.count("Planned") - text.count("Planned (") - text.count("Planned and"), 3)
        self.assertIn("Today", text)

    def test_completed_week_has_no_planned_wording(self):
        import pdf_reports

        dash = lr.build_dashboard(self.data["entries"], self.data["roster"], self.data["campaigns"], preset="last_week", now=NOW)
        self.assertEqual(dash["capture_summary"]["awaiting_upcoming"], 0)
        text = pdf_text(pdf_reports.weekly_report_pdf_bytes(dash, "All municipalities", generated_on=NOW))
        self.assertIn("Generated: Thursday, 10 September 2026", text)
        for wording in ("still in progress", "Planned (not yet", "incl. planned", "Status"):
            self.assertNotIn(wording, text)

    def test_grouped_other_row_has_its_own_rounded_share(self):
        mix = lr.activity_mix([{"activity": a} for a in ["A"] * 40 + ["B", "C", "D"] * 2 + ["E", "F"]])
        grouped = lr.activity_mix_with_other(mix, 2)
        self.assertEqual([r["activity"] for r in grouped], ["A", "B", "4 other activity types"])
        other = grouped[-1]
        self.assertEqual(other["activities"], 6)
        self.assertEqual(other["percent"], 13)  # 6 of 48 = 12.5% -> 13%, the same half-up rule as each row
        self.assertEqual(sum(r["activities"] for r in grouped), 48)
        self.assertEqual(lr.activity_mix_with_other(mix, 10), mix)

    def test_weekly_pdf_other_row_prints_its_share(self):
        import pdf_reports

        rows = [{"activity": f"Type {i:02d}", "activities": 1, "percent": 8} for i in range(12)]
        self.dash["activity_mix"] = rows
        text = pdf_text(pdf_reports.weekly_report_pdf_bytes(self.dash, "All municipalities", generated_on=NOW))
        self.assertRegex(text, r"2 other activity types\s+2\s+17%")

    def test_trend_chart_plots_the_row_totals_with_short_horizontal_week_labels(self):
        import pdf_reports

        weeks = lr.trend_report_weeks(self.data["entries"], self.data["roster"], weeks_back=12, now=NOW)
        chart = next(c for c in pdf_reports._trend_chart(weeks, NOW).contents if hasattr(c, "categoryAxis"))
        self.assertEqual(chart.data, [[w["total_activities"] for w in weeks], [w["total_canvassing"] for w in weeks]])
        names = chart.categoryAxis.categoryNames
        self.assertEqual(names[0], "22 Jun")
        self.assertEqual(names[-1], "7 Sep*")  # the week in progress on the generation date
        self.assertTrue(all(len(n) <= 7 for n in names))
        self.assertEqual(chart.categoryAxis.labels.angle, 0)

    def test_trend_pdf_marks_the_week_in_progress_and_shows_generation_date(self):
        import pdf_reports

        weeks = lr.trend_report_weeks(self.data["entries"], self.data["roster"], weeks_back=8, now=NOW)
        text = pdf_text(pdf_reports.trend_report_pdf_bytes(weeks, "All municipalities", generated_on=NOW))
        self.assertIn("Generated: Thursday, 10 September 2026", text)
        self.assertIn(f"{weeks[-1]['label']} (in progress)", text)
        self.assertIn("include planned activities that have not taken place yet", " ".join(text.split()))
        for week in weeks[:-1]:
            self.assertNotIn(f"{week['label']} (in progress)", text)

    def test_trend_pdf_shows_candidates_reporting_per_week(self):
        import pdf_reports

        weeks = lr.trend_report_weeks(self.data["entries"], self.data["roster"], weeks_back=8, now=NOW)
        text = pdf_text(pdf_reports.trend_report_pdf_bytes(weeks, "All municipalities"))
        self.assertIn("Candidates Reporting", text)
        for week in weeks:
            self.assertIn(f"{week['candidates_reporting']} / {week['candidates_expected']}", text)


@unittest.skipUnless(HAS_API_DEPS, "FastAPI TestClient (httpx) is not installed")
class GzipResponseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global appmod
        import main as appmod
        import memory_db

        cls.memory_db = memory_db

    def setUp(self):
        self.originals = (appmod.entries_col, appmod.roster_col, appmod.campaigns_col)
        data = synthetic()
        for doc in data["roster"] + data["entries"]:
            doc["_id"] = ObjectId()
        appmod.entries_col = self.memory_db.MemoryCollection(data["entries"])
        appmod.roster_col = self.memory_db.MemoryCollection(data["roster"])
        appmod.campaigns_col = self.memory_db.MemoryCollection(data["campaigns"])
        self.client = TestClient(appmod.app)
        self.client.__enter__()
        self.leader = {"Authorization": "Bearer " + appmod.make_role_token("coordinator_leader")}

    def tearDown(self):
        self.client.__exit__(None, None, None)
        appmod.entries_col, appmod.roster_col, appmod.campaigns_col = self.originals

    def test_dashboard_json_is_gzipped_when_the_browser_accepts_it(self):
        response = self.client.get("/api/leader/dashboard", headers={**self.leader, "Accept-Encoding": "gzip"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("content-encoding"), "gzip")
        self.assertIn("kpis", response.json())  # transparently decompressed, same JSON

    def test_uncompressed_when_not_accepted_and_identical_content(self):
        plain = self.client.get("/api/leader/dashboard", headers={**self.leader, "Accept-Encoding": "identity"})
        zipped = self.client.get("/api/leader/dashboard", headers={**self.leader, "Accept-Encoding": "gzip"})
        self.assertIsNone(plain.headers.get("content-encoding"))
        self.assertEqual(plain.json(), zipped.json())

    def test_small_responses_are_left_alone(self):
        response = self.client.get("/api/health", headers={"Accept-Encoding": "gzip"})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.headers.get("content-encoding"))


if __name__ == "__main__":
    unittest.main()
