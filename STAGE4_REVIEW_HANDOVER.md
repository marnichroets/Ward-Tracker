# Ward Tracker — Stage 4 review corrections (development only)

**Starting source:** committed `dev/pho-premium-upgrade` Stage 4 archive supplied by the project owner. This package does not change the running app, the MongoDB database, the candidate roster, councillor allocations, or production infrastructure.

## What changed

- Coordinator opens in a **read-only Activities** list with reporting-week and search filters. Campaigns tab shows a **read-only submitted-campaign overview**. Hidden legacy manual capture controls are no longer presented or invoked.
- Leadership dashboard and reporting UI no longer show Official Capture percentages, waiting queues, or manual capture status.
- Weekly PDF and enhanced leadership Excel now present **date-based activity timing** instead of manual Campaign Manager capture status. The original five leadership workbook sheets, frozen Smartsheet exports and database capture fields remain for compatibility.
- Meeting Pack PDF/PowerPoint and preview still share an eight-slide layout. Candidate rankings are replaced by participation coverage and activity mix; Official Capture is replaced by a completed-vs-planned activity slide. Completed here means **activity date has been reached**, not independent verification of attendance or execution.
- Historical ward status only considers activities occurring **before the selected reporting period**; it no longer looks ahead at later records. Unobserved comparison periods show **No comparison available**. Periods consisting only of future plans use planning language, without premature performance judgments.
- Upcoming items and campaign status are clearly labelled as a **Current planning update, as of the report generation date**, including when reviewing an old historical period.
- Bumped frontend offline-shell cache version to v37. API calls continue bypassing the service-worker cache.
- Replaced legacy Stage 4 test assertions with the revised reporting contract, added synthetic no-database regression tests and updated the parity-checking tool.

## Compatibility and caveats

- No destructive migration, database or roster changes. Legacy capture routes, flags, and hidden compatibility markup are **retained but not used in the updated coordinator and leadership screens**. A future security/maintenance stage may retire them fully after a dependency audit.
- No production deployment, merging, or GitHub push was performed. Test with the local synthetic server first.
- The original offline duplicate-rejection issue remains a **pre-production blocker**. Full role-based access controls, backup/recovery testing and privacy review remain required before PHO rollout.
- The supplied code archive deliberately contains no `.git` folder. Preserve your local repository history by applying the `.patch` file instead of replacing the entire checkout.

## Tests performed in the review environment

- `node --test frontend/*.test.js`: **19/19 frontend files passed**.
- `PYTHONPATH=tests:. python -m pytest -q tests/test_stage4_review.py tests/test_leadership_reporting.py -k 'not API'`: **68 passed, 3 skipped, 26 deselected** (plus four subtests).
- Additional synthetic PDF/PPTX generation for completed, in-progress, future and historical periods: **8 pages and 8 editable PowerPoint slides per sample**. No manual-capture or candidate-ranking wording appeared in those PDFs.
- Full backend suite and full golden output comparisons could **not** run here because the environment lacks `bson`/`pymongo`/`motor` and has no network access to install them. These must be run in the normal Windows development environment before treating the changes as verified.

## Owner's next action

1. Verify `git status` is clean and that you are on `dev/pho-premium-upgrade` in `C:\Users\user\Desktop\Ward-Tracker-Latest`.
2. From PowerShell, validate with `git apply --check <path-to-patch>` before applying it with `git apply <path-to-patch>`.
3. Run your standard full Python + frontend suites, golden comparison on synthetic data, and local mobile/desktop UI checks. Check sample Meeting Packs for the seven standard periods.
4. Review before committing. Do not merge/deploy production until independently approved.
