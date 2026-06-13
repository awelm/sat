from __future__ import annotations

import unittest

from spotit import (
    can_make_spotit_deck,
    solve_spotit_deck,
    validate_spotit_deck,
)


class SpotItTests(unittest.TestCase):
    def assert_valid_result(
        self,
        *,
        total_animals: int,
        card_count: int,
        animals_per_card: int | None,
        lambda_value: int,
        require_all_animals: bool = True,
    ) -> None:
        result = solve_spotit_deck(
            total_animals=total_animals,
            card_count=card_count,
            animals_per_card=animals_per_card,
            lambda_value=lambda_value,
            require_all_animals=require_all_animals,
            timeout_ms=10_000,
        )
        self.assertIs(result.exists, True)
        self.assertEqual(len(result.deck), card_count)
        validate_spotit_deck(
            result.deck,
            total_animals=total_animals,
            lambda_value=lambda_value,
            animals_per_card=animals_per_card,
            require_all_animals=require_all_animals,
        )

    def test_fano_plane_size_is_satisfiable(self) -> None:
        self.assert_valid_result(
            total_animals=7,
            card_count=7,
            animals_per_card=3,
            lambda_value=1,
        )

    def test_lambda_two_can_be_satisfiable(self) -> None:
        self.assert_valid_result(
            total_animals=6,
            card_count=4,
            animals_per_card=3,
            lambda_value=2,
        )

    def test_lambda_two_unsat_case(self) -> None:
        result = solve_spotit_deck(
            total_animals=5,
            card_count=4,
            animals_per_card=3,
            lambda_value=2,
            timeout_ms=10_000,
        )
        self.assertIs(result.exists, False)
        self.assertEqual(result.status, "unsat")

    def test_no_fixed_card_size_mode(self) -> None:
        self.assert_valid_result(
            total_animals=4,
            card_count=3,
            animals_per_card=None,
            lambda_value=2,
        )

    def test_compatibility_wrapper_still_returns_yes_no_and_method(self) -> None:
        exists, method = can_make_spotit_deck(
            total_animals=7,
            card_count=7,
            animals_per_card=3,
            lambda_value=1,
            timeout_ms=10_000,
        )
        self.assertIs(exists, True)
        self.assertIn("smt", method)

    def test_invalid_lambda_is_rejected_before_z3(self) -> None:
        result = solve_spotit_deck(
            total_animals=5,
            card_count=3,
            animals_per_card=2,
            lambda_value=3,
        )
        self.assertIs(result.exists, False)
        self.assertEqual(result.status, "invalid")


if __name__ == "__main__":
    unittest.main()
