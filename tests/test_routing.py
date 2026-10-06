import pytest

import routing


def test_haversine_distance_is_zero_for_same_point() -> None:
	assert routing.haversine_distance_km((51.0, 7.0), (51.0, 7.0)) == 0


def test_exact_route_uses_depot_at_both_ends() -> None:
	durations = [
		[0, 1, 10, 10],
		[1, 0, 1, 10],
		[10, 1, 0, 1],
		[10, 10, 1, 0],
	]

	assert routing.optimize_route(durations) == [0, 1, 2, 3, 0]


def test_exact_route_keeps_pinned_stops_in_their_positions() -> None:
	durations = [
		[0, 1, 9, 9, 9],
		[1, 0, 8, 1, 8],
		[9, 8, 0, 8, 1],
		[9, 1, 8, 0, 8],
		[9, 8, 1, 8, 0],
	]

	route = routing.optimize_route(durations, fixed_positions={2: 2, 4: 4})

	assert route[2] == 2
	assert route[4] == 4
	assert sorted(route[1:-1]) == [1, 2, 3, 4]


def test_exact_route_optimizes_travel_time_not_road_distance() -> None:
	distances = [
		[0, 1, 8, 1],
		[1, 0, 1, 8],
		[8, 1, 0, 1],
		[1, 8, 1, 0],
	]
	durations = [
		[0, 100, 1, 100],
		[100, 0, 100, 1],
		[1, 100, 0, 100],
		[100, 1, 100, 0],
	]

	assert routing.optimize_route(durations) == [0, 1, 3, 2, 0]
	assert routing._route_cost([0, 1, 3, 2, 0], durations) == 202
	assert routing._route_cost([0, 1, 2, 3, 0], distances) == 4


def test_large_constrained_route_tries_alternative_first_stops() -> None:
	durations = [[0 if first == second else 30 for second in range(6)] for first in range(6)]
	durations[0][1] = 0
	durations[1][2] = 1
	durations[1][3] = 2
	durations[2][3] = 1
	durations[3][4] = 1
	durations[4][5] = 1
	durations[5][2] = 1
	durations[2][0] = 1
	straight_line = [[0 if first == second else 1 for second in range(6)] for first in range(6)]

	route = routing.optimize_route(
		durations,
		straight_line,
		fixed_positions={1: 1},
		exact_stop_limit=3,
	)

	assert route == [0, 1, 3, 4, 5, 2, 0]
	assert routing._route_cost(route, durations) == 6


def test_large_route_contains_every_stop_once() -> None:
	count = 12
	durations = [[0 if first == second else abs(first - second) for second in range(count)] for first in range(count)]

	route = routing.optimize_route(durations, time_limit_seconds=0.1)

	assert route[0] == 0
	assert route[-1] == 0
	assert sorted(route[1:-1]) == list(range(1, count))


def test_route_signature_changes_when_stop_changes() -> None:
	first = routing.route_signature([("depot", 51.0, 7.0), (1, 51.1, 7.1)], "https://router.project-osrm.org")
	second = routing.route_signature([("depot", 51.0, 7.0), (1, 51.2, 7.1)], "https://router.project-osrm.org")

	assert first != second


def test_fetch_osrm_table_validates_and_returns_matrices(monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.setattr(
		routing,
		"_request_json",
		lambda url, timeout: {"durations": [[0, 2], [2, 0]], "distances": [[0, 100], [100, 0]]},
	)

	durations, distances = routing.fetch_osrm_table([(51.0, 7.0), (51.1, 7.1)], endpoint="https://example.test")

	assert durations == [[0, 2], [2, 0]]
	assert distances == [[0, 100], [100, 0]]


def test_fetch_osrm_table_rejects_missing_matrix(monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.setattr(routing, "_request_json", lambda url, timeout: {})

	with pytest.raises(routing.RoutingError):
		routing.fetch_osrm_table([(51.0, 7.0)])


def test_fetch_osrm_table_rejects_non_numeric_values(monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.setattr(
		routing,
		"_request_json",
		lambda url, timeout: {"durations": [[0, "slow"], [2, 0]], "distances": [[0, 100], [100, 0]]},
	)

	with pytest.raises(routing.RoutingError):
		routing.fetch_osrm_table([(51.0, 7.0), (51.1, 7.1)])


def test_fetch_osrm_route_converts_geojson_coordinates(monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.setattr(
		routing,
		"_request_json",
		lambda url, timeout: {
			"routes": [
				{
					"distance": 1234,
					"duration": 321,
					"geometry": {"coordinates": [[7.0, 51.0], [7.1, 51.1]]},
					"legs": [
						{"geometry": {"coordinates": [[7.0, 51.0], [7.05, 51.05]]}},
					],
				}
			],
		},
	)

	geometry = routing.fetch_osrm_route([(51.0, 7.0), (51.1, 7.1)], endpoint="https://example.test")

	assert geometry.coordinates == [[51.0, 7.0], [51.1, 7.1]]
	assert geometry.leg_coordinates == [[[51.0, 7.0], [51.05, 7.05]]]
	assert geometry.distance_m == 1234
	assert geometry.duration_s == 321


def test_fetch_osrm_route_rejects_missing_geometry(monkeypatch: pytest.MonkeyPatch) -> None:
	monkeypatch.setattr(routing, "_request_json", lambda url, timeout: {"routes": [{}]})

	with pytest.raises(routing.RoutingError):
		routing.fetch_osrm_route([(51.0, 7.0), (51.1, 7.1)])
