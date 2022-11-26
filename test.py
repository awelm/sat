from smt import smt
from brute import brute

distances = [
    [0, 10, 15, 20],
    [10, 0, 35, 25],
    [15, 35, 0, 300],
    [20, 25, 300, 0]
]

smt_dist, smt_path = smt(distances)
brute_dist, brute_path = brute(distances, 0)
print(smt_dist, smt_path)
print(brute_dist, brute_path)
assert smt_dist == brute_dist
assert smt_path == brute_path or smt_path == brute_path[::-1]