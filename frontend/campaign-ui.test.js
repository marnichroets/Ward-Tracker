const assert = require('assert');
const fs = require('fs');
const path = require('path');
const WeekDates = require('./week-dates');

// Phase 3: candidate-facing campaign UI (list, create, detail, add activity,
// weekly repeat, archived-campaign guard). These tests execute the real
// production functions extracted from index.html (not a re-implementation)
// against a tiny DOM/network stub, matching the convention already
// established in roster-selection.test.js.

const html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');
const DAY_ORDER = WeekDates.DAY_ORDER;

function extractFunctionSource(src, name) {
  const marker = `function ${name}(`;
  let start = src.indexOf(marker);
  if (start === -1) throw new Error(`could not find function ${name}() in index.html`);
  // Preserve `async` — a plain `function ${name}(` search lands after it.
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

// --- Structural checks on the markup itself ---
assert.ok(html.includes('id="campaignsSection"'), 'campaigns section must exist on the candidate home screen');
assert.ok(html.includes('id="startCampaignBtn"'), 'Start Campaign button must exist');
assert.ok(html.includes('id="screenStartCampaign"'), 'Start Campaign screen must exist');
assert.ok(html.includes('id="screenCampaignDetail"'), 'Campaign detail screen must exist');
assert.ok(html.includes('id="fRepeatWeekly"'), 'Repeat weekly checkbox must exist on the add-activity form');
assert.ok(/for="fVenue">Location \/ Venue \*/.test(html), 'Venue field must be labelled "Location / Venue *"');
assert.ok(html.includes('Enter where this activity will take place.'), 'Venue helper text must be present');
assert.ok(!/navigator\.geolocation/.test(html), 'no GPS/geolocation code must be present in this phase');
assert.ok(!/location_lat|location_lng|location_source/.test(html), 'no coordinate fields must be present in this phase');

const campaignDateRangeSrc = extractFunctionSource(html, 'campaignDateRange');
const campaignStatusLabelSrc = extractFunctionSource(html, 'campaignStatusLabel');
const escapeHtmlSrc = extractFunctionSource(html, 'escapeHtml');
const renderCampaignCardSrc = extractFunctionSource(html, 'renderCampaignCard');
const formatTimeRangeSrc = extractFunctionSource(html, 'formatTimeRange');
const legacyActivityTextSrc = extractFunctionSource(html, 'legacyActivityText');

// --- campaignDateRange / campaignStatusLabel / renderCampaignCard ---
{
  const body = `
    ${escapeHtmlSrc}
    ${campaignDateRangeSrc}
    ${campaignStatusLabelSrc}
    ${renderCampaignCardSrc}
    return {campaignDateRange, campaignStatusLabel, renderCampaignCard};
  `;
  const { campaignDateRange, campaignStatusLabel, renderCampaignCard } = new Function('WeekDates', body)(WeekDates);

  assert.strictEqual(campaignDateRange({start_date:'2026-09-05', end_date:'2026-09-26'}), '5 Sep – 26 Sep');
  assert.strictEqual(campaignStatusLabel('planned'), 'Planned');
  assert.strictEqual(campaignStatusLabel('archived'), 'Archived');

  const activeCardHtml = renderCampaignCard({id:'abc123', name:'Ward 13 Drive', start_date:'2026-09-05', end_date:'2026-09-26', status:'active'});
  assert.ok(activeCardHtml.includes('Ward 13 Drive'));
  assert.ok(activeCardHtml.includes('data-open-campaign="abc123"'));
  assert.ok(!activeCardHtml.includes('cbadge archived'), 'an active campaign must not get the archived badge class');

  const archivedCardHtml = renderCampaignCard({id:'xyz', name:'Old Drive', start_date:'2026-01-01', end_date:'2026-01-10', status:'archived'});
  assert.ok(archivedCardHtml.includes('cbadge archived'), 'an archived campaign must get the archived badge class');

  console.log('campaign card rendering tests passed');
}

// --- renderCampaignsSection: active vs. past categorization ---
{
  const renderCampaignsSectionSrc = extractFunctionSource(html, 'renderCampaignsSection');
  const elements = {
    campaignsSection: { hidden: false },
    campaignList: { innerHTML: '' },
    pastCampaignsToggle: { hidden: false, textContent: '' },
    pastCampaignList: { hidden: false, innerHTML: '' },
  };
  // renderCampaignsSection reads the outer `campaigns`/`pastCampaignsOpen`
  // closures directly (as it does in index.html); reproduce that by
  // re-declaring them as the function's free variables via `this` isn't
  // possible for a plain function body, so instead build one Function per
  // scenario with the values baked in as top-level bindings.
  function renderWith(campaigns, pastCampaignsOpen) {
    const doc = { querySelectorAll: () => [] };
    const scenario = new Function('elements', 'document', 'WeekDates', `
      let campaigns = ${JSON.stringify(campaigns)};
      let pastCampaignsOpen = ${JSON.stringify(pastCampaignsOpen)};
      function $(id){ return elements[id]; }
      ${escapeHtmlSrc}
      ${campaignDateRangeSrc}
      ${campaignStatusLabelSrc}
      ${renderCampaignCardSrc}
      ${renderCampaignsSectionSrc}
      renderCampaignsSection();
    `);
    scenario(elements, doc, WeekDates);
  }

  renderWith([
    {id:'1', name:'Active One', start_date:'2026-09-01', end_date:'2026-09-20', status:'active'},
    {id:'2', name:'Planned One', start_date:'2026-10-01', end_date:'2026-10-20', status:'planned'},
    {id:'3', name:'Done One', start_date:'2026-01-01', end_date:'2026-01-10', status:'completed'},
    {id:'4', name:'Old One', start_date:'2025-01-01', end_date:'2025-01-10', status:'archived'},
  ], false);
  assert.strictEqual(elements.campaignsSection.hidden, false);
  assert.ok(elements.campaignList.innerHTML.includes('Active One'));
  assert.ok(elements.campaignList.innerHTML.includes('Planned One'));
  assert.ok(!elements.campaignList.innerHTML.includes('Done One'), 'completed campaigns must not appear in the main active list');
  assert.ok(!elements.campaignList.innerHTML.includes('Old One'), 'archived campaigns must not appear in the main active list');
  assert.strictEqual(elements.pastCampaignsToggle.hidden, false);
  assert.ok(elements.pastCampaignsToggle.textContent.includes('2'), 'past-campaigns toggle must show the count');
  assert.strictEqual(elements.pastCampaignList.hidden, true, 'past list stays collapsed until toggled');

  renderWith([], false);
  assert.strictEqual(elements.campaignsSection.hidden, true, 'the whole section hides when there are no active campaigns and no past ones shown by default');

  renderWith([
    {id:'3', name:'Done One', start_date:'2026-01-01', end_date:'2026-01-10', status:'completed'},
  ], false);
  assert.strictEqual(elements.campaignsSection.hidden, false, 'section must stay visible so the past-campaigns toggle remains reachable when there are no active campaigns');
  assert.strictEqual(elements.campaignList.innerHTML, '');
  assert.strictEqual(elements.pastCampaignsToggle.hidden, false, 'past-campaigns toggle must still be reachable with zero active campaigns');

  console.log('renderCampaignsSection categorization tests passed');
}

// --- updateRepeatVisibility: repeat option only for a new activity inside a non-archived campaign ---
{
  const updateRepeatVisibilitySrc = extractFunctionSource(html, 'updateRepeatVisibility');
  function runScenario({ editingKey, editingPendingLocalId, activeCampaign }) {
    const elements = {
      fRepeatField: { hidden: false },
      fRepeatWeekly: { checked: true },
      fRepeatUntilField: { hidden: false },
    };
    const fn = new Function('elements', `
      let editingKey = ${JSON.stringify(editingKey)};
      let editingPendingLocalId = ${JSON.stringify(editingPendingLocalId)};
      let activeCampaign = ${JSON.stringify(activeCampaign)};
      function $(id){ return elements[id]; }
      ${updateRepeatVisibilitySrc}
      updateRepeatVisibility();
    `);
    fn(elements);
    return elements;
  }

  let els = runScenario({ editingKey: null, editingPendingLocalId: null, activeCampaign: { status: 'active' } });
  assert.strictEqual(els.fRepeatField.hidden, false, 'a new activity inside an active campaign must offer Repeat weekly');

  els = runScenario({ editingKey: 'abc', editingPendingLocalId: null, activeCampaign: { status: 'active' } });
  assert.strictEqual(els.fRepeatField.hidden, true, 'editing an existing occurrence must never offer Repeat weekly');
  assert.strictEqual(els.fRepeatWeekly.checked, false, 'the checkbox must be forced off when hidden');

  els = runScenario({ editingKey: null, editingPendingLocalId: null, activeCampaign: null });
  assert.strictEqual(els.fRepeatField.hidden, true, 'the ordinary non-campaign flow must never show Repeat weekly');

  els = runScenario({ editingKey: null, editingPendingLocalId: null, activeCampaign: { status: 'archived' } });
  assert.strictEqual(els.fRepeatField.hidden, true, 'an archived campaign must never offer Repeat weekly');

  console.log('updateRepeatVisibility tests passed');
}

// --- renderDayChips: date bounds follow the active campaign, not the selected week ---
{
  const renderDayChipsSrc = extractFunctionSource(html, 'renderDayChips');
  const isDateInWeekSrc = extractFunctionSource(html, 'isDateInWeek');
  const weekStartYmdSrc = extractFunctionSource(html, 'weekStartYmd');
  const weekEndYmdSrc = extractFunctionSource(html, 'weekEndYmd');
  const defaultActivityDateSrc = extractFunctionSource(html, 'defaultActivityDate');

  function runScenario({ activeCampaign, selectedWeekKey, initialDateValue }) {
    const elements = { fDate: { value: initialDateValue, min: '', max: '' } };
    const fn = new Function('elements', 'WeekDates', `
      let activeCampaign = ${JSON.stringify(activeCampaign)};
      let selectedWeekKey = ${JSON.stringify(selectedWeekKey)};
      function $(id){ return elements[id]; }
      ${weekStartYmdSrc}
      ${weekEndYmdSrc}
      ${isDateInWeekSrc}
      ${defaultActivityDateSrc}
      ${renderDayChipsSrc}
      renderDayChips();
    `);
    fn(elements, WeekDates);
    return elements.fDate;
  }

  let f = runScenario({ activeCampaign: { start_date: '2026-09-05', end_date: '2026-09-26' }, selectedWeekKey: '2026-08-30', initialDateValue: '' });
  assert.strictEqual(f.min, '2026-09-05');
  assert.strictEqual(f.max, '2026-09-26');
  assert.ok(f.value >= '2026-09-05' && f.value <= '2026-09-26', 'a fresh campaign date must default inside the campaign range');

  f = runScenario({ activeCampaign: { start_date: '2026-09-05', end_date: '2026-09-26' }, selectedWeekKey: '2026-08-30', initialDateValue: '2026-10-01' });
  assert.ok(f.value >= '2026-09-05' && f.value <= '2026-09-26', 'a date outside the campaign range must be corrected back into range');

  f = runScenario({ activeCampaign: null, selectedWeekKey: '2026-08-30', initialDateValue: '' });
  assert.strictEqual(f.min, WeekDates.ymdFromDate(WeekDates.reportingWeekStart('2026-08-30')), 'the ordinary (non-campaign) flow must still bound dates to the selected week');

  console.log('renderDayChips campaign-bound date tests passed');
}

// --- saveCampaignActivity: routes to the correct campaign endpoint, never /api/entries ---
{
  const saveCampaignActivitySrc = extractFunctionSource(html, 'saveCampaignActivity');
  const resolveOtherActivityTextSrc = extractFunctionSource(html, 'resolveOtherActivityText');

  function buildHarness({ fields, activeCampaign, editingKey, editingOriginalEntry }) {
    const calls = [];
    const elements = Object.assign({
      fDate: { value: '' }, fStartTime: { value: '' }, fEndTime: { value: '' },
      fVenue: { value: '' }, fActivity: { value: 'Door to Door' },
      fOtherActivity: { value: '' }, fRepeatWeekly: { checked: false }, fRepeatUntil: { value: '' },
      saveBtn: { disabled: false, textContent: '' }, addStatus: { textContent: '', className: '' },
    }, fields);
    const body = `
      const OTHER_OPTION = 'Other';
      let selectedType = null;
      let editingKey = ${JSON.stringify(editingKey || null)};
      let editingPendingLocalId = null;
      let editingOriginalEntry = ${JSON.stringify(editingOriginalEntry || null)};
      let activeCampaign = ${JSON.stringify(activeCampaign)};
      const personId = 'test-candidate', personName = 'Test Candidate', personWard = 'Ward 1';
      function $(id){ return elements[id]; }
      function showAddStatus(ok, msg){ elements.addStatus.textContent = msg; }
      async function openCampaignDetail(id){ calls.push({fn:'openCampaignDetail', id}); }
      async function api(path, opts){ calls.push({path, opts: opts && JSON.parse(opts.body || 'null'), method: opts && opts.method}); return {}; }
      ${resolveOtherActivityTextSrc}
      ${legacyActivityTextSrc}
      ${saveCampaignActivitySrc}
      return saveCampaignActivity();
    `;
    const factory = new Function('elements', 'calls', 'DAY_ORDER', `return (async()=>{ ${body} })();`);
    return { promise: factory(elements, calls, DAY_ORDER), calls, elements };
  }

  // New single activity: must hit the single-activity endpoint, never /api/entries.
  (async () => {
    const { promise, calls } = buildHarness({
      fields: {
        fDate: { value: '2026-09-19' }, fStartTime: { value: '09:00' }, fEndTime: { value: '12:00' },
        fVenue: { value: 'Ward 7 Main Road' },
      },
      activeCampaign: { id: 'camp1', start_date: '2026-09-05', end_date: '2026-09-26', status: 'active' },
    });
    await promise;
    const apiCalls = calls.filter(c => c.path);
    assert.strictEqual(apiCalls.length, 1);
    assert.strictEqual(apiCalls[0].path, '/api/campaigns/camp1/activities');
    assert.strictEqual(apiCalls[0].method, 'POST');
    assert.strictEqual(apiCalls[0].opts.venue, 'Ward 7 Main Road');
    assert.ok(!apiCalls.some(c => c.path === '/api/entries'), 'a campaign activity must never hit the plain /api/entries endpoint');
    console.log('saveCampaignActivity single-activity routing test passed');
  })();

  // New repeating activity: must hit the repeat endpoint with the correct derived weekday.
  (async () => {
    const { promise, calls } = buildHarness({
      fields: {
        fDate: { value: '2026-09-19' }, fStartTime: { value: '09:00' }, fEndTime: { value: '12:00' },
        fVenue: { value: 'Ward 7 Main Road' }, fRepeatWeekly: { checked: true }, fRepeatUntil: { value: '2026-10-03' },
      },
      activeCampaign: { id: 'camp1', start_date: '2026-09-05', end_date: '2026-09-26', status: 'active' },
    });
    await promise;
    const apiCalls = calls.filter(c => c.path);
    assert.strictEqual(apiCalls.length, 1);
    assert.strictEqual(apiCalls[0].path, '/api/campaigns/camp1/activities/repeat');
    assert.strictEqual(apiCalls[0].opts.weekday, 'sat', '2026-09-19 is a Saturday');
    assert.strictEqual(apiCalls[0].opts.until, '2026-10-03');
    console.log('saveCampaignActivity repeat routing + weekday derivation test passed');
  })();

  // Editing an existing occurrence must go through the normal PUT /api/entries/{id}.
  (async () => {
    const { promise, calls } = buildHarness({
      fields: {
        fDate: { value: '2026-09-19' }, fStartTime: { value: '10:00' }, fEndTime: { value: '13:00' },
        fVenue: { value: 'Changed Venue' },
      },
      activeCampaign: { id: 'camp1', start_date: '2026-09-05', end_date: '2026-09-26', status: 'active' },
      editingKey: 'entry123',
      editingOriginalEntry: { day: 'sat', week_key: '2026-09-13', week_label: '14 Sep - 20 Sep', notes: null, type: 'Door to Door', type_display: 'Door to Door' },
    });
    await promise;
    const apiCalls = calls.filter(c => c.path);
    assert.strictEqual(apiCalls.length, 1);
    assert.strictEqual(apiCalls[0].path, '/api/entries/entry123');
    assert.strictEqual(apiCalls[0].method, 'PUT');
    console.log('saveCampaignActivity edit routing test passed');
  })();

  // Missing venue on a NEW campaign activity must block the save entirely (no api() call).
  (async () => {
    const { promise, calls, elements } = buildHarness({
      fields: {
        fDate: { value: '2026-09-19' }, fStartTime: { value: '09:00' }, fEndTime: { value: '12:00' },
        fVenue: { value: '' },
      },
      activeCampaign: { id: 'camp1', start_date: '2026-09-05', end_date: '2026-09-26', status: 'active' },
    });
    await promise;
    assert.strictEqual(calls.filter(c => c.path).length, 0, 'a missing Location/Venue must block save before any network call');
    assert.ok(elements.addStatus.textContent.toLowerCase().includes('location'));
    console.log('saveCampaignActivity required-venue-for-new-activity test passed');
  })();

  // A date outside the campaign's own range must block the save.
  (async () => {
    const { promise, calls } = buildHarness({
      fields: {
        fDate: { value: '2026-10-05' }, fStartTime: { value: '09:00' }, fEndTime: { value: '12:00' },
        fVenue: { value: 'Ward 7 Main Road' },
      },
      activeCampaign: { id: 'camp1', start_date: '2026-09-05', end_date: '2026-09-26', status: 'active' },
    });
    await promise;
    assert.strictEqual(calls.filter(c => c.path).length, 0, 'a date outside the campaign range must never reach the API');
    console.log('saveCampaignActivity date-boundary test passed');
  })();
}

// --- cSaveBtn: client-side 1-42 day duration validation mirrors the backend rule ---
{
  const cSaveHandlerBody = extractBlock(html, "$('cSaveBtn').onclick = async ()=>{");
  function run({ name, startDate, endDate }) {
    const calls = [];
    const elements = {
      cName: { value: name }, cStartDate: { value: startDate }, cEndDate: { value: endDate },
      cSaveBtn: { disabled: false, textContent: '' }, cStatus: { textContent: '', className: '' },
    };
    const fn = new Function('elements', 'calls', 'WeekDates', `return (async()=>{
      const personId = 'test-candidate';
      function $(id){ return elements[id]; }
      function showCampaignStatus(ok, msg){ elements.cStatus.textContent = msg; elements.cStatus.className = 'status show ' + (ok?'ok':'err'); }
      async function api(path, opts){ calls.push({path, opts: opts && JSON.parse(opts.body || 'null')}); return {id:'newcamp'}; }
      async function loadCampaigns(){}
      async function openCampaignDetail(){}
      ${cSaveHandlerBody}
    })();`);
    return fn(elements, calls, WeekDates).then(() => ({ calls, elements }));
  }

  (async () => {
    let { calls, elements } = await run({ name: 'Ward 13 Drive', startDate: '2026-09-01', endDate: '2026-10-12' }); // 42 inclusive days
    assert.strictEqual(calls.length, 1, 'exactly 42 inclusive days must be accepted');

    ({ calls, elements } = await run({ name: 'Ward 13 Drive', startDate: '2026-09-01', endDate: '2026-10-13' })); // 43 days
    assert.strictEqual(calls.length, 0, '43 inclusive days must be rejected client-side');
    assert.ok(elements.cStatus.textContent.includes('42'));

    ({ calls, elements } = await run({ name: '', startDate: '2026-09-01', endDate: '2026-09-05' }));
    assert.strictEqual(calls.length, 0, 'a blank campaign name must be rejected');

    ({ calls, elements } = await run({ name: 'X', startDate: '2026-09-10', endDate: '2026-09-01' }));
    assert.strictEqual(calls.length, 0, 'end date before start date must be rejected');

    console.log('Start Campaign duration-validation tests passed');
  })();
}

// --- openCampaignDetail: archived campaigns hide Add Activity and show the banner ---
{
  const openCampaignDetailSrc = extractFunctionSource(html, 'openCampaignDetail');

  function run(campaignStatus) {
    const elements = {
      cdName: { textContent: '' }, cdRange: { textContent: '' },
      cdArchivedBanner: { hidden: false }, cdActList: { innerHTML: '' },
      cdAddActivityBtn: { style: { display: '' } },
    };
    const shown = [];
    const fn = new Function('elements', 'shown', 'WeekDates', 'formatTimeRangeSrcText', 'escapeHtmlSrcText', 'campaignDateRangeSrcText', `return (async()=>{
      let activeCampaign = null;
      function $(id){ return elements[id]; }
      function show(id){ shown.push(id); }
      const document = { querySelectorAll: () => [] };
      async function api(path){
        if(path.endsWith('/activities')) return [];
        return { id:'camp1', name:'Test Campaign', start_date:'2026-09-05', end_date:'2026-09-26', status: ${JSON.stringify(campaignStatus)} };
      }
      eval(escapeHtmlSrcText);
      eval(campaignDateRangeSrcText);
      eval(formatTimeRangeSrcText);
      ${openCampaignDetailSrc}
      await openCampaignDetail('camp1');
      return elements;
    })();`);
    return fn(elements, shown, WeekDates, formatTimeRangeSrc, escapeHtmlSrc, campaignDateRangeSrc);
  }

  (async () => {
    const activeEls = await run('active');
    assert.strictEqual(activeEls.cdArchivedBanner.hidden, true);
    assert.strictEqual(activeEls.cdAddActivityBtn.style.display, 'block');

    const archivedEls = await run('archived');
    assert.strictEqual(archivedEls.cdArchivedBanner.hidden, false, 'the Archived banner must show for an archived campaign');
    assert.strictEqual(archivedEls.cdAddActivityBtn.style.display, 'none', 'Add Activity must be hidden for an archived campaign');

    console.log('openCampaignDetail archived-guard tests passed');
  })();
}
