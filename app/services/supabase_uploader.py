import os, requests, uuid
import streamlit as st
import urllib.parse
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

# Get user name 
def get_user_name_by_email(email: str) -> str | None:
    url = f"{SUPABASE_URL}/rest/v1/Users?email=eq.{email}&select=name"
    response = requests.get(url, headers=HEADERS)

    if response.ok:
        data = response.json()
        if data and "name" in data[0]:
            return data[0]["name"]
    return None

# Get user id
def get_user_id_by_email(email: str) -> str | None:
    url = f"{SUPABASE_URL}/rest/v1/Users?email=eq.{email}&select=id"
    response = requests.get(url, headers=HEADERS)

    if response.ok:
        data = response.json()
        if data and "id" in data[0]:
            return data[0]["id"]
    return None

def get_or_create_category(category_name):
    name = str(category_name).strip() if category_name else ""

    if name.lower() in ["", "nan", "none"]:
        name = "No Category"

    response = requests.get(
        f"{SUPABASE_URL}/rest/v1/Item_Categories?name=eq.{name}",
        headers=HEADERS
    )
    if response.ok and response.json():
        return response.json()[0]["id"]

    response = requests.post(
        f"{SUPABASE_URL}/rest/v1/Item_Categories",
        headers=HEADERS,
        json={"name": name}
    )

    try:
        if response.ok:
            return response.json()[0]["id"]
        else:
            print(f"❌ Error creating category: {name} → {response.text}")
            return None
    except Exception as e:
        print(f"❌ Error parsing response when creating category '{name}': {e}")
        return None

def fetch_all_categories():
    url = f"{SUPABASE_URL}/rest/v1/Item_Categories?select=id,name&order=name.asc"
    r = requests.get(url, headers=HEADERS)
    return r.json() if r.ok else []

def get_latest_stock_items(categories: list[str] | None = None):
    base = f"{SUPABASE_URL}/rest/v1/Latest_Item_Stock?select=name,description,category_name"

    if categories:
        vals = ",".join([f"%22{c}%22" for c in categories if c and str(c).strip()])
        url = f"{base}&category_name=in.({vals})"
    else:
        url = base

    r = requests.get(url, headers=HEADERS, timeout=30)
    if r.ok:
        return r.json()
    else:
        print(f"❌ Error fetching latest stock items: {r.status_code} - {r.text}")
        return []

def get_item_by_name(name):
    encoded_name = urllib.parse.quote(name)
    url = f"{SUPABASE_URL}/rest/v1/Items?name=ilike.{encoded_name}"

    response = requests.get(url, headers=HEADERS)

    try:
        if response.ok:
            data = response.json()
            if data:
                return data[0]
            else:
                print(f"ℹ️ Item '{name}' not found (empty response).")
        else:
            print(f"❌ Error querying item '{name}': {response.status_code} - {response.text}")
    except Exception as e:
        print(f"❌ Exception parsing item response '{name}': {e}")

    return None

def insert_item(item_data):
    try:
        response = requests.post(
            f"{SUPABASE_URL}/rest/v1/Items",
            headers=HEADERS,
            json=item_data
        )

        if response.ok:
            try:
                return response.json()[0]
            except Exception as parse_error:
                print(f"❌ JSON parsing error for item {item_data['name']}: {parse_error}")
                print(f"🔴 Raw response: {response.text}")
                return None
        else:
            print(f"❌ Error creating item: {item_data['name']}")
            print(f"📦 Payload: {item_data}")
            print(f"🔴 Supabase response: {response.status_code} - {response.text}")
            return None

    except Exception as e:
        print(f"❌ Exception while creating item {item_data['name']}: {e}")
        return None

def insert_stock(stock_data):
    response = requests.post(
        f"{SUPABASE_URL}/rest/v1/System_Stock",
        headers=HEADERS,
        json=stock_data
    )
    if not response.ok:
        print(f"❌ Error inserting stock for item_id {stock_data['item_id']}")
        print(f"📦 Payload: {stock_data}")
        print(f"🔴 Supabase response: {response.status_code} - {response.text}")

def upload_inventory_data(items_data: list):
    total = len(items_data)

    for idx, row in enumerate(items_data):
        name = str(row.get("Name", "")).strip()
        category = str(row.get("Category", "")).strip()
        description = str(row.get("Description", "")).strip()

        if not name:
            st.warning(f"⚠️ Empty name in row {idx+1}. Skipping.")
            continue

        category_id = get_or_create_category(category)
        if not category_id:
            st.warning(f"⚠️ Could not get/create category for '{category}'")
            continue

        existing = get_item_by_name(name)
        if not existing:
            item = insert_item({
                "name": name,
                "category_id": category_id,
                "description": description
            })
        else:
            item = existing

        item_id = item.get("id") if item else None
        try:
            item_id = str(uuid.UUID(str(item_id)))  # asegura que sea UUID válido
        except Exception:
            st.warning(f"⚠️ Invalid ID for '{name}': {item_id}")
            continue

        stock_payload = {
            "item_id": item_id,
            "on_hand": row.get("On Hand", 0),
            "available": row.get("Available", 0),
            "on_so": row.get("On SO", 0),
            "on_po": row.get("On PO", 0)
        }

        response = requests.post(
            f"{SUPABASE_URL}/rest/v1/System_Stock",
            headers=HEADERS,
            json=stock_payload
        )

        if not response.ok:
            st.warning(f"❌ Error inserting stock for '{name}'")
            print(f"📦 Payload: {stock_payload}")
            print(f"🔴 Supabase response: {response.status_code} - {response.text}")
        else:
            print(f"✅ Stock inserted for {name}")

    st.success("✅ Inventory loaded successfully.")

def get_item_id_by_name(name):
    item = get_item_by_name(name)
    return item["id"] if item else None

def create_stock_count_entry(date, responsable, categories: list = None):
    payload = {
        "count_date": date,
        "responsable": responsable,
        "categories": categories or []
    }
    response = requests.post(
        f"{SUPABASE_URL}/rest/v1/Stock_Counts",
        headers=HEADERS,
        json=payload
    )
    if response.ok:
        return response.json()[0]["id"]
    else:
        print("❌ Error creating stock count entry.")
        return None

def insert_stock_count_item(stock_count_id, item_id, quantity):
    payload = {
        "stock_count_id": stock_count_id,
        "item_id": item_id,
        "counted_quantity": quantity
    }
    response = requests.post(
        f"{SUPABASE_URL}/rest/v1/Stock_Count_Items",
        headers=HEADERS,
        json=payload
    )
    if not response.ok:
        print(f"❌ Error inserting count for item_id {item_id}")

def upload_physical_count(parsed_data: list):
    if not parsed_data:
        print("⚠️ No data to upload.")
        return

    first_row = parsed_data[0]
    date = first_row["count_date"]
    responsable = first_row["responsable"]
    categories = []

    stock_count_id = create_stock_count_entry(date, responsable, categories)

    if not stock_count_id:
        return

    for row in parsed_data:
        item_id = get_item_id_by_name(row["name"])
        if item_id:
            insert_stock_count_item(stock_count_id, item_id, row["actual_count"])
        else:
            print(f"⚠️ Item '{row['name']}'not found in the database.")

## For Physical Counts

def insert_physical_count(data: dict):
    url = f"{SUPABASE_URL}/rest/v1/Stock_Counts"
    
    custom_headers = HEADERS.copy()
    custom_headers["Prefer"] = "return=representation"

    print("📨 Sending stock count:")
    print("Payload:", data)

    response = requests.post(url, headers=custom_headers, json=data)

    try:
        result = response.json()
    except Exception as e:
        print("❌ JSON parsing error:", str(e))
        print("Raw text:", response.text)
        return None

    if response.ok and isinstance(result, list) and len(result) > 0:
        print("✅ Supabase response:", result[0])
        return result[0]
    else:
        print("❌ Supabase error:")
        print(f"Status code: {response.status_code}")
        print(f"Response text: {response.text}")
        return None
   
def insert_physical_count_items(items: list) -> bool:
    
    url = f"{SUPABASE_URL}/rest/v1/Stock_Count_Items"

    headers = dict(HEADERS)
    prefer = headers.get("Prefer", "")
    if "return=" not in prefer:
        headers["Prefer"] = (prefer + ",return=representation").strip(",")
    headers["Content-Type"] = "application/json"
    resp = requests.post(url, headers=headers, json=items)

    if resp.ok:
        return True

    st.error("❌ Error inserting physical count items.")
    return False

def fetch_latest_stock_items():
    url = f"{SUPABASE_URL}/rest/v1/Latest_Item_Stock?select=name,description,category_name"
    response = requests.get(url, headers=HEADERS)
    if response.ok:
        return response.json()
    else:
        print(f"❌ Error fetching latest stock items: {response.status_code} - {response.text}")
        return []

def insert_physical_count_categories(data: list):
    url = f"{SUPABASE_URL}/rest/v1/Stock_Count_Item_Categories"
    response = requests.post(url, headers=HEADERS, json=data)

    if response.ok:
        return True
    else:
        print("❌ Failed to insert categories:")
        print("Payload:", data)
        print(f"Status: {response.status_code} - {response.text}")
        return False

def get_all_categories():
    url = f"{SUPABASE_URL}/rest/v1/Item_Categories?select=id,name"
    response = requests.get(url, headers=HEADERS)
    if response.ok:
        return response.json()
    else:
        print(f"❌ Failed to fetch categories: {response.status_code} - {response.text}")
        return []

#System VS Physicall Count

def fetch_inventory_comparison():
    url = f"{SUPABASE_URL}/rest/v1/Inventory_Comparison?select=*"
    response = requests.get(url, headers=HEADERS)
    if response.ok:
        return response.json()
    else:
        print("❌ Error fetching Inventory_Comparison")
        print("Status:", response.status_code)
        print("Response:", response.text)
        return []

def fetch_orders_exceed_inventory():
    url = f"{SUPABASE_URL}/rest/v1/Orders_Exceed_Inventory?select=item_id,description,on_hand, on_so,category_id"
    response = requests.get(url, headers=HEADERS)
    if response.ok:
        return response.json()
    else:
        print("❌ Error fetching Orders_Exceed_Inventory")
        print("Status:", response.status_code)
        print("Response:", response.text)
        return []


#Restock Options

#KPI's

def fetch_restock_kpi_source():
    url = f"{SUPABASE_URL}/rest/v1/restock_kpi_source"

    response = requests.get(url, headers=HEADERS)
    return response.json() if response.ok else []


def insert_restock_qt(data: list):
    url = f"{SUPABASE_URL}/rest/v1/Restock"
    response = requests.post(url, headers=HEADERS, json=data)

    if response.ok:
        return True
    else:
        print("❌ Failed to insert restock quantities:")
        print("Payload:", data)
        print(f"Status: {response.status_code} - {response.text}")
        return False