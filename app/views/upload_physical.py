import streamlit as st
import pandas as pd
import tempfile
import os
from dotenv import load_dotenv
from datetime import datetime
from io import BytesIO
from openpyxl.styles import Font, Border, Side
from app.services.supabase_uploader import (
    insert_physical_count,
    insert_physical_count_items,
    fetch_latest_stock_items,
    get_item_by_name,
    insert_physical_count_categories,
    get_all_categories
)
from app.services.excel_handler import parse_physical_count



# ---------- Utils ----------

def coerce_note(v) -> str:
    """Force Notes to a string; if null/empty/<=1 char -> ' ?'."""
    try:
        if pd.isna(v):
            return " "
    except Exception:
        pass
    s = str(v).replace("\u00a0", " ").strip()  # remove NBSP and trim
    if s.lower() in ("", "nan", "none", "null", "nat") or len(s) <= 1:
        return " "
    return s


# ---------- Download template ----------

def generate_physical_inventory_template(items: list, included_categories: list[str]) -> bytes:
    df = pd.DataFrame(items)

    rename_map = {"category_name": "Category", "name": "Name", "description": "Description"}
    df = df.rename(columns=rename_map)

    # Columnas finales (incluye Notes)
    df = df[["Category", "Name", "Description"]]
    df["Counted"] = ""
    df["Notes"] = ""

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="PhysicalCount", startrow=3)
        sheet = writer.sheets["PhysicalCount"]

        # Metadatos
        sheet["A1"] = "Count Date:"
        sheet["B1"] = ""
        sheet["A2"] = "Responsible:"
        sheet["B2"] = ""
        sheet["A3"] = "Included Categories:"
        sheet["B3"] = "; ".join(included_categories)

        # Formato
        thin = Border(left=Side(style="thin"), right=Side(style="thin"),
                      top=Side(style="thin"), bottom=Side(style="thin"))
        # Encabezados en negrita (fila 4 por startrow=3)
        for cell in sheet[4]:
            cell.font = Font(bold=True)
        # Bordes para datos (5 columnas: Category, Name, Description, Counted, Notes)
        max_row = 4 + len(df)
        for row in sheet.iter_rows(min_row=5, max_row=max_row, min_col=1, max_col=5):
            for cell in row:
                cell.border = thin

    output.seek(0)
    return output.getvalue()


# ---------- Processor (path) ----------

def process_uploaded_physical_file(path: str):
    st.info("🚀 Starting process_uploaded_physical_file...")

    try:
        # ---------- Read file ----------
        st.info("📂 Reading Excel file...")
        df = pd.read_excel(path, header=None)

        st.write("📄 File preview (safe types):")
        st.dataframe(df.head(6).astype("string"))

        # ---------- Metadata ----------
        st.info("🔎 Extracting metadata...")
        count_date = str(df.iloc[0, 1]).strip()
        responsable = str(df.iloc[1, 1]).strip()
        st.write(f"Raw count_date: {count_date}, Raw responsable: {responsable}")

        if not count_date or count_date.lower() == "nan":
            st.error("❌ 'Count Date' is missing in the file.")
            return
        if not responsable or responsable.lower() == "nan":
            st.error("❌ 'Responsible' is missing in the file.")
            return
        st.success(f"📅 Count Date: {count_date} | 👤 Responsible: {responsable}")

        # ---------- Headers ----------
        st.info("📝 Validating headers...")
        headers = [str(h).strip() for h in df.iloc[3].tolist()]
        expected = ["Category", "Name", "Description", "Counted", "Notes"]
        st.write(f"Headers found: {headers}")
        if headers != expected:
            st.error(f"❌ Column mismatch.\nExpected: {expected}\nFound: {headers}")
            return

        # ---------- Data slice ----------
        st.info("📊 Preparing data frame...")
        data_df = df.iloc[5:].copy()
        data_df.columns = expected

        # 1) Convertir TODO a texto y limpiar NBSP/espacios
        data_df = data_df.astype("string")
        for c in data_df.columns:
            data_df[c] = (data_df[c]
                          .str.replace("\u00a0", " ", regex=False)
                          .str.strip())

        # 2) Limpiar y convertir SOLO 'Counted' a número
        data_df["Counted"] = (data_df["Counted"]
                              .str.replace(r"[^\d\.\-]", "", regex=True)
                              .replace({"": None, "nan": None}))
        data_df["Counted"] = pd.to_numeric(data_df["Counted"], errors="coerce").fillna(0)

        # 3) Notas normalizadas
        data_df["Notes"] = data_df["Notes"].map(coerce_note)

        # 4) Mantener filas con Name real (ya todo es str)
        data_df = data_df[data_df["Name"].str.len() > 0]

        st.success("✅ Data cleaned (all text, Counted numeric)")
        st.write("📦 Parsed item data (after cleaning):")
        st.dataframe(data_df.head().astype("string"))

        # ---------- Insert header ----------
        st.info("📩 Inserting stock count header...")
        count_record = insert_physical_count({"count_date": count_date, "responsable": responsable})
        st.write("count_record returned:", count_record)

        if not count_record or not count_record.get("id"):
            st.error("❌ Could not create stock count record.")
            return
        count_id = count_record["id"]
        st.success(f"🆔 Stock count header created with id={count_id}")

        # ---------- Build items payload (ALWAYS include 'notes') ----------
        st.info("📦 Building payload for Stock_Count_Items (including 'notes')...")

        count_items = []
        missing = 0

        st.write("🧭 Columns in data_df:", list(data_df.columns))
        st.write("🔎 Sample Name/Notes before loop:")
        try:
            st.dataframe(data_df[["Name", "Notes"]].head(10).astype("string"))
        except Exception:
            st.dataframe(data_df.head(10).astype("string"))

        for idx, row in data_df.iterrows():
            name = row["Name"]
            counted = float(row["Counted"])  # ya es numérico seguro
            note_val = coerce_note(row.get("Notes", None))

            st.write(f"🔹 Row {idx} -> Name={name} | Counted={counted} | Notes={note_val}")

            item = get_item_by_name(name)
            if not item:
                missing += 1
                st.warning(f"⚠️ Item not found: {name}")
                continue

            payload_item = {
                "stock_count_id": count_id,
                "item_id": item["id"],
                "counted_qty": counted,
                "notes": note_val,     # 👈 siempre presente
            }
            count_items.append(payload_item)

        if missing:
            st.info(f"ℹ️ Skipped {missing} rows due to missing items.")
        st.success(f"📦 Built payload with {len(count_items)} items.")

        st.write("🧪 Sanity check (first 3 payload items):")
        st.json(count_items[:3])

        # ---------- Categories (LOGICA MANTENIDA) ----------
        st.info("📂 Extracting categories...")
        categories = (
            data_df["Category"]
            .dropna()
            .map(lambda x: str(x).strip())
            .replace({"nan": ""})
            .tolist()
        )
        categories = sorted({c for c in categories if c})
        count_categories = [{"stock_count_id": count_id, "category_name": cat} for cat in categories]
        st.write("Categories payload:", count_categories)

        st.info(f"🗂️ Uploading {len(count_categories)} categories...")
        if not insert_physical_count_categories(count_categories):
            st.warning("⚠️ Some categories could not be saved.")
        else:
            st.success("✅ Categories successfully uploaded.")

        # ---------- Upload items ----------
        st.info(f"📤 Uploading {len(count_items)} count items to Supabase...")
        ok = insert_physical_count_items(count_items)
        if ok:
            st.success("✅ Physical count items successfully uploaded.")
        else:
            st.error("❌ Failed to upload physical count items.")

    except Exception as e:
        import traceback
        st.error(f"❌ Error processing file: {str(e)}")
        st.code(traceback.format_exc())


# ---------- Main view (Streamlit UI) ----------

def show_upload_physical():
    st.subheader("📤 Upload Physical Count File")

    uploaded_file = st.file_uploader("Select the file with physical count", type=["xlsx"])

    if uploaded_file:

        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
            tmp.write(uploaded_file.read())
            temp_path = tmp.name

        try:
            df = pd.read_excel(temp_path, header=None)
            st.dataframe(df.head(6).astype("string"))

            # Extract metadata
            count_date = str(df.iloc[0, 1]).strip()
            responsable = str(df.iloc[1, 1]).strip()

            if not count_date or count_date.lower() == "nan":
                st.error("❌ 'Count Date' is missing in the file.")
                return
            if not responsable or responsable.lower() == "nan":
                st.error("❌ 'Responsible' is missing in the file.")
                return

            # Headers
            raw_headers = df.iloc[3].tolist()
            headers = [str(h).strip().lower() for h in raw_headers]
            expected_headers = ["category", "name", "description", "counted", "notes"]

            if headers != expected_headers:
                st.error(f"❌ Header mismatch.\nExpected: {expected_headers}\nFound: {headers}")
                return

            # ----- Data slice
            df_data = df.iloc[4:].copy()
            df_data.columns = expected_headers

            # Convertir TODO a texto y limpiar NBSP/espacios
            df_data = df_data.astype("string")
            for c in df_data.columns:
                df_data[c] = (df_data[c]
                              .str.replace("\u00a0", " ", regex=False)
                              .str.strip())

            # Counted -> número
            df_data = df_data.dropna(subset=["name", "counted"])
            df_data["counted"] = (df_data["counted"]
                                  .str.replace(r"[^\d\.\-]", "", regex=True)
                                  .replace({"": None, "nan": None}))
            df_data["counted"] = pd.to_numeric(df_data["counted"], errors="coerce").fillna(0)

            # Notes normalizado (siempre presente)
            df_data["notes"] = df_data["notes"].map(coerce_note)

            st.dataframe(df_data.head().astype("string"))

            # Insert header
            count_record = insert_physical_count({
                "count_date": count_date,
                "responsable": responsable
            })

            if not count_record or not count_record.get("id"):
                st.error("❌ Could not create stock count record.")
                return

            count_id = count_record["id"]
            count_items = []
            category_set = set()

            # Initialize progress
            total_steps = len(df_data) + 3  # Items + categories + inserts + final step
            progress = st.progress(0)
            status = st.empty()
            step = 0

            # Build items (incluye notes)
            for i, (_, row) in enumerate(df_data.iterrows(), 1):
                status.info(f"🔍 Matching item {i} of {len(df_data)}: {row['name']}")
                item = get_item_by_name(row["name"])
                if not item:
                    st.warning(f"⚠️ Item not found: {row['name']}")
                    continue
                count_items.append({
                    "stock_count_id": count_id,
                    "item_id": item["id"],
                    "counted_qty": float(row["counted"]),
                    "notes": coerce_note(row["notes"]),  # 👈 ahora viaja a Supabase
                })
                if row["category"]:
                    category_set.add(row["category"])
                step += 1
                progress.progress(step / total_steps)

            st.write("🧪 First 3 payload items (with notes):")
            st.json(count_items[:3])

            status.info(f"📤 Uploading {len(count_items)} items to Supabase...")
            items_ok = insert_physical_count_items(count_items)
            step += 1
            progress.progress(step / total_steps)

            # Categories -> match to ids
            status.info("🔎 Matching categories to IDs...")
            all_categories = get_all_categories()
            category_lookup = {
                c["name"].strip().lower(): c["id"]
                for c in all_categories
            }

            matched_categories = []
            for name in category_set:
                category_id = category_lookup.get(name.strip().lower())
                if category_id:
                    matched_categories.append({
                        "stock_count_id": count_id,
                        "category_id": category_id
                    })
                else:
                    st.warning(f"⚠️ Category not found in DB: {name}")
            step += 1
            progress.progress(step / total_steps)

            status.info(f"📁 Uploading {len(matched_categories)} categories...")
            category_ok = insert_physical_count_categories(matched_categories)
            step += 1
            progress.progress(min(step / total_steps, 1.0))  # Ensure 100% max

            if items_ok and category_ok:
                status.success("✅ Physical count and categories successfully uploaded.")
            elif items_ok:
                status.warning("⚠️ Items uploaded, but some categories were not found.")
            else:
                status.error("❌ Failed to upload physical count items.")

            progress.empty()  # Remove progress bar after completion

        except Exception as e:
            st.error(f"❌ Error processing file: {str(e)}")
        finally:
            os.unlink(temp_path)
