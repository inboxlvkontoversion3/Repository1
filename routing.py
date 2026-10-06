"""Road-route optimization helpers for the order-planning page."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from itertools import combinations, permutations
from json import dumps, loads
from math import asin, cos, isfinite, radians, sin, sqrt
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


DEFAULT_OSRM_ENDPOINT = "https://router.project-osrm.org"
OSRM_TIMEOUT_SECONDS = 6
EXACT_STOP_LIMIT = 10


class RoutingError(RuntimeError):
	"""Raised when the routing provider cannot return a usable result."""


@dataclass(frozen=True)
class RouteGeometry:
	"""Final road geometry and provider totals for an ordered route."""

	coordinates: list[list[float]]
	distance_m: float
	duration_s: float
	leg_coordinates: list[list[list[float]]] = field(default_factory=list)


def haversine_distance_km(first: tuple[float, float], second: tuple[float, float]) -> float:
	"""Return the great-circle distance between latitude/longitude pairs."""
	latitude_one, longitude_one = map(radians, first)
	latitude_two, longitude_two = map(radians, second)
	delta_latitude = latitude_two - latitude_one
	delta_longitude = longitude_two - longitude_one
	a = sin(delta_latitude / 2) ** 2 + cos(latitude_one) * cos(latitude_two) * sin(delta_longitude / 2) ** 2
	return 6371.0088 * 2 * asin(sqrt(a))


def haversine_matrix(points: list[tuple[float, float]]) -> list[list[float]]:
	"""Build a symmetric straight-line distance matrix in kilometres."""
	matrix = [[0.0 for _ in points] for _ in points]
	for first, second in combinations(range(len(points)), 2):
		distance = haversine_distance_km(points[first], points[second])
		matrix[first][second] = distance
		matrix[second][first] = distance
	return matrix


def _validate_matrix(matrix: list[list[float]]) -> None:
	if not matrix or any(len(row) != len(matrix) for row in matrix):
		raise RoutingError("OSRM hat keine vollständige Kostenmatrix geliefert.")
	if any(
		not isinstance(value, (int, float)) or not isfinite(value) or value < 0
		for row in matrix
		for value in row
	):
		raise RoutingError("OSRM hat ungültige Kostenwerte geliefert.")


def _route_cost(route: list[int], matrix: list[list[float]]) -> float:
	return sum(matrix[first][second] for first, second in zip(route, route[1:]))


def _two_opt(route: list[int], matrix: list[list[float]], deadline: float) -> list[int]:
	best_route = route
	best_cost = _route_cost(best_route, matrix)
	improved = True
	while improved and monotonic() < deadline:
		improved = False
		for first in range(1, len(best_route) - 2):
			for second in range(first + 1, len(best_route) - 1):
				candidate = best_route[:first] + best_route[first:second + 1][::-1] + best_route[second + 1:]
				candidate_cost = _route_cost(candidate, matrix)
				if candidate_cost + 1e-9 < best_cost:
					best_route = candidate
					best_cost = candidate_cost
					improved = True
					break
			if improved or monotonic() >= deadline:
				break
	return best_route


def _nearest_neighbor(start: int, matrix: list[list[float]], straight_line: list[list[float]]) -> list[int]:
	remaining = set(range(1, len(matrix)))
	route = [0]
	current = 0
	while remaining:
		next_stop = min(remaining, key=lambda stop: (matrix[current][stop], straight_line[current][stop], stop))
		route.append(next_stop)
		remaining.remove(next_stop)
		current = next_stop
	return route + [0]


def _exact_route(matrix: list[list[float]], fixed_positions: dict[int, int] | None = None) -> list[int]:
	stop_count = len(matrix) - 1
	if fixed_positions:
		fixed_by_position = {position: stop for stop, position in fixed_positions.items()}
		free_stops = [stop for stop in range(1, len(matrix)) if stop not in fixed_positions]
		free_positions = [position for position in range(1, stop_count + 1) if position not in fixed_by_position]
		best_route: tuple[float, tuple[int, ...]] | None = None
		for permutation in permutations(free_stops):
			ordered_stops = dict(fixed_by_position)
			ordered_stops.update(zip(free_positions, permutation))
			candidate = (0, *(ordered_stops[position] for position in range(1, stop_count + 1)), 0)
			candidate_result = (_route_cost(list(candidate), matrix), candidate)
			if best_route is None or candidate_result < best_route:
				best_route = candidate_result
		return list(best_route[1]) if best_route else [0, 0]
	paths: dict[tuple[int, int], tuple[float, tuple[int, ...]]] = {
		(1 << (stop - 1), stop): (matrix[0][stop], (0, stop))
		for stop in range(1, len(matrix))
	}
	for subset_size in range(2, len(matrix)):
		for subset in range(1, 1 << (len(matrix) - 1)):
			if subset.bit_count() != subset_size:
				continue
			for last in range(1, len(matrix)):
				last_bit = 1 << (last - 1)
				if not subset & last_bit:
					continue
				previous_subset = subset ^ last_bit
				candidates = [
					(paths[(previous_subset, previous_last)][0] + matrix[previous_last][last], paths[(previous_subset, previous_last)][1] + (last,))
					for previous_last in range(1, len(matrix))
					if previous_subset & (1 << (previous_last - 1))
				]
				paths[(subset, last)] = min(candidates, key=lambda item: (item[0], item[1]))
	full_subset = (1 << stop_count) - 1
	best = min(
		[
			(
			paths[(full_subset, last)][0] + matrix[last][0],
			paths[(full_subset, last)][1] + (0,),
			)
			for last in range(1, len(matrix))
		],
		key=lambda item: (item[0], item[1]),
	)
	return list(best[1])


def _constrained_nearest_neighbor(
	matrix: list[list[float]],
	straight_line: list[list[float]],
	fixed_positions: dict[int, int],
	first_stop: int | None = None,
) -> list[int]:
	stop_count = len(matrix) - 1
	ordered_stops: dict[int, int] = {position: stop for stop, position in fixed_positions.items()}
	remaining = set(range(1, len(matrix))) - set(fixed_positions)
	current = 0
	first_free_position = min(
		(position for position in range(1, stop_count + 1) if position not in ordered_stops),
		default=None,
	)
	for position in range(1, stop_count + 1):
		if position not in ordered_stops:
			if position == first_free_position and first_stop is not None:
				next_stop = first_stop
			else:
				next_stop = min(remaining, key=lambda stop: (matrix[current][stop], straight_line[current][stop], stop))
			ordered_stops[position] = next_stop
			remaining.remove(next_stop)
		current = ordered_stops[position]
	return [0, *(ordered_stops[position] for position in range(1, stop_count + 1)), 0]


def _constrained_two_opt(route: list[int], matrix: list[list[float]], fixed_positions: dict[int, int], deadline: float) -> list[int]:
	best_route = route
	best_cost = _route_cost(best_route, matrix)
	free_positions = [position for position in range(1, len(route) - 1) if position not in fixed_positions.values()]
	while monotonic() < deadline:
		best_neighbor = best_route
		best_neighbor_cost = best_cost
		free_stops = [best_route[position] for position in free_positions]
		for first_index in range(len(free_positions) - 1):
			for last_index in range(first_index + 1, len(free_positions)):
				candidate = best_route.copy()
				reversed_stops = reversed(free_stops[first_index:last_index + 1])
				for position, stop in zip(free_positions[first_index:last_index + 1], reversed_stops):
					candidate[position] = stop
				candidate_cost = _route_cost(candidate, matrix)
				if candidate_cost + 1e-9 < best_neighbor_cost:
					best_neighbor, best_neighbor_cost = candidate, candidate_cost
				if monotonic() >= deadline:
					break
			if monotonic() >= deadline:
				break
		if monotonic() < deadline:
			for source_index in range(len(free_positions)):
				for target_index in range(len(free_positions)):
					if source_index == target_index:
						continue
					reordered_stops = free_stops.copy()
					moved_stop = reordered_stops.pop(source_index)
					reordered_stops.insert(target_index, moved_stop)
					candidate = best_route.copy()
					for position, stop in zip(free_positions, reordered_stops):
						candidate[position] = stop
					candidate_cost = _route_cost(candidate, matrix)
					if candidate_cost + 1e-9 < best_neighbor_cost:
						best_neighbor, best_neighbor_cost = candidate, candidate_cost
					if monotonic() >= deadline:
						break
				if monotonic() >= deadline:
					break
		if best_neighbor_cost + 1e-9 >= best_cost:
			break
		best_route, best_cost = best_neighbor, best_neighbor_cost
	return best_route


def _validate_fixed_positions(fixed_positions: dict[int, int] | None, stop_count: int) -> dict[int, int]:
	if not fixed_positions:
		return {}
	if (
		any(stop < 1 or stop > stop_count or position < 1 or position > stop_count for stop, position in fixed_positions.items())
		or len(set(fixed_positions.values())) != len(fixed_positions)
	):
		raise RoutingError("Die fixierten Stopppositionen sind ungültig.")
	return dict(fixed_positions)


def optimize_route(
	duration_matrix: list[list[float]],
	straight_line_matrix: list[list[float]] | None = None,
	fixed_positions: dict[int, int] | None = None,
	exact_stop_limit: int = EXACT_STOP_LIMIT,
	time_limit_seconds: float = 2.0,
) -> list[int]:
	"""Return a depot-first route minimizing travel time with exact or bounded heuristics."""
	_validate_matrix(duration_matrix)
	if len(duration_matrix) == 1:
		return [0, 0]
	if straight_line_matrix is None:
		straight_line_matrix = duration_matrix
	_validate_matrix(straight_line_matrix)
	if len(straight_line_matrix) != len(duration_matrix):
		raise RoutingError("OSRM hat keine übereinstimmenden Kostenmatrizen geliefert.")
	fixed_positions = _validate_fixed_positions(fixed_positions, len(duration_matrix) - 1)
	if len(duration_matrix) - 1 <= exact_stop_limit:
		return _exact_route(duration_matrix, fixed_positions)
	deadline = monotonic() + max(0.01, time_limit_seconds)
	if fixed_positions:
		free_stops = set(range(1, len(duration_matrix))) - set(fixed_positions)
		if not free_stops:
			return _constrained_nearest_neighbor(duration_matrix, straight_line_matrix, fixed_positions)
		first_free_position = min(
			position
			for position in range(1, len(duration_matrix))
			if position not in fixed_positions.values()
		)
		previous_stop = 0 if first_free_position == 1 else next(
			stop for stop, position in fixed_positions.items() if position == first_free_position - 1
		)
		starts = sorted(
			free_stops,
			key=lambda stop: (duration_matrix[previous_stop][stop], straight_line_matrix[previous_stop][stop], stop),
		)
		best_route: list[int] | None = None
		best_cost = float("inf")
		for start_index, start in enumerate(starts):
			if monotonic() >= deadline:
				break
			remaining_time = deadline - monotonic()
			starts_left = len(starts) - start_index
			start_deadline = monotonic() + remaining_time / starts_left
			candidate = _constrained_nearest_neighbor(
				duration_matrix,
				straight_line_matrix,
				fixed_positions,
				first_stop=start,
			)
			candidate = _constrained_two_opt(candidate, duration_matrix, fixed_positions, start_deadline)
			candidate_cost = _route_cost(candidate, duration_matrix)
			if candidate_cost < best_cost:
				best_route, best_cost = candidate, candidate_cost
		return best_route or _constrained_nearest_neighbor(
			duration_matrix,
			straight_line_matrix,
			fixed_positions,
			first_stop=starts[0],
		)
	best_route = _nearest_neighbor(0, duration_matrix, straight_line_matrix)
	best_cost = _route_cost(best_route, duration_matrix)
	for start in sorted(range(1, len(duration_matrix)), key=lambda stop: (duration_matrix[0][stop], stop)):
		if monotonic() >= deadline:
			break
		candidate = [0]
		remaining = set(range(1, len(duration_matrix)))
		remaining.remove(start)
		candidate.append(start)
		while remaining:
			current = candidate[-1]
			next_stop = min(remaining, key=lambda stop: (duration_matrix[current][stop], straight_line_matrix[current][stop], stop))
			candidate.append(next_stop)
			remaining.remove(next_stop)
		candidate.append(0)
		candidate = _two_opt(candidate, duration_matrix, deadline)
		candidate_cost = _route_cost(candidate, duration_matrix)
		if candidate_cost < best_cost:
			best_route, best_cost = candidate, candidate_cost
	return best_route


def route_signature(stops: list[tuple[object, float, float]], endpoint: str) -> str:
	"""Return a stable cache key for a depot and ordered active-stop snapshot."""
	payload = dumps({"endpoint": endpoint.rstrip("/"), "stops": stops}, sort_keys=True, default=str)
	return sha256(payload.encode("utf-8")).hexdigest()


def _request_json(url: str, timeout: float) -> dict:
	request = Request(url, headers={"User-Agent": "Autotourenplaner/0.1"})
	try:
		with urlopen(request, timeout=timeout) as response:
			return loads(response.read().decode("utf-8"))
	except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
		raise RoutingError(f"Der Routingdienst ist nicht erreichbar: {error}") from error


def _coordinates_url(points: list[tuple[float, float]]) -> str:
	return ";".join(f"{longitude:.6f},{latitude:.6f}" for latitude, longitude in points)


def fetch_osrm_table(
	points: list[tuple[float, float]],
	endpoint: str = DEFAULT_OSRM_ENDPOINT,
	timeout: float = OSRM_TIMEOUT_SECONDS,
) -> tuple[list[list[float]], list[list[float]]]:
	"""Fetch duration and distance matrices for latitude/longitude points."""
	if len(points) < 1:
		raise RoutingError("Mindestens ein Routingpunkt ist erforderlich.")
	query = urlencode({"annotations": "duration,distance"})
	data = _request_json(f"{endpoint.rstrip('/')}/table/v1/driving/{_coordinates_url(points)}?{query}", timeout)
	durations = data.get("durations")
	distances = data.get("distances")
	if not isinstance(durations, list) or not isinstance(distances, list):
		raise RoutingError("OSRM hat keine gültige Entfernungsmatrix geliefert.")
	_validate_matrix(durations)
	_validate_matrix(distances)
	return durations, distances


def fetch_osrm_route(
	points: list[tuple[float, float]],
	endpoint: str = DEFAULT_OSRM_ENDPOINT,
	timeout: float = OSRM_TIMEOUT_SECONDS,
) -> RouteGeometry:
	"""Fetch the road geometry for an already optimized ordered route."""
	query = urlencode({"overview": "full", "geometries": "geojson", "steps": "true"})
	data = _request_json(f"{endpoint.rstrip('/')}/route/v1/driving/{_coordinates_url(points)}?{query}", timeout)
	routes = data.get("routes")
	if not isinstance(routes, list) or not routes or not isinstance(routes[0], dict):
		raise RoutingError("OSRM hat keine gültige Routenlinie geliefert.")
	route = routes[0]
	geometry = route.get("geometry", {})
	coordinates = geometry.get("coordinates") if isinstance(geometry, dict) else None
	if not isinstance(coordinates, list) or len(coordinates) < 2:
		raise RoutingError("OSRM hat keine gültige Routenlinie geliefert.")
	try:
		converted_coordinates = [[float(latitude), float(longitude)] for longitude, latitude in coordinates]
		distance_m = float(route.get("distance", 0))
		duration_s = float(route.get("duration", 0))
	except (TypeError, ValueError) as error:
		raise RoutingError("OSRM hat ungültige Routendaten geliefert.") from error
	if not all(isfinite(value) for point in converted_coordinates for value in point):
		raise RoutingError("OSRM hat ungültige Routendaten geliefert.")
	leg_coordinates = []
	for leg in route.get("legs", []):
		leg_geometry = leg.get("geometry", {}) if isinstance(leg, dict) else {}
		leg_points = leg_geometry.get("coordinates") if isinstance(leg_geometry, dict) else None
		if not isinstance(leg_points, list) or len(leg_points) < 2:
			continue
		try:
			converted_leg = [[float(latitude), float(longitude)] for longitude, latitude in leg_points]
		except (TypeError, ValueError) as error:
			raise RoutingError("OSRM hat ungültige Teilroutendaten geliefert.") from error
		if not all(isfinite(value) for point in converted_leg for value in point):
			raise RoutingError("OSRM hat ungültige Teilroutendaten geliefert.")
		leg_coordinates.append(converted_leg)
	return RouteGeometry(
		coordinates=converted_coordinates,
		distance_m=distance_m,
		duration_s=duration_s,
		leg_coordinates=leg_coordinates,
	)