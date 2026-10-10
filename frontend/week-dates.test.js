const assert = require('assert');
const WeekDates = require('./week-dates');

assert.strictEqual(
  WeekDates.currentWeekKey(new Date('2026-08-30T21:59:00Z')),
  '2026-08-23'
);
assert.strictEqual(
  WeekDates.weekLabel(WeekDates.currentWeekKey(new Date('2026-08-30T21:59:00Z'))),
  '24 Aug - 30 Aug'
);
assert.strictEqual(
  WeekDates.currentWeekKey(new Date('2026-08-30T22:01:00Z')),
  '2026-08-30'
);
assert.strictEqual(
  WeekDates.weekLabel(WeekDates.currentWeekKey(new Date('2026-08-30T22:01:00Z'))),
  '31 Aug - 6 Sep'
);
assert.strictEqual(WeekDates.activityDate('2026-08-23', 'sun'), '2026-08-30');
assert.strictEqual(WeekDates.activityDate('2026-08-30', 'mon'), '2026-08-31');
assert.strictEqual(WeekDates.activityDate('2026-08-30', 'sun'), '2026-09-06');

// --- Candidate-dashboard reminder cards: weekLabelWithYear / isSaturday ---
// Spec example: mocked "now" of 2026-10-10 (a Saturday) SAST.
{
  const now = new Date('2026-10-10T10:00:00+02:00');
  const current = WeekDates.currentWeekKey(now);
  const upcoming = WeekDates.nextWeekKey(current);
  assert.strictEqual(current, '2026-10-04');
  assert.strictEqual(upcoming, '2026-10-11');
  assert.strictEqual(WeekDates.weekLabelWithYear(current), '5–11 October 2026');
  assert.strictEqual(WeekDates.weekLabelWithYear(upcoming), '12–18 October 2026');
  assert.strictEqual(WeekDates.isSaturday(now), true);
}

// Normal mid-month week (Wednesday).
assert.strictEqual(
  WeekDates.weekLabelWithYear(WeekDates.currentWeekKey(new Date('2026-09-16T09:00:00+02:00'))),
  '14–20 September 2026'
);

// Saturday / Sunday / Monday day-of-week detection.
assert.strictEqual(WeekDates.isSaturday(new Date('2026-09-19T23:00:00+02:00')), true); // Sat
assert.strictEqual(WeekDates.isSaturday(new Date('2026-09-20T00:01:00+02:00')), false); // Sun
assert.strictEqual(WeekDates.isSaturday(new Date('2026-09-21T00:01:00+02:00')), false); // Mon

// Month boundary within the same year: Mon 28 Sep - Sun 4 Oct 2026.
assert.strictEqual(
  WeekDates.weekLabelWithYear(WeekDates.currentWeekKey(new Date('2026-09-29T10:00:00+02:00'))),
  '28 September – 4 October 2026'
);

// December -> January year boundary: Mon 28 Dec 2026 - Sun 3 Jan 2027.
{
  const current = WeekDates.currentWeekKey(new Date('2026-12-30T10:00:00+02:00'));
  const upcoming = WeekDates.nextWeekKey(current);
  assert.strictEqual(WeekDates.weekLabelWithYear(current), '28 December 2026 – 3 January 2027');
  assert.strictEqual(WeekDates.weekLabelWithYear(upcoming), '4–10 January 2027');
}

// Leap-year February: 2028 is a leap year; Mon 28 Feb - Sun 5 Mar 2028.
assert.strictEqual(
  WeekDates.weekLabelWithYear(WeekDates.currentWeekKey(new Date('2028-02-29T10:00:00+02:00'))),
  '28 February – 5 March 2028'
);

console.log('frontend week date tests passed');
