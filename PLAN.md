# Execution Plan

Goal: implement the generalized Spot It solver from the Notion outline as a
small, readable SMT modeling example.

Acceptance criteria:
- Keep the blog untouched.
- Model "Can you assign V animals to K cards so that every two cards share
  exactly lambda animals?" directly as card/animal assignment constraints.
- Return an example deck when the instance is satisfiable, not only a yes/no
  answer.
- Preserve a simple CLI for the original 57/55/8 Spot It parameters and for
  experiments such as lambda=2.
- Add validation helpers so tests can prove every card has the right size,
  optional animal coverage holds, and every card pair shares the requested
  lambda.

Commit sequence:
1. Checkpoint this Spot It implementation plan.
2. Replace the positional integer encoding with a clearer Boolean incidence
   matrix in `spotit.py`.
3. Add deterministic tests for satisfiable and unsatisfiable generalized cases,
   including a lambda=2 case.
4. Run syntax and Spot It correctness checks, then review before committing the
   implementation.
