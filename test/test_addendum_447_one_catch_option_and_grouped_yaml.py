"""ADDENDUM 447 (2026-10-09) -- one catch option, and the YAML in sections.

Player: "Can you fold the max catch rate/catch rate scaling options into one? Also, please reorder the yaml options so
that related/similar options are near each other and in a sensible order."
"""
from __future__ import annotations

import json
import tempfile
import zipfile
from pathlib import Path

from . import PokemonXDTestBase
from ..game_data import catch_rate_exclusions as cre


def _seed(test: PokemonXDTestBase) -> dict:
    world = test.multiworld.worlds[test.player]
    with tempfile.TemporaryDirectory() as tmp_dir:
        world.generate_output(tmp_dir)
        with zipfile.ZipFile(next(Path(tmp_dir).glob("*.appxd"))) as zf:
            return json.loads(zf.read("seed.json"))


class TestScaledWithAnExclusion(PokemonXDTestBase):
    options = {"catch_rate_scaling": "location_scaled", "catch_rate_exclude_citadark": True}

    def test_scaled_not_max_and_citadark_left_vanilla(self) -> None:
        """ADDENDUM 448: the player no longer picks the percentage; Location Scaled uses the world's own."""
        from .. import CATCH_RATE_LOCATION_SCALED_KEEP_PERCENT

        seed = _seed(self)
        self.assertEqual(CATCH_RATE_LOCATION_SCALED_KEEP_PERCENT, seed["catch_rate_scaling"])
        self.assertTrue(0 < CATCH_RATE_LOCATION_SCALED_KEEP_PERCENT < 100)
        self.assertFalse(seed["max_catch_rate"])
        self.assertEqual([], seed["max_catch_rate_excluded_trainers"])
        progress = {int(k) for k in seed["catch_rate_progress_by_trainer"]}
        self.assertTrue(progress)
        self.assertFalse(progress & set(cre.citadark_trainer_indices()))


class TestGuaranteedCatchesIsMax(PokemonXDTestBase):
    options = {"catch_rate_scaling": "guaranteed_catches", "catch_rate_exclude_greevil": True}

    def test_max_and_no_scaled_pass(self) -> None:
        seed = _seed(self)
        self.assertTrue(seed["max_catch_rate"])
        self.assertEqual(0, seed["catch_rate_scaling"])
        self.assertEqual(sorted(cre.greevil_trainer_indices()), seed["max_catch_rate_excluded_trainers"])


class TestVanilla(PokemonXDTestBase):
    options = {"catch_rate_scaling": "off", "catch_rate_exclude_citadark": True}

    def test_nothing(self) -> None:
        seed = _seed(self)
        self.assertFalse(seed["max_catch_rate"])
        self.assertEqual(0, seed["catch_rate_scaling"])
        self.assertEqual([], seed["max_catch_rate_excluded_trainers"])


class TestTheWebWorldUsesTheGroups(PokemonXDTestBase):
    def test_groups(self) -> None:
        from ..options import OPTION_GROUPS

        web = self.multiworld.worlds[self.player].web
        self.assertIs(OPTION_GROUPS, web.option_groups)
        self.assertEqual(["Goal", "Locations & Progression", "Trainer Checks", "Shadow Pokemon", "Difficulty",
                          "Your Pokemon", "Speed", "Death Link", "Filler Weights", "Item & Location Options"],
                         [g.name for g in web.option_groups])
