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

The base-parameter page loads `data/Verladestellen.xlsx` and stores the selected loading point in `.autotourenplaner/settings.json`. Page 5 uses the public OSRM routing service to calculate one route containing all active orders. The selected loading point is always the first and last stop. A single table request is used for optimization and a second request retrieves the final road geometry; the requests have short timeouts and provider failures are shown in the UI.

The `OSRM_ENDPOINT` environment variable can override the default routing endpoint. The application requires network access while calculating a route. Haversine distances are used locally to guide larger-route heuristics, but they are not presented as a fallback route when OSRM is unavailable. Vehicle capacity and splitting one set of active orders into multiple tours are not implemented yet.

## Tests

```bash
pytest
```
