const assert = require('assert');
const fs = require('fs');
const path = require('path');
const WeekDates = require('./week-dates');

// Leadership Meeting Pack (PHO Stage 4): the Prepare Meeting entry point,
// period selection, preview/download requests and the preview cards —
// executed as the real source extracted from index.html.

const html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');

function extractFunctionSource(src, name) {
  const marker = `function ${name}(`;
  let start = src.indexOf(marker);
  if (start === -1) throw new Error(`could not find function ${name}() in index.html`);
  if (src.slice(start - 6, start) === 'async ') start -= 6;
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
const src = (...names) => names.map((n) => extractFunctionSource(html, n)).join('\n');

// --- one clearly visible entry point, and the view's controls ---
{
  const nav = html.slice(html.indexOf('<nav class="leader-nav" aria-label="Leadership sections">'));
  const navHtml = nav.slice(0, nav.indexOf('</nav>'));
  assert.ok(/id="leaderNavMeeting"[^>]*>Prepare Meeting</.test(navHtml), 'the leadership app bar must have a Prepare Meeting button');
  assert.strictEqual((html.match(/>Prepare Meeting</g) || []).length, 2, 'exactly one button plus the view heading say Prepare Meeting');
  ['meetingWeek', 'meetingLength', 'meetingDates', 'meetingPdfBtn', 'meetingPptxBtn', 'meetingPreview', 'leaderMeetingBack'].forEach((id) => {
    assert.ok(html.includes(`id="${id}"`), `${id} must exist`);
  });
  assert.ok(/>Download PDF</.test(html) && />Download PowerPoint</.test(html), 'both download options must be offered');
  console.log('Prepare Meeting button and view controls exist');
}

// --- period: defaults to the latest completed week; exact dates shown ---
const CURRENT = '2026-09-06'; // the week Monday 7 - Sunday 13 September 2026
function periodFns(weekValue, lengthValue) {
  const els = { meetingWeek: { value: weekValue }, meetingLength: { value: lengthValue } };
  return new Function('WeekDates', 'CURRENT_WEEK_KEY', '$',
    `${src('weekStartYmd', 'weekEndYmd', 'meetingDefaultWeekKey', 'meetingPeriod', 'meetingDatesLabel', 'meetingParams', 'meetingFilename')}
     return {meetingPeriod, meetingDatesLabel, meetingParams, meetingFilename};`)(WeekDates, CURRENT, (id) => els[id]);
}
{
  const fns = periodFns('', '1');
  const period = fns.meetingPeriod();
  assert.deepStrictEqual([period.from, period.to], ['2026-08-31', '2026-09-06'], 'no selection = the latest completed Monday-Sunday week');
  assert.strictEqual(fns.meetingDatesLabel(period), 'Monday, 31 August – Sunday, 6 September 2026');
  assert.strictEqual(fns.meetingParams().toString(), 'date_from=2026-08-31&date_to=2026-09-06');
  assert.strictEqual(fns.meetingFilename('pptx'), 'Ntsikana_Meeting_Pack_2026-08-31_to_2026-09-06.pptx');

  const four = periodFns('2026-09-06', '4').meetingPeriod();
  assert.deepStrictEqual([four.from, four.to], ['2026-08-17', '2026-09-13'], '4 weeks ending the chosen week');
  const twelve = periodFns('2026-08-30', '12').meetingPeriod();
  assert.deepStrictEqual([twelve.from, twelve.to], ['2026-06-15', '2026-09-06']);
  const yearEnd = periodFns('2025-12-28', '1');
  assert.strictEqual(yearEnd.meetingDatesLabel(yearEnd.meetingPeriod()), 'Monday, 29 December 2025 – Sunday, 4 January 2026');
  console.log('meetingPeriod defaults to the last completed week and names exact dates');
}

// --- a period including this week or next week says so ---
{
  const els = { meetingWeek: { value: CURRENT }, meetingLength: { value: '1' }, meetingDates: { textContent: '' },
    meetingNote: { textContent: '', hidden: true } };
  const fn = new Function('WeekDates', 'CURRENT_WEEK_KEY', '$',
    `${src('weekStartYmd', 'weekEndYmd', 'meetingDefaultWeekKey', 'meetingPeriod', 'meetingDatesLabel', 'updateMeetingDates')} return updateMeetingDates;`
  )(WeekDates, CURRENT, (id) => els[id]);
  fn();
  assert.strictEqual(els.meetingNote.hidden, false);
  assert.ok(/shown as planned, never as completed/.test(els.meetingNote.textContent));
  els.meetingWeek.value = '2026-09-13';
  fn();
  assert.ok(/planned and have not taken place yet/.test(els.meetingNote.textContent), 'next week is all planned');
  els.meetingWeek.value = '2026-08-30';
  fn();
  assert.strictEqual(els.meetingNote.hidden, true, 'a completed week needs no note');
  console.log('updateMeetingDates flags periods that include unfinished weeks');
}

// --- preview and both downloads ask for exactly the same period ---
(async () => {
  const els = {
    meetingWeek: { value: '2026-08-30' }, meetingLength: { value: '4' }, meetingDates: { textContent: '' },
    meetingNote: { textContent: '', hidden: true }, meetingStatus: { className: '', textContent: '' },
    meetingPreview: { innerHTML: '', classList: { add() {}, remove() {} } }, meetingPreviewCount: { textContent: '' },
    meetingPdfBtn: { disabled: false, textContent: 'Download PDF' }, meetingPptxBtn: { disabled: false, textContent: 'Download PowerPoint' },
    meetingCombinedPdfBtn: { disabled: true, textContent: 'Download combined PDF' }, meetingFileList: { innerHTML: '' },
  };
  const calls = [];
  const downloads = [];
  let combinedPayload = null;
  const fns = new Function('WeekDates', 'CURRENT_WEEK_KEY', '$', 'api', 'fetch', 'API_BASE', 'leaderHeaders', 'friendlyErrorMessage',
    'triggerBlobDownload', 'renderMeetingPreview', 'escapeHtml', 'FormData',
    `let meetingPack = null; let meetingRequestSeq = 0; let meetingAttachments = [];
     let meetingAddingFiles = false; let meetingDeckOrder = Array.from({length:8},(_,i)=>'g:'+(i+1));
     ${src('weekStartYmd', 'weekEndYmd', 'meetingDefaultWeekKey', 'meetingPeriod', 'meetingDatesLabel', 'meetingParams', 'meetingFilename',
       'setMeetingStatus', 'meetingCanDownload', 'meetingSequence', 'renderMeetingAttachments', 'downloadCombinedMeetingPack',
       'updateMeetingDates', 'loadMeetingPreview', 'downloadMeetingPack')}
     return {loadMeetingPreview, downloadMeetingPack, downloadCombinedMeetingPack, renderMeetingAttachments};`)(
    WeekDates, CURRENT, (id) => els[id],
    async (p) => { calls.push(p); return { period: {} }; },
    async (url, opts) => { calls.push(url); if(opts && opts.method==='POST') combinedPayload = opts.body.entries;
      return { ok: true, headers: { get: key => key === 'X-Meeting-Pages' ? '8' : null }, blob: async () => 'BLOB' }; },
    'https://api.example', () => ({ Authorization: 'Bearer x' }), (e, f) => f,
    (blob, name) => downloads.push(name), () => {},
    new Function(`${extractFunctionSource(html, 'escapeHtml')} return escapeHtml;`)(),
    class FakeFormData { constructor(){ this.entries=[]; } append(...args){ this.entries.push(args); } });
  await fns.loadMeetingPreview();
  await fns.downloadMeetingPack(els.meetingPdfBtn, 'pdf', 'Download PDF');
  await fns.downloadMeetingPack(els.meetingPptxBtn, 'pptx', 'Download PowerPoint');
  const q = 'date_from=2026-08-10&date_to=2026-09-06';
  assert.deepStrictEqual(calls, [
    `/api/leader/meeting-pack?${q}`,
    `https://api.example/api/leader/meeting-pack.pdf?${q}`,
    `https://api.example/api/leader/meeting-pack.pptx?${q}`,
  ], 'preview, PDF and PowerPoint must request the identical period');
  assert.deepStrictEqual(downloads, ['Ntsikana_Meeting_Pack_2026-08-10_to_2026-09-06.pdf', 'Ntsikana_Meeting_Pack_2026-08-10_to_2026-09-06.pptx']);
  assert.strictEqual(els.meetingPptxBtn.textContent, 'Download PowerPoint', 'button label restored after download');
  assert.ok(html.includes('id="meetingDrop"') && html.includes('id="meetingFiles"') && html.includes('id="meetingCombinedPdfBtn"'), 'optional PDF drop zone and combined export exist');
  assert.strictEqual(els.meetingCombinedPdfBtn.disabled, false, 'customised PDF supports reordering original slides without attachments');
  await fns.downloadCombinedMeetingPack();
  assert.strictEqual(calls.at(-1), 'https://api.example/api/leader/meeting-pack/combined.pdf');
  assert.deepStrictEqual(combinedPayload.slice(0,2), [['date_from','2026-08-10'], ['date_to','2026-09-06']]);
  assert.strictEqual(combinedPayload[2][0], 'sequence_json');
  assert.strictEqual(JSON.parse(combinedPayload[2][1]).length, 8, 'all original slides listed in the custom deck');
  assert.ok(downloads.at(-1).endsWith('_customised.pdf'));
  assert.strictEqual(els.meetingCombinedPdfBtn.disabled, false, 'button restored after merge');


  console.log('preview and downloads request the same period');

  // --- preview cards show the pack's own figures, escaped ---
  const pack = {
    title: 'Leadership Meeting Pack', constituency: 'Ntsikana Constituency', scope: 'All municipalities',
    generated_label: 'Thursday, 10 September 2026',
    period: { label: 'Monday 7 September – Sunday 13 September 2026', short_label: '7–13 Sep 2026', state: 'in_progress',
      state_label: 'Period in progress — includes planned activities' },
    kpis: { total: 48, completed: 24, planned: 24, canvassing: 30 },
    tiles: [{ label: 'Activities', value: '48', note: '24 completed · 24 planned' }],
    summary: ['So far 24 activities have taken place and 24 more are planned.'],
    comparison: { available: true, period_label: '31 Aug 2026 - 6 Sep 2026', activities: { previous: 44, label: 'Up 9%' }, canvassing: { label: 'Up 7%' } },
    trend: [{ label: '31 Aug', range: '31 Aug - 6 Sep', total: 44, completed: 44, planned: 0, captured: 13, waiting: 31, in_period: false },
      { label: '7 Sep', range: '7 Sep - 13 Sep', total: 48, completed: 24, planned: 24, captured: 1, waiting: 23, in_period: true }],
    municipalities: [{ municipality: 'Amahlathi', activities: 26, canvassing: 16, captured: 1, wards_active: 8, wards_total: 14,
      candidates_reporting: 8, candidates_expected: 13, coverage: {completed: 4, planned: 4, no_entries: 6}, status_counts: { Strong: 6, Active: 2, 'Needs Attention': 3, 'No Activity': 3 } }],
    participation: { submitted: 18, expected: 28, not_logged: 10 },
    activity_mix: [{ activity: '<script>alert(1)</script>', activities: 7, percent: 15 }],
    attention: [{ title: '10 candidates have not logged any activity', items: ['A (Amahlathi)', 'B (Raymond Mhlaba)'] }],
    upcoming: { as_of: 'Thursday, 10 September 2026', window_label: 'Friday, 11 September 2026 – Thursday, 24 September 2026', activities: [], campaigns: [] },
  };
  const view = { meetingPreview: { innerHTML: '' }, meetingPreviewCount: { textContent: '' }, meetingDates: { textContent: '' },
    meetingFileList: { innerHTML: '' }, meetingCombinedPdfBtn: { disabled: true } };
  const render = new Function('$', 'escapeHtml', 'plural',
    `let meetingPack = null; let meetingAttachments = []; let meetingGeneratedSlideHtml = [];
     let meetingDeckOrder = []; let meetingAddingFiles = false;
     const MEETING_SLIDE_TITLES = ['Title', 'Executive summary', 'Activity trend', 'Municipalities and wards', 'Candidate participation', 'Completed and planned', 'Records to review', 'Current planning update'];
     ${src('meetingDefaultDeck', 'meetingCanDownload', 'renderMeetingAttachments', 'meetingRenderDeck',
       'mpFoot', 'mpSlide', 'mpTable', 'mpBars', 'mpEmpty', 'renderMeetingPreview')}
     return function(pack) {meetingPack = pack; renderMeetingPreview(pack);};`
  )((id) => view[id], new Function(`${extractFunctionSource(html, 'escapeHtml')} return escapeHtml;`)(),
    (n, one, many) => `${n} ${n === 1 ? one : many}`);
  render(pack);
  const out = view.meetingPreview.innerHTML;
  assert.strictEqual((out.match(/<article class="mp-slide/g) || []).length, 8, 'the preview shows all eight slides');
  assert.ok(!out.includes('<script>alert(1)</script>') && out.includes('&lt;script&gt;'), 'activity labels are escaped');
  assert.ok(!out.includes('Official Capture') && !out.includes('Most active candidates'), 'retired capture and candidate ranking are absent');
  ['Period in progress — includes planned activities', '24 completed · 24 planned', '18 of 28', 'Completed (date reached)',
    'Planned (future date)', 'No activities are planned for the next 14 days yet.', 'Activity types recorded (no candidate ranking)'].forEach((t) => {
    assert.ok(out.includes(t), `preview must show: ${t}`);
  });
  assert.strictEqual(view.meetingDates.textContent, pack.period.label, 'the confirmed dates come from the generated pack');
  assert.ok(view.meetingPreviewCount.textContent.startsWith('8 pages'));
  console.log('renderMeetingPreview shows the pack figures for all eight slides');

  // --- every other view hides the Meeting view ---
  ['leaderDetailBack', 'openLeaderReports'].forEach((name) => {
    assert.ok(/\$\('leaderMeetingView'\)\.hidden = true;/.test(extractFunctionSource(html, name)), `${name} must hide the Meeting view`);
  });
  assert.ok(/\$\('leaderMeetingView'\)\.hidden = false;/.test(extractFunctionSource(html, 'openLeaderMeeting')));
  console.log('meeting-pack UI tests passed');
})().catch((e) => { console.error(e); process.exit(1); });
