const assert = require('assert');
const fs = require('fs');
const path = require('path');

// Coordinator Reports simplification: the Coordinator home screen must stop
// acting as an individual activity capture queue and become a simple place
// to generate the three existing SmartSheet reports (Canvassing,
// Public / Street Meetings, Presence). Nothing about the underlying capture
// data, campaign administration, or the Leader dashboard may be removed —
// only moved behind an explicit "Manage..." toggle. These are structural
// checks against the real production markup (not a re-implementation),
// matching the convention established in official-capture-ui.test.js.

const html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');

function indexOfOrThrow(haystack, needle, label) {
  const i = haystack.indexOf(needle);
  assert.ok(i !== -1, `expected to find ${label}`);
  return i;
}

// --- 1. Coordinator home screen: simple, report-first ---
const screenAdminStart = indexOfOrThrow(html, 'id="screenAdmin"', 'the Coordinator screen');
const h1Idx = indexOfOrThrow(html, '<h1>Coordinator Reports</h1>', 'the "Coordinator Reports" heading');
assert.ok(h1Idx > screenAdminStart, 'the Coordinator Reports heading must be on the Coordinator screen');
assert.ok(
  html.includes('Generate the reports needed for weekly constituency administration.'),
  'the Coordinator Reports helper line must be present'
);

// --- 2. Reporting period control (existing week selector, reused) ---
const adminWeekBarIdx = indexOfOrThrow(html, 'id="adminWeekBar"', 'the reporting period control');
assert.ok(adminWeekBarIdx > h1Idx, 'the reporting period control must appear on the Coordinator Reports home screen');

// --- 3. Exactly three reports, using the existing official category names ---
const canvassingBtnIdx = indexOfOrThrow(html, 'id="exportSmartsheetCanvassingXlsx"', 'the Canvassing report button');
const publicBtnIdx = indexOfOrThrow(html, 'id="exportSmartsheetPublicXlsx"', 'the Public / Street Meetings report button');
const presenceBtnIdx = indexOfOrThrow(html, 'id="exportSmartsheetPresenceXlsx"', 'the Presence report button');
assert.ok(html.includes('>Canvassing Activities<'), 'the exact existing "Canvassing Activities" label must be used');
assert.ok(html.includes('>Public / Street Meetings<'), 'the exact existing "Public / Street Meetings" label must be used');
assert.ok(html.includes('>Presence Activities<'), 'the exact existing "Presence Activities" label must be used');
[canvassingBtnIdx, publicBtnIdx, presenceBtnIdx].forEach((i) => {
  assert.ok(i > adminWeekBarIdx, 'each report button must appear after the reporting period control, on the home screen');
});

// --- 4. Individual capture queue is no longer the default view ---
const advancedToggleIdx = indexOfOrThrow(html, 'id="coordinatorAdvancedToggle"', 'the "Manage..." advanced toggle');
const advancedSectionIdx = indexOfOrThrow(html, '<div id="coordinatorAdvanced" hidden>', 'the collapsed advanced section');
assert.ok(advancedToggleIdx > presenceBtnIdx, 'the advanced toggle must come after the three reports, not before them');
assert.ok(advancedSectionIdx > advancedToggleIdx, 'the advanced section must be the thing the toggle reveals');

// Each of the three lives inside its own simple report card with one
// "Download Excel" button, not a grid of format choices.
const reportCardOpenings = html.match(/<div class="card coordinator-report-card">/g) || [];
assert.strictEqual(reportCardOpenings.length, 3, 'exactly three report cards must exist on the Coordinator home screen');
const homeScreenSlice = html.slice(adminWeekBarIdx, advancedToggleIdx);
const downloadExcelButtons = homeScreenSlice.match(/>Download Excel<\/button>/g) || [];
assert.strictEqual(downloadExcelButtons.length, 3, 'each report card must offer exactly one "Download Excel" button, and only on the home screen');

const officialCapturePanelIdx = indexOfOrThrow(html, 'id="officialCapturePanel"', 'the Official Capture panel');
const captureAwaitingIdx = indexOfOrThrow(html, 'id="captureAwaitingCount"', 'the Awaiting Capture count');
const campaignCapturePanelIdx = indexOfOrThrow(html, 'id="campaignCapturePanel"', 'the Campaign Administration panel');
[officialCapturePanelIdx, captureAwaitingIdx, campaignCapturePanelIdx].forEach((i) => {
  assert.ok(i > advancedSectionIdx, 'individual capture-queue/campaign administration UI must be nested inside the collapsed advanced section, not on the default home screen');
});

// --- 5. Nothing was deleted: every old capture control still exists, just relocated ---
['captureExportBtn', 'weeklyCaptureDownloadBtn', 'wardAssignmentsToggle', 'rosterToggle', 'exportXlsxBtn', 'printReportBtn', 'adminHistory']
  .forEach((id) => assert.ok(html.includes(`id="${id}"`), `${id} must still exist somewhere (moved, not deleted)`));

// The literal button-label text for the removed-from-home-screen actions
// must still exist in the source (dynamically rendered by renderCaptureRow),
// proving the capture workflow itself was not deleted.
assert.ok(html.includes("isAwaiting?'Mark Captured':'Undo Capture'"), 'Mark Captured control must still exist in the (now secondary) capture workflow');
assert.ok(html.includes('>Copy Details<'), 'Copy Details control must still exist in the (now secondary) capture workflow');

// --- 5b. Legacy comma-delimited CSV fallback is hidden, not deleted ---
// so the coordinator can't accidentally grab a locale-fragile CSV instead
// of one of the three proper .xlsx reports, but the backend endpoints and
// their frontend wiring stay fully intact for anything else that uses them.
const csvFallbackWrapperIdx = indexOfOrThrow(html, '<div id="smartsheetCsvFallback" hidden>', 'the hidden CSV fallback wrapper');
assert.ok(csvFallbackWrapperIdx > advancedSectionIdx, 'the CSV fallback wrapper must live inside the collapsed advanced section');
['exportSmartsheetCanvassing', 'exportSmartsheetPublic', 'exportSmartsheetPresence', 'exportSmartsheetAll'].forEach((id) => {
  const idIdx = indexOfOrThrow(html, `id="${id}"`, `the legacy CSV button ${id}`);
  assert.ok(idIdx > csvFallbackWrapperIdx, `${id} must be nested inside the hidden CSV fallback wrapper`);
});
// downloadSmartsheetCsv wiring itself must still exist untouched (the
// backend endpoints it calls stay intact for anything else that needs them).
assert.ok(html.includes('function downloadSmartsheetCsv('), 'the CSV download function must still exist, just no longer surfaced by default');
assert.ok(html.includes("downloadSmartsheetCsv(category, $(id), label)"), 'the CSV buttons must still be wired to their handler');

// --- 6. No duplicate element ids from the restructuring ---
['exportSmartsheetCanvassingXlsx', 'exportSmartsheetPublicXlsx', 'exportSmartsheetPresenceXlsx', 'coordinatorAdvancedToggle', 'coordinatorAdvanced', 'adminWeekBar']
  .forEach((id) => {
    const count = (html.match(new RegExp(`id="${id}"`, 'g')) || []).length;
    assert.strictEqual(count, 1, `${id} must appear exactly once (no duplicate ids)`);
  });

// --- 7. Leader dashboard is untouched by this change ---
assert.ok(html.includes('id="screenLeadership"'), 'the Leader dashboard screen must still exist');
assert.ok(!/screenLeadership[\s\S]{0,400}coordinatorAdvanced/.test(html), 'the Leader dashboard must not be nested inside the Coordinator advanced section');

console.log('coordinator-reports-ui.test.js OK');
