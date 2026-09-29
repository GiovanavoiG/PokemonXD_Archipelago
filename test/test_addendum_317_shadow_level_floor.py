"""ADDENDUM 317 -- a Shadow is never levelled BELOW the unmodified game's.

Player: "floor it at the vanilla level."

Matching a Shadow to its holder's team average runs both ways. Until ADDENDUM 315 the downward half never
showed, because the six Sixes' Shadows were matched up to a rematch team's 50; with the holder resolved to the
Cipher Lab fight their teams average 8.8-14 against a vanilla Shadow level of 17, so matching alone made them
weaker than vanilla."""
import math
import unittest

from ..game_data import real_trainer_data as rtd
from ..randomizer.enhanced_difficulty import (
    ENHANCED_DIFFICULTY_LEVEL_MULTIPLIER,
    shadow_level_assignment,
)


class TestTheFloor(unittest.TestCase):
    def setUp(self) -> None:
        self.census = rtd.real_shadow_census()
        self.matched, self.matched_ddpk = shadow_level_assignment(self.census, scale_levels=False)
        self.scaled, self.scaled_ddpk = shadow_level_assignment(self.census, scale_levels=True)

    def test_no_shadow_is_below_its_vanilla_level(self) -> None:
        for row in self.census:
            self.assertGreaterEqual(self.matched[row["dpkm_index"]], row["shadow_level"], row)
            self.assertGreaterEqual(self.scaled[row["dpkm_index"]], row["shadow_level"], row)

    def test_the_population_this_is_about_is_real(self) -> None:
        """If no Shadow's team ever averaged below its own level, this rule would be untested decoration."""
        below = [r for r in self.census
                 if r["team_avg_level"] is not None and r["team_avg_level"] < r["shadow_level"]]
        self.assertTrue(below)
        for row in below:
            self.assertEqual(row["shadow_level"], self.matched[row["dpkm_index"]], row)

    def test_matching_up_is_untouched(self) -> None:
        for row in self.census:
            if row["team_avg_level"] is not None and row["team_avg_level"] > row["shadow_level"]:
                self.assertEqual(math.floor(row["team_avg_level"]), self.matched[row["dpkm_index"]], row)

    def test_the_floor_is_applied_before_scaling(self) -> None:
        """So a floored Shadow scales like a matched one: 17 -> 22, never 17 from one rule and 11 from another."""
        for row in self.census:
            base = max(row["team_avg_level"] or 0, row["shadow_level"])
            self.assertEqual(math.floor(base * ENHANCED_DIFFICULTY_LEVEL_MULTIPLIER),
                             self.scaled[row["dpkm_index"]], row)

    def test_both_halves_still_agree(self) -> None:
        by_ddpk = {r["ddpk_index"]: r for r in self.census}
        for ddpk_index, level in self.scaled_ddpk.items():
            self.assertEqual(level, self.scaled[by_ddpk[ddpk_index]["dpkm_index"]])

    def test_the_sixes_land_at_the_vanilla_seventeen(self) -> None:
        for ddpk in (3, 4, 5, 6, 7, 14):
            self.assertEqual(17, self.matched_ddpk[ddpk])
            self.assertEqual(math.floor(17 * ENHANCED_DIFFICULTY_LEVEL_MULTIPLIER), self.scaled_ddpk[ddpk])
