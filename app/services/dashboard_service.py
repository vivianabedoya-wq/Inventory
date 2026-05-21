import os, requests
import streamlit as st
from dotenv import load_dotenv
from datetime import datetime
from urllib.parse import quote

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}

def fetch_stockout_items():
    url = f"{SUPABASE_URL}/rest/v1/Stockout_Items?select=item_id,description,on_hand,category_id"
    response = requests.get(url, headers=HEADERS)
    if response.ok:
        return response.json()
    else:
        st.error("❌ Out-of-stock data could not be obtained.")
        st.text(f"🔴 Supabase response: {response.status_code} - {response.text}")
        return []

def fetch_categories():
    url = f"{SUPABASE_URL}/rest/v1/Item_Categories?select=id,name"
    response = requests.get(url, headers=HEADERS)
    if response.ok:
        return response.json()
    else:
        return []
    
def fetch_last_system_stock_date() -> str | None:
    url = (
        f"{SUPABASE_URL}/rest/v1/System_Stock"
        "?select=updated_at::date"
        "&order=updated_at.desc.nullslast"
        "&limit=1"
    )
    r = requests.get(url, headers=HEADERS, timeout=15)
    if not r.ok:
        st.error(f"Supabase {r.status_code}: {r.text}")
        return None
    rows = r.json()
    return rows[0]["updated_at"] if rows else None

def fetch_last_physical_stock_info() -> str | None:
    url = (
        f"{SUPABASE_URL}/rest/v1/Stock_Counts"
        "?select=created_at::date"
        "&order=created_at.desc.nullslast"
        "&limit=1"
    )
    r = requests.get(url, headers=HEADERS, timeout=15)
    if not r.ok:
        st.error(f"Supabase {r.status_code}: {r.text}")
        return None
    rows = r.json()
    return rows[0]["created_at"] if rows else None

