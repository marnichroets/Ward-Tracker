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
**Status: IMPLEMENTED, awaiting review before deploy.**

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

### Phase 4 — Admin campaign dashboard + Official Capture Workspace
**The Official Capture Workspace is a HARD REQUIREMENT** — not SmartSheet,
a separate coordinator screen designed around the coordinator's actual job
(Candidates → Ward Tracker → coordinator → official Campaign Manager),
whose purpose is making it fast to transcribe planned/completed activities
by hand, without opening multiple screens or contacting the candidate for
missing information.

Each row must make immediately visible:
- DATE, START, END
- CANDIDATE, WARD, CAMPAIGN (if any)
- OFFICIAL ACTIVITY TYPE (mapped/overridable, or "Official type needs
  confirmation" — see §4)
- LOCATION / VENUE (candidate-entered text — see §4)
- CAPTURE STATUS (Awaiting Capture / Captured — see §4)

Workspace requirements:
- One activity per row, chronological by default.
- Awaiting-capture count and captured count shown up top.
- Filters: candidate, date/date-range, campaign, official activity type,
  capture status.
- Mark Captured / **Undo** (see §4 for `captured_at` handling on undo).
- "Copy details" per row (plain-text summary to clipboard) if it fits
  without cluttering the UI.
- Excel export of the workspace view, added alongside (not replacing) the
  existing SmartSheet/raw exports.
- Activities without a campaign (`campaign_id == null`) must still appear.
- Must derive from normal activity + campaign records — no duplicated
  reporting database.

Campaign admin view should later show: campaign name, candidate, start/end
dates, duration, activity count, upcoming activities, past/completed
activities, week-by-week coverage, and linked activities chronologically.

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
coordinator can choose the correct type from the complete official list and
persist that choice per activity (stored on `entries.official_activity_type`
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

## 6. Current Safety Baseline

Accepted production reference, confirmed post-Phase-1-deploy and
reconfirmed post-Phase-2-deploy (both deploys: 0 IDs added, 0 removed):

- Activity total: **71** (unchanged across both deploys)
- Cecilia Anne Auld (CLLR): **13** activities, all under
  `cecilia-anne-auld-cllr` — single canonical identity confirmed
- Kevin activities: **0** (confirmed still deleted)
- Roster: **26** entries, confirmed via post-deploy backup

No secrets or Admin PINs are recorded in this file, ever.
