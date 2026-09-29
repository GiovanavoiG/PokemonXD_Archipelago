"""Regression coverage for ADDENDUM 101 (player request: "Remove munchlax from the pool of randomizable
pokemon. While you're at it, get rid of lugia and bonsly too."). Confirms `real_species_pool()` -- the single
shared source every real candidate-species list in this project draws from (ordinary trainer-team shuffling,
the Shadow Pokemon Expansion new-member picker, and Enhanced Difficulty's new-member picker) -- never returns
Lugia, Bonsly, or Munchlax as a possible randomization target."""
from __future__ import annotations

import unittest

from ..game_data.real_trainer_data import PERMANENTLY_EXCLUDED_SPECIES_INDICES, real_species_pool

LUGIA = 249
BONSLY = 413
MUNCHLAX = 414


class TestPermanentlyExcludedSpecies(unittest.TestCase):
    def test_excluded_set_is_exactly_lugia_bonsly_munchlax(self) -> None:
        self.assertEqual(PERMANENTLY_EXCLUDED_SPECIES_INDICES, frozenset({LUGIA, BONSLY, MUNCHLAX}))

    def test_none_of_the_three_appear_in_the_real_species_pool(self) -> None:
        pool = real_species_pool()
        self.assertNotIn(LUGIA, pool)
        self.assertNotIn(BONSLY, pool)
        self.assertNotIn(MUNCHLAX, pool)

    def test_the_pool_still_has_plenty_of_other_species(self) -> None:
        # Sanity check that this is a narrow 3-species exclusion, not something that gutted the whole pool.
        pool = real_species_pool()
        self.assertGreater(len(pool), 350)


if __name__ == "__main__":
    unittest.main()
