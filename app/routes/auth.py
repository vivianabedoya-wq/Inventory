from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, HTMLResponse
from authlib.integrations.starlette_client import OAuth
from dotenv import load_dotenv
from pathlib import Path
import os
import requests

load_dotenv()

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

BACKEND_URL = os.getenv("BACKEND_URL")
REDIRECT_URI = os.getenv("REDIRECT_URI", f"{BACKEND_URL}/auth/callback")
STREAMLIT_URL = os.getenv("STREAMLIT_URL", "http://localhost:8501")

for var, value in {
    "GOOGLE_CLIENT_ID": GOOGLE_CLIENT_ID,
    "GOOGLE_CLIENT_SECRET": GOOGLE_CLIENT_SECRET,
    "SUPABASE_URL": SUPABASE_URL,
    "SUPABASE_KEY": SUPABASE_KEY,
}.items():
    if not value:
        raise ValueError(f"❌ {var} no se está leyendo del .env")

oauth = OAuth()
oauth.register(
    name="google",
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)

router = APIRouter()

@router.get("/login")
async def login(request: Request):
    return await oauth.google.authorize_redirect(request, REDIRECT_URI)

@router.get("/auth/callback")
async def auth_callback(request: Request):
    token = await oauth.google.authorize_access_token(request)
    user_info = await oauth.google.userinfo(token=token)
    email = user_info.get("email")

    if not email:
        return RedirectResponse(url=f"{STREAMLIT_URL}/unauthorized")

    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    }

    r = requests.get(
        f"{SUPABASE_URL}/rest/v1/Users?email=eq.{email}&status=eq.active",
        headers=headers
    )

    if r.ok and r.json():
        return RedirectResponse(url=f"{STREAMLIT_URL}/?user={email}")
    else:
        return RedirectResponse(url=f"{STREAMLIT_URL}/unauthorized")

@router.get("/logout")
async def logout():
    return RedirectResponse(url=f"{STREAMLIT_URL}?logout=1")
