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
  'landing-phone': { vp: PHONE, hash: '', waitFor: '#whoName' },
  'landing-desktop': { vp: DESKTOP, hash: '', waitFor: '#whoName' },
  'coordinator-debug': {
    vp: DESKTOP, login: adminLogin, hash: '', waitFor: '#whoName', fullPage: false,
    actions: `try { await loadAdmin(); return 'ok'; } catch (e) { return String(e && (e.stack || e.message || e)); }`,
  },
  // Same path as after a successful PIN entry (the #admin deep link has a
  // pre-existing boot-order bug, logged for Stage 2).
  'coordinator-desktop': { vp: DESKTOP, login: adminLogin, hash: '', waitFor: '#whoName',
    actions: `await loadAdmin(); show('screenAdmin');`, settle: 800 },
  'coordinator-phone': { vp: PHONE, login: adminLogin, hash: '', waitFor: '#whoName',
    actions: `await loadAdmin(); show('screenAdmin');`, settle: 800 },
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
  const overflow = await evaluate(cdp, 'return document.documentElement.scrollWidth - window.innerWidth');
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
  return { name, files, horizontalOverflowPx: overflow, ...(actionResult !== undefined ? { actionResult } : {}), consoleErrors: consoleErrors.splice(0) };
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
