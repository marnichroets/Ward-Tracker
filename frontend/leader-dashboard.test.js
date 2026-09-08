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

// --- renderLeaderNotLogged / renderLeaderLogged: candidate names are HTML-escaped ---
{
  const notLoggedSrc = extractFunctionSource(html, 'renderLeaderNotLogged');
  const loggedSrc = extractFunctionSource(html, 'renderLeaderLogged');
  const wardDisplaySrc = extractFunctionSource(html, 'candidateWardDisplay');
  const XSS = '<img src=x onerror=alert(1)>';

  function run(src, fnName, rows) {
    const elements = {};
    function el(id) {
      if (!elements[id]) elements[id] = { innerHTML: '', textContent: '' };
      return elements[id];
    }
    const fn = new Function('$', 'escapeHtml', `${wardDisplaySrc}\n${src}\nreturn ${fnName};`)(el, new Function(`${escapeHtmlSrc}\nreturn escapeHtml;`)());
    fn(rows);
    return elements;
  }

  const notLoggedEls = run(notLoggedSrc, 'renderLeaderNotLogged', [{name: XSS, ward: 'Ward 4'}]);
  const notLoggedHtml = notLoggedEls.leaderNotLoggedList.innerHTML;
  assert.ok(!notLoggedHtml.includes(XSS), 'Has Not Logged row must not contain the raw payload');
  assert.ok(!/<img[^>]*onerror=/i.test(notLoggedHtml), 'Has Not Logged row must not contain an executable <img onerror>');

  const loggedEls = run(loggedSrc, 'renderLeaderLogged', [{name: XSS, ward: 'Ward 4', activities: 2, canvassing: 1}]);
  const loggedHtml = loggedEls.leaderLoggedList.innerHTML;
  assert.ok(!loggedHtml.includes(XSS), 'Who Logged row must not contain the raw payload');
  assert.ok(!/<img[^>]*onerror=/i.test(loggedHtml), 'Who Logged row must not contain an executable <img onerror>');

  console.log('renderLeaderLogged / renderLeaderNotLogged escaping tests passed');
}

// --- candidateWardDisplay: municipality + clean multi-ward list ---
{
  const src = extractFunctionSource(html, 'candidateWardDisplay');
  const fn = new Function(`${src}\nreturn candidateWardDisplay;`)();
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

// --- No manual date inputs remain in the Leadership export UI ---
{
  const reportsSectionMatch = html.match(/<section class="leader-section" id="leaderReportsSection">[\s\S]*?<\/section>/);
  assert.ok(reportsSectionMatch, 'Reporting & Export section must exist');
  const reportsSectionHtml = reportsSectionMatch[0];
  assert.ok(!/type="date"/.test(reportsSectionHtml), 'no manual date-picker fields may remain in Reporting & Export');
  assert.ok(!/\bFrom\b/.test(reportsSectionHtml), 'no "From" label may remain in Reporting & Export');
  assert.ok(!/\bTo\b/.test(reportsSectionHtml), 'no "To" label may remain in Reporting & Export');
  assert.ok(/id="leaderExportWeek"/.test(reportsSectionHtml), 'a week selector must be present');
  assert.ok(/Select Week/.test(reportsSectionHtml), 'the week selector must be labelled "Select Week"');
  assert.ok(/Download Excel Report/.test(reportsSectionHtml), 'the download button must remain');
  console.log('Reporting & Export UI has no manual date fields');
}

// --- The selected export week is passed to the export request as that week's Monday-Sunday range ---
{
  const weekStartYmdSrc = extractFunctionSource(html, 'weekStartYmd');
  const weekEndYmdSrc = extractFunctionSource(html, 'weekEndYmd');
  const downloadSrc = extractFunctionSource(html, 'downloadLeaderExcel');

  function run(exportWeekValue, leaderWeekKey) {
    const elements = {
      leaderExportWeek: { value: exportWeekValue },
      leaderExportBtn: { disabled: false, textContent: 'Download Excel Report' },
      leaderStatus: { className: '', textContent: '' },
    };
    let capturedParams = null;
    const fn = new Function('WeekDates', '$', 'leaderWeekKey', 'fetchLeaderExcelBlob', 'triggerBlobDownload', 'setLeaderStatus', `
      ${weekStartYmdSrc}
      ${weekEndYmdSrc}
      async ${downloadSrc}
      return downloadLeaderExcel();
    `);
    return fn(
      WeekDates,
      (id) => elements[id],
      leaderWeekKey,
      async (params) => { capturedParams = params; return 'blob'; },
      () => {},
      () => {}
    ).then(() => capturedParams);
  }

  run('2026-08-30', '2026-09-06').then((params) => {
    assert.strictEqual(params.get('preset'), 'custom');
    assert.strictEqual(params.get('date_from'), '2026-08-31', 'must use the SELECTED export week, not the dashboard week');
    assert.strictEqual(params.get('date_to'), '2026-09-06');
    assert.strictEqual(params.get('ward'), null, 'the weekly constituency report ignores the top ward filter');
    assert.strictEqual(params.get('person_id'), null, 'the weekly constituency report ignores the top candidate filter');
    console.log('downloadLeaderExcel uses the selected export week');
  });
}

// --- Main dashboard: no separate Canvassing Activities KPI, only 3 KPIs ---
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
    kpis: { total_activities: 5, total_canvassing: 2, active_campaigns: 1, wards_active: { active: 2, total: 4 } },
    comparison: {},
    period: { label: 'This week' },
  });
  assert.ok(html_out.includes('Total Activities'), 'Total Activities KPI must remain');
  assert.ok(html_out.includes('Wards Active'), 'Wards Active KPI must remain');
  assert.ok(html_out.includes('Active Campaigns'), 'Active Campaigns KPI must remain');
  assert.ok(!html_out.includes('Canvassing Activities'), 'the separate Canvassing Activities KPI must be removed from the main dashboard');
  assert.strictEqual((html_out.match(/leader-kpi/g) || []).length, 3, 'exactly 3 KPI cards must render');
  console.log('renderLeaderKpis no longer shows a Canvassing Activities card');
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
