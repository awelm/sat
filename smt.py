from z3 import *

# Given an adjacency matrix describing a graph, return the minimum cost and route that starts at city 0, visits each
# city exactly once and returns to city 0
def smt(distances):
    num_cities = len(distances)
    s = Optimize()

    # Variables representing our decision to use an edge or not
    edges_used = [[Bool("r_%s_%s" % (i, j)) for j in range(num_cities)] for i in range(num_cities)]

    # Variable representing the total distance traveled. If we use an edge, then its distance
    # is added to total_distance
    total_distance = Int("total_distance")
    s.add(total_distance == Sum(
        [If(edges_used[i][j], distances[i][j], 0) for i in range(num_cities) for j in range(num_cities)]))

    # Variables representing the order in which cities are visited. This will help us eliminate
    # subtours by applying the MTZ constraint (explained below)
    orders = [Int("order_%s" % i) for i in range(num_cities)]
    for i in range(num_cities):
        s.add(orders[i] >= 0, orders[i] < num_cities)

    # Add constraint that binds edges_used with the order in which cities are visited
    for i in range(num_cities):
        for j in range(num_cities):
            if i != j:
                # Apply MTZ constraint to eliminate subtours from our solution. All this means is that if we use an edge
                # from city i -> city j, then city j must be visited after city i. This also ensures that city 0 is
                # visited first
                if j != 0:
                    s.add(If(edges_used[i][j] == True, orders[j] > orders[i], True))
            else:
                # You can't travel from a city to itself
                s.add(edges_used[i][j] == False)

    # Add constraint to ensure that each city in the tour has only one predecessor and one successor. This can be
    # enforced by ensuring the sum of each row and column in the `edges_used` matrix is 1. Use Bools instead of
    # Integers to encode this constraint more efficiently
    for i in range(num_cities):
        visited = False
        for j in range(num_cities):
            s.add(If(edges_used[i][j] == True, visited == False, True))
            visited = Or(visited, edges_used[i][j])
        s.add(visited == True)

    # Call the solver and return the minimum cost and tour path
    s.minimize(total_distance)
    if s.check() == sat:
        model = s.model()
        min_tour_cost = model[total_distance].as_long()
        return min_tour_cost, get_tour_path(s, 0, num_cities, edges_used)
    else:
        return -1, []


# Return the optimal tour path found by the solver
def get_tour_path(s, start_city, num_cities, routes):
    model = s.model()
    curr_city = start_city
    path = []
    for i in range(num_cities):
        for j in range(num_cities):
            if model[routes[curr_city][j]]:
                path.append(curr_city)
                curr_city = j
                break

    return path + [start_city]
