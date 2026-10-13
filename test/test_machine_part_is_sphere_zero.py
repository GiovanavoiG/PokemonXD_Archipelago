"""ADDENDUM 191. The Machine Part must be obtainable with nothing collected, in every mode.

Player: "The machine part is needed to progress the HQ, which is needed to get the snag machine. It should be
available in sphere 0 always."

WHY THE GRAPH DID NOT ALREADY SAY THIS. regions.REGION_EDGES records one job for the Machine Part -- repair
the scooter, open Agate Village -- and that is not all it does. Progressing the Pokemon HQ Lab needs it too,
and the HQ Lab is where the Snag Machine comes from, without which nothing in Orre works at all.

With travel randomization OFF the requirement held by accident: Agate is behind the Part and everything is
behind Agate, so the fill had nowhere else to put it. With it ON, ADDENDUM 106 makes Agate unconditionally
open and the Part gates literally nothing -- measured at 573 of 677 locations in the off mode against 0 of 675
in the on mode -- so the fill was free to bury it, and did.

These tests assert the guarantee directly rather than trusting either accident.

ADDENDUM 483 (issue #6) RETRACTS the Snag Machine half. Player: "You get snag machine without machine part, therefore
that logic is wrong." The lab hands over the Snag Machine at 0x0F; the Machine Part is Gateon's 0x16, after it. The
Part stays sphere zero -- with travel shuffle off it still opens Agate Village and everything past it -- but it no
longer gates snagging or the purification ladder.
"""
from __future__ import annotations

from BaseClasses import CollectionState

from . import PokemonXDTestBase
from .. import items


class _MachinePartIsReachableImmediately:
    """Shared body. `options` is set by each subclass; the assertion is identical in both modes."""

    def test_the_machine_part_is_reachable_with_nothing_collected(self) -> None:
        # WorldTestBase leaves the pool unfilled, so run the real fill here -- the guarantee is about where
        # the item ENDS UP, and asserting the declaration alone would only test that a dict was written to.
        from Fill import distribute_items_restrictive

        distribute_items_restrictive(self.multiworld)
        part = items.requirement_to_pool_item("Machine Part")
        placed = [location for location in self.multiworld.get_locations(self.player)
                  if location.item is not None and location.item.name == part]
        self.assertEqual(1, len(placed), f"expected exactly one {part} placement, got {len(placed)}")
        empty = CollectionState(self.multiworld)
        self.assertTrue(
            placed[0].can_reach(empty),
            f"{part} is on {placed[0].name} in {placed[0].parent_region.name}, which is not reachable with "
            f"nothing collected -- Agate Village is behind it with vanilla travel, so the run is stuck before it "
            f"starts",
        )

    def test_it_is_declared_early_rather_than_left_to_luck(self) -> None:
        part = items.requirement_to_pool_item("Machine Part")
        self.assertEqual(1, self.multiworld.early_items[self.player].get(part))

    def test_the_purification_ladder_needs_the_part_only_through_agate(self) -> None:
        """RETARGETED BY ADDENDUM 483. Was "the purification ladder is behind the Snag Machine": the ladder needed the
        Machine Part outright. Now it needs Agate Village (the Purify Chamber), which needs the Part only with travel
        shuffle off."""
        part = items.requirement_to_pool_item("Machine Part")
        first = self.multiworld.get_location("Purify 1 Shadow Pokemon", self.player)
        without = CollectionState(self.multiworld)
        for item in self.multiworld.itempool:
            if item.player == self.player and item.name != part and item.advancement:
                without.collect(item, True)
        agate_needs_the_part = not self.multiworld.worlds[self.player].options.randomize_travel_locations
        self.assertEqual(not agate_needs_the_part, first.can_reach(without))
        without.collect(self.get_item_by_name(part), True)
        self.assertTrue(first.can_reach(without))

class TestMachinePartTravelOn(_MachinePartIsReachableImmediately, PokemonXDTestBase):
    options = {"randomize_travel_locations": True, "key_item_shuffle": True,
               "randomize_chests": True, "randomize_shops": True}


class TestMachinePartTravelOff(_MachinePartIsReachableImmediately, PokemonXDTestBase):
    options = {"randomize_travel_locations": False, "key_item_shuffle": True,
               "randomize_chests": True, "randomize_shops": True}
