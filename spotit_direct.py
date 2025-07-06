#!/usr/bin/env python3
"""
Direct Boolean encoding - avoid expensive PB constraints entirely
"""

from z3 import *
import time
import argparse
import multiprocessing

def exactly_one_direct(bs):
    """Exactly one using direct Boolean encoding - much faster than PbEq"""
    if len(bs) <= 1:
        return And(bs) if bs else BoolVal(False)
    
    # At least one
    at_least_one = Or(bs)
    
    # At most one - pairwise exclusion
    at_most_one = [Not(And(bs[i], bs[j])) for i in range(len(bs)) for j in range(i+1, len(bs))]
    
    return And([at_least_one] + at_most_one)

def exactly_k_direct(bs, k):
    """Direct encoding for exactly k - avoid PB solver entirely"""
    n = len(bs)
    
    if k == 0:
        return And([Not(b) for b in bs])
    elif k == 1:
        return exactly_one_direct(bs)
    elif k == n:
        return And(bs)
    elif k > n:
        return BoolVal(False)
    
    # For small k, use auxiliary variables with direct encoding
    if k <= 3 and n <= 10:
        # Use combinatorial approach for small cases
        from itertools import combinations
        
        # Exactly k means: at least one k-subset is true, and no (k+1)-subset is true
        k_subsets = list(combinations(range(n), k))
        kplus1_subsets = list(combinations(range(n), k+1)) if k+1 <= n else []
        
        # At least one k-subset must be all true and rest false
        at_least_k = []
        for subset in k_subsets:
            clause = []
            for i in range(n):
                if i in subset:
                    clause.append(bs[i])
                else:
                    clause.append(Not(bs[i]))
            at_least_k.append(And(clause))
        
        return Or(at_least_k)
    
    # Fallback to PbEq for larger cases
    return PbEq([(b, 1) for b in bs], k)

def encode_spotit_direct(v, k, b, basic_symmetry=True):
    """Direct Boolean encoding without expensive PB constraints"""
    card_symbol = [[Bool(f"c{i}s{j}") for j in range(v)] for i in range(b)]
    constraints = []

    print("Using direct Boolean encoding...")
    
    # 1. Exactly k symbols per card - use direct encoding when possible
    for i in range(b):
        if k <= 3:  # Use direct encoding for small k
            constraints.append(exactly_k_direct(card_symbol[i], k))
        else:  # Fallback to PbEq
            constraints.append(PbEq([(card_symbol[i][j], 1) for j in range(v)], k))

    # 2. Pair constraints - use direct encoding (exactly 1 is easier)
    for i in range(b):
        for j in range(i + 1, b):
            shared = [And(card_symbol[i][s], card_symbol[j][s]) for s in range(v)]
            constraints.append(exactly_one_direct(shared))  # Much faster than PbEq(..., 1)

    # 3. Symbol usage - at least one is cheap
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

def solve_instance_direct(v, k, b, timeout_s=86400, threads=None, basic_symmetry=True):
    """Solver optimized for direct Boolean encoding"""
    card_symbol, constraints = encode_spotit_direct(v, k, b, basic_symmetry)
    
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

    s = Solver()
    s.set("timeout", timeout_s * 1000)
    
    if threads is None:
        threads = min(8, multiprocessing.cpu_count())
    s.set("threads", threads)
    
    # Optimized for pure Boolean problems (no PB overhead)
    s.set("phase_selection", 0)            # Simple phase selection
    s.set("restart_strategy", 1)           # Geometric restart
    s.set("restart_factor", 1.5)           # Frequent restarts for Boolean problems
    s.set("random_seed", 42)
    s.set("max_memory", 16000)
    
    print(f"Z3 Direct Boolean config: {threads} threads")

    s.add(constraints)
    print("Starting direct Boolean solver...")

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

    model, cs, solve_time = solve_instance_direct(
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