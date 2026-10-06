"""Optimize and display the order of stops in one tour."""

from html import escape
from copy import deepcopy
import os
from pathlib import Path

import folium
import pandas as pd
import streamlit as st
from folium.plugins import AntPath
from folium.template import Template
from streamlit_folium import st_folium

from config import has_valid_selected_vehicle, load_settings
from profiles import get_profile_paths
from order_import import (
	GEOCODING_STATUS_COLUMN,
	load_orders,
	normalize_order_postal_codes,
	vehicle_assignment_counts,
)
from route_editor import route_editor
from routing import (
	DEFAULT_OSRM_ENDPOINT,
	RoutingError,
	fetch_osrm_route,
	fetch_osrm_table,
	haversine_matrix,
	optimize_route,
	route_signature,
)


project_root = Path(__file__).resolve().parents[1]
profile_paths = get_profile_paths(project_root, st.session_state["active_profile_id"])
settings_path = profile_paths.settings
settings = load_settings(settings_path)
if not has_valid_selected_vehicle(settings):
	st.warning("Die Kapazität des ausgewählten Fahrzeugtyps muss eine natürliche Zahl sein.")
	st.stop()

orders_path = profile_paths.orders
if not orders_path.exists():
	st.warning("Legen Sie mindestens einen Auftrag auf der Seite Aufträge an.")
	st.stop()


def format_value(value: object) -> str:
	if pd.isna(value):
		return ""
	return str(value)


def format_duration(seconds: float) -> str:
	minutes = round(seconds / 60)
	hours, remaining_minutes = divmod(minutes, 60)
	return f"{hours} Std. {remaining_minutes:02d} Min." if hours else f"{remaining_minutes} Min."


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


class DynamicAntPath(AntPath):
	_template = Template(
		"""
		{% macro script(this, kwargs) %}
			var {{ this.get_name() }} = L.polyline.antPath(
				{{ this.locations|tojson }},
				{{ this.options|tojavascript }}
			).addTo({{ this._parent.get_name() }});
		{% endmacro %}
		"""
	)


def load_selected_depot() -> pd.Series | None:
	depot_path = project_root / "data" / "Verladestellen.xlsx"
	if not depot_path.exists():
		return None
	depots = pd.read_excel(depot_path)
	selected_name = settings.get("selected_verladestelle")
	if not selected_name or "Name" not in depots.columns:
		return None
	selected = depots.loc[depots["Name"].astype(str) == str(selected_name)]
	return selected.iloc[0] if not selected.empty else None

st.title("Reihenfolge")
st.write("Die aktiven Aufträge werden mit der Verladestelle als Start und Ziel angeordnet.")

active_indices = list(st.session_state.get("tourenbildung_active_order_indices", []))
active_tour_signature = tuple(active_indices)
if st.session_state.get("reihenfolge_active_tour_signature") != active_tour_signature:
	st.session_state["reihenfolge_active_tour_signature"] = active_tour_signature
	st.session_state["reihenfolge_pinned_positions"] = {}
	st.session_state.pop("reihenfolge_manual_route", None)

if not active_indices:
	st.info("Aktivieren Sie zuerst mindestens einen Auftrag auf der Seite Tourenbildung.")
	st.stop()

orders = normalize_order_postal_codes(load_orders(orders_path))
missing_indices = [index for index in active_indices if index not in orders.index]
if missing_indices:
	st.error("Ein oder mehrere aktive Aufträge sind nicht mehr vorhanden. Bitte bilden Sie die Tour erneut.")
	st.stop()
active_orders = orders.loc[active_indices].copy()
active_orders["Breite"] = pd.to_numeric(active_orders["Breite"], errors="coerce")
active_orders["Länge"] = pd.to_numeric(active_orders["Länge"], errors="coerce")
invalid_coordinates = active_orders[active_orders[["Breite", "Länge"]].isna().any(axis=1)]
if not invalid_coordinates.empty:
	invalid_addresses = ", ".join(
		f"{format_value(row['PLZ'])} {format_value(row['Ort'])}" for _, row in invalid_coordinates.iterrows()
	)
	st.error(f"Für folgende aktive Aufträge fehlen Kartenkoordinaten: {invalid_addresses}")
	st.stop()

depot = load_selected_depot()
if depot is None:
	st.error("Die ausgewählte Verladestelle konnte nicht gefunden werden.")
	st.stop()
depot_latitude = pd.to_numeric(depot.get("Breite"), errors="coerce")
depot_longitude = pd.to_numeric(depot.get("Länge"), errors="coerce")
if pd.isna(depot_latitude) or pd.isna(depot_longitude):
	st.error("Für die ausgewählte Verladestelle fehlen Kartenkoordinaten.")
	st.stop()

endpoint = os.environ.get("OSRM_ENDPOINT", DEFAULT_OSRM_ENDPOINT)
points = [(float(depot_latitude), float(depot_longitude))]
points.extend((float(row["Breite"]), float(row["Länge"])) for _, row in active_orders.iterrows())
signature_stops = [("depot", points[0][0], points[0][1])]
signature_stops.extend(
	(index, latitude, longitude)
	for index, (latitude, longitude) in zip(active_orders.index, points[1:])
)
base_signature = route_signature(signature_stops, endpoint)

expected_route_stops = set(range(1, len(active_orders) + 1))
manual_route = st.session_state.get("reihenfolge_manual_route")
if manual_route and set(manual_route) != expected_route_stops:
	manual_route = None
	st.session_state.pop("reihenfolge_manual_route", None)

pinned_positions = {
	int(stop): int(position)
	for stop, position in st.session_state.get("reihenfolge_pinned_positions", {}).items()
	if int(stop) in expected_route_stops and 1 <= int(position) <= len(active_orders)
}
if len(set(pinned_positions.values())) != len(pinned_positions):
	pinned_positions = {}
	st.session_state["reihenfolge_pinned_positions"] = pinned_positions

cached_result = st.session_state.get("reihenfolge_route_result")
if cached_result and (
	cached_result.get("signature") != base_signature
	 or "leg_geometry" not in cached_result
):
	cached_result = None
	st.session_state.pop("reihenfolge_route_result", None)

if st.button("Reihenfolge optimieren", type="primary"):
	st.session_state.pop("reihenfolge_manual_route", None)
	cached_result = None
	st.session_state.pop("reihenfolge_route_result", None)
	st.rerun()

if cached_result is None:
	with st.spinner("Fahrzeiten werden abgerufen und die Reihenfolge wird berechnet ..."):
		try:
			if manual_route:
				route = [0, *manual_route, 0]
			else:
				duration_matrix, _distance_matrix = fetch_osrm_table(points, endpoint=endpoint)
				straight_line_matrix = haversine_matrix(points)
				route = optimize_route(
					duration_matrix,
					straight_line_matrix,
					fixed_positions=pinned_positions,
				)
			route_geometry = fetch_osrm_route([points[index] for index in route], endpoint=endpoint)
		except RoutingError as error:
			st.error(f"Die Route konnte nicht berechnet werden: {error}")
			st.stop()
		cached_result = {
			"signature": base_signature,
			"route": route,
			"geometry": route_geometry.coordinates,
			"leg_geometry": route_geometry.leg_coordinates,
			"distance_m": route_geometry.distance_m,
			"duration_s": route_geometry.duration_s,
		}
		st.session_state["reihenfolge_route_result"] = cached_result

route = cached_result["route"]
route_geometry = cached_result["geometry"]
route_points = [points[index] for index in route]

left_column, map_column = st.columns(2, gap="medium")
with left_column:
	st.markdown(
		f"<div style='margin:0 0 0.6rem 0;font-size:1rem;color:inherit;font-weight:400'>"
		f"Gesamtfahrstrecke: {cached_result['distance_m'] / 1000:.1f} km</div>",
		unsafe_allow_html=True,
	)
	editor_rows = []
	for position, point_index in enumerate(route):
		if point_index == 0:
			name = format_value(depot.get("Name"))
			address = format_value(depot.get("Adresse"))
			label = "Verladestelle"
			deadline = "SKW"
			quantity = ""
			rest = address if str(name).upper() == str(deadline).upper() else f"{name} | {address}"
			continue
		order = active_orders.iloc[point_index - 1]
		name = f"{format_value(order['PLZ'])} {format_value(order['Ort'])}"
		address = format_value(order["Straße"])
		label = f"Stopp {position}"
		deadline = format_value(order["Termin bis"])
		quantity = format_value(order["Anzahl"])
		rest = f"{name} | {address}"
		editor_rows.append({
			"point_index": point_index,
			"deadline": deadline,
			"quantity": quantity,
			"rest": rest,
		})
	current_order = route[1:-1]
	depot_name = format_value(depot.get("Name"))
	depot_address = format_value(depot.get("Adresse"))
	depot_rest = depot_address if depot_name.upper() == "SKW" else f"{depot_name} | {depot_address}"
	st.markdown(
		f"<div style='line-height:1.5;margin:0 0 0.15rem 0;font-size:1rem;color:inherit;font-weight:400'>"
		f"1. Verladestelle <span style='font-weight:400;color:inherit'>| SKW | {escape(depot_rest)}</span></div>",
		unsafe_allow_html=True,
	)
	component_action = route_editor(
		rows=editor_rows,
		order=current_order,
		pinned=list(pinned_positions),
		key=f"reihenfolge_editor_{st.session_state['active_profile_id']}",
		default=None,
	)
	st.markdown(
		f"<div style='line-height:1.5;margin:-0.75rem 0 0 0;font-size:1rem;color:inherit;font-weight:400'>"
		f"{len(active_orders) + 2}. Verladestelle <span style='font-weight:400;color:inherit'>| SKW | {escape(depot_rest)}</span></div>",
		unsafe_allow_html=True,
	)
	if isinstance(component_action, dict):
		action_id = component_action.get("action_id")
		if isinstance(action_id, int) and action_id != st.session_state.get("reihenfolge_last_action_id"):
			if (
				component_action.get("type") == "info"
				and isinstance(component_action.get("point_index"), int)
				and component_action["point_index"] in expected_route_stops
			):
				st.session_state["reihenfolge_last_action_id"] = action_id
				show_order_details(active_orders.index[component_action["point_index"] - 1])
				st.stop()
			new_order = component_action.get("order")
			new_pinned = component_action.get("pinned", [])
			if (
				isinstance(new_order, list)
				and set(new_order) == expected_route_stops
				and len(new_order) == len(expected_route_stops)
				and isinstance(new_pinned, list)
				and all(stop in expected_route_stops for stop in new_pinned)
			):
				st.session_state["reihenfolge_last_action_id"] = action_id
				st.session_state["reihenfolge_pinned_positions"] = {
					stop: position for position, stop in enumerate(new_order, start=1) if stop in new_pinned
				}
				if component_action.get("type") == "drag":
					st.session_state["reihenfolge_manual_route"] = new_order
					try:
						route_geometry = fetch_osrm_route(
							[points[index] for index in [0, *new_order, 0]], endpoint=endpoint
						)
					except RoutingError as error:
						st.error(f"Die Route konnte nicht berechnet werden: {error}")
						st.stop()
					st.session_state["reihenfolge_route_result"] = {
						"signature": base_signature,
						"route": [0, *new_order, 0],
						"geometry": route_geometry.coordinates,
						"leg_geometry": route_geometry.leg_coordinates,
						"distance_m": route_geometry.distance_m,
						"duration_s": route_geometry.duration_s,
					}
				st.rerun()

with map_column:
	st.subheader("Karte")
	map_signature = tuple(tuple(point) for point in points)
	map_bounds = [
		[
			min(point[0] for point in route_points),
			min(point[1] for point in route_points),
		],
		[
			max(point[0] for point in route_points),
			max(point[1] for point in route_points),
		],
	]
	map_center = [
		(map_bounds[0][0] + map_bounds[1][0]) / 2,
		(map_bounds[0][1] + map_bounds[1][1]) / 2,
	]
	base_map = st.session_state.get("reihenfolge_base_map")
	if base_map is None or st.session_state.get("reihenfolge_map_signature") != map_signature:
		base_map = folium.Map(
			location=map_center,
			zoom_start=9,
			tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
			attr="Tiles &copy; Esri",
		)
		base_map.fit_bounds(map_bounds, padding=(0, 0))
		DynamicAntPath(route_geometry, weight=0, opacity=0).add_to(base_map)
		folium.RegularPolygonMarker(
			location=points[0],
			number_of_sides=3,
			rotation=-90,
			radius=12,
			color="#b91c1c",
			fill=True,
			fill_color="#b91c1c",
			fill_opacity=0.9,
			popup=f"Verladestelle: {escape(format_value(depot.get('Name')))}",
		).add_to(base_map)
		st.session_state["reihenfolge_base_map"] = base_map
		st.session_state["reihenfolge_map_signature"] = map_signature

	route_layers = folium.FeatureGroup(name="Route")
	folium.PolyLine(route_geometry, color="#1d4ed8", weight=5, opacity=0.85).add_to(route_layers)
	DynamicAntPath(
		route_geometry,
		color="#60a5fa",
		weight=4,
		opacity=0.9,
		dash_array=[12, 20],
		delay=900,
	).add_to(route_layers)
	for position, point_index in enumerate(route[1:-1], start=2):
		latitude, longitude = points[point_index]
		order = active_orders.iloc[point_index - 1]
		popup_html = (
			f"<div><strong>Stopp {position}</strong><br>"
			f"<strong>Adresse:</strong> {escape(format_value(order['PLZ']))} "
			f"{escape(format_value(order['Ort']))}, {escape(format_value(order['Straße']))}<br>"
			f"<strong>Anzahl:</strong> {escape(format_value(order['Anzahl']))}<br>"
			f"<strong>Fahrzeugart:</strong> {escape(format_value(order['Fahrzeugart']))}<br>"
			f"<strong>Termin bis:</strong> {escape(format_value(order['Termin bis']))}<br>"
			f"<strong>Hinweise:</strong> {escape(format_value(order['Hinweise']))}</div>"
		)
		popup = folium.Popup(popup_html, max_width=320)
		popup._id = f"popup_{point_index}"
		popup_element = next(iter(popup.html._children.values()))
		popup_element._id = f"html_popup_{point_index}"
		popup.html._children = {f"html_popup_{point_index}": popup_element}
		folium.Marker(
			location=[latitude, longitude],
			icon=folium.DivIcon(
				html=f'<div style="background:#1d4ed8;color:white;border:2px solid white;border-radius:50%;width:26px;height:26px;text-align:center;line-height:22px;font-weight:700">{position}</div>'
			),
			popup=popup,
		).add_to(route_layers)
	map_action = st_folium(
		deepcopy(base_map),
		key=f"reihenfolge_map_{st.session_state['active_profile_id']}",
		width=None,
		height=600,
		returned_objects=[],
		feature_group_to_add=route_layers,
	)
