import io
import os
import json
import time
import logging
import traceback
import warnings
import gc
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import streamlit as st
from dotenv import load_dotenv


LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("leads_file_cleaner")

def slog(msg: str, level: str = "info", extra=None):

    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    
    log_msg = f"[{timestamp}] [leads-cleaner] {msg}"
    if extra:
        log_msg += f" | EXTRA: {extra}"
    
    print(log_msg, flush=True)
    getattr(logger, level.lower(), logger.info)(msg)

class step_log:

    def __init__(self, name: str):
        self.name = name
        self.t0 = None

    def __enter__(self):
        self.t0 = time.perf_counter()
        slog(f"STEP START: {self.name}")
        return self

    def __exit__(self, exc_type, exc, tb):
        dt = time.perf_counter() - self.t0
        if exc:
            slog(f"STEP ERROR: {self.name} after {dt:.3f}s :: {exc}", "error")
            slog("TRACEBACK:\n" + "".join(traceback.format_exception(exc_type, exc, tb)), "error")
        else:
            slog(f"STEP END:   {self.name} in {dt:.3f}s")
        return False

def create_session_with_retries():
    session = requests.Session()
    

    retry_strategy = Retry(
        total=3,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "PUT", "DELETE", "OPTIONS", "TRACE"],
        backoff_factor=1
    )
    
    adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=10, pool_maxsize=10)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    return session

def safe_dataframe_operation(func, *args, **kwargs):

    slog(f"Starting dataframe operation: {func.__name__}")
    
    try:
        result = func(*args, **kwargs)
        
        gc.collect()
            
        return result
    except Exception as e:
        slog(f"Operation failed: {e}", "error")
        raise

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

HEADERS = {
    "apikey": SUPABASE_KEY or "",
    "Authorization": f"Bearer {SUPABASE_KEY}" if SUPABASE_KEY else "",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}

GE_BUCKET = os.getenv("GE_BUCKET", "google_earth_files")
GE_LATEST_KEY = os.getenv("GE_LATEST_KEY", "current/latest.xlsx")
UPDATES_TABLE = "Hubspot_Leads_Updates"

slog(f"ENV CHECK: SUPABASE_URL set? {bool(SUPABASE_URL)} ; SUPABASE_KEY length={len(SUPABASE_KEY or '')} ; BUCKET={GE_BUCKET}")

def _today_date_str() -> str:
    utc_now = datetime.utcnow()
    teg_now = utc_now - timedelta(hours=6)
    return teg_now.strftime("%Y-%m-%d")

def _norm_id(val) -> str:
    if val is None:
        return ""
    s = str(val).strip()
    if s == "" or s.lower() in {"nan", "none", "null"}:
        return ""
    s_no_commas = s.replace(",", "")
    try:
        f = float(s_no_commas)
        if f.is_integer():
            return str(int(f))
    except Exception:
        pass
    if s_no_commas.isdigit():
        return str(int(s_no_commas))
    return s

def _fmt_mmddyyyy(val) -> str:
    s = "" if val is None else str(val).strip()
    if s == "" or s.lower() in {"nan", "null", "none"}:
        return ""
    dt = pd.to_datetime(s, errors="coerce", utc=False)
    if pd.isna(dt):
        return ""
    try:
        dt = dt.tz_localize(None)
    except Exception:
        pass
    return dt.strftime("%m/%d/%Y")

def _normalize_yes_no_ge(val: str) -> str:
    s = "" if val is None else str(val).strip().lower()
    if s in {"yes", "y", "true", "1"}:
        return "Yes"
    if s in {"no", "n", "false", "0"}:
        return "No"
    if s in {"", "nan", "none", "null"}:
        return ""
    return ""

def _parse_to_mmddyyyy_ge(val) -> str:
    if val is None:
        return ""
    if isinstance(val, (datetime, pd.Timestamp)):
        try:
            dt = pd.to_datetime(val).to_pydatetime().replace(tzinfo=None)
            return dt.strftime("%m/%d/%Y")
        except Exception:
            return ""
    s = str(val).strip()
    if s == "" or s.lower() in {"nan", "null", "none", "nat", "-"}:
        return ""
    try:
        return datetime.strptime(s, "%m/%d/%Y").strftime("%m/%d/%Y")
    except Exception:
        pass
    try:
        return datetime.strptime(s, "%Y-%m-%d").strftime("%m/%d/%Y")
    except Exception:
        pass
    try:
        f = float(s)
        days = int(f)
        if 1 <= days <= 60000:
            origin = datetime(1899, 12, 30)
            d = origin + pd.Timedelta(days=days)
            return d.strftime("%m/%d/%Y")
        return ""
    except Exception:
        return ""

DATETIME_COLS = [
    "LastActionAt", "LastEmailedAt", "ClosingDate", "ClosedLostAt", "CancelledAt",
    "EstimateCreatedAt", "EstimateModifiedAt", "CreatedAt", "ModifiedAt",
]
DATE_ONLY_COLS = [
    "CalendarEventAt", "CalendarEventEnd", "FollowUpDate", "ClosedWonAt",
    "Google Earth Last Picture At", "Google Earth Last Checked At",
]
PHONE_COLS = [
    "PreferredContactPhoneNumber", "WorkPhoneNumber", "CellPhoneNumber", "SmsPhoneNumber",
]
BEFORE_ZIPCODE = [
    "Has Fence on Google Earth", "Google Earth Last Picture At", "Google Earth Last Checked At",
]
AFTER_LEADSTATUS = [
    "Asked To Be Contacted On",
    "Asked Contact For Promos Date",
    "Asked Contact For Promos",
    "Asked Contact Next Year Date",
    "Asked Contact Next Year",
    "Asked For No Contact",
    "Eligible for Emails",
]
DEFAULTS_AFTER_LEADSTATUS = {
    "Asked To Be Contacted On": "",
    "Asked Contact For Promos Date": "",
    "Asked Contact For Promos": "No",
    "Asked Contact Next Year Date": "",
    "Asked Contact Next Year": "No",
    "Asked For No Contact": "No",
    "Eligible for Emails": "Yes",
}
SUPABASE_TO_FILE_COLS = {
    "asked_to_be_contacted_on": "Asked To Be Contacted On",
    "asked_contact_for_promos_date": "Asked Contact For Promos Date",
    "asked_contact_for_promos": "Asked Contact For Promos",
    "asked_contact_next_year_date": "Asked Contact Next Year Date",
    "asked_contact_next_year": "Asked Contact Next Year",
    "asked_for_no_contact": "Asked For No Contact",
    "eligible_for_emails": "Eligible for Emails",
}
SUPABASE_ID_FIELD = "lead"
SUPABASE_EMAIL_FIELD = "email"
COLUMN_ALIASES = {
    "Eligible For Emails": "Eligible for Emails",
    "Asked to be contacted on": "Asked To Be Contacted On",
    "Asked to Be Contacted On": "Asked To Be Contacted On",
    "Asked contact for promos date": "Asked Contact For Promos Date",
    "Asked contact next year date": "Asked Contact Next Year Date",
}

def normalize_column_names(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    rename_map = {old: new for old, new in COLUMN_ALIASES.items() if old in out.columns}
    if rename_map:
        out = out.rename(columns=rename_map)
    return out

def load_file(uploaded_file) -> Tuple[pd.DataFrame, Optional[str]]:

    file_bytes = uploaded_file.read()
    name = uploaded_file.name.lower()
    size = getattr(uploaded_file, "size", None)
    slog(f"load_file: name={name} size={size}")

    file_stream = io.BytesIO(file_bytes)

    if name.endswith((".csv", ".txt")):
        df = pd.read_csv(file_stream, dtype=str)
        return df, None

    elif name.endswith((".xlsx", ".xls")):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            df = pd.read_excel(file_stream, engine="openpyxl", dtype=str)
        return df, None

    else:
        raise ValueError("Unsupported file type. Please upload CSV or Excel (.xlsx/.xls).")

def load_file_optimized(uploaded_file, max_size_mb=5) -> Tuple[pd.DataFrame, Optional[str]]:

    file_bytes = uploaded_file.read()
    name = uploaded_file.name.lower()
    size = getattr(uploaded_file, "size", None)
    slog(f"load_file_optimized: name={name} size={size}")
    
    if size and size > max_size_mb * 1024 * 1024:
        raise ValueError(f"File too large: {size} bytes. Maximum allowed: {max_size_mb}MB")

    try:
        file_stream = io.BytesIO(file_bytes)
        
        if name.endswith((".csv", ".txt")):

            df = pd.read_csv(file_stream, dtype=str, low_memory=True)
            return df, None

        elif name.endswith((".xlsx", ".xls")):

            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                
                file_stream.seek(0) 
                sample_df = pd.read_excel(file_stream, engine="openpyxl", nrows=5)
                columns = sample_df.columns.tolist()
                
                file_stream.seek(0)
                df = pd.read_excel(
                    file_stream, 
                    engine="openpyxl", 
                    dtype=str,
                    usecols=columns
                )
            return df, None

        else:
            raise ValueError("Unsupported file type. Please upload CSV or Excel (.xlsx/.xls).")
            
    except Exception as e:
        slog(f"Error loading file {name}: {e}", "error")
        raise

def load_previous_file_safe(prev_file, max_size_mb=5) -> Optional[pd.DataFrame]:

    if not prev_file:
        return None
        
    prev_size = getattr(prev_file, "size", 0) or 0
    slog(f"load_previous_file_safe: name={prev_file.name} size={prev_size} bytes")
    
    # Verificar tamaño máximo
    if prev_size > max_size_mb * 1024 * 1024:
        slog(f"Previous file too large: {prev_size} > {max_size_mb}MB - Skipping", "warning")
        return None
    
    try:
        wanted_cols = set(["Id", "Email"] + BEFORE_ZIPCODE + AFTER_LEADSTATUS)
        
        def _usecols(colname: str) -> bool:
            c = str(colname).strip()
            return (c in wanted_cols) or (c.lower() in {w.lower() for w in wanted_cols})

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            
            file_bytes = prev_file.read()
            file_stream = io.BytesIO(file_bytes)
            
            try:
                pdf = pd.read_excel(
                    file_stream,
                    engine="openpyxl",
                    dtype=str,
                    usecols=_usecols
                )
                slog(f"Previous file loaded with filtered columns: {pdf.shape}")
                return normalize_column_names(pdf)
            except Exception as e:
                slog(f"Failed to load with filtered columns, trying full: {e}")
                # Fallback: cargar completo pero con dtype=str
                file_stream.seek(0)  # Reiniciar el stream
                pdf_full = pd.read_excel(
                    file_stream, 
                    engine="openpyxl", 
                    dtype=str
                )
                slog(f"Previous file loaded full: {pdf_full.shape}")
                return normalize_column_names(pdf_full)
                
    except Exception as e:
        slog(f"Failed to load previous file safely: {e}", "error")
        return None

def ensure_datetime_series(s: pd.Series) -> pd.Series:
    if pd.api.types.is_datetime64_any_dtype(s):
        return s
    s_clean = s.astype(str).str.strip().str.replace('Z', '', regex=False)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        dt = pd.to_datetime(s_clean, errors="coerce")
        if dt.isna().mean() > 0.4:
            s_no_frac = s_clean.str.replace(r"\.(\d{1,9})$", "", regex=True)
            dt = pd.to_datetime(s_no_frac, errors="coerce")
    return dt

def clean_majority_date_like_columns(df: pd.DataFrame, threshold: float = 0.6) -> Tuple[pd.DataFrame, int]:
    out = df.copy()
    total_blanked = 0
    for col in out.columns:
        s = out[col]
        if pd.api.types.is_datetime64_any_dtype(s) or s.dtype == object:
            dt = ensure_datetime_series(s)
            ratio = dt.notna().mean()
            if ratio >= threshold:
                mask_bad = dt.isna() & s.notna()
                total_blanked += int(mask_bad.sum())
                out.loc[mask_bad, col] = ""
    return out, total_blanked

def format_datetime_columns(df: pd.DataFrame, cols: List[str], fmt: str) -> Tuple[pd.DataFrame, Dict[str, int]]:
    out = df.copy()
    counts: Dict[str, int] = {}
    for col in cols:
        if col not in out.columns:
            continue
        dt = ensure_datetime_series(out[col])
        counts[col] = int(dt.notna().sum())
        out[col] = dt.dt.strftime(fmt).fillna("")
    return out, counts

def format_phone(raw: str) -> Tuple[str, str]:
    if pd.isna(raw):
        return "", "blank"
    digits = ''.join(ch for ch in str(raw) if ch.isdigit())
    if len(digits) == 0:
        return "", "blank"
    if len(digits) == 11 and digits.startswith('1'):
        digits = digits[1:]
    if len(digits) == 10:
        area, exch, last4 = digits[:3], digits[3:6], digits[6:]
        return f"({area}) {exch}-{last4}", "std10"
    if len(digits) > 10:
        area = digits[:-7]
        exch = digits[-7:-4]
        last4 = digits[-4:]
        return f"({area}) {exch}-{last4}", "long"
    return "", "short"

def format_phone_columns(df: pd.DataFrame, cols: List[str]) -> Tuple[pd.DataFrame, Dict[str, Dict[str, int]]]:
    out = df.copy()
    summary: Dict[str, Dict[str, int]] = {}
    for col in cols:
        if col not in out.columns:
            continue
        stats = {"std10": 0, "long": 0, "short": 0, "blank": 0}
        def _apply(v):
            formatted, status = format_phone(v)
            stats[status] += 1
            return formatted
        out[col] = out[col].apply(_apply)
        summary[col] = stats
    return out, summary

def format_zipcode_column(df: pd.DataFrame, col_name: str = "ZipCode") -> pd.DataFrame:
    out = df.copy()
    if col_name not in out.columns:
        return out
    def _fmt(v):
        s = "" if pd.isna(v) else str(v)
        digits = "".join(ch for ch in s if ch.isdigit())
        if len(digits) == 0:
            return ""
        if len(digits) >= 5:
            return digits[:5]
        return digits.zfill(5)
    out[col_name] = out[col_name].apply(_fmt)
    return out

def insert_columns(df: pd.DataFrame, before: Optional[str], after: Optional[str], cols_with_defaults: Dict[str, str]) -> pd.DataFrame:
    out = df.copy()

    def _insert_at(df_, idx_, col_name, default_val):
        if col_name in df_.columns:
            df_[col_name] = df_[col_name].fillna("")
            mask_blank = df_[col_name].astype(str).str.strip().eq("")
            if default_val != "":
                df_.loc[mask_blank, col_name] = default_val
            return df_
        cols = list(df_.columns)
        cols[idx_:idx_] = [col_name]
        df_ = df_.reindex(columns=cols)
        df_[col_name] = default_val
        return df_

    if before and before in out.columns:
        insert_idx = out.columns.get_loc(before)
        for name in BEFORE_ZIPCODE:
            default_val = cols_with_defaults.get(name, "")
            out = _insert_at(out, insert_idx, name, default_val)
            insert_idx += 1
    if after and after in out.columns:
        insert_idx = out.columns.get_loc(after) + 1
        for name in AFTER_LEADSTATUS:
            default_val = cols_with_defaults.get(name, "")
            out = _insert_at(out, insert_idx, name, default_val)
            insert_idx += 1
    else:
        for name in AFTER_LEADSTATUS:
            if name not in out.columns:
                out[name] = cols_with_defaults.get(name, "")
            else:
                mask_blank = out[name].astype(str).str.strip().eq("")
                dflt = cols_with_defaults.get(name, "")
                if dflt != "":
                    out.loc[mask_blank, name] = dflt
    return out

def enrich_from_previous_for_columns(current: pd.DataFrame, previous: Optional[pd.DataFrame], cols_to_enrich: List[str]) -> Tuple[pd.DataFrame, Dict[str, int]]:
    if previous is None or previous.empty or "Id" not in current.columns:
        return current, {"duplicated_ids": 0, "rows_enriched": 0}
    present_cols = [c for c in cols_to_enrich if c in previous.columns]
    if not present_cols:
        return current, {"duplicated_ids": 0, "rows_enriched": 0}
    previous = previous.drop_duplicates(subset=["Id"], keep="first")
    merged = current.merge(previous[["Id"] + present_cols], on="Id", how="left", suffixes=("", "_prev"))
    rows_enriched = 0
    for c in present_cols:
        prev_c = f"{c}_prev"
        if prev_c in merged.columns:
            merged[c] = merged[c].fillna("").astype(str)
            mask_take_prev = merged[c].str.strip().eq("") | merged[c].str.lower().eq("nan")
            rows_enriched += int(mask_take_prev.sum())
            merged.loc[mask_take_prev, c] = merged.loc[mask_take_prev, prev_c]
            merged.drop(columns=[prev_c], inplace=True)
    return merged, {"duplicated_ids": 0, "rows_enriched": rows_enriched}

def apply_after_leadstatus_rules(current: pd.DataFrame, previous: Optional[pd.DataFrame],
                                 defaults: Dict[str, str], cols: List[str], id_col: str = "Id") -> Tuple[pd.DataFrame, int]:
    out = current.copy()
    replacements = 0
    for c in cols:
        if c not in out.columns:
            out[c] = defaults.get(c, "")
        else:
            mask_blank = out[c].astype(str).str.strip().eq("")
            dflt = defaults.get(c, "")
            if dflt != "":
                out.loc[mask_blank, c] = dflt
    if previous is None or previous.empty or id_col not in out.columns:
        return out, replacements

    prev_cols = [id_col] + [c for c in cols if c in previous.columns]
    prev = previous[prev_cols].drop_duplicates(subset=[id_col], keep="first")
    merged = out.merge(prev, on=id_col, how="left", suffixes=("", "__prev"))

    for c in cols:
        dflt = defaults.get(c, "")
        prev_c = f"{c}__prev"
        if prev_c not in merged.columns:
            continue
        prev_val = merged[prev_c].astype(str)
        prev_is_blank = prev_val.str.strip().eq("") | prev_val.str.lower().eq("nan")
        mask_is_default_now = merged[c].astype(str) == dflt
        take_prev = (~prev_is_blank) & (prev_val != dflt) & mask_is_default_now
        replacements += int(take_prev.sum())
        merged.loc[take_prev, c] = merged.loc[take_prev, prev_c]
        merged.drop(columns=[prev_c], inplace=True)
    return merged, replacements

def _fetch_pending_updates_from_supabase() -> Tuple[List[Dict], Optional[str]]:
    try:
        if not SUPABASE_URL or not SUPABASE_KEY:
            return [], "Missing SUPABASE_URL/SUPABASE_KEY"
        
        base_fields = ["id", SUPABASE_ID_FIELD, SUPABASE_EMAIL_FIELD] + list(SUPABASE_TO_FILE_COLS.keys())
        select_q = ",".join(base_fields)
        url = f"{SUPABASE_URL}/rest/v1/{UPDATES_TABLE}"
        params = {"select": select_q, "added_to_file_date": "is.null"}
        
        slog(f"GET pending updates → {url} (select={select_q})")
        
        # Usar sesión con retries
        session = create_session_with_retries()
        resp = session.get(url, headers=HEADERS, params=params, timeout=45)  # Aumentar timeout
        
        if not resp.ok:
            slog(f"Supabase GET error {resp.status_code}: {resp.text[:500]}", "error")
            return [], f"Supabase GET error {resp.status_code}"
        
        data = resp.json()
        slog(f"Pending updates fetched: {len(data)}")
        return data, None
        
    except requests.exceptions.Timeout:
        slog("Supabase GET timeout after 45s", "error")
        return [], "Supabase GET timeout"
    except Exception as e:
        slog(f"Supabase GET exception: {e}", "error")
        return [], f"Supabase GET exception: {str(e)}"

def apply_supabase_pending_updates(df: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, int], List[str]]:
    out = df.copy()
    updates, err = _fetch_pending_updates_from_supabase()
    stats = {"pending": 0, "matched_rows": 0, "cells_written": 0, "unmatched": 0}
    processed_update_ids: List[str] = []

    if err:
        slog(f"apply_supabase_pending_updates: {err}", "error")
        return out, stats, processed_update_ids

    stats["pending"] = len(updates)
    if stats["pending"] == 0:
        return out, stats, processed_update_ids

    has_id_col = "Id" in out.columns
    has_email_col = "Email" in out.columns

    id_int_pos_map: Dict[int, int] = {}
    id_str_pos_map: Dict[str, int] = {}
    email_pos_map: Dict[str, int] = {}

    norm_str = lambda v: str(v).strip()
    norm_low = lambda v: str(v).strip().lower()

    if has_id_col:
        sub = out[out["Id"].notna()].reset_index()
        for _, row in sub.iterrows():
            pos = int(row["index"])
            raw_id = row["Id"]
            s = norm_str(raw_id)
            if s == "" or s.lower() == "nan":
                continue
            try:
                id_int = int(s.replace(",", ""))
                id_int_pos_map[id_int] = pos
            except ValueError:
                id_str_pos_map[norm_low(s)] = pos

    if has_email_col:
        sub = out[out["Email"].notna()].reset_index()
        for _, row in sub.iterrows():
            pos = int(row["index"])
            em = norm_low(row["Email"])
            if em and em != "nan":
                email_pos_map[em] = pos

    DATE_KEYS = {"asked_contact_for_promos_date", "asked_contact_next_year_date"}

    for upd in updates:
        pos = None
        lead_val = upd.get(SUPABASE_ID_FIELD, None)
        if lead_val is not None:
            s = norm_str(lead_val)
            if s:
                try:
                    lead_int = int(s.replace(",", ""))
                    if has_id_col and lead_int in id_int_pos_map:
                        pos = id_int_pos_map[lead_int]
                except ValueError:
                    key = norm_low(s)
                    if has_id_col and key in id_str_pos_map:
                        pos = id_str_pos_map[key]
        if pos is None:
            email_val = norm_low(upd.get(SUPABASE_EMAIL_FIELD, "") or "")
            if email_val and has_email_col and email_val in email_pos_map:
                pos = email_pos_map[email_val]

        if pos is None:
            stats["unmatched"] += 1
            continue

        stats["matched_rows"] += 1

        for sb_key, file_col in SUPABASE_TO_FILE_COLS.items():
            if sb_key not in upd:
                continue
            val = upd.get(sb_key, None)
            if val is None:
                continue
            if sb_key in DATE_KEYS:
                out.iat[pos, out.columns.get_loc(file_col)] = _fmt_mmddyyyy(val)
            else:
                out.iat[pos, out.columns.get_loc(file_col)] = val
            stats["cells_written"] += 1

        if "id" in upd and upd["id"] is not None:
            processed_update_ids.append(str(upd["id"]))

    slog(f"apply_supabase_pending_updates: {stats}")
    return out, stats, processed_update_ids

def _join_ids_for_in(ids: List[str]) -> str:
    out_items = []
    for x in ids:
        s = str(x)
        if s.isdigit():
            out_items.append(s)
        else:
            s_escaped = s.replace('"', '\\"')
            out_items.append(f'"{s_escaped}"')
    return ",".join(out_items)

def mark_lead_updates_as_added(update_ids: List[str]) -> Tuple[int, Optional[str]]:
    if not update_ids:
        slog("mark_lead_updates_as_added: no ids to update")
        return 0, None
    if not SUPABASE_URL or not SUPABASE_KEY:
        return 0, "Missing SUPABASE_URL/SUPABASE_KEY"

    date_str = _today_date_str()
    updated_total = 0
    chunk_size = 300

    for i in range(0, len(update_ids), chunk_size):
        chunk = update_ids[i:i + chunk_size]
        ids_csv = _join_ids_for_in(chunk)
        url = f"{SUPABASE_URL}/rest/v1/{UPDATES_TABLE}?id=in.({ids_csv})"
        body = {"added_to_file_date": date_str, "added_to_file": "Yes"}
        slog(f"PATCH mark added → {len(chunk)} ids")

        try:
            # Usar sesión con retries
            session = create_session_with_retries()
            resp = session.patch(url, headers=HEADERS, data=json.dumps(body), timeout=30)
            if not resp.ok:
                return updated_total, f"Supabase PATCH error {resp.status_code}: {resp.text}"
            try:
                data = resp.json()
                updated_total += len(data)
            except Exception:
                updated_total += len(chunk)
        except Exception as e:
            return updated_total, f"Supabase PATCH exception: {e}"

    slog(f"mark_lead_updates_as_added: updated_total={updated_total}")
    return updated_total, None

def _headers_for_storage() -> Dict[str, str]:
    return {
        "apikey": SUPABASE_KEY or "",
        "Authorization": f"Bearer {SUPABASE_KEY}" if SUPABASE_KEY else "",
    }

def _download_latest_google_earth_bytes() -> Tuple[Optional[bytes], Optional[str]]:
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None, "Missing SUPABASE_URL/SUPABASE_KEY"
    
    url = f"{SUPABASE_URL}/storage/v1/object/{GE_BUCKET}/{GE_LATEST_KEY}"
    slog(f"Download GE latest from storage: {GE_BUCKET}/{GE_LATEST_KEY}")
    
    try:
        session = create_session_with_retries()
        resp = session.get(url, headers=_headers_for_storage(), timeout=120)  # Timeout más largo para archivos grandes
        
        if resp.status_code == 404:
            slog("GE latest not found (404).")
            return None, None
        if not resp.ok:
            slog(f"Storage GET error {resp.status_code}: {resp.text[:500]}", "error")
            return None, f"Storage GET error {resp.status_code}"
        
        slog(f"GE latest downloaded: {len(resp.content)} bytes")
        return resp.content, None
        
    except requests.exceptions.Timeout:
        slog("Storage GET timeout after 120s", "error")
        return None, "Storage GET timeout"
    except Exception as e:
        slog(f"Storage GET exception: {e}", "error")
        return None, f"Storage GET exception: {str(e)}"

# Google Earth

def _load_google_earth_latest_df() -> Tuple[Optional[pd.DataFrame], Dict[str, str], Optional[str]]:
    b, err = _download_latest_google_earth_bytes()
    if err:
        return None, {}, err
    if b is None:
        return None, {}, None

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            xl = pd.ExcelFile(io.BytesIO(b))
    except Exception as e:
        return None, {}, f"Failed opening latest.xlsx: {e}"

    REQ_CANON = [
        "Id",
        "Has Fence on Google Earth",
        "Google Earth Last Picture At",
        "Google Earth Last Checked At",
    ]
    REQ_LOWER = [c.lower() for c in REQ_CANON]

    chosen_df = None
    chosen_sheet = None

    for sheet in xl.sheet_names:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                tmp = xl.parse(sheet)
            cols_raw = [str(c).replace("\u00A0", " ").strip() for c in tmp.columns]
            cols_lower = [c.lower() for c in cols_raw]
            if not all(req in cols_lower for req in REQ_LOWER):
                continue
            rename_map = {}
            for canon, req_low in zip(REQ_CANON, REQ_LOWER):
                for original, lower in zip(cols_raw, cols_lower):
                    if lower == req_low:
                        rename_map[original] = canon
                        break
            tmp.columns = cols_raw
            tmp = tmp.rename(columns=rename_map)
            chosen_df = tmp
            chosen_sheet = sheet
            break
        except Exception:
            continue

    if chosen_df is None:
        return None, {}, f"latest.xlsx missing required columns: {REQ_CANON}"

    raw_rows = len(chosen_df)

    df_raw = chosen_df.copy()
    df_raw["Id"] = df_raw["Id"].apply(_norm_id)
    df_raw = df_raw[df_raw["Id"] != ""]
    df_raw = df_raw.drop_duplicates(subset=["Id"], keep="last").reset_index(drop=True)

    df_out = pd.DataFrame({
        "Id": df_raw["Id"],
        "Has Fence on Google Earth": df_raw["Has Fence on Google Earth"].apply(_normalize_yes_no_ge),
        "Google Earth Last Picture At": df_raw["Google Earth Last Picture At"].apply(_parse_to_mmddyyyy_ge),
        "Google Earth Last Checked At": df_raw["Google Earth Last Checked At"].apply(_parse_to_mmddyyyy_ge),
    })

    meta = {
        "sheet": chosen_sheet or "",
        "raw_rows": str(raw_rows),
        "rows_after_dedupe": str(len(df_out)),
    }
    slog(f"GE overlay df prepared: rows={len(df_out)} (sheet={meta['sheet']})")
    return df_out, meta, None

def overlay_google_earth_latest(df: pd.DataFrame) -> pd.DataFrame:
    ge_df, meta, err = _load_google_earth_latest_df()
    if err:
        slog(f"overlay_google_earth_latest error: {err}", "error")
        return df
    if ge_df is None or ge_df.empty or "Id" not in df.columns:
        slog("overlay_google_earth_latest: nothing to apply.")
        return df

    out = df.copy()
    out_idx: Dict[str, int] = {}
    for i, v in enumerate(out["Id"]):
        key = _norm_id(v)
        if key:
            out_idx[key] = i

    for col in ["Has Fence on Google Earth", "Google Earth Last Picture At", "Google Earth Last Checked At"]:
        if col not in out.columns:
            out[col] = ""

    applied = 0
    for _, row in ge_df.iterrows():
        rid = _norm_id(row["Id"])
        if not rid:
            continue
        pos = out_idx.get(rid)
        if pos is None:
            continue

        hv = str(row["Has Fence on Google Earth"]).strip()
        if hv in {"Yes", "No"}:
            if str(out.iat[pos, out.columns.get_loc("Has Fence on Google Earth")]).strip() != hv:
                out.iat[pos, out.columns.get_loc("Has Fence on Google Earth")] = hv

        pic = str(row["Google Earth Last Picture At"]).strip()
        if pic:
            if str(out.iat[pos, out.columns.get_loc("Google Earth Last Picture At")]).strip() != pic:
                out.iat[pos, out.columns.get_loc("Google Earth Last Picture At")] = pic

        chk = str(row["Google Earth Last Checked At"]).strip()
        if chk:
            if str(out.iat[pos, out.columns.get_loc("Google Earth Last Checked At")]).strip() != chk:
                out.iat[pos, out.columns.get_loc("Google Earth Last Checked At")] = chk
        applied += 1

    slog(f"overlay_google_earth_latest: applied to {applied} rows")
    return out

# UI 

def show_hubspot_file_creator():
    st.set_page_config(
        page_title="Leads File Cleaner", 
        layout="wide",
        page_icon="🧹"
    )
    st.title("🧹 Leads File Cleaner")

    MAX_FILE_SIZE_MB = 5 

    if "ui_init_done" not in st.session_state:
        st.session_state.update({
            "processed_df_df": None,
            "pending_processed_ids": [],
            "updates_marked": False,
            "final_ready": False,
            "final_csv_bytes": None,
            "final_xlsx_bytes": None,
            "last_main_file_sig": None,
            "last_prev_file_sig": None,
            "proc_step": 0,
            "proc_df_work": None,
            "proc_prev_df": None,
            "proc_sb_stats": None,
            "proc_ids": [],
            "ui_init_done": True,
        })
        slog("UI state initialized")

    with st.expander("⚠️ Important Limits for Render"):
        st.warning("""
        **Due to Render memory limits:**
        - Main file: max 5MB
        - Previous file: max 5MB (CSV format)  
        - Large files may cause the app to restart
        - For best results, use filtered/smaller files
        """)

    col1, col2 = st.columns(2)
    with col1:
        main_file = st.file_uploader("New leads file", type=["csv", "txt", "xlsx", "xls"], key="main")
        if main_file:
            main_size_mb = getattr(main_file, "size", 0) / (1024 * 1024)
            st.write(f"Size: {main_size_mb:.2f} MB")
            if main_size_mb > MAX_FILE_SIZE_MB:
                st.error(f"❌ File too large! Max {MAX_FILE_SIZE_MB}MB")
                
    with col2:
        prev_file = st.file_uploader("Previous version CSV Format (optional)", type=["csv", "txt", "xlsx", "xls"], key="prev")
        if prev_file:
            prev_size_mb = getattr(prev_file, "size", 0) / (1024 * 1024)
            st.write(f"Size: {prev_size_mb:.2f} MB")
            if prev_size_mb > MAX_FILE_SIZE_MB:
                st.error(f"❌ File too large! Max {MAX_FILE_SIZE_MB}MB")

    def _file_sig(uploaded):
        if not uploaded: return None
        try:
            return (uploaded.name, uploaded.size)
        except Exception:
            return (uploaded.name, None)

    main_sig = _file_sig(main_file)
    prev_sig = _file_sig(prev_file)

    if main_sig != st.session_state.get("last_main_file_sig") or prev_sig != st.session_state.get("last_prev_file_sig"):
        st.session_state.update({
            "processed_df_df": None,
            "pending_processed_ids": [],
            "updates_marked": False,
            "final_ready": False,
            "final_csv_bytes": None,
            "final_xlsx_bytes": None,
            "last_main_file_sig": main_sig,
            "last_prev_file_sig": prev_sig,
            "proc_step": 0,
            "proc_df_work": None,
            "proc_prev_df": None,
            "proc_sb_stats": None,
            "proc_ids": [],
        })
        slog(f"Files changed: main={main_sig} prev={prev_sig}")

    if not main_file:
        st.info("Please upload a main file to begin.")
        st.session_state.update({"final_ready": False, "final_csv_bytes": None, "final_xlsx_bytes": None})
        return

    main_file_size = getattr(main_file, "size", 0)
    if main_file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
        st.error(f"File too large: {main_file_size} bytes. Maximum allowed: {MAX_FILE_SIZE_MB}MB")
        return

    if prev_file:
        prev_file_size = getattr(prev_file, "size", 0)
        if prev_file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
            st.error(f"Previous file too large: {prev_file_size} bytes. Maximum allowed: {MAX_FILE_SIZE_MB}MB")
            prev_file = None

    try:
        with step_log("Load main file"):
            main_df, _ = safe_dataframe_operation(load_file_optimized, main_file, MAX_FILE_SIZE_MB)
            main_df = normalize_column_names(main_df)
            slog(f"Main columns: {list(main_df.columns)[:12]} ... total={len(main_df.columns)}")
            slog(f"Main df loaded: shape={main_df.shape}")
            st.success(f"✅ Main file loaded: {main_df.shape[0]} rows, {main_df.shape[1]} columns")
    except Exception as e:
        st.error(f"Failed to load main file: {e}")
        slog(f"Load main file FAILED: {e}", "error")
        return

    prev_df = None
    if prev_file:
        with step_log("Load previous file safely"):
            prev_df = load_previous_file_safe(prev_file, MAX_FILE_SIZE_MB)
            if prev_df is not None:
                slog(f"Previous df loaded safely: shape={prev_df.shape}")
                st.success(f"✅ Previous file loaded: {prev_df.shape[0]} rows")
            else:
                st.warning("Could not load previous file (continuing without it)")
                slog("Previous file loading failed")

    # Start processing
    if st.button("🚀 Process", key="process_btn", help="Run the cleaning pipeline", type="primary"):

        gc.collect()
        
        st.session_state.proc_df_work = main_df.copy()
        st.session_state.proc_prev_df = prev_df
        st.session_state.proc_step = 1
        slog("Process button clicked → step=1")
        st.rerun()

    if st.session_state.proc_step > 0:
        total_steps = 7
        step = st.session_state.proc_step
        df_work = st.session_state.proc_df_work
        prev_df_local = st.session_state.proc_prev_df

        prog = st.progress(min((step - 1) / total_steps, 0.999))
        status = st.status("Processing…", expanded=True)

        try:
            if step == 1:
                with step_log("Step 1: Clean date-like columns"):
                    df_work, _ = safe_dataframe_operation(clean_majority_date_like_columns, df_work)
                    slog(f"Step1 df shape: {df_work.shape}")
            elif step == 2:
                with step_log("Step 2: Format datetime columns"):
                    df_work, _ = safe_dataframe_operation(format_datetime_columns, df_work, DATETIME_COLS, "%m/%d/%Y %I:%M %p")
                    slog(f"Step2 df shape: {df_work.shape}")
            elif step == 3:
                with step_log("Step 3: Format date-only columns"):
                    df_work, _ = safe_dataframe_operation(format_datetime_columns, df_work, DATE_ONLY_COLS, "%m/%d/%Y")
                    slog(f"Step3 df shape: {df_work.shape}")
            elif step == 4:
                with step_log("Step 4: Phones + Zip"):
                    _, _ = safe_dataframe_operation(format_phone_columns, df_work, PHONE_COLS)
                    df_work = safe_dataframe_operation(format_zipcode_column, df_work)
                    slog(f"Step4 df shape: {df_work.shape}")
            elif step == 5:
                with step_log("Step 5: Insert cols + defaults + enrich"):
                    cols_with_defaults = {**{c: "" for c in BEFORE_ZIPCODE}, **DEFAULTS_AFTER_LEADSTATUS}
                    df_work = safe_dataframe_operation(insert_columns, df_work, before="ZipCode", after="LeadStatus", cols_with_defaults=cols_with_defaults)
                    # Solo enriquecer si tenemos datos previos
                    if prev_df_local is not None:
                        df_work, _ = safe_dataframe_operation(enrich_from_previous_for_columns, df_work, prev_df_local, BEFORE_ZIPCODE)
                        df_work, _ = safe_dataframe_operation(apply_after_leadstatus_rules, df_work, prev_df_local, DEFAULTS_AFTER_LEADSTATUS, AFTER_LEADSTATUS)
                    else:
                        slog("Skipping previous file enrichment - no data available")
                    slog(f"Step5 df shape: {df_work.shape}")
            elif step == 6:
                with step_log("Step 6: Apply Supabase pending updates"):
                    df_work, sb_stats, processed_ids = safe_dataframe_operation(apply_supabase_pending_updates, df_work)
                    st.session_state.proc_sb_stats = sb_stats
                    st.session_state.proc_ids = processed_ids
                    slog(f"Step6 df shape: {df_work.shape} ; stats={sb_stats} ; ids={len(processed_ids)}")
            elif step == 7:
                with step_log("Step 7: Overlay Google Earth + finalize"):
                    df_work = safe_dataframe_operation(overlay_google_earth_latest, df_work)
                    df_work = df_work.fillna("")
                    st.session_state["processed_df_df"] = df_work
                    st.session_state["updates_marked"] = False
                    st.session_state["final_ready"] = False
                    st.session_state["final_csv_bytes"] = None
                    st.session_state["final_xlsx_bytes"] = None
                    slog(f"FINAL df ready: shape={df_work.shape}")

                status.update(label="Processing complete ✅", state="complete")
                prog.progress(1.0)
                st.success("✅ File processed. You can now generate the final file.")

                st.session_state.proc_step = 0
                st.rerun()

            st.session_state.proc_df_work = df_work
            st.session_state.proc_step = step + 1
            prog.progress(step / total_steps)
            st.rerun()

        except Exception as e:
            status.update(label="Processing failed ❌", state="error")
            st.session_state.proc_step = 0
            st.error(f"Processing failed: {e}")
            slog(f"Processing exception at step {step}: {e}", "error")

    # Generate Final File
    if st.session_state.get("processed_df_df") is not None and st.session_state.proc_step == 0:
        st.divider()

        if not st.session_state.get("final_ready", False):
            st.session_state["final_csv_bytes"] = None
            st.session_state["final_xlsx_bytes"] = None

            if st.button("🔧 Generate Final File", key="gen_final_btn"):
                if not st.session_state.get("updates_marked", False):
                    processed_ids = st.session_state.get("proc_ids", []) or st.session_state.get("pending_processed_ids", [])
                    if processed_ids:
                        with step_log("Mark Supabase updates as added"):
                            updated_count, err = mark_lead_updates_as_added(processed_ids)
                        if err:
                            st.error(f"Failed to mark Supabase updates as added: {err}")
                            slog(f"mark updates FAILED: {err}", "error")
                            st.stop()
                        else:
                            st.success(f"✅ Supabase updated: {updated_count} row(s).")
                            slog(f"mark updates OK: updated={updated_count}")
                            st.session_state["updates_marked"] = True
                            st.session_state["pending_processed_ids"] = []
                    else:
                        st.session_state["updates_marked"] = True
                        slog("No pending update ids to mark.")

                try:
                    df_final = st.session_state["processed_df_df"]
                    with step_log("Build final CSV/XLSX"):
                        csv_bytes = safe_dataframe_operation(lambda: df_final.to_csv(index=False).encode("utf-8"))
                        xlsx_bytes = io.BytesIO()
                        with pd.ExcelWriter(xlsx_bytes, engine="openpyxl") as writer:
                            df_final.to_excel(writer, index=False, sheet_name="Processed")
                        xlsx_bytes.seek(0)
                        slog(f"Final buffers: csv={len(csv_bytes)} bytes ; xlsx={len(xlsx_bytes.getvalue())} bytes")

                    st.session_state["final_csv_bytes"] = csv_bytes
                    st.session_state["final_xlsx_bytes"] = xlsx_bytes.getvalue()
                    st.session_state["final_ready"] = True
                    st.success("✅ Final file generated.")

                except Exception as e:
                    st.error(f"Failed generating final file: {e}")
                    slog(f"Generate final FAILED: {e}", "error")
                    st.stop()

        if st.session_state.get("final_ready", False):
            today_tag = _today_date_str()
            csv_name = f"final_file_{today_tag}.csv"
            xlsx_name = f"final_file_{today_tag}.xlsx"

            st.download_button(
                "⬇️ Download CSV",
                data=st.session_state["final_csv_bytes"],
                file_name=csv_name,
                mime="text/csv",
                key="dl_csv_final_btn",
            )
            st.download_button(
                "⬇️ Download Excel (.xlsx)",
                data=st.session_state["final_xlsx_bytes"],
                file_name=xlsx_name,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="dl_xlsx_final_btn",
            )

if __name__ == "__main__":
    show_hubspot_file_creator()