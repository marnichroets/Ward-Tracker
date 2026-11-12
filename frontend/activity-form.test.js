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
assert.ok(html.includes('id="fWardField"'), 'a read-only ward display must exist on screenAdd');
assert.ok(html.includes('id="fMunicipalityField"'), 'a read-only municipality display must exist on screenAdd');
{
  // Stage 2C terminology correction: ward and municipality are shown as two
  // separately labelled, non-editable values (the roster's legacy `ward`
  // text holds either — see candidateArea) instead of one "Municipality"
  // box that could read "Ward 3". Neither is an input the candidate can edit.
  const wardMarkup = html.slice(html.indexOf('id="fWardField"'), html.indexOf('</div>', html.indexOf('id="fWardField"')));
  const munMarkup = html.slice(html.indexOf('id="fMunicipalityField"'), html.indexOf('</div>', html.indexOf('id="fMunicipalityField"')));
  assert.ok(/>Ward</.test(wardMarkup) && !/<input/.test(wardMarkup), 'the ward value is labelled "Ward" and is not editable');
  assert.ok(/>Municipality</.test(munMarkup) && !/<input/.test(munMarkup), 'the municipality value is labelled "Municipality" and is not editable');
}
{
  // The Back control must sit above the section heading ("addGreet"),
  // exactly as specced ("above the section heading"), not buried in the card.
  const screenAddIdx = html.indexOf('id="screenAdd"');
  const backIdx = html.indexOf('id="addBackBtn"', screenAddIdx);
  const greetIdx = html.indexOf('id="addGreet"', screenAddIdx);
  assert.ok(backIdx > -1 && greetIdx > -1 && backIdx < greetIdx, 'addBackBtn must appear above the addGreet heading in screenAdd');
}

// --- The roster participant checkbox/multi-select picker must be gone ---
{
  assert.ok(!html.includes('fRosterParticipantsField'), 'the roster participant field wrapper must no longer exist');
  assert.ok(!html.includes('fRosterParticipants"'), 'the roster participant checkbox list must no longer exist');
  assert.ok(!html.includes('roster-participant-option'), 'roster participant checkbox styling must no longer exist');
  assert.ok(!/populateRosterParticipants/.test(html), 'the roster participant picker render function must no longer exist');
  assert.ok(html.includes('Who helped / participated? (Optional)'), 'the manual participant field must be labelled per spec');
  assert.ok(html.includes('id="fOtherParticipants"'), 'the manual "who helped" name-entry list must exist');
  assert.ok(html.includes('id="addParticipantBtn"'), 'an "Add another person" control must exist');
  console.log('roster participant picker removal tests passed');
}

// --- Photo evidence must allow gallery selection, not camera-only, and is optional ---
{
  const evidenceInputMatch = html.match(/<input type="file" id="fEvidence"[^>]*>/);
  assert.ok(evidenceInputMatch, 'the photo evidence file input must exist');
  const evidenceInputTag = evidenceInputMatch[0];
  assert.ok(!/capture\s*=/.test(evidenceInputTag), 'fEvidence must not force capture (camera-only) — gallery selection must remain available');
  assert.ok(/accept="image\/\*"/.test(evidenceInputTag), 'fEvidence must still only accept images');
  assert.ok(html.includes('Add a photo if you have one. You can take a photo or choose one from your gallery.'), 'the evidence field help text must mention both camera and gallery, and that it is optional');
  assert.ok(html.includes('Photo Evidence (Optional)'), 'the evidence field label must read "Photo Evidence (Optional)", not required');
  assert.ok(!html.includes('Photo Evidence *'), 'the evidence field must no longer be marked as required');
  console.log('photo evidence camera/gallery/optional tests passed');
}

const isWardOnlyLocationSrc = extractFunctionSource(html, 'isWardOnlyLocation');
const wardOnlyLocationMessageSrc = extractLineContaining(html, 'const WARD_ONLY_LOCATION_MESSAGE');
const updateAddScreenWardAndBackSrc = extractFunctionSource(html, 'updateAddScreenWardAndBack');
const escapeHtmlSrc = extractFunctionSource(html, 'escapeHtml');
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
  // Municipality-label correction: the roster value shown as "Municipality"
  // may itself be a longer municipality name — still exact-match rejected.
  assert.strictEqual(isWardOnlyLocation('Amahlathi Local Municipality', 'Amahlathi Local Municipality'), true);
  assert.strictEqual(isWardOnlyLocation('amahlathi local municipality', 'Amahlathi Local Municipality'), true, 'case-insensitive');
  assert.strictEqual(isWardOnlyLocation('Amathole District Municipality', 'Amathole District Municipality'), true);
  assert.strictEqual(isWardOnlyLocation('Mlungisi Community Hall, Ward 13', 'Ward 13'), false, 'a real venue mentioning the ward must be allowed');
  assert.strictEqual(isWardOnlyLocation('Main Street, Ward 13', 'Ward 13'), false);
  assert.strictEqual(isWardOnlyLocation('Mlungisi Community Hall', 'Ward 13'), false);
  assert.strictEqual(isWardOnlyLocation('New Goodwin Park', 'Raymond Mhlaba'), false, 'a genuinely specific venue must be allowed');
  assert.strictEqual(isWardOnlyLocation('Mlungisi Community Hall, Ward 13', 'Amahlathi'), false);
  assert.strictEqual(isWardOnlyLocation('Some Hall', ''), false, 'a blank ward never blocks a real location');
  assert.strictEqual(isWardOnlyLocation('', 'Ward 13'), false, 'blank handled separately by the required-venue check, not this one');
  console.log('isWardOnlyLocation tests passed');
}

// --- candidateArea: what the candidate sees as ward vs municipality ---
// (Stage 2C) The roster's legacy `ward` text holds a ward for some
// candidates and a municipality name for others; the separate municipality
// and confirmed actual_ward(s) fields decide which is which. Display only.
const parseRosterWardTextSrc = extractFunctionSource(html, 'parseRosterWardText');
const confirmedWardsForSrc = extractFunctionSource(html, 'confirmedWardsFor');
const candidateAreaSrc = extractFunctionSource(html, 'candidateArea');
const candidateAreaTextSrc = extractFunctionSource(html, 'candidateAreaText');
const weekNameSrc = extractFunctionSource(html, 'weekName');
{
  const { candidateArea, candidateAreaText } = new Function(`${parseRosterWardTextSrc}\n${confirmedWardsForSrc}\n${candidateAreaSrc}\n${candidateAreaTextSrc}\nreturn {candidateArea, candidateAreaText};`)();
  // The screenshot case: a single-ward roster record whose ward text is
  // "Ward 3" must never be presented as a municipality.
  let a = candidateArea({ ward: 'Ward 3', municipality: 'Amahlathi', actual_ward: 'Ward 3' });
  assert.deepStrictEqual([a.ward, a.municipality], ['Ward 3', 'Amahlathi']);
  assert.strictEqual(candidateAreaText({ ward: 'Ward 3', municipality: 'Amahlathi', actual_ward: 'Ward 3' }), 'Ward 3 · Amahlathi');
  a = candidateArea({ ward: 'Ward 3' });
  assert.deepStrictEqual([a.ward, a.municipality], ['Ward 3', ''], 'a ward without a recorded municipality shows no invented municipality');
  // Legacy ward text that is really a municipality name, with a confirmed ward.
  a = candidateArea({ ward: 'Amahlathi', actual_ward: 'Ward 9' });
  assert.deepStrictEqual([a.ward, a.municipality], ['Ward 9', 'Amahlathi']);
  // Multi-ward (PR) candidate: no single ward shown; the form asks instead.
  a = candidateArea({ ward: 'Raymond Mhlaba', municipality: 'Raymond Mhlaba', actual_wards: ['Ward 1', 'Ward 4'] });
  assert.deepStrictEqual([a.ward, a.municipality], ['', 'Raymond Mhlaba']);
  assert.strictEqual(candidateAreaText({ ward: 'Raymond Mhlaba', actual_wards: ['Ward 1', 'Ward 4'] }), 'Wards 1, 4 · Raymond Mhlaba');
  // Municipality-only (no confirmed ward) and blank demo accounts.
  a = candidateArea({ ward: 'Amahlathi', municipality: 'Amahlathi' });
  assert.deepStrictEqual([a.ward, a.municipality], ['', 'Amahlathi']);
  a = candidateArea({ ward: '' });
  assert.deepStrictEqual([a.ward, a.municipality], ['', '']);
  assert.strictEqual(candidateAreaText({ ward: '' }), '');
  // Bare number and "number, area" legacy forms.
  a = candidateArea({ ward: '7' });
  assert.deepStrictEqual([a.ward, a.municipality], ['Ward 7', '']);
  a = candidateArea({ ward: '14, Amahlathi' });
  assert.deepStrictEqual([a.ward, a.municipality], ['Ward 14', 'Amahlathi']);
  console.log('candidateArea ward/municipality display tests passed');
}

// --- updateAddScreenWardAndBack: ward + municipality display, Back label ---
{
  function run({ person, activeCampaign, editingOriginalEntry = null, returnTo = { view: 'overview', weekKey: '2026-11-08' } }) {
    const elements = {
      fWard: { textContent: '' }, fWardField: { hidden: false },
      fMunicipality: { textContent: '' }, fMunicipalityField: { hidden: false },
      fAreaContext: { hidden: false },
      fWardChoice: { value: '', innerHTML: '' },
      fWardChoiceField: { hidden: false },
      fOtherParticipantsField: { hidden: false },
      fEvidenceField: { hidden: false },
      addBackBtn: { textContent: '' },
    };
    const body = `
      ${parseRosterWardTextSrc}
      ${confirmedWardsForSrc}
      ${candidateAreaSrc}
      const person = ${JSON.stringify(person)};
      let personArea = candidateArea(person);
      let personConfirmedWards = confirmedWardsFor(person);
      let activeCampaign = ${JSON.stringify(activeCampaign)};
      let editingOriginalEntry = ${JSON.stringify(editingOriginalEntry)};
      let addReturnTo = ${JSON.stringify(returnTo)};
      const CURRENT_WEEK_KEY = '2026-11-08', NEXT_WEEK_KEY = '2026-11-15';
      ${weekNameSrc}
      function $(id){ return elements[id]; }
      ${escapeHtmlSrc}
      ${updateAddScreenWardAndBackSrc}
      updateAddScreenWardAndBack();
    `;
    new Function('elements', body)(elements);
    return elements;
  }

  let el = run({ person: { ward: 'Ward 13', municipality: 'Amahlathi', actual_ward: 'Ward 13' }, activeCampaign: null });
  assert.strictEqual(el.fWardField.hidden, false);
  assert.strictEqual(el.fWard.textContent, 'Ward 13', 'a ward is shown under the Ward label');
  assert.strictEqual(el.fMunicipality.textContent, 'Amahlathi', 'the municipality is shown under the Municipality label');
  assert.strictEqual(el.fEvidenceField.hidden, false);
  assert.strictEqual(el.addBackBtn.textContent, '← My weeks');
  assert.strictEqual(el.fWardChoiceField.hidden, true, 'a single/no-ward candidate never sees the ward picker');

  el = run({ person: { ward: 'Ward 13' }, activeCampaign: null, returnTo: { view: 'list', weekKey: '2026-11-15' } });
  assert.strictEqual(el.fMunicipalityField.hidden, true, 'no municipality is invented when the roster has none');
  assert.strictEqual(el.addBackBtn.textContent, '← Back to next week', 'Back names the week list it returns to');

  el = run({ person: { ward: 'Ward 13' }, activeCampaign: { id: 'camp1' } });
  assert.strictEqual(el.fWard.textContent, 'Ward 13');
  assert.strictEqual(el.fEvidenceField.hidden, true);
  assert.strictEqual(el.addBackBtn.textContent, '← Back to campaign');

  // Marnich/Kevin-style blank roster ward: never blocks the screen, just hides the read-only context.
  el = run({ person: { ward: '' }, activeCampaign: null });
  assert.strictEqual(el.fWardField.hidden, true);
  assert.strictEqual(el.fAreaContext.hidden, true);

  // A candidate confirmed to several wards must see the picker, populated
  // with exactly their own confirmed wards, defaulting to no selection for
  // a new activity — forcing an explicit choice rather than a silent guess.
  const multi = { ward: 'Raymond Mhlaba', actual_wards: ['Ward 1', 'Ward 4', 'Ward 13'] };
  el = run({ person: multi, activeCampaign: null });
  assert.strictEqual(el.fWardChoiceField.hidden, false, 'a multi-ward candidate must see the ward picker');
  assert.ok(el.fWardChoice.innerHTML.includes('Ward 1') && el.fWardChoice.innerHTML.includes('Ward 4') && el.fWardChoice.innerHTML.includes('Ward 13'));
  assert.strictEqual(el.fWardChoice.value, '', 'no ward is preselected for a brand-new activity');
  assert.strictEqual(el.fWardField.hidden, true, 'no single ward is displayed for a multi-ward candidate');
  assert.strictEqual(el.fMunicipality.textContent, 'Raymond Mhlaba');

  // Editing an existing activity preselects that activity's own ward.
  el = run({ person: multi, activeCampaign: null, editingOriginalEntry: { ward: 'Ward 4' } });
  assert.strictEqual(el.fWardChoice.value, 'Ward 4', 'editing must preselect the activity\'s own historical ward');

  // Editing an activity whose stored ward text no longer matches any of the
  // candidate's current confirmed wards must never silently pick one —
  // it falls back to requiring an explicit re-selection.
  el = run({ person: multi, activeCampaign: null, editingOriginalEntry: { ward: 'Raymond Mhlaba' } });
  assert.strictEqual(el.fWardChoice.value, '');

  console.log('updateAddScreenWardAndBack tests passed');
}

// --- addBackBtn handler: never saves/submits/creates, routes correctly ---
{
  function run({ activeCampaign, returnTo = { view: 'overview', weekKey: '2026-11-08' } }) {
    const body = `
      let activeCampaign = ${JSON.stringify(activeCampaign)};
      let addReturnTo = ${JSON.stringify(returnTo)};
      let selectedWeekKey = 'changed-while-editing';
      const calls = [];
      function show(id){ calls.push({fn:'show', id, selectedWeekKey}); }
      function renderWeekList(){ calls.push({fn:'renderWeekList', selectedWeekKey}); }
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
  assert.ok(calls.some(c => c.fn === 'show' && c.id === 'screenWeek'), 'Add opened from the home screen returns to the home screen');
  assert.ok(!calls.some(c => c.fn === 'openCampaignDetail'));
  assert.ok(!calls.some(c => c.fn === 'api' || c.fn === 'fetch'), 'Back must never call the network — it must not save/submit/create');

  calls = run({ activeCampaign: null, returnTo: { view: 'list', weekKey: '2026-11-15' } });
  assert.ok(calls.some(c => c.fn === 'show' && c.id === 'screenWeekList' && c.selectedWeekKey === '2026-11-15'),
    'Back from a form opened on a week list returns to THAT week\'s list, even after a week change inside the form');
  assert.ok(!calls.some(c => c.fn === 'api' || c.fn === 'fetch'));

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
  const effectiveWardSrc = extractFunctionSource(html, 'effectiveWard');
  const candidateWeekKeyForDateSrc = extractFunctionSource(html, 'candidateWeekKeyForDate');
  const saveButtonLabelSrc = extractFunctionSource(html, 'saveButtonLabel');

  function buildHarness({ fields, personWard, photos = [{id: 'p1'}], confirmedWards = [], online = true, weekKey = '2026-08-30', editing = null }) {
    const calls = [];
    const elements = Object.assign({
      fDate: { value: '2026-09-01' }, fStartTime: { value: '09:00' }, fEndTime: { value: '10:00' },
      fVenue: { value: '' }, fActivity: { value: 'Door to Door' },
      fOtherActivity: { value: '' }, fWardChoice: { value: '' },
      saveBtn: { disabled: false, textContent: '' }, addStatus: { textContent: '', className: '' },
    }, fields);
    const body = `
      const OTHER_OPTION = 'Other';
      let selectedType = null, selectedDay = null;
      let editingKey = ${JSON.stringify(editing && editing.key || null)}, editingPendingLocalId = null, editingOriginalEntry = ${JSON.stringify(editing && editing.entry || null)};
      let activeCampaign = null;
      let evidencePhotos = ${JSON.stringify(photos)};
      let selectedWeekKey = ${JSON.stringify(weekKey)};
      const CURRENT_WEEK_KEY = '2026-08-30', NEXT_WEEK_KEY = '2026-09-06';
      let pendingSaveFeedback = null;
      function renderWeekWarning(){ calls.push({fn:'renderWeekWarning'}); }
      ${candidateWeekKeyForDateSrc}
      ${weekNameSrc}
      ${saveButtonLabelSrc}
      const personId = 'test-candidate', personName = 'Test Candidate';
      let personWard = ${JSON.stringify(personWard)};
      let personConfirmedWards = ${JSON.stringify(confirmedWards)};
      const navigator = { onLine: ${JSON.stringify(online)} };
      function $(id){ return elements[id]; }
      ${effectiveWardSrc}
      function showAddStatus(ok, msg){ elements.addStatus.textContent = msg; }
      function showWeekStatus(){}
      function weekLabel(wk){ return wk; }
      function queuePendingEntry(entry){ calls.push({fn:'queuePendingEntry', entry}); return 'pending-local-1'; }
      function updatePendingEntry(){ calls.push({fn:'updatePendingEntry'}); }
      async function trySyncOne(){ calls.push({fn:'trySyncOne'}); return true; }
      async function loadMyWeek(view){ calls.push({fn:'loadMyWeek', view, feedback: pendingSaveFeedback, selectedWeekKey}); }
      async function api(path, opts){ calls.push({fn:'api', path, opts: opts && JSON.parse(opts.body || 'null'), method: opts && opts.method}); return {}; }
      async function postActivityWithDuplicate(path, body){ calls.push({fn:'api', path, opts: body, method:'POST'}); return {id: 'srv-1'}; }
      function friendlyErrorMessage(err, fallback){ return fallback; }
      function selectedRosterParticipantIds(){ return []; }
      function selectedOtherParticipants(){ return []; }
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
    assert.strictEqual(elements.addStatus.textContent, 'Please enter the specific location or venue within your municipality.');

    // Case-insensitive ward-only location: rejected.
    ({ promise, calls, elements } = buildHarness({ fields: { fVenue: { value: 'ward 13' } }, personWard: 'Ward 13' }));
    await promise;
    assert.ok(!calls.some(c => c.fn === 'api'));
    assert.strictEqual(elements.addStatus.textContent, 'Please enter the specific location or venue within your municipality.');

    // Photo evidence is now optional: a new activity with zero photos must
    // succeed and submit evidence_photos: [] — not be blocked.
    ({ promise, calls, elements } = buildHarness({ fields: { fVenue: { value: 'Community Hall' } }, personWard: 'Ward 13', photos: [] }));
    await promise;
    assert.ok(calls.some(c => c.fn === 'api' && c.path === '/api/entries' && Array.isArray(c.opts.evidence_photos) && c.opts.evidence_photos.length === 0), 'an activity with no photo evidence must submit successfully with an empty evidence_photos array');
    assert.notStrictEqual(elements.addStatus.textContent, 'Please add at least one photo before submitting this activity.');

    // A new activity WITH a photo still succeeds and includes it.
    ({ promise, calls, elements } = buildHarness({ fields: { fVenue: { value: 'Community Hall' } }, personWard: 'Ward 13', photos: [{id: 'p1'}] }));
    await promise;
    assert.ok(calls.some(c => c.fn === 'api' && Array.isArray(c.opts.evidence_photos) && c.opts.evidence_photos.length === 1), 'an activity with a photo must still submit it');

    // A specific venue that happens to mention the ward: allowed through to the API.
    ({ promise, calls, elements } = buildHarness({ fields: { fVenue: { value: 'Mlungisi Community Hall, Ward 13' } }, personWard: 'Ward 13' }));
    await promise;
    assert.ok(calls.some(c => c.fn === 'api' && c.path === '/api/entries' && c.opts.venue === 'Mlungisi Community Hall, Ward 13'), 'a specific venue must save normally');

    // Blank roster ward (e.g. Marnich/Kevin demo accounts): location still required, but never flagged as ward-only.
    ({ promise, calls, elements } = buildHarness({ fields: { fVenue: { value: 'Community Hall' } }, personWard: '' }));
    await promise;
    assert.ok(calls.some(c => c.fn === 'api' && c.opts.ward === ''), 'a blank roster ward must not block activity creation');

    // A candidate confirmed to only one ward is unaffected by the multi-ward
    // picker — personWard (whatever the roster/municipality field holds) is
    // still what gets sent, exactly as before this feature existed.
    ({ promise, calls, elements } = buildHarness({
      fields: { fVenue: { value: 'Community Hall' } }, personWard: 'Amahlathi', confirmedWards: ['Ward 9'],
    }));
    await promise;
    assert.ok(calls.some(c => c.fn === 'api' && c.opts.ward === 'Amahlathi'), 'single-confirmed-ward candidates keep sending personWard unchanged');

    // A candidate confirmed to MULTIPLE wards must explicitly pick one —
    // this is the fix for the bug where such a candidate could never submit
    // an activity at all (the backend rejected the municipality text as an
    // invalid ward choice).
    ({ promise, calls, elements } = buildHarness({
      fields: { fVenue: { value: 'Community Hall' }, fWardChoice: { value: '' } },
      personWard: 'Raymond Mhlaba', confirmedWards: ['Ward 1', 'Ward 4', 'Ward 13'],
    }));
    await promise;
    assert.ok(!calls.some(c => c.fn === 'api'), 'a multi-ward candidate with no ward chosen must never reach the API');
    assert.strictEqual(elements.addStatus.textContent, 'Please select which ward this activity is for.');

    ({ promise, calls, elements } = buildHarness({
      fields: { fVenue: { value: 'Community Hall' }, fWardChoice: { value: 'Ward 13' } },
      personWard: 'Raymond Mhlaba', confirmedWards: ['Ward 1', 'Ward 4', 'Ward 13'],
    }));
    await promise;
    assert.ok(calls.some(c => c.fn === 'api' && c.opts.ward === 'Ward 13'), 'the chosen ward, not the municipality text, must be sent for a multi-ward candidate');

    // A venue that just restates the SELECTED ward is still rejected as ward-only.
    ({ promise, calls, elements } = buildHarness({
      fields: { fVenue: { value: 'Ward 13' }, fWardChoice: { value: 'Ward 13' } },
      personWard: 'Raymond Mhlaba', confirmedWards: ['Ward 1', 'Ward 4', 'Ward 13'],
    }));
    await promise;
    assert.ok(!calls.some(c => c.fn === 'api'));
    assert.strictEqual(elements.addStatus.textContent, 'Please enter the specific location or venue within your municipality.');

    // Offline + no photo: a plain new activity is a safe JSON submission —
    // it must queue for later sync, not be blocked.
    ({ promise, calls, elements } = buildHarness({
      fields: { fVenue: { value: 'Community Hall' } }, personWard: 'Ward 13', photos: [], online: false,
    }));
    await promise;
    assert.ok(calls.some(c => c.fn === 'queuePendingEntry'), 'a new no-photo activity must queue safely while offline');
    assert.ok(!calls.some(c => c.fn === 'api'));
    assert.notStrictEqual(elements.addStatus.textContent, 'Please reconnect to submit this activity with photo evidence.');

    // Offline + a photo already attached: still requires reconnecting —
    // the one case this task's "simple rule" keeps blocked.
    ({ promise, calls, elements } = buildHarness({
      fields: { fVenue: { value: 'Community Hall' } }, personWard: 'Ward 13', photos: [{id: 'p1'}], online: false,
    }));
    await promise;
    assert.ok(!calls.some(c => c.fn === 'queuePendingEntry' || c.fn === 'api'), 'a new activity with a pending photo must not queue or submit offline');
    assert.strictEqual(elements.addStatus.textContent, 'Please reconnect to submit this activity with photo evidence.');

    console.log('ordinary saveBtn location validation tests passed');

    // --- Stage 2C: the week an activity is saved to is never a surprise ---
    const venue = { fVenue: { value: 'Community Hall' } };
    // This week: saved under this week's key and day, then the candidate
    // lands on THIS week's list with a confirmation naming week + date.
    ({ promise, calls } = buildHarness({ fields: Object.assign({ fDate: { value: '2026-09-03' } }, venue), personWard: 'Ward 13', photos: [] }));
    await promise;
    let post = calls.find(c => c.fn === 'api' && c.path === '/api/entries');
    assert.strictEqual(post.opts.week_key, '2026-08-30');
    assert.strictEqual(post.opts.day, 'thu');
    assert.strictEqual(post.opts.activity_date, '2026-09-03');
    let land = calls.find(c => c.fn === 'loadMyWeek');
    assert.strictEqual(land.view, 'list', 'after saving, the candidate lands on the week list');
    assert.deepStrictEqual(land.feedback, { weekKey: '2026-08-30', date: '2026-09-03', pending: false, edited: false, id: 'srv-1' });

    // Next week: saved under next week's key, and the list shown is next week's.
    ({ promise, calls } = buildHarness({ fields: Object.assign({ fDate: { value: '2026-09-08' } }, venue), personWard: 'Ward 13', photos: [], weekKey: '2026-09-06' }));
    await promise;
    post = calls.find(c => c.fn === 'api' && c.path === '/api/entries');
    assert.strictEqual(post.opts.week_key, '2026-09-06');
    assert.strictEqual(post.opts.day, 'tue');
    land = calls.find(c => c.fn === 'loadMyWeek');
    assert.strictEqual(land.selectedWeekKey, '2026-09-06');
    assert.strictEqual(land.feedback.weekKey, '2026-09-06');

    // A date in the OTHER week (form opened for this week, date in next
    // week) is never saved silently: blocked, the week warning shown.
    ({ promise, calls, elements } = buildHarness({ fields: Object.assign({ fDate: { value: '2026-09-08' } }, venue), personWard: 'Ward 13', photos: [] }));
    await promise;
    assert.ok(!calls.some(c => c.fn === 'api' || c.fn === 'queuePendingEntry'), 'a date in another week must not save until the week change is confirmed');
    assert.ok(calls.some(c => c.fn === 'renderWeekWarning'));
    assert.ok(/next week/.test(elements.addStatus.textContent) && /Move to next week/.test(elements.addStatus.textContent) && /Choose a date this week/.test(elements.addStatus.textContent));

    // After "Choose a date this week" the date is empty: Save stays refused
    // until a day in the displayed week is picked.
    ({ promise, calls, elements } = buildHarness({ fields: Object.assign({ fDate: { value: '' } }, venue), personWard: 'Ward 13', photos: [] }));
    await promise;
    assert.ok(!calls.some(c => c.fn === 'api' || c.fn === 'queuePendingEntry'), 'no save without a date');
    assert.strictEqual(elements.addStatus.textContent, 'Please choose a date in this week.');
    ({ promise, calls, elements } = buildHarness({ fields: Object.assign({ fDate: { value: '' } }, venue), personWard: 'Ward 13', photos: [], weekKey: '2026-09-06' }));
    await promise;
    assert.strictEqual(elements.addStatus.textContent, 'Please choose a date in next week.');

    // Offline, a contradicting date is refused just the same — it never
    // reaches the pending queue under the wrong week.
    ({ promise, calls } = buildHarness({ fields: Object.assign({ fDate: { value: '2026-09-08' } }, venue), personWard: 'Ward 13', photos: [], online: false }));
    await promise;
    assert.ok(!calls.some(c => c.fn === 'queuePendingEntry' || c.fn === 'api'), 'offline saves are refused on a week contradiction too');

    // Every saved activity's week matches its own date (never the other week).
    ({ promise, calls } = buildHarness({ fields: Object.assign({ fDate: { value: '2026-09-13' } }, venue), personWard: 'Ward 13', photos: [], weekKey: '2026-09-06' }));
    await promise;
    post = calls.find(c => c.fn === 'api' && c.path === '/api/entries');
    assert.deepStrictEqual([post.opts.week_key, post.opts.day, post.opts.activity_date], ['2026-09-06', 'sun', '2026-09-13']);

    // And the reverse (planning next week, date picked in this week).
    ({ promise, calls, elements } = buildHarness({ fields: Object.assign({ fDate: { value: '2026-09-01' } }, venue), personWard: 'Ward 13', photos: [], weekKey: '2026-09-06' }));
    await promise;
    assert.ok(!calls.some(c => c.fn === 'api'));
    assert.ok(/this week/.test(elements.addStatus.textContent));

    // A date outside both permitted weeks is explained, never sent.
    ({ promise, calls, elements } = buildHarness({ fields: Object.assign({ fDate: { value: '2026-09-20' } }, venue), personWard: 'Ward 13', photos: [] }));
    await promise;
    assert.ok(!calls.some(c => c.fn === 'api'));
    assert.strictEqual(elements.addStatus.textContent, 'Please choose a date in this week or next week.');

    // Offline: queued on the phone, and the confirmation says so — it must
    // not claim the activity reached the server.
    ({ promise, calls } = buildHarness({ fields: Object.assign({ fDate: { value: '2026-09-05' } }, venue), personWard: 'Ward 13', photos: [], online: false }));
    await promise;
    assert.strictEqual(calls.find(c => c.fn === 'queuePendingEntry').entry.week_key, '2026-08-30');
    land = calls.find(c => c.fn === 'loadMyWeek');
    assert.strictEqual(land.feedback.pending, true);
    assert.strictEqual(land.feedback.id, 'pending-local-1', 'the queued row is highlighted in the list');

    // An existing record (even one with a historical blank venue) can still
    // be opened and updated through the normal PUT.
    ({ promise, calls } = buildHarness({
      fields: { fDate: { value: '2026-09-02' }, fVenue: { value: '' } }, personWard: 'Ward 13', photos: [],
      editing: { key: 'e-old', entry: { id: 'e-old', type: 'Door to Door', type_display: 'Door to Door', week_key: '2026-08-30', day: 'tue', venue: '' } },
    }));
    await promise;
    const put = calls.find(c => c.fn === 'api' && c.method === 'PUT');
    assert.ok(put && put.path === '/api/entries/e-old', 'editing an existing record uses PUT /api/entries/{id}');
    assert.strictEqual(put.opts.week_key, '2026-08-30');
    land = calls.find(c => c.fn === 'loadMyWeek');
    assert.deepStrictEqual([land.feedback.edited, land.feedback.id], [true, 'e-old']);

    console.log('Stage 2C week-selection save tests passed');
  })();
}

// --- selectedOtherParticipants: manual name entry (zero/one/many/duplicates) ---
{
  const selectedOtherParticipantsSrc = extractFunctionSource(html, 'selectedOtherParticipants');

  function run(values) {
    const body = `
      const document = { querySelectorAll(sel){ return ${JSON.stringify(values)}.map(v=>({value:v})); } };
      ${selectedOtherParticipantsSrc}
      return selectedOtherParticipants();
    `;
    return new Function(body)();
  }

  assert.deepStrictEqual(run([]), [], 'zero manual names is allowed and returns an empty list');
  assert.deepStrictEqual(run(['']), [], 'a blank row contributes nothing');
  assert.deepStrictEqual(run(['Thabo Mokoena']), ['Thabo Mokoena'], 'one manual name');
  assert.deepStrictEqual(
    run(['Thabo Mokoena', 'Sarah Daniels']),
    ['Thabo Mokoena', 'Sarah Daniels'],
    'multiple manual names, in entry order'
  );
  assert.deepStrictEqual(
    run(['Thabo Mokoena', 'thabo mokoena', '  Thabo   Mokoena  ']),
    ['Thabo Mokoena'],
    'case/whitespace-insensitive duplicates collapse to the first spelling, per existing normalization'
  );
  console.log('selectedOtherParticipants manual-name tests passed');
}

// --- resetActivityExtras / selectedRosterParticipantIds: new vs. edit ---
{
  const resetActivityExtrasSrc = extractFunctionSource(html, 'resetActivityExtras');
  const selectedRosterParticipantIdsSrc = extractFunctionSource(html, 'selectedRosterParticipantIds');

  function run(entry) {
    const otherParticipantsAdded = [];
    const body = `
      let otherParticipantRows = 0;
      let evidencePhotos = [];
      const elements = { fOtherParticipants: { innerHTML: '' } };
      function $(id){ return elements[id]; }
      function addOtherParticipantInput(value){ otherParticipantsAdded.push(value); }
      function renderEvidencePreview(){}
      ${resetActivityExtrasSrc}
      ${selectedRosterParticipantIdsSrc}
      resetActivityExtras(${JSON.stringify(entry)});
      return selectedRosterParticipantIds();
    `;
    const fn = new Function('otherParticipantsAdded', `return (function(){ ${body} })();`);
    return fn(otherParticipantsAdded);
  }

  assert.deepStrictEqual(run(null), [], 'a brand-new activity never sends participant_ids — no roster selection is required');
  assert.deepStrictEqual(
    run({ participant_ids: ['bob-candidate'], other_participants: [] }),
    ['bob-candidate'],
    'editing an activity that already has historical roster participant_ids must preserve them unchanged — there is no UI to alter them any more'
  );
  console.log('participant_ids preserved-on-edit / empty-on-new tests passed');
}
