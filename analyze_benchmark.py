from __future__ import annotations

import argparse
import csv
import math
import os
import platform
import random
import statistics
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


PairKey = Tuple[int, int, int, str]

SUMMARY_FIELDNAMES = [
    "solver",
    "size",
    "attempts",
    "ok",
    "failures",
    "median_seconds",
    "mean_seconds",
    "min_seconds",
    "max_seconds",
]

COMPARISON_FIELDNAMES = [
    "size",
    "baseline_solver",
    "candidate_solver",
    "paired_instances",
    "candidate_attempts",
    "candidate_failures",
    "dp_median_seconds",
    "candidate_median_seconds",
    "median_speedup",
    "mean_log_speedup",
    "speedup_ci_low",
    "speedup_ci_high",
    "smt_wins",
    "dp_wins",
    "ties",
    "sign_test_p_value",
    "verdict",
]


@dataclass(frozen=True)
class TimingRow:
    solver: str
    size: int
    iteration: int
    instance_seed: int
    symmetric: str
    status: str
    time_seconds: Optional[float]

    @property
    def key(self) -> PairKey:
        return (self.size, self.iteration, self.instance_seed, self.symmetric)


def read_raw_rows(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def build_timing_rows(raw_rows: Iterable[Dict[str, str]]) -> List[TimingRow]:
    rows = []
    for row in raw_rows:
        time_seconds = None
        if row["time_seconds"]:
            time_seconds = float(row["time_seconds"])
        rows.append(
            TimingRow(
                solver=row["solver"],
                size=int(row["size"]),
                iteration=int(row["iteration"]),
                instance_seed=int(row["instance_seed"]),
                symmetric=row["symmetric"],
                status=row["status"],
                time_seconds=time_seconds,
            )
        )
    return rows


def median(values: List[float]) -> Optional[float]:
    if not values:
        return None
    return statistics.median(values)


def mean(values: List[float]) -> Optional[float]:
    if not values:
        return None
    return statistics.fmean(values)


def percentile(values: List[float], percentile_value: float) -> Optional[float]:
    if not values:
        return None
    sorted_values = sorted(values)
    index = (len(sorted_values) - 1) * percentile_value
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return sorted_values[int(index)]
    fraction = index - lower
    return sorted_values[lower] * (1 - fraction) + sorted_values[upper] * fraction


def bootstrap_median_ci(
    values: List[float],
    samples: int,
    confidence: float,
    rng: random.Random,
) -> Tuple[Optional[float], Optional[float]]:
    if not values:
        return None, None

    bootstrapped = []
    for _ in range(samples):
        resample = [values[rng.randrange(len(values))] for _ in values]
        bootstrapped.append(statistics.median(resample))

    tail = (1 - confidence) / 2
    return percentile(bootstrapped, tail), percentile(bootstrapped, 1 - tail)


def sign_test_p_value(wins: int, losses: int) -> Optional[float]:
    trials = wins + losses
    if trials == 0:
        return None
    tail = sum(math.comb(trials, k) for k in range(wins, trials + 1))
    return min(1.0, tail / (2**trials))


def format_float(value: Optional[float], digits: int = 6) -> str:
    if value is None:
        return ""
    return f"{value:.{digits}g}"


def summarize_solver_rows(rows: Iterable[TimingRow]) -> List[Dict[str, object]]:
    grouped: Dict[Tuple[str, int], List[TimingRow]] = defaultdict(list)
    for row in rows:
        grouped[(row.solver, row.size)].append(row)

    summary = []
    for (solver, size), solver_rows in sorted(grouped.items(), key=lambda item: item[0]):
        ok_times = [
            row.time_seconds
            for row in solver_rows
            if row.status == "ok" and row.time_seconds is not None
        ]
        summary.append(
            {
                "solver": solver,
                "size": size,
                "attempts": len(solver_rows),
                "ok": len(ok_times),
                "failures": len(solver_rows) - len(ok_times),
                "median_seconds": format_float(median(ok_times)),
                "mean_seconds": format_float(mean(ok_times)),
                "min_seconds": format_float(min(ok_times) if ok_times else None),
                "max_seconds": format_float(max(ok_times) if ok_times else None),
            }
        )
    return summary


def compare_solver_to_dp(
    rows: Iterable[TimingRow],
    candidate_solver: str,
    bootstrap_samples: int,
    confidence: float,
    alpha: float,
    min_pairs: int,
    rng: random.Random,
) -> List[Dict[str, object]]:
    dp_by_key = {
        row.key: row
        for row in rows
        if row.solver == "dp" and row.status == "ok" and row.time_seconds is not None
    }
    candidate_rows_by_size: Dict[int, List[TimingRow]] = defaultdict(list)
    candidate_attempts_by_size: Dict[int, int] = defaultdict(int)
    candidate_failures_by_size: Dict[int, int] = defaultdict(int)

    for row in rows:
        if row.solver != candidate_solver:
            continue
        candidate_attempts_by_size[row.size] += 1
        if row.status != "ok" or row.time_seconds is None:
            candidate_failures_by_size[row.size] += 1
            continue
        candidate_rows_by_size[row.size].append(row)

    comparison_rows = []
    for size, candidate_rows in sorted(candidate_rows_by_size.items()):
        pairs = []
        for candidate in candidate_rows:
            baseline = dp_by_key.get(candidate.key)
            if baseline is None or baseline.time_seconds is None:
                continue
            pairs.append((baseline.time_seconds, candidate.time_seconds))

        if not pairs:
            continue

        speedups = [dp_time / candidate_time for dp_time, candidate_time in pairs]
        log_speedups = [
            math.log(dp_time) - math.log(candidate_time)
            for dp_time, candidate_time in pairs
        ]
        wins = sum(1 for dp_time, candidate_time in pairs if candidate_time < dp_time)
        losses = sum(1 for dp_time, candidate_time in pairs if candidate_time > dp_time)
        ties = len(pairs) - wins - losses
        p_value = sign_test_p_value(wins, losses)
        ci_low, ci_high = bootstrap_median_ci(
            speedups,
            samples=bootstrap_samples,
            confidence=confidence,
            rng=rng,
        )
        median_speedup = median(speedups)

        if len(pairs) < min_pairs:
            verdict = "UNDERPOWERED"
        elif median_speedup is not None and ci_low is not None and ci_high is not None:
            if median_speedup > 1 and ci_low > 1 and p_value is not None and p_value <= alpha:
                verdict = "PASS"
            elif median_speedup < 1 and ci_high < 1:
                verdict = "FAIL"
            else:
                verdict = "INCONCLUSIVE"
        else:
            verdict = "INCONCLUSIVE"

        comparison_rows.append(
            {
                "size": size,
                "baseline_solver": "dp",
                "candidate_solver": candidate_solver,
                "paired_instances": len(pairs),
                "candidate_attempts": candidate_attempts_by_size[size],
                "candidate_failures": candidate_failures_by_size[size],
                "dp_median_seconds": format_float(median([pair[0] for pair in pairs])),
                "candidate_median_seconds": format_float(
                    median([pair[1] for pair in pairs])
                ),
                "median_speedup": format_float(median_speedup),
                "mean_log_speedup": format_float(mean(log_speedups)),
                "speedup_ci_low": format_float(ci_low),
                "speedup_ci_high": format_float(ci_high),
                "smt_wins": wins,
                "dp_wins": losses,
                "ties": ties,
                "sign_test_p_value": format_float(p_value),
                "verdict": verdict,
            }
        )

    return comparison_rows


def write_csv(
    path: Path,
    rows: List[Dict[str, object]],
    fieldnames: List[str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def parse_params(values: Sequence[str]) -> Dict[str, str]:
    params = {}
    for value in values:
        if "=" not in value:
            raise ValueError("--param values must be formatted as name=value")
        name, setting = value.split("=", 1)
        params[name] = setting
    return params


def command_output(command: List[str]) -> str:
    try:
        return subprocess.check_output(command, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return ""


def collect_environment() -> Dict[str, str]:
    z3_version = ""
    try:
        import z3

        z3_version = z3.get_version_string()
    except Exception:
        pass

    return {
        "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "python": sys.version.replace("\n", " "),
        "python_executable": sys.executable,
        "platform": platform.platform(),
        "z3": z3_version,
        "git_head": command_output(["git", "rev-parse", "--short", "HEAD"]),
        "git_status": command_output(["git", "status", "--short"]),
    }


def solver_label(solver: str) -> str:
    return "DP" if solver == "dp" else solver


def numeric(value: object) -> Optional[float]:
    if value == "" or value is None:
        return None
    return float(value)


def write_plot(
    path: Path,
    summary_rows: List[Dict[str, object]],
    comparison_rows: List[Dict[str, object]],
    candidate: str,
) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter, LogLocator

    series: Dict[str, List[Tuple[int, float]]] = defaultdict(list)
    for row in summary_rows:
        median_seconds = numeric(row["median_seconds"])
        if median_seconds is None:
            continue
        solver = str(row["solver"])
        if solver not in ("dp", candidate):
            continue
        series[solver].append((int(row["size"]), median_seconds))

    if not series:
        raise ValueError("no plottable timing data found")

    plotted_sizes = [
        size
        for points in series.values()
        for size, _ in points
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 6), dpi=180)
    colors = {"dp": "#d62728", candidate: "#1f77b4"}
    markers = {"dp": "o", candidate: "o"}
    for solver in (candidate, "dp"):
        points = sorted(series.get(solver, []))
        if not points:
            continue
        ax.plot(
            [size for size, _ in points],
            [seconds for _, seconds in points],
            color=colors.get(solver),
            marker=markers.get(solver, "o"),
            linewidth=2.4,
            markersize=5.5,
            label=f"{solver_label(solver)} median",
        )

    pass_sizes = [
        int(row["size"])
        for row in comparison_rows
        if row.get("verdict") == "PASS"
    ]
    if pass_sizes:
        ax.axvspan(
            min(pass_sizes),
            max(pass_sizes),
            color="#4C78A8",
            alpha=0.09,
            label="SMT faster with significance",
        )

    ax.set_yscale("log")
    ax.yaxis.set_major_locator(LogLocator(base=10))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:g}"))
    observed_times = [
        seconds
        for points in series.values()
        for _, seconds in points
    ]
    if min(observed_times) < 1 < max(observed_times):
        ax.axhline(1, color="#6b7280", linestyle="--", linewidth=1.0, alpha=0.7)
        ax.text(
            max(plotted_sizes) + 0.08,
            1,
            "1s",
            va="bottom",
            ha="left",
            fontsize=9,
            color="#4b5563",
        )
    ax.set_xticks(sorted(set(plotted_sizes)))
    ax.set_xlabel("Cities")
    ax.set_ylabel("Median runtime (seconds, log scale)")
    ax.set_title("TSP Benchmark: SMT vs DP Median Runtime")
    ax.grid(axis="y", which="major", color="#d9dde3", linewidth=0.9)
    ax.grid(axis="x", which="major", color="#eef1f5", linewidth=0.7)
    ax.legend(frameon=True, framealpha=0.96, edgecolor="#d9dde3")
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)


def markdown_table(rows: List[Dict[str, object]], headers: List[str]) -> List[str]:
    if not rows:
        return ["No rows."]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(row[header]) for header in headers) + " |")
    return lines


def markdown_image_reference(markdown_path: Path, image_path: Path) -> str:
    return Path(
        os.path.relpath(image_path.resolve(), markdown_path.parent.resolve())
    ).as_posix()


def write_markdown(
    path: Path,
    chart_path: Path,
    csv_path: Path,
    summary_csv_path: Optional[Path],
    comparison_csv_path: Optional[Path],
    summary_rows: List[Dict[str, object]],
    comparison_rows: List[Dict[str, object]],
    run_id: str,
    candidate: str,
    cli_invocation: str,
    params: Dict[str, str],
    environment: Dict[str, str],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    chart_reference = markdown_image_reference(path, chart_path)
    lines = [
        "# TSP Benchmark Run",
        "",
        f"- Run ID: `{run_id}`",
        f"- Commit: `{environment.get('git_head', '')}`",
        f"- Candidate solver: `{candidate}`",
        f"- CLI invocation: `{cli_invocation}`",
        f"- Raw CSV: `{csv_path}`",
    ]
    if summary_csv_path is not None:
        lines.append(f"- Summary CSV: `{summary_csv_path}`")
    if comparison_csv_path is not None:
        lines.append(f"- Comparison CSV: `{comparison_csv_path}`")

    lines.extend(
        [
            "",
            f"![SMT vs DP benchmark chart]({chart_reference})",
            "",
            "## Parameters",
            "",
        ]
    )
    for key, value in sorted(params.items()):
        lines.append(f"- {key}: `{value}`")

    lines.extend(
        [
            "",
            "## Solver Timing Summary",
            "",
        ]
    )
    lines.extend(
        markdown_table(
            summary_rows,
            [
                "solver",
                "size",
                "attempts",
                "ok",
                "failures",
                "median_seconds",
                "mean_seconds",
                "min_seconds",
                "max_seconds",
            ],
        )
    )
    lines.extend(
        [
            "",
            "## Paired DP vs SMT Significance",
            "",
        ]
    )
    lines.extend(
        markdown_table(
            comparison_rows,
            [
                "size",
                "paired_instances",
                "dp_median_seconds",
                "candidate_median_seconds",
                "median_speedup",
                "speedup_ci_low",
                "speedup_ci_high",
                "smt_wins",
                "dp_wins",
                "sign_test_p_value",
                "verdict",
            ],
        )
    )
    lines.extend(
        [
            "",
            "## Environment",
            "",
            f"- Python: `{environment.get('python', '')}`",
            f"- Python executable: `{environment.get('python_executable', '')}`",
            f"- Platform: `{environment.get('platform', '')}`",
            f"- Z3: `{environment.get('z3', '')}`",
        ]
    )
    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv", type=Path)
    parser.add_argument("--candidate", default="smt:lazy:auto")
    parser.add_argument("--plot", type=Path, default=None)
    parser.add_argument("--markdown", type=Path, default=None)
    parser.add_argument("--run-id", default="")
    parser.add_argument("--cli-invocation", default="")
    parser.add_argument("--param", action="append", default=[])
    parser.add_argument("--summary-csv", type=Path, default=None)
    parser.add_argument("--comparison-csv", type=Path, default=None)
    parser.add_argument("--bootstrap-samples", type=int, default=10_000)
    parser.add_argument("--confidence", type=float, default=0.95)
    parser.add_argument("--alpha", type=float, default=0.05)
    parser.add_argument("--min-pairs", type=int, default=10)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    if args.markdown is not None and args.plot is None:
        parser.error("--markdown requires --plot so the report can include a chart")

    raw_rows = read_raw_rows(args.csv)
    rows = build_timing_rows(raw_rows)
    rng = random.Random(args.seed)
    summary_rows = summarize_solver_rows(rows)
    comparison_rows = compare_solver_to_dp(
        rows,
        candidate_solver=args.candidate,
        bootstrap_samples=args.bootstrap_samples,
        confidence=args.confidence,
        alpha=args.alpha,
        min_pairs=args.min_pairs,
        rng=rng,
    )

    for row in comparison_rows:
        print(
            "size={size} pairs={paired_instances} speedup={median_speedup} "
            "ci=[{speedup_ci_low}, {speedup_ci_high}] wins={smt_wins} "
            "losses={dp_wins} p={sign_test_p_value} verdict={verdict}".format(
                **row
            )
        )

    if args.summary_csv is not None:
        write_csv(args.summary_csv, summary_rows, SUMMARY_FIELDNAMES)
    if args.comparison_csv is not None:
        write_csv(args.comparison_csv, comparison_rows, COMPARISON_FIELDNAMES)
    if args.plot is not None:
        write_plot(args.plot, summary_rows, comparison_rows, args.candidate)
    if args.markdown is not None:
        environment = collect_environment()
        write_markdown(
            args.markdown,
            chart_path=args.plot,
            csv_path=args.csv,
            summary_csv_path=args.summary_csv,
            comparison_csv_path=args.comparison_csv,
            summary_rows=summary_rows,
            comparison_rows=comparison_rows,
            run_id=args.run_id,
            candidate=args.candidate,
            cli_invocation=args.cli_invocation,
            params=parse_params(args.param),
            environment=environment,
        )


if __name__ == "__main__":
    main()
