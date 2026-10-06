"""Select filtered orders for tour formation."""

from copy import deepcopy
from html import escape
import json
from pathlib import Path

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from config import has_valid_selected_vehicle, load_settings
from map_utils import scale_quantity_to_radius
from profiles import get_profile_paths
from order_import import (
	GEOCODING_STATUS_COLUMN,
	load_orders,
	normalize_order_postal_codes,
	vehicle_assignment_counts,
)


project_root = Path(__file__).resolve().parents[1]
profile_paths = get_profile_paths(project_root, st.session_state["active_profile_id"])
settings_path = profile_paths.settings
if not has_valid_selected_vehicle(load_settings(settings_path)):
	st.warning("Die Kapazität des ausgewählten Fahrzeugtyps muss eine natürliche Zahl sein.")
	st.stop()

orders_path = profile_paths.orders
if not orders_path.exists():
	st.warning("Legen Sie mindestens einen Auftrag auf der Seite Aufträge an.")
	st.stop()

orders = normalize_order_postal_codes(load_orders(orders_path))
filtered_indices = st.session_state.get("tourenbildung_filtered_order_indices")
if not filtered_indices:
	st.warning("Bitte wählen Sie zuerst Aufträge auf der Seite Aufträge filtern aus.")
	st.stop()

filtered_indices = [index for index in filtered_indices if index in orders.index]
if not filtered_indices:
	st.warning("Die gefilterten Aufträge sind nicht mehr vorhanden. Bitte wenden Sie den Filter erneut an.")
	st.stop()

filtered_orders = orders.loc[filtered_indices]
active_indices = set(st.session_state.get("tourenbildung_active_order_indices", filtered_indices))
active_indices.intersection_update(filtered_indices)
st.session_state["tourenbildung_active_order_indices"] = list(active_indices)


def format_value(value: object) -> str:
	if pd.isna(value):
		return ""
	return str(value)


@st.dialog("Auftragsdetails")
def show_order_details(order_index: object) -> None:
	order = orders.loc[order_index]
	dreiachser, sattelzug = vehicle_assignment_counts(order)
	excluded_columns = {"Breite", "Länge", GEOCODING_STATUS_COLUMN}
	for column, value in order.items():
		if column not in excluded_columns:
			st.write(f"**{column}:** {format_value(value)}")
	st.write(f"**Aufträge Dreiachser:** {format_value(dreiachser)}")
	st.write(f"**Aufträge Sattelzug:** {format_value(sattelzug)}")


st.title("Tourenbildung")
st.write("Markieren Sie die Aufträge, die in die Tourenbildung übernommen werden sollen.")
st.markdown(
	"""
	<style>
	.st-key-tourenbildung_order_list {
		gap: 0.25rem;
	}
	.st-key-tourenbildung_order_list .stButton > button {
		min-height: 2rem;
		padding: 0.15rem 0.5rem;
	}
	</style>
	""",
	unsafe_allow_html=True,
)

total_quantity = pd.to_numeric(filtered_orders["Anzahl"], errors="coerce").fillna(0).sum()
active_orders = filtered_orders.loc[filtered_orders.index.isin(active_indices)]
active_quantity = pd.to_numeric(active_orders["Anzahl"], errors="coerce").fillna(0).sum()

widget_column, map_column = st.columns(2, gap="medium")
with widget_column:
	status_columns = st.columns([1, 1, 0.55], gap="small")
	with status_columns[0]:
		st.markdown(f"**Gefiltert:** {len(filtered_orders)} Aufträge, {total_quantity:g}l |")
	with status_columns[1]:
		st.markdown(f"**Aktiv:** {len(active_orders)} Aufträge, {active_quantity:g}l |")
	with status_columns[2]:
		if st.button("Weiter", type="primary", disabled=not active_indices):
			st.switch_page("pages/05_Reihenfolge.py")

	with st.container(key="tourenbildung_order_list"):
		for order_index, order in filtered_orders.iterrows():
			is_active = order_index in active_indices
			status_label = "Aktiv" if is_active else "Inaktiv"
			deadline = format_value(order["Termin bis"])
			quantity = format_value(order["Anzahl"])
			label_parts = []
			if deadline:
				label_parts.append(deadline)
			if quantity:
				label_parts.append(f"{quantity:>4}l")
			if format_value(order['PLZ']):
				label_parts.append(format_value(order['PLZ']))
			if format_value(order['Ort']):
				label_parts.append(format_value(order['Ort']))
			if format_value(order['Straße']):
				label_parts.append(format_value(order['Straße']))
			label = " | ".join(label_parts)
			order_columns = st.columns([8, 1, 0.6], gap="small")
			with order_columns[0]:
				st.write(label)
			with order_columns[1]:
				if st.button(status_label, key=f"tourenbildung_active_{order_index}", type="primary" if is_active else "secondary"):
					if is_active:
						active_indices.remove(order_index)
					else:
						active_indices.add(order_index)
					st.session_state["tourenbildung_active_order_indices"] = list(active_indices)
					st.rerun()
			with order_columns[2]:
				if st.button("i", key=f"tourenbildung_details_{order_index}"):
					show_order_details(order_index)


with map_column:
	st.subheader("Karte")
	mapped_orders = filtered_orders.copy()
	mapped_orders["Breite"] = pd.to_numeric(mapped_orders["Breite"], errors="coerce")
	mapped_orders["Länge"] = pd.to_numeric(mapped_orders["Länge"], errors="coerce")
	mapped_orders["Anzahl"] = pd.to_numeric(mapped_orders["Anzahl"], errors="coerce").fillna(0)
	mapped_orders = mapped_orders.dropna(subset=["Breite", "Länge"])
	verladestelle = pd.DataFrame()
	verladestellen_path = project_root / "data" / "Verladestellen.xlsx"
	if verladestellen_path.exists():
		verladestellen = pd.read_excel(verladestellen_path)
		selected_name = load_settings(settings_path).get("selected_verladestelle")
		if selected_name and "Name" in verladestellen.columns:
			selected_rows = verladestellen.loc[verladestellen["Name"].astype(str) == str(selected_name)]
			if not selected_rows.empty:
				verladestelle = selected_rows.iloc[0]
	if not verladestelle.empty:
		verladestelle["Breite"] = pd.to_numeric(verladestelle.get("Breite"), errors="coerce")
		verladestelle["Länge"] = pd.to_numeric(verladestelle.get("Länge"), errors="coerce")
		if pd.isna(verladestelle["Breite"]) or pd.isna(verladestelle["Länge"]):
			verladestelle = pd.DataFrame()
	if mapped_orders.empty:
		st.warning("Für die gefilterten Aufträge sind keine Kartenkoordinaten vorhanden.")
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
		settings = load_settings(settings_path)
		min_size = int(settings["map_dot_min_size"])
		max_size = int(settings["map_dot_max_size"])
		if min_size > max_size:
			min_size, max_size = max_size, min_size
		quantity_min = mapped_orders["Anzahl"].min()
		quantity_max = mapped_orders["Anzahl"].max()
		order_map = folium.Map(
			location=map_center,
			zoom_start=9,
			tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
			attr="Tiles &copy; Esri",
		)
		order_map.fit_bounds(map_bounds, padding=(0, 0))
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
				popup=f"Verladestelle: {escape(str(verladestelle['Name']))}",
			).add_to(order_map)
		order_markers = folium.FeatureGroup(name="Aufträge")
		for order_index, order in mapped_orders.iterrows():
			is_active = order_index in active_indices
			color = "#15803d" if is_active else "#9ca3af"
			address = f"{order['PLZ']} {order['Ort']}, {order['Straße']}"
			marker = folium.CircleMarker(
				location=[order["Breite"], order["Länge"]],
				radius=scale_quantity_to_radius(order["Anzahl"], quantity_min, quantity_max, min_size, max_size),
				color=color,
				fill=True,
				fill_color=color,
				fill_opacity=0.85 if is_active else 0.25,
				opacity=0.95 if is_active else 0.4,
			)
			marker._id = f"order_marker_{order_index}"
			marker_name = marker.get_name()
			next_active = not is_active
			action = escape(
				json.dumps(
					{
						"tourenbildung_order": int(order_index),
						"tourenbildung_active": next_active,
					}
				),
				quote=True,
			)
			active_color = "#15803d"
			inactive_color = "#9ca3af"
			popup_html = f"""
				<div>{escape(address)}<br>Anzahl: {order['Anzahl']:g}</div>
				<hr style="margin: 6px 0">
				<button type="button" onclick="event.stopPropagation(); const center=window.map.getCenter(); const action={action}; action.tourenbildung_action_id=Date.now(); action.tourenbildung_zoom=window.map.getZoom(); action.tourenbildung_center={{lat:center.lat,lng:center.lng}}; window.parent.postMessage({{isStreamlitMessage:true,type:'streamlit:setComponentValue',value:action,dataType:'json'}}, '*'); try {{ const marker=window.{marker_name}; if (marker) marker.setStyle({{color:'{active_color if next_active else inactive_color}', fillColor:'{active_color if next_active else inactive_color}', fillOpacity:{0.85 if next_active else 0.25}, opacity:{0.95 if next_active else 0.4}}}); }} catch (error) {{}}">{'Deaktivieren' if is_active else 'Aktivieren'}</button>
			"""
			folium.Popup(popup_html).add_to(marker)
			marker.add_to(order_markers)
		map_view = st.session_state.get("tourenbildung_map_view", {})
		map_action = st_folium(
			deepcopy(order_map),
			key=f"tourenbildung_order_map_{st.session_state['active_profile_id']}",
			width=None,
			height=600,
			zoom=map_view.get("zoom"),
			center=map_view.get("center"),
			returned_objects=[],
			feature_group_to_add=order_markers,
		)
		if isinstance(map_action, dict):
			selected_order = map_action.get("tourenbildung_order")
			selected_active = map_action.get("tourenbildung_active")
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
				isinstance(selected_order, int)
				and selected_order in filtered_orders.index
				and isinstance(selected_active, bool)
				and isinstance(selected_action_id, int)
				and selected_action_id != st.session_state.get("tourenbildung_last_action_id")
			):
				st.session_state["tourenbildung_last_action_id"] = selected_action_id
				active_indices = set(st.session_state.get("tourenbildung_active_order_indices", filtered_indices))
				if selected_active:
					active_indices.add(selected_order)
				else:
					active_indices.discard(selected_order)
				st.session_state["tourenbildung_active_order_indices"] = list(active_indices)
				st.rerun()