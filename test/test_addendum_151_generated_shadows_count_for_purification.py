"""ADDENDUM 151 (2026-09-11): generated Shadow Pokemon and the purification checks.

Player: "Make sure whatever shadow pokemon we generate are included in those purification checks."

They are, and by construction rather than by accident -- but the reasons are spread across three modules and
none of them were asserted anywhere, so a future change to any one of them could break it silently. These
tests pin the chain:

  1. `shadow_expansion` draws every new species with `rng.sample` from a pool that already excludes the 83
     vanilla shadow species -- so no generated shadow ever shares a species with another shadow, new or old.
  2. All 83 vanilla shadow species are themselves distinct.
  3. `NamedPurificationTracker` is keyed by SPECIES and has no shadow whitelist of any kind -- it fires for
     any party member whose recap purified flag goes 0 -> nonzero.

(1) and (2) matter because of (3): a species-keyed tracker fires once per species, so two shadows sharing a
species would count as one purification. Nothing in this game produces that, and these tests are what keep it
that way.

Also here: a drift fix. `ram_client.CHEST_LOCATION_COUNT` still said 115 after ADDENDUM 134 dropped
locations.py's to 91.
"""
from __future__ import annotations

import json
import pathlib
import random
import unittest

from .. import locations, ram_client as rc
from ..game_data import real_trainer_data as rtd
from ..game_data.real_moveset_data import load_level_up_moves
from ..game_data.real_shadow_data import vanilla_shadow_species
from ..randomizer import shadow_expansion

_SHADOW_LIST = pathlib.Path(__file__).resolve().parent.parent / "data" / "shadow_pokemon_list.json"
BLOCK_BASE = 0x80479380
STREAK = rc.NamedPurificationTracker._CONFIRM_STREAK


class TestMirroredConstantsDoNotDrift(unittest.TestCase):
    """ram_client.py duplicates these rather than importing locations.py (which needs the real Archipelago
    package to load). Duplication is fine; silent drift is not."""

    def test_chest_count_matches_locations(self) -> None:
        self.assertEqual(rc.CHEST_LOCATION_COUNT, locations.CHEST_LOCATION_COUNT)

    def test_chest_count_is_the_post_key_item_fence_number(self) -> None:
        """ADDENDUM 134 dropped it 115 -> 91; ram_client kept saying 115 until ADDENDUM 151.

        RETARGETED 2026-09-13 (ADDENDUM 168): 91 -> 90. Chest 115 sits in room 175, the debug room that
        game_data/chest_regions.EXCLUDED_ROOMS now drops outright, and it was never covered by the key-item
        fence (its item id is 0). The literal is kept deliberately -- this test's whole job is to be a second,
        independent copy of the number so ram_client.py's hand-mirrored constant cannot drift in silence, which
        is exactly what happened between ADDENDUM 134 and 151.
        """
        # ADDENDUM 174: 90 -> 89. The literal is still kept deliberately (this test's whole job is to be a
        # second, independent copy of the number), but it now counts chest LOCATIONS, and chests 108/113 share
        # one. CHEST_COVERED_CHEST_COUNT is still 90.
        # ADDENDUM 177: 89 -> 94 and 90 -> 95. Five fenced key-item chests became checks under KeyItemShuffle.
        # UPDATED 2026-09-15 (ADDENDUM 224): 95, not 94. The 108/113 shared-flag pair was split back into two
        # locations -- identity comes from the chest's own berry now, not from the flag they share.
        self.assertEqual(rc.CHEST_LOCATION_COUNT, 95)
        self.assertEqual(locations.CHEST_COVERED_CHEST_COUNT, 95)

    def test_purification_count_matches_locations(self) -> None:
        self.assertEqual(rc.PURIFICATION_LOCATION_COUNT, locations.PURIFICATION_LOCATION_COUNT)

    def test_the_client_can_never_name_a_location_the_seed_does_not_have(self) -> None:
        for name in rc.CHEST_LOCATION_NAMES:
            self.assertIn(name, locations.LOCATION_TABLE)
        # ADDENDUM 174: the two tables are built independently (ram_client cannot import locations), so the
        # name FORMAT is the duplicated part and a one-character difference would make every chest check bounce.
        self.assertEqual(rc.CHEST_ID_TO_LOCATION, locations.CHEST_ID_TO_LOCATION)
        for count in (1, rc.PURIFICATION_LOCATION_COUNT):
            self.assertIn(rc.purification_location_name(count), locations.LOCATION_TABLE)


class TestSpeciesUniqueness(unittest.TestCase):
    def test_the_83_vanilla_shadows_are_all_different_species(self) -> None:
        entries = json.loads(_SHADOW_LIST.read_text())
        names = [e["species_name"] for e in entries]
        self.assertEqual(len(names), 83)
        self.assertEqual(len(set(names)), 83, "a repeated species would count as one purification, not two")

    def test_generated_shadows_never_reuse_a_species(self) -> None:
        census = rtd.real_trainer_free_slot_census()
        species_pool = rtd.real_species_pool()
        level_up_moves = load_level_up_moves()
        excluded = vanilla_shadow_species()
        if not (census and species_pool and level_up_moves and excluded is not None):
            self.skipTest("real ISO-extracted data files not present in this build")
        for seed in (1, 7, 99):
            plans = shadow_expansion.build_shadow_expansion_plans(
                census, species_pool, level_up_moves, excluded,
                shadow_expansion.SHADOW_EXPANSION_MAX_NEW_POKEMON, random.Random(seed),
            )
            generated = [p["species"] for plan in plans for p in plan["new_pokemon"]]
            self.assertTrue(generated)
            self.assertEqual(len(generated), len(set(generated)), f"seed {seed} repeated a species")

    def test_generated_shadows_never_collide_with_a_vanilla_shadow(self) -> None:
        census = rtd.real_trainer_free_slot_census()
        species_pool = rtd.real_species_pool()
        level_up_moves = load_level_up_moves()
        excluded = vanilla_shadow_species()
        if not (census and species_pool and level_up_moves and excluded is not None):
            self.skipTest("real ISO-extracted data files not present in this build")
        plans = shadow_expansion.build_shadow_expansion_plans(
            census, species_pool, level_up_moves, excluded,
            shadow_expansion.SHADOW_EXPANSION_MAX_NEW_POKEMON, random.Random(4),
        )
        generated = {p["species"] for plan in plans for p in plan["new_pokemon"]}
        self.assertFalse(generated & set(excluded))


# ============================================================================================================
# The tracker itself, driven with a synthetic party
# ============================================================================================================
class _Member:
    def __init__(self, party_index: int, species: int) -> None:
        self.party_index = party_index
        self.species = species
        self.reliable_species = species
        # ADDENDUM 236: the pairing check reads the member's own name, and a real PartyMember always has one.
        # Matches _Recap's name so this fake stays a self-consistent pairing, which is what it has always meant.
        self.name = "MON"


class _Recap:
    def __init__(self, purified_flag: int) -> None:
        self.purified_flag = purified_flag
        self.name = "MON"


class _Party:
    """Patches the two reads NamedPurificationTracker.poll makes."""

    def __init__(self, flags_by_species: "dict[int, int]") -> None:
        self.flags_by_species = flags_by_species

    def __enter__(self):
        self._members = rc.read_party_members
        self._correlate = rc.correlate_party_with_recap
        order = list(self.flags_by_species)
        rc.read_party_members = lambda *a, **k: [
            _Member(i, species) for i, species in enumerate(order)
        ]
        rc.correlate_party_with_recap = lambda *a, **k: {
            i: (_Recap(self.flags_by_species[species]), "name_matches")
            for i, species in enumerate(order)
        }
        return self

    def __exit__(self, *exc):
        rc.read_party_members = self._members
        rc.correlate_party_with_recap = self._correlate


def _run(tracker, flags, polls=1):
    fired = []
    with _Party(flags):
        for _ in range(polls):
            fired += tracker.poll(BLOCK_BASE)
    return fired


class TestAnyPurifiedSpeciesCounts(unittest.TestCase):
    """The decisive property: the tracker has no notion of "is this one of the 83". A generated shadow is an
    ordinary party member with a purified flag, and that is all it needs to be."""

    # Deliberately a species that is NOT in the vanilla shadow roster.
    GENERATED = 448   # out of the Gen III dex range on purpose -- the tracker must not care

    def test_a_species_the_vanilla_roster_never_had_still_fires(self) -> None:
        counter = rc.PurificationCountTracker()
        _run(counter, {self.GENERATED: 0})
        fired = _run(counter, {self.GENERATED: 64}, polls=STREAK)
        self.assertEqual(fired, ["Purify 1 Shadow Pokemon"])

    def test_generated_and_vanilla_shadows_share_one_counter(self) -> None:
        """The cumulative thresholds are "purify N Shadow Pokemon", not "N of the original 83"."""
        counter = rc.PurificationCountTracker()
        _run(counter, {self.GENERATED: 0, 216: 0})         # 216 = Teddiursa, a real vanilla shadow
        fired = _run(counter, {self.GENERATED: 64, 216: 0}, polls=STREAK)
        self.assertEqual(fired, ["Purify 1 Shadow Pokemon"])
        fired = _run(counter, {self.GENERATED: 64, 216: 64}, polls=STREAK)
        self.assertEqual(fired, ["Purify 2 Shadow Pokemon"])
        self.assertEqual(counter.total_purified, 2)

    def test_there_is_no_shadow_whitelist_anywhere_in_the_path(self) -> None:
        """Stated as a test because it is the reason this works, and it would be easy to 'tidy up' by adding
        one. Any species at all must be able to reach the counter."""
        for species in (1, 151, 386, 448, 9999):
            counter = rc.PurificationCountTracker()
            _run(counter, {species: 0})
            self.assertEqual(
                _run(counter, {species: 64}, polls=STREAK), ["Purify 1 Shadow Pokemon"], species
            )

    def test_the_counter_still_stops_at_the_last_real_threshold(self) -> None:
        counter = rc.PurificationCountTracker()
        counter.total_purified = rc.PURIFICATION_LOCATION_COUNT
        _run(counter, {self.GENERATED: 0})
        self.assertEqual(_run(counter, {self.GENERATED: 64}, polls=STREAK), [])


if __name__ == "__main__":
    unittest.main()
