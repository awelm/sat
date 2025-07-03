# This code is mostly taken from: https://www.interviewbit.com/blog/travelling-salesman-problem/

from __future__ import annotations

from typing import Dict, List, Tuple

MAX = 999999


def TSP(
    mask: int,
    pos: int,
    graph: List[List[int]],
    dp: List[List[int]],
    next_move: Dict[Tuple[int, int], int],
    n: int,
    visited: int,
) -> int:
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


def dp(graph: List[List[int]]) -> Tuple[int, List[int]]:
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
