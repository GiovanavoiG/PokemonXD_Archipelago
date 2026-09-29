"""ADDENDUM 189. A named pickup location must not sit in a region other than the place its own name says.

The eight `S.S. Libra - ...` pickups were bucketed under "Realgam Tower" -- the ship's own chests (30-38)
were already in "SS Libra", so one vessel carried two regions and logic believed half of it was reachable
from the Realgam tournament onward, nine story transitions before the ship can be boarded. Under key-item
shuffle that is a live softlock, not cosmetic: a gate item lands on a location the sweep calls sphere 2 and
the player cannot reach until 0x5A.

This is the same class of mistake ADDENDUM 184 fixed for Kaminko's House, which is why the fence is written
against the whole table rather than against the eight names: any future walkthrough-part grouping that files
a location under the wrong heading fails here instead of surfacing as an unwinnable seed.
"""
from __future__ import annotations

import unittest

from .. import locations

# Location-name prefix -> the region (or region-name stem) that prefix commits the location to. Only prefixes
# that really do name a place belong here; a prefix whose locations legitimately live elsewhere is listed in
# ACCEPTED_REBUCKETS below with the reason.
PREFIX_TO_REGION_STEM: "dict[str, str]" = {
    "S.S. Libra": "SS Libra",
    "Agate Village": "Agate Village",
    "Relic Forest": "Agate Village",
    "Cipher Key Lair": "Cipher Key Lair",
    "Cipher Lab": "Cipher Lab",
    "Citadark Isle": "Citadark Isle",
    "Gateon Port": "Gateon Port",
    "Kaminko's House": "Kaminko's House",
    "Mt. Battle": "Mt. Battle",
    "Phenac City": "Phenac City",
    "Pyrite Town": "Pyrite Town",
    "Realgam Tower": "Realgam Tower",
    "Snagem Hideout": "Snagem Hideout",
    "Pokemon HQ Lab": "Pokemon HQ Lab",
}

# Deliberate disagreements, each with the reason it is correct. These are the entries `_REBUCKET_BY_NAME`
# exists for: the name records where the player was told about the item, the region records where it is.
ACCEPTED_REBUCKETS: "dict[str, str]" = {
    "Outskirt Stand - Eevee Gift": "Pokemon HQ Lab",
    "Outskirt Stand - HQ Lab Potions": "Pokemon HQ Lab",
}


class TestLocationRegionNameAgreement(unittest.TestCase):
    def test_named_pickups_live_in_the_region_their_name_states(self) -> None:
        offenders: "list[str]" = []
        for region_name, location_names in locations.LOCATIONS_BY_REGION.items():
            for name in location_names:
                if " - " not in name:
                    continue
                if ACCEPTED_REBUCKETS.get(name) == region_name:
                    continue
                stem = PREFIX_TO_REGION_STEM.get(name.split(" - ", 1)[0])
                if stem is None:
                    continue
                if not region_name.startswith(stem):
                    offenders.append(f"{name!r} is in region {region_name!r}, not {stem!r}")
        self.assertEqual(
            [], sorted(offenders),
            "a location filed under the wrong region reads as reachable in the wrong sphere; add a reason to "
            "ACCEPTED_REBUCKETS if the disagreement is deliberate",
        )

    def test_the_ship_is_one_region(self) -> None:
        """Every S.S. Libra pickup and every S.S. Libra chest share a region."""
        named = {name for names in locations.LOCATIONS_BY_REGION.values() for name in names
                 if name.startswith("S.S. Libra")}
        # ADDENDUM 237: was 8. Seven of the eight "S.S. Libra - ..." pickups were retired as duplicates of
        # the ship's own per-chest locations -- the census matched three of them to a specific chest by item
        # (Iron, Max Ether, Yellow Flute). "S.S. Libra - Bonsly's Item" survived as unverified.
        #
        # ADDENDUM 335: the Bonsly pickup is retired too, so NONE survive and the set is legitimately empty.
        # The test keeps its real point -- whatever is named shares one region -- and the emptiness is
        # asserted rather than allowed to pass vacuously, so a name reappearing without a region is still
        # caught.
        self.assertEqual(set(), named,
                         "every 'S.S. Libra - ...' pickup is retired; a new one needs a region here")
        for name in named:
            self.assertIn(name, locations.LOCATIONS_BY_REGION["SS Libra"])
