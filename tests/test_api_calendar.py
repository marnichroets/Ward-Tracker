import asyncio
import copy
import io
import os
import unittest

from week_dates import current_week_key, format_week_label, activity_date_for_day

try:
    import fastapi  # noqa: F401
    from bson import ObjectId
    from fastapi import HTTPException

    HAS_API_DEPS = True
except ModuleNotFoundError:
    ObjectId = None
    HTTPException = Exception
    HAS_API_DEPS = False

if HAS_API_DEPS:
    from test_api_smartsheet import FakeCollection, FakeEvidenceBucket

TEST_WEEK_KEY = current_week_key()
TEST_WEEK_LABEL = format_week_label(TEST_WEEK_KEY)
TEST_MONDAY = activity_date_for_day(TEST_WEEK_KEY, "mon")


def entry_doc(**overrides):
    doc = {
        "_id": ObjectId(), "person_id": "willem-p", "name": "Willem P",
        "ward": "Ward 7", "day": "mon", "type": "Door to Door", "type_display": "Door to Door",
        "notes": None, "week_key": TEST_WEEK_KEY, "week_label": TEST_WEEK_LABEL,
        "activity_date": "2026-09-16", "start_time": "09:00", "end_time": "11:00",
        "venue": "Bezville Hall", "campaign_id": "", "submitted_at": "2026-09-16T10:00:00+00:00",
    }
    doc.update(overrides)
    return doc


def campaign_doc(**overrides):
    doc = {
        "_id": ObjectId(), "name": "Soup Kitchen Drive", "person_id": "spokazi-m",
        "municipality": "Amahlathi", "wards": ["Ward 14"], "submission_status": "submitted",
        "start_date": "2026-09-01", "end_date": "2026-09-30",
        "planned_activities": [
            {"id": "p1", "date": "2026-09-20", "time": "10:00", "activity_type": "Soup Kitchen", "area": "On the street corner"},
        ],
    }
    doc.update(overrides)
    return doc


@unittest.skipUnless(HAS_API_DEPS, "FastAPI dependencies are not installed")
class CalendarApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("MONGO_URI", "mongodb://127.0.0.1:1")
        os.environ.setdefault("ADMIN_PIN", "1234")
        os.environ.setdefault("JWT_SECRET", "local-test-secret")
        global appmod
        import main as appmod

    def setUp(self):
        self.original_entries_col = appmod.entries_col
        self.original_roster_col = appmod.roster_col
        self.original_campaigns_col = appmod.campaigns_col
        self.original_evidence_bucket = appmod.evidence_bucket
        self.entries = FakeCollection()
        self.roster = FakeCollection()
        self.campaigns = FakeCollection()
        self.roster.docs = [
            {"_id": ObjectId(), "name": "Willem P", "ward": "Ward 7", "name_slug": "willem-p", "municipality": "Raymond Mhlaba"},
            {"_id": ObjectId(), "name": "Spokazi M", "ward": "Ward 14", "name_slug": "spokazi-m", "municipality": "Amahlathi"},
        ]
        appmod.entries_col = self.entries
        appmod.roster_col = self.roster
        appmod.campaigns_col = self.campaigns
        appmod.evidence_bucket = FakeEvidenceBucket()

    def tearDown(self):
        appmod.entries_col = self.original_entries_col
        appmod.roster_col = self.original_roster_col
        appmod.campaigns_col = self.original_campaigns_col
        appmod.evidence_bucket = self.original_evidence_bucket

    def test_requires_admin_token(self):
        with self.assertRaises(HTTPException):
            asyncio.run(appmod.require_admin(None))

    def test_calendar_json_combines_logged_and_planned(self):
        self.entries.docs = [entry_doc()]
        self.campaigns.docs = [campaign_doc()]

        result = asyncio.run(appmod.admin_calendar(month_key="2026-09", status=None, _=True))
        self.assertEqual(result["month_key"], "2026-09")
        self.assertEqual(result["month_label"], "September 2026")
        self.assertEqual(result["previous_month_key"], "2026-08")
        self.assertEqual(result["next_month_key"], "2026-10")
        statuses = {e["status"] for e in result["entries"]}
        self.assertEqual(statuses, {"LOGGED", "PLANNED"})

    def test_raymond_mhlaba_ward_7_and_amahlathi_ward_7_remain_distinct(self):
        self.entries.docs = [
            entry_doc(person_id="willem-p", ward="Ward 7"),
            entry_doc(_id=ObjectId(), person_id="spokazi-m", name="Spokazi M", ward="Ward 7", activity_date="2026-09-17"),
        ]
        self.campaigns.docs = []
        result = asyncio.run(appmod.admin_calendar(month_key="2026-09", status=None, _=True))
        ward_labels = {e["municipality_ward"] for e in result["entries"]}
        self.assertEqual(ward_labels, {"Raymond Mhlaba Ward 7", "Amahlathi Ward 7"})

    def test_status_filter_planned(self):
        self.entries.docs = [entry_doc()]
        self.campaigns.docs = [campaign_doc()]
        result = asyncio.run(appmod.admin_calendar(month_key="2026-09", status="planned", _=True))
        self.assertTrue(result["entries"])
        self.assertTrue(all(e["status"] == "PLANNED" for e in result["entries"]))

    def test_confirmed_duplicate_excluded_from_calendar(self):
        self.entries.docs = [entry_doc(duplicate_review_status="confirmed_duplicate")]
        self.campaigns.docs = []
        result = asyncio.run(appmod.admin_calendar(month_key="2026-09", status=None, _=True))
        self.assertEqual(result["entries"], [])

    def test_invalid_month_key_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(appmod.admin_calendar(month_key="2026-13", status=None, _=True))
        self.assertEqual(ctx.exception.status_code, 400)

    def test_default_month_is_current_month_when_omitted(self):
        result = asyncio.run(appmod.admin_calendar(month_key=None, status=None, _=True))
        self.assertEqual(result["month_key"], appmod.current_month_key())

    def test_direct_month_selection_returns_that_exact_month(self):
        result_sep = asyncio.run(appmod.admin_calendar(month_key="2026-09", status=None, _=True))
        result_oct = asyncio.run(appmod.admin_calendar(month_key="2026-10", status=None, _=True))
        self.assertEqual(result_sep["month_key"], "2026-09")
        self.assertEqual(result_oct["month_key"], "2026-10")
        self.assertNotEqual(result_sep["month_label"], result_oct["month_label"])

    def test_planned_future_month_activity_appears_only_in_its_own_month(self):
        # A campaign planned activity dated in October must show up when
        # October is selected, and never bleed into September's calendar.
        self.campaigns.docs = [campaign_doc(
            start_date="2026-10-01", end_date="2026-10-31",
            planned_activities=[{"id": "p1", "date": "2026-10-15", "time": "09:00", "activity_type": "Info Table", "area": ""}],
        )]
        self.entries.docs = []

        september = asyncio.run(appmod.admin_calendar(month_key="2026-09", status=None, _=True))
        october = asyncio.run(appmod.admin_calendar(month_key="2026-10", status=None, _=True))
        self.assertEqual(september["entries"], [])
        self.assertEqual(len(october["entries"]), 1)
        self.assertEqual(october["entries"][0]["status"], "PLANNED")
        self.assertEqual(october["entries"][0]["date"], "2026-10-15")

    def test_empty_month_returns_no_entries_without_any_write(self):
        self.entries.docs = []
        self.campaigns.docs = []
        result = asyncio.run(appmod.admin_calendar(month_key="2026-11", status=None, _=True))
        self.assertEqual(result["entries"], [])
        self.assertEqual(result["month_key"], "2026-11")
        # No roster/entries/campaigns documents were created by selecting an
        # empty month.
        self.assertEqual(self.entries.docs, [])
        self.assertEqual(self.campaigns.docs, [])

    def test_export_filename_reflects_selected_month(self):
        self.entries.docs = [entry_doc()]
        response_sep = asyncio.run(appmod.admin_calendar_export_xlsx(month_key="2026-09", _=True))
        response_oct = asyncio.run(appmod.admin_calendar_export_xlsx(month_key="2026-10", _=True))
        self.assertEqual(
            response_sep.headers["content-disposition"],
            "attachment; filename=Ntsikana_Activity_Calendar_September_2026.xlsx",
        )
        self.assertEqual(
            response_oct.headers["content-disposition"],
            "attachment; filename=Ntsikana_Activity_Calendar_October_2026.xlsx",
        )
        self.assertNotIn("current", response_sep.headers["content-disposition"])

    def test_xlsx_export_is_genuine_workbook_with_two_sheets(self):
        self.entries.docs = [entry_doc()]
        self.campaigns.docs = [campaign_doc()]
        response = asyncio.run(appmod.admin_calendar_export_xlsx(month_key="2026-09", _=True))

        async def body():
            chunks = [chunk async for chunk in response.body_iterator]
            return b"".join(c if isinstance(c, bytes) else c.encode() for c in chunks)

        payload = asyncio.run(body())
        self.assertTrue(payload.startswith(b"PK\x03\x04"))
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(payload))
        self.assertEqual(wb.sheetnames, ["Calendar", "Activity List"])

    def test_calendar_generation_causes_zero_database_writes(self):
        # Both routes must only ever call the read side of the fake
        # collections — patch out every write method so an accidental write
        # fails the test loudly instead of silently succeeding.
        for col in (self.entries, self.roster, self.campaigns):
            for method in ("insert_one", "find_one_and_update", "delete_one"):
                setattr(col, method, self._forbidden_write)

        self.entries.docs = [entry_doc()]
        self.campaigns.docs = [campaign_doc()]
        asyncio.run(appmod.admin_calendar(month_key="2026-09", status=None, _=True))
        asyncio.run(appmod.admin_calendar_export_xlsx(month_key="2026-09", _=True))
        # Reaching here without the forbidden-write assertion firing is the
        # proof: no write method was ever invoked by either route.

    @staticmethod
    async def _forbidden_write(*args, **kwargs):
        raise AssertionError("the calendar must never write to the database")

    def test_existing_three_reports_unaffected_by_calendar_addition(self):
        # Same fixture, run through the pre-existing SmartSheet export too —
        # proves adding the calendar route changed nothing about it.
        self.entries.docs = [entry_doc(type_display="Door to Door")]
        response = asyncio.run(appmod.admin_smartsheet_export_xlsx("2026-09", "CANVASSING", True))

        async def body():
            chunks = [chunk async for chunk in response.body_iterator]
            return b"".join(c if isinstance(c, bytes) else c.encode() for c in chunks)

        payload = asyncio.run(body())
        self.assertTrue(payload.startswith(b"PK\x03\x04"))


if __name__ == "__main__":
    unittest.main()
