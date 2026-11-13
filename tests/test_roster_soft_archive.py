"""Safety checks for inactive councillors: stop new selection, preserve history."""
import asyncio
import copy
import os
import unittest
from datetime import date
from types import SimpleNamespace

os.environ.setdefault("MONGO_URI", "mongodb://127.0.0.1:1")
os.environ.setdefault("ADMIN_PIN", "local-test-pin")
os.environ.setdefault("JWT_SECRET", "local-test-secret")

from bson import ObjectId
from fastapi import HTTPException

import main
import leadership_reporting


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    def __aiter__(self):
        self.iterator = iter(self.rows)
        return self

    async def __anext__(self):
        try:
            return next(self.iterator)
        except StopIteration:
            raise StopAsyncIteration


class RosterFake:
    def __init__(self):
        self.docs = [
            {"_id": ObjectId(), "name": "Current Candidate", "name_slug": "current-candidate", "ward": "Ward 1", "municipality": "Amahlathi"},
            {"_id": ObjectId(), "name": "Former Candidate", "name_slug": "former-candidate", "ward": "Ward 2", "municipality": "Amahlathi"},
        ]

    async def find_one(self, query):
        for row in self.docs:
            if all(row.get(k) == v for k, v in query.items()):
                return copy.deepcopy(row)
        return None

    def find(self, query=None, projection=None):
        query = query or {}
        rows = []
        for row in self.docs:
            ok = True
            for k,v in query.items():
                if isinstance(v,dict) and "$in" in v:
                    ok = row.get(k) in v["$in"]
                elif row.get(k) != v:
                    ok = False
                if not ok: break
            if not ok: continue
            if projection:
                include = [k for k,v in projection.items() if v]
                output = {k:copy.deepcopy(row[k]) for k in include if k in row} if include else copy.deepcopy(row)
                if projection.get("_id") == 0: output.pop("_id", None)
            else: output = copy.deepcopy(row)
            rows.append(output)
        return Cursor(rows)

    async def find_one_and_update(self, query, update, return_document=True):
        for row in self.docs:
            if row.get("_id") == query.get("_id"):
                row.update(copy.deepcopy(update["$set"]))
                return copy.deepcopy(row)
        return None


class SoftArchiveTests(unittest.TestCase):
    def setUp(self):
        self.original_roster = main.roster_col
        self.roster = RosterFake()
        main.roster_col = self.roster

    def tearDown(self):
        main.roster_col = self.original_roster

    def test_archive_does_not_delete_name_or_alter_ward_assignment(self):
        person = self.roster.docs[1]
        before_id, before_ward = person["_id"], person["ward"]
        result = asyncio.run(main.update_roster_active(str(before_id), main.RosterActiveUpdateIn(active=False), True))
        self.assertFalse(result["active"])
        self.assertEqual(result["id"], str(before_id))
        self.assertEqual(len(self.roster.docs), 2)
        self.assertEqual(self.roster.docs[1]["ward"], before_ward)
        self.assertTrue(self.roster.docs[1]["inactive_since"])

    def test_archive_rejects_bad_id(self):
        with self.assertRaises(HTTPException) as exc:
            asyncio.run(main.update_roster_active("bad-id", main.RosterActiveUpdateIn(active=False), True))
        self.assertEqual(exc.exception.status_code, 400)

    def test_inactive_name_disappears_from_new_activity_selection(self):
        self.roster.docs[1]["active"] = False
        names = asyncio.run(main.roster_names())
        self.assertEqual([x["name"] for x in names], ["Current Candidate"])
        self.assertNotIn("active", names[0])  # existing public JSON shape maintained
        self.assertEqual(len(self.roster.docs), 2)

    def test_inactive_person_cannot_submit_new_entry_or_campaign(self):
        self.roster.docs[1]["active"] = False
        body = SimpleNamespace(name="Former Candidate", ward="Ward 2", person_id="former-candidate")
        with self.assertRaises(HTTPException) as exc:
            asyncio.run(main.resolve_and_canonicalize_person(body))
        self.assertEqual(exc.exception.status_code, 400)
        with self.assertRaises(HTTPException) as exc:
            asyncio.run(main.resolve_campaign_person_id("former-candidate"))
        self.assertEqual(exc.exception.status_code, 400)
        with self.assertRaises(HTTPException) as exc:
            asyncio.run(main.require_roster_person("former-candidate"))
        self.assertEqual(exc.exception.status_code, 400)
        with self.assertRaises(HTTPException):
            asyncio.run(main.validate_participant_ids(["former-candidate"]))
        asyncio.run(main.validate_participant_ids(["current-candidate"]))
        # Historical participants remain valid when editing their original activity.
        asyncio.run(main.validate_participant_ids(
            ["former-candidate"], previously_attached_ids=["former-candidate"]
        ))
        # Being attached to one activity cannot authorize adding a different inactive person.
        with self.assertRaises(HTTPException):
            asyncio.run(main.validate_participant_ids(
                ["former-candidate"], previously_attached_ids=["current-candidate"]
            ))

    def test_historical_reporting_keeps_archived_person_before_archive_date(self):
        self.roster.docs[1]["active"] = False
        self.roster.docs[1]["inactive_since"] = "2026-11-13"
        historical_entry = {"person_id": "former-candidate", "name": "Former Candidate", "ward": "Ward 2", "activity_date": "2026-10-31", "week_key": "2026-10-25", "type": "Door to Door"}
        ctx = leadership_reporting.build_roster_context(self.roster.docs, [historical_entry])
        past_pool = leadership_reporting.candidate_period_pool(ctx, None, None, period_end=date(2026,11,1))
        today_pool = leadership_reporting.candidate_period_pool(ctx, None, None, period_end=date(2026,11,15))
        self.assertEqual({p["id"] for p in past_pool}, {"current-candidate", "former-candidate"})
        self.assertEqual({p["id"] for p in today_pool}, {"current-candidate"})
        self.assertEqual(historical_entry["person_id"], "former-candidate")
        self.assertEqual(len(self.roster.docs), 2)

    def test_reactivate_restores_name_selection(self):
        pid = self.roster.docs[1]["_id"]
        asyncio.run(main.update_roster_active(str(pid), main.RosterActiveUpdateIn(active=False), True))
        asyncio.run(main.update_roster_active(str(pid), main.RosterActiveUpdateIn(active=True), True))
        names = asyncio.run(main.roster_names())
        self.assertEqual(len(names), 2)
        self.assertIsNone(self.roster.docs[1]["inactive_since"])
