"""Streamlit entry point for the Autotourenplaner."""

from pathlib import Path

import streamlit as st

from config import has_valid_selected_vehicle, load_settings
from order_import import load_orders


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
    </style>
    """,
    unsafe_allow_html=True,
)

settings_path = Path(__file__).resolve().parent / ".autotourenplaner" / "settings.json"
vehicle_selection_valid = has_valid_selected_vehicle(load_settings(settings_path))
orders_path = Path(__file__).resolve().parent / "data" / "Aufträge.xlsx"
orders_enabled = orders_path.exists() and not load_orders(orders_path).empty
pages = [
    st.Page("pages/01_Grundparameter.py", title="Grundparameter", icon="⚙️"),
    st.Page("pages/02_Aufträge.py", title="Aufträge", icon="📋", url_path="auftraege"),
    st.Page("pages/03_Aufträge_filtern.py", title="Aufträge filtern", icon="🧭", url_path="auftraege-filtern"),
    st.Page("pages/04_Tourenbildung.py", title="Tourenbildung", icon="🗺️", url_path="tourenbildung"),
    st.Page("pages/05_Reihenfolge.py", title="Reihenfolge", icon="🔀", url_path="reihenfolge"),
    st.Page("pages/06_Einstellungen.py", title="Einstellungen", icon="⚙️"),
]

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

page = st.navigation(pages, position="sidebar")
page.run()
