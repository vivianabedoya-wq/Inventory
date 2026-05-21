import os
from urllib.parse import urljoin
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

LOGO = os.getenv("LOGO") or ""
STREAMLIT_URL = os.getenv("STREAMLIT_URL") or ""
BACKEND_URL = (os.getenv("BACKEND_URL") or "").rstrip("/")


def _safe_stretch_button(label: str, key: str):

    try:
        return st.button(label, key=key, width="stretch")
    except TypeError:
        return st.button(label, key=key, use_container_width=True)


def _handle_logout(backend_url: str | None):

    for k in list(st.session_state.keys()):
        del st.session_state[k]
    try:
        st.cache_data.clear()
    except Exception:
        pass
    try:
        st.cache_resource.clear()
    except Exception:
        pass

    try:
        st.query_params.update({})
    except Exception:
        pass

    if backend_url:
        logout_url = urljoin(backend_url.rstrip("/") + "/", "logout")

        if not st.session_state.get("_redirected_after_logout"):
            st.session_state["_redirected_after_logout"] = True
            st.markdown(
                f"""
                <script>
                  // Replace current history entry (avoids back button loop)
                  window.location.replace("{logout_url}");
                </script>
                """,
                unsafe_allow_html=True,
            )

        st.info("Redirecting… If it does not happen automatically, click below.")
        st.link_button("Go to Logout", logout_url)
        st.stop()
    else:
        st.success("Logged out locally (no BACKEND_URL is set).")
        if st.button("Back to Home", key="go_home"):
            st.rerun()
        st.stop()


def show_sidebar_menu():
    if "active_menu" not in st.session_state:
        st.session_state.active_menu = None
    if "active_submenu" not in st.session_state:
        st.session_state.active_submenu = None

    with st.sidebar:
        if LOGO.strip():
            try:
                st.image(LOGO)
            except Exception as e:
                st.warning(f"Logo could not be loaded: {e}")

        st.subheader(f"Hi, {st.session_state.get('name', 'User')}")

        # ==== Main Menu ====
        if _safe_stretch_button("📈 Dashboard", key="btn_dashboard"):
            st.session_state.active_menu = "Dashboard"
            st.session_state.active_submenu = None

        if _safe_stretch_button("📤 Inventory", key="btn_inventory"):
            st.session_state.active_menu = "Inventory"
            st.session_state.active_submenu = None

        if _safe_stretch_button("🚩 HubSpot", key="btn_hubspot"):
            st.session_state.active_menu = "HubSpot"
            st.session_state.active_submenu = None

        if _safe_stretch_button("🌎 Google Earth", key="btn_google"):
            st.session_state.active_menu = "Google Earth"
            st.session_state.active_submenu = None

        st.markdown("---")

        # ==== Submenus ====
        if st.session_state.active_menu == "Inventory":
            st.markdown("**Inventory Options:**")
            if _safe_stretch_button("🖥️ System Inventory", key="btn_sys_inv"):
                st.session_state.active_submenu = "System Inventory"
            if _safe_stretch_button("📝 Physical Count", key="btn_phys_count"):
                st.session_state.active_submenu = "Physical Count"
            if _safe_stretch_button("🛠️ Restock Manager", key="btn_restock_count"):
                st.session_state.active_submenu = "Restock Manager"

        if st.session_state.active_menu == "HubSpot":
            st.markdown("**HubSpot Options:**")
            if _safe_stretch_button("📑 Create New Leads File", key="btn_lds_file"):
                st.session_state.active_submenu = "Create New Leads File"

    return st.session_state.get("active_menu"), st.session_state.get("active_submenu")
