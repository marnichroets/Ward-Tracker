// Screenshot the LOCAL synthetic environment (devtools/local_server.py) at
// desktop and phone widths, using headless Chrome over the DevTools
// protocol — no npm dependencies (Node >= 22 ships a global WebSocket).
//
//   node devtools/screenshot.mjs [scenario-name ...]
//
// Refuses any origin other than 127.0.0.1, so it can never be pointed at
// production. Output: devtools/screenshots/<scenario>.png (git-ignored).
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync, existsSync, mkdtempSync, readdirSync, unlinkSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const ORIGIN = process.env.WARD_TRACKER_LOCAL_ORIGIN || 'http://127.0.0.1:8765';
if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(ORIGIN)) throw new Error('screenshots only run against the local 127.0.0.1 server');
const OUT = join(HERE, 'screenshots');
const CHROME = [
  process.env.CHROME_PATH,
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  '/usr/bin/google-chrome', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
].find((p) => p && existsSync(p));

const DESKTOP = { width: 1440, height: 900, mobile: false, scale: 1 };
const LAPTOP = { width: 1024, height: 768, mobile: false, scale: 1 };
const PHONE = { width: 390, height: 844, mobile: true, scale: 2 };
const SMALL_PHONE = { width: 360, height: 740, mobile: true, scale: 2 };

const leaderLogin = `
  const r = await fetch('/api/leader/login', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({pin:'2222'})});
  localStorage.setItem('leaderToken', (await r.json()).token);`;
const adminLogin = `
  const r = await fetch('/api/admin/login', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({pin:'1111'})});
  localStorage.setItem('adminToken', (await r.json()).token);`;

// Signs in as the first synthetic roster candidate through the real UI.
const candidateSignIn = `
  const input = document.getElementById('whoName');
  input.value = 'Ayanda Zondi'; input.dispatchEvent(new Event('input', {bubbles:true}));
  await new Promise(r=>setTimeout(r,400));
  const pick = document.querySelector('.name-suggestion'); if(pick) pick.dispatchEvent(new PointerEvent('pointerdown', {bubbles:true}));
  await new Promise(r=>setTimeout(r,200));
  document.getElementById('whoContinue').click();
  await new Promise(r=>setTimeout(r,1500));`;

// Each scenario: viewport, optional login, hash route, then optional
// in-page actions; waitFor is a selector that must exist before capture.
export const SCENARIOS = {
  'leader-desktop': { vp: DESKTOP, login: leaderLogin, hash: '#leader', waitFor: '#leaderKpis .leader-kpi' },
  'leader-laptop': { vp: LAPTOP, login: leaderLogin, hash: '#leader', waitFor: '#leaderKpis .leader-kpi' },
  'leader-phone': { vp: PHONE, login: leaderLogin, hash: '#leader', waitFor: '#leaderKpis .leader-kpi' },
  'leader-small-phone': { vp: SMALL_PHONE, login: leaderLogin, hash: '#leader', waitFor: '#leaderKpis .leader-kpi' },
  'leader-12-weeks-desktop': {
    vp: DESKTOP, login: leaderLogin, hash: '#leader', waitFor: '#leaderKpis .leader-kpi',
    actions: `document.querySelector('[data-leader-weeks="12"]').click();`, settle: 1500,
  },
  'leader-drill-ward-desktop': {
    vp: DESKTOP, login: leaderLogin, hash: '#leader', waitFor: '[data-drill-kind="ward"]',
    actions: `document.querySelector('[data-drill-kind="ward"]').click();`, settle: 600,
  },
  'leader-reports-desktop': {
    vp: DESKTOP, login: leaderLogin, hash: '#leader', waitFor: '#leaderKpis .leader-kpi',
    actions: `document.getElementById('leaderNavReports').click();`, settle: 500,
  },
  'leader-reports-phone': {
    vp: PHONE, login: leaderLogin, hash: '#leader', waitFor: '#leaderKpis .leader-kpi',
    actions: `document.getElementById('leaderNavReports').click();`, settle: 500,
  },
  'leader-meeting-desktop': {
    vp: DESKTOP, login: leaderLogin, hash: '#leader', waitFor: '#leaderKpis .leader-kpi',
    actions: `document.getElementById('leaderNavMeeting').click();
      for(let i=0;i<50 && !document.querySelector('#meetingPreview .mp-slide');i++) await new Promise(r=>setTimeout(r,200));
      return JSON.stringify({dates: document.getElementById('meetingDates').textContent,
        week: document.getElementById('meetingWeek').selectedOptions[0].textContent,
        slides: document.querySelectorAll('#meetingPreview .mp-slide').length});`, settle: 600,
  },
  'leader-meeting-phone': {
    vp: PHONE, login: leaderLogin, hash: '#leader', waitFor: '#leaderKpis .leader-kpi',
    actions: `document.getElementById('leaderNavMeeting').click();
      for(let i=0;i<50 && !document.querySelector('#meetingPreview .mp-slide');i++) await new Promise(r=>setTimeout(r,200));`, settle: 600,
  },
  'leader-meeting-in-progress-desktop': {
    vp: DESKTOP, login: leaderLogin, hash: '#leader', waitFor: '#leaderKpis .leader-kpi', fullPage: false,
    actions: `document.getElementById('leaderNavMeeting').click();
      for(let i=0;i<50 && !document.querySelector('#meetingPreview .mp-slide');i++) await new Promise(r=>setTimeout(r,200));
      const sel = document.getElementById('meetingWeek'); sel.value = CURRENT_WEEK_KEY; sel.dispatchEvent(new Event('change'));
      await new Promise(r=>setTimeout(r,1500));
      return JSON.stringify({dates: document.getElementById('meetingDates').textContent, note: document.getElementById('meetingNote').textContent});`, settle: 600,
  },
  'leader-drill-ward-phone': {
    vp: PHONE, login: leaderLogin, hash: '#leader', waitFor: '[data-drill-kind="ward"]',
    actions: `document.querySelector('[data-drill-kind="ward"]').click();`, settle: 600,
  },
  'leader-tooltip-desktop': {
    vp: DESKTOP, login: leaderLogin, hash: '#leader', waitFor: '#leaderTrendWeeks [data-tip]', fullPage: false,
    actions: `const el = [...document.querySelectorAll('#leaderTrendWeeks [data-tip]')].at(-2);
      el.scrollIntoView({block:'center'}); await new Promise(r=>setTimeout(r,400)); const b = el.getBoundingClientRect();
      el.dispatchEvent(new PointerEvent('pointerover', {bubbles:true, clientX:b.x+b.width/2, clientY:b.y+4}));`, settle: 400,
  },
  // Candidate (Stage 2C): home with one panel per week; every "Add" opens the
  // form already in that week; saves land on that week's list with a
  // confirmation naming the week and day.
  'candidate-home-phone': { vp: PHONE, hash: '', waitFor: '#whoName', actions: candidateSignIn, settle: 1200 },
  'candidate-home-small-phone': { vp: SMALL_PHONE, hash: '', waitFor: '#whoName', fullPage: false, actions: candidateSignIn, settle: 1200 },
  'candidate-home-desktop': { vp: DESKTOP, hash: '', waitFor: '#whoName', actions: candidateSignIn, settle: 1200 },
  'candidate-list-phone': { vp: PHONE, hash: '', waitFor: '#whoName',
    actions: candidateSignIn + `document.getElementById('reviewThisWeekBtn').click(); await new Promise(r=>setTimeout(r,500));`, settle: 500 },
  'candidate-add-phone': { vp: PHONE, hash: '', waitFor: '#whoName', fullPage: false,
    actions: candidateSignIn + `document.getElementById('addThisWeekBtn').click(); await new Promise(r=>setTimeout(r,600));
      return JSON.stringify({banner: document.getElementById('addWeekBanner').innerText.replace(/\\s+/g,' '), date: fDate.value,
        chips: [...document.querySelectorAll('#fDateChips [data-quick-value]')].map(b=>b.dataset.quickValue), save: saveBtn.textContent});`, settle: 600 },
  'candidate-add-full-phone': { vp: PHONE, hash: '', waitFor: '#whoName',
    actions: candidateSignIn + `document.getElementById('addThisWeekBtn').click(); await new Promise(r=>setTimeout(r,600));`, settle: 600 },
  'candidate-add-next-phone': { vp: PHONE, hash: '', waitFor: '#whoName', fullPage: false,
    actions: candidateSignIn + `document.getElementById('addNextWeekBtn').click(); await new Promise(r=>setTimeout(r,600));
      return JSON.stringify({banner: document.getElementById('addWeekBanner').innerText.replace(/\\s+/g,' '), date: fDate.value,
        chips: [...document.querySelectorAll('#fDateChips [data-quick-value]')].map(b=>b.dataset.quickValue), save: saveBtn.textContent});`, settle: 600 },
  'candidate-add-desktop': { vp: DESKTOP, hash: '', waitFor: '#whoName',
    actions: candidateSignIn + `document.getElementById('addNextWeekBtn').click(); await new Promise(r=>setTimeout(r,600));`, settle: 600 },
  'candidate-add-filled-phone': { vp: PHONE, hash: '', waitFor: '#whoName', fullPage: false,
    actions: candidateSignIn + `document.getElementById('addThisWeekBtn').click(); await new Promise(r=>setTimeout(r,600));
      document.querySelector('#fActivityChips [data-quick-value]').click();
      document.querySelectorAll('#fDateChips [data-quick-value]')[5].click();
      const st = document.getElementById('fStartTime'); st.value = '09:00'; st.dispatchEvent(new Event('change', {bubbles:true}));
      const venueChip = document.querySelector('#fVenueChips [data-quick-value]'); if(venueChip) venueChip.click();
      document.getElementById('fVenue').scrollIntoView({block:'center'});`, settle: 600 },
  // A next-week date picked while adding to THIS week: flagged, and Save is
  // refused until the candidate moves it or keeps this week.
  'candidate-week-change-phone': { vp: PHONE, hash: '', waitFor: '#whoName', fullPage: false,
    actions: candidateSignIn + `document.getElementById('addThisWeekBtn').click(); await new Promise(r=>setTimeout(r,600));
      [...document.querySelectorAll('#fActivityChips [data-quick-value]')].find(b=>b.dataset.quickValue==='Street Meeting').click();
      const st = document.getElementById('fStartTime'); st.value = '10:00'; st.dispatchEvent(new Event('change', {bubbles:true}));
      fVenue.value = 'Taxi rank, Main Road';
      fDate.value = WeekDates.activityDate(NEXT_WEEK_KEY, 'wed'); fDate.dispatchEvent(new Event('change', {bubbles:true}));
      saveBtn.click(); await new Promise(r=>setTimeout(r,500));
      const blocked = {screen: document.querySelector('.screen.active').id, status: addStatus.textContent, warning: fWeekWarningText.textContent};
      document.getElementById('fWeekWarning').scrollIntoView({block:'center'});
      return JSON.stringify(blocked);`, settle: 500 },
  // End-to-end journey: home → "Plan for next week" → quick picks → Save →
  // lands on NEXT week's list with the confirmation, row present on that date.
  'candidate-save-phone': { vp: PHONE, hash: '', waitFor: '#whoName', fullPage: false,
    actions: candidateSignIn + `
      const beforeNext = document.getElementById('nextWeekCount').textContent;
      document.getElementById('addNextWeekBtn').click(); await new Promise(r=>setTimeout(r,600));
      [...document.querySelectorAll('#fActivityChips [data-quick-value]')].find(b=>b.dataset.quickValue==='Telecanvassing').click();
      document.querySelectorAll('#fDateChips [data-quick-value]')[1].click();
      const picked = fDate.value;
      const st = document.getElementById('fStartTime'); st.value = '15:30'; st.dispatchEvent(new Event('change', {bubbles:true}));
      fVenue.value = 'Community hall, Ward 1'; fVenue.dispatchEvent(new Event('input', {bubbles:true}));
      document.getElementById('saveBtn').click();
      await new Promise(r=>setTimeout(r,2000));
      const saved = document.querySelector('#actList .actrow.justsaved');
      const out = {screen: document.querySelector('.screen.active').id, list: listWeekName.textContent, picked,
        banner: saveFeedback.innerText.replace(/\\s+/g,' '), savedRow: saved ? saved.innerText.replace(/\\s+/g,' ') : null,
        beforeNext, afterNext: document.getElementById('nextWeekCount').textContent,
        homeNextStatus: document.getElementById('nextWeekStatus').textContent};
      return JSON.stringify(out);`, settle: 400 },
  // Offline: the save is queued on the phone, the confirmation says it is
  // waiting to sync; going back online sends it and says so.
  'candidate-offline-phone': { vp: PHONE, hash: '', waitFor: '#whoName', fullPage: false,
    actions: candidateSignIn + `
      document.getElementById('addThisWeekBtn').click(); await new Promise(r=>setTimeout(r,600));
      [...document.querySelectorAll('#fActivityChips [data-quick-value]')].find(b=>b.dataset.quickValue==='House Meeting').click();
      document.querySelectorAll('#fDateChips [data-quick-value]')[2].click();
      const st = document.getElementById('fStartTime'); st.value = '18:00'; st.dispatchEvent(new Event('change', {bubbles:true}));
      fVenue.value = 'Church hall, Ward 1';
      Object.defineProperty(navigator, 'onLine', {configurable: true, get: () => false});
      document.getElementById('saveBtn').click();
      await new Promise(r=>setTimeout(r,1500));
      const out = {screen: document.querySelector('.screen.active').id, banner: saveFeedback.innerText.replace(/\\s+/g,' '),
        queued: JSON.parse(localStorage.getItem('pendingEntries') || '[]').length, pendingTags: document.querySelectorAll('.pendingtag').length};
      return JSON.stringify(out);`, settle: 400 },
  'candidate-offline-synced-phone': { vp: PHONE, hash: '', waitFor: '#whoName', fullPage: false,
    actions: candidateSignIn + `
      document.getElementById('addThisWeekBtn').click(); await new Promise(r=>setTimeout(r,600));
      [...document.querySelectorAll('#fActivityChips [data-quick-value]')].find(b=>b.dataset.quickValue==='Street Meeting').click();
      document.querySelectorAll('#fDateChips [data-quick-value]')[0].click();
      const st = document.getElementById('fStartTime'); st.value = '19:00'; st.dispatchEvent(new Event('change', {bubbles:true}));
      fVenue.value = 'Clinic gate, Ward 1';
      Object.defineProperty(navigator, 'onLine', {configurable: true, get: () => false});
      document.getElementById('saveBtn').click(); await new Promise(r=>setTimeout(r,1200));
      const queuedBefore = JSON.parse(localStorage.getItem('pendingEntries') || '[]').length;
      Object.defineProperty(navigator, 'onLine', {configurable: true, get: () => true});
      window.dispatchEvent(new Event('online')); await new Promise(r=>setTimeout(r,2000));
      let syncError = null; const left = JSON.parse(localStorage.getItem('pendingEntries') || '[]');
      if(left.length){ try{ await api('/api/entries', {method:'POST', body: JSON.stringify(left[0].entry)}); }catch(e){ syncError = {status: e.status, detail: e.detail}; } }
      return JSON.stringify({syncError, queuedBefore, queuedAfter: JSON.parse(localStorage.getItem('pendingEntries') || '[]').length,
        status: listStatus.textContent, pendingTags: document.querySelectorAll('.pendingtag').length});`, settle: 400 },
  // An existing record opens in the week it belongs to and saves as an edit.
  'candidate-edit-phone': { vp: PHONE, hash: '', waitFor: '#whoName', fullPage: false,
    actions: candidateSignIn + `
      document.getElementById('reviewThisWeekBtn').click(); await new Promise(r=>setTimeout(r,500));
      const row = document.querySelector('#actList .actrow'); const id = row.dataset.key; row.click(); await new Promise(r=>setTimeout(r,500));
      const form = {banner: document.getElementById('addWeekBanner').innerText.replace(/\\s+/g,' '), save: saveBtn.textContent, date: fDate.value};
      fEndTime.value = fEndTime.options[fEndTime.selectedIndex + 1] ? fEndTime.options[fEndTime.selectedIndex + 1].value : fEndTime.value;
      saveBtn.click(); await new Promise(r=>setTimeout(r,1500));
      return JSON.stringify(Object.assign(form, {screen: document.querySelector('.screen.active').id, banner2: saveFeedback.innerText.replace(/\\s+/g,' '),
        highlighted: (document.querySelector('.actrow.justsaved')||{}).dataset ? document.querySelector('.actrow.justsaved').dataset.key === id : false}));`, settle: 400 },
  // Campaigns stay reachable from home; a campaign activity form is headed
  // by the campaign (its own date range), not a week.
  'candidate-campaign-phone': { vp: PHONE, hash: '', waitFor: '#whoName', fullPage: false,
    actions: candidateSignIn + `document.querySelector('#campaignList [data-open-campaign]').click(); await new Promise(r=>setTimeout(r,1000));
      const detail = document.querySelector('.screen.active').id;
      document.getElementById('cdAddActivityBtn').click(); await new Promise(r=>setTimeout(r,600));
      return JSON.stringify({detail, banner: document.getElementById('addWeekBanner').innerText.replace(/\\s+/g,' '), save: saveBtn.textContent,
        warningHidden: fWeekWarning.hidden, hint: fDateWeekHint.textContent});`, settle: 500 },
  // Validation: the error sits right above Save and the field is brought into view.
  'candidate-validation-phone': { vp: PHONE, hash: '', waitFor: '#whoName', fullPage: false,
    actions: candidateSignIn + `document.getElementById('addThisWeekBtn').click(); await new Promise(r=>setTimeout(r,600));
      [...document.querySelectorAll('#fActivityChips [data-quick-value]')].find(b=>b.dataset.quickValue==='Door to Door').click();
      const st = document.getElementById('fStartTime'); st.value = '09:00'; st.dispatchEvent(new Event('change', {bubbles:true}));
      saveBtn.click(); await new Promise(r=>setTimeout(r,800));
      const s = addStatus.getBoundingClientRect(), b = saveBtn.getBoundingClientRect();
      return JSON.stringify({status: addStatus.textContent, invalid: fVenue.getAttribute('aria-invalid'), statusAboveSave: s.bottom <= b.top});`, settle: 500 },
  'landing-phone': { vp: PHONE, hash: '', waitFor: '#whoName' },
  'landing-desktop': { vp: DESKTOP, hash: '', waitFor: '#whoName' },
  // Regression check for the #admin deep link with a saved session: must land
  // on the coordinator workspace, not fall back to the PIN prompt.
  'coordinator-deeplink': {
    vp: DESKTOP, login: adminLogin, hash: '#admin', waitFor: '#screenAdmin.active, #screenPin.active', fullPage: false,
    actions: `return document.querySelector('.screen.active').id;`,
  },
  'coordinator-desktop': { vp: DESKTOP, login: adminLogin, hash: '#admin', waitFor: '#screenAdmin.active .capture-row' },
  'coordinator-phone': { vp: PHONE, login: adminLogin, hash: '#admin', waitFor: '#screenAdmin.active .capture-row', segment: 1700 },
  'coordinator-reports-desktop': { vp: DESKTOP, login: adminLogin, hash: '#admin', waitFor: '#screenAdmin.active .capture-row',
    actions: `document.querySelector('[data-coord-tab="reports"]').click();`, settle: 500 },
  'coordinator-reports-phone': { vp: PHONE, login: adminLogin, hash: '#admin', waitFor: '#screenAdmin.active .capture-row',
    actions: `document.querySelector('[data-coord-tab="reports"]').click();`, settle: 500 },
  'coordinator-campaigns-desktop': { vp: DESKTOP, login: adminLogin, hash: '#admin', waitFor: '#screenAdmin.active .capture-row',
    actions: `document.querySelector('[data-coord-tab="campaigns"]').click(); document.getElementById('campaignCaptureToggle').click();`, settle: 1200 },
  // What "Download PDF" (window.print) produces: the weekly submission report only.
  'coordinator-print': { vp: DESKTOP, login: adminLogin, hash: '#admin', waitFor: '#screenAdmin.active #reportCard .reporthead', media: 'print' },
  'coordinator-data-desktop': { vp: DESKTOP, login: adminLogin, hash: '#admin', waitFor: '#screenAdmin.active .capture-row',
    actions: `document.querySelector('[data-coord-tab="data"]').click();`, settle: 500 },
};

function wait(ms) { return new Promise((r) => setTimeout(r, ms)); }

async function cdpSession(wsUrl) {
  const ws = new WebSocket(wsUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  let id = 0;
  const pending = new Map();
  const listeners = [];
  ws.onmessage = (msg) => {
    const data = JSON.parse(msg.data);
    if (data.id && pending.has(data.id)) {
      const { resolve, reject } = pending.get(data.id);
      pending.delete(data.id);
      data.error ? reject(new Error(data.error.message)) : resolve(data.result);
    } else if (data.method) listeners.forEach((fn) => fn(data));
  };
  return {
    send(method, params = {}) {
      const msgId = ++id;
      ws.send(JSON.stringify({ id: msgId, method, params }));
      return new Promise((resolve, reject) => pending.set(msgId, { resolve, reject }));
    },
    on(fn) { listeners.push(fn); },
    close() { ws.close(); },
  };
}

async function evaluate(cdp, expression) {
  const res = await cdp.send('Runtime.evaluate', { expression: `(async()=>{${expression}})()`, awaitPromise: true, returnByValue: true });
  if (res.exceptionDetails) throw new Error(res.exceptionDetails.exception?.description || res.exceptionDetails.text);
  return res.result.value;
}

async function capture(cdp, name, sc, consoleErrors) {
  const { vp } = sc;
  await cdp.send('Emulation.setDeviceMetricsOverride', { width: vp.width, height: vp.height, deviceScaleFactor: vp.scale, mobile: vp.mobile });
  await cdp.send('Emulation.setTouchEmulationEnabled', { enabled: vp.mobile });
  await cdp.send('Page.navigate', { url: ORIGIN + '/' });
  await wait(900);
  await evaluate(cdp, `localStorage.clear(); ${sc.login || ''}`);
  await cdp.send('Page.navigate', { url: ORIGIN + '/' + (sc.hash || '') });
  await wait(600);
  await cdp.send('Page.reload', { ignoreCache: true });
  const deadline = Date.now() + 15000;
  while (!(await evaluate(cdp, `return !!document.querySelector(${JSON.stringify(sc.waitFor)})`))) {
    if (Date.now() > deadline) throw new Error(`${name}: timed out waiting for ${sc.waitFor}`);
    await wait(200);
  }
  await wait(500);
  let actionResult;
  if (sc.actions) { actionResult = await evaluate(cdp, sc.actions); await wait(sc.settle || 500); }
  await cdp.send('Emulation.setEmulatedMedia', { media: sc.media || '' });
  const overflow = await evaluate(cdp, 'return document.documentElement.scrollWidth - window.innerWidth');
  const activeScreen = await evaluate(cdp, "return document.querySelector('.screen.active')?.id || null");
  const files = [];
  // Only this scenario's own previous output, inside devtools/screenshots/.
  for (const f of readdirSync(OUT)) {
    if (f === `${name}.png` || (f.startsWith(`${name}-`) && /^\d+\.png$/.test(f.slice(name.length + 1)))) unlinkSync(join(OUT, f));
  }
  if (sc.fullPage === false) {
    const shot = await cdp.send('Page.captureScreenshot', { format: 'png' });
    writeFileSync(join(OUT, `${name}.png`), Buffer.from(shot.data, 'base64'));
    files.push(`${name}.png`);
  } else {
    // Full page, in readable segments (one PNG per segment) rather than one
    // giant image: SEGMENT css px each, captured beyond the viewport.
    const m = await cdp.send('Page.getLayoutMetrics');
    const total = Math.ceil(m.cssContentSize.height);
    const segment = sc.segment || (vp.mobile ? 1700 : 4600);
    for (let y = 0, part = 1; y < total; y += segment, part++) {
      const clip = { x: 0, y, width: vp.width, height: Math.min(segment, total - y), scale: 1 };
      const shot = await cdp.send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: true, clip });
      const file = total > segment ? `${name}-${part}.png` : `${name}.png`;
      writeFileSync(join(OUT, file), Buffer.from(shot.data, 'base64'));
      files.push(file);
    }
  }
  return { name, files, activeScreen, horizontalOverflowPx: overflow, ...(actionResult !== undefined ? { actionResult } : {}), consoleErrors: consoleErrors.splice(0) };
}

async function main() {
  if (!CHROME) throw new Error('Chrome/Edge not found; set CHROME_PATH');
  mkdirSync(OUT, { recursive: true });
  const names = process.argv.slice(2).length ? process.argv.slice(2) : Object.keys(SCENARIOS);
  const profile = mkdtempSync(join(tmpdir(), 'wt-shots-'));
  const port = 9333;
  const chrome = spawn(CHROME, ['--headless=new', `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`,
    '--no-first-run', '--no-default-browser-check', '--hide-scrollbars', '--force-color-profile=srgb', 'about:blank'], { stdio: 'ignore' });
  try {
    let targets;
    for (let i = 0; i < 50; i++) {
      try { targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json(); if (targets.length) break; } catch { /* starting */ }
      await wait(200);
    }
    const page = targets.find((t) => t.type === 'page');
    const cdp = await cdpSession(page.webSocketDebuggerUrl);
    const consoleErrors = [];
    cdp.on((ev) => {
      if (ev.method === 'Runtime.exceptionThrown') consoleErrors.push(ev.params.exceptionDetails.exception?.description || ev.params.exceptionDetails.text);
      if (ev.method === 'Runtime.consoleAPICalled' && ev.params.type === 'error') consoleErrors.push(ev.params.args.map((a) => a.value ?? a.description).join(' '));
      if (ev.method === 'Log.entryAdded' && ev.params.entry.level === 'error') consoleErrors.push(ev.params.entry.text + ' ' + (ev.params.entry.url || ''));
    });
    await cdp.send('Page.enable'); await cdp.send('Runtime.enable'); await cdp.send('Log.enable');
    const results = [];
    for (const name of names) {
      if (!SCENARIOS[name]) throw new Error(`unknown scenario ${name}`);
      try { results.push(await capture(cdp, name, SCENARIOS[name], consoleErrors)); }
      catch (e) { results.push({ name, error: e.message, consoleErrors: consoleErrors.splice(0) }); }
    }
    cdp.close();
    console.log(JSON.stringify(results, null, 1));
  } finally {
    chrome.kill();
  }
}

main().catch((e) => { console.error(e); process.exit(1); });
