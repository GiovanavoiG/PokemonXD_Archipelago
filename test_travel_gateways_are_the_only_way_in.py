"""ADDENDUM 190. With randomize_travel_locations on, a destination's own item is the ONLY way to it.

The player, reading a generated seed: "Pyrite cannot open of its own shop. All of this logic is busted -- you
are not accounting for *having access to the region*."

WHAT HAD DRIFTED. ADDENDUM 104 built the travel gateways as an EXTRA entrance alongside the vanilla story
chain, and said so: turning the option on "can only ever make a region reachable EARLIER". True when written.
ADDENDUM 171 then made Client.enforce_travel_locks hold every not-yet-received destination's map bit CLEAR on
every tick -- the story unlock is taken back as fast as the game grants it -- and the region graph was never
told. Logic kept offering a path the client was actively re-locking.

MEASURED before the fix, on a travel-shuffle world holding every progression item EXCEPT the twelve travel
unlocks: all 675 locations reachable. The twelve items gated nothing at all, while in game they gated
everything.

The two tests below are the inverse-shaped question -- not "is each gateway wired up?", which can only answer
yes, but "is there any way in that is not the gateway?" and "does the graph settle in one pass?".
"""
from __future__ import annotations

from BaseClasses import CollectionState

from . import PokemonXDTestBase
from .. import travel_locations
from ..regions import REGION_EDGES

TRAVEL_ON = {
    "randomize_travel_locations": True,
    "key_item_shuffle": True,
    "randomize_chests": True,
    "randomize_shops": True,
}


def _state_holding_everything_except_travel_unlocks(multiworld) -> CollectionState:
    state = CollectionState(multiworld)
    for item in multiworld.itempool:
        if item.advancement and not item.name.startswith(travel_locations.TRAVEL_UNLOCK_ITEM_PREFIX):
            state.collect(item, True)
    state.sweep_for_advancements()
    return state


class TestTravelGatewaysAreTheOnlyWayIn(PokemonXDTestBase):
    options = dict(TRAVEL_ON)

    def test_no_gateway_only_region_is_reachable_without_its_unlock(self) -> None:
        """The bug, stated as a test. Every item in the pool except the twelve unlocks opens nothing."""
        state = _state_holding_everything_except_travel_unlocks(self.multiworld)
        reachable = sorted(
            region for region in travel_locations.gateway_only_regions()
            if state.can_reach(region, player=self.player)
        )
        self.assertEqual(
            [], reachable,
            "these regions are reachable without their travel unlock, but the client holds their map bit "
            "clear until that item arrives -- logic is promising access the game will refuse",
        )

    def test_kaminkos_house_stays_open(self) -> None:
        """Kaminko's is reachable with no travel unlock at all -- which is WHY its item was retired.

        RETARGETED 2026-09-25 (ADDENDUM 356). This used to assert the exemption: Kaminko's sat in
        `TRAVEL_CLEAR_EXEMPT`, so the client never re-locked it and `gateway_only_regions()` never suppressed
        its chain edge. Both are still true in effect, but by a shorter route -- Kaminko's is no longer a
        randomizable destination at all, so there is nothing to exempt and the exempt set is empty.

        THE PROPERTY IS UNCHANGED and is the one that matters: with every travel unlock withheld, Kaminko's
        House is still reachable. That was the finding ADDENDUM 270 recorded as "filler wearing a key item's
        name", and it is what made retiring the item safe rather than merely tidy."""
        self.assertNotIn("Kaminko's House", travel_locations.TRAVEL_LOCATION_NAMES)
        self.assertNotIn("Kaminko's House", travel_locations.gateway_only_regions())
        self.assertNotIn("Kaminko's House", travel_locations.TRAVEL_LOCATION_TARGET_REGION)
        state = _state_holding_everything_except_travel_unlocks(self.multiworld)
        self.assertTrue(state.can_reach("Kaminko's House", player=self.player))

    def test_the_exempt_set_is_empty_and_is_not_a_tombstone(self) -> None:
        """ADDENDUM 356. The set stays as the single source both halves derive from, but a retired name must
        not be parked in it -- that would silently exempt the destination if anyone put it back in the bit
        table, which is the opposite of what retiring it meant."""
        self.assertEqual(frozenset(), travel_locations.TRAVEL_CLEAR_EXEMPT)
        self.assertEqual(set(travel_locations.TRAVEL_LOCATION_TARGET_REGION.values()),
                         set(travel_locations.gateway_only_regions()))

    def test_every_destination_is_reachable_in_one_pass(self) -> None:
        """No entrance rule may depend on reachability another entrance rule has not computed yet.

        A rule that calls `state.can_reach(other_region)` is evaluated against the PREVIOUS pass's answer, so a
        chain of them resolves one link per pass. The first cut of the ADDENDUM 190 fix did exactly that --
        Phenac gates SS Libra gates Snagem gates the Key Lair -- and `all_state`, which is the state Fill
        plans against, reported all three unreachable while holding every item in the pool. Region
        prerequisites are entrance SOURCES now; this test is what notices if one turns back into a question.
        """
        state = CollectionState(self.multiworld)
        for item in self.multiworld.itempool:
            if item.advancement:
                state.collect(item, True)
        state.update_reachable_regions(self.player)
        unreachable = sorted(
            region for region in set(travel_locations.TRAVEL_LOCATION_TARGET_REGION.values())
            if not state.can_reach(region, player=self.player)
        )
        self.assertEqual(
            [], unreachable,
            "reachable only after extra passes -- an entrance rule is asking a question it should be "
            "expressing as its source region",
        )

    def test_the_suppressed_edges_are_exactly_the_gateway_only_ones(self) -> None:
        """Every chain edge that survives points at a region with no travel unlock of its own."""
        gateway_only = travel_locations.gateway_only_regions()
        surviving = {
            entrance.name
            for region in self.multiworld.get_regions(self.player)
            for entrance in region.entrances
        }
        for _source, target, _required in REGION_EDGES:
            if target not in gateway_only:
                continue
            self.assertTrue(
                all(not name.startswith(f"{_source} -> {target}") for name in surviving),
                f"the story chain still walks into {target}, which the client re-locks",
            )

    def test_the_data_rom_survives_the_suppression(self) -> None:
        """A suppressed edge's item requirement moves to the gateway rather than evaporating.

        Cipher Lab and the Poke Spots have a Data ROM requirement on a chain edge that is now suppressed.
        Flying there does not hand you the ID Card, so holding the unlock alone must not be enough.

        NARROWED 2026-09-16 (ADDENDUM 240): Pyrite Town used to be in this list and no longer belongs.
        Player: "Pyrite vending machine and first shop version are accessible as soon as pyrite town is."
        Plain Pyrite carries no ROM requirement any more, so flying there on its own unlock SHOULD open it --
        that is the feature, not the leak. The test below asserts that directly rather than leaving it
        untested.
        """
        state = CollectionState(self.multiworld)
        for item in self.multiworld.itempool:
            if item.advancement and item.name.startswith(travel_locations.TRAVEL_UNLOCK_ITEM_PREFIX):
                state.collect(item, True)
        state.sweep_for_advancements()
        for region in ("Cipher Lab", "Poke Spots"):
            self.assertFalse(
                state.can_reach(region, player=self.player),
                f"{region} opened on its travel unlock alone -- the Data ROM requirement was dropped with the "
                f"suppressed chain edge instead of moving to the gateway",
            )
        self.assertTrue(
            state.can_reach("Pyrite Town", player=self.player),
            "plain Pyrite Town has no Data ROM requirement any more, so its own travel unlock must be enough",
        )


class TestTravelOffIsUntouched(PokemonXDTestBase):
    options = {"randomize_travel_locations": False, "key_item_shuffle": True}

    def test_the_vanilla_chain_still_runs(self) -> None:
        """With the option off there are no gateways, so every region must still chain off its predecessor."""
        state = CollectionState(self.multiworld)
        for item in self.multiworld.itempool:
            if item.advancement:
                state.collect(item, True)
        state.sweep_for_advancements()
        for _source, target, _required in REGION_EDGES:
            self.assertTrue(
                state.can_reach(target, player=self.player),
                f"{target} is unreachable with every item held and travel randomization off",
            )
