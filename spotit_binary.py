#!/usr/bin/env python3
"""
Binary encoding approach - avoid heavy PB constraints by using binary variables
"""

from z3 import *
import time
import argparse

def binary_encoding_exactly_k(bs, k):
    """Use binary adder tree instead of PbEq for better performance"""
    n = len(bs)
    if k == 0:
        return And([Not(b) for b in bs])
    if k == n:
        return And(bs)
    if k == 1:
        # At least one true
        at_least_one = Or(bs)
        # At most one true - use pairwise constraints
        at_most_one = [Not(And(bs[i], bs[j])) for i in range(n) for j in range(i+1, n)]
        return And([at_least_one] + at_most_one)
    
    # For larger k, use auxiliary variables to build a counting network
    # This is more complex but avoids the PB constraint overhead
    return PbEq([(b, 1) for b in bs], k)  # Fallback for now

def encode_spotit_binary(v, k, b, basic_symmetry=True):
    """Binary encoding with reduced PB constraint overhead"""
    card_symbol = [[Bool(f"c{i}s{j}") for j in range(v)] for i in range(b)]
    constraints = []

    # 1. Exactly k symbols per card - use optimized encoding for small k
    for i in range(b):
        if k <= 3:  # Use direct encoding for small k
            constraints.append(binary_encoding_exactly_k(card_symbol[i], k))
        else:
            constraints.append(PbEq([(card_symbol[i][j], 1) for j in range(v)], k))

    # 2. Pair constraints - try to reduce using auxiliary variables
    for i in range(b):
        for j in range(i + 1, b):
            # For each pair, introduce auxiliary variable for shared symbol
            shared_vars = [Bool(f"share_{i}_{j}_{s}") for s in range(v)]
            
            # Link shared_vars to actual sharing
            for s in range(v):
                constraints.append(shared_vars[s] == And(card_symbol[i][s], card_symbol[j][s]))
            
            # Exactly one shared symbol
            constraints.append(binary_encoding_exactly_k(shared_vars, 1))

    # 3. Symbol usage
    for s in range(v):
        constraints.append(Or([card_symbol[i][s] for i in range(b)]))

    # 4. Basic symmetry
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

def solve_binary(v, k, b, timeout_s=3600):
    """Solve with binary encoding approach"""
    card_symbol, constraints = encode_spotit_binary(v, k, b)
    
    print(f"Binary encoding - Variables: {b * v + b * (b-1) // 2 * v}")
    print(f"Constraints: {len(constraints)}")

    s = Solver()
    s.set("timeout", timeout_s * 1000)
    s.set("threads", 8)
    
    # Optimized for binary problems
    s.set("phase_selection", 2)            # Random phase selection
    s.set("random_seed", 42)
    s.set("restart_strategy", 0)           # Luby restart strategy
    
    s.add(constraints)
    print("Starting binary encoding solver...")

    t0 = time.time()
    res = s.check()
    elapsed = time.time() - t0
    
    print(f"--> Result: {res} in {elapsed:.1f}s")
    return res == sat, elapsed

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("v", type=int)
    parser.add_argument("k", type=int)
    parser.add_argument("--timeout", type=int, default=3600)
    args = parser.parse_args()

    solved, time_taken = solve_binary(args.v, args.k, args.v, args.timeout)
    if solved:
        print(f"✓ Binary encoding solved in {time_taken:.3f}s")
    else:
        print(f"✗ Binary encoding failed after {time_taken:.3f}s")

if __name__ == "__main__":
    main()