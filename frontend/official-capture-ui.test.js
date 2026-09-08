const assert = require('assert');
const fs = require('fs');
const path = require('path');
const WeekDates = require('./week-dates');

// Phase 4: Official Capture Workspace (admin-only). These tests execute the
// real production functions extracted from index.html (not a
// re-implementation), matching the convention established in
// campaign-ui.test.js / roster-selection.test.js.

const html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');

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

// --- Structural checks on the markup itself ---
assert.ok(html.includes('id="officialCapturePanel"'), 'Official Capture panel must exist on the admin screen');
assert.ok(html.includes('id="captureAwaitingCount"'), 'Awaiting Capture count must exist');
assert.ok(html.includes('id="captureCapturedCount"'), 'Captured count must exist');
assert.ok(html.includes('id="captureTotalCount"'), 'Total count must exist');
assert.ok(html.includes('id="captureExportBtn"'), 'Official Capture Excel export button must exist');
assert.ok(html.includes('id="weeklyCaptureWeek"'), 'Weekly Capture Report week selector must exist');
assert.ok(html.includes('id="weeklyCaptureIncludeCaptured"'), 'Weekly Capture Report Include Captured toggle must exist');
assert.ok(html.includes('id="weeklyCaptureOpenBtn"'), 'Open Weekly Capture Report action must exist');
assert.ok(html.includes('id="weeklyCaptureDownloadBtn"'), 'Download Weekly Capture Excel action must exist');
assert.ok(/<option value="awaiting_capture">Awaiting Capture<\/option>/.test(html), 'Status filter must default-list Awaiting Capture');
assert.ok(!/navigator\.geolocation/.test(html), 'no GPS/geolocation code must be present in this phase');
assert.ok(!/location_lat|location_lng|location_source/.test(html), 'no coordinate fields must be present in this phase');

const escapeHtmlSrc = extractFunctionSource(html, 'escapeHtml');
const fullDateLabelSrc = extractFunctionSource(html, 'fullDateLabel');
const copyCaptureDetailsTextSrc = extractFunctionSource(html, 'copyCaptureDetailsText');
const captureRowMatchesFiltersSrc = extractFunctionSource(html, 'captureRowMatchesFilters');
const renderCaptureRowSrc = extractFunctionSource(html, 'renderCaptureRow');

// Extra workflow states explicitly forbidden by the Phase 4 brief must never
// appear in the row-rendering function itself (scoped narrowly here, since
// e.g. "Submitted" is legitimate unrelated text elsewhere in the admin UI).
assert.ok(
  !/Draft|Processing|Approved|Submitted|Failed|Reviewed/.test(renderCaptureRowSrc),
  'renderCaptureRow must only ever express Awaiting Capture / Captured'
);

function makeSandbox({ captureFilters, officialCaptureData } = {}) {
  const body = `
    const FULL_MONTHS = ['January','February','March','April','May','June','July','August','September','October','November','December'];
    const NEEDS_CONFIRMATION_OPTION = '__needs_confirmation__';
    let captureFilters = ${JSON.stringify(captureFilters || {})};
    let officialCaptureData = ${JSON.stringify(officialCaptureData || null)};
    ${escapeHtmlSrc}
    ${fullDateLabelSrc}
    ${copyCaptureDetailsTextSrc}
    ${captureRowMatchesFiltersSrc}
    ${renderCaptureRowSrc}
    return { fullDateLabel, copyCaptureDetailsText, captureRowMatchesFilters, renderCaptureRow };
  `;
  return new Function('WeekDates', body)(WeekDates);
}

// --- fullDateLabel ---
{
  const { fullDateLabel } = makeSandbox();
  assert.strictEqual(fullDateLabel('2026-09-08'), '8 September 2026');
  assert.strictEqual(fullDateLabel('2026-01-01'), '1 January 2026');
  assert.strictEqual(fullDateLabel(''), '—');
  assert.strictEqual(fullDateLabel(null), '—');
  console.log('fullDateLabel tests passed');
}

// --- copyCaptureDetailsText ---
{
  const { copyCaptureDetailsText } = makeSandbox();
  const withCampaign = copyCaptureDetailsText({
    activity_date: '2026-09-08', start_time: '16:00', end_time: '18:00',
    name: 'Example Candidate', municipality: 'Amahlathi', ward: 'Ward 13', campaign_name: 'September Canvassing',
    type_display: 'Door to Door', official_activity_type: 'In-person Canvassing / Door-to-door',
    venue: 'Mlungisi Community Hall', notes: 'Well attended', participants: 'Bob Candidate, Thabo Mokoena',
  });
  assert.strictEqual(withCampaign, [
    'Date: 8 September 2026',
    'Time: 16:00 - 18:00',
    'Candidate: Example Candidate',
    'Municipality: Amahlathi',
    'Ward: Ward 13',
    'Campaign: September Canvassing',
    'Activity: Door to Door',
    'Official Type: In-person Canvassing / Door-to-door',
    'Location: Mlungisi Community Hall',
    'Notes: Well attended',
    'Participants: Bob Candidate, Thabo Mokoena',
  ].join('\n'), 'field order must match what is needed when capturing on the official site');

  // No campaign/municipality/notes/participants -> those lines are omitted
  // entirely, not shown as "—".
  const withoutCampaign = copyCaptureDetailsText({
    activity_date: '2026-09-08', start_time: '16:00', end_time: '18:00',
    name: 'Example Candidate', ward: 'Ward 13', campaign_name: null,
    type_display: 'Door to Door', official_activity_type: null,
    venue: 'Mlungisi Community Hall',
  });
  assert.ok(!withoutCampaign.includes('Campaign:'), 'Campaign line must be omitted when there is no campaign');
  assert.ok(!withoutCampaign.includes('Municipality:'), 'Municipality line must be omitted when absent');
  assert.ok(!withoutCampaign.includes('Notes:'), 'Notes line must be omitted when absent');
  assert.ok(!withoutCampaign.includes('Participants:'), 'Participants line must be omitted when absent');
  assert.ok(withoutCampaign.includes('Official Type: Official type needs confirmation'));

  // Never leaks technical/internal fields even if present on the object.
  const raw = copyCaptureDetailsText({
    id: 'abc123', person_id: 'jane-doe', campaign_id: 'cmp1', recurrence_id: 'rec1',
    activity_date: '2026-09-08', name: 'Jane Doe', ward: 'Ward 1', type_display: 'Rally', venue: 'Hall',
  });
  ['abc123', 'jane-doe', 'cmp1', 'rec1'].forEach(technical => {
    assert.ok(!raw.includes(technical), `Copy Details must never include technical field value "${technical}"`);
  });

  console.log('copyCaptureDetailsText tests passed');
}

// --- captureRowMatchesFilters ---
{
  const base = {
    id: 'a', person_id: 'jane-doe', campaign_id: 'cmp1', official_activity_type: 'Rally',
    capture_status: 'awaiting_capture', activity_date: '2026-09-10',
  };

  let { captureRowMatchesFilters } = makeSandbox({ captureFilters: { status: 'awaiting_capture', personId: '', campaignId: '', officialType: '', dateFrom: '', dateTo: '' } });
  assert.strictEqual(captureRowMatchesFilters(base), true);
  assert.strictEqual(captureRowMatchesFilters(Object.assign({}, base, { capture_status: 'captured' })), false);

  ({ captureRowMatchesFilters } = makeSandbox({ captureFilters: { status: 'all', personId: 'someone-else', campaignId: '', officialType: '', dateFrom: '', dateTo: '' } }));
  assert.strictEqual(captureRowMatchesFilters(base), false, 'candidate filter must exclude non-matching person_id');
  assert.strictEqual(captureRowMatchesFilters(Object.assign({}, base, { person_id: 'someone-else' })), true);

  ({ captureRowMatchesFilters } = makeSandbox({ captureFilters: { status: 'all', personId: '', campaignId: 'cmp2', officialType: '', dateFrom: '', dateTo: '' } }));
  assert.strictEqual(captureRowMatchesFilters(base), false, 'campaign filter must exclude non-matching campaign_id');

  ({ captureRowMatchesFilters } = makeSandbox({ captureFilters: { status: 'all', personId: '', campaignId: '', officialType: '__needs_confirmation__', dateFrom: '', dateTo: '' } }));
  assert.strictEqual(captureRowMatchesFilters(base), false, 'needs-confirmation filter must exclude a row with a resolved type');
  assert.strictEqual(captureRowMatchesFilters(Object.assign({}, base, { official_activity_type: null })), true);

  ({ captureRowMatchesFilters } = makeSandbox({ captureFilters: { status: 'all', personId: '', campaignId: '', officialType: '', dateFrom: '2026-09-01', dateTo: '2026-09-05' } }));
  assert.strictEqual(captureRowMatchesFilters(base), false, 'date range filter must exclude a row outside the range');
  assert.strictEqual(captureRowMatchesFilters(Object.assign({}, base, { activity_date: '2026-09-03' })), true);

  console.log('captureRowMatchesFilters tests passed');
}

// --- renderCaptureRow ---
{
  const officialCaptureData = { official_activity_types: ['Rally', 'March'] };
  const { renderCaptureRow } = makeSandbox({ officialCaptureData });

  const awaitingHtml = renderCaptureRow({
    id: 'a1', activity_date: '2026-09-08', start_time: '16:00', end_time: '18:00',
    name: 'Example Candidate', ward: 'Ward 13', campaign_name: 'September Canvassing',
    type_display: 'Door to Door', venue: 'Mlungisi Community Hall',
    official_activity_type: null, official_activity_type_source: 'unmapped',
    capture_status: 'awaiting_capture',
  });
  assert.ok(awaitingHtml.includes('Awaiting Capture'));
  assert.ok(awaitingHtml.includes('Mark Captured'));
  assert.ok(!awaitingHtml.includes('Undo Capture'));
  assert.ok(awaitingHtml.includes('8 September 2026'));
  assert.ok(awaitingHtml.includes('capture-badge awaiting'));
  // The id IS present for wiring the click handler...
  assert.ok(awaitingHtml.includes('data-id="a1"'));
  // ...but never rendered as visible label text anywhere else in the row.
  assert.ok(!/>a1</.test(awaitingHtml), 'the raw entry id must never appear as visible row text');

  const capturedHtml = renderCaptureRow({
    id: 'a2', activity_date: '2026-09-08', name: 'Example Candidate', ward: 'Ward 13',
    campaign_name: null, type_display: 'Rally', venue: 'Town Square',
    official_activity_type: 'Rally', official_activity_type_source: 'suggested',
    capture_status: 'captured',
  });
  assert.ok(capturedHtml.includes('Captured'));
  assert.ok(capturedHtml.includes('Undo Capture'));
  assert.ok(!capturedHtml.includes('Mark Captured'));
  assert.ok(capturedHtml.includes('capture-badge captured'));
  assert.ok(capturedHtml.includes('Campaign: —'), 'no campaign must render as a clean dash');
  assert.ok(capturedHtml.includes('(suggested)'), 'a suggested (unconfirmed) type must be visually distinguished');
  assert.ok(capturedHtml.includes('selected'), 'the resolved official type must be pre-selected in the dropdown');

  // HTML-escaping of candidate-controlled free text.
  const escapedHtml = renderCaptureRow({
    id: 'a3', activity_date: '2026-09-08', name: '<script>alert(1)</script>', ward: 'Ward 1',
    type_display: 'Door to Door', venue: '<img src=x>', capture_status: 'awaiting_capture',
  });
  assert.ok(!escapedHtml.includes('<script>alert(1)</script>'));
  assert.ok(!escapedHtml.includes('<img src=x>'));

  console.log('renderCaptureRow tests passed');
}

// --- renderWeeklyCaptureList ---
{
  const renderWeeklyCaptureListSrc = extractFunctionSource(html, 'renderWeeklyCaptureList');
  function run(entries) {
    const elements = { weeklyCaptureList: { innerHTML: '' } };
    const body = `
      const FULL_MONTHS = ['January','February','March','April','May','June','July','August','September','October','November','December'];
      function $(id){ return elements[id]; }
      const document = { querySelectorAll(){ return []; } };
      ${escapeHtmlSrc}
      ${fullDateLabelSrc}
      ${renderWeeklyCaptureListSrc}
      renderWeeklyCaptureList(entries);
    `;
    new Function('WeekDates', 'elements', 'entries', body)(WeekDates, elements, entries);
    return elements.weeklyCaptureList.innerHTML;
  }

  const html_out = run([{
    id: 'e1', activity_date: '2026-09-08', name: 'Example Candidate', municipality: 'Amahlathi',
    ward: 'Ward 13', campaign_name: 'September Canvassing', type_display: 'Door to Door',
    official_activity_type: 'In-person Canvassing / Door-to-door', venue: 'Mlungisi Community Hall',
    notes: 'Well attended', participants: 'Bob Candidate', capture_status: 'awaiting_capture',
  }]);
  assert.ok(html_out.includes('Amahlathi'), 'Municipality must be shown');
  assert.ok(html_out.includes('Well attended'), 'Notes must be shown when present');
  assert.ok(html_out.includes('Bob Candidate'), 'Participants must be shown when present');
  assert.ok(html_out.includes('Awaiting Capture'));

  const emptyHtml = run([]);
  assert.ok(/Nothing to capture/.test(emptyHtml), 'an empty week must show a clear empty state, not a blank list');

  console.log('renderWeeklyCaptureList tests passed');
}

console.log('official-capture-ui.test.js: all tests passed');
