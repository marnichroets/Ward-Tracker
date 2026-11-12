"""Run the real Ward Tracker app locally against SYNTHETIC data.

    python devtools/local_server.py            # http://127.0.0.1:8765

What this is: the unmodified FastAPI app from main.py plus the unmodified
frontend/, wired to an in-memory store seeded by devtools/synthetic_data.py.
It exists so the app can be developed, tested and screenshotted without
touching production.

Isolation guarantees (each one independent of the others):
  1. MONGO_URI is forcibly overridden to an unroutable local address before
     main.py is imported, so even a missed code path cannot reach a real DB.
  2. Every collection main.py uses (and its `db`/GridFS handles) is replaced
     with an in-memory store before the server starts.
  3. The served page gets API_BASE = this local origin, and every response
     carries a Content-Security-Policy with connect-src 'self', so the
     browser itself refuses any request to the production API.
  4. Binds to 127.0.0.1 only — never reachable from other machines.
Local sign-in PINs (synthetic environment only): coordinator 1111, leader 2222.
"""
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
HOST, PORT = "127.0.0.1", int(os.environ.get("WARD_TRACKER_LOCAL_PORT", "8765"))
ORIGIN = f"http://{HOST}:{PORT}"
ADMIN_PIN, LEADER_PIN = "1111", "2222"

# (1) Override — never setdefault — so a real MONGO_URI/PIN in the shell
# environment can never be picked up by this process.
os.environ["MONGO_URI"] = "mongodb://127.0.0.1:1/?serverSelectionTimeoutMS=200"
os.environ["DB_NAME"] = "ward_tracker_local_synthetic"
os.environ["ADMIN_PIN"] = ADMIN_PIN
os.environ["COORDINATOR_LEADER_PIN"] = LEADER_PIN
os.environ["JWT_SECRET"] = secrets.token_hex(32)
os.environ["FRONTEND_ORIGIN"] = ORIGIN
for leaked in ("LEADER_PIN", "LEADER_PIN_HASH", "COORDINATOR_LEADER_PIN_HASH"):
    os.environ.pop(leaked, None)

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "devtools"))

import main  # noqa: E402
from fastapi.responses import HTMLResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from memory_db import MemoryCollection, MemoryDatabase, NoPhotoBucket  # noqa: E402
import synthetic_data  # noqa: E402

LOCAL_CONFIG = (
    '<script>window.WARD_TRACKER_CONFIG = {apiBase: "", environment: "local-synthetic", '
    f'environmentLabel: "Local development · synthetic data, not real activity · PINs {ADMIN_PIN} / {LEADER_PIN}"}};</script>\n'
)
CSP = (
    "default-src 'self'; connect-src 'self'; img-src 'self' data: blob:; "
    "script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'"
)


def install_memory_store():
    data = synthetic_data.generate()
    main.db = MemoryDatabase()
    main.client = None
    main.entries_col = MemoryCollection(data["entries"])
    main.roster_col = MemoryCollection(data["roster"])
    main.campaigns_col = MemoryCollection(data["campaigns"])
    main.activity_audit_col = MemoryCollection()
    main.evidence_bucket = NoPhotoBucket()
    return data


def serve_index():
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    marker = '<script src="./week-dates.js"></script>'
    if marker not in html:
        raise RuntimeError("index.html changed: cannot inject local config safely; refusing to serve")
    return html.replace(marker, LOCAL_CONFIG + marker, 1)


def build_app():
    app = main.app

    @app.middleware("http")
    async def local_csp(request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Ward-Tracker-Environment"] = "local-synthetic"
        return response

    @app.get("/", include_in_schema=False)
    @app.get("/index.html", include_in_schema=False)
    async def index():
        return HTMLResponse(serve_index(), headers={"Cache-Control": "no-store"})

    app.mount("/", StaticFiles(directory=str(FRONTEND)), name="frontend")
    return app


if __name__ == "__main__":
    import uvicorn

    data = install_memory_store()
    print(f"Synthetic data: {len(data['roster'])} candidates, {len(data['entries'])} activities, "
          f"{len(data['campaigns'])} campaigns")
    print(f"Ward Tracker (LOCAL, SYNTHETIC DATA) on {ORIGIN}  —  coordinator PIN {ADMIN_PIN}, leader PIN {LEADER_PIN}")
    uvicorn.run(build_app(), host=HOST, port=PORT, log_level="warning")
