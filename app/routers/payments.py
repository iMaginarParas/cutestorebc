"""
Payments router

POST /payments/create-order   → create Razorpay order, store in DB
POST /payments/verify         → verify signature, mark as paid, grant access
GET  /payments/status         → check if current user has paid
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.config import settings
from app.services.auth_service import get_current_user
from app.services.razorpay_service import create_order, verify_signature
from app.services.supabase_client import get_supabase

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────────────────

class OrderResponse(BaseModel):
    order_id: str
    amount: int          # paise
    currency: str
    razorpay_key_id: str
    product_name: str


class VerifyRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_or_create_purchase_record(db, user_id: str, order_id: str):
    """Insert a pending purchase row; idempotent on order_id."""
    db.table("purchases").upsert({
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "razorpay_order_id": order_id,
        "amount_paise": settings.product_price_paise,
        "currency": "INR",
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }, on_conflict="razorpay_order_id").execute()


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/create-order", response_model=OrderResponse)
def create_payment_order(user: dict = Depends(get_current_user)):
    """
    Creates a Razorpay order for 200 INR.
    Returns details needed by the frontend Razorpay Checkout widget.
    """
    user_id = user["sub"]
    db = get_supabase()

    # Check if already purchased
    existing = (
        db.table("purchases")
        .select("status")
        .eq("user_id", user_id)
        .eq("status", "paid")
        .execute()
    )
    if existing.data:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You have already purchased this product.",
        )

    receipt = f"rcpt_{user_id[:8]}_{uuid.uuid4().hex[:8]}"
    order = create_order(receipt)

    _get_or_create_purchase_record(db, user_id, order["id"])

    return OrderResponse(
        order_id=order["id"],
        amount=order["amount"],
        currency=order["currency"],
        razorpay_key_id=settings.razorpay_key_id,
        product_name=settings.product_name,
    )


@router.post("/verify")
def verify_payment(body: VerifyRequest, user: dict = Depends(get_current_user)):
    """
    Called by the frontend after Razorpay Checkout succeeds.
    Verifies HMAC signature and marks the purchase as paid.
    """
    user_id = user["sub"]

    if not verify_signature(
        body.razorpay_order_id,
        body.razorpay_payment_id,
        body.razorpay_signature,
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Payment signature verification failed.",
        )

    db = get_supabase()

    # Update purchase record
    result = (
        db.table("purchases")
        .update({
            "status": "paid",
            "razorpay_payment_id": body.razorpay_payment_id,
            "razorpay_signature": body.razorpay_signature,
            "paid_at": datetime.now(timezone.utc).isoformat(),
        })
        .eq("razorpay_order_id", body.razorpay_order_id)
        .eq("user_id", user_id)
        .execute()
    )

    if not result.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found for this user.",
        )

    # Grant product access
    db.table("product_access").upsert({
        "user_id": user_id,
        "granted_at": datetime.now(timezone.utc).isoformat(),
        "razorpay_order_id": body.razorpay_order_id,
    }, on_conflict="user_id").execute()

    return {
        "success": True,
        "message": "Payment verified. Access granted! 🎉",
        "payment_id": body.razorpay_payment_id,
    }


@router.get("/status")
def payment_status(user: dict = Depends(get_current_user)):
    """Check whether the current user has paid."""
    user_id = user["sub"]
    db = get_supabase()

    access = (
        db.table("product_access")
        .select("granted_at")
        .eq("user_id", user_id)
        .execute()
    )

    if access.data:
        return {
            "has_access": True,
            "granted_at": access.data[0]["granted_at"],
        }

    return {"has_access": False}
