# This code is mostly taken from: https://www.geeksforgeeks.org/traveling-salesman-problem-tsp-implementation/

from __future__ import annotations

from sys import maxsize
from itertools import permutations
from typing import List, Tuple


def brute(graph: List[List[int]], start: int = 0) -> Tuple[int, List[int]]:
    V = len(graph)
    # store all vertex apart from source vertex
    vertex = []
    for i in range(V):
        if i != start:
            vertex.append(i)

    # store minimum weight Hamiltonian Cycle
    min_cost = maxsize
    min_path = []
    next_permutation = permutations(vertex)
    for i in next_permutation:
        # store current Path weight(cost)
        current_pathweight = 0
        # compute current path weight
        k = start
        for j in i:
            current_pathweight += graph[k][j]
            k = j
        current_pathweight += graph[k][start]
        # update minimum
        if current_pathweight < min_cost:
            min_cost = current_pathweight
            min_path = i

    return min_cost, [start] + list(min_path) + [start]
