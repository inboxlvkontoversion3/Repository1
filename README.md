# Autotourenplaner

A Streamlit prototype for planning car tours, with a German user interface and English project internals.

## Requirements

- Python 3.11 or newer
- A virtual environment is recommended

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[test]"
```

## Start the application

```bash
python launcher.py
```

On Linux, the launcher stops any existing Streamlit process running this project's `app.py` before starting a fresh instance.

The application includes these pages:

- Grundparameter
- Aufträge
- Aufträge filtern
- Tourenbildung
- Reihenfolge
- Einstellungen

The app provides six profiles with internal IDs `1` through `6`: Hübinger, Broll, Kolodziej, Grevener, Zehner, and Gast. Select a profile in the sidebar; the browser remembers it in a cookie. This is only a profile selector, not authentication or access control. Each profile has its own orders workbook, planning settings, filters, active-order selection, map view, and pinned/manual route order under `.autotourenplaner/profiles/`. A profile starts with an empty orders workbook the first time it is used; existing profile data is preserved. Legacy shared files are not imported automatically. The loading-point and vehicle-assignment reference workbooks remain shared. Display names can be changed in `PROFILES` in `profiles.py`; retain each numeric profile ID to keep its saved data.

The base-parameter page loads `data/Verladestellen.xlsx` and stores the selected loading point in the current profile's settings. Page 5 uses the public OSRM routing service to calculate one route containing all active orders. The selected loading point is always the first and last stop. Stop order is optimized for travel time, while pinned stops stay in their selected positions. The displayed estimated truck driving time is OSRM's driving-time estimate multiplied by 1.2 to account for slower truck speeds. A single table request supplies travel times and a second request retrieves the final road geometry; the requests have short timeouts and provider failures are shown in the UI.

The `OSRM_ENDPOINT` environment variable can override the default routing endpoint. The application requires network access while calculating a route. Haversine distances are used locally to guide larger-route heuristics, but they are not presented as a fallback route when OSRM is unavailable. Vehicle capacity and splitting one set of active orders into multiple tours are not implemented yet.

Order addresses are geocoded with Nominatim first. After each unsuccessful full-address, postal-code-and-city, or postal-code search, the app tries Photon with that same address and the recipient country code before moving to the next search.

## Tests

```bash
pytest
```
