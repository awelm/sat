from __future__ import annotations

import argparse
import csv
import json
import random
import signal
import statistics
import time
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from dp import dp
from smt import SmtStats, smt


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


class SolverTimedOut(Exception):
    def __init__(self, elapsed_seconds: float) -> None:
        super().__init__("solver exceeded its wall-clock timeout")
        self.elapsed_seconds = elapsed_seconds


def time_solver(
    fn: Callable[[], Tuple[int, List[int]]],
    timeout_seconds: Optional[float] = None,
) -> Tuple[float, Tuple[int, List[int]]]:
    start = time.perf_counter()
    if timeout_seconds is None or timeout_seconds <= 0:
        result = fn()
        return time.perf_counter() - start, result

    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)

    def timeout_handler(_signum, _frame) -> None:
        raise SolverTimedOut(time.perf_counter() - start)

    signal.signal(signal.SIGALRM, timeout_handler)
    signal.setitimer(signal.ITIMER_REAL, timeout_seconds)
    try:
        result = fn()
        return time.perf_counter() - start, result
    finally:
        signal.setitimer(signal.ITIMER_REAL, *previous_timer)
        signal.signal(signal.SIGALRM, previous_handler)


def tour_cost(distances: List[List[int]], path: List[int]) -> int:
    return sum(distances[path[i]][path[i + 1]] for i in range(len(path) - 1))


def assert_valid_tour(path: List[int], size: int, solver: str) -> None:
    if len(path) != size + 1:
        raise AssertionError(f"{solver} returned a path with the wrong length")
    if path[0] != 0 or path[-1] != 0:
        raise AssertionError(f"{solver} returned a path that does not start/end at 0")
    if set(path[:-1]) != set(range(size)):
        raise AssertionError(f"{solver} returned a path that does not visit every city")


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


def print_failures(label: str, failures_by_size: Dict[int, int]) -> None:
    failures = [
        (size, count)
        for size, count in failures_by_size.items()
        if count
    ]
    if failures:
        print(f"{label} failures:", failures)


def parse_list(value: str) -> List[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def build_instance_seed(seed: int, size: int, iteration: int) -> int:
    return seed + size * 1_000_003 + iteration


def remaining_budget_seconds(
    elapsed_by_solver: Dict[str, float],
    solver_name: str,
    global_timeout_seconds: float,
) -> Optional[float]:
    if global_timeout_seconds <= 0:
        return None
    return max(0.0, global_timeout_seconds - elapsed_by_solver.get(solver_name, 0.0))


def solver_budget_exhausted(
    elapsed_by_solver: Dict[str, float],
    solver_name: str,
    global_timeout_seconds: float,
) -> bool:
    remaining = remaining_budget_seconds(
        elapsed_by_solver,
        solver_name,
        global_timeout_seconds,
    )
    return remaining is not None and remaining <= 0


def smt_timeout_ms_for_attempt(
    configured_timeout_ms: int,
    remaining_seconds: Optional[float],
) -> int:
    if remaining_seconds is None:
        return configured_timeout_ms
    remaining_ms = max(1, int(remaining_seconds * 1000))
    if configured_timeout_ms <= 0:
        return remaining_ms
    return min(configured_timeout_ms, remaining_ms)


def write_csv(path: Path, rows: Iterable[Dict[str, object]]) -> None:
    fieldnames = [
        "solver",
        "size",
        "iteration",
        "instance_seed",
        "symmetric",
        "status",
        "time_seconds",
        "cost",
        "check_count",
        "subtour_cut_count",
        "subtour_iterations",
        "strategy",
        "uses_order_constraints",
        "objective",
        "path",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


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
    parser.add_argument("--global-timeout-seconds", type=float, default=0)
    parser.add_argument("--smt-objectives", default="auto")
    parser.add_argument("--smt-strategies", default="lazy")
    parser.add_argument("--smt-timeout-ms", type=int, default=0)
    parser.add_argument("--allow-smt-failures", action="store_true")
    parser.add_argument(
        "--smt-modified",
        dest="smt_modified",
        action="store_true",
        default=False,
    )
    parser.add_argument("--csv", type=Path, default=None)
    parser.add_argument("--no-plot", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    smt_objectives = parse_list(args.smt_objectives)
    smt_strategies = parse_list(args.smt_strategies)
    smt_labels = [
        f"{strategy}:{objective}"
        for strategy in smt_strategies
        for objective in smt_objectives
    ]
    smt_times_by_label: Dict[str, Dict[int, List[float]]] = {
        label: {} for label in smt_labels
    }
    smt_failures_by_label: Dict[str, Dict[int, int]] = {
        label: {} for label in smt_labels
    }
    dp_times_by_size: Dict[int, List[float]] = {}
    smt_modified_times_by_label: Dict[str, Dict[int, List[float]]] = {
        label: {} for label in smt_labels
    }
    smt_modified_failures_by_label: Dict[str, Dict[int, int]] = {
        label: {} for label in smt_labels
    }
    elapsed_by_solver: Dict[str, float] = {}
    csv_rows: List[Dict[str, object]] = []

    required_orders = {args.required_city: args.required_day}

    for size in range(args.min_size, args.max_size + 1):
        for times_by_size in smt_times_by_label.values():
            times_by_size[size] = []
        for failures_by_size in smt_failures_by_label.values():
            failures_by_size[size] = 0
        dp_times_by_size[size] = []
        for times_by_size in smt_modified_times_by_label.values():
            times_by_size[size] = []
        for failures_by_size in smt_modified_failures_by_label.values():
            failures_by_size[size] = 0

        for iteration in range(args.iterations):
            instance_seed = build_instance_seed(args.seed, size, iteration)
            distances = build_distances(
                size,
                random.Random(instance_seed),
                symmetric=args.symmetric,
            )
            if args.verbose:
                print(
                    f"size={size} iteration={iteration} "
                    f"instance_seed={instance_seed} distances={distances}"
                )

            smt_results_by_label: Dict[str, Tuple[int, List[int]]] = {}
            dp_result: Tuple[int, List[int]] | None = None

            if args.smt:
                for strategy in smt_strategies:
                    for objective in smt_objectives:
                        label = f"{strategy}:{objective}"
                        solver_name = f"smt:{label}"
                        remaining_seconds = remaining_budget_seconds(
                            elapsed_by_solver,
                            solver_name,
                            args.global_timeout_seconds,
                        )
                        if remaining_seconds is not None and remaining_seconds <= 0:
                            smt_failures_by_label[label][size] += 1
                            csv_rows.append(
                                {
                                    "solver": solver_name,
                                    "size": size,
                                    "iteration": iteration,
                                    "instance_seed": instance_seed,
                                    "symmetric": args.symmetric,
                                    "status": "global_timeout",
                                    "time_seconds": "",
                                    "cost": "",
                                    "check_count": "",
                                    "subtour_cut_count": "",
                                    "subtour_iterations": "",
                                    "strategy": strategy,
                                    "uses_order_constraints": "",
                                    "objective": objective,
                                    "path": "",
                                }
                            )
                            continue
                        stats = SmtStats()
                        try:
                            smt_time, smt_result = time_solver(
                                lambda: smt(
                                    distances,
                                    objective=objective,
                                    strategy=strategy,
                                    stats=stats,
                                    timeout_ms=smt_timeout_ms_for_attempt(
                                        args.smt_timeout_ms,
                                        remaining_seconds,
                                    ),
                                ),
                                timeout_seconds=remaining_seconds,
                            )
                            elapsed_by_solver[solver_name] = (
                                elapsed_by_solver.get(solver_name, 0.0) + smt_time
                            )
                        except SolverTimedOut as error:
                            smt_failures_by_label[label][size] += 1
                            elapsed_by_solver[solver_name] = args.global_timeout_seconds
                            csv_rows.append(
                                {
                                    "solver": solver_name,
                                    "size": size,
                                    "iteration": iteration,
                                    "instance_seed": instance_seed,
                                    "symmetric": args.symmetric,
                                    "status": "global_timeout",
                                    "time_seconds": error.elapsed_seconds,
                                    "cost": "",
                                    "check_count": stats.check_count,
                                    "subtour_cut_count": stats.subtour_cut_count,
                                    "subtour_iterations": json.dumps(
                                        stats.subtour_iterations
                                    ),
                                    "strategy": stats.strategy or strategy,
                                    "uses_order_constraints": stats.uses_order_constraints,
                                    "objective": stats.resolved_objective or objective,
                                    "path": "",
                                }
                            )
                            continue
                        smt_cost, smt_path = smt_result
                        if smt_cost == -1:
                            budget_exhausted = solver_budget_exhausted(
                                elapsed_by_solver,
                                solver_name,
                                args.global_timeout_seconds,
                            )
                            if not args.allow_smt_failures and not budget_exhausted:
                                raise AssertionError(
                                    f"smt({label}) returned unsat/unknown"
                                )
                            status = "global_timeout" if budget_exhausted else "unsat_or_unknown"
                            if budget_exhausted:
                                elapsed_by_solver[solver_name] = args.global_timeout_seconds
                            smt_failures_by_label[label][size] += 1
                            csv_rows.append(
                                {
                                    "solver": f"smt:{label}",
                                    "size": size,
                                    "iteration": iteration,
                                    "instance_seed": instance_seed,
                                    "symmetric": args.symmetric,
                                    "status": status,
                                    "time_seconds": smt_time,
                                    "cost": "",
                                    "check_count": stats.check_count,
                                    "subtour_cut_count": stats.subtour_cut_count,
                                    "subtour_iterations": json.dumps(
                                        stats.subtour_iterations
                                    ),
                                    "strategy": stats.strategy,
                                    "uses_order_constraints": (
                                        stats.uses_order_constraints
                                    ),
                                    "objective": stats.resolved_objective,
                                    "path": "",
                                }
                            )
                            continue
                        smt_times_by_label[label][size].append(smt_time)
                        smt_results_by_label[label] = smt_result
                        assert_valid_tour(smt_path, size, f"smt({label})")
                        if tour_cost(distances, smt_path) != smt_cost:
                            raise AssertionError(
                                f"smt({label}) returned a tour whose cost does not match"
                            )
                        csv_rows.append(
                            {
                                "solver": f"smt:{label}",
                                "size": size,
                                "iteration": iteration,
                                "instance_seed": instance_seed,
                                "symmetric": args.symmetric,
                                "status": "ok",
                                "time_seconds": smt_time,
                                "cost": smt_cost,
                                "check_count": stats.check_count,
                                "subtour_cut_count": stats.subtour_cut_count,
                                "subtour_iterations": json.dumps(stats.subtour_iterations),
                                "strategy": stats.strategy,
                                "uses_order_constraints": stats.uses_order_constraints,
                                "objective": stats.resolved_objective,
                                "path": json.dumps(smt_path),
                            }
                        )

            if (
                args.smt_modified
                and args.required_city < size
                and args.required_day < size
            ):
                for strategy in smt_strategies:
                    for objective in smt_objectives:
                        label = f"{strategy}:{objective}"
                        solver_name = f"smt-modified:{label}"
                        remaining_seconds = remaining_budget_seconds(
                            elapsed_by_solver,
                            solver_name,
                            args.global_timeout_seconds,
                        )
                        if remaining_seconds is not None and remaining_seconds <= 0:
                            smt_modified_failures_by_label[label][size] += 1
                            csv_rows.append(
                                {
                                    "solver": solver_name,
                                    "size": size,
                                    "iteration": iteration,
                                    "instance_seed": instance_seed,
                                    "symmetric": args.symmetric,
                                    "status": "global_timeout",
                                    "time_seconds": "",
                                    "cost": "",
                                    "check_count": "",
                                    "subtour_cut_count": "",
                                    "subtour_iterations": "",
                                    "strategy": strategy,
                                    "uses_order_constraints": "",
                                    "objective": objective,
                                    "path": "",
                                }
                            )
                            continue
                        stats = SmtStats()
                        try:
                            modified_time, modified_result = time_solver(
                                lambda: smt(
                                    distances,
                                    required_orders,
                                    objective=objective,
                                    strategy=strategy,
                                    stats=stats,
                                    timeout_ms=smt_timeout_ms_for_attempt(
                                        args.smt_timeout_ms,
                                        remaining_seconds,
                                    ),
                                ),
                                timeout_seconds=remaining_seconds,
                            )
                            elapsed_by_solver[solver_name] = (
                                elapsed_by_solver.get(solver_name, 0.0) + modified_time
                            )
                        except SolverTimedOut as error:
                            smt_modified_failures_by_label[label][size] += 1
                            elapsed_by_solver[solver_name] = args.global_timeout_seconds
                            csv_rows.append(
                                {
                                    "solver": solver_name,
                                    "size": size,
                                    "iteration": iteration,
                                    "instance_seed": instance_seed,
                                    "symmetric": args.symmetric,
                                    "status": "global_timeout",
                                    "time_seconds": error.elapsed_seconds,
                                    "cost": "",
                                    "check_count": stats.check_count,
                                    "subtour_cut_count": stats.subtour_cut_count,
                                    "subtour_iterations": json.dumps(
                                        stats.subtour_iterations
                                    ),
                                    "strategy": stats.strategy or strategy,
                                    "uses_order_constraints": stats.uses_order_constraints,
                                    "objective": stats.resolved_objective or objective,
                                    "path": "",
                                }
                            )
                            continue
                        modified_cost, modified_path = modified_result
                        if modified_cost == -1:
                            budget_exhausted = solver_budget_exhausted(
                                elapsed_by_solver,
                                solver_name,
                                args.global_timeout_seconds,
                            )
                            if not args.allow_smt_failures and not budget_exhausted:
                                raise AssertionError(
                                    f"modified smt({label}) unexpectedly returned unsat/unknown"
                                )
                            status = "global_timeout" if budget_exhausted else "unsat_or_unknown"
                            if budget_exhausted:
                                elapsed_by_solver[solver_name] = args.global_timeout_seconds
                            smt_modified_failures_by_label[label][size] += 1
                            csv_rows.append(
                                {
                                    "solver": f"smt-modified:{label}",
                                    "size": size,
                                    "iteration": iteration,
                                    "instance_seed": instance_seed,
                                    "symmetric": args.symmetric,
                                    "status": status,
                                    "time_seconds": modified_time,
                                    "cost": "",
                                    "check_count": stats.check_count,
                                    "subtour_cut_count": stats.subtour_cut_count,
                                    "subtour_iterations": json.dumps(
                                        stats.subtour_iterations
                                    ),
                                    "strategy": stats.strategy,
                                    "uses_order_constraints": (
                                        stats.uses_order_constraints
                                    ),
                                    "objective": stats.resolved_objective,
                                    "path": "",
                                }
                            )
                            continue
                        smt_modified_times_by_label[label][size].append(modified_time)
                        assert_valid_tour(
                            modified_path,
                            size,
                            f"modified smt({label})",
                        )
                        if tour_cost(distances, modified_path) != modified_cost:
                            raise AssertionError(
                                f"modified smt({label}) returned a tour whose cost does not match"
                            )
                        if modified_path[args.required_day] != args.required_city:
                            raise AssertionError(
                                f"modified smt({label}) did not honor the required city/day constraint"
                            )
                        csv_rows.append(
                            {
                                "solver": f"smt-modified:{label}",
                                "size": size,
                                "iteration": iteration,
                                "instance_seed": instance_seed,
                                "symmetric": args.symmetric,
                                "status": "ok",
                                "time_seconds": modified_time,
                                "cost": modified_cost,
                                "check_count": stats.check_count,
                                "subtour_cut_count": stats.subtour_cut_count,
                                "subtour_iterations": json.dumps(stats.subtour_iterations),
                                "strategy": stats.strategy,
                                "uses_order_constraints": stats.uses_order_constraints,
                                "objective": stats.resolved_objective,
                                "path": json.dumps(modified_path),
                            }
                        )

            if args.dp:
                if solver_budget_exhausted(
                    elapsed_by_solver,
                    "dp",
                    args.global_timeout_seconds,
                ):
                    csv_rows.append(
                        {
                            "solver": "dp",
                            "size": size,
                            "iteration": iteration,
                            "instance_seed": instance_seed,
                            "symmetric": args.symmetric,
                            "status": "global_timeout",
                            "time_seconds": "",
                            "cost": "",
                            "check_count": "",
                            "subtour_cut_count": "",
                            "subtour_iterations": "",
                            "strategy": "",
                            "uses_order_constraints": "",
                            "objective": "",
                            "path": "",
                        }
                    )
                    continue
                remaining_seconds = remaining_budget_seconds(
                    elapsed_by_solver,
                    "dp",
                    args.global_timeout_seconds,
                )
                try:
                    dp_time, dp_result = time_solver(
                        lambda: dp(distances),
                        timeout_seconds=remaining_seconds,
                    )
                    elapsed_by_solver["dp"] = elapsed_by_solver.get("dp", 0.0) + dp_time
                except SolverTimedOut as error:
                    elapsed_by_solver["dp"] = args.global_timeout_seconds
                    csv_rows.append(
                        {
                            "solver": "dp",
                            "size": size,
                            "iteration": iteration,
                            "instance_seed": instance_seed,
                            "symmetric": args.symmetric,
                            "status": "global_timeout",
                            "time_seconds": error.elapsed_seconds,
                            "cost": "",
                            "check_count": "",
                            "subtour_cut_count": "",
                            "subtour_iterations": "",
                            "strategy": "",
                            "uses_order_constraints": "",
                            "objective": "",
                            "path": "",
                        }
                    )
                    continue
                dp_times_by_size[size].append(dp_time)
                assert_valid_tour(dp_result[1], size, "dp()")
                if tour_cost(distances, dp_result[1]) != dp_result[0]:
                    raise AssertionError("dp() returned a tour whose cost does not match")
                csv_rows.append(
                    {
                        "solver": "dp",
                        "size": size,
                        "iteration": iteration,
                        "instance_seed": instance_seed,
                        "symmetric": args.symmetric,
                        "status": "ok",
                        "time_seconds": dp_time,
                        "cost": dp_result[0],
                        "check_count": "",
                        "subtour_cut_count": "",
                        "subtour_iterations": "",
                        "strategy": "",
                        "uses_order_constraints": "",
                        "objective": "",
                        "path": json.dumps(dp_result[1]),
                    }
                )

            if dp_result is not None:
                for label, smt_result in smt_results_by_label.items():
                    if smt_result[0] != dp_result[0]:
                        raise AssertionError(
                            f"smt({label}) and dp() disagree for "
                            f"size={size}, iteration={iteration}"
                        )

    for label, times_by_size in smt_times_by_label.items():
        print_summary(f"SMT {label}", times_by_size)
        print_failures(f"SMT {label}", smt_failures_by_label[label])
    for label, times_by_size in smt_modified_times_by_label.items():
        print_summary(f"Modified SMT {label}", times_by_size)
        print_failures(
            f"Modified SMT {label}",
            smt_modified_failures_by_label[label],
        )
    print_summary("DP", dp_times_by_size)

    if args.csv is not None:
        write_csv(args.csv, csv_rows)

    if args.no_plot:
        return

    import matplotlib.pyplot as plt

    for label, times_by_size in smt_times_by_label.items():
        smt_sizes = [size for size, times in times_by_size.items() if times]
        smt_medians = [statistics.median(times_by_size[size]) for size in smt_sizes]
        if smt_sizes:
            plt.scatter(smt_sizes, smt_medians, label=f"smt:{label}")

    for label, times_by_size in smt_modified_times_by_label.items():
        modified_sizes = [size for size, times in times_by_size.items() if times]
        modified_medians = [
            statistics.median(times_by_size[size]) for size in modified_sizes
        ]
        if modified_sizes:
            plt.scatter(
                modified_sizes,
                modified_medians,
                label=f"smt-modified:{label}",
            )

    dp_sizes = [size for size, times in dp_times_by_size.items() if times]
    dp_medians = [statistics.median(dp_times_by_size[size]) for size in dp_sizes]

    if dp_sizes:
        plt.scatter(dp_sizes, dp_medians, label="dp")

    plt.xlabel("Cities")
    plt.ylabel("Median time (seconds)")
    plt.legend()
    plt.show()


if __name__ == "__main__":
    main()
