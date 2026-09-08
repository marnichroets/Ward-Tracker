const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const WeekDates = require('./week-dates');
const SmartSheetActivities = require('./smartsheet-activities');
const TimeOptions = require('./time-options');

// Whole-script load smoke test. Individual functions are unit-tested by
// extracting their source elsewhere (campaign-ui.test.js, html-safety.test.js,
// etc.), but none of those catch a dangling top-level statement that calls a
// function no longer defined (a ReferenceError thrown while the script's
// top-level statements run in order) — exactly the bug this test reproduces:
// a leftover `syncLeaderCustomDates();` init call survived a refactor that
// deleted that function, silently breaking every event binding physically
// below it in the file (admin export/print buttons included), because a
// classic <script> tag halts remaining top-level statements after an
// uncaught synchronous exception, even though hoisted function declarations
// above/below it stay callable.
//
// This test actually executes the production <script> body (not a
// reimplementation) against a minimal element/browser stub, then asserts
// specific bindings load-bearing to real features actually landed —
// bindings physically late in the file, so this only passes if every
// top-level statement before them ran without throwing.

const html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');
const scriptMatch = html.match(/<script>([\s\S]*?)<\/script>/);
if (!scriptMatch) throw new Error('could not find the inline <script> body in index.html');
const scriptSrc = scriptMatch[1];

function makeElementStub(id) {
  const el = {
    id,
    value: '',
    textContent: '',
    innerHTML: '',
    hidden: false,
    disabled: false,
    checked: false,
    className: '',
    style: {},
    dataset: {},
    children: [],
    classList: {
      add() {}, remove() {}, toggle() {}, contains() { return false; },
    },
    onclick: null, onchange: null, oninput: null, onsubmit: null,
    addEventListener() {}, removeEventListener() {},
    appendChild(child) { el.children.push(child); return child; },
    removeChild() {}, remove() {}, click() {}, focus() {}, blur() {},
    scrollIntoView() {}, closest() { return null; },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    getAttribute() { return null; }, setAttribute() {}, removeAttribute() {},
  };
  return el;
}

function buildSandbox() {
  const elements = new Map();
  const storage = new Map();
  const documentStub = {
    getElementById(id) {
      if (!elements.has(id)) elements.set(id, makeElementStub(id));
      return elements.get(id);
    },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    createElement() { return makeElementStub(null); },
    addEventListener() {}, removeEventListener() {},
    title: '',
    body: makeElementStub('body'),
  };
  const localStorageStub = {
    getItem(key) { return storage.has(key) ? storage.get(key) : null; },
    setItem(key, value) { storage.set(key, String(value)); },
    removeItem(key) { storage.delete(key); },
  };
  const sandbox = {
    console,
    WeekDates,
    SmartSheetActivities,
    TimeOptions,
    document: documentStub,
    window: { addEventListener() {}, removeEventListener() {}, location: { reload() {}, hash: '' } },
    navigator: {},
    location: { reload() {}, href: '', hash: '' },
    localStorage: localStorageStub,
    fetch() { return Promise.reject(new Error('fetch is not available in this smoke test')); },
    alert() {}, confirm() { return false; }, prompt() { return null; },
    URLSearchParams, FormData: class { append() {} },
    Blob: class {}, URL: { createObjectURL() { return ''; }, revokeObjectURL() {} },
    // No-op stand-ins: this is a load-time smoke test, not a timer test, and
    // a real Node timer would otherwise keep the process alive waiting on it.
    setTimeout() { return 0; }, clearTimeout() {},
    setInterval() { return 0; }, clearInterval() {},
    Date, Math, JSON, Intl,
  };
  sandbox.globalThis = sandbox;
  return { sandbox, elements };
}

const { sandbox, elements } = buildSandbox();
vm.createContext(sandbox);

assert.doesNotThrow(() => {
  vm.runInContext(scriptSrc, sandbox, { filename: 'index.html-inline-script.js' });
}, 'the production script must execute top to bottom without throwing');

// Bindings physically near the very end of the script (admin export/print,
// which is exactly what this bug silently broke) — proof execution reached
// the bottom of the file, not just past the specific line that used to throw.
assert.strictEqual(typeof elements.get('exportXlsxBtn').onclick, 'function', 'admin Export report (Excel) button must be wired');
assert.strictEqual(typeof elements.get('exportBtn').onclick, 'function', 'admin Raw backup (CSV) button must be wired');
assert.strictEqual(typeof elements.get('printReportBtn').onclick, 'function', 'admin Print Report button must be wired');

// Leadership dashboard bindings this session's own feature work depends on.
assert.strictEqual(typeof elements.get('leaderPrevWeek').onclick, 'function');
assert.strictEqual(typeof elements.get('leaderNextWeek').onclick, 'function');
assert.strictEqual(typeof elements.get('leaderNavReports').onclick, 'function');
assert.strictEqual(typeof elements.get('reportWeeklyExcelBtn').onclick, 'function');
assert.strictEqual(typeof elements.get('reportTrendPdfBtn').onclick, 'function');

console.log('full script load smoke test passed');
