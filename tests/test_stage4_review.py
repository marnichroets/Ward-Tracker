"""Stage 4 review safeguards; fully synthetic fixtures, no DB or network."""
import io
import unittest
from datetime import date
from unittest.mock import patch

from openpyxl import load_workbook
from pypdf import PdfReader
from pptx import Presentation

import leadership_reporting as lr
import meeting_pack as mp
import pdf_reports
from test_pho_dashboard import ROSTER, entries, NOW
from test_leadership_reporting import entry_doc


class Stage4ReviewTests(unittest.TestCase):
    def pack(self, start, end, data=None):
        return mp.build_meeting_pack(entries() if data is None else data, ROSTER, [], start, end, now=NOW)

    def test_historical_period_cannot_see_future_activities(self):
        p = self.pack('2025-01-06', '2025-01-12')
        self.assertFalse(p['comparison']['available'])
        self.assertEqual(p['kpis']['total'], 0)
        self.assertTrue(all(m['status_counts']['Needs Attention'] == 0 for m in p['municipalities']))
        self.assertFalse(any('wards with no recorded activity' in a['title'] for a in p['attention']))
        self.assertTrue(any('No activity records available' in a['title'] for a in p['attention']))

    def test_future_period_is_planning_not_performance(self):
        docs = entries() + [entry_doc('alice-candidate', 'Alice Candidate', 'Ward 1', 'Door to Door',
                                      '2026-09-13', 'wed', '2026-09-16')]
        p = self.pack('2026-09-14', '2026-09-20', docs)
        self.assertEqual((p['kpis']['completed'], p['kpis']['planned']), (0, 1))
        self.assertEqual(p['period']['state'], 'not_started')
        self.assertEqual(p['tiles'][2]['label'], 'Candidates planned')
        self.assertEqual(p['tiles'][3]['label'], 'Wards planned')
        self.assertNotIn('capture', p)
        self.assertNotIn('top', p['participation'])

    def test_current_week_separates_completed_from_planned(self):
        p = self.pack('2026-09-07', '2026-09-13')
        self.assertEqual((p['kpis']['total'], p['kpis']['completed'], p['kpis']['planned']), (4, 3, 1))
        self.assertFalse(any('capture' in a['title'].lower() for a in p['attention']))
        self.assertEqual(p['tiles'][2]['note'], 'Includes plans')

    def test_pdf_and_powerpoint_are_editable_and_no_capture_or_ranking_text(self):
        for period in [('2026-08-31', '2026-09-06'), ('2026-09-07', '2026-09-13'),
                       ('2026-09-14', '2026-09-20'), ('2025-01-06', '2025-01-12')]:
            with self.subTest(period=period):
                p = self.pack(*period)
                pdf = PdfReader(io.BytesIO(mp.meeting_pack_pdf_bytes(p)))
                ppt = Presentation(io.BytesIO(mp.meeting_pack_pptx_bytes(p)))
                self.assertEqual((len(pdf.pages), len(ppt.slides)), (8, 8))
                text = '\n'.join(page.extract_text() or '' for page in pdf.pages)
                for obsolete in ('Official Capture', 'Captured in Campaign Manager', 'Most active candidates'):
                    self.assertNotIn(obsolete, text)
                self.assertIn('Current planning update', text)
                self.assertIn('As of Thursday, 10 September 2026', text)
                self.assertTrue(any(shape.has_chart for slide in ppt.slides for shape in slide.shapes)) if p['kpis']['total'] else None
                self.assertTrue(any(shape.has_table for slide in ppt.slides for shape in slide.shapes))
                for slide in ppt.slides:
                    for shape in slide.shapes:
                        self.assertGreaterEqual(shape.left, 0)
                        self.assertGreaterEqual(shape.top, 0)
                        self.assertLessEqual(shape.left + shape.width, ppt.slide_width + 1)
                        self.assertLessEqual(shape.top + shape.height, ppt.slide_height + 1)

    def test_weekly_pdf_and_enhanced_excel_do_not_show_capture(self):
        d = lr.build_dashboard(entries(), ROSTER, [], preset='custom',
                               date_from='2026-09-07', date_to='2026-09-13', now=NOW)
        weekly = pdf_reports.weekly_report_pdf_bytes(d, 'All municipalities', generated_on=NOW)
        text = '\n'.join(page.extract_text() or '' for page in PdfReader(io.BytesIO(weekly)).pages)
        self.assertIn('Completed and Planned Activities', text)
        self.assertNotIn('Official Capture Progress', text)
        self.assertNotIn('Captured in Campaign Manager', text)
        with patch.object(lr, 'sast_today', return_value=NOW):
            xlsx = lr.leadership_workbook_bytes(entries(), ROSTER, [], d)
        wb = load_workbook(io.BytesIO(xlsx))
        self.assertEqual(wb.sheetnames[:5], ['Weekly Summary', 'Ward Performance', 'Activities',
                                             'Campaigns', 'Weekly Canvassing Activities'])
        self.assertEqual(wb.sheetnames[5:], ['Activity Timing', 'Municipality Summary',
                                             'Activity Mix', '12-Week Trend'])
        vals = dict(wb['Activity Timing'].values)
        self.assertEqual((vals['Completed (date reached)'], vals['Planned (future dates)']), (3, 1))


if __name__ == '__main__':
    unittest.main()
