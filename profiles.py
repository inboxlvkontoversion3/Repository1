"""Profile-specific workspaces and saved planning state."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping

import pandas as pd

from order_import import ORDER_COLUMNS, save_orders


PROFILE_COOKIE_NAME = "autotourenplaner_profile"


@dataclass(frozen=True)
class Profile:
    id: str
    name: str


PROFILES = (
    Profile("1", "Hübinger"),
    Profile("2", "Broll"),
    Profile("3", "Kolodziej"),
    Profile("4", "Grevener"),
    Profile("5", "Zehner"),
    Profile("6", "Gast"),
)
PROFILE_IDS = tuple(profile.id for profile in PROFILES)
PROFILE_NAMES = {profile.id: profile.name for profile in PROFILES}


def resolve_profile_selection(
    selected_profile_id: str | None,
    cookie_profile_id: str | None,
) -> str | None:
    """Keep a valid current selection; use the cookie only to initialize it."""
    if selected_profile_id in PROFILE_IDS:
        return selected_profile_id
    if cookie_profile_id in PROFILE_IDS:
        return cookie_profile_id
    return None


PROFILE_STATE_KEYS = (
    "filter_vehicle_types_value",
    "filter_vehicle_types_default_type",
    "filter_date_range_value",
    "filter_postal_input_value",
    "tourenbildung_filtered_order_indices",
    "tourenbildung_active_order_indices",
    "tourenbildung_map_view",
    "reihenfolge_active_tour_signature",
    "reihenfolge_pinned_positions",
    "reihenfolge_manual_route",
)


@dataclass(frozen=True)
class ProfilePaths:
    orders: Path
    settings: Path
    state: Path


def get_profile_paths(project_root: Path, profile_id: str) -> ProfilePaths:
    """Return the storage paths for a known profile ID."""
    if profile_id not in PROFILE_IDS:
        raise ValueError(f"Unbekanntes Benutzerprofil: {profile_id}")

    profile_directory = project_root / ".autotourenplaner" / "profiles" / profile_id
    return ProfilePaths(
        orders=profile_directory / "Aufträge.xlsx",
        settings=profile_directory / "settings.json",
        state=profile_directory / "state.json",
    )


def initialize_profile_workspace(project_root: Path, profile_id: str) -> ProfilePaths:
    """Create the selected profile's workspace without changing existing data."""
    paths = get_profile_paths(project_root, profile_id)
    paths.orders.parent.mkdir(parents=True, exist_ok=True)

    if not paths.orders.exists():
        save_orders(pd.DataFrame(columns=ORDER_COLUMNS), paths.orders)

    return paths


def load_profile_state(path: Path) -> dict[str, Any]:
    """Load serializable, profile-specific planning state."""
    if not path.exists():
        return {}

    with path.open(encoding="utf-8") as state_file:
        state = json.load(state_file, object_hook=_decode_state_value)
    if not isinstance(state, dict):
        raise ValueError(f"Ungültige Profildaten in {path}")
    loaded_state = {key: value for key, value in state.items() if key in PROFILE_STATE_KEYS}
    for key in ("filter_date_range_value", "reihenfolge_active_tour_signature"):
        value = loaded_state.get(key)
        if isinstance(value, list):
            loaded_state[key] = tuple(value)
    pinned_positions = loaded_state.get("reihenfolge_pinned_positions")
    if isinstance(pinned_positions, dict):
        loaded_state["reihenfolge_pinned_positions"] = {
            int(stop): int(position) for stop, position in pinned_positions.items()
        }
    return loaded_state


def save_profile_state(path: Path, session_state: Mapping[str, Any]) -> None:
    """Atomically save only the user-facing planning state, not derived caches."""
    state = {
        key: session_state[key]
        for key in PROFILE_STATE_KEYS
        if key in session_state
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.stem}-",
            suffix=path.suffix,
            delete=False,
        ) as state_file:
            temporary_path = state_file.name
            json.dump(state, state_file, ensure_ascii=False, indent=2, default=_encode_state_value)
            state_file.write("\n")
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            Path(temporary_path).unlink(missing_ok=True)


def _encode_state_value(value: object) -> object:
    if isinstance(value, date):
        return {"__date__": value.isoformat()}
    if isinstance(value, tuple):
        return {"__tuple__": list(value)}
    raise TypeError(f"Nicht unterstützter Wert im Profilstatus: {type(value).__name__}")


def _decode_state_value(value: dict[str, Any]) -> object:
    if set(value) == {"__date__"}:
        return date.fromisoformat(value["__date__"])
    if set(value) == {"__tuple__"}:
        return tuple(value["__tuple__"])
    return value
