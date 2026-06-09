from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from z3 import And, Bool, If, Implies, Int, Not, Optimize, Sum, is_true, sat


def smt(
    distances: List[List[int]],
    required_orders: Optional[Dict[int, int]] = None,
    timeout_ms: int = 0,
) -> Tuple[int, List[int]]:
    """Search a Boolean adjacency matrix for the cheapest valid TSP tour."""
    num_cities = len(distances)
    if num_cities == 0:
        return -1, []
    if num_cities == 1:
        return 0, [0, 0]

    solver = Optimize()
    if timeout_ms > 0:
        solver.set("timeout", timeout_ms)

    cities = range(num_cities)

    # Same shape as the input adjacency matrix:
    # use_edge[i][j] asks whether the tour travels directly from city i to city j.
    use_edge = [[Bool(f"use_edge_{i}_{j}") for j in cities] for i in cities]
    for city in cities:
        solver.add(Not(use_edge[city][city]))

    # visit_order[i] is the day/position when city i is visited. City 0 is the start.
    visit_order = [Int(f"visit_order_{i}") for i in cities]
    solver.add(visit_order[0] == 0)
    for city in range(1, num_cities):
        solver.add(And(visit_order[city] >= 1, visit_order[city] < num_cities))

    if required_orders:
        for city, day in required_orders.items():
            if not (0 <= city < num_cities and 0 <= day < num_cities):
                raise ValueError("required_orders contains out of range values")
            solver.add(visit_order[city] == day)

    # Each row chooses where that city goes next.
    # Each column chooses where that city is reached from.
    for city in cities:
        solver.add(_exactly_one(use_edge[city]))
        solver.add(_exactly_one([use_edge[source][city] for source in cities]))

    # Chosen edges must connect consecutive visit positions, which prevents subtours.
    for source in cities:
        for destination in cities:
            if source == destination:
                continue
            solver.add(
                Implies(
                    use_edge[source][destination],
                    _is_next_visit(visit_order, source, destination, num_cities),
                )
            )

    objective_distances = _normalize_distances_for_solver(distances)
    solver.minimize(_selected_edge_cost(use_edge, objective_distances))

    if solver.check() != sat:
        return -1, []

    path = _path_from_successors(_successors_from_model(solver.model(), use_edge), 0)
    return _path_cost(distances, path), path


def _exactly_one(choices):
    return Sum([If(choice, 1, 0) for choice in choices]) == 1


def _is_next_visit(visit_order, source: int, destination: int, num_cities: int):
    if destination == 0:
        return visit_order[source] == num_cities - 1
    if source == 0:
        return visit_order[destination] == 1
    return visit_order[destination] == visit_order[source] + 1


def _selected_edge_cost(use_edge, distances: List[List[int]]):
    cities = range(len(distances))
    return Sum(
        [
            If(use_edge[i][j], distances[i][j], 0)
            for i in cities
            for j in cities
            if i != j
        ]
    )


def _normalize_distances_for_solver(distances: List[List[int]]) -> List[List[int]]:
    """Shift edge costs without changing which tour is cheapest."""
    num_cities = len(distances)
    reduced = [[0] * num_cities for _ in range(num_cities)]

    # Every tour uses one outgoing edge from each city, so subtracting a constant
    # from each row changes every tour's cost by the same amount.
    for i in range(num_cities):
        row_min = min(distances[i][j] for j in range(num_cities) if i != j)
        for j in range(num_cities):
            if i != j:
                reduced[i][j] = distances[i][j] - row_min

    # Every tour also uses one incoming edge to each city, so the same idea applies
    # to columns after row reduction.
    for j in range(num_cities):
        column_min = min(reduced[i][j] for i in range(num_cities) if i != j)
        for i in range(num_cities):
            if i != j:
                reduced[i][j] -= column_min

    return reduced


def _successors_from_model(model, use_edge) -> List[int]:
    successors = [-1] * len(use_edge)
    for source, row in enumerate(use_edge):
        for destination, selected in enumerate(row):
            if is_true(model.evaluate(selected, model_completion=True)):
                successors[source] = destination
                break
        if successors[source] == -1:
            raise RuntimeError(f"solver returned an incomplete tour for city {source}")
    return successors


def _path_from_successors(successors: List[int], start_city: int) -> List[int]:
    city = start_city
    path = [start_city]
    for _ in range(len(successors) - 1):
        city = successors[city]
        path.append(city)
    return path + [start_city]


def _path_cost(distances: List[List[int]], path: List[int]) -> int:
    return sum(distances[path[i]][path[i + 1]] for i in range(len(path) - 1))
