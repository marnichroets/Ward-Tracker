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
  const XSS = '<img src=x onerror=alert(1)>';

  function run(src, fnName, rows) {
    const elements = {};
    function el(id) {
      if (!elements[id]) elements[id] = { innerHTML: '', textContent: '' };
      return elements[id];
    }
    const fn = new Function('$', 'escapeHtml', `${src}\nreturn ${fnName};`)(el, new Function(`${escapeHtmlSrc}\nreturn escapeHtml;`)());
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
