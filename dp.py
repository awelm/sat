from __future__ import annotations

from functools import cache
from typing import List, Tuple


def dp(graph: List[List[int]]) -> Tuple[int, List[int]]:
    n = len(graph)
    if n == 0:
        return -1, []
    if n == 1:
        return 0, [0, 0]

    all_visited = (1 << n) - 1

    @cache
    def best_cost(mask: int, city: int) -> int:
        if mask == all_visited:
            return graph[city][0]

        return min(
            graph[city][next_city] + best_cost(mask | (1 << next_city), next_city)
            for next_city in range(n)
            if not mask & (1 << next_city)
        )

    path = [0]
    mask = 1
    city = 0
    while len(path) < n:
        next_city = min(
            (
                next_city
                for next_city in range(n)
                if not mask & (1 << next_city)
            ),
            key=lambda next_city: graph[city][next_city]
            + best_cost(mask | (1 << next_city), next_city),
        )
        path.append(next_city)
        mask |= 1 << next_city
        city = next_city

    path.append(0)
    return best_cost(1, 0), path
