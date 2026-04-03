import os
import hmac
import hashlib
import httpx
import uuid
import mimetypes

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Depends, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr
from supabase import create_client, Client
from dotenv import load_dotenv
from typing import List, Optional

load_dotenv()

RAZORPAY_KEY_ID     = os.environ["RAZORPAY_KEY_ID"]
RAZORPAY_KEY_SECRET = os.environ["RAZORPAY_KEY_SECRET"]
SUPABASE_URL        = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY        = os.environ["SUPABASE_KEY"]
ADMIN_SECRET        = os.environ.get("ADMIN_SECRET", "change-me")
RAZORPAY_API        = "https://api.razorpay.com/v1"
STORAGE_BUCKET      = "product"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Valid upload folder names (kept explicit to prevent path traversal)
VALID_FOLDERS = {"products", "categories", "banners", "logo", "reviews"}


# ── Helpers ───────────────────────────────────────────────────────────────────

async def razorpay_create_order(amount: int, currency: str, receipt: str, notes: dict) -> dict:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{RAZORPAY_API}/orders",
            auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET),
            json={"amount": amount, "currency": currency, "receipt": receipt, "notes": notes},
        )
    if not resp.is_success:
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

app = FastAPI(title="Cute Store API", version="2.1.0")

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
async def upload_image(
    file: UploadFile = File(...),
    folder: str = Query(
        default="products",
        description="Storage sub-folder. One of: products, categories, banners, logo"
    ),
):
    """
    Upload any image to Supabase Storage and get back a public URL.

    Use the `folder` query param to keep images organised:
      - ?folder=products    (default) – product images
      - ?folder=categories  – category thumbnail images
      - ?folder=banners     – homepage banner images (banner_1/2/3)
      - ?folder=logo        – store logo

    After getting the URL, call the relevant endpoint to save it:
      - PUT /admin/site-assets/logo
      - PUT /admin/site-assets/banner_1  (or banner_2 / banner_3)
      - PATCH /admin/categories/{id}     { "image_url": "<url>" }
    """
    if folder not in VALID_FOLDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid folder '{folder}'. Must be one of: {', '.join(sorted(VALID_FOLDERS))}"
        )

    allowed_types = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/avif"}
    content_type = file.content_type or "application/octet-stream"
    if content_type not in allowed_types:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {content_type}")

    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 5 MB)")

    ext = mimetypes.guess_extension(content_type) or ".jpg"
    ext = ext.replace(".jpe", ".jpg")
    filename = f"{folder}/{uuid.uuid4().hex}{ext}"   # e.g. banners/abc123.jpg

    upload_url = f"{SUPABASE_URL}/storage/v1/object/{STORAGE_BUCKET}/{filename}"
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            upload_url,
            content=data,
            headers={
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type":  content_type,
                "x-upsert":      "true",
            },
        )

    if resp.status_code not in (200, 201):
        detail = resp.json() if resp.content else {}
        raise HTTPException(
            status_code=500,
            detail=f"Storage upload failed: {detail.get('message', 'unknown error')}"
        )

    public_url = f"{SUPABASE_URL}/storage/v1/object/public/{STORAGE_BUCKET}/{filename}"
    return {"url": public_url, "filename": filename, "folder": folder}



# ── Video Upload ──────────────────────────────────────────────────────────────

STORAGE_VIDEO_BUCKET = "product"   # reuse same bucket, videos go in reviews/ subfolder

@app.post("/admin/upload-video", dependencies=[Depends(verify_admin)])
async def upload_video(file: UploadFile = File(...)):
    """
    Upload a short vertical review video to Supabase Storage and return its public URL.

    Accepted formats : video/mp4, video/webm, video/quicktime (.mov)
    Max size         : 50 MB
    Stored under     : reviews/<uuid>.<ext>   in the 'product' bucket

    Typical flow:
      1. POST /admin/upload-video          → { url, filename }
      2. POST /admin/review-videos         → { video_url: "<url>", reviewer_name: "…", … }
    """
    allowed_video_types = {"video/mp4", "video/webm", "video/quicktime"}
    content_type = file.content_type or "application/octet-stream"
    if content_type not in allowed_video_types:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported video type: {content_type}. Allowed: mp4, webm, mov"
        )

    data = await file.read()
    if len(data) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Video too large (max 50 MB)")

    ext_map = {"video/mp4": ".mp4", "video/webm": ".webm", "video/quicktime": ".mov"}
    ext = ext_map.get(content_type, ".mp4")
    filename = f"reviews/{uuid.uuid4().hex}{ext}"   # e.g. reviews/abc123.mp4

    upload_url = f"{SUPABASE_URL}/storage/v1/object/{STORAGE_VIDEO_BUCKET}/{filename}"
    async with httpx.AsyncClient(timeout=120.0) as client:          # longer timeout for video
        resp = await client.post(
            upload_url,
            content=data,
            headers={
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type":  content_type,
                "x-upsert":      "true",
            },
        )

    if resp.status_code not in (200, 201):
        detail = resp.json() if resp.content else {}
        raise HTTPException(
            status_code=500,
            detail=f"Storage upload failed: {detail.get('message', 'unknown error')}"
        )

    public_url = f"{SUPABASE_URL}/storage/v1/object/public/{STORAGE_VIDEO_BUCKET}/{filename}"
    return {"url": public_url, "filename": filename}


# ── Schemas ───────────────────────────────────────────────────────────────────

class CartItem(BaseModel):
    id: str
    name: str
    qty: int
    price: int  # paise

class DeliveryAddress(BaseModel):
    line1: str
    line2: Optional[str] = None
    city: str
    state: str
    pincode: str
    country: str = "India"

class CreateOrderRequest(BaseModel):
    name: str
    email: EmailStr
    phone: str
    delivery_address: DeliveryAddress
    amount: int         # total in paise
    items: List[CartItem] = []
    notes: Optional[str] = None

class VerifyPaymentRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


# ── Public Routes ─────────────────────────────────────────────────────────────

@app.get("/")
def health():
    return {"status": "ok", "store": "Cute Store ✿"}


# ── Site Assets (public) ──────────────────────────────────────────────────────

@app.get("/site-assets")
def public_site_assets():
    """
    Returns all ACTIVE site assets for the storefront to consume.
    Typically called once on app load to get logo + banners.

    Response shape:
    {
      "logo":    { "url": "...", "alt": "Store Logo" },
      "banners": [
        { "key": "banner_1", "url": "...", "alt": "...", "link_url": "..." },
        { "key": "banner_2", "url": "...", ... }
      ]
    }
    """
    result = supabase.table("site_assets").select("*").eq("active", True).execute()
    logo    = None
    banners = []
    for row in result.data:
        if row["key"] == "logo":
            logo = {"url": row["url"], "alt": row.get("alt", "Store Logo")}
        elif row["key"].startswith("banner_"):
            banners.append({
                "key":      row["key"],
                "url":      row["url"],
                "alt":      row.get("alt", ""),
                "link_url": row.get("link_url"),
            })
    # Sort banners: banner_1, banner_2, banner_3
    banners.sort(key=lambda b: b["key"])
    return {"logo": logo, "banners": banners}


# ── Categories (public) ───────────────────────────────────────────────────────

@app.get("/categories")
def public_categories():
    """Return all active categories including their thumbnail image."""
    result = (
        supabase.table("categories")
        .select("id,name,description,slug,image_url")
        .eq("active", True)
        .order("name")
        .execute()
    )
    return {"categories": result.data}


# ── Products (public) ─────────────────────────────────────────────────────────

@app.get("/products")
def public_products(category: Optional[str] = Query(None, description="Filter by category slug")):
    query = (
        supabase.table("products")
        .select("id,name,description,price,image_url,images,category_id")
        .eq("active", True)
        .order("created_at", desc=True)
    )
    if category:
        cat = supabase.table("categories").select("id").eq("slug", category).eq("active", True).execute()
        if not cat.data:
            return {"products": []}
        query = query.eq("category_id", cat.data[0]["id"])
    result = query.execute()
    return {"products": result.data}



# ── Review Videos (public) ────────────────────────────────────────────────────

@app.get("/review-videos")
def public_review_videos(product_id: Optional[str] = Query(None, description="Filter by product ID")):
    """
    Returns all ACTIVE review videos ordered by sort_order, for the storefront review section.

    Optional ?product_id=<uuid> to show only videos linked to a specific product.

    Response shape:
    {
      "review_videos": [
        {
          "id": "…",
          "video_url": "…",
          "thumbnail_url": "…",
          "reviewer_name": "Priya S.",
          "reviewer_handle": "@priya",
          "caption": "Absolutely love it! 😍",
          "product_id": "…",
          "sort_order": 0
        },
        …
      ]
    }
    """
    query = (
        supabase.table("review_videos")
        .select("id,video_url,thumbnail_url,reviewer_name,reviewer_handle,caption,product_id,sort_order")
        .eq("active", True)
        .order("sort_order")
        .order("created_at", desc=True)
    )
    if product_id:
        query = query.eq("product_id", product_id)

    result = query.execute()
    return {"review_videos": result.data}


# ── Customer Profile & Order History ─────────────────────────────────────────

@app.get("/profile/orders")
def get_order_history(
    email: Optional[str] = Query(None),
    phone: Optional[str] = Query(None),
):
    if not email and not phone:
        raise HTTPException(status_code=400, detail="Provide email or phone query param")

    query = supabase.table("purchases").select(
        "id,created_at,razorpay_order_id,razorpay_payment_id,"
        "amount,currency,status,items,delivery_address,customer_name,"
        "customer_email,customer_phone,notes"
    )
    if email:
        query = query.eq("customer_email", email)
    else:
        query = query.eq("customer_phone", phone)

    result = query.order("created_at", desc=True).execute()
    return {"orders": result.data}

@app.get("/profile/orders/{order_id}")
def get_order_detail(order_id: str):
    result = supabase.table("purchases").select("*").eq("id", order_id).execute()
    if not result.data:
        result = supabase.table("purchases").select("*").eq("razorpay_order_id", order_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Order not found")
    return {"order": result.data[0]}


# ── Checkout: Create Order ────────────────────────────────────────────────────

@app.post("/create-order")
async def create_order(body: CreateOrderRequest):
    if body.amount <= 0:
        raise HTTPException(status_code=400, detail="Invalid order amount")

    phone = body.phone.strip()
    if not phone.lstrip("+").isdigit() or len(phone.lstrip("+")) < 10:
        raise HTTPException(status_code=400, detail="Invalid phone number")

    rp_order = await razorpay_create_order(
        amount=body.amount,
        currency="INR",
        receipt=f"rcpt_{uuid.uuid4().hex[:16]}",
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
        "delivery_address":  body.delivery_address.model_dump(),
        "amount":            body.amount,
        "currency":          "INR",
        "items":             [i.model_dump() for i in body.items],
        "notes":             body.notes,
        "status":            "pending",
    }).execute()

    return {
        "order_id": rp_order["id"],
        "amount":   body.amount,
        "currency": "INR",
        "key_id":   RAZORPAY_KEY_ID,
    }


# ── Checkout: Verify Payment ──────────────────────────────────────────────────

@app.post("/verify-payment")
def verify_payment(body: VerifyPaymentRequest):
    payload  = f"{body.razorpay_order_id}|{body.razorpay_payment_id}"
    expected = hmac.new(RAZORPAY_KEY_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected, body.razorpay_signature):
        supabase.table("purchases").update({"status": "failed"}).eq(
            "razorpay_order_id", body.razorpay_order_id
        ).execute()
        raise HTTPException(status_code=400, detail="Payment verification failed")

    result = supabase.table("purchases").update({
        "status":              "paid",
        "razorpay_payment_id": body.razorpay_payment_id,
        "razorpay_signature":  body.razorpay_signature,
    }).eq("razorpay_order_id", body.razorpay_order_id).select("*").execute()

    order = result.data[0] if result.data else {}
    return {
        "success":           True,
        "order":             order,
        "payment_id":        body.razorpay_payment_id,
        "razorpay_order_id": body.razorpay_order_id,
    }


# ── Webhook ───────────────────────────────────────────────────────────────────

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
            supabase.table("purchases").update({
                "status": "paid",
                "razorpay_payment_id": p["id"],
            }).eq("razorpay_order_id", p["order_id"]).execute()

    elif event == "payment.failed":
        p = payload["payload"]["payment"]["entity"]
        if p.get("order_id"):
            supabase.table("purchases").update({"status": "failed"}).eq(
                "razorpay_order_id", p["order_id"]
            ).execute()

    return {"status": "ok"}