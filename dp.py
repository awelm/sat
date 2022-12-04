# This code is mostly taken from: https://www.interviewbit.com/blog/travelling-salesman-problem/

MAX = 999999

def TSP(mask, pos, graph, dp, n, visited):
    if mask == visited:
        return graph[pos][0]
    if dp[mask][pos] != -1:
        return dp[mask][pos]
    ans = MAX
    for city in range(0, n):
        if ((mask & (1 << city)) == 0):
            new = graph[pos][city] + TSP(mask | (1 << city), city, graph, dp, n, visited)
            ans = min(ans, new)

    dp[mask][pos] = ans
    return dp[mask][pos]


def dp(graph):
    n = len(graph)
    visited = (1 << n) - 1
    r, c = 1 << n, n
    dp = [[-1 for _ in range(c)] for _ in range(r)]
    for i in range(0, (1 << n)):
        for j in range(0, n):
            dp[i][j] = -1
    return TSP(1, 0, graph, dp, n, visited), []