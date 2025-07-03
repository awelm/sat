from __future__ import annotations

from typing import Dict, List

import argparse

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

min_size: int = 10
max_size: int = 23
iterations: int = 10
smt_enabled: bool = True
dp_enabled: bool = True
modified_smt_enabled: bool = True

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-size", type=int, default=min_size)
    parser.add_argument("--max-size", type=int, default=max_size)
    parser.add_argument("--iterations", type=int, default=iterations)
    parser.add_argument("--smt", dest="smt", action="store_true", default=smt_enabled)
    parser.add_argument("--dp", dest="dp", action="store_true", default=dp_enabled)
    parser.add_argument("--smt-ordered", dest="smt_ordered", action="store_true", default=modified_smt_enabled)
    parser.add_argument("--no-plot", action="store_true")
    args = parser.parse_args()

    smt_enabled_local = args.smt
    dp_enabled_local = args.dp
    smt_modified_enabled = args.smt_ordered

    smt_times_by_size: Dict[int, List[float]] = {}
    dp_times_by_size: Dict[int, List[float]] = {}
    smt_modified_times_by_size: Dict[int, List[float]] = {}

    for size in range(args.min_size, args.max_size + 1):
        smt_times_by_size[size] = []
        dp_times_by_size[size] = []
        smt_modified_times_by_size[size] = []
        for _ in range(args.iterations):
            distances = [[random.randint(0, 100) for _ in range(size)] for _ in range(size)]
            for i in range(size):
                distances[i][i] = 0
            print(f"size {size}, distances {distances}")
            if smt_enabled_local:
                start = time.perf_counter()
                smt_dist, smt_path = smt(distances)
                smt_time = time.perf_counter() - start
                print(f"smt: {smt_dist}, {smt_path}")
                print(f"smt took {smt_time}")
                smt_times_by_size[size].append(smt_time)
            if smt_modified_enabled:
                required_orders = {size - 1: 1} if size > 1 else {0: 0}
                start = time.perf_counter()
                modified_dist, modified_path = smt(distances, required_orders)
                modified_time = time.perf_counter() - start
                print(f"smt ordered: {modified_dist}, {modified_path}")
                print(f"smt ordered took {modified_time}")
                smt_modified_times_by_size[size].append(modified_time)
            if dp_enabled_local:
                start = time.perf_counter()
                dp_dist, dp_path = dp(distances)
                dp_time = time.perf_counter() - start
                print(f"dp took {dp_time}")
                print(f"dp: {dp_dist}, {dp_path}")
                dp_times_by_size[size].append(dp_time)
            if smt_enabled_local and dp_enabled_local:
                if smt_dist == dp_dist:
                    print("Agree")
                else:
                    print("DISAGREE")

    for size in smt_times_by_size:
        print(f"size {size}: {smt_times_by_size[size]}")
        print(f"size {size}: {dp_times_by_size[size]}")
        print(f"size {size}: {smt_modified_times_by_size[size]}")



    smt_sizes = [sz for sz, t in smt_times_by_size.items() if t]
    smt_medians = [statistics.median(smt_times_by_size[sz]) for sz in smt_sizes]
    modified_sizes = [sz for sz, t in smt_modified_times_by_size.items() if t]
    modified_medians = [statistics.median(smt_modified_times_by_size[sz]) for sz in modified_sizes]

    dp_sizes = [sz for sz, t in dp_times_by_size.items() if t]
    dp_medians = [statistics.median(dp_times_by_size[sz]) for sz in dp_sizes]

    print("SMT size → median_time:", list(zip(smt_sizes, smt_medians)))
    print("Modified SMT size → median_time:", list(zip(modified_sizes, modified_medians)))
    print("DP size → median_time:", list(zip(dp_sizes, dp_medians)))

    if not args.no_plot:
        plt.scatter(dp_sizes, dp_medians, label="dp")
        plt.scatter(smt_sizes, smt_medians, label="smt")
        plt.scatter(modified_sizes, modified_medians, label="smt_ordered")
        plt.xlabel("Cities")
        plt.ylabel("Median time (seconds)")
        plt.legend()
        plt.show()


if __name__ == "__main__":
    main()
