import streamlit as st
from app.views.charts.stockout_chart import show_stockout_section
from app.views.charts.orders_exceed_inventory_chart import show_demand_exceeds_stock_section
from app.views.charts.system_vs_physicall_count_table import show_inventory_comparison
def show_dashboard():
    st.title("Inventory Dashboard")
    col1, col2 = st.columns(2)

    with col1:       
        show_stockout_section()

    with col2:
        show_demand_exceeds_stock_section()

    show_inventory_comparison()
    
