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
