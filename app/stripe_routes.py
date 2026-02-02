import os
import sqlite3
from datetime import datetime, timezone
from typing import Optional, Dict, Any

import stripe
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

router = APIRouter()

stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

DB_PATH = os.getenv("APP_DB_PATH", "app/data/app.db")

APP_BASE_URL = os.getenv("APP_BASE_URL", "http://127.0.0.1:4242")

PRICE_STARTER = os.getenv("STRIPE_PRICE_STARTER", "")
PRICE_PRO = os.getenv("STRIPE_PRICE_PRO", "")

PLAN_BY_PRICE = {
    PRICE_STARTER: {"plan": "starter", "monthly_credits": 300},
    PRICE_PRO: {"plan": "pro", "monthly_credits": 1000},
}


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def add_credits_for_plan(conn: sqlite3.Connection, user_id: int, plan: str, monthly_credits: int):
    # resets monthly (you can decide exact logic; this sets now and adds credits)
    conn.execute(
        "UPDATE users SET plan=?, credits=credits+?, credits_reset_at=? WHERE id=?",
        (plan, monthly_credits, utc_now_iso(), user_id),
    )


def set_free_plan(conn: sqlite3.Connection, user_id: int):
    conn.execute("UPDATE users SET plan='free' WHERE id=?", (user_id,))


def get_user_by_id(conn: sqlite3.Connection, user_id: int) -> Optional[sqlite3.Row]:
    cur = conn.execute("SELECT * FROM users WHERE id=?", (user_id,))
    return cur.fetchone()


def get_user_by_customer(conn: sqlite3.Connection, customer_id: str) -> Optional[sqlite3.Row]:
    cur = conn.execute("SELECT * FROM users WHERE stripe_customer_id=?", (customer_id,))
    return cur.fetchone()


@router.post("/api/stripe/create-checkout-session")
async def create_checkout_session(req: Request):
    """
    Body: { "user_id": 123, "price_id": "price_..." }
    """
    data = await req.json()
    user_id = int(data.get("user_id", 0))
    price_id = str(data.get("price_id", "")).strip()

    if not user_id or not price_id:
        raise HTTPException(status_code=400, detail="Missing user_id or price_id")

    if price_id not in PLAN_BY_PRICE:
        raise HTTPException(status_code=400, detail="Unknown price_id")

    conn = db()
    try:
        user = get_user_by_id(conn, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Create/reuse Stripe customer
        customer_id = user["stripe_customer_id"]
        if not customer_id:
            customer = stripe.Customer.create(
                metadata={"user_id": str(user_id), "app": "jus-clip-it"}
            )
            customer_id = customer["id"]
            conn.execute(
                "UPDATE users SET stripe_customer_id=? WHERE id=?",
                (customer_id, user_id),
            )
            conn.commit()

        # Create Checkout Session (subscription)
        # Stripe Checkout Sessions API supports mode="subscription" with line_items price. :contentReference[oaicite:3]{index=3}
        session = stripe.checkout.Session.create(
            mode="subscription",
            customer=customer_id,
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=f"{APP_BASE_URL}/?success=1&session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{APP_BASE_URL}/?canceled=1",
            allow_promotion_codes=True,
        )

        return {"url": session["url"]}
    finally:
        conn.close()


@router.post("/api/stripe/create-portal-session")
async def create_portal_session(req: Request):
    """
    Body: { "user_id": 123 }
    """
    data = await req.json()
    user_id = int(data.get("user_id", 0))
    if not user_id:
        raise HTTPException(status_code=400, detail="Missing user_id")

    conn = db()
    try:
        user = get_user_by_id(conn, user_id)
        if not user or not user["stripe_customer_id"]:
            raise HTTPException(status_code=400, detail="No Stripe customer for this user")

        # Customer portal session lets customers manage subscription/billing. :contentReference[oaicite:4]{index=4}
        session = stripe.billing_portal.Session.create(
            customer=user["stripe_customer_id"],
            return_url=f"{APP_BASE_URL}/",
        )
        return {"url": session["url"]}
    finally:
        conn.close()


@router.post("/api/stripe/webhook")
async def stripe_webhook(request: Request):
    """
    Stripe will POST events here.
    Must verify signature using webhook secret. :contentReference[oaicite:5]{index=5}
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    whsec = os.getenv("STRIPE_WEBHOOK_SECRET", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, whsec)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid signature")

    event_type = event["type"]
    obj = event["data"]["object"]

    conn = db()
    try:
        # 1) Checkout completed (first time subscription creation)
        if event_type == "checkout.session.completed":
            # For subscriptions, checkout.session has customer + subscription
            customer_id = obj.get("customer")
            subscription_id = obj.get("subscription")

            if customer_id:
                user = get_user_by_customer(conn, customer_id)
                if user:
                    if subscription_id:
                        conn.execute(
                            "UPDATE users SET stripe_subscription_id=? WHERE id=?",
                            (subscription_id, user["id"]),
                        )
                    conn.commit()

        # 2) Subscription updated (upgrade/downgrade/renew/active)
        if event_type == "customer.subscription.updated":
            customer_id = obj.get("customer")
            status = obj.get("status")  # active, past_due, canceled, etc.
            items = obj.get("items", {}).get("data", [])
            price_id = None
            if items:
                price_id = items[0].get("price", {}).get("id")

            if customer_id:
                user = get_user_by_customer(conn, customer_id)
                if user:
                    if status == "active" and price_id in PLAN_BY_PRICE:
                        plan_info = PLAN_BY_PRICE[price_id]
                        add_credits_for_plan(conn, user["id"], plan_info["plan"], plan_info["monthly_credits"])
                    elif status in ("canceled", "unpaid", "incomplete_expired"):
                        set_free_plan(conn, user["id"])
                    conn.commit()

        # 3) Subscription deleted (cancel)
        if event_type == "customer.subscription.deleted":
            customer_id = obj.get("customer")
            if customer_id:
                user = get_user_by_customer(conn, customer_id)
                if user:
                    set_free_plan(conn, user["id"])
                    conn.commit()

    finally:
        conn.close()

    return JSONResponse({"received": True})
