import io
import unittest
import xml.etree.ElementTree as ET
import zipfile
from datetime import date, time

from openpyxl import load_workbook

from activity_calendar import (
    ACTIVITY_LIST_HEADERS,
    LOGGED,
    MUNICIPALITY_NOT_RECORDED,
    PLANNED,
    STATUS_LEGEND,
    build_calendar_entries,
    calendar_filename,
    calendar_summary_counts,
    calendar_xlsx_bytes,
    group_by_day,
    logged_calendar_rows,
    municipality_ward_compact,
    municipality_ward_label,
    planned_calendar_rows,
)
from activity_records import CONFIRMED_DUPLICATE
from leadership_reporting import entry_date
from week_dates import month_bounds, month_label, next_month_key, previous_month_key


MONTH_KEY = "2026-09"
MONTH_START, MONTH_END = month_bounds(MONTH_KEY)


def entry(**overrides):
    doc = {
        "id": "1", "person_id": "willem-p", "name": "Willem P",
        "activity_date": "2026-09-16", "ward": "Ward 7", "venue": "Bezville Hall",
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
    def test_combines_municipality_and_single_ward(self):
        self.assertEqual(municipality_ward_label("Raymond Mhlaba", "Ward 7"), "Raymond Mhlaba Ward 7")

    def test_combines_municipality_and_multiple_wards(self):
        self.assertEqual(
            municipality_ward_label("Amahlathi", ["Ward 2", "Ward 14"]),
            "Amahlathi Ward 2, Amahlathi Ward 14",
        )

    def test_raymond_mhlaba_ward_7_and_amahlathi_ward_7_remain_distinct(self):
        a = municipality_ward_label("Raymond Mhlaba", "Ward 7")
        b = municipality_ward_label("Amahlathi", "Ward 7")
        self.assertNotEqual(a, b)
        self.assertEqual({a, b}, {"Raymond Mhlaba Ward 7", "Amahlathi Ward 7"})

    def test_unknown_municipality_shows_explicit_not_recorded_text(self):
        self.assertEqual(municipality_ward_label("", "Ward 7"), MUNICIPALITY_NOT_RECORDED)
        self.assertEqual(municipality_ward_label(None, None), MUNICIPALITY_NOT_RECORDED)

    def test_municipality_known_no_ward_shows_municipality_alone(self):
        self.assertEqual(municipality_ward_label("Amahlathi", ""), "Amahlathi")

    def test_never_double_prefixes_a_legacy_municipality_only_ward(self):
        self.assertEqual(municipality_ward_label("Amahlathi", "Amahlathi"), "Amahlathi")


class LoggedCalendarRowsTests(unittest.TestCase):
    def test_uses_real_stored_activity_data(self):
        rows = logged_calendar_rows(
            [entry()], {}, {"willem-p": "Raymond Mhlaba"}, MONTH_START, MONTH_END, entry_date,
        )
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["date"], date(2026, 9, 16))
        self.assertEqual(row["activity"], "Door to Door")
        self.assertEqual(row["venue"], "Bezville Hall")
        self.assertEqual(row["candidate"], "Willem P")
        self.assertEqual(row["status"], LOGGED)
        self.assertEqual(row["municipality_ward"], "Raymond Mhlaba Ward 7")

    def test_status_is_logged_not_planned(self):
        rows = logged_calendar_rows([entry()], {}, {}, MONTH_START, MONTH_END, entry_date)
        self.assertEqual(rows[0]["status"], "LOGGED")
        self.assertNotEqual(rows[0]["status"], "PLANNED")

    def test_excludes_activities_outside_the_month(self):
        rows = logged_calendar_rows(
            [entry(activity_date="2026-08-31"), entry(activity_date="2026-10-01")],
            {}, {}, MONTH_START, MONTH_END, entry_date,
        )
        self.assertEqual(rows, [])

    def test_confirmed_duplicate_excluded_using_shared_rule(self):
        rows = logged_calendar_rows(
            [entry(duplicate_review_status=CONFIRMED_DUPLICATE)],
            {}, {}, MONTH_START, MONTH_END, entry_date,
        )
        self.assertEqual(rows, [], "a confirmed duplicate must never appear on the calendar")

    def test_missing_time_is_never_invented(self):
        rows = logged_calendar_rows(
            [entry(start_time=None, end_time=None)], {}, {}, MONTH_START, MONTH_END, entry_date,
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
            [entry(campaign_id="c1")], {"c1": "Soup Kitchen Drive"}, {}, MONTH_START, MONTH_END, entry_date,
        )
        self.assertEqual(rows[0]["campaign_name"], "Soup Kitchen Drive")


class PlannedCalendarRowsTests(unittest.TestCase):
    def test_uses_planned_activity_row_data(self):
        c = campaign(planned_activities=[
            {"id": "p1", "date": "2026-09-20", "time": "09:00", "activity_type": "Soup Kitchen", "area": "On the street corner"},
        ])
        rows = planned_calendar_rows([c], {"spokazi-m": "Spokazi M"}, MONTH_START, MONTH_END)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["date"], date(2026, 9, 20))
        self.assertEqual(row["activity"], "Soup Kitchen")
        self.assertEqual(row["venue"], "On the street corner")
        self.assertEqual(row["candidate"], "Spokazi M")
        self.assertEqual(row["campaign_name"], "Soup Kitchen Drive")
        self.assertEqual(row["status"], PLANNED)
        self.assertEqual(row["municipality_ward"], "Amahlathi Ward 14")

    def test_status_is_planned_not_logged(self):
        c = campaign(planned_activities=[{"id": "p1", "date": "2026-09-20", "time": "09:00", "activity_type": "Soup Kitchen", "area": ""}])
        rows = planned_calendar_rows([c], {}, MONTH_START, MONTH_END)
        self.assertEqual(rows[0]["status"], "PLANNED")

    def test_planned_row_never_marked_as_completed_reporting(self):
        # A planned row must never be classifiable as LOGGED/reportable via
        # the shared duplicate/reportable rule — it isn't even an `entries`
        # document, so it can never enter is_reportable_activity's domain.
        c = campaign(planned_activities=[{"id": "p1", "date": "2026-09-20", "time": "09:00", "activity_type": "Soup Kitchen", "area": ""}])
        rows = planned_calendar_rows([c], {}, MONTH_START, MONTH_END)
        self.assertNotIn("duplicate_review_status", rows[0])
        self.assertEqual(rows[0]["status"], PLANNED)

    def test_draft_campaigns_excluded(self):
        c = campaign(submission_status="draft", planned_activities=[
            {"id": "p1", "date": "2026-09-20", "time": "09:00", "activity_type": "Soup Kitchen", "area": ""},
        ])
        rows = planned_calendar_rows([c], {}, MONTH_START, MONTH_END)
        self.assertEqual(rows, [])

    def test_activities_outside_month_excluded(self):
        c = campaign(planned_activities=[
            {"id": "p1", "date": "2026-08-31", "time": "09:00", "activity_type": "Soup Kitchen", "area": ""},
            {"id": "p2", "date": "2026-10-01", "time": "09:00", "activity_type": "Soup Kitchen", "area": ""},
        ])
        rows = planned_calendar_rows([c], {}, MONTH_START, MONTH_END)
        self.assertEqual(rows, [])

    def test_missing_planned_time_is_never_invented(self):
        c = campaign(planned_activities=[{"id": "p1", "date": "2026-09-20", "time": "", "activity_type": "Soup Kitchen", "area": ""}])
        rows = planned_calendar_rows([c], {}, MONTH_START, MONTH_END)
        self.assertEqual(rows[0]["time_label"], "Time not recorded")

    def test_no_campaign_municipality_shows_not_recorded(self):
        c = campaign(municipality="", planned_activities=[
            {"id": "p1", "date": "2026-09-20", "time": "09:00", "activity_type": "Soup Kitchen", "area": ""},
        ])
        rows = planned_calendar_rows([c], {}, MONTH_START, MONTH_END)
        self.assertEqual(rows[0]["municipality_ward"], MUNICIPALITY_NOT_RECORDED)


class BuildCalendarEntriesTests(unittest.TestCase):
    def test_combines_logged_and_planned_without_deduping(self):
        # No reliable per-row link exists between a planned_activities item
        # and a logged entries document anywhere in this app, so both a
        # planned row and an unrelated logged row for the same day must
        # both appear — never silently collapsed.
        e = entry(activity_date="2026-09-20", type_display="Soup Kitchen")
        c = campaign(planned_activities=[
            {"id": "p1", "date": "2026-09-20", "time": "09:00", "activity_type": "Soup Kitchen", "area": ""},
        ])
        rows = build_calendar_entries([e], [c], {}, {}, {}, MONTH_START, MONTH_END, entry_date)
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["status"] for r in rows}, {"LOGGED", "PLANNED"})

    def test_status_filter_planned_only(self):
        e = entry()
        c = campaign(planned_activities=[{"id": "p1", "date": "2026-09-20", "time": "09:00", "activity_type": "Soup Kitchen", "area": ""}])
        rows = build_calendar_entries([e], [c], {}, {}, {}, MONTH_START, MONTH_END, entry_date, status_filter="PLANNED")
        self.assertTrue(rows)
        self.assertTrue(all(r["status"] == "PLANNED" for r in rows))

    def test_status_filter_logged_only(self):
        e = entry()
        c = campaign(planned_activities=[{"id": "p1", "date": "2026-09-20", "time": "09:00", "activity_type": "Soup Kitchen", "area": ""}])
        rows = build_calendar_entries([e], [c], {}, {}, {}, MONTH_START, MONTH_END, entry_date, status_filter="logged")
        self.assertTrue(rows)
        self.assertTrue(all(r["status"] == "LOGGED" for r in rows))

    def test_sorted_chronologically(self):
        e1 = entry(activity_date="2026-09-20", start_time="14:00")
        e2 = entry(activity_date="2026-09-05", start_time="09:00")
        rows = build_calendar_entries([e1, e2], [], {}, {}, {}, MONTH_START, MONTH_END, entry_date)
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


class CalendarXlsxTests(unittest.TestCase):
    def _rows(self):
        e = entry(activity_date="2026-09-16")
        c = campaign(planned_activities=[
            {"id": "p1", "date": "2026-09-20", "time": "10:00", "activity_type": "Soup Kitchen", "area": "On the street corner"},
        ])
        return build_calendar_entries(
            [e], [c], {}, {"willem-p": "Raymond Mhlaba"}, {"spokazi-m": "Spokazi M"},
            MONTH_START, MONTH_END, entry_date,
        )

    def test_produces_a_genuine_xlsx_with_two_worksheets(self):
        payload = calendar_xlsx_bytes(self._rows(), MONTH_KEY)
        self.assertTrue(payload.startswith(b"PK\x03\x04"), "must be a genuine .xlsx, not CSV/text")
        wb = load_workbook(io.BytesIO(payload))
        self.assertEqual(wb.sheetnames, ["Calendar", "Activity List"])

    def test_calendar_sheet_shows_clean_header_block(self):
        wb = load_workbook(io.BytesIO(calendar_xlsx_bytes(self._rows(), MONTH_KEY)))
        ws = wb["Calendar"]
        self.assertEqual(ws["A2"].value, "Democratic Alliance")
        self.assertEqual(ws["A3"].value, "Ntsikana Constituency")
        self.assertEqual(ws["A4"].value, "Activity Calendar")
        self.assertEqual(ws["A5"].value, "September 2026")

    def test_calendar_header_is_not_oversized(self):
        wb = load_workbook(io.BytesIO(calendar_xlsx_bytes(self._rows(), MONTH_KEY)))
        ws = wb["Calendar"]
        # The weekday header (and grid) must start within the first ~9 rows
        # — a handful of compact header lines, not a sprawling banner.
        self.assertEqual(ws["A9"].value, "Monday")

    def test_month_summary_reconciles_exactly_with_the_rows(self):
        rows = self._rows()
        total, logged, planned = calendar_summary_counts(rows)
        self.assertEqual((total, logged, planned), (2, 1, 1))
        wb = load_workbook(io.BytesIO(calendar_xlsx_bytes(rows, MONTH_KEY)))
        ws = wb["Calendar"]
        self.assertEqual(ws["A6"].value, f"Total Activities: {total}  |  Logged: {logged}  |  Planned: {planned}")

    def test_empty_month_shows_plain_message_not_zero_counts(self):
        wb = load_workbook(io.BytesIO(calendar_xlsx_bytes([], MONTH_KEY)))
        ws = wb["Calendar"]
        self.assertEqual(ws["A6"].value, "No activities scheduled for this month.")

    def test_legend_present_and_print_safe(self):
        wb = load_workbook(io.BytesIO(calendar_xlsx_bytes(self._rows(), MONTH_KEY)))
        ws = wb["Calendar"]
        self.assertEqual(ws["A7"].value, STATUS_LEGEND)
        self.assertIn("✓", STATUS_LEGEND)
        self.assertIn("○", STATUS_LEGEND)
        self.assertIn("Logged", STATUS_LEGEND)
        self.assertIn("Planned", STATUS_LEGEND)

    def test_calendar_cell_text_uses_compact_symbol_and_ward_form(self):
        wb = load_workbook(io.BytesIO(calendar_xlsx_bytes(self._rows(), MONTH_KEY)))
        ws = wb["Calendar"]
        day16 = next(c for row in ws.iter_rows(min_row=10) for c in row if c.value and str(c.value).startswith("16\n"))
        self.assertIn("✓ 09:00 Door to Door · Raymond Mhlaba W7", str(day16.value))
        self.assertNotIn("(LOGGED)", str(day16.value))
        self.assertNotIn("Ward 7", str(day16.value), "the compact grid must abbreviate to W7, not spell out Ward 7")

    def test_missing_time_never_invented_and_stays_compact(self):
        docs_row = {
            "date": date(2026, 9, 21), "start_time": "", "end_time": "", "time_label": "Time not recorded",
            "activity": "Info Table", "municipality": "Amahlathi", "ward": "Ward 4",
            "municipality_ward": "Amahlathi Ward 4", "venue": "", "candidate": "", "campaign_name": "", "status": PLANNED,
        }
        wb = load_workbook(io.BytesIO(calendar_xlsx_bytes([docs_row], MONTH_KEY)))
        ws = wb["Calendar"]
        day21 = next(c for row in ws.iter_rows(min_row=10) for c in row if c.value and str(c.value).startswith("21\n"))
        self.assertIn("○ Info Table · Amahlathi W4", str(day21.value))
        self.assertNotIn("Time not recorded", str(day21.value), "the Calendar grid must never repeat 'Time not recorded'")

    def test_busy_day_row_grows_and_never_drops_activities(self):
        busy_docs = [
            entry(activity_date="2026-09-10", start_time=f"{9+i:02d}:00", end_time=f"{10+i:02d}:00", type_display=f"Activity {i}")
            for i in range(8)
        ]
        rows = logged_calendar_rows(busy_docs, {}, {"willem-p": "Raymond Mhlaba"}, MONTH_START, MONTH_END, entry_date)
        wb = load_workbook(io.BytesIO(calendar_xlsx_bytes(rows, MONTH_KEY)))
        ws = wb["Calendar"]
        day10 = next(c for row in ws.iter_rows(min_row=10) for c in row if c.value and str(c.value).startswith("10\n"))
        for i in range(8):
            self.assertIn(f"Activity {i}", str(day10.value), "every activity on a busy day must still be present, never dropped")
        row_height = ws.row_dimensions[day10.row].height
        self.assertGreater(row_height, 80, "a busy day's row must grow taller than the default")

    def test_days_outside_the_month_are_shaded_not_prominent(self):
        wb = load_workbook(io.BytesIO(calendar_xlsx_bytes(self._rows(), MONTH_KEY)))
        ws = wb["Calendar"]
        # 1 Sep 2026 is a Tuesday: cell A10 (Monday of the first grid row) is
        # outside the month and must be blank, not a real day-1 cell.
        self.assertFalse(ws["A10"].value)
        self.assertEqual(ws["A10"].fill.patternType, "solid")

    def test_activity_list_headers_exact(self):
        wb = load_workbook(io.BytesIO(calendar_xlsx_bytes(self._rows(), MONTH_KEY)))
        ws = wb["Activity List"]
        self.assertEqual([c.value for c in ws[1]], ACTIVITY_LIST_HEADERS)

    def test_activity_list_date_and_time_cells_are_real_types_with_sa_format(self):
        import datetime as dt
        wb = load_workbook(io.BytesIO(calendar_xlsx_bytes(self._rows(), MONTH_KEY)))
        ws = wb["Activity List"]
        rows_by_status = {row[9].value: row for row in ws.iter_rows(min_row=2)}
        logged_row = rows_by_status["LOGGED"]
        self.assertIsInstance(logged_row[0].value, dt.date)
        self.assertEqual(logged_row[0].number_format, "dd/mm/yyyy")
        self.assertIsInstance(logged_row[1].value, dt.time)
        self.assertEqual(logged_row[1].number_format, "HH:MM")
        self.assertEqual(logged_row[3].value, "Raymond Mhlaba")  # MUNICIPALITY column
        self.assertEqual(logged_row[4].value, "Ward 7")  # WARD column, separate

    def test_planned_row_has_no_end_time_and_status_planned(self):
        wb = load_workbook(io.BytesIO(calendar_xlsx_bytes(self._rows(), MONTH_KEY)))
        ws = wb["Activity List"]
        planned_row = next(row for row in ws.iter_rows(min_row=2) if row[9].value == "PLANNED")
        self.assertIsNone(planned_row[2].value)  # TIME END
        self.assertEqual(planned_row[3].value, "Amahlathi")
        self.assertEqual(planned_row[4].value, "Ward 14")

    def test_no_formulas_outside_the_header_block(self):
        wb = load_workbook(io.BytesIO(calendar_xlsx_bytes(self._rows(), MONTH_KEY)))
        for name in wb.sheetnames:
            for row in wb[name].iter_rows():
                for cell in row:
                    self.assertNotEqual(cell.data_type, "f")

    def test_only_the_six_header_lines_are_merged_on_the_calendar_sheet(self):
        wb = load_workbook(io.BytesIO(calendar_xlsx_bytes(self._rows(), MONTH_KEY)))
        merged = sorted(str(r) for r in wb["Calendar"].merged_cells.ranges)
        self.assertEqual(merged, [f"A{n}:G{n}" for n in range(2, 8)])
        self.assertEqual(list(wb["Activity List"].merged_cells.ranges), [])

    def test_logo_embedded_when_available(self):
        wb = load_workbook(io.BytesIO(calendar_xlsx_bytes(self._rows(), MONTH_KEY)))
        # static/logo.png exists in this repo (the same file the Coordinator/
        # Leadership weekly report workbook already embeds).
        self.assertEqual(len(wb["Calendar"]._images), 1)

    def test_activity_list_can_be_omitted(self):
        payload = calendar_xlsx_bytes(self._rows(), MONTH_KEY, include_activity_list=False)
        wb = load_workbook(io.BytesIO(payload))
        self.assertEqual(wb.sheetnames, ["Calendar"])

    def test_activity_list_rows_alternate_shading(self):
        rows = self._rows() + self._rows()  # ensure at least 3 data rows
        wb = load_workbook(io.BytesIO(calendar_xlsx_bytes(rows, MONTH_KEY)))
        ws = wb["Activity List"]
        first_data_row_fill = ws.cell(row=2, column=1).fill.patternType
        second_data_row_fill = ws.cell(row=3, column=1).fill.patternType
        self.assertNotEqual(first_data_row_fill, second_data_row_fill, "alternating rows must actually differ")


class CalendarFilenameTests(unittest.TestCase):
    def test_filename_reflects_selected_month(self):
        self.assertEqual(calendar_filename("2026-09"), "Ntsikana_Activity_Calendar_September_2026.xlsx")
        self.assertEqual(calendar_filename("2026-10"), "Ntsikana_Activity_Calendar_October_2026.xlsx")

    def test_filename_never_says_current(self):
        self.assertNotIn("current", calendar_filename("2026-09").lower())


class MunicipalityWardCompactTests(unittest.TestCase):
    def test_abbreviates_ward_number(self):
        self.assertEqual(municipality_ward_compact("Raymond Mhlaba Ward 7"), "Raymond Mhlaba W7")

    def test_abbreviates_every_ward_in_a_multi_ward_list(self):
        self.assertEqual(
            municipality_ward_compact("Amahlathi Ward 2, Amahlathi Ward 14"),
            "Amahlathi W2, Amahlathi W14",
        )

    def test_leaves_municipality_not_recorded_untouched(self):
        self.assertEqual(municipality_ward_compact(MUNICIPALITY_NOT_RECORDED), MUNICIPALITY_NOT_RECORDED)


AUGUST_KEY = "2026-08"
AUGUST_START, AUGUST_END = month_bounds(AUGUST_KEY)
_MUNICIPALITY_BY_PERSON = {"willem-p": "Raymond Mhlaba", "spokazi-m": "Amahlathi", "thulani-d": "Raymond Mhlaba"}
_WARDS_BY_PERSON = {"willem-p": "Ward 7", "spokazi-m": "Ward 14", "thulani-d": "Ward 3"}
_BUSY_MONTH_ACTIVITY_DATES = ["2026-08-03", "2026-08-03", "2026-08-14", "2026-08-14", "2026-08-14", "2026-08-27", "2026-08-31"]


def _busy_month_docs(count: int = 34) -> list[dict]:
    """A regression fixture reproducing the reported production bug: a
    genuinely busy August 2026 (34 logged activities, several sharing a
    date, real punctuation/ward text) — not a single trivial fixture row."""
    people = list(_MUNICIPALITY_BY_PERSON)
    docs = []
    for i in range(count):
        person_id = people[i % len(people)]
        date_str = _BUSY_MONTH_ACTIVITY_DATES[i % len(_BUSY_MONTH_ACTIVITY_DATES)]
        docs.append({
            "id": str(i), "week_key": "2026-08-03", "day": "mon", "person_id": person_id,
            "type": "Door to Door", "type_display": f"Door to Door — Ward {i}",
            "ward": _WARDS_BY_PERSON[person_id], "venue": f"Community Hall #{i}",
            "activity_date": date_str, "start_time": f"{9 + i % 8:02d}:00", "end_time": f"{10 + i % 8:02d}:00",
        })
    return docs


def _busy_month_rows() -> list[dict]:
    return build_calendar_entries(
        _busy_month_docs(), [], {}, _MUNICIPALITY_BY_PERSON, {}, AUGUST_START, AUGUST_END, entry_date,
    )


class CalendarWorkbookIntegrityTests(unittest.TestCase):
    """Regression coverage for the production Excel-repair bug: rich-text
    runs whose separator run (a bare "\\n") had no xml:space="preserve",
    which Excel's strict validator rejected — repairing (silently dropping)
    the whole cell, so the Calendar grid rendered empty even though the
    Activity List and summary counts were correct. Root cause: openpyxl
    CellRichText/TextBlock rich-text cells. Fix: Calendar day cells are now
    a single plain string with one whole-cell font — the same proven write
    path every other export in this app already uses."""

    def _sheet1_xml(self, payload: bytes) -> ET.Element:
        with zipfile.ZipFile(io.BytesIO(payload)) as z:
            raw = z.read("xl/worksheets/sheet1.xml")
        return ET.fromstring(raw)  # raises if not well-formed XML

    def test_worksheet_xml_is_well_formed_for_a_busy_month(self):
        payload = calendar_xlsx_bytes(_busy_month_rows(), AUGUST_KEY)
        root = self._sheet1_xml(payload)  # must not raise
        self.assertEqual(root.tag, "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}worksheet")

    def test_every_workbook_xml_part_parses_cleanly(self):
        payload = calendar_xlsx_bytes(_busy_month_rows(), AUGUST_KEY)
        with zipfile.ZipFile(io.BytesIO(payload)) as z:
            xml_names = [n for n in z.namelist() if n.endswith(".xml") or n.endswith(".rels")]
            self.assertTrue(xml_names)
            for name in xml_names:
                with self.subTest(part=name):
                    ET.fromstring(z.read(name))  # raises ET.ParseError if malformed

    def test_no_rich_text_run_elements_in_the_calendar_worksheet(self):
        # The exact structure that triggered the Excel repair dialog — a
        # <c t="inlineStr"><is><r>...</r><r><t>\n</t></r><r>...</r></is></c>
        # rich-text cell — must never be produced again.
        payload = calendar_xlsx_bytes(_busy_month_rows(), AUGUST_KEY)
        root = self._sheet1_xml(payload)
        runs = list(root.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}r"))
        self.assertEqual(runs, [], "no <r> rich-text run elements may appear in the Calendar worksheet")

    def test_no_whitespace_only_text_elements_missing_xml_space_preserve(self):
        payload = calendar_xlsx_bytes(_busy_month_rows(), AUGUST_KEY)
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

    def test_calendar_cells_for_known_busy_month_dates_contain_the_activity_text(self):
        # The bug this guards against: Activity List has data, summary
        # counts are correct, but the Calendar grid cells are empty. Check
        # several specific known August dates, not just the totals.
        rows = _busy_month_rows()
        total, logged, planned = calendar_summary_counts(rows)
        self.assertEqual((total, logged, planned), (34, 34, 0))

        wb = load_workbook(io.BytesIO(calendar_xlsx_bytes(rows, AUGUST_KEY)))
        ws = wb["Calendar"]

        def cell_for_day(day: int):
            return next(c for row in ws.iter_rows(min_row=10) for c in row if c.value and str(c.value).startswith(f"{day}\n"))

        for date_str in sorted(set(_BUSY_MONTH_ACTIVITY_DATES)):
            day = int(date_str.split("-")[2])
            with self.subTest(date=date_str):
                cell_text = str(cell_for_day(day).value)
                self.assertIn("Door to Door", cell_text, f"day {day}'s cell must contain the real activity text, not be blank")
                self.assertIn("✓", cell_text)

        # 3 Aug 2026 has 10 activities in this fixture (34 docs cycling
        # through 7 dates) — confirm none of them were dropped.
        day3_text = str(cell_for_day(3).value)
        expected_on_day3 = sum(1 for i in range(34) if _BUSY_MONTH_ACTIVITY_DATES[i % 7] == "2026-08-03")
        self.assertEqual(day3_text.count("✓"), expected_on_day3, "every activity logged on this date must survive generation")

    def test_workbook_survives_openpyxl_save_load_round_trip_with_all_values_intact(self):
        rows = _busy_month_rows()
        payload = calendar_xlsx_bytes(rows, AUGUST_KEY)
        wb = load_workbook(io.BytesIO(payload))
        # Re-save what was just loaded and reload again — a second round
        # trip must not lose or corrupt anything either.
        buf2 = io.BytesIO()
        wb.save(buf2)
        wb2 = load_workbook(io.BytesIO(buf2.getvalue()))
        ws1, ws2 = wb["Calendar"], wb2["Calendar"]
        values1 = [[c.value for c in row] for row in ws1.iter_rows()]
        values2 = [[c.value for c in row] for row in ws2.iter_rows()]
        self.assertEqual(values1, values2)
        non_blank = sum(1 for row in values1 for v in row if v)
        self.assertGreater(non_blank, 30, "a busy month must leave plenty of non-blank grid cells after two round trips")

    def test_illegal_xml_control_characters_are_stripped_from_calendar_text(self):
        dirty_docs = [{
            "id": "1", "person_id": "willem-p", "name": "Willem P",
            "type": "Door to Door", "type_display": "Door to Door\x0bwith a control char",
            "ward": "Ward 7", "venue": "Hall", "activity_date": "2026-08-05",
            "start_time": "09:00", "end_time": "10:00",
        }]
        rows = logged_calendar_rows(dirty_docs, {}, _MUNICIPALITY_BY_PERSON, AUGUST_START, AUGUST_END, entry_date)
        payload = calendar_xlsx_bytes(rows, AUGUST_KEY)
        root = self._sheet1_xml(payload)  # must not raise — proves the control char never reached the XML
        wb = load_workbook(io.BytesIO(payload))
        ws = wb["Calendar"]
        day5 = next(c for row in ws.iter_rows(min_row=10) for c in row if c.value and str(c.value).startswith("5\n"))
        self.assertNotIn("\x0b", str(day5.value))
        self.assertIn("Door to Door", str(day5.value))
        # The stored database document itself is never mutated by export.
        self.assertEqual(dirty_docs[0]["type_display"], "Door to Door\x0bwith a control char")

    def test_activity_list_headers_and_format_unaffected_by_the_rich_text_fix(self):
        rows = _busy_month_rows()
        wb = load_workbook(io.BytesIO(calendar_xlsx_bytes(rows, AUGUST_KEY)))
        ws = wb["Activity List"]
        self.assertEqual([c.value for c in ws[1]], ACTIVITY_LIST_HEADERS)
        first_row = next(ws.iter_rows(min_row=2))
        self.assertEqual(first_row[0].number_format, "dd/mm/yyyy")
        self.assertEqual(first_row[1].number_format, "HH:MM")
        self.assertEqual(ws.freeze_panes, "A2")

    def test_month_selection_still_produces_valid_workbooks_for_several_months(self):
        for month_key, expected_status in (("2026-08", (34, 34, 0)), ("2026-09", None), ("2026-10", None)):
            with self.subTest(month=month_key):
                if month_key == "2026-08":
                    rows = _busy_month_rows()
                else:
                    start, end = month_bounds(month_key)
                    rows = build_calendar_entries([], [], {}, {}, {}, start, end, entry_date)
                payload = calendar_xlsx_bytes(rows, month_key)
                self.assertTrue(payload.startswith(b"PK\x03\x04"))
                self._sheet1_xml(payload)  # well-formed
                wb = load_workbook(io.BytesIO(payload))
                self.assertEqual(wb.sheetnames, ["Calendar", "Activity List"])
                self.assertEqual(wb["Calendar"]["A5"].value, month_label(month_key))
                if expected_status:
                    self.assertEqual(calendar_summary_counts(rows), expected_status)


if __name__ == "__main__":
    unittest.main()
