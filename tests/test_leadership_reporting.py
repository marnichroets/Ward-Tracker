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

    def test_candidate_activity_splits_logged_and_not_logged_by_period(self):
        dashboard = self.lr.build_dashboard(self.entries, self.roster, self.campaigns, now=self.now)
        candidate_activity = dashboard["candidate_activity"]

        logged_ids = [row["id"] for row in candidate_activity["logged"]]
        not_logged_ids = [row["id"] for row in candidate_activity["not_logged"]]
        self.assertEqual(logged_ids, ["alice-candidate", "bob-candidate"])
        self.assertEqual(not_logged_ids, ["charlie-candidate"])
        self.assertEqual(candidate_activity["logged"][0]["activities"], 2)
        self.assertEqual(candidate_activity["logged"][1]["activities"], 1)
        self.assertEqual(candidate_activity["not_logged"][0]["ward"], "Ward 3")

    def test_candidate_activity_shows_ward_not_assigned_for_unassigned_candidate(self):
        roster = self.roster + [{"name": "Dana Candidate", "ward": "", "name_slug": "dana-candidate"}]
        dashboard = self.lr.build_dashboard(self.entries, roster, self.campaigns, now=self.now)

        not_logged = {row["id"]: row for row in dashboard["candidate_activity"]["not_logged"]}
        self.assertIn("dana-candidate", not_logged)
        self.assertEqual(not_logged["dana-candidate"]["ward"], "Ward not assigned")

    def test_who_logged_and_has_not_logged_are_mutually_exclusive(self):
        # Invariant: for every candidate in the selected period, exactly one
        # of who_logged / has_not_logged holds — never both, never neither.
        for preset in ("this_week", "last_week", "last_4_weeks", "all"):
            dashboard = self.lr.build_dashboard(self.entries, self.roster, self.campaigns, preset=preset, now=self.now)
            ca = dashboard["candidate_activity"]
            logged_ids = {row["id"] for row in ca["logged"]}
            not_logged_ids = {row["id"] for row in ca["not_logged"]}
            self.assertEqual(logged_ids & not_logged_ids, set(), f"candidate in both lists for preset={preset}")
            all_ids = {p["id"] for p in self.lr.build_roster_context(self.roster, self.entries)["by_person_id"].values()}
            self.assertEqual(logged_ids | not_logged_ids, all_ids, f"candidate missing from both lists for preset={preset}")
            for row in ca["logged"]:
                self.assertGreater(row["activities"], 0)
            for row in ca["not_logged"]:
                self.assertEqual(row["activities"], 0)

    def test_candidate_filter_matches_the_same_totals_as_who_logged(self):
        # Selecting a candidate via the person_id filter (what the dashboard
        # dropdown sends) must produce the exact same activity/canvassing
        # totals as that candidate's own row in candidate_activity — the
        # dropdown must never disagree with Who Logged / Has Not Logged.
        for preset in ("this_week", "last_week", "last_4_weeks", "all"):
            unfiltered = self.lr.build_dashboard(self.entries, self.roster, self.campaigns, preset=preset, now=self.now)
            ca = unfiltered["candidate_activity"]
            by_id = {row["id"]: row for row in ca["logged"] + ca["not_logged"]}
            for person_id, expected in by_id.items():
                filtered = self.lr.build_dashboard(
                    self.entries, self.roster, self.campaigns, preset=preset, person_id=person_id, now=self.now
                )
                self.assertEqual(
                    filtered["kpis"]["total_activities"], expected["activities"],
                    f"{person_id} total_activities mismatch for preset={preset}",
                )
                self.assertEqual(
                    filtered["kpis"]["total_canvassing"], expected["canvassing"],
                    f"{person_id} total_canvassing mismatch for preset={preset}",
                )
                if expected["activities"] > 0:
                    filtered_ids = {r["id"] for r in filtered["candidate_activity"]["logged"]}
                    self.assertIn(person_id, filtered_ids)
                    not_logged_ids = {r["id"] for r in filtered["candidate_activity"]["not_logged"]}
                    self.assertNotIn(person_id, not_logged_ids)

    def test_candidate_and_ward_filters_combine_without_silently_dropping_data(self):
        # Filtering by both a candidate and their own confirmed ward must
        # still return their real activity; filtering by a candidate and an
        # unrelated ward is allowed to legitimately return zero.
        own_ward_result = self.lr.build_dashboard(
            self.entries, self.roster, self.campaigns, preset="this_week", ward="Ward 1", person_id="alice-candidate", now=self.now
        )
        self.assertEqual(own_ward_result["kpis"]["total_activities"], 2)

        other_ward_result = self.lr.build_dashboard(
            self.entries, self.roster, self.campaigns, preset="this_week", ward="Ward 2", person_id="alice-candidate", now=self.now
        )
        self.assertEqual(other_ward_result["kpis"]["total_activities"], 0)

    def test_candidate_with_ambiguous_historical_ward_never_shows_as_zero_activity_ward_member(self):
        # Reproduces the live "Mavis Krishi" bug: a roster candidate whose
        # actual_ward is unresolved because her own historical activities
        # carry two different explicit wards must not be listed as a
        # (0-activity) "candidate" of either ward for a period where her
        # real activities exist but aren't attributed to either ward.
        roster = [
            {"name": "Mavis Krishi", "name_slug": "mavis-krishi", "ward": ""},
            {"name": "Malixole Ncume", "name_slug": "malixole-ncume", "ward": "Ward 9", "actual_ward": "Ward 9"},
        ]
        entries = [
            entry_doc("mavis-krishi", "Mavis Krishi", "Ward 9", "Door to Door", "2026-08-23", "mon", "2026-08-25"),
            entry_doc("mavis-krishi", "Mavis Krishi", "Ward 13", "Door to Door", "2026-08-23", "fri", "2026-08-29"),
            entry_doc("mavis-krishi", "Mavis Krishi", "", "Door to Door", "2026-08-30", "tue", "2026-09-01"),
            entry_doc("mavis-krishi", "Mavis Krishi", "", "Blue Wave", "2026-08-30", "wed", "2026-09-02"),
            entry_doc("mavis-krishi", "Mavis Krishi", "", "Door to Door", "2026-08-30", "thu", "2026-09-03"),
            entry_doc("mavis-krishi", "Mavis Krishi", "", "Door to Door", "2026-08-30", "fri", "2026-09-04"),
        ]
        dashboard = self.lr.build_dashboard(entries, roster, [], preset="last_week", now=date(2026, 9, 8))

        ca = dashboard["candidate_activity"]
        logged = {row["id"]: row for row in ca["logged"]}
        not_logged = {row["id"] for row in ca["not_logged"]}
        self.assertIn("mavis-krishi", logged)
        self.assertEqual(logged["mavis-krishi"]["activities"], 4)
        self.assertNotIn("mavis-krishi", not_logged)

        by_ward = {row["ward"]: row for row in dashboard["ward_performance"]}
        self.assertNotIn("Mavis Krishi", by_ward["Ward 9"]["candidate"])
        self.assertNotIn("Mavis Krishi", by_ward["Ward 13"]["candidate"])
        self.assertEqual(by_ward["Ward 9"]["activities"], 0)
        self.assertEqual(by_ward["Ward 13"]["activities"], 0)

        # Reconciliation: nothing disappears or double-counts.
        total = dashboard["kpis"]["total_activities"]
        ward_sum = sum(row["activities"] for row in dashboard["ward_performance"])
        unassigned = dashboard["ward_model"]["unassigned_period_activities"]
        self.assertEqual(ward_sum + unassigned, total)

    def test_confirmed_actual_ward_wins_over_ambiguous_historical_text(self):
        roster = [{"name": "Pat Confirmed", "name_slug": "pat-confirmed", "ward": "", "actual_ward": "Ward 7"}]
        entries = [
            entry_doc("pat-confirmed", "Pat Confirmed", "Ward 3", "Door to Door", "2026-09-06", "mon", "2026-09-07"),
            entry_doc("pat-confirmed", "Pat Confirmed", "Ward 12", "Door to Door", "2026-08-30", "mon", "2026-08-31"),
        ]
        context = self.lr.build_roster_context(roster, entries)
        self.assertEqual(context["by_person_id"]["pat-confirmed"]["ward"], "Ward 7")

        dashboard = self.lr.build_dashboard(entries, roster, [], preset="this_week", now=self.now)
        by_ward = {row["ward"]: row for row in dashboard["ward_performance"]}
        # The confirmed roster assignment (Ward 7) is who "Pat Confirmed" is
        # listed as belonging to; it is never attached to Ward 3 or Ward 12
        # purely because old activities happened to mention those wards.
        self.assertIn("Pat Confirmed", by_ward["Ward 7"]["candidate"])
        if "Ward 3" in by_ward:
            self.assertNotIn("Pat Confirmed", by_ward["Ward 3"]["candidate"])
        if "Ward 12" in by_ward:
            self.assertNotIn("Pat Confirmed", by_ward["Ward 12"]["candidate"])

    def test_explicit_activity_ward_still_counts_toward_that_wards_totals(self):
        # An activity's own explicit ward text is still respected for that
        # activity's attribution — this fix only stops the *candidate name*
        # from being listed under a ward that isn't their confirmed one.
        roster = [{"name": "Pat Explicit", "name_slug": "pat-explicit", "ward": "", "actual_ward": "Ward 7"}]
        entries = [
            entry_doc("pat-explicit", "Pat Explicit", "Ward 3", "Door to Door", "2026-09-06", "mon", "2026-09-07"),
        ]
        dashboard = self.lr.build_dashboard(entries, roster, [], preset="this_week", now=self.now)
        by_ward = {row["ward"]: row for row in dashboard["ward_performance"]}
        self.assertEqual(by_ward["Ward 3"]["activities"], 1)
        self.assertEqual(by_ward["Ward 7"]["activities"], 0)

    def test_dedupe_candidate_names_merges_only_safe_subset_matches(self):
        merged = self.lr.dedupe_candidate_names(
            ["R. Pickering", "Richard Brennand Pickering (CLLR)", "Richard Pickering"]
        )
        self.assertEqual(merged, ["R. Pickering", "Richard Brennand Pickering (CLLR)"])

        merged = self.lr.dedupe_candidate_names(["Ndileka Ngxakangxaka", "Ndileka Ngxakangxaka (CLLR)"])
        self.assertEqual(merged, ["Ndileka Ngxakangxaka (CLLR)"])

        merged = self.lr.dedupe_candidate_names(["Jean Lombard (CLLR)", "Jean Lombard (cllr)"])
        self.assertEqual(len(merged), 1)

    def test_dedupe_candidate_names_keeps_unrelated_people_separate(self):
        # An initial-only name must never be silently merged with a
        # different, unrelated full name that happens to share a surname.
        merged = self.lr.dedupe_candidate_names(["A. Smith", "Brian Smith"])
        self.assertEqual(sorted(merged), ["A. Smith", "Brian Smith"])

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
        self.assertIn("Ntsikana Constituency", wb["Weekly Summary"]["A2"].value)
        self.assertIn(dashboard["period"]["label"], wb["Weekly Summary"]["A3"].value)
        ward_column = [cell[0].value for cell in wb["Ward Performance"].iter_rows(min_row=2, min_col=2, max_col=2)]
        self.assertIn("Ward 3", ward_column)
        self.assertEqual(wb["Ward Performance"]["A1"].value, "Municipality")
        self.assertEqual(wb["Ward Performance"]["E1"].value, "Canvassing Activities")
        self.assertIn("Roster Participants", activity_headers)
        self.assertIn("Other Participants", activity_headers)
        self.assertIn("Participant Count", activity_headers)
        self.assertIn("Evidence Photo Count", activity_headers)

    def test_weekly_summary_sheet_matches_dashboard_totals_exactly(self):
        # The workbook must never drift from the live dashboard: it reads
        # the same dashboard dict, not a second calculation.
        dashboard = self.lr.build_dashboard(self.entries, self.roster, self.campaigns, now=self.now)
        payload = self.lr.leadership_workbook_bytes(self.entries, self.roster, self.campaigns, dashboard)
        wb = load_workbook(io.BytesIO(payload))
        ws = wb["Weekly Summary"]

        values = [[cell.value for cell in row] for row in ws.iter_rows(min_row=1, max_col=6)]
        summary_header_row = next(i for i, r in enumerate(values) if r[0] == "SUMMARY")
        cell_by_label = {
            r[0]: r[1] for r in values[summary_header_row + 1:summary_header_row + 7] if r[0]
        }
        self.assertEqual(cell_by_label["Total Activities"], dashboard["kpis"]["total_activities"])
        self.assertEqual(cell_by_label["Canvassing Activities"], dashboard["kpis"]["total_canvassing"])
        self.assertEqual(cell_by_label["Active Campaigns"], dashboard["kpis"]["active_campaigns"])
        self.assertEqual(
            cell_by_label["Wards Active"],
            f"{dashboard['kpis']['wards_active']['active']} / {dashboard['kpis']['wards_active']['total']}",
        )
        ca = dashboard["candidate_activity"]
        self.assertEqual(cell_by_label["Candidates Who Logged"], len(ca["logged"]))
        self.assertEqual(cell_by_label["Candidates Who Did Not Log"], len(ca["not_logged"]))

        # Who Logged / Has Not Logged section headings and row counts.
        who_logged_header_row = next(i for i, r in enumerate(values) if r[0] == "WHO LOGGED")
        self.assertEqual(
            values[who_logged_header_row + 1][:5],
            ["Candidate", "Municipality", "Ward(s)", "Activities", "Canvassing Activities"],
        )
        logged_names = {values[who_logged_header_row + 2 + i][0] for i in range(len(ca["logged"]))}
        self.assertEqual(logged_names, {r["name"] for r in ca["logged"]})

        has_not_logged_header_row = next(i for i, r in enumerate(values) if r[0] == "HAS NOT LOGGED")
        self.assertEqual(values[has_not_logged_header_row + 1][:3], ["Candidate", "Municipality", "Ward(s)"])
        not_logged_names = {values[has_not_logged_header_row + 2 + i][0] for i in range(len(ca["not_logged"]))}
        self.assertEqual(not_logged_names, {r["name"] for r in ca["not_logged"]})

        ward_summary_header_row = next(i for i, r in enumerate(values) if r[0] == "WARD SUMMARY")
        self.assertEqual(
            values[ward_summary_header_row + 1][:6],
            ["Municipality", "Ward", "Candidate", "Activities", "Canvassing Activities", "Status"],
        )
        ward_rows_in_sheet = len(dashboard["ward_performance"])
        sheet_ward_names = {
            values[ward_summary_header_row + 2 + i][1] for i in range(ward_rows_in_sheet)
        }
        self.assertEqual(sheet_ward_names, {row["ward"] for row in dashboard["ward_performance"]})

    def test_weekly_summary_no_secrets_or_internal_fields(self):
        dashboard = self.lr.build_dashboard(self.entries, self.roster, self.campaigns, now=self.now)
        payload = self.lr.leadership_workbook_bytes(self.entries, self.roster, self.campaigns, dashboard)
        wb = load_workbook(io.BytesIO(payload))
        ws = wb["Weekly Summary"]
        all_text = " ".join(
            str(cell.value) for row in ws.iter_rows(max_col=5) for cell in row if cell.value is not None
        )
        for forbidden in ("person_id", "_id", "token", "mongo", "Mongo", "gridfs", "GridFS"):
            self.assertNotIn(forbidden, all_text)

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

    def test_ward_performance_orders_by_municipality_then_ward_number(self):
        dashboard = self.lr.build_dashboard(self.entries, self.roster, self.campaigns, now=self.now)

        ordered_wards = [row["ward"] for row in dashboard["ward_performance"]]
        self.assertEqual(ordered_wards, ["Ward 1", "Ward 2", "Ward 3"])

    def test_ward_performance_orders_numerically_not_lexicographically(self):
        roster = [
            {"name": "P2", "name_slug": "p2", "ward": "", "actual_ward": "Ward 2"},
            {"name": "P10", "name_slug": "p10", "ward": "", "actual_ward": "Ward 10"},
            {"name": "P11", "name_slug": "p11", "ward": "", "actual_ward": "Ward 11"},
        ]
        dashboard = self.lr.build_dashboard([], roster, [], preset="this_week", now=self.now)
        ordered_wards = [row["ward"] for row in dashboard["ward_performance"]]
        self.assertEqual(ordered_wards, ["Ward 2", "Ward 10", "Ward 11"])

    def test_ward_performance_groups_by_municipality_before_ward_number(self):
        roster = [
            {"name": "Andre Van Rayner", "name_slug": "andre-van-rayner", "ward": "", "municipality": "Raymond Mhlaba", "actual_ward": "Ward 4"},
            {"name": "Richard Pickering", "name_slug": "richard-pickering", "ward": "", "municipality": "Amahlathi", "actual_ward": "Ward 4"},
        ]
        dashboard = self.lr.build_dashboard([], roster, [], preset="this_week", now=self.now)
        ordered = [(row["municipality"], row["ward"]) for row in dashboard["ward_performance"]]
        # Both official municipalities' full ward ranges are now present
        # (see OFFICIAL_WARD_COUNTS), but the two Ward 4s must still sort as
        # separate rows in municipality order, never merged into one.
        amahlathi_4_index = ordered.index(("Amahlathi", "Ward 4"))
        raymond_4_index = ordered.index(("Raymond Mhlaba", "Ward 4"))
        self.assertLess(amahlathi_4_index, raymond_4_index)
        self.assertEqual(ordered.count(("Amahlathi", "Ward 4")), 1)
        self.assertEqual(ordered.count(("Raymond Mhlaba", "Ward 4")), 1)

    def test_same_numbered_ward_in_different_municipalities_never_merges_activities(self):
        # Amahlathi Ward 9 (Mavis Krishi) and Raymond Mhlaba Ward 9 (Malixole
        # Ncume) must be reported completely independently.
        roster = [
            {"name": "Mavis Krishi", "name_slug": "mavis-krishi", "ward": "", "municipality": "Amahlathi", "actual_ward": "Ward 9"},
            {"name": "Malixole Ncume", "name_slug": "malixole-ncume", "ward": "", "municipality": "Raymond Mhlaba", "actual_ward": "Ward 9"},
        ]
        entries = [
            entry_doc("mavis-krishi", "Mavis Krishi", "", "Door to Door", "2026-09-06", "mon", "2026-09-07"),
            entry_doc("mavis-krishi", "Mavis Krishi", "", "Blue Wave", "2026-09-06", "tue", "2026-09-08"),
        ]
        dashboard = self.lr.build_dashboard(entries, roster, [], preset="this_week", now=self.now)
        by_muni = {(row["municipality"], row["ward"]): row for row in dashboard["ward_performance"]}

        amahlathi_9 = by_muni[("Amahlathi", "Ward 9")]
        raymond_9 = by_muni[("Raymond Mhlaba", "Ward 9")]
        self.assertEqual(amahlathi_9["candidate"], "Mavis Krishi")
        self.assertEqual(amahlathi_9["activities"], 2)
        self.assertEqual(raymond_9["candidate"], "Malixole Ncume")
        self.assertEqual(raymond_9["activities"], 0)
        self.assertNotIn("Malixole", amahlathi_9["candidate"])
        self.assertNotIn("Mavis", raymond_9["candidate"])

    def test_multi_ward_candidate_activity_counts_once_toward_its_own_selected_ward(self):
        roster = [{
            "name": "Spokazi Elizabeth Mpayipeli", "name_slug": "spokazi-elizabeth-mpayipeli",
            "ward": "", "municipality": "Amahlathi",
            "actual_wards": ["Ward 2", "Ward 3", "Ward 7", "Ward 10", "Ward 11", "Ward 14"],
        }]
        entries = [
            entry_doc("spokazi-elizabeth-mpayipeli", "Spokazi Elizabeth Mpayipeli", "Ward 2", "Door to Door", "2026-09-06", "mon", "2026-09-07"),
        ]
        dashboard = self.lr.build_dashboard(entries, roster, [], preset="this_week", now=self.now)
        by_ward = {row["ward"]: row for row in dashboard["ward_performance"]}

        self.assertEqual(by_ward["Ward 2"]["activities"], 1)
        for other_ward in ("Ward 3", "Ward 7", "Ward 10", "Ward 11", "Ward 14"):
            self.assertEqual(by_ward[other_ward]["activities"], 0, f"{other_ward} must not double-count Spokazi's Ward 2 activity")
        self.assertEqual(dashboard["kpis"]["total_activities"], 1)

        ca = dashboard["candidate_activity"]
        spokazi_row = next(r for r in ca["logged"] if r["id"] == "spokazi-elizabeth-mpayipeli")
        self.assertEqual(spokazi_row["activities"], 1)
        self.assertEqual(spokazi_row["ward"], "Ward 2, Ward 3, Ward 7, Ward 10, Ward 11, Ward 14")

    def test_multi_ward_candidate_filter_selects_only_that_ward_activity(self):
        roster = [{
            "name": "Spokazi Elizabeth Mpayipeli", "name_slug": "spokazi-elizabeth-mpayipeli",
            "ward": "", "municipality": "Amahlathi",
            "actual_wards": ["Ward 2", "Ward 3"],
        }]
        entries = [
            entry_doc("spokazi-elizabeth-mpayipeli", "Spokazi Elizabeth Mpayipeli", "Ward 2", "Door to Door", "2026-09-06", "mon", "2026-09-07"),
            entry_doc("spokazi-elizabeth-mpayipeli", "Spokazi Elizabeth Mpayipeli", "Ward 3", "Door to Door", "2026-09-06", "tue", "2026-09-08"),
        ]
        context = self.lr.build_roster_context(roster, entries)
        ward_2_key = self.lr.ward_key("Amahlathi", "Ward 2")
        ward_3_key = self.lr.ward_key("Amahlathi", "Ward 3")

        dashboard_ward_2 = self.lr.build_dashboard(entries, roster, [], preset="this_week", ward=ward_2_key, now=self.now)
        self.assertEqual(dashboard_ward_2["kpis"]["total_activities"], 1)
        dashboard_ward_3 = self.lr.build_dashboard(entries, roster, [], preset="this_week", ward=ward_3_key, now=self.now)
        self.assertEqual(dashboard_ward_3["kpis"]["total_activities"], 1)

    def test_wards_active_denominator_uses_official_ward_counts(self):
        roster = [
            {"name": "Mavis Krishi", "name_slug": "mavis-krishi", "ward": "", "municipality": "Amahlathi", "actual_ward": "Ward 9"},
            {"name": "Andre Van Rayner", "name_slug": "andre-van-rayner", "ward": "", "municipality": "Raymond Mhlaba", "actual_ward": "Ward 4"},
        ]
        dashboard = self.lr.build_dashboard([], roster, [], preset="this_week", now=self.now)
        self.assertEqual(dashboard["kpis"]["wards_active"]["total"], 14 + 21)

        amahlathi_only = self.lr.build_dashboard([], roster, [], preset="this_week", municipality="Amahlathi", now=self.now)
        self.assertEqual(amahlathi_only["kpis"]["wards_active"]["total"], 14)

        raymond_only = self.lr.build_dashboard([], roster, [], preset="this_week", municipality="Raymond Mhlaba", now=self.now)
        self.assertEqual(raymond_only["kpis"]["wards_active"]["total"], 21)

    def test_ward_performance_shows_all_official_wards_even_with_no_candidate(self):
        roster = [{"name": "Mavis Krishi", "name_slug": "mavis-krishi", "ward": "", "municipality": "Amahlathi", "actual_ward": "Ward 9"}]
        dashboard = self.lr.build_dashboard([], roster, [], preset="this_week", municipality="Amahlathi", now=self.now)
        wards_shown = {row["ward"] for row in dashboard["ward_performance"]}
        self.assertEqual(len(wards_shown), 14)
        self.assertIn("Ward 8", wards_shown)  # nobody confirmed for it yet — still shown

    def test_municipality_filter_scopes_kpis_and_never_mixes_municipalities(self):
        roster = [
            {"name": "Mavis Krishi", "name_slug": "mavis-krishi", "ward": "", "municipality": "Amahlathi", "actual_ward": "Ward 9"},
            {"name": "Malixole Ncume", "name_slug": "malixole-ncume", "ward": "", "municipality": "Raymond Mhlaba", "actual_ward": "Ward 9"},
        ]
        entries = [
            entry_doc("mavis-krishi", "Mavis Krishi", "", "Door to Door", "2026-09-06", "mon", "2026-09-07"),
            entry_doc("malixole-ncume", "Malixole Ncume", "", "Door to Door", "2026-09-06", "mon", "2026-09-07"),
        ]
        amahlathi_dashboard = self.lr.build_dashboard(entries, roster, [], preset="this_week", municipality="Amahlathi", now=self.now)
        self.assertEqual(amahlathi_dashboard["kpis"]["total_activities"], 1)
        raymond_dashboard = self.lr.build_dashboard(entries, roster, [], preset="this_week", municipality="Raymond Mhlaba", now=self.now)
        self.assertEqual(raymond_dashboard["kpis"]["total_activities"], 1)
        all_dashboard = self.lr.build_dashboard(entries, roster, [], preset="this_week", now=self.now)
        self.assertEqual(all_dashboard["kpis"]["total_activities"], 2)

    def test_daily_canvassing_sums_to_the_same_week_canvassing_kpi(self):
        entries = [
            entry_doc("alice-candidate", "Alice Candidate", "Ward 1", "Door to Door", "2026-09-06", "mon", "2026-09-07"),
            entry_doc("alice-candidate", "Alice Candidate", "Ward 1", "Door to Door", "2026-09-06", "wed", "2026-09-09"),
            entry_doc("alice-candidate", "Alice Candidate", "Ward 1", "Door to Door", "2026-09-06", "fri", "2026-09-11"),
        ]
        dashboard = self.lr.build_dashboard(entries, self.roster, [], preset="this_week", now=self.now)
        daily = dashboard["daily_canvassing"]
        self.assertEqual(len(daily), 7)
        self.assertEqual(sum(day["total"] for day in daily), dashboard["kpis"]["total_canvassing"])
        self.assertGreater(dashboard["kpis"]["total_canvassing"], 0)

    def test_daily_canvassing_changes_with_selected_week(self):
        entries = [
            entry_doc("alice-candidate", "Alice Candidate", "Ward 1", "Door to Door", "2026-08-30", "mon", "2026-08-31"),
        ]
        this_week = self.lr.build_dashboard(entries, self.roster, [], preset="this_week", now=self.now)
        last_week = self.lr.build_dashboard(entries, self.roster, [], preset="last_week", now=self.now)
        self.assertEqual(sum(d["total"] for d in this_week["daily_canvassing"]), 0)
        self.assertEqual(sum(d["total"] for d in last_week["daily_canvassing"]), 1)
        self.assertNotEqual(
            [d["date"] for d in this_week["daily_canvassing"]],
            [d["date"] for d in last_week["daily_canvassing"]],
        )

    def test_daily_canvassing_marks_future_days_without_hiding_real_data(self):
        # self.now = Thu 10 Sep 2026; the selected week runs Mon 7 Sep -
        # Sun 13 Sep, so Mon-Thu are past/today and Fri-Sun are future.
        entries = [
            entry_doc("alice-candidate", "Alice Candidate", "Ward 1", "Door to Door", "2026-09-06", "fri", "2026-09-11"),
        ]
        dashboard = self.lr.build_dashboard(entries, self.roster, [], preset="this_week", now=self.now)
        by_date = {d["date"]: d for d in dashboard["daily_canvassing"]}

        self.assertFalse(by_date["2026-09-07"]["is_future"])
        self.assertFalse(by_date["2026-09-10"]["is_future"])
        self.assertTrue(by_date["2026-09-11"]["is_future"])
        # A future day with a genuinely pre-logged activity still reports
        # its real count — "future" is a display flag, never a data hider.
        self.assertEqual(by_date["2026-09-11"]["total"], 1)
        self.assertTrue(by_date["2026-09-13"]["is_future"])
        self.assertEqual(sum(d["total"] for d in dashboard["daily_canvassing"]), dashboard["kpis"]["total_canvassing"])

    def test_incomplete_week_compares_against_same_point_last_week_not_full_week(self):
        # self.now = 2026-09-10 (Thursday) in the this_week period 7-13 Sep,
        # so this week is only partially elapsed (Mon-Thu = 4 days so far).
        entries = [
            entry_doc("alice-candidate", "Alice Candidate", "Ward 1", "Door to Door", "2026-09-06", "mon", "2026-09-07"),
            # Full previous week (31 Aug - 6 Sep) has activity on all 7 days.
            entry_doc("alice-candidate", "Alice Candidate", "Ward 1", "Door to Door", "2026-08-30", "mon", "2026-08-31"),
            entry_doc("alice-candidate", "Alice Candidate", "Ward 1", "Door to Door", "2026-08-30", "sun", "2026-09-06"),
        ]
        dashboard = self.lr.build_dashboard(entries, self.roster, [], preset="this_week", now=self.now)
        self.assertTrue(dashboard["period_in_progress"])
        self.assertEqual(dashboard["comparison"]["noun"], "same point last week")
        # Previous week's "so far" (Mon-Thu equivalent) excludes the Sunday
        # entry, so the comparison is 1 vs 1, not 1 vs 2.
        self.assertEqual(dashboard["comparison"]["canvassing"]["previous"], 1)

    def test_complete_week_compares_against_full_last_week(self):
        dashboard = self.lr.build_dashboard(self.entries, self.roster, self.campaigns, preset="last_week", now=self.now)
        self.assertFalse(dashboard["period_in_progress"])
        self.assertEqual(dashboard["comparison"]["noun"], "last week")

    def test_last_activity_ignores_future_planned_dates_for_current_period(self):
        entries = self.entries + [
            entry_doc("alice-candidate", "Alice Candidate", "Ward 1", "Door to Door", "2026-09-13", "mon", "2026-09-14"),
        ]

        dashboard = self.lr.build_dashboard(entries, self.roster, self.campaigns, now=self.now)
        ward_one = next(row for row in dashboard["ward_performance"] if row["ward"] == "Ward 1")

        self.assertEqual(ward_one["last_activity"], "2026-09-08")

    def test_municipality_roster_value_is_not_counted_as_ward(self):
        # Uses a municipality name outside OFFICIAL_WARD_COUNTS deliberately
        # — this test is about municipality text vs. a ward number, not
        # about the official-ward-structure pre-registration.
        roster = [
            {"name": "Kevin Leader", "ward": "Buffalo City", "name_slug": "kevin-leader"},
            {"name": "Mapped Candidate", "ward": "Test Municipality", "name_slug": "mapped-candidate"},
        ]
        entries = [
            entry_doc("mapped-candidate", "Mapped Candidate", "Ward 7, Adelaide", "Door to Door", "2026-08-30", "mon", "2026-08-31"),
            entry_doc("mapped-candidate", "Mapped Candidate", "Test Municipality", "Door to Door", "2026-09-06", "mon", "2026-09-07"),
        ]

        dashboard = self.lr.build_dashboard(entries, roster, [], now=self.now)

        self.assertEqual([row["ward"] for row in dashboard["ward_performance"]], ["Ward 7"])
        self.assertEqual(dashboard["ward_performance"][0]["municipality"], "Test Municipality")
        self.assertNotIn("Buffalo City", [row["ward"] for row in dashboard["ward_performance"]])
        self.assertEqual(dashboard["kpis"]["wards_active"], {"active": 1, "total": 1})
        self.assertEqual(dashboard["kpis"]["candidate_participation"], {"submitted": 1, "expected": 1})

    def test_explicit_actual_ward_overrides_legacy_municipality(self):
        roster = [
            {
                "name": "Confirmed Candidate",
                "ward": "Test Municipality",
                "municipality": "Test Municipality",
                "actual_ward": "Ward 07",
                "name_slug": "confirmed-candidate",
            }
        ]
        entries = [
            entry_doc("confirmed-candidate", "Confirmed Candidate", "Test Municipality", "Door to Door", "2026-09-06", "mon", "2026-09-07"),
        ]

        dashboard = self.lr.build_dashboard(entries, roster, [], now=self.now)

        self.assertEqual(dashboard["ward_performance"][0]["ward"], "Ward 7")
        self.assertEqual(dashboard["ward_performance"][0]["municipality"], "Test Municipality")
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
        roster = [{"name": "Bad Stored Value", "ward": "Test Municipality", "actual_ward": "Test Municipality", "name_slug": "bad-stored-value"}]

        dashboard = self.lr.build_dashboard([], roster, [], now=self.now)

        self.assertEqual(dashboard["ward_performance"], [])
        self.assertEqual(dashboard["ward_model"]["unassigned_candidates"], 1)

    def test_ambiguous_historical_activity_stays_unassigned(self):
        roster = [
            {"name": "Ambiguous Candidate", "ward": "Test Municipality", "name_slug": "ambiguous-candidate"},
            {"name": "Mapped Candidate", "ward": "Test Municipality", "name_slug": "mapped-candidate"},
        ]
        entries = [
            entry_doc("ambiguous-candidate", "Ambiguous Candidate", "Ward 13 and Ward 7 RMM", "Door to Door", "2026-09-06", "mon", "2026-09-07"),
            entry_doc("mapped-candidate", "Mapped Candidate", "Ward 4 Test Municipality", "Door to Door", "2026-09-06", "mon", "2026-09-07"),
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
        roster = [{"name": "Mapped Candidate", "ward": "Test Municipality", "name_slug": "mapped-candidate"}]
        entries = [
            entry_doc("mapped-candidate", "Mapped Candidate", "Ward 23 Test Municipality", "Door to Door", "2026-09-06", "mon", "2026-09-07"),
        ]
        dashboard = self.lr.build_dashboard(entries, roster, [], now=self.now)
        payload = self.lr.leadership_workbook_bytes(entries, roster, [], dashboard)

        wb = load_workbook(io.BytesIO(payload), data_only=True)
        self.assertEqual(wb["Ward Performance"]["A2"].value, "Test Municipality")
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
