"""Small browser component for persisting the selected profile cookie."""

from pathlib import Path

import streamlit.components.v1 as components


_profile_cookie = components.declare_component(
    "profile_cookie",
    path=Path(__file__).resolve().parent / "components" / "profile_cookie",
)


def sync_profile_cookie(profile_id: str) -> None:
    """Write the selected profile ID to a long-lived browser cookie."""
    _profile_cookie(profile_id=profile_id, key="profile_cookie_sync", height=0)
