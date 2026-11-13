"""Additional chart fields must not change KPI totals."""
import unittest
from datetime import date

import leadership_reporting as lr


class CategoryTrendTests(unittest.TestCase):
    def test_category_counts_reconcile_by_week(self):
        entries = [
            {'activity_date':'2026-11-11','type':'Door to Door','type_display':'Door to Door', 'name':'A', 'person_id':'a', 'ward':'Ward 1'},
            {'activity_date':'2026-11-12','type':'Public Meeting','type_display':'Public Meeting', 'name':'B', 'person_id':'b', 'ward':'Ward 2'},
            {'activity_date':'2026-11-12','type':'Door to Door','type_display':'Door to Door', 'name':'A', 'person_id':'a', 'ward':'Ward 1'},
        ]
        context = lr.build_roster_context([], entries)
        period = lr.resolve_period('custom','2026-11-09','2026-11-15',now=date(2026,11,13))
        row = lr.weekly_operational_trend(entries, context, period, None, None, None, date(2026,11,13))[-1]
        self.assertEqual(row['total_activities'], 3)
        self.assertEqual(row['activity_types'], {'Door to Door':2, 'Public Meeting':1})
        self.assertEqual(sum(row['activity_types'].values()), row['total_activities'])


if __name__ == '__main__':
    unittest.main()
