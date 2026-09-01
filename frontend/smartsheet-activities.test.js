const assert = require('assert');
const fs = require('fs');
const path = require('path');

const {ACTIVITY_OPTIONS, CANONICAL_ACTIVITY_OPTIONS, OTHER_OPTION, CATEGORIES, CATEGORY_LABELS} = require('./smartsheet-activities');

const seen = new Set(ACTIVITY_OPTIONS.map(v => v.toLowerCase()));
assert.strictEqual(seen.size, ACTIVITY_OPTIONS.length, 'activity labels should not be duplicated');
assert.ok(ACTIVITY_OPTIONS.includes('House Meeting'));
assert.ok(ACTIVITY_OPTIONS.includes('Street Meeting'));
assert.ok(ACTIVITY_OPTIONS.includes('Blue Wave'));
assert.strictEqual(CATEGORIES.CANVASSING, 'CANVASSING');
assert.strictEqual(CATEGORIES.PUBLIC_STREET_MEETING, 'PUBLIC_STREET_MEETING');
assert.strictEqual(CATEGORIES.PRESENCE, 'PRESENCE');
assert.strictEqual(CATEGORY_LABELS.NEEDS_REVIEW, 'Needs Review');

// --- Item 13: Other is the last dropdown option, kept out of the canonical/mapped list ---
assert.strictEqual(OTHER_OPTION, 'Other');
assert.strictEqual(ACTIVITY_OPTIONS[ACTIVITY_OPTIONS.length - 1], OTHER_OPTION, 'Other must be the final Activity option');
assert.ok(!CANONICAL_ACTIVITY_OPTIONS.includes(OTHER_OPTION), 'Other must not be one of the fixed/mapped activities');
assert.strictEqual(ACTIVITY_OPTIONS.length, CANONICAL_ACTIVITY_OPTIONS.length + 1, 'ACTIVITY_OPTIONS should be the canonical list plus Other');
assert.deepStrictEqual(ACTIVITY_OPTIONS.slice(0, -1), CANONICAL_ACTIVITY_OPTIONS, 'every option before Other must be an official/canonical activity');

const html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');
assert.ok(html.includes('id="fDate"'), 'candidate form should include a date picker');
assert.ok(html.includes('id="fStartTime"'), 'candidate form should include start time');
assert.ok(html.includes('id="fEndTime"'), 'candidate form should include end time');
assert.ok(html.includes('id="fActivity"'), 'candidate form should include one activity select');
assert.ok(html.includes('id="fVenue"'), 'candidate form should include venue / area');
assert.ok(!html.includes('id="typeChips"'), 'candidate form should not use category/type chips');

// --- Item 13: the "Other activity" field markup ---
assert.ok(/<div class="field" id="fOtherActivityField" hidden>/.test(html), 'Other activity field must be hidden by default');
assert.ok(/<input type="text" id="fOtherActivity"/.test(html), 'Other activity must be one simple text field');
// Exactly one Activity select and one Other-activity field — no second/parallel category dropdown.
assert.strictEqual((html.match(/id="fActivity"/g) || []).length, 1, 'there must be only one Activity dropdown');
assert.ok(!/id="fCategory"|id="fSmartsheet"|id="fReportingCategory"/.test(html), 'no separate category dropdown should be added');

const inlineScripts = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi)];
inlineScripts.forEach((match) => {
  new Function(match[1]);
});

// --- extract real functions straight out of index.html, mirroring time-options.test.js ---
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

function escapeHtml(s){return (s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}

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
  set value(v) { if (this._options.some((o) => o.value === v)) this._value = v; }
  get value() { return this._value; }
  optionValues() { return this._options.map((o) => o.value); }
}

class FakeField {
  constructor() { this.hidden = true; this._value = ''; }
  set value(v) { this._value = v; }
  get value() { return this._value; }
}

// --- resolveOtherActivityText(): blank/whitespace rejection + trimming + wording preservation ---
const resolveOtherActivityTextFactory = new Function(
  `${extractFunctionSource(html, 'resolveOtherActivityText')}\nreturn resolveOtherActivityText;`
);
const resolveOtherActivityText = resolveOtherActivityTextFactory();

assert.strictEqual(resolveOtherActivityText('  Community prayer event  '), 'Community prayer event', 'leading/trailing whitespace must be trimmed');
assert.strictEqual(resolveOtherActivityText('Community prayer event'), 'Community prayer event', 'exact custom wording must be preserved');
assert.strictEqual(resolveOtherActivityText(''), '', 'blank text resolves to empty (rejected by the save guard)');
assert.strictEqual(resolveOtherActivityText('   '), '', 'whitespace-only text resolves to empty (rejected by the save guard)');
assert.strictEqual(resolveOtherActivityText('\t\n '), '', 'whitespace-only (tabs/newlines) resolves to empty');
assert.strictEqual(resolveOtherActivityText(undefined), '', 'missing value resolves to empty, not "undefined"');
assert.strictEqual(resolveOtherActivityText('Door to Door'), 'Door to Door', 'wording matching an official label is preserved verbatim, not converted');

// The save handler must actually gate on this — i.e. still refuse to submit when it's blank.
assert.ok(
  /isOtherSelected\s*&&\s*!otherActivityText/.test(html),
  'saving must be blocked when Other is selected and the custom text resolves to empty'
);

// --- populateActivitySelect(): Other rendered last, both Other and canonical selections work ---
let activitySelect = new FakeSelect();
const populateActivitySelectFactory = new Function(
  'ACTIVITY_OPTIONS', 'escapeHtml', '$',
  `${extractFunctionSource(html, 'populateActivitySelect')}\nreturn populateActivitySelect;`
);
const populateActivitySelect = populateActivitySelectFactory(
  ACTIVITY_OPTIONS, escapeHtml, (id) => (id === 'fActivity' ? activitySelect : null)
);

activitySelect = new FakeSelect();
populateActivitySelect();
assert.strictEqual(activitySelect.optionValues()[activitySelect.optionValues().length - 1], OTHER_OPTION, 'rendered dropdown must end with Other');

activitySelect = new FakeSelect();
populateActivitySelect(OTHER_OPTION);
assert.strictEqual(activitySelect.value, OTHER_OPTION, 'selecting Other via extraValue must select the Other option');

activitySelect = new FakeSelect();
populateActivitySelect('House Meeting');
assert.strictEqual(activitySelect.value, 'House Meeting', 'a normal activity must still populate/select exactly as before');
assert.notStrictEqual(activitySelect.value, OTHER_OPTION);

// --- showOtherActivityField() / hideOtherActivityField(): reveal for Other, hidden for normal activities ---
const fieldFns = new Function(
  'field', 'input',
  `const $ = (id) => (id === 'fOtherActivityField' ? field : input);\n${extractFunctionSource(html, 'showOtherActivityField')}\n${extractFunctionSource(html, 'hideOtherActivityField')}\nreturn {showOtherActivityField, hideOtherActivityField};`
);
const field = new FakeField();
const input = new FakeField();
const {showOtherActivityField, hideOtherActivityField} = fieldFns(field, input);

hideOtherActivityField();
assert.strictEqual(field.hidden, true, 'Other activity field must start hidden for a normal activity');
assert.strictEqual(input.value, '', 'hiding must clear any leftover custom text');

showOtherActivityField('');
assert.strictEqual(field.hidden, false, 'selecting Other must reveal the Other activity field');
assert.strictEqual(input.value, '', 'a fresh Other selection should not prefill any wording');

showOtherActivityField('Community prayer event');
assert.strictEqual(field.hidden, false, 'editing an existing custom entry must reveal the field');
assert.strictEqual(input.value, 'Community prayer event', 'editing must prefill the exact stored wording');

hideOtherActivityField();
assert.strictEqual(field.hidden, true, 'switching back to a normal activity must hide the field again');

// --- Candidate-facing rendering must never surface internal SmartSheet/review terms ---
const actRowTemplateMatch = html.match(/html \+= `<div class="actrow"[\s\S]*?<\/div>`;/);
assert.ok(actRowTemplateMatch, 'could not find the candidate weekly activity row template');
const forbiddenTerms = ['smartsheet_category', 'category_source', 'canonical_activity', 'NEEDS_REVIEW', 'category_reviewed', 'admin_review'];
forbiddenTerms.forEach((term) => {
  assert.ok(!actRowTemplateMatch[0].includes(term), `candidate activity row must not reference "${term}"`);
});

const savePayloadMatch = html.match(/const entry=\{[\s\S]*?\};/);
assert.ok(savePayloadMatch, 'could not find the candidate save payload construction');
forbiddenTerms.forEach((term) => {
  assert.ok(!savePayloadMatch[0].includes(term), `candidate save payload must not send "${term}"`);
});

// --- edge case: an off-grid "type marker" leak (previous Other selection reused as a normal one) must be guarded ---
assert.ok(
  html.includes("editingOriginalEntry.type !== OTHER_OPTION"),
  'the legacy type-preservation quirk must not leak the Other marker into a normal (non-Other) resubmission'
);

console.log('smartsheet activity frontend tests passed');
