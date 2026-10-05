"""Import and geocode orders pasted from the transport system export."""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
from collections.abc import Callable, Iterator
from io import StringIO
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zipfile import BadZipFile

import pandas as pd


ORDER_COLUMNS = [
	"Termin bis",
	"PLZ",
	"Ort",
	"Straße",
	"Anzahl",
	"Fahrzeugart",
	"Hinweise",
	"Filterübersteuerung",
	"Komplettourgrenze automatisch",
	"Breite",
	"Länge",
	"Geocodierungsstatus",
]
FILTER_OVERRIDE_COLUMN = "Filterübersteuerung"
FILTER_OVERRIDE_VALUES = ("", "Immer anzeigen", "Immer ausschließen")
QUANTITY_THRESHOLD_OVERRIDE_COLUMN = "Komplettourgrenze automatisch"
GEOCODING_STATUS_COLUMN = "Geocodierungsstatus"
GEOCODING_STATUS_STREET_FALLBACK = "street_fallback"
GEOCODING_STATUS_NOT_FOUND = "not_found"
IMPORT_COLUMNS = {
	"Termin bis": "Termin bis",
	"Empf-Plz": "PLZ",
	"Empf-Ort": "Ort",
	"Empf-Straße": "Straße",
	"Anzahl": "Anzahl",
}
VEHICLE_ASSIGNMENT_COLUMNS = {
	"country": "Empfänger-LKZ",
	"postal_code": "Empfänger-PLZ",
	"city": "Empfänger-Ort",
	"street": "Straße / Hausnummer",
	"dreiachser": "Aufträge Dreiachser",
	"sattelzug": "Aufträge Sattelzug",
}
DEFAULT_VEHICLE_ASSIGNMENT_PATH = Path(__file__).resolve().parent / "data" / "Auftragfahrzeugart.xlsx"


def load_orders(path: Path) -> pd.DataFrame:
	"""Load orders and tolerate a workbook interrupted during a previous save."""
	try:
		return pd.read_excel(path, dtype={"PLZ": "string"})
	except (BadZipFile, ValueError):
		return pd.DataFrame(columns=ORDER_COLUMNS)


def normalize_order_dates(orders: pd.DataFrame) -> bool:
	"""Normalize valid order dates to the German date format used in exports."""
	original_dates = orders["Termin bis"]
	parsed_dates = pd.to_datetime(original_dates, format="mixed", dayfirst=True, errors="coerce")
	normalized_dates = parsed_dates.dt.strftime("%d.%m.%Y").where(
		parsed_dates.notna(), original_dates.fillna("").astype(str)
	)
	changed = not original_dates.fillna("").astype(str).equals(normalized_dates)
	if changed:
		orders["Termin bis"] = normalized_dates
	return changed


def save_orders(orders: pd.DataFrame, path: Path) -> None:
	"""Replace the orders workbook atomically so readers never see a partial ZIP."""
	path.parent.mkdir(parents=True, exist_ok=True)
	temporary_path: str | None = None
	try:
		with tempfile.NamedTemporaryFile(
			dir=path.parent,
			prefix=f".{path.stem}-",
			suffix=path.suffix,
			delete=False,
		) as temporary_file:
			temporary_path = temporary_file.name
		orders.to_excel(temporary_path, index=False)
		os.replace(temporary_path, path)
		temporary_path = None
	finally:
		if temporary_path is not None:
			Path(temporary_path).unlink(missing_ok=True)


def _normalize_match_value(value: object) -> str:
	"""Normalize recipient fields for matching Excel and export values."""
	if pd.isna(value):
		return ""
	text = str(value).strip().casefold()
	if text.endswith(".0") and text[:-2].isdigit():
		text = text[:-2]
	return re.sub(r"\s+", " ", text)


def load_vehicle_assignments(path: Path | None = None) -> pd.DataFrame:
	"""Load and aggregate recipient vehicle counts from the assignment workbook."""
	if path is None:
		path = DEFAULT_VEHICLE_ASSIGNMENT_PATH
	assignments = pd.read_excel(path, dtype=object, keep_default_na=False)
	missing = set(VEHICLE_ASSIGNMENT_COLUMNS.values()) - set(assignments.columns)
	if missing:
		raise ValueError(f"Fehlende Spalten in Fahrzeugart-Tabelle: {', '.join(sorted(missing))}")

	key_columns = [VEHICLE_ASSIGNMENT_COLUMNS[name] for name in ("country", "postal_code", "city", "street")]
	for column in key_columns:
		assignments[column] = assignments[column].map(_normalize_match_value)
	postal_code_column = VEHICLE_ASSIGNMENT_COLUMNS["postal_code"]
	assignments[postal_code_column] = assignments[postal_code_column].map(normalize_postal_code)
	for column in (VEHICLE_ASSIGNMENT_COLUMNS["dreiachser"], VEHICLE_ASSIGNMENT_COLUMNS["sattelzug"]):
		assignments[column] = pd.to_numeric(assignments[column], errors="coerce")
	return assignments.groupby(key_columns, as_index=False, dropna=False)[
		[VEHICLE_ASSIGNMENT_COLUMNS["dreiachser"], VEHICLE_ASSIGNMENT_COLUMNS["sattelzug"]]
	].sum(min_count=1)


def vehicle_assignment_counts(order: pd.Series, path: Path | None = None) -> tuple[object, object]:
	"""Return the two vehicle assignment counts matching an order address."""
	assignments = load_vehicle_assignments(path)
	key_columns = [VEHICLE_ASSIGNMENT_COLUMNS[name] for name in ("postal_code", "city", "street")]
	order_key = tuple(_normalize_match_value(order[column]) for column in ("PLZ", "Ort", "Straße"))
	indexed_assignments = assignments.set_index(key_columns)
	if order_key not in indexed_assignments.index:
		return 0, 0
	matching = indexed_assignments.loc[[order_key]]
	return (
		matching[VEHICLE_ASSIGNMENT_COLUMNS["dreiachser"]].sum(),
		matching[VEHICLE_ASSIGNMENT_COLUMNS["sattelzug"]].sum(),
	)


def _vehicle_type_for_order(
	order: pd.Series,
	assignments: pd.DataFrame,
	country: object = "",
) -> str:
	"""Return a vehicle type only when the assignment table gives one clear result."""
	assignment_country = VEHICLE_ASSIGNMENT_COLUMNS["country"]
	assignment_keys = [VEHICLE_ASSIGNMENT_COLUMNS[name] for name in ("postal_code", "city", "street")]
	order_key = tuple(_normalize_match_value(order[column]) for column in ("PLZ", "Ort", "Straße"))
	key_matches = assignments.set_index(assignment_keys).index.isin([order_key])
	if _normalize_match_value(country):
		matches = assignments[key_matches & (assignments[assignment_country] == _normalize_match_value(country))]
	else:
		matches = assignments[key_matches]
		if matches[assignment_country].nunique() > 1:
			return ""

	if len(matches) != 1:
		return ""
	row = matches.iloc[0]
	dreiachser = row[VEHICLE_ASSIGNMENT_COLUMNS["dreiachser"]]
	sattelzug = row[VEHICLE_ASSIGNMENT_COLUMNS["sattelzug"]]
	if pd.isna(dreiachser) or pd.isna(sattelzug):
		return ""
	if dreiachser != 0 and sattelzug == 0:
		return "Dreiachser"
	if dreiachser == 0 and sattelzug != 0:
		return "Sattelzug"
	return ""


def parse_pasted_orders(text: str) -> pd.DataFrame:
	"""Parse the tab-separated export and return rows in the app's schema."""
	rows = pd.read_csv(
		StringIO(text),
		sep="\t",
		dtype=str,
		keep_default_na=False,
	)
	missing = {"Termin bis", "Empf-Plz", "Empf-Ort", "Empf-Straße", "Anzahl"} - set(rows)
	if missing:
		raise ValueError(f"Fehlende Spalten: {', '.join(sorted(missing))}")

	imported = pd.DataFrame(index=rows.index)
	for source, target in IMPORT_COLUMNS.items():
		imported[target] = rows[source].str.strip()
	imported["PLZ"] = imported["PLZ"].map(normalize_postal_code)
	imported["Termin bis"] = imported["Termin bis"].str.split().str[0]
	dispo_hints = rows["Dispo - Hinweis"] if "Dispo - Hinweis" in rows else pd.Series("", index=rows.index)
	dfue_hints = rows["DFÜ-Hinweise"] if "DFÜ-Hinweise" in rows else pd.Series("", index=rows.index)
	imported["Hinweise"] = (
		dispo_hints.str.strip().str.replace("/", "", regex=False)
		+ dfue_hints.str.strip().str.replace("/", "", regex=False).map(lambda value: f" {value}" if value else "")
	).str.strip()
	assignments = load_vehicle_assignments()
	country_values = rows.get(
		"Empf-LKZ",
		rows.get("Empfänger-LKZ", pd.Series("", index=rows.index)),
	)
	imported["Fahrzeugart"] = [
		(
			"Dreiachser"
			if "achse" in imported.loc[index, "Hinweise"].casefold()
			else _vehicle_type_for_order(imported.loc[index], assignments, country_values.loc[index])
		)
		for index in imported.index
	]
	imported[FILTER_OVERRIDE_COLUMN] = ""
	imported[QUANTITY_THRESHOLD_OVERRIDE_COLUMN] = False
	imported["Breite"] = pd.NA
	imported["Länge"] = pd.NA
	imported[GEOCODING_STATUS_COLUMN] = ""
	return imported.loc[:, ORDER_COLUMNS]


def normalize_postal_code(value: object) -> str:
	"""Keep German postal codes as five-character strings."""
	text = str(value).strip()
	if text in {"", "<NA>", "nan", "NaN"}:
		return ""
	if text.isdigit() and len(text) <= 5:
		return text.zfill(5)
	return text


def normalize_order_postal_codes(orders: pd.DataFrame) -> pd.DataFrame:
	"""Normalize postal codes after loading orders from Excel."""
	if "PLZ" in orders:
		orders["PLZ"] = orders["PLZ"].map(normalize_postal_code)
	return orders


def normalize_order_quantity(value: str) -> int:
	"""Convert an edited order quantity to an integer."""
	return int(value)


def apply_default_quantity_exclusions(orders: pd.DataFrame, threshold: int) -> bool:
	"""Exclude orders at the threshold unless they already have an override."""
	if QUANTITY_THRESHOLD_OVERRIDE_COLUMN not in orders:
		orders[QUANTITY_THRESHOLD_OVERRIDE_COLUMN] = False
	orders[QUANTITY_THRESHOLD_OVERRIDE_COLUMN] = (
		orders[QUANTITY_THRESHOLD_OVERRIDE_COLUMN].fillna(False).astype(bool)
	)
	quantities = pd.to_numeric(orders["Anzahl"], errors="coerce")
	should_exclude = quantities.ge(threshold) & orders[FILTER_OVERRIDE_COLUMN].eq("")
	orders.loc[should_exclude, FILTER_OVERRIDE_COLUMN] = "Immer ausschließen"
	orders.loc[should_exclude, QUANTITY_THRESHOLD_OVERRIDE_COLUMN] = True
	return bool(should_exclude.any())


def update_quantity_threshold_exclusion(
	orders: pd.DataFrame,
	order_index: int,
	threshold: int,
) -> None:
	"""Update a threshold-generated exclusion after an order quantity edit."""
	if QUANTITY_THRESHOLD_OVERRIDE_COLUMN not in orders:
		orders[QUANTITY_THRESHOLD_OVERRIDE_COLUMN] = False
	orders[QUANTITY_THRESHOLD_OVERRIDE_COLUMN] = (
		orders[QUANTITY_THRESHOLD_OVERRIDE_COLUMN].fillna(False).astype(bool)
	)
	quantity = pd.to_numeric(orders.at[order_index, "Anzahl"], errors="coerce")
	is_above_threshold = pd.notna(quantity) and quantity >= threshold
	is_automatic = orders.at[order_index, QUANTITY_THRESHOLD_OVERRIDE_COLUMN]
	override = orders.at[order_index, FILTER_OVERRIDE_COLUMN]

	if is_automatic:
		if override != "Immer ausschließen":
			orders.at[order_index, QUANTITY_THRESHOLD_OVERRIDE_COLUMN] = False
		elif not is_above_threshold:
			orders.at[order_index, FILTER_OVERRIDE_COLUMN] = ""
			orders.at[order_index, QUANTITY_THRESHOLD_OVERRIDE_COLUMN] = False
	elif is_above_threshold and override == "":
		orders.at[order_index, FILTER_OVERRIDE_COLUMN] = "Immer ausschließen"
		orders.at[order_index, QUANTITY_THRESHOLD_OVERRIDE_COLUMN] = True


def geocode_address(address: str, opener: Callable = urlopen) -> tuple[float, float] | None:
	"""Look up an address with the public Nominatim endpoint."""
	query = urlencode({"q": address, "format": "jsonv2", "limit": 1, "countrycodes": "de"})
	request = Request(
		f"https://nominatim.openstreetmap.org/search?{query}",
		headers={"User-Agent": "Autotourenplaner/0.1 (local planning tool)"},
	)
	with opener(request, timeout=15) as response:
		results = json.load(response)
	if not results:
		return None
	return float(results[0]["lat"]), float(results[0]["lon"])


def _clean_address_part(value: object) -> str:
	"""Normalize a field value for the geocoding string."""
	text = str(value)
	if text in {"", "<NA>", "nan", "NaN"}:
		return ""
	return text.strip()


def _mark_warning(orders: pd.DataFrame, row_index: int, level: str) -> None:
	"""Store the geocoding warning without changing the address values."""
	status = GEOCODING_STATUS_STREET_FALLBACK if level == "street" else GEOCODING_STATUS_NOT_FOUND
	orders.at[row_index, GEOCODING_STATUS_COLUMN] = status


def geocode_orders(
	orders: pd.DataFrame,
	progress: Callable[[int], None] | None = None,
	sleep: Callable[[float], None] = time.sleep,
	opener: Callable = urlopen,
) -> Iterator[tuple[int, tuple[float, float] | None]]:
	"""Yield coordinates for each order, respecting Nominatim's one-second limit."""
	cache: dict[str, tuple[float, float] | None] = {}
	last_request = 0.0
	if GEOCODING_STATUS_COLUMN not in orders:
		orders[GEOCODING_STATUS_COLUMN] = ""
	for position, row in enumerate(orders.itertuples(index=False), start=1):
		row_index = position - 1
		street = _clean_address_part(row.Straße)
		plz = normalize_postal_code(row.PLZ)
		ort = _clean_address_part(row.Ort)
		full_address = ", ".join(part for part in (street, plz, ort, "Deutschland") if part)
		fallback_address = ", ".join(part for part in (plz, ort, "Deutschland") if part)
		coordinates: tuple[float, float] | None = None
		candidates = [full_address]
		if street:
			candidates.append(fallback_address)
		if plz:
			candidates.append(f"Deutschland, {plz}")

		for candidate in candidates:
			if not candidate:
				continue
			if candidate not in cache:
				wait = 1.0 - (time.monotonic() - last_request)
				if wait > 0:
					sleep(wait)
				cache[candidate] = geocode_address(candidate, opener=opener)
				last_request = time.monotonic()
			coordinates = cache[candidate]
			if coordinates is not None:
				if candidate != full_address:
					_mark_warning(orders, row_index, "street")
				break

		if coordinates is None:
			_mark_warning(orders, row_index, "all")
		if progress:
			progress(position)
		yield row_index, coordinates