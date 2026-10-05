"""Streamlit component registration for the interactive route editor."""

from pathlib import Path

import streamlit.components.v1 as components


route_editor = components.declare_component(
	"route_editor",
	path=Path(__file__).resolve().parent / "components" / "route_editor",
)
