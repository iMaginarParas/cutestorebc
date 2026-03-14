import os
import hmac
import hashlib
import httpx

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
RAZORPAY_KEY_ID     = os.environ["RAZORPAY_KEY_ID"]
RAZORPAY_KEY_SECRET = os.environ["RAZORPAY_KEY_SECRET"]
SUPABASE_URL        = os.environ["SUPABASE_URL"]
SUPABASE_KEY        = os.environ["SUPABASE_KEY"]

PRODUCT_PRICE_PAISE = 19900   # ₹199 → paise
PRODUCT_NAME        = "My Awesome Product"
RAZORPAY_API        = "https://api.razorpay.com/v1"

# ── Clients ───────────────────────────────────────────────────────────────────
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


async def razorpay_create_order(amount: int, currency: str, receipt: str, notes: dict) -> dict:
    """Create a Razorpay order directly via REST — no SDK required."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{RAZORPAY_API}/orders",
            auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET),
            json={"amount": amount, "currency": currency, "receipt": receipt, "notes": notes},
        )
    resp.raise_for_status()
    return resp.json()


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="Product Payment API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Schemas ───────────────────────────────────────────────────────────────────
class CreateOrderRequest(BaseModel):
    name: str
    email: EmailStr
    phone: str


class VerifyPaymentRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/")
def health():
    return {"status": "ok", "product": PRODUCT_NAME, "price": "₹199"}


@app.post("/create-order")
async def create_order(body: CreateOrderRequest):
    rp_order = await razorpay_create_order(
        amount=PRODUCT_PRICE_PAISE,
        currency="INR",
        receipt=f"receipt_{body.email}",
        notes={
            "customer_name":  body.name,
            "customer_email": body.email,
            "customer_phone": body.phone,
        },
    )

    supabase.table("purchases").insert({
        "razorpay_order_id": rp_order["id"],
        "customer_name":     body.name,
        "customer_email":    body.email,
        "customer_phone":    body.phone,
        "amount":            PRODUCT_PRICE_PAISE,
        "currency":          "INR",
        "status":            "pending",
    }).execute()

    return {
        "order_id": rp_order["id"],
        "amount":   PRODUCT_PRICE_PAISE,
        "currency": "INR",
        "key_id":   RAZORPAY_KEY_ID,
        "product":  PRODUCT_NAME,
    }


@app.post("/verify-payment")
def verify_payment(body: VerifyPaymentRequest):
    payload  = f"{body.razorpay_order_id}|{body.razorpay_payment_id}"
    expected = hmac.new(
        RAZORPAY_KEY_SECRET.encode(),
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, body.razorpay_signature):
        supabase.table("purchases").update({"status": "failed"}).eq(
            "razorpay_order_id", body.razorpay_order_id
        ).execute()
        raise HTTPException(status_code=400, detail="Payment verification failed")

    supabase.table("purchases").update({
        "status":              "paid",
        "razorpay_payment_id": body.razorpay_payment_id,
        "razorpay_signature":  body.razorpay_signature,
    }).eq("razorpay_order_id", body.razorpay_order_id).execute()

    return {"success": True, "message": "Payment verified successfully"}


@app.post("/webhook")
async def razorpay_webhook(request: Request):
    webhook_secret = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")
    body_bytes     = await request.body()
    signature      = request.headers.get("x-razorpay-signature", "")

    if webhook_secret:
        expected = hmac.new(
            webhook_secret.encode(), body_bytes, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise HTTPException(status_code=400, detail="Invalid webhook signature")

    payload = await request.json()
    event   = payload.get("event", "")

    if event == "payment.captured":
        payment    = payload["payload"]["payment"]["entity"]
        order_id   = payment.get("order_id")
        payment_id = payment.get("id")
        if order_id:
            supabase.table("purchases").update({
                "status":              "paid",
                "razorpay_payment_id": payment_id,
            }).eq("razorpay_order_id", order_id).execute()

    elif event == "payment.failed":
        payment  = payload["payload"]["payment"]["entity"]
        order_id = payment.get("order_id")
        if order_id:
            supabase.table("purchases").update({"status": "failed"}).eq(
                "razorpay_order_id", order_id
            ).execute()

    return {"status": "ok"}


@app.get("/purchases")
def get_purchases(email: str | None = None):
    query = supabase.table("purchases").select("*").order("created_at", desc=True)
    if email:
        query = query.eq("customer_email", email)
    result = query.execute()
    return {"purchases": result.data}