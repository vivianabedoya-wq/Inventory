import os
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

HEADERS = {
    "apikey": SUPABASE_KEY or "",
    "Authorization": f"Bearer {SUPABASE_KEY}" if SUPABASE_KEY else "",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}


def parse_us_date_to_iso(us_date_str: str) -> str | None:

    if not us_date_str or not us_date_str.strip():
        return None
    try:
        dt = datetime.strptime(us_date_str.strip(), "%m/%d/%Y")
        return dt.date().isoformat()
    except Exception:
        return None


def insert_lead_update(payload: dict) -> tuple[int, str | None]:

    if not SUPABASE_URL or not SUPABASE_KEY:
        return 0, "Supabase credentials are missing. Please set SUPABASE_URL and SUPABASE_KEY."

    url = f"{SUPABASE_URL}/rest/v1/Hubspot_Leads_Updates"

    try:
        resp = requests.post(url, headers=HEADERS, json=payload, timeout=30)
    except requests.RequestException as e:
        return 0, f"Network error while contacting Supabase: {e}"

    if resp.ok:
        try:
            data = resp.json()
            inserted_count = 1 if isinstance(data, dict) else len(data)
            return inserted_count, None
        except Exception:
            return 1, None

    text = resp.text
    status = resp.status_code
    return 0, f"Supabase error {status}: {text}"
