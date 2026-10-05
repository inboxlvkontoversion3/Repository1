"""Placeholder for tour formation."""

from datetime import date
from copy import deepcopy
from html import escape
import json
from pathlib import Path

import pandas as pd
import folium
import streamlit as st
from streamlit_folium import st_folium

from config import has_valid_selected_vehicle, load_settings, selected_vehicle_type
from map_utils import filter_orders, scale_quantity_to_radius
from order_import import (
	FILTER_OVERRIDE_COLUMN,
	FILTER_OVERRIDE_VALUES,
	QUANTITY_THRESHOLD_OVERRIDE_COLUMN,
	load_orders,
	normalize_order_postal_codes,
	save_orders,
)


settings_path = Path(__file__).resolve().parents[1] / ".autotourenplaner" / "settings.json"
if not has_valid_selected_vehicle(load_settings(settings_path)):
	st.warning("Die Kapazität des ausgewählten Fahrzeugtyps muss eine natürliche Zahl sein.")
	st.stop()

orders_path = Path(__file__).resolve().parents[1] / "data" / "Aufträge.xlsx"
if not orders_path.exists():
	st.warning("Legen Sie mindestens einen Auftrag auf der Seite Aufträge an.")
	st.stop()
orders = normalize_order_postal_codes(load_orders(orders_path))
if FILTER_OVERRIDE_COLUMN not in orders:
	orders[FILTER_OVERRIDE_COLUMN] = ""
orders[FILTER_OVERRIDE_COLUMN] = orders[FILTER_OVERRIDE_COLUMN].fillna("").where(
	orders[FILTER_OVERRIDE_COLUMN].isin(FILTER_OVERRIDE_VALUES), ""
)
if QUANTITY_THRESHOLD_OVERRIDE_COLUMN not in orders:
	orders[QUANTITY_THRESHOLD_OVERRIDE_COLUMN] = False
orders[QUANTITY_THRESHOLD_OVERRIDE_COLUMN] = orders[
	QUANTITY_THRESHOLD_OVERRIDE_COLUMN
].fillna(False).astype(bool)
if orders.empty:
	st.warning("Legen Sie mindestens einen Auftrag auf der Seite Aufträge an.")
	st.stop()

st.title("Aufträge filtern")
st.write("Aufträge nach Menge und Fahrzeugart auf der Karte.")

settings = load_settings(settings_path)
selected_type = selected_vehicle_type(settings)
min_size = int(settings["map_dot_min_size"])
max_size = int(settings["map_dot_max_size"])
if min_size > max_size:
	min_size, max_size = max_size, min_size

verladestellen_path = Path(__file__).resolve().parents[1] / "data" / "Verladestellen.xlsx"
verladestelle = pd.DataFrame()
if verladestellen_path.exists():
	verladestellen = pd.read_excel(verladestellen_path)
	selected_name = settings.get("selected_verladestelle")
	if selected_name and "Name" in verladestellen.columns:
		selected_rows = verladestellen.loc[
			verladestellen["Name"].astype(str) == str(selected_name)
		]
		if not selected_rows.empty:
			verladestelle = selected_rows.iloc[0]

orders["Breite"] = pd.to_numeric(orders["Breite"], errors="coerce")
orders["Länge"] = pd.to_numeric(orders["Länge"], errors="coerce")
orders["Anzahl"] = pd.to_numeric(orders["Anzahl"], errors="coerce")
mapped_orders = orders.dropna(subset=["Breite", "Länge", "Anzahl"])

available_vehicle_types = sorted(
	set(settings["vehicles"])
	| {
		vehicle_type
		for vehicle_type in orders["Fahrzeugart"].fillna("").astype(str).str.strip().unique()
		if vehicle_type
	}
)
vehicle_filter_options = list(settings["vehicles"])
unassigned_vehicle_type = ""
valid_order_dates = pd.to_datetime(orders["Termin bis"], dayfirst=True, errors="coerce").dropna()
default_vehicle_filter = [selected_type] if selected_type in available_vehicle_types else []
default_vehicle_filter.append(unassigned_vehicle_type)


def save_vehicle_filter() -> None:
	st.session_state["filter_vehicle_types_value"] = [
		vehicle_type
		for vehicle_type in vehicle_filter_options + [unassigned_vehicle_type]
		if st.session_state[f"filter_vehicle_type_{vehicle_type or 'unassigned'}_widget"]
	]


def save_date_filter() -> None:
	st.session_state["filter_date_range_value"] = (
		st.session_state["filter_date_start_widget"],
		st.session_state["filter_date_end_widget"],
	)


def save_postal_filter() -> None:
	st.session_state["filter_postal_input_value"] = st.session_state["filter_postal_input_widget"]


if (
	"filter_vehicle_types_value" not in st.session_state
	 or st.session_state.get("filter_vehicle_types_default_type") != selected_type
):
	st.session_state["filter_vehicle_types_value"] = default_vehicle_filter
	st.session_state["filter_vehicle_types_default_type"] = selected_type
st.session_state["filter_vehicle_types_value"] = [
	vehicle_type
	for vehicle_type in st.session_state["filter_vehicle_types_value"]
	if vehicle_type in vehicle_filter_options + [unassigned_vehicle_type]
]
default_date_range = (
	(valid_order_dates.min().date(), valid_order_dates.max().date())
	if not valid_order_dates.empty
	else None
)
st.session_state.setdefault("filter_date_range_value", default_date_range)
st.session_state.setdefault("filter_postal_input_value", "")
for vehicle_type in vehicle_filter_options + [unassigned_vehicle_type]:
	st.session_state[f"filter_vehicle_type_{vehicle_type or 'unassigned'}_widget"] = (
		vehicle_type in st.session_state["filter_vehicle_types_value"]
	)
stored_date_range = st.session_state["filter_date_range_value"]
if isinstance(stored_date_range, date):
	stored_date_range = (stored_date_range, stored_date_range)
st.session_state["filter_date_start_widget"] = stored_date_range[0] if stored_date_range else None
st.session_state["filter_date_end_widget"] = stored_date_range[1] if stored_date_range else None
st.session_state["filter_postal_input_widget"] = st.session_state["filter_postal_input_value"]

filter_column, map_column = st.columns(2, gap="medium")
with filter_column:
	st.subheader("Aufträge filtern")
	st.markdown("**Fahrzeugart**")
	vehicle_toggle_columns = st.columns(len(vehicle_filter_options) + 1)
	for column, vehicle_type in zip(
		vehicle_toggle_columns,
		vehicle_filter_options + [unassigned_vehicle_type],
	):
		with column:
			st.toggle(
				vehicle_type or "Nicht zugewiesen",
				key=f"filter_vehicle_type_{vehicle_type or 'unassigned'}_widget",
				on_change=save_vehicle_filter,
			)
	selected_vehicle_types = [
		vehicle_type
		for vehicle_type in vehicle_filter_options + [unassigned_vehicle_type]
		if st.session_state[f"filter_vehicle_type_{vehicle_type or 'unassigned'}_widget"]
	]
	selected_date_range: tuple[date, date] | None = None
	if not valid_order_dates.empty:
		date_columns = st.columns(2)
		with date_columns[0]:
			start_date = st.date_input(
				"Termin von",
				format="DD.MM.YYYY",
				key="filter_date_start_widget",
				on_change=save_date_filter,
				help="Einschließlich dieses Datums.",
			)
		with date_columns[1]:
			end_date = st.date_input(
				"Termin bis",
				format="DD.MM.YYYY",
				key="filter_date_end_widget",
				on_change=save_date_filter,
				help="Einschließlich dieses Datums.",
			)
		if isinstance(start_date, date) and isinstance(end_date, date):
			selected_date_range = (start_date, end_date)
	postal_input = st.text_input(
		"PLZ-Bereiche",
		key="filter_postal_input_widget",
		on_change=save_postal_filter,
		placeholder="z. B. 2, 04",
		help="Mehrere Präfixe mit Komma oder Leerzeichen trennen. Ein Präfix reicht, z. B. 01.",
	)
	postal_tokens = postal_input.replace(",", " ").split()
	postal_prefixes = [prefix for prefix in postal_tokens if prefix.isdigit()]
	if postal_input and len(postal_prefixes) != len(postal_tokens):
		st.caption("Ungültige PLZ-Bereiche werden ignoriert.")
	order_matches = filter_orders(
		orders,
		vehicle_types=selected_vehicle_types,
		date_range=selected_date_range,
		postal_prefixes=postal_prefixes,
	)
	always_show = orders[FILTER_OVERRIDE_COLUMN].eq("Immer anzeigen")
	always_exclude = orders[FILTER_OVERRIDE_COLUMN].eq("Immer ausschließen")
	order_matches = (order_matches | always_show) & ~always_exclude
	filtered_quantity = pd.to_numeric(
		orders.loc[order_matches, "Anzahl"], errors="coerce"
	).fillna(0).sum()
	st.markdown(
		f'<div style="font-size: 14px; color: inherit;">{int(order_matches.sum())} Aufträge | Anzahl gesamt: {filtered_quantity:g}</div>',
		unsafe_allow_html=True,
	)
	if st.button(
		"Alle Filterausnahmen entfernen",
		disabled=not orders[FILTER_OVERRIDE_COLUMN].isin(FILTER_OVERRIDE_VALUES[1:]).any(),
	):
		orders[FILTER_OVERRIDE_COLUMN] = ""
		orders[QUANTITY_THRESHOLD_OVERRIDE_COLUMN] = False
		save_orders(orders, orders_path)
		st.rerun()

	no_visible_orders = not order_matches.any()
	if no_visible_orders:
		st.warning(
			"Keine Aufträge entsprechen den aktuellen Filtern oder Filterausnahmen. "
			"Passen Sie die Filter an oder entfernen Sie die Filterausnahmen, bevor Sie fortfahren."
		)

if not verladestelle.empty:
	verladestelle["Breite"] = pd.to_numeric(verladestelle.get("Breite"), errors="coerce")
	verladestelle["Länge"] = pd.to_numeric(verladestelle.get("Länge"), errors="coerce")
	if pd.isna(verladestelle["Breite"]) or pd.isna(verladestelle["Länge"]):
		verladestelle = pd.DataFrame()

with map_column:
	if mapped_orders.empty:
		st.warning("Für die Aufträge sind noch keine Kartenkoordinaten vorhanden.")
	else:
		map_points = mapped_orders[["Breite", "Länge"]].values.tolist()
		if not verladestelle.empty:
			map_points.append([verladestelle["Breite"], verladestelle["Länge"]])
		map_bounds = [
			[
				min(point[0] for point in map_points),
				min(point[1] for point in map_points),
			],
			[
				max(point[0] for point in map_points),
				max(point[1] for point in map_points),
			],
		]
		map_center = [
			sum(point[0] for point in map_points) / len(map_points),
			sum(point[1] for point in map_points) / len(map_points),
		]
		map_signature = (
			tuple(tuple(point) for point in map_points),
			str(verladestelle.get("Name", "")) if not verladestelle.empty else "",
		)
		stored_map_signature = st.session_state.get("tourenbildung_map_signature")
		base_map = st.session_state.get("tourenbildung_base_map")
		if base_map is None or stored_map_signature != map_signature:
			base_map = folium.Map(
				location=map_center,
				zoom_start=9,
				tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
				attr="Tiles &copy; Esri",
			)
			base_map.fit_bounds(map_bounds, padding=(0, 0))
			if not verladestelle.empty:
				folium.RegularPolygonMarker(
					location=[verladestelle["Breite"], verladestelle["Länge"]],
					number_of_sides=3,
					rotation=-90,
					radius=12,
					color="#b91c1c",
					fill=True,
					fill_color="#b91c1c",
					fill_opacity=0.9,
					popup=f"Verladestelle: {verladestelle['Name']}",
				).add_to(base_map)
			st.session_state["tourenbildung_base_map"] = base_map
			st.session_state["tourenbildung_map_signature"] = map_signature
		order_map = deepcopy(base_map)

		vehicle_colors = {
			"Sattelzug": "#1f77b4",
			"Dreiachser": "#e67e22",
		}
		quantity_min = mapped_orders["Anzahl"].min()
		quantity_max = mapped_orders["Anzahl"].max()
		map_view = st.session_state.get("tourenbildung_map_view", {})
		order_markers = folium.FeatureGroup(name="Aufträge")
		for order_index, order in mapped_orders.iterrows():
			vehicle_type = str(order["Fahrzeugart"]).strip()
			marker_color = vehicle_colors.get(vehicle_type, "#6b7280")
			is_match = bool(order_matches.loc[order_index])
			address = f"{order['PLZ']} {order['Ort']}, {order['Straße']}"
			current_override = order[FILTER_OVERRIDE_COLUMN] or "Normale Filter verwenden"
			marker = folium.CircleMarker(
				location=[order["Breite"], order["Länge"]],
				radius=scale_quantity_to_radius(order["Anzahl"], quantity_min, quantity_max, min_size, max_size),
				color=marker_color,
				fill=True,
				fill_color=marker_color,
				fill_opacity=0.75 if is_match else 0.18,
				opacity=0.9 if is_match else 0.3,
			)
			marker._id = f"order_marker_{order_index}"
			marker_name = marker.get_name()
			status_id = f"{marker_name}_filter_status"
			def action_message(override: str) -> str:
				return escape(
					json.dumps(
						{
							"tourenbildung_order": int(order_index),
							"tourenbildung_override": override,
						}
					),
					quote=True,
				)

			popup_html = f"""
				<div>{escape(address)}<br>
				Anzahl: {order['Anzahl']:g}<br>
				Fahrzeugart: {escape(vehicle_type or 'Nicht angegeben')}<br>
				<span id="{status_id}">Aktuelle Filterregel: {escape(current_override)}</span></div>
				<hr style="margin: 6px 0">
				<button type="button" onclick="event.stopPropagation(); const center=window.map.getCenter(); const action={action_message('Immer anzeigen')}; action.tourenbildung_action_id=Date.now(); action.tourenbildung_zoom=window.map.getZoom(); action.tourenbildung_center={{lat:center.lat,lng:center.lng}}; window.parent.postMessage({{isStreamlitMessage:true,type:'streamlit:setComponentValue',value:action,dataType:'json'}}, '*');">Immer anzeigen</button>
				<button type="button" onclick="event.stopPropagation(); const center=window.map.getCenter(); const action={action_message('Immer ausschließen')}; action.tourenbildung_action_id=Date.now(); action.tourenbildung_zoom=window.map.getZoom(); action.tourenbildung_center={{lat:center.lat,lng:center.lng}}; window.parent.postMessage({{isStreamlitMessage:true,type:'streamlit:setComponentValue',value:action,dataType:'json'}}, '*');">Immer ausschließen</button>
				<button type="button" onclick="event.stopPropagation(); const center=window.map.getCenter(); const action={action_message('')}; action.tourenbildung_action_id=Date.now(); action.tourenbildung_zoom=window.map.getZoom(); action.tourenbildung_center={{lat:center.lat,lng:center.lng}}; window.parent.postMessage({{isStreamlitMessage:true,type:'streamlit:setComponentValue',value:action,dataType:'json'}}, '*');">Normale Filter</button>
			"""
			folium.Popup(popup_html, max_width=500).add_to(marker)
			marker.add_to(order_markers)

		map_action = st_folium(
			order_map,
			key="tourenbildung_map",
			width=None,
			height=600,
			zoom=map_view.get("zoom"),
			center=map_view.get("center"),
			returned_objects=[],
			feature_group_to_add=order_markers,
		)
		if isinstance(map_action, dict):
			selected_popup_order = map_action.get("tourenbildung_order")
			selected_popup_override = map_action.get("tourenbildung_override")
			selected_action_id = map_action.get("tourenbildung_action_id")
			selected_map_center = map_action.get("tourenbildung_center")
			selected_map_zoom = map_action.get("tourenbildung_zoom")
			if (
				isinstance(selected_map_center, dict)
				and isinstance(selected_map_zoom, (int, float))
				and isinstance(selected_map_center.get("lat"), (int, float))
				and isinstance(selected_map_center.get("lng"), (int, float))
			):
				st.session_state["tourenbildung_map_view"] = {
					"center": [selected_map_center["lat"], selected_map_center["lng"]],
					"zoom": selected_map_zoom,
				}
			if (
				isinstance(selected_popup_order, int)
				and selected_popup_order in orders.index
				and selected_popup_override in FILTER_OVERRIDE_VALUES
				and isinstance(selected_action_id, int)
				and selected_action_id != st.session_state.get("tourenbildung_last_action_id")
			):
				st.session_state["tourenbildung_last_action_id"] = selected_action_id
				orders.loc[selected_popup_order, FILTER_OVERRIDE_COLUMN] = selected_popup_override
				orders.loc[selected_popup_order, QUANTITY_THRESHOLD_OVERRIDE_COLUMN] = False
				save_orders(orders, orders_path)
				st.rerun()

if st.button("Weiter", type="primary", disabled=not order_matches.any()):
	st.session_state["tourenbildung_filtered_order_indices"] = orders.index[order_matches].tolist()
	st.session_state["tourenbildung_active_order_indices"] = orders.index[order_matches].tolist()
	st.switch_page("pages/04_Tourenbildung.py")
