import os
from dotenv import load_dotenv
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware  # NEW
from starlette.middleware.sessions import SessionMiddleware
from app.routes.auth import router as auth_router

env_path = Path(__file__).resolve().parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

app = FastAPI(title="SFR GB API", version="1.0.0")

FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "")
FRONTEND_ORIGIN_ALT = os.getenv("FRONTEND_ORIGIN_ALT", "")
allow_origins = [o for o in [FRONTEND_ORIGIN, FRONTEND_ORIGIN_ALT] if o]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SECRET_KEY = os.getenv("SECRET_KEY", "change-me")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY)

app.include_router(auth_router)

@app.get("/healthz")
def healthz():
    return {"status": "ok"}

@app.get("/")
def root():
    return {"service": "sfr-gb-backend", "ok": True}
