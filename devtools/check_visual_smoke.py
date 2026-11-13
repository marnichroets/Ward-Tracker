"""Validate screenshots captured against the isolated synthetic Ward Tracker server.

Run: python devtools/check_visual_smoke.py /tmp/ward-tracker-screens.json
Refuse silent failures: screenshot.mjs captures errors per scenario but exits
successfully so it can finish later screenshots.
"""
import json
import sys
from pathlib import Path


EXPECTED_SCREENS = {
    "landing-phone": "screenWho",
    "landing-desktop": "screenWho",
    "leader-desktop": "screenLeadership",
    "leader-phone": "screenLeadership",
    "leader-small-phone": "screenLeadership",
    "leader-meeting-desktop": "screenLeadership",
    "leader-meeting-phone": "screenLeadership",
    "leader-reports-phone": "screenLeadership",
    "candidate-home-phone": "screenWeek",
    "candidate-home-small-phone": "screenWeek",
    "candidate-add-phone": "screenAdd",
    "candidate-offline-synced-phone": "screenWeekList",
    "coordinator-deeplink": "screenAdmin",
    "coordinator-desktop": "screenAdmin",
    "coordinator-phone": "screenAdmin",
    "coordinator-reports-phone": "screenAdmin",
    "coordinator-data-desktop": "screenAdmin",
}


def validate(path: Path) -> list[str]:
    items = json.loads(path.read_text(encoding="utf-8"))
    issues = []
    present = {item["name"] for item in items}
    for missing in sorted(set(EXPECTED_SCREENS) - present):
        issues.append(f"{missing}: screenshot scenario was not run")
    for item in items:
        name = item["name"]
        if item.get("error"):
            issues.append(f"{name}: {item['error']}")
            continue
        if item.get("activeScreen") != EXPECTED_SCREENS.get(name):
            issues.append(f"{name}: unexpected active screen {item.get('activeScreen')!r} "
                          f"(expected {EXPECTED_SCREENS.get(name)!r})")
        if item.get("horizontalOverflowPx", 1000) > 2:
            issues.append(f"{name}: {item['horizontalOverflowPx']}px horizontal overflow")
        if not item.get("files"):
            issues.append(f"{name}: screenshot not produced")
        errors = item.get("consoleErrors") or []
        if errors:
            issues.append(f"{name}: browser console errors: {errors[:3]}")
    by_name = {item["name"]: item for item in items}
    pack = by_name.get("leader-meeting-desktop", {})
    if not pack.get("error"):
        try:
            data = json.loads(pack.get("actionResult") or "{}")
            if data.get("slides") != 8:
                issues.append(f"leader-meeting-desktop: expected 8 slides, got {data.get('slides')!r}")
        except (TypeError, json.JSONDecodeError) as exc:
            issues.append(f"leader-meeting-desktop: could not parse meeting preview: {exc}")
    offline = by_name.get("candidate-offline-synced-phone", {})
    if not offline.get("error"):
        try:
            data = json.loads(offline.get("actionResult") or "{}")
            if data.get("queuedBefore") != 1 or data.get("queuedAfter") != 0:
                issues.append(f"candidate-offline-synced-phone: sync did not clear queue: {data}")
        except (TypeError, json.JSONDecodeError) as exc:
            issues.append(f"candidate-offline-synced-phone: could not parse sync check: {exc}")
    print(f"Checked {len(items)} synthetic browser scenarios")
    for item in items:
        print(f"  {item['name']}: active={item.get('activeScreen')}, "
              f"overflow={item.get('horizontalOverflowPx')}px, "
              f"screenshots={len(item.get('files', []))}")
    return issues


if __name__ == "__main__":
    found = validate(Path(sys.argv[1]))
    if found:
        print("\nVISUAL SMOKE FAILED:", *found, sep="\n- ", file=sys.stderr)
        sys.exit(1)
    print("Visual smoke checks passed (synthetic local data only)")
