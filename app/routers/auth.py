"""
Auth router – Email/Password via Supabase

POST /auth/register   → create account
POST /auth/login      → get JWT
POST /auth/logout     → invalidate session
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr

from app.services.supabase_client import get_supabase

router = APIRouter()


class AuthRequest(BaseModel):
    email: EmailStr
    password: str


@router.post("/register", status_code=status.HTTP_201_CREATED)
def register(body: AuthRequest):
    db = get_supabase()
    res = db.auth.sign_up({"email": body.email, "password": body.password})
    if res.user is None:
        raise HTTPException(status_code=400, detail="Registration failed. Email may already be in use.")
    return {"message": "Account created. Check your email to confirm.", "user_id": str(res.user.id)}


@router.post("/login")
def login(body: AuthRequest):
    db = get_supabase()
    try:
        res = db.auth.sign_in_with_password({"email": body.email, "password": body.password})
    except Exception as e:
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    return {
        "access_token": res.session.access_token,
        "token_type": "bearer",
        "user_id": str(res.user.id),
        "email": res.user.email,
    }


@router.post("/logout")
def logout():
    db = get_supabase()
    db.auth.sign_out()
    return {"message": "Logged out."}