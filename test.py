from smt import smt
from dp import dp
import random
import time
import matplotlib.pyplot as plt
import statistics
''''
distances = [
    [0, 10, 15, 20],
    [10, 0, 35, 25],
    [15, 35, 0, 300],
    [20, 25, 300, 0]
]
'''

min_size = 10
max_size = 23
iterations = 10
smt_enabled = True
dp_enabled = True

smt_times_by_size: dict[int, list[float]] = {}
dp_times_by_size: dict[int, list[float]] = {}

for size in range(min_size, max_size + 1):
    smt_times_by_size[size] = []
    dp_times_by_size[size] = []
    for _ in range(iterations):
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
            smt_times_by_size[size].append(smt_time)
        if dp_enabled:
            start = time.perf_counter()
            dp_dist, dp_path = dp(distances)
            dp_time = time.perf_counter() - start
            print(f"dp took {dp_time}")
            print(f"dp: {dp_dist}, {dp_path}")
            dp_times_by_size[size].append(dp_time)
        if smt_enabled and dp_enabled:
            if smt_dist == dp_dist:
                print("Agree")
            else:
                print("DISAGREE")

for size in smt_times_by_size:
    print(f"size {size}: {smt_times_by_size[size]}")
    print(f"size {size}: {dp_times_by_size[size]}")


smt_sizes = [sz for sz, t in smt_times_by_size.items() if t]
smt_medians = [statistics.median(smt_times_by_size[sz]) for sz in smt_sizes]

dp_sizes = [sz for sz, t in dp_times_by_size.items() if t]
dp_medians = [statistics.median(dp_times_by_size[sz]) for sz in dp_sizes]

print("SMT size → median_time:", list(zip(smt_sizes, smt_medians)))
print("DP size → median_time:", list(zip(dp_sizes, dp_medians)))

plt.scatter(dp_sizes,  dp_medians,  label="dp")
plt.scatter(smt_sizes, smt_medians, label="smt")
plt.xlabel("Cities")
plt.ylabel("Median time (seconds)")
plt.legend()
plt.show()