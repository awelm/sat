from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from z3 import Bool, BoolRef, Int, Optimize, Sum, If, And, sat


# Given an adjacency matrix describing a graph, return the minimum cost and route that
# starts at city 0, visits each city exactly once and returns to city 0.
def smt(
    distances: List[List[int]],
    required_orders: Optional[Dict[int, int]] = None,
) -> Tuple[int, List[int]]:
    num_cities = len(distances)
    if num_cities == 1:
        # Trivial case: start and end at the only city with zero cost
        return 0, [0, 0]

    s = Optimize()

    # Variables representing our decision to use an edge or not.
    edges_used: List[List[BoolRef]] = [
        [Bool(f"r_{i}_{j}") for j in range(num_cities)] for i in range(num_cities)
    ]

    # Variable representing the total distance traveled. If we use an edge then its
    # distance is added to total_distance.
    total_distance = Int("total_distance")
    s.add(
        total_distance
        == Sum(
            [
                If(edges_used[i][j], distances[i][j], 0)
                for i in range(num_cities)
                for j in range(num_cities)
            ]
        )
    )

    # Variables representing the order in which cities are visited. This will help us
    # eliminate subtours by applying the MTZ constraint (explained below).
    orders = [Int(f"order_{i}") for i in range(num_cities)]
    s.add(orders[0] == 0)
    for i in range(1, num_cities):
        s.add(And(orders[i] >= 1, orders[i] < num_cities))

    if required_orders:
        for city, day in required_orders.items():
            if not (0 <= city < num_cities and 0 <= day < num_cities):
                raise ValueError("required_orders contains out of range values")
            s.add(orders[city] == day)

    # Add constraint that binds edges_used with the order in which cities are visited.
    for i in range(num_cities):
        s.add(edges_used[i][i] == False)
        s.add(Sum([If(edges_used[i][j], 1, 0) for j in range(num_cities)]) == 1)

    # Add constraint to ensure that each city in the tour has only one predecessor and
    # one successor. This can be enforced by ensuring the sum of each row and column in
    # the edges_used matrix is 1.
    for j in range(num_cities):
        s.add(Sum([If(edges_used[i][j], 1, 0) for i in range(num_cities)]) == 1)

    for i in range(1, num_cities):
        for j in range(1, num_cities):
            if i != j:
                s.add(
                    orders[i]
                    - orders[j]
                    + (num_cities - 1) * If(edges_used[i][j], 1, 0)
                    <= num_cities - 2
                )

    # Call the solver and return the minimum cost and tour path.
    s.minimize(total_distance)

    if s.check() == sat:
        model = s.model()
        cost = model[total_distance].as_long()
        return cost, get_tour_path(s, 0, num_cities, edges_used)

    return -1, []


# Return the optimal tour path found by the solver.
def get_tour_path(
    s: Optimize,
    start_city: int,
    num_cities: int,
    routes: List[List[BoolRef]],
) -> List[int]:
    model = s.model()
    curr_city = start_city
    path = []
    for _ in range(num_cities):
        path.append(curr_city)
        for j in range(num_cities):
            if model[routes[curr_city][j]]:
                curr_city = j
                break
    return path + [start_city]
