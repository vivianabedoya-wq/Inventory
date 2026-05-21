import streamlit as st
import pandas as pd
from app.views.charts.stockout_chart import show_stockout_section
from app.views.charts.orders_exceed_inventory_chart import show_demand_exceeds_stock_section
from app.views.charts.system_vs_physicall_count_table import show_inventory_comparison
from app.services.supabase_uploader import (
    fetch_restock_kpi_source,
    fetch_orders_exceed_inventory)
from app.services.dashboard_service import(
    fetch_stockout_items,
    fetch_categories,
    fetch_last_system_stock_date,
    fetch_last_physical_stock_info
)
from app.views.restock_manager import build_kpis
from app.views.charts.stock_status_dashboard_chart import show_out_of_stock_pie

STATUS_ORDER = ["Critical", "Reorder now", "Near", "Healthy"]

def overall_restock_status_from_kpis(kpis: dict) -> dict:
    def g(key):  
        v = kpis.get(key, 0)
        try:
            return int(v)
        except Exception:
            return 0

    critical = g("Critical")
    reorder  = g("Reorder now")
    near     = g("Near")
    healthy  = g("Healthy")

    urgent = critical + reorder

    def fmt_items(n):  
        return f"{n} item" + ("" if n == 1 else "s")

    if urgent > 0:
        return {
            "title":  "Need to Reorder",
            "value":  fmt_items(urgent),      
            "action": "- 🔴Needs Action",
            "delta-color": "normal"
        }
    if near > 0:
        return {
            "title":  "Near Minimum",
            "value":  fmt_items(near),
            "action": "🟠 Check",
            "delta-color": "off"
        }
    return {
        "title":  "Healthy",
        "value":  fmt_items(healthy),
        "action": "🟢 No action need it",
        "delta-color": "normal"
    }

def get_items_out_of_stock_status() -> pd.DataFrame:
    items = fetch_stockout_items()       
    if not items:
        return pd.DataFrame(columns=["category", "items_out_of_stock"])

    cats = fetch_categories() or []     

    df = pd.DataFrame(items)
    df["on_hand"] = pd.to_numeric(df.get("on_hand"), errors="coerce").fillna(0)
    df = df[df["on_hand"] <= 0]

    if cats:
        cdf = pd.DataFrame(cats).rename(columns={"id": "category_id", "name": "category"})
        df = df.merge(cdf[["category_id", "category"]], on="category_id", how="left")
    else:
        df["category"] = None

    df["category"] = df["category"].fillna("No Category")

    out = (
        df.groupby("category", dropna=False)
          .size()
          .rename("items_out_of_stock")
          .sort_values(ascending=False)
          .reset_index()
    )
    return out

def get_items_in_so_with_insuficient_stock(empty_return=""):
    data = fetch_orders_exceed_inventory()
    if not data:
        return empty_return

    df = pd.DataFrame(data)
    df["on_hand"] = pd.to_numeric(df.get("on_hand"), errors="coerce").fillna(0)
    df["on_so"]   = pd.to_numeric(df.get("on_so"),   errors="coerce").fillna(0)

    n = int((df["on_so"] > df["on_hand"]).sum())
    return n if n > 0 else empty_return  

def show_dashboard():
    st.title("Dashboard")

    t1, t2 = st.columns(2)
    with t1:
        st.subheader("Summary")
    with t2:
        st.subheader("Inventory Status")

    data = fetch_restock_kpi_source()
    df, kpis = build_kpis(data)
    df["status"] = pd.Categorical(df["status"], categories=STATUS_ORDER, ordered=True)

    status = overall_restock_status_from_kpis(kpis)  # tu helper
    stock_status = get_items_out_of_stock_status()
    insuficient = get_items_in_so_with_insuficient_stock()

    col_left, col_right = st.columns([1, 1])   

    # Left Part
    with col_left:
        st.metric(
            label=status["title"],
            value=status["value"],
            delta=status["action"],
            delta_color=status.get("delta-color", "normal"),
            border=True,
        )

        st.markdown("<div style='height: 8px'></div>", unsafe_allow_html=True)

        title = "Insuficient Items in SO"
        value = f"{insuficient} Items" if insuficient else "0 Items"
        delta = "🟢 No Action Need It" if not insuficient else "- 🔴 Check This Out"
        color = "normal" 

        st.metric(
            label=title,
            value=value,
            delta=delta,
            delta_color=color,
            border=True,
        )

        col_a, col_b = st.columns(2, border= True)

        with col_a:
            last_system = fetch_last_system_stock_date()
            st.caption("Most Recent Systemn Inventory Date")
            st.markdown(last_system)

        with col_b:
            last_physical = fetch_last_physical_stock_info()
            st.caption("Most Recent Physical Inventory Date")
            st.markdown(last_physical)

    # Right Part
    with col_right:
        show_out_of_stock_pie(stock_status, figsize=(6, 6), fill=False)

    # Outside 
    show_inventory_comparison()
    
