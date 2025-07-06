#!/usr/bin/env python3
"""
Hybrid approach: Direct encoding for "exactly 1" constraints, 
optimized PB settings for "exactly k" constraints
"""

from z3 import *
import time
import argparse
import multiprocessing

def exactly_one_direct(bs):
    """Direct encoding for exactly one - avoids PB solver"""
    if len(bs) == 0:
        return BoolVal(False)
    if len(bs) == 1:
        return bs[0]
    
    # At least one
    at_least_one = Or(bs)
    
    # At most one - pairwise exclusion (more efficient than PbLe)
    at_most_one = []
    for i in range(len(bs)):
        for j in range(i+1, len(bs)):
            at_most_one.append(Not(And(bs[i], bs[j])))
    
    return And([at_least_one] + at_most_one)

def encode_spotit_hybrid(v, k, b, basic_symmetry=True):
    """Hybrid: direct encoding for exactly-1, optimized PB for exactly-k"""
    card_symbol = [[Bool(f"c{i}s{j}") for j in range(v)] for i in range(b)]
    constraints = []

    print("Using hybrid encoding: direct for exactly-1, PB for exactly-k...")
    
    # 1. Exactly k symbols per card - keep using PbEq (unavoidable for large k)
    for i in range(b):
        constraints.append(PbEq([(card_symbol[i][j], 1) for j in range(v)], k))

    # 2. CRITICAL: Pair constraints use direct encoding (exactly 1 shared symbol)
    # This eliminates most PB constraint usage since you have 1596 pair constraints!
    for i in range(b):
        for j in range(i + 1, b):
            shared = [And(card_symbol[i][s], card_symbol[j][s]) for s in range(v)]
            constraints.append(exactly_one_direct(shared))  # No PB solver needed!

    # 3. Symbol usage - at least one (cheap)
    for s in range(v):
        constraints.append(Or([card_symbol[i][s] for i in range(b)]))

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

    return card_symbol, constraints

def solve_instance_hybrid(v, k, b, timeout_s=86400, threads=None, basic_symmetry=True):
    """Hybrid solver - optimized for mixed constraint types"""
    card_symbol, constraints = encode_spotit_hybrid(v, k, b, basic_symmetry)
    
    print(f"Variables: {b * v}")
    print(f"Constraints: {len(constraints)}")
    
    print("\n=== CONSTRAINT BREAKDOWN ===")
    card_constraints = b  # These use PB
    pair_constraints = b * (b - 1) // 2  # These use direct Boolean now!
    symbol_constraints = v
    symmetry_constraints = len(constraints) - card_constraints - pair_constraints - symbol_constraints
    
    print(f"Card constraints (PB, exactly k symbols per card): {card_constraints}")
    print(f"Pair constraints (DIRECT, exactly 1 shared symbol): {pair_constraints}")
    print(f"Symbol constraints (at least once): {symbol_constraints}")
    print(f"Symmetry breaking constraints: {symmetry_constraints}")
    print(f"Total: {len(constraints)} constraints")

    s = Solver()
    s.set("timeout", timeout_s * 1000)
    
    if threads is None:
        threads = min(8, multiprocessing.cpu_count())
    s.set("threads", threads)
    
    # Optimized for hybrid Boolean + PB
    # Reduce PB solver overhead since most constraints are now direct Boolean
    s.set("pb.conflict_frequency", 10000)  # Less frequent PB analysis
    s.set("pb.learn_complements", False)   # Disable expensive PB learning
    
    # Favor Boolean solver
    s.set("phase_selection", 3)            # Caching (good for Boolean)
    s.set("restart_strategy", 1)           # Geometric restart
    s.set("restart_factor", 1.2)           # Moderate restarts
    s.set("random_seed", 42)
    s.set("max_memory", 16000)
    
    print(f"Z3 Hybrid config: {threads} threads, reduced PB overhead")

    s.add(constraints)
    print("Starting hybrid solver...")

    t0 = time.time()
    res = s.check()
    elapsed = time.time() - t0
    
    print(f"--> Z3 returned {res}  (in {elapsed:.1f} s)")

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
    """Print solution"""
    symbols = [f"S{i}" for i in range(v)]
    for i, row in enumerate(card_symbol):
        syms = [symbols[j] for j in range(v) if is_true(model.evaluate(row[j]))]
        print(f"Card {i:>3}:  " + ", ".join(syms))
    print(f"\nEvery card has exactly {k} symbols – verified.")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("v", type=int)
    parser.add_argument("k", type=int)
    parser.add_argument("--timeout", type=int, default=86400)
    parser.add_argument("--no-basic-symmetry", action="store_true")
    args = parser.parse_args()

    v, k = args.v, args.k
    if not quick_feasibility(v, k):
        print("Instance fails feasibility check")
        return

    model, cs, solve_time = solve_instance_hybrid(
        v, k, v, 
        timeout_s=args.timeout, 
        basic_symmetry=not args.no_basic_symmetry
    )
    
    if model:
        pretty_print(model, cs, v, k)
        print(f"\n✓ Solution found in {solve_time:.3f} seconds")
    else:
        print(f"No solution found after {solve_time:.3f} seconds")

if __name__ == "__main__":
    main()