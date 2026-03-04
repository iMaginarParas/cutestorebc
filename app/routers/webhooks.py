"""
Razorpay Webhook handler

Configure in Razorpay Dashboard → Webhooks:
  URL:    https://your-domain.com/webhooks/razorpay
  Secret: same as RAZORPAY_KEY_SECRET (or set a dedicated webhook secret)
  Events: payment.captured, payment.failed, order.paid

This is the server-side safety net — even if the user closes the browser
after payment, this will still mark the purchase as paid.
"""

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException, Request, status

from app.services.razorpay_service import verify_webhook_signature
from app.services.supabase_client import get_supabase

router = APIRouter()


@router.post("/razorpay")
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: str = Header(...),
):
    body = await request.body()

    if not verify_webhook_signature(body, x_razorpay_signature):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid webhook signature",
        )

    event = json.loads(body)
    event_type = event.get("event")
    payload = event.get("payload", {})

    db = get_supabase()

    # ── payment.captured ─────────────────────────────────────────────────────
    if event_type == "payment.captured":
        payment = payload.get("payment", {}).get("entity", {})
        order_id = payment.get("order_id")
        payment_id = payment.get("id")

        if order_id and payment_id:
            # Update purchase
            db.table("purchases").update({
                "status": "paid",
                "razorpay_payment_id": payment_id,
                "paid_at": datetime.now(timezone.utc).isoformat(),
            }).eq("razorpay_order_id", order_id).execute()

            # Find user to grant access
            purchase_row = (
                db.table("purchases")
                .select("user_id")
                .eq("razorpay_order_id", order_id)
                .execute()
            )
            if purchase_row.data:
                user_id = purchase_row.data[0]["user_id"]
                db.table("product_access").upsert({
                    "user_id": user_id,
                    "granted_at": datetime.now(timezone.utc).isoformat(),
                    "razorpay_order_id": order_id,
                }, on_conflict="user_id").execute()

    # ── payment.failed ────────────────────────────────────────────────────────
    elif event_type == "payment.failed":
        payment = payload.get("payment", {}).get("entity", {})
        order_id = payment.get("order_id")
        if order_id:
            db.table("purchases").update({
                "status": "failed",
            }).eq("razorpay_order_id", order_id).execute()

    return {"status": "ok"}
