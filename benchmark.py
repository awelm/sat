from __future__ import annotations

import argparse
import random
import statistics
import time
from typing import Dict, List, Tuple

import matplotlib.pyplot as plt

from dp import dp
from smt import smt


def build_distances(size: int, rng: random.Random, symmetric: bool) -> List[List[int]]:
    distances = [[0] * size for _ in range(size)]
    if symmetric:
        for i in range(size):
            for j in range(i + 1, size):
                weight = rng.randint(1, 100)
                distances[i][j] = weight
                distances[j][i] = weight
        return distances

    for i in range(size):
        for j in range(size):
            if i != j:
                distances[i][j] = rng.randint(1, 100)
    return distances


def time_solver(fn) -> Tuple[float, Tuple[int, List[int]]]:
    start = time.perf_counter()
    result = fn()
    return time.perf_counter() - start, result


def tour_cost(distances: List[List[int]], path: List[int]) -> int:
    return sum(distances[path[i]][path[i + 1]] for i in range(len(path) - 1))


def print_summary(label: str, times_by_size: Dict[int, List[float]]) -> None:
    summary = []
    for size, times in times_by_size.items():
        if not times:
            continue
        summary.append(
            (
                size,
                min(times),
                statistics.median(times),
                max(times),
            )
        )
    print(f"{label} size -> min/median/max:", summary)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-size", type=int, default=10)
    parser.add_argument("--max-size", type=int, default=20)
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--symmetric", action="store_true")
    parser.add_argument("--required-city", type=int, default=2)
    parser.add_argument("--required-day", type=int, default=1)
    parser.add_argument("--no-smt", dest="smt", action="store_false", default=True)
    parser.add_argument("--no-dp", dest="dp", action="store_false", default=True)
    parser.add_argument(
        "--smt-modified",
        dest="smt_modified",
        action="store_true",
        default=False,
    )
    parser.add_argument("--no-plot", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    smt_times_by_size: Dict[int, List[float]] = {}
    dp_times_by_size: Dict[int, List[float]] = {}
    smt_modified_times_by_size: Dict[int, List[float]] = {}

    required_orders = {args.required_city: args.required_day}

    for size in range(args.min_size, args.max_size + 1):
        smt_times_by_size[size] = []
        dp_times_by_size[size] = []
        smt_modified_times_by_size[size] = []

        for iteration in range(args.iterations):
            distances = build_distances(size, rng, symmetric=args.symmetric)
            if args.verbose:
                print(f"size={size} iteration={iteration} distances={distances}")

            smt_result: Tuple[int, List[int]] | None = None
            dp_result: Tuple[int, List[int]] | None = None

            if args.smt:
                smt_time, smt_result = time_solver(lambda: smt(distances))
                smt_times_by_size[size].append(smt_time)
                if tour_cost(distances, smt_result[1]) != smt_result[0]:
                    raise AssertionError("smt() returned a tour whose cost does not match")

            if (
                args.smt_modified
                and args.required_city < size
                and args.required_day < size
            ):
                modified_time, modified_result = time_solver(
                    lambda: smt(distances, required_orders)
                )
                smt_modified_times_by_size[size].append(modified_time)
                modified_cost, modified_path = modified_result
                if modified_cost == -1:
                    raise AssertionError("modified smt() unexpectedly returned unsat")
                if tour_cost(distances, modified_path) != modified_cost:
                    raise AssertionError(
                        "modified smt() returned a tour whose cost does not match"
                    )
                if modified_path[args.required_day] != args.required_city:
                    raise AssertionError(
                        "modified smt() did not honor the required city/day constraint"
                    )

            if args.dp:
                dp_time, dp_result = time_solver(lambda: dp(distances))
                dp_times_by_size[size].append(dp_time)
                if tour_cost(distances, dp_result[1]) != dp_result[0]:
                    raise AssertionError("dp() returned a tour whose cost does not match")

            if smt_result is not None and dp_result is not None and smt_result[0] != dp_result[0]:
                raise AssertionError(
                    f"smt() and dp() disagree for size={size}, iteration={iteration}"
                )

    print_summary("SMT", smt_times_by_size)
    print_summary("Modified SMT", smt_modified_times_by_size)
    print_summary("DP", dp_times_by_size)

    if args.no_plot:
        return

    smt_sizes = [size for size, times in smt_times_by_size.items() if times]
    smt_medians = [statistics.median(smt_times_by_size[size]) for size in smt_sizes]

    modified_sizes = [size for size, times in smt_modified_times_by_size.items() if times]
    modified_medians = [
        statistics.median(smt_modified_times_by_size[size]) for size in modified_sizes
    ]

    dp_sizes = [size for size, times in dp_times_by_size.items() if times]
    dp_medians = [statistics.median(dp_times_by_size[size]) for size in dp_sizes]

    if dp_sizes:
        plt.scatter(dp_sizes, dp_medians, label="dp")
    if smt_sizes:
        plt.scatter(smt_sizes, smt_medians, label="smt")
    if modified_sizes:
        plt.scatter(modified_sizes, modified_medians, label="smt_modified")

    plt.xlabel("Cities")
    plt.ylabel("Median time (seconds)")
    plt.legend()
    plt.show()


if __name__ == "__main__":
    main()
