#!/usr/bin/env python3
"""
Test different solver strategies for the Spot-It problem
"""

import subprocess
import time
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed

def run_strategy(strategy_name, command, timeout_minutes=30):
    """Run a single strategy with timeout"""
    print(f"Starting {strategy_name}...")
    start_time = time.time()
    
    try:
        result = subprocess.run(
            command, 
            shell=True, 
            capture_output=True, 
            text=True, 
            timeout=timeout_minutes * 60
        )
        elapsed = time.time() - start_time
        
        if "Solution found" in result.stdout or "✓" in result.stdout:
            return {
                'strategy': strategy_name,
                'status': 'SOLVED',
                'time': elapsed,
                'output': result.stdout
            }
        elif "No solution" in result.stdout or "unsat" in result.stdout:
            return {
                'strategy': strategy_name,
                'status': 'UNSAT',
                'time': elapsed,
                'output': result.stdout
            }
        else:
            return {
                'strategy': strategy_name,
                'status': 'TIMEOUT',
                'time': elapsed,
                'output': result.stdout
            }
    except subprocess.TimeoutExpired:
        return {
            'strategy': strategy_name,
            'status': 'TIMEOUT',
            'time': timeout_minutes * 60,
            'output': f'Timeout after {timeout_minutes} minutes'
        }
    except Exception as e:
        return {
            'strategy': strategy_name,
            'status': 'ERROR',
            'time': time.time() - start_time,
            'output': str(e)
        }

def main():
    if len(sys.argv) != 3:
        print("Usage: python test_strategies.py v k")
        return
    
    v, k = int(sys.argv[1]), int(sys.argv[2])
    timeout_minutes = 10  # Short timeout for testing
    
    strategies = [
        ("Original", f"python spotit.py {v} {k} --timeout {timeout_minutes*60}"),
        ("No Extra Symmetry", f"python spotit.py {v} {k} --timeout {timeout_minutes*60}"),
        ("Optimized", f"python spotit_optimized.py {v} {k} --timeout {timeout_minutes*60}"),
        ("Optimized + Extra Sym", f"python spotit_optimized.py {v} {k} --extra-symmetry --timeout {timeout_minutes*60}"),
    ]
    
    print(f"Testing strategies for v={v}, k={k} with {timeout_minutes} minute timeout each")
    print("=" * 60)
    
    # Run strategies in parallel
    with ProcessPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(run_strategy, name, cmd, timeout_minutes): name 
            for name, cmd in strategies
        }
        
        results = []
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            
            print(f"\n{result['strategy']}: {result['status']}")
            print(f"Time: {result['time']:.1f}s")
            if result['status'] == 'SOLVED':
                print("🎉 FOUND SOLUTION!")
                print(result['output'])
                break  # Stop other processes if we found a solution
    
    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY:")
    for result in sorted(results, key=lambda x: x['time']):
        print(f"{result['strategy']:20} | {result['status']:8} | {result['time']:6.1f}s")

if __name__ == "__main__":
    main()