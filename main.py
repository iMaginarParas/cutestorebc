import os
import hmac
import hashlib
import httpx

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from supabase import create_client, Client
from dotenv import load_dotenv
from admin import router as admin_router

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
RAZORPAY_KEY_ID     = os.environ["RAZORPAY_KEY_ID"]
RAZORPAY_KEY_SECRET = os.environ["RAZORPAY_KEY_SECRET"]
SUPABASE_URL        = os.environ["SUPABASE_URL"]
SUPABASE_KEY        = os.environ["SUPABASE_KEY"]

PRODUCT_PRICE_PAISE = 19900
PRODUCT_NAME        = "My Awesome Product"
RAZORPAY_API        = "https://api.razorpay.com/v1"

# ── Clients ───────────────────────────────────────────────────────────────────
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


async def razorpay_create_order(amount: int, currency: str, receipt: str, notes: dict) -> dict:
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

app.include_router(admin_router)


# ── Schemas ───────────────────────────────────────────────────────────────────
class CreateOrderRequest(BaseModel):
    name: str
    email: EmailStr
    phone: str
    product_id: str | None = None   # optional: link to a specific product


class VerifyPaymentRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/")
def health():
    return {"status": "ok", "product": PRODUCT_NAME, "price": "₹199"}


@app.get("/products")
def public_products():
    """Public: list only active products."""
    result = supabase.table("products").select("id,name,description,price").eq("active", True).execute()
    return {"products": result.data}


@app.post("/create-order")
async def create_order(body: CreateOrderRequest):
    # Resolve price from product if product_id provided, else use default
    amount = PRODUCT_PRICE_PAISE
    product_name = PRODUCT_NAME
    if body.product_id:
        res = supabase.table("products").select("name,price").eq("id", body.product_id).eq("active", True).single().execute()
        if res.data:
            amount = res.data["price"]
            product_name = res.data["name"]

    rp_order = await razorpay_create_order(
        amount=amount,
        currency="INR",
        receipt=f"receipt_{body.email}",
        notes={"customer_name": body.name, "customer_email": body.email, "customer_phone": body.phone},
    )

    supabase.table("purchases").insert({
        "razorpay_order_id": rp_order["id"],
        "customer_name":     body.name,
        "customer_email":    body.email,
        "customer_phone":    body.phone,
        "amount":            amount,
        "currency":          "INR",
        "status":            "pending",
    }).execute()

    return {"order_id": rp_order["id"], "amount": amount, "currency": "INR", "key_id": RAZORPAY_KEY_ID, "product": product_name}


@app.post("/verify-payment")
def verify_payment(body: VerifyPaymentRequest):
    payload  = f"{body.razorpay_order_id}|{body.razorpay_payment_id}"
    expected = hmac.new(RAZORPAY_KEY_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected, body.razorpay_signature):
        supabase.table("purchases").update({"status": "failed"}).eq("razorpay_order_id", body.razorpay_order_id).execute()
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
    body_bytes = await request.body()
    signature  = request.headers.get("x-razorpay-signature", "")

    if webhook_secret:
        expected = hmac.new(webhook_secret.encode(), body_bytes, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise HTTPException(status_code=400, detail="Invalid webhook signature")

    payload = await request.json()
    event   = payload.get("event", "")

    if event == "payment.captured":
        p = payload["payload"]["payment"]["entity"]
        if p.get("order_id"):
            supabase.table("purchases").update({"status": "paid", "razorpay_payment_id": p["id"]}).eq("razorpay_order_id", p["order_id"]).execute()
    elif event == "payment.failed":
        p = payload["payload"]["payment"]["entity"]
        if p.get("order_id"):
            supabase.table("purchases").update({"status": "failed"}).eq("razorpay_order_id", p["order_id"]).execute()

    return {"status": "ok"}