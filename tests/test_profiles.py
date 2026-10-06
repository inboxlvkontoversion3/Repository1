from datetime import date
from pathlib import Path

import pandas as pd
from streamlit.testing.v1 import AppTest

from config import load_settings, save_settings
from order_import import ORDER_COLUMNS, load_orders, save_orders
from profiles import (
    PROFILE_IDS,
    PROFILE_NAMES,
    PROFILES,
    get_profile_paths,
    initialize_profile_workspace,
    load_profile_state,
    resolve_profile_selection,
    save_profile_state,
)


def test_six_fixed_profiles_have_stable_ids_and_display_names() -> None:
    assert len(PROFILES) == 6
    assert PROFILE_IDS == ("1", "2", "3", "4", "5", "6")
    assert tuple(profile.name for profile in PROFILES) == (
        "Hübinger",
        "Broll",
        "Kolodziej",
        "Grevener",
        "Zehner",
        "Gast",
    )


def test_profile_switch_selection_takes_precedence_over_saved_cookie() -> None:
    assert resolve_profile_selection("6", "4") == "6"
    assert resolve_profile_selection(None, "4") == "4"
    assert resolve_profile_selection("unknown", None) is None


def test_app_blocks_pages_until_profile_is_selected() -> None:
    app_path = Path(__file__).parents[1] / "app.py"
    app_test = AppTest.from_file(str(app_path)).run(timeout=15)

    assert not app_test.exception
    assert app_test.session_state.get("active_profile_id") is None
    assert not app_test.title
    assert app_test.selectbox(key="pending_profile_selector").options == list(
        PROFILE_NAMES.values()
    )
    assert any("Benutzerprofil" in warning.value for warning in app_test.warning)

    app_test.selectbox(key="pending_profile_selector").select("Grevener")
    app_test.button(key="confirm_profile_selection").click().run(timeout=15)

    assert not app_test.exception
    assert app_test.session_state.get("active_profile_id") == "4"
    assert [element.value for element in app_test.title] == ["Grundparameter"]
    assert app_test.selectbox(key="profile_selector").value == "4"

    app_test.selectbox(key="profile_selector").select("Gast").run(timeout=15)

    assert not app_test.exception
    assert app_test.session_state.get("active_profile_id") == "6"
    assert app_test.selectbox(key="profile_selector").value == "6"


def test_profile_initialization_does_not_import_legacy_shared_data(tmp_path: Path) -> None:
    legacy_orders_path = tmp_path / "data" / "Aufträge.xlsx"
    legacy_settings_path = tmp_path / ".autotourenplaner" / "settings.json"
    legacy_orders = pd.DataFrame([{column: "" for column in ORDER_COLUMNS}])
    legacy_orders.loc[0, "Ort"] = "Musterstadt"
    save_orders(legacy_orders, legacy_orders_path)
    save_settings(legacy_settings_path, {"view": "Kompakt"})

    paths = initialize_profile_workspace(tmp_path, PROFILE_IDS[0])

    assert load_orders(paths.orders).empty
    assert not paths.settings.exists()
    assert not paths.state.exists()
    assert not get_profile_paths(tmp_path, PROFILE_IDS[1]).orders.parent.exists()
    assert legacy_orders_path.exists()
    assert legacy_settings_path.exists()


def test_profile_initialization_preserves_existing_data(tmp_path: Path) -> None:
    paths = get_profile_paths(tmp_path, PROFILE_IDS[0])
    orders = pd.DataFrame([{column: "" for column in ORDER_COLUMNS}])
    orders.loc[0, "Ort"] = "Profilstadt"
    save_orders(orders, paths.orders)
    save_settings(paths.settings, {"view": "Kompakt"})

    initialize_profile_workspace(tmp_path, PROFILE_IDS[0])

    assert load_orders(paths.orders)["Ort"].tolist() == ["Profilstadt"]
    assert load_settings(paths.settings)["view"] == "Kompakt"


def test_profile_state_round_trips_dates_pins_and_manual_order(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state = {
        "filter_date_range_value": (date(2026, 9, 1), date(2026, 9, 30)),
        "reihenfolge_active_tour_signature": (1, 2, 3),
        "reihenfolge_pinned_positions": {2: 1, 3: 2},
        "reihenfolge_manual_route": [2, 3, 1],
        "reihenfolge_route_result": {"route": [0, 2, 3, 1, 0]},
    }

    save_profile_state(state_path, state)
    loaded_state = load_profile_state(state_path)

    assert loaded_state["filter_date_range_value"] == state["filter_date_range_value"]
    assert loaded_state["reihenfolge_active_tour_signature"] == (1, 2, 3)
    assert loaded_state["reihenfolge_pinned_positions"] == {2: 1, 3: 2}
    assert loaded_state["reihenfolge_manual_route"] == [2, 3, 1]
    assert "reihenfolge_route_result" not in loaded_state


def test_profile_paths_reject_unknown_ids(tmp_path: Path) -> None:
    try:
        get_profile_paths(tmp_path, "../other")
    except ValueError as error:
        assert "Unbekanntes Benutzerprofil" in str(error)
    else:
        raise AssertionError("Unknown profile IDs must not produce workspace paths.")


def test_profile_cookie_component_persists_the_selected_id() -> None:
    component_path = Path(__file__).parents[1] / "components" / "profile_cookie" / "index.html"
    component_source = component_path.read_text(encoding="utf-8")

    assert 'const name = "autotourenplaner_profile"' in component_source
    assert "Max-Age=31536000" in component_source
    assert 'event.data.args?.profile_id' in component_source
