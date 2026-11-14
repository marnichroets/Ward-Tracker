const assert = require('assert');
const fs = require('fs');
const path = require('path');
const WeekDates = require('./week-dates');
const SmartSheetActivities = require('./smartsheet-activities');
const TimeOptions = require('./time-options');

// PHO Stage 2: faster candidate capture on a phone. Quick-pick chips only
// FILL the existing fields — validation, payloads and the save path are
// unchanged — so these tests cover the pick logic, the markup contract and
// HTML escaping, executed as the real source extracted from index.html.

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
    else if (src[i] === '}') { depth--; if (depth === 0) { i++; break; } }
  }
  return src.slice(start, i);
}
const constLine = (name) => {
  const m = html.match(new RegExp(`^const ${name} = [^\\n]*;$`, 'm'));
  if (!m) throw new Error(`const ${name} not found`);
  return m[0];
};
const escapeHtmlSrc = extractFunctionSource(html, 'escapeHtml');

// --- Expired election countdown is gone (not just hidden) ---
{
  assert.ok(!/electionDays|Election Day Countdown|updateElectionCountdown|election-countdown/.test(html), 'the expired election countdown must be fully removed');
  console.log('election countdown removed');
}

// --- Form order and structure: what → when → where; optional extras folded ---
{
  const add = html.slice(html.indexOf('id="screenAdd"'), html.indexOf('id="screenStartCampaign"'));
  const at = (needle) => { const i = add.indexOf(needle); assert.ok(i > -1, `missing ${needle}`); return i; };
  assert.ok(at('id="fActivity"') < at('id="fDate"') && at('id="fDate"') < at('id="fStartTime"') && at('id="fStartTime"') < at('id="fVenue"'),
    'fields follow the agreed candidate flow: Activity → Date → Start/End → Location');
  ['fActivityChips', 'fDateChips', 'fVenueChips'].forEach((id) => at(`id="${id}"`));
  const more = at('id="fMoreDetails"');
  assert.ok(more < at('id="fOtherParticipantsField"') && at('id="fEvidenceField"') < add.indexOf('</details>', more),
    'helpers and read-only historical evidence sit inside Additional details');
  assert.strictEqual((add.match(/id="saveBtn"/g) || []).length, 1, 'still exactly one Save button');
  // Stage 2C: Save sits in normal flow after the form, with its status line
  // directly above it — a sticky button could cover fields, validation
  // errors or the keyboard's focused input on a phone.
  assert.ok(!/#saveBtn\{[^}]*position:\s*sticky/.test(html) && !/#saveBtn\{[^}]*position:\s*fixed/.test(html), 'Save is never sticky/fixed over the form');
  assert.ok(at('</details>') < at('id="addStatus"') && at('id="addStatus"') < at('id="saveBtn"'), 'status sits just above Save, after the optional fold');
  // Four plain sections: What → When → Where → Additional details.
  assert.ok(at('What activity?') < at('When?') && at('When?') < at('Where?') && at('Where?') < at('Additional details'), 'the form reads What → When → Where → Additional details');
  assert.ok(at('id="fWhenWeek"') < at('id="fDateChips"'), 'the week being worked in is named right above the day shortcuts');
  assert.ok(at('id="addWeekBanner"') < at('What activity?'), 'the week banner heads the form');
  assert.ok(more < at('id="fCampaignField"'), 'the optional campaign link lives in the Additional details fold');
  // The venue placeholder is neutral: never a sample ward/place that could
  // contradict the candidate's own ward and municipality shown above it.
  const venueTag = add.match(/<input[^>]*id="fVenue"[^>]*>/)[0];
  assert.ok(/placeholder="Enter venue or area"/.test(venueTag), 'neutral venue placeholder');
  assert.ok(!/Ward \d|Mlungisi/.test(venueTag), 'the placeholder names no ward or place');
  console.log('add-activity form order and optional fold are correct');
}

// --- Candidate home: two week panels, each with its own add/review ---
{
  const home = html.slice(html.indexOf('id="screenWeek"'), html.indexOf('id="screenWeekList"'));
  ['addThisWeekBtn', 'reviewThisWeekBtn', 'addNextWeekBtn', 'reviewNextWeekBtn', 'thisWeekRange', 'nextWeekRange'].forEach((id) =>
    assert.ok(home.includes(`id="${id}"`), `home screen has ${id}`));
  assert.ok(home.indexOf('id="weekPanelThis"') < home.indexOf('id="weekPanelNext"'), 'this week comes first');
  assert.ok(home.indexOf('id="weekPanelNext"') < home.indexOf('id="campaignsSection"'), 'campaigns sit below both weeks (secondary)');
  assert.ok(!/weekTabs|reminderCards|deadlineNote/.test(html), 'the old competing tabs/reminder cards are gone');
  assert.strictEqual((home.match(/class="btn primary"/g) || []).length, 2, 'exactly one primary action per week on the home screen');
  console.log('candidate home has one clear panel per week');
}

// --- Day shortcuts always match the week being worked in ---
{
  const fn = new Function('WeekDates', 'elements', `
    ${constLine('SHORT_DAYS')}
    ${escapeHtmlSrc}
    ${extractFunctionSource(html, 'quickDateChoices')}
    ${extractFunctionSource(html, 'renderQuickChips')}
    ${extractFunctionSource(html, 'weekStartYmd')}
    ${extractFunctionSource(html, 'weekEndYmd')}
    ${extractFunctionSource(html, 'renderDateChips')}
    function $(id){ return elements[id]; }
    let activeCampaign = null, selectedWeekKey = null;
    return (weekKey, campaign) => { selectedWeekKey = weekKey; activeCampaign = campaign || null; renderDateChips(); };`);
  const classes = new Set();
  const elements = {
    fDate: { value: '', min: '2026-11-09', max: '2026-11-22' },
    fDateChips: { innerHTML: '', hidden: true, classList: { toggle: (c, on) => (on ? classes.add(c) : classes.delete(c)) } },
  };
  const render = fn(WeekDates, elements);
  const days = () => [...elements.fDateChips.innerHTML.matchAll(/data-quick-value="([^"]+)"/g)].map((m) => m[1]);
  render('2026-11-08');
  assert.deepStrictEqual(days(), ['2026-11-09', '2026-11-10', '2026-11-11', '2026-11-12', '2026-11-13', '2026-11-14', '2026-11-15'], 'this week: Mon 9 – Sun 15');
  assert.ok(classes.has('daychips'));
  render('2026-11-15');
  assert.deepStrictEqual(days(), ['2026-11-16', '2026-11-17', '2026-11-18', '2026-11-19', '2026-11-20', '2026-11-21', '2026-11-22'], 'next week: Mon 16 – Sun 22, never this week');
  assert.ok(/aria-label="Mon 16"/.test(elements.fDateChips.innerHTML), 'each day chip has a readable label');
  elements.fDate.min = '2026-11-01'; elements.fDate.max = '2026-12-10';
  render('2026-11-15', { start_date: '2026-11-01', end_date: '2026-12-10' });
  assert.ok(days().every((d) => d >= '2026-11-01' && d <= '2026-12-10'), 'a campaign uses its own range');
  assert.ok(!classes.has('daychips'));
  console.log('day shortcuts follow the selected week');
}

function handlerBody(id) {
  const marker = `$('${id}').onclick = ()=>{`;
  const start = html.indexOf(marker);
  if (start === -1) throw new Error(`handler for ${id} not found`);
  let depth = 0, i = html.indexOf('{', start);
  const open = i;
  for (; i < html.length; i++) {
    if (html[i] === '{') depth++;
    else if (html[i] === '}') { depth--; if (depth === 0) break; }
  }
  return html.slice(open + 1, i);
}

// --- Week warning + week banner: the week is always stated, changes confirmed ---
{
  const setup = new Function('WeekDates', 'elements', `
    ${escapeHtmlSrc}
    ${extractFunctionSource(html, 'weekStartYmd')}
    ${extractFunctionSource(html, 'weekEndYmd')}
    ${extractFunctionSource(html, 'isDateInWeek')}
    ${extractFunctionSource(html, 'weekName')}
    ${extractFunctionSource(html, 'candidateWeekKeyForDate')}
    ${extractFunctionSource(html, 'campaignDateRange')}
    ${extractFunctionSource(html, 'saveButtonLabel')}
    ${extractFunctionSource(html, 'renderAddWeekBanner')}
    ${extractFunctionSource(html, 'renderWeekWarning')}
    const CURRENT_WEEK_KEY = '2026-11-08', NEXT_WEEK_KEY = '2026-11-15';
    let selectedWeekKey = CURRENT_WEEK_KEY, activeCampaign = null, editingKey = null, editingPendingLocalId = null;
    function $(id){ return elements[id]; }
    function refreshAddWeek(){ renderAddWeekBanner(); renderWeekWarning(); }
    function showAddStatus(ok, msg){ elements.addStatus.textContent = msg; }
    function clickMove(){ ${handlerBody('fWeekMoveBtn')} }
    function clickChoose(){ ${handlerBody('fWeekKeepBtn')} }
    return {
      set(wk, opts){ selectedWeekKey = wk; activeCampaign = (opts && opts.campaign) || null; editingKey = (opts && opts.editingKey) || null; },
      week: () => selectedWeekKey,
      renderAddWeekBanner, renderWeekWarning, clickMove, clickChoose,
    };`);
  const el = (extra) => Object.assign({ textContent: '', innerHTML: '', hidden: false, className: '', classList: { toggle() {} } }, extra);
  const elements = {
    addWeekBanner: el(), addGreet: el(), addTitle: el(), addWeekNote: el(), fWhenWeek: el(), saveBtn: el(),
    fDate: el({ value: '' }), fWeekWarning: el({ hidden: true }), fWeekWarningText: el(), fWeekWarningActions: el(),
    fWeekMoveBtn: el(), fWeekKeepBtn: el(), fDateChips: el(), addStatus: el(),
  };
  const h = setup(WeekDates, elements);

  h.set('2026-11-08'); h.renderAddWeekBanner();
  assert.strictEqual(elements.addGreet.textContent, 'Adding to');
  assert.strictEqual(elements.addTitle.textContent, 'This week');
  assert.strictEqual(elements.addWeekNote.textContent, '9–15 November 2026');
  assert.strictEqual(elements.fWhenWeek.textContent, 'This week · 9–15 November');
  assert.strictEqual(elements.saveBtn.textContent, 'Save to this week');

  h.set('2026-11-15'); h.renderAddWeekBanner();
  assert.strictEqual(elements.addGreet.textContent, 'Planning for');
  assert.strictEqual(elements.addTitle.textContent, 'Next week');
  assert.strictEqual(elements.addWeekNote.textContent, '16–22 November 2026');
  assert.ok(/next/.test(elements.addWeekBanner.className), 'next week has its own colour');
  assert.strictEqual(elements.saveBtn.textContent, 'Save to next week');

  h.set('2026-11-08', { editingKey: 'e1' }); h.renderAddWeekBanner();
  assert.strictEqual(elements.addGreet.textContent, 'Editing an activity in');
  assert.strictEqual(elements.saveBtn.textContent, 'Save changes');

  h.set('2026-11-08', { campaign: { name: 'Ward 4 Drive', start_date: '2026-10-23', end_date: '2026-11-25' } }); h.renderAddWeekBanner();
  assert.strictEqual(elements.addTitle.textContent, 'Ward 4 Drive');
  assert.strictEqual(elements.saveBtn.textContent, 'Save campaign activity');

  // Same week: no warning.
  h.set('2026-11-08'); elements.fDate.value = '2026-11-12'; h.renderWeekWarning();
  assert.strictEqual(elements.fWeekWarning.hidden, true);
  // Deliberately picked a next-week date while adding to this week.
  elements.fDate.value = '2026-11-17'; h.renderWeekWarning();
  assert.strictEqual(elements.fWeekWarning.hidden, false, 'a date in the other week is clearly flagged');
  assert.ok(elements.fWeekWarningText.innerHTML.includes('Tuesday, 17 November is in NEXT WEEK'));
  assert.strictEqual(elements.fWeekMoveBtn.textContent, 'Move to next week');
  assert.strictEqual(elements.fWeekKeepBtn.textContent, 'Choose a date this week', 'the alternative asks for a date, never implies one is kept');
  assert.strictEqual(elements.fWeekMoveBtn.hidden, false);
  // Planning next week, but picked a date in this week.
  h.set('2026-11-15'); elements.fDate.value = '2026-11-10'; h.renderWeekWarning();
  assert.ok(elements.fWeekWarningText.innerHTML.includes('is in THIS WEEK'));
  assert.strictEqual(elements.fWeekMoveBtn.textContent, 'Move to this week');
  assert.strictEqual(elements.fWeekKeepBtn.textContent, 'Choose a date next week');
  // Outside both permitted weeks: explained, no "move" offered.
  elements.fDate.value = '2026-12-01'; h.renderWeekWarning();
  assert.strictEqual(elements.fWeekWarning.hidden, false);
  assert.strictEqual(elements.fWeekMoveBtn.hidden, true);
  // Campaign activities follow the campaign's own range: never this warning.
  h.set('2026-11-08', { campaign: { name: 'X', start_date: '2026-10-23', end_date: '2026-11-25' } }); elements.fDate.value = '2026-11-20'; h.renderWeekWarning();
  assert.strictEqual(elements.fWeekWarning.hidden, true);

  // "Move to next week": the form switches to next week and keeps the date
  // the candidate picked exactly.
  h.set('2026-11-08'); elements.fDate.value = '2026-11-18'; h.renderAddWeekBanner(); h.renderWeekWarning();
  h.clickMove();
  assert.strictEqual(h.week(), '2026-11-15', 'the form is now for next week');
  assert.strictEqual(elements.fDate.value, '2026-11-18', 'the intended date is preserved');
  assert.strictEqual(elements.addTitle.textContent, 'Next week');
  assert.strictEqual(elements.saveBtn.textContent, 'Save to next week');
  assert.strictEqual(elements.fWeekWarning.hidden, true, 'no contradiction remains');

  // "Choose a date this week": the form stays on this week and the date is
  // cleared — nothing is picked for the candidate.
  h.set('2026-11-08'); elements.fDate.value = '2026-11-18'; h.renderAddWeekBanner(); h.renderWeekWarning();
  h.clickChoose();
  assert.strictEqual(h.week(), '2026-11-08', 'the form stays on this week');
  assert.strictEqual(elements.fDate.value, '', 'no date is chosen for the candidate');
  assert.strictEqual(elements.addTitle.textContent, 'This week');
  assert.strictEqual(elements.fWeekWarning.hidden, true);
  assert.strictEqual(elements.addStatus.textContent, 'Now choose a day in this week.');
  console.log('week banner and week-change warning are explicit');
}

// --- Save confirmation names the actual week and day; offline is honest ---
{
  const fn = new Function('WeekDates', `
    ${extractFunctionSource(html, 'weekName')}
    ${extractFunctionSource(html, 'saveFeedbackText')}
    const CURRENT_WEEK_KEY = '2026-11-08', NEXT_WEEK_KEY = '2026-11-15';
    return saveFeedbackText;`)(WeekDates);
  assert.deepStrictEqual(fn({ weekKey: '2026-11-08', date: '2026-11-12' }), { title: 'Activity saved — This week', detail: 'Thursday, 12 November' });
  assert.deepStrictEqual(fn({ weekKey: '2026-11-15', date: '2026-11-17' }), { title: 'Activity planned — Next week', detail: 'Tuesday, 17 November' });
  assert.deepStrictEqual(fn({ weekKey: '2026-11-08', date: '2026-11-10', edited: true }), { title: 'Changes saved — This week', detail: 'Tuesday, 10 November' });
  const offline = fn({ weekKey: '2026-11-15', date: '2026-11-17', pending: true });
  assert.strictEqual(offline.title, 'Saved on this phone — waiting to sync');
  assert.ok(offline.detail.startsWith('Next week · Tuesday, 17 November') && /not reached the server/.test(offline.detail), 'offline saves never claim to have reached the server');
  console.log('save confirmation names the real week and date');
}

// --- quickDateChoices ---
{
  const fn = new Function('WeekDates', `${constLine('SHORT_DAYS')}\n${extractFunctionSource(html, 'quickDateChoices')}\nreturn quickDateChoices;`)(WeekDates);
  const week = fn('2026-11-09', '2026-11-15', '2026-11-12');
  assert.strictEqual(week.length, 7, 'a one-week range offers every day');
  assert.deepStrictEqual(week.map((d) => d.value)[0], '2026-11-09');
  assert.strictEqual(week.find((d) => d.value === '2026-11-12').label, 'Today');
  assert.strictEqual(week[0].label, 'Mon 9');
  const campaign = fn('2026-11-01', '2026-12-10', '2026-11-12');
  assert.deepStrictEqual(campaign.map((d) => d.value), ['2026-11-12', '2026-11-13', '2026-11-14', '2026-11-15'], 'long ranges: today, tomorrow, coming Sat and Sun');
  const future = fn('2026-12-01', '2026-12-20', '2026-11-12');
  assert.deepStrictEqual(future.map((d) => d.value), ['2026-12-01', '2026-12-02', '2026-12-03', '2026-12-04'], 'a future campaign offers its first days');
  assert.ok(future.every((d) => d.value >= '2026-12-01' && d.value <= '2026-12-20'), 'never offers a date outside the allowed range');
  assert.deepStrictEqual(fn('', '', '2026-11-12'), []);
  console.log('quickDateChoices offers only allowed dates');
}

// --- quickActivityChoices + rememberRecentPicks (per-device, localStorage) ---
{
  const canonical = SmartSheetActivities.CANONICAL_ACTIVITY_OPTIONS;
  const store = {};
  const localStorage = { getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); } };
  const fns = new Function('localStorage', 'CANONICAL_ACTIVITY_OPTIONS', 'personId', `
    ${constLine('QUICK_ACTIVITY_DEFAULTS')}
    ${extractFunctionSource(html, 'recentPicksKey')}
    ${extractFunctionSource(html, 'readRecentPicks')}
    ${extractFunctionSource(html, 'rememberRecentPicks')}
    ${extractFunctionSource(html, 'quickActivityChoices')}
    return {readRecentPicks, rememberRecentPicks, quickActivityChoices};`)(localStorage, canonical, 'test-candidate');

  assert.deepStrictEqual(fns.quickActivityChoices([], canonical), ['Door to Door', 'Info table : canvassing', 'House Meeting', 'Street Meeting', 'Telecanvassing']);
  fns.rememberRecentPicks('Oversight', 'Community hall, Ward 4');
  fns.rememberRecentPicks('Door to Door', 'community HALL, ward 4');
  fns.rememberRecentPicks('Other', '');
  const recent = fns.readRecentPicks();
  assert.deepStrictEqual(recent.activities, ['Door to Door', 'Oversight'], 'most recent first; "Other" is never offered as a quick pick');
  assert.deepStrictEqual(recent.venues, ['community HALL, ward 4'], 'venues dedupe case-insensitively; blanks ignored');
  assert.deepStrictEqual(fns.quickActivityChoices(recent.activities, canonical).slice(0, 2), ['Door to Door', 'Oversight']);
  assert.strictEqual(fns.quickActivityChoices(recent.activities, canonical).length, 5);
  for (let i = 0; i < 10; i++) fns.rememberRecentPicks('Door to Door', `Venue ${i}`);
  assert.strictEqual(fns.readRecentPicks().venues.length, 6, 'recent venues are capped');
  store['wardTrackerRecent:test-candidate'] = '{not json';
  assert.deepStrictEqual(fns.readRecentPicks(), { activities: [], venues: [] }, 'corrupt storage never breaks the form');
  console.log('recent activity/venue picks are remembered safely per device');
}

// --- suggestEndTime: fills a sensible end time, never overrides a valid one ---
{
  const fn = new Function(`${extractFunctionSource(html, 'suggestEndTime')}\nreturn suggestEndTime;`)();
  const options = TimeOptions.TIME_OPTIONS;
  assert.strictEqual(fn('09:00', '', options), '10:00');
  assert.strictEqual(fn('09:30', '', options), '10:30');
  assert.strictEqual(fn('09:00', '08:00', options), '10:00', 'an end time before the start is replaced');
  assert.strictEqual(fn('09:00', '12:00', options), '12:00', 'a valid end time is never overridden');
  assert.strictEqual(fn('22:00', '', options), '', 'no suggestion past the last available time');
  assert.strictEqual(fn('', '11:00', options), '11:00');
  console.log('suggestEndTime fills, never overrides');
}

// --- renderQuickChips escapes candidate-typed venues ---
{
  const el = { innerHTML: '', hidden: true };
  const fn = new Function('$', `${escapeHtmlSrc}\n${extractFunctionSource(html, 'renderQuickChips')}\nreturn renderQuickChips;`)(() => el);
  const XSS = '"><img src=x onerror=alert(1)>';
  fn('fVenueChips', [{ value: XSS, label: XSS }], XSS);
  assert.ok(!el.innerHTML.includes('<img'), 'venue text must be escaped in chips');
  assert.ok(el.innerHTML.includes('aria-pressed="true"'), 'the current value is marked selected');
  assert.strictEqual(el.hidden, false);
  fn('fVenueChips', [], '');
  assert.strictEqual(el.hidden, true, 'an empty chip row is hidden');
  console.log('renderQuickChips escapes data and hides when empty');
}

console.log('candidate-quick-capture.test.js OK');
