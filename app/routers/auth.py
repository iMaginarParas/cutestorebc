"""
Auth router – thin wrapper around Supabase Google OAuth.

Flow:
  1. Frontend calls  GET /auth/login/google  → redirects to Google via Supabase
  2. Google redirects back to Supabase, which issues a JWT
  3. Supabase redirects browser to your frontend with #access_token in the URL
  4. Frontend stores the token and sends it as `Authorization: Bearer <token>`
     on every protected API call.

No server-side session needed – Supabase handles it all.
"""

from fastapi import APIRouter
from fastapi.responses import RedirectResponse
from app.config import settings

router = APIRouter()


@router.get("/login/google")
def login_google():
    """
    Redirect the user to Supabase's Google OAuth endpoint.
    Supabase will handle the Google OAuth dance and redirect
    back to your frontend with a JWT.
    """
    supabase_google_url = (
        f"{settings.supabase_url}/auth/v1/authorize"
        f"?provider=google"
        f"&redirect_to={settings.frontend_success_url}"
    )
    return RedirectResponse(url=supabase_google_url)


@router.get("/status")
def auth_status():
    return {
        "message": "Send your Supabase JWT as `Authorization: Bearer <token>`",
        "google_login": f"{settings.app_base_url}/auth/login/google",
    }
