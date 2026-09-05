from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


try:
    SAST = ZoneInfo("Africa/Johannesburg")
except ZoneInfoNotFoundError:
    # Johannesburg has no DST; this keeps local/dev Windows installs working
    # even when the IANA tzdata package is not present.
    SAST = timezone(timedelta(hours=2), "SAST")


DAY_ORDER = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY_LABELS = {
    "mon": "Mon",
    "tue": "Tue",
    "wed": "Wed",
    "thu": "Thu",
    "fri": "Fri",
    "sat": "Sat",
    "sun": "Sun",
}
DAY_OFFSET = {"mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6, "sun": 7}
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _sast_date(now: datetime | date | None = None) -> date:
    if now is None:
        return datetime.now(SAST).date()
    if isinstance(now, datetime):
        if now.tzinfo is None:
            now = now.replace(tzinfo=SAST)
        return now.astimezone(SAST).date()
    if isinstance(now, date):
        return now
    raise TypeError("now must be a date, datetime, or None")


def sast_today(now: datetime | date | None = None) -> date:
    """Public wrapper for callers outside week_dates (e.g. campaign status
    derivation) that need "today" using the same SAST rules as everything
    else here, instead of a naive datetime.now().date()."""
    return _sast_date(now)


def current_week_key(now: datetime | date | None = None) -> str:
    today = _sast_date(now)
    monday = today - timedelta(days=today.weekday())
    sunday_anchor = monday - timedelta(days=1)
    return sunday_anchor.isoformat()


def next_week_key(week_key: str) -> str:
    return (_anchor_date(week_key) + timedelta(days=7)).isoformat()


def candidate_week_keys(now: datetime | date | None = None) -> tuple[str, str]:
    current = current_week_key(now)
    return current, next_week_key(current)


def validate_candidate_week_key(
    week_key: str, now: datetime | date | None = None
) -> str:
    """Allow candidate writes only for SAST current or immediately next week."""
    _anchor_date(week_key)
    if week_key not in candidate_week_keys(now):
        raise ValueError("Candidates may only submit activities for This Week or Next Week")
    return week_key


def _anchor_date(week_key: str) -> date:
    return date.fromisoformat(week_key)


def reporting_week_start(week_key: str) -> date:
    return _anchor_date(week_key) + timedelta(days=1)


def reporting_week_end(week_key: str) -> date:
    return _anchor_date(week_key) + timedelta(days=7)


# A campaign is a short programme, not an open-ended plan — 42 CALENDAR
# DATES is the maximum span, counting both start_date and end_date. A
# same-day campaign (start_date == end_date) is exactly 1 calendar date.
# Duration is deliberately computed as an inclusive day count
# ((end - start).days + 1), NOT the raw (end - start).days difference, to
# avoid an off-by-one: 2026-09-01..2026-10-12 is the 42nd calendar date
# (duration_days == 42, accepted); 2026-09-01..2026-10-13 is the 43rd
# (duration_days == 43, rejected).
MAX_CAMPAIGN_DAYS = 42


def validate_campaign_date_range(start_date: str, end_date: str) -> tuple[date, date]:
    """Validate a campaign's start/end dates: both required, end may not be
    before start, and the inclusive calendar-date span (start and end both
    counted) may not exceed MAX_CAMPAIGN_DAYS."""
    if not start_date:
        raise ValueError("start_date is required")
    if not end_date:
        raise ValueError("end_date is required")
    try:
        start = date.fromisoformat(start_date)
    except (TypeError, ValueError):
        raise ValueError("start_date must be an ISO calendar date")
    try:
        end = date.fromisoformat(end_date)
    except (TypeError, ValueError):
        raise ValueError("end_date must be an ISO calendar date")
    if end < start:
        raise ValueError("end_date may not be before start_date")
    duration_days = (end - start).days + 1
    if duration_days > MAX_CAMPAIGN_DAYS:
        raise ValueError(f"Campaign duration may not exceed {MAX_CAMPAIGN_DAYS} calendar days")
    return start, end


def format_week_label(week_key: str) -> str:
    start = reporting_week_start(week_key)
    end = reporting_week_end(week_key)
    return f"{start.day} {MONTHS[start.month - 1]} - {end.day} {MONTHS[end.month - 1]}"


def activity_date_for_day_date(week_key: str, day: str) -> date:
    if day not in DAY_OFFSET:
        raise ValueError(f"Invalid day: {day}")
    return _anchor_date(week_key) + timedelta(days=DAY_OFFSET[day])


def activity_date_for_day(week_key: str, day: str) -> str:
    return activity_date_for_day_date(week_key, day).isoformat()


def normalise_new_activity_date(
    week_key: str, day: str, activity_date: str | None = None
) -> str:
    """Validate a new submission without changing its selected week."""
    expected = activity_date_for_day(week_key, day)
    if activity_date is None or activity_date == "":
        return expected
    try:
        supplied = date.fromisoformat(activity_date)
    except (TypeError, ValueError):
        raise ValueError("activity_date must be an ISO calendar date")
    if supplied.isoformat() != activity_date or activity_date != expected:
        raise ValueError("activity_date does not match week_key and day")
    return activity_date
