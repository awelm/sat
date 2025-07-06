from __future__ import annotations

from typing import Dict, List, Tuple
from concurrent.futures import ProcessPoolExecutor, as_completed
import argparse
import multiprocessing

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
smt_modified_enabled: bool = False


def run_single_benchmark(task_data: Tuple) -> Dict:
    """Run a single benchmark task in parallel."""
    size, iteration, distances, smt_enabled, dp_enabled, smt_modified_enabled = task_data
    results = {
        'size': size,
        'iteration': iteration,
        'smt_time': None,
        'smt_dist': None,
        'smt_path': None,
        'dp_time': None,
        'dp_dist': None,
        'dp_path': None,
        'modified_time': None,
        'modified_dist': None,
        'modified_path': None,
        'agree': None
    }
    
    print(f"Running size {size}, iteration {iteration}")
    
    if smt_enabled:
        start = time.perf_counter()
        smt_dist, smt_path = smt(distances)
        smt_time = time.perf_counter() - start
        results['smt_time'] = smt_time
        results['smt_dist'] = smt_dist
        results['smt_path'] = smt_path
        print(f"  SMT: {smt_dist} in {smt_time:.4f}s")
    
    if smt_modified_enabled and size >= 3:
        required_orders = {2: 1}
        start = time.perf_counter()
        modified_dist, modified_path = smt(distances, required_orders)
        modified_time = time.perf_counter() - start
        results['modified_time'] = modified_time
        results['modified_dist'] = modified_dist
        results['modified_path'] = modified_path
        print(f"  SMT Modified: {modified_dist} in {modified_time:.4f}s")
    
    if dp_enabled:
        start = time.perf_counter()
        dp_dist, dp_path = dp(distances)
        dp_time = time.perf_counter() - start
        results['dp_time'] = dp_time
        results['dp_dist'] = dp_dist
        results['dp_path'] = dp_path
        print(f"  DP: {dp_dist} in {dp_time:.4f}s")
    
    if smt_enabled and dp_enabled:
        if results['smt_dist'] == -1:
            results['agree'] = 'timeout'
            print(f"  WARNING: SMT solver timed out (DP found {results['dp_dist']})")
        elif results['smt_dist'] != results['dp_dist']:
            results['agree'] = False
            raise RuntimeError(f"DISAGREEMENT found on size {size}, iteration {iteration}: SMT={results['smt_dist']}, DP={results['dp_dist']}. This indicates a bug in one of the algorithms.")
        else:
            results['agree'] = True
    
    return results

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--min-size", type=int, default=min_size)
    parser.add_argument("--max-size", type=int, default=max_size)
    parser.add_argument("--iterations", type=int, default=iterations)
    parser.add_argument("--smt", dest="smt", action="store_true", default=smt_enabled)
    parser.add_argument("--dp", dest="dp", action="store_true", default=dp_enabled)
    parser.add_argument("--smt-modified", dest="smt_modified", action="store_true", default=smt_modified_enabled)
    parser.add_argument("--no-plot", action="store_true")
    parser.add_argument("--workers", type=int, default=min(4, multiprocessing.cpu_count()), 
                       help="Number of parallel workers")
    args = parser.parse_args()

    # Generate all tasks upfront
    tasks = []
    for size in range(args.min_size, args.max_size + 1):
        for iteration in range(args.iterations):
            distances = [[random.randint(0, 100) for _ in range(size)] for _ in range(size)]
            for i in range(size):
                distances[i][i] = 0
            
            task_data = (size, iteration, distances, args.smt, args.dp, args.smt_modified)
            tasks.append(task_data)
    
    print(f"Running {len(tasks)} tasks with {args.workers} workers...")
    
    # Run tasks in parallel
    results = []
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        future_to_task = {executor.submit(run_single_benchmark, task): task for task in tasks}
        
        for future in as_completed(future_to_task):
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                task = future_to_task[future]
                print(f"Task {task[0]}-{task[1]} failed: {e}")
    
    # Organize results
    smt_times_by_size: Dict[int, List[float]] = {}
    dp_times_by_size: Dict[int, List[float]] = {}
    smt_modified_times_by_size: Dict[int, List[float]] = {}
    
    for size in range(args.min_size, args.max_size + 1):
        smt_times_by_size[size] = []
        dp_times_by_size[size] = []
        smt_modified_times_by_size[size] = []
    
    # Track timeouts and disagreements
    timeouts_by_size = {}
    disagreements = []
    
    for result in results:
        size = result['size']
        if result['smt_time'] is not None:
            smt_times_by_size[size].append(result['smt_time'])
        if result['dp_time'] is not None:
            dp_times_by_size[size].append(result['dp_time'])
        if result['modified_time'] is not None:
            smt_modified_times_by_size[size].append(result['modified_time'])
            
        # Track timeouts
        if result.get('agree') == 'timeout':
            if size not in timeouts_by_size:
                timeouts_by_size[size] = 0
            timeouts_by_size[size] += 1
        
        # Track real disagreements (not timeouts)
        if result.get('agree') is False:
            disagreements.append(result)

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
    
    # Summary
    print("\n=== SUMMARY ===")
    if timeouts_by_size:
        print("SMT Timeouts by size:")
        for size, count in sorted(timeouts_by_size.items()):
            print(f"  Size {size}: {count}/{args.iterations} timeouts")
    else:
        print("No SMT timeouts occurred")
    
    if disagreements:
        print(f"\nReal disagreements found: {len(disagreements)}")
        for d in disagreements:
            print(f"  Size {d['size']}: SMT={d['smt_dist']}, DP={d['dp_dist']}")
    else:
        print("\nNo disagreements found (excluding timeouts)")

    if not args.no_plot:
        plt.scatter(dp_sizes, dp_medians, label="dp")
        plt.scatter(smt_sizes, smt_medians, label="smt")
        plt.scatter(modified_sizes, modified_medians, label="smt_modified")
        plt.xlabel("Cities")
        plt.ylabel("Median time (seconds)")
        plt.legend()
        plt.show()


if __name__ == "__main__":
    main()
