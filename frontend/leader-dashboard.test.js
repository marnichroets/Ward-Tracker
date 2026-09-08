const assert = require('assert');
const fs = require('fs');
const path = require('path');
const WeekDates = require('./week-dates');

// Coordinator Leader dashboard: weekly navigation query-building and the
// "Who Logged" / "Has Not Logged" render functions, executed as the real
// production source extracted from index.html (not a re-implementation),
// matching the convention established in campaign-ui.test.js.

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
    else if (src[i] === '}') {
      depth--;
      if (depth === 0) { i++; break; }
    }
  }
  return src.slice(start, i);
}

const escapeHtmlSrc = extractFunctionSource(html, 'escapeHtml');

// --- leaderWeekLabelWithYear: Monday-Sunday range, with year shown ---
{
  const src = extractFunctionSource(html, 'leaderWeekLabelWithYear');
  const fn = new Function('WeekDates', `${src}\nreturn leaderWeekLabelWithYear;`)(WeekDates);
  assert.strictEqual(fn('2026-09-06'), '7 Sep – 13 Sep 2026');
  assert.strictEqual(fn(WeekDates.currentWeekKey(new Date('2026-08-30T22:01:00Z'))), '31 Aug – 6 Sep 2026');
  console.log('leaderWeekLabelWithYear tests passed');
}

// --- leaderQuery: always a Monday-Sunday custom range for the selected week ---
{
  const weekStartYmdSrc = extractFunctionSource(html, 'weekStartYmd');
  const weekEndYmdSrc = extractFunctionSource(html, 'weekEndYmd');
  const leaderQuerySrc = extractFunctionSource(html, 'leaderQuery');

  function buildQuery(leaderState, leaderWeekKey) {
    const fn = new Function('WeekDates', 'leaderState', 'leaderWeekKey', `
      ${weekStartYmdSrc}
      ${weekEndYmdSrc}
      ${leaderQuerySrc}
      return leaderQuery();
    `);
    return fn(WeekDates, leaderState, leaderWeekKey);
  }

  const qs = buildQuery({ward: '', personId: ''}, '2026-09-06');
  const params = new URLSearchParams(qs);
  assert.strictEqual(params.get('preset'), 'custom');
  assert.strictEqual(params.get('date_from'), '2026-09-07');
  assert.strictEqual(params.get('date_to'), '2026-09-13');
  assert.strictEqual(params.get('ward'), null, 'no ward filter must be omitted, not sent empty');
  assert.strictEqual(params.get('person_id'), null, 'no candidate filter must be omitted, not sent empty');

  const filtered = new URLSearchParams(buildQuery({ward: 'Ward 7', personId: 'john-smith'}, '2026-09-06'));
  assert.strictEqual(filtered.get('ward'), 'Ward 7');
  assert.strictEqual(filtered.get('person_id'), 'john-smith');

  console.log('leaderQuery weekly-range tests passed');
}

// --- renderLeaderNotLogged / renderWeeklyActivityTable: candidate names are HTML-escaped ---
{
  const notLoggedSrc = extractFunctionSource(html, 'renderLeaderNotLogged');
  const weeklyActivitySrc = extractFunctionSource(html, 'renderWeeklyActivityTable');
  const evidenceCountLabelSrc = extractFunctionSource(html, 'evidenceCountLabel');
  const wardOnlySrc = extractFunctionSource(html, 'wardOnlyDisplay');
  const wardDisplaySrc = extractFunctionSource(html, 'candidateWardDisplay');
  const XSS = '<img src=x onerror=alert(1)>';

  function run(src, fnName, arg, extraDeps) {
    const elements = {};
    function el(id) {
      if (!elements[id]) elements[id] = { innerHTML: '', textContent: '' };
      return elements[id];
    }
    const escapeHtml = new Function(`${escapeHtmlSrc}\nreturn escapeHtml;`)();
    const deps = Object.assign({ evidenceLinks: () => '' }, extraDeps || {});
    const fn = new Function(
      '$', 'escapeHtml', 'evidenceLinks',
      `${wardOnlySrc}\n${wardDisplaySrc}\n${evidenceCountLabelSrc}\n${src}\nreturn ${fnName};`
    )(el, escapeHtml, deps.evidenceLinks);
    fn(arg);
    return elements;
  }

  const notLoggedEls = run(notLoggedSrc, 'renderLeaderNotLogged', [{name: XSS, ward: 'Ward 4'}]);
  const notLoggedHtml = notLoggedEls.leaderNotLoggedList.innerHTML;
  assert.ok(!notLoggedHtml.includes(XSS), 'Has Not Logged row must not contain the raw payload');
  assert.ok(!/<img[^>]*onerror=/i.test(notLoggedHtml), 'Has Not Logged row must not contain an executable <img onerror>');

  const weeklyEls = run(weeklyActivitySrc, 'renderWeeklyActivityTable', {
    kpis: { candidate_participation: { submitted: 1, expected: 1 } },
    period: { label: 'This week' },
    weekly_activity: [{ candidate: XSS, ward: 'Ward 4', activity: 'Door to Door', venue: 'Hall', participant_count: 0, evidence_photo_count: 0 }],
  });
  const weeklyHtml = weeklyEls.leaderLoggedList.innerHTML;
  assert.ok(!weeklyHtml.includes(XSS), 'Live Weekly Activity Report row must not contain the raw payload');
  assert.ok(!/<img[^>]*onerror=/i.test(weeklyHtml), 'Live Weekly Activity Report row must not contain an executable <img onerror>');

  console.log('renderWeeklyActivityTable / renderLeaderNotLogged escaping tests passed');
}

// --- candidateWardDisplay: municipality + clean multi-ward list ---
{
  const src = extractFunctionSource(html, 'candidateWardDisplay');
  const wardOnlySrc = extractFunctionSource(html, 'wardOnlyDisplay');
  const fn = new Function(`${wardOnlySrc}\n${src}\nreturn candidateWardDisplay;`)();
  assert.strictEqual(fn({ward: 'Ward not assigned', municipality: ''}), 'Ward not assigned');
  assert.strictEqual(fn({ward: 'Ward 9', municipality: 'Amahlathi'}), 'Amahlathi — Ward 9');
  assert.strictEqual(
    fn({ward: 'Ward 2, Ward 3, Ward 7, Ward 10, Ward 11, Ward 14', municipality: 'Amahlathi'}),
    'Amahlathi — Wards 2, 3, 7, 10, 11, 14'
  );
  console.log('candidateWardDisplay tests passed');
}

// --- reportingWeekOptions: real, generated Monday-Sunday weeks (never hard-coded) ---
{
  const src = extractFunctionSource(html, 'reportingWeekOptions');
  const fn = new Function('WeekDates', 'CURRENT_WEEK_KEY', `${src}\nreturn reportingWeekOptions;`)(
    WeekDates, '2026-09-06'
  );
  const weeks = fn();
  assert.ok(weeks.length >= 8, 'should offer a practical range of weeks, not just the current one');
  assert.deepStrictEqual(weeks, [...new Set(weeks)], 'no duplicate weeks');
  weeks.forEach((wk) => {
    const start = WeekDates.reportingWeekStart(wk);
    const end = WeekDates.reportingWeekEnd(wk);
    assert.strictEqual(start.getDay(), 1, `${wk} must start on a Monday`);
    assert.strictEqual(end.getDay(), 0, `${wk} must end on a Sunday`);
    assert.strictEqual((end - start) / 86400000, 6, `${wk} must span exactly 7 days`);
  });
  assert.ok(weeks.includes('2026-09-06'), 'the current week must be one of the offered options');
  console.log('reportingWeekOptions generates real Monday-Sunday weeks');
}

// --- Reports hub: the duplicate top "Download Excel" button is gone ---
{
  assert.ok(!/id="leaderDownloadTop"/.test(html), 'the top Dashboard "Download Excel" button must be removed');
  assert.ok(!/function downloadLeaderExcelTop/.test(html), 'the now-unreachable top-button handler must be deleted, not left dead');
  assert.ok(!/id="leaderReportsSection"/.test(html), 'the old inline "Reporting & Export" card must be removed from the dashboard');
  assert.ok(!/id="leaderExportWeek"/.test(html), 'the old inline week selector must be removed');
  assert.ok(!/id="leaderExportBtn"/.test(html), 'the old inline export button must be removed');
  console.log('duplicate top Excel button and old inline Reports card are gone');
}

// --- Reports hub: dedicated Reports view exists with no manual date inputs ---
{
  function extractDivBlock(src, openTagNeedle) {
    const start = src.indexOf(openTagNeedle);
    if (start === -1) throw new Error(`could not find ${openTagNeedle} in index.html`);
    const tagEnd = src.indexOf('>', start);
    let depth = 1;
    let i = tagEnd + 1;
    const tagRe = /<div\b|<\/div>/g;
    tagRe.lastIndex = i;
    let m;
    while ((m = tagRe.exec(src))) {
      if (m[0] === '<div') depth++; else depth--;
      if (depth === 0) { i = tagRe.lastIndex; break; }
    }
    return src.slice(start, i);
  }

  const viewHtml = extractDivBlock(html, '<div id="leaderReportsView"');
  assert.ok(!/type="date"/.test(viewHtml), 'no manual date-picker fields may exist in the Reports view');
  assert.ok(/id="leaderReportsWeek"/.test(viewHtml), 'a week selector must be present');
  assert.ok(/Select Week/.test(viewHtml), 'the week selector must be labelled "Select Week"');
  assert.ok(/id="leaderReportsMunicipality"/.test(viewHtml), 'a municipality selector must be present');
  assert.ok(/Back to Dashboard/.test(viewHtml), 'a clear way back to the dashboard must be present');
  ['Weekly Excel Report', 'Weekly PDF Report', 'Municipality Activity Report', 'Weekly Activity Submission Update', 'Activity Trend Report'].forEach((title) => {
    assert.ok(viewHtml.includes(title), `report card "${title}" must be present`);
  });
  // Card order must match the spec exactly.
  const order = ['Weekly Excel Report', 'Weekly PDF Report', 'Municipality Activity Report', 'Weekly Activity Submission Update', 'Activity Trend Report']
    .map((title) => viewHtml.indexOf(title));
  assert.deepStrictEqual(order, [...order].sort((a, b) => a - b), 'report cards must appear in the specified order');
  assert.ok(viewHtml.includes('Do NOT show candidates who have not logged') === false, 'sanity: this is UI copy, not the internal spec text');
  console.log('Reports view exists with week/municipality selectors and the five report cards in order');
}

// --- Reports hub: Weekly Excel/PDF downloads use the selected report week, ignore ward/candidate filters ---
{
  const weekStartYmdSrc = extractFunctionSource(html, 'weekStartYmd');
  const weekEndYmdSrc = extractFunctionSource(html, 'weekEndYmd');
  const filenameSrc = extractFunctionSource(html, 'weeklyReportFilename');
  const safeLabelSrc = extractFunctionSource(html, 'safeFilenameLabel');
  const paramsSrc = extractFunctionSource(html, 'reportsWeekParams');
  const selectedWeekSrc = extractFunctionSource(html, 'reportsSelectedWeekKey');
  const statusSrc = extractFunctionSource(html, 'setLeaderReportsStatus');
  const runDownloadSrc = extractFunctionSource(html, 'runReportDownload');
  const excelSrc = extractFunctionSource(html, 'downloadWeeklyExcelReport');

  function run(exportWeekValue) {
    const elements = {
      leaderReportsWeek: { value: exportWeekValue },
      reportWeeklyExcelBtn: { disabled: false, textContent: 'Download Excel' },
      leaderReportsStatus: { className: '', textContent: '' },
    };
    let capturedParams = null;
    const fn = new Function('WeekDates', '$', 'leaderWeekKey', 'CURRENT_WEEK_KEY', 'fetchLeaderExcelBlob', 'triggerBlobDownload', `
      ${weekStartYmdSrc}
      ${weekEndYmdSrc}
      ${safeLabelSrc}
      ${filenameSrc}
      ${paramsSrc}
      ${selectedWeekSrc}
      ${statusSrc}
      async ${runDownloadSrc}
      async ${excelSrc}
      return downloadWeeklyExcelReport();
    `);
    return fn(
      WeekDates,
      (id) => elements[id],
      '2026-09-06',
      '2026-09-06',
      async (params) => { capturedParams = params; return 'blob'; },
      () => {}
    ).then(() => capturedParams);
  }

  run('2026-08-30').then((params) => {
    assert.strictEqual(params.get('preset'), 'custom');
    assert.strictEqual(params.get('date_from'), '2026-08-31', 'must use the SELECTED report week, not the dashboard week');
    assert.strictEqual(params.get('date_to'), '2026-09-06');
    assert.strictEqual(params.get('ward'), null, 'the weekly report ignores the dashboard ward filter');
    assert.strictEqual(params.get('person_id'), null, 'the weekly report ignores the dashboard candidate filter');
    console.log('downloadWeeklyExcelReport uses the selected report week and ignores ward/candidate filters');
  });
}

// --- Reports hub: filenames match the exact convention from the spec ---
{
  const weekStartYmdSrc = extractFunctionSource(html, 'weekStartYmd');
  const weekEndYmdSrc = extractFunctionSource(html, 'weekEndYmd');
  const safeLabelSrc = extractFunctionSource(html, 'safeFilenameLabel');
  const filenameSrc = extractFunctionSource(html, 'weeklyReportFilename');
  const fn = new Function('WeekDates', `${weekStartYmdSrc}\n${weekEndYmdSrc}\n${safeLabelSrc}\n${filenameSrc}\nreturn weeklyReportFilename;`)(WeekDates);

  assert.strictEqual(fn('2026-09-06', null, 'xlsx'), 'Ntsikana_Weekly_Report_2026-09-07_to_2026-09-13.xlsx');
  assert.strictEqual(fn('2026-09-06', 'Amahlathi', 'pdf'), 'Amahlathi_Weekly_Report_2026-09-07_to_2026-09-13.pdf');
  assert.strictEqual(fn('2026-09-06', 'Raymond Mhlaba', 'pdf'), 'Raymond_Mhlaba_Weekly_Report_2026-09-07_to_2026-09-13.pdf');
  assert.ok(/^[A-Za-z0-9_-]+\.pdf$/.test(fn('2026-09-06', 'Raymond / Mhlaba!!', 'pdf')), 'unsafe municipality text must be sanitized out of the filename');
  console.log('weeklyReportFilename matches the exact naming convention from the spec');
}

// --- Reports hub: Wednesday/Trend filenames follow the spec's naming convention ---
{
  const wednesdaySrc = extractFunctionSource(html, 'wednesdayReportFilename');
  const trendSrc = extractFunctionSource(html, 'trendReportFilename');
  const wed = new Function('WeekDates', 'CURRENT_WEEK_KEY', `${wednesdaySrc}\nreturn wednesdayReportFilename;`)(WeekDates, WeekDates.currentWeekKey());
  assert.ok(/^Ntsikana_Activity_Update_\d{4}-\d{2}-\d{2}\.pdf$/.test(wed()), 'Wednesday report filename must match Ntsikana_Activity_Update_<date>.pdf');

  const weekStartYmdSrc = extractFunctionSource(html, 'weekStartYmd');
  const weekEndYmdSrc = extractFunctionSource(html, 'weekEndYmd');
  const trend = new Function('WeekDates', 'CURRENT_WEEK_KEY', `${weekStartYmdSrc}\n${weekEndYmdSrc}\n${trendSrc}\nreturn trendReportFilename;`)(WeekDates, '2026-09-06');
  assert.strictEqual(trend(8), 'Ntsikana_Activity_Trend_2026-07-20_to_2026-09-13.pdf');
  console.log('wednesdayReportFilename / trendReportFilename match the spec naming convention');
}

// --- Reports hub: opening/closing the Reports view toggles dashboard chrome, never the dashboard's own week/filter bar at the same time ---
{
  const openSrc = extractFunctionSource(html, 'openLeaderReports');
  const backSrc = extractFunctionSource(html, 'leaderDetailBack');
  const chromeSrc = extractFunctionSource(html, 'showLeaderChrome');
  const controlsSrc = extractFunctionSource(html, 'populateLeaderReportsControls');
  const weekLabelSrc = extractFunctionSource(html, 'leaderWeekLabelWithYear');
  const weekOptsSrc = extractFunctionSource(html, 'reportingWeekOptions');
  const statusSrc = extractFunctionSource(html, 'setLeaderReportsStatus');

  const elements = {
    leaderDashboardView: { hidden: false },
    leaderWardDetailView: { hidden: false },
    leaderCampaignDetailView: { hidden: false },
    leaderReportsView: { hidden: true },
    leaderReportsWeek: { innerHTML: '', value: '' },
    leaderReportsMunicipality: { innerHTML: '', value: '' },
    leaderReportsStatus: { className: '', textContent: '' },
  };
  const chromeEls = { weekbar: { hidden: false }, filterbar: { hidden: false } };
  const doc = {
    querySelector: (sel) => (sel === '.leader-weekbar' ? chromeEls.weekbar : chromeEls.filterbar),
  };

  const fn = new Function(
    'WeekDates', 'CURRENT_WEEK_KEY', 'leaderWeekKey', 'leaderState', 'leaderData', '$', 'escapeHtml', 'document',
    `${weekOptsSrc}\n${weekLabelSrc}\n${chromeSrc}\n${statusSrc}\n${controlsSrc}\n${openSrc}\n${backSrc}\nreturn {openLeaderReports, leaderDetailBack};`
  )(WeekDates, '2026-09-06', '2026-09-06', {ward:'', personId:'', municipality:''}, {filter_options:{municipalities:[]}}, (id) => elements[id], (s) => s, doc);

  fn.openLeaderReports();
  assert.strictEqual(elements.leaderReportsView.hidden, false, 'Reports view must open');
  assert.strictEqual(elements.leaderDashboardView.hidden, true, 'Dashboard view must hide while Reports is open');
  assert.strictEqual(chromeEls.weekbar.hidden, true, 'the dashboard week-nav bar must hide while Reports is open');
  assert.strictEqual(chromeEls.filterbar.hidden, true, 'the dashboard ward/candidate/municipality filter bar must hide while Reports is open');

  fn.leaderDetailBack();
  assert.strictEqual(elements.leaderReportsView.hidden, true, 'Back to Dashboard must close the Reports view');
  assert.strictEqual(elements.leaderDashboardView.hidden, false, 'Back to Dashboard must restore the dashboard view');
  assert.strictEqual(chromeEls.weekbar.hidden, false, 'Back to Dashboard must restore the week-nav bar');
  assert.strictEqual(chromeEls.filterbar.hidden, false, 'Back to Dashboard must restore the filter bar');
  console.log('openLeaderReports/leaderDetailBack correctly toggle the dedicated Reports view and dashboard chrome');
}

// --- Main dashboard: exactly 4 KPIs — Total Activities, Canvassing Activities, Wards Active, Active Campaigns ---
{
  const src = extractFunctionSource(html, 'renderLeaderKpis');

  function run(data) {
    const elements = { leaderKpis: { innerHTML: '' } };
    const fn = new Function(
      '$', 'escapeHtml', 'leaderComparisonNote', 'leaderRatioText',
      `${src}\nreturn renderLeaderKpis;`
    )((id) => elements[id], (s) => s, () => '', (r) => `${r.active}/${r.total}`);
    fn(data);
    return elements.leaderKpis.innerHTML;
  }

  const html_out = run({
    kpis: {
      total_activities: 5, total_canvassing: 2, active_campaigns: 1,
      wards_active: { active: 2, total: 4 },
      candidate_participation: { submitted: 8, expected: 24 },
    },
    comparison: {},
    period: { label: 'This week' },
  });
  assert.ok(html_out.includes('Total Activities'), 'Total Activities KPI must remain');
  assert.ok(html_out.includes('Canvassing Activities'), 'Canvassing Activities KPI must be restored to the top KPI cards');
  assert.ok(html_out.includes('Wards Active'), 'Wards Active KPI must be restored to the top KPI cards');
  assert.ok(html_out.includes('2/4'), 'Wards Active must show active/total as X/Y');
  assert.ok(html_out.includes('Active Campaigns'), 'Active Campaigns KPI must remain');
  assert.ok(!html_out.includes('Candidates Who Logged'), 'candidate participation is now a small line near the live report, not a top KPI card');
  assert.strictEqual((html_out.match(/leader-kpi/g) || []).length, 4, 'exactly 4 KPI cards must render');
  console.log('renderLeaderKpis shows exactly Total Activities / Canvassing Activities / Wards Active / Active Campaigns');
}

// --- Main dashboard chart: "Activities This Week", daily totals sum to Total Activities ---
{
  assert.ok(html.includes('<h2>Activities This Week</h2>'), 'the main dashboard chart must be retitled "Activities This Week"');
  assert.ok(!html.includes('<h2>Canvassing This Week</h2>'), 'the old "Canvassing This Week" heading must be gone');

  const markupSrc = extractFunctionSource(html, 'dailyActivitiesMarkup');
  const fn = new Function('escapeHtml', `${markupSrc}\nreturn dailyActivitiesMarkup;`)((s) => s);

  const days = [
    { date: '2026-09-07', label: 'Mon 7 Sep', total: 2, is_future: false },
    { date: '2026-09-08', label: 'Tue 8 Sep', total: 1, is_future: false },
    { date: '2026-09-09', label: 'Wed 9 Sep', total: 0, is_future: false },
    { date: '2026-09-10', label: 'Thu 10 Sep', total: 3, is_future: false },
    { date: '2026-09-11', label: 'Fri 11 Sep', total: 0, is_future: true },
    { date: '2026-09-12', label: 'Sat 12 Sep', total: 0, is_future: true },
    { date: '2026-09-13', label: 'Sun 13 Sep', total: 0, is_future: true },
  ];
  const markup = fn(days);
  assert.ok(markup.includes('All activities logged per day.'), 'chart subtitle must describe all activities, not just canvassing');
  assert.ok(!markup.toLowerCase().includes('canvassing'), 'the chart must no longer mention canvassing');
  const total = days.reduce((sum, d) => sum + d.total, 0);
  assert.strictEqual(total, 6, 'sanity check on the fixture itself');
  console.log('dailyActivitiesMarkup renders an all-activities chart with no canvassing reference');
}

// --- renderLeaderTrend wires daily_activities + the activities comparison, not canvassing ---
{
  const src = extractFunctionSource(html, 'renderLeaderTrend');
  const elements = { leaderTrendLabel: { innerHTML: '' }, leaderTrend: { innerHTML: '' } };
  let capturedDays = null;
  const fn = new Function(
    '$', 'escapeHtml', 'leaderChangeClass', 'dailyActivitiesMarkup',
    `${src}\nreturn renderLeaderTrend;`
  )(
    (id) => elements[id],
    (s) => s,
    () => 'flat',
    (days) => { capturedDays = days; return '<div>chart</div>'; }
  );
  const data = {
    comparison: { activities: { label: 'Up 10% vs last week' }, canvassing: { label: 'Down 5% vs last week' } },
    daily_activities: [{ date: '2026-09-07', label: 'Mon 7 Sep', total: 4, is_future: false }],
  };
  fn(data);
  assert.ok(elements.leaderTrendLabel.innerHTML.includes('Up 10%'), 'the trend label must reflect the activities comparison, not canvassing');
  assert.deepStrictEqual(capturedDays, data.daily_activities, 'the chart must be fed daily_activities');
  console.log('renderLeaderTrend uses daily_activities and the activities comparison');
}

// --- Ward Performance and Latest Activity are removed from the main dashboard ---
{
  // Ward Performance: the large performance table is gone (candidates can
  // legitimately manage multiple wards, so a ward-vs-ward table is
  // misleading) — but this is a UI-only removal, never a data/backend one.
  assert.ok(!html.includes('<h2>Ward Performance</h2>'), 'the Ward Performance heading must be removed from the dashboard');
  assert.ok(!html.includes('id="leaderWardSection"'), 'the Ward Performance section wrapper must be removed');
  assert.ok(!html.includes('id="leaderWardPerformance"'), 'the Ward Performance render target must be removed');
  assert.ok(!html.includes('data-leader-jump="leaderWardSection"'), 'the "Wards" nav link must be removed along with its only target section');
  assert.ok(!/function renderLeaderWardPerformance/.test(html), 'the now-unreachable Ward Performance renderer must be deleted, not left dead');
  assert.ok(!/async function openLeaderWard\(/.test(html), 'the now-unreachable ward drill-down loader must be deleted, not left dead');
  assert.ok(!/function leaderStatusClass/.test(html), 'the now-unreachable ward status-pill helper must be deleted, not left dead');
  assert.ok(!html.includes('ward ranking') && !html.includes('leaderboard') && !html.includes('"best ward"') && !html.includes('"worst ward"'), 'no ward/candidate ranking or scoring must be introduced in its place');

  // Latest Activity: removed from the dashboard UI, but renderLeaderActivities
  // itself must remain — the campaign detail view still uses it.
  assert.ok(!html.includes('<h2>Latest Activity</h2>'), 'the Latest Activity heading must be removed from the dashboard');
  assert.ok(!html.includes('id="leaderActivitySection"'), 'the Latest Activity section wrapper must be removed');
  assert.ok(!html.includes('id="leaderActivityFeed"'), 'the Latest Activity render target must be removed');
  assert.ok(!html.includes('data-leader-jump="leaderActivitySection"'), 'the "Activities" nav link must be removed along with its only target section');
  assert.ok(/function renderLeaderActivities/.test(html), 'renderLeaderActivities must remain — the campaign detail view still calls it');
  assert.ok(!/data\.latest_activity/.test(html), 'the dashboard must no longer render dashboard.latest_activity anywhere');

  console.log('Ward Performance and Latest Activity removed from the main dashboard; no ranking/scoring introduced');
}

// --- Live Weekly Activity Report: columns, chronological data, participants/evidence display ---
{
  const src = extractFunctionSource(html, 'renderWeeklyActivityTable');
  const wardOnlySrc = extractFunctionSource(html, 'wardOnlyDisplay');
  const evidenceCountLabelSrc = extractFunctionSource(html, 'evidenceCountLabel');

  function run(data, evidenceLinksImpl) {
    const elements = { leaderLoggedCount: { textContent: '' }, leaderWeeklyActivitySubtitle: { textContent: '' }, leaderLoggedList: { innerHTML: '' } };
    const fn = new Function(
      '$', 'escapeHtml', 'evidenceLinks',
      `${wardOnlySrc}\n${evidenceCountLabelSrc}\n${src}\nreturn renderWeeklyActivityTable;`
    )((id) => elements[id], (s) => s, evidenceLinksImpl || (() => ''));
    fn(data);
    return elements;
  }

  const els = run({
    period: { label: '7 Sep – 13 Sep 2026' },
    kpis: { candidate_participation: { submitted: 5, expected: 24 } },
    weekly_activity: [
      { activity_date: '2026-09-07', date_label: '7 Sep', candidate: 'Ndileka Ngxakangxaka', municipality: 'Amahlathi', ward: 'Ward 6', activity: 'Door to Door', venue: 'Mlungisi', participant_count: 3, evidence_photo_count: 1, evidence_photos: [{id: 'p1'}], person_id: 'ndileka' },
      { activity_date: '2026-09-08', date_label: '8 Sep', candidate: 'Willem Pieter Bezuidenhout', municipality: 'Raymond Mhlaba', ward: 'Ward 7', activity: 'Door to Door', venue: 'Adelaide', participant_count: 0, evidence_photo_count: 2, evidence_photos: [{id: 'p2'}, {id: 'p3'}], person_id: 'willem' },
    ],
  });

  assert.ok(els.leaderWeeklyActivitySubtitle.textContent.includes('7 Sep – 13 Sep 2026'), 'subtitle must show the selected week period');
  assert.ok(els.leaderWeeklyActivitySubtitle.textContent.includes('5') && els.leaderWeeklyActivitySubtitle.textContent.includes('24'), 'subtitle must show "Candidates reporting: X / Y"');
  const rowsHtml = els.leaderLoggedList.innerHTML;
  assert.ok(rowsHtml.includes('>Date<') && rowsHtml.includes('>Candidate<') && rowsHtml.includes('>Municipality<') && rowsHtml.includes('>Ward<') && rowsHtml.includes('>Activity<') && rowsHtml.includes('>Venue / Area<') && rowsHtml.includes('>Participants<') && rowsHtml.includes('>Evidence<'), 'table headers must match the required column set');
  assert.ok(rowsHtml.includes('Ndileka Ngxakangxaka') && rowsHtml.includes('Willem Pieter Bezuidenhout'));
  assert.ok(rowsHtml.includes('3'), 'a non-zero participant count must show as a number');
  assert.ok(rowsHtml.includes('1 photo'), 'evidence count must show as "1 photo"');
  assert.ok(rowsHtml.includes('2 photos'), 'evidence count must show as "2 photos"');

  const emptyEls = run({ period: { label: 'This week' }, kpis: {}, weekly_activity: [] });
  assert.ok(/No activity recorded/.test(emptyEls.leaderLoggedList.innerHTML));

  console.log('renderWeeklyActivityTable renders the required columns and reconciles with the KPI participation line');
}

// --- openLeaderCampaign: regression for "Could not load this campaign" on a valid campaign ---
// Root cause: openLeaderCampaign called a trendMarkup(...) helper that no
// longer existed in the file (removed as part of an earlier Ward
// Performance cleanup) — the ReferenceError was swallowed by the catch
// block and always rendered the generic error state. This test extracts
// the real production function and proves a valid API response now
// renders full detail instead of falling into that catch.
{
  const openLeaderCampaignSrc = extractFunctionSource(html, 'openLeaderCampaign');
  const renderLeaderActivitiesSrc = extractFunctionSource(html, 'renderLeaderActivities');
  const wardOnlySrc = extractFunctionSource(html, 'wardOnlyDisplay');

  assert.ok(!html.includes('trendMarkup'), 'no reference to the deleted trendMarkup helper may remain anywhere in the file');

  const elements = {
    leaderDashboardView: { hidden: false },
    leaderWardDetailView: { hidden: false },
    leaderCampaignDetailView: { hidden: true, innerHTML: '' },
  };
  function el(id) {
    if (!elements[id]) elements[id] = { innerHTML: '', textContent: '', onclick: null };
    return elements[id];
  }
  const escapeHtml = new Function(`${escapeHtmlSrc}\nreturn escapeHtml;`)();
  const campaignPayload = {
    campaign: {
      id: 'camp1', name: 'Ndileka Ngxakangxaka', candidate: 'Ndileka Ngxakangxaka (CLLR)',
      municipality: 'Amahlathi', ward: 'Ward 6', purpose: '', start_date: '2026-09-05', end_date: '2026-09-23',
      duration_days: 19, duration: '19 days', status: 'active',
      week_progress: { current: 1, total: 3, label: 'Week 1 of 3' }, activities: 4, canvassing: 4,
    },
    activities: [
      { id: 'a1', candidate: 'Ndileka Ngxakangxaka (CLLR)', ward: 'Ward 6', activity: 'Door to Door', activity_date: '2026-09-07', date_label: 'Yesterday', venue: 'Kubusie Village', participant_count: 0, evidence_photo_count: 0, evidence_photos: [], person_id: 'ndileka' },
    ],
    canvassing_trend: { weeks: [], has_history: false },
  };
  let apiCalledWith = null;
  const api = async (path, opts) => { apiCalledWith = { path, opts }; return campaignPayload; };
  const evidenceLinks = () => '';

  const fn = new Function(
    '$', 'escapeHtml', 'api', 'leaderHeaders', 'evidenceLinks', 'leaderDetailBack', 'document',
    `${wardOnlySrc}\n${renderLeaderActivitiesSrc}\nasync ${openLeaderCampaignSrc}\nreturn openLeaderCampaign;`
  )(el, escapeHtml, api, () => ({}), evidenceLinks, () => {}, { querySelectorAll: () => [] });

  fn('camp1').then(() => {
    assert.ok(apiCalledWith && apiCalledWith.path === '/api/leader/campaigns/camp1', 'must call the campaign detail endpoint with the clicked campaign id');
    const html_out = elements.leaderCampaignDetailView.innerHTML;
    assert.ok(!/Could not load this campaign/.test(html_out), 'a valid campaign response must never fall through to the error state');
    assert.ok(html_out.includes('Ndileka Ngxakangxaka'), 'campaign name must render');
    assert.ok(html_out.includes('Week 1 of 3'), 'current progress must render');
    assert.ok(html_out.includes('3 weeks'), 'duration must render in weeks, not raw days');
    assert.ok(html_out.includes('Back to Dashboard'), 'a clear way back to the dashboard must be present');
    assert.ok(html_out.includes('Activities in this campaign'));
    assert.ok(html_out.includes('No purpose added'), 'a blank purpose must fall back to this exact text');
    console.log('openLeaderCampaign renders full detail for a valid campaign (regression: "Could not load this campaign")');
  });
}
