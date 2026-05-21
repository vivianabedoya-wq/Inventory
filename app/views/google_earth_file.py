from __future__ import annotations
import os
import io
import hashlib
import pandas as pd
import streamlit as st

from datetime import datetime
from typing import Any, Dict, Tuple, List
from app.services.google_earth_service import (
    make_supabase,
    storage_download_bytes,
    storage_upload_bytes,
    storage_signed_url,
)

def _safe_stretch_button(label: str, key: str, button_type: str | None = None):
    """
    Create a full-width button across Streamlit versions.

    Tries in order:
    1) New API: st.button(..., width="stretch", type=button_type)
    2) Old API with type: st.button(..., use_container_width=True, type=button_type)
    3) Old API without type: st.button(..., use_container_width=True)

    Returns the boolean click state.
    """
    try:
        return st.button(label, key=key, width="stretch", type=button_type)
    except TypeError:
        try:
            return st.button(label, key=key, use_container_width=True, type=button_type)
        except TypeError:
            return st.button(label, key=key, use_container_width=True)


REQ_COLS = [
    "Id",
    "Has Fence on Google Earth",
    "Google Earth Last Picture At",
    "Google Earth Last Checked At",
]

YES_SET = {"yes", "y", "true", "1"}
NO_SET  = {"no", "n", "false", "0"}

def _normalize_yes_no(val: Any) -> str:
    if val is None:
        return ""
    s = str(val).strip().lower()
    if s == "":
        return ""
    if s in YES_SET:
        return "Yes"
    if s in NO_SET:
        return "No"
    return ""

def _is_effectively_empty(val: Any) -> bool:
    if val is None:
        return True
    s = str(val).strip().lower()
    return s in {"", "nan", "none", "null", "nat", "-"}

def _parse_excel_serial(s: str):
    try:
        f = float(s)
        days = int(f)
        origin = datetime(1899, 12, 30)
        return (origin + pd.Timedelta(days=days)).date()
    except Exception:
        return None

def _parse_us_date(val: Any):
    if _is_effectively_empty(val):
        return None

    s = str(val).strip()

    try:
        return datetime.strptime(s, "%m/%d/%Y").date()
    except Exception:
        pass

    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        pass

    d = _parse_excel_serial(s)
    if d is not None:
        return d

    return None

def _require_columns(df: pd.DataFrame):
    missing = [c for c in REQ_COLS if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

def _dedupe_last_wins(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["Id"] = df["Id"].astype(str).str.strip()
    df = df[df["Id"] != ""]
    return df.drop_duplicates(subset=["Id"], keep="last").reset_index(drop=True)

def _row_hash(row: pd.Series) -> str:
    lp = row["last_picture"].isoformat() if pd.notnull(row["last_picture"]) else ""
    lc = row["last_checked"].isoformat() if pd.notnull(row["last_checked"]) else ""
    sig = f"{row['has_fence']}|{lp}|{lc}"
    return hashlib.md5(sig.encode("utf-8")).hexdigest()

def normalize_excel_bytes(
    xlsx_bytes: bytes,
    collect_invalid_samples: bool = True,
    max_samples_per_column: int = 20,
) -> Tuple[pd.DataFrame, Dict[str, int], Dict[str, List[Dict[str, Any]]]]:

    df_raw = pd.read_excel(io.BytesIO(xlsx_bytes), dtype=str)
    _require_columns(df_raw)

    for c in REQ_COLS:
        if c in df_raw.columns:
            df_raw[c] = df_raw[c].astype(str).str.strip()

    total_rows = len(df_raw)
    df = _dedupe_last_wins(df_raw)
    after_id = len(df)
    discarded_empty_id = total_rows - after_id

    df["Has Fence on Google Earth"] = df["Has Fence on Google Earth"].apply(_normalize_yes_no)

    invalid_picture = 0
    invalid_checked = 0
    pic_samples: List[Dict[str, Any]] = []
    chk_samples: List[Dict[str, Any]] = []

    def _norm_pic(v, row_id):
        nonlocal invalid_picture, pic_samples
        d = _parse_us_date(v)
        if d is None and not _is_effectively_empty(v):
            invalid_picture += 1
            if collect_invalid_samples and len(pic_samples) < max_samples_per_column:
                pic_samples.append({"Id": row_id, "Raw Value": v})
        return d

    def _norm_chk(v, row_id):
        nonlocal invalid_checked, chk_samples
        d = _parse_us_date(v)
        if d is None and not _is_effectively_empty(v):
            invalid_checked += 1
            if collect_invalid_samples and len(chk_samples) < max_samples_per_column:
                chk_samples.append({"Id": row_id, "Raw Value": v})
        return d

    ids = df["Id"].tolist()
    pic_raw = df["Google Earth Last Picture At"].tolist()
    chk_raw = df["Google Earth Last Checked At"].tolist()

    last_picture_norm = []
    last_checked_norm = []
    for row_id, pic_v, chk_v in zip(ids, pic_raw, chk_raw):
        last_picture_norm.append(_norm_pic(pic_v, row_id))
        last_checked_norm.append(_norm_chk(chk_v, row_id))

    df_out = pd.DataFrame({
        "id": df["Id"],
        "has_fence": df["Has Fence on Google Earth"],
        "last_picture": last_picture_norm,
        "last_checked": last_checked_norm,
    })

    df_out["row_hash"] = df_out.apply(_row_hash, axis=1)

    metrics = {
        "total_rows_input": total_rows,
        "rows_after_id_filter": after_id,
        "discarded_empty_id": discarded_empty_id,
        "invalid_date_picture": invalid_picture,
        "invalid_date_checked": invalid_checked,
    }

    samples = {
        "invalid_picture_samples": pic_samples,
        "invalid_checked_samples": chk_samples,
    }
    return df_out, metrics, samples

def _date_or_none(x):
    return None if pd.isna(x) else x

def compare_new_vs_baseline(new_df: pd.DataFrame, base_df: pd.DataFrame) -> Dict[str, Any]:

    new_idx = new_df.set_index("id")
    base_idx = base_df.set_index("id") if len(base_df) else pd.DataFrame(columns=new_idx.columns).set_index(pd.Index([]))

    new_ids = set(new_idx.index)
    base_ids = set(base_idx.index)

    added_ids = sorted(new_ids - base_ids)
    common_ids = new_ids & base_ids

    modified_ids = []
    for i in common_ids:
        a = new_idx.loc[i]
        b = base_idx.loc[i]
        a_tuple = (a["has_fence"], _date_or_none(a["last_picture"]), _date_or_none(a["last_checked"]))
        b_tuple = (b["has_fence"], _date_or_none(b["last_picture"]), _date_or_none(b["last_checked"]))
        if a_tuple != b_tuple:
            modified_ids.append(i)

    unchanged_ids = sorted(common_ids - set(modified_ids))

    return {
        "new_records": len(added_ids),
        "modified_records": len(modified_ids),
        "unchanged_records": len(unchanged_ids),
        "total_new": len(new_df),
        "total_baseline": len(base_df),
        "added_ids_sample": added_ids[:10],
        "modified_ids_sample": modified_ids[:10],
    }

def decide_replace(summary: Dict[str, Any]) -> bool:
    return (summary["new_records"] + summary["modified_records"]) > 0

def run_compare_flow(new_file_bytes: bytes, baseline_file_bytes: bytes | None) -> Dict[str, Any]:

    new_df, new_metrics, new_samples = normalize_excel_bytes(new_file_bytes, collect_invalid_samples=True)

    if baseline_file_bytes is None:
        base_df = pd.DataFrame(columns=["id", "has_fence", "last_picture", "last_checked", "row_hash"])
        base_metrics = {"total_rows_input": 0}
    else:
        base_df, base_metrics, _ = normalize_excel_bytes(baseline_file_bytes, collect_invalid_samples=False)

    summary = compare_new_vs_baseline(new_df, base_df)
    replace = decide_replace(summary)

    return {
        "summary": summary,
        "replace_baseline": replace,
        "new_metrics": new_metrics,
        "baseline_metrics": base_metrics,
        "invalid_samples": new_samples,
    }

# UI

BUCKET = "google_earth_files"
BASELINE_KEY = "current/latest.xlsx"

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

def _guard_creds():
    if not SUPABASE_URL or not SUPABASE_KEY:
        st.error("Supabase credentials not found. Please set SUPABASE_URL and SUPABASE_KEY.")
        st.stop()

def show_google_form():
    st.title("Google Earth File Control")
    st.caption("Upload the NEW .xlsx, compare with the current baseline, and replace it if changes are detected.")

    _guard_creds()
    client = make_supabase(SUPABASE_URL, SUPABASE_KEY)

    with st.expander("Current baseline (download link)"):
        url = storage_signed_url(client, BUCKET, BASELINE_KEY, expires_sec=900)
        if url:
            st.markdown(f"[Download current/latest.xlsx]({url})")
        else:
            st.info("No baseline found yet.")

    uploaded = st.file_uploader("Upload NEW Google Earth file (.xlsx)", type=["xlsx"])
    auto_replace = st.checkbox("Auto-replace baseline when changes are detected", value=True)

    if uploaded:
        st.info(f"Processing file: **{uploaded.name}**")
        new_bytes = uploaded.read()

        baseline_bytes = storage_download_bytes(client, BUCKET, BASELINE_KEY)

        with st.spinner("Comparing with current baseline..."):
            result = run_compare_flow(new_file_bytes=new_bytes, baseline_file_bytes=baseline_bytes)

        summary = result["summary"]

        st.subheader("Comparison Summary")
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("New records", summary["new_records"])
        c2.metric("Modified records", summary["modified_records"])
        c3.metric("Unchanged records", summary["unchanged_records"])
        c4.metric("Total (NEW)", summary["total_new"])
        c5.metric("Total (BASELINE)", summary["total_baseline"])

        with st.expander("Details"):
            st.write("**Added IDs:**", summary["added_ids_sample"])
            st.write("**Modified IDs:**", summary["modified_ids_sample"])

        changes = summary["new_records"] + summary["modified_records"]
        if changes == 0:
            st.success("No changes detected. Baseline remains the same.")
        else:
            st.warning("Changes detected.")
            if auto_replace:
                storage_upload_bytes(client, BUCKET, BASELINE_KEY, new_bytes, upsert=True)
                st.success("Baseline updated automatically (current/latest.xlsx).")
            else:
                if _safe_stretch_button("Replace baseline with NEW file", key="replace_btn", button_type="primary"):
                    storage_upload_bytes(client, BUCKET, BASELINE_KEY, new_bytes, upsert=True)
                    st.success("Baseline updated (current/latest.xlsx).")
                else:
                    st.info("Baseline not replaced yet. Click the button to proceed.")
    else:
        st.info("Upload the NEW .xlsx file to start the comparison.")
