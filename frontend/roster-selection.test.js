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
const confirmedWardsForSrc = extractFunctionSource(html, 'confirmedWardsFor');
const areaSrc = ['parseRosterWardText', 'candidateArea', 'candidateAreaText'].map((n) => extractFunctionSource(html, n)).join('\n');
const escapeHtmlSrc = extractFunctionSource(html, 'escapeHtml');
const councillorDisplayNameSrc = extractFunctionSource(html, 'councillorDisplayName');
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
    weekTitle: { textContent: '' },
    homeArea: { textContent: '', hidden: true },
  };
  const body = `
    function $(id){ return elements[id]; }
    let selectedRosterPerson = null;
    let personId=null, personName=null, personWard=null, personConfirmedWards=[];
    let personArea = {ward:'', municipality:''};
    const CURRENT_WEEK_KEY = '2026-11-08';
    let selectedWeekKey = '2026-11-15';
    let suggestionIndex = -1;
    let loadMyWeekCalls = 0;
    let loadCampaignsCalls = 0;
    const rosterNamesData = rosterData;
    async function loadMyWeek(){ loadMyWeekCalls++; }
    async function loadCampaigns(){ loadCampaignsCalls++; }
    ${confirmedWardsForSrc}
    ${areaSrc}
    ${slugSrc}
    ${escapeHtmlSrc}
    ${councillorDisplayNameSrc}
    ${matchingRosterNamesSrc}
    ${hideNameSuggestionsSrc}
    ${renderNameSuggestionsSrc}
    ${selectRosterNameSrc}
    async function runInput(){ ${inputHandlerBody} }
    async function runContinue(){ ${continueHandlerBody} }
    return {
      runInput, runContinue, selectRosterName, matchingRosterNames, councillorDisplayName,
      getState: () => ({
        selectedRosterPerson, personId, personName, personWard, personConfirmedWards, loadMyWeekCalls, loadCampaignsCalls,
        personArea, selectedWeekKey, homeArea: elements.homeArea.textContent, weekTitle: elements.weekTitle.textContent,
        whoWardValue: elements.whoWard.value, whoNameValue: elements.whoName.value,
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
  assert.deepStrictEqual(s.personConfirmedWards, [], 'a candidate with no actual_wards has no confirmed-ward list');
}

// --- selecting a candidate confirmed to several wards captures that list ---
{
  const MULTI_WARD_ROSTER = [
    { name: 'Andre Van Rayner', ward: 'Raymond Mhlaba', actual_wards: ['Ward 1', 'Ward 4', 'Ward 13'] },
  ];
  const { harness, elements } = buildHarness(MULTI_WARD_ROSTER);
  harness.selectRosterName(MULTI_WARD_ROSTER[0]);
  harness.runContinue();
  const s = harness.getState();
  assert.strictEqual(s.whoNameValue, 'Andre Van Rayner (CLLR)', 'display title is visible to candidate');
  assert.strictEqual(s.weekTitle, 'Andre Van Rayner (CLLR)', 'home heading shows the councillor title');
  assert.strictEqual(s.personName, 'Andre Van Rayner', 'stored identity is always the canonical roster name');
  assert.strictEqual(s.personId, 'andre-van-rayner');
  assert.deepStrictEqual(s.personConfirmedWards, ['Ward 1', 'Ward 4', 'Ward 13']);
  assert.strictEqual(s.personWard, 'Raymond Mhlaba', 'the payload ward stays the roster text; the backend resolves the canonical ward');
  assert.strictEqual(elements.whoWard.value, 'Wards 1, 4, 13 · Raymond Mhlaba', 'wards and municipality are shown as what they are');
  assert.deepStrictEqual([s.personArea.ward, s.personArea.municipality], ['', 'Raymond Mhlaba']);
}

// --- Stage 2C: a "Ward N" roster value is shown as a ward, never as a municipality ---
{
  const person = { name: 'Ayanda Zondi', ward: 'Ward 3', municipality: 'Amahlathi', actual_ward: 'Ward 3' };
  const { harness, elements } = buildHarness([person]);
  harness.selectRosterName(person);
  assert.strictEqual(elements.whoWard.value, 'Ward 3 · Amahlathi');
  harness.runContinue();
  const s = harness.getState();
  assert.strictEqual(s.personWard, 'Ward 3', 'payload ward unchanged by the display correction');
  assert.deepStrictEqual([s.personArea.ward, s.personArea.municipality], ['Ward 3', 'Amahlathi']);
  assert.strictEqual(s.weekTitle, 'Ayanda Zondi', 'the home screen names the signed-in candidate');
  assert.strictEqual(s.homeArea, 'Ward 3 · Amahlathi');
  assert.strictEqual(s.selectedWeekKey, '2026-11-08', 'signing in always starts on this week');
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

// The seven agreed councillors show their role; only four need a suffix
// added, since Cecilia, Richard and Spokazi already have (CLLR) in the roster.
{
  const { harness } = buildHarness(ROSTER);
  for(const name of ['Mavis Krishi','Thulani Dasa','Busisiwe Yonela Mqamelo','Andre Van Rayner']){
    assert.strictEqual(harness.councillorDisplayName(name), name + ' (CLLR)');
  }
  for(const name of ['Cecilia Anne Auld (CLLR)', 'Richard Brennand Pickering (CLLR)', 'Spokazi Elizabeth Mpayipeli (CLLR)']){
    assert.strictEqual(harness.councillorDisplayName(name), name, 'never duplicate the title');
  }
  assert.strictEqual(harness.councillorDisplayName('Marnich Roets'), 'Marnich Roets');
}
console.log('roster selection tests passed');
