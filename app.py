"""Streamlit entry point for the Autotourenplaner."""

from pathlib import Path

import streamlit as st

from config import has_valid_selected_vehicle, load_settings
from order_import import load_orders
from profile_cookie import sync_profile_cookie
from profiles import (
    PROFILE_COOKIE_NAME,
    PROFILE_IDS,
    PROFILE_NAMES,
    get_profile_paths,
    initialize_profile_workspace,
    load_profile_state,
    resolve_profile_selection,
    save_profile_state,
)


st.set_page_config(
    page_title="Autotourenplaner",
    page_icon="🚗",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .block-container {        padding-top: 0.75rem;
    }
    header[data-testid="stHeader"] {
        background: transparent;
    }
    .block-container h1 {
        font-size: 2rem;
        padding: 0;
        margin-top: 0;
        margin-bottom: 0.5rem;
    }
    /* Hide the cookie component container completely */
    .st-key-profile_cookie_sync {
        display: none !important;
        height: 0 !important;
        margin: 0 !important;
        padding: 0 !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

project_root = Path(__file__).resolve().parent
cookie_profile_id = st.context.cookies.get(PROFILE_COOKIE_NAME)
cookie_profile_is_valid = cookie_profile_id in PROFILE_IDS
selection_was_confirmed = st.session_state.get("profile_selection_confirmed", False)
previous_profile_id = st.session_state.get("active_profile_id")

initial_profile_id = resolve_profile_selection(
    st.session_state.get("profile_selector"),
    cookie_profile_id,
)
if initial_profile_id is not None:
    st.session_state["profile_selector"] = initial_profile_id


if not cookie_profile_is_valid and not selection_was_confirmed:
    st.markdown(
        """
        <style>
        @keyframes profile-selector-pulse {
            0%, 100% { box-shadow: 0 0 0 0 rgba(245, 158, 11, 0.25); }
            50% { box-shadow: 0 0 0 5px rgba(245, 158, 11, 0.4); }
        }
        [data-testid="stSidebar"] .st-key-profile_selector [data-baseweb="select"] {
            border: 2px solid #f59e0b !important;
            border-radius: 0.5rem;
            animation: profile-selector-pulse 1.5s ease-in-out infinite;
        }
        [data-testid="stSidebar"] [data-testid="stSidebarNav"] {
            display: none !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.sidebar.warning("Bitte wählen Sie Ihr Benutzerprofil, um fortzufahren.")
    with st.sidebar.form("profile_selection_form"):
        st.selectbox(
            "Benutzerprofil auswählen",
            options=PROFILE_IDS,
            format_func=PROFILE_NAMES.__getitem__,
            key="pending_profile_selector",
            index=None,
        )
        profile_selection_submitted = st.form_submit_button(
            "Profil auswählen",
            type="primary",
            key="confirm_profile_selection",
        )
    if profile_selection_submitted:
        selected_profile_id = st.session_state["pending_profile_selector"]
        if selected_profile_id in PROFILE_IDS:
            st.session_state["profile_selector"] = selected_profile_id
            st.session_state["profile_selection_confirmed"] = True
            st.rerun()
else:
    st.sidebar.selectbox(
        "Benutzerprofil",
        options=PROFILE_IDS,
        format_func=PROFILE_NAMES.__getitem__,
        key="profile_selector",
    )

profile_id = st.session_state.get("profile_selector")
profile_is_identified = profile_id in PROFILE_IDS and (
    cookie_profile_is_valid or st.session_state.get("profile_selection_confirmed", False)
)

pages = [
    st.Page("pages/01_Grundparameter.py", title="Grundparameter", icon="⚙️"),
    st.Page("pages/02_Aufträge.py", title="Aufträge", icon="📋", url_path="auftraege"),
    st.Page("pages/03_Aufträge_filtern.py", title="Aufträge filtern", icon="🧭", url_path="auftraege-filtern"),
    st.Page("pages/04_Tourenbildung.py", title="Tourenbildung", icon="🗺️", url_path="tourenbildung"),
    st.Page("pages/05_Reihenfolge.py", title="Reihenfolge", icon="🔀", url_path="reihenfolge"),
    st.Page("pages/06_Einstellungen.py", title="Einstellungen", icon="⚙️"),
]
page = st.navigation(pages, position="sidebar")

if not profile_is_identified:
    st.warning("Wählen Sie links im Seitenmenü ein Benutzerprofil aus.")
    st.stop()

if previous_profile_id in PROFILE_IDS and (
    cookie_profile_is_valid or selection_was_confirmed
):
    previous_paths = get_profile_paths(project_root, previous_profile_id)
    try:
        save_profile_state(previous_paths.state, st.session_state)
    except (OSError, TypeError, ValueError) as error:
        st.error(f"Der Profilstatus konnte nicht gespeichert werden: {error}")
        st.stop()

sync_profile_cookie(profile_id)
if previous_profile_id != profile_id:
    for state_key in list(st.session_state.keys()):
        if state_key not in {
            "profile_selector",
            "profile_cookie_sync",
            "profile_selection_confirmed",
        }:
            del st.session_state[state_key]
    try:
        st.session_state.update(load_profile_state(get_profile_paths(project_root, profile_id).state))
    except (OSError, TypeError, ValueError) as error:
        st.error(f"Der Profilstatus konnte nicht geladen werden: {error}")
        st.stop()

st.session_state["active_profile_id"] = profile_id
try:
    profile_paths = initialize_profile_workspace(project_root, profile_id)
except (OSError, ValueError) as error:
    st.error(f"Der Profilordner konnte nicht vorbereitet werden: {error}")
    st.stop()

settings_path = profile_paths.settings
vehicle_selection_valid = has_valid_selected_vehicle(load_settings(settings_path))
orders_path = profile_paths.orders
orders_enabled = orders_path.exists() and not load_orders(orders_path).empty

if not vehicle_selection_valid:
    st.markdown(
        """
        <style>
        [data-testid="stSidebarNavLink"][href$="/auftraege"],
        [data-testid="stSidebarNavLink"][href$="/auftraege-filtern"],
        [data-testid="stSidebarNavLink"][href$="/tourenbildung"],
        [data-testid="stSidebarNavLink"][href$="/reihenfolge"] {
            color: var(--text-color-secondary) !important;
            opacity: 0.45;
            pointer-events: none;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
elif not orders_enabled:
    st.markdown(
        """
        <style>
        [data-testid="stSidebarNavLink"][href$="/auftraege-filtern"],
        [data-testid="stSidebarNavLink"][href$="/tourenbildung"],
        [data-testid="stSidebarNavLink"][href$="/reihenfolge"] {
            color: var(--text-color-secondary) !important;
            opacity: 0.45;
            pointer-events: none;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

page.run()
try:
    save_profile_state(profile_paths.state, st.session_state)
except (OSError, TypeError, ValueError) as error:
    st.error(f"Der Profilstatus konnte nicht gespeichert werden: {error}")
