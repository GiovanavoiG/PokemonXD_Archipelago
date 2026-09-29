"""ADDENDUM 197. Enhanced Difficulty is a Choice, and level scaling is its own toggle.

Player, in three messages: "rather than on or off, add settings for 'up to one additional pokemon' 'up to two
additional pokemon' and 'fill enemy team'"; "make the level boosting a different setting right underneath.
That one can be on/off, to enable or disable the 1.33x scaling"; "Keep our current rules on which trainers can
ONLY receive 0, 1, or 2 pokemon."

The third message is the one with teeth. The ramp's bands are NOT replaced by a flat number -- they stay
exactly as they were and they are themselves ceilings. The player's setting is a second ceiling laid over
them, and the lower one wins, so a setting can only ever lower what a band receives. The table below is that
rule written out, and it is the contract this file exists to hold.
"""
from __future__ import annotations

import random
import unittest

from . import PokemonXDTestBase
from ..options import EnhancedDifficulty, EnhancedDifficultyLevelScaling, PokemonXDOptions
from ..randomizer.team_shuffle import Species
from ..randomizer.enhanced_difficulty import (
    ENHANCED_DIFFICULTY_LEVEL_MULTIPLIER,
    FILL_THE_TEAM,
    _tier_add_count,
    build_enhanced_difficulty_plan,
    cap_for_option,
)

# trainer_index -> {setting: expected additions}, with free slots deliberately generous (5) so the ceiling
# under test is the ramp/setting rather than the trainer's own room.
_BANDS = {
    3:  {"off": 0, "one": 0, "two": 0, "fill": 0},   # the untouched opening band
    8:  {"off": 0, "one": 1, "two": 1, "fill": 1},
    13: {"off": 0, "one": 1, "two": 2, "fill": 2},
    99: {"off": 0, "one": 1, "two": 2, "fill": 5},   # 5 == free_slots, i.e. "fill"
}
_CAPS = {"off": 0, "one": 1, "two": 2, "fill": FILL_THE_TEAM}


class TestTheBandsSurviveEverySetting(unittest.TestCase):
    def test_the_whole_table(self) -> None:
        for trainer_index, row in _BANDS.items():
            for setting, expected in row.items():
                actual = _tier_add_count(trainer_index, 5, _CAPS[setting])
                self.assertEqual(expected, actual,
                                 f"trainer {trainer_index} on '{setting}' should add {expected}, got {actual}")

    def test_a_setting_can_only_ever_lower_a_band(self) -> None:
        """The invariant behind the table: two ceilings, the lower wins."""
        for trainer_index in (1, 5, 6, 10, 11, 15, 16, 200):
            unlimited = _tier_add_count(trainer_index, 5, FILL_THE_TEAM)
            for cap in (0, 1, 2):
                self.assertLessEqual(_tier_add_count(trainer_index, 5, cap), unlimited)

    def test_fill_is_byte_for_byte_the_old_behaviour(self) -> None:
        """`fill_enemy_team` is a rename of the old on/off option's ON, not a new behaviour."""
        for trainer_index in range(1, 40):
            for free in range(0, 6):
                self.assertEqual(_tier_add_count(trainer_index, free, FILL_THE_TEAM),
                                 _tier_add_count(trainer_index, free))

    def test_free_slots_still_win_over_the_setting(self) -> None:
        """"Up to" in the other direction: a trainer with one slot never gets two."""
        self.assertEqual(1, _tier_add_count(99, 1, 2))
        self.assertEqual(0, _tier_add_count(99, 0, FILL_THE_TEAM))

    def test_the_option_values_map_to_the_caps(self) -> None:
        self.assertEqual(0, cap_for_option(EnhancedDifficulty.option_off))
        self.assertEqual(1, cap_for_option(EnhancedDifficulty.option_up_to_one_additional_pokemon))
        self.assertEqual(2, cap_for_option(EnhancedDifficulty.option_up_to_two_additional_pokemon))
        self.assertEqual(FILL_THE_TEAM, cap_for_option(EnhancedDifficulty.option_fill_enemy_team))


def _census() -> "list[dict]":
    return [{"trainer_index": index, "free_slots": 3, "avg_level": 30,
             "member_levels": {index * 10: 30, index * 10 + 1: 30}}
            for index in (3, 8, 13, 99)]


def _plan(cap, scale):
    return build_enhanced_difficulty_plan(
        _census(),
        {1: Species(species_id=1)},
        {1: [(1, 33)]},
        random.Random(7),
        permanently_excluded_trainer_indices=frozenset(),
        max_added_members=cap,
        scale_levels=scale,
    )


class TestLevelScalingIsIndependent(unittest.TestCase):
    """The second message: the 1.33x is its own switch now, either half usable without the other."""

    def test_scaling_off_writes_no_level_assignment(self) -> None:
        plan = _plan(FILL_THE_TEAM, False)
        self.assertEqual({}, plan["level_assignment"],
                         "with scaling off nothing should be rewritten -- not even to the same value, which "
                         "would still be a pointless ISO write")

    def test_scaling_on_scales_every_existing_member(self) -> None:
        plan = _plan(0, True)
        self.assertTrue(plan["level_assignment"])
        for level in plan["level_assignment"].values():
            self.assertEqual(int(30 * ENHANCED_DIFFICULTY_LEVEL_MULTIPLIER), level)

    def test_padding_without_scaling_adds_members_at_the_unboosted_level(self) -> None:
        """Otherwise turning scaling off would still hand a padded trainer members 33% above its own team."""
        plan = _plan(FILL_THE_TEAM, False)
        self.assertTrue(plan["new_dpkm_entries"])
        for entry in plan["new_dpkm_entries"]:
            self.assertEqual(30, entry["level"])

    def test_scaling_without_padding_adds_nobody(self) -> None:
        plan = _plan(0, True)
        self.assertEqual([], plan["new_dpkm_entries"])
        self.assertEqual([], plan["team_slot_plan"])


class TestTheOptionsThemselves(unittest.TestCase):
    def test_enhanced_difficulty_is_a_choice_with_the_players_four_settings(self) -> None:
        # `name_lookup` is the canonical set; `options` also carries AP's own back-compat aliases
        # ("false" -> 0, inherited from this option having been a Toggle), which is why it is not compared.
        self.assertEqual(
            {"off", "up_to_one_additional_pokemon", "up_to_two_additional_pokemon", "fill_enemy_team"},
            set(EnhancedDifficulty.name_lookup.values()),
        )
        self.assertEqual(0, EnhancedDifficulty.default)

    def test_level_scaling_sits_directly_underneath_it(self) -> None:
        """"a different setting right underneath" -- and field order is what the template renders."""
        names = list(PokemonXDOptions.type_hints)
        self.assertEqual(names.index("enhanced_difficulty") + 1,
                         names.index("enhanced_difficulty_level_scaling"))
        self.assertEqual(0, EnhancedDifficultyLevelScaling.default)


class TestBothOffIsUntouched(PokemonXDTestBase):
    options = {"enhanced_difficulty": "off", "enhanced_difficulty_level_scaling": False}

    def test_a_seed_generates_with_both_halves_off(self) -> None:
        self.assertFalse(self.multiworld.worlds[self.player].options.enhanced_difficulty)
        self.assertFalse(self.multiworld.worlds[self.player].options.enhanced_difficulty_level_scaling)
