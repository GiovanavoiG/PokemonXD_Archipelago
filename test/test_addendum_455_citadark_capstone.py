"""ADDENDUM 455 (2026-10-09) -- Citadark Isle is path scaling's capstone.

For path scaling, Citadark is strapped onto the end of the path every time as an extra area/layer: with the
ramp's maximum at 50, Citadark is 53.
"""
from __future__ import annotations

import unittest

from ..randomizer import path_level_scaling as pls


class TestTheCapstone(unittest.TestCase):
    def setUp(self) -> None:
        self.regions = set(pls.region_by_trainer_index().values())
        self.tiers = pls.path_tiers(self.regions)

    def test_numbers(self) -> None:
        self.assertEqual((50, 3, 53), (pls.LAST_TIER_LEVEL, pls.CITADARK_EXTRA_LEVELS, pls.CITADARK_LEVEL))

    def test_intended_path(self) -> None:
        self.assertTrue(pls.has_capstone(self.tiers))
        self.assertEqual(len(self.tiers) - 1, pls.tier_index("Citadark Isle", self.tiers, self.regions))
        self.assertEqual(53, pls.tier_level(len(self.tiers) - 1, self.tiers))
        self.assertEqual(8, pls.tier_level(0, self.tiers))
        self.assertEqual(50, pls.tier_level(pls.tier_index("Cipher Key Lair", self.tiers, self.regions), self.tiers),
                         "the last area before Citadark is the old top")

    def test_every_trainer(self) -> None:
        regions = pls.region_by_trainer_index()
        levels = pls.level_by_trainer_index()
        citadark = {levels[i] for i, r in regions.items() if r == "Citadark Isle" and i in levels}
        self.assertEqual({53}, citadark)
        self.assertEqual(50, max(level for i, level in levels.items() if regions[i] != "Citadark Isle"))

    def test_last_whatever_sphere_it_opens_in(self) -> None:
        spheres = {region: 5 for region in self.regions}
        spheres["Citadark Isle"] = 0                 # handed over first
        order = pls.sphere_tier_order(spheres, self.regions)
        self.assertEqual(max(order.values()), order["Citadark Isle"])
        levels = pls.level_by_trainer_index(tier_by_region=order)
        regions = pls.region_by_trainer_index()
        self.assertEqual({53}, {levels[i] for i, r in regions.items() if r == "Citadark Isle" and i in levels})

    def test_enhanced_difficulty_still_multiplies_it(self) -> None:
        from ..randomizer.enhanced_difficulty import ENHANCED_DIFFICULTY_LEVEL_MULTIPLIER
        self.assertEqual(70, int(pls.CITADARK_LEVEL * ENHANCED_DIFFICULTY_LEVEL_MULTIPLIER))

    def test_without_citadark_the_ramp_is_unchanged(self) -> None:
        regions = self.regions - {"Citadark Isle"}
        tiers = pls.path_tiers(regions)
        self.assertFalse(pls.has_capstone(tiers))
        self.assertEqual(50, pls.tier_level(len(tiers) - 1, tiers))


if __name__ == "__main__":
    unittest.main()
