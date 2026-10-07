"""Placeholder for orders."""

from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from config import has_valid_selected_vehicle, load_settings
from profiles import get_profile_paths
from order_table import order_table
from order_import import (
	ORDER_COLUMNS,
	GEOCODING_STATUS_COLUMN,
	geocode_orders,
	load_orders,
	normalize_order_quantity,
	normalize_order_postal_codes,
	normalize_order_countries,
	parse_pasted_orders,
	normalize_order_dates,
	save_orders,
	FILTER_OVERRIDE_COLUMN,
	apply_default_quantity_exclusions,
	QUANTITY_THRESHOLD_OVERRIDE_COLUMN,
	update_quantity_threshold_exclusion,
	save_vehicle_assignment,
)


project_root = Path(__file__).resolve().parents[1]
profile_paths = get_profile_paths(project_root, st.session_state["active_profile_id"])
settings_path = profile_paths.settings
if not has_valid_selected_vehicle(load_settings(settings_path)):
	st.warning("Die Kapazität des ausgewählten Fahrzeugtyps muss eine natürliche Zahl sein.")
	st.stop()

orders_path = profile_paths.orders
orders = normalize_order_postal_codes(load_orders(orders_path))
country_codes_changed = normalize_order_countries(orders)
if normalize_order_dates(orders):
	country_codes_changed = True
if country_codes_changed:
	save_orders(orders, orders_path)
if GEOCODING_STATUS_COLUMN not in orders:
	orders[GEOCODING_STATUS_COLUMN] = ""
orders["Fahrzeugart"] = orders["Fahrzeugart"].fillna("").astype("string")

st.title("Aufträge")
st.markdown(
	"""
	<style>
	.block-container {
		padding-bottom: 0.5rem !important;
	}
	[data-testid="stExpander"] summary {
		padding: 2px 10px;
	}
	[data-testid="stExpanderDetails"] {
		padding: 6px 10px;
	}
	[data-testid="stExpanderDetails"] [data-testid="stVerticalBlock"] {
		gap: 4px;
	}
	[data-testid="stExpander"] textarea {
		height: 50px !important;
		min-height: 50px !important;
	}
	[data-testid="stExpander"] button {
		min-height: 2rem;
		padding: 1px 10px;
	}
	</style>
	""",
	unsafe_allow_html=True,
)
with st.expander("Aufträge aus Export importieren", expanded=True):
	pasted_orders = st.text_area(
		"Exportdaten",
		height=50,
		label_visibility="collapsed",
		placeholder="Tabellarischen Export hier einfügen ...",
	)
	if st.button("Importieren"):
		if not pasted_orders.strip():
			st.warning("Das Feld darf nicht leer sein.")
		else:
			try:
				imported_orders = parse_pasted_orders(pasted_orders)
				apply_default_quantity_exclusions(
					imported_orders,
					int(load_settings(settings_path)["komplettourgrenze"]),
				)
				progress = st.progress(0, text="Adressen werden gesucht ...")
				for row_index, coordinates in geocode_orders(
					imported_orders,
					progress=lambda current: progress.progress(current / len(imported_orders), text=f"Adresse {current} von {len(imported_orders)} ..."),
				):
					if coordinates:
						imported_orders.loc[row_index, ["Breite", "Länge"]] = coordinates
				progress.empty()
				orders = pd.concat([orders, imported_orders], ignore_index=True).reindex(columns=ORDER_COLUMNS)
				save_orders(orders, orders_path)
				st.success(f"{len(imported_orders)} Aufträge importiert.")
				st.rerun()
			except (ValueError, OSError, TimeoutError) as error:
				st.error(f"Import fehlgeschlagen: {error}")

@st.fragment(key=f"orders_table_{st.session_state['active_profile_id']}")
def render_orders_table() -> pd.DataFrame:
	orders = normalize_order_postal_codes(load_orders(orders_path))
	normalize_order_countries(orders)
	if GEOCODING_STATUS_COLUMN not in orders:
		orders[GEOCODING_STATUS_COLUMN] = ""
	orders["Fahrzeugart"] = orders["Fahrzeugart"].fillna("").astype("string")
	total_quantity = pd.to_numeric(orders["Anzahl"], errors="coerce").fillna(0).sum()
	st.markdown(
		f'<div style="font-size: 20px; line-height: 1.5; color: inherit;">{len(orders)} Aufträge | Anzahl gesamt: <strong>{total_quantity:g}</strong></div>',
		unsafe_allow_html=True,
	)

	coordinate_columns = {"Breite", "Länge"}
	hidden_columns = {
		*coordinate_columns,
		GEOCODING_STATUS_COLUMN,
		FILTER_OVERRIDE_COLUMN,
		QUANTITY_THRESHOLD_OVERRIDE_COLUMN,
	}
	visible_columns = [column for column in orders.columns if column not in hidden_columns]
	displayed_orders = orders.loc[:, [*visible_columns, GEOCODING_STATUS_COLUMN]].copy()
	displayed_orders[GEOCODING_STATUS_COLUMN] = displayed_orders[GEOCODING_STATUS_COLUMN].fillna("").astype(str)
	displayed_orders["Fahrzeugart"] = displayed_orders["Fahrzeugart"].fillna("").astype("string")
	displayed_orders["Termin bis"] = (
		pd.to_datetime(displayed_orders["Termin bis"], dayfirst=True, errors="coerce")
		.dt.strftime("%Y-%m-%d")
		.fillna("")
	)
	component_rows = displayed_orders.astype(object).where(pd.notna(displayed_orders), None).to_dict("records")
	for row_index, row in enumerate(component_rows):
		row["row_index"] = row_index
	vehicle_types = list(load_settings(settings_path)["vehicles"])
	component_action = order_table(
		rows=component_rows,
		vehicle_types=vehicle_types,
		key=f"orders_table_component_{st.session_state['active_profile_id']}",
		default=None,
	)

	if isinstance(component_action, dict):
		action_id = component_action.get("action_id")
		if isinstance(action_id, int) and action_id != st.session_state.get("orders_last_action_id"):
			st.session_state["orders_last_action_id"] = action_id
			row_index = component_action.get("row")
			if isinstance(row_index, int) and 0 <= row_index < len(orders):
				if component_action.get("type") == "delete":
					orders = orders.drop(index=row_index).reset_index(drop=True)
					save_orders(orders, orders_path)
				elif component_action.get("type") == "remember_vehicle_type":
					vehicle_type = component_action.get("value")
					if isinstance(vehicle_type, str):
						try:
							added = save_vehicle_assignment(orders.iloc[row_index], vehicle_type)
						except (OSError, ValueError) as error:
							st.error(f"Fahrzeugart konnte nicht gespeichert werden: {error}")
						else:
							location = "neu hinzugefügt" if added else "aktualisiert"
							st.success(f"Fahrzeugart „{vehicle_type}“ für diesen Empfänger {location}.")
				elif component_action.get("type") == "edit":
					column = component_action.get("column")
					value = component_action.get("value", "")
					if column in {"Termin bis", "Anzahl", "Fahrzeugart", "Hinweise"} and isinstance(value, str):
						if column == "Termin bis" and value:
							value = date.fromisoformat(value).strftime("%d.%m.%Y")
						elif column == "Anzahl":
							value = normalize_order_quantity(value)
						orders.at[row_index, column] = value
						if column == "Anzahl":
							update_quantity_threshold_exclusion(
								orders,
								row_index,
								int(load_settings(settings_path)["komplettourgrenze"]),
							)
						save_orders(orders, orders_path)
				st.rerun(scope="fragment")

	return orders


orders = render_orders_table()

st.markdown(
	"""
	<style>
	[data-testid="stHorizontalBlock"] {
		display: flex !important;
		width: fit-content !important;
		gap: 0.5rem !important;
		align-items: center !important;
	}
	[data-testid="stHorizontalBlock"] > div {
		flex: 0 0 auto !important;
		width: auto !important;
	}
	</style>
	""",
	unsafe_allow_html=True,
)

button_col_1, button_col_2, warning_col = st.columns([1.7, 0.8, 3], gap=0)
with button_col_1:
	if st.button("Auftragstabelle leeren", disabled=orders.empty):
		save_orders(pd.DataFrame(columns=ORDER_COLUMNS), orders_path)
		st.rerun()

with button_col_2:
	if st.button("Weiter", type="primary", disabled=orders.empty):
		st.switch_page("pages/03_Aufträge_filtern.py")

with warning_col:
	if orders.empty:
		st.warning("Importieren Sie mindestens einen Auftrag aus Komalog, bevor Sie fortfahren.")
