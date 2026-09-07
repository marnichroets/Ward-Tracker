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
            ["Weekly Summary", "Ward Performance", "Activities", "Campaigns", "Weekly Canvassing Activities"],
        )
        activity_headers = [cell.value for cell in wb["Activities"][1]]
        self.assertNotIn("person_id", activity_headers)
        self.assertNotIn("campaign_id", activity_headers)
        self.assertEqual(wb["Weekly Summary"]["A2"].value, "Reporting period")
        self.assertEqual(wb["Ward Performance"]["B2"].value, "Ward 3")
        self.assertEqual(wb["Weekly Summary"]["A6"].value, "Canvassing activities")
        self.assertEqual(wb["Ward Performance"]["A1"].value, "Municipality")
        self.assertEqual(wb["Ward Performance"]["E1"].value, "Canvassing Activities")
        self.assertIn("Roster Participants", activity_headers)
        self.assertIn("Other Participants", activity_headers)
        self.assertIn("Participant Count", activity_headers)
        self.assertIn("Evidence Photo Count", activity_headers)

    def test_excel_activities_include_participants_and_evidence_counts(self):
        entries = [
            entry_doc(
                "alice-candidate", "Alice Candidate", "Ward 1", "Door to Door", "2026-09-06", "mon", "2026-09-07",
                participant_ids=["bob-candidate"],
                other_participants=["Thabo Mokoena", "thabo mokoena", "Sarah Daniels"],
                evidence_photos=[{"id": "64b64c36b7f51c3c4d111111"}, {"id": "64b64c36b7f51c3c4d222222"}],
            )
        ]
        dashboard = self.lr.build_dashboard(entries, self.roster, [], now=self.now)
        payload = self.lr.leadership_workbook_bytes(entries, self.roster, [], dashboard)

        wb = load_workbook(io.BytesIO(payload), data_only=True)
        headers = [cell.value for cell in wb["Activities"][1]]
        row = [cell.value for cell in wb["Activities"][2]]
        by_header = dict(zip(headers, row))

        self.assertEqual(by_header["Roster Participants"], "Bob Candidate")
        self.assertEqual(by_header["Other Participants"], "Thabo Mokoena, Sarah Daniels")
        self.assertEqual(by_header["Participant Count"], 3)
        self.assertEqual(by_header["Evidence Photo Count"], 2)

    def test_latest_activity_exposes_participant_and_evidence_counts(self):
        entries = [
            entry_doc(
                "alice-candidate", "Alice Candidate", "Ward 1", "Door to Door", "2026-09-06", "mon", "2026-09-07",
                participant_ids=["bob-candidate"],
                other_participants=["Sarah Daniels"],
                evidence_photos=[{"id": "64b64c36b7f51c3c4d111111"}],
            )
        ]

        rows = self.lr.latest_activity(entries, self.now, self.lr.build_roster_context(self.roster, entries))

        self.assertEqual(rows[0]["person_id"], "alice-candidate")
        self.assertEqual(rows[0]["participant_count"], 2)
        self.assertEqual(rows[0]["evidence_photo_count"], 1)

    def test_ward_performance_orders_attention_first(self):
        dashboard = self.lr.build_dashboard(self.entries, self.roster, self.campaigns, now=self.now)

        ordered_statuses = [row["status"] for row in dashboard["ward_performance"]]
        self.assertEqual(ordered_statuses, ["Needs Attention", "Active", "Strong"])

    def test_last_activity_ignores_future_planned_dates_for_current_period(self):
        entries = self.entries + [
            entry_doc("alice-candidate", "Alice Candidate", "Ward 1", "Door to Door", "2026-09-13", "mon", "2026-09-14"),
        ]

        dashboard = self.lr.build_dashboard(entries, self.roster, self.campaigns, now=self.now)
        ward_one = next(row for row in dashboard["ward_performance"] if row["ward"] == "Ward 1")

        self.assertEqual(ward_one["last_activity"], "2026-09-08")

    def test_municipality_roster_value_is_not_counted_as_ward(self):
        roster = [
            {"name": "Kevin Leader", "ward": "Amahlathi", "name_slug": "kevin-leader"},
            {"name": "Mapped Candidate", "ward": "Raymond Mhlaba", "name_slug": "mapped-candidate"},
        ]
        entries = [
            entry_doc("mapped-candidate", "Mapped Candidate", "Ward 7, Adelaide", "Door to Door", "2026-08-30", "mon", "2026-08-31"),
            entry_doc("mapped-candidate", "Mapped Candidate", "Raymond Mhlaba", "Door to Door", "2026-09-06", "mon", "2026-09-07"),
        ]

        dashboard = self.lr.build_dashboard(entries, roster, [], now=self.now)

        self.assertEqual([row["ward"] for row in dashboard["ward_performance"]], ["Ward 7"])
        self.assertEqual(dashboard["ward_performance"][0]["municipality"], "Raymond Mhlaba")
        self.assertNotIn("Amahlathi", [row["ward"] for row in dashboard["ward_performance"]])
        self.assertEqual(dashboard["kpis"]["wards_active"], {"active": 1, "total": 1})
        self.assertEqual(dashboard["kpis"]["candidate_participation"], {"submitted": 1, "expected": 1})

    def test_explicit_actual_ward_overrides_legacy_municipality(self):
        roster = [
            {
                "name": "Confirmed Candidate",
                "ward": "Raymond Mhlaba",
                "municipality": "Raymond Mhlaba",
                "actual_ward": "Ward 07",
                "name_slug": "confirmed-candidate",
            }
        ]
        entries = [
            entry_doc("confirmed-candidate", "Confirmed Candidate", "Raymond Mhlaba", "Door to Door", "2026-09-06", "mon", "2026-09-07"),
        ]

        dashboard = self.lr.build_dashboard(entries, roster, [], now=self.now)

        self.assertEqual(dashboard["ward_performance"][0]["ward"], "Ward 7")
        self.assertEqual(dashboard["ward_performance"][0]["municipality"], "Raymond Mhlaba")
        self.assertEqual(dashboard["ward_performance"][0]["activities"], 1)

    def test_explicit_historical_ward_beats_candidate_assignment(self):
        roster = [
            {"name": "Confirmed Candidate", "ward": "Amahlathi", "actual_ward": "Ward 7", "name_slug": "confirmed-candidate"},
        ]
        entries = [
            entry_doc("confirmed-candidate", "Confirmed Candidate", "Ward 10", "Door to Door", "2026-09-06", "mon", "2026-09-07"),
            entry_doc("confirmed-candidate", "Confirmed Candidate", "Amahlathi", "Door to Door", "2026-09-06", "tue", "2026-09-08"),
        ]

        dashboard = self.lr.build_dashboard(entries, roster, [], now=self.now)
        by_ward = {row["ward"]: row for row in dashboard["ward_performance"]}

        self.assertEqual(by_ward["Ward 7"]["activities"], 1)
        self.assertEqual(by_ward["Ward 10"]["activities"], 1)

    def test_ward_value_normalization_and_rejection(self):
        self.assertEqual(self.lr.normalize_actual_ward_value("7"), "Ward 7")
        self.assertEqual(self.lr.normalize_actual_ward_value("Ward 07"), "Ward 7")
        self.assertEqual(self.lr.normalize_actual_ward_value("ward 7"), "Ward 7")
        with self.assertRaises(ValueError):
            self.lr.normalize_actual_ward_value("Amahlathi")

    def test_invalid_stored_actual_ward_does_not_crash_reporting(self):
        roster = [{"name": "Bad Stored Value", "ward": "Amahlathi", "actual_ward": "Amahlathi", "name_slug": "bad-stored-value"}]

        dashboard = self.lr.build_dashboard([], roster, [], now=self.now)

        self.assertEqual(dashboard["ward_performance"], [])
        self.assertEqual(dashboard["ward_model"]["unassigned_candidates"], 1)

    def test_ambiguous_historical_activity_stays_unassigned(self):
        roster = [
            {"name": "Ambiguous Candidate", "ward": "Amahlathi", "name_slug": "ambiguous-candidate"},
            {"name": "Mapped Candidate", "ward": "Amahlathi", "name_slug": "mapped-candidate"},
        ]
        entries = [
            entry_doc("ambiguous-candidate", "Ambiguous Candidate", "Ward 13 and Ward 7 RMM", "Door to Door", "2026-09-06", "mon", "2026-09-07"),
            entry_doc("mapped-candidate", "Mapped Candidate", "Ward 4 Amahlathi", "Door to Door", "2026-09-06", "mon", "2026-09-07"),
        ]

        dashboard = self.lr.build_dashboard(entries, roster, [], now=self.now)

        self.assertEqual([row["ward"] for row in dashboard["ward_performance"]], ["Ward 4"])
        self.assertEqual(dashboard["ward_model"]["unassigned_period_activities"], 1)
        self.assertEqual(dashboard["kpis"]["total_activities"], 2)
        self.assertEqual(dashboard["kpis"]["wards_active"], {"active": 1, "total": 1})
        self.assertEqual(dashboard["kpis"]["candidate_participation"], {"submitted": 1, "expected": 1})

    def test_exact_ward_filter_does_not_match_other_ward_numbers(self):
        roster = [
            {"name": "Ward One", "ward": "Ward 1", "name_slug": "ward-one"},
            {"name": "Ward Ten", "ward": "Ward 10", "name_slug": "ward-ten"},
        ]
        entries = [
            entry_doc("ward-one", "Ward One", "Ward 1", "Door to Door", "2026-09-06", "mon", "2026-09-07"),
            entry_doc("ward-ten", "Ward Ten", "Ward 10", "Door to Door", "2026-09-06", "tue", "2026-09-08"),
        ]

        dashboard = self.lr.build_dashboard(entries, roster, [], ward="Ward 1", now=self.now)
        detail = self.lr.build_ward_detail(entries, roster, [], ward="Ward 1", now=self.now)

        self.assertEqual(dashboard["kpis"]["total_activities"], 1)
        self.assertEqual(detail["ward"]["activities"], 1)
        self.assertEqual(detail["recent_activities"][0]["ward"], "Ward 1")

    def test_excel_ward_performance_uses_actual_ward_values(self):
        roster = [{"name": "Mapped Candidate", "ward": "Raymond Mhlaba", "name_slug": "mapped-candidate"}]
        entries = [
            entry_doc("mapped-candidate", "Mapped Candidate", "Ward 23 Raymond Mhlaba", "Door to Door", "2026-09-06", "mon", "2026-09-07"),
        ]
        dashboard = self.lr.build_dashboard(entries, roster, [], now=self.now)
        payload = self.lr.leadership_workbook_bytes(entries, roster, [], dashboard)

        wb = load_workbook(io.BytesIO(payload), data_only=True)
        self.assertEqual(wb["Ward Performance"]["A2"].value, "Raymond Mhlaba")
        self.assertEqual(wb["Ward Performance"]["B2"].value, "Ward 23")


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
    for key, value in query.items():
        if isinstance(value, dict) and "$in" in value:
            if doc.get(key) not in value["$in"]:
                return False
        elif doc.get(key) != value:
            return False
    return True


def entry_doc(person_id, name, ward, activity, week_key, day, activity_date, **overrides):
    doc = {
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
    doc.update(overrides)
    return doc


async def streaming_body(response):
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk if isinstance(chunk, bytes) else chunk.encode())
    return b"".join(chunks)


if __name__ == "__main__":
    unittest.main()
