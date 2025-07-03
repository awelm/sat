from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from z3 import Bool, BoolRef, Int, Optimize, Sum, If, And, Or, Distinct, sat


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

    s = Optimize()

    # Successor array: succ[i] represents the city that follows city i in the tour
    succ = [Int(f"succ_{i}") for i in range(num_cities)]
    
    # Each city has exactly one successor, and it's a valid city different from itself
    for i in range(num_cities):
        s.add(And(succ[i] >= 0, succ[i] < num_cities, succ[i] != i))
    
    # Ensure it's a permutation (each city is successor of exactly one other city)
    s.add(Distinct(*succ))

    # Total cost is sum of distances from each city to its successor
    total_distance = Int("total_distance")
    s.add(total_distance == Sum([
        Sum([If(succ[i] == j, distances[i][j], 0) for j in range(num_cities)])
        for i in range(num_cities)
    ]))

    # Use order variables to prevent subtours (Miller-Tucker-Zemlin constraints)
    orders = [Int(f"order_{i}") for i in range(num_cities)]
    s.add(orders[0] == 0)  # Start city has order 0
    
    for i in range(1, num_cities):
        s.add(And(orders[i] >= 1, orders[i] < num_cities))
    
    # MTZ constraints: if i->j, then order[j] = order[i] + 1 (mod n)
    for i in range(num_cities):
        for j in range(1, num_cities):  # j != 0 to avoid wrapping issues
            if i != j:
                s.add(If(succ[i] == j, 
                         orders[j] == orders[i] + 1, 
                         True))

    # Handle required orders constraint
    if required_orders:
        for city, day in required_orders.items():
            if not (0 <= city < num_cities and 0 <= day < num_cities):
                raise ValueError("required_orders contains out of range values")
            s.add(orders[city] == day)

    # Call the solver and return the minimum cost and tour path.
    s.minimize(total_distance)

    if s.check() == sat:
        model = s.model()
        cost = model[total_distance].as_long()
        return cost, get_tour_path(model, 0, num_cities, succ)

    return -1, []


# Return the optimal tour path found by the solver.
def get_tour_path(
    model,
    start_city: int,
    num_cities: int,
    succ: List[Int],
) -> List[int]:
    curr_city = start_city
    path = []
    for _ in range(num_cities):
        path.append(curr_city)
        curr_city = model[succ[curr_city]].as_long()
    return path + [start_city]
