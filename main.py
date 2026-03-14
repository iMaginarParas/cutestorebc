import os
import hmac
import hashlib
import httpx
import uuid
import mimetypes

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr
from supabase import create_client, Client
from dotenv import load_dotenv
from typing import List

load_dotenv()

RAZORPAY_KEY_ID     = os.environ["RAZORPAY_KEY_ID"]
RAZORPAY_KEY_SECRET = os.environ["RAZORPAY_KEY_SECRET"]
SUPABASE_URL        = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY        = os.environ["SUPABASE_KEY"]
ADMIN_SECRET        = os.environ.get("ADMIN_SECRET", "change-me")
RAZORPAY_API        = "https://api.razorpay.com/v1"
STORAGE_BUCKET      = "product"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


# ── Helpers ───────────────────────────────────────────────────────────────────

async def razorpay_create_order(amount: int, currency: str, receipt: str, notes: dict) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{RAZORPAY_API}/orders",
            auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET),
            json={"amount": amount, "currency": currency, "receipt": receipt, "notes": notes},
        )
    if not resp.is_success:
        # Surface the actual Razorpay error message back to the client
        try:
            err = resp.json()
            msg = err.get("error", {}).get("description") or err.get("message") or resp.text
        except Exception:
            msg = resp.text
        raise HTTPException(status_code=502, detail=f"Razorpay error: {msg}")
    return resp.json()

def verify_admin(x_admin_token: str = Header(...)):
    if x_admin_token != ADMIN_SECRET:
        raise HTTPException(status_code=401, detail="Invalid admin token")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="Cute Store API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from admin import router as admin_router
app.include_router(admin_router)

try:
    app.mount("/static", StaticFiles(directory="static"), name="static")
except Exception:
    pass


# ── Image Upload ──────────────────────────────────────────────────────────────

@app.post("/admin/upload-image", dependencies=[Depends(verify_admin)])
async def upload_image(file: UploadFile = File(...)):
    """
    Receives an image from the admin panel, uploads it to Supabase Storage
    using the service-role key (which lives safely in Railway env vars),
    and returns the public URL.
    """
    # Validate type
    allowed = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/avif"}
    content_type = file.content_type or "application/octet-stream"
    if content_type not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {content_type}")

    # Read file bytes (max 5 MB)
    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 5 MB)")

    # Generate unique filename
    ext = mimetypes.guess_extension(content_type) or ".jpg"
    ext = ext.replace(".jpe", ".jpg")   # normalise
    filename = f"{uuid.uuid4().hex}{ext}"

    # Upload to Supabase Storage via REST (service-role key = full access)
    upload_url = f"{SUPABASE_URL}/storage/v1/object/{STORAGE_BUCKET}/{filename}"
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            upload_url,
            content=data,
            headers={
                "Authorization":  f"Bearer {SUPABASE_KEY}",
                "Content-Type":   content_type,
                "x-upsert":       "true",
            },
        )

    if resp.status_code not in (200, 201):
        detail = resp.json() if resp.content else {}
        raise HTTPException(status_code=500, detail=f"Storage upload failed: {detail.get('message','unknown error')}")

    public_url = f"{SUPABASE_URL}/storage/v1/object/public/{STORAGE_BUCKET}/{filename}"
    return {"url": public_url, "filename": filename}


# ── Schemas ───────────────────────────────────────────────────────────────────

class CartItem(BaseModel):
    id: str
    name: str
    qty: int
    price: int

class CreateOrderRequest(BaseModel):
    name: str
    email: EmailStr
    phone: str
    amount: int
    items: List[CartItem] = []

class VerifyPaymentRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


# ── Public Routes ─────────────────────────────────────────────────────────────

@app.get("/")
def health():
    return {"status": "ok", "store": "Cute Store ✿"}

@app.get("/products")
def public_products():
    result = (
        supabase.table("products")
        .select("id,name,description,price,image_url")
        .eq("active", True)
        .order("created_at", desc=True)
        .execute()
    )
    return {"products": result.data}

@app.post("/create-order")
async def create_order(body: CreateOrderRequest):
    if body.amount <= 0:
        raise HTTPException(status_code=400, detail="Invalid order amount")
    rp_order = await razorpay_create_order(
        amount=body.amount,
        currency="INR",
        receipt=f"rcpt_{uuid.uuid4().hex[:16]}",
        notes={"customer_name": body.name, "customer_email": body.email, "customer_phone": body.phone},
    )
    supabase.table("purchases").insert({
        "razorpay_order_id": rp_order["id"],
        "customer_name":     body.name,
        "customer_email":    body.email,
        "customer_phone":    body.phone,
        "amount":            body.amount,
        "currency":          "INR",
        "items":             [i.model_dump() for i in body.items],
        "status":            "pending",
    }).execute()
    return {"order_id": rp_order["id"], "amount": body.amount, "currency": "INR", "key_id": RAZORPAY_KEY_ID}

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
    return {"success": True}

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