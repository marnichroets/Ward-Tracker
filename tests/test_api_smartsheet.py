import asyncio
import copy
import csv
import io
import os
import unittest
from types import SimpleNamespace


try:
    import fastapi  # noqa: F401
    from bson import ObjectId
    from fastapi import HTTPException

    HAS_API_DEPS = True
except ModuleNotFoundError:
    ObjectId = None
    HTTPException = Exception
    HAS_API_DEPS = False


@unittest.skipUnless(HAS_API_DEPS, "FastAPI dependencies are not installed")
class FastApiSmartSheetTests(unittest.TestCase):
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
        self.entries = FakeCollection()
        self.roster = FakeCollection()
        appmod.entries_col = self.entries
        appmod.roster_col = self.roster

    def tearDown(self):
        appmod.entries_col = self.original_entries_col
        appmod.roster_col = self.original_roster_col

    def test_candidate_submission_persists_new_fields_and_derived_category(self):
        body = appmod.EntryIn(
            person_id="test-candidate",
            name="Test Candidate",
            ward="Ward 1",
            day="mon",
            type="Door to Door",
            type_display="Door to Door",
            notes=None,
            week_key="2026-08-30",
            week_label="31 Aug - 6 Sep",
            activity_date="2026-08-31",
            start_time="09:00",
            end_time="10:30",
            venue="Ward office",
        )

        result = asyncio.run(appmod.create_entry(body))

        self.assertEqual(len(self.entries.docs), 1)
        self.assertEqual(result["start_time"], "09:00")
        self.assertEqual(result["end_time"], "10:30")
        self.assertEqual(result["venue"], "Ward office")
        self.assertEqual(result["smartsheet_category"], "CANVASSING")
        self.assertEqual(result["canonical_activity"], "Door to Door")

    def test_candidate_submission_rejects_obvious_invalid_time_range(self):
        body = appmod.EntryIn(
            person_id="test-candidate",
            name="Test Candidate",
            ward="Ward 1",
            day="mon",
            type="Blue Wave",
            type_display="Blue Wave",
            week_key="2026-08-30",
            week_label="31 Aug - 6 Sep",
            activity_date="2026-08-31",
            start_time="11:00",
            end_time="10:30",
            venue="Main road",
        )

        with self.assertRaises(HTTPException) as exc:
            asyncio.run(appmod.create_entry(body))
        self.assertEqual(exc.exception.status_code, 400)
        self.assertEqual(len(self.entries.docs), 0)

    def test_update_without_notes_preserves_existing_notes(self):
        entry_id = ObjectId()
        self.entries.docs = [
            entry_doc(
                _id=entry_id,
                type_display="Door to Door",
                week_key="2026-08-30",
                day="mon",
                start_time="09:00",
                end_time="10:00",
                venue="Area 1",
            )
        ]
        self.entries.docs[0]["notes"] = "Existing historical note"
        body = appmod.EntryIn(
            person_id="test-candidate",
            name="Test Candidate",
            ward="Ward 1",
            day="mon",
            type="Door to Door",
            type_display="Door to Door",
            notes=None,
            week_key="2026-08-30",
            week_label="31 Aug - 6 Sep",
            activity_date="2026-08-31",
            start_time="09:30",
            end_time="10:30",
            venue="Area 1",
        )

        updated = asyncio.run(appmod.update_entry(str(entry_id), body))

        self.assertEqual(updated["notes"], "Existing historical note")
        self.assertEqual(self.entries.docs[0]["notes"], "Existing historical note")

    def test_existing_csv_and_xlsx_exports_run_against_mocked_data(self):
        self.entries.docs = [
            entry_doc(type_display="Door to Door", week_key="2026-08-30", day="mon"),
        ]
        self.roster.docs = [
            {"_id": ObjectId(), "name": "Test Candidate", "ward": "Ward 1", "name_slug": "test-candidate"}
        ]

        csv_response = asyncio.run(appmod.admin_export_csv(True))
        csv_payload = asyncio.run(streaming_body(csv_response)).decode("utf-8-sig")
        self.assertIn("name,ward,week_label,day,activity_date,type,notes,submitted_at", csv_payload)
        self.assertIn("Door to Door", csv_payload)

        xlsx_response = asyncio.run(appmod.admin_export_xlsx("2026-08-30", True))
        xlsx_payload = asyncio.run(streaming_body(xlsx_response))
        self.assertTrue(xlsx_payload.startswith(b"PK"))

    def test_smartsheet_summary_export_and_review_use_mocked_data_only(self):
        unclear_id = ObjectId()
        self.entries.docs = [
            entry_doc(type_display="Door to Door", week_key="2026-08-30", day="mon", start_time="09:00", end_time="10:00", venue="Area 1"),
            entry_doc(type_display="Street Meeting", week_key="2026-08-30", day="tue"),
            entry_doc(type_display="Blue Wave", week_key="2026-08-30", day="wed"),
            entry_doc(_id=unclear_id, type_display="Meeting", type="Meeting", week_key="2026-08-30", day="thu"),
        ]

        summary = asyncio.run(appmod.admin_smartsheet_summary("2026-08-30", True))
        self.assertEqual(summary["weekly"]["CANVASSING"], 1)
        self.assertEqual(summary["weekly"]["PUBLIC_STREET_MEETING"], 1)
        self.assertEqual(summary["weekly"]["PRESENCE"], 1)
        self.assertEqual(summary["weekly"]["NEEDS_REVIEW"], 1)

        canvassing_response = asyncio.run(appmod.admin_smartsheet_export_csv("2026-08-30", "CANVASSING", True))
        canvassing_rows = csv_rows(asyncio.run(streaming_body(canvassing_response)))
        self.assertEqual(canvassing_rows[0][:9], [
            "DATE", "TIME START", "TIME END", "CONSTITUENCY", "WARD", "VENUE", "ACTIVITY", "BOOST POST", "INFO GRAPHIC",
        ])
        self.assertEqual(len(canvassing_rows), 2)
        self.assertEqual(canvassing_rows[1][6], "Door to Door")

        review_rows = asyncio.run(appmod.admin_smartsheet_review(True))["entries"]
        self.assertEqual(len(review_rows), 1)
        self.assertEqual(review_rows[0]["original_activity"], "Meeting")

        reviewed = asyncio.run(appmod.review_smartsheet_category(
            str(unclear_id),
            appmod.CategoryReviewIn(smartsheet_category="PRESENCE"),
            True,
        ))
        self.assertEqual(reviewed["type_display"], "Meeting")
        self.assertEqual(reviewed["smartsheet_category"], "PRESENCE")
        self.assertEqual(self.entries.docs[-1]["type_display"], "Meeting")

    def test_admin_auth_rejects_missing_token_and_accepts_generated_token(self):
        with self.assertRaises(HTTPException):
            asyncio.run(appmod.require_admin(None))

        token = appmod.make_admin_token()
        self.assertTrue(asyncio.run(appmod.require_admin("Bearer " + token)))


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

    async def create_index(self, *args, **kwargs):
        return "idx"

    def find(self, query=None, projection=None):
        query = query or {}
        docs = [doc for doc in self.docs if matches(doc, query)]
        if projection:
            docs = [project(doc, projection) for doc in docs]
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

    async def find_one_and_update(self, query, update, return_document=True):
        for doc in self.docs:
            if matches(doc, query):
                doc.update(copy.deepcopy(update.get("$set", {})))
                return copy.deepcopy(doc)
        return None

    async def delete_one(self, query):
        before = len(self.docs)
        self.docs = [doc for doc in self.docs if not matches(doc, query)]
        return SimpleNamespace(deleted_count=before - len(self.docs))


def matches(doc, query):
    return all(doc.get(key) == value for key, value in query.items())


def project(doc, projection):
    projected = {}
    include_keys = [key for key, value in projection.items() if value]
    if include_keys:
        for key in include_keys:
            if key in doc:
                projected[key] = doc[key]
    else:
        projected = copy.deepcopy(doc)
    if projection.get("_id") == 0:
        projected.pop("_id", None)
    return projected


def entry_doc(
    _id=None,
    type_display="Door to Door",
    type=None,
    week_key="2026-08-30",
    day="mon",
    start_time=None,
    end_time=None,
    venue=None,
):
    doc = {
        "_id": _id or ObjectId(),
        "person_id": "test-candidate",
        "name": "Test Candidate",
        "ward": "Ward 1",
        "day": day,
        "type": type or type_display,
        "type_display": type_display,
        "notes": None,
        "week_key": week_key,
        "week_label": "31 Aug - 6 Sep",
        "submitted_at": "2026-09-01T10:00:00+00:00",
    }
    if start_time is not None:
        doc["start_time"] = start_time
    if end_time is not None:
        doc["end_time"] = end_time
    if venue is not None:
        doc["venue"] = venue
    return doc


async def streaming_body(response):
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk if isinstance(chunk, bytes) else chunk.encode())
    return b"".join(chunks)


def csv_rows(payload):
    return list(csv.reader(io.StringIO(payload.decode("utf-8-sig"))))


if __name__ == "__main__":
    unittest.main()
