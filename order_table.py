"""Streamlit component registration for the inline orders table."""

from pathlib import Path

import streamlit.components.v1 as components


order_table = components.declare_component(
	"order_table",
	path=Path(__file__).resolve().parent / "components" / "order_table",
)
