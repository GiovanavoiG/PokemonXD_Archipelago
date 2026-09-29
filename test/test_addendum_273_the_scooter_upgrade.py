"""ADDENDUM 273 (2026-09-18): the Scooter Upgrade.

Player: *"Let's add a scooter item that raises our floor for SS Libra to 0x5A - this would need to be active
with location shuffle on AND off - but SS libra is the only one that needs modified with it off. This also
means that unless we have the scooter item, SS Libra should be set to 0x4E on the map screen."*

SS Libra is one map ICON over two REGIONS (`story_bytes.AREA_GROUPS`): the stranded first visit at 0x4E and
the real ship at 0x5A. The ladder names the step between them -- `0x57 -> 0x5A, "scooter upgraded in Gateon --
the real SS Libra visit"` -- so the upgrade is a real story event with a real byte, and this item now stands
in for it.

## The rule it replaces

`AreaFloorRule("SS Libra", 0x5A, (("Gateon Port", 0x5A),))` is DELETED, on the player's call ("Scooter item
replaces it entirely"). Keeping it as an alternative would have meant a player who walked Gateon far enough
got the real ship whether or not the multiworld ever sent the item -- the item gating nothing, which is the
defect ADDENDUM 270 found in `Travel Unlock - Kaminko's House`.

It could not simply be EDITED to mention the item, because no `AreaFloorRule` can express "the player holds an
Archipelago item". That is why the floor moved into `AreaStoryByteMemory`.

## Two halves, deliberately separate

Deleting the rule left nothing that could ever name 0x5A -- `area_entry_floor` is the ICON's first tier (0x4E)
by ADDENDUM 247's design. So the item is a floor CANDIDATE (`_scooter_floor`) as well as a CAP
(`_cap_ss_libra`):

* the **raise** applies only to the real-ship region, never to `SS Libra (stranded)` -- raising the stranded
  region would delete the visit the Scooter is supposed to come after;
* the **cap** applies to the RESULT, after the high-water branch, because a mark of 0x5A can be sitting in a
  persisted file from a session where the player did hold the item, and a gate that only filtered the static
  floor would be walked straight past by the memory's own file.

The first cut had only the cap, and ADDENDUM 247's own tests caught it: holding the Scooter returned 0x4E.

## What it gates, which is more than SS Libra

In logic the item sits on `("Kaminko's House (Robo Groudon)", "SS Libra")`, and SS Libra is a chokepoint in
the vanilla chain -- everything past it is behind the Scooter too: `Cipher Key Lair` and its two tiers,
`Outskirt Stand`, `Snagem Hideout` and `Citadark Isle`. That is vanilla's own shape (you cross the ship to
reach the Key Lair), not something engineered here, and it makes the Scooter a required progression item for
the goal.
"""
from __future__ import annotations

import sys
import types
import unittest

if "dolphin_memory_engine" not in sys.modules:
    _stub = types.ModuleType("dolphin_memory_engine")
    for _n in ("hook", "un_hook"):
        setattr(_stub, _n, lambda: None)
    _stub.is_hooked = lambda: False
    _stub.read_bytes = lambda address, length: b""
    _stub.write_bytes = lambda address, data: None
    sys.modules["dolphin_memory_engine"] = _stub

from BaseClasses import CollectionState

from . import PokemonXDTestBase
from .. import items, ram_client as rc, travel_locations
from ..game_data import story_bytes as sb


class TestTheItemItself(unittest.TestCase):
    def test_it_exists_and_is_progression(self) -> None:
        self.assertEqual("Scooter Upgrade", items.SCOOTER_ITEM_NAME)
        self.assertEqual("progression", items.ITEM_TABLE[items.SCOOTER_ITEM_NAME].classification.name)

    def test_it_has_a_frozen_id(self) -> None:
        """ADDENDUM 270's rule, applied on the commit that adds the item rather than discovered later."""
        self.assertEqual(257, items._FROZEN_ITEM_OFFSETS[items.SCOOTER_ITEM_NAME])
        self.assertEqual(257, items.ITEM_TABLE[items.SCOOTER_ITEM_NAME].id_offset)

    def test_it_has_no_bag_item(self) -> None:
        """The scooter upgrade is a cutscene, not an item you carry. A `game_item_id` here would send the
        delivery path looking for a Bag slot that does not exist."""
        self.assertIsNone(items.ITEM_TABLE[items.SCOOTER_ITEM_NAME].game_item_id)

    def test_it_is_not_in_the_real_key_item_table(self) -> None:
        """`game_data/key_items.py` rows all have real ids and feed the Bag reconciler."""
        from ..game_data import key_items

        self.assertNotIn(items.SCOOTER_ITEM_NAME, key_items.KEY_ITEM_BY_NAME)

    def test_it_follows_its_own_option_and_not_key_item_shuffle(self) -> None:
        """ADDENDUM 274. It is NOT in `GATING_KEY_ITEM_NAMES`: that set means "a real story key item, in the
        pool when `key_item_shuffle` is on", and the Scooter is neither half of that. Putting it there would
        have made one option silently control two unrelated things."""
        self.assertNotIn(items.SCOOTER_ITEM_NAME, items.GATING_KEY_ITEM_NAMES)
        self.assertIn(items.SCOOTER_ITEM_NAME, items.OPTION_GATED_PROGRESSION_ITEMS)


class TestTheOldRuleIsGone(unittest.TestCase):
    def test_no_floor_rule_lets_ANOTHER_AREA_open_the_real_ship(self) -> None:
        """NARROWED by ADDENDUM 293, which gave the ship a rule of its own.

        What ADDENDUM 273 removed was `AreaFloorRule("SS Libra", 0x5A, (("Gateon Port", 0x5A),))` -- late
        Gateon opening the upgraded ship, which would have meant the Scooter gated nothing for a player who
        got there by playing. The 293 rule is a different animal: it names only SS Libra, it cannot be
        satisfied by progress anywhere else, and its floor is above the scooter tier rather than at it, so it
        can never stand in for the item. The property 273 actually needs is that NO OTHER AREA can open this
        one, and that is what is asserted."""
        for rule in sb.AREA_FLOOR_RULES:
            if rule.target != "SS Libra":
                continue
            self.assertEqual([], [area for area, _ in rule.requires if area != "SS Libra"],
                             f"{rule.what!r} lets another area open the ship -- that is the Scooter's job")

    def test_late_gateon_no_longer_opens_the_real_ship(self) -> None:
        self.assertIsNone(sb.dynamic_region_floor("SS Libra", {"Gateon Port": 0x5A}))

    def test_the_two_tiers_are_still_what_the_ladder_says(self) -> None:
        upgrade = [t for t in sb.TRANSITIONS if t.after == rc.SS_LIBRA_SCOOTER_FLOOR]
        self.assertEqual(1, len(upgrade))
        self.assertIn("scooter", upgrade[0].what.lower())
        self.assertEqual(rc.SS_LIBRA_STRANDED_FLOOR, sb.area_entry_floor("SS Libra"))


class TestTheByteTheMapScreenWrites(unittest.TestCase):
    def test_without_the_scooter_it_is_the_stranded_floor(self) -> None:
        mem = rc.AreaStoryByteMemory(scooter_held=False)
        self.assertEqual(0x4E, mem.target_for("SS Libra"))

    def test_with_the_scooter_it_is_the_real_ship(self) -> None:
        mem = rc.AreaStoryByteMemory(scooter_held=True)
        self.assertEqual(0x5A, mem.target_for("SS Libra"))

    def test_the_stranded_region_is_never_raised_by_the_item(self) -> None:
        """Raising it would delete the visit the Scooter is meant to come after."""
        for held in (False, True):
            mem = rc.AreaStoryByteMemory(scooter_held=held)
            self.assertEqual(0x4E, mem.target_for("SS Libra (stranded)"), f"scooter_held={held}")

    def test_a_persisted_high_water_mark_does_not_beat_the_gate(self) -> None:
        """The reason the cap is applied to the result rather than to the floor lookup. This mark is exactly
        what a file written in a session where the player HELD the item looks like."""
        mem = rc.AreaStoryByteMemory(scooter_held=False)
        mem.observe("SS Libra", 0x5C)
        self.assertEqual(0x4E, mem.target_for("SS Libra"))
        self.assertEqual(1, mem.capped_ss_libra)

    def test_the_mark_is_still_there_once_the_item_arrives(self) -> None:
        """Capped, not erased -- the gate must not cost the player progress they really made.

        ADDENDUM 293: the answer is 0x5D rather than the 0x5C mark, because 0x5C is a pass-through of the
        0x5B -> 0x5D transition and the ship skips it now. Still "not erased" -- the mark is what lets the
        skip's rule bind at all, and the result is above the stranded floor, which is the whole claim."""
        mem = rc.AreaStoryByteMemory(scooter_held=False)
        mem.observe("SS Libra", 0x5C)
        mem.target_for("SS Libra")
        mem.scooter_held = True
        self.assertEqual(0x5D, mem.target_for("SS Libra"))
        self.assertGreater(mem.target_for("SS Libra"), rc.SS_LIBRA_STRANDED_FLOOR)

    def test_no_other_area_is_touched(self) -> None:
        """*"SS libra is the only one that needs modified."*"""
        before = rc.AreaStoryByteMemory(scooter_held=True)
        after = rc.AreaStoryByteMemory(scooter_held=False)
        for region in ("Pyrite Town", "Phenac City", "Agate Village", "Cipher Lab", "Realgam Tower",
                       "Mt. Battle", "Citadark Isle", "Cipher Key Lair", "Snagem Hideout"):
            self.assertEqual(before.target_for(region), after.target_for(region), region)


class TestTheRoomsAndRegionsAreDerived(unittest.TestCase):
    """ADDENDUM 254's lesson applied up front: a hand-typed room set drifts from the table beside it."""

    def test_the_regions_come_from_area_groups(self) -> None:
        self.assertEqual(frozenset(sb.AREA_GROUPS["SS Libra"]), rc.SS_LIBRA_REGIONS)

    def test_the_rooms_come_from_the_region_table(self) -> None:
        from ..game_data import chest_regions

        expected = {room for room, region in chest_regions.ROOM_TO_REGION.items()
                    if region in rc.SS_LIBRA_REGIONS}
        self.assertEqual(expected, set(rc.SS_LIBRA_ROOM_IDS))
        self.assertTrue(rc.SS_LIBRA_ROOM_IDS, "an empty room set would make the off-mode gate silently inert")


class TestTheLogicGate(PokemonXDTestBase):
    options = {"randomize_travel_locations": False, "shuffle_scooter_upgrade": True}

    def test_the_real_ship_is_behind_the_item(self) -> None:
        state = CollectionState(self.multiworld)
        for name in self.KEY_ITEM_CHAIN:
            state.collect(self.get_item_by_name(name), prevent_sweep=True)
        state.sweep_for_advancements()
        self.assertFalse(state.can_reach("SS Libra", player=self.player),
                         "the whole vanilla chain must not be enough on its own")
        state.collect(self.get_item_by_name(items.SCOOTER_ITEM_NAME), prevent_sweep=True)
        state.sweep_for_advancements()
        self.assertTrue(state.can_reach("SS Libra", player=self.player))

    def test_everything_past_the_ship_is_behind_it_too(self) -> None:
        """Stated rather than discovered later: SS Libra is a chokepoint, so the Scooter gates the goal."""
        state = CollectionState(self.multiworld)
        for name in self.KEY_ITEM_CHAIN:
            state.collect(self.get_item_by_name(name), prevent_sweep=True)
        state.sweep_for_advancements()
        for region in ("Cipher Key Lair (exterior)", "Outskirt Stand", "Snagem Hideout", "Citadark Isle"):
            self.assertFalse(state.can_reach(region, player=self.player), region)

    def test_the_item_is_in_the_pool_with_the_option_on(self) -> None:
        self.assertIn(items.SCOOTER_ITEM_NAME, {i.name for i in self.multiworld.itempool})


class TestWithTheOptionOff(PokemonXDTestBase):
    """The default. Everything must behave exactly as it did before ADDENDUM 273 existed."""

    options = {"randomize_travel_locations": False, "shuffle_scooter_upgrade": False}

    def test_the_item_is_not_created(self) -> None:
        self.assertNotIn(items.SCOOTER_ITEM_NAME, {i.name for i in self.multiworld.itempool})

    def test_and_the_ship_is_therefore_not_gated_on_it(self) -> None:
        """`regions._item_is_in_the_pool` drops a requirement naming an item that was never created -- the
        same treatment the Machine Part and the Music Disc get. Naming an uncreated item would make every
        region past that edge permanently unreachable, which is a generation failure, not a gate."""
        state = CollectionState(self.multiworld)
        for item in self.multiworld.itempool:
            if item.advancement:
                state.collect(item, prevent_sweep=True)
        state.sweep_for_advancements()
        self.assertTrue(state.can_reach("SS Libra", player=self.player))
