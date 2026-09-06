# CLAUDE.md — Ward Tracker

Project memory for Claude Code. Read this before making changes; it encodes
architecture, safety rules, and boundaries this repo has already settled on.
For deep design history/rationale, see `CAMPAIGNS.md`.

## Project

**Ward Tracker** — a candidate activity-tracking and coordinator reporting
tool.

- Production frontend: https://ward-tracker.vercel.app
- Production backend: https://ward-tracker-production.up.railway.app
- Current production baseline: **Phase 5** deployed at commit
  `90400fb76051cf2a9323b52697b1fa9abb2b70a1`. Update this line only after a
  new phase's deployment is approved and completed — never speculatively.

## Architecture

- **Backend**: FastAPI (single file, `main.py`), MongoDB via Motor
  (`motor.motor_asyncio`), JWT for the admin/coordinator session token.
  Supporting modules: `week_dates.py` (Monday–Sunday week-key model),
  `smartsheet_reporting.py` (SmartSheet classification/export — see hard
  boundary below, and do not add unrelated logic to it), `official_capture.py`
  (Official Capture Workspace), `activity_validation.py` (small, neutral
  candidate-activity validation helpers shared by `main.py` — created in
  Phase 5.1 specifically so this kind of logic never has to live inside the
  SmartSheet module just because it also touches venue/ward text).
- **Frontend**: a single static file, `frontend/index.html` — vanilla JS,
  no framework, no build step, no bundler. All screens are `<div class="screen">`
  blocks toggled via a `show(id)` helper; state lives in top-level `let`
  globals (`personId`, `personWard`, `activeCampaign`, etc.), not a
  framework store. Frontend tests are plain Node scripts under `frontend/*.test.js`
  (no test runner/framework) that extract real functions/handler bodies out
  of `index.html` via string search and execute them against a tiny DOM/
  network stub — run each with `node frontend/<name>.test.js`.
- **Deployment**: Vercel (frontend), Railway (backend). No other production
  services exist for this project.

## Core workflow

Candidate selects their **roster identity** (never free-text)
→ candidate logs an ordinary activity, or starts/joins a **campaign**
→ candidate enters a specific **Location / Venue** (ward is automatic)
→ coordinator reviews in the **Official Capture** workspace
→ coordinator manually transcribes the activity into the official Campaign
  Manager (an external system this app never talks to)
→ coordinator marks it **Captured** in Ward Tracker.

## Campaigns

- A campaign is a container/programme (name + date range), not an activity
  itself — it is never counted as one.
- Ordinary (non-campaign) activities are a fully independent, always-legal
  path; campaigns don't replace them.
- Campaign activities (single or recurring-weekly) are materialized as
  normal `entries` documents with a `campaign_id` — indistinguishable in
  shape from a plain activity anywhere they're displayed or exported.
- Max campaign duration: 42 calendar days inclusive (`MAX_CAMPAIGN_DAYS` in
  `week_dates.py`).
- An archived campaign is frozen from every candidate mutation (new
  activities, edits, campaign edits) but stays fully readable everywhere.
- Historical campaign data is never cascade-deleted.

## Identity

- Roster-only identity. `resolve_and_canonicalize_person` (main.py) is the
  single enforcement point: it looks up the roster by slugified name and
  **overwrites** whatever name/ward/person_id the client sent with the
  roster's canonical values — for every entry create/update, regardless of
  caller. Campaign creation/activities re-resolve the same way via
  `resolve_campaign_person_id`/`require_roster_person`.
- An arbitrary/typed name that isn't an exact roster match is rejected
  (400), never silently accepted as a new identity.
- Do not reintroduce free-text identity for any candidate-facing flow.

## Ward / Location

- **Ward** always comes from the canonical roster record — the backend
  ignores any ward the client supplies and substitutes the roster's own
  value (see Identity above). The frontend shows it as read-only context
  (`fWard`/`fWardField` on screenAdd); it is never a second source of truth
  and never independently editable.
  - **UI label vs. data model**: the candidate-facing label is
    **"Municipality"** (changed from "Ward" in the 5.1.1 correction) because
    that's what the field is actually used for — some roster entries hold a
    ward number, others a municipality name. The underlying field/column,
    Pydantic field name, and every variable/function name (`ward`,
    `RosterIn.ward`, `location_is_ward_only`, etc.) are deliberately
    unchanged — this was a wording-only correction, not a schema change.
  - An admin can correct one candidate's roster ward/municipality text via
    `PATCH /api/admin/roster/{roster_id}` (`update_roster_ward` in
    `main.py`) — it updates only that document's `ward` field, never
    name/name_slug/_id, and never touches any already-stored activity
    (each activity keeps its own `ward` text copy from submission time).
    Use this instead of delete+recreate for a roster correction — deleting
    and re-adding risks a window where the candidate is briefly "not on the
    roster" and never preserves the original `_id`.
- Some roster entries intentionally have a **blank ward** (demo accounts) —
  this must never block activity creation. Only the Location/Venue
  requirement below is unconditional.
- **Location / Venue** (the `venue` field) is candidate-typed free text —
  deliberately no GPS, no coordinates, no map dependency. It is **required
  for every new activity** (ordinary, campaign, and recurring campaign) but
  the requirement never applies retroactively:
  - A brand-new activity with a blank venue is rejected, both frontend
    (`isNewEntry` checks in `frontend/index.html`) and backend
    (`entry_doc_from_body`/`campaign_activity_base_doc` in `main.py`, only
    on the `existing_doc is None` / create path).
  - Editing an existing activity — including one with a historical blank
    venue — is never newly blocked by this rule. Historical blank venues
    are never rewritten, backfilled, or migrated.
  - A location that just restates the ward ("Ward 13", "ward 13", "13" for
    a ward literally named "Ward 13"; or an exact municipality name like
    "Amahlathi"/"Raymond Mhlaba") is rejected as not a real place —
    `location_is_ward_only()` in `activity_validation.py` (deliberately kept
    out of `smartsheet_reporting.py` — see the SmartSheet hard boundary
    below), mirrored in JS as `isWardOnlyLocation()`. This is a **conservative, exact,
    case-insensitive match only** — never fuzzy. A location that merely
    *mentions* the ward ("Mlungisi Community Hall, Ward 13") must always be
    allowed.
  - Do not invent a ward-normalization migration or rewrite historical ward
    values — roster wards may be a simple "Ward 13" or a broader
    municipality-style name; both are valid as-is.

## Official Capture

Statuses are exactly `awaiting_capture` / `captured` — no others.

- The workspace always shows candidate, ward, and location/venue as
  **separate** fields — never merge ward and location, never add GPS.
- If a candidate edits meaningful official-relevant data (date, start/end
  time, venue, or the Ward Tracker activity type) on an already-Captured
  activity, it reopens: `capture_status` resets to `awaiting_capture`,
  `captured_at` clears, and if the activity *type* changed,
  `official_activity_type` also clears (the coordinator must reconfirm). A
  notes-only edit, or a PUT that resubmits identical values, never disturbs
  a captured activity. See `_apply_post_capture_edit_reset` in `main.py`.
- An activity cannot be marked Captured while its official type is
  unresolved.

## Official activity type mapping

`official_capture.py` maps Ward Tracker activity text to the official
Campaign Manager's type list: **46** official types total, **17** confident
targets reached via **19** known source-text variants; everything else
needs coordinator confirmation ("Needs Review"). Do not silently expand
this mapping table as a side effect of unrelated work.

## SmartSheet — hard boundary

`smartsheet_reporting.py` and its 3-sheet workbook export
(Canvassing / Public-Street / Presence, plus the Needs Review flow) are a
**separate, frozen format** consumed outside this app. `smartsheet_reporting.py`
must contain SmartSheet classification/export logic **only** — never grow
into a general home for shared candidate-activity logic (venue/ward
validation, general reporting helpers, etc.) just because it happens to
also touch those fields; put genuinely shared, SmartSheet-unrelated logic
in its own small neutral module (e.g. `activity_validation.py`) or privately
in `main.py` instead. Do not:
- edit `smartsheet_reporting.py` casually, change its category mappings,
  headers, or sheet structure, or add unrelated helpers to it,
- let unrelated reporting work (e.g. the general admin workbook) import
  from or write to it,
- break `tests/test_smartsheet_reporting.py` / `tests/test_api_smartsheet.py`'s
  SmartSheet coverage — it must stay green.

The **general admin** workbook (`/api/admin/export.xlsx`, built in
`main.py`) is a completely separate export and is where additive,
non-SmartSheet reporting features (e.g. the Phase 5.1 "Weekly Overview"
trend sheet) belong.

## Data safety

- No destructive migration without explicit approval; no mass rewrite of
  historical activities.
- No production test records, no roster/campaign edits, no captured-status
  changes, and no deletion during verification — real candidates may be
  using production while development happens in parallel.
- Take read-only pre/post snapshots around deploys (see `backups/`).
- Never send POST/PUT/PATCH/DELETE to production while implementing or
  verifying a change — local tests only.

## Do not build without an explicit request

GPS/maps, photos, VRM, AI features, notifications, browser automation,
automatic Campaign Manager submission, a new candidate auth system, complex
analytics/dashboards, or new capture-workflow states beyond
awaiting_capture/captured.

## Testing

- Backend: `python3 -m pytest` — always run the complete suite, not just
  targeted tests. Current baseline: see the most recent phase's
  implementation report for the passing count (grows as phases add tests).
- Frontend: `node frontend/<name>.test.js` for each file under `frontend/*.test.js`
  — there is no single runner/`package.json`, so run every file. Keep the
  SmartSheet, campaign, official capture, roster identity, and Excel/report
  suites green on every change.
- Never rely only on targeted tests before calling a change complete.

## Deployment

- Existing Railway project/service and existing Vercel project only — never
  create replacement production services.
- No production mutation for verification purposes.
