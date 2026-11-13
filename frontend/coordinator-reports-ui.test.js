const assert = require('assert');
const fs = require('fs');
const path = require('path');

// Coordinator workspace structure. The Reports tab is a simple place to
// generate the three existing SmartSheet reports (Canvassing,
// Public / Street Meetings, Presence) plus the auto-generated Ntsikana
// Activity Calendar. PHO Stage 2 (2026-11-12) supersedes the earlier layout
// that hid Official Capture behind a "Manage..." toggle: the workspace is now
// tabbed and Official Capture — the coordinator's daily job — is the default
// tab. Nothing about the underlying capture data, campaign administration,
// or the Leader dashboard may be removed — only relocated. These are
// structural checks against the real production markup (not a
// re-implementation), matching the convention in official-capture-ui.test.js.

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

// --- 3. Four reports, using the existing official category names ---
const canvassingBtnIdx = indexOfOrThrow(html, 'id="exportSmartsheetCanvassingXlsx"', 'the Canvassing report button');
const publicBtnIdx = indexOfOrThrow(html, 'id="exportSmartsheetPublicXlsx"', 'the Public / Street Meetings report button');
const presenceBtnIdx = indexOfOrThrow(html, 'id="exportSmartsheetPresenceXlsx"', 'the Presence report button');
const calendarViewBtnIdx = indexOfOrThrow(html, 'id="viewCalendarBtn"', 'the Ntsikana Canvassing Calendar "View Calendar" button');
const calendarDownloadBtnIdx = indexOfOrThrow(html, 'id="downloadCalendarBtn"', 'the Ntsikana Canvassing Calendar "Download Excel" button');
assert.ok(html.includes('>Canvassing Activities<'), 'the exact existing "Canvassing Activities" label must be used');
assert.ok(html.includes('>Public / Street Meetings<'), 'the exact existing "Public / Street Meetings" label must be used');
assert.ok(html.includes('>Presence Activities<'), 'the exact existing "Presence Activities" label must be used');
assert.ok(html.includes('>Ntsikana Canvassing Calendar<'), 'the calendar report card must use the exact "Ntsikana Canvassing Calendar" title');
assert.ok(
  html.includes('Automatically generated from canvassing activities and campaign plans.'),
  'the calendar report card helper line must be present'
);
[canvassingBtnIdx, publicBtnIdx, presenceBtnIdx, calendarViewBtnIdx].forEach((i) => {
  assert.ok(i > adminWeekBarIdx, 'each report button must appear after the reporting period control, on the home screen');
});
assert.ok(calendarViewBtnIdx > presenceBtnIdx, 'the calendar card must come after the three SmartSheet report cards');
assert.ok(calendarDownloadBtnIdx > calendarViewBtnIdx, 'the calendar card\'s Download Excel button must follow its View Calendar button');

// --- 3b. Direct month selection controls both View Calendar and Download Excel ---
const monthPickerIdx = indexOfOrThrow(html, 'id="calendarMonthPicker"', 'the calendar month picker');
assert.ok(html.includes('<input type="month" id="calendarMonthPicker">'), 'must be a native month input, the preferred simple implementation');
assert.ok(monthPickerIdx < calendarViewBtnIdx && monthPickerIdx < calendarDownloadBtnIdx, 'the month picker must appear before the buttons it controls');
assert.ok(
  html.includes("$('viewCalendarBtn').onclick") &&
  /\$\('viewCalendarBtn'\)\.onclick = \(\)=>\{[\s\S]{0,200}calendarMonthPicker/.test(html),
  'the View Calendar button handler must read the selected month from the picker'
);
assert.ok(
  /\$\('downloadCalendarBtn'\)\.onclick = \(\)=>downloadCalendarXlsx\(\$\('calendarMonthPicker'\)\.value/.test(html),
  'the Download Excel button on the home screen must read the selected month from the picker'
);

// --- 4. Operations-first workspace; capture workflow is retired from the UI ---
const tabOf = (name) => {
  const i = indexOfOrThrow(html, `data-coord-panel="${name}"`, `the ${name} tab panel`);
  const open = html.lastIndexOf('<section', i);
  return { open, tag: html.slice(open, html.indexOf('>', i) + 1) };
};
const activitiesPanel = tabOf('activities');
const reportsPanel = tabOf('reports');
const campaignsPanel = tabOf('campaigns');
const dataPanel = tabOf('data');
assert.ok(!/\shidden[\s>]/.test(activitiesPanel.tag), 'Activities is visible by default');
[reportsPanel,campaignsPanel,dataPanel].forEach((p)=>assert.ok(/\shidden[\s>]/.test(p.tag)));
assert.ok(html.includes('data-coord-tab="activities" aria-selected="true"'), 'Activities tab selected initially');
assert.ok(!html.includes('data-coord-tab="capture"'), 'no visible Official Capture tab');
assert.ok(activitiesPanel.open < reportsPanel.open && reportsPanel.open < campaignsPanel.open && campaignsPanel.open < dataPanel.open);
['coordinatorActivityWeek','coordinatorActivitySearch','coordinatorActivityList'].forEach(id=>assert.ok(html.includes(`id="${id}"`)));
assert.ok(html.includes('function renderCoordinatorActivities('));
assert.ok(!html.includes('await Promise.all([loadOfficialCapture()'), 'coordinator no longer loads legacy capture queue');
assert.ok(!html.includes('await Promise.all([loadCampaignCaptureAdmin()'), 'coordinator no longer loads legacy campaign capture');
assert.ok(h1Idx > reportsPanel.open && h1Idx < campaignsPanel.open, 'Reports heading still inside its tab');
const reportCardOpenings = html.match(/<div class="card coordinator-report-card">/g) || [];
assert.strictEqual(reportCardOpenings.length, 4);
const reportsSlice = html.slice(adminWeekBarIdx, indexOfOrThrow(html, 'Weekly submission report', 'weekly heading'));
assert.ok(adminWeekBarIdx > reportsPanel.open && adminWeekBarIdx < campaignsPanel.open);
assert.strictEqual((reportsSlice.match(/>Download Excel<\/button>/g)||[]).length,4);
assert.strictEqual((reportsSlice.match(/>View Calendar<\/button>/g)||[]).length,1);
// Historical fields and export handlers are retained but not accessible to users.
const captureIndex = indexOfOrThrow(html,'id="coordPanelCapture"','dormant capture panel');
assert.ok(html.slice(captureIndex,captureIndex+170).includes('display:none!important'));
const campaignCaptureIndex = indexOfOrThrow(html,'id="campaignCapturePanel"','dormant campaign capture panel');
assert.ok(html.slice(campaignCaptureIndex,campaignCaptureIndex+180).includes('display:none!important'));
['captureExportBtn','weeklyCaptureDownloadBtn','wardAssignmentsToggle','rosterToggle','exportXlsxBtn','printReportBtn','adminHistory']
 .forEach(id=>assert.ok(html.includes(`id="${id}"`),`${id} retained for compatibility`));

// --- 5b. Legacy comma-delimited CSV fallback is hidden, not deleted ---
// so the coordinator can't accidentally grab a locale-fragile CSV instead
// of one of the three proper .xlsx reports, but the backend endpoints and
// their frontend wiring stay fully intact for anything else that uses them.
const csvFallbackWrapperIdx = indexOfOrThrow(html, '<div id="smartsheetCsvFallback" hidden>', 'the hidden CSV fallback wrapper');
assert.ok(csvFallbackWrapperIdx > reportsPanel.open && csvFallbackWrapperIdx < campaignsPanel.open, 'the (hidden) CSV fallback wrapper stays with the SmartSheet export in the Reports tab');
['exportSmartsheetCanvassing', 'exportSmartsheetPublic', 'exportSmartsheetPresence', 'exportSmartsheetAll'].forEach((id) => {
  const idIdx = indexOfOrThrow(html, `id="${id}"`, `the legacy CSV button ${id}`);
  assert.ok(idIdx > csvFallbackWrapperIdx, `${id} must be nested inside the hidden CSV fallback wrapper`);
});
// downloadSmartsheetCsv wiring itself must still exist untouched (the
// backend endpoints it calls stay intact for anything else that needs them).
assert.ok(html.includes('function downloadSmartsheetCsv('), 'the CSV download function must still exist, just no longer surfaced by default');
assert.ok(html.includes("downloadSmartsheetCsv(category, $(id), label)"), 'the CSV buttons must still be wired to their handler');

// --- 6. No duplicate element ids from the restructuring ---
['exportSmartsheetCanvassingXlsx', 'exportSmartsheetPublicXlsx', 'exportSmartsheetPresenceXlsx', 'adminWeekBar', 'coordPanelCapture', 'coordPanelActivities', 'coordPanelReports', 'coordPanelCampaigns', 'coordPanelData']
  .forEach((id) => {
    const count = (html.match(new RegExp(`id="${id}"`, 'g')) || []).length;
    assert.strictEqual(count, 1, `${id} must appear exactly once (no duplicate ids)`);
  });

// --- 7. Leader dashboard is untouched by this change ---
assert.ok(html.includes('id="screenLeadership"'), 'the Leader dashboard screen must still exist');
assert.ok(html.indexOf('id="screenLeadership"') > dataPanel.open, 'the Leader dashboard must not be nested inside the coordinator workspace');
assert.ok(!html.slice(html.indexOf('id="screenLeadership"'), html.indexOf('<script src="./week-dates.js">')).includes('data-coord-panel'), 'no coordinator tab panel inside the Leader dashboard markup');

console.log('coordinator-reports-ui.test.js OK');
