# PHO Upgrade Plan — Ward Tracker

Agreed approach for upgrading Ward Tracker into a premium, PHO-ready
operational reporting platform. Keep this file current as each stage lands —
it records what was agreed and what is actually done, not aspirations.

- **Branch:** `dev/pho-premium-upgrade` (cut from clean `main` at `163658b`,
  2026-11-12). All work happens here. Nothing is merged or deployed without
  explicit approval.
- **Status:** Stages 0 and 0A complete. **Stage 1 complete — awaiting
  review before Stage 2.**
- **Scope clarification (2026-11-12):** this upgrades the *existing, live*
  Ntsikana Ward Tracker in place — not a separate demonstration product.
  Synthetic data is used only for local development and testing; every
  change must work unchanged against existing production data. The full
  candidate-auth redesign and individual PHO accounts are deferred until
  after the PHO pitch; the Stage 0A findings below remain open.

## 1. Objective

A polished, fast, secure and credible tool that can be demonstrated to PHO
without risking any current Ward Tracker functionality.

## 2. Agreed decisions (2026-11-12)

1. **Election countdown** — remove the expired countdown (election day
   4 Nov 2026 has passed; the landing page permanently shows "0 DAYS TO GO").
   Scheduled for Stage 2 (candidate experience).
2. **Scope** — the first premium demonstration is built around Ntsikana
   Constituency. Keep future PHO expansion in mind (no hard-coded
   single-constituency assumptions in new code), but **no multi-tenancy now**.
3. **Candidate authentication** — unauthorized modification/deletion of
   candidate activities is a **high-priority security issue**. The proposed
   remediation is in §6.4.
4. **PHO access** — PHO will eventually get separate, individually
   authenticated, read-only access. The shared Coordinator Leader PIN is not
   the long-term solution (§6.4, R4).
5. **Brand** — use the existing DA logo (`frontend/da-logo.png`) and refine the
   current palette. Do not invent or claim official DA brand standards.

## 3. Guardrails (non-negotiable)

- Work only on `dev/pho-premium-upgrade`. No production deployments,
  configuration changes or data changes.
- Never send POST/PUT/PATCH/DELETE to production; verification is local only.
- Preserve all existing activities, campaigns, exports, offline functionality,
  official capture workflows and SmartSheet integrations. Reporting
  calculations and SmartSheet formats stay byte-for-byte compatible.
  `smartsheet_reporting.py` is not edited.
- No new paid services and no unnecessary dependencies. Charts use the
  existing hand-written SVG approach; password hashing uses Python's stdlib
  (`hashlib.scrypt`); tokens use the already-installed `python-jose`.
- **Sample data is never presented as real performance.** Prototype figures
  are synthetic, carry a persistent "SAMPLE DATA — not actual performance"
  banner, and use fictional candidate names (§7).

## 4. Stages

| Stage | Scope | Exit criteria | Status |
|---|---|---|---|
| **0** | Reliable baseline: repair date-dependent tests without weakening assertions; bring documentation up to date | Full backend + frontend suites green; docs accurate | **Done** (§5) |
| **0A** | Focused, read-only security assessment of candidate endpoints; containment + remediation proposal | Findings, containment and remediation reviewed | **Done — awaiting review** (§6) |
| **1** | Premium visual foundation + PHO leadership dashboard in the live app, developed on synthetic data; desktop and mobile first-class | Reviewed on desktop + phone widths | **Done — awaiting review** (§5A) |
| **2** | Coordinator and candidate experience improvements without altering business logic | All suites green; screenshots reviewed | Not started |
| **3** | Verified reporting capabilities + performance, reusing existing data and infrastructure | Golden-output tests prove existing numbers unchanged | Not started |
| **4** | Security hardening, comprehensive regression, desktop/mobile checks, independent review, then request deployment approval | Review signed off | Not started |

Per the 2026-11-12 clarification, improvements go directly into the live
app's own files (`frontend/index.html`, `leadership_reporting.py`, …) on
this branch. Only the local development tooling lives separately, in
`devtools/`, and it is never deployed.

## 5. Stage 0 results

### 5.1 Date-dependent tests

- **Symptom:** clean `main` gave 509 passed / **95 failed** (90 in
  `tests/test_campaigns.py`, 5 in `tests/test_operational_upgrade.py`).
- **Root cause:** test fixtures use literal Sept/Oct 2026 campaign dates
  (authored 2026-09-05 and 2026-09-14). Once the real date passed those end
  dates, the Phase 5 past-campaign creation guard (`create_campaign`,
  `main.py`) correctly rejected them. This was test rot, not an app regression.
- **Fix (tests only):** new helper `tests/frozen_clock.py` patches
  `week_dates._sast_date`, the single function every app-side "today" goes through
  (`sast_today`, `current_week_key`, campaign status, leadership periods),
  so the whole app sees one consistent date. An explicit `now` argument is
  always honoured. Both affected modules pin "today" to 2026-09-14 via
  `setUpModule`/`tearDownModule`, so the patch never leaks into other test
  modules. **No assertion and no fixture date was changed.**
- **Result:** 604 passed, 0 failed, 122 subtests. All 16 frontend test files
  pass.
- **Future-proofing check:** the full suite was also run with the clock pushed
  to 2027-03-01 and 2028-01-15 — 604 passed both times, so no other test
  module contains this kind of date dependency.

### 5.2 Documentation

- `CLAUDE.md` updated: actual module list (leadership/PDF/calendar/records/
  config modules), roles and access model, the photo evidence that already
  exists, the test-clock convention and the current baseline. Pointer to
  this plan added.
- `CAMPAIGNS.md` updated: Phase 4/5 status corrected to deployed (consistent
  with the CLAUDE.md production baseline), photo evidence status corrected.
- **Needs owner confirmation:** CLAUDE.md's "Current production baseline"
  line still names `90400fb` (Phase 5). `main` is ~60 commits ahead, and
  later features (leadership dashboard, calendar, reminder cards) appear to be
  live. Per CLAUDE.md's own rule that line is only changed after a deploy is
  confirmed, so it was left as-is. Please confirm the deployed commit
  (read-only, from the Vercel/Railway dashboards).

## 5A. Stage 1 results — premium visual foundation + PHO leadership dashboard

### What changed
- **Visual foundation (all screens):** refined design tokens in place —
  DA navy/blue/gold unchanged as hues; cool neutral surfaces; semantic
  status colours; validated chart palette (`--viz-1` DA blue `#2568AE`,
  `--viz-2` deepened DA gold `#C2862C`, `--viz-3` teal `#1F8A70` — passes
  lightness, chroma, colour-blind separation and 3:1 contrast checks; the
  original gold `#D89B3C` failed contrast for chart marks). Visible keyboard
  focus rings. Pinch-zoom re-enabled (`maximum-scale=1` removed).
- **Leadership screen → executive dashboard** (same `#leader` route, same
  `/api/leader/dashboard` call, one request per view):
  navy app bar with the DA logo; period control (1 / 4 / 12 weeks, week
  navigation); municipality/ward/candidate filters with "Clear filters";
  a one-sentence executive summary built only from on-screen figures;
  6 KPI cards with 12-week sparklines; interactive 12-week activity trend
  (canvassing vs other); daily chart; ward coverage (all 35 wards in
  natural order, never ranked); municipality summary; official capture
  progress; candidate participation; activity mix; activity records;
  active campaigns with progress.
- **Interaction:** every chart mark is a keyboard-focusable target with a
  tooltip; selecting a day, ward, municipality, candidate, activity type,
  canvassing or "waiting for capture" filters the activity records below
  (drill-down), with a one-click "Filter the whole dashboard to this";
  selecting a week in any weekly chart opens that week. Every chart has a
  "Show as table" view, so no value is hover-only.
- **Backend (additive):** `operational_trend`, `capture_summary`,
  `municipality_summary`, and `capture_status`/`is_canvassing` on activity
  rows. One wording fix: an in-progress *multi-week* period's comparison
  now reads "same point in the previous period" instead of "same point
  last week" (single-week wording unchanged).
- **Unchanged:** Reports page and its three downloads, Excel/PDF output,
  SmartSheet, coordinator and candidate screens (structure), offline
  queue. Service-worker cache bumped to v32 because shell files changed.

### Verification
- Backend: **623 passed**, 0 failed (122 subtests). Frontend: **16/16** files pass.
- Golden comparison (7 filter scenarios, synthetic data): every
  pre-existing `build_dashboard` value and every leadership Excel cell is
  identical before/after; the only difference is the corrected multi-week
  comparison wording.
- New sections reconcile with the KPIs by test (capture total, municipality
  sum and last trend week all equal `total_activities`).
- Screenshots at 1440 / 1024 / 390 / 360 px: no horizontal overflow, no
  console errors. Scripted with `devtools/screenshot.mjs`.
- Performance (478 synthetic activities): `build_dashboard` 173 ms (1 week) /
  384 ms (12 weeks), up from 129 / 305 ms; Stage 3 targets this.

### Local development environment (synthetic data only)
```
python devtools/local_server.py      # http://127.0.0.1:8765 (coordinator PIN 1111, leader PIN 2222)
node devtools/screenshot.mjs          # desktop + phone screenshots -> devtools/screenshots/
```
The real `main.py` app and `frontend/` run against an in-memory store
seeded with deterministic, fictional-candidate data shaped like Ntsikana
(Amahlathi 14 wards, Raymond Mhlaba 21). Isolation: `MONGO_URI` forced to an
unroutable address, all collections replaced in memory, CSP
`connect-src 'self'` blocks any production API call, bound to 127.0.0.1,
and a persistent "synthetic data, not real activity" banner on every screen.

### Found, deferred to later stages
- **Pre-existing bug (Stage 2):** opening `/#admin` with a saved coordinator
  session always falls back to the PIN prompt — `loadAdmin()` runs during
  boot and assigns `smartsheetReviewOpen`, a `let` declared later in the
  script (temporal dead zone `ReferenceError`). Present on `main`.
- Expired election countdown removal (Stage 2, as agreed).
- Stage 3: gzip API responses (Starlette `GZipMiddleware`, no new
  dependency — the 12-week payload is 276 KB uncompressed); compute ward
  attribution once per entry; date-bounded queries.

## 6. Stage 0A — security assessment (read-only)

Method: source review of every route in `main.py` plus the frontend's auth and
offline code. No production requests were made.

### 6.1 Findings

| ID | Severity | Finding |
|---|---|---|
| **S1** | **High** | **Candidate identity is a bearer name.** Every candidate route trusts the client-supplied `person_id`, which is just the slug of a public roster name (`GET /api/roster/names` lists every name unauthenticated). Anyone with the app URL can, for any candidate: list activities (`GET /api/entries`), create (`POST`), edit (`PUT /api/entries/{id}`) and **hard-delete** (`DELETE /api/entries/{id}?person_id=…`) activities; create/edit/submit/archive/delete campaigns and campaign activities. Deletion is `delete_one` with **no audit record**, so it is unrecoverable except from backups. A malicious edit to a Captured activity also silently reopens it (Phase 5 reset), corrupting the coordinator's queue. |
| **S2** | **High** | **Unthrottled PIN logins.** `/api/admin/login` and `/api/leader/login` have no rate limit or lockout; the admin PIN is compared with `!=` (not constant-time). A short numeric PIN can be brute-forced in minutes. An admin token grants full coordinator write access (roster delete/reassign, capture changes) for 30 days. |
| **S3** | High *(if env unset)* | **Hard-coded leader PIN fallback.** If neither `COORDINATOR_LEADER_PIN(_HASH)` nor `LEADER_PIN(_HASH)` is set, the leader PIN falls back to a hash of `1234` that sits in the source code (`DEFAULT_LEADER_PIN_HASH`). |
| **S4** | Medium | **Evidence photos exposed via S1.** Candidate `GET /api/entries` returns each photo's `access_token`, and the owner-path photo check needs only `person_id` + that token. So anyone can view any candidate's photos. Tokens also travel in URL query strings, where they can leak through logs and referrers. |
| **S5** | Medium | **Unauthenticated uploads.** `POST /api/evidence/photos` accepts up to 6 MB per image for any roster name, with no rate limit or quota. That opens a storage-exhaustion path into the production MongoDB (GridFS). |
| **S6** | Medium | **Shared, long-lived, irrevocable tokens.** 30-day JWTs live in `localStorage`; the only revocation is rotating `JWT_SECRET`. One shared admin PIN and one shared leader PIN (token hard-codes a single person's name) means no per-person accountability. |
| **S7** | Low–Medium *(if env unset)* | CORS falls back to `*` with `allow_credentials=True` when `FRONTEND_ORIGIN` is unset. Impact is limited because auth uses an `Authorization` header (not cookies), but it should still be pinned. |
| **S8** | Low | Legacy public reads: `GET /api/campaigns/{id}` and `/api/campaigns/{id}/activities` without `person_id` return any submitted campaign (including support-person names). Requires knowing the ObjectId. |
| **S9** | Low | No security headers on the frontend (no `vercel.json`): no CSP, no `frame-ancestors` (clickjacking of coordinator screens), no `Referrer-Policy`. |
| — | Info | No XSS issue found in a spot check: `escapeHtml` is applied consistently to rendered fields, and `frontend/html-safety.test.js` guards this. No server-side request logging or audit of candidate mutations exists. |

### 6.2 Immediate containment (no code change; owner actions, owner's call)

These are production configuration or operational actions. They are
**recommendations only**; nothing has been changed.

1. **Verify Railway environment variables** (read-only look):
   `ADMIN_PIN` is long and random (recommend ≥10 characters, not a short numeric
   PIN); `COORDINATOR_LEADER_PIN` or `_HASH` is set (closes S3);
   `FRONTEND_ORIGIN=https://ward-tracker.vercel.app` (closes S7);
   `JWT_SECRET` is ≥32 random bytes.
2. If `ADMIN_PIN` is short or widely shared, **rotate it**. Rotating
   `JWT_SECRET` at the same time revokes every outstanding admin/leader token
   (everyone signs in once more).
3. **Back up now and daily until S1 is fixed.** Take a read-only snapshot of
   `entries`, `campaigns`, `roster` (existing `backups/` practice). Confirm whether
   the MongoDB plan has automated backups (free-tier Atlas clusters do not).
4. Share the app URL only with roster candidates and staff, never publicly.
5. Compare successive admin Excel exports (per-candidate activity counts) to
   spot unexpected deletions until audit logging exists.

### 6.3 Proposed remediation — summary

Ordered by risk reduction per unit of change. Every item is additive, behind
tests, and requires explicit approval before any deployment.

| Ref | Change | Closes | Disruption |
|---|---|---|---|
| **R1** | Login hardening: per-IP + global throttling with backoff on PIN endpoints, constant-time compare, fail closed at startup if no leader PIN is configured | S2, S3 | None for legitimate users |
| **R2** | Audit before-images: before any candidate `PUT`/`DELETE` on an entry, write the full previous document to the existing `activity_audit` collection | Makes S1 tampering **detectable and recoverable** | None (behaviour unchanged) |
| **R3** | **Candidate access codes** (main fix, §6.4) | S1, S4, S5, S8 | One-time code entry per device |
| **R4** | Individual staff accounts incl. read-only PHO role | S6, decision 4 | Staff sign in with username + passphrase |
| **R5** | `vercel.json` security headers | S9 | None |

**Recommended sequencing:** R1 + R2 first, as a small "containment" change
set (low risk, high value). R3 next as its own staged rollout. R4 and R5 in
Stage 4. R1–R3 touch only backend auth plumbing and a small enrolment
screen, so they can be developed alongside the Stage 1 prototype if you
approve. They are independent of it.

### 6.4 Proposed remediation — design detail

**R3 · Candidate access codes** — chosen as the simplest secure option that
keeps the current name-autocomplete flow.

- The coordinator issues each roster candidate a **personal access code**
  (10 characters from an unambiguous alphabet, about 50 bits — impractical to
  guess even before rate limiting) from the Coordinator workspace. It is
  shown once and can be shared two ways:
  - as a one-tap link with the code in the URL **fragment**
    (`…/#enrol=<slug>.<code>`; fragments are never sent to servers or logs,
    and the page strips it after use), or
  - typed manually after selecting the name (existing autocomplete).
- Stored as a salted `hashlib.scrypt` hash plus `token_version` on the
  candidate's roster document (additive fields; no other roster field
  touched; stdlib only).
- `POST /api/candidate/login` (throttled like R1) exchanges name + code
  for a candidate JWT `{role: candidate, sub: name_slug, ver}`. The token is
  long-lived (proposed 180 days; candidates use their own phones) and kept in
  `localStorage` like today's staff tokens.
- A new `require_candidate` dependency on every candidate route derives the
  identity **from the token**. A request for another person's data gets the
  same 404 the code already uses. Roster canonicalization runs unchanged
  after it.
- **Revocation:** "Reset code" in the Coordinator workspace bumps
  `token_version`, logging out every device of that candidate (lost phone,
  shared code).
- **Rollout without breaking live candidates:**
  1. Ship in `optional` mode (`CANDIDATE_AUTH_MODE` env flag): tokens
     accepted and used by the new frontend; unauthenticated requests still
     work but are counted.
  2. Coordinator issues codes; an enrolment column in the Coordinator
     workspace shows who has signed in.
  3. Flip to `required` only after enrolment is confirmed and the new
     frontend has reached all devices (service-worker update banner).
  4. Remove the legacy public campaign reads (S8). Photo GET then requires
     the owner's token or a staff token, with no tokens in URLs. Uploads
     require a candidate token plus a per-person daily quota (S4, S5).
- **Offline safety (verified):** `trySyncOne` keeps a queued activity on
  *any* failure, including 401, so enforcement can never discard offline work.
  The new UI adds "Sign in again to send N pending activities". Tokens
  persist offline.
- **Alternatives rejected:**
  - one shared candidate PIN: no per-person isolation;
  - 4–6 digit personal PINs: low entropy, and lockouts strong enough to stop
    guessing would also lock out real candidates;
  - SMS/WhatsApp OTP: paid service;
  - email magic links: email isn't reliably used by candidates.

**R4 · Individual staff and PHO accounts** — a `staff_accounts` collection
(username, scrypt hash, role ∈ `admin` / `coordinator_leader` / `pho_viewer`,
`token_version`, `disabled`). Shorter token lifetime than today. Accounts are
provisioned by an operator script (no self-signup). `pho_viewer` passes
only a new read-only `require_reader` dependency on leadership GET routes. The
existing PIN logins keep working in parallel until accounts are issued, then
retire.

**R5 · Headers** — `vercel.json`:
- `Content-Security-Policy`, initially allowing inline script and style
  because `index.html` is a single inline file;
- `connect-src` limited to self and the Railway API;
- `frame-ancestors 'none'`, `Referrer-Policy: strict-origin-when-cross-origin`
  and `X-Content-Type-Options: nosniff`.

### 6.5 Security test plan

Pytest per route and mode:
- no token → 401 (required mode) or allowed-and-counted (optional mode);
- another candidate's token → 404;
- own token → unchanged behaviour;
- a token with a stale `token_version` → 401;
- throttling triggers and recovers;
- an audit before-image is written on every candidate PUT/DELETE.

Frontend: a 401 during sync leaves the queue intact; enrolment link handling
strips the fragment. The SmartSheet, campaign, official capture, roster
identity and export suites must stay green throughout.

## 7. Stage 1 prototype — synthetic data policy

- Data is generated by a deterministic, seeded script in the exact shape of
  `/api/leader/dashboard`. It is **never derived from production**.
- It uses Ntsikana's public geography (municipality and ward structure) for
  realism, but **fictional candidate names** and randomly generated counts.
- A persistent "SAMPLE DATA — not actual performance" banner appears on every
  screen, and a caption appears on every chart. Screenshots and exports from
  the prototype carry the same label.

## 8. Dashboard data availability (from the audit)

Data already returned by `/api/leader/dashboard` but never rendered:
`ward_performance`, `needs_attention`, `daily_canvassing`,
`canvassing_trend`, `comparison.participation` (participation is only shown
as subtitle text). These need **no backend change**.

Additive backend work (Stage 3):
- expose `trend_report_weeks` (already powers the trend PDF) as JSON;
- activity-mix aggregation in `leadership_reporting.py`, using the existing
  classifier read-only;
- capture-status aggregates (totals only, no rows) for leadership;
- per-week participation.

## 9. Design direction

Refine the existing tokens rather than replace them (`--navy #153B63`,
`--blue #2568AE`, `--gold #D89B3C`):
- add a cool neutral scale and semantic colours (success, warning, danger,
  info, no data);
- 4px spacing grid; system font stack with tabular numerals for figures;
- extend the in-house SVG chart helpers (bar, horizontal bar, line, stacked
  bar, meter), each with an accessible table fallback;
- candidate screens stay a 480px column; coordinator and leadership screens
  get a wide desktop layout;
- remove `maximum-scale=1` (pinch-zoom); add visible focus styles and
  `aria-live` status.

## 10. Testing protocol (every stage)

- **Suites:** full `python3 -m pytest` plus every `node frontend/*.test.js`.
- **Golden outputs:** for any reporting change, compare dashboard JSON and
  Excel/PDF structure before and after on identical synthetic data.
- **Viewports:** Chrome at 1440, 1024, 390 and 360 px.
  - no horizontal scroll;
  - tap targets ≥44px;
  - keyboard-only pass;
  - 200% zoom.
- **Offline:** DevTools offline: add an activity, confirm it is queued,
  reconnect, confirm it syncs. Bump the service-worker cache version whenever
  shell files change.
- **Data:** local/test MongoDB with synthetic data only. No production
  requests of any kind.
