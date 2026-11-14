"""Pin the app's SAST "today" for test modules whose fixtures use literal
calendar dates.

Every app-side notion of "today" (sast_today, current_week_key, campaign
status derivation, the past-campaign creation guard, leadership periods)
resolves through week_dates._sast_date when no explicit `now` is passed.
Patching that one function keeps all of them consistent with each other —
unlike patching main.sast_today alone, which would leave current_week_key on
the real clock. An explicit `now` argument is always honoured unchanged.
"""
from datetime import date
from unittest import mock

import week_dates


def freeze_sast_today(today: date):
    """Return a patcher (call .start()/.stop(), e.g. from setUpModule /
    tearDownModule) that makes the app's SAST "today" equal `today`."""
    original = week_dates._sast_date

    def frozen(now=None):
        return today if now is None else original(now)

    return mock.patch.object(week_dates, "_sast_date", frozen)
