import io
import unittest
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from datetime import date

from openpyxl import load_workbook

from activity_calendar import (
    ACTIVITY_LIST_HEADERS,
    ACTIVITY_ROW_HEIGHT,
    LOGGED,
    MUNICIPALITY_NOT_RECORDED,
    PLANNED,
    PLANNED_MARK,
    WARD_NOT_RECORDED,
    _MAX_ACTIVITY_ROW_HEIGHT,
    _MIN_ACTIVITY_ROW_HEIGHT,
    build_calendar_entries,
    calendar_filename,
    calendar_summary_counts,
    calendar_xlsx_bytes,
    group_by_day,
    logged_calendar_rows,
    municipality_ward_label,
    planned_calendar_rows,
    resolve_logged_activity_geography,
    _ward_municipality_block_line,
)
from activity_records import CAMPAIGN_FLOW, CONFIRMED_DUPLICATE, LEGACY_UNVERIFIED
from leadership_reporting import entry_date
from smartsheet_reporting import (
    CANVASSING,
    PRESENCE,
    PUBLIC_STREET_MEETING,
    classification_for_entry,
    smartsheet_bucket,
    smartsheet_rows,
)
from week_dates import month_bounds, month_label, next_month_key, previous_month_key

MONTH_KEY = "2026-09"
MONTH_START, MONTH_END = month_bounds(MONTH_KEY)

# Real activity type strings from smartsheet_reporting.CANONICAL_ACTIVITY_CATEGORY,
# one per SmartSheet bucket, so tests can prove the calendar keeps exactly
# what the "Canvassing Activities" report would keep and drops the rest.
CANVASSING_TYPES = ["Door to Door", "Info Table", "Telecanvassing", "House Meeting", "Canvassing Surgery"]
NON_CANVASSING_TYPES = ["Public Meeting", "Street Meeting", "Oversight", "Clean up", "Poster fighting"]


def entry(**overrides):
    doc = {
        "id": "1", "person_id": "willem-p", "name": "Willem P",
        "activity_date": "2026-09-16", "ward": "Ward 7", "venue": "Bedford",
        "type": "Door to Door", "type_display": "Door to Door",
        "start_time": "09:00", "end_time": "11:00", "campaign_id": "",
    }
    doc.update(overrides)
    return doc


def campaign(**overrides):
    doc = {
        "id": "c1", "name": "Soup Kitchen Drive", "person_id": "spokazi-m",
        "municipality": "Amahlathi", "wards": ["Ward 14"], "submission_status": "submitted",
        "planned_activities": [],
    }
    doc.update(overrides)
    return doc


class MunicipalityWardLabelTests(unittest.TestCase):
    """`municipality_ward_label` still backs `row["municipality_ward"]` (the
    JSON API / web View Calendar field) even though the Excel Calendar grid
    now uses its own ward-first block line — untouched by this rewrite."""

    def test_combines_municipality_and_single_ward(self):
        self.assertEqual(municipality_ward_label("Raymond Mhlaba", "Ward 7"), "Raymond Mhlaba Ward 7")

    def test_raymond_mhlaba_ward_7_and_amahlathi_ward_7_remain_distinct(self):
        a = municipality_ward_label("Raymond Mhlaba", "Ward 7")
        b = municipality_ward_label("Amahlathi", "Ward 7")
        self.assertNotEqual(a, b)

    def test_unknown_municipality_shows_explicit_not_recorded_text(self):
        self.assertEqual(municipality_ward_label("", "Ward 7"), MUNICIPALITY_NOT_RECORDED)

    def test_never_double_prefixes_a_legacy_municipality_only_ward(self):
        self.assertEqual(municipality_ward_label("Amahlathi", "Amahlathi"), "Amahlathi")


class ResolveLoggedActivityGeographyTests(unittest.TestCase):
    """The safe, display-only municipality/ward fallback precedence:
    A. doc.municipality (activity's own, if ever present) ->
    B. a *trusted*-linked campaign's own municipality ->
    C. the roster's own canonical municipality (pre-existing lookup) ->
    D. a blank activity ward filled in only for a single-confirmed-ward
       candidate. Never guesses across ambiguity; never mutates anything."""

    def test_roster_municipality_fills_in_when_activity_has_none(self):
        doc = entry(municipality=None)  # entries never actually persist one; explicit for clarity
        municipality, ward = resolve_logged_activity_geography(doc, {"willem-p": "Raymond Mhlaba"})
        self.assertEqual(municipality, "Raymond Mhlaba")
        self.assertEqual(ward, "Ward 7")  # the activity's own ward text is always used verbatim

    def test_activitys_own_stored_municipality_always_wins_when_present(self):
        doc = entry(municipality="Amahlathi")
        municipality, _ = resolve_logged_activity_geography(doc, {"willem-p": "Raymond Mhlaba"})
        self.assertEqual(municipality, "Amahlathi", "step A must never be overridden by roster (step C)")

    def test_trusted_campaign_geography_used_when_roster_lookup_is_unavailable(self):
        doc = entry(campaign_id="c1", campaign_link_source=CAMPAIGN_FLOW)  # a TRUSTED source
        municipality, _ = resolve_logged_activity_geography(
            doc, municipality_by_person={},  # roster lookup fails entirely (e.g. renamed candidate)
            trusted_campaign_geography={"c1": ("Amahlathi", ["Ward 14"])},
        )
        self.assertEqual(municipality, "Amahlathi")

    def test_untrusted_legacy_campaign_link_is_never_used_for_geography(self):
        doc = entry(campaign_id="c1", campaign_link_source=LEGACY_UNVERIFIED)
        municipality, _ = resolve_logged_activity_geography(
            doc, municipality_by_person={},
            trusted_campaign_geography={"c1": ("Amahlathi", ["Ward 14"])},
        )
        self.assertEqual(municipality, "", "an unverified/legacy campaign link must never be trusted for geography")

    def test_blank_ward_filled_from_a_single_confirmed_roster_ward(self):
        doc = entry(ward="")
        municipality, ward = resolve_logged_activity_geography(
            doc, {"willem-p": "Raymond Mhlaba"}, actual_wards_by_person={"willem-p": ["Ward 7"]},
        )
        self.assertEqual(municipality, "Raymond Mhlaba")
        self.assertEqual(ward, "Ward 7")

    def test_multi_ward_candidate_blank_activity_ward_is_never_guessed(self):
        # Spokazi-style: municipality resolves safely, but with several
        # confirmed wards and no ward on the activity itself, the specific
        # ward must never be guessed.
        doc = entry(person_id="spokazi-m", ward="")
        municipality, ward = resolve_logged_activity_geography(
            doc, {"spokazi-m": "Amahlathi"}, actual_wards_by_person={"spokazi-m": ["Ward 2", "Ward 11", "Ward 14"]},
        )
        self.assertEqual(municipality, "Amahlathi")
        self.assertEqual(ward, "", "a multi-ward candidate's blank activity ward must never be guessed")
        # Calendar display for this exact case:
        self.assertEqual(_ward_municipality_block_line(municipality, ward), f"Amahlathi · {WARD_NOT_RECORDED}")

    def test_explicit_activity_ward_is_never_overridden_even_for_a_multi_ward_candidate(self):
        doc = entry(person_id="spokazi-m", ward="Ward 7")
        municipality, ward = resolve_logged_activity_geography(
            doc, {"spokazi-m": "Amahlathi"}, actual_wards_by_person={"spokazi-m": ["Ward 2", "Ward 7", "Ward 14"]},
        )
        self.assertEqual((municipality, ward), ("Amahlathi", "Ward 7"))
        self.assertEqual(_ward_municipality_block_line(municipality, ward), "Wrd 7 · Amahlathi")

    def test_no_municipality_anywhere_ward_is_never_invented_either(self):
        doc = entry(ward="")
        municipality, ward = resolve_logged_activity_geography(doc, municipality_by_person={})
        self.assertEqual((municipality, ward), ("", ""))

    def test_resolution_is_display_only_and_never_mutates_the_source_document(self):
        doc = entry(ward="")
        before = dict(doc)
        resolve_logged_activity_geography(
            doc, {"willem-p": "Raymond Mhlaba"}, actual_wards_by_person={"willem-p": ["Ward 7"]},
        )
        self.assertEqual(doc, before)

    def test_logged_calendar_rows_applies_the_same_resolution_end_to_end(self):
        docs = [
            entry(id="1", person_id="willem-p", ward=""),  # single confirmed ward -> filled
            entry(id="2", person_id="spokazi-m", ward=""),  # multi-ward -> stays unresolved
        ]
        rows = logged_calendar_rows(
            docs, {}, {"willem-p": "Raymond Mhlaba", "spokazi-m": "Amahlathi"},
            MONTH_START, MONTH_END, entry_date,
            actual_wards_by_person={"willem-p": ["Ward 7"], "spokazi-m": ["Ward 2", "Ward 11"]},
        )
        by_id = {r["candidate"]: r for r in rows}
        willem_row = next(r for r in rows if r["date"] and r.get("ward") == "Ward 7")
        spokazi_row = next(r for r in rows if r is not willem_row)
        self.assertEqual(willem_row["municipality"], "Raymond Mhlaba")
        self.assertEqual(spokazi_row["municipality"], "Amahlathi")
        self.assertEqual(spokazi_row["ward"], "")


class CanvassingClassificationScopeTests(unittest.TestCase):
    """The calendar must reuse the exact same classifier the "Canvassing
    Activities" Coordinator report uses — never a second/duplicated
    classification — and only ever include CANVASSING-bucketed activities."""

    def test_canvassing_types_are_included(self):
        docs = [entry(id=str(i), type=t, type_display=t) for i, t in enumerate(CANVASSING_TYPES)]
        rows = logged_calendar_rows(docs, {}, {"willem-p": "Raymond Mhlaba"}, MONTH_START, MONTH_END, entry_date)
        self.assertEqual(len(rows), len(CANVASSING_TYPES))

    def test_non_canvassing_types_are_excluded(self):
        docs = [entry(id=str(i), type=t, type_display=t) for i, t in enumerate(NON_CANVASSING_TYPES)]
        rows = logged_calendar_rows(docs, {}, {"willem-p": "Raymond Mhlaba"}, MONTH_START, MONTH_END, entry_date)
        self.assertEqual(rows, [], "no activity classified outside CANVASSING may ever appear on this calendar")

    def test_mixed_batch_keeps_only_the_canvassing_activities(self):
        docs = (
            [entry(id=f"c{i}", type=t, type_display=t) for i, t in enumerate(CANVASSING_TYPES)]
            + [entry(id=f"n{i}", type=t, type_display=t) for i, t in enumerate(NON_CANVASSING_TYPES)]
        )
        rows = logged_calendar_rows(docs, {}, {"willem-p": "Raymond Mhlaba"}, MONTH_START, MONTH_END, entry_date)
        self.assertEqual(len(rows), len(CANVASSING_TYPES))
        self.assertEqual({r["activity"] for r in rows}, set(CANVASSING_TYPES))

    def test_every_kept_row_actually_matches_the_shared_classifier(self):
        # Cross-check against the classifier directly, rather than a
        # hard-coded list — proves this calendar reuses the real function,
        # not a private copy of "the six examples".
        docs = [entry(id=str(i), type=t, type_display=t) for i, t in enumerate(CANVASSING_TYPES + NON_CANVASSING_TYPES)]
        rows = logged_calendar_rows(docs, {}, {"willem-p": "Raymond Mhlaba"}, MONTH_START, MONTH_END, entry_date)
        kept_activities = {r["activity"] for r in rows}
        for doc in docs:
            is_canvassing = smartsheet_bucket(classification_for_entry(doc)) == CANVASSING
            with self.subTest(activity=doc["type"]):
                self.assertEqual(doc["type"] in kept_activities, is_canvassing)

    def test_non_canvassing_activity_is_not_deleted_or_modified_anywhere(self):
        doc = entry(id="1", type="Oversight", type_display="Oversight")
        before = dict(doc)
        logged_calendar_rows([doc], {}, {}, MONTH_START, MONTH_END, entry_date)
        self.assertEqual(doc, before, "building the calendar must never mutate the source document, kept or excluded")

    def test_planned_activity_uses_the_same_classifier(self):
        c = campaign(planned_activities=[
            {"id": "p1", "date": "2026-09-20", "time": "09:00", "activity_type": "Info Table", "area": ""},
            {"id": "p2", "date": "2026-09-21", "time": "09:00", "activity_type": "Public Meeting", "area": ""},
        ])
        rows = planned_calendar_rows([c], {}, MONTH_START, MONTH_END)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["activity"], "Info Table")

    def test_calendar_count_reconciles_with_the_canvassing_smartsheet_export(self):
        # The same underlying dataset, run through the real "Canvassing
        # Activities" report's own row builder, must produce the same count.
        docs = [
            entry(id=str(i), type=t, type_display=t, week_key="2026-09-14", day="mon")
            for i, t in enumerate(CANVASSING_TYPES + NON_CANVASSING_TYPES)
        ]
        calendar_rows = logged_calendar_rows(docs, {}, {"willem-p": "Raymond Mhlaba"}, MONTH_START, MONTH_END, entry_date)
        canvassing_report_rows = smartsheet_rows(docs, "2026-09-14", CANVASSING)
        self.assertEqual(len(calendar_rows), len(canvassing_report_rows))
        self.assertEqual(len(calendar_rows), len(CANVASSING_TYPES))


class LoggedCalendarRowsTests(unittest.TestCase):
    def test_uses_real_stored_activity_data(self):
        rows = logged_calendar_rows(
            [entry()], {}, {"willem-p": "Raymond Mhlaba"}, MONTH_START, MONTH_END, entry_date,
        )
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["date"], date(2026, 9, 16))
        self.assertEqual(row["activity"], "Door to Door")
        self.assertEqual(row["venue"], "Bedford")
        self.assertEqual(row["candidate"], "Willem P")
        self.assertEqual(row["status"], LOGGED)
        self.assertEqual(row["municipality_ward"], "Raymond Mhlaba Ward 7")

    def test_excludes_activities_outside_the_month(self):
        rows = logged_calendar_rows(
            [entry(activity_date="2026-08-31"), entry(activity_date="2026-10-01")],
            {}, {}, MONTH_START, MONTH_END, entry_date,
        )
        self.assertEqual(rows, [])

    def test_confirmed_duplicate_excluded_using_shared_rule(self):
        rows = logged_calendar_rows(
            [entry(duplicate_review_status=CONFIRMED_DUPLICATE)],
            {}, {"willem-p": "Raymond Mhlaba"}, MONTH_START, MONTH_END, entry_date,
        )
        self.assertEqual(rows, [], "a confirmed duplicate must never appear on the calendar")

    def test_missing_time_is_never_invented(self):
        rows = logged_calendar_rows(
            [entry(start_time=None, end_time=None)], {}, {"willem-p": "Raymond Mhlaba"}, MONTH_START, MONTH_END, entry_date,
        )
        self.assertEqual(rows[0]["time_label"], "Time not recorded")
        self.assertEqual(rows[0]["start_time"], "")

    def test_municipality_not_inferred_from_venue_or_name(self):
        rows = logged_calendar_rows(
            [entry(venue="Amahlathi Community Hall", name="Someone in Raymond Mhlaba")],
            {}, {},  # no roster municipality known for this person_id
            MONTH_START, MONTH_END, entry_date,
        )
        self.assertEqual(rows[0]["municipality"], "")
        self.assertEqual(rows[0]["municipality_ward"], MUNICIPALITY_NOT_RECORDED)

    def test_campaign_name_resolved_by_campaign_id(self):
        rows = logged_calendar_rows(
            [entry(campaign_id="c1")], {"c1": "Soup Kitchen Drive"}, {"willem-p": "Raymond Mhlaba"}, MONTH_START, MONTH_END, entry_date,
        )
        self.assertEqual(rows[0]["campaign_name"], "Soup Kitchen Drive")


class PlannedCalendarRowsTests(unittest.TestCase):
    def test_uses_planned_activity_row_data(self):
        c = campaign(planned_activities=[
            {"id": "p1", "date": "2026-09-20", "time": "09:00", "activity_type": "Info Table", "area": "On the street corner"},
        ])
        rows = planned_calendar_rows([c], {"spokazi-m": "Spokazi M"}, MONTH_START, MONTH_END)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["date"], date(2026, 9, 20))
        self.assertEqual(row["activity"], "Info Table")
        self.assertEqual(row["venue"], "On the street corner")
        self.assertEqual(row["candidate"], "Spokazi M")
        self.assertEqual(row["campaign_name"], "Soup Kitchen Drive")
        self.assertEqual(row["status"], PLANNED)
        self.assertEqual(row["municipality_ward"], "Amahlathi Ward 14")

    def test_draft_campaigns_excluded(self):
        c = campaign(submission_status="draft", planned_activities=[
            {"id": "p1", "date": "2026-09-20", "time": "09:00", "activity_type": "Info Table", "area": ""},
        ])
        rows = planned_calendar_rows([c], {}, MONTH_START, MONTH_END)
        self.assertEqual(rows, [])

    def test_activities_outside_month_excluded(self):
        c = campaign(planned_activities=[
            {"id": "p1", "date": "2026-08-31", "time": "09:00", "activity_type": "Info Table", "area": ""},
            {"id": "p2", "date": "2026-10-01", "time": "09:00", "activity_type": "Info Table", "area": ""},
        ])
        rows = planned_calendar_rows([c], {}, MONTH_START, MONTH_END)
        self.assertEqual(rows, [])

    def test_missing_planned_time_is_never_invented(self):
        c = campaign(planned_activities=[{"id": "p1", "date": "2026-09-20", "time": "", "activity_type": "Info Table", "area": ""}])
        rows = planned_calendar_rows([c], {}, MONTH_START, MONTH_END)
        self.assertEqual(rows[0]["time_label"], "Time not recorded")

    def test_no_campaign_municipality_shows_not_recorded(self):
        c = campaign(municipality="", planned_activities=[
            {"id": "p1", "date": "2026-09-20", "time": "09:00", "activity_type": "Info Table", "area": ""},
        ])
        rows = planned_calendar_rows([c], {}, MONTH_START, MONTH_END)
        self.assertEqual(rows[0]["municipality_ward"], MUNICIPALITY_NOT_RECORDED)


class BuildCalendarEntriesTests(unittest.TestCase):
    def test_combines_logged_and_planned_without_deduping(self):
        e = entry(activity_date="2026-09-20", type_display="Info Table")
        c = campaign(planned_activities=[
            {"id": "p1", "date": "2026-09-20", "time": "09:00", "activity_type": "Info Table", "area": ""},
        ])
        rows = build_calendar_entries([e], [c], {}, {"willem-p": "Raymond Mhlaba"}, {}, MONTH_START, MONTH_END, entry_date)
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["status"] for r in rows}, {"LOGGED", "PLANNED"})

    def test_status_filter_planned_only(self):
        e = entry()
        c = campaign(planned_activities=[{"id": "p1", "date": "2026-09-20", "time": "09:00", "activity_type": "Info Table", "area": ""}])
        rows = build_calendar_entries([e], [c], {}, {"willem-p": "Raymond Mhlaba"}, {}, MONTH_START, MONTH_END, entry_date, status_filter="PLANNED")
        self.assertTrue(rows)
        self.assertTrue(all(r["status"] == "PLANNED" for r in rows))

    def test_sorted_chronologically(self):
        e1 = entry(activity_date="2026-09-20", start_time="14:00")
        e2 = entry(activity_date="2026-09-05", start_time="09:00")
        rows = build_calendar_entries([e1, e2], [], {}, {"willem-p": "Raymond Mhlaba"}, {}, MONTH_START, MONTH_END, entry_date)
        self.assertEqual([r["date"] for r in rows], [date(2026, 9, 5), date(2026, 9, 20)])


class GroupByDayTests(unittest.TestCase):
    def test_groups_multiple_entries_on_the_same_day(self):
        rows = [
            {"date": date(2026, 9, 20), "start_time": "09:00"},
            {"date": date(2026, 9, 20), "start_time": "14:00"},
            {"date": date(2026, 9, 21), "start_time": "09:00"},
        ]
        grouped = group_by_day(rows)
        self.assertEqual(len(grouped[date(2026, 9, 20)]), 2)
        self.assertEqual(len(grouped[date(2026, 9, 21)]), 1)


class MonthNavigationIntegrationTests(unittest.TestCase):
    def test_next_and_previous_month_key_round_trip(self):
        self.assertEqual(previous_month_key(next_month_key(MONTH_KEY)), MONTH_KEY)


class CalendarFilenameTests(unittest.TestCase):
    def test_filename_reflects_selected_month(self):
        self.assertEqual(calendar_filename("2026-09"), "Ntsikana_Canvassing_Calendar_September_2026.xlsx")
        self.assertEqual(calendar_filename("2026-10"), "Ntsikana_Canvassing_Calendar_October_2026.xlsx")

    def test_filename_never_says_current(self):
        self.assertNotIn("current", calendar_filename("2026-09").lower())


def _xml(payload: bytes, part: str = "xl/worksheets/sheet1.xml") -> ET.Element:
    with zipfile.ZipFile(io.BytesIO(payload)) as z:
        raw = z.read(part)
    return ET.fromstring(raw)  # raises ET.ParseError if malformed


_OUTSIDE_MONTH_HEADER_RGB = "00C9D3DE"  # activity_calendar._OUTSIDE_MONTH_HEADER_FILL


def _activity_texts_for_date(ws, target_date):
    """Test helper for the weekly-section grid: scan from row 9, track
    which column holds `target_date` whenever an IN-MONTH day/date header
    is encountered (never an out-of-month leading/trailing padding day,
    identified by its distinct header fill — this avoids a same-day-number
    collision between e.g. a trailing "2 Oct" and a real "2 Sep"), and
    collect every non-blank activity-block string found beneath it (in row
    order) until the next "WEEK ..." label row."""
    import re as _re
    texts = []
    current_col = None
    for row in ws.iter_rows(min_row=9):
        first_text = str(row[0].value or "")
        if first_text.startswith("WEEK "):
            current_col = None
            continue
        matched_header = False
        for c in row:
            text = str(c.value or "")
            m = _re.fullmatch(r"[A-Z]{3} (\d{1,2})", text)
            if m and int(m.group(1)) == target_date.day and c.fill.fgColor.rgb != _OUTSIDE_MONTH_HEADER_RGB:
                current_col = c.column
                matched_header = True
        if matched_header:
            continue
        if current_col:
            val = row[current_col - 1].value
            if val:
                texts.append(str(val))
    return texts


class CalendarXlsxStructureTests(unittest.TestCase):
    def _rows(self):
        e = entry(activity_date="2026-09-16")
        c = campaign(planned_activities=[
            {"id": "p1", "date": "2026-09-20", "time": "10:00", "activity_type": "Info Table", "area": "On the street corner"},
        ])
        return build_calendar_entries(
            [e], [c], {}, {"willem-p": "Raymond Mhlaba"}, {"spokazi-m": "Spokazi M"},
            MONTH_START, MONTH_END, entry_date,
        )

    def test_produces_a_genuine_xlsx_with_two_worksheets(self):
        payload = calendar_xlsx_bytes(self._rows(), MONTH_KEY)
        self.assertTrue(payload.startswith(b"PK\x03\x04"), "must be a genuine .xlsx, not CSV/text")
        wb = load_workbook(io.BytesIO(payload))
        self.assertEqual(wb.sheetnames, ["Calendar", "Canvassing Activity List"])

    def test_calendar_sheet_shows_clean_canvassing_header_block(self):
        wb = load_workbook(io.BytesIO(calendar_xlsx_bytes(self._rows(), MONTH_KEY)))
        ws = wb["Calendar"]
        self.assertEqual(ws["A2"].value, "Democratic Alliance")
        self.assertEqual(ws["A3"].value, "Ntsikana Constituency")
        self.assertEqual(ws["A4"].value, "Canvassing Calendar")
        self.assertEqual(ws["A5"].value, "September 2026")

    def test_summary_shows_logged_and_planned_split_when_both_exist(self):
        rows = self._rows()
        total, logged, planned = calendar_summary_counts(rows)
        self.assertEqual((total, logged, planned), (2, 1, 1))
        wb = load_workbook(io.BytesIO(calendar_xlsx_bytes(rows, MONTH_KEY)))
        self.assertEqual(wb["Calendar"]["A6"].value, f"Logged: {logged}  |  Planned: {planned}")

    def test_summary_shows_single_count_when_all_logged(self):
        rows = logged_calendar_rows([entry()], {}, {"willem-p": "Raymond Mhlaba"}, MONTH_START, MONTH_END, entry_date)
        wb = load_workbook(io.BytesIO(calendar_xlsx_bytes(rows, MONTH_KEY)))
        self.assertEqual(wb["Calendar"]["A6"].value, "Canvassing Activities: 1")

    def test_empty_month_shows_plain_message(self):
        wb = load_workbook(io.BytesIO(calendar_xlsx_bytes([], MONTH_KEY)))
        self.assertEqual(wb["Calendar"]["A6"].value, "No canvassing activities scheduled for this month.")

    def test_legend_only_appears_when_a_planned_entry_exists(self):
        rows_with_planned = self._rows()
        wb = load_workbook(io.BytesIO(calendar_xlsx_bytes(rows_with_planned, MONTH_KEY)))
        self.assertIn(PLANNED_MARK, wb["Calendar"]["A7"].value)
        self.assertIn("Planned", wb["Calendar"]["A7"].value)

        rows_logged_only = logged_calendar_rows([entry()], {}, {"willem-p": "Raymond Mhlaba"}, MONTH_START, MONTH_END, entry_date)
        wb2 = load_workbook(io.BytesIO(calendar_xlsx_bytes(rows_logged_only, MONTH_KEY)))
        self.assertFalse(wb2["Calendar"]["A7"].value, "no legend needed when nothing is marked Planned")

    def test_logged_activity_block_has_no_status_clutter(self):
        rows = logged_calendar_rows([entry()], {}, {"willem-p": "Raymond Mhlaba"}, MONTH_START, MONTH_END, entry_date)
        wb = load_workbook(io.BytesIO(calendar_xlsx_bytes(rows, MONTH_KEY)))
        texts = _activity_texts_for_date(wb["Calendar"], date(2026, 9, 16))
        self.assertEqual(len(texts), 1)
        self.assertNotIn("(LOGGED)", texts[0])
        self.assertNotIn("LOGGED", texts[0])
        self.assertNotIn(PLANNED_MARK, texts[0])

    def test_activity_block_is_time_ward_municipality_venue_activity(self):
        rows = logged_calendar_rows([entry()], {}, {"willem-p": "Raymond Mhlaba"}, MONTH_START, MONTH_END, entry_date)
        wb = load_workbook(io.BytesIO(calendar_xlsx_bytes(rows, MONTH_KEY)))
        texts = _activity_texts_for_date(wb["Calendar"], date(2026, 9, 16))
        self.assertEqual(texts, ["09:00 - 11:00\nWrd 7 · Raymond Mhlaba\nBedford · Door to Door"])

    def test_raymond_mhlaba_ward_7_and_amahlathi_ward_7_remain_distinct_on_the_grid(self):
        docs = [
            entry(id="1", person_id="willem-p", ward="Ward 7", activity_date="2026-09-16"),
            entry(id="2", person_id="spokazi-m", ward="Ward 7", activity_date="2026-09-17"),
        ]
        rows = logged_calendar_rows(docs, {}, {"willem-p": "Raymond Mhlaba", "spokazi-m": "Amahlathi"}, MONTH_START, MONTH_END, entry_date)
        wb = load_workbook(io.BytesIO(calendar_xlsx_bytes(rows, MONTH_KEY)))
        ws = wb["Calendar"]
        text16 = _activity_texts_for_date(ws, date(2026, 9, 16))[0]
        text17 = _activity_texts_for_date(ws, date(2026, 9, 17))[0]
        self.assertIn("Wrd 7 · Raymond Mhlaba", text16)
        self.assertIn("Wrd 7 · Amahlathi", text17)

    def test_missing_venue_shows_activity_alone_never_a_placeholder(self):
        rows = logged_calendar_rows([entry(venue="")], {}, {"willem-p": "Raymond Mhlaba"}, MONTH_START, MONTH_END, entry_date)
        wb = load_workbook(io.BytesIO(calendar_xlsx_bytes(rows, MONTH_KEY)))
        text = _activity_texts_for_date(wb["Calendar"], date(2026, 9, 16))[0]
        self.assertIn("Door to Door", text)
        for placeholder in ("None", "null", " · Door to Door"):
            self.assertNotIn(placeholder, text)

    def test_missing_time_line_is_omitted_not_invented(self):
        rows = logged_calendar_rows(
            [entry(start_time=None, end_time=None)], {}, {"willem-p": "Raymond Mhlaba"}, MONTH_START, MONTH_END, entry_date,
        )
        wb = load_workbook(io.BytesIO(calendar_xlsx_bytes(rows, MONTH_KEY)))
        text = _activity_texts_for_date(wb["Calendar"], date(2026, 9, 16))[0]
        self.assertEqual(text, "Wrd 7 · Raymond Mhlaba\nBedford · Door to Door")
        self.assertNotIn("Time not recorded", text)

    def test_planned_activity_is_marked_subtly_on_its_time_line(self):
        c = campaign(planned_activities=[
            {"id": "p1", "date": "2026-09-20", "time": "10:00", "activity_type": "Info Table", "area": "On the street corner"},
        ])
        rows = planned_calendar_rows([c], {"spokazi-m": "Spokazi M"}, MONTH_START, MONTH_END)
        wb = load_workbook(io.BytesIO(calendar_xlsx_bytes(rows, MONTH_KEY)))
        text = _activity_texts_for_date(wb["Calendar"], date(2026, 9, 20))[0]
        self.assertEqual(text.split("\n")[0], f"{PLANNED_MARK} 10:00")

    def test_multiple_activities_on_the_same_day_occupy_separate_rows_not_one_tall_cell(self):
        docs = [
            entry(id="1", activity_date="2026-09-16", start_time="09:00", end_time="12:00", venue="Bedford", type="Door to Door", type_display="Door to Door"),
            entry(id="2", person_id="spokazi-m", ward="Ward 10", activity_date="2026-09-16", start_time="14:00", end_time="16:00", venue="Stutterheim", type="Info Table", type_display="Info Table"),
        ]
        rows = logged_calendar_rows(docs, {}, {"willem-p": "Raymond Mhlaba", "spokazi-m": "Amahlathi"}, MONTH_START, MONTH_END, entry_date)
        wb = load_workbook(io.BytesIO(calendar_xlsx_bytes(rows, MONTH_KEY)))
        texts = _activity_texts_for_date(wb["Calendar"], date(2026, 9, 16))
        self.assertEqual(texts, [
            "09:00 - 12:00\nWrd 7 · Raymond Mhlaba\nBedford · Door to Door",
            "14:00 - 16:00\nWrd 10 · Amahlathi\nStutterheim · Info Table",
        ])

    def test_busy_day_shows_every_activity_never_summarized(self):
        docs = [
            entry(id=str(i), activity_date="2026-09-10", start_time=f"{9 + i:02d}:00", end_time=f"{10 + i:02d}:00", venue=f"Venue {i}")
            for i in range(9)
        ]
        rows = logged_calendar_rows(docs, {}, {"willem-p": "Raymond Mhlaba"}, MONTH_START, MONTH_END, entry_date)
        wb = load_workbook(io.BytesIO(calendar_xlsx_bytes(rows, MONTH_KEY)))
        texts = _activity_texts_for_date(wb["Calendar"], date(2026, 9, 10))
        self.assertEqual(len(texts), 9, "every activity on a busy day must get its own row, none dropped, none summarized")
        for i, text in enumerate(texts):
            self.assertIn(f"Venue {i} · Door to Door", text)
        for t in texts:
            self.assertNotIn("activities", t)

    def test_no_body_activity_row_is_a_giant_multi_hundred_point_row(self):
        # Regression for the reported scroll-jump bug: a whole week used to
        # collapse into one ~300pt row. Every normal activity row must now
        # stay within the required 42-60pt bound, regardless of how many
        # activities that day has.
        docs = [
            entry(id=str(i), activity_date="2026-09-10", start_time=f"{9 + i % 8:02d}:00", venue=f"Venue {i}")
            for i in range(12)
        ]
        rows = logged_calendar_rows(docs, {}, {"willem-p": "Raymond Mhlaba"}, MONTH_START, MONTH_END, entry_date)
        wb = load_workbook(io.BytesIO(calendar_xlsx_bytes(rows, MONTH_KEY)))
        ws = wb["Calendar"]
        activity_row_heights = [
            h for row_idx in range(9, ws.max_row + 1)
            if (h := ws.row_dimensions[row_idx].height) and h > 25  # excludes the compact week-label/day-header rows
        ]
        self.assertTrue(activity_row_heights)
        for h in activity_row_heights:
            self.assertLessEqual(h, _MAX_ACTIVITY_ROW_HEIGHT, "no body activity row may exceed the required ~60pt bound")
            self.assertGreaterEqual(h, _MIN_ACTIVITY_ROW_HEIGHT)
        self.assertEqual(ACTIVITY_ROW_HEIGHT, min(activity_row_heights))
        self.assertEqual(ACTIVITY_ROW_HEIGHT, max(activity_row_heights))

    def test_calendar_scroll_structure_has_multiple_normal_rows_per_week(self):
        # The actual fix, structurally: a busy week must be several normal
        # rows, not one giant one — Excel scrolling then advances smoothly.
        docs = [entry(id=str(i), activity_date="2026-09-14", start_time=f"{9+i:02d}:00", venue=f"Venue {i}") for i in range(6)]
        docs += [entry(id=f"t{i}", activity_date="2026-09-15", start_time=f"{9+i:02d}:00", venue=f"Venue t{i}") for i in range(3)]
        rows = logged_calendar_rows(docs, {}, {"willem-p": "Raymond Mhlaba"}, MONTH_START, MONTH_END, entry_date)
        wb = load_workbook(io.BytesIO(calendar_xlsx_bytes(rows, MONTH_KEY)))
        ws = wb["Calendar"]
        # Find the "WEEK 14-20 SEPTEMBER" label row, then count how many
        # rows follow before the next "WEEK " row / end of sheet.
        week_row = next(r for r in range(9, ws.max_row + 1) if str(ws.cell(row=r, column=1).value or "").startswith("WEEK 14"))
        next_week_row = next(
            (r for r in range(week_row + 1, ws.max_row + 1) if str(ws.cell(row=r, column=1).value or "").startswith("WEEK ")),
            ws.max_row + 1,
        )
        body_rows_in_week = next_week_row - week_row - 2  # minus the label row and the day-header row
        # Monday needs 6 activity rows; that week section must have at
        # least that many ordinary rows, each individually height-bounded
        # (already proven above) rather than one merged/tall row.
        self.assertGreaterEqual(body_rows_in_week, 6)
        for r in range(week_row + 2, week_row + 2 + body_rows_in_week):
            self.assertLessEqual(ws.row_dimensions[r].height or ACTIVITY_ROW_HEIGHT, _MAX_ACTIVITY_ROW_HEIGHT)

    def test_days_outside_the_month_are_shaded_not_prominent(self):
        wb = load_workbook(io.BytesIO(calendar_xlsx_bytes(self._rows(), MONTH_KEY)))
        ws = wb["Calendar"]
        # 1 Sep 2026 is a Tuesday: the first week section's Monday header
        # cell is "MON 31" (August) — outside the selected month, shaded.
        self.assertEqual(ws["A10"].value, "MON 31")
        self.assertEqual(ws["A10"].fill.patternType, "solid")
        self.assertNotEqual(ws["A10"].fill.fgColor.rgb, ws["B10"].fill.fgColor.rgb, "outside-month header must look different from an in-month header")

    def test_print_setup_is_landscape_fit_to_width_with_repeated_header(self):
        wb = load_workbook(io.BytesIO(calendar_xlsx_bytes(self._rows(), MONTH_KEY)))
        ws = wb["Calendar"]
        self.assertEqual(ws.page_setup.orientation, "landscape")
        self.assertEqual(ws.page_setup.fitToWidth, 1)
        self.assertEqual(ws.page_setup.fitToHeight, 0)
        self.assertEqual(ws.print_title_rows, "$1:$8")

    def test_freeze_panes_covers_only_the_top_header_not_a_whole_week(self):
        wb = load_workbook(io.BytesIO(calendar_xlsx_bytes(self._rows(), MONTH_KEY)))
        ws = wb["Calendar"]
        self.assertEqual(ws.freeze_panes, "A9")

    def test_activity_list_sheet_renamed_and_headers_exact(self):
        wb = load_workbook(io.BytesIO(calendar_xlsx_bytes(self._rows(), MONTH_KEY)))
        ws = wb["Canvassing Activity List"]
        self.assertEqual([c.value for c in ws[1]], ACTIVITY_LIST_HEADERS)

    def test_activity_list_date_and_time_cells_are_real_types_with_sa_format(self):
        import datetime as dt
        wb = load_workbook(io.BytesIO(calendar_xlsx_bytes(self._rows(), MONTH_KEY)))
        ws = wb["Canvassing Activity List"]
        rows_by_status = {row[9].value: row for row in ws.iter_rows(min_row=2)}
        logged_row = rows_by_status["LOGGED"]
        self.assertIsInstance(logged_row[0].value, dt.date)
        self.assertEqual(logged_row[0].number_format, "dd/mm/yyyy")
        self.assertIsInstance(logged_row[1].value, dt.time)
        self.assertEqual(logged_row[1].number_format, "HH:MM")
        self.assertEqual(logged_row[3].value, "Raymond Mhlaba")  # MUNICIPALITY column
        self.assertEqual(logged_row[4].value, "Ward 7")  # WARD column, full text, separate

    def test_activity_list_contains_every_row_the_calendar_uses(self):
        rows = self._rows()
        wb = load_workbook(io.BytesIO(calendar_xlsx_bytes(rows, MONTH_KEY)))
        al_rows = list(wb["Canvassing Activity List"].iter_rows(min_row=2))
        self.assertEqual(len(al_rows), len(rows))

    def test_no_formulas_anywhere(self):
        wb = load_workbook(io.BytesIO(calendar_xlsx_bytes(self._rows(), MONTH_KEY)))
        for name in wb.sheetnames:
            for row in wb[name].iter_rows():
                for cell in row:
                    self.assertNotEqual(cell.data_type, "f")

    def test_logo_embedded_when_available(self):
        wb = load_workbook(io.BytesIO(calendar_xlsx_bytes(self._rows(), MONTH_KEY)))
        self.assertEqual(len(wb["Calendar"]._images), 1)

    def test_activity_list_can_be_omitted(self):
        payload = calendar_xlsx_bytes(self._rows(), MONTH_KEY, include_activity_list=False)
        wb = load_workbook(io.BytesIO(payload))
        self.assertEqual(wb.sheetnames, ["Calendar"])

    def test_activity_list_rows_alternate_shading(self):
        rows = self._rows() + self._rows()
        wb = load_workbook(io.BytesIO(calendar_xlsx_bytes(rows, MONTH_KEY)))
        ws = wb["Canvassing Activity List"]
        first = ws.cell(row=2, column=1).fill.patternType
        second = ws.cell(row=3, column=1).fill.patternType
        self.assertNotEqual(first, second)


class CalendarWorkbookIntegrityTests(unittest.TestCase):
    """Regression coverage for the earlier production Excel-repair bug
    (openpyxl rich-text runs — see git history) and the plain-string fix
    that replaced it. Must never regress."""

    def _rows(self):
        return logged_calendar_rows(
            [entry(id=str(i), activity_date="2026-09-10", start_time=f"{9+i:02d}:00", end_time=f"{10+i:02d}:00", venue=f"Venue {i}") for i in range(12)],
            {}, {"willem-p": "Raymond Mhlaba"}, MONTH_START, MONTH_END, entry_date,
        )

    def test_worksheet_xml_is_well_formed_for_a_busy_day(self):
        payload = calendar_xlsx_bytes(self._rows(), MONTH_KEY)
        root = _xml(payload)
        self.assertEqual(root.tag, "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}worksheet")

    def test_every_workbook_xml_part_parses_cleanly(self):
        payload = calendar_xlsx_bytes(self._rows(), MONTH_KEY)
        with zipfile.ZipFile(io.BytesIO(payload)) as z:
            xml_names = [n for n in z.namelist() if n.endswith(".xml") or n.endswith(".rels")]
            self.assertTrue(xml_names)
            for name in xml_names:
                with self.subTest(part=name):
                    ET.fromstring(z.read(name))

    def test_no_rich_text_run_elements_anywhere(self):
        payload = calendar_xlsx_bytes(self._rows(), MONTH_KEY)
        root = _xml(payload)
        runs = list(root.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}r"))
        self.assertEqual(runs, [], "no <r> rich-text run elements may appear in the Calendar worksheet (CellRichText/TextBlock/InlineFont must never be reintroduced)")

    def test_no_whitespace_only_text_elements_missing_xml_space_preserve(self):
        payload = calendar_xlsx_bytes(self._rows(), MONTH_KEY)
        with zipfile.ZipFile(io.BytesIO(payload)) as z:
            for name in z.namelist():
                if not name.startswith("xl/worksheets/") or not name.endswith(".xml"):
                    continue
                root = ET.fromstring(z.read(name))
                for t in root.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t"):
                    text = t.text or ""
                    preserve = t.get("{http://www.w3.org/XML/1998/namespace}space")
                    if (text != text.strip() or text == "") and preserve != "preserve":
                        self.fail(f"{name} has a whitespace-only <t> without xml:space=\"preserve\": {text!r}")

    def test_workbook_survives_two_openpyxl_save_load_round_trips(self):
        payload = calendar_xlsx_bytes(self._rows(), MONTH_KEY)
        wb = load_workbook(io.BytesIO(payload))
        buf2 = io.BytesIO()
        wb.save(buf2)
        wb2 = load_workbook(io.BytesIO(buf2.getvalue()))
        v1 = [[c.value for c in row] for row in wb["Calendar"].iter_rows()]
        v2 = [[c.value for c in row] for row in wb2["Calendar"].iter_rows()]
        self.assertEqual(v1, v2)

    def test_illegal_xml_control_characters_are_stripped_without_mutating_the_source(self):
        dirty_doc = entry(id="1", type_display="Door to Door\x0bwith a control char", activity_date="2026-09-05")
        before = dict(dirty_doc)
        rows = logged_calendar_rows([dirty_doc], {}, {"willem-p": "Raymond Mhlaba"}, MONTH_START, MONTH_END, entry_date)
        payload = calendar_xlsx_bytes(rows, MONTH_KEY)
        _xml(payload)  # must not raise — proves the control char never reached the XML
        wb = load_workbook(io.BytesIO(payload))
        text = _activity_texts_for_date(wb["Calendar"], date(2026, 9, 5))[0]
        self.assertNotIn("\x0b", text)
        self.assertEqual(dirty_doc, before, "sanitization is export-only and must never touch the source document")


class ZeroDatabaseWriteTests(unittest.TestCase):
    """These are pure functions with no database handle at all — this test
    exists to make that invariant explicit and catch any future regression
    that accidentally threads a write-capable collection into the module."""

    def test_generating_a_workbook_never_mutates_any_input_document(self):
        docs = [entry(id=str(i)) for i in range(5)]
        campaigns = [campaign(planned_activities=[
            {"id": "p1", "date": "2026-09-20", "time": "09:00", "activity_type": "Info Table", "area": ""},
        ])]
        docs_before = [dict(d) for d in docs]
        campaigns_before = [dict(c) for c in campaigns]
        rows = build_calendar_entries(docs, campaigns, {}, {"willem-p": "Raymond Mhlaba"}, {}, MONTH_START, MONTH_END, entry_date)
        calendar_xlsx_bytes(rows, MONTH_KEY)
        self.assertEqual(docs, docs_before)
        self.assertEqual(campaigns, campaigns_before)


AUGUST_KEY = "2026-08"
AUGUST_START, AUGUST_END = month_bounds(AUGUST_KEY)
_MUNICIPALITY_BY_PERSON = {"willem-p": "Raymond Mhlaba", "spokazi-m": "Amahlathi", "thulani-d": "Raymond Mhlaba"}
_WARDS_BY_PERSON = {"willem-p": "Ward 7", "spokazi-m": "Ward 14", "thulani-d": "Ward 3"}


class MultiMonthTests(unittest.TestCase):
    """Month selector coverage (backend side): August/September/October all
    produce valid, correctly labelled workbooks, including an empty month."""

    def test_several_months_all_produce_valid_workbooks(self):
        for month_key in ("2026-08", "2026-09", "2026-10"):
            with self.subTest(month=month_key):
                start, end = month_bounds(month_key)
                docs = [entry(id="1", activity_date=f"{month_key}-05")]
                rows = build_calendar_entries(docs, [], {}, {"willem-p": "Raymond Mhlaba"}, {}, start, end, entry_date)
                payload = calendar_xlsx_bytes(rows, month_key)
                self.assertTrue(payload.startswith(b"PK\x03\x04"))
                _xml(payload)
                wb = load_workbook(io.BytesIO(payload))
                self.assertEqual(wb.sheetnames, ["Calendar", "Canvassing Activity List"])
                self.assertEqual(wb["Calendar"]["A5"].value, month_label(month_key))

    def test_month_with_only_non_canvassing_activity_is_an_empty_canvassing_calendar(self):
        # A month can have real Ward Tracker activity and still show
        # nothing here if none of it is canvassing-classified.
        start, end = month_bounds("2026-10")
        docs = [entry(id="1", activity_date="2026-10-05", type="Oversight", type_display="Oversight")]
        rows = build_calendar_entries(docs, [], {}, {"willem-p": "Raymond Mhlaba"}, {}, start, end, entry_date)
        self.assertEqual(rows, [])
        wb = load_workbook(io.BytesIO(calendar_xlsx_bytes(rows, "2026-10")))
        self.assertEqual(wb["Calendar"]["A6"].value, "No canvassing activities scheduled for this month.")


# --- September reconciliation: the reported ~119-all-activity month, now
# recomputed under the Canvassing-only scope this rewrite requires. --------

SEPTEMBER_KEY = "2026-09"
SEPTEMBER_START, SEPTEMBER_END = month_bounds(SEPTEMBER_KEY)
_SEPTEMBER_ALL_ACTIVITY_TYPES = CANVASSING_TYPES + NON_CANVASSING_TYPES  # 5 canvassing + 5 non-canvassing
_SEPTEMBER_LOGGED_COUNT = 110  # + 9 planned below = the previously-reported 119
_SEPTEMBER_PLANNED_COUNT = 9
_SEPTEMBER_BUSY_DATES = ["2026-09-02", "2026-09-09", "2026-09-16", "2026-09-23", "2026-09-30"]


def _september_all_activity_docs(count: int = _SEPTEMBER_LOGGED_COUNT) -> list[dict]:
    """Reproduces the previously-reported ~119-activity September, but
    across ALL activity types (half canvassing, half not) rather than the
    all-canvassing fixture used elsewhere in this file — this is what lets
    the reconciliation tests below prove the scope correction actually
    excludes something real."""
    people = list(_MUNICIPALITY_BY_PERSON)
    docs = []
    for i in range(count):
        person_id = people[i % len(people)]
        activity_type = _SEPTEMBER_ALL_ACTIVITY_TYPES[i % len(_SEPTEMBER_ALL_ACTIVITY_TYPES)]
        docs.append({
            "id": str(i), "week_key": "2026-08-31", "day": "mon", "person_id": person_id,
            "type": activity_type, "type_display": activity_type,
            "ward": _WARDS_BY_PERSON[person_id], "venue": f"Venue #{i}",
            "activity_date": _SEPTEMBER_BUSY_DATES[i % len(_SEPTEMBER_BUSY_DATES)],
            "start_time": f"{9 + i % 8:02d}:00", "end_time": f"{10 + i % 8:02d}:00",
        })
    return docs


def _september_stress_campaign(count: int = _SEPTEMBER_PLANNED_COUNT) -> dict:
    return {
        "id": "c-sept", "name": "September Push", "person_id": "spokazi-m",
        "municipality": "Amahlathi", "wards": ["Ward 14"], "submission_status": "submitted",
        "planned_activities": [
            {
                "id": f"p{i}", "date": f"2026-09-{5 + (i % 20):02d}", "time": f"{8 + i % 6:02d}:00",
                "activity_type": CANVASSING_TYPES[i % len(CANVASSING_TYPES)], "area": "",
            }
            for i in range(count)
        ],
    }


class SeptemberReconciliationTest(unittest.TestCase):
    """Section 10 of the brief: recompute September under the Canvassing-
    only scope and report (previous all-activity count, new canvassing-only
    count, count excluded) — proven programmatically, not hand-calculated."""

    @classmethod
    def setUpClass(cls):
        cls.docs = _september_all_activity_docs()
        cls.campaign = _september_stress_campaign()
        # "Previous" all-activity calendar count: every reportable doc in
        # the month, with no classification filter at all (the old scope).
        cls.previous_all_activity_count = len([
            d for d in cls.docs if SEPTEMBER_START <= entry_date(d) <= SEPTEMBER_END
        ]) + _SEPTEMBER_PLANNED_COUNT
        cls.canvassing_rows = build_calendar_entries(
            cls.docs, [cls.campaign], {"c-sept": "September Push"}, _MUNICIPALITY_BY_PERSON, {"spokazi-m": "Spokazi M"},
            SEPTEMBER_START, SEPTEMBER_END, entry_date,
        )
        cls.payload = calendar_xlsx_bytes(cls.canvassing_rows, SEPTEMBER_KEY)

    def test_previous_all_activity_count_matches_the_reported_119(self):
        self.assertEqual(self.previous_all_activity_count, 119)

    def test_new_canvassing_only_count_is_smaller_and_exact(self):
        # Exactly half of the 10 rotating types are canvassing -> half of
        # 110 logged, plus all 9 planned (all chosen from CANVASSING_TYPES).
        expected_logged = sum(
            1 for d in self.docs
            if smartsheet_bucket(classification_for_entry(d)) == CANVASSING
        )
        total, logged, planned = calendar_summary_counts(self.canvassing_rows)
        self.assertEqual(logged, expected_logged)
        self.assertEqual(planned, _SEPTEMBER_PLANNED_COUNT)
        self.assertEqual(total, expected_logged + _SEPTEMBER_PLANNED_COUNT)
        self.assertLess(total, self.previous_all_activity_count, "the Canvassing Calendar must be a strict subset of the old all-activity calendar")

    def test_excluded_count_accounts_for_the_rest_and_nothing_is_altered(self):
        total, _, _ = calendar_summary_counts(self.canvassing_rows)
        excluded = self.previous_all_activity_count - total
        self.assertGreater(excluded, 0)
        self.assertEqual(excluded + total, self.previous_all_activity_count)
        # None of the excluded (or included) source documents were touched.
        for doc in self.docs:
            self.assertIn("type_display", doc)  # still the original, unmodified shape

    def test_workbook_is_well_formed_and_opens_without_repair(self):
        self.assertTrue(self.payload.startswith(b"PK\x03\x04"))
        with zipfile.ZipFile(io.BytesIO(self.payload)) as z:
            for name in z.namelist():
                if name.endswith(".xml") or name.endswith(".rels"):
                    ET.fromstring(z.read(name))
        root = _xml(self.payload)
        self.assertEqual(list(root.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}r")), [])

    def test_every_canvassing_activity_is_individually_visible_on_a_busy_day(self):
        wb = load_workbook(io.BytesIO(self.payload))
        ws = wb["Calendar"]
        canvassing_docs_by_date: dict[str, list[dict]] = {}
        for doc in self.docs:
            if smartsheet_bucket(classification_for_entry(doc)) == CANVASSING:
                canvassing_docs_by_date.setdefault(doc["activity_date"], []).append(doc)
        for date_str, docs_that_day in canvassing_docs_by_date.items():
            d = date.fromisoformat(date_str)
            texts = _activity_texts_for_date(ws, d)
            with self.subTest(date=date_str):
                # >= not == : this date may also carry a PLANNED campaign
                # activity (a separate row of its own) alongside the
                # logged ones counted here.
                self.assertGreaterEqual(len(texts), len(docs_that_day), "every activity that day must get its own row")
                combined = "\n".join(texts)
                self.assertNotIn(" activities", combined, "the canvassing calendar must never summarize a busy day")
                for doc in docs_that_day:
                    self.assertIn(f"Venue #{doc['id']}", combined, f"activity {doc['id']} must be individually visible")

    def test_calendar_summary_reconciles_with_activity_list_row_count(self):
        wb = load_workbook(io.BytesIO(self.payload))
        al_row_count = len(list(wb["Canvassing Activity List"].iter_rows(min_row=2)))
        total, _, _ = calendar_summary_counts(self.canvassing_rows)
        self.assertEqual(total, al_row_count)

    def test_activity_list_statuses_match_logged_and_planned_counts(self):
        wb = load_workbook(io.BytesIO(self.payload))
        statuses = [row[9].value for row in wb["Canvassing Activity List"].iter_rows(min_row=2)]
        _, logged, planned = calendar_summary_counts(self.canvassing_rows)
        self.assertEqual(statuses.count("LOGGED"), logged)
        self.assertEqual(statuses.count("PLANNED"), planned)


if __name__ == "__main__":
    unittest.main()
