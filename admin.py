import os
from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel
from supabase import create_client, Client
from typing import Optional, List

def get_supabase() -> Client:
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "change-me")

def verify_admin(x_admin_token: str = Header(...)):
    if x_admin_token != ADMIN_SECRET:
        raise HTTPException(status_code=401, detail="Invalid admin token")
    return True


# ── Product Schemas ────────────────────────────────────────────────────────────

class ProductCreate(BaseModel):
    name: str
    description: Optional[str] = None
    price: int                        # paise
    images: List[str] = []           # ordered list of image URLs
    image_url: Optional[str] = None  # first image, kept for backwards compat
    active: bool = True
    category_id: Optional[str] = None

class ProductUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[int] = None
    images: Optional[List[str]] = None
    image_url: Optional[str] = None
    active: Optional[bool] = None
    category_id: Optional[str] = None


# ── Category Schemas ───────────────────────────────────────────────────────────

class CategoryCreate(BaseModel):
    name: str
    description: Optional[str] = None
    slug: str                         # e.g. "accessories", "clothing"
    image_url: Optional[str] = None  # category thumbnail image
    active: bool = True

class CategoryUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    slug: Optional[str] = None
    image_url: Optional[str] = None
    active: Optional[bool] = None


# ── Site Assets Schemas ────────────────────────────────────────────────────────
# One row per slot in `site_assets` table.
# Valid keys:  logo | banner_1 | banner_2 | banner_3

VALID_ASSET_KEYS = {"logo", "banner_1", "banner_2", "banner_3"}

class SiteAssetUpsert(BaseModel):
    url: str                          # image URL returned by /admin/upload-image
    alt: Optional[str] = None        # alt text / accessible label
    active: bool = True
    link_url: Optional[str] = None   # click-through URL (banners only)


# ── Router ─────────────────────────────────────────────────────────────────────

router = APIRouter(prefix="/admin", tags=["admin"])


# ── Product Routes ─────────────────────────────────────────────────────────────

@router.get("/products", dependencies=[Depends(verify_admin)])
def list_products(supabase: Client = Depends(get_supabase)):
    result = supabase.table("products").select("*").order("created_at", desc=True).execute()
    return {"products": result.data}

@router.post("/products", dependencies=[Depends(verify_admin)], status_code=201)
def create_product(body: ProductCreate, supabase: Client = Depends(get_supabase)):
    image_url = body.images[0] if body.images else body.image_url
    result = supabase.table("products").insert({
        "name":        body.name,
        "description": body.description,
        "price":       body.price,
        "images":      body.images,
        "image_url":   image_url,
        "active":      body.active,
        "category_id": body.category_id,
    }).execute()
    return {"product": result.data[0]}

@router.patch("/products/{product_id}", dependencies=[Depends(verify_admin)])
def update_product(product_id: str, body: ProductUpdate, supabase: Client = Depends(get_supabase)):
    updates = body.model_dump(exclude_none=True)
    if "images" in updates:
        updates["image_url"] = updates["images"][0] if updates["images"] else None
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    result = supabase.table("products").update(updates).eq("id", product_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"product": result.data[0]}

@router.delete("/products/{product_id}", dependencies=[Depends(verify_admin)])
def delete_product(product_id: str, supabase: Client = Depends(get_supabase)):
    result = supabase.table("products").delete().eq("id", product_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Product not found")
    return {"deleted": True, "id": product_id}


# ── Category Routes ────────────────────────────────────────────────────────────

@router.get("/categories", dependencies=[Depends(verify_admin)])
def admin_list_categories(supabase: Client = Depends(get_supabase)):
    result = supabase.table("categories").select("*").order("name").execute()
    return {"categories": result.data}

@router.post("/categories", dependencies=[Depends(verify_admin)], status_code=201)
def create_category(body: CategoryCreate, supabase: Client = Depends(get_supabase)):
    existing = supabase.table("categories").select("id").eq("slug", body.slug).execute()
    if existing.data:
        raise HTTPException(status_code=409, detail=f"Category slug '{body.slug}' already exists")
    result = supabase.table("categories").insert({
        "name":        body.name,
        "description": body.description,
        "slug":        body.slug,
        "image_url":   body.image_url,
        "active":      body.active,
    }).execute()
    return {"category": result.data[0]}

@router.patch("/categories/{category_id}", dependencies=[Depends(verify_admin)])
def update_category(category_id: str, body: CategoryUpdate, supabase: Client = Depends(get_supabase)):
    updates = body.model_dump(exclude_none=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    if "slug" in updates:
        existing = supabase.table("categories").select("id").eq("slug", updates["slug"]).execute()
        if existing.data and existing.data[0]["id"] != category_id:
            raise HTTPException(status_code=409, detail=f"Slug '{updates['slug']}' already in use")
    result = supabase.table("categories").update(updates).eq("id", category_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Category not found")
    return {"category": result.data[0]}

@router.delete("/categories/{category_id}", dependencies=[Depends(verify_admin)])
def delete_category(category_id: str, supabase: Client = Depends(get_supabase)):
    supabase.table("products").update({"category_id": None}).eq("category_id", category_id).execute()
    result = supabase.table("categories").delete().eq("id", category_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Category not found")
    return {"deleted": True, "id": category_id}


# ── Site Assets: Logo + Banners ────────────────────────────────────────────────

@router.get("/site-assets", dependencies=[Depends(verify_admin)])
def get_all_site_assets(supabase: Client = Depends(get_supabase)):
    """
    Returns all asset slots as a dict keyed by slot name.
    Missing slots are returned as null so the frontend always sees all 4 keys.

    Response shape:
    {
      "assets": {
        "logo":     { "key": "logo", "url": "...", "alt": "Store Logo", "active": true, "link_url": null },
        "banner_1": { ... },
        "banner_2": null,
        "banner_3": { ... }
      }
    }
    """
    result = supabase.table("site_assets").select("*").execute()
    by_key = {row["key"]: row for row in result.data}
    return {"assets": {k: by_key.get(k) for k in VALID_ASSET_KEYS}}

@router.put("/site-assets/{key}", dependencies=[Depends(verify_admin)])
def upsert_site_asset(key: str, body: SiteAssetUpsert, supabase: Client = Depends(get_supabase)):
    """
    Create or replace a slot.  key must be: logo | banner_1 | banner_2 | banner_3

    Typical flow:
      1. POST /admin/upload-image  → get back { url }
      2. PUT  /admin/site-assets/banner_1  { "url": "<url>", "alt": "Summer Sale", "link_url": "/sale" }
    """
    if key not in VALID_ASSET_KEYS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid key '{key}'. Allowed: {', '.join(sorted(VALID_ASSET_KEYS))}"
        )
    payload = {
        "key":      key,
        "url":      body.url,
        "alt":      body.alt or key.replace("_", " ").title(),
        "active":   body.active,
        "link_url": body.link_url,
    }
    result = supabase.table("site_assets").upsert(payload, on_conflict="key").execute()
    return {"asset": result.data[0]}

@router.patch("/site-assets/{key}/toggle", dependencies=[Depends(verify_admin)])
def toggle_site_asset_active(key: str, supabase: Client = Depends(get_supabase)):
    """Toggle active/inactive on a banner without deleting it."""
    if key not in VALID_ASSET_KEYS:
        raise HTTPException(status_code=400, detail=f"Invalid key '{key}'")
    row = supabase.table("site_assets").select("active").eq("key", key).execute()
    if not row.data:
        raise HTTPException(status_code=404, detail=f"Asset '{key}' not configured yet")
    result = supabase.table("site_assets").update({"active": not row.data[0]["active"]}).eq("key", key).execute()
    return {"asset": result.data[0]}

@router.delete("/site-assets/{key}", dependencies=[Depends(verify_admin)])
def delete_site_asset(key: str, supabase: Client = Depends(get_supabase)):
    """Remove an asset slot entirely (clears the image)."""
    if key not in VALID_ASSET_KEYS:
        raise HTTPException(status_code=400, detail=f"Invalid key '{key}'")
    supabase.table("site_assets").delete().eq("key", key).execute()
    return {"deleted": True, "key": key}


# ── Purchase / Order Routes ────────────────────────────────────────────────────

@router.get("/purchases", dependencies=[Depends(verify_admin)])
def list_purchases(supabase: Client = Depends(get_supabase)):
    result = supabase.table("purchases").select("*").order("created_at", desc=True).execute()
    return {"purchases": result.data}

@router.get("/purchases/{purchase_id}", dependencies=[Depends(verify_admin)])
def get_purchase(purchase_id: str, supabase: Client = Depends(get_supabase)):
    result = supabase.table("purchases").select("*").eq("id", purchase_id).execute()
    if not result.data:
        raise HTTPException(status_code=404, detail="Purchase not found")
    return {"purchase": result.data[0]}