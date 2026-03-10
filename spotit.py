from __future__ import annotations

import chz
from z3 import If, Int, Or, Solver, Sum, sat, unsat


def can_make_spotit_deck(
    total_animals: int,
    card_count: int,
    animals_per_card: int,
    lambda_value: int = 1,
    require_all_animals: bool = True,
    timeout_ms: int = 0,
) -> tuple[bool | None, str]:
    if total_animals <= 0 or card_count < 0 or animals_per_card < 0:
        return False, "invalid parameters"
    if animals_per_card > total_animals:
        return False, "more animals per card than total animals"
    if lambda_value < 0 or lambda_value > animals_per_card:
        return False, "invalid lambda"
    if require_all_animals and card_count * animals_per_card < total_animals:
        return False, "not enough slots to use every animal"

    solver = Solver()
    solver.set("threads", 8)
    solver.set("random_seed", 0)
    if timeout_ms > 0:
        solver.set("timeout", timeout_ms)

    cards = [
        [Int(f"card_{card_index}_{position}") for position in range(animals_per_card)]
        for card_index in range(card_count)
    ]

    for card_index in range(card_count):
        for position in range(animals_per_card):
            solver.add(
                cards[card_index][position] >= 0,
                cards[card_index][position] < total_animals,
            )
        for position in range(animals_per_card - 1):
            solver.add(cards[card_index][position] < cards[card_index][position + 1])

    if card_count > 0:
        for position in range(animals_per_card):
            solver.add(cards[0][position] == position)

    if lambda_value == 1 and card_count > 1:
        for card_index in range(1, card_count):
            solver.add(
                Sum(
                    [
                        If(
                            Or(
                                [
                                    cards[card_index][position] == animal_index
                                    for position in range(animals_per_card)
                                ]
                            ),
                            1,
                            0,
                        )
                        for animal_index in range(animals_per_card)
                    ]
                )
                == 1
            )

    if require_all_animals:
        for animal_index in range(total_animals):
            solver.add(
                Or(
                    [
                        cards[card_index][position] == animal_index
                        for card_index in range(card_count)
                        for position in range(animals_per_card)
                    ]
                )
            )

    for left_card in range(card_count):
        for right_card in range(left_card + 1, card_count):
            solver.add(
                Sum(
                    [
                        If(cards[left_card][left_position] == cards[right_card][right_position], 1, 0)
                        for left_position in range(animals_per_card)
                        for right_position in range(animals_per_card)
                    ]
                )
                == lambda_value
            )

    result = solver.check()
    if result == sat:
        return True, "generic smt search"
    if result == unsat:
        return False, "generic smt search"
    return None, "generic smt search"


def main(
    animals: int = 57,
    cards: int = 55,
    animals_per_card: int = 8,
    lambda_value: int = 1,
    require_all_animals: bool = True,
    timeout_ms: int = 0,
) -> None:
    exists, method = can_make_spotit_deck(
        total_animals=animals,
        card_count=cards,
        animals_per_card=animals_per_card,
        lambda_value=lambda_value,
        require_all_animals=require_all_animals,
        timeout_ms=timeout_ms,
    )
    print(
        {
            "animals": animals,
            "cards": cards,
            "animals_per_card": animals_per_card,
            "lambda_value": lambda_value,
            "require_all_animals": require_all_animals,
            "exists": exists,
            "method": method,
        }
    )


if __name__ == "__main__":
    chz.entrypoint(main)
