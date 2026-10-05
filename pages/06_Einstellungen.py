"""Simple file-based settings."""

from pathlib import Path

import streamlit as st

from config import load_settings, save_settings


st.title("Einstellungen")
st.write("Hier werden spaeter allgemeine Anwendungseinstellungen verwaltet.")

settings_path = Path(__file__).resolve().parents[1] / ".autotourenplaner" / "settings.json"
settings = load_settings(settings_path)

komplettourgrenze = st.number_input(
    "Komplettourgrenze",
    min_value=1,
    value=int(settings["komplettourgrenze"]),
    step=1,
)

view = st.selectbox(
    "Ansicht",
    options=["Standard", "Kompakt"],
    index=["Standard", "Kompakt"].index(settings["view"])
    if settings["view"] in ["Standard", "Kompakt"]
    else 0,
)

st.subheader("Auftragskarte")
map_dot_min_size = st.number_input(
    "Minimale Punktgröße",
    min_value=1,
    max_value=50,
    value=int(settings["map_dot_min_size"]),
    step=1,
)
map_dot_max_size = st.number_input(
    "Maximale Punktgröße",
    min_value=1,
    max_value=50,
    value=int(settings["map_dot_max_size"]),
    step=1,
)
if map_dot_min_size > map_dot_max_size:
    st.warning("Die minimale Punktgröße darf nicht größer als die maximale sein.")

if st.button("Einstellungen speichern", type="primary", disabled=map_dot_min_size > map_dot_max_size):
    settings.update(
        {
            "language": "German",
            "view": view,
            "komplettourgrenze": komplettourgrenze,
            "map_dot_min_size": map_dot_min_size,
            "map_dot_max_size": map_dot_max_size,
        }
    )
    save_settings(settings_path, settings)
    st.success("Einstellungen wurden gespeichert.")
