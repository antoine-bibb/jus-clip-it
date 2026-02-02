from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import sqlite3
import traceback
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

import stripe
from dotenv import load_dotenv
from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

# =========================================================
# App (MUST be before decorators)
# =========================================================
app = FastAPI()

# =========================================================
# ENV
# =========================================================
load_dotenv()

# =========================================================
# PLAN CONFIG
# =========================================================
PLANS = {
    "free":  {"monthly_credits": 10, "price_monthly": 0},
    "basic": {"monthly_credits": 30, "price_monthly": 12},
    "plus":  {"monthly_credits": 45, "price_monthly": 18},
    "pro":   {"monthly_credits": 75, "price_monthly": 28},
}
DEFAULT_PLAN = "free"
RESET_DAYS = 30
JOB_COST = 1

# =========================================================
# STRIPE CONFIG
# =========================================================
stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "").strip()
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://127.0.0.1:8000").strip()
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()

STRIPE_PRICE_TO_PLAN = {
    os.getenv("STRIPE_PRICE_BASIC", "").strip(): "basic",
    os.getenv("STRIPE_PRICE_PLUS", "").strip(): "plus",
    os.getenv("STRIPE_PRICE_PRO", "").strip(): "pro",
}
STRIPE_PRICE_TO_PLAN = {k: v for k, v in STRIPE_PRICE_TO_PLAN.items() if k}

# =========================================================
# Paths
# =========================================================
APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
TEMPLATES_DIR = APP_DIR / "templates"
DATA_DIR = APP_DIR / "data"
DB_PATH = DATA_DIR / "app.db"

STATIC_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# =========================================================
# DB helpers
# =========================================================
def db_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def db_init():
    conn = db_conn()
    try:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT NOT NULL UNIQUE,
            username TEXT NOT NULL UNIQUE,
            pw_hash TEXT NOT NULL,
            credits INTEGER NOT NULL DEFAULT 0,
            plan TEXT NOT NULL DEFAULT 'free',
            billing TEXT NOT NULL DEFAULT 'none',
            next_reset_at TEXT,
            stripe_customer_id TEXT,
            stripe_subscription_id TEXT,
            created_at TEXT NOT NULL
        );
        """)

        conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
        """)

        cols = {row["name"] for row in conn.execute("PRAGMA table_info(users);").fetchall()}

        def add_col(sql: str):
            conn.execute(sql)

        if "plan" not in cols:
            add_col("ALTER TABLE users ADD COLUMN plan TEXT NOT NULL DEFAULT 'free';")
        if "billing" not in cols:
            add_col("ALTER TABLE users ADD COLUMN billing TEXT NOT NULL DEFAULT 'none';")
        if "next_reset_at" not in cols:
            add_col("ALTER TABLE users ADD COLUMN next_reset_at TEXT;")
        if "stripe_customer_id" not in cols:
            add_col("ALTER TABLE users ADD COLUMN stripe_customer_id TEXT;")
        if "stripe_subscription_id" not in cols:
            add_col("ALTER TABLE users ADD COLUMN stripe_subscription_id TEXT;")

        conn.commit()
    finally:
        conn.close()

@app.on_event("startup")
def _startup():
    db_init()

# =========================================================
# Password + Session helpers
# =========================================================
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
COOKIE_NAME = "jc_session"

def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
    return "pbkdf2_sha256$120000$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(dk).decode()

def _verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_b64, dk_b64 = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        iters_i = int(iters)
        salt = base64.b64decode(salt_b64.encode())
        dk_expected = base64.b64decode(dk_b64.encode())
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters_i)
        return hmac.compare_digest(dk, dk_expected)
    except Exception:
        return False

def _create_session(user_id: str, days: int = 14) -> Dict[str, Any]:
    token = secrets.token_urlsafe(32)
    now = datetime.utcnow()
    expires = now + timedelta(days=days)

    conn = db_conn()
    try:
        conn.execute(
            "INSERT INTO sessions(token, user_id, expires_at, created_at) VALUES(?,?,?,?)",
            (token, user_id, expires.isoformat(), now.isoformat()),
        )
        conn.commit()
    finally:
        conn.close()

    return {"token": token, "expires_at": expires}

def _get_user_by_session(token: str) -> Optional[sqlite3.Row]:
    conn = db_conn()
    try:
        s = conn.execute("SELECT * FROM sessions WHERE token = ?", (token,)).fetchone()
        if not s:
            return None

        expires_at = datetime.fromisoformat(s["expires_at"])
        if datetime.utcnow() > expires_at:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            conn.commit()
            return None

        u = conn.execute("SELECT * FROM users WHERE id = ?", (s["user_id"],)).fetchone()
        return u
    finally:
        conn.close()

def _delete_session(token: str):
    conn = db_conn()
    try:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()
    finally:
        conn.close()

def _maybe_reset_credits(user_id: str) -> sqlite3.Row:
    conn = db_conn()
    try:
        u = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not u:
            raise HTTPException(status_code=404, detail="User not found")

        plan = (u["plan"] or DEFAULT_PLAN).lower()
        if plan not in PLANS:
            plan = DEFAULT_PLAN

        now = datetime.utcnow()
        next_reset_raw = u["next_reset_at"]

        should_reset = False
        if not next_reset_raw:
            should_reset = True
        else:
            try:
                next_reset = datetime.fromisoformat(next_reset_raw)
                should_reset = now >= next_reset
            except Exception:
                should_reset = True

        if should_reset:
            monthly = int(PLANS[plan]["monthly_credits"])
            new_next_reset = (now + timedelta(days=RESET_DAYS)).isoformat()
            conn.execute(
                "UPDATE users SET credits = ?, next_reset_at = ? WHERE id = ?",
                (monthly, new_next_reset, user_id),
            )
            conn.commit()

        return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    finally:
        conn.close()

def get_current_user(request: Request) -> sqlite3.Row:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Not logged in")
    u = _get_user_by_session(token)
    if not u:
        raise HTTPException(status_code=401, detail="Session expired. Please login again.")
    return _maybe_reset_credits(u["id"])

def user_jobs_root(user_id: str) -> Path:
    p = DATA_DIR / "users" / user_id / "jobs"
    p.mkdir(parents=True, exist_ok=True)
    return p

# =========================================================
# Pages
# =========================================================
@app.get("/", response_class=HTMLResponse)
def home():
    index_path = TEMPLATES_DIR / "index.html"
    if not index_path.exists():
        return HTMLResponse("<h1>Missing app/templates/index.html</h1>", status_code=500)
    return HTMLResponse(index_path.read_text(encoding="utf-8"))

# =========================================================
# Billing helper endpoint (fixes your 404)
# =========================================================
@app.get("/api/billing/plans")
def billing_plans():
    return {
        "plans": [
            {"key": "free", "name": "Free", "credits": PLANS["free"]["monthly_credits"], "price_monthly": 0},
            {"key": "basic", "name": "Basic", "credits": PLANS["basic"]["monthly_credits"], "price_monthly": PLANS["basic"]["price_monthly"], "price_id": os.getenv("STRIPE_PRICE_BASIC", "").strip()},
            {"key": "plus", "name": "Plus", "credits": PLANS["plus"]["monthly_credits"], "price_monthly": PLANS["plus"]["price_monthly"], "price_id": os.getenv("STRIPE_PRICE_PLUS", "").strip()},
            {"key": "pro", "name": "Pro", "credits": PLANS["pro"]["monthly_credits"], "price_monthly": PLANS["pro"]["price_monthly"], "price_id": os.getenv("STRIPE_PRICE_PRO", "").strip()},
        ]
    }

# =========================================================
# Auth
# =========================================================
@app.post("/api/auth/signup")
def signup(response: Response, email: str = Form(...), username: str = Form(...), password: str = Form(...)):
    email = (email or "").strip().lower()
    username = (username or "").strip()
    password = password or ""

    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Invalid email")
    if len(username) < 3:
        raise HTTPException(status_code=400, detail="Username must be at least 3 characters")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    user_id = str(uuid.uuid4())[:12]
    pw_hash = _hash_password(password)
    now = datetime.utcnow()

    plan = "free"
    billing = "none"
    credits = int(PLANS["free"]["monthly_credits"])
    next_reset_at = (now + timedelta(days=RESET_DAYS)).isoformat()

    conn = db_conn()
    try:
        try:
            conn.execute(
                """
                INSERT INTO users(id, email, username, pw_hash, credits, plan, billing, next_reset_at, created_at)
                VALUES(?,?,?,?,?,?,?,?,?)
                """,
                (user_id, email, username, pw_hash, credits, plan, billing, next_reset_at, now.isoformat()),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=409, detail="Email or username already exists")
    finally:
        conn.close()

    sess = _create_session(user_id)
    response.set_cookie(COOKIE_NAME, sess["token"], httponly=True, samesite="lax", secure=False, max_age=14 * 24 * 3600, path="/")
    return {"ok": True, "email": email, "username": username, "credits": credits, "plan": plan}

@app.post("/api/auth/login")
def login(response: Response, username: str = Form(...), password: str = Form(...)):
    username = (username or "").strip()
    password = password or ""

    conn = db_conn()
    try:
        u = conn.execute("SELECT * FROM users WHERE username = ? OR email = ?", (username, username.lower())).fetchone()
    finally:
        conn.close()

    if not u or not _verify_password(password, u["pw_hash"]):
        raise HTTPException(status_code=401, detail="Invalid username/email or password")

    u2 = _maybe_reset_credits(u["id"])
    sess = _create_session(u["id"])
    response.set_cookie(COOKIE_NAME, sess["token"], httponly=True, samesite="lax", secure=False, max_age=14 * 24 * 3600, path="/")

    return {"ok": True, "email": u2["email"], "username": u2["username"], "credits": int(u2["credits"]), "plan": u2["plan"], "billing": u2["billing"], "next_reset_at": u2["next_reset_at"]}

@app.get("/api/auth/me")
def me(user=Depends(get_current_user)):
    return {"ok": True, "email": user["email"], "username": user["username"], "credits": int(user["credits"]), "plan": user["plan"], "billing": user["billing"], "next_reset_at": user["next_reset_at"]}

@app.post("/api/auth/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE_NAME)
    if token:
        _delete_session(token)
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}

# =========================================================
# Stripe endpoints
# =========================================================
@app.post("/api/stripe/create-checkout-session")
async def stripe_create_checkout_session(request: Request, user=Depends(get_current_user)):
    if not stripe.api_key:
        raise HTTPException(status_code=500, detail="Stripe secret key not set")

    data = await request.json()
    price_id = str(data.get("price_id", "")).strip()
    if not price_id or price_id not in STRIPE_PRICE_TO_PLAN:
        raise HTTPException(status_code=400, detail="Invalid price_id")

    conn = db_conn()
    try:
        u = conn.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
        if not u:
            raise HTTPException(status_code=404, detail="User not found")

        customer_id = u["stripe_customer_id"]
        if not customer_id:
            customer = stripe.Customer.create(email=u["email"], metadata={"user_id": u["id"], "app": "jus-clip-it"})
            customer_id = customer["id"]
            conn.execute("UPDATE users SET stripe_customer_id=? WHERE id=?", (customer_id, u["id"]))
            conn.commit()

        session = stripe.checkout.Session.create(
            mode="subscription",
            customer=customer_id,
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=f"{APP_BASE_URL}/?success=1",
            cancel_url=f"{APP_BASE_URL}/?canceled=1",
            allow_promotion_codes=True,
            client_reference_id=u["id"],
        )
        return {"url": session["url"]}
    finally:
        conn.close()

@app.post("/api/stripe/create-portal-session")
async def stripe_create_portal_session(user=Depends(get_current_user)):
    if not stripe.api_key:
        raise HTTPException(status_code=500, detail="Stripe secret key not set")

    conn = db_conn()
    try:
        u = conn.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
        if not u or not u["stripe_customer_id"]:
            raise HTTPException(status_code=400, detail="No Stripe customer yet")

        portal = stripe.billing_portal.Session.create(customer=u["stripe_customer_id"], return_url=f"{APP_BASE_URL}/")
        return {"url": portal["url"]}
    finally:
        conn.close()

# =========================================================
# Stripe webhook (ONLY ONE)
# =========================================================
@app.post("/api/stripe/webhook")
async def stripe_webhook(request: Request):
    if not STRIPE_WEBHOOK_SECRET:
        return JSONResponse({"error": "Missing STRIPE_WEBHOOK_SECRET"}, status_code=500)

    payload = await request.body()
    sig = request.headers.get("stripe-signature")
    if not sig:
        return JSONResponse({"error": "Missing stripe-signature header"}, status_code=400)

    try:
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    except Exception as e:
        print("❌ Webhook signature verify failed:", repr(e))
        return JSONResponse({"error": "Invalid signature"}, status_code=400)

    etype = event.get("type", "unknown")
    eid = event.get("id", "no_id")
    obj = (event.get("data") or {}).get("object") or {}
    print(f"✅ Stripe event received: {etype} ({eid})")

    try:
        conn = db_conn()
        try:
            if etype == "checkout.session.completed":
                customer_id = obj.get("customer")
                sub_id = obj.get("subscription")
                if customer_id:
                    u = conn.execute("SELECT * FROM users WHERE stripe_customer_id=?", (customer_id,)).fetchone()
                    if u and sub_id:
                        conn.execute("UPDATE users SET stripe_subscription_id=?, billing='stripe' WHERE id=?", (sub_id, u["id"]))
                        conn.commit()

            elif etype in ("customer.subscription.created", "customer.subscription.updated"):
                customer_id = obj.get("customer")
                status = obj.get("status", "")

                items = (obj.get("items") or {}).get("data") or []
                price_id = None
                if items and items[0].get("price"):
                    price_id = items[0]["price"].get("id")

                if customer_id:
                    u = conn.execute("SELECT * FROM users WHERE stripe_customer_id=?", (customer_id,)).fetchone()
                    if u and status == "active" and price_id in STRIPE_PRICE_TO_PLAN:
                        plan = STRIPE_PRICE_TO_PLAN[price_id]
                        monthly = int(PLANS[plan]["monthly_credits"])
                        now = datetime.utcnow()
                        next_reset_at = (now + timedelta(days=RESET_DAYS)).isoformat()
                        conn.execute("UPDATE users SET plan=?, billing='stripe', credits=?, next_reset_at=? WHERE id=?", (plan, monthly, next_reset_at, u["id"]))
                        conn.commit()

            elif etype == "customer.subscription.deleted":
                customer_id = obj.get("customer")
                if customer_id:
                    u = conn.execute("SELECT * FROM users WHERE stripe_customer_id=?", (customer_id,)).fetchone()
                    if u:
                        now = datetime.utcnow()
                        next_reset_at = (now + timedelta(days=RESET_DAYS)).isoformat()
                        free_credits = int(PLANS["free"]["monthly_credits"])
                        conn.execute("UPDATE users SET plan='free', billing='none', credits=?, next_reset_at=? WHERE id=?", (free_credits, next_reset_at, u["id"]))
                        conn.commit()
        finally:
            conn.close()

    except Exception as e:
        print("🔥 Webhook crashed:", etype, eid, repr(e))
        traceback.print_exc()
        # return 200 so Stripe doesn’t retry forever while you debug
        return JSONResponse({"received": True, "processing_error": str(e)}, status_code=200)

    return JSONResponse({"received": True}, status_code=200)

# =========================================================
# Video range streaming
# =========================================================
def range_file_response(path: Path, request: Request, content_type: str = "video/mp4"):
    file_size = path.stat().st_size
    range_header = request.headers.get("range")
    if not range_header:
        return FileResponse(str(path), media_type=content_type)

    m = re.match(r"bytes=(\d+)-(\d*)", range_header)
    if not m:
        return FileResponse(str(path), media_type=content_type)

    start = int(m.group(1))
    end = int(m.group(2)) if m.group(2) else file_size - 1
    end = min(end, file_size - 1)

    if start > end or start >= file_size:
        raise HTTPException(status_code=416, detail="Range Not Satisfiable")

    chunk_size = (end - start) + 1

    def iterfile():
        with open(path, "rb") as f:
            f.seek(start)
            remaining = chunk_size
            while remaining > 0:
                read_size = 1024 * 1024
                data = f.read(min(read_size, remaining))
                if not data:
                    break
                remaining -= len(data)
                yield data

    headers = {
        "Content-Range": f"bytes {start}-{end}/{file_size}",
        "Accept-Ranges": "bytes",
        "Content-Length": str(chunk_size),
    }
    return StreamingResponse(iterfile(), status_code=206, media_type=content_type, headers=headers)

# =========================================================
# Jobs
# =========================================================
@app.post("/api/jobs")
async def api_create_job(
    request: Request,
    user=Depends(get_current_user),
    video: UploadFile = File(...),
    clip_len: int = Form(25),
    max_clips: int = Form(8),
    out_aspect: str = Form("9:16"),
    out_w: int = Form(1080),
    out_h: int = Form(1920),
    crop_mode: str = Form("center"),
    crop_x: float = Form(50.0),
    crop_y: float = Form(50.0),
    crop_w: float = Form(56.0),
    crop_h: float = Form(100.0),
    follow_sample_fps: int = Form(10),
    follow_smooth: float = Form(0.18),
    follow_hold_frames: int = Form(24),
    follow_deadzone_px: int = Form(28),
    follow_min_switch_frames: int = Form(16),
    follow_max_move_px_per_sec: int = Form(320),
):
    if clip_len < 5 or clip_len > 120:
        raise HTTPException(status_code=400, detail="clip_len must be 5-120 seconds")
    if max_clips < 1 or max_clips > 50:
        raise HTTPException(status_code=400, detail="max_clips must be 1-50")

    allowed_aspects = {"9:16", "1:1", "16:9"}
    if out_aspect not in allowed_aspects:
        raise HTTPException(status_code=400, detail="out_aspect must be 9:16, 1:1, or 16:9")

    ALLOWED_CROP_MODES = {"none", "center", "left", "right", "manual", "smart", "speaker"}
    if crop_mode not in ALLOWED_CROP_MODES:
        raise HTTPException(status_code=400, detail="crop_mode must be none/center/left/right/manual/smart/speaker")

    if out_w < 0 or out_h < 0:
        raise HTTPException(status_code=400, detail="out_w/out_h must be >= 0")

    def clamp(v, lo, hi):
        try:
            v = float(v)
        except Exception:
            return lo
        return max(lo, min(hi, v))

    crop_x = clamp(crop_x, 0, 100)
    crop_y = clamp(crop_y, 0, 100)
    crop_w = clamp(crop_w, 10, 100)
    crop_h = clamp(crop_h, 10, 100)

    conn = db_conn()
    try:
        row = conn.execute("SELECT credits FROM users WHERE id = ?", (user["id"],)).fetchone()
        credits = int(row["credits"]) if row else 0
        if credits < JOB_COST:
            raise HTTPException(status_code=402, detail="No credits left")
        conn.execute("UPDATE users SET credits = credits - ? WHERE id = ?", (JOB_COST, user["id"]))
        conn.commit()
    finally:
        conn.close()

    job_id = str(uuid.uuid4())[:8]
    job_dir = user_jobs_root(user["id"]) / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    in_path = job_dir / "input.mp4"
    with in_path.open("wb") as f:
        shutil.copyfileobj(video.file, f)

    from app.engine import create_job  # noqa

    engine_kwargs = dict(
        job_dir=job_dir,
        clip_len=clip_len,
        max_clips=max_clips,
        out_aspect=out_aspect,
        out_w=out_w,
        out_h=out_h,
        crop_mode=crop_mode,
        crop_x=crop_x,
        crop_y=crop_y,
        crop_w=crop_w,
        crop_h=crop_h,
        follow_sample_fps=follow_sample_fps,
        follow_smooth=follow_smooth,
        follow_hold_frames=follow_hold_frames,
        follow_deadzone_px=follow_deadzone_px,
        follow_min_switch_frames=follow_min_switch_frames,
        follow_max_move_px_per_sec=follow_max_move_px_per_sec,
    )

    try:
        create_job(**engine_kwargs)
    except TypeError:
        for k in [
            "follow_sample_fps",
            "follow_smooth",
            "follow_hold_frames",
            "follow_deadzone_px",
            "follow_min_switch_frames",
            "follow_max_move_px_per_sec",
        ]:
            engine_kwargs.pop(k, None)
        create_job(**engine_kwargs)

    conn = db_conn()
    try:
        row = conn.execute("SELECT credits FROM users WHERE id = ?", (user["id"],)).fetchone()
        new_credits = int(row["credits"]) if row else 0
    finally:
        conn.close()

    return {"job_id": job_id, "credits": new_credits}

@app.get("/api/jobs/{job_id}/clips")
def api_list_clips(job_id: str, user=Depends(get_current_user)):
    from app.engine import list_clips  # noqa
    job_dir = user_jobs_root(user["id"]) / job_id
    if not job_dir.exists():
        raise HTTPException(status_code=404, detail="Job not found")
    return {"clips": list_clips(job_dir)}

@app.get("/api/jobs/{job_id}/files/{filename}")
def api_job_file(job_id: str, filename: str, user=Depends(get_current_user)):
    job_dir = user_jobs_root(user["id"]) / job_id
    p = job_dir / filename
    if not p.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(str(p))

@app.get("/api/jobs/{job_id}/clips/{idx}/video")
def api_clip_video(job_id: str, idx: int, request: Request, user=Depends(get_current_user)):
    from app.engine import get_clip_paths  # noqa
    job_dir = user_jobs_root(user["id"]) / job_id
    paths = get_clip_paths(job_dir, idx)
    p = paths["clip_mp4"]
    if not p.exists():
        raise HTTPException(status_code=404, detail="Clip not found")
    return range_file_response(p, request, content_type="video/mp4")

@app.get("/api/jobs/{job_id}/clips/{idx}/words")
def api_clip_words(job_id: str, idx: int, user=Depends(get_current_user)):
    from app.engine import get_clip_paths, transcribe_words_whisper  # noqa
    job_dir = user_jobs_root(user["id"]) / job_id
    paths = get_clip_paths(job_dir, idx)
    clip_mp4 = paths["clip_mp4"]
    words_json = paths["words_json"]

    if not clip_mp4.exists():
        raise HTTPException(status_code=404, detail="Clip not found")

    if not words_json.exists():
        words = transcribe_words_whisper(str(clip_mp4), model_size="base")
        words_json.write_text(json.dumps({"words": words}, indent=2), encoding="utf-8")

    return json.loads(words_json.read_text(encoding="utf-8"))

@app.get("/api/jobs/{job_id}/clips/{idx}/captions.srt")
def api_clip_srt(job_id: str, idx: int, user=Depends(get_current_user)):
    from app.engine import get_clip_paths  # noqa
    job_dir = user_jobs_root(user["id"]) / job_id
    paths = get_clip_paths(job_dir, idx)
    srt = paths["srt"]
    if not srt.exists():
        _ = api_clip_words(job_id, idx, user=user)
    if not srt.exists():
        raise HTTPException(status_code=404, detail="SRT not found")
    return FileResponse(str(srt), media_type="text/plain")

@app.get("/api/jobs/{job_id}/clips/{idx}/captions.json")
def api_clip_words_json(job_id: str, idx: int, user=Depends(get_current_user)):
    from app.engine import get_clip_paths  # noqa
    job_dir = user_jobs_root(user["id"]) / job_id
    paths = get_clip_paths(job_dir, idx)
    words_json = paths["words_json"]
    if not words_json.exists():
        _ = api_clip_words(job_id, idx, user=user)
    return FileResponse(str(words_json), media_type="application/json")

@app.post("/api/jobs/{job_id}/clips/{idx}/captions")
def api_save_captions(job_id: str, idx: int, srt_text: str = Form(""), user=Depends(get_current_user)):
    job_dir = user_jobs_root(user["id"]) / job_id
    srt = job_dir / f"clip_{idx}.srt"
    if not (job_dir / f"clip_{idx}.mp4").exists():
        raise HTTPException(status_code=404, detail="Clip not found")
    srt.write_text(srt_text or "", encoding="utf-8")
    return {"ok": True}
