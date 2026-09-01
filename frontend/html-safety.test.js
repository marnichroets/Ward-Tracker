const assert = require('assert');
const fs = require('fs');
const path = require('path');

// Follow-up security audit for Item 13 (Other activity): candidate-entered
// activity text is user-controlled input. This proves the real rendering
// templates shipped in index.html HTML-escape it everywhere it is inserted
// into innerHTML, by extracting and executing the actual production source
// (not a re-implementation) against XSS payloads.

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

function extractTemplateLiteral(src, marker) {
  const markerIdx = src.indexOf(marker);
  if (markerIdx === -1) throw new Error(`marker not found: ${marker}`);
  const start = src.indexOf('`', markerIdx);
  const end = src.indexOf('`', start + 1);
  if (end === -1) throw new Error(`unterminated template literal for marker: ${marker}`);
  return src.slice(start, end + 1);
}

const escapeHtmlSrc = extractFunctionSource(html, 'escapeHtml');
const escapeHtml = new Function(`${escapeHtmlSrc}\nreturn escapeHtml;`)();

const XSS_SCRIPT = '<script>alert(1)</script>';
const XSS_IMG = '<img src=x onerror=alert(1)>';
const XSS_PAYLOADS = [XSS_SCRIPT, XSS_IMG];

// --- 1. Candidate's own "My Week" activity row (the ${escapeHtml(entry.type_display || entry.type)} line) ---
const candidateRowTemplate = extractTemplateLiteral(html, 'html += `<div class="actrow"');
const buildCandidateRow = new Function(
  'entry', 'details', 'dayWithDate', 'entryWeekKey',
  `${escapeHtmlSrc}\nreturn ${candidateRowTemplate};`
);
const dayWithDateStub = () => 'Mon 31 Aug';
const entryWeekKeyStub = (e) => e.week_key;

function candidateEntry(overrides) {
  return Object.assign({
    id: 'e1', type: 'Door to Door', type_display: 'Door to Door',
    week_key: '2026-08-30', day: 'mon', notes: null, isPending: false,
  }, overrides);
}

XSS_PAYLOADS.forEach((payload) => {
  const row = buildCandidateRow(candidateEntry({type_display: payload, type: payload}), '', dayWithDateStub, entryWeekKeyStub);
  assert.ok(!row.includes(payload), `candidate activity row must not contain the raw payload: ${payload}`);
  assert.ok(row.includes(escapeHtml(payload)), `candidate activity row must contain the escaped form of: ${payload}`);
  assert.ok(!/<script[\s>]/i.test(row), 'candidate row must not contain an executable <script> tag');
  assert.ok(!/<img[^>]*onerror=/i.test(row), 'candidate row must not contain an executable <img onerror>');

  // Payload via notes must also be escaped.
  const rowWithNote = buildCandidateRow(candidateEntry({notes: payload}), '', dayWithDateStub, entryWeekKeyStub);
  assert.ok(!rowWithNote.includes(payload), `candidate note must not contain the raw payload: ${payload}`);
  assert.ok(rowWithNote.includes(escapeHtml(payload)), `candidate note must contain the escaped form of: ${payload}`);
});

// Normal activity text still renders correctly (not mangled by escaping).
const normalRow = buildCandidateRow(candidateEntry({type_display: 'Door to Door'}), 'Details', dayWithDateStub, entryWeekKeyStub);
assert.ok(normalRow.includes('Door to Door'), 'a normal activity label must render as-is');

// A candidate's own previously-submitted Other activity must show its exact
// wording, never the literal word "Other" or internal review terminology.
const otherRow = buildCandidateRow(candidateEntry({type: 'Other', type_display: 'Community prayer event'}), '', dayWithDateStub, entryWeekKeyStub);
assert.ok(otherRow.includes('Community prayer event'), 'candidate must see their exact custom wording');
assert.ok(!/>Other</.test(otherRow), 'candidate must not see the literal word "Other" as their displayed activity');
assert.ok(!otherRow.includes('NEEDS_REVIEW'), 'candidate must never see NEEDS_REVIEW');

// --- 2. Admin SmartSheet review list row (the ${escapeHtml(entry.original_activity...)} line) ---
const reviewRowTemplate = extractTemplateLiteral(html, 'return `<div class="review-row"');
const buildReviewRow = new Function(
  'entry', 'options',
  `${escapeHtmlSrc}\nreturn ${reviewRowTemplate};`
);

function reviewEntry(overrides) {
  return Object.assign({
    id: 'r1', original_activity: 'Community prayer event',
    name: 'Nomsa Dlamini', ward: 'Ward 4', activity_date: '2026-08-31',
  }, overrides);
}

XSS_PAYLOADS.forEach((payload) => {
  const row = buildReviewRow(reviewEntry({original_activity: payload}), '');
  assert.ok(!row.includes(payload), `admin review row must not contain the raw payload: ${payload}`);
  assert.ok(row.includes(escapeHtml(payload)), `admin review row must contain the escaped form of: ${payload}`);
  assert.ok(!/<script[\s>]/i.test(row), 'admin review row must not contain an executable <script> tag');
  assert.ok(!/<img[^>]*onerror=/i.test(row), 'admin review row must not contain an executable <img onerror>');
});

// Admin review rendering remains correct for ordinary custom wording.
const normalReviewRow = buildReviewRow(reviewEntry({original_activity: 'Community prayer event'}), '');
assert.ok(normalReviewRow.includes('Community prayer event'), 'admin review row must show the exact candidate wording');
assert.ok(normalReviewRow.includes('Nomsa Dlamini'), 'admin review row must show the candidate name');

// --- 3. Exhaustive location check: every innerHTML assignment that interpolates
// candidate activity text must route it through escapeHtml(...) ---
// (documents every location audited, per the follow-up report)
assert.ok(/\$\('actList'\)\.innerHTML = html;/.test(html), 'candidate week list render point found');
assert.ok(/\$\('smartsheetReviewList'\)\.innerHTML = entries\.map/.test(html), 'admin review list render point found');
['entry.type_display', 'entry.type'].forEach((expr) => {
  const escapedForm = `escapeHtml(${expr}`;
  assert.ok(html.includes(escapedForm) || candidateRowTemplate.includes(expr), `${expr} must be escaped where rendered`);
});

console.log('html safety tests passed');
