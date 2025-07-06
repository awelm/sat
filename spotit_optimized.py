#!/usr/bin/env python3
"""
Optimized Spot-It solver with better Z3 configuration
"""

from z3 import *
from math import comb
import time
import argparse
import sys
import multiprocessing
import random
import os

def exactly_k(bs, k):
    """Exactly k of the Boolean literals in *bs* are true."""
    return PbEq([(b, 1) for b in bs], k)

def at_least_k(bs, k):
    return PbGe([(b, 1) for b in bs], k)

def encode_spotit_optimized(v, k, b, extra_symmetry=False, basic_symmetry=True):
    """
    Optimized encoding with better constraint structure
    """
    card_symbol = [[Bool(f"c{i}s{j}") for j in range(v)] for i in range(b)]
    constraints = []

    # 1. Exactly k symbols per card
    for i in range(b):
        constraints.append(exactly_k(card_symbol[i], k))

    # 2. Pair constraints - optimized with early pruning
    for i in range(b):
        for j in range(i + 1, b):
            both = [And(card_symbol[i][s], card_symbol[j][s]) for s in range(v)]
            constraints.append(exactly_k(both, 1))

    # 3. Symbol usage constraints
    for s in range(v):
        constraints.append(at_least_k([card_symbol[i][s] for i in range(b)], 1))

    # 4. Basic symmetry breaking
    if basic_symmetry:
        for s in range(v):
            constraints.append(card_symbol[0][s] if s < k else Not(card_symbol[0][s]))
        if b >= 2:
            constraints.append(card_symbol[1][0])
            second_fixed = list(range(k, min(v, k + k - 1)))
            for s in range(v):
                if s in second_fixed:
                    constraints.append(card_symbol[1][s])
                elif s != 0:
                    constraints.append(Not(card_symbol[1][s]))

    # 5. Simplified extra symmetry (less aggressive)
    if extra_symmetry and b >= 3:
        # Only lexicographic ordering for first 3 cards
        for i in range(min(b-1, 3)):
            for s in range(v-1):
                # If card i doesn't have symbol s but has s+1, then card i+1 must have s+1
                constraints.append(Or(card_symbol[i][s], Not(card_symbol[i][s+1]), card_symbol[i+1][s+1]))

    return card_symbol, constraints

def solve_instance_optimized(v, k, b, timeout_s=86400, threads=None, extra_symmetry=False, basic_symmetry=True):
    """
    Optimized solver with better Z3 configuration
    """
    card_symbol, constraints = encode_spotit_optimized(v, k, b, extra_symmetry, basic_symmetry)
    
    print(f"Variables: {b * v}")
    print(f"Constraints: {len(constraints)}")
    
    # Explain the constraint structure
    print("\n=== CONSTRAINT BREAKDOWN ===")
    card_constraints = b
    pair_constraints = b * (b - 1) // 2
    symbol_constraints = v
    symmetry_constraints = len(constraints) - card_constraints - pair_constraints - symbol_constraints
    
    print(f"Card constraints (exactly k symbols per card): {card_constraints}")
    print(f"Pair constraints (any two cards share exactly 1 symbol): {pair_constraints}")
    print(f"Symbol constraints (each symbol used at least once): {symbol_constraints}")
    print(f"Symmetry breaking constraints: {symmetry_constraints}")
    print(f"Total: {len(constraints)} constraints")

    # Optimized solver configuration
    s = Solver()
    s.set("timeout", timeout_s * 1000)
    
    if threads is None:
        threads = multiprocessing.cpu_count()
    s.set("threads", threads)
    
    # Advanced Z3 settings for SAT problems
    s.set("sat.phase", "caching")           # Better phase selection
    s.set("sat.restart", "geometric")       # Geometric restart strategy
    s.set("sat.restart.base", 1.5)         # Restart base factor
    s.set("sat.gc", "dyn_psm")             # Dynamic clause deletion
    s.set("sat.gc.burst", True)            # Burst garbage collection
    s.set("sat.gc.defrag", True)           # Defragment memory
    s.set("sat.simplify", True)            # Enable simplification
    s.set("sat.simplify.delay", 0)         # Immediate simplification
    
    # Memory management
    s.set("max_memory", 16000)             # 16GB memory limit
    s.set("sat.max_memory", 8000)          # 8GB for SAT solver
    
    print(f"Z3 optimized configuration: {threads} threads with advanced SAT settings")

    s.add(constraints)
    print("Starting optimized Z3 solver...")

    t0 = time.time()
    res = s.check()
    elapsed = time.time() - t0
    
    print(f"--> Z3 returned {res}  (in {elapsed:.1f} s)")
    
    if res == sat or res == unsat:
        print("\n=== Z3 STATISTICS ===")
        stats = s.statistics()
        key_stats = ["conflicts", "decisions", "propagations", "restarts", "memory", "time"]
        for i in range(len(stats)):
            key, value = stats[i]
            if any(k in key.lower() for k in key_stats):
                print(f"  {key}: {value}")

    if res == sat:
        return s.model(), card_symbol, elapsed
    return None, None, elapsed

def quick_feasibility(v, k):
    if k < 2 or v < k:
        return False
    b = v
    r_times_v = b * k
    if r_times_v % v != 0:
        return False
    r = r_times_v // v
    return (r * (k - 1)) % (v - 1) == 0

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("v", nargs="?", type=int)
    parser.add_argument("k", nargs="?", type=int)
    parser.add_argument("--timeout", type=int, default=86400)
    parser.add_argument("--extra-symmetry", action="store_true")
    parser.add_argument("--no-basic-symmetry", action="store_true")
    args = parser.parse_args()

    if args.v is None:
        print("Usage: python spotit_optimized.py v k [options]")
        return

    v, k = args.v, args.k
    if not quick_feasibility(v, k):
        print("Instance fails feasibility check")
        return

    model, cs, solve_time = solve_instance_optimized(
        v, k, v, 
        timeout_s=args.timeout, 
        extra_symmetry=args.extra_symmetry, 
        basic_symmetry=not args.no_basic_symmetry
    )
    
    if model:
        print(f"\n✓ Solution found in {solve_time:.3f} seconds")
    else:
        print(f"No solution found after {solve_time:.3f} seconds")

if __name__ == "__main__":
    main()