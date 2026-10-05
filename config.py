"""Small file-based configuration interface for the prototype."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_SETTINGS = {
    "language": "German",
    "view": "Standard",
    "map_dot_min_size": 5,
    "map_dot_max_size": 18,
    "komplettourgrenze": 20000,
    "selected_verladestelle": None,
    "vehicles": {
        "Sattelzug": {"enabled": True, "capacity": 40},
        "Dreiachser": {"enabled": True, "capacity": 30},
    },
}


def load_settings(path: Path) -> dict[str, Any]:
    """Load settings or return the default values."""
    if not path.exists():
        return DEFAULT_SETTINGS.copy()

    with path.open(encoding="utf-8") as settings_file:
        stored_settings = json.load(settings_file)

    merged_settings = {**DEFAULT_SETTINGS, **stored_settings}

    if "language" not in merged_settings and "sprache" in stored_settings:
        merged_settings["language"] = stored_settings["sprache"]
    if "view" not in merged_settings and "ansicht" in stored_settings:
        merged_settings["view"] = stored_settings["ansicht"]

    return merged_settings


def save_settings(path: Path, settings: dict[str, Any]) -> None:
    """Save settings to a small JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as settings_file:
        json.dump(settings, settings_file, ensure_ascii=False, indent=2)
        settings_file.write("\n")


def save_selected_verladestelle(path: Path, name: str) -> None:
    """Persist the selected loading point without changing other settings."""
    settings = load_settings(path)
    settings["selected_verladestelle"] = name
    save_settings(path, settings)


def save_vehicles(path: Path, vehicles: dict[str, dict[str, Any]]) -> None:
    """Persist vehicle availability and capacity without changing other settings."""
    settings = load_settings(path)
    settings["vehicles"] = vehicles
    save_settings(path, settings)


def has_enabled_vehicle(settings: dict[str, Any]) -> bool:
    """Return whether at least one configured vehicle type is enabled."""
    return any(vehicle.get("enabled", False) for vehicle in settings["vehicles"].values())


def selected_vehicle_type(settings: dict[str, Any]) -> str | None:
    """Return the first enabled vehicle type, if one is configured."""
    return next(
        (
            vehicle_type
            for vehicle_type, vehicle in settings["vehicles"].items()
            if vehicle.get("enabled", False)
        ),
        None,
    )


def has_valid_selected_vehicle(settings: dict[str, Any]) -> bool:
    """Return whether the selected vehicle has a positive integer capacity."""
    vehicle_type = selected_vehicle_type(settings)
    if vehicle_type is None:
        return False
    capacity = settings["vehicles"][vehicle_type].get("capacity")
    return isinstance(capacity, int) and not isinstance(capacity, bool) and capacity > 0
