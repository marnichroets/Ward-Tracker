# trigger redeploy
import os
import re
import io
import csv
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from motor.motor_asyncio import AsyncIOMotorClient
from bson import ObjectId
from jose import jwt, JWTError
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.chart import BarChart, Reference
from openpyxl.drawing.image import Image as XLImage
import certifi
import ssl

# Atlas on this host rejects TLS 1.3 (TLSV1_ALERT_INTERNAL_ERROR); cap at TLS 1.2.
_original_create_default_context = ssl.create_default_context


def _create_default_context_tls12(*args, **kwargs):
    context = _original_create_default_context(*args, **kwargs)
    context.maximum_version = ssl.TLSVersion.TLSv1_2
    return context


ssl.create_default_context = _create_default_context_tls12

# ---------- Config ----------
MONGO_URI = os.environ["MONGO_URI"]                     # required — set in Railway
DB_NAME = os.environ.get("DB_NAME", "ward_tracker")
ADMIN_PIN = os.environ["ADMIN_PIN"]                      # required — your coordinator PIN
JWT_SECRET = os.environ["JWT_SECRET"]                    # required — long random string
JWT_ALGO = "HS256"
JWT_EXPIRE_DAYS = 30
FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "*")  # set to your Vercel URL once deployed
LOGO_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "logo.png")

app = FastAPI(title="Ntsikana Ward Tracker API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN] if FRONTEND_ORIGIN != "*" else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = AsyncIOMotorClient(MONGO_URI, tlsCAFile=certifi.where())
db = client[DB_NAME]
entries_col = db["entries"]
roster_col = db["roster"]


@app.on_event("startup")
async def ensure_indexes():
    await entries_col.create_index([("person_id", 1), ("week_key", 1)])
    await roster_col.create_index("name_slug", unique=True)


# ---------- Helpers ----------
def slugify(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def oid_str(doc: dict) -> dict:
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    return doc


def current_week_key() -> str:
    today = datetime.now(timezone.utc).date()
    sunday = today - timedelta(days=(today.weekday() + 1) % 7)
    return sunday.isoformat()


_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def format_week_label(week_key: str) -> str:
    sunday = datetime.strptime(week_key, "%Y-%m-%d").date()
    following_sunday = sunday + timedelta(days=7)
    fmt = lambda d: f"{d.day} {_MONTHS[d.month - 1]}"
    return f"{fmt(sunday)} – {fmt(following_sunday)}"


def make_admin_token() -> str:
    payload = {
        "role": "admin",
        "exp": datetime.now(timezone.utc) + timedelta(days=JWT_EXPIRE_DAYS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


async def require_admin(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing admin token")
    token = authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
    except JWTError:
        raise HTTPException(401, "Invalid or expired admin token")
    if payload.get("role") != "admin":
        raise HTTPException(401, "Invalid admin token")
    return True


# ---------- Schemas ----------
class LoginRequest(BaseModel):
    pin: str


class EntryIn(BaseModel):
    person_id: str
    name: str
    ward: str
    day: str  # mon..sun
    type: str
    type_display: str
    notes: Optional[str] = None
    week_key: str
    week_label: str


class EntryOut(EntryIn):
    id: str
    submitted_at: str


class RosterIn(BaseModel):
    name: str
    ward: str


# ---------- Auth ----------
@app.post("/api/admin/login")
async def admin_login(body: LoginRequest):
    if body.pin != ADMIN_PIN:
        raise HTTPException(401, "Incorrect PIN")
    return {"token": make_admin_token()}


# ---------- Member: entries ----------
@app.get("/api/entries", response_model=List[EntryOut])
async def list_my_entries(person_id: str, week_key: str):
    cursor = entries_col.find({"person_id": person_id, "week_key": week_key})
    out = []
    async for doc in cursor:
        d = oid_str(doc)
        out.append(d)
    return out


@app.post("/api/entries", response_model=EntryOut)
async def create_entry(body: EntryIn):
    doc = body.dict()
    doc["submitted_at"] = datetime.now(timezone.utc).isoformat()
    res = await entries_col.insert_one(doc)
    doc["_id"] = res.inserted_id
    return oid_str(doc)


@app.put("/api/entries/{entry_id}", response_model=EntryOut)
async def update_entry(entry_id: str, body: EntryIn):
    doc = body.dict()
    doc["submitted_at"] = datetime.now(timezone.utc).isoformat()
    result = await entries_col.find_one_and_update(
        {"_id": ObjectId(entry_id), "person_id": body.person_id},
        {"$set": doc},
        return_document=True,
    )
    if not result:
        raise HTTPException(404, "Entry not found")
    return oid_str(result)


@app.delete("/api/entries/{entry_id}")
async def delete_entry(entry_id: str, person_id: str):
    result = await entries_col.delete_one({"_id": ObjectId(entry_id), "person_id": person_id})
    if result.deleted_count == 0:
        raise HTTPException(404, "Entry not found")
    return {"deleted": True}


# ---------- Admin: report ----------
@app.get("/api/admin/report")
async def admin_report(week_key: str, _: bool = Depends(require_admin)):
    cursor = entries_col.find({"week_key": week_key})
    entries = [oid_str(doc) async for doc in cursor]
    return {"week_key": week_key, "entries": entries}


@app.get("/api/admin/all")
async def admin_all(_: bool = Depends(require_admin)):
    cursor = entries_col.find({})
    entries = [oid_str(doc) async for doc in cursor]
    return {"entries": entries}


@app.get("/api/admin/export.csv")
async def admin_export_csv(_: bool = Depends(require_admin)):
    cursor = entries_col.find({})
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["name", "ward", "week_label", "day", "type", "notes", "submitted_at"])
    async for doc in cursor:
        writer.writerow([
            doc.get("name", ""), doc.get("ward", ""), doc.get("week_label", ""),
            doc.get("day", ""), doc.get("type_display", doc.get("type", "")),
            doc.get("notes", "") or "", doc.get("submitted_at", ""),
        ])
    # utf-8-sig adds a BOM so Excel correctly reads non-ASCII characters (e.g. en dashes in week_label)
    csv_bytes = buf.getvalue().encode("utf-8-sig")
    return StreamingResponse(
        iter([csv_bytes]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=ward-tracker-export.csv"},
    )


DAY_ORDER = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
DAY_LABELS = {"mon": "Mon", "tue": "Tue", "wed": "Wed", "thu": "Thu", "fri": "Fri", "sat": "Sat", "sun": "Sun"}
# Offset in days from a Sunday-anchored week_key (the week's start) to each weekday.
DAY_OFFSET = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}


@app.get("/api/admin/export.xlsx")
async def admin_export_xlsx(week_key: Optional[str] = None, _: bool = Depends(require_admin)):
    this_week_key = week_key or current_week_key()
    cursor = entries_col.find({"week_key": this_week_key})

    candidates = {}
    total_activities = 0
    type_counts = Counter()
    day_counts = {d: 0 for d in DAY_ORDER}
    async for doc in cursor:
        total_activities += 1
        name = doc.get("name", "")
        day = doc.get("day", "")
        type_display = doc.get("type_display") or doc.get("type", "")
        notes = (doc.get("notes") or "").strip()

        if type_display:
            type_counts[type_display] += 1
        if day in day_counts:
            day_counts[day] += 1

        c = candidates.setdefault(name, {"ward": doc.get("ward", ""), "days": {}, "notes": {}})
        if not c["ward"]:
            c["ward"] = doc.get("ward", "")
        c["days"][day] = f'{c["days"][day]}, {type_display}' if day in c["days"] else type_display
        if notes:
            c["notes"][day] = f'{c["notes"][day]}; {notes}' if day in c["notes"] else notes

    total_candidates = len(candidates)
    names_sorted = sorted(candidates.keys(), key=lambda n: n.lower())
    roster_docs = [doc async for doc in roster_col.find({})]
    roster_size = len(roster_docs)
    breakdown_str = " · ".join(f"{t}: {n}" for t, n in sorted(type_counts.items()))

    week_start = datetime.strptime(this_week_key, "%Y-%m-%d").date()
    day_dates = {d: week_start + timedelta(days=DAY_OFFSET[d]) for d in DAY_ORDER}

    headers = (
        ["Name", "Ward"]
        + [f"{DAY_LABELS[d]}\n{day_dates[d].day} {_MONTHS[day_dates[d].month - 1]}" for d in DAY_ORDER]
        + ["Notes"]
    )
    n_cols = len(headers)

    wb = Workbook()
    ws = wb.active
    ws.title = "Report"

    # --- Logo, top-left, above the title ---
    if os.path.exists(LOGO_PATH):
        logo_img = XLImage(LOGO_PATH)
        logo_img.width = 50
        logo_img.height = 61  # preserves the source's ~240:293 aspect ratio
        ws.add_image(logo_img, "A1")
        ws.row_dimensions[1].height = 48

    row = 2
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=n_cols)
    title_cell = ws.cell(row=row, column=1, value="Ntsikana Constituency — Weekly Ward Activity Report")
    title_cell.font = Font(bold=True, size=14, color="153B63")
    row += 1

    summary_top_row = row
    ws.cell(row=row, column=1, value=f"Week: {format_week_label(this_week_key)}"); row += 1
    ws.cell(row=row, column=1, value=f"Generated: {datetime.now(timezone.utc).strftime('%d %b %Y')}"); row += 1
    ws.cell(row=row, column=1, value=f"Total activities this week: {total_activities}"); row += 1
    ws.cell(row=row, column=1, value=f"Total candidates this week: {total_candidates}"); row += 1
    if breakdown_str:
        ws.cell(row=row, column=1, value=f"Activity breakdown: {breakdown_str}"); row += 1
    if roster_size > 0:
        ws.cell(row=row, column=1, value=f"Submission status: {total_candidates} of {roster_size} candidates submitted"); row += 1

    # --- Bar chart: activities per day. Source data lives in hidden columns to the right. ---
    chart_col = n_cols + 2
    ws.cell(row=1, column=chart_col, value="Day")
    ws.cell(row=1, column=chart_col + 1, value="Count")
    for i, d in enumerate(DAY_ORDER):
        ws.cell(row=2 + i, column=chart_col, value=DAY_LABELS[d])
        ws.cell(row=2 + i, column=chart_col + 1, value=day_counts[d])
    ws.column_dimensions[get_column_letter(chart_col)].hidden = True
    ws.column_dimensions[get_column_letter(chart_col + 1)].hidden = True

    chart = BarChart()
    chart.type = "col"
    chart.title = "Activities per day"
    chart.y_axis.title = "Count"
    chart.x_axis.title = "Day"
    chart.legend = None
    chart.width = 8
    chart.height = 6
    chart_data = Reference(ws, min_col=chart_col + 1, min_row=1, max_row=1 + len(DAY_ORDER))
    chart_cats = Reference(ws, min_col=chart_col, min_row=2, max_row=1 + len(DAY_ORDER))
    chart.add_data(chart_data, titles_from_data=True)
    chart.set_categories(chart_cats)
    ws.add_chart(chart, f"{get_column_letter(chart_col)}{summary_top_row}")

    row += 1  # spacer before the table
    header_row_idx = row
    header_fill = PatternFill(start_color="2568AE", end_color="2568AE", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")
    thin_side = Side(style="thin", color="DCD6C9")
    thin_border = Border(left=thin_side, right=thin_side, top=thin_side, bottom=thin_side)
    shade_fill = PatternFill(start_color="F3F1EC", end_color="F3F1EC", fill_type="solid")

    for col_idx, header in enumerate(headers, start=1):
        cell = ws.cell(row=header_row_idx, column=col_idx, value=header)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = thin_border
    ws.row_dimensions[header_row_idx].height = 30

    for row_offset, name in enumerate(names_sorted):
        r_idx = header_row_idx + 1 + row_offset
        c = candidates[name]
        row_fill = shade_fill if row_offset % 2 == 1 else None

        name_cell = ws.cell(row=r_idx, column=1, value=name)
        ward_cell = ws.cell(row=r_idx, column=2, value=c["ward"])
        for cell in (name_cell, ward_cell):
            cell.border = thin_border
            if row_fill:
                cell.fill = row_fill

        for day_idx, day in enumerate(DAY_ORDER):
            col = 3 + day_idx
            value = c["days"].get(day, "")
            cell = ws.cell(row=r_idx, column=col, value=value)
            cell.border = thin_border
            if row_fill:
                cell.fill = row_fill
            if value:
                cell.font = Font(bold=True)

        notes_parts = [f"{DAY_LABELS[d]}: {c['notes'][d]}" for d in DAY_ORDER if d in c["notes"]]
        notes_cell = ws.cell(row=r_idx, column=n_cols, value="; ".join(notes_parts))
        notes_cell.border = thin_border
        if row_fill:
            notes_cell.fill = row_fill

    last_row = header_row_idx + len(names_sorted)
    ws.freeze_panes = f"A{header_row_idx + 1}"

    for col_idx in range(1, n_cols + 1):
        col_letter = get_column_letter(col_idx)
        max_len = max(len(part) for part in headers[col_idx - 1].split("\n"))
        for r_idx in range(header_row_idx + 1, last_row + 1):
            val = ws.cell(row=r_idx, column=col_idx).value
            if val:
                max_len = max(max_len, len(str(val)))
        ws.column_dimensions[col_letter].width = max_len + 2

    # --- Not Yet Submitted: roster candidates with no entry this week ---
    submitted_names = {n.strip().lower() for n in names_sorted}
    not_submitted = sorted(
        (r for r in roster_docs if r.get("name", "").strip().lower() not in submitted_names),
        key=lambda r: r.get("name", "").lower(),
    )
    if not_submitted:
        row = last_row + 2
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=n_cols)
        section_title = ws.cell(row=row, column=1, value=f"Not Yet Submitted ({len(not_submitted)} of {roster_size})")
        section_title.font = Font(bold=True, size=12, color="B0473A")
        row += 1
        red_fill = PatternFill(start_color="FDF0EE", end_color="FDF0EE", fill_type="solid")
        for r in not_submitted:
            name_cell = ws.cell(row=row, column=1, value=r.get("name", ""))
            ward_cell = ws.cell(row=row, column=2, value=r.get("ward", ""))
            for cell in (name_cell, ward_cell):
                cell.fill = red_fill
                cell.border = thin_border
            row += 1

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=ward-tracker-report.xlsx"},
    )


# ---------- Public: roster names (for name autocomplete) ----------
@app.get("/api/roster/names")
async def roster_names():
    cursor = roster_col.find({}, {"_id": 0, "name": 1, "ward": 1})
    return [doc async for doc in cursor]


# ---------- Admin: roster ----------
@app.get("/api/admin/roster")
async def get_roster(_: bool = Depends(require_admin)):
    cursor = roster_col.find({})
    return [oid_str(doc) async for doc in cursor]


@app.post("/api/admin/roster")
async def add_roster(body: RosterIn, _: bool = Depends(require_admin)):
    doc = body.dict()
    doc["name_slug"] = slugify(body.name)
    try:
        res = await roster_col.insert_one(doc)
    except Exception:
        raise HTTPException(409, "That candidate is already on the list")
    doc["_id"] = res.inserted_id
    return oid_str(doc)


@app.delete("/api/admin/roster/{roster_id}")
async def delete_roster(roster_id: str, _: bool = Depends(require_admin)):
    result = await roster_col.delete_one({"_id": ObjectId(roster_id)})
    if result.deleted_count == 0:
        raise HTTPException(404, "Not found")
    return {"deleted": True}


@app.get("/api/health")
async def health():
    return {"ok": True}
