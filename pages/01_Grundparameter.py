"""Base planning parameters."""

from pathlib import Path

import pandas as pd
import streamlit as st

from config import has_valid_selected_vehicle, load_settings, save_selected_verladestelle, save_vehicles, selected_vehicle_type
from profiles import get_profile_paths


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
SETTINGS_PATH = get_profile_paths(
	PROJECT_ROOT,
	st.session_state["active_profile_id"],
).settings


def find_workbook() -> Path | None:
	"""Find the loading-point workbook in the project's data directory."""
	workbook_path = DATA_DIR / "Verladestellen.xlsx"
	return workbook_path if workbook_path.exists() else None


def load_verladestellen() -> pd.DataFrame:
	workbook_path = find_workbook()
	if workbook_path is None:
		return pd.DataFrame(columns=["Name", "Adresse", "Breite", "Länge"])

	return pd.read_excel(workbook_path, header=0)


def save_selection() -> None:
	save_selected_verladestelle(SETTINGS_PATH, st.session_state.verladestelle_name)


def save_vehicle_settings() -> None:
	selected_type = st.session_state.selected_vehicle_type
	vehicles = {
		"Sattelzug": {
			"enabled": selected_type == "Sattelzug",
			"capacity": st.session_state.sattelzug_capacity,
		},
		"Dreiachser": {
			"enabled": selected_type == "Dreiachser",
			"capacity": st.session_state.dreiachser_capacity,
		},
	}
	save_vehicles(SETTINGS_PATH, vehicles)


st.title("Grundparameter")
st.write("Hier werden die allgemeinen Planungsparameter festgelegt.")

settings = load_settings(SETTINGS_PATH)
vehicles = settings["vehicles"]
st.session_state.setdefault("selected_vehicle_type", selected_vehicle_type(settings))
for vehicle_name, state_prefix in (("Sattelzug", "sattelzug"), ("Dreiachser", "dreiachser")):
	vehicle_settings = vehicles[vehicle_name]
	st.session_state.setdefault(f"{state_prefix}_enabled", vehicle_settings["enabled"])
	st.session_state.setdefault(f"{state_prefix}_capacity", vehicle_settings["capacity"])

st.subheader("Fahrzeugtypen")
vehicle_columns = st.columns(2)
st.radio(
	"Fahrzeugtyp",
	options=("Sattelzug", "Dreiachser"),
	key="selected_vehicle_type",
	horizontal=True,
	on_change=save_vehicle_settings,
)

verladestellen = load_verladestellen()
if verladestellen.empty:
	st.error("Die Datei Verladestellen.xlsx wurde nicht gefunden oder enthält keine Verladestellen.")
else:
	names = verladestellen["Name"].astype(str).tolist()
	stored_name = settings.get("selected_verladestelle")
	selected_index = names.index(stored_name) if stored_name in names else 0

	st.session_state.setdefault("verladestelle_name", names[selected_index])
	selected_name = st.selectbox(
		"Verladestelle",
		options=names,
		key="verladestelle_name",
		on_change=save_selection,
	)

	selected_row = verladestellen.loc[
		verladestellen["Name"].astype(str) == selected_name
	].iloc[0]
	st.write(f"Adresse: {selected_row['Adresse']}")

selected_settings = load_settings(SETTINGS_PATH)
has_valid_capacity = has_valid_selected_vehicle(selected_settings)
if not has_valid_capacity:
	st.warning("Die Kapazität des ausgewählten Fahrzeugtyps ist nicht gültig.")

if st.button("Weiter", type="primary", disabled=not has_valid_capacity):
	st.switch_page("pages/02_Aufträge.py")
