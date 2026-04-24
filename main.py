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

# Free shipping threshold in paise (₹199)
FREE_SHIPPING_THRESHOLD = 19900

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Valid upload folder names (kept explicit to prevent path traversal)
VALID_FOLDERS = {"products", "categories", "banners", "logo", "blog"}


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

app = FastAPI(title="Prottiva Store API", version="3.0.0")

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
        description="Storage sub-folder. One of: products, categories, banners, logo, blog"
    ),
):
    """
    Upload any image to Supabase Storage and get back a public URL.

    Use the `folder` query param to keep images organised:
      - ?folder=products    (default) – product images
      - ?folder=categories  – category thumbnail images
      - ?folder=banners     – homepage banner images
      - ?folder=logo        – store logo
      - ?folder=blog        – blog post cover images

    After getting the URL, call the relevant endpoint to save it.
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
    filename = f"{folder}/{uuid.uuid4().hex}{ext}"

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


# ── Direct-to-Supabase video upload config ────────────────────────────────────

@app.get("/admin/video-upload-config", dependencies=[Depends(verify_admin)])
def video_upload_config():
    """
    Returns Supabase credentials so the browser uploads videos DIRECTLY to
    Supabase Storage — bypassing Railway's body-size and timeout limits.
    """
    return {
        "supabase_url": SUPABASE_URL,
        "supabase_key": SUPABASE_KEY,
        "bucket":       STORAGE_BUCKET,
        "folder":       "reviews",
    }


# ── Schemas ───────────────────────────────────────────────────────────────────

class CartItem(BaseModel):
    id: str
    name: str
    qty: int
    price: int               # paise (already discounted if subscription)
    is_subscription: bool = False
    sub_frequency: Optional[str] = None   # "30" | "60" | "90" days

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
    amount: int              # total in paise
    items: List[CartItem] = []
    notes: Optional[str] = None

class VerifyPaymentRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str

class NewsletterRequest(BaseModel):
    email: EmailStr

class SubscriptionRequest(BaseModel):
    product_id: str
    customer_name: str
    customer_email: EmailStr
    customer_phone: str
    delivery_address: DeliveryAddress
    frequency_days: int = 60      # 30 / 60 / 90
    discount_pct: float = 15.0    # 15% off

class BlogPostCreate(BaseModel):
    slug: str
    title: str
    excerpt: Optional[str] = None
    content: Optional[str] = None   # HTML string stored as text
    category: Optional[str] = None  # nutrition | skincare | wellness | guides
    cover_url: Optional[str] = None
    author: Optional[str] = "Prottiva Team"
    published_at: Optional[str] = None
    read_time: Optional[int] = 5
    active: bool = True

class BlogPostUpdate(BaseModel):
    title: Optional[str] = None
    excerpt: Optional[str] = None
    content: Optional[str] = None
    category: Optional[str] = None
    cover_url: Optional[str] = None
    author: Optional[str] = None
    published_at: Optional[str] = None
    read_time: Optional[int] = None
    active: Optional[bool] = None


# ── Public Routes ─────────────────────────────────────────────────────────────

@app.get("/")
def health():
    return {"status": "ok", "store": "Prottiva Nutrition", "version": "3.0.0"}


# ── Site Assets (public) ──────────────────────────────────────────────────────

@app.get("/site-assets")
def public_site_assets():
    """Returns logo + active banners for the storefront."""
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
        .select("id,name,description,price,image_url,images,category_id,created_at")
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

@app.get("/products/{product_id}")
def public_product_by_id(product_id: str):
    """Fetch a single active product by UUID — used by product.html"""
    result = (
        supabase.table("products")
        .select("id,name,description,price,image_url,images,category_id,created_at")
        .eq("id", product_id)
        .eq("active", True)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"product": result.data[0]}


# ── Review Videos (public) ────────────────────────────────────────────────────

@app.get("/review-videos")
def public_review_videos(product_id: Optional[str] = Query(None)):
    """Returns all ACTIVE review videos. Optional ?product_id= to filter."""
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


# ── Newsletter ────────────────────────────────────────────────────────────────

@app.post("/newsletter")
def subscribe_newsletter(body: NewsletterRequest):
    """
    Subscribe an email address to the newsletter.
    Requires a `newsletter_subscribers` table:
      - email (text, primary key / unique)
      - subscribed_at (timestamptz, default now())
    """
    try:
        supabase.table("newsletter_subscribers").upsert(
            {"email": body.email},
            on_conflict="email"
        ).execute()
    except Exception:
        # Table may not exist yet — silently pass to avoid breaking the frontend
        pass
    return {"success": True, "message": "Subscribed successfully"}


# ── Subscriptions (Subscribe & Save) ─────────────────────────────────────────

@app.post("/subscriptions")
def create_subscription(body: SubscriptionRequest):
    """
    Create a Subscribe & Save record with 15% discount.

    Requires a `subscriptions` table:
      id uuid default gen_random_uuid() primary key,
      product_id uuid references products(id),
      product_name text,
      base_price int,
      discounted_price int,
      discount_pct float,
      customer_name text,
      customer_email text,
      customer_phone text,
      delivery_address jsonb,
      frequency_days int,
      status text default 'active',  -- active | paused | cancelled
      created_at timestamptz default now()
    """
    prod = (
        supabase.table("products")
        .select("id,name,price")
        .eq("id", body.product_id)
        .eq("active", True)
        .execute()
    )
    if not prod.data:
        raise HTTPException(status_code=404, detail="Product not found")

    product = prod.data[0]
    discounted_price = int(product["price"] * (1 - body.discount_pct / 100))

    result = supabase.table("subscriptions").insert({
        "product_id":       body.product_id,
        "product_name":     product["name"],
        "base_price":       product["price"],
        "discounted_price": discounted_price,
        "discount_pct":     body.discount_pct,
        "customer_name":    body.customer_name,
        "customer_email":   body.customer_email,
        "customer_phone":   body.customer_phone,
        "delivery_address": body.delivery_address.model_dump(),
        "frequency_days":   body.frequency_days,
        "status":           "active",
    }).execute()

    return {
        "success":         True,
        "subscription_id": result.data[0]["id"] if result.data else None,
        "discounted_price": discounted_price,
        "message":         f"Subscribed! You save {body.discount_pct:.0f}% on every delivery."
    }

@app.get("/subscriptions")
def get_subscriptions_by_email(email: str = Query(..., description="Customer email")):
    """Get all subscriptions for a customer by email."""
    result = (
        supabase.table("subscriptions")
        .select("*")
        .eq("customer_email", email)
        .order("created_at", desc=True)
        .execute()
    )
    return {"subscriptions": result.data}

@app.patch("/subscriptions/{subscription_id}/status")
def update_subscription_status(
    subscription_id: str,
    status: str = Query(..., description="active | paused | cancelled"),
):
    """Allow customers to pause or cancel their subscription."""
    if status not in ("active", "paused", "cancelled"):
        raise HTTPException(status_code=400, detail="status must be: active | paused | cancelled")
    result = (
        supabase.table("subscriptions")
        .update({"status": status})
        .eq("id", subscription_id)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Subscription not found")
    return {"success": True, "subscription": result.data[0]}


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


# ── Blog (public) ─────────────────────────────────────────────────────────────

@app.get("/blog")
def public_blog_posts(
    category: Optional[str] = Query(None, description="Filter by category slug"),
    limit:    int            = Query(20, le=50, description="Max posts to return"),
):
    """
    Return published blog posts, newest first.
    Requires a `blog_posts` table — silently returns [] if not yet created.

    Table schema:
      id uuid default gen_random_uuid() primary key,
      slug text unique not null,
      title text not null,
      excerpt text,
      content text,          -- HTML body
      category text,         -- nutrition | skincare | wellness | guides
      cover_url text,
      author text default 'Prottiva Team',
      published_at date,
      read_time int default 5,
      active boolean default true,
      created_at timestamptz default now()
    """
    try:
        query = (
            supabase.table("blog_posts")
            .select("id,slug,title,excerpt,category,cover_url,author,published_at,read_time")
            .eq("active", True)
            .order("published_at", desc=True)
            .limit(limit)
        )
        if category:
            query = query.eq("category", category)
        result = query.execute()
        return {"posts": result.data}
    except Exception:
        return {"posts": []}

@app.get("/blog/{slug}")
def public_blog_post(slug: str):
    """Return a single published blog post by slug (full content)."""
    try:
        result = (
            supabase.table("blog_posts")
            .select("*")
            .eq("slug", slug)
            .eq("active", True)
            .execute()
        )
        if not result.data:
            raise HTTPException(status_code=404, detail="Post not found")
        return {"post": result.data[0]}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=404, detail="Post not found")


# ── Blog Admin ────────────────────────────────────────────────────────────────

@app.get("/admin/blog", dependencies=[Depends(verify_admin)])
def admin_list_blog_posts():
    """List all blog posts (active and inactive) for admin."""
    try:
        result = (
            supabase.table("blog_posts")
            .select("id,slug,title,category,active,published_at,read_time")
            .order("published_at", desc=True)
            .execute()
        )
        return {"posts": result.data}
    except Exception:
        return {"posts": []}

@app.post("/admin/blog", dependencies=[Depends(verify_admin)], status_code=201)
def admin_create_blog_post(body: BlogPostCreate):
    """Create a new blog post."""
    # Check for duplicate slug
    try:
        existing = supabase.table("blog_posts").select("id").eq("slug", body.slug).execute()
        if existing.data:
            raise HTTPException(status_code=409, detail=f"Slug '{body.slug}' already exists")
        result = supabase.table("blog_posts").insert(body.model_dump()).execute()
        return {"post": result.data[0] if result.data else {}}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.patch("/admin/blog/{slug}", dependencies=[Depends(verify_admin)])
def admin_update_blog_post(slug: str, body: BlogPostUpdate):
    """Partially update a blog post by slug."""
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    result = supabase.table("blog_posts").update(updates).eq("slug", slug).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Post not found")
    return {"post": result.data[0]}

@app.delete("/admin/blog/{slug}", dependencies=[Depends(verify_admin)])
def admin_delete_blog_post(slug: str):
    """Soft-delete a blog post (sets active=False)."""
    result = supabase.table("blog_posts").update({"active": False}).eq("slug", slug).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Post not found")
    return {"success": True, "slug": slug}


# ── Admin: Subscriptions ──────────────────────────────────────────────────────

@app.get("/admin/subscriptions", dependencies=[Depends(verify_admin)])
def admin_list_subscriptions(
    status: Optional[str] = Query(None, description="active | paused | cancelled")
):
    """List all subscriptions (optionally filtered by status)."""
    try:
        query = supabase.table("subscriptions").select("*").order("created_at", desc=True)
        if status:
            query = query.eq("status", status)
        result = query.execute()
        return {"subscriptions": result.data}
    except Exception:
        return {"subscriptions": []}

@app.get("/admin/newsletter-subscribers", dependencies=[Depends(verify_admin)])
def admin_list_newsletter_subscribers():
    """List all newsletter subscribers."""
    try:
        result = supabase.table("newsletter_subscribers").select("*").order("subscribed_at", desc=True).execute()
        return {"subscribers": result.data, "count": len(result.data)}
    except Exception:
        return {"subscribers": [], "count": 0}


# ── Checkout: Create Order ────────────────────────────────────────────────────

@app.post("/create-order")
async def create_order(body: CreateOrderRequest):
    if body.amount <= 0:
        raise HTTPException(status_code=400, detail="Invalid order amount")

    phone = body.phone.strip()
    if not phone.lstrip("+").isdigit() or len(phone.lstrip("+")) < 10:
        raise HTTPException(status_code=400, detail="Invalid phone number")

    # Check if any item is a subscription
    has_subscription = any(getattr(i, 'is_subscription', False) for i in body.items)

    rp_order = await razorpay_create_order(
        amount=body.amount,
        currency="INR",
        receipt=f"rcpt_{uuid.uuid4().hex[:16]}",
        notes={
            "customer_name":  body.name,
            "customer_email": body.email,
            "customer_phone": body.phone,
            "has_subscription": str(has_subscription),
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

    # Auto-create subscription records for any subscription items
    if order:
        items = order.get("items", [])
        for item in items:
            if item.get("is_subscription"):
                try:
                    supabase.table("subscriptions").insert({
                        "product_id":       item.get("id"),
                        "product_name":     item.get("name"),
                        "base_price":       item.get("price"),
                        "discounted_price": item.get("price"),
                        "discount_pct":     15.0,
                        "customer_name":    order.get("customer_name"),
                        "customer_email":   order.get("customer_email"),
                        "customer_phone":   order.get("customer_phone"),
                        "delivery_address": order.get("delivery_address"),
                        "frequency_days":   int(item.get("sub_frequency") or 60),
                        "status":           "active",
                        "purchase_id":      order.get("id"),
                    }).execute()
                except Exception:
                    pass  # Don't fail payment verification if subscription write fails

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