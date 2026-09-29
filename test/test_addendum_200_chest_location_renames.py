"""ADDENDUM 200. A chest location can carry a human name, and both sides have to spell it identically.

Player: "Relabel the Chest 98 check to 'Pickup PDA'." -- REVERSED by ADDENDUM 246, which moved chest 98 to
"ONBS 3F Chest 1" once the player checked the game: "Pickup PDA is in hq lab right by chest 3, not pyrite
town". The MECHANISM these tests cover is unchanged and is the reason the rename was safe to make.

A location's NAME is its identity to Archipelago. `locations.py` builds it for the world and `ram_client.py`
builds it again for the client -- independently, because that file deliberately cannot import `locations`
(it has to load without the world package). Nothing enforces that the two agree except that they agree, and a
one-character difference means every chest check is silently rejected with no error anywhere. So the override
table lives in `game_data/chest_names.py`, which both import, and these tests check the agreement itself
rather than either side's answer.

The frozen id follows the NEW name and keeps its number: the id is the stable thing (ADDENDUM 26), the label
is not."""
from __future__ import annotations

import unittest

from .. import locations, ram_client
from ..game_data import chest_names


class TestChestNameOverride(unittest.TestCase):
    def test_chest_98_is_the_first_onbs_3f_chest(self) -> None:
        """ADDENDUM 246. Was "Pickup PDA"; the ISO puts chest 98 in room 110, which is ONBS."""
        self.assertEqual("ONBS 3F Chest 1", locations.CHEST_ID_TO_LOCATION[98])

    def test_the_old_names_are_gone_everywhere(self) -> None:
        for gone in ("Chest 98 (Room 110)", "Pickup PDA", "Chest 99 (Room 110)", "ONBS 3F Chest"):
            self.assertNotIn(gone, locations.LOCATION_TABLE, gone)
            self.assertNotIn(gone, locations.CHEST_LOCATION_NAMES, gone)
            self.assertNotIn(gone, ram_client.CHEST_LOCATION_NAMES, gone)

    def test_both_renames_kept_their_frozen_ids(self) -> None:
        """The rename must not renumber anything -- ADDENDUM 26's whole point."""
        self.assertEqual(1510, locations.LOCATION_TABLE["ONBS 3F Chest 1"].id_offset)
        self.assertEqual(1511, locations.LOCATION_TABLE["ONBS 3F Chest 2"].id_offset)

    def test_the_retired_labels_stay_as_tombstones(self) -> None:
        """Retired ids are never reissued (ADDENDUM 26/242), so the old strings keep their frozen entries
        even though they name no live location any more."""
        frozen = locations._FROZEN_LOCATION_OFFSETS
        self.assertEqual(1510, frozen["Pickup PDA"])
        self.assertEqual(1511, frozen["ONBS 3F Chest"])

    def test_they_kept_their_region(self) -> None:
        self.assertEqual("Pyrite Town (ONBS)", locations.CHEST_LOCATION_TO_REGION["ONBS 3F Chest 1"])
        self.assertEqual("Pyrite Town (ONBS)", locations.CHEST_LOCATION_TO_REGION["ONBS 3F Chest 2"])

    def test_the_hq_lab_has_no_pda_location_to_confuse_it_with(self) -> None:
        """The reason the rename happened. The lab holds three treasure boxes and nothing else, so no
        location here can be the pickup the player found beside chest 3."""
        lab = {name for name, data in locations.LOCATION_TABLE.items()
               if data.region == "Pokemon HQ Lab" and name in locations.CHEST_LOCATION_NAMES}
        self.assertEqual({"Outside HQ Lab", "Master Ball Chest", "Player's Room Chest"}, lab)


class TestBothSidesSpellEveryChestTheSame(unittest.TestCase):
    """The real contract. Not just the renamed one -- every chest, so a future override cannot land on one
    side only."""

    def test_the_full_chest_id_to_name_maps_are_identical(self) -> None:
        self.assertEqual(locations.CHEST_ID_TO_LOCATION, dict(ram_client.CHEST_ID_TO_LOCATION))

    def test_the_name_lists_are_identical(self) -> None:
        self.assertEqual(sorted(locations.CHEST_LOCATION_NAMES), sorted(ram_client.CHEST_LOCATION_NAMES))

    def test_every_override_reaches_both_sides(self) -> None:
        for chest_ids, name in chest_names.CHEST_LOCATION_NAME_OVERRIDES.items():
            for chest_id in chest_ids:
                self.assertEqual(name, locations.CHEST_ID_TO_LOCATION[chest_id])
                self.assertEqual(name, ram_client.CHEST_ID_TO_LOCATION[chest_id])

    def test_every_chest_location_still_has_an_id(self) -> None:
        """A renamed location with no entry in the frozen table would be auto-assigned a brand-new id and the
        old one orphaned -- the exact ADDENDUM 26 failure, just arriving by way of a rename."""
        for name in locations.CHEST_LOCATION_NAMES:
            self.assertIn(name, locations.LOCATION_TABLE, f"{name} has no location id")

    def test_no_override_collides_with_an_existing_location_name(self) -> None:
        generated = {
            f"Chest {ids[0]} (Room {room})" if len(ids) == 1
            else "Chest " + "+".join(str(c) for c in ids) + f" (Room {room})"
            for ids, room, _region in locations.CHEST_LOCATION_ROWS
        }
        for name in chest_names.CHEST_LOCATION_NAME_OVERRIDES.values():
            self.assertNotIn(name, generated, f"{name} collides with a generated chest name")


if __name__ == "__main__":
    unittest.main()
