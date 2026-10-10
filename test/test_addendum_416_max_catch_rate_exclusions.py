"""ADDENDUM 416 (2026-10-04) -- Max Catch Rate can spare Citadark Isle and/or Greevil.

Player: "Can we add options to make it so that catch rate maxing doesn't work on 1. Citadark Isle 2. Greevil?"
"""
from __future__ import annotations

import unittest

from . import PokemonXDTestBase
from .. import options as O
from ..game_data import catch_rate_exclusions as cre, shadow_holders as sh
from ..tools import iso_patcher
from .test_addendum_300_max_catch_rate import _FakeDdpk, _ddpk_blob


class TestTheOptions(unittest.TestCase):
    def test_two_toggles_off_by_default_right_after_catch_rate_scaling(self) -> None:
        """ADDENDUM 447: Max Catch Rate folded into Catch Rate Scaling; the exclusions follow it."""
        names = list(O.PokemonXDOptions.type_hints)
        at = names.index("catch_rate_scaling")
        self.assertEqual(["catch_rate_exclude_citadark", "catch_rate_exclude_greevil"], names[at + 1:at + 3])
        self.assertFalse(O.CatchRateExcludeCitadark.default)
        self.assertFalse(O.CatchRateExcludeGreevil.default)


class TestWhoIsExcluded(unittest.TestCase):
    def test_greevil_is_his_three_rows(self) -> None:
        self.assertEqual(frozenset({199, 200, 201}), cre.greevil_trainer_indices())

    def test_greevil_is_inside_citadark(self) -> None:
        self.assertLessEqual(cre.greevil_trainer_indices() - {201}, cre.citadark_trainer_indices() | {201})

    def test_the_vanilla_records_each_option_keeps(self) -> None:
        holders = sh.vanilla_shadow_holders()
        teams: "dict[int, list[int]]" = {}
        for ddpk in holders:
            for row in sh.shadows_held_more_than_once().get(ddpk, (holders[ddpk].trainer_index,)):
                teams.setdefault(row, []).append(ddpk)
        greevil = cre.excluded_ddpk_indices(teams, cre.greevil_trainer_indices())
        citadark = cre.excluded_ddpk_indices(teams, cre.citadark_trainer_indices())
        self.assertEqual({73, 74, 75, 76, 77, 78, 79}, greevil, "Greevil's seven, Lugia's fight included")
        self.assertLessEqual(greevil, citadark)
        self.assertEqual(36, len(citadark), "every Shadow first offered on Citadark Isle")

    def test_a_record_first_offered_earlier_is_not_spared(self) -> None:
        """One byte per record: a Shadow snagged before Citadark keeps the maxed rate even if a Citadark fight
        carries it again."""
        self.assertEqual(set(), cre.excluded_ddpk_indices({10: [5], 190: [5]}, frozenset({190})))
        self.assertEqual({5}, cre.excluded_ddpk_indices({190: [5], 199: [5]}, frozenset({190})))


class TestThePatcherSkipsThem(unittest.TestCase):
    RECORDS = [(0, 0), (128, 190), (128, 190), (128, 190)]

    def test_skipped_records_keep_their_rate(self) -> None:
        blob = bytes(_ddpk_blob(self.RECORDS))
        out, (raised, in_use) = iso_patcher.apply_shadow_catch_rate(blob, _FakeDdpk(4), 0xFF, skip={2})
        self.assertEqual((2, 3), (raised, in_use))
        self.assertEqual(0xFF, out[0x20 + 1 * 0x18 + 1])
        self.assertEqual(190, out[0x20 + 2 * 0x18 + 1], "excluded -- vanilla")
        self.assertEqual(0xFF, out[0x20 + 3 * 0x18 + 1])

    def test_an_exclusion_takes_the_conditional_guarantee(self) -> None:
        """SUPERSEDED by ADDENDUM 450: with an exclusion on, the guarantee is no longer switched off -- it becomes
        conditional on a catch rate of 255, which the excluded records do not have."""
        from pathlib import Path
        source = Path(iso_patcher.__file__).read_text(encoding="utf-8")
        block = source[source.index("        if catch_rate_excluded_trainers:"):][:1400]
        self.assertIn("conditional_catch.dol_patch_words()", block)
        self.assertIn("always_catch = write_always_catch_code_patch(output_path)", block)


class TestTheSeedCarriesThem(PokemonXDTestBase):
    options = {"catch_rate_scaling": "guaranteed_catches", "catch_rate_exclude_greevil": True}

    def test_seed_data(self) -> None:
        import json
        import tempfile
        import zipfile
        from pathlib import Path

        world = self.multiworld.worlds[self.player]
        with tempfile.TemporaryDirectory() as tmp_dir:
            world.generate_output(tmp_dir)
            with zipfile.ZipFile(next(Path(tmp_dir).glob("*.appxd"))) as zf:
                seed_data = json.loads(zf.read("seed.json"))
        self.assertTrue(seed_data["max_catch_rate"])
        self.assertEqual(sorted(cre.greevil_trainer_indices()), seed_data["max_catch_rate_excluded_trainers"])


class TestNoExclusionWithoutMaxCatchRate(PokemonXDTestBase):
    options = {"catch_rate_scaling": "off", "catch_rate_exclude_citadark": True}

    def test_nothing_is_carried(self) -> None:
        import json
        import tempfile
        import zipfile
        from pathlib import Path

        world = self.multiworld.worlds[self.player]
        with tempfile.TemporaryDirectory() as tmp_dir:
            world.generate_output(tmp_dir)
            with zipfile.ZipFile(next(Path(tmp_dir).glob("*.appxd"))) as zf:
                seed_data = json.loads(zf.read("seed.json"))
        self.assertEqual([], seed_data["max_catch_rate_excluded_trainers"])


if __name__ == "__main__":
    unittest.main()
