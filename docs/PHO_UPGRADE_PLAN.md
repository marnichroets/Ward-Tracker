# PHO Upgrade Plan — Ward Tracker

Agreed approach for upgrading Ward Tracker into a premium, PHO-ready
operational reporting platform. Keep this file current as each stage lands —
it records what was agreed and what is actually done, not aspirations.

- **Branch:** `dev/pho-premium-upgrade` (cut from clean `main` at `163658b`,
  2026-11-12). All work happens here. Nothing is merged or deployed without
  explicit approval.
- **Status:** Stages 0, 0A, 1, 2 and 2C complete.
  **Stage 3 complete — awaiting review before Stage 4** (§5D).
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
| **2** | Coordinator and candidate experience improvements without altering business logic | All suites green; screenshots reviewed | **Done — awaiting review** (§5B) |
| **3** | Verified reporting capabilities + performance, reusing existing data and infrastructure | Golden-output tests prove existing numbers unchanged | **Done — awaiting review** (§5D) |
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
- **Pre-existing bug — fixed in Stage 2 (§5B):** opening `/#admin` with a saved coordinator
  session always falls back to the PIN prompt — `loadAdmin()` runs during
  boot and assigns `smartsheetReviewOpen`, a `let` declared later in the
  script (temporal dead zone `ReferenceError`). Present on `main`.
- Expired election countdown removal — done in Stage 2 (§5B).
- Stage 3: gzip API responses (Starlette `GZipMiddleware`, no new
  dependency — the 12-week payload is 276 KB uncompressed); compute ward
  attribution once per entry; date-bounded queries.

## 5B. Stage 2 results — coordinator, candidate and dashboard refinements

### What changed
1. **Coordinator workspace** — wide, branded, tabbed: **Official Capture**
   (default, awaiting-count badge), Reports, Campaigns, Candidates & data.
   Replaces the 480px column where capture hid behind a "Manage…" toggle.
   All 71 existing element ids and handlers moved verbatim (script-checked).
   Capture counts up front, filters in one row, the queue as a card grid,
   rendered 24 at a time (oldest first) with "Show more". "Download PDF"
   still prints only the weekly submission report (print-emulation check).
2. **Candidate quick capture** — same fields, validation, payloads and
   save path. Form order Activity → Date → Start/End → Location;
   quick-pick chips for common/recent activities, every day of the
   selectable week and the candidate's own recent places; end time auto-
   filled one hour after the start (never overriding a valid end); Start/
   End side by side; sticky Save; optional helpers/photo folded (auto-open
   when an activity already has them); floating "Add an activity". Recent
   picks are per-device localStorage conveniences only.
3. **Expired election countdown removed** (markup, timer, CSS).
4. **Bug fix (pre-existing on `main`):** `/#admin` with a saved session no
   longer falls back to the PIN prompt (temporal-dead-zone `let`).
   `frontend/boot-order.test.js` guards the general pattern and fails on
   the old code.
5. **Leadership refinements:**
   - *Capture clarity* — every activity is exactly one of **Captured**
     (transcribed), **Waiting** (already happened, not yet captured) or
     **Planned** (future date, can't be captured yet). The headline rate is
     now "of completed activities captured", so planned work no longer drags
     it down. Three-part bar, three drillable counts, a one-line key, and a
     three-series weekly chart. Backend fields (additive):
     `capture_summary.due_total`, `captured_percent_of_due`; weekly
     `awaiting_due`/`planned`; per-row `capture_state` — all reconciled by test.
   - *Less scrolling, nothing hidden* — one-sentence summary on phones;
     sticky jump bar on phones; collapsible municipality ward groups with an
     "N of M active · K need attention" line (open on desktop, closed on
     phones, remembered across re-renders); Reporting names list
     collapsible; mobile activity cards 12 then "Show all"; shorter phone
     charts. Phone dashboard height roughly halved.

### Verification
- Backend **624 passed**, 0 failed (122 subtests) — 10 consecutive clean
  runs. One earlier run reported a single failure while an accidental
  concurrent screenshot job was loading the machine; it did not reproduce
  and its name was not captured.
- Frontend **18/18** files pass (new: `boot-order.test.js`,
  `candidate-quick-capture.test.js`; updated where they encoded superseded
  decisions: `coordinator-reports-ui.test.js` §4, `leader-dashboard.test.js`
  capture/summary/ward assertions).
- Golden check: every pre-existing dashboard value and leadership Excel cell
  identical; only the documented multi-week wording differs.
- Local end-to-end checks: quick-picked activity saved through the real API
  and validation; offline save queued with "Pending"; `/#admin` deep link
  lands on the workspace. No horizontal overflow or console errors at
  1440 / 1024 / 390 / 360 px. Service-worker cache bumped to v33.

## 5C. Stage 2C results — candidate experience refinement

Frontend only (`frontend/index.html`, `frontend/week-dates.js`, `sw.js`); no
backend, payload, validation or data change.

### What changed
1. **Home = two week panels.** *This week* (blue) and *Next week* (gold),
   each with its dates, a count, a Mon–Sun strip showing which days have
   activities, and exactly two actions (Add / Review). An empty week shows
   only Add, and its status in amber ("Nothing planned yet"; on Saturdays
   "…please plan next week by tonight"). Removed: the two reminder cards,
   the This/Next tab switcher, the floating "+ Add an activity", the
   duplicate instructions. Campaigns sit below, compact, as secondary.
   "Done" is now a quiet "I'm done for now" link. Desktop shows both weeks
   side by side.
2. **One-week list screen** (Review) with the week banner, activities in
   date/time order (helpers/photo counts only when present — the repeated
   "No photo evidence recorded / No additional participants" lines are
   gone) and one Add button for that week.
3. **Week is always explicit in the form.** A banner ("Adding to THIS WEEK ·
   9–15 November 2026" / "Planning for NEXT WEEK"), a week tag on "When?",
   day shortcuts that are always that week's seven days, and a Save button
   that names the week ("Save to next week"). Every Add resets the date into
   its own week (no date carried over from a previous form).
4. **Deliberate week change needs confirmation.** The date picker spans the
   two weeks the backend accepts (`validate_candidate_week_key`). A date in
   the other week shows a warning with *Move to next week* (switches the
   form to that week, keeping the date) / *Choose a date this week* (clears
   the date — nothing is picked for the candidate); Save is refused while
   the date contradicts the displayed week or is empty. Venue placeholder
   is the neutral "Enter venue or area". A date outside both weeks is
   explained and refused. Campaign activities keep their campaign's own
   range (with a "· this week" hint under the date).
5. **Form in four sections:** What activity? (chips first, then "Or choose
   from the full list") → When? → Where? → Additional details (campaign
   link, helpers, photo — folded; opens automatically when the activity
   already has any). Save is no longer sticky — it sits after the form with
   errors directly above it; an error now stays visible and scrolls/marks
   the field it is about.
6. **Ward / municipality terminology.** Inspected the data: the roster's
   legacy `ward` text holds a ward ("Ward 1") for single-ward candidates and
   a municipality name for others, while `municipality` and
   `actual_ward(s)` are the authoritative separate fields. The form and the
   sign-in screen now show **Ward** and **Municipality** separately
   (`candidateArea()`), each only when known; multi-ward candidates still
   pick their ward. Display only — the payload still sends the roster
   `ward` text and the backend still resolves the canonical ward.
7. **Save feedback names the real week and day**: "Activity saved — This
   week · Thursday, 12 November", "Activity planned — Next week · …",
   "Changes saved — …". Offline: "Saved on this phone — waiting to sync …
   It has not reached the server yet". After a later sync: "Activities
   saved on this phone have now reached the server." The saved row is
   highlighted (amber while waiting). Campaign saves confirm the day too.

### Verification
- Backend **624 passed**, 0 failed (122 subtests) — unchanged.
- Frontend **18/18** files pass. New regression cases: correct week for
  Add-to-this-week / Add-to-next-week, day shortcuts match the shown week,
  week-change warning + refused save, saved week/day in the feedback, offline
  honesty, editing an existing record (incl. historical blank venue),
  ward/municipality derivation, Back returns to the list it came from.
  Updated where they encoded superseded UI: `activity-form` (Municipality
  label, Back label), `campaign-ui` (date bounds now span both weeks),
  `candidate-quick-capture` (sticky Save), `html-safety` (row moved),
  `roster-selection`, `script-load` (reminder cards removed).
- Local journeys (synthetic server): home → Plan next week → save → lands on
  next week's list with the confirmation and the new row (count 0 → 1);
  week-change refused until confirmed; offline save queued then synced on
  reconnect; edit of an existing record; campaign activity form; no
  horizontal overflow at 1440 / 390 / 360 px; coordinator and leader screens
  unchanged. Service-worker cache bumped to v34.

### Remaining / noted
- Pre-existing: an offline-queued activity that the backend later rejects as
  a *possible duplicate* (409) stays "waiting to sync" indefinitely — the
  queue has no duplicate-review step. Honest, but never resolves on its own.

## 5D. Stage 3 results — verified reporting and performance

### What changed
1. **Golden-output harness** — `devtools/golden_reports.py snapshot OUT.json`
   runs every report endpoint in-process against the deterministic
   synthetic store with "today" frozen (2026-11-12) and records ~95,000
   values: dashboard / ward / campaign JSON for 9 filter scenarios, every
   cell of every Excel export (leadership, admin, official capture,
   SmartSheet, calendar), every CSV row and the text of every PDF.
   `compare OLD NEW` fails on any changed or removed value and lists
   additions. Same isolation as `local_server.py`.
2. **Dashboard speed** (no output change): `build_ward_rows` attributes each
   activity to its ward once instead of once per ward row (it was
   83,770 attributions for 478 activities); the two pure text parsers
   (`actual_ward_from_text`, name-word normalisation) are cached on their
   string input. `build_dashboard` on 478 synthetic activities: **190 → 20 ms**
   (1 week), **357 → 53 ms** (12 weeks).
3. **gzip** — Starlette's built-in `GZipMiddleware` (no new dependency;
   ≥1 KB, level 6, only when the browser sends `Accept-Encoding: gzip`).
   4-week dashboard over HTTP: **144 KB → 11 KB**; 12-week ~311 KB → ~18 KB.
4. **Leadership Excel** — four sheets appended after the original five
   (unchanged): *Official Capture* (captured / waiting / planned / total,
   rate of completed captured, oldest waiting), *Municipality Summary*,
   *Activity Mix*, *12-Week Trend* (incl. capture split and candidates
   reporting per week). All read straight from the dashboard dict; text is
   formula-safe (`safe_cell_text`).
5. **Weekly PDF** — three sections appended before the footer: Official
   Capture Progress, Municipality Summary, Activity Mix (top 10 + "N other
   types"). Existing sections unchanged and in the same order.
6. **Trend PDF** — new *Candidates Reporting* column ("18 / 28"), from
   per-week participation added to `trend_report_weeks` rows using the
   dashboard's own candidate pool and "has logged" rule.
7. **`activity_mix`** added to the dashboard JSON (additive) — same grouping,
   order and half-up rounding as the on-screen Activity mix panel.
8. **Robustness fix (pre-existing):** PDF table cells are XML-escaped, so a
   name/activity containing markup-like text (`<b>`) no longer makes PDF
   generation fail with a 500.
9. Reports page card descriptions mention the new content; service-worker
   cache v35; `devtools/screenshot.mjs` gained `leader-reports-desktop/-phone`.
10. **Reports page Municipality selector (owner decision, 2026-11-13):** the
    weekly Excel and PDF stay constituency-wide. The selector moved from the
    shared top bar into the Activity Trend Report card, labelled
    "Municipality · Trend Report only" with the hint "Only changes this Trend
    Report. The weekly Excel and PDF reports are not affected."; the week
    selector says it is for the weekly reports. Same element ids and
    handlers — no calculation or export contract changed.

### Verification
- Golden: baseline snapshot taken twice before any change — identical
  (95,017 values). After the performance work: **0 changed / 0 removed / 0
  added**. After the report additions: every change is inside the weekly and
  trend PDFs I extended, and a script confirmed each original PDF's full
  text is still present, in order, in the new one (only the footer moved
  down). Every dashboard number, all five original leadership sheets, admin
  exports, Official Capture exports and SmartSheet CSV/XLSX are identical.
- Backend **639 passed**, 0 failed (126 subtests), three consecutive runs —
  15 new in `tests/test_stage3_reporting.py` (grouped ward rows equal a
  per-ward rescan for 4 filters, cached parsers, mix ordering/rounding and
  reconciliation, trend participation = dashboard KPI per week, sheet order
  and reconciliation, PDF section order, markup escaping, gzip on/off/small).
  One existing test updated: the leadership workbook's exact sheet list now
  includes the four appended sheets.
- Frontend **18/18** files pass.
- Local Reports page at 1440 / 390 px: no horizontal overflow; only console
  message is the local server's missing favicon.
- **Compression vs offline/frontend (headless Chrome, local synthetic
  server, service worker active and controlling):** large `/api` responses
  arrive `Content-Encoding: gzip`, `Vary: Origin, Accept-Encoding`; the
  dashboard renders with no page errors; the Excel/PDF files received through
  the app's own download helpers open intact (9 sheets; PDFs parse with the
  new sections). Candidate offline journeys pass: save offline → queued (1) →
  reconnect → synced (0), no errors. By design the service worker never
  touches API responses in production (the API is a different origin — its
  fetch handler returns early) and caches only shell files served by Vercel,
  which this middleware does not affect; the page reads bodies only via
  `json()/text()/blob()` (decoded by the browser) and never `Content-Length`;
  gzip applies to responses only, never to uploads.
- *Local-only quirk noticed (pre-existing, not changed):* under
  `devtools/local_server.py` the API shares the page's origin, so there the
  service worker's stale-while-revalidate branch also serves `/api` GETs.
  Production is unaffected; worth a one-line exclusion in Stage 4.
- Golden harness note: the coordinator workbook's "Generated:" print date uses
  the real clock (`datetime.now`), so `compare` lists such stamps separately
  as ignored print dates rather than report differences.
- Review artifacts (git-ignored): `devtools/artifacts/stage3/` — the three
  synthetic example reports, all golden snapshots and comparison outputs,
  and the browser-received compression-check files.

### Not done (deliberately)
- **Date-bounded Mongo queries** — not worth the risk now: ward status uses
  all-time history ("Needs Attention" vs "No Activity"), the comparison uses
  the previous period and the trend 12 weeks, so a bounded query would change
  numbers unless carefully widened. With the dashboard now ~50 ms, the full
  read is not the bottleneck.
- **Trend JSON endpoint** — no screen consumes it yet.

### 5D.1 PDF presentation pass (2026-11-13, after the Stage 3 quality review)
Presentation only — every figure still comes from the dashboard dict or the
trend rows; Excel, SmartSheet, dashboard JSON and admin exports unchanged.
1. **Weekly PDF fits on two pages** (was three, the last nearly empty):
   compact logo/title header, the week as a seven-day strip instead of a
   seven-row table, slightly tighter table rows (body 9.5 pt), short sections
   kept whole with their heading, and no heading stranded at a page foot.
   "Page N of M" on every page of every leadership PDF.
2. **Trend chart**: x-axis names each week by its Monday ("21 Sep"),
   horizontal, Helvetica 8.5 pt (7.5 pt at 12 weeks) with an axis title
   "Week starting (Monday)"; wider plot, light gridlines, legend above the
   plot. The table keeps the full week ranges. Plotted values are the rows'
   own totals (asserted by test).
3. **Clarity**: every weekly and trend PDF shows "Generated: <weekday, date>"
   (SAST). When the period still has future-dated activities, a tinted note
   explains it and the summary shows *Total (completed + planned)*,
   *Completed (date has passed)* and *Planned (not yet taken place)* using the
   established `capture_summary` definitions (`due_total`,
   `awaiting_upcoming`); canvassing and per-candidate counts are labelled
   "incl. planned"; the day strip marks each day Completed / Today / Planned.
   A not-yet-started week says so. In the trend report the current week reads
   "(in progress)" in the table, "*" on the chart, with a footnote. A finished
   week shows none of this wording.
4. **Activity Mix "N other activity types"** row now shows its share,
   rounded from its combined count with the same half-up rule as every other
   row (`leadership_reporting.activity_mix_with_other`).

Verification: backend **646 passed** (7 new), frontend 18/18. Golden: all
differences are inside the weekly/trend PDFs plus the Wednesday update PDF's
shared header and page number (same figures). A table-level check of the
regenerated PDFs against the original pre-Stage-3 baseline — 7 weekly and 4
trend scenarios — found **0 mismatches in 175 figure checks**. Every page of
the regenerated reports was inspected as an image
(`devtools/artifacts/stage3/`, git-ignored).

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
