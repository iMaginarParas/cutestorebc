import os
from fastapi import APIRouter, HTTPException, Depends, Header
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from supabase import create_client, Client
from typing import Optional

def get_supabase() -> Client:
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "change-me")

def verify_admin(x_admin_token: str = Header(...)):
    if x_admin_token != ADMIN_SECRET:
        raise HTTPException(status_code=401, detail="Invalid admin token")
    return True

class ProductCreate(BaseModel):
    name: str
    description: Optional[str] = None
    price: int              # in paise
    image_url: Optional[str] = None
    active: bool = True

class ProductUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[int] = None
    image_url: Optional[str] = None
    active: Optional[bool] = None

router = APIRouter(prefix="/admin", tags=["admin"])

@router.get("/products", dependencies=[Depends(verify_admin)])
def list_products(supabase: Client = Depends(get_supabase)):
    result = supabase.table("products").select("*").order("created_at", desc=True).execute()
    return {"products": result.data}

@router.post("/products", dependencies=[Depends(verify_admin)], status_code=201)
def create_product(body: ProductCreate, supabase: Client = Depends(get_supabase)):
    result = supabase.table("products").insert({
        "name": body.name, "description": body.description,
        "price": body.price, "image_url": body.image_url, "active": body.active,
    }).execute()
    return {"product": result.data[0]}

@router.patch("/products/{product_id}", dependencies=[Depends(verify_admin)])
def update_product(product_id: str, body: ProductUpdate, supabase: Client = Depends(get_supabase)):
    updates = body.model_dump(exclude_none=True)
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

@router.get("/purchases", dependencies=[Depends(verify_admin)])
def list_purchases(supabase: Client = Depends(get_supabase)):
    result = supabase.table("purchases").select("*").order("created_at", desc=True).execute()
    return {"purchases": result.data}