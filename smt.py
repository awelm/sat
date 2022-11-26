from z3 import *

# distances between cities
num_cities = 4
'''
    [0, 0, 1, 0],
    [0, 0, 0, 1],
    [0, 1, 0, 0],
    [1, 0, 0, 0]
'''

def smt(distances):
    # matrix to keep track of routes
    routes = [[Int("r_%s_%s" % (i, j)) for j in range(num_cities)] for i in range(num_cities)]

    # total distance traveled
    total_distance = Int("total_distance")

    s = Optimize()

    orders = [Int("order_%s" % i) for i in range(num_cities)]
    for i in range(num_cities):
        s.add(orders[i] >= 0, orders[i] < num_cities)

    for i in range(num_cities):
      for j in range(num_cities):
        if i != j:
            s.add(routes[i][j] >= 0, routes[i][j] <= 1)
            if j != 0:
                s.add(If(routes[i][j] == 1, orders[j] > orders[i], True))
        else:
            s.add(routes[i][j] == 0)

    for i in range(num_cities):
        s.add(Sum(routes[i]) == 1)

    # ensure we only visit each city once
    for i in range(num_cities):
        constraint = routes[0][i]
        for j in range(1,num_cities):
            constraint += routes[j][i]
        s.add(constraint == 1)

    # ensure the total distance is the sum of the distances between the cities we visit
    s.add(total_distance == Sum([routes[i][j] * distances[i][j] for i in range(num_cities) for j in range(num_cities)]))

    s.minimize(total_distance)
    if s.check() == sat:
      model = s.model()
      min_dist = model[total_distance]
      curr = 0
      path = []
      for i in range(num_cities):
        for j in range(num_cities):
          if model[routes[curr][j]] == 1:
            #print("Travel from city %s to city %s. Distance %d" % (curr, j, distances[i][j]))
            path.append(curr)
            curr = j
            break

      return min_dist, path+[0]

    else:
      return -1, []