const assert = require('assert');
const fs = require('fs');
const path = require('path');

const {TIME_OPTIONS, BLANK_LABEL} = require('./time-options');

// --- time-options.js data ---
assert.strictEqual(BLANK_LABEL, 'Select time');
assert.strictEqual(TIME_OPTIONS[0], '06:00');
assert.strictEqual(TIME_OPTIONS[TIME_OPTIONS.length - 1], '22:00');
['06:00', '06:30', '12:00', '12:30', '21:30', '22:00'].forEach((t) => {
  assert.ok(TIME_OPTIONS.includes(t), `expected ${t} in TIME_OPTIONS`);
});
assert.ok(!TIME_OPTIONS.includes('22:30'), '22:30 is past the last allowed slot');
assert.ok(!TIME_OPTIONS.includes('05:30'), '05:30 is before the first allowed slot');

TIME_OPTIONS.forEach((t) => {
  assert.ok(/^([01]\d|2[0-3]):[0-5]\d$/.test(t), `${t} must be HH:MM 24-hour`);
});

const seen = new Set(TIME_OPTIONS);
assert.strictEqual(seen.size, TIME_OPTIONS.length, 'time options should not be duplicated');

for (let i = 1; i < TIME_OPTIONS.length; i++) {
  const [ph, pm] = TIME_OPTIONS[i - 1].split(':').map(Number);
  const [ch, cm] = TIME_OPTIONS[i].split(':').map(Number);
  const prevMinutes = ph * 60 + pm;
  const curMinutes = ch * 60 + cm;
  assert.strictEqual(curMinutes - prevMinutes, 30, `options must be exactly 30 minutes apart at index ${i}`);
}

// --- index.html: native time picker replaced with selects ---
const html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');
assert.ok(!/type=["']time["']/.test(html), 'native type="time" input must no longer be used');
assert.ok(/<select[^>]*\bid="fStartTime"/.test(html), 'Start Time must be a <select>');
assert.ok(/<select[^>]*\bid="fEndTime"/.test(html), 'End Time must be a <select>');
assert.ok(html.includes('./time-options.js'), 'index.html must load time-options.js');

const inlineScripts = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi)];
inlineScripts.forEach((match) => {
  new Function(match[1]);
});

// --- service worker: cache bumped and new asset included ---
const sw = fs.readFileSync(path.join(__dirname, 'sw.js'), 'utf8');
const cacheMatch = sw.match(/CACHE_NAME\s*=\s*'ward-tracker-shell-v(\d+)'/);
assert.ok(cacheMatch, 'sw.js must define a versioned CACHE_NAME');
assert.ok(Number(cacheMatch[1]) >= 5, 'cache version must be bumped past v4 for the time-entry change');
assert.ok(sw.includes("'./time-options.js'"), 'service worker shell must cache time-options.js');

// --- populateTimeSelect(): off-grid stored time on edit must be preserved, not erased ---
// Extracts the real function bodies straight out of index.html (rather than
// re-implementing the logic here) so this test fails if the shipped code drifts.
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

// Minimal <select> stand-in matching real HTMLSelectElement behavior that matters here:
// setting .innerHTML with no `selected` option selects the first option by default, and
// setting .value to something absent from the current options list is a silent no-op.
class FakeSelect {
  constructor() { this._options = []; this._value = ''; }
  set innerHTML(html) {
    const optionRe = /<option value="([^"]*)">([^<]*)<\/option>/g;
    const opts = [];
    let m;
    while ((m = optionRe.exec(html))) opts.push({value: m[1], text: m[2]});
    this._options = opts;
    this._value = opts.length ? opts[0].value : '';
  }
  set value(v) {
    if (this._options.some((o) => o.value === v)) this._value = v;
  }
  get value() { return this._value; }
  hasOption(v) { return this._options.some((o) => o.value === v); }
}

const populateTimeSelectFactory = new Function(
  'TimeOptions',
  `${extractFunctionSource(html, 'escapeHtml')}\n${extractFunctionSource(html, 'populateTimeSelect')}\nreturn populateTimeSelect;`
);
const populateTimeSelect = populateTimeSelectFactory({TIME_OPTIONS, BLANK_LABEL});

[
  {label: 'off-grid start time', stored: '08:15'},
  {label: 'off-grid end time', stored: '09:45'},
].forEach(({label, stored}) => {
  const select = new FakeSelect();
  populateTimeSelect(select, stored);

  assert.strictEqual(select.value, stored, `${label}: stored value must be selected`);
  assert.ok(select.hasOption(stored), `${label}: stored value must be inserted as an available option`);
  assert.notStrictEqual(select.value, '', `${label}: must not be erased (blank) on edit`);

  // Not silently rounded/replaced with a neighboring 30-minute grid value.
  const [h, m] = stored.split(':').map(Number);
  const roundedDown = `${String(h).padStart(2, '0')}:${m < 30 ? '00' : '30'}`;
  const roundedUp = m < 30
    ? `${String(h).padStart(2, '0')}:30`
    : `${String(h + 1).padStart(2, '0')}:00`;
  assert.notStrictEqual(select.value, roundedDown, `${label}: must not be replaced with the nearest lower grid value`);
  assert.notStrictEqual(select.value, roundedUp, `${label}: must not be replaced with the nearest upper grid value`);

  // The normal 30-minute grid must still be fully present alongside the off-grid extra.
  assert.strictEqual(select._options.length, TIME_OPTIONS.length + 2, `${label}: blank + full grid + the one off-grid extra`);
  TIME_OPTIONS.forEach((t) => {
    assert.ok(select.hasOption(t), `${label}: normal grid option ${t} must remain present`);
  });
  assert.ok(select.hasOption(''), `${label}: blank "Select time" option must remain present`);
});

// Blank historical time must keep working: no stored time selects the blank option,
// without injecting a spurious extra option.
const blankSelect = new FakeSelect();
populateTimeSelect(blankSelect, '');
assert.strictEqual(blankSelect.value, '', 'blank historical time should keep the blank option selected');
assert.strictEqual(blankSelect._options.length, TIME_OPTIONS.length + 1, 'blank value should not add an extra option');

const undefinedSelect = new FakeSelect();
populateTimeSelect(undefinedSelect, undefined);
assert.strictEqual(undefinedSelect.value, '', 'missing/undefined historical time should also fall back to blank');

console.log('time-options frontend tests passed');
