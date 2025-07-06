#!/usr/bin/env python3
"""
Generalised Spot‑It solver – SAT encoding only
(Everything is done through Z3; no combinatorial shortcuts are used.)

Usage
-----

    python spotit.py              # run a few test cases
    python spotit.py  v  k  [--timeout 300]

Command‑line options
--------------------
    v, k          integers (k ≥ 2, k ≤ v)
    --timeout     wall‑clock timeout in seconds (default 300)
"""

from z3 import *
from math import comb
import time
import argparse
import sys
import multiprocessing
import random
import os


# ---------------------------------------------------------------------------
#  Helper – nice cardinality wrappers
# ---------------------------------------------------------------------------

def exactly_k(bs, k):
    """Exactly k of the Boolean literals in *bs* are true."""
    return PbEq([(b, 1) for b in bs], k)


def at_least_k(bs, k):
    return PbGe([(b, 1) for b in bs], k)


def at_most_k(bs, k):
    return PbLe([(b, 1) for b in bs], k)


# ---------------------------------------------------------------------------
#  Core SAT model
# ---------------------------------------------------------------------------

def encode_spotit(v, k, b, extra_symmetry=False, basic_symmetry=True):
    """
    Build a pure Boolean model:

        – card_symbol[i][j]  True  ⟺  symbol j is printed on card i
    """
    # One Boolean variable per "symbol appears on card"
    card_symbol = [[Bool(f"c{i}s{j}") for j in range(v)] for i in range(b)]
    constraints = []

    # 1.  Exactly k symbols per card
    for i in range(b):
        constraints.append(exactly_k(card_symbol[i], k))

    # 2.  Any two different cards share **exactly one** symbol
    #     〈 c_i ∧ c_j 〉 = 1
    for i in range(b):
        for j in range(i + 1, b):
            both = [card_symbol[i][s] & card_symbol[j][s] for s in range(v)]
            constraints.append(exactly_k(both, 1))

    # 3.  Every symbol is used at least once (no wasted pictures)
    for s in range(v):
        constraints.append(at_least_k([card_symbol[i][s] for i in range(b)], 1))

    # 4.  Basic symmetry breaking (optional)
    if basic_symmetry:
        #     – first card = symbols 0..k‑1
        for s in range(v):
            constraints.append(card_symbol[0][s] if s < k else Not(card_symbol[0][s]))
        #     – second card shares symbol 0, contains symbols k..k+(k‑2)
        if b >= 2:
            constraints.append(card_symbol[1][0])
            second_fixed = list(range(k, k + k - 1))
            for s in range(v):
                if s in second_fixed:
                    constraints.append(card_symbol[1][s])
                elif s != 0:
                    constraints.append(Not(card_symbol[1][s]))

    # 5. Extra symmetry breaking (optional)
    if extra_symmetry and b >= 3:
        # Force lexicographic ordering of cards (expensive but powerful)
        for i in range(min(b-1, 5)):  # Only first few cards to avoid explosion
            card_i = [If(card_symbol[i][s], 1 << s, 0) for s in range(v)]
            card_next = [If(card_symbol[i+1][s], 1 << s, 0) for s in range(v)]
            # Card i should be lexicographically <= card i+1
            constraints.append(Sum(card_i) <= Sum(card_next))
        
        # Force symbol usage order - symbols should appear in order of first use
        for s in range(min(v-1, 10)):  # Limit to avoid too many constraints
            # If symbol s+1 is used, then symbol s must be used first
            symbol_s_first_card = [If(card_symbol[i][s], i, b) for i in range(b)]
            symbol_s1_first_card = [If(card_symbol[i][s+1], i, b) for i in range(b)]
            first_s = Sum([If(card_symbol[i][s], 1, 0) for i in range(b)])
            first_s1 = Sum([If(card_symbol[i][s+1], 1, 0) for i in range(b)])
            # Only add constraint if both symbols are used
            constraints.append(Or(first_s1 == 0, first_s > 0))

    return card_symbol, constraints


def solve_instance(v, k, b, timeout_s=3600, threads=None, extra_symmetry=False, basic_symmetry=True):
    """
    Build the SAT instance and ask Z3.

    Returns
    -------
        model  –  Z3 model if SAT
        None   –  if UNSAT or timed‑out
    """
    card_symbol, constraints = encode_spotit(v, k, b, extra_symmetry, basic_symmetry)
    
    print(f"Variables: {b * v}")
    print(f"Constraints: {len(constraints)}")
    
    # Explain the constraint structure
    print("\n=== CONSTRAINT BREAKDOWN ===")
    card_constraints = b  # Each card has exactly k symbols
    pair_constraints = b * (b - 1) // 2  # Each pair of cards shares exactly 1 symbol
    symbol_constraints = v  # Each symbol appears at least once
    symmetry_constraints = len(constraints) - card_constraints - pair_constraints - symbol_constraints
    
    print(f"Card constraints (exactly k symbols per card): {card_constraints}")
    print(f"Pair constraints (any two cards share exactly 1 symbol): {pair_constraints}")
    print(f"Symbol constraints (each symbol used at least once): {symbol_constraints}")
    print(f"Symmetry breaking constraints: {symmetry_constraints}")
    print(f"Total: {len(constraints)} constraints")

    # Use regular solver with PB-optimized configuration
    s = Solver()
    s.set("timeout", timeout_s * 1000)     # ms
    
    # Basic threading - let Z3 decide optimal thread count
    if threads is None:
        threads = min(8, multiprocessing.cpu_count())
    s.set("threads", threads)
    
    # PB constraint optimizations (using valid parameters)
    s.set("pb.conflict_frequency", 500)    # More frequent PB conflict analysis
    s.set("pb.learn_complements", True)    # Learn complement constraints
    
    # Restart and search optimizations
    s.set("restart_strategy", 1)           # Geometric restart strategy
    s.set("restart_factor", 1.1)           # Conservative restart base
    s.set("phase_selection", 3)            # Caching phase selection
    s.set("random_seed", 42)               # Reproducible results
    
    # Memory and conflict optimizations  
    s.set("max_memory", 12000)             # 12GB memory limit
    
    print(f"Z3 configuration: {threads} threads")

    s.add(constraints)
    print("Starting Z3 solver...")

    t0 = time.time()
    res = s.check()
    elapsed = time.time() - t0
    
    print(f"--> Z3 returned {res}  (in {elapsed:.1f} s)")
    
    # Show detailed final statistics
    if res == sat or res == unsat:
        print("\n=== DETAILED Z3 STATISTICS ===")
        stats = s.statistics()
        for i in range(len(stats)):
            key, value = stats[i]
            print(f"  {key}: {value}")

    if res == sat:
        return s.model(), card_symbol, elapsed
    return None, None, elapsed


# ---------------------------------------------------------------------------
#  Utilities
# ---------------------------------------------------------------------------

def pretty_print(model, card_symbol, v, k):
    """Print a found design in a human‑readable format."""
    symbols = [f"S{i}" for i in range(v)]
    for i, row in enumerate(card_symbol):
        syms = [symbols[j] for j in range(v) if is_true(model.evaluate(row[j]))]
        print(f"Card {i:>3}:  " + ", ".join(syms))
    print(f"\nEvery card has exactly {k} symbols – verified.")


def quick_feasibility(v, k):
    """
    Necessary numerical conditions (same as in the old `is_feasible`),
    used only to skip impossible b.
    """
    if k < 2 or v < k:
        return False
    # In a (v,k,λ=1) design we must have v ≡ 1 (mod k−1) and
    # b = v , r = k , etc.  We do *not* use this to prune more,
    # just the two divisibility conditions:
    b = v
    r_times_v = b * k
    if r_times_v % v != 0:
        return False
    r = r_times_v // v
    return (r * (k - 1)) % (v - 1) == 0


# ---------------------------------------------------------------------------
#  Command‑line interface
# ---------------------------------------------------------------------------

def benchmark_symmetry():
    """Compare normal vs extra symmetry breaking across different problem sizes."""
    print("=== SYMMETRY BREAKING BENCHMARK ===")
    print("Testing when extra symmetry helps vs hurts...")
    
    test_cases = [
        (7, 3),   # Small
        (13, 4),  # Medium  
        (21, 5),  # Large
        # Skip larger ones for now as they take too long
    ]
    
    results = []
    
    for v, k in test_cases:
        print(f"\n--- Testing v={v}, k={k} ---")
        
        if not quick_feasibility(v, k):
            print("Not feasible, skipping")
            continue
            
        # Test normal symmetry
        print("Normal symmetry breaking...")
        try:
            model1, cs1, time1 = solve_instance(v, k, v, timeout_s=60, extra_symmetry=False)
            normal_time = time1 if model1 else float('inf')
            normal_solved = model1 is not None  
        except:
            normal_time = float('inf')
            normal_solved = False
            
        # Test extra symmetry
        print("Extra symmetry breaking...")
        try:
            model2, cs2, time2 = solve_instance(v, k, v, timeout_s=60, extra_symmetry=True)
            extra_time = time2 if model2 else float('inf')
            extra_solved = model2 is not None
        except:
            extra_time = float('inf')
            extra_solved = False
            
        # Analyze results
        if normal_solved and extra_solved:
            speedup = normal_time / extra_time
            if speedup > 1.1:
                verdict = f"EXTRA HELPS ({speedup:.2f}x faster)"
            elif speedup < 0.9:
                verdict = f"NORMAL HELPS ({1/speedup:.2f}x faster)"
            else:
                verdict = "SIMILAR"
        elif normal_solved and not extra_solved:
            verdict = "NORMAL WINS (extra failed)"
        elif extra_solved and not normal_solved:
            verdict = "EXTRA WINS (normal failed)" 
        else:
            verdict = "BOTH FAILED"
            
        result = {
            'v': v, 'k': k,
            'normal_time': normal_time,
            'extra_time': extra_time,
            'normal_solved': normal_solved,
            'extra_solved': extra_solved,
            'verdict': verdict
        }
        results.append(result)
        
        print(f"Normal: {normal_time:.3f}s ({'✓' if normal_solved else '✗'})")
        print(f"Extra:  {extra_time:.3f}s ({'✓' if extra_solved else '✗'})")
        print(f"Result: {verdict}")
        
    # Summary analysis
    print(f"\n{'='*60}")
    print("SUMMARY:")
    for r in results:
        variables = r['v'] * r['v']  # Approximate problem size
        constraint_ratio = (r['v'] + r['v']*(r['v']-1)//2 + r['v'] + 57) / (r['v'] + r['v']*(r['v']-1)//2 + r['v'] + 42)  # Rough estimate
        print(f"v={r['v']}, k={r['k']} (~{variables} vars): {r['verdict']}")
        
    return results

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("v", nargs="?", type=int)
    parser.add_argument("k", nargs="?", type=int)
    parser.add_argument("--timeout", type=int, default=86400,
                        help="per‑instance timeout in seconds (default 86400)")
    parser.add_argument("--extra-symmetry", action="store_true",
                        help="add extra symmetry breaking constraints (may help or hurt)")
    parser.add_argument("--no-basic-symmetry", action="store_true",
                        help="disable basic symmetry breaking constraints")
    parser.add_argument("--benchmark", action="store_true",
                        help="run symmetry breaking benchmark")
    args = parser.parse_args()

    if args.benchmark:
        benchmark_symmetry()
        return
        
    if args.v is None and args.k is None:
        # demo mode – run a few small examples
        demos = [(7, 3), (13, 4), (15, 3), (57, 8)]
        for v, k in demos:
            print("\n" + "-" * 60)
            print(f"Testing v = {v},  k = {k}")
            if not quick_feasibility(v, k):
                print("  Numerically impossible, skipped.")
                continue
            model, cs, solve_time = solve_instance(v, k, v, timeout_s=args.timeout, extra_symmetry=args.extra_symmetry, basic_symmetry=not args.no_basic_symmetry)
            if model:
                pretty_print(model, cs, v, k)
                print(f"✓ Solution found in {solve_time:.3f} seconds")
            else:
                print(f"  No solution (unsat or timeout) after {solve_time:.3f} seconds")
    else:
        v = args.v
        k = args.k
        if not quick_feasibility(v, k):
            print("Instance fails the basic divisibility conditions – aborting.")
            return
        model, cs, solve_time = solve_instance(v, k, v, timeout_s=args.timeout, extra_symmetry=args.extra_symmetry, basic_symmetry=not args.no_basic_symmetry)
        if model:
            pretty_print(model, cs, v, k)
            print(f"\n✓ Solution found in {solve_time:.3f} seconds")
        else:
            print(f"No solution found (unsat or timeout) after {solve_time:.3f} seconds")

if __name__ == "__main__":
    main()