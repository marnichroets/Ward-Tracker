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

client = AsyncIOMotorClient(MONGO_URI)
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
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=ward-tracker-export.csv"},
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
