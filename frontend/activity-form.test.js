const assert = require('assert');
const fs = require('fs');
const path = require('path');
const WeekDates = require('./week-dates');

// Phase 5.1: candidate UX + reporting polish.
//  - Back navigation on the shared Add/Edit Activity screen (screenAdd),
//    used for ordinary activities, campaign activities, and edits of both.
//  - Ward auto-fill (read-only display) + stricter Location/Venue
//    validation on the ordinary (non-campaign) activity form.
// These tests execute the real production functions/handler bodies
// extracted from index.html (not a re-implementation), matching the
// convention already established in roster-selection.test.js and
// campaign-ui.test.js.

const html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');
const DAY_ORDER = WeekDates.DAY_ORDER;

function extractFunctionSource(src, name) {
  const marker = `function ${name}(`;
  let start = src.indexOf(marker);
  if (start === -1) throw new Error(`could not find function ${name}() in index.html`);
  if (src.slice(Math.max(0, start - 6), start) === 'async ') start -= 6;
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

function extractLineContaining(src, marker) {
  const idx = src.indexOf(marker);
  if (idx === -1) throw new Error(`marker not found: ${marker}`);
  const lineEnd = src.indexOf('\n', idx);
  return src.slice(idx, lineEnd === -1 ? undefined : lineEnd);
}

// --- Structural checks on the markup itself ---
assert.ok(html.includes('id="addBackBtn"'), 'screenAdd must have a Back control');
assert.ok(html.includes('id="fWardField"'), 'a read-only ward field must exist on screenAdd');
assert.ok(/<input type="text" id="fWard"[^>]*readonly/.test(html), 'fWard must be readonly — it is only ever set from the roster-resolved ward');
{
  // The Back control must sit above the section heading ("addGreet"),
  // exactly as specced ("above the section heading"), not buried in the card.
  const screenAddIdx = html.indexOf('id="screenAdd"');
  const backIdx = html.indexOf('id="addBackBtn"', screenAddIdx);
  const greetIdx = html.indexOf('id="addGreet"', screenAddIdx);
  assert.ok(backIdx > -1 && greetIdx > -1 && backIdx < greetIdx, 'addBackBtn must appear above the addGreet heading in screenAdd');
}

const isWardOnlyLocationSrc = extractFunctionSource(html, 'isWardOnlyLocation');
const wardOnlyLocationMessageSrc = extractLineContaining(html, 'const WARD_ONLY_LOCATION_MESSAGE');
const updateAddScreenWardAndBackSrc = extractFunctionSource(html, 'updateAddScreenWardAndBack');
const addBackBtnHandlerBody = extractBlock(html, "$('addBackBtn').onclick = (e)=>{");

// --- isWardOnlyLocation: pure function, exercised directly ---
{
  const body = `${isWardOnlyLocationSrc}\nreturn isWardOnlyLocation;`;
  const isWardOnlyLocation = new Function(body)();

  assert.strictEqual(isWardOnlyLocation('Ward 13', 'Ward 13'), true);
  assert.strictEqual(isWardOnlyLocation('ward 13', 'Ward 13'), true, 'case-insensitive');
  assert.strictEqual(isWardOnlyLocation('  Ward 13  ', 'Ward 13'), true, 'trimmed');
  assert.strictEqual(isWardOnlyLocation('13', 'Ward 13'), true, 'bare ward number');
  assert.strictEqual(isWardOnlyLocation('Amahlathi', 'Amahlathi'), true);
  assert.strictEqual(isWardOnlyLocation('Raymond Mhlaba', 'Raymond Mhlaba'), true);
  assert.strictEqual(isWardOnlyLocation('Mlungisi Community Hall, Ward 13', 'Ward 13'), false, 'a real venue mentioning the ward must be allowed');
  assert.strictEqual(isWardOnlyLocation('Main Street, Ward 13', 'Ward 13'), false);
  assert.strictEqual(isWardOnlyLocation('Mlungisi Community Hall', 'Ward 13'), false);
  assert.strictEqual(isWardOnlyLocation('Some Hall', ''), false, 'a blank ward never blocks a real location');
  assert.strictEqual(isWardOnlyLocation('', 'Ward 13'), false, 'blank handled separately by the required-venue check, not this one');
  console.log('isWardOnlyLocation tests passed');
}

// --- updateAddScreenWardAndBack: ward display + Back label/target ---
{
  function run({ personWard, activeCampaign }) {
    const elements = {
      fWard: { value: '' },
      fWardField: { hidden: false },
      addBackBtn: { textContent: '' },
    };
    const body = `
      let personWard = ${JSON.stringify(personWard)};
      let activeCampaign = ${JSON.stringify(activeCampaign)};
      function $(id){ return elements[id]; }
      ${updateAddScreenWardAndBackSrc}
      updateAddScreenWardAndBack();
    `;
    new Function('elements', body)(elements);
    return elements;
  }

  let el = run({ personWard: 'Ward 13', activeCampaign: null });
  assert.strictEqual(el.fWardField.hidden, false);
  assert.strictEqual(el.fWard.value, 'Ward 13');
  assert.strictEqual(el.addBackBtn.textContent, '← Back to my week');

  el = run({ personWard: 'Ward 13', activeCampaign: { id: 'camp1' } });
  assert.strictEqual(el.fWardField.hidden, false);
  assert.strictEqual(el.fWard.value, 'Ward 13');
  assert.strictEqual(el.addBackBtn.textContent, '← Back to campaign');

  // Marnich/Kevin-style blank roster ward: never blocks the screen, just hides the read-only field.
  el = run({ personWard: '', activeCampaign: null });
  assert.strictEqual(el.fWardField.hidden, true);
  assert.strictEqual(el.addBackBtn.textContent, '← Back to my week');

  console.log('updateAddScreenWardAndBack tests passed');
}

// --- addBackBtn handler: never saves/submits/creates, routes correctly ---
{
  function run({ activeCampaign }) {
    const calls = [];
    const elements = {};
    const body = `
      let activeCampaign = ${JSON.stringify(activeCampaign)};
      const calls = [];
      function show(id){ calls.push({fn:'show', id}); }
      async function openCampaignDetail(id){ calls.push({fn:'openCampaignDetail', id}); }
      async function api(){ calls.push({fn:'api'}); }
      async function fetch(){ calls.push({fn:'fetch'}); }
      const e = { preventDefault(){ calls.push({fn:'preventDefault'}); } };
      ${addBackBtnHandlerBody}
      return calls;
    `;
    return new Function(body)();
  }

  let calls = run({ activeCampaign: null });
  assert.ok(calls.some(c => c.fn === 'preventDefault'));
  assert.ok(calls.some(c => c.fn === 'show' && c.id === 'screenWeek'), 'ordinary Add Activity Back must return to candidate home');
  assert.ok(!calls.some(c => c.fn === 'openCampaignDetail'));
  assert.ok(!calls.some(c => c.fn === 'api' || c.fn === 'fetch'), 'Back must never call the network — it must not save/submit/create');

  calls = run({ activeCampaign: { id: 'camp42' } });
  assert.ok(calls.some(c => c.fn === 'openCampaignDetail' && c.id === 'camp42'), 'Add Campaign Activity Back must return to that campaign\'s detail screen');
  assert.ok(!calls.some(c => c.fn === 'show' && c.id === 'screenWeek'));
  assert.ok(!calls.some(c => c.fn === 'api' || c.fn === 'fetch'), 'Back must never call the network — it must not save/submit/create');

  console.log('addBackBtn handler tests passed');
}

// --- Ordinary saveBtn handler: required + ward-only location validation ---
{
  const saveBtnHandlerBody = extractBlock(html, "$('saveBtn').onclick = async ()=>{");
  const weekStartYmdSrc = extractFunctionSource(html, 'weekStartYmd');
  const weekEndYmdSrc = extractFunctionSource(html, 'weekEndYmd');
  const isDateInWeekSrc = extractFunctionSource(html, 'isDateInWeek');
  const dayFromActivityDateSrc = extractFunctionSource(html, 'dayFromActivityDate');
  const legacyActivityTextSrc = extractFunctionSource(html, 'legacyActivityText');
  const resolveOtherActivityTextSrc = extractFunctionSource(html, 'resolveOtherActivityText');

  function buildHarness({ fields, personWard }) {
    const calls = [];
    const elements = Object.assign({
      fDate: { value: '2026-09-01' }, fStartTime: { value: '09:00' }, fEndTime: { value: '10:00' },
      fVenue: { value: '' }, fActivity: { value: 'Door to Door' },
      fOtherActivity: { value: '' },
      saveBtn: { disabled: false, textContent: '' }, addStatus: { textContent: '', className: '' },
    }, fields);
    const body = `
      const OTHER_OPTION = 'Other';
      let selectedType = null, selectedDay = null;
      let editingKey = null, editingPendingLocalId = null, editingOriginalEntry = null;
      let activeCampaign = null;
      let selectedWeekKey = '2026-08-30';
      const personId = 'test-candidate', personName = 'Test Candidate';
      let personWard = ${JSON.stringify(personWard)};
      let navigatorOnLine = true;
      const navigator = { onLine: true };
      function $(id){ return elements[id]; }
      function showAddStatus(ok, msg){ elements.addStatus.textContent = msg; }
      function showWeekStatus(){}
      function weekLabel(wk){ return wk; }
      function queuePendingEntry(){ calls.push({fn:'queuePendingEntry'}); }
      function updatePendingEntry(){ calls.push({fn:'updatePendingEntry'}); }
      async function trySyncOne(){ calls.push({fn:'trySyncOne'}); return true; }
      async function loadMyWeek(){ calls.push({fn:'loadMyWeek'}); }
      async function api(path, opts){ calls.push({fn:'api', path, opts: opts && JSON.parse(opts.body || 'null'), method: opts && opts.method}); return {}; }
      ${weekStartYmdSrc}
      ${weekEndYmdSrc}
      ${isDateInWeekSrc}
      ${dayFromActivityDateSrc}
      ${legacyActivityTextSrc}
      ${resolveOtherActivityTextSrc}
      ${isWardOnlyLocationSrc}
      ${wardOnlyLocationMessageSrc}
      return (async()=>{ ${saveBtnHandlerBody} })();
    `;
    const factory = new Function('elements', 'calls', 'DAY_ORDER', 'WeekDates', `return (async()=>{ ${body} })();`);
    return { promise: factory(elements, calls, DAY_ORDER, WeekDates), calls, elements };
  }

  (async () => {
    // Blank location on a new entry: rejected, no api call.
    let { promise, calls, elements } = buildHarness({ fields: { fVenue: { value: '' } }, personWard: 'Ward 13' });
    await promise;
    assert.ok(!calls.some(c => c.fn === 'api'), 'blank location must never reach the API');
    assert.strictEqual(elements.addStatus.textContent, 'Please add the venue or area.');

    // Exact ward-only location: rejected with the ward-only message, no api call.
    ({ promise, calls, elements } = buildHarness({ fields: { fVenue: { value: 'Ward 13' } }, personWard: 'Ward 13' }));
    await promise;
    assert.ok(!calls.some(c => c.fn === 'api'), 'a ward-only location must never reach the API');
    assert.strictEqual(elements.addStatus.textContent, 'Please enter the specific location or venue within your ward.');

    // Case-insensitive ward-only location: rejected.
    ({ promise, calls, elements } = buildHarness({ fields: { fVenue: { value: 'ward 13' } }, personWard: 'Ward 13' }));
    await promise;
    assert.ok(!calls.some(c => c.fn === 'api'));
    assert.strictEqual(elements.addStatus.textContent, 'Please enter the specific location or venue within your ward.');

    // A specific venue that happens to mention the ward: allowed through to the API.
    ({ promise, calls, elements } = buildHarness({ fields: { fVenue: { value: 'Mlungisi Community Hall, Ward 13' } }, personWard: 'Ward 13' }));
    await promise;
    assert.ok(calls.some(c => c.fn === 'api' && c.path === '/api/entries' && c.opts.venue === 'Mlungisi Community Hall, Ward 13'), 'a specific venue must save normally');

    // Blank roster ward (e.g. Marnich/Kevin demo accounts): location still required, but never flagged as ward-only.
    ({ promise, calls, elements } = buildHarness({ fields: { fVenue: { value: 'Community Hall' } }, personWard: '' }));
    await promise;
    assert.ok(calls.some(c => c.fn === 'api' && c.opts.ward === ''), 'a blank roster ward must not block activity creation');

    console.log('ordinary saveBtn location validation tests passed');
  })();
}
