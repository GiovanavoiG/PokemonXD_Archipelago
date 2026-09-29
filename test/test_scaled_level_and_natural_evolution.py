"""Regression coverage for two ADDENDUM 100 changes that had no dedicated test file yet:

1. `enhanced_difficulty._scaled_level()` -- the player's "Change the difficulty enhancement to make the
   pokemon 1.33x their level instead - round down if it's not a whole number" request, replacing the old flat
   `+3` level boost.
2. `team_shuffle.resolve_natural_evolution()` -- the player's "add logic to the randomization to use the
   highest possible evolution at that level - for example, if a trainer WOULD randomize to a level 70
   houndour, instead make it a houndoom" request.

Both were implemented and wired up earlier in this addendum but only verified via static grep of the existing
suite, never with dedicated unit tests -- this file closes that gap."""
from __future__ import annotations

import unittest

from ..randomizer.enhanced_difficulty import ENHANCED_DIFFICULTY_LEVEL_MULTIPLIER, _scaled_level
from ..randomizer.team_shuffle import Species, resolve_natural_evolution


class TestScaledLevel(unittest.TestCase):
    def test_rounds_down_a_non_whole_result(self) -> None:
        # The player's own example: 1.33x, round down if not whole.
        self.assertEqual(_scaled_level(30, 1.33), 39)  # 39.9 -> 39
        self.assertEqual(_scaled_level(50, 1.33), 66)  # 66.5 -> 66

    def test_exact_whole_number_result_is_unaffected(self) -> None:
        self.assertEqual(_scaled_level(100, 2.0), 100)  # would clamp anyway, but exactly whole
        self.assertEqual(_scaled_level(20, 1.5), 30)  # exactly 30.0

    def test_clamped_to_the_real_1_to_100_level_range(self) -> None:
        self.assertEqual(_scaled_level(90, 1.33), 100)  # 119.7 floors to 119, clamps to 100
        self.assertEqual(_scaled_level(0, 1.33), 1)  # floors to 0, clamps up to the real minimum

    def test_default_multiplier_is_1_33(self) -> None:
        self.assertEqual(ENHANCED_DIFFICULTY_LEVEL_MULTIPLIER, 1.33)

    def test_never_rounds_up(self) -> None:
        # A case where plain `round()` would go up (66.5 rounds to 66 or 67 depending on banker's rounding)
        # must still floor down, confirming this isn't accidentally using round().
        self.assertEqual(_scaled_level(50, 1.33), 66)


def _species(evolves_into: int | None, evolves_at_level: int | None) -> Species:
    return Species(
        species_id=0,  # unused by resolve_natural_evolution -- it looks the species up by the pool's dict key
        is_legendary=False,
        evolves_into=evolves_into,
        evolves_at_level=evolves_at_level,
    )


class TestResolveNaturalEvolution(unittest.TestCase):
    def _houndour_chain(self) -> dict[int, Species]:
        # Mirrors the player's own example: Houndour (evolves at 24) -> Houndoom (final form).
        return {
            1: _species(evolves_into=2, evolves_at_level=24),  # Houndour
            2: _species(evolves_into=None, evolves_at_level=None),  # Houndoom
        }

    def test_the_players_own_example_houndour_to_houndoom(self) -> None:
        self.assertEqual(resolve_natural_evolution(1, 70, self._houndour_chain()), 2)

    def test_stays_unevolved_below_the_threshold(self) -> None:
        self.assertEqual(resolve_natural_evolution(1, 23, self._houndour_chain()), 1)

    def test_evolves_exactly_at_the_threshold_level(self) -> None:
        self.assertEqual(resolve_natural_evolution(1, 24, self._houndour_chain()), 2)

    def test_species_with_no_evolution_data_is_returned_unchanged(self) -> None:
        pool = {5: _species(evolves_into=None, evolves_at_level=None)}
        self.assertEqual(resolve_natural_evolution(5, 100, pool), 5)

    def test_multi_stage_chain_walks_as_far_as_level_allows(self) -> None:
        # Charmander(16)->Charmeleon(36)->Charizard.
        pool = {
            10: _species(evolves_into=11, evolves_at_level=16),
            11: _species(evolves_into=12, evolves_at_level=36),
            12: _species(evolves_into=None, evolves_at_level=None),
        }
        self.assertEqual(resolve_natural_evolution(10, 15, pool), 10)   # too low to evolve at all
        self.assertEqual(resolve_natural_evolution(10, 20, pool), 11)  # first stage only
        self.assertEqual(resolve_natural_evolution(10, 40, pool), 12)  # both stages

    def test_unknown_species_id_is_returned_unchanged(self) -> None:
        self.assertEqual(resolve_natural_evolution(999, 100, {}), 999)

    def test_defensively_bounded_against_a_cyclic_pool(self) -> None:
        # Should never be produced by real evolution_data.py, but resolve_natural_evolution's 6-iteration cap
        # must still terminate rather than looping forever if the pool were ever malformed.
        pool = {
            1: _species(evolves_into=2, evolves_at_level=1),
            2: _species(evolves_into=1, evolves_at_level=1),
        }
        result = resolve_natural_evolution(1, 100, pool)
        self.assertIn(result, (1, 2))


if __name__ == "__main__":
    unittest.main()
