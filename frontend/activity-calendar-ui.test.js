const assert = require('assert');
const fs = require('fs');
const path = require('path');

// Ntsikana Activity Calendar (Coordinator, read-only). Structural checks
// against the real production markup/JS (not a re-implementation), matching
// the convention established in coordinator-reports-ui.test.js.

const html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');

function indexOfOrThrow(haystack, needle, label) {
  const i = haystack.indexOf(needle);
  assert.ok(i !== -1, `expected to find ${label}`);
  return i;
}

function extractFunctionSource(src, name) {
  const marker = `function ${name}(`;
  let start = src.indexOf(marker);
  if (start === -1) throw new Error(`could not find function ${name}() in index.html`);
  if (src.slice(Math.max(0, start - 6), start) === 'async ') start -= 6;
  const braceStart = src.indexOf('{', start);
  let depth = 0;
  let i = braceStart;
  for (; i < src.length; i++) {
    if (src[i] === '{') depth++;
    else if (src[i] === '}') {
      depth--;
      if (depth === 0) { i++; break; }
    }
  }
  return src.slice(start, i);
}

// --- 1. Calendar is its own screen, reachable from Coordinator Reports ---
const screenCalendarIdx = indexOfOrThrow(html, 'id="screenCalendar"', 'the calendar screen');
assert.ok(html.includes('<h1>Ntsikana Activity Calendar</h1>'), 'the calendar screen heading must read exactly "Ntsikana Activity Calendar"');
assert.ok(
  html.includes('Automatically generated from logged and planned campaign activities. Read-only.'),
  'the calendar screen must make clear it is read-only and auto-generated'
);

// --- 2. Month navigation + a simple status filter, nothing more elaborate ---
const monthBarIdx = indexOfOrThrow(html, 'id="calendarMonthBar"', 'the month navigation bar');
assert.ok(monthBarIdx > screenCalendarIdx, 'the month bar must be on the calendar screen');
assert.ok(html.includes("id=\"calendarStatusFilter\""), 'a status filter select must exist');
assert.ok(/<option value="all">All<\/option>/.test(html), 'status filter must offer All');
assert.ok(/<option value="planned">Planned<\/option>/.test(html), 'status filter must offer Planned');
assert.ok(/<option value="logged">Logged<\/option>/.test(html), 'status filter must offer Logged');

const renderCalendarMonthBarSrc = extractFunctionSource(html, 'renderCalendarMonthBar');
assert.ok(renderCalendarMonthBarSrc.includes('Previous Month'), 'Previous Month control must exist');
assert.ok(renderCalendarMonthBarSrc.includes('Current Month'), 'Current Month control must exist');
assert.ok(renderCalendarMonthBarSrc.includes('Next Month'), 'Next Month control must exist');

// --- 3. No editing affordance anywhere on the calendar screen ---
const screenCalendarBlockEnd = html.indexOf('<!-- 6. Coordinator Leader');
const screenCalendarBlock = html.slice(screenCalendarIdx, screenCalendarBlockEnd);
['<input type="text"', 'contenteditable', 'data-edit-entry', '<form'].forEach((marker) => {
  assert.ok(!screenCalendarBlock.includes(marker), `the calendar screen must not contain an editing affordance (${marker})`);
});

// --- 4. Rendering functions never invent a municipality or a time ---
const renderCalendarDetailSrc = extractFunctionSource(html, 'renderCalendarDetail');
assert.ok(renderCalendarDetailSrc.includes("'Municipality not recorded'"), 'the detail view must fall back to "Municipality not recorded", never guess one');
assert.ok(renderCalendarDetailSrc.includes('time_label'), 'the detail view must show the stored time_label (which is "Time not recorded" when genuinely missing), not invent one');

// --- 5. Download Excel calls the calendar export endpoint, not a CSV one ---
const downloadCalendarXlsxSrc = extractFunctionSource(html, 'downloadCalendarXlsx');
assert.ok(downloadCalendarXlsxSrc.includes('/api/admin/calendar/export.xlsx'), 'must download from the calendar xlsx export endpoint');
assert.ok(!downloadCalendarXlsxSrc.includes('.csv'), 'the calendar download must never fall back to CSV');

// --- 6. loadCalendar hits the admin-authenticated JSON endpoint ---
const loadCalendarSrc = extractFunctionSource(html, 'loadCalendar');
assert.ok(loadCalendarSrc.includes('/api/admin/calendar'), 'must fetch from /api/admin/calendar');
assert.ok(loadCalendarSrc.includes('adminHeaders()'), 'the calendar must use the Coordinator (admin) auth headers, not any candidate/leader path');

// --- 7. No duplicate ids introduced ---
['viewCalendarBtn', 'downloadCalendarBtn', 'screenCalendar', 'calendarBack', 'calendarMonthBar', 'calendarStatusFilter', 'calendarDownloadBtn', 'calendarGrid', 'calendarDetail']
  .forEach((id) => {
    const count = (html.match(new RegExp(`id="${id}"`, 'g')) || []).length;
    assert.strictEqual(count, 1, `${id} must appear exactly once (no duplicate ids)`);
  });

// --- 8. Leader dashboard is untouched by this addition ---
assert.ok(html.includes('id="screenLeadership"'), 'the Leader dashboard screen must still exist');
assert.ok(!/screenLeadership[\s\S]{0,400}screenCalendar/.test(html), 'the calendar screen must not be nested inside the Leader dashboard');
assert.ok(!screenCalendarBlock.includes('screenLeadership'), 'the calendar screen must not reference/embed the Leader dashboard');

// --- 9. Functional smoke test: actually execute the real grid-rendering
// code (extracted, not re-implemented) against realistic API-shaped data,
// to catch a real bug (e.g. an off-by-one in weekday alignment or day
// count) that a purely structural/text check above cannot. ---
const escapeHtmlSrc = extractFunctionSource(html, 'escapeHtml');
const calendarStatusBadgeSrc = extractFunctionSource(html, 'calendarStatusBadge');
const calendarWardCompactSrc = extractFunctionSource(html, 'calendarWardCompact');
const calendarEntryLineSrc = extractFunctionSource(html, 'calendarEntryLine');
const renderCalendarGridSrc = extractFunctionSource(html, 'renderCalendarGrid');
const calendarDayNamesMatch = html.match(/const CALENDAR_DAY_NAMES = (\[[^\]]*\]);/);
assert.ok(calendarDayNamesMatch, 'CALENDAR_DAY_NAMES must be defined');

function makeFakeElement() {
  return { innerHTML: '', textContent: '', dataset: {}, querySelectorAll: () => [] };
}

function runRenderCalendarGrid(data) {
  const elements = { calendarGrid: makeFakeElement() };
  const body = `
    const CALENDAR_DAY_NAMES = ${calendarDayNamesMatch[1]};
    let calendarLastData = null;
    function $(id){ return elements[id]; }
    ${escapeHtmlSrc}
    ${calendarStatusBadgeSrc}
    ${calendarWardCompactSrc}
    ${calendarEntryLineSrc}
    ${renderCalendarGridSrc}
    renderCalendarGrid(data);
  `;
  new Function('elements', 'data', body)(elements, data);
  return elements.calendarGrid.innerHTML;
}

{
  // September 2026: 1 Sep 2026 is a Tuesday -> exactly 1 leading blank cell
  // (Monday), and 30 days in the month.
  const gridHtml = runRenderCalendarGrid({
    month_key: '2026-09',
    entries: [
      { date: '2026-09-16', time_label: '09:00 - 11:00', activity: 'Door to Door', status: 'LOGGED', municipality_ward: 'Raymond Mhlaba Ward 7' },
      { date: '2026-09-20', time_label: '10:00', activity: 'Soup Kitchen', status: 'PLANNED', municipality_ward: 'Amahlathi Ward 4' },
    ],
  });
  const blankCount = (gridHtml.match(/class="calendar-cell blank"/g) || []).length;
  assert.strictEqual(blankCount, 1, 'September 2026 must render exactly one leading blank cell (1 Sep 2026 is a Tuesday)');
  const dayNumbers = (gridHtml.match(/class="calendar-daynum">(\d+)</g) || []).length;
  assert.strictEqual(dayNumbers, 30, 'September has 30 days');
  assert.ok(gridHtml.includes('✓ 09:00 - 11:00 Door to Door'), 'a LOGGED entry must render its real stored time and activity with its status symbol');
  assert.ok(gridHtml.includes('status-logged'), 'a LOGGED entry must carry the logged status class');
  assert.ok(gridHtml.includes('○ 10:00 Soup Kitchen'), 'a PLANNED entry must render its real stored time and activity with its status symbol');
  assert.ok(gridHtml.includes('status-planned'), 'a PLANNED entry must carry the planned status class');
  assert.ok(gridHtml.includes('Raymond Mhlaba W7'), 'the grid must show the compact municipality+ward form (W7, not Ward 7)');
  assert.ok(!gridHtml.includes('Raymond Mhlaba Ward 7'), 'the grid must abbreviate Ward N to WN, not spell it out');
  assert.ok(gridHtml.includes('Amahlathi W4'), 'a second entry\'s municipality+ward must also be shown');
  assert.ok(!gridHtml.includes('No activities scheduled'), 'the empty-month message must not show when there are activities');
  console.log('renderCalendarGrid functional smoke test passed');
}

{
  // A day with no entries must still render (just the day number, no
  // entry lines) — never silently dropped from the grid — and the whole
  // month shows the explicit empty-month message once.
  const gridHtml = runRenderCalendarGrid({ month_key: '2026-09', entries: [] });
  const dayNumbers = (gridHtml.match(/class="calendar-daynum">(\d+)</g) || []).length;
  assert.strictEqual(dayNumbers, 30, 'every day of the month must render even with zero activities');
  assert.ok(!gridHtml.includes('calendar-entry'), 'no entry chips should render when there are no activities');
  assert.ok(gridHtml.includes('No activities scheduled for this month.'), 'an empty month must show the exact required message');
}

{
  // Missing time is never invented, and never repeats "Time not recorded"
  // inside the compact grid line.
  const gridHtml = runRenderCalendarGrid({
    month_key: '2026-09',
    entries: [
      { date: '2026-09-05', time_label: 'Time not recorded', activity: 'Info Table', status: 'PLANNED', municipality_ward: 'Amahlathi Ward 4' },
    ],
  });
  assert.ok(gridHtml.includes('○ Info Table'), 'a missing time must simply be omitted, not invented');
  assert.ok(!gridHtml.includes('Time not recorded'), 'the compact grid must never repeat "Time not recorded"');
}

console.log('activity-calendar-ui.test.js OK');
