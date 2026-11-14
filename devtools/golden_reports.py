"""Golden-output snapshot of every report this app produces — LOCAL ONLY.

    python devtools/golden_reports.py snapshot OUT.json   # capture outputs
    python devtools/golden_reports.py compare OLD.json NEW.json

Runs the real main.py endpoint functions in-process against the
deterministic synthetic store (devtools/synthetic_data.py) with the app's
SAST "today" frozen, then records every report in a canonical, diffable
form: dashboard/ward/campaign JSON, every Excel cell value, every CSV row
and the text of every PDF. Take a snapshot before a reporting change and
another after it; `compare` fails on any changed or removed value and only
lists additions (new keys, sheets, columns) for review.

Isolation is the same as devtools/local_server.py: MONGO_URI is forced to
an unroutable address and every collection is replaced in memory before
anything runs, so this can never read or write a real database.
"""
import asyncio
import csv
import io
import json
import os
import re
import secrets
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FROZEN_TODAY = date(2026, 11, 12)  # a Thursday: the current week has past, today's and planned activities

os.environ["MONGO_URI"] = "mongodb://127.0.0.1:1/?serverSelectionTimeoutMS=200"
os.environ["DB_NAME"] = "ward_tracker_golden_synthetic"
os.environ["ADMIN_PIN"] = "1111"
os.environ["COORDINATOR_LEADER_PIN"] = "2222"
os.environ["JWT_SECRET"] = secrets.token_hex(32)
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "devtools"))
sys.path.insert(0, str(ROOT / "tests"))

from frozen_clock import freeze_sast_today  # noqa: E402

_clock = freeze_sast_today(FROZEN_TODAY)
_clock.start()

import main  # noqa: E402
from bson import ObjectId  # noqa: E402
from memory_db import MemoryCollection, MemoryDatabase, NoPhotoBucket  # noqa: E402
import synthetic_data  # noqa: E402


def install_store():
    data = synthetic_data.generate(today=FROZEN_TODAY)
    # Deterministic ids, so entry/roster ids in outputs are stable between runs.
    counter = iter(range(1, 1_000_000))
    for name in ("roster", "entries"):
        for doc in data[name]:
            doc["_id"] = ObjectId(f"{next(counter):024x}")
    main.db = MemoryDatabase()
    main.client = None
    main.entries_col = MemoryCollection(data["entries"])
    main.roster_col = MemoryCollection(data["roster"])
    main.campaigns_col = MemoryCollection(data["campaigns"])
    main.activity_audit_col = MemoryCollection()
    main.evidence_bucket = NoPhotoBucket()
    return data


async def body_bytes(response) -> bytes:
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk if isinstance(chunk, bytes) else chunk.encode("utf-8"))
    return b"".join(chunks)


def xlsx_cells(data: bytes) -> dict:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data))
    out = {}
    for ws in wb.worksheets:
        out[ws.title] = {
            "merged": sorted(str(r) for r in ws.merged_cells.ranges),
            "rows": [[None if v is None else str(v) for v in row] for row in ws.iter_rows(values_only=True)],
        }
    out["__sheet_order__"] = wb.sheetnames
    return out


def pdf_text(data: bytes) -> list:
    from pypdf import PdfReader

    return [page.extract_text().splitlines() for page in PdfReader(io.BytesIO(data)).pages]


def csv_rows(data: bytes) -> list:
    return list(csv.reader(io.StringIO(data.decode("utf-8-sig"))))


def jsonable(value):
    return json.loads(json.dumps(value, default=str))


DASHBOARD_SCENARIOS = {
    "this_week": {},
    "last_week": {"preset": "last_week"},
    "next_week": {"preset": "custom", "date_from": "2026-11-16", "date_to": "2026-11-22"},
    "four_weeks": {"preset": "custom", "date_from": "2026-10-19", "date_to": "2026-11-15"},
    "twelve_weeks": {"preset": "custom", "date_from": "2026-08-24", "date_to": "2026-11-15"},
    "amahlathi": {"municipality": "Amahlathi"},
    "raymond_mhlaba_last_week": {"preset": "last_week", "municipality": "Raymond Mhlaba"},
}


async def capture(data: dict) -> dict:
    out: dict = {"frozen_today": FROZEN_TODAY.isoformat(), "dashboard": {}, "leader_xlsx": {}, "leader_pdf": {}}
    leader = dict(preset="this_week", date_from=None, date_to=None, ward=None, person_id=None, municipality=None, _=True)

    first_dashboard = None
    for name, overrides in DASHBOARD_SCENARIOS.items():
        args = {**leader, **overrides}
        dashboard = await main.leader_dashboard(**args)
        first_dashboard = first_dashboard or dashboard
        out["dashboard"][name] = jsonable(dashboard)
        out["leader_xlsx"][name] = xlsx_cells(await body_bytes(await main.leader_export_xlsx(**args)))
        pdf_args = {k: args[k] for k in ("preset", "date_from", "date_to", "municipality")}
        out["leader_pdf"][f"weekly:{name}"] = pdf_text(await body_bytes(await main.leader_weekly_report_pdf(**pdf_args, _=True)))

    # A filtered ward and candidate taken from the data itself.
    ward_row = next(r for r in first_dashboard["ward_performance"] if r["activities"])
    person = first_dashboard["candidate_activity"]["logged"][0]
    for name, overrides in {"ward": {"ward": ward_row["ward_key"]},
                            "person": {"person_id": person["id"]}}.items():
        args = {**leader, **overrides}
        out["dashboard"][name] = jsonable(await main.leader_dashboard(**args))
        out["leader_xlsx"][name] = xlsx_cells(await body_bytes(await main.leader_export_xlsx(**args)))

    out["ward_detail"] = {}
    for row in first_dashboard["ward_performance"][:4]:
        key = row["ward_key"]
        out["ward_detail"][key] = jsonable(await main.leader_ward_detail(
            ward=key, preset="this_week", date_from=None, date_to=None, person_id=None, _=True))
    out["campaign_detail"] = {
        str(c["_id"]): jsonable(await main.leader_campaign_detail(str(c["_id"]), _=True)) for c in data["campaigns"]
    }

    out["leader_pdf"]["wednesday"] = pdf_text(await body_bytes(await main.leader_wednesday_report_pdf(municipality=None, _=True)))
    for muni in (None, "Amahlathi"):
        for weeks in (8, 12):
            pdf = await main.leader_trend_report_pdf(municipality=muni, weeks_back=weeks, _=True)
            out["leader_pdf"][f"trend:{muni or 'all'}:{weeks}"] = pdf_text(await body_bytes(pdf))

    week_keys = [main.current_week_key(), main.leadership_reporting.previous_week_key(main.current_week_key())]
    admin: dict = {}
    for wk in week_keys:
        admin[f"report:{wk}"] = jsonable(await main.admin_report(week_key=wk, _=True))
        admin[f"export.xlsx:{wk}"] = xlsx_cells(await body_bytes(await main.admin_export_xlsx(week_key=wk, _=True)))
        admin[f"smartsheet_summary:{wk}"] = jsonable(await main.admin_smartsheet_summary(week_key=wk, _=True))
        for category in ("CANVASSING", "PUBLIC_STREET_MEETING", "PRESENCE"):
            admin[f"smartsheet.csv:{wk}:{category}"] = csv_rows(await body_bytes(
                await main.admin_smartsheet_export_csv(week_key=wk, category=category, _=True)))
            admin[f"smartsheet.xlsx:{wk}:{category}"] = xlsx_cells(await body_bytes(
                await main.admin_smartsheet_export_xlsx(week_key=wk, category=category, _=True)))
        for include in (False, True):
            admin[f"capture_weekly:{wk}:{include}"] = jsonable(await main.admin_official_capture_weekly(
                week_key=wk, include_captured=include, _=True))
            admin[f"capture_weekly.xlsx:{wk}:{include}"] = xlsx_cells(await body_bytes(
                await main.admin_official_capture_weekly_export_xlsx(week_key=wk, include_captured=include, _=True)))
    admin["export.xlsx:default"] = xlsx_cells(await body_bytes(await main.admin_export_xlsx(week_key=None, _=True)))
    admin["export.csv"] = csv_rows(await body_bytes(await main.admin_export_csv(_=True)))
    admin["all"] = jsonable(await main.admin_all(_=True))
    admin["official_capture"] = jsonable(await main.admin_official_capture(_=True))
    admin["official_capture.xlsx"] = xlsx_cells(await body_bytes(await main.admin_official_capture_export_xlsx(
        status=None, person_id=None, campaign_id=None, official_activity_type=None, date_from=None, date_to=None, _=True)))
    admin["smartsheet_review"] = jsonable(await main.admin_smartsheet_review(_=True))
    admin["calendar"] = jsonable(await main.admin_calendar(month_key="2026-11", status=None, _=True))
    admin["calendar.xlsx"] = xlsx_cells(await body_bytes(await main.admin_calendar_export_xlsx(month_key="2026-11", _=True)))
    out["admin"] = admin
    return out


def flatten(value, path="", out=None):
    out = {} if out is None else out
    if isinstance(value, dict):
        for k, v in value.items():
            flatten(v, f"{path}/{k}", out)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            flatten(v, f"{path}[{i}]", out)
    else:
        out[path] = value
    return out


# The coordinator workbook stamps its print date from the real clock
# (main.admin_export_xlsx uses datetime.now), which the frozen SAST clock
# does not cover; a change of that stamp alone is not a report difference.
PRINT_DATE = re.compile(r"^Generated: \d{1,2} [A-Z][a-z]{2} \d{4}$")


def compare(old_path: str, new_path: str) -> int:
    old = flatten(json.loads(Path(old_path).read_text(encoding="utf-8")))
    new = flatten(json.loads(Path(new_path).read_text(encoding="utf-8")))
    differing = [p for p in old if p in new and old[p] != new[p]]
    print_dates = [p for p in differing if PRINT_DATE.match(str(old[p])) and PRINT_DATE.match(str(new[p]))]
    changed = [p for p in differing if p not in print_dates]
    removed = [p for p in old if p not in new]
    added = [p for p in new if p not in old]
    print(f"{len(old)} values compared: {len(changed)} changed, {len(removed)} removed, {len(added)} added"
          f" ({len(print_dates)} print-date stamps ignored)")
    for label, paths in (("CHANGED", changed), ("REMOVED", removed)):
        for p in paths[:200]:
            print(f"  {label} {p}: {old[p]!r} -> {new.get(p, '<missing>')!r}")
    groups: dict = {}
    for p in added:
        groups.setdefault(p.split("[")[0] if "[" in p else p.rsplit("/", 1)[0], []).append(p)
    for prefix, paths in sorted(groups.items())[:200]:
        print(f"  added {prefix}  ({len(paths)} value{'s' if len(paths) != 1 else ''})")
    return 1 if changed or removed else 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "snapshot":
        # Built outside the event loop: synthetic_data runs its own loop.
        result = asyncio.run(capture(install_store()))
        Path(sys.argv[2]).write_text(json.dumps(result, indent=1, sort_keys=True), encoding="utf-8")
        print(f"Snapshot written: {sys.argv[2]}")
    elif len(sys.argv) == 4 and sys.argv[1] == "compare":
        sys.exit(compare(sys.argv[2], sys.argv[3]))
    else:
        print(__doc__)
        sys.exit(2)
