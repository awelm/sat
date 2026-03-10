from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from z3 import And, Bool, BoolRef, Distinct, If, Implies, Int, Not, Optimize, PbEq, PbLe, Sum, sat


# Given an adjacency matrix describing a graph, return the minimum cost and route that
# starts at city 0, visits each city exactly once and returns to city 0.
def smt(
    distances: List[List[int]],
    required_orders: Optional[Dict[int, int]] = None,
) -> Tuple[int, List[int]]:
    num_cities = len(distances)
    if num_cities == 0:
        return -1, []
    if num_cities == 1:
        return 0, [0, 0]

    solver = Optimize()
    solver.set("pb.compile_equality", True)

    # Variables representing our decision to use an edge or not.
    edges_used: List[List[BoolRef]] = [
        [Bool(f"r_{i}_{j}") for j in range(num_cities)] for i in range(num_cities)
    ]

    total_distance = None
    if _can_use_weighted_maxsat(distances):
        _add_weighted_maxsat_objective(solver, edges_used, distances)
    else:
        # Variable representing the total distance traveled. If we use an edge then its
        # distance is added to total_distance.
        total_distance = Int("total_distance")
        solver.add(
            total_distance
            == Sum(
                [
                    If(edges_used[i][j], distances[i][j], 0)
                    for i in range(num_cities)
                    for j in range(num_cities)
                ]
            )
        )

    _add_degree_constraints(solver, edges_used, num_cities)
    if not required_orders and _is_symmetric(distances):
        _add_reverse_tour_symmetry_break(solver, edges_used, num_cities)
    if required_orders:
        _add_required_order_constraints(
            solver,
            edges_used,
            num_cities,
            required_orders,
        )

    if total_distance is not None:
        solver.minimize(total_distance)

    while solver.check() == sat:
        model = solver.model()
        successors = _get_successors(model, edges_used, num_cities)
        subtours = _get_subtours(successors)
        if len(subtours) == 1 and len(subtours[0]) == num_cities:
            return _tour_cost(distances, successors), _build_tour_path(successors, 0)
        _add_subtour_elimination_constraints(solver, edges_used, subtours)

    return -1, []


def _is_symmetric(distances: List[List[int]]) -> bool:
    num_cities = len(distances)
    for i in range(num_cities):
        for j in range(i + 1, num_cities):
            if distances[i][j] != distances[j][i]:
                return False
    return True


def _can_use_weighted_maxsat(distances: List[List[int]]) -> bool:
    num_cities = len(distances)
    for i in range(num_cities):
        for j in range(num_cities):
            if i != j and distances[i][j] < 0:
                return False
    return True


def _add_weighted_maxsat_objective(
    solver: Optimize,
    edges_used: List[List[BoolRef]],
    distances: List[List[int]],
) -> None:
    num_cities = len(distances)
    for i in range(num_cities):
        for j in range(num_cities):
            if i != j and distances[i][j] > 0:
                # Maximizing the weight of edges we do not use is equivalent to minimizing
                # the total weight of the tour whenever edge weights are non-negative.
                solver.add_soft(Not(edges_used[i][j]), distances[i][j])


def _add_reverse_tour_symmetry_break(
    solver: Optimize,
    edges_used: List[List[BoolRef]],
    num_cities: int,
) -> None:
    if num_cities <= 2:
        return

    first_city = Int("first_city")
    last_city = Int("last_city")
    solver.add(first_city == Sum([If(edges_used[0][j], j, 0) for j in range(num_cities)]))
    solver.add(last_city == Sum([If(edges_used[i][0], i, 0) for i in range(num_cities)]))
    solver.add(first_city < last_city)


def _add_degree_constraints(
    solver: Optimize,
    edges_used: List[List[BoolRef]],
    num_cities: int,
) -> None:
    for i in range(num_cities):
        solver.add(edges_used[i][i] == False)
        solver.add(PbEq([(edges_used[i][j], 1) for j in range(num_cities)], 1))
    for j in range(num_cities):
        solver.add(PbEq([(edges_used[i][j], 1) for i in range(num_cities)], 1))

    # Two-cycles are never part of a valid tour once there are at least 3 cities, so
    # ruling them out up front cuts a large class of bad models before lazy cuts kick in.
    if num_cities > 2:
        for i in range(num_cities):
            for j in range(i + 1, num_cities):
                solver.add(Not(And(edges_used[i][j], edges_used[j][i])))


def _add_required_order_constraints(
    solver: Optimize,
    edges_used: List[List[BoolRef]],
    num_cities: int,
    required_orders: Dict[int, int],
) -> None:
    orders = [Int(f"order_{i}") for i in range(num_cities)]
    solver.add(orders[0] == 0)
    for i in range(1, num_cities):
        solver.add(And(orders[i] >= 1, orders[i] < num_cities))
    solver.add(Distinct(orders))

    for city, day in required_orders.items():
        if not (0 <= city < num_cities and 0 <= day < num_cities):
            raise ValueError("required_orders contains out of range values")
        solver.add(orders[city] == day)

    for i in range(num_cities):
        for j in range(num_cities):
            if i == j:
                continue
            if j == 0:
                solver.add(Implies(edges_used[i][j], orders[i] == num_cities - 1))
            elif i == 0:
                solver.add(Implies(edges_used[i][j], orders[j] == 1))
            else:
                solver.add(Implies(edges_used[i][j], orders[j] == orders[i] + 1))


def _get_successors(
    model,
    edges_used: List[List[BoolRef]],
    num_cities: int,
) -> List[int]:
    successors = [-1] * num_cities
    for i in range(num_cities):
        for j in range(num_cities):
            if model.evaluate(edges_used[i][j]):
                successors[i] = j
                break
        if successors[i] == -1:
            raise RuntimeError(f"solver returned an incomplete tour for city {i}")
    return successors


def _get_subtours(successors: List[int]) -> List[List[int]]:
    unvisited = set(range(len(successors)))
    subtours = []
    while unvisited:
        start_city = next(iter(unvisited))
        subtour = []
        curr_city = start_city
        while curr_city in unvisited:
            unvisited.remove(curr_city)
            subtour.append(curr_city)
            curr_city = successors[curr_city]
        subtours.append(subtour)
    return subtours


def _add_subtour_elimination_constraints(
    solver: Optimize,
    edges_used: List[List[BoolRef]],
    subtours: List[List[int]],
) -> None:
    num_cities = len(edges_used)
    for subtour in subtours:
        if len(subtour) == num_cities:
            continue
        solver.add(
            PbLe(
                [
                    (edges_used[i][j], 1)
                    for i in subtour
                    for j in subtour
                    if i != j
                ],
                len(subtour) - 1,
            )
        )


def _build_tour_path(successors: List[int], start_city: int) -> List[int]:
    curr_city = start_city
    path = [start_city]
    for _ in range(len(successors) - 1):
        curr_city = successors[curr_city]
        path.append(curr_city)
    return path + [start_city]


def _tour_cost(distances: List[List[int]], successors: List[int]) -> int:
    return sum(distances[city][successors[city]] for city in range(len(successors)))
