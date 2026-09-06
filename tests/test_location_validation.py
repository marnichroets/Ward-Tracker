import asyncio
import copy
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


# Phase 5.1: Ward auto-fill + stricter Location/Venue validation.
#   - The candidate's ward has always come from the roster only (never the
#     client) for ordinary entries — resolve_and_canonicalize_person already
#     overwrites body.ward before entry_doc_from_body ever sees it. These
#     tests exercise the *new* piece: Location/Venue is required for new
#     activities and must not simply restate the ward, while historical/edit
#     compatibility (blank legacy venues, blank roster wards) is preserved.
#   - Mirrors the conventions in tests/test_api_smartsheet.py (FakeCollection,
#     direct async-function calls against the real handlers).
@unittest.skipUnless(HAS_API_DEPS, "FastAPI dependencies are not installed")
class NewEntryLocationValidationTests(unittest.TestCase):
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
        self.roster.docs = [
            {"_id": ObjectId(), "name": "Ward Candidate", "ward": "Ward 13", "name_slug": "ward-candidate"},
            {"_id": ObjectId(), "name": "Test Candidate", "ward": "Ward 13", "name_slug": "test-candidate"},
            {"_id": ObjectId(), "name": "Municipality Candidate", "ward": "Amahlathi", "name_slug": "municipality-candidate"},
            # "Municipality" UI-label correction: a roster ward can be a full
            # municipality name, not just a short "Amahlathi"/"Ward 13" form.
            {"_id": ObjectId(), "name": "Long Municipality Candidate", "ward": "Amahlathi Local Municipality", "name_slug": "long-municipality-candidate"},
            {"_id": ObjectId(), "name": "Raymond Mhlaba Candidate", "ward": "Raymond Mhlaba", "name_slug": "raymond-mhlaba-candidate"},
            # Marnich/Kevin-style demo accounts: intentionally blank roster ward.
            {"_id": ObjectId(), "name": "Blank Ward Candidate", "ward": "", "name_slug": "blank-ward-candidate"},
        ]
        appmod.entries_col = self.entries
        appmod.roster_col = self.roster

    def tearDown(self):
        appmod.entries_col = self.original_entries_col
        appmod.roster_col = self.original_roster_col

    def _body(self, **overrides):
        kwargs = dict(
            person_id="ward-candidate",
            name="Ward Candidate",
            ward="Ward 13",
            day="mon",
            type="Door to Door",
            type_display="Door to Door",
            week_key="2026-08-30",
            week_label="31 Aug - 6 Sep",
            activity_date="2026-08-31",
            start_time="09:00",
            end_time="10:00",
            venue="Mlungisi Community Hall",
        )
        kwargs.update(overrides)
        return appmod.EntryIn(**kwargs)

    # ---- required ----

    def test_new_entry_requires_a_location(self):
        with self.assertRaises(HTTPException) as exc:
            asyncio.run(appmod.create_entry(self._body(venue=None)))
        self.assertEqual(exc.exception.status_code, 400)
        self.assertEqual(len(self.entries.docs), 0)

    # ---- ward-only rejection ----

    def test_new_entry_rejects_exact_ward_as_location(self):
        with self.assertRaises(HTTPException) as exc:
            asyncio.run(appmod.create_entry(self._body(venue="Ward 13")))
        self.assertIn("specific location", exc.exception.detail)
        self.assertEqual(len(self.entries.docs), 0)

    def test_new_entry_rejects_case_insensitive_ward_as_location(self):
        with self.assertRaises(HTTPException):
            asyncio.run(appmod.create_entry(self._body(venue="ward 13")))
        self.assertEqual(len(self.entries.docs), 0)

    def test_new_entry_rejects_bare_ward_number_as_location(self):
        with self.assertRaises(HTTPException):
            asyncio.run(appmod.create_entry(self._body(venue="13")))
        self.assertEqual(len(self.entries.docs), 0)

    def test_new_entry_rejects_municipality_name_as_location(self):
        with self.assertRaises(HTTPException):
            asyncio.run(appmod.create_entry(self._body(
                person_id="municipality-candidate", name="Municipality Candidate", ward="Amahlathi",
                venue="Amahlathi",
            )))
        self.assertEqual(len(self.entries.docs), 0)

    def test_new_entry_rejects_full_municipality_name_as_location(self):
        with self.assertRaises(HTTPException):
            asyncio.run(appmod.create_entry(self._body(
                person_id="long-municipality-candidate", name="Long Municipality Candidate",
                ward="Amahlathi Local Municipality", venue="Amahlathi Local Municipality",
            )))
        self.assertEqual(len(self.entries.docs), 0)

    def test_new_entry_rejects_case_insensitive_full_municipality_name_as_location(self):
        with self.assertRaises(HTTPException):
            asyncio.run(appmod.create_entry(self._body(
                person_id="long-municipality-candidate", name="Long Municipality Candidate",
                ward="Amahlathi Local Municipality", venue="amahlathi local municipality",
            )))
        self.assertEqual(len(self.entries.docs), 0)

    def test_new_entry_rejects_raymond_mhlaba_as_location(self):
        with self.assertRaises(HTTPException):
            asyncio.run(appmod.create_entry(self._body(
                person_id="raymond-mhlaba-candidate", name="Raymond Mhlaba Candidate",
                ward="Raymond Mhlaba", venue="Raymond Mhlaba",
            )))
        self.assertEqual(len(self.entries.docs), 0)

    def test_new_entry_allows_a_genuinely_specific_venue_in_a_named_municipality(self):
        result = asyncio.run(appmod.create_entry(self._body(
            person_id="raymond-mhlaba-candidate", name="Raymond Mhlaba Candidate",
            ward="Raymond Mhlaba", venue="New Goodwin Park",
        )))
        self.assertEqual(result["venue"], "New Goodwin Park")

    # ---- legitimate locations that merely mention the ward must be allowed ----

    def test_new_entry_allows_location_containing_ward_text(self):
        result = asyncio.run(appmod.create_entry(self._body(venue="Mlungisi Community Hall, Ward 13")))
        self.assertEqual(result["venue"], "Mlungisi Community Hall, Ward 13")

    def test_new_entry_allows_another_location_containing_ward_text(self):
        result = asyncio.run(appmod.create_entry(self._body(venue="Main Street, Ward 13")))
        self.assertEqual(result["venue"], "Main Street, Ward 13")

    # ---- blank roster ward must never block creation ----

    def test_blank_roster_ward_does_not_block_new_entry(self):
        result = asyncio.run(appmod.create_entry(self._body(
            person_id="blank-ward-candidate", name="Blank Ward Candidate", ward="ignored-by-backend",
            venue="Community Hall",
        )))
        self.assertEqual(result["ward"], "")
        self.assertEqual(result["venue"], "Community Hall")

    def test_blank_roster_ward_still_requires_a_location(self):
        with self.assertRaises(HTTPException):
            asyncio.run(appmod.create_entry(self._body(
                person_id="blank-ward-candidate", name="Blank Ward Candidate", venue=None,
            )))
        self.assertEqual(len(self.entries.docs), 0)

    # ---- edit/legacy compatibility: never newly enforced on existing docs ----

    def test_editing_historical_blank_location_entry_is_not_blocked(self):
        entry_id = ObjectId()
        self.entries.docs = [entry_doc(_id=entry_id, venue=None)]
        updated = asyncio.run(appmod.update_entry(str(entry_id), self._body(
            person_id="test-candidate", name="Test Candidate", venue=None, start_time="10:00", end_time="11:00",
        )))
        self.assertIsNone(updated["venue"])
        self.assertEqual(updated["start_time"], "10:00")

    def test_editing_historical_entry_does_not_rewrite_blank_venue(self):
        entry_id = ObjectId()
        self.entries.docs = [entry_doc(_id=entry_id, venue=None)]
        asyncio.run(appmod.update_entry(str(entry_id), self._body(
            person_id="test-candidate", name="Test Candidate", venue=None, notes="unrelated note",
        )))
        self.assertIsNone(self.entries.docs[0]["venue"], "editing must never backfill a historical blank venue")


# "Municipality" UI-label correction: a targeted, single-record admin
# correction tool for the roster's ward/municipality text (PATCH
# /api/admin/roster/{roster_id}) — never touches name/name_slug/_id, and
# never rewrites any already-stored activity (each activity keeps its own
# `ward` text copy from when it was submitted).
@unittest.skipUnless(HAS_API_DEPS, "FastAPI dependencies are not installed")
class RosterWardUpdateTests(unittest.TestCase):
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
        self.jean_id = ObjectId()
        self.roster.docs = [
            {"_id": self.jean_id, "name": "Jean Lombard", "ward": "Old Municipality Text", "name_slug": "jean-lombard"},
        ]
        appmod.entries_col = self.entries
        appmod.roster_col = self.roster

    def tearDown(self):
        appmod.entries_col = self.original_entries_col
        appmod.roster_col = self.original_roster_col

    def test_update_roster_ward_changes_only_the_ward_field(self):
        result = asyncio.run(appmod.update_roster_ward(
            str(self.jean_id), appmod.RosterWardUpdateIn(ward="Amathole District Municipality"),
        ))
        self.assertEqual(result["ward"], "Amathole District Municipality")
        self.assertEqual(result["name"], "Jean Lombard")
        self.assertEqual(result["name_slug"], "jean-lombard")
        self.assertEqual(result["id"], str(self.jean_id))
        self.assertEqual(len(self.roster.docs), 1, "must never create a duplicate roster record")

    def test_update_roster_ward_rejects_unknown_id(self):
        with self.assertRaises(HTTPException) as exc:
            asyncio.run(appmod.update_roster_ward(
                str(ObjectId()), appmod.RosterWardUpdateIn(ward="Amathole District Municipality"),
            ))
        self.assertEqual(exc.exception.status_code, 404)

    def test_update_roster_ward_does_not_touch_historical_activities(self):
        entry_id = ObjectId()
        self.entries.docs = [{
            "_id": entry_id, "person_id": "jean-lombard", "name": "Jean Lombard",
            "ward": "Old Municipality Text", "day": "mon", "type": "Door to Door",
            "type_display": "Door to Door", "notes": None, "week_key": "2026-08-30",
            "week_label": "31 Aug - 6 Sep", "venue": "Some Historical Venue",
            "submitted_at": "2026-08-31T10:00:00+00:00",
        }]
        asyncio.run(appmod.update_roster_ward(
            str(self.jean_id), appmod.RosterWardUpdateIn(ward="Amathole District Municipality"),
        ))
        self.assertEqual(self.entries.docs[0]["ward"], "Old Municipality Text", "a historical activity's stored ward text must never be rewritten")

    def test_new_activity_after_roster_update_uses_new_canonical_municipality(self):
        asyncio.run(appmod.update_roster_ward(
            str(self.jean_id), appmod.RosterWardUpdateIn(ward="Amathole District Municipality"),
        ))
        result = asyncio.run(appmod.create_entry(appmod.EntryIn(
            person_id="jean-lombard", name="Jean Lombard", ward="ignored-by-backend",
            day="mon", type="Door to Door", type_display="Door to Door",
            week_key="2026-08-30", week_label="31 Aug - 6 Sep", activity_date="2026-08-31",
            start_time="09:00", end_time="10:00", venue="Stutterheim Community Hall",
        )))
        self.assertEqual(result["ward"], "Amathole District Municipality")

    def test_roster_still_has_exactly_one_jean_lombard_after_update(self):
        asyncio.run(appmod.update_roster_ward(
            str(self.jean_id), appmod.RosterWardUpdateIn(ward="Amathole District Municipality"),
        ))
        jean_records = [r for r in self.roster.docs if r["name"] == "Jean Lombard"]
        self.assertEqual(len(jean_records), 1)
        self.assertEqual(jean_records[0]["name_slug"], "jean-lombard")


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


def entry_doc(_id=None, type_display="Door to Door", week_key="2026-08-30", day="mon", venue=None):
    return {
        "_id": _id or ObjectId(),
        "person_id": "test-candidate",
        "name": "Test Candidate",
        "ward": "Ward 13",
        "day": day,
        "type": type_display,
        "type_display": type_display,
        "notes": None,
        "week_key": week_key,
        "week_label": "31 Aug - 6 Sep",
        "venue": venue,
        "submitted_at": "2026-09-01T10:00:00+00:00",
    }


if __name__ == "__main__":
    unittest.main()
