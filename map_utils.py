"""Helpers for displaying orders on the planning map."""

from __future__ import annotations

from datetime import date
from math import exp, log

import pandas as pd


def stop_position_color(position: int, stop_count: int) -> str:
    """Return a red-to-green color based on a stop's 1-based route position."""
    start = (220, 38, 38)
    end = (22, 163, 74)
    progress = 0.0 if stop_count <= 1 else (position - 1) / (stop_count - 1)
    progress = max(0.0, min(1.0, progress))
    channels = [round(first + progress * (last - first)) for first, last in zip(start, end)]
    return "#" + "".join(f"{channel:02x}" for channel in channels)


def scale_quantity_to_radius(
    quantity: float,
    quantity_min: float,
    quantity_max: float,
    radius_min: int,
    radius_max: int,
) -> float:
    """Map an order quantity geometrically to a clamped marker radius."""
    if radius_min > radius_max:
        radius_min, radius_max = radius_max, radius_min
    if quantity_max <= quantity_min:
        return float(radius_min)
    proportion = (quantity - quantity_min) / (quantity_max - quantity_min)
    proportion = max(0.0, min(1.0, proportion))
    if proportion == 0.0:
        return float(radius_min)
    if proportion == 1.0:
        return float(radius_max)
    return exp(log(radius_min) + proportion * (log(radius_max) - log(radius_min)))


def filter_orders(
    orders: pd.DataFrame,
    vehicle_types: list[str] | None = None,
    date_range: tuple[date, date] | None = None,
    postal_prefixes: list[str] | None = None,
) -> pd.Series:
    """Return a mask for orders matching all active filters."""
    mask = pd.Series(True, index=orders.index)

    if vehicle_types:
        mask &= orders["Fahrzeugart"].fillna("").astype(str).isin(vehicle_types)

    if date_range:
        order_dates = pd.to_datetime(orders["Termin bis"], dayfirst=True, errors="coerce")
        start_date, end_date = date_range
        mask &= order_dates.dt.date.ge(start_date) & order_dates.dt.date.le(end_date)

    if postal_prefixes:
        postal_codes = orders["PLZ"].fillna("").astype(str)
        mask &= postal_codes.map(
            lambda postal_code: any(postal_code.startswith(prefix) for prefix in postal_prefixes)
        )

    return mask
