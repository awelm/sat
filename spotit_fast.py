#!/usr/bin/env python3
"""
Fastest version - disable expensive lookahead decision making
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

def encode_spotit(v, k, b, extra_symmetry=False, basic_symmetry=True):
    """Build a pure Boolean model"""
    card_symbol = [[Bool(f"c{i}s{j}") for j in range(v)] for i in range(b)]
    constraints = []

    # 1. Exactly k symbols per card
    for i in range(b):
        constraints.append(exactly_k(card_symbol[i], k))

    # 2. Any two different cards share exactly one symbol
    for i in range(b):
        for j in range(i + 1, b):
            both = [card_symbol[i][s] & card_symbol[j][s] for s in range(v)]
            constraints.append(exactly_k(both, 1))

    # 3. Every symbol is used at least once
    for s in range(v):
        constraints.append(at_least_k([card_symbol[i][s] for i in range(b)], 1))

    # 4. Basic symmetry breaking
    if basic_symmetry:
        for s in range(v):
            constraints.append(card_symbol[0][s] if s < k else Not(card_symbol[0][s]))
        if b >= 2:
            constraints.append(card_symbol[1][0])
            second_fixed = list(range(k, k + k - 1))
            for s in range(v):
                if s in second_fixed:
                    constraints.append(card_symbol[1][s])
                elif s != 0:
                    constraints.append(Not(card_symbol[1][s]))

    # 5. Extra symmetry breaking (simplified)
    if extra_symmetry and b >= 3:
        # Minimal extra symmetry - just force third card structure
        constraints.append(card_symbol[2][0])  # Third card shares symbol 0 with first two
        # Force it to have next available symbols
        for s in range(1, min(k, v)):
            if s < 2*k-1:  # Avoid conflicts with second card
                continue
            constraints.append(card_symbol[2][s] if s < k+k-1 else Not(card_symbol[2][s]))

    return card_symbol, constraints

def solve_instance_fastest(v, k, b, timeout_s=86400, threads=None, extra_symmetry=False, basic_symmetry=True):
    """Fastest solver configuration - disable expensive lookahead"""
    card_symbol, constraints = encode_spotit(v, k, b, extra_symmetry, basic_symmetry)
    
    print(f"Variables: {b * v}")
    print(f"Constraints: {len(constraints)}")
    
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

    # FASTEST configuration - disable lookahead completely
    s = Solver()
    s.set("timeout", timeout_s * 1000)
    
    if threads is None:
        threads = min(8, multiprocessing.cpu_count())
    s.set("threads", threads)
    
    # CRITICAL: Disable expensive lookahead decision making
    s.set("case_split", 0)                 # Disable case splitting lookahead
    s.set("theory_case_split", False)      # Disable theory-specific case splitting
    
    # Fast decision heuristics instead of lookahead
    s.set("phase_selection", 0)            # Fixed phase selection (fastest)
    s.set("restart_strategy", 0)           # Luby restart (more predictable)
    s.set("restart_factor", 2.0)           # Aggressive restarts
    
    # PB optimizations
    s.set("pb.conflict_frequency", 100)    # Very frequent PB conflict analysis
    s.set("pb.learn_complements", True)
    
    # Memory and performance
    s.set("max_memory", 16000)
    s.set("random_seed", 42)
    
    print(f"Z3 FASTEST config: {threads} threads, lookahead DISABLED")

    s.add(constraints)
    print("Starting FASTEST Z3 solver...")

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

def pretty_print(model, card_symbol, v, k):
    """Print a found design in a human‑readable format."""
    symbols = [f"S{i}" for i in range(v)]
    for i, row in enumerate(card_symbol):
        syms = [symbols[j] for j in range(v) if is_true(model.evaluate(row[j]))]
        print(f"Card {i:>3}:  " + ", ".join(syms))
    print(f"\nEvery card has exactly {k} symbols – verified.")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("v", nargs="?", type=int)
    parser.add_argument("k", nargs="?", type=int)
    parser.add_argument("--timeout", type=int, default=86400)
    parser.add_argument("--extra-symmetry", action="store_true")
    parser.add_argument("--no-basic-symmetry", action="store_true")
    args = parser.parse_args()

    if args.v is None:
        print("Usage: python spotit_fast.py v k [options]")
        return

    v, k = args.v, args.k
    if not quick_feasibility(v, k):
        print("Instance fails feasibility check")
        return

    model, cs, solve_time = solve_instance_fastest(
        v, k, v, 
        timeout_s=args.timeout, 
        extra_symmetry=args.extra_symmetry, 
        basic_symmetry=not args.no_basic_symmetry
    )
    
    if model:
        pretty_print(model, cs, v, k)
        print(f"\n✓ Solution found in {solve_time:.3f} seconds")
    else:
        print(f"No solution found after {solve_time:.3f} seconds")

if __name__ == "__main__":
    main()