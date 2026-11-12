"""PHO executive dashboard sections (operational_trend, capture_summary,
municipality_summary, per-row capture_status) and the local synthetic
development environment."""
import asyncio
import os
import unittest
from datetime import date

os.environ.setdefault("MONGO_URI", "mongodb://127.0.0.1:1")
os.environ.setdefault("ADMIN_PIN", "1234")
os.environ.setdefault("JWT_SECRET", "local-test-secret")

import leadership_reporting as lr
from test_leadership_reporting import entry_doc

NOW = date(2026, 9, 10)  # Thursday of the 2026-09-07..13 week

ROSTER = [
    {"name": "Alice Candidate", "ward": "Ward 1", "name_slug": "alice-candidate", "municipality": "Amahlathi", "actual_ward": "Ward 1"},
    {"name": "Bob Candidate", "ward": "Ward 2", "name_slug": "bob-candidate", "municipality": "Amahlathi", "actual_ward": "Ward 2"},
    {"name": "Cara Candidate", "ward": "Ward 7", "name_slug": "cara-candidate", "municipality": "Raymond Mhlaba", "actual_ward": "Ward 7"},
]


def entries():
    return [
        # This week (2026-09-07..13)
        entry_doc("alice-candidate", "Alice Candidate", "Ward 1", "Door to Door", "2026-09-06", "mon", "2026-09-07", capture_status="captured"),
        entry_doc("alice-candidate", "Alice Candidate", "Ward 1", "Oversight", "2026-09-06", "tue", "2026-09-08"),
        entry_doc("cara-candidate", "Cara Candidate", "Ward 7", "Door to Door", "2026-09-06", "wed", "2026-09-09"),
        # Planned for later this week: awaiting, but not yet due.
        entry_doc("cara-candidate", "Cara Candidate", "Ward 7", "Street Meeting", "2026-09-06", "sat", "2026-09-12"),
        # Last week (2026-08-31..09-06) — one has no capture_status at all (historical shape).
        entry_doc("bob-candidate", "Bob Candidate", "Ward 2", "Door to Door", "2026-08-30", "mon", "2026-08-31", capture_status="captured"),
        entry_doc("alice-candidate", "Alice Candidate", "Ward 1", "House Meeting", "2026-08-30", "fri", "2026-09-04"),
        # A coordinator-confirmed duplicate never counts anywhere.
        entry_doc("bob-candidate", "Bob Candidate", "Ward 2", "Door to Door", "2026-09-06", "mon", "2026-09-07",
                  duplicate_review_status="confirmed_duplicate"),
    ]


def dashboard(**kwargs):
    kwargs.setdefault("preset", "this_week")
    return lr.build_dashboard(entries(), ROSTER, [], now=NOW, **kwargs)


class OperationalTrendTests(unittest.TestCase):
    def test_twelve_weeks_ending_with_selected_week(self):
        trend = dashboard()["operational_trend"]
        self.assertEqual(len(trend), 12)
        self.assertEqual(trend[-1]["week_key"], "2026-09-06")
        self.assertTrue(trend[-1]["is_current"])
        self.assertEqual([r["week_key"] for r in trend], sorted(r["week_key"] for r in trend))

    def test_last_week_row_reconciles_with_kpis(self):
        data = dashboard()
        row = data["operational_trend"][-1]
        self.assertEqual(row["total_activities"], data["kpis"]["total_activities"])
        self.assertEqual(row["total_activities"], 4)
        self.assertEqual(row["total_canvassing"], data["kpis"]["total_canvassing"])
        self.assertEqual(row["captured"] + row["awaiting_capture"], row["total_activities"])
        self.assertEqual(row["captured"], 1)
        self.assertEqual(row["candidates_reporting"], data["kpis"]["candidate_participation"]["submitted"])
        self.assertEqual(row["candidates_expected"], 3)

    def test_previous_week_and_historical_capture_default(self):
        previous = dashboard()["operational_trend"][-2]
        self.assertEqual(previous["week_key"], "2026-08-30")
        self.assertEqual(previous["total_activities"], 2)
        # The historical document with no capture_status resolves to awaiting.
        self.assertEqual((previous["captured"], previous["awaiting_capture"]), (1, 1))
        self.assertEqual(previous["candidates_reporting"], 2)

    def test_respects_filters(self):
        trend = dashboard(municipality="Raymond Mhlaba")["operational_trend"]
        self.assertEqual(trend[-1]["total_activities"], 2)
        self.assertEqual(trend[-1]["candidates_expected"], 1)

    def test_covers_a_period_longer_than_twelve_weeks(self):
        data = lr.build_dashboard(entries(), ROSTER, [], preset="custom", date_from="2026-03-02", date_to="2026-09-13", now=NOW)
        self.assertGreaterEqual(len(data["operational_trend"]), data["period"]["week_count"])


class CaptureSummaryTests(unittest.TestCase):
    def test_counts_and_due_versus_upcoming(self):
        summary = dashboard()["capture_summary"]
        self.assertEqual(summary["total"], 4)
        self.assertEqual(summary["captured"], 1)
        self.assertEqual(summary["awaiting"], 3)
        self.assertEqual(summary["awaiting_due"], 2)       # 8 and 9 Sep
        self.assertEqual(summary["awaiting_upcoming"], 1)  # 12 Sep is after NOW
        self.assertEqual(summary["captured_percent"], 25)
        self.assertEqual(summary["oldest_awaiting_date"], "2026-09-08")
        self.assertEqual(summary["oldest_awaiting_days"], 2)

    def test_empty_period(self):
        summary = lr.build_dashboard([], ROSTER, [], now=NOW)["capture_summary"]
        self.assertEqual(summary["total"], 0)
        self.assertIsNone(summary["captured_percent"])
        self.assertIsNone(summary["oldest_awaiting_days"])


class MunicipalitySummaryTests(unittest.TestCase):
    def test_rows_sum_to_period_total(self):
        data = dashboard()
        rows = {r["municipality"]: r for r in data["municipality_summary"]}
        self.assertEqual(set(rows), {"Amahlathi", "Raymond Mhlaba"})
        self.assertEqual(sum(r["activities"] for r in rows.values()), data["kpis"]["total_activities"])
        self.assertEqual(rows["Amahlathi"]["activities"], 2)
        self.assertEqual(rows["Amahlathi"]["candidates_reporting"], 1)
        self.assertEqual(rows["Amahlathi"]["candidates_expected"], 2)
        self.assertEqual(rows["Raymond Mhlaba"]["canvassing"], 1)

    def test_wards_come_from_ward_performance(self):
        data = dashboard()
        amahlathi = next(r for r in data["municipality_summary"] if r["municipality"] == "Amahlathi")
        wards = [w for w in data["ward_performance"] if w["municipality"] == "Amahlathi"]
        self.assertEqual(amahlathi["wards_total"], len(wards))
        self.assertEqual(amahlathi["wards_total"], 14)  # official Amahlathi ward count
        self.assertEqual(amahlathi["wards_active"], 1)

    def test_unattributable_activity_gets_a_remainder_row(self):
        stray = entry_doc("nobody", "Unknown Person", "", "Door to Door", "2026-09-06", "mon", "2026-09-07")
        data = lr.build_dashboard(entries() + [stray], ROSTER, [], now=NOW)
        rows = data["municipality_summary"]
        self.assertEqual(rows[-1]["municipality"], "Municipality not recorded")
        self.assertEqual(sum(r["activities"] for r in rows), data["kpis"]["total_activities"])

    def test_municipality_filter_limits_rows(self):
        rows = dashboard(municipality="Amahlathi")["municipality_summary"]
        self.assertEqual([r["municipality"] for r in rows], ["Amahlathi"])


class ActivityRowTests(unittest.TestCase):
    def test_rows_carry_capture_status_and_canvassing_flag(self):
        rows = {(r["candidate"], r["activity_date"]): r for r in dashboard()["weekly_activity"]}
        self.assertEqual(rows[("Alice Candidate", "2026-09-07")]["capture_status"], "captured")
        self.assertTrue(rows[("Alice Candidate", "2026-09-07")]["is_canvassing"])
        self.assertEqual(rows[("Alice Candidate", "2026-09-08")]["capture_status"], "awaiting_capture")
        self.assertFalse(rows[("Alice Candidate", "2026-09-08")]["is_canvassing"])


class SyntheticEnvironmentTests(unittest.TestCase):
    """The local development environment must stay synthetic and isolated."""

    @classmethod
    def setUpClass(cls):
        import sys
        devtools = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "devtools")
        if devtools not in sys.path:
            sys.path.insert(0, devtools)
        import memory_db
        import synthetic_data
        cls.memory_db = memory_db
        cls.synthetic_data = synthetic_data

    def test_generation_is_deterministic(self):
        a = self.synthetic_data.generate(today=NOW)
        b = self.synthetic_data.generate(today=NOW)
        strip = lambda docs: [{k: v for k, v in d.items() if k != "_id"} for d in docs]
        self.assertEqual(strip(a["entries"]), strip(b["entries"]))
        self.assertEqual(a["roster"], b["roster"])

    def test_synthetic_data_reconciles_through_the_real_reporting_engine(self):
        data = self.synthetic_data.generate(today=NOW)
        dash = lr.build_dashboard(data["entries"], data["roster"], data["campaigns"], now=NOW)
        self.assertGreater(dash["kpis"]["total_activities"], 0)
        self.assertEqual(dash["capture_summary"]["total"], dash["kpis"]["total_activities"])
        self.assertEqual(sum(r["activities"] for r in dash["municipality_summary"]), dash["kpis"]["total_activities"])
        self.assertEqual(dash["kpis"]["wards_active"]["total"], 35)  # Amahlathi 14 + Raymond Mhlaba 21

    def test_synthetic_data_has_no_photos_and_only_synthetic_people(self):
        data = self.synthetic_data.generate(today=NOW)
        self.assertTrue(all(not e["evidence_photos"] for e in data["entries"]))
        roster_slugs = {r["name_slug"] for r in data["roster"]}
        self.assertTrue(all(e["person_id"] in roster_slugs for e in data["entries"]))

    def test_memory_store_operators(self):
        from bson import ObjectId
        col = self.memory_db.MemoryCollection([
            {"name_slug": "a", "tags": ["x"], "meta": {"ok": True}},
            {"name_slug": "b", "recurrence_id": "r1"},
        ])

        async def run():
            self.assertEqual(len([d async for d in col.find({"name_slug": {"$in": ["a", "b"]}})]), 2)
            self.assertEqual(len([d async for d in col.find({"recurrence_id": {"$exists": True}})]), 1)
            self.assertIsNotNone(await col.find_one({"tags": "x"}))
            self.assertIsNotNone(await col.find_one({"meta.ok": True}))
            updated = await col.find_one_and_update({"name_slug": "a"}, {"$set": {"meta.ok": False}, "$unset": {"tags": ""}}, return_document=True)
            self.assertEqual(updated["meta"], {"ok": False})
            self.assertNotIn("tags", updated)
            res = await col.insert_one({"name_slug": "c"})
            self.assertIsInstance(res.inserted_id, ObjectId)
            self.assertEqual((await col.delete_one({"name_slug": "c"})).deleted_count, 1)
            only = await col.find_one({"name_slug": "b"}, {"name_slug": 1})
            self.assertEqual(set(only), {"_id", "name_slug"})

        asyncio.run(run())

    def test_local_server_source_forces_isolation(self):
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "devtools", "local_server.py")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn('os.environ["MONGO_URI"] = "mongodb://127.0.0.1:1', src)
        self.assertNotIn("setdefault(\"MONGO_URI\"", src)
        self.assertIn("connect-src 'self'", src)
        self.assertIn('HOST, PORT = "127.0.0.1"', src)
        self.assertNotIn("railway.app", src)


if __name__ == "__main__":
    unittest.main()
