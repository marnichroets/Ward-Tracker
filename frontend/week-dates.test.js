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

console.log('frontend week date tests passed');
