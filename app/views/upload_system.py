import streamlit as st
import tempfile, os
from app.services.excel_handler import parse_inventory_summary
from app.services.supabase_uploader import upload_inventory_data

def show_upload_system():
    st.subheader("📅 Upload System Inventory File")

    uploaded_file = st.file_uploader("Select the file InventorySummary.xlsx", type=["xlsx"])

    if uploaded_file:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            tmp.write(uploaded_file.read())
            temp_path = tmp.name

        try:
            items = parse_inventory_summary(temp_path)
            st.info(f"File uploaded with {len(items)} ítems.")

            if st.button("Upload to Supabase", key="upload_system_btn"):
                total = len(items)
                
                bar = st.progress(0)

                for idx, item in enumerate(items, start=1):
                    
                    upload_inventory_data([item])
                    bar.progress(int(idx / total * 100))

                st.success("✅ Inventory loaded successfully.")
        except Exception as e:
            st.error(f"❌ Error: {str(e)}")
        finally:
            os.unlink(temp_path)
