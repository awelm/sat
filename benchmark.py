from __future__ import annotations

import argparse
import csv
import json
import multiprocessing
import random
import signal
import statistics
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from queue import Empty
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

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


TIMEOUT_STATUSES = {"timeout", "problem_timeout", "global_timeout"}


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


def attempt_timeout_seconds(
    remaining_seconds: Optional[float],
    problem_timeout_seconds: float,
) -> Optional[float]:
    if problem_timeout_seconds <= 0:
        return remaining_seconds
    if remaining_seconds is None:
        return problem_timeout_seconds
    return min(remaining_seconds, problem_timeout_seconds)


def timeout_status_for_attempt(
    remaining_seconds: Optional[float],
    effective_timeout_seconds: Optional[float],
    problem_timeout_seconds: float,
) -> str:
    if effective_timeout_seconds is None:
        return "timeout"
    if (
        remaining_seconds is not None
        and abs(effective_timeout_seconds - remaining_seconds) <= 1e-6
        and (
            problem_timeout_seconds <= 0
            or remaining_seconds <= problem_timeout_seconds + 1e-6
        )
    ):
        return "global_timeout"
    if problem_timeout_seconds > 0:
        return "problem_timeout"
    return "timeout"


def failure_status_for_solver_return(
    elapsed_by_solver: Dict[str, float],
    solver_name: str,
    global_timeout_seconds: float,
    remaining_seconds: Optional[float],
    effective_timeout_seconds: Optional[float],
    problem_timeout_seconds: float,
    elapsed_seconds: float,
) -> str:
    if solver_budget_exhausted(
        elapsed_by_solver,
        solver_name,
        global_timeout_seconds,
    ):
        return "global_timeout"
    if (
        effective_timeout_seconds is not None
        and elapsed_seconds >= effective_timeout_seconds * 0.95
    ):
        return timeout_status_for_attempt(
            remaining_seconds,
            effective_timeout_seconds,
            problem_timeout_seconds,
        )
    return "unsat_or_unknown"


def smt_timeout_ms_for_attempt(
    configured_timeout_ms: int,
    effective_timeout_seconds: Optional[float],
) -> int:
    if effective_timeout_seconds is None:
        return configured_timeout_ms
    remaining_ms = max(1, int(effective_timeout_seconds * 1000))
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


def empty_row(
    solver: str,
    size: int,
    iteration: int,
    instance_seed: int,
    symmetric: bool,
    status: str,
    strategy: str = "",
    objective: str = "",
) -> Dict[str, object]:
    return {
        "solver": solver,
        "size": size,
        "iteration": iteration,
        "instance_seed": instance_seed,
        "symmetric": symmetric,
        "status": status,
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


def smt_attempt_row(
    size: int,
    iteration: int,
    instance_seed: int,
    symmetric: bool,
    strategy: str,
    objective: str,
    required_orders: Optional[Dict[int, int]],
    problem_timeout_seconds: float,
    smt_timeout_ms: int,
    allow_smt_failures: bool,
    modified: bool,
) -> Dict[str, object]:
    distances = build_distances(size, random.Random(instance_seed), symmetric=symmetric)
    stats = SmtStats()
    solver_prefix = "smt-modified" if modified else "smt"
    solver_name = f"{solver_prefix}:{strategy}:{objective}"
    effective_timeout_seconds = attempt_timeout_seconds(None, problem_timeout_seconds)

    try:
        elapsed_seconds, result = time_solver(
            lambda: smt(
                distances,
                required_orders,
                objective=objective,
                strategy=strategy,
                stats=stats,
                timeout_ms=smt_timeout_ms_for_attempt(
                    smt_timeout_ms,
                    effective_timeout_seconds,
                ),
            ),
            timeout_seconds=effective_timeout_seconds,
        )
    except SolverTimedOut as error:
        return {
            **empty_row(
                solver_name,
                size,
                iteration,
                instance_seed,
                symmetric,
                timeout_status_for_attempt(
                    None,
                    effective_timeout_seconds,
                    problem_timeout_seconds,
                ),
            ),
            "time_seconds": error.elapsed_seconds,
            "check_count": stats.check_count,
            "subtour_cut_count": stats.subtour_cut_count,
            "subtour_iterations": json.dumps(stats.subtour_iterations),
            "strategy": stats.strategy or strategy,
            "uses_order_constraints": stats.uses_order_constraints,
            "objective": stats.resolved_objective or objective,
        }

    cost, path = result
    if cost == -1:
        status = (
            timeout_status_for_attempt(
                None,
                effective_timeout_seconds,
                problem_timeout_seconds,
            )
            if effective_timeout_seconds is not None
            and elapsed_seconds >= effective_timeout_seconds * 0.95
            else "unsat_or_unknown"
        )
        if not allow_smt_failures and status == "unsat_or_unknown":
            raise AssertionError(f"{solver_name} returned unsat/unknown")
        return {
            **empty_row(
                solver_name,
                size,
                iteration,
                instance_seed,
                symmetric,
                status,
            ),
            "time_seconds": elapsed_seconds,
            "check_count": stats.check_count,
            "subtour_cut_count": stats.subtour_cut_count,
            "subtour_iterations": json.dumps(stats.subtour_iterations),
            "strategy": stats.strategy,
            "uses_order_constraints": stats.uses_order_constraints,
            "objective": stats.resolved_objective,
        }

    assert_valid_tour(path, size, solver_name)
    if tour_cost(distances, path) != cost:
        raise AssertionError(f"{solver_name} returned a tour whose cost does not match")
    if modified and required_orders:
        for city, day in required_orders.items():
            if path[day] != city:
                raise AssertionError(f"{solver_name} did not honor the required city/day constraint")

    return {
        "solver": solver_name,
        "size": size,
        "iteration": iteration,
        "instance_seed": instance_seed,
        "symmetric": symmetric,
        "status": "ok",
        "time_seconds": elapsed_seconds,
        "cost": cost,
        "check_count": stats.check_count,
        "subtour_cut_count": stats.subtour_cut_count,
        "subtour_iterations": json.dumps(stats.subtour_iterations),
        "strategy": stats.strategy,
        "uses_order_constraints": stats.uses_order_constraints,
        "objective": stats.resolved_objective,
        "path": json.dumps(path),
    }


def dp_attempt_row(
    size: int,
    iteration: int,
    instance_seed: int,
    symmetric: bool,
    problem_timeout_seconds: float,
) -> Dict[str, object]:
    distances = build_distances(size, random.Random(instance_seed), symmetric)
    effective_timeout_seconds = attempt_timeout_seconds(None, problem_timeout_seconds)
    try:
        elapsed_seconds, result = time_solver(
            lambda: dp(distances),
            timeout_seconds=effective_timeout_seconds,
        )
    except SolverTimedOut as error:
        return {
            **empty_row(
                "dp",
                size,
                iteration,
                instance_seed,
                symmetric,
                timeout_status_for_attempt(
                    None,
                    effective_timeout_seconds,
                    problem_timeout_seconds,
                ),
            ),
            "time_seconds": error.elapsed_seconds,
        }

    cost, path = result
    assert_valid_tour(path, size, "dp()")
    if tour_cost(distances, path) != cost:
        raise AssertionError("dp() returned a tour whose cost does not match")
    return {
        "solver": "dp",
        "size": size,
        "iteration": iteration,
        "instance_seed": instance_seed,
        "symmetric": symmetric,
        "status": "ok",
        "time_seconds": elapsed_seconds,
        "cost": cost,
        "check_count": "",
        "subtour_cut_count": "",
        "subtour_iterations": "",
        "strategy": "",
        "uses_order_constraints": "",
        "objective": "",
        "path": json.dumps(path),
    }


def dp_attempt_process(
    result_queue: multiprocessing.Queue,
    size: int,
    iteration: int,
    instance_seed: int,
    symmetric: bool,
    problem_timeout_seconds: float,
) -> None:
    try:
        result_queue.put(
            (
                "row",
                dp_attempt_row(
                    size,
                    iteration,
                    instance_seed,
                    symmetric,
                    problem_timeout_seconds,
                ),
            )
        )
    except BaseException:
        result_queue.put(("error", traceback.format_exc()))


def terminate_process(process: multiprocessing.Process) -> None:
    if process.is_alive():
        process.terminate()
        process.join(timeout=1)
    if process.is_alive():
        process.kill()
    process.join()


def close_queue(queue: multiprocessing.Queue) -> None:
    queue.close()
    queue.join_thread()


def dp_problem_timeout_row(
    size: int,
    iteration: int,
    instance_seed: int,
    symmetric: bool,
    elapsed_seconds: float,
    problem_timeout_seconds: float,
) -> Dict[str, object]:
    effective_timeout_seconds = attempt_timeout_seconds(None, problem_timeout_seconds)
    return {
        **empty_row(
            "dp",
            size,
            iteration,
            instance_seed,
            symmetric,
            timeout_status_for_attempt(
                None,
                effective_timeout_seconds,
                problem_timeout_seconds,
            ),
        ),
        "time_seconds": elapsed_seconds,
    }


def dp_skipped_after_timeout_row(
    size: int,
    iteration: int,
    instance_seed: int,
    symmetric: bool,
) -> Dict[str, object]:
    return empty_row(
        "dp",
        size,
        iteration,
        instance_seed,
        symmetric,
        "skipped_after_timeout",
    )


def cleanup_dp_attempts(active_attempts: Iterable[Dict[str, object]]) -> None:
    for attempt in list(active_attempts):
        process = attempt["process"]
        terminate_process(process)
        result_queue = attempt["queue"]
        close_queue(result_queue)


def read_dp_attempt_result(
    result_queue: multiprocessing.Queue,
    process: multiprocessing.Process,
    size: int,
    iteration: int,
) -> Dict[str, object]:
    if process.exitcode not in (0, None):
        raise RuntimeError(
            f"dp worker exited unexpectedly for size={size} iteration={iteration} "
            f"with exit code {process.exitcode}"
        )
    try:
        kind, payload = result_queue.get_nowait()
    except Empty as error:
        raise RuntimeError(
            f"dp worker produced no result for size={size} iteration={iteration}"
        ) from error
    if kind == "error":
        raise RuntimeError(
            f"dp worker failed for size={size} iteration={iteration}\n{payload}"
        )
    if kind != "row":
        raise RuntimeError(f"dp worker produced an unknown result kind: {kind}")
    return payload


def benchmark_instances(args: argparse.Namespace) -> List[Tuple[int, int, int]]:
    return [
        (size, iteration, build_instance_seed(args.seed, size, iteration))
        for size in range(args.min_size, args.max_size + 1)
        for iteration in range(args.iterations)
    ]


def run_dp_rows_until_timeout(
    args: argparse.Namespace,
    instances: Sequence[Tuple[int, int, int]],
) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    stopped_after_timeout = False
    for size, iteration, instance_seed in instances:
        if stopped_after_timeout:
            rows.append(
                empty_row(
                    "dp",
                    size,
                    iteration,
                    instance_seed,
                    args.symmetric,
                    "skipped_after_timeout",
                )
            )
            continue
        if args.dp_max_size > 0 and size > args.dp_max_size:
            rows.append(
                empty_row(
                    "dp",
                    size,
                    iteration,
                    instance_seed,
                    args.symmetric,
                    "skipped_dp_max_size",
                )
            )
            continue

        distances = build_distances(size, random.Random(instance_seed), args.symmetric)
        effective_timeout_seconds = attempt_timeout_seconds(
            None,
            args.problem_timeout_seconds,
        )
        try:
            elapsed_seconds, result = time_solver(
                lambda: dp(distances),
                timeout_seconds=effective_timeout_seconds,
            )
        except SolverTimedOut as error:
            if args.stop_dp_after_timeout:
                stopped_after_timeout = True
            rows.append(
                {
                    **empty_row(
                        "dp",
                        size,
                        iteration,
                        instance_seed,
                        args.symmetric,
                        timeout_status_for_attempt(
                            None,
                            effective_timeout_seconds,
                            args.problem_timeout_seconds,
                        ),
                    ),
                    "time_seconds": error.elapsed_seconds,
                }
            )
            continue

        cost, path = result
        assert_valid_tour(path, size, "dp()")
        if tour_cost(distances, path) != cost:
            raise AssertionError("dp() returned a tour whose cost does not match")
        rows.append(
            {
                "solver": "dp",
                "size": size,
                "iteration": iteration,
                "instance_seed": instance_seed,
                "symmetric": args.symmetric,
                "status": "ok",
                "time_seconds": elapsed_seconds,
                "cost": cost,
                "check_count": "",
                "subtour_cut_count": "",
                "subtour_iterations": "",
                "strategy": "",
                "uses_order_constraints": "",
                "objective": "",
                "path": json.dumps(path),
            }
        )
    return rows


def run_dp_rows_parallel_until_timeout(
    args: argparse.Namespace,
    instances: Sequence[Tuple[int, int, int]],
) -> List[Dict[str, object]]:
    if args.dp_workers <= 1:
        return run_dp_rows_until_timeout(args, instances)

    rows: List[Dict[str, object]] = []
    instances_by_size: Dict[int, List[Tuple[int, int, int]]] = {}
    for size, iteration, instance_seed in instances:
        instances_by_size.setdefault(size, []).append((size, iteration, instance_seed))

    stopped_after_timeout = False
    for size in sorted(instances_by_size):
        size_instances = instances_by_size[size]
        if stopped_after_timeout:
            for _, iteration, instance_seed in size_instances:
                rows.append(
                    empty_row(
                        "dp",
                        size,
                        iteration,
                        instance_seed,
                        args.symmetric,
                        "skipped_after_timeout",
                    )
                )
            continue

        if args.dp_max_size > 0 and size > args.dp_max_size:
            for _, iteration, instance_seed in size_instances:
                rows.append(
                    empty_row(
                        "dp",
                        size,
                        iteration,
                        instance_seed,
                        args.symmetric,
                        "skipped_dp_max_size",
                    )
                )
            continue

        context = multiprocessing.get_context("spawn")
        active_attempts: List[Dict[str, object]] = []
        next_instance_index = 0

        def submit_next_instance() -> bool:
            nonlocal next_instance_index
            if next_instance_index >= len(size_instances):
                return False
            size, iteration, instance_seed = size_instances[next_instance_index]
            next_instance_index += 1
            result_queue = context.Queue(maxsize=1)
            process = context.Process(
                target=dp_attempt_process,
                args=(
                    result_queue,
                    size,
                    iteration,
                    instance_seed,
                    args.symmetric,
                    args.problem_timeout_seconds,
                ),
            )
            process.start()
            active_attempts.append(
                {
                    "process": process,
                    "queue": result_queue,
                    "size": size,
                    "iteration": iteration,
                    "instance_seed": instance_seed,
                    "started_at": time.perf_counter(),
                }
            )
            return True

        for _ in range(min(args.dp_workers, len(size_instances))):
            submit_next_instance()

        stop_this_size = False
        try:
            while active_attempts:
                now = time.perf_counter()
                timed_out_attempt = None
                if args.problem_timeout_seconds > 0:
                    for attempt in active_attempts:
                        elapsed_seconds = now - float(attempt["started_at"])
                        if elapsed_seconds >= args.problem_timeout_seconds:
                            timed_out_attempt = attempt
                            break

                if timed_out_attempt is not None:
                    active_attempts.remove(timed_out_attempt)
                    process = timed_out_attempt["process"]
                    terminate_process(process)
                    result_queue = timed_out_attempt["queue"]
                    close_queue(result_queue)
                    rows.append(
                        dp_problem_timeout_row(
                            int(timed_out_attempt["size"]),
                            int(timed_out_attempt["iteration"]),
                            int(timed_out_attempt["instance_seed"]),
                            args.symmetric,
                            now - float(timed_out_attempt["started_at"]),
                            args.problem_timeout_seconds,
                        )
                    )
                    if args.stop_dp_after_timeout:
                        stopped_after_timeout = True
                        stop_this_size = True
                        for attempt in active_attempts:
                            process = attempt["process"]
                            terminate_process(process)
                            result_queue = attempt["queue"]
                            close_queue(result_queue)
                            rows.append(
                                dp_skipped_after_timeout_row(
                                    int(attempt["size"]),
                                    int(attempt["iteration"]),
                                    int(attempt["instance_seed"]),
                                    args.symmetric,
                                )
                            )
                        active_attempts.clear()
                        break
                    submit_next_instance()
                    continue

                completed_attempts = [
                    attempt
                    for attempt in active_attempts
                    if not attempt["process"].is_alive()
                ]
                if not completed_attempts:
                    time.sleep(0.05)
                    continue

                for attempt in completed_attempts:
                    if attempt not in active_attempts:
                        continue
                    active_attempts.remove(attempt)
                    process = attempt["process"]
                    process.join()
                    result_queue = attempt["queue"]
                    try:
                        row = read_dp_attempt_result(
                            result_queue,
                            process,
                            int(attempt["size"]),
                            int(attempt["iteration"]),
                        )
                    finally:
                        close_queue(result_queue)
                    rows.append(row)
                    if args.stop_dp_after_timeout and str(row["status"]) in TIMEOUT_STATUSES:
                        stopped_after_timeout = True
                        stop_this_size = True
                        for other_attempt in active_attempts:
                            other_process = other_attempt["process"]
                            terminate_process(other_process)
                            other_queue = other_attempt["queue"]
                            close_queue(other_queue)
                            rows.append(
                                dp_skipped_after_timeout_row(
                                    int(other_attempt["size"]),
                                    int(other_attempt["iteration"]),
                                    int(other_attempt["instance_seed"]),
                                    args.symmetric,
                                )
                            )
                        active_attempts.clear()
                        break
                    submit_next_instance()

                if stop_this_size:
                    break
        except BaseException:
            cleanup_dp_attempts(active_attempts)
            active_attempts.clear()
            raise

        if not stop_this_size:
            continue

        for _, iteration, instance_seed in size_instances[next_instance_index:]:
            rows.append(
                dp_skipped_after_timeout_row(
                    size, iteration, instance_seed, args.symmetric
                )
            )

    return rows


def solver_sort_order(solver: str) -> Tuple[int, str]:
    if solver.startswith("smt:"):
        return 0, solver
    if solver.startswith("smt-modified:"):
        return 1, solver
    if solver == "dp":
        return 2, solver
    return 3, solver


def row_sort_key(row: Dict[str, object]) -> Tuple[int, int, Tuple[int, str]]:
    return (
        int(row["size"]),
        int(row["iteration"]),
        solver_sort_order(str(row["solver"])),
    )


def print_summaries_from_rows(
    rows: Iterable[Dict[str, object]],
    smt_labels: Sequence[str],
    include_modified: bool,
) -> None:
    rows_by_solver: Dict[str, List[Dict[str, object]]] = {}
    for row in rows:
        rows_by_solver.setdefault(str(row["solver"]), []).append(row)

    solver_names = [f"smt:{label}" for label in smt_labels]
    if include_modified:
        solver_names.extend(f"smt-modified:{label}" for label in smt_labels)
    solver_names.append("dp")

    for solver_name in solver_names:
        solver_rows = rows_by_solver.get(solver_name, [])
        times_by_size: Dict[int, List[float]] = {}
        failures_by_size: Dict[int, int] = {}
        for row in solver_rows:
            size = int(row["size"])
            times_by_size.setdefault(size, [])
            failures_by_size.setdefault(size, 0)
            if row["status"] == "ok" and row["time_seconds"] != "":
                times_by_size[size].append(float(row["time_seconds"]))
            elif row["status"] != "ok":
                failures_by_size[size] += 1
        label = solver_name
        if solver_name.startswith("smt:"):
            label = f"SMT {solver_name.removeprefix('smt:')}"
        elif solver_name.startswith("smt-modified:"):
            label = f"Modified SMT {solver_name.removeprefix('smt-modified:')}"
        elif solver_name == "dp":
            label = "DP"
        print_summary(label, times_by_size)
        print_failures(label, failures_by_size)


def validate_rows_against_dp(rows: Iterable[Dict[str, object]]) -> None:
    dp_cost_by_key = {
        (
            int(row["size"]),
            int(row["iteration"]),
            int(row["instance_seed"]),
            str(row["symmetric"]),
        ): int(row["cost"])
        for row in rows
        if row["solver"] == "dp" and row["status"] == "ok"
    }
    for row in rows:
        solver = str(row["solver"])
        if not solver.startswith("smt:") or row["status"] != "ok":
            continue
        key = (
            int(row["size"]),
            int(row["iteration"]),
            int(row["instance_seed"]),
            str(row["symmetric"]),
        )
        dp_cost = dp_cost_by_key.get(key)
        if dp_cost is not None and int(row["cost"]) != dp_cost:
            raise AssertionError(
                f"{solver} and dp() disagree for size={row['size']}, "
                f"iteration={row['iteration']}"
            )


def plot_rows(rows: Iterable[Dict[str, object]], smt_labels: Sequence[str]) -> None:
    import matplotlib.pyplot as plt

    rows_by_solver: Dict[str, List[Dict[str, object]]] = {}
    for row in rows:
        if row["status"] == "ok" and row["time_seconds"] != "":
            rows_by_solver.setdefault(str(row["solver"]), []).append(row)

    for solver_name in [f"smt:{label}" for label in smt_labels] + ["dp"]:
        times_by_size: Dict[int, List[float]] = {}
        for row in rows_by_solver.get(solver_name, []):
            times_by_size.setdefault(int(row["size"]), []).append(float(row["time_seconds"]))
        sizes = sorted(size for size, times in times_by_size.items() if times)
        medians = [statistics.median(times_by_size[size]) for size in sizes]
        if sizes:
            plt.scatter(sizes, medians, label=solver_name)

    plt.xlabel("Cities")
    plt.ylabel("Median time (seconds)")
    plt.legend()
    plt.show()


def run_parallel_benchmark(
    args: argparse.Namespace,
    smt_strategies: Sequence[str],
    smt_objectives: Sequence[str],
    smt_labels: Sequence[str],
) -> None:
    if args.global_timeout_seconds > 0:
        raise ValueError("parallel workers require --global-timeout-seconds 0")

    instances = benchmark_instances(args)
    required_orders = {args.required_city: args.required_day}
    rows: List[Dict[str, object]] = []

    if args.dp and not args.overlap_dp_with_smt:
        rows.extend(run_dp_rows_parallel_until_timeout(args, instances))

    with ProcessPoolExecutor(max_workers=args.smt_workers) as executor:
        futures = []
        if args.smt:
            for size, iteration, instance_seed in instances:
                for strategy in smt_strategies:
                    for objective in smt_objectives:
                        futures.append(
                            executor.submit(
                                smt_attempt_row,
                                size,
                                iteration,
                                instance_seed,
                                args.symmetric,
                                strategy,
                                objective,
                                None,
                                args.problem_timeout_seconds,
                                args.smt_timeout_ms,
                                args.allow_smt_failures,
                                False,
                            )
                        )
        if args.smt_modified:
            for size, iteration, instance_seed in instances:
                if args.required_city >= size or args.required_day >= size:
                    continue
                for strategy in smt_strategies:
                    for objective in smt_objectives:
                        futures.append(
                            executor.submit(
                                smt_attempt_row,
                                size,
                                iteration,
                                instance_seed,
                                args.symmetric,
                                strategy,
                                objective,
                                required_orders,
                                args.problem_timeout_seconds,
                                args.smt_timeout_ms,
                                args.allow_smt_failures,
                                True,
                            )
                        )

        if args.dp and args.overlap_dp_with_smt:
            rows.extend(run_dp_rows_parallel_until_timeout(args, instances))

        for future in as_completed(futures):
            rows.append(future.result())

    rows = sorted(rows, key=row_sort_key)
    validate_rows_against_dp(rows)
    print_summaries_from_rows(rows, smt_labels, args.smt_modified)
    if args.csv is not None:
        write_csv(args.csv, rows)
    if not args.no_plot:
        plot_rows(rows, smt_labels)


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
    parser.add_argument("--dp-max-size", type=int, default=0)
    parser.add_argument(
        "--stop-dp-after-timeout",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--global-timeout-seconds", type=float, default=0)
    parser.add_argument("--problem-timeout-seconds", type=float, default=0)
    parser.add_argument("--smt-objectives", default="auto")
    parser.add_argument("--smt-strategies", default="lazy")
    parser.add_argument("--smt-timeout-ms", type=int, default=0)
    parser.add_argument("--dp-workers", type=int, default=1)
    parser.add_argument("--smt-workers", type=int, default=1)
    parser.add_argument(
        "--overlap-dp-with-smt",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
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
    if args.dp_workers < 1:
        parser.error("--dp-workers must be at least 1")
    if args.smt_workers < 1:
        parser.error("--smt-workers must be at least 1")
    if (
        (args.dp_workers > 1 or args.smt_workers > 1)
        and args.global_timeout_seconds > 0
    ):
        parser.error("parallel workers require --global-timeout-seconds 0")

    smt_objectives = parse_list(args.smt_objectives)
    smt_strategies = parse_list(args.smt_strategies)
    smt_labels = [
        f"{strategy}:{objective}"
        for strategy in smt_strategies
        for objective in smt_objectives
    ]
    if args.dp_workers > 1 or args.smt_workers > 1:
        run_parallel_benchmark(args, smt_strategies, smt_objectives, smt_labels)
        return
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
    dp_stopped_after_timeout = False

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
                        effective_timeout_seconds = attempt_timeout_seconds(
                            remaining_seconds,
                            args.problem_timeout_seconds,
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
                                        effective_timeout_seconds,
                                    ),
                                ),
                                timeout_seconds=effective_timeout_seconds,
                            )
                            elapsed_by_solver[solver_name] = (
                                elapsed_by_solver.get(solver_name, 0.0) + smt_time
                            )
                        except SolverTimedOut as error:
                            smt_failures_by_label[label][size] += 1
                            status = timeout_status_for_attempt(
                                remaining_seconds,
                                effective_timeout_seconds,
                                args.problem_timeout_seconds,
                            )
                            if status == "global_timeout":
                                elapsed_by_solver[solver_name] = args.global_timeout_seconds
                            else:
                                elapsed_by_solver[solver_name] = (
                                    elapsed_by_solver.get(solver_name, 0.0)
                                    + error.elapsed_seconds
                                )
                            csv_rows.append(
                                {
                                    "solver": solver_name,
                                    "size": size,
                                    "iteration": iteration,
                                    "instance_seed": instance_seed,
                                    "symmetric": args.symmetric,
                                    "status": status,
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
                            status = failure_status_for_solver_return(
                                elapsed_by_solver,
                                solver_name,
                                args.global_timeout_seconds,
                                remaining_seconds,
                                effective_timeout_seconds,
                                args.problem_timeout_seconds,
                                smt_time,
                            )
                            if not args.allow_smt_failures and status == "unsat_or_unknown":
                                raise AssertionError(
                                    f"smt({label}) returned unsat/unknown"
                                )
                            if status == "global_timeout":
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
                        effective_timeout_seconds = attempt_timeout_seconds(
                            remaining_seconds,
                            args.problem_timeout_seconds,
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
                                        effective_timeout_seconds,
                                    ),
                                ),
                                timeout_seconds=effective_timeout_seconds,
                            )
                            elapsed_by_solver[solver_name] = (
                                elapsed_by_solver.get(solver_name, 0.0) + modified_time
                            )
                        except SolverTimedOut as error:
                            smt_modified_failures_by_label[label][size] += 1
                            status = timeout_status_for_attempt(
                                remaining_seconds,
                                effective_timeout_seconds,
                                args.problem_timeout_seconds,
                            )
                            if status == "global_timeout":
                                elapsed_by_solver[solver_name] = args.global_timeout_seconds
                            else:
                                elapsed_by_solver[solver_name] = (
                                    elapsed_by_solver.get(solver_name, 0.0)
                                    + error.elapsed_seconds
                                )
                            csv_rows.append(
                                {
                                    "solver": solver_name,
                                    "size": size,
                                    "iteration": iteration,
                                    "instance_seed": instance_seed,
                                    "symmetric": args.symmetric,
                                    "status": status,
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
                            status = failure_status_for_solver_return(
                                elapsed_by_solver,
                                solver_name,
                                args.global_timeout_seconds,
                                remaining_seconds,
                                effective_timeout_seconds,
                                args.problem_timeout_seconds,
                                modified_time,
                            )
                            if not args.allow_smt_failures and status == "unsat_or_unknown":
                                raise AssertionError(
                                    f"modified smt({label}) unexpectedly returned unsat/unknown"
                                )
                            if status == "global_timeout":
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
                if dp_stopped_after_timeout:
                    csv_rows.append(
                        {
                            "solver": "dp",
                            "size": size,
                            "iteration": iteration,
                            "instance_seed": instance_seed,
                            "symmetric": args.symmetric,
                            "status": "skipped_after_timeout",
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
                if args.dp_max_size > 0 and size > args.dp_max_size:
                    csv_rows.append(
                        {
                            "solver": "dp",
                            "size": size,
                            "iteration": iteration,
                            "instance_seed": instance_seed,
                            "symmetric": args.symmetric,
                            "status": "skipped_dp_max_size",
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
                effective_timeout_seconds = attempt_timeout_seconds(
                    remaining_seconds,
                    args.problem_timeout_seconds,
                )
                try:
                    dp_time, dp_result = time_solver(
                        lambda: dp(distances),
                        timeout_seconds=effective_timeout_seconds,
                    )
                    elapsed_by_solver["dp"] = elapsed_by_solver.get("dp", 0.0) + dp_time
                except SolverTimedOut as error:
                    status = timeout_status_for_attempt(
                        remaining_seconds,
                        effective_timeout_seconds,
                        args.problem_timeout_seconds,
                    )
                    if status == "global_timeout":
                        elapsed_by_solver["dp"] = args.global_timeout_seconds
                    else:
                        elapsed_by_solver["dp"] = (
                            elapsed_by_solver.get("dp", 0.0) + error.elapsed_seconds
                        )
                    if args.stop_dp_after_timeout:
                        dp_stopped_after_timeout = True
                    csv_rows.append(
                        {
                            "solver": "dp",
                            "size": size,
                            "iteration": iteration,
                            "instance_seed": instance_seed,
                            "symmetric": args.symmetric,
                            "status": status,
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
