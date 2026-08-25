# trigger redeploy
import os
import re
import io
import csv
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
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
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
    monday = today - timedelta(days=today.weekday())
    return monday.isoformat()


_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def format_week_label(week_key: str) -> str:
    monday = datetime.strptime(week_key, "%Y-%m-%d").date()
    sunday = monday + timedelta(days=6)
    fmt = lambda d: f"{d.day} {_MONTHS[d.month - 1]}"
    return f"{fmt(monday)} – {fmt(sunday)}"


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


@app.get("/api/admin/export.xlsx")
async def admin_export_xlsx(_: bool = Depends(require_admin)):
    cursor = entries_col.find({})
    rows = []
    async for doc in cursor:
        rows.append({
            "name": doc.get("name", ""),
            "ward": doc.get("ward", ""),
            "week_key": doc.get("week_key", ""),
            "week": doc.get("week_label", ""),
            "day": (doc.get("day") or "").capitalize(),
            "type": doc.get("type_display") or doc.get("type", ""),
            "notes": doc.get("notes") or "",
            "submitted_at": doc.get("submitted_at", ""),
        })
    # Stable sort: name ascending within a week, then week_key descending (newest first).
    rows.sort(key=lambda r: r["name"])
    rows.sort(key=lambda r: r["week_key"], reverse=True)

    this_week_key = current_week_key()
    this_week_rows = [r for r in rows if r["week_key"] == this_week_key]
    total_activities = len(this_week_rows)
    total_candidates = len({r["name"].strip().lower() for r in this_week_rows if r["name"]})

    headers = ["Name", "Ward", "Week", "Day", "Activity Type", "Notes", "Submitted At"]
    n_cols = len(headers)

    wb = Workbook()
    ws = wb.active
    ws.title = "Report"

    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=n_cols)
    title_cell = ws.cell(row=1, column=1, value="Ntsikana Constituency — Weekly Ward Activity Report")
    title_cell.font = Font(bold=True, size=14, color="153B63")

    ws.cell(row=2, column=1, value=f"Week: {format_week_label(this_week_key)}")
    ws.cell(row=3, column=1, value=f"Generated: {datetime.now(timezone.utc).strftime('%d %b %Y')}")
    ws.cell(row=4, column=1, value=f"Total activities this week: {total_activities}")
    ws.cell(row=5, column=1, value=f"Total candidates this week: {total_candidates}")

    header_row_idx = 7
    header_fill = PatternFill(start_color="2568AE", end_color="2568AE", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")
    for col_idx, header in enumerate(headers, start=1):
        cell = ws.cell(row=header_row_idx, column=col_idx, value=header)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for r_idx, row in enumerate(rows, start=header_row_idx + 1):
        ws.cell(row=r_idx, column=1, value=row["name"])
        ws.cell(row=r_idx, column=2, value=row["ward"])
        ws.cell(row=r_idx, column=3, value=row["week"])
        ws.cell(row=r_idx, column=4, value=row["day"])
        ws.cell(row=r_idx, column=5, value=row["type"])
        ws.cell(row=r_idx, column=6, value=row["notes"])
        ws.cell(row=r_idx, column=7, value=row["submitted_at"])

    ws.freeze_panes = f"A{header_row_idx + 1}"

    for col_idx in range(1, n_cols + 1):
        col_letter = get_column_letter(col_idx)
        max_len = len(headers[col_idx - 1])
        for r_idx in range(header_row_idx + 1, header_row_idx + 1 + len(rows)):
            val = ws.cell(row=r_idx, column=col_idx).value
            if val:
                max_len = max(max_len, len(str(val)))
        ws.column_dimensions[col_letter].width = max_len + 2

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=ward-tracker-report.xlsx"},
    )


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
