from pathlib import Path
from datetime import date
from math import sqrt
from urllib.parse import parse_qs, urlsplit

import pandas as pd

from config import DEFAULT_SETTINGS, has_valid_selected_vehicle, load_settings, save_settings
from map_utils import filter_orders, scale_quantity_to_radius
from order_import import (
    GEOCODING_STATUS_COLUMN,
    GEOCODING_STATUS_NOT_FOUND,
    GEOCODING_STATUS_STREET_FALLBACK,
    ORDER_COLUMNS,
    apply_default_quantity_exclusions,
    geocode_orders,
    load_orders,
    normalize_order_quantity,
	normalize_order_dates,
	normalize_order_countries,
    normalize_order_postal_codes,
    parse_pasted_orders,
    save_orders,
    QUANTITY_THRESHOLD_OVERRIDE_COLUMN,
    update_quantity_threshold_exclusion,
)


PROJECT_ROOT = Path(__file__).parents[1]
PAGES_DIR = PROJECT_ROOT / "pages"


def test_pages_include_filtered_orders_and_tour_generation() -> None:
    page_names = {page.name for page in PAGES_DIR.glob("*.py")}

    assert page_names == {
        "01_Grundparameter.py",
        "02_Aufträge.py",
        "03_Aufträge_filtern.py",
        "04_Tourenbildung.py",
        "05_Reihenfolge.py",
        "06_Einstellungen.py",
    }


def test_first_page_hides_vehicle_capacity_widget() -> None:
    page_source = (PAGES_DIR / "01_Grundparameter.py").read_text(encoding="utf-8")

    assert 'f"Kapazität {vehicle_name}"' not in page_source
    assert 'st.number_input(' not in page_source


def test_filter_page_blocks_progress_when_no_orders_match() -> None:
    page_source = (PAGES_DIR / "03_Aufträge_filtern.py").read_text(encoding="utf-8")

    assert 'Keine Aufträge entsprechen den aktuellen Filtern oder Filterausnahmen.' in page_source
    assert 'disabled=not order_matches.any()' in page_source


def test_order_page_resets_pins_when_active_tours_change() -> None:
    page_source = (PAGES_DIR / "05_Reihenfolge.py").read_text(encoding="utf-8")

    assert 'active_tour_signature = tuple(active_indices)' in page_source
    assert 'st.session_state.get("reihenfolge_active_tour_signature") != active_tour_signature' in page_source
    assert 'st.session_state["reihenfolge_pinned_positions"] = {}' in page_source
    assert 'st.session_state.pop("reihenfolge_manual_route", None)' in page_source


def test_filter_page_persists_filter_widget_values() -> None:
    page_source = (PAGES_DIR / "03_Aufträge_filtern.py").read_text(encoding="utf-8")

    assert 'st.toggle(' in page_source
    assert 'Nicht zugewiesen' in page_source
    assert 'filter_vehicle_type_{vehicle_type or \'unassigned\'}_widget' in page_source
    assert 'key="filter_date_start_widget"' in page_source
    assert 'key="filter_date_end_widget"' in page_source
    assert 'key="filter_postal_input_widget"' in page_source
    assert 'filter_vehicle_types_value' in page_source
    assert 'filter_date_range_value' in page_source
    assert 'filter_postal_input_value' in page_source
    assert 'on_change=save_vehicle_filter' in page_source
    assert 'on_change=save_date_filter' in page_source
    assert 'on_change=save_postal_filter' in page_source
    assert 'default_vehicle_filter = [selected_type] if selected_type in available_vehicle_types else []' in page_source
    assert 'set(settings["vehicles"])' in page_source
    assert 'st.session_state.get("filter_vehicle_types_default_type") != selected_type' in page_source
    assert 'st.session_state.setdefault("filter_postal_input_value", "")' in page_source
    assert 'selected_date_range = (start_date, end_date)' in page_source


def test_order_table_vehicle_filter_uses_configured_vehicle_types() -> None:
    page_source = (PAGES_DIR / "02_Aufträge.py").read_text(encoding="utf-8")
    component_source = (PROJECT_ROOT / "components" / "order_table" / "index.html").read_text(encoding="utf-8")

    assert 'vehicle_types = list(load_settings(settings_path)["vehicles"])' in page_source
    assert "vehicle_types=vehicle_types" in page_source
    assert 'args.vehicle_types || []' in component_source
    assert 'vehicleType || "Nicht zugewiesen"' in component_source
    assert 'render({ rows: state.rows, vehicle_types: state.vehicleTypes.slice(0, -1) });' in component_source


def test_order_page_emphasizes_total_without_growing_table_height() -> None:
    page_source = (PAGES_DIR / "02_Aufträge.py").read_text(encoding="utf-8")
    component_source = (PROJECT_ROOT / "components" / "order_table" / "index.html").read_text(encoding="utf-8")

    assert 'font-size: 20px; line-height: 1.5' in page_source
    assert 'Anzahl gesamt: <strong>{total_quantity:g}</strong>' in page_source
    assert '#scroll { max-height: 519px;' in component_source
    assert '#scroll { max-height: 486px; }' in component_source
    assert 'height: 562,' in component_source


def test_order_table_hover_reveals_only_overflowing_values() -> None:
    component_source = (PROJECT_ROOT / "components" / "order_table" / "index.html").read_text(encoding="utf-8")

    assert '.cell[data-full-value][data-overflow="true"]:hover::after' in component_source
    assert 'textMeasure.measureText(text).width > availableWidth' in component_source


def test_order_table_date_picker_opens_from_the_cell() -> None:
    page_source = (PAGES_DIR / "02_Aufträge.py").read_text(encoding="utf-8")
    component_source = (PROJECT_ROOT / "components" / "order_table" / "index.html").read_text(encoding="utf-8")

    assert 'if (column === "Termin bis") input.type = "date";' in component_source
    assert 'input.addEventListener("click", () => input.showPicker?.());' in component_source
    assert 'actionId: Date.now()' in component_source
    assert 'column in {"Termin bis", "Anzahl", "Fahrzeugart", "Hinweise"}' in page_source
    assert 'date.fromisoformat(value).strftime("%d.%m.%Y")' in page_source
    assert "if normalize_order_dates(orders):" in page_source
    assert 'save_orders(orders, orders_path)' in page_source


def test_order_table_colors_geocoding_failures_by_severity() -> None:
    page_source = (PAGES_DIR / "02_Aufträge.py").read_text(encoding="utf-8")
    component_source = (PROJECT_ROOT / "components" / "order_table" / "index.html").read_text(encoding="utf-8")

    assert '[*visible_columns, GEOCODING_STATUS_COLUMN]' in page_source
    assert 'displayed_orders[GEOCODING_STATUS_COLUMN].fillna("").astype(str)' in page_source
    assert 'displayed_orders.astype(object).where(pd.notna(displayed_orders), None).to_dict("records")' in page_source
    assert '.cell.geocoding-warning input { color: var(--geocoding-warning); }' in component_source
    assert '.cell.geocoding-error input { color: var(--geocoding-error); }' in component_source
    assert 'column === "Straße"' in component_source
    assert '["PLZ", "Ort", "Straße"].includes(column)' in component_source


def test_order_dates_are_normalized_to_german_format() -> None:
    orders = pd.DataFrame({"Termin bis": ["23.09.2026", "2026-09-24", None]})

    assert normalize_order_dates(orders)
    assert orders["Termin bis"].tolist() == ["23.09.2026", "24.09.2026", ""]


def test_missing_settings_use_defaults(tmp_path: Path) -> None:
    assert load_settings(tmp_path / "settings.json") == DEFAULT_SETTINGS
    assert DEFAULT_SETTINGS["komplettourgrenze"] == 20000


def test_default_quantity_exclusions_respect_threshold_and_existing_overrides() -> None:
    orders = pd.DataFrame(
        {
            "Anzahl": [19999, 20000, 25000, 30000],
            "Filterübersteuerung": ["", "", "Immer anzeigen", "Immer ausschließen"],
        }
    )

    changed = apply_default_quantity_exclusions(orders, 20000)

    assert changed
    assert orders["Filterübersteuerung"].tolist() == [
        "",
        "Immer ausschließen",
        "Immer anzeigen",
        "Immer ausschließen",
    ]
    assert orders[QUANTITY_THRESHOLD_OVERRIDE_COLUMN].tolist() == [False, True, False, False]


def test_quantity_edits_update_only_automatic_threshold_exclusions() -> None:
    orders = pd.DataFrame(
        {
            "Anzahl": [20000, 20000, 19999],
            "Filterübersteuerung": ["Immer ausschließen", "Immer ausschließen", ""],
            QUANTITY_THRESHOLD_OVERRIDE_COLUMN: [True, False, False],
        }
    )

    orders.loc[0, "Anzahl"] = 19999
    update_quantity_threshold_exclusion(orders, 0, 20000)
    orders.loc[1, "Anzahl"] = 19999
    update_quantity_threshold_exclusion(orders, 1, 20000)
    orders.loc[2, "Anzahl"] = 20000
    update_quantity_threshold_exclusion(orders, 2, 20000)

    assert orders["Filterübersteuerung"].tolist() == ["", "Immer ausschließen", "Immer ausschließen"]
    assert orders[QUANTITY_THRESHOLD_OVERRIDE_COLUMN].tolist() == [False, False, True]


def test_quantity_exclusions_are_applied_during_import_not_filtering() -> None:
    import_page_source = (PAGES_DIR / "02_Aufträge.py").read_text(encoding="utf-8")
    filter_page_source = (PAGES_DIR / "03_Aufträge_filtern.py").read_text(encoding="utf-8")

    assert "apply_default_quantity_exclusions(" in import_page_source
    assert "apply_default_quantity_exclusions(" not in filter_page_source


def test_selected_vehicle_requires_a_natural_capacity() -> None:
    settings = {"vehicles": {"Sattelzug": {"enabled": True, "capacity": 40}}}
    assert has_valid_selected_vehicle(settings)

    settings["vehicles"]["Sattelzug"]["capacity"] = 0
    assert not has_valid_selected_vehicle(settings)

    settings["vehicles"]["Sattelzug"]["capacity"] = 40.5
    assert not has_valid_selected_vehicle(settings)


def test_settings_can_be_saved_and_loaded(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    save_settings(settings_path, {"language": "German", "view": "Kompakt"})

    assert load_settings(settings_path)["view"] == "Kompakt"


def test_quantity_scaling_uses_configured_radius_bounds() -> None:
    assert scale_quantity_to_radius(500, 500, 10000, 5, 18) == 5
    assert scale_quantity_to_radius(10000, 500, 10000, 5, 18) == 18
    assert scale_quantity_to_radius(5250, 500, 10000, 5, 18) == sqrt(5 * 18)
    assert scale_quantity_to_radius(0, 500, 10000, 5, 18) == 5
    assert scale_quantity_to_radius(12000, 500, 10000, 5, 18) == 18


def test_quantity_scaling_handles_equal_quantities() -> None:
    assert scale_quantity_to_radius(500, 500, 500, 5, 18) == 5


def test_order_filters_combine_and_match_multiple_postal_prefixes() -> None:
    orders = pd.DataFrame(
        {
            "Fahrzeugart": ["Sattelzug", "Sattelzug", "Dreiachser", "Sattelzug"],
            "Termin bis": ["10.09.2026", "20.09.2026", "15.09.2026", "20.09.2026"],
            "PLZ": ["01234", "23456", "04567", "99999"],
        }
    )

    mask = filter_orders(
        orders,
        vehicle_types=["Sattelzug"],
        date_range=(date(2026, 9, 1), date(2026, 9, 20)),
        postal_prefixes=["2", "04"],
    )

    assert mask.tolist() == [False, True, False, False]


def test_order_filters_include_orders_on_a_single_selected_date() -> None:
    orders = pd.DataFrame(
        {
            "Fahrzeugart": ["Sattelzug", "Sattelzug"],
            "Termin bis": ["10.09.2026", "11.09.2026"],
            "PLZ": ["01234", "23456"],
        }
    )

    mask = filter_orders(
        orders,
        date_range=(date(2026, 9, 10), date(2026, 9, 10)),
    )

    assert mask.tolist() == [True, False]


def test_order_filters_allow_empty_criteria() -> None:
    orders = pd.DataFrame(
        {
            "Fahrzeugart": ["Sattelzug", "Dreiachser"],
            "Termin bis": ["10.09.2026", "15.09.2026"],
            "PLZ": ["01234", "23456"],
        }
    )

    assert filter_orders(orders).tolist() == [True, True]


def test_pasted_orders_are_mapped_and_hints_are_combined() -> None:
    text = (
        "Termin bis\tEmpf-Plz\tEmpf-Ort\tEmpf-Straße\tAnzahl\tDispo - Hinweis\tDFÜ-Hinweise\n"
        "23.09.2026 23:59:00\t44581\tCastrop-Rauxel\tHebewerkstr. 25-27\t1500\tSattelzug/\tRef.-Nr.: INFO"
    )

    orders = parse_pasted_orders(text)

    assert orders.loc[0, "Termin bis"] == "23.09.2026"
    assert orders.loc[0, "Empf-LKZ"] == "D"
    assert orders.loc[0, "Ort"] == "Castrop-Rauxel"
    assert orders.loc[0, "Hinweise"] == "Sattelzug Ref.-Nr.: INFO"


def test_achse_hint_overrides_vehicle_assignment(monkeypatch) -> None:
    monkeypatch.setattr(
        "order_import.load_vehicle_assignments",
        lambda: pd.DataFrame(
            {
                "Empfänger-LKZ": ["D"],
                "Empfänger-PLZ": ["12345"],
                "Empfänger-Ort": ["Berlin"],
                "Straße / Hausnummer": ["Alpha 1"],
                "Aufträge Dreiachser": [0],
                "Aufträge Sattelzug": [3],
            }
        ),
    )

    orders = parse_pasted_orders(
        "Termin bis\tEmpf-LKZ\tEmpf-Plz\tEmpf-Ort\tEmpf-Straße\tAnzahl\tDispo - Hinweis\tDFÜ-Hinweise\n"
        "23.09.2026\tD\t12345\tBerlin\tAlpha 1\t1\tSattelzug/\tFahrzeugAcHsEtyp"
    )

    assert orders.loc[0, "Fahrzeugart"] == "Dreiachser"
    assert orders.loc[0, "Hinweise"] == "Sattelzug FahrzeugAcHsEtyp"


def test_pasted_orders_assign_vehicle_type_from_recipient_table(monkeypatch, tmp_path: Path) -> None:
    assignment_path = tmp_path / "Auftragfahrzeugart.xlsx"
    pd.DataFrame(
        {
            "Empfänger-LKZ": ["D", "D", "D", "D", "D"],
            "Empfänger-PLZ": ["12345", "23456", "34567", "45678", "45678"],
            "Empfänger-Ort": ["Berlin", "Leipzig", "Köln", "Bonn", "Bonn"],
            "Straße / Hausnummer": ["Alpha 1", "Beta 2", "Gamma 3", "Delta 4", "Delta 4"],
            "Aufträge Dreiachser": [0, 4, 0, 0, 0],
            "Aufträge Sattelzug": [3, 0, 0, 0, 1],
        }
    ).to_excel(assignment_path, index=False)
    monkeypatch.setattr("order_import.DEFAULT_VEHICLE_ASSIGNMENT_PATH", assignment_path)

    orders = parse_pasted_orders(
        "Termin bis\tEmpf-LKZ\tEmpf-Plz\tEmpf-Ort\tEmpf-Straße\tAnzahl\n"
        "23.09.2026\tD\t12345\tBerlin\tAlpha 1\t1\n"
        "23.09.2026\tD\t23456\tLeipzig\tBeta 2\t1\n"
        "23.09.2026\tD\t34567\tKöln\tGamma 3\t1\n"
        "23.09.2026\tD\t45678\tBonn\tDelta 4\t1\n"
        "23.09.2026\tD\t99999\tBonn\tUnknown 5\t1"
    )

    assert orders["Fahrzeugart"].tolist() == ["Sattelzug", "Dreiachser", "", "Sattelzug", ""]


def test_pasted_orders_match_assignment_postal_codes_with_dropped_leading_zero(monkeypatch, tmp_path: Path) -> None:
    assignment_path = tmp_path / "Auftragfahrzeugart.xlsx"
    pd.DataFrame(
        {
            "Empfänger-LKZ": ["D"],
            "Empfänger-PLZ": [9599],
            "Empfänger-Ort": ["Freiberg"],
            "Straße / Hausnummer": ["Frauensteiner Str. 105"],
            "Aufträge Dreiachser": [0],
            "Aufträge Sattelzug": [3],
        }
    ).to_excel(assignment_path, index=False)
    monkeypatch.setattr("order_import.DEFAULT_VEHICLE_ASSIGNMENT_PATH", assignment_path)

    orders = parse_pasted_orders(
        "Termin bis\tEmpf-LKZ\tEmpf-Plz\tEmpf-Ort\tEmpf-Straße\tAnzahl\n"
        "23.09.2026\tD\t09599\tFreiberg\tFrauensteiner Str. 105\t1"
    )

    assert orders.loc[0, "Fahrzeugart"] == "Sattelzug"


def test_postal_codes_keep_leading_zero_through_excel_round_trip(tmp_path: Path) -> None:
    text = "Termin bis\tEmpf-Plz\tEmpf-Ort\tEmpf-Straße\tAnzahl\n23.09.2026\t01234\tLeipzig\tMusterstraße 1\t1500"
    parsed = parse_pasted_orders(text)
    workbook = tmp_path / "orders.xlsx"
    parsed.to_excel(workbook, index=False)

    loaded = pd.read_excel(workbook, dtype={"PLZ": "string"})

    assert normalize_order_postal_codes(loaded).loc[0, "PLZ"] == "01234"


def test_legacy_orders_default_to_germany_and_country_codes_are_normalized() -> None:
    legacy_orders = pd.DataFrame({"Termin bis": ["23.09.2026"], "PLZ": ["01234"]})

    assert normalize_order_countries(legacy_orders)
    assert legacy_orders.loc[0, "Empf-LKZ"] == "D"

    imported_orders = parse_pasted_orders(
        "Termin bis\tEmpf-LKZ\tEmpf-Plz\tEmpf-Ort\tEmpf-Straße\tAnzahl\n"
        "23.09.2026\tnl\t1234\tAmsterdam\tCanal 1\t1"
    )
    assert imported_orders.loc[0, "Empf-LKZ"] == "NL"


def test_order_quantity_edit_is_normalized_to_integer() -> None:
    assert normalize_order_quantity("5000") == 5000


def test_corrupt_orders_workbook_can_be_replaced(tmp_path: Path) -> None:
    workbook = tmp_path / "orders.xlsx"
    workbook.write_bytes(b"incomplete workbook")

    assert load_orders(workbook).columns.tolist() == ORDER_COLUMNS

    orders = pd.DataFrame({column: [] for column in ORDER_COLUMNS})
    save_orders(orders, workbook)
    assert load_orders(workbook).empty


def test_geocoding_uses_cache_for_duplicate_addresses() -> None:
    calls = []

    def opener(request, timeout):
        calls.append(request.full_url)

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'[{"lat": "51.5", "lon": "7.2"}]'

        return Response()

    orders = parse_pasted_orders(
        "Termin bis\tEmpf-Plz\tEmpf-Ort\tEmpf-Straße\tAnzahl\n"
        "23.09.2026\t44581\tCastrop-Rauxel\tHebewerkstr. 25-27\t1500\n"
        "24.09.2026\t44581\tCastrop-Rauxel\tHebewerkstr. 25-27\t1500"
    )

    results = list(geocode_orders(orders, sleep=lambda _: None, opener=opener))

    assert len(calls) == 1
    assert results == [(0, (51.5, 7.2)), (1, (51.5, 7.2))]


def test_geocoding_retries_without_street_and_marks_warning() -> None:
    calls = []

    def opener(request, timeout):
        calls.append(request.full_url)

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                if "Hebewerkstr" in request.full_url:
                    return b'[]'
                return b'[{"lat": "51.5", "lon": "7.2"}]'

        return Response()

    orders = parse_pasted_orders(
        "Termin bis\tEmpf-Plz\tEmpf-Ort\tEmpf-Straße\tAnzahl\n"
        "23.09.2026\t44581\tCastrop-Rauxel\tHebewerkstr. 25-27\t1500"
    )

    results = list(geocode_orders(orders, sleep=lambda _: None, opener=opener))

    assert len(calls) == 2
    assert results == [(0, (51.5, 7.2))]
    assert orders.loc[0, "Straße"] == "Hebewerkstr. 25-27"
    assert orders.loc[0, GEOCODING_STATUS_COLUMN] == GEOCODING_STATUS_STREET_FALLBACK


def test_geocoding_retries_with_country_and_postal_code_and_marks_warning() -> None:
    calls = []

    def opener(request, timeout):
        calls.append(request.full_url)

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                if len(calls) == 3:
                    return b'[{"lat": "51.5", "lon": "7.2"}]'
                return b'[]'

        return Response()

    orders = parse_pasted_orders(
        "Termin bis\tEmpf-Plz\tEmpf-Ort\tEmpf-Straße\tAnzahl\n"
        "23.09.2026\t44581\tCastrop-Rauxel\tHebewerkstr. 25-27\t1500"
    )

    results = list(geocode_orders(orders, sleep=lambda _: None, opener=opener))

    assert len(calls) == 3
    query = parse_qs(urlsplit(calls[2]).query)
    assert query["q"] == ["44581"]
    assert query["countrycodes"] == ["de"]
    assert "Deutschland" not in calls[2]
    assert results == [(0, (51.5, 7.2))]
    assert orders.loc[0, GEOCODING_STATUS_COLUMN] == GEOCODING_STATUS_STREET_FALLBACK


def test_geocoding_uses_iso_country_code_for_each_imported_country() -> None:
    calls = []

    def opener(request, timeout):
        calls.append(request.full_url)

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'[{"lat": "51.5", "lon": "7.2"}]'

        return Response()

    orders = parse_pasted_orders(
        "Termin bis\tEmpf-LKZ\tEmpf-Plz\tEmpf-Ort\tEmpf-Straße\tAnzahl\n"
        "23.09.2026\tD\t10115\tBerlin\tStreet 1\t1\n"
        "23.09.2026\tNL\t10115\tAmsterdam\tStreet 1\t1\n"
        "23.09.2026\tCH\t10115\tZürich\tStreet 1\t1"
    )

    results = list(geocode_orders(orders, sleep=lambda _: None, opener=opener))

    assert len(calls) == 3
    assert [
        parse_qs(urlsplit(call).query)["countrycodes"][0]
        for call in calls
    ] == ["de", "nl", "ch"]
    assert all("Deutschland" not in call and "Germany" not in call for call in calls)
    assert results == [(0, (51.5, 7.2)), (1, (51.5, 7.2)), (2, (51.5, 7.2))]


def test_geocoding_marks_address_fields_red_when_every_lookup_fails() -> None:
    def opener(request, timeout):
        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self):
                return b'[]'

        return Response()

    orders = parse_pasted_orders(
        "Termin bis\tEmpf-Plz\tEmpf-Ort\tEmpf-Straße\tAnzahl\n"
        "23.09.2026\t44581\tCastrop-Rauxel\tHebewerkstr. 25-27\t1500"
    )

    results = list(geocode_orders(orders, sleep=lambda _: None, opener=opener))

    assert results == [(0, None)]
    assert orders.loc[0, "PLZ"] == "44581"
    assert orders.loc[0, "Ort"] == "Castrop-Rauxel"
    assert orders.loc[0, "Straße"] == "Hebewerkstr. 25-27"
    assert orders.loc[0, GEOCODING_STATUS_COLUMN] == GEOCODING_STATUS_NOT_FOUND
