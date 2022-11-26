from sys import maxsize
from itertools import permutations

V = 4


# implementation of traveling Salesman Problem
def brute(graph, s):
    # store all vertex apart from source vertex
    vertex = []
    for i in range(V):
        if i != s:
            vertex.append(i)

    # store minimum weight Hamiltonian Cycle
    min_cost = maxsize
    min_path = []
    next_permutation = permutations(vertex)
    for i in next_permutation:

        # store current Path weight(cost)
        current_pathweight = 0

        # compute current path weight
        k = s
        for j in i:
            current_pathweight += graph[k][j]
            k = j
        current_pathweight += graph[k][s]

        # update minimum
        if current_pathweight < min_cost:
            min_cost = current_pathweight
            min_path = i

    return min_cost, [0] + list(min_path) + [0]


# Driver Code
if __name__ == "__main__":
    # matrix representation of graph
    graph = [
        [0, 10, 15, 20],
        [10, 0, 35, 25],
        [15, 35, 0, 300],
        [20, 25, 300, 0]
    ]
    s = 0
    cost, path = travellingSalesmanProblem(graph, s)
    print(cost)
    print(path)