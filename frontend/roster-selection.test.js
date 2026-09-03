const assert = require('assert');
const fs = require('fs');
const path = require('path');

// Roster-only candidate identity (data-quality fix): the "Your name" field on
// screenWho must only accept a roster entry the user explicitly clicked/
// selected, never freely typed text — that's what let "Cecilia Anne Auld
// (CLLR)" and "Cecilia Auld" become two different dashboard people. These
// tests execute the real production callbacks extracted from index.html
// (not a re-implementation) against a tiny DOM stub.

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

function extractBlock(src, marker) {
  const idx = src.indexOf(marker);
  if (idx === -1) throw new Error(`marker not found: ${marker}`);
  const braceStart = src.indexOf('{', idx);
  let depth = 0;
  let i = braceStart;
  for (; i < src.length; i++) {
    if (src[i] === '{') depth++;
    else if (src[i] === '}') {
      depth--;
      if (depth === 0) { i++; break; }
    }
  }
  return src.slice(braceStart + 1, i - 1);
}

// Confirm the readonly ward field and the error copy the spec requires.
assert.ok(
  /<input type="text" id="whoWard"[^>]*readonly/.test(html),
  'whoWard must be readonly — it is only ever set by a roster selection, never typed'
);

const slugSrc = extractFunctionSource(html, 'slug');
const escapeHtmlSrc = extractFunctionSource(html, 'escapeHtml');
const matchingRosterNamesSrc = extractFunctionSource(html, 'matchingRosterNames');
const hideNameSuggestionsSrc = extractFunctionSource(html, 'hideNameSuggestions');
const renderNameSuggestionsSrc = extractFunctionSource(html, 'renderNameSuggestions');
const selectRosterNameSrc = extractFunctionSource(html, 'selectRosterName');
const inputHandlerBody = extractBlock(html, "$('whoName').addEventListener('input', ()=>{");
const continueHandlerBody = extractBlock(html, "$('whoContinue').onclick = async ()=>{");

function buildHarness(rosterData) {
  const elements = {
    whoName: { value: '', setAttribute() {} },
    whoWard: { value: '' },
    whoStatus: { textContent: '', className: '' },
    whoContinue: { disabled: false, textContent: 'Continue' },
    nameSuggestions: { hidden: true, innerHTML: '' },
  };
  const body = `
    function $(id){ return elements[id]; }
    let selectedRosterPerson = null;
    let personId=null, personName=null, personWard=null;
    let suggestionIndex = -1;
    let loadMyWeekCalls = 0;
    const rosterNamesData = rosterData;
    async function loadMyWeek(){ loadMyWeekCalls++; }
    ${slugSrc}
    ${escapeHtmlSrc}
    ${matchingRosterNamesSrc}
    ${hideNameSuggestionsSrc}
    ${renderNameSuggestionsSrc}
    ${selectRosterNameSrc}
    async function runInput(){ ${inputHandlerBody} }
    async function runContinue(){ ${continueHandlerBody} }
    return {
      runInput, runContinue, selectRosterName, matchingRosterNames,
      getState: () => ({
        selectedRosterPerson, personId, personName, personWard, loadMyWeekCalls,
        whoWardValue: elements.whoWard.value,
        whoStatusText: elements.whoStatus.textContent,
      }),
    };
  `;
  const factory = new Function('elements', 'rosterData', body);
  return { harness: factory(elements, rosterData), elements };
}

const ROSTER = [
  { name: 'Cecilia Anne Auld (CLLR)', ward: 'Ward 4' },
  { name: 'Marnich Roets', ward: 'Ward 1' },
];

// --- typed but unselected name is rejected ---
{
  const { harness, elements } = buildHarness(ROSTER);
  elements.whoName.value = 'Cecilia Anne Auld (CLLR)'; // typed exactly, never clicked
  harness.runContinue();
  const s = harness.getState();
  assert.strictEqual(s.personId, null, 'Continue must not proceed on typed-only text');
  assert.strictEqual(s.loadMyWeekCalls, 0);
  assert.strictEqual(s.whoStatusText, 'Please select your name from the list.');
}

// --- unknown name is rejected ---
{
  const { harness, elements } = buildHarness(ROSTER);
  elements.whoName.value = 'Someone Not On The Roster';
  harness.runContinue();
  const s = harness.getState();
  assert.strictEqual(s.personId, null);
  assert.strictEqual(s.whoStatusText, 'Please select your name from the list.');
  assert.strictEqual(harness.matchingRosterNames('Someone Not On').length, 0, 'no suggestions for an unknown name');
}

// --- clicking/selecting a roster suggestion fills ward and enables Continue ---
{
  const { harness, elements } = buildHarness(ROSTER);
  harness.selectRosterName(ROSTER[0]);
  assert.strictEqual(elements.whoName.value, 'Cecilia Anne Auld (CLLR)');
  assert.strictEqual(elements.whoWard.value, 'Ward 4');
  harness.runContinue();
  const s = harness.getState();
  assert.strictEqual(s.personId, 'cecilia-anne-auld-cllr');
  assert.strictEqual(s.personName, 'Cecilia Anne Auld (CLLR)');
  assert.strictEqual(s.personWard, 'Ward 4');
  assert.strictEqual(s.loadMyWeekCalls, 1, 'valid selection must be able to Continue');
}

// --- changing text after roster selection invalidates the selection ---
{
  const { harness, elements } = buildHarness(ROSTER);
  harness.selectRosterName(ROSTER[0]);
  elements.whoName.value = 'Cecilia Anne Auld (CLLR) extra';
  harness.runInput();
  const midState = harness.getState();
  assert.strictEqual(midState.selectedRosterPerson, null, 'typing after selection must clear it');
  assert.strictEqual(midState.whoWardValue, '', 'ward must clear along with the invalidated selection');

  harness.runContinue();
  const s = harness.getState();
  assert.strictEqual(s.personId, null, 'Continue must be blocked after the selection was invalidated');
  assert.strictEqual(s.whoStatusText, 'Please select your name from the list.');
}

// --- re-typing the exact same selected name still requires re-selecting (not enough to "match") ---
{
  const { harness, elements } = buildHarness(ROSTER);
  harness.selectRosterName(ROSTER[0]);
  elements.whoName.value = 'Cecilia Auld'; // a plausible-looking but different typed variant
  harness.runInput();
  harness.runContinue();
  const s = harness.getState();
  assert.strictEqual(s.personId, null, 'a differently-typed variant of the same person must not be accepted without re-selecting');
}

// --- autocomplete matching still works (desktop/mobile share the same JS path) ---
{
  const { harness } = buildHarness(ROSTER);
  const matches = harness.matchingRosterNames('auld');
  assert.strictEqual(matches.length, 1);
  assert.strictEqual(matches[0].name, 'Cecilia Anne Auld (CLLR)');
  assert.strictEqual(harness.matchingRosterNames('marnich')[0].name, 'Marnich Roets');
}

console.log('roster selection tests passed');
