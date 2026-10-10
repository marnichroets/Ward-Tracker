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
//  - Static JS/CSS/image shell files: stale-while-revalidate — answer from cache
//    immediately (fast, and works offline), but always also fetch the network copy in the
//    background and refresh the cache for next time. This bounds staleness to at most one
//    page load even on a deploy that doesn't bump CACHE_NAME below, instead of serving an
//    old cached file indefinitely (the previous cache-first strategy's bug).
//
// Update flow: install() does NOT call skipWaiting() — a newly installed worker sits in
// "waiting" instead of silently taking over a tab that has it open mid-use. It only
// activates when the page explicitly says so (see the SKIP_WAITING message handler below,
// triggered by the candidate clicking "Update" on the small banner in index.html) or
// naturally, once every tab on the old version has closed. Either way, nothing here ever
// force-reloads a tab out from under unsaved work.
const CACHE_NAME = 'ward-tracker-shell-v30';
const SHELL_FILES = ['./', './index.html', './week-dates.js', './smartsheet-activities.js', './time-options.js', './da-logo.png'];

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
  event.respondWith(isShellDocument ? networkFirst(req) : staleWhileRevalidate(req));
});
