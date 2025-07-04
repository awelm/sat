#!/usr/bin/env python3
"""
Z3 SAT solver for generalized Spot It! card game assignment problem.

Given v distinct pictures and k pictures per card, find an arrangement
where any two cards share exactly one picture.
"""

from z3 import *
from math import comb
import time
import threading
import sys

# Configure Z3 global parameters for maximum performance
set_param('parallel.enable', True)
set_param('parallel.threads.max', 32)  # Max CPU utilization

def solve_generalized_spotit(v, k, max_cards=None, timeout_ms=300000):
    """
    Solve the generalized Spot It problem using Z3.
    
    Args:
        v: Number of distinct pictures (symbols) available
        k: Number of pictures per card (must be >= 2)
        max_cards: Maximum number of cards to try (if None, calculate optimal)
        timeout_ms: Timeout in milliseconds (currently unused)
        
    Returns:
        dict: Assignment of symbols to cards if satisfiable, None otherwise
    """
    
    if k < 2:
        print("Error: k must be >= 2 for meaningful Spot It problem")
        return None
    
    if v < k:
        print(f"Error: Cannot put {k} pictures per card when only {v} pictures exist")
        return None
    
    print(f"=== GENERALIZED SPOT IT SOLVER ===")
    print(f"Pictures available (v): {v}")
    print(f"Pictures per card (k): {k}")
    
    # Calculate search bounds - limit to V cards 
    max_possible_cards = comb(v, k)
    if max_cards is None:
        max_cards = v  # Limit to number of symbols
    
    print(f"Maximum possible distinct cards: {max_possible_cards}")
    print(f"Trying up to {max_cards} cards (limited to v)")
    
    # Try different numbers of cards, starting from minimum feasible
    min_cards = k + 1  # Need at least k+1 cards for meaningful problem
    
    for num_cards in range(min_cards, min(max_cards + 1, max_possible_cards + 1)):
        print(f"\n--- Trying {num_cards} cards ---")
        
        if not is_feasible(v, k, num_cards):
            print(f"  Skipping {num_cards} cards - mathematically infeasible")
            continue
            
        result = solve_with_parameters(v, k, num_cards)
        if result is not None:
            print(f"\n🎉 SOLUTION FOUND with {num_cards} cards!")
            return result
            
        print(f"  No solution with {num_cards} cards")
    
    print(f"\n❌ No solution found for v={v}, k={k} up to {max_cards} cards")
    return None

def is_feasible(v, k, b):
    """Check if parameters v, k, b could theoretically work."""
    # Each symbol appears in exactly r cards, where r = bk/v must be integer
    if (b * k) % v != 0:
        return False
    
    r = (b * k) // v
    
    # Any two symbols appear together in exactly λ cards, where λ = r(k-1)/(v-1) must be integer
    if v > 1:
        if (r * (k - 1)) % (v - 1) != 0:
            return False
    
    return True

def solve_with_parameters(v, k, b):
    """Solve Spot It with specific parameters using Z3."""
    
    print(f"  Solving: {b} cards, {v} symbols, {k} symbols per card")
    
    # Use highly optimized solver based on problem analysis
    solver = Solver()
    
    # Maximum resource allocation - no limits!
    solver.set("max_memory", 64000)    # 64GB memory limit
    solver.set("max_steps", 4294967295)
    solver.set("proof", False)  # Disable proof generation for speed
    solver.set("model", True)   # We need models
    
    # High-performance solver settings
    solver.set("phase_selection", 3)    # Best phase selection
    solver.set("restart_strategy", 1)   # Optimal restart strategy  
    solver.set("restart.max", 4294967295)  # No restart limits
    solver.set("random_seed", 42)       # Good seed
    solver.set("threads", 32)           # Max CPU threads
    
    print(f"  Configured solver for hard {b}-card problem")
    
    # Variables: card_symbol[i][j] = True if card i contains symbol j
    card_symbol = [[Bool(f"c{i}s{j}") for j in range(v)]  # Shorter variable names
                   for i in range(b)]
    
    # For large problems, use more efficient constraint encoding
    if b >= 20:  # Large problem optimizations
        print("  Using optimized encoding for large problem...")
        
        # Constraint 1: Each card has exactly k symbols (cardinality constraint)
        for i in range(b):
            solver.add(Sum([If(card_symbol[i][j], 1, 0) for j in range(v)]) == k)
        
        # Constraint 2: Any two cards share exactly one symbol (optimized with auxiliary variables)
        shared_vars = {}
        for i in range(b):
            for j in range(i + 1, b):
                # Create auxiliary variables for shared symbols
                shared_symbols = []
                for l in range(v):
                    shared_var = Bool(f"shared_{i}_{j}_{l}")
                    solver.add(shared_var == And(card_symbol[i][l], card_symbol[j][l]))
                    shared_symbols.append(shared_var)
                
                # Exactly one shared symbol
                solver.add(Sum([If(sv, 1, 0) for sv in shared_symbols]) == 1)
    else:
        # Standard encoding for smaller problems
        # Constraint 1: Each card has exactly k symbols (more efficient encoding)
        for i in range(b):
            # Use PbEq for pseudo-boolean constraints - more efficient than Sum/If
            solver.add(PbEq([(card_symbol[i][j], 1) for j in range(v)], k))
        
        # Constraint 2: Any two cards share exactly one symbol (optimized)
        for i in range(b):
            for j in range(i + 1, b):
                # More efficient: direct pseudo-boolean constraint
                solver.add(PbEq([(And(card_symbol[i][l], card_symbol[j][l]), 1) for l in range(v)], 1))
    
    # Constraint 3: Each symbol appears on at least 1 card (optimized)
    for j in range(v):
        solver.add(Or([card_symbol[i][j] for i in range(b)]))  # More direct encoding
    
    # Symmetry breaking constraints (optimized)
    print("  Adding symmetry breaking constraints...")
    
    # Fix first card to contain first k symbols (batch constraints)
    first_card_constraints = []
    for j in range(k):
        first_card_constraints.append(card_symbol[0][j])
    for j in range(k, v):
        first_card_constraints.append(Not(card_symbol[0][j]))
    solver.add(And(first_card_constraints))
    
    # Second card constraints (batch)
    if b > 1:
        second_card_constraints = [card_symbol[1][0]]  # Must share symbol 0
        used_count = 0
        for j in range(k, v):
            if used_count < k - 1:
                second_card_constraints.append(card_symbol[1][j])
                used_count += 1
            else:
                second_card_constraints.append(Not(card_symbol[1][j]))
        solver.add(And(second_card_constraints))
    
    # Simplified lexicographic ordering (less complex constraints)
    for i in range(min(2, b - 1)):  # Reduce to first 2 cards only
        for j in range(min(v, 10)):  # Limit constraint complexity
            if j > 0:
                solver.add(Implies(And([Not(card_symbol[i][l]) for l in range(j)]),
                                 Implies(card_symbol[i+1][j], Not(card_symbol[i][j]))))
    
    print(f"  Added optimized symmetry breaking")
    
    # Debug info
    print(f"  Created {b * v} boolean variables")
    print(f"  Total constraints: {b + b * (b - 1) // 2 + v}")
    
    # Solve with progress tracking
    print("  Starting Z3 solve...")
    print("  Detailed progress will be shown every 5 seconds...")
    start_time = time.time()
    
    # Progress tracker with detailed stats
    solving = [True]  # Use list for mutable reference
    last_stats = {}
    
    def progress_tracker():
        nonlocal last_stats
        while solving[0]:
            time.sleep(5)  # Check every 5 seconds
            if solving[0]:
                total_elapsed = time.time() - start_time
                
                # Get current solver statistics
                try:
                    current_stats = solver.statistics()
                    stats_dict = {}
                    for i in range(len(current_stats)):
                        key, value = current_stats[i]
                        stats_dict[key] = value
                    
                    # Show progress metrics
                    conflicts = stats_dict.get('conflicts', 0)
                    decisions = stats_dict.get('decisions', 0)
                    propagations = stats_dict.get('propagations', 0)
                    memory = stats_dict.get('memory', 0)
                    
                    # Calculate rates since last check
                    conflict_rate = ""
                    decision_rate = ""
                    if last_stats:
                        conflict_delta = conflicts - last_stats.get('conflicts', 0)
                        decision_delta = decisions - last_stats.get('decisions', 0)
                        if conflict_delta > 0:
                            conflict_rate = f" (+{conflict_delta}/5s)"
                        if decision_delta > 0:
                            decision_rate = f" (+{decision_delta}/5s)"
                    
                    # Adaptive reporting based on problem hardness
                    if b >= 50:  # Very hard problems
                        # Show rates and efficiency metrics
                        prop_per_conflict = propagations / max(conflicts, 1)
                        decision_per_conflict = decisions / max(conflicts, 1)
                        
                        print(f"  [{total_elapsed:3.0f}s] Conflicts: {conflicts:,}{conflict_rate} | "
                              f"Decisions: {decisions:,}{decision_rate} | "
                              f"Memory: {memory:.1f}MB")
                        print(f"        Efficiency: {prop_per_conflict:.0f} props/conflict, "
                              f"{decision_per_conflict:.1f} decisions/conflict")
                        
                        # Suggest if Z3 might be struggling
                        if conflicts > 0 and total_elapsed > 60:
                            conflict_per_sec = conflicts / total_elapsed
                            if conflict_per_sec < 100:  # Very slow progress
                                print(f"        Warning: Low conflict rate ({conflict_per_sec:.1f}/s) - problem may be very hard")
                                
                                # Suggest stopping if efficiency gets very bad
                                if total_elapsed > 180 and prop_per_conflict > 15000:
                                    print(f"        Suggestion: Consider stopping - efficiency very low ({prop_per_conflict:.0f} props/conflict)")
                                    
                                # Suggest alternative approaches
                                if total_elapsed > 300 and conflict_per_sec < 30:
                                    print(f"        Suggestion: Z3 may be stuck - consider different approach or smaller problem")
                    else:
                        print(f"  [{total_elapsed:3.0f}s] Conflicts: {conflicts:,}{conflict_rate} | "
                              f"Decisions: {decisions:,}{decision_rate} | "
                              f"Propagations: {propagations:,} | "
                              f"Memory: {memory:.1f}MB")
                    
                    last_stats = stats_dict.copy()
                    
                except Exception as e:
                    # Fallback to simple timer if stats unavailable
                    print(f"  [{total_elapsed:3.0f}s] Z3 working... (stats unavailable)")
                
                sys.stdout.flush()
    
    # Start progress tracker in background
    progress_thread = threading.Thread(target=progress_tracker, daemon=True)
    progress_thread.start()
    
    # Pre-simplify constraints before main solve
    solver.push()  # Save state for potential backtracking
    result = solver.check()
    elapsed = time.time() - start_time
    
    # Stop progress tracker
    solving[0] = False
    
    print(f"  Z3 result: {result}")
    print(f"  Solving time: {elapsed:.2f}s")
    
    # Print solver statistics
    stats = solver.statistics()
    if stats:
        print("  Z3 Statistics:")
        for i in range(len(stats)):
            key, value = stats[i]
            print(f"    {key}: {value}")
    else:
        print("  No statistics available")
    
    if result == sat:
        print(f"  ✅ Solution found!")
        model = solver.model()
        solution = {}
        # Optimized solution extraction
        for i in range(b):
            card_symbols = [j for j in range(v) if is_true(model.evaluate(card_symbol[i][j]))]
            solution[f"card_{i}"] = card_symbols
        solver.pop()  # Clean up
        return solution
    elif result == unsat:
        print(f"  ❌ Proven unsatisfiable")
        solver.pop()
        return None
    else:
        print(f"  ❓ Unknown result")
        solver.pop()
        return None

def print_solution(solution, v):
    """Pretty print the solution with symbol names."""
    if solution is None:
        print("No solution to display")
        return
    
    # Generate symbol names
    if v <= 8:
        symbols = ["Dog", "Cat", "Bird", "Fish", "Horse", "Cow", "Pig", "Sheep"][:v]
    else:
        symbols = [f"Symbol_{i}" for i in range(v)]
        
    print("\n=== GENERALIZED SPOT IT SOLUTION ===")
    symbols_per_card = len(list(solution.values())[0]) if solution else 0
    print(f"Each card contains exactly {symbols_per_card} symbols")
    print(f"Any two cards share exactly 1 symbol in common")
    print()
    
    for card_name in sorted(solution.keys(), key=lambda x: int(x.split('_')[1])):
        card_num = int(card_name.split('_')[1])
        symbol_indices = solution[card_name]
        symbol_names = [symbols[i] for i in sorted(symbol_indices)]
        print(f"Card {card_num:2d}: {', '.join(symbol_names)}")

def verify_solution(solution):
    """Verify that the solution satisfies all Spot It constraints."""
    if solution is None:
        return False
        
    cards = list(solution.values())
    num_cards = len(cards)
    
    print(f"\n=== VERIFICATION ===")
    print(f"Number of cards: {num_cards}")
    
    # Check each card has the expected number of symbols
    expected_symbols = len(cards[0]) if cards else 0
    for i, card in enumerate(cards):
        if len(card) != expected_symbols:
            print(f"ERROR: Card {i} has {len(card)} symbols, expected {expected_symbols}")
            return False
    print(f"✓ Each card has exactly {expected_symbols} symbols")
    
    # Check any two cards share exactly one symbol
    violations = 0
    for i in range(num_cards):
        for j in range(i + 1, num_cards):
            shared = len(set(cards[i]) & set(cards[j]))
            if shared != 1:
                print(f"ERROR: Cards {i} and {j} share {shared} symbols, expected 1")
                violations += 1
                if violations > 10:
                    print("... (more violations)")
                    break
        if violations > 10:
            break
    
    if violations == 0:
        print("✓ Any two cards share exactly one symbol")
        return True
    else:
        print(f"✗ Found {violations} constraint violations")
        return False

def run_test_cases():
    """Run some known solvable test cases."""
    print("=== RUNNING TEST CASES ===\n")
    
    test_cases = [
        (7, 3),   # Fano plane: 7 points, 3 per line
        (13, 4),  # 13 points, 4 per line  
        (6, 3),   # Simple case
        (8, 4),   # Might work
        (15, 3),  # Another test
    ]
    
    for v, k in test_cases:
        print(f"\n{'='*50}")
        print(f"TEST CASE: v={v}, k={k}")
        print(f"{'='*50}")
        
        solution = solve_generalized_spotit(v, k, max_cards=30, timeout_ms=10000)
        
        if solution:
            print_solution(solution, v)
            is_valid = verify_solution(solution)
            if is_valid:
                print(f"✅ Test case v={v}, k={k} PASSED")
            else:
                print(f"❌ Test case v={v}, k={k} FAILED verification")
        else:
            print(f"❌ Test case v={v}, k={k} - No solution found")
        
        print(f"{'='*50}\n")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) == 1:
        run_test_cases()
    elif len(sys.argv) == 3:
        v = int(sys.argv[1])
        k = int(sys.argv[2])
        
        print(f"Solving generalized Spot It with v={v}, k={k}")
        solution = solve_generalized_spotit(v, k)
        
        if solution:
            print_solution(solution, v)
            is_valid = verify_solution(solution)
            if is_valid:
                print("\n🎉 Solution is valid!")
            else:
                print("\n❌ Solution has errors")
        else:
            print("\n❌ No solution found")
    else:
        print("Usage:")
        print("  python spotit.py              # Run test cases")
        print("  python spotit.py <v> <k>      # Solve for specific v, k")
        print("  Example: python spotit.py 7 3")