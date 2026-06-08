from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional, Tuple

from z3 import (
    And,
    Bool,
    BoolRef,
    BoolVal,
    If,
    Implies,
    Int,
    Not,
    Optimize,
    PbEq,
    PbLe,
    Sum,
    sat,
)

ObjectiveMode = Literal["auto", "soft", "linear"]
StrategyMode = Literal["lazy", "ordered"]


@dataclass
class SmtStats:
    strategy: str = ""
    uses_order_constraints: bool = False
    resolved_objective: str = ""
    check_count: int = 0
    subtour_cut_count: int = 0
    subtour_iterations: List[List[int]] = field(default_factory=list)


# Given an adjacency matrix describing a graph, return the minimum cost and route that
# starts at city 0, visits each city exactly once and returns to city 0.
def smt(
    distances: List[List[int]],
    required_orders: Optional[Dict[int, int]] = None,
    objective: ObjectiveMode = "auto",
    strategy: StrategyMode = "lazy",
    stats: Optional[SmtStats] = None,
    timeout_ms: int = 0,
) -> Tuple[int, List[int]]:
    num_cities = len(distances)
    if num_cities == 0:
        return -1, []
    if num_cities == 1:
        return 0, [0, 0]

    solver = Optimize()
    solver.set("pb.compile_equality", True)
    solver.set("maxsat_engine", "maxres")
    if timeout_ms > 0:
        solver.set("timeout", timeout_ms)

    # Variables representing our decision to use an edge or not.
    # Self-edges are constants, not solver variables. That keeps the edge matrix easy
    # to read while avoiding n unnecessary Booleans and smaller degree constraints.
    edges_used: List[List[BoolRef]] = [
        [
            BoolVal(False) if i == j else Bool(f"r_{i}_{j}")
            for j in range(num_cities)
        ]
        for i in range(num_cities)
    ]

    total_distance = None
    objective_distances = _reduce_assignment_objective_distances(distances)
    resolved_objective = _resolve_objective(objective_distances, objective)
    resolved_strategy = _resolve_strategy(strategy)
    use_order_constraints = bool(required_orders) or resolved_strategy == "ordered"
    if stats is not None:
        stats.strategy = resolved_strategy
        stats.uses_order_constraints = use_order_constraints
        stats.resolved_objective = resolved_objective

    if resolved_objective == "soft":
        _add_weighted_maxsat_objective(solver, edges_used, objective_distances)
    else:
        # Variable representing the total distance traveled. If we use an edge then its
        # distance is added to total_distance.
        total_distance = Int("total_distance")
        solver.add(
            total_distance
            == Sum(
                [
                    If(edges_used[i][j], objective_distances[i][j], 0)
                    for i in range(num_cities)
                    for j in range(num_cities)
                    if i != j
                ]
            )
        )

    _add_degree_constraints(
        solver,
        edges_used,
        num_cities,
        forbid_two_cycles=not use_order_constraints,
    )
    if not required_orders and _is_symmetric(distances):
        _add_reverse_tour_symmetry_break(solver, edges_used, num_cities)
    if use_order_constraints:
        _add_order_constraints(
            solver,
            edges_used,
            num_cities,
            required_orders or {},
        )

    if total_distance is not None:
        solver.minimize(total_distance)

    while True:
        result = solver.check()
        if stats is not None:
            stats.check_count += 1
        if result != sat:
            break

        model = solver.model()
        successors = _get_successors(model, edges_used, num_cities)
        subtours = _get_subtours(successors)
        if len(subtours) == 1 and len(subtours[0]) == num_cities:
            return _tour_cost(distances, successors), _build_tour_path(successors, 0)
        cut_sizes = _add_subtour_elimination_constraints(solver, edges_used, subtours)
        if stats is not None:
            stats.subtour_cut_count += len(cut_sizes)
            stats.subtour_iterations.append(cut_sizes)

    return -1, []


def _resolve_objective(
    distances: List[List[int]],
    objective: ObjectiveMode,
) -> str:
    if objective not in ("auto", "soft", "linear"):
        raise ValueError("objective must be one of: auto, soft, linear")
    if objective == "auto":
        return "soft" if _can_use_weighted_maxsat(distances) else "linear"
    if objective == "soft" and not _can_use_weighted_maxsat(distances):
        raise ValueError("soft objective requires non-negative off-diagonal distances")
    return objective


def _resolve_strategy(strategy: StrategyMode) -> str:
    if strategy not in ("lazy", "ordered"):
        raise ValueError("strategy must be one of: lazy, ordered")
    return strategy


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


def _reduce_assignment_objective_distances(distances: List[List[int]]) -> List[List[int]]:
    """Remove row/column constants from the objective without changing the argmin."""
    num_cities = len(distances)
    reduced = [[0] * num_cities for _ in range(num_cities)]

    for i in range(num_cities):
        row_min = min(distances[i][j] for j in range(num_cities) if i != j)
        for j in range(num_cities):
            if i != j:
                reduced[i][j] = distances[i][j] - row_min

    for j in range(num_cities):
        column_min = min(reduced[i][j] for i in range(num_cities) if i != j)
        for i in range(num_cities):
            if i != j:
                reduced[i][j] -= column_min

    return reduced


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
    forbid_two_cycles: bool = True,
) -> None:
    for i in range(num_cities):
        solver.add(
            PbEq(
                [(edges_used[i][j], 1) for j in range(num_cities) if i != j],
                1,
            )
        )
    for j in range(num_cities):
        solver.add(
            PbEq(
                [(edges_used[i][j], 1) for i in range(num_cities) if i != j],
                1,
            )
        )

    # Two-cycles are never part of a valid tour once there are at least 3 cities, so
    # ruling them out up front cuts a large class of bad models before lazy cuts kick in.
    if forbid_two_cycles and num_cities > 2:
        for i in range(num_cities):
            for j in range(i + 1, num_cities):
                solver.add(Not(And(edges_used[i][j], edges_used[j][i])))


def _add_order_constraints(
    solver: Optimize,
    edges_used: List[List[BoolRef]],
    num_cities: int,
    required_orders: Dict[int, int],
) -> None:
    orders = [Int(f"order_{i}") for i in range(num_cities)]
    solver.add(orders[0] == 0)
    for i in range(1, num_cities):
        solver.add(And(orders[i] >= 1, orders[i] < num_cities))

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
) -> List[int]:
    num_cities = len(edges_used)
    all_cities = frozenset(range(num_cities))
    seen: set[frozenset[int]] = set()
    cut_sizes = []
    for subtour in subtours:
        subset = frozenset(subtour)
        if len(subset) == num_cities:
            continue
        complement = all_cities - subset
        candidates = [subset]
        if 1 < len(complement) < num_cities:
            candidates.append(complement)
        subset = min(candidates, key=lambda item: (len(item), tuple(sorted(item))))
        if len(subset) <= 1 or subset in seen:
            continue
        seen.add(subset)
        solver.add(
            PbLe(
                [
                    (edges_used[i][j], 1)
                    for i in subset
                    for j in subset
                    if i != j
                ],
                len(subset) - 1,
            )
        )
        cut_sizes.append(len(subset))
    return cut_sizes


def _build_tour_path(successors: List[int], start_city: int) -> List[int]:
    curr_city = start_city
    path = [start_city]
    for _ in range(len(successors) - 1):
        curr_city = successors[curr_city]
        path.append(curr_city)
    return path + [start_city]


def _tour_cost(distances: List[List[int]], successors: List[int]) -> int:
    return sum(distances[city][successors[city]] for city in range(len(successors)))
