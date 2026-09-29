"""ADDENDUM 237. The Overworld Items census: retire the duplicates, exclude the unverified.

Player: "where is the 'Agate Village - eagun's item' check? what does that represent?" -- then, after the
census: "Retire the duplicates and mark anything we aren't certain on as excluded."
"""
from __future__ import annotations

import unittest

from .. import locations as L
from ..game_data import chest_table, overworld_item_census as census


class TestTheCensusItself(unittest.TestCase):
    def test_the_two_sets_are_disjoint(self) -> None:
        """UPDATED BY ADDENDUM 335. The second set used to be `UNCERTAIN_EXCLUDED_LOCATIONS` -- names this
        census could not vouch for, kept and marked EXCLUDED. The player has since played every one of them
        ("None of these are real"), so they are retired under their own reason and the pairing is now two
        RETIREMENTS that must not overlap."""
        self.assertEqual(frozenset(),
                         census.RETIRED_DUPLICATE_LOCATIONS & census.RETIRED_UNREAL_LOCATIONS)
        self.assertEqual(len(census.RETIRED_LOCATIONS),
                         len(census.RETIRED_DUPLICATE_LOCATIONS) + len(census.RETIRED_UNREAL_LOCATIONS))

    def test_the_arithmetic_that_justified_retiring_them(self) -> None:
        """115 real boxes exist and 95 are already chest locations, so the Overworld Items cannot all be
        distinct physical pickups. This is the whole argument, kept executable."""
        real_boxes = len(chest_table.CHESTS)
        chest_locations = len({c for ids in L.CHEST_LOCATION_TO_CHEST_IDS.values() for c in ids})
        self.assertEqual(115, real_boxes)
        self.assertEqual(95, chest_locations)
        self.assertGreater(chest_locations + len(census.RETIRED_DUPLICATE_LOCATIONS), real_boxes,
                           "if this ever stops being true, the duplication argument no longer holds")

    def test_most_chest_locations_are_item_balls_not_large_chests(self) -> None:
        """Why the two categories describe the same objects: model 36 is the small overworld item ball."""
        in_ap = {c for ids in L.CHEST_LOCATION_TO_CHEST_IDS.values() for c in ids}
        balls = sum(1 for c in chest_table.CHESTS if c["chest"] in in_ap and c["model"] == 36)
        self.assertGreaterEqual(balls, 80)


class TestRetirement(unittest.TestCase):
    def test_no_retired_name_is_in_the_current_table(self) -> None:
        for name in census.RETIRED_DUPLICATE_LOCATIONS:
            self.assertNotIn(name, L.LOCATION_TABLE, name)

    def test_no_retired_name_is_in_any_region(self) -> None:
        """The filter has to run after every later pass that re-adds names, or it is silently undone."""
        for region_locations in L.LOCATIONS_BY_REGION.values():
            for name in region_locations:
                self.assertNotIn(name, census.RETIRED_DUPLICATE_LOCATIONS, name)

    def test_retired_ids_are_not_reassigned(self) -> None:
        """ADDENDUM 26's rule: a retired name's frozen offset stays behind, and no LIVE name may take it."""
        live_offsets = {data.id_offset for data in L.LOCATION_TABLE.values()}
        for name in census.RETIRED_DUPLICATE_LOCATIONS:
            frozen = L._FROZEN_LOCATION_OFFSETS.get(name)
            if frozen is None:
                continue
            owners = [n for n, d in L.LOCATION_TABLE.items() if d.id_offset == frozen]
            self.assertLessEqual(len(owners), 1, f"{name}'s old id {frozen} is held by {owners}")

    def test_the_uncertain_ones_are_gone_now(self) -> None:
        """RETARGETED BY ADDENDUM 335, and the flip is the finding.

        This asserted that the fourteen unverified names SURVIVE -- which was right while they were unknown,
        because retiring a real location loses a check. They are not unknown any more: the player played
        every one and none exists. What the test guards now is that they really left the table, and that
        ADDENDUM 26's rule held while they did."""
        for name in census.RETIRED_UNREAL_LOCATIONS:
            self.assertNotIn(name, L.LOCATION_TABLE, name)
            self.assertIn(name, L._FROZEN_LOCATION_OFFSETS,
                          f"{name}'s id must stay recorded and never be reassigned")

    def test_eaguns_item_is_retired_after_all(self) -> None:
        """The player's own question, and its eventual answer. ADDENDUM 237 began with "where is the 'Agate
        Village - eagun's item' check? what does that represent?" -- it was kept as a bare "... Item" name
        the census could not place. ADDENDUM 335 answers it: nowhere, because it is not there."""
        self.assertIn("Agate Village - Eagun's Item", census.RETIRED_UNREAL_LOCATIONS)
        self.assertNotIn("Agate Village - Eagun's Item", L.LOCATION_TABLE)

    def test_the_uncertain_mechanism_is_gone_rather_than_empty(self) -> None:
        """ADDENDA 247/298's rule: a condition that can never bind reads as a guarantee. With every name
        ruled on, an empty uncertain set still wired into `locations.py` would claim to protect something."""
        self.assertFalse(hasattr(census, "UNCERTAIN_EXCLUDED_LOCATIONS"))
