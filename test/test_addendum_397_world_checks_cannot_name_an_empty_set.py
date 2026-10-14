"""SUPERSEDED BY ADDENDUM 404 (2026-10-03) -- chests are always checks, so `world_checks` can never name nothing.

The fallback this file was written for is gone. It fired only when chests, shop purchases and trainer defeats
were ALL off; ADDENDUM 404 removed the chest option, so that combination cannot be configured and the fallback
could never bind again. Per ADDENDA 247/298 it was deleted rather than left standing. What it was for is now
guaranteed by construction, and the tests below check that guarantee instead: `world_checks` always has chests to
name, the zero-margin configuration has room in sphere zero, and the fallback text is not quietly reintroduced.

The original record follows unchanged.

ADDENDUM 397 (2026-10-01) -- `world_checks` falls back to `everything` when it names nothing.

Player: "Shops are progression eligible. ... rethink this whole thing"
        "there's so many eligible progression items. go tally them and mark them"
        "Even with all the options off."

They were right on every count, and ADDENDUM 396 had stopped one rung short of the cause.

WHAT 396 GOT RIGHT: every fill failure in a 500-seed roll had more progression items than non-EXCLUDED
locations. WHAT IT GOT WRONG: it called that the bug. It is the symptom. The cause is that
`progression_locations = world_checks` NAMES three categories -- chests, shop purchases and trainer defeats
-- and a seed with all three of those turned off selects an EMPTY SET. The ladder in `locations.py` then
demotes every Shadow catch and every purification to filler for a restriction that no longer restricts
anything, and what survives is six locations out of 1,191 names: the five Krane Memos and Catch - Eevee.

Shop purchases were never demotable by this option at all -- `world_checks_excluded` is `scope < 1` and the
minimum scope is 1 since `overworld_only` was retired, so that branch has been dead code. A shop location
that is created is always progression-eligible. 396's analysis read "0 shop locations" (because
`randomize_shops` was off and none were CREATED) as "shops were demoted", which is how the wrong half of the
mechanism got written down.

WHAT THE TALLY SHOWED. Same seed, same four category toggles off, only `progression_locations` differing:

    scope = everything (the default)   177 locations created, 37 progression-eligible, fill succeeds
    scope = world_checks               177 locations created,  6 progression-eligible, fill dies

So the world is NOT fragile with the options off. It is fragile with ONE option plus all three of that
option's own categories disabled.

THE ZERO-MARGIN CASE, which is why this is a fix and not a cosmetic one. 396's guard compares progression
items against capacity and refuses when items exceed it. There is a band it cannot see:

    capacity 6, progression items 6, sphere-zero eligible locations 1  ->  FillError, every seed

Counts match, so the guard stays silent; fill dies anyway. Catch - Eevee is the only one of the six in sphere
zero -- the five Krane Memos sit behind Data ROM and Mayor's Note -- and `fill_restrictive` is a heuristic,
not a solver, so with zero slack and one opening slot it fails on an instance that is technically
satisfiable. That is the "too small sphere 1" the Archipelago maintainer guessed at and 396 denied.

MEASURED. 120 seeds rolled inside the danger band (world_checks, all three off, small item pools):

    before   87 refused   30 clean    3 fill failures
    after   15 refused  105 clean    0 fill failures

Full suite under the change: the only failures were ADDENDUM 396's own four tests, which asserted a
starvation that no longer happens. No pre-existing test moved.

396's count guard STAYS, as a backstop -- 15 of those 120 still need refusing, and they are genuinely
impossible pools rather than a contradiction in the options.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from BaseClasses import CollectionState, LocationProgressType

from . import PokemonXDTestBase
from .. import locations as L

# The shape ADDENDUM 397 rescued: every OPTIONAL category off, scope `world_checks`. Chests can no longer be off.
ALL_OPTIONAL_CATEGORIES_OFF = {
    "randomize_shops": False,
    "shuffle_trainer_defeats": False,
    "randomize_travel_locations": False,
    "purification_progression_cap": 0,   # ADDENDUM 449: was progression_locations: world_checks
    "key_item_shuffle": True,
}


def _eligible(world) -> "list":
    return [
        location for location in world.multiworld.get_locations(world.player)
        if location.address is not None and location.progress_type is not LocationProgressType.EXCLUDED
    ]


class TestWorldChecksAlwaysHasChestsToName(PokemonXDTestBase):
    options = ALL_OPTIONAL_CATEGORIES_OFF

    def test_the_seed_generates(self) -> None:
        self.assertTrue(self.multiworld.itempool)

    def test_chests_carry_the_scope(self) -> None:
        chests = [l for l in _eligible(self.world) if L.is_chest_location(l.name)]
        self.assertGreater(len(chests), 50)

    def test_the_scope_is_honoured_rather_than_widened(self) -> None:
        """With 397's fallback gone, `world_checks` means what it says: catches stay filler-only."""
        catches = [
            l for l in self.multiworld.get_locations(self.player)
            if l.name.startswith("Catch - ")
            and l.name not in (L.GUARANTEED_SPECIES_LOCATION, L.EEVEELUTION_LOCATION_NAME)
        ]
        self.assertTrue(catches)
        self.assertTrue(all(c.progress_type is LocationProgressType.EXCLUDED for c in catches))


class TestTheZeroMarginCaseHasRoomNow(PokemonXDTestBase):
    """Capacity 6 against 6, one sphere-zero slot -- the band ADDENDUM 396's guard could not see. Chests fixed it."""

    options = {**ALL_OPTIONAL_CATEGORIES_OFF, "shuffle_scooter_upgrade": False,
               "robo_kyogre_parts_unlock_citadark": False}

    def test_sphere_zero_is_wide(self) -> None:
        """Measured 2026-10-03: 8 eligible locations open with no items (Catch - Eevee plus seven chests in the
        HQ Lab and Gateon), against 1 before chests were permanent. Capacity 80 against 6 progression; 0 of 20
        seeds failed fill."""
        empty = CollectionState(self.multiworld)
        self.assertGreaterEqual(sum(1 for l in _eligible(self.world) if l.can_reach(empty)), 8)


class TestTheFallbackIsGone(unittest.TestCase):
    def test_it_is_not_reintroduced(self) -> None:
        source = (Path(__file__).resolve().parent.parent / "locations.py").read_text(encoding="utf-8")
        self.assertNotIn("if _scope < 2 and not (include_chests", source)
        self.assertIn("    include_chests = True", source)

    def test_the_scope_option_is_gone(self) -> None:
        """ADDENDUM 449 removed `progression_locations`; nothing reads it any more."""
        source = (Path(__file__).resolve().parent.parent / "locations.py").read_text(encoding="utf-8")
        self.assertNotIn('getattr(world.options, "progression_locations"', source)
        from ..options import PokemonXDOptions
        self.assertNotIn("progression_locations", PokemonXDOptions.type_hints)
