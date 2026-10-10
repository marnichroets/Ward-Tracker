// MANDATORY pre-deployment test: an offline/pending activity created under
// "Version A" of the app must survive an application-shell update to
// "Version B" completely unchanged — still present, still syncable, and
// syncing it must never create a duplicate submission.
//
// This runs the REAL page code (getPendingQueue/queuePendingEntry/
// trySyncOne/removePendingEntry, extracted live out of index.html's own
// <script> via the same vm sandbox script-load.test.js uses — not a
// reimplementation) against a real localStorage-backed stub. The
// "Version B" update step is simulated by running sw.js's own real
// install/activate handlers (see sw-cache-strategy.test.js for the
// dedicated cache-behaviour coverage) in a SEPARATE, isolated
// ServiceWorkerGlobalScope sandbox that has no `localStorage` binding at
// all — mirroring the real browser spec (a service worker cannot reach a
// page's localStorage), so the update step structurally cannot touch it.
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');
const WeekDates = require('./week-dates');
const SmartSheetActivities = require('./smartsheet-activities');
const TimeOptions = require('./time-options');

const html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');
const scriptMatch = html.match(/<script>([\s\S]*?)<\/script>/);
if (!scriptMatch) throw new Error('could not find the inline <script> body in index.html');
const pageScriptSrc = scriptMatch[1];

const swSrc = fs.readFileSync(path.join(__dirname, 'sw.js'), 'utf8');

function makeElementStub(id) {
  const el = {
    id, value: '', textContent: '', innerHTML: '', hidden: false, disabled: false, checked: false,
    className: '', style: {}, dataset: {}, children: [],
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    onclick: null, onchange: null, oninput: null, onsubmit: null,
    addEventListener() {}, removeEventListener() {},
    appendChild(child) { el.children.push(child); return child; },
    removeChild() {}, remove() {}, click() {}, focus() {}, blur() {},
    scrollIntoView() {}, closest() { return null; },
    querySelector() { return null; }, querySelectorAll() { return []; },
    getAttribute() { return null; }, setAttribute() {}, removeAttribute() {},
  };
  return el;
}

function buildPageSandbox() {
  const elements = new Map();
  // The real, visible-side-effect storage backing localStorage — this is
  // the exact Map we diff before/after the simulated SW update to prove
  // nothing touched it.
  const storage = new Map();
  const documentStub = {
    getElementById(id) { if (!elements.has(id)) elements.set(id, makeElementStub(id)); return elements.get(id); },
    querySelector() { return null; }, querySelectorAll() { return []; },
    createElement() { return makeElementStub(null); },
    addEventListener() {}, removeEventListener() {}, title: '', body: makeElementStub('body'),
  };
  const localStorageStub = {
    getItem(key) { return storage.has(key) ? storage.get(key) : null; },
    setItem(key, value) { storage.set(key, String(value)); },
    removeItem(key) { storage.delete(key); },
  };
  const sandbox = {
    console, WeekDates, SmartSheetActivities, TimeOptions,
    document: documentStub,
    window: { addEventListener() {}, removeEventListener() {}, location: { reload() {}, hash: '' } },
    navigator: {}, location: { reload() {}, href: '', hash: '' },
    localStorage: localStorageStub,
    fetch() { return Promise.reject(new Error('fetch is not available in this smoke test')); },
    alert() {}, confirm() { return false; }, prompt() { return null; },
    URLSearchParams, FormData: class { append() {} },
    Blob: class {}, URL: { createObjectURL() { return ''; }, revokeObjectURL() {} },
    setTimeout() { return 0; }, clearTimeout() {}, setInterval() { return 0; }, clearInterval() {},
    Date, Math, JSON, Intl,
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(pageScriptSrc, sandbox, { filename: 'index.html-inline-script.js' });
  return { sandbox, storage };
}

// A completely separate global scope, exactly like a real service worker —
// no `localStorage`, `document`, or `window` binding exists here at all.
function runSwUpdateCycle(oldCacheName, newCacheName) {
  const store = new Map();
  const events = {};
  const cacheObj = (name) => {
    if (!store.has(name)) store.set(name, new Map());
    const map = store.get(name);
    return {
      addAll(urls) { urls.forEach((u) => map.set(u, 'shell-asset')); return Promise.resolve(); },
      put(req, res) { map.set(typeof req === 'string' ? req : req.url, res); return Promise.resolve(); },
      match(req) { return Promise.resolve(map.get(typeof req === 'string' ? req : req.url)); },
    };
  };
  const caches = {
    open(name) { return Promise.resolve(cacheObj(name)); },
    keys() { return Promise.resolve(Array.from(store.keys())); },
    delete(name) { return Promise.resolve(store.delete(name)); },
    match() { return Promise.resolve(undefined); },
  };
  // Pre-seed the "old" version's cache, as if Version A had already run.
  store.set(oldCacheName, new Map([['./index.html', 'old-shell']]));
  const self_ = {
    addEventListener(name, fn) { events[name] = fn; },
    skipWaiting() {},
    clients: { claim() { return Promise.resolve(); } },
    location: { origin: 'https://ward-tracker.vercel.app' },
  };
  const swSandbox = {
    self: self_, caches, URL,
    fetch() { return Promise.reject(new Error('offline during this simulated update')); },
    console,
  };
  swSandbox.globalThis = swSandbox;
  vm.createContext(swSandbox);
  // Run the bumped-version source so CACHE_NAME differs from the pre-seeded old one.
  const bumpedSrc = swSrc.replace(/ward-tracker-shell-v\d+/, newCacheName);
  vm.runInContext(bumpedSrc, swSandbox, { filename: 'sw.js' });
  let installed, activated;
  events.install({ waitUntil: (p) => { installed = p; } });
  events.activate({ waitUntil: (p) => { activated = p; } });
  return Promise.all([installed, activated]).then(() => ({
    // Proof this scope never had a localStorage binding to touch in the
    // first place — not just that it chose not to call it.
    hadLocalStorageBinding: 'localStorage' in swSandbox,
    finalCacheKeys: Array.from(store.keys()),
  }));
}

(async () => {
  // --- Version A: candidate creates an offline/pending activity ---
  const { sandbox: pageA, storage } = buildPageSandbox();
  const offlineEntry = {
    person_id: 'nomsa-dlamini', week_key: '2026-10-04', day: 'wed',
    type: 'canvassing', venue: 'Mlungisi Community Hall', notes: 'Door to door',
  };
  const localId = pageA.queuePendingEntry(offlineEntry, null);
  assert.ok(localId, 'queuePendingEntry must return a localId for the offline entry');

  const rawBefore = storage.get('pendingEntries');
  assert.ok(rawBefore, 'pendingEntries must be written to localStorage');
  const queueBefore = JSON.parse(rawBefore);
  assert.strictEqual(queueBefore.length, 1, 'exactly one pending entry must exist before the update');
  assert.strictEqual(queueBefore[0].entry.venue, 'Mlungisi Community Hall');

  // --- Version B: the application shell / service worker updates ---
  const { hadLocalStorageBinding, finalCacheKeys } = await runSwUpdateCycle(
    'ward-tracker-shell-v29', 'ward-tracker-shell-v99-test'
  );
  assert.strictEqual(hadLocalStorageBinding, false, 'a service worker scope must have no localStorage binding at all');
  assert.ok(!finalCacheKeys.includes('ward-tracker-shell-v29'), 'the old shell cache must be cleaned up on activate');
  assert.ok(finalCacheKeys.includes('ward-tracker-shell-v99-test'), 'the new shell cache must exist after activate');

  // --- After the update: the pending activity must be completely intact ---
  const rawAfter = storage.get('pendingEntries');
  assert.strictEqual(rawAfter, rawBefore, 'the pending-activity localStorage record must be byte-for-byte unchanged by the update');

  const queueAfter = JSON.parse(pageA.getPendingQueue ? JSON.stringify(pageA.getPendingQueue()) : rawAfter);
  assert.strictEqual(queueAfter.length, 1, 'exactly one pending entry must still exist after the update — none lost, none duplicated');
  assert.strictEqual(queueAfter[0].localId, localId);
  assert.strictEqual(queueAfter[0].entry.venue, 'Mlungisi Community Hall');

  // --- It must still be syncable, and sync exactly once (no duplicate) ---
  let postCount = 0;
  pageA.fetch = (url, opts) => {
    if (opts && opts.method === 'POST' && url.includes('/api/entries')) {
      postCount++;
      return Promise.resolve({ ok: true, headers: { get: () => 'application/json' }, json: async () => ({ id: 'synced-1' }) });
    }
    return Promise.reject(new Error('unexpected request: ' + url));
  };
  const synced = await pageA.trySyncOne(localId);
  assert.strictEqual(synced, true, 'trySyncOne must report success once the network is back');
  assert.strictEqual(postCount, 1, 'syncing the pending activity must POST exactly once — no duplicate submission');

  const queueAfterSync = pageA.getPendingQueue();
  assert.strictEqual(queueAfterSync.length, 0, 'a successfully synced entry must be removed from the local queue, leaving none behind');

  console.log('offline-pending-activity survives application update tests passed');
})().catch((e) => { console.error(e); process.exit(1); });
