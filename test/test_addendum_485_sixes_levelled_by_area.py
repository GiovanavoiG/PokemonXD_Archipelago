"""ADDENDUM 485 (2026-10-13) -- the Sixes are levelled by where each fight really is.

The Sixes were mostly the same level at Cipher Lab and at Phenac. With path scaling, their fights in each area are
now levelled to that area, separately.
"""
from __future__ import annotations

import unittest

from ..game_data import load_json_data_file, trainer_placements, trainer_roster
from ..randomizer import path_level_scaling as pls

CIPHER_LAB_ROWS = tuple(range(33, 45))       # #1 (with the Shadow) and #2 (the same team once it is snagged)
PHENAC_ROWS = tuple(range(112, 124))         # #3 (with the Shadow) and #4 (without)


class TestTheRowsAreWhereTheCensusSays(unittest.TestCase):
    def test_the_phenac_teams_are_the_level_20_rows(self) -> None:
        """The hand-transcribed census's "Phenac Area Cipher Peons" Sixes are rows 118-123, member for member."""
        census = load_json_data_file("trainer_census.json")
        phenac = {t["name"].split()[-1].upper(): [m["level"] for m in t["team"]]
                  for area in census["trainer_pools"] if area["name"] == "Phenac Area Cipher Peons"
                  for t in area["trainers"] if "six" in t["name"].lower()}
        self.assertTrue(phenac)
        for index in range(118, 124):
            row = trainer_roster.TRAINERS_BY_INDEX[index]
            if row["name"] in phenac:
                self.assertEqual(phenac[row["name"]], [m["level"] for m in row["team"]], row["name"])

    def test_logic_placements_are_unchanged(self) -> None:
        for index in PHENAC_ROWS:
            self.assertEqual("Cipher Lab", trainer_placements.PLACEMENTS[index].region)
        for index in range(39, 45):
            self.assertEqual("Phenac City (Post-Sixes)", trainer_placements.PLACEMENTS[index].region)


class TestTheLevels(unittest.TestCase):
    def test_intended_path(self) -> None:
        levels = pls.level_by_trainer_index()
        cipher = {levels[i] for i in CIPHER_LAB_ROWS}
        phenac = {levels[i] for i in PHENAC_ROWS}
        self.assertEqual(1, len(cipher))
        self.assertEqual(1, len(phenac))
        self.assertGreater(phenac.pop(), cipher.pop(), "Phenac is later on the path")
        self.assertEqual(levels[129], levels[118], "the Post-Sixes band, with Quelor -- no new tier")

    def test_a_seed_order_still_separates_them(self) -> None:
        regions = set(pls.region_by_trainer_index().values())
        spheres = {region: 0 for region in regions}
        spheres["Cipher Lab"] = 5
        spheres["Phenac City"] = spheres["Phenac City (Mayor's House)"] = spheres["Phenac City (Post-Sixes)"] = 1
        levels = pls.level_by_trainer_index(tier_by_region=pls.sphere_tier_order(spheres, regions))
        self.assertLess(levels[118], levels[33], "an early Phenac and a late Cipher Lab are levelled apart")

    def test_the_tier_count_did_not_change(self) -> None:
        self.assertEqual(len(pls.path_tiers(set(trainer_placements.REGIONS_WITH_TRAINERS))),
                         len(pls.path_tiers(set(pls.region_by_trainer_index().values()))))


if __name__ == "__main__":
    unittest.main()
