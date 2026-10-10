// Caches the app shell (this page + its local assets) so it still opens with no connection.
// API calls (a different origin) are left alone — the page's own offline queue handles those.
//
// This worker's Cache Storage (`caches`) holds ONLY application shell files — it never
// reads or writes localStorage/sessionStorage/IndexedDB, which a service worker has no
// access to in the first place (a separate global scope by spec). The candidate's offline
// pending-activity queue and campaign drafts live in the page's localStorage and are
// completely untouched by anything in this file.
//
// Strategy:
//  - Navigation/HTML shell requests: network-first, falling back to the cached shell only
//    when offline — so a deployed change reaches the very next load, never served stale
//    just because an old copy happens to be cached.
//  - Critical application JS (CRITICAL_JS_FILES below — the scripts candidate login,
//    autocomplete, the election countdown, and dashboard init all depend on): also
//    network-first. An online load always attempts the current network copy first — no
//    one-load lag — and only falls back to the last cached copy when the network fetch
//    genuinely fails (offline), so offline capability is unchanged.
//  - Non-critical visual assets (da-logo.png): stale-while-revalidate — answer from cache
//    immediately (fast, and works offline), but always also fetch the network copy in the
//    background and refresh the cache for next time. A one-load lag here is harmless; this
//    file almost never changes and isn't required for the app to function correctly.
//
// Update flow: install() does NOT call skipWaiting() — a newly installed worker sits in
// "waiting" instead of silently taking over a tab that has it open mid-use. It only
// activates when the page explicitly says so (see the SKIP_WAITING message handler below,
// triggered by the candidate clicking "Update" on the small banner in index.html) or
// naturally, once every tab on the old version has closed. Either way, nothing here ever
// force-reloads a tab out from under unsaved work.
const CACHE_NAME = 'ward-tracker-shell-v31';
const CRITICAL_JS_FILES = ['./week-dates.js', './smartsheet-activities.js', './time-options.js'];
const SHELL_FILES = ['./', './index.html', ...CRITICAL_JS_FILES, './da-logo.png'];
// Resolved once at startup against this worker's own URL, so a plain
// pathname comparison in the fetch handler below is enough — no re-parsing
// per request.
const CRITICAL_JS_PATHS = new Set(CRITICAL_JS_FILES.map((f) => new URL(f, self.location.href).pathname));

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_FILES))
  );
});

// The page posts this once the candidate explicitly clicks "Update" on the
// update-available banner — never sent automatically.
self.addEventListener('message', (event) => {
  if (event.data === 'SKIP_WAITING') self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      // Only ever deletes this worker's OWN obsolete shell-asset cache
      // versions (ward-tracker-shell-v*) — Cache Storage is a separate
      // browser storage area from localStorage/IndexedDB and holds no
      // candidate data, so this can never remove anything user-created.
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

async function networkFirst(req) {
  try {
    const res = await fetch(req);
    if (res && res.ok) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(req, res.clone());
    }
    return res;
  } catch (e) {
    const cached = await caches.match(req);
    return cached || caches.match('./index.html');
  }
}

// Same network-first shape as above, but for a critical JS asset falling
// back to the shell document would be wrong (it'd hand the browser HTML
// where it expected a script). Fall back only to that exact file's own
// last cached copy — genuinely offline with nothing cached yet is the only
// remaining failure case, same as any other uncached offline request.
async function networkFirstAsset(req) {
  try {
    const res = await fetch(req);
    if (res && res.ok) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(req, res.clone());
    }
    return res;
  } catch (e) {
    const cached = await caches.match(req);
    if (cached) return cached;
    throw e;
  }
}

async function staleWhileRevalidate(req) {
  const cached = await caches.match(req);
  const networkFetch = fetch(req)
    .then(async (res) => {
      if (res && res.ok) {
        const cache = await caches.open(CACHE_NAME);
        cache.put(req, res.clone());
      }
      return res;
    })
    .catch(() => null);

  if (cached) {
    // Serve the cached copy immediately; the network refresh above keeps
    // running in the background so the *next* load gets the latest file.
    return cached;
  }
  const fresh = await networkFetch;
  return fresh || caches.match('./index.html');
}

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return; // never intercept API writes — let them fail/succeed naturally

  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return; // API calls go straight to network

  const isShellDocument = req.mode === 'navigate' || url.pathname.endsWith('/index.html') || url.pathname === '/';
  if (isShellDocument) {
    event.respondWith(networkFirst(req));
    return;
  }
  if (CRITICAL_JS_PATHS.has(url.pathname)) {
    event.respondWith(networkFirstAsset(req));
    return;
  }
  event.respondWith(staleWhileRevalidate(req));
});
