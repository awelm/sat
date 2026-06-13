from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from typing import Optional, Sequence

from z3 import And, Bool, If, Not, Or, Solver, Sum, is_true, sat, unsat


Deck = list[list[int]]


@dataclass(frozen=True)
class SpotItResult:
    exists: bool | None
    method: str
    status: str
    deck: Deck


def solve_spotit_deck(
    total_animals: int,
    card_count: int,
    animals_per_card: Optional[int] = None,
    lambda_value: int = 1,
    require_all_animals: bool = True,
    timeout_ms: int = 0,
) -> SpotItResult:
    """Find a deck where every pair of cards shares exactly lambda animals."""
    invalid = _invalid_reason(
        total_animals,
        card_count,
        animals_per_card,
        lambda_value,
        require_all_animals,
    )
    if invalid is not None:
        return SpotItResult(False, invalid, "invalid", [])

    solver = Solver()
    solver.set("random_seed", 0)
    if timeout_ms > 0:
        solver.set("timeout", timeout_ms)

    cards = range(card_count)
    animals = range(total_animals)

    # Incidence matrix: card_has_animal[c][a] means card c contains animal a.
    card_has_animal = [
        [Bool(f"card_{card}_has_animal_{animal}") for animal in animals]
        for card in cards
    ]

    if animals_per_card is not None:
        for card in cards:
            solver.add(
                Sum(
                    [If(card_has_animal[card][animal], 1, 0) for animal in animals]
                )
                == animals_per_card
            )

        # Symmetry break: any satisfying deck can be renamed so card 0 contains
        # the first animals_per_card animals. This avoids equivalent searches.
        if card_count > 0:
            for animal in animals:
                if animal < animals_per_card:
                    solver.add(card_has_animal[0][animal])
                else:
                    solver.add(Not(card_has_animal[0][animal]))

    if require_all_animals:
        for animal in animals:
            solver.add(
                Or([card_has_animal[card][animal] for card in cards])
            )

    for left_card in cards:
        for right_card in range(left_card + 1, card_count):
            # This is the generalized Spot It rule. For normal Spot It,
            # lambda_value is 1; lambda_value=2 asks for two shared symbols.
            shared_animals = [
                If(
                    And(
                        card_has_animal[left_card][animal],
                        card_has_animal[right_card][animal],
                    ),
                    1,
                    0,
                )
                for animal in animals
            ]
            solver.add(Sum(shared_animals) == lambda_value)

    result = solver.check()
    if result == sat:
        deck = _deck_from_model(solver.model(), card_has_animal)
        validate_spotit_deck(
            deck,
            total_animals=total_animals,
            lambda_value=lambda_value,
            animals_per_card=animals_per_card,
            require_all_animals=require_all_animals,
        )
        return SpotItResult(True, "incidence matrix smt search", "sat", deck)
    if result == unsat:
        return SpotItResult(False, "incidence matrix smt search", "unsat", [])
    return SpotItResult(None, "incidence matrix smt search", "unknown", [])


def can_make_spotit_deck(
    total_animals: int,
    card_count: int,
    animals_per_card: int,
    lambda_value: int = 1,
    require_all_animals: bool = True,
    timeout_ms: int = 0,
) -> tuple[bool | None, str]:
    """Compatibility wrapper that preserves the old yes/no API."""
    result = solve_spotit_deck(
        total_animals=total_animals,
        card_count=card_count,
        animals_per_card=animals_per_card,
        lambda_value=lambda_value,
        require_all_animals=require_all_animals,
        timeout_ms=timeout_ms,
    )
    return result.exists, result.method


def validate_spotit_deck(
    deck: Deck,
    total_animals: int,
    lambda_value: int = 1,
    animals_per_card: Optional[int] = None,
    require_all_animals: bool = True,
) -> None:
    for card in deck:
        if len(card) != len(set(card)):
            raise AssertionError(f"card has a duplicate animal: {card}")
        if animals_per_card is not None and len(card) != animals_per_card:
            raise AssertionError(f"card has the wrong size: {card}")
        for animal in card:
            if not (0 <= animal < total_animals):
                raise AssertionError(f"animal is out of range: {animal}")

    if require_all_animals:
        used_animals = {animal for card in deck for animal in card}
        if used_animals != set(range(total_animals)):
            raise AssertionError("deck does not use every animal")

    for left_index, left_card in enumerate(deck):
        for right_card in deck[left_index + 1:]:
            shared_count = len(set(left_card) & set(right_card))
            if shared_count != lambda_value:
                raise AssertionError(
                    f"cards share {shared_count} animals instead of {lambda_value}: "
                    f"{left_card} {right_card}"
                )


def _invalid_reason(
    total_animals: int,
    card_count: int,
    animals_per_card: Optional[int],
    lambda_value: int,
    require_all_animals: bool,
) -> Optional[str]:
    if total_animals <= 0:
        return "invalid total_animals"
    if card_count < 0:
        return "invalid card_count"
    if animals_per_card is not None and animals_per_card < 0:
        return "invalid animals_per_card"
    if lambda_value < 0:
        return "invalid lambda_value"
    if lambda_value > total_animals:
        return "lambda larger than total animals"
    if animals_per_card is not None and animals_per_card > total_animals:
        return "more animals per card than total animals"
    if animals_per_card is not None and lambda_value > animals_per_card:
        return "lambda larger than fixed card size"
    if require_all_animals and card_count == 0:
        return "no cards available to use animals"
    if (
        require_all_animals
        and animals_per_card is not None
        and card_count * animals_per_card < total_animals
    ):
        return "not enough slots to use every animal"
    return None


def _deck_from_model(model, card_has_animal) -> Deck:
    deck: Deck = []
    for card in card_has_animal:
        deck.append(
            [
                animal
                for animal, present in enumerate(card)
                if is_true(model.evaluate(present, model_completion=True))
            ]
        )
    return deck


def _parse_args(argv: Optional[Sequence[str]]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Solve a generalized Spot It deck with Z3."
    )
    parser.add_argument("--animals", type=int, default=57)
    parser.add_argument("--cards", type=int, default=55)
    parser.add_argument("--animals-per-card", type=int, default=8)
    parser.add_argument(
        "--no-fixed-card-size",
        action="store_true",
        help="omit the per-card size constraint",
    )
    parser.add_argument("--lambda-value", type=int, default=1)
    parser.add_argument(
        "--require-all-animals",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--timeout-ms", type=int, default=0)
    parser.add_argument("--show-deck", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = _parse_args(argv)
    animals_per_card = None if args.no_fixed_card_size else args.animals_per_card
    result = solve_spotit_deck(
        total_animals=args.animals,
        card_count=args.cards,
        animals_per_card=animals_per_card,
        lambda_value=args.lambda_value,
        require_all_animals=args.require_all_animals,
        timeout_ms=args.timeout_ms,
    )
    output = {
        "animals": args.animals,
        "cards": args.cards,
        "animals_per_card": animals_per_card,
        "lambda_value": args.lambda_value,
        "require_all_animals": args.require_all_animals,
        "exists": result.exists,
        "status": result.status,
        "method": result.method,
    }
    if args.show_deck and result.deck:
        output["deck"] = result.deck
    print(json.dumps(output, sort_keys=True))


if __name__ == "__main__":
    main()
