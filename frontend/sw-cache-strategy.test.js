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

function buildSwSandbox({ networkFiles }) {
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
  const setNetworkFiles = (files) => {
    resolvedNetworkFiles = {};
    Object.entries(files).forEach(([k, v]) => { resolvedNetworkFiles[toKey(k)] = v; });
  };
  setNetworkFiles(networkFiles);
  let fetchCallCount = 0;
  const fetchFn = (req) => {
    fetchCallCount++;
    const content = resolvedNetworkFiles[toKey(req)];
    if (content === undefined) return Promise.reject(new Error('network unreachable: ' + toKey(req)));
    return Promise.resolve(makeFakeResponse(content));
  };
  const self_ = {
    addEventListener(name, fn) { events[name] = fn; },
    skipWaiting: () => { self_._skipWaitingCalled = true; },
    clients: { claim: () => { claimed.count++; return Promise.resolve(); } },
    location: { origin: ORIGIN },
    _skipWaitingCalled: false,
  };
  const sandbox = {
    self: self_, caches, fetch: fetchFn, URL,
    console,
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(swSrc, sandbox, { filename: 'sw.js' });
  return { sandbox, events, store, claimed, setNetworkFiles, getFetchCallCount: () => fetchCallCount };
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
  // --- "Version A" install + activate: shell files land in Cache Storage ---
  const networkFilesV1 = {
    './': 'HTML-v1', './index.html': 'HTML-v1', './week-dates.js': 'JS-v1',
    './smartsheet-activities.js': 'SS-v1', './time-options.js': 'TO-v1', './da-logo.png': 'LOGO',
  };
  const ctxA = buildSwSandbox({ networkFiles: networkFilesV1 });
  await runInstall(ctxA);
  await runActivate(ctxA);
  assert.strictEqual(ctxA.claimed.count, 1, 'activate must claim clients exactly once');
  assert.ok(!ctxA.sandbox.self._skipWaitingCalled, 'install must NOT call skipWaiting() — updates wait for explicit consent');

  // Stale-while-revalidate: a cached static asset is served immediately,
  // and the background fetch refreshes the cache for the *next* load.
  const cachedJs = await runFetch(ctxA, './week-dates.js');
  assert.strictEqual(cachedJs.body, 'JS-v1', 'cached asset must be served immediately');

  // --- "Version B": shell files changed on the network; a new worker installs ---
  const networkFilesV2 = {
    './': 'HTML-v2', './index.html': 'HTML-v2', './week-dates.js': 'JS-v2',
    './smartsheet-activities.js': 'SS-v2', './time-options.js': 'TO-v2', './da-logo.png': 'LOGO',
  };
  const resolvedNetworkFilesV2 = {};
  Object.entries(networkFilesV2).forEach(([k, v]) => { resolvedNetworkFilesV2[toKey(k)] = v; });
  // Simulate the SAME cache name still active (a deploy that forgot to bump
  // CACHE_NAME) by swapping in new network content without any new SW
  // version — stale-while-revalidate must still self-heal within one load.
  ctxA.setNetworkFiles(networkFilesV2);
  const stillCachedOldJs = await runFetch(ctxA, './week-dates.js');
  assert.strictEqual(stillCachedOldJs.body, 'JS-v1', 'first load after a deploy may still answer from cache (expected)');
  await new Promise((r) => setTimeout(r, 0)); // let the background revalidation fetch settle
  const healedJs = await runFetch(ctxA, './week-dates.js');
  assert.strictEqual(healedJs.body, 'JS-v2', 'the very next load must serve the refreshed asset — staleness bounded to one load');

  // Navigation/document requests are network-first: always fresh when online.
  const navResponse = await runFetch(ctxA, './index.html', 'navigate');
  assert.strictEqual(navResponse.body, 'HTML-v2', 'navigation requests must be network-first, never stuck on a stale cached shell');

  // --- Now simulate a real CACHE_NAME bump (the normal/recommended deploy) ---
  // A second worker instance represents the new sw.js version after a
  // deploy that also bumped CACHE_NAME; its own install only populates ITS
  // cache, then activate must purge every other (now-obsolete) cache name —
  // Cache Storage only, never touching the page's localStorage.
  const bumpedSrc = swSrc.replace(/ward-tracker-shell-v\d+/, 'ward-tracker-shell-v31-test');
  const sandboxB = { ...ctxA.sandbox }; // reuse the same fake caches store
  const eventsB = {};
  sandboxB.self = {
    addEventListener(name, fn) { eventsB[name] = fn; },
    skipWaiting: () => {},
    clients: { claim: () => Promise.resolve() },
    location: { origin: 'https://ward-tracker.vercel.app' },
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
  assert.ok(keysBeforeActivate.includes('ward-tracker-shell-v30'), 'old cache must still exist until the new worker activates');
  let capturedActivate;
  eventsB.activate({ waitUntil: (p) => { capturedActivate = p; } });
  await Promise.resolve(capturedActivate);
  const keysAfterActivate = await ctxA.sandbox.caches.keys();
  assert.ok(!keysAfterActivate.includes('ward-tracker-shell-v30'), 'the obsolete shell cache must be removed on activate');
  assert.ok(keysAfterActivate.includes('ward-tracker-shell-v31-test'), 'the new shell cache must remain');

  console.log('sw.js cache-strategy tests passed');
})().catch((e) => { console.error(e); process.exit(1); });
