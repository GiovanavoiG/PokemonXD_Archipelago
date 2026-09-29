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
            f"nothing collected -- the Snag Machine is behind it, so the run is stuck before it starts",
        )

    def test_it_is_declared_early_rather_than_left_to_luck(self) -> None:
        part = items.requirement_to_pool_item("Machine Part")
        self.assertEqual(1, self.multiworld.early_items[self.player].get(part))

    def test_the_purification_ladder_is_behind_the_snag_machine(self) -> None:
        """"Sphere zero" has to exclude the places that need the Part, or it means nothing.

        The first cut of ADDENDUM 191 declared the Machine Part early and stopped there. The purification
        ladder was gated on reaching Agate Village alone -- which with travel randomization on is sphere zero
        -- so `Purify N` counted as a sphere-zero location and the fill put the Machine Part on `Purify 6`:
        purify six Shadow Pokemon to obtain the Snag Machine you need to snag any. Purifying means snagging
        first, so the ladder is ANDed with the Part.
        """
        empty = CollectionState(self.multiworld)
        first = self.multiworld.get_location("Purify 1 Shadow Pokemon", self.player)
        self.assertFalse(
            first.can_reach(empty),
            "the purification ladder is reachable with nothing collected, so the Machine Part can be hidden "
            "on it -- behind the Snag Machine it is needed to obtain",
        )
        part = items.requirement_to_pool_item("Machine Part")
        with_part = CollectionState(self.multiworld)
        with_part.collect(self.get_item_by_name(part), True)
        with_part.sweep_for_advancements()
        self.assertTrue(first.can_reach(with_part),
                        "and it must open on the Part alone once Agate Village is reachable")


class TestMachinePartTravelOn(_MachinePartIsReachableImmediately, PokemonXDTestBase):
    options = {"randomize_travel_locations": True, "key_item_shuffle": True,
               "randomize_chests": True, "randomize_shops": True}


class TestMachinePartTravelOff(_MachinePartIsReachableImmediately, PokemonXDTestBase):
    options = {"randomize_travel_locations": False, "key_item_shuffle": True,
               "randomize_chests": True, "randomize_shops": True}
