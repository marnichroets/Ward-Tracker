import asyncio
import copy
import io
import os
import unittest
from datetime import date
from types import SimpleNamespace

try:
    from openpyxl import load_workbook

    HAS_REPORT_DEPS = True
except ModuleNotFoundError:
    load_workbook = None
    HAS_REPORT_DEPS = False

try:
    from bson import ObjectId
    from fastapi import HTTPException

    HAS_API_DEPS = True
except ModuleNotFoundError:
    ObjectId = None
    HTTPException = Exception
    HAS_API_DEPS = False


@unittest.skipUnless(HAS_REPORT_DEPS, "openpyxl is not installed")
class LeadershipReportingTests(unittest.TestCase):
    def setUp(self):
        import leadership_reporting as lr

        self.lr = lr
        self.now = date(2026, 9, 10)
        self.roster = [
            {"name": "Alice Candidate", "ward": "Ward 1", "name_slug": "alice-candidate"},
            {"name": "Bob Candidate", "ward": "Ward 2", "name_slug": "bob-candidate"},
            {"name": "Charlie Candidate", "ward": "Ward 3", "name_slug": "charlie-candidate"},
        ]
        self.entries = [
            entry_doc("alice-candidate", "Alice Candidate", "Ward 1", "Door to Door", "2026-09-06", "mon", "2026-09-07"),
            entry_doc("alice-candidate", "Alice Candidate", "Ward 1", "Blue Wave", "2026-09-06", "tue", "2026-09-08"),
            entry_doc("bob-candidate", "Bob Candidate", "Ward 2", "Blue Wave", "2026-09-06", "wed", "2026-09-09"),
            entry_doc("charlie-candidate", "Charlie Candidate", "Ward 3", "Street Meeting", "2026-08-30", "tue", "2026-09-01"),
            entry_doc("alice-candidate", "Alice Candidate", "Ward 1", "Door to Door", "2026-08-30", "mon", "2026-08-31"),
        ]
        self.campaigns = [
            {
                "id": "camp1",
                "person_id": "alice-candidate",
                "name": "Ward 1 Canvassing Drive",
                "purpose": "Increase canvassing",
                "start_date": "2026-09-07",
                "end_date": "2026-09-28",
                "created_at": "2026-09-01T08:00:00+00:00",
                "archived_at": None,
            }
        ]

    def test_dashboard_counts_current_week_from_existing_records(self):
        dashboard = self.lr.build_dashboard(self.entries, self.roster, self.campaigns, now=self.now)

        self.assertEqual(dashboard["period"]["start_date"], "2026-09-07")
        self.assertEqual(dashboard["period"]["end_date"], "2026-09-13")
        self.assertEqual(dashboard["kpis"]["total_activities"], 3)
        self.assertEqual(dashboard["kpis"]["total_canvassing"], 1)
        self.assertEqual(dashboard["kpis"]["active_campaigns"], 1)
        self.assertEqual(dashboard["kpis"]["wards_active"], {"active": 2, "total": 3})
        self.assertEqual(
            dashboard["kpis"]["candidate_participation"],
            {"submitted": 2, "expected": 3},
        )

    def test_ward_statuses_are_transparent_and_not_scores(self):
        dashboard = self.lr.build_dashboard(self.entries, self.roster, self.campaigns, now=self.now)
        by_ward = {row["ward"]: row for row in dashboard["ward_performance"]}

        self.assertEqual(by_ward["Ward 1"]["status"], "Strong")
        self.assertIn("two-activities-per-week", by_ward["Ward 1"]["status_reason"])
        self.assertEqual(by_ward["Ward 2"]["status"], "Active")
        self.assertIn("no canvassing", by_ward["Ward 2"]["status_reason"].lower())
        self.assertEqual(by_ward["Ward 3"]["status"], "Needs Attention")
        self.assertIn("No activity recorded", by_ward["Ward 3"]["status_reason"])

    def test_filtering_by_ward_updates_denominators(self):
        dashboard = self.lr.build_dashboard(
            self.entries,
            self.roster,
            self.campaigns,
            ward="Ward 1",
            now=self.now,
        )

        self.assertEqual(dashboard["kpis"]["total_activities"], 2)
        self.assertEqual(dashboard["kpis"]["total_canvassing"], 1)
        self.assertEqual(dashboard["kpis"]["wards_active"], {"active": 1, "total": 1})
        self.assertEqual(dashboard["kpis"]["candidate_participation"], {"submitted": 1, "expected": 1})

    def test_canvassing_trend_handles_zero_previous_week(self):
        change = self.lr.change_summary(current=4, previous=0, noun="last week")

        self.assertIsNone(change["percent"])
        self.assertEqual(change["direction"], "up")
        self.assertEqual(change["label"], "New activity vs last week")

    def test_excel_workbook_is_valid_and_omits_internal_ids(self):
        dashboard = self.lr.build_dashboard(self.entries, self.roster, self.campaigns, now=self.now)
        payload = self.lr.leadership_workbook_bytes(self.entries, self.roster, self.campaigns, dashboard)

        wb = load_workbook(io.BytesIO(payload))
        self.assertEqual(
            wb.sheetnames,
            ["Weekly Summary", "Ward Performance", "Activities", "Campaigns", "Weekly Canvassing"],
        )
        activity_headers = [cell.value for cell in wb["Activities"][1]]
        self.assertNotIn("person_id", activity_headers)
        self.assertNotIn("campaign_id", activity_headers)
        self.assertEqual(wb["Weekly Summary"]["A2"].value, "Reporting period")
        self.assertEqual(wb["Ward Performance"]["A2"].value, "Ward 1")


@unittest.skipUnless(HAS_API_DEPS, "API dependencies are not installed")
class LeadershipApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("MONGO_URI", "mongodb://127.0.0.1:1")
        os.environ.setdefault("ADMIN_PIN", "1234")
        os.environ.setdefault("JWT_SECRET", "local-test-secret")
        global appmod
        import main as appmod
        appmod.LEADER_PIN = None
        appmod.LEADER_PIN_HASH = appmod.DEFAULT_LEADER_PIN_HASH

    def setUp(self):
        self.original_entries_col = appmod.entries_col
        self.original_roster_col = appmod.roster_col
        self.original_campaigns_col = appmod.campaigns_col
        self.entries = FakeCollection()
        self.roster = FakeCollection()
        self.campaigns = FakeCollection()
        self.roster.docs = [
            {"_id": ObjectId(), "name": "Alice Candidate", "ward": "Ward 1", "name_slug": "alice-candidate"},
            {"_id": ObjectId(), "name": "Bob Candidate", "ward": "Ward 2", "name_slug": "bob-candidate"},
        ]
        this_week = appmod.current_week_key()
        week_start = appmod.activity_date_for_day(this_week, "mon")
        week_tuesday = appmod.activity_date_for_day(this_week, "tue")
        week_end = appmod.activity_date_for_day(this_week, "sun")
        self.entries.docs = [
            entry_doc("alice-candidate", "Alice Candidate", "Ward 1", "Door to Door", this_week, "mon", week_start),
            entry_doc("bob-candidate", "Bob Candidate", "Ward 2", "Blue Wave", this_week, "tue", week_tuesday),
        ]
        self.campaigns.docs = [
            {
                "_id": ObjectId(),
                "person_id": "alice-candidate",
                "name": "Ward 1 Drive",
                "purpose": "",
                "start_date": week_start,
                "end_date": week_end,
                "created_at": "2026-09-01T08:00:00+00:00",
                "archived_at": None,
            }
        ]
        appmod.entries_col = self.entries
        appmod.roster_col = self.roster
        appmod.campaigns_col = self.campaigns

    def tearDown(self):
        appmod.entries_col = self.original_entries_col
        appmod.roster_col = self.original_roster_col
        appmod.campaigns_col = self.original_campaigns_col

    def test_leader_login_accepts_temporary_pin_and_rejects_wrong_pin(self):
        ok = asyncio.run(appmod.leader_login(appmod.LoginRequest(pin="1234")))
        self.assertIn("token", ok)

        with self.assertRaises(HTTPException) as exc:
            asyncio.run(appmod.leader_login(appmod.LoginRequest(pin="9999")))
        self.assertEqual(exc.exception.status_code, 401)

    def test_leader_token_cannot_unlock_admin_routes(self):
        token = appmod.make_leader_token()
        with self.assertRaises(HTTPException) as exc:
            asyncio.run(appmod.require_admin(f"Bearer {token}"))
        self.assertEqual(exc.exception.status_code, 401)

    def test_leader_dashboard_endpoint_is_read_only(self):
        before_entries = copy.deepcopy(self.entries.docs)
        before_roster = copy.deepcopy(self.roster.docs)
        before_campaigns = copy.deepcopy(self.campaigns.docs)

        dashboard = asyncio.run(appmod.leader_dashboard(_=True))

        self.assertEqual(dashboard["kpis"]["total_activities"], 2)
        self.assertEqual(self.entries.docs, before_entries)
        self.assertEqual(self.roster.docs, before_roster)
        self.assertEqual(self.campaigns.docs, before_campaigns)

    def test_leader_export_endpoint_returns_valid_xlsx(self):
        response = asyncio.run(appmod.leader_export_xlsx(_=True))
        payload = asyncio.run(streaming_body(response))

        wb = load_workbook(io.BytesIO(payload))
        self.assertIn("Weekly Summary", wb.sheetnames)
        self.assertIn("Ward Performance", wb.sheetnames)


class AsyncCursor:
    def __init__(self, docs):
        self.docs = [copy.deepcopy(doc) for doc in docs]

    def __aiter__(self):
        self._iter = iter(self.docs)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


class FakeCollection:
    def __init__(self):
        self.docs = []

    def find(self, query=None, projection=None):
        query = query or {}
        docs = [doc for doc in self.docs if matches(doc, query)]
        return AsyncCursor(docs)

    async def find_one(self, query):
        for doc in self.docs:
            if matches(doc, query):
                return copy.deepcopy(doc)
        return None

    async def insert_one(self, doc):
        stored = copy.deepcopy(doc)
        stored["_id"] = ObjectId()
        self.docs.append(stored)
        return SimpleNamespace(inserted_id=stored["_id"])


def matches(doc, query):
    return all(doc.get(key) == value for key, value in query.items())


def entry_doc(person_id, name, ward, activity, week_key, day, activity_date):
    return {
        "_id": ObjectId() if ObjectId else f"{person_id}-{activity_date}-{day}",
        "person_id": person_id,
        "name": name,
        "ward": ward,
        "day": day,
        "type": activity,
        "type_display": activity,
        "notes": None,
        "week_key": week_key,
        "week_label": "Week",
        "activity_date": activity_date,
        "start_time": "09:00",
        "end_time": "10:00",
        "venue": "Community Hall",
        "submitted_at": "2026-09-07T08:00:00+00:00",
    }


async def streaming_body(response):
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk if isinstance(chunk, bytes) else chunk.encode())
    return b"".join(chunks)


if __name__ == "__main__":
    unittest.main()
