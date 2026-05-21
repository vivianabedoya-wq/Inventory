import streamlit as st
from typing import Optional, Tuple, Any, Dict
from app.services.hubspot_service import (
    insert_lead_update,
    parse_us_date_to_iso
)

def _yes_no_select(label: str, key: str) -> str:
    """UI control with blank/Yes/No options (returns the raw selection)."""
    return st.selectbox(label, ["", "Yes", "No"], key=key)


def _date_text_input(label: str, key: str) -> str:
    """Plain text input for a date (mm/dd/yyyy). We validate later."""
    return st.text_input(label, placeholder="mm/dd/yyyy", key=key)


def _validate_required(lead_number: Optional[int], email: str) -> Tuple[bool, str]:
    """Require either a valid lead_number or a non-empty email."""
    has_lead = lead_number is not None and lead_number != 0
    has_email = email.strip() != ""
    if not (has_lead or has_email):
        return False, "You must provide either Lead Number or Email."
    return True, ""


def _validate_date_field(value: str, field_name: str) -> Tuple[bool, str, Optional[str]]:
    """If blank -> OK and return None; if invalid -> show error."""
    if (value or "").strip() == "":
        return True, "", None
    iso = parse_us_date_to_iso(value)
    if not iso:
        return False, f"{field_name} must be in mm/dd/yyyy format.", None
    return True, "", iso


def _parse_lead_number(raw: str) -> Optional[int]:
    """Safely parse lead_number text input to int or None."""
    s = (raw or "").strip()
    if not s:
        return None
    try:
        n = int(s)
        return n if n != 0 else None
    except ValueError:
        return None


def _yes_no_or_none(selection: Any) -> Optional[str]:
    """Normalize to 'Yes'/'No'/None."""
    if selection is None:
        return None
    if isinstance(selection, str):
        s = selection.strip()
        if s == "":
            return None
        s_low = s.lower()
        if s_low in ("yes", "y", "true", "1"):
            return "Yes"
        if s_low in ("no", "n", "false", "0"):
            return "No"
        return None
    if isinstance(selection, bool):
        return "Yes" if selection else "No"
    return None


def _omit_none(d: Dict[str, Any]) -> Dict[str, Any]:
    """Drop keys whose value is None (avoid overwriting existing values)."""
    return {k: v for k, v in d.items() if v is not None}

#UI

def show_update_lead_form():
    st.header("🚩 HubSpot Lead Contact Preferences Update")

    if "_flash_msg" in st.session_state:
        msg = st.session_state.pop("_flash_msg")
        st.toast(msg, icon="✅")

    for key, default in [
        ("lead_number_raw", ""),
        ("email", ""),
        ("asked_for_no_contact_sel", ""),
        ("elgible_for_emails_sel", ""),
        ("follow_up_on", ""),
        ("asked_contact_for_promos_sel", ""),
        ("next_year_date_txt", ""),
        ("promos_date_txt", ""),
    ]:
        st.session_state.setdefault(key, default)

    no_contact = st.session_state.get("asked_for_no_contact_sel", "")
    eligible = st.session_state.get("eligible_for_emails_sel", "")

    if no_contact in ("Yes", "No") and eligible not in ("Yes", "No"):
        st.session_state["eligible_for_emails_sel"] = "No" if no_contact == "Yes" else "Yes"
    elif eligible in ("Yes", "No") and no_contact not in ("Yes", "No"):
        st.session_state["asked_for_no_contact_sel"] = "No" if eligible == "Yes" else "Yes"

    asked_contact_next_year_auto = None  

    with st.form("lead_update_form", clear_on_submit=False):
        st.subheader("Lead Information", divider="gray")
        col_1, col_2 = st.columns(2)
        with col_1:
            lead_number_raw = st.text_input("Lead Number", key="lead_number_raw")
        with col_2:
            email = st.text_input("Email", key="email")

        st.subheader("Keep in Touch Preferences", divider="gray")
        col_3, col_4 = st.columns(2)
        with col_3:
            _yes_no_select("Asked For No Contact", key="asked_for_no_contact_sel")
        with col_4:
            _yes_no_select("Eligible For Emails", key="eligible_for_emails_sel")

        st.subheader("Promotions & Follow-Up Preferences", divider="gray")
        col_5, col_6 = st.columns(2)
        with col_5:
            follow_up_on = st.text_input("Follow-Up On", key="follow_up_on")
            if (follow_up_on or "").strip():
                asked_contact_next_year_auto = "Yes"  # auto flag if provided
            _yes_no_select("Consent for Promotional Contact", key="asked_contact_for_promos_sel")

        with col_6:
            _date_text_input("Customer Request Submission Date", key="next_year_date_txt")
            _date_text_input("Consent for Promotional Contact Date", key="promos_date_txt")

        save = st.form_submit_button("💾 Save")

    #Submission

    if not save:
        return

    lead_number = _parse_lead_number(lead_number_raw)
    ok_required, err_required = _validate_required(lead_number, email)
    if not ok_required:
        st.error(f"❌ {err_required}")
        return

    ok_d1, err_d1, promos_iso = _validate_date_field(
        st.session_state.promos_date_txt, "Asked Contact For Promos Date"
    )
    ok_d2, err_d2, next_year_iso = _validate_date_field(
        st.session_state.next_year_date_txt, "Asked Contact Next Year Date"
    )
    if not ok_d1:
        st.error(f"❌ {err_d1}")
        return
    if not ok_d2:
        st.error(f"❌ {err_d2}")
        return

    asked_for_no_contact = _yes_no_or_none(st.session_state.get("asked_for_no_contact_sel"))
    eligible_for_emails = _yes_no_or_none(st.session_state.get("eligible_for_emails_sel"))
    asked_contact_for_promos = _yes_no_or_none(st.session_state.get("asked_contact_for_promos_sel"))

    asked_contact_next_year = asked_contact_next_year_auto

    if asked_for_no_contact is None and eligible_for_emails in ("Yes", "No"):
        asked_for_no_contact = "No" if eligible_for_emails == "Yes" else "Yes"
    if eligible_for_emails is None and asked_for_no_contact in ("Yes", "No"):
        eligible_for_emails = "No" if asked_for_no_contact == "Yes" else "Yes"

    payload = _omit_none({
        "lead": lead_number,
        "email": (email.strip() or None),
        "asked_to_be_contacted_on": (st.session_state.follow_up_on.strip() or None),
        "asked_contact_for_promos_date": promos_iso,
        "asked_contact_next_year_date": next_year_iso,
        "asked_contact_for_promos": asked_contact_for_promos,
        "asked_contact_next_year": asked_contact_next_year,
        "asked_for_no_contact": asked_for_no_contact,
        "eligible_for_emails": eligible_for_emails,
    })

    inserted_count, error_msg = insert_lead_update(payload)
    if error_msg:
        st.error(f"❌ Save failed. {error_msg}")
        return

    st.session_state["_flash_msg"] = f"✅ {inserted_count} record(s) saved to Hubspot_Leads_Updates."

    for key in [
        "lead_number_raw", "email", "asked_for_no_contact_sel", "eligible_for_emails_sel",
        "follow_up_on", "asked_contact_for_promos_sel", "next_year_date_txt", "promos_date_txt"
    ]:
        st.session_state.pop(key, None)

    st.rerun()

