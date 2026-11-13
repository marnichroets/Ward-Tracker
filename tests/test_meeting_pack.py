"""Leadership Meeting Pack (PHO Stage 4): period rules, figures identical to
the dashboard, completed vs planned, PDF/PowerPoint parity and layout
safety, and the leader-only API."""
import asyncio
import io
import os
import re
import sys
import unittest
from datetime import date

os.environ.setdefault("MONGO_URI", "mongodb://127.0.0.1:1")
os.environ.setdefault("ADMIN_PIN", "1234")
os.environ.setdefault("JWT_SECRET", "local-test-secret")

import leadership_reporting as lr
import meeting_pack as mp

DEVTOOLS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "devtools")
if DEVTOOLS not in sys.path:
    sys.path.insert(0, DEVTOOLS)
import synthetic_data  # noqa: E402

try:
    from pptx import Presentation
    from pypdf import PdfReader

    HAS_RENDER_DEPS = True
except ImportError:
    HAS_RENDER_DEPS = False

NOW = date(2026, 9, 10)  # Thursday of the 2026-09-07..13 week
DATA = synthetic_data.generate(today=NOW)


def pack(date_from=None, date_to=None, data=DATA):
    return mp.build_meeting_pack(data["entries"], data["roster"], data["campaigns"], date_from, date_to, now=NOW)


def dashboard(date_from, date_to, data=DATA):
    return lr.build_dashboard(data["entries"], data["roster"], data["campaigns"], preset="custom",
                              date_from=date_from, date_to=date_to, now=NOW)


def pdf_text(data: bytes) -> str:
    return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages)


def pptx_text(data: bytes) -> str:
    out = []
    for slide in Presentation(io.BytesIO(data)).slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                out.append(shape.text_frame.text)
            if shape.has_table:
                out.extend(cell.text for row in shape.table.rows for cell in row.cells)
    return "\n".join(out)


class PeriodTests(unittest.TestCase):
    def test_default_is_the_latest_completed_week(self):
        for today, monday in [(date(2026, 9, 10), "2026-08-31"), (date(2026, 9, 13), "2026-08-31"),
                              (date(2026, 9, 14), "2026-09-07")]:
            start, end = mp.default_period(today)
            self.assertEqual(start.isoformat(), monday, today)
            self.assertEqual((end - start).days, 6)
            self.assertLess(end, today, "the default week must have ended")

    def test_only_whole_weeks_up_to_the_limit(self):
        with self.assertRaises(ValueError):
            mp.resolve_meeting_period("2026-09-08", "2026-09-13", NOW)  # Tuesday start
        with self.assertRaises(ValueError):
            mp.resolve_meeting_period("2026-09-07", "2026-09-12", NOW)  # Saturday end
        with self.assertRaises(ValueError):
            mp.resolve_meeting_period("2026-09-14", "2026-09-06", NOW)
        with self.assertRaises(ValueError):
            mp.resolve_meeting_period("2025-01-06", "2026-09-13", NOW)  # far more than 26 weeks
        with self.assertRaises(ValueError):
            mp.resolve_meeting_period("2026-09-07", None, NOW)
        start, end = mp.resolve_meeting_period("2026-03-16", "2026-09-13", NOW)  # exactly 26 weeks
        self.assertEqual(((end - start).days + 1) // 7, 26)

    def test_labels_name_exact_dates(self):
        p = pack()["period"]
        self.assertEqual(p["label"], "Monday 31 August – Sunday 6 September 2026")
        self.assertEqual(p["short_label"], "31 Aug – 6 Sep 2026")
        self.assertEqual(mp.period_long_label(date(2025, 12, 29), date(2026, 1, 4)),
                         "Monday 29 December 2025 – Sunday 4 January 2026")


class FigureTests(unittest.TestCase):
    """Every figure in the pack is the dashboard's own for the same period."""

    def check_against_dashboard(self, date_from, date_to):
        p, d = pack(date_from, date_to), dashboard(date_from, date_to)
        k, cap = d["kpis"], d["capture_summary"]
        self.assertEqual(p["kpis"]["total"], k["total_activities"])
        self.assertEqual(p["kpis"]["canvassing"], k["total_canvassing"])
        self.assertEqual(p["kpis"]["participation"], k["candidate_participation"])
        self.assertEqual(p["kpis"]["wards_active"], k["wards_active"])
        self.assertEqual(p["kpis"]["active_campaigns"], k["active_campaigns"])
        self.assertNotIn("capture", p)
        self.assertEqual(p["kpis"]["completed"], sum(1 for row in d["weekly_activity"] if lr.maybe_date(row["activity_date"]) <= NOW))
        self.assertEqual(p["kpis"]["planned"], sum(1 for row in d["weekly_activity"] if lr.maybe_date(row["activity_date"]) > NOW))
        self.assertEqual(p["kpis"]["completed"] + p["kpis"]["planned"], k["total_activities"])
        self.assertEqual([{k2: m[k2] for k2 in d["municipality_summary"][0]} for m in p["municipalities"]], d["municipality_summary"])
        for m in p["municipalities"]:
            if m["wards_total"]:
                self.assertEqual(sum(m["status_counts"].values()), m["wards_total"])
        self.assertEqual([w["total"] for w in p["trend"]], [w["total_activities"] for w in d["operational_trend"]])
        for w, row in zip(p["trend"], d["operational_trend"]):
            self.assertEqual(w["completed"] + w["planned"], row["total_activities"])
            self.assertEqual(w["planned"], sum(1 for r in lr.reportable_activities(DATA["entries"])
                                              if (dt := lr.entry_date(r)) and dt > NOW
                                              and lr.maybe_date(row["start_date"]) <= dt <= lr.maybe_date(row["end_date"])))
        self.assertNotIn("top", p["participation"])
        self.assertEqual(p["comparison"]["activities"], d["comparison"]["activities"])
        self.assertFalse(any("capture" in str(a.get("title", "")).lower() for a in p["attention"]))
        return p, d

    def test_completed_week(self):
        p, _d = self.check_against_dashboard("2026-08-31", "2026-09-06")
        self.assertEqual(p["period"]["state"], "completed")
        self.assertEqual(p["kpis"]["planned"], 0)
        self.assertNotIn("planned", " ".join(p["summary"]))

    def test_week_in_progress_separates_planned(self):
        p, _d = self.check_against_dashboard("2026-09-07", "2026-09-13")
        self.assertEqual(p["period"]["state"], "in_progress")
        self.assertGreater(p["kpis"]["planned"], 0)
        self.assertIn(f"{p['kpis']['completed']} completed · {p['kpis']['planned']} planned", p["tiles"][0]["note"])
        self.assertIn("planned", p["summary"][0])

    def test_week_not_started_is_all_planned(self):
        p, _d = self.check_against_dashboard("2026-09-14", "2026-09-20")
        self.assertEqual(p["period"]["state"], "not_started")
        self.assertEqual(p["kpis"]["completed"], 0)
        self.assertEqual(p["kpis"]["planned"], p["kpis"]["total"])

    def test_twelve_and_twenty_six_weeks(self):
        p, _d = self.check_against_dashboard("2026-06-22", "2026-09-13")
        self.assertEqual(len(p["trend"]), 12)
        p, _d = self.check_against_dashboard("2026-03-16", "2026-09-13")
        self.assertEqual(len(p["trend"]), 26)
        self.assertTrue(all(w["in_period"] for w in p["trend"]))

    def test_upcoming_is_the_next_fourteen_days_of_planned_activities(self):
        p = pack()
        up = lr.build_dashboard(DATA["entries"], DATA["roster"], DATA["campaigns"], preset="custom",
                                date_from="2026-09-11", date_to="2026-09-24", now=NOW)
        self.assertEqual(len(p["upcoming"]["activities"]), up["kpis"]["total_activities"])
        self.assertEqual(p["upcoming"]["window_label"], "Friday, 11 September 2026 – Thursday, 24 September 2026")
        statuses = {c["status"].split(" ")[0] for c in p["upcoming"]["campaigns"]}
        self.assertTrue(statuses <= {"Week", "Starts", "Active"}, statuses)

    def test_attention_items_state_only_recorded_facts(self):
        p, d = pack("2026-08-31", "2026-09-06"), dashboard("2026-08-31", "2026-09-06")
        titles = " | ".join(a["title"] for a in p["attention"])
        idle = sum(1 for w in d["ward_performance"] if w["activities"] == 0)
        if idle:
            self.assertIn(f"{idle} ward", titles)
        not_logged = d["candidate_activity"]["not_logged"]
        if not_logged:
            item = next(a for a in p["attention"] if "candidates have no recorded activities in this period" in a["title"])
            self.assertEqual(len(item["items"]), len(not_logged))

    def test_empty_data(self):
        empty = {"entries": [], "roster": DATA["roster"], "campaigns": []}
        p = pack("2026-08-31", "2026-09-06", data=empty)
        self.assertEqual(p["kpis"]["total"], 0)
        self.assertEqual(p["summary"][0], "No activities were recorded for the selected period.")
        self.assertEqual(p["upcoming"]["activities"], [])


class TextFittingTests(unittest.TestCase):
    def test_long_names_are_shortened_to_fit_their_column(self):
        name = "Nomvuyiso Bulelwa Zandile Mbeki-Dube-Ntshinga (Proportional Representation)"
        cols, aligns, cells = mp._table_layout(6.0, [2.75, 1.95, 1.3, 1.43], ["Candidate", "Municipality", "Activities", "Canvassing"],
                                               [[name, "Raymond Mhlaba", 3, 1]], 14)
        self.assertAlmostEqual(sum(cols), 6.0)
        self.assertTrue(cells[1][0].endswith("…"))
        self.assertLessEqual(mp.text_width(cells[1][0], 14), cols[0] - 0.24)
        self.assertEqual(aligns, ["left", "left", "right", "right"])

    def test_lists_end_with_and_n_more_rather_than_a_cut_name(self):
        names = [f"Candidate Number {i} (Amahlathi)" for i in range(40)]
        text = mp.fit_list(names, 6.0, 13, 2)
        self.assertRegex(text, r"; and \d+ more$")
        self.assertLessEqual(len(mp.wrap(text, 6.0, 13)), 2)
        shown = text.split("; and")[0].split("; ")
        self.assertTrue(all(n in names for n in shown), "every listed name is complete")

    def test_nice_axis(self):
        self.assertEqual(mp.nice_axis(0), (5, 1))
        self.assertEqual(mp.nice_axis(52), (60, 20))
        self.assertEqual(mp.nice_axis(7), (8, 2))


@unittest.skipUnless(HAS_RENDER_DEPS, "python-pptx/pypdf are not installed")
class RenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packs = {name: pack(*args) for name, args in {
            "completed": ("2026-08-31", "2026-09-06"),
            "in_progress": ("2026-09-07", "2026-09-13"),
            "long": ("2026-03-16", "2026-09-13"),
        }.items()}

    def test_eight_slides_sixteen_by_nine_in_both_formats(self):
        for name, p in self.packs.items():
            with self.subTest(name):
                reader = PdfReader(io.BytesIO(mp.meeting_pack_pdf_bytes(p)))
                self.assertEqual(len(reader.pages), 8)
                box = reader.pages[0].mediabox
                self.assertAlmostEqual(float(box.width) / float(box.height), 16 / 9, places=2)
                prs = Presentation(io.BytesIO(mp.meeting_pack_pptx_bytes(p)))
                self.assertEqual(len(prs.slides), 8)
                self.assertAlmostEqual(prs.slide_width / prs.slide_height, 16 / 9, places=2)

    def test_pdf_and_powerpoint_show_the_same_words_and_figures(self):
        for name, p in self.packs.items():
            with self.subTest(name):
                pdf_words = re.findall(r"[\w%/–·+…'()-]+", pdf_text(mp.meeting_pack_pdf_bytes(p)))
                ppt_words = re.findall(r"[\w%/–·+…'()-]+", pptx_text(mp.meeting_pack_pptx_bytes(p)))
                # The PDF also contains the chart axis labels, which PowerPoint keeps inside the chart object.
                self.assertTrue(set(ppt_words) <= set(pdf_words), set(ppt_words) - set(pdf_words))
                for number in (p["kpis"]["total"], p["kpis"]["canvassing"], p["kpis"]["completed"], p["kpis"]["planned"]):
                    self.assertIn(str(number), ppt_words)

    def test_powerpoint_is_editable(self):
        prs = Presentation(io.BytesIO(mp.meeting_pack_pptx_bytes(self.packs["in_progress"])))
        charts = [s for slide in prs.slides for s in slide.shapes if s.has_chart]
        tables = [s for slide in prs.slides for s in slide.shapes if s.has_table]
        self.assertEqual(len(charts), 2)  # activity trend + completed/planned status
        self.assertGreaterEqual(len(tables), 3)
        trend = charts[0].chart
        p = self.packs["in_progress"]
        self.assertEqual(list(trend.plots[0].series[0].values), [w["completed"] for w in p["trend"]])
        self.assertEqual(list(trend.plots[0].series[1].values), [w["planned"] for w in p["trend"]])

    def test_every_shape_stays_on_the_slide(self):
        for name, p in self.packs.items():
            prs = Presentation(io.BytesIO(mp.meeting_pack_pptx_bytes(p)))
            for n, slide in enumerate(prs.slides, 1):
                for shape in slide.shapes:
                    with self.subTest(name=name, slide=n, shape=shape.name):
                        self.assertGreaterEqual(shape.left, 0)
                        self.assertGreaterEqual(shape.top, 0)
                        self.assertLessEqual(shape.left + shape.width, prs.slide_width + 1)
                        self.assertLessEqual(shape.top + shape.height, prs.slide_height + 1)


class MeetingPackApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global appmod
        import main as appmod
        import memory_db
        from bson import ObjectId
        cls.ObjectId = ObjectId
        cls.memory_db = memory_db

    def setUp(self):
        self.originals = (appmod.entries_col, appmod.roster_col, appmod.campaigns_col)
        data = synthetic_data.generate(today=NOW)
        for doc in data["roster"] + data["entries"]:
            doc["_id"] = self.ObjectId()
        appmod.entries_col = self.memory_db.MemoryCollection(data["entries"])
        appmod.roster_col = self.memory_db.MemoryCollection(data["roster"])
        appmod.campaigns_col = self.memory_db.MemoryCollection(data["campaigns"])

    def tearDown(self):
        appmod.entries_col, appmod.roster_col, appmod.campaigns_col = self.originals

    def test_routes_are_leader_only(self):
        from fastapi.testclient import TestClient
        with TestClient(appmod.app) as client:
            for path in ("/api/leader/meeting-pack", "/api/leader/meeting-pack.pdf", "/api/leader/meeting-pack.pptx"):
                self.assertEqual(client.get(path).status_code, 401, path)
                admin = {"Authorization": "Bearer " + appmod.make_role_token("admin")}
                self.assertEqual(client.get(path, headers=admin).status_code, 401, path)

    def test_routes_serve_the_same_pack(self):
        from fastapi.testclient import TestClient
        leader = {"Authorization": "Bearer " + appmod.make_role_token("coordinator_leader")}
        q = "?date_from=2026-08-31&date_to=2026-09-06"
        with TestClient(appmod.app) as client:
            data = client.get("/api/leader/meeting-pack" + q, headers=leader)
            self.assertEqual(data.status_code, 200)
            self.assertEqual(data.json()["period"]["start_date"], "2026-08-31")
            pdf = client.get("/api/leader/meeting-pack.pdf" + q, headers=leader)
            self.assertEqual(pdf.headers["content-type"], "application/pdf")
            self.assertIn("Ntsikana_Meeting_Pack_2026-08-31_to_2026-09-06.pdf", pdf.headers["content-disposition"])
            pptx = client.get("/api/leader/meeting-pack.pptx" + q, headers=leader)
            self.assertTrue(pptx.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.presentationml"))
            self.assertTrue(pptx.content.startswith(b"PK"))
            bad = client.get("/api/leader/meeting-pack?date_from=2026-09-01&date_to=2026-09-06", headers=leader)
            self.assertEqual(bad.status_code, 400)
            self.assertIn("Monday", bad.json()["detail"])


if __name__ == "__main__":
    unittest.main()
