// Loads the REAL frontend/sw.js source (not a reimplementation) into a fake
// ServiceWorkerGlobalScope and exercises its install/activate/fetch handlers
// directly, plus asserts — by inspecting the source text itself — that this
// file has no way to touch localStorage/sessionStorage/IndexedDB even if it
// wanted to (a service worker has no access to those APIs by spec; this is
// belt-and-suspenders proof on top of that spec guarantee).
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const swSrc = fs.readFileSync(path.join(__dirname, 'sw.js'), 'utf8');

// --- Structural guarantee: sw.js cannot reach page storage at all ---
// Strip comments first so this checks actual code, not the file's own
// explanatory prose about why it never touches these APIs.
const swCodeOnly = swSrc.replace(/\/\/.*$/gm, '').replace(/\/\*[\s\S]*?\*\//g, '');
for (const forbidden of [/\blocalStorage\b/, /\bsessionStorage\b/, /\bindexedDB\b/i, /\bdocument\./, /\bwindow\./]) {
  assert.ok(
    !forbidden.test(swCodeOnly),
    `sw.js code must never reference ${forbidden} — the offline pending-activity queue and ` +
    `campaign drafts live in the page's localStorage, a completely separate storage area ` +
    `a service worker cannot access`
  );
}

// The CACHE_NAME this run of sw.js actually uses — read it out rather than
// hardcoding it, so this test doesn't silently go stale next time it's bumped.
const CURRENT_CACHE_NAME = (swSrc.match(/CACHE_NAME = '([^']+)'/) || [])[1];
assert.ok(CURRENT_CACHE_NAME, 'could not read CACHE_NAME out of sw.js');

// --- Fake ServiceWorkerGlobalScope: an in-memory Cache Storage + fetch stub ---
function makeFakeResponse(body) {
  return {
    ok: true,
    body,
    clone() { return makeFakeResponse(body); },
  };
}

const ORIGIN = 'https://ward-tracker.vercel.app';
// Mirrors how a real browser resolves every Cache Storage key and Request
// URL to an absolute URL (against the page/registration origin) regardless
// of whether relative ('./index.html') or absolute strings were used.
function toKey(reqOrUrl) {
  const raw = typeof reqOrUrl === 'string' ? reqOrUrl : reqOrUrl.url;
  return new URL(raw, ORIGIN + '/').href;
}

function buildSwSandbox({ networkFiles, src }) {
  const store = new Map(); // cacheName -> Map(absoluteUrl -> response)
  const events = {};
  const claimed = { count: 0 };
  const cacheObj = (name) => {
    if (!store.has(name)) store.set(name, new Map());
    const map = store.get(name);
    return {
      addAll(urls) {
        // Reads the CURRENT (possibly swapped-via-setNetworkFiles) content,
        // not a stale closure snapshot — matches a real network fetch.
        urls.forEach((u) => map.set(toKey(u), makeFakeResponse(resolvedNetworkFiles[toKey(u)])));
        return Promise.resolve();
      },
      put(req, res) {
        map.set(toKey(req), res);
        return Promise.resolve();
      },
      match(req) {
        return Promise.resolve(map.get(toKey(req)));
      },
    };
  };
  const caches = {
    open(name) { return Promise.resolve(cacheObj(name)); },
    keys() { return Promise.resolve(Array.from(store.keys())); },
    delete(name) { const existed = store.delete(name); return Promise.resolve(existed); },
    match(req) {
      const key = toKey(req);
      for (const map of store.values()) {
        if (map.has(key)) return Promise.resolve(map.get(key));
      }
      return Promise.resolve(undefined);
    },
  };
  let resolvedNetworkFiles = {};
  let networkOnline = true;
  const setNetworkFiles = (files) => {
    resolvedNetworkFiles = {};
    Object.entries(files).forEach(([k, v]) => { resolvedNetworkFiles[toKey(k)] = v; });
  };
  const setOnline = (value) => { networkOnline = value; };
  setNetworkFiles(networkFiles);
  let fetchCallCount = 0;
  const fetchFn = (req) => {
    fetchCallCount++;
    if (!networkOnline) return Promise.reject(new Error('offline'));
    const content = resolvedNetworkFiles[toKey(req)];
    if (content === undefined) return Promise.reject(new Error('network unreachable: ' + toKey(req)));
    return Promise.resolve(makeFakeResponse(content));
  };
  const self_ = {
    addEventListener(name, fn) { events[name] = fn; },
    skipWaiting: () => { self_._skipWaitingCalled = true; },
    clients: { claim: () => { claimed.count++; return Promise.resolve(); } },
    location: { origin: ORIGIN, href: ORIGIN + '/sw.js' },
    _skipWaitingCalled: false,
  };
  const sandbox = {
    self: self_, caches, fetch: fetchFn, URL,
    console,
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(src || swSrc, sandbox, { filename: 'sw.js' });
  return {
    sandbox, events, store, claimed, setNetworkFiles, setOnline,
    getFetchCallCount: () => fetchCallCount,
  };
}

function runInstall(ctx) {
  let captured;
  const event = { waitUntil: (p) => { captured = p; } };
  ctx.events.install(event);
  return Promise.resolve(captured);
}
function runActivate(ctx) {
  let captured;
  const event = { waitUntil: (p) => { captured = p; } };
  ctx.events.activate(event);
  return Promise.resolve(captured);
}
function runFetch(ctx, url, mode) {
  let responded;
  const event = {
    request: { method: 'GET', url: toKey(url), mode: mode || 'same-origin' },
    respondWith: (p) => { responded = p; },
  };
  ctx.events.fetch(event);
  return responded;
}

(async () => {
  // --- "Version A": app loads, shell files land in Cache Storage ---
  const networkFilesV1 = {
    './': 'HTML-v1', './index.html': 'HTML-v1', './week-dates.js': 'JS-v1',
    './smartsheet-activities.js': 'SS-v1', './time-options.js': 'TO-v1', './da-logo.png': 'LOGO-v1',
  };
  const ctxA = buildSwSandbox({ networkFiles: networkFilesV1 });
  await runInstall(ctxA);
  await runActivate(ctxA);
  assert.strictEqual(ctxA.claimed.count, 1, 'activate must claim clients exactly once');
  assert.ok(!ctxA.sandbox.self._skipWaitingCalled, 'install must NOT call skipWaiting() — updates wait for explicit consent');

  // --- Critical JS (week-dates.js etc.) is network-first ---
  // Online and unchanged: still just gets the (same) network copy, and
  // caches it, proving the network path is actually taken (not skipped in
  // favour of cache) even when there's nothing new to show.
  const onlineUnchanged = await runFetch(ctxA, './week-dates.js');
  assert.strictEqual(onlineUnchanged.body, 'JS-v1', 'online load must come from the network');
  assert.strictEqual(ctxA.getFetchCallCount(), 1, 'a critical JS asset must always be attempted over the network while online — no cache-first shortcut');

  // da-logo.png (non-critical visual asset) stays stale-while-revalidate:
  // the cached copy answers immediately without waiting on the network.
  const logoFirstLoad = await runFetch(ctxA, './da-logo.png');
  assert.strictEqual(logoFirstLoad.body, 'LOGO-v1', 'logo must be servable from the shell cache');

  // --- REQUIRED TEST 1: an ONLINE normal load gets Version B immediately, first try ---
  // "Version B is deployed" — network content changes, nothing else about
  // this worker/cache changes (no new install, no page reload beyond the
  // one normal load itself).
  const networkFilesV2 = {
    './': 'HTML-v2', './index.html': 'HTML-v2', './week-dates.js': 'JS-v2',
    './smartsheet-activities.js': 'SS-v2', './time-options.js': 'TO-v2', './da-logo.png': 'LOGO-v1',
  };
  ctxA.setNetworkFiles(networkFilesV2);
  const fetchCountBeforeV2 = ctxA.getFetchCallCount();

  const weekDatesV2 = await runFetch(ctxA, './week-dates.js');
  assert.strictEqual(weekDatesV2.body, 'JS-v2', 'week-dates.js: an online normal load must receive Version B on the very first request — no one-load lag');

  const smartsheetV2 = await runFetch(ctxA, './smartsheet-activities.js');
  assert.strictEqual(smartsheetV2.body, 'SS-v2', 'smartsheet-activities.js: must also receive Version B immediately');

  const timeOptionsV2 = await runFetch(ctxA, './time-options.js');
  assert.strictEqual(timeOptionsV2.body, 'TO-v2', 'time-options.js: must also receive Version B immediately');

  const navV2 = await runFetch(ctxA, './index.html', 'navigate');
  assert.strictEqual(navV2.body, 'HTML-v2', 'navigation requests must also always be Version B online — unchanged prior behaviour');

  // Each critical-JS/document request above must have gone over the network
  // (not a cache hit), proving "network-first", not merely "eventually
  // correct" — exactly 4 fetches for the 4 requests just made.
  assert.strictEqual(ctxA.getFetchCallCount() - fetchCountBeforeV2, 4, 'every online critical-JS/document request above must have hit the network, not the cache');

  // The successful Version B fetches must also have refreshed the cache
  // (for the offline fallback test below, and for future offline use).
  const cachedAfterV2 = await ctxA.sandbox.caches.match({ url: toKey('./week-dates.js') });
  assert.strictEqual(cachedAfterV2.body, 'JS-v2', 'a successful network-first fetch must still update the cache for offline fallback');

  // --- REQUIRED TEST 2: offline, the same critical JS still loads from cache ---
  ctxA.setOnline(false);
  const offlineWeekDates = await runFetch(ctxA, './week-dates.js');
  assert.strictEqual(offlineWeekDates.body, 'JS-v2', 'offline: critical JS must fall back to the last cached (Version B) copy, not fail outright');

  const offlineNav = await runFetch(ctxA, './index.html', 'navigate');
  assert.strictEqual(offlineNav.body, 'HTML-v2', 'offline: navigation must also fall back to the cached shell — offline capability unchanged');

  const offlineLogo = await runFetch(ctxA, './da-logo.png');
  assert.strictEqual(offlineLogo.body, 'LOGO-v1', 'offline: the non-critical visual asset must still be servable from cache too');
  ctxA.setOnline(true);

  // --- Cache cleanup still only ever touches Cache Storage ---
  // A second worker instance represents the new sw.js version after a
  // deploy that also bumped CACHE_NAME; its own install only populates ITS
  // cache, then activate must purge every other (now-obsolete) cache name —
  // Cache Storage only, never touching the page's localStorage.
  const bumpedCacheName = CURRENT_CACHE_NAME + '-test';
  const bumpedSrc = swSrc.replace(new RegExp(`CACHE_NAME = '${CURRENT_CACHE_NAME}'`), `CACHE_NAME = '${bumpedCacheName}'`);
  const resolvedNetworkFilesV2 = {};
  Object.entries(networkFilesV2).forEach(([k, v]) => { resolvedNetworkFilesV2[toKey(k)] = v; });
  const sandboxB = { ...ctxA.sandbox }; // reuse the same fake caches store
  const eventsB = {};
  sandboxB.self = {
    addEventListener(name, fn) { eventsB[name] = fn; },
    skipWaiting: () => {},
    clients: { claim: () => Promise.resolve() },
    location: { origin: ORIGIN, href: ORIGIN + '/sw.js' },
  };
  sandboxB.fetch = (req) => {
    const content = resolvedNetworkFilesV2[toKey(req)];
    return content !== undefined
      ? Promise.resolve(makeFakeResponse(content))
      : Promise.reject(new Error('unreachable'));
  };
  vm.createContext(sandboxB);
  vm.runInContext(bumpedSrc, sandboxB, { filename: 'sw.js (bumped)' });
  let capturedInstall;
  eventsB.install({ waitUntil: (p) => { capturedInstall = p; } });
  await Promise.resolve(capturedInstall);
  const keysBeforeActivate = await ctxA.sandbox.caches.keys();
  assert.ok(keysBeforeActivate.includes(CURRENT_CACHE_NAME), 'old cache must still exist until the new worker activates');
  let capturedActivate;
  eventsB.activate({ waitUntil: (p) => { capturedActivate = p; } });
  await Promise.resolve(capturedActivate);
  const keysAfterActivate = await ctxA.sandbox.caches.keys();
  assert.ok(!keysAfterActivate.includes(CURRENT_CACHE_NAME), 'the obsolete shell cache must be removed on activate');
  assert.ok(keysAfterActivate.includes(bumpedCacheName), 'the new shell cache must remain');

  console.log('sw.js cache-strategy tests passed');
})().catch((e) => { console.error(e); process.exit(1); });
