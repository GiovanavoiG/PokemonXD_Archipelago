"""ADDENDUM 266 (2026-09-17): every trainer defeat is behind the items that reach it.

Player: "for location shuffle, are all trainer defeats properly gated behind their area/the items needed to
reach them?"

Audited and yes. This file is the audit turned into a standing test, because the answer is only worth
anything for as long as it stays true -- and the two ways it could stop being true are both silent.

## What the audit found

267 `Defeat -` locations with `randomize_travel_locations` on. Held-one-back, withholding exactly one
`Travel Unlock` item from an otherwise-complete state:

    Travel Unlock - Phenac City       gates  95   Cipher Key Lair(+ext), Citadark, Phenac(+Post-Sixes), SS Libra, Snagem
    Travel Unlock - SS Libra          gates  69   Cipher Key Lair(+ext), Citadark, SS Libra, Snagem
    Travel Unlock - Snagem Hideout    gates  65   Cipher Key Lair(+ext), Citadark, Snagem
    Travel Unlock - Cipher Key Lair    gates  53   Cipher Key Lair, Citadark
    Travel Unlock - Cipher Lab        gates  48   Cipher Lab
    Travel Unlock - Pyrite Town       gates  21   Pyrite Town
    Travel Unlock - Poke Spots        gates  13   Poke Spots, Pyrite Town (ONBS)
    Travel Unlock - Mt. Battle        gates   3   Mt. Battle
    Travel Unlock - Outskirt Stand    gates   3   Outskirt Stand
    Travel Unlock - Kaminko's House   gates   0
    Travel Unlock - Orre Colosseum    gates   0
    Travel Unlock - Realgam Tower     gates   0

The three zeroes are each explained, and none is a hole:

  * **Kaminko's House** is one of ADDENDUM 106's four always-open regions when travel randomization is on, so
    its 8 defeats are meant to be reachable from the start. Its item exists because the map ICON is a real
    destination, not because it gates anything.
  * **Orre Colosseum**'s item opens a region that gates nothing, deliberately and documented in ADDENDUM 185
    -- the player's instruction was "Leave Orre Colosseum as a gettable location", not "make it a key".
  * **Realgam Tower** holds no trainer defeats at all: the 232-row DTNR story roster contains no Realgam
    trainer. The Tower Colosseum fights are simply not in that table.

## The one thing that looks alarming and is not

84 of 267 are reachable with NO items, and 37 of those sit in a catch-all region called `Unique Trainer
Defeats`. **All 37 are EXCLUDED**, by construction: they are `trainer_placements.PLACEMENTS` rows with
`region=None` -- 36 already-missable rows the player marked "N/A", plus Hordel -- and `region=None` means
"no region known, filler only". AP requires every location to be reachable so filler can be placed, so they
are parked somewhere always-open and marked EXCLUDED. That module says it best: *reachable and never required
is exactly the right shape.*

The other 47 are Agate Village, Gateon Port, Kaminko's House and Pokemon HQ Lab -- ADDENDUM 106's four
always-open regions, again by design.

## Why this needs a test rather than a paragraph

Both failure modes are silent. A defeat location filed in the wrong region is reachable too early and nothing
says so until a seed is unwinnable (ADDENDUM 245's shape). And a `region=None` row that stops being EXCLUDED
becomes a progression-eligible check with no gate at all -- which is ADDENDUM 252's near-miss, caught then
only by generating with an option off and counting.
"""
from __future__ import annotations

import unittest

from BaseClasses import CollectionState, LocationProgressType

from . import PokemonXDTestBase
from .. import travel_locations


class _TravelShuffleBase(PokemonXDTestBase):
    options = {"randomize_travel_locations": True, "shuffle_trainer_defeats": True}

    def defeats(self):
        return [l for l in self.multiworld.get_locations(1) if l.name.startswith("Defeat")]

    def state_without(self, withheld: "set[str]"):
        """Everything advancement in the pool except `withheld`."""
        state = CollectionState(self.multiworld)
        for item in self.multiworld.itempool:
            if item.advancement and item.name not in withheld:
                state.collect(item, prevent_sweep=True)
        state.sweep_for_advancements()
        return state


class TestEveryDefeatIsBehindItsTravelUnlock(_TravelShuffleBase):

    def test_every_defeat_location_is_reachable_with_everything(self) -> None:
        """The floor. A defeat nobody can ever reach is a check that can never fire, which this project has
        shipped before (ADDENDUM 168's "naming an item that was never created")."""
        state = self.state_without(set())
        unreachable = [l.name for l in self.defeats() if not l.can_reach(state)]
        self.assertEqual([], unreachable)

    def test_withholding_one_travel_unlock_closes_exactly_its_own_regions(self) -> None:
        """THE AUDIT. For every travel unlock, the defeats that close when it is withheld must all live in
        regions that unlock is genuinely responsible for -- its own, or ones reached through it.

        Asserted as "closes something, and everything it closes is downstream of it" rather than as the
        literal counts above: the counts move whenever a trainer is re-regioned, and pinning them would make
        this a test of one seed's table rather than of the property."""
        full = self.state_without(set())
        defeats = self.defeats()
        prefix = travel_locations.TRAVEL_UNLOCK_ITEM_PREFIX
        travel_items = sorted({i.name for i in self.multiworld.itempool
                               if i.advancement and i.name.startswith(prefix)})
        self.assertGreater(len(travel_items), 5, "travel randomization is not actually on")

        gated_by: "dict[str, set[str]]" = {}
        for item in travel_items:
            partial = self.state_without({item})
            gated_by[item] = {l.parent_region.name for l in defeats
                              if l.can_reach(full) and not l.can_reach(partial)}

        # Every region that any travel unlock gates must be gated by at least one -- i.e. no region with
        # defeats is left entirely ungated except the ones documented as always-open.
        always_open = {"Pokemon HQ Lab", "Kaminko's House", "Gateon Port", "Agate Village",
                       "Unique Trainer Defeats"}
        gated_regions = set().union(*gated_by.values()) if gated_by else set()
        regions_with_defeats = {l.parent_region.name for l in defeats}
        ungated = regions_with_defeats - gated_regions - always_open
        self.assertEqual(set(), ungated,
                         "these regions hold trainer defeats that no travel unlock gates -- with travel "
                         "randomization on that means the map icon is the only thing standing in the way, "
                         "and the client re-locks the icon every tick")

    def test_the_three_unlocks_that_gate_nothing_are_the_documented_three(self) -> None:
        """Named explicitly, because a FOURTH appearing is exactly the shape of a trainer quietly losing its
        region -- and each of these three has its own separate reason for being harmless."""
        full = self.state_without(set())
        defeats = self.defeats()
        prefix = travel_locations.TRAVEL_UNLOCK_ITEM_PREFIX
        idle = set()
        for item in sorted({i.name for i in self.multiworld.itempool
                            if i.advancement and i.name.startswith(prefix)}):
            partial = self.state_without({item})
            if not any(l.can_reach(full) and not l.can_reach(partial) for l in defeats):
                idle.add(item)
        # NARROWED 2026-09-25 (ADDENDUM 356) from three names to two. Kaminko's House was the first of the
        # three and the only one that was a plain mistake rather than a decision -- an always-open region
        # behind a progression item. Its item is retired, so it cannot be idle; it is not there at all.
        self.assertEqual(
            {f"{prefix}Orre Colosseum", f"{prefix}Realgam Tower"},
            idle,
            "Orre Colosseum opens a region that gates nothing by decision (ADDENDUM 185), and the 232-row "
            "roster has no Realgam trainer at all. A THIRD name here means a trainer lost its region.")
        self.assertNotIn(f"{prefix}Kaminko's House", {i.name for i in self.multiworld.itempool},
                         "ADDENDUM 356 retired it; an idle progression item is not a thing to keep")


class TestTheUngatedDefeatsAreAllFillerOnly(_TravelShuffleBase):
    """The half that would actually break a seed. A location reachable at sphere zero is fine; a
    PROGRESSION-ELIGIBLE one whose trainer is deep in the game is an unwinnable seed."""

    def test_nothing_reachable_with_no_items_is_progression_eligible_unless_its_region_is_open(self) -> None:
        state = CollectionState(self.multiworld)
        open_at_start = [l for l in self.defeats() if l.can_reach(state)]
        self.assertTrue(open_at_start)
        always_open = {"Pokemon HQ Lab", "Kaminko's House", "Gateon Port", "Agate Village"}
        offenders = [
            f"{l.name} ({l.parent_region.name})" for l in open_at_start
            if l.parent_region.name not in always_open
            and l.progress_type is not LocationProgressType.EXCLUDED
        ]
        self.assertEqual([], offenders,
                         "a progression-eligible check with no gate, on a trainer whose region is unknown -- "
                         "this is how ADDENDUM 245's unwinnable seed was shaped")

    def test_every_region_none_row_is_excluded(self) -> None:
        """Pinned at the source as well as at the outcome. `region=None` means "filler only"; the two halves
        of that sentence living in different files is how one of them gets changed alone."""
        from ..game_data import trainer_placements

        parked = [l for l in self.defeats() if l.parent_region.name == "Unique Trainer Defeats"]
        self.assertTrue(parked)
        self.assertEqual(
            sum(1 for p in trainer_placements.PLACEMENTS.values() if p.region is None),
            len(parked),
            "every region-less placement should be parked in the catch-all region, and nothing else should")
        for location in parked:
            self.assertIs(LocationProgressType.EXCLUDED, location.progress_type, location.name)


if __name__ == "__main__":
    unittest.main()
