const assert = require('assert');
const fs = require('fs');
const path = require('path');
const WeekDates = require('./week-dates');
const SmartSheetActivities = require('./smartsheet-activities');
const TimeOptions = require('./time-options');

// PHO Stage 2: faster candidate capture on a phone. Quick-pick chips only
// FILL the existing fields — validation, payloads and the save path are
// unchanged — so these tests cover the pick logic, the markup contract and
// HTML escaping, executed as the real source extracted from index.html.

const html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');

function extractFunctionSource(src, name) {
  const marker = `function ${name}(`;
  const start = src.indexOf(marker);
  if (start === -1) throw new Error(`could not find function ${name}() in index.html`);
  const braceStart = src.indexOf('{', start);
  let depth = 0;
  let i = braceStart;
  for (; i < src.length; i++) {
    if (src[i] === '{') depth++;
    else if (src[i] === '}') { depth--; if (depth === 0) { i++; break; } }
  }
  return src.slice(start, i);
}
const constLine = (name) => {
  const m = html.match(new RegExp(`^const ${name} = [^\\n]*;$`, 'm'));
  if (!m) throw new Error(`const ${name} not found`);
  return m[0];
};
const escapeHtmlSrc = extractFunctionSource(html, 'escapeHtml');

// --- Expired election countdown is gone (not just hidden) ---
{
  assert.ok(!/electionDays|Election Day Countdown|updateElectionCountdown|election-countdown/.test(html), 'the expired election countdown must be fully removed');
  console.log('election countdown removed');
}

// --- Form order and structure: what → when → where; optional extras folded ---
{
  const add = html.slice(html.indexOf('id="screenAdd"'), html.indexOf('id="screenStartCampaign"'));
  const at = (needle) => { const i = add.indexOf(needle); assert.ok(i > -1, `missing ${needle}`); return i; };
  assert.ok(at('id="fActivity"') < at('id="fDate"') && at('id="fDate"') < at('id="fStartTime"') && at('id="fStartTime"') < at('id="fVenue"'),
    'fields follow the agreed candidate flow: Activity → Date → Start/End → Location');
  ['fActivityChips', 'fDateChips', 'fVenueChips'].forEach((id) => at(`id="${id}"`));
  const more = at('id="fMoreDetails"');
  assert.ok(more < at('id="fOtherParticipantsField"') && at('id="fEvidenceField"') < add.indexOf('</details>', more),
    'helpers and photo evidence sit inside the optional "Helpers & photo" fold');
  assert.strictEqual((add.match(/id="saveBtn"/g) || []).length, 1, 'still exactly one Save button');
  assert.ok(/#screenAdd #saveBtn\{position:sticky/.test(html), 'Save stays reachable (sticky) on a long phone form');
  console.log('add-activity form order and optional fold are correct');
}

// --- quickDateChoices ---
{
  const fn = new Function('WeekDates', `${constLine('SHORT_DAYS')}\n${extractFunctionSource(html, 'quickDateChoices')}\nreturn quickDateChoices;`)(WeekDates);
  const week = fn('2026-11-09', '2026-11-15', '2026-11-12');
  assert.strictEqual(week.length, 7, 'a one-week range offers every day');
  assert.deepStrictEqual(week.map((d) => d.value)[0], '2026-11-09');
  assert.strictEqual(week.find((d) => d.value === '2026-11-12').label, 'Today');
  assert.strictEqual(week[0].label, 'Mon 9');
  const campaign = fn('2026-11-01', '2026-12-10', '2026-11-12');
  assert.deepStrictEqual(campaign.map((d) => d.value), ['2026-11-12', '2026-11-13', '2026-11-14', '2026-11-15'], 'long ranges: today, tomorrow, coming Sat and Sun');
  const future = fn('2026-12-01', '2026-12-20', '2026-11-12');
  assert.deepStrictEqual(future.map((d) => d.value), ['2026-12-01', '2026-12-02', '2026-12-03', '2026-12-04'], 'a future campaign offers its first days');
  assert.ok(future.every((d) => d.value >= '2026-12-01' && d.value <= '2026-12-20'), 'never offers a date outside the allowed range');
  assert.deepStrictEqual(fn('', '', '2026-11-12'), []);
  console.log('quickDateChoices offers only allowed dates');
}

// --- quickActivityChoices + rememberRecentPicks (per-device, localStorage) ---
{
  const canonical = SmartSheetActivities.CANONICAL_ACTIVITY_OPTIONS;
  const store = {};
  const localStorage = { getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); } };
  const fns = new Function('localStorage', 'CANONICAL_ACTIVITY_OPTIONS', 'personId', `
    ${constLine('QUICK_ACTIVITY_DEFAULTS')}
    ${extractFunctionSource(html, 'recentPicksKey')}
    ${extractFunctionSource(html, 'readRecentPicks')}
    ${extractFunctionSource(html, 'rememberRecentPicks')}
    ${extractFunctionSource(html, 'quickActivityChoices')}
    return {readRecentPicks, rememberRecentPicks, quickActivityChoices};`)(localStorage, canonical, 'test-candidate');

  assert.deepStrictEqual(fns.quickActivityChoices([], canonical), ['Door to Door', 'Info table : canvassing', 'House Meeting', 'Street Meeting', 'Telecanvassing']);
  fns.rememberRecentPicks('Oversight', 'Community hall, Ward 4');
  fns.rememberRecentPicks('Door to Door', 'community HALL, ward 4');
  fns.rememberRecentPicks('Other', '');
  const recent = fns.readRecentPicks();
  assert.deepStrictEqual(recent.activities, ['Door to Door', 'Oversight'], 'most recent first; "Other" is never offered as a quick pick');
  assert.deepStrictEqual(recent.venues, ['community HALL, ward 4'], 'venues dedupe case-insensitively; blanks ignored');
  assert.deepStrictEqual(fns.quickActivityChoices(recent.activities, canonical).slice(0, 2), ['Door to Door', 'Oversight']);
  assert.strictEqual(fns.quickActivityChoices(recent.activities, canonical).length, 5);
  for (let i = 0; i < 10; i++) fns.rememberRecentPicks('Door to Door', `Venue ${i}`);
  assert.strictEqual(fns.readRecentPicks().venues.length, 6, 'recent venues are capped');
  store['wardTrackerRecent:test-candidate'] = '{not json';
  assert.deepStrictEqual(fns.readRecentPicks(), { activities: [], venues: [] }, 'corrupt storage never breaks the form');
  console.log('recent activity/venue picks are remembered safely per device');
}

// --- suggestEndTime: fills a sensible end time, never overrides a valid one ---
{
  const fn = new Function(`${extractFunctionSource(html, 'suggestEndTime')}\nreturn suggestEndTime;`)();
  const options = TimeOptions.TIME_OPTIONS;
  assert.strictEqual(fn('09:00', '', options), '10:00');
  assert.strictEqual(fn('09:30', '', options), '10:30');
  assert.strictEqual(fn('09:00', '08:00', options), '10:00', 'an end time before the start is replaced');
  assert.strictEqual(fn('09:00', '12:00', options), '12:00', 'a valid end time is never overridden');
  assert.strictEqual(fn('22:00', '', options), '', 'no suggestion past the last available time');
  assert.strictEqual(fn('', '11:00', options), '11:00');
  console.log('suggestEndTime fills, never overrides');
}

// --- renderQuickChips escapes candidate-typed venues ---
{
  const el = { innerHTML: '', hidden: true };
  const fn = new Function('$', `${escapeHtmlSrc}\n${extractFunctionSource(html, 'renderQuickChips')}\nreturn renderQuickChips;`)(() => el);
  const XSS = '"><img src=x onerror=alert(1)>';
  fn('fVenueChips', [{ value: XSS, label: XSS }], XSS);
  assert.ok(!el.innerHTML.includes('<img'), 'venue text must be escaped in chips');
  assert.ok(el.innerHTML.includes('aria-pressed="true"'), 'the current value is marked selected');
  assert.strictEqual(el.hidden, false);
  fn('fVenueChips', [], '');
  assert.strictEqual(el.hidden, true, 'an empty chip row is hidden');
  console.log('renderQuickChips escapes data and hides when empty');
}

console.log('candidate-quick-capture.test.js OK');
