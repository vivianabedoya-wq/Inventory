import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import requests
import os
from dotenv import load_dotenv

load_dotenv()
RED=os.getenv("RED")
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

def show_stockout_section():
    st.subheader("Items out of Stock")

    data = fetch_stockout_items()
    if not data:
        return

    df = pd.DataFrame(data)
    df["on_hand"] = pd.to_numeric(df["on_hand"], errors="coerce")

    categories = fetch_categories()
    category_map = {cat["id"]: cat["name"] for cat in categories}

    df["category_name"] = df["category_id"].map(category_map)

    selected_category = st.selectbox("🔍 Filter by Category", ["All"] + sorted(df["category_name"].dropna().unique().tolist()))
    if selected_category != "All":
        df = df[df["category_name"] == selected_category]

    if df.empty:
        st.info("✅ There are no out-of-stock items for this category..")
        return

    df = df.sort_values(by="on_hand")

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=df["on_hand"],
        y=df["description"],
        orientation='h',
        marker=dict(color="RED"),
        hovertemplate='%{x:.0f} units'
    ))

    fig.add_shape(
        type="line",
        x0=0, x1=0,
        y0=-0.5, y1=len(df) - 0.5,
        line=dict(color="white", dash="dash"),
        layer="below"
    )

    fig.add_shape(
        type="line",
        x0=min(df["on_hand"].min(), -1), x1=max(df["on_hand"].max(), 1),
        y0=len(df)-0.5, y1=len(df)-0.5,
        line=dict(color="white", width=2),
        layer="below"
    )
    fig.add_shape(
        type="line",
        x0=min(df["on_hand"].min(), -1), x1=min(df["on_hand"].min(), -1),
        y0=-0.5, y1=len(df)-0.5,
        line=dict(color="white", width=2),
        layer="below"
    )

    fig.update_xaxes(showgrid=True, gridcolor="gray", zeroline=True, zerolinecolor="white")
    fig.update_yaxes(showgrid=True, gridcolor="gray")

    fig.update_layout(
        title=f"Out of stock by item ({len(df)} items)",
        xaxis_title="Stock Quantities",
        yaxis_title="Description",
        yaxis=dict(autorange="reversed"),
        template="plotly_dark"
    )

    st.plotly_chart(fig, width="stretch")
