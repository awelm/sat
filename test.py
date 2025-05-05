from smt import smt
from dp import dp
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

max_size = 18
smt_enabled = True
dp_enabled = True

smt_sizes = []
smt_times = []
dp_sizes = []
dp_times = []

for _ in range(100):
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
    if dp_enabled:
        start = time.perf_counter()
        dp_dist, dp_path = dp(distances)
        dp_time = time.perf_counter() - start
        print(f"dp took {dp_time}")
        print(f"dp: {dp_dist}, {dp_path}")
        dp_sizes.append(size)
        dp_times.append(dp_time)
    if smt_enabled and dp_enabled:
        if smt_dist == dp_dist:
            print("Agree")
        else:
            print("DISAGREE")

print("smt sizes and times:", list(zip(smt_sizes, smt_times))[-10:])
print("dp sizes and times:", list(zip(dp_sizes, dp_times))[-10:])

plt.scatter(dp_sizes, dp_times, label="dp")
plt.scatter(smt_sizes, smt_times, label="smt")
plt.xlabel('Cities')
plt.ylabel('Time (seconds)')
plt.legend()
plt.show()