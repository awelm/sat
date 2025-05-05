# This code is mostly taken from: https://www.interviewbit.com/blog/travelling-salesman-problem/

MAX = 999999


def TSP(mask, pos, graph, dp, next_move, n, visited):
    if mask == visited:
        return graph[pos][0]

    if dp[mask][pos] != -1:
        return dp[mask][pos]

    ans = MAX
    for city in range(n):
        if (mask & (1 << city)) == 0:
            new_cost = graph[pos][city] + TSP(
                mask | (1 << city), city, graph, dp, next_move, n, visited
            )
            if new_cost < ans:
                ans = new_cost
                next_move[(mask, pos)] = city

    dp[mask][pos] = ans
    return ans


def dp(graph):
    n = len(graph)
    visited = (1 << n) - 1

    dp_tbl = [[-1] * n for _ in range(1 << n)]
    next_move = {}

    cost = TSP(1, 0, graph, dp_tbl, next_move, n, visited)

    # Reconstruct optimal path (start and end at city 0)
    mask, pos = 1, 0
    path = [0]
    while len(path) < n:
        pos = next_move[(mask, pos)]
        path.append(pos)
        mask |= 1 << pos
    path.append(0)
    return cost, path