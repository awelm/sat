from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from z3 import Int, Optimize, Sum, If, And, Distinct, sat, set_param

# Global configuration
DEFAULT_TIMEOUT_MS = 600000  # 10 minutes

# Configure Z3 solver parameters once at module level for better performance
set_param('parallel.enable', True)
set_param('parallel.threads.max', 8)
set_param('opt.priority', 'lex')
set_param('smt.arith.solver', 2)
set_param('smt.phase_selection', 5)
set_param('smt.restart_strategy', 1)
set_param('smt.random_seed', 0)
set_param('smt.arith.random_initial_value', True)
set_param('opt.enable_sls', False)


# Given an adjacency matrix describing a graph, return the minimum cost and route that
# starts at city 0, visits each city exactly once and returns to city 0.
def smt(
    distances: List[List[int]],
    required_orders: Optional[Dict[int, int]] = None,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
) -> Tuple[int, List[int]]:
    num_cities = len(distances)
    if num_cities == 0:
        return -1, []
    if num_cities == 1:
        return 0, [0, 0]

    s = Optimize()
    s.set(timeout=timeout_ms)
    succ = [Int(f"succ_{i}") for i in range(num_cities)]
    
    # Basic constraints: each city has exactly one valid successor
    constraints = [Distinct(*succ)]
    cost_terms = []
    
    for i in range(num_cities):
        constraints.extend([succ[i] >= 0, succ[i] < num_cities, succ[i] != i])
        for j in range(num_cities):
            if i != j:
                cost_terms.append(If(succ[i] == j, distances[i][j], 0))
    
    s.add(And(constraints))
    
    # Minimize total distance
    total_distance = Int("total_distance")
    s.add(total_distance == Sum(cost_terms))

    # Prevent subtours with Miller-Tucker-Zemlin constraints
    orders = [Int(f"order_{i}") for i in range(num_cities)]
    mtz_constraints = [orders[0] == 0]
    
    for i in range(1, num_cities):
        mtz_constraints.extend([orders[i] >= 1, orders[i] < num_cities])
    
    for i in range(num_cities):
        for j in range(num_cities):
            if i != j:
                if j == 0:
                    mtz_constraints.append(If(succ[i] == j, orders[i] == num_cities - 1, True))
                else:
                    mtz_constraints.append(If(succ[i] == j, orders[j] == orders[i] + 1, True))
    
    s.add(And(mtz_constraints))

    # Handle required orders constraint
    if required_orders:
        for city, day in required_orders.items():
            if not (0 <= city < num_cities and 0 <= day < num_cities):
                raise ValueError("required_orders contains out of range values")
            s.add(orders[city] == day)

    s.minimize(total_distance)

    if s.check() == sat:
        model = s.model()
        cost = model[total_distance].as_long()
        return cost, get_tour_path(model, 0, num_cities, succ)

    return -1, []


def get_tour_path(model, start_city: int, num_cities: int, succ) -> List[int]:
    """Extract tour path from successor variables."""
    curr_city = start_city
    path = []
    for _ in range(num_cities):
        path.append(curr_city)
        curr_city = model[succ[curr_city]].as_long()
    return path + [start_city]
