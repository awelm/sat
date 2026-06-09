from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from z3 import And, Bool, If, Implies, Int, Not, Optimize, Sum, is_true, sat


# Given an adjacency matrix describing a graph, return the minimum cost and route that
# starts at city 0, visits each city exactly once and returns to city 0.
def smt(
    distances: List[List[int]],
    required_orders: Optional[Dict[int, int]] = None,
    timeout_ms: int = 0,
) -> Tuple[int, List[int]]:
    num_cities = len(distances)
    if num_cities == 0:
        return -1, []
    if num_cities == 1:
        return 0, [0, 0]

    solver = Optimize()
    if timeout_ms > 0:
        solver.set("timeout", timeout_ms)

    cities = range(num_cities)

    # edge[i][j] means the tour goes directly from city i to city j.
    edge = [[Bool(f"edge_{i}_{j}") for j in cities] for i in cities]
    for i in cities:
        solver.add(Not(edge[i][i]))

    # order[i] is the day/position when city i is visited. City 0 is the start.
    order = [Int(f"order_{i}") for i in cities]
    solver.add(order[0] == 0)
    for i in range(1, num_cities):
        solver.add(And(order[i] >= 1, order[i] < num_cities))

    if required_orders:
        for city, day in required_orders.items():
            if not (0 <= city < num_cities and 0 <= day < num_cities):
                raise ValueError("required_orders contains out of range values")
            solver.add(order[city] == day)

    # Every city has exactly one outgoing edge and one incoming edge.
    for i in cities:
        solver.add(Sum([If(edge[i][j], 1, 0) for j in cities]) == 1)
        solver.add(Sum([If(edge[j][i], 1, 0) for j in cities]) == 1)

    # If we travel i -> j, then j must be the next city in the visit order.
    # This rules out disconnected subtours.
    for i in cities:
        for j in cities:
            if i == j:
                continue
            if j == 0:
                solver.add(Implies(edge[i][j], order[i] == num_cities - 1))
            elif i == 0:
                solver.add(Implies(edge[i][j], order[j] == 1))
            else:
                solver.add(Implies(edge[i][j], order[j] == order[i] + 1))

    objective_distances = _reduce_assignment_objective_distances(distances)
    solver.minimize(
        Sum(
            [
                If(edge[i][j], objective_distances[i][j], 0)
                for i in cities
                for j in cities
                if i != j
            ]
        )
    )

    if solver.check() != sat:
        return -1, []

    model = solver.model()
    successors = _get_successors(model, edge)
    return _tour_cost(distances, successors), _build_tour_path(successors, 0)


def _reduce_assignment_objective_distances(distances: List[List[int]]) -> List[List[int]]:
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


def _get_successors(model, edge: List[List[Bool]]) -> List[int]:
    successors = [-1] * len(edge)
    for i, row in enumerate(edge):
        for j, decision in enumerate(row):
            if is_true(model.evaluate(decision, model_completion=True)):
                successors[i] = j
                break
        if successors[i] == -1:
            raise RuntimeError(f"solver returned an incomplete tour for city {i}")
    return successors


def _build_tour_path(successors: List[int], start_city: int) -> List[int]:
    curr_city = start_city
    path = [start_city]
    for _ in range(len(successors) - 1):
        curr_city = successors[curr_city]
        path.append(curr_city)
    return path + [start_city]


def _tour_cost(distances: List[List[int]], successors: List[int]) -> int:
    return sum(distances[city][successors[city]] for city in range(len(successors)))
