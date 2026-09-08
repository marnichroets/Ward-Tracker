"""One-time admin script to apply the authoritative Amahlathi / Raymond
Mhlaba municipality + ward mapping to the live roster, via the existing
PATCH /api/admin/roster/{id}/assignment endpoint.

Usage:
    ADMIN_PIN=xxxx python scripts_apply_ward_mapping.py --dry-run
    ADMIN_PIN=xxxx python scripts_apply_ward_mapping.py --apply

Never writes historical activities, never deletes anything, never touches
a roster record not explicitly listed below (Jean Lombard and Ernie
Lombard are deliberately untouched — neither appears in either supplied
PR list).
"""
import json
import os
import sys
import urllib.request

BASE = "https://ward-tracker-production.up.railway.app"

# name_slug -> (municipality, [wards] or [] for PR-only/unresolved)
MAPPING = {
    # Raymond Mhlaba
    "andre-van-rayner": ("Raymond Mhlaba", ["Ward 1", "Ward 4", "Ward 5", "Ward 13", "Ward 14", "Ward 16", "Ward 17"]),
    "cecilia-anne-auld-cllr": ("Raymond Mhlaba", ["Ward 10"]),
    "thulani-dasa": ("Raymond Mhlaba", ["Ward 3", "Ward 8", "Ward 19"]),
    # PR list spells this "Mgamelo"; roster spells "Mqamelo" — treated as
    # the same person (unique match, same first+middle name, same
    # municipality) but flagged in the final report as a resolved spelling
    # variant, not silently assumed.
    "busisiwe-yonela-mqamelo": ("Raymond Mhlaba", ["Ward 2", "Ward 6", "Ward 11", "Ward 12", "Ward 15", "Ward 18"]),
    "willem-pieter-bezuidenhout": ("Raymond Mhlaba", ["Ward 7"]),
    "mccayla-verosa-fredericks": ("Raymond Mhlaba", []),
    "willie-de-lange": ("Raymond Mhlaba", []),
    # Yandisa conflict: PR list says "Yandisa Mlamla", Ward 20 source says
    # "Yandisa Mayaya" — NOT merged. Municipality only; no ward assigned.
    "yandisa-mlamla": ("Raymond Mhlaba", []),
    "sthathu-toni": ("Raymond Mhlaba", []),
    "malixole-ncume-cllr": ("Raymond Mhlaba", ["Ward 9"]),
    "singaphi-livingstone-sijako": ("Raymond Mhlaba", ["Ward 21"]),
    # Amahlathi
    "spokazi-elizabeth-mpayipeli-cllr": ("Amahlathi", ["Ward 2", "Ward 3", "Ward 7", "Ward 10", "Ward 11", "Ward 14"]),
    "richard-brennand-pickering-cllr": ("Amahlathi", ["Ward 4"]),
    "mavis-krishi": ("Amahlathi", ["Ward 9"]),
    "thandiwe-nandipha-ncamla": ("Amahlathi", ["Ward 5"]),
    "norah-norinky-toyiya": ("Amahlathi", []),
    "zanobuhle-booi": ("Amahlathi", ["Ward 13"]),
    # Second conflict found while resolving names: the ward source names
    # "Palamente Bayi" for Wards 8 and 12, but the roster/PR list only has
    # "Sandile Helman Bayi" — different first names, no authoritative proof
    # they are the same person. NOT merged; municipality only, no ward.
    "sandile-helman-bayi": ("Amahlathi", []),
    "ndileka-ngxakangxaka-cllr": ("Amahlathi", ["Ward 6"]),
    "lamla-matutu": ("Amahlathi", []),
    "khanyisa-khweleni": ("Amahlathi", []),
    "doneline-ellis": ("Amahlathi", ["Ward 1"]),
}


def api(method, path, token=None, body=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def main():
    dry_run = "--apply" not in sys.argv
    pin = os.environ.get("ADMIN_PIN")
    if not pin:
        print("Set ADMIN_PIN environment variable first.", file=sys.stderr)
        sys.exit(1)

    token = api("POST", "/api/admin/login", body={"pin": pin})["token"]
    roster = api("GET", "/api/admin/roster", token=token)
    by_slug = {doc["name_slug"]: doc for doc in roster}

    missing = [slug for slug in MAPPING if slug not in by_slug]
    if missing:
        print("WARNING: not found in live roster, skipping:", missing)

    for slug, (municipality, wards) in MAPPING.items():
        doc = by_slug.get(slug)
        if not doc:
            continue
        roster_id = doc["id"]
        current_wards = doc.get("actual_wards") or []
        current_municipality = doc.get("municipality") or ""
        action = "SET" if dry_run else "APPLYING"
        print(f"{action} {doc['name']!r} ({slug}): municipality {current_municipality!r} -> {municipality!r}, "
              f"wards {current_wards} -> {wards}")
        if not dry_run:
            api(
                "PATCH", f"/api/admin/roster/{roster_id}/assignment", token=token,
                body={"municipality": municipality, "actual_wards": wards},
            )

    print()
    print("Dry run only — pass --apply to write these changes." if dry_run else "Applied.")


if __name__ == "__main__":
    main()
