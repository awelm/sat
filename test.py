from smt import smt
from brute import brute
import random
import time
import matplotlib.pyplot as plt

''''
distances = [
    [0, 10, 15, 20],
    [10, 0, 35, 25],
    [15, 35, 0, 300],
    [20, 25, 300, 0]
]
'''

max_size = 9
smt_enabled = True
brute_enabled = False

smt_sizes = []
smt_times = []
brute_sizes = []
brute_times = []

for _ in range(300):
    size = random.randint(2, max_size)
    distances = [[random.randint(0, 100) for _ in range(size)] for _ in range(size)]
    for i in range(size):
        distances[i][i] = 0
    print(f"size {size}, distances {distances}")
    if smt_enabled:
        start = time.perf_counter()
        smt_dist, smt_path = smt(distances)
        smt_time = time.perf_counter() - start
        print(f"smt: {smt_dist}, {smt_path}")
        print(f"smt took {smt_time}")
        smt_sizes.append(size)
        smt_times.append(smt_time)
    if brute_enabled:
        start = time.perf_counter()
        brute_dist, brute_path = brute(distances, 0)
        brute_time = time.perf_counter() - start
        print(f"brute took {brute_time}")
        print(f"brute: {brute_dist}, {brute_path}")
        brute_sizes.append(size)
        brute_times.append(brute_time)
    if smt_enabled and brute_enabled:
        if smt_dist == brute_dist and (smt_path == brute_path or smt_path == brute_path[::-1]):
            print("Agree")
        else:
            print("DISAGREE")


plt.scatter(brute_sizes, brute_times, label="brute")
plt.scatter(smt_sizes, smt_times, label="smt")
plt.xlabel('Cities')
plt.ylabel('Time (seconds)')
plt.show()