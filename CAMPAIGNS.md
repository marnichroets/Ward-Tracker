# Campaigns — Roadmap & Design Reference

Single source of truth for the Campaign feature. Update this file as each
phase lands — it should always reflect what's actually implemented, not just
what's planned.

## 1. Purpose

Ward Tracker is the **planning and activity-preparation tool**. A separate
official system remains the final reporting/capture system of record.

Ward Tracker must make it easy to transfer activity information into that
official system — it must never duplicate or replace it.

## 2. Core Data Principles

- A campaign is a container/programme, not an activity.
- Individually scheduled activities remain normal `entries` records.
- `entries.campaign_id` is nullable.
- Historical activities remain untouched.
- Normal activities do not require a campaign.
- Never cascade-delete linked activities.
- Campaign ownership (`person_id`) is immutable after creation.
- Campaigns can be any length from 1 calendar day up to 42 calendar days
  inclusive (`duration_days = (end - start).days + 1`, `1 <= duration_days <= 42`).
- SAST date handling remains authoritative for all date logic.
- Existing roster canonicalization remains authoritative for all identity.
- Existing SmartSheet/export functionality stays in place until deliberately
  retired later.
- Do not rewrite historical IDs or records.
- New per-activity fields (official activity type, capture status) are
  additive and nullable/defaulted exactly like `campaign_id` — no historical
  document is ever rewritten to add them.
- Location is candidate-entered free text (the existing `venue` field) —
  no coordinates, no GPS, no map dependency. Historical activities with a
  blank venue are never rewritten or backfilled.
- Official activity type mapping is a display/reporting layer only — it
  never renames or reclassifies the existing `type`/`type_display`/
  `smartsheet_category` fields that the SmartSheet export already depends
  on.

## 3. Campaign Phase Roadmap

### Phase 1 — Campaign backend foundation
**Status: CLOSED — deployed to production and verified.**

Production verification (post-deploy):
- Activity count unchanged: 71 before, 71 after (0 IDs added, 0 removed).
- Roster unchanged: 26 entries.
- Kevin: 0 activities (confirmed still deleted).
- Cecilia Anne Auld (CLLR): single canonical identity confirmed
  (`cecilia-anne-auld-cllr`).

- New `campaigns` collection (`person_id`, `name`, `start_date`, `end_date`,
  `created_at`, `archived_at`).
- Campaign CRUD + archive: `POST/GET/PUT /api/campaigns[/{id}]`,
  `PATCH /api/campaigns/{id}/archive`, optional `DELETE /api/campaigns/{id}`
  (409 if any activity references it — never a cascade).
- Person-scoped ownership checks on every mutation route (update/archive/
  delete), reusing the existing roster canonicalization principle — a
  different roster identity gets 404, not a data change.
- Ownership (`person_id`) is structurally immutable after creation — the
  update path never accepts a new owner.
- Status (`planned`/`active`/`completed`/`archived`) is derived from dates
  at read time, never stored, except the manual `archived_at` flag.
- Max 42 inclusive calendar days enforced explicitly (see Core Data
  Principles above).
- No cascade delete from campaign → entries, anywhere.
- `entries.campaign_id: Optional[str] = None` added to the admin-facing
  model only, for forward compatibility — no historical document rewritten,
  no endpoint sets it yet.
- No frontend changes yet.
- No campaign-activity linking or generation yet (that's Phase 2).
- 164 tests passing (full suite, including regression coverage for roster
  identity, legacy/custom Other handling, exports, and the unmodified
  `/api/entries` write window).

### Phase 2 — Campaign-linked activities + recurring scheduling
**Status: CLOSED — deployed to production and verified.**

Production verification (post-deploy): activity count unchanged (71 before,
71 after — 0 IDs added, 0 removed), roster unchanged (26 entries), no
production activity or roster data modified during deployment.

Core requirement — recurring scheduling is **not optional**.

- Campaign activities are real `entries` records, never schedule metadata.
- Server-side recurring activity generation: each occurrence gets its own
  individual activity record (never one opaque recurring object).
- Individual occurrence edit/delete works exactly like any normal activity
  (unmodified `PUT`/`DELETE /api/entries/{id}`).
- **Idempotency key is `(recurrence_id, activity_date)`, not
  `(campaign_id, activity_date, type)`.** `recurrence_id` is a deterministic
  hash of the repeat request's meaningful content (campaign, weekday, first
  occurrence date, until, type, time, venue) — a byte-for-byte identical
  retry recomputes the same `recurrence_id` and is skipped as a duplicate;
  two independently-created activities that merely share a type and date
  (different time, venue, or a separate recurring series) get different
  hashes and are both allowed. Enforced with an application-level
  pre-check plus a MongoDB **partial unique index** on
  `(recurrence_id, activity_date)` — partial so it only applies to
  documents that actually have a `recurrence_id`, leaving every existing
  and future non-recurring activity untouched.
- A separate, campaign-scoped date validation path (bounded by the
  campaign's own start/end dates) — never the candidate week-key rule.
- **Do not** weaken the normal `/api/entries` current/next-week rule
  globally — the campaign-scoped path is additive and separate.

### Phase 3 — Candidate campaign UI
**Status: CLOSED — deployed to production and verified.**

Production verification (post-deploy): live frontend confirmed byte-identical
to the deployed commit; roster/campaigns endpoints confirmed live and
read-only-verified; no GPS/geolocation code present; Location/Venue label,
placeholder, and helper text confirmed correct in production.

- Select roster identity.
- See active campaigns (planned/active only; completed/archived sit behind
  a "View past campaigns" toggle so the home screen stays uncluttered).
- Create a campaign (name, start date, end date only; 1–42 inclusive
  calendar days enforced client-side to match the backend rule exactly).
- Schedule individual activities within a campaign, using the Phase 2
  single-activity endpoint (never `/api/entries` for a new campaign
  activity).
- Schedule recurring activities within a campaign via a "Repeat weekly"
  checkbox — the weekday is derived from the selected date, never asked of
  the candidate; uses the Phase 2 repeat endpoint.
- See upcoming/scheduled campaign activities in chronological order, with
  date, activity type, start/end time, and venue visible per row — never
  recurrence IDs, database IDs, SmartSheet categories, or any other
  admin-only field.
- Archived campaigns remain viewable (campaign header + its activities),
  clearly labelled "Archived", with no Add Activity or Repeat option.
- Still allow ordinary non-campaign activity submission, completely
  unchanged (same form, same `/api/entries` endpoint, same current/
  next-week rule).
- Location is the existing `venue` field, relabelled "Location / Venue *"
  with a placeholder example and short helper text — see §4 below. No GPS,
  coordinates, or map dependency of any kind.
- Simple, mobile-first experience — minimal fields, minimal clicks. The
  ordinary candidate flow stays approximately: Name → Activity → Date →
  Start time → End time → Location / Venue → Submit. Campaign context adds
  at most: Campaign, Repeat weekly (+ Repeat until when checked). No
  administrative concepts (capture status, official type list, recurrence
  IDs, etc.) are ever shown to candidates.

### Phase 4 — Official Capture Workspace
**Status: IMPLEMENTED, awaiting review before deploy.**

**The Official Capture Workspace is a HARD REQUIREMENT** — not SmartSheet,
a separate coordinator screen designed around the coordinator's actual job
(Candidates → Ward Tracker → coordinator → official Campaign Manager),
whose purpose is making it fast to transcribe planned/completed activities
by hand, without opening multiple screens or contacting the candidate for
missing information. No automation of the official Campaign Manager website
itself is part of this phase — the coordinator still does that step by hand.

- New, completely isolated `official_capture.py` module — never imports
  `CANONICAL_ACTIVITY_CATEGORY`/`classify_activity_text`/any SmartSheet
  bucketing concept, and `smartsheet_reporting.py` is untouched by this
  phase (only its generic, classification-free `spreadsheet_safe_text`
  injection guard is reused for the new export, deliberately, per this
  section's own instruction — not a violation of the boundary).
- Admin-only workspace inside the existing coordinator screen (`screenAdmin`,
  PIN + JWT auth, same `require_admin` dependency as every other admin
  route — no second auth system). Candidates never see any of this.
- Each row: DATE, START, END, CANDIDATE, WARD, CAMPAIGN (or "—" when
  `campaign_id` is null), WARD TRACKER ACTIVITY (untouched original
  `type_display`), OFFICIAL ACTIVITY TYPE (resolved suggestion/override, or
  "Official type needs confirmation"), LOCATION / VENUE, CAPTURE STATUS.
  No Mongo IDs or other technical fields are ever rendered as visible text.
- Top-of-workspace counts (Awaiting Capture / Captured / Total) are always
  computed over the *full* dataset, independent of the active filters.
- Default view: Status = Awaiting Capture, oldest-activity-first ordering.
  Filtering for on-screen display happens client-side against one fetched
  dataset (`GET /api/admin/official-capture`, no query params) — consistent
  with how every other admin panel in this app already works. The Excel
  export (`GET /api/admin/official-capture/export.xlsx`) accepts the same
  filter values as query params (`status`, `person_id`, `campaign_id`,
  `official_activity_type`, `date_from`, `date_to`) and re-applies them
  server-side via the same `official_capture.filter_entries` predicate, so
  the exported file always matches what's on screen.
- Mark Captured / Undo Capture: `PATCH /api/admin/entries/{entry_id}/capture`
  — one endpoint, admin-protected, supports confirming/changing
  `official_activity_type` and/or changing `capture_status` in the same
  call. `captured_at` is always server-generated (`datetime.now(UTC)`); the
  request body has no `captured_at` field at all, so a client value cannot
  even be supplied, let alone trusted. Undo clears it back to `null`.
  Exactly two states exist — `awaiting_capture` / `captured` — no Draft/
  Processing/Approved/Submitted/Failed/Reviewed states were added.
- "Copy Details" is a per-row clipboard action, entirely client-side (no
  backend round trip) — built from already-fetched, already-clean display
  fields; never includes Mongo IDs, `person_id`, `campaign_id`,
  `recurrence_id`, or SmartSheet-internal fields. Omits the Campaign line
  entirely (not a dash) when there is no campaign.
- Excel export: new columns (DATE, START TIME, END TIME, CANDIDATE, WARD,
  CAMPAIGN, WARD TRACKER ACTIVITY, OFFICIAL ACTIVITY TYPE, LOCATION / VENUE,
  CAPTURE STATUS, CAPTURED AT), no macros/formulas/merged cells, added
  alongside (never replacing) the existing SmartSheet/raw exports.
  Candidate-controlled free text (candidate name, ward, campaign name,
  activity, venue) passes through the existing `spreadsheet_safe_text`
  guard — reused, not duplicated. Campaign name is included because
  candidates can name their own campaigns (Phase 3) and is therefore
  untrusted free text too, sanitized the same way.
- Activities without a campaign still appear (`campaign_name: null`,
  rendered as "—"). Campaign names are resolved live, per request, from
  `campaigns_col` by `campaign_id` — never backfilled onto the entry
  document.
- Derives entirely from `entries_col` + `campaigns_col` at read time — no
  duplicated reporting collection, no new Mongo index required (dataset is
  small; a full collection scan per admin request is consistent with every
  existing admin/report/SmartSheet endpoint).

**Resolved — full official list obtained:** an earlier draft of this phase
flagged that only the confidently-mapped examples were documented, with no
complete Campaign Manager type enumeration available. The coordinator has
since supplied the full known official Campaign Manager activity list — 46
types — now `official_capture.OFFICIAL_ACTIVITY_TYPES`. Two separate lists
exist deliberately:
- The full 46-type list drives the admin dropdown and all server-side
  validation of a manual override — a coordinator can confirm **any**
  Ward Tracker activity, confidently-mapped or not, as **any** of the 46
  types.
- The narrower confident-mapping table (19 Ward Tracker source variants →
  17 unique targets, all 17 confirmed to be a subset of the full 46) drives
  *only* the automatic suggestion — an ambiguous/unmapped activity (e.g.
  "Street Meeting", "Sports day", "Social Media") gets no suggestion at all
  ("Official type needs confirmation"), never a guess from the larger list,
  but the coordinator can still manually choose any of the 46 for it.

Campaign admin view (campaign name, candidate, start/end dates, duration,
activity count, upcoming/past activities, week-by-week coverage) remains
future work — not part of this phase.

### Phase 5 — Optional proof/photo support
- Optional only — never required to save an activity.
- No photo storage implementation until a storage/security design is
  separately approved (no object storage exists in this stack today).

## 4. Location, Official Activity Type & Capture Status (additive, cross-cutting)

These apply to activity records generally (campaign-linked or not) and are
introduced alongside Phases 2–4 (schema/backend as each phase needs them;
Phase 2 itself adds none of these three — see the Phase 2 section above).

### Location — candidate-entered text, deliberately not coordinates

**Decision (Phase 3): location is the existing `venue` field, typed by the
candidate — no GPS, no coordinates, no map/geocoding dependency of any
kind.** An earlier draft of this phase explored `location_lat`/
`location_lng`/`location_source` fields captured via the browser's native
Geolocation API. That entire approach was deliberately dropped before
implementation to keep the candidate workflow as simple as possible — no
permission prompts, no "current vs. planned location" distinction, no
coordinate-privacy design to get right. It was never deployed and no
schema field for it exists anywhere in this codebase.

The chosen approach instead:
- `venue` (the existing field, unchanged in the database) is relabelled
  in the UI as **"Location / Venue \*"**, with a placeholder example
  ("Mlungisi Community Hall, Ward 13") and helper text ("Enter where this
  activity will take place.").
- **Required for new activities** (client-side, matching the existing
  required-venue rule the plain activity form already had) — both for
  ordinary and campaign-linked activity creation.
- Historical activities with a blank venue are never rewritten, backfilled,
  or otherwise touched — the requirement applies going forward only.
- The Official Capture Workspace (Phase 4) shows this text directly as
  LOCATION / VENUE — there is no separate "location completeness" concept,
  no coordinates, and no "Open Location" map-link action.
- If a future need for an actual map pin re-emerges, treat it as a new,
  separately-approved decision — not an assumed extension of this phase.
  The safest lightweight option at that point would remain Leaflet +
  OpenStreetMap (no API key at this scale) rather than Google Maps, per
  the same reasoning as before, but nothing here commits to building it.

### Official activity type mapping

A new, separate mapping table (`official_capture.py` — Ward Tracker
canonical activity → official Campaign Manager type) drives a *suggested*
`official_activity_type`. Confident mappings are suggested automatically;
anything ambiguous or unmapped shows **"Official type needs confirmation"**
in the capture workspace — the mapping layer never silently guesses. The
coordinator can choose any type from the full 46-type official list (see
"Resolved — full official list obtained" under Phase 4 above) and persist
that choice per activity (stored on
`entries.official_activity_type`
once confirmed/overridden — mirrors the existing `smartsheet_category`/
`category_source` automatic-vs-admin-review pattern). The mapping table
never touches `CANONICAL_ACTIVITY_CATEGORY`, `classify_activity_text`, or
any SmartSheet bucketing logic — historical activities are never renamed or
reclassified. Roughly a third of Ward Tracker's current activity list maps
confidently; several (e.g. the DA-specific "Rescue Event" family,
"Fundraiser", "Women Safety") have no official equivalent and stay
"needs confirmation" until the coordinator classifies them. The
candidate-facing activity dropdown is **not** being expanded to match the
full official list in this pass — that is an open decision for later, not
assumed.

### Capture status — explicit, not purely computed

- New activities explicitly get `entries.capture_status = "awaiting_capture"`
  at creation time (not left to a computed default).
- Historical activities safely resolve to "Awaiting Capture" on read
  without any document being rewritten.
- Coordinator actions: **Mark Captured** sets `capture_status = "captured"`
  and `captured_at` to now; **Undo** sets `capture_status` back to
  `"awaiting_capture"` and clears `captured_at` to `null` — mistakes are
  always reversible, and `captured_at` never holds a stale value after an
  undo.
- Admin-only field and mutation; candidates never see it, exactly like the
  existing SmartSheet metadata is excluded from candidate-facing responses.

## 5. Deferred / Not Now

- No photo implementation yet.
- No removal of SmartSheet code yet.
- No new authentication system.
- No historical migrations/backfills.
- No official-system duplication.
- No GPS/coordinates/map/geocoding dependency of any kind — location stays
  candidate-typed text (see §4); this was explicitly decided against, not
  merely postponed.
- No expansion of the candidate-facing activity dropdown to the full
  official type list yet (see §4) — a separate future decision.
- No vehicle registration mark (VRM) field of any kind, anywhere.
- No automated submission to the official Campaign Manager website — Phase 4
  is a transcription aid only; the coordinator still enters data there by
  hand.

Phase 4 explicitly re-confirms all of the above still holds: GPS,
coordinates, maps, and VRM remain fully removed (never added); photos remain
deferred to a future, separately-approved phase; SmartSheet stays a
completely separate, untouched system (own file, own categories, own
exports); and no automatic Campaign Manager submission was built.

## 6. Current Safety Baseline

Accepted production reference, confirmed post-Phase-1-deploy and
reconfirmed post-Phase-2-deploy (both deploys: 0 IDs added, 0 removed):

- Activity total: **71** (unchanged across both deploys)
- Cecilia Anne Auld (CLLR): **13** activities, all under
  `cecilia-anne-auld-cllr` — single canonical identity confirmed
- Kevin activities: **0** (confirmed still deleted)
- Roster: **26** entries, confirmed via post-deploy backup

No secrets or Admin PINs are recorded in this file, ever.
