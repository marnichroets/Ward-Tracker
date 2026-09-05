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

## 3. Campaign Phase Roadmap

### Phase 1 — Campaign backend foundation
**Status: IMPLEMENTED LOCALLY, TESTED, NOT YET DEPLOYED.**

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
Core requirement — recurring scheduling is **not optional**.

- Campaign activities are real `entries` records, never schedule metadata.
- Server-side recurring activity generation: each occurrence gets its own
  individual activity record (never one opaque recurring object).
- Individual occurrence edit/delete works exactly like any normal activity.
- Idempotency/duplicate protection on repeat generation.
- A separate, campaign-scoped date validation path (bounded by the
  campaign's own start/end dates).
- **Do not** weaken the normal `/api/entries` current/next-week rule
  globally — the campaign-scoped path is additive and separate.

### Phase 3 — Candidate campaign UI
- Select roster identity.
- See active campaigns.
- Create a campaign (name, start date, end date only).
- Schedule individual activities within a campaign.
- Schedule recurring activities within a campaign.
- See upcoming campaign activities.
- Simple, mobile-first experience — minimal fields, minimal clicks.

### Phase 4 — Admin campaign dashboard + Official Capture Report
**Official Capture Report is a HARD REQUIREMENT** — not SmartSheet, a
separate report whose purpose is making it fast to transcribe planned/
completed activities into the official system by hand.

At minimum it must expose:
- DATE
- START TIME
- END TIME
- CANDIDATE
- WARD
- CAMPAIGN
- ACTIVITY TYPE
- LOCATION / VENUE
- PROOF / PHOTO STATUS (future)

Report requirements:
- One activity per row.
- Date/week/date-range filtering.
- Optional candidate/campaign/activity-type filters.
- Clean screen optimized for easy copying into the official system.
- Excel export.
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

## 4. Deferred / Not Now

- No photo implementation yet.
- No removal of SmartSheet code yet.
- No new authentication system.
- No historical migrations/backfills.
- No official-system duplication.

## 5. Current Safety Baseline

Accepted production reference as of the last verified backup:

- Activity backup total: **71**
- Cecilia Anne Auld (CLLR): **13** activities, all under
  `cecilia-anne-auld-cllr`
- Kevin activities: **0**
- Roster still requires a fresh final verification before Phase 1
  deployment.

No secrets or Admin PINs are recorded in this file, ever.
