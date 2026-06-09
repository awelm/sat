# Execution Plan

Goal: make the SMT TSP example read more like "choose edges in an adjacency
matrix, then ask Z3 to find the best valid tour" while preserving a clear
performance lead over `dp.py`.

Acceptance criteria:
- Keep the blog untouched.
- Preserve exact TSP answers, including the required city/day variant.
- Keep small iteration tests fast; run the full n=30 sweep only after the code
  is reviewed and the focused benchmark still looks good.
- Prefer readability over peak speed, but do not keep changes that lose the
  relaxed >5x lead once DP becomes slow.

Commit sequence:
1. Checkpoint the existing simplification baseline.
2. Explore matrix-shaped SMT formulations and identify the smallest readable
   version that keeps the focused benchmark healthy.
3. Implement the chosen simplification in `smt.py` with minimal harness changes.
4. Run correctness checks, focused benchmarks, reviewer subagent loops, then the
   full n=30 benchmark only if the focused checks pass.
