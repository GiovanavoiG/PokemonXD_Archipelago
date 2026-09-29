"""ADDENDUM 270 (2026-09-18): the location-shuffle audit.

Player: "Can you go through all our location shuffle details and check for more bugs/issues/things that might
need changed?" Four parallel read-only audits (graph, client runtime, story-byte writers, item/location
tables); every finding below was re-verified here before anything was changed.

The five that were real, worst first.

## 1. A map destination is several regions, and the graph gated one of them (UNWINNABLE SEEDS)

`gateway_only_regions()` returned one region per destination -- the one its gateway connects to. But
`story_bytes.AREA_GROUPS` records the real shape: one map ICON, several regions. Pyrite Town is
`("Pyrite Town", "Pyrite Town (ONBS)")`; SS Libra is `("SS Libra (stranded)", "SS Libra")`.

A sibling tier entered from elsewhere kept its ordinary chain edge, so the graph believed you could reach it
without the destination's item -- while the client held that destination's map bit clear every tick.

Measured, `Travel Unlock - Pyrite Town` withheld, everything else in hand: **nine progression-eligible
locations in `Pyrite Town (ONBS)` still reachable.** A seed putting a key item on one generates cleanly and
cannot be finished. `Kaminko's House (Robo Groudon)` behind SS Libra was the same, two chests.

`shop_stock.py` already modelled this correctly. The region graph did not, and nothing compared them -- the
"two tables describing one fact" pattern again.

**The first fix attempt was wrong and the suite caught it.** Adding the siblings to `gateway_only` suppresses
their chain edges, and the gateway connects to its own target, not to the siblings -- so they were stranded
with no entrance at all. A sibling is not reached THROUGH the icon; it is reached through the game once the
icon has let you into the area. Its edge must survive and gain the item.

## 2. An unreadable story byte wrote blind, poisoning a file that outlives the client

`AreaStoryByteMemory.poll` guarded its "already right" short-circuit on `story_byte is not None`
and then wrote anyway when it was None -- without capturing `saved_byte`. `left_map_screen` reads a missing
`saved_byte` as "no map visit in progress", releases `_write_outstanding` and restores nothing. So the hovered
destination's floor stayed in the save, `observe()` banked it into the PERSISTED per-area high-water file, and
it was re-applied on every future entry.

The function's own contract forty lines up already said what should happen: *"an unknown destination, an area
with no story window, and an unreadable story byte each decline rather than defaulting."* Two of the three did.

## 3. A travel item paid out its own check

`vanilla_unlock_story_byte(D)` and `_story_byte_was_earned_here`'s `floor` are **the same function on the same
region**. With `floor <= threshold`, arriving at D satisfied both sides with equality -- and the area memory
had just committed exactly that floor. So `Unlock - D` fired the moment the player used `Travel Unlock - D`,
with no story progress at all. ADDENDUM 268's guard was structurally inert for the one destination it most
needed to cover.

Strictly-before is also what vanilla does: a destination's icon appears when the story reaches its value,
which happens somewhere else. You unlock the icon and then go.

## 4. The Parts override froze the map bookkeeping

`check_area_story_memory` returns early while the override holds the byte -- correctly, the byte is not its
business -- but `_room_before_map`, `saved_byte` and `_write_outstanding` are all cleared *below* that return.
An override arming mid-map-visit pinned them for the whole trip, so the next back-out was measured against a
room the player had left two areas ago: a back-out reads as a trip, or a trip as a back-out, and the byte is
committed to (or restored from) the wrong area's floor.

## 5. Eleven checks that could never fire

With `randomize_travel_locations` OFF, the 11 `Unlock - X` locations were still created -- and
`enforce_travel_locks`, the only thing that sends them, returns on its first line when the option is off.
Every other option-gated category had its own `continue`; this one computed `is_travel_unlock` and then used
it only to mark EXCLUDED, never to skip creation.

Also fixed in passing: the credit path's dedup guard named `ctx.locations_checked`, which nothing in this
client or in `CommonClient` ever writes, so it was always False and every earned `Unlock -` id was re-offered
every poll. Harmless -- `_send_checks` filters on the right set -- but the comment claimed a guarantee the
code did not provide.
"""
from __future__ import annotations

import pathlib
import re
import sys
import types
import unittest

if "dolphin_memory_engine" not in sys.modules:
    _stub = types.ModuleType("dolphin_memory_engine")
    _stub.hook = lambda: None
    _stub.un_hook = lambda: None
    _stub.is_hooked = lambda: False
    _stub.read_bytes = lambda address, length: b""
    _stub.write_bytes = lambda address, data: None
    sys.modules["dolphin_memory_engine"] = _stub

from unittest import mock

from BaseClasses import CollectionState, LocationProgressType

from . import PokemonXDTestBase
from .. import ram_client as rc
from .. import travel_locations
from ..game_data import story_bytes


class TestEveryTierOfADestinationIsBehindItsItem(PokemonXDTestBase):
    """FINDING 1 -- the unwinnable-seed one."""

    options = {"randomize_travel_locations": True, "shuffle_trainer_defeats": True, "randomize_chests": True}

    def _without(self, item_name: str):
        state = CollectionState(self.multiworld)
        for item in self.multiworld.itempool:
            if item.advancement and item.name != item_name:
                state.collect(item, prevent_sweep=True)
        state.sweep_for_advancements()
        return state

    def _progression_in(self, region_name: str, state):
        return [l for l in self.multiworld.get_locations(1)
                if l.parent_region.name == region_name
                and l.progress_type is not LocationProgressType.EXCLUDED
                and l.can_reach(state)]

    def test_no_sibling_tier_is_reachable_without_its_destinations_item(self) -> None:
        """Derived from the real tables, so a newly-grouped region is covered the day it is added rather than
        the day someone remembers to list it here."""
        siblings = travel_locations.travel_item_by_sibling_region()
        self.assertTrue(siblings, "no sibling tiers at all -- has AREA_GROUPS changed shape?")
        for region_name, item_name in sorted(siblings.items()):
            state = self._without(item_name)
            leaked = self._progression_in(region_name, state)
            self.assertEqual([], [l.name for l in leaked],
                             f"{region_name} is reachable without {item_name}, but the client holds that "
                             f"destination's map bit clear every tick -- a key item here is an unwinnable seed")

    def test_pyrite_onbs_specifically(self) -> None:
        """Named because it is the one that was measured leaking nine progression-eligible locations, and
        because ONBS is the tier a reader is most likely to think of as "its own place"."""
        self.assertIn("Pyrite Town (ONBS)", travel_locations.travel_item_by_sibling_region())
        self.assertEqual("Travel Unlock - Pyrite Town",
                         travel_locations.travel_item_by_sibling_region()["Pyrite Town (ONBS)"])

    def test_nothing_was_stranded_by_the_fix(self) -> None:
        """The first attempt at this DID strand things -- adding siblings to `gateway_only` suppressed their
        edges while the gateway connects only to its own target. This is the assertion that caught it."""
        state = self._without("")
        unreachable = [l.name for l in self.multiworld.get_locations(1) if not l.can_reach(state)]
        self.assertEqual([], unreachable)

    def test_a_sibling_is_never_also_a_gateway_target(self) -> None:
        """A region that is some OTHER destination's gateway target already has its own item; giving it a
        second would gate it on both."""
        gateways = travel_locations.gateway_only_regions()
        for region_name in travel_locations.travel_item_by_sibling_region():
            self.assertNotIn(region_name, gateways, region_name)


class TestAnUnreadableByteDeclines(unittest.TestCase):
    """FINDING 2 -- the save-corruption one."""

    def setUp(self) -> None:
        self.memory = rc.AreaStoryByteMemory()
        self.written: "list[bytes]" = []
        patch = mock.patch.object(rc, "write_bytes",
                                  lambda address, payload: self.written.append(payload))
        patch.start()
        self.addCleanup(patch.stop)

    def _hover(self, story_byte, region="Citadark Isle"):
        """`poll` IS the hover write: (block_base, hovered_region, current_region, story_byte). `current_region`
        is None here on purpose -- a map screen is a menu, so the player is not standing in a region while the
        cursor rests on a destination, and `observe()` has nothing to record."""
        with mock.patch.object(rc, "read_story_byte", return_value=story_byte):
            return self.memory.poll(0x80479120, region, None, story_byte)

    def test_an_unreadable_byte_writes_nothing(self) -> None:
        self.assertIsNone(self._hover(None))
        self.assertEqual([], self.written, "a blind write is what poisons the persisted file")
        self.assertEqual(1, self.memory.declined_unreadable_byte)

    def test_it_leaves_no_outstanding_write_behind(self) -> None:
        """The second half of the failure: a write with no `saved_byte` released the lock without restoring,
        which is how a foreign byte reached `observe()`."""
        self._hover(None)
        self.assertFalse(self.memory._write_outstanding)
        self.assertIsNone(self.memory.saved_byte)

    def test_a_readable_byte_still_writes_and_records_it(self) -> None:
        note = self._hover(0x17)
        self.assertIsNotNone(note)
        self.assertEqual(1, len(self.written))
        self.assertEqual(0x17, self.memory.saved_byte)
        self.assertTrue(self.memory._write_outstanding)

    def test_the_second_hover_of_a_visit_keeps_the_first_saved_byte(self) -> None:
        """ADDENDUM 229's rule, re-pinned: what a player backing out wants is the byte from before they
        opened the map, not the one the previous hover left."""
        self._hover(0x17)
        self._hover(0x6E, region="Agate Village")
        self.assertEqual(0x17, self.memory.saved_byte)


class TestNoLiveItemIdIsAllowedToDrift(unittest.TestCase):
    """FINDING 6 -- found during the audit, fixed here.

    `_FROZEN_ITEM_OFFSETS` exists so that an id, once shipped, means the same item forever. Two live names had
    never been pasted into it -- the merged Poke Spots unlock and the combined key item -- so their ids came
    from `_freeze_offsets`' `next_free` counter and would have moved the moment anyone added a frozen entry or
    reordered the table. They were frozen at the values they already resolved to (255 and 256), so every seed
    generated before this addendum keeps working.

    The general assertion is the point of this class. Naming the two would only re-pin what is already fixed;
    what the table needs is something that fails the day a THIRD one is added without its number."""

    def test_every_item_in_the_table_has_a_frozen_id(self) -> None:
        from .. import items

        unfrozen = sorted(name for name in items.ITEM_TABLE if name not in items._FROZEN_ITEM_OFFSETS)
        self.assertEqual(
            [], unfrozen,
            "these items' ids come from next_free, so they move whenever anything above them changes. Paste "
            "each one's CURRENT id_offset into _FROZEN_ITEM_OFFSETS -- current, not tidy: seeds already "
            "generated carry the number it has today.")

    def test_the_frozen_table_still_has_no_duplicate_ids(self) -> None:
        """`_freeze_offsets` raises on a collision in the built table, which covers retired entries only by
        accident. This checks the source dict itself, where a copy-paste error would actually be made."""
        from .. import items

        seen: "dict[int, str]" = {}
        for name, offset in items._FROZEN_ITEM_OFFSETS.items():
            self.assertNotIn(offset, seen, f"{name!r} and {seen.get(offset)!r} both claim id {offset}")
            seen[offset] = name

    def test_the_retired_poke_spot_ids_are_not_reused(self) -> None:
        """ADDENDUM 177 merged three destinations into one item. Their ids stay reserved rather than being
        handed to the merged item or to anything else."""
        from .. import items

        for retired, offset in (("Travel Unlock - Cave Poke Spot", 242),
                                ("Travel Unlock - Oasis Poke Spot", 245),
                                ("Travel Unlock - Rockground Poke Spot", 248)):
            self.assertEqual(offset, items._FROZEN_ITEM_OFFSETS[retired])
            self.assertNotIn(retired, items.ITEM_TABLE, "retired names stay as tombstones, not live items")
        self.assertEqual(255, items._FROZEN_ITEM_OFFSETS["Travel Unlock - Poke Spots"])


class TestADestinationDoesNotCreditItself(unittest.TestCase):
    """FINDING 3."""

    def test_the_threshold_and_the_floor_really_are_the_same_function(self) -> None:
        """The reason `<=` was inert, stated as a fact about the code rather than as a claim."""
        for name in travel_locations.TRAVEL_LOCATION_NAMES:
            threshold = travel_locations.vanilla_unlock_story_byte(name)
            if threshold is None:
                continue
            region = (travel_locations.TRAVEL_UNLOCK_STORY_REGION.get(name)
                      or travel_locations.TRAVEL_LOCATION_TARGET_REGION.get(name))
            # ADDENDUM 324: `area_unlock_floor`, which is the function BOTH sides use now. The entry floor
            # split away from it when the Cipher Key Lair icon was given an explicit 0x64; the self-credit
            # reasoning is about where a byte can be earned, so it followed the unlock floor and the identity
            # this test exists to state is intact.
            self.assertEqual(story_bytes.area_unlock_floor(region), threshold,
                             f"{name}: if these ever differ, the self-credit reasoning needs revisiting")

    # ========================================================================================================
    # RETARGETED 2026-09-25 (ADDENDUM 355)
    # ========================================================================================================
    # This used to pin the literal `floor is None or floor < threshold`. That was the RIGHT pin for the rule
    # of the day: the gate compared the player's current region floor against the threshold, `<=` made it
    # inert for the destination the player had just travelled to (the threshold and that floor are the same
    # function on the same region), and the travel item paid out its own `Unlock -` check.
    #
    # The gate is gone -- ADDENDUM 355 replaced it, because it was one-sided in the other direction. THE
    # FINDING IT PROTECTS IS NOT GONE, and it is the finding that shaped 355's design: a travel item must not
    # be able to pay out its own check. So the tests below are that property re-expressed against the mark
    # rule, which forbids it by a different and stronger route.
    #
    # WHY THE NEW RULE CANNOT SELF-CREDIT: arriving at D writes D's entry floor, and that write is OURS.
    # `observe()` banks nothing this client wrote (ADDENDA 229/275/277) and nothing carried in from another
    # area (ADDENDUM 288). A mark exists only where the GAME moved the byte with the player standing there.
    # The item gets you to D; the mark still has to be earned in D.
    #
    # THE EQUALITY CASE, which is what `<` vs `<=` was really about, is now simply not expressible: there is
    # no comparison left between a threshold and a floor derived from the same region. The comparison is
    # against a high-water the game produced.

    def test_the_superseded_literal_is_really_gone(self) -> None:
        """If this fails as a PAIR with the rest of the class passing, someone reintroduced the old gate."""
        source = (pathlib.Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")
        # The NAME still appears twice, in prose, saying what replaced it -- that is the point of keeping
        # an addendum trail. What must not exist is a definition or a call.
        self.assertNotIn("def _story_byte_was_earned_here", source)
        self.assertNotIn("_story_byte_was_earned_here(", source)
        self.assertNotIn("floor is None or floor <= threshold", source)

    def test_the_credit_never_compares_against_a_floor_at_all(self) -> None:
        source = (pathlib.Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")
        start = source.index("def _unlock_mark_for")
        following = re.search(r"^(?:async )?def enforce_travel_locks", source[start:], re.M)
        assert following is not None
        gate = source[start:start + following.start()]
        # CODE ONLY. Both docstrings quote the retired `floor < threshold` while explaining why it is gone,
        # and a prose mention is the opposite of a regression.
        code = re.sub(r'""".*?"""', "", gate, flags=re.S)
        for fragment in ("area_unlock_floor", "area_entry_floor", "floor < threshold", "floor <= threshold"):
            self.assertNotIn(fragment, code, fragment)
        self.assertIn("mark is not None and mark >= threshold", code)

    def test_the_mark_the_credit_reads_refuses_our_own_writes(self) -> None:
        """The load-bearing half. `observe()` is where self-credit is now impossible, so the guards that make
        that true are pinned HERE, next to the finding they serve, and not only in their own addendum's file."""
        ram = (pathlib.Path(__file__).resolve().parent.parent / "ram_client.py").read_text(encoding="utf-8")
        # Anchored on the CLASS: `observe` is a common method name in this file and the first one is a
        # battle-roster reader that has nothing to do with the story byte.
        cls_at = ram.index("class AreaStoryByteMemory")
        start = ram.index("    def observe(", cls_at)
        body = ram[start:ram.index("\n    def ", start + 10)]
        self.assertIn("_write_outstanding", body, "ADDENDUM 229: a hover write in the air is not a mark")
        self.assertIn("last_written_target", body, "ADDENDA 275/277: a value WE wrote is not a value we saw")
        self.assertIn("self._last_observed_region", body, "ADDENDUM 288: a byte carried in was not earned here")

    def test_a_travel_arrival_writes_the_floor_that_would_have_self_credited(self) -> None:
        """States the hazard as a live fact rather than as history: for every destination the value written on
        arrival is exactly the threshold its own check is gated on. That is why banking our own writes would
        reopen this, and why the guard above is load-bearing rather than defensive."""
        for name in travel_locations.TRAVEL_LOCATION_NAMES:
            threshold = travel_locations.vanilla_unlock_story_byte(name)
            if threshold is None:
                continue
            region = (travel_locations.TRAVEL_UNLOCK_STORY_REGION.get(name)
                      or travel_locations.TRAVEL_LOCATION_TARGET_REGION.get(name))
            self.assertEqual(story_bytes.area_unlock_floor(region), threshold, name)


class TestTheOverrideReleasesTheMapBookkeeping(unittest.TestCase):
    """FINDING 4 -- structural, `Client.py` is not importable here."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (pathlib.Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")

    def test_the_early_return_clears_the_map_state(self) -> None:
        start = self.source.index("if ctx.story_byte_override.active:")
        body = self.source[start:start + 700]
        for fragment in ("ctx._room_before_map = None",
                         "ctx.area_story_memory.saved_byte = None",
                         "ctx.area_story_memory._write_outstanding = False"):
            self.assertIn(fragment, body, fragment)

    def test_it_only_clears_once_the_player_is_off_the_map(self) -> None:
        """Clearing while still ON the map would throw away the pre-map byte mid-visit -- the state is about
        the player's movement, and they have not moved yet."""
        start = self.source.index("if ctx.story_byte_override.active:")
        body = self.source[start:start + 700]
        self.assertIn("!= ram_client.MAP_SCREEN_ROOM_ID", body)


class TestUnlockLocationsOnlyExistWhenTheyCanFire(PokemonXDTestBase):
    """FINDING 5."""

    options = {"randomize_travel_locations": False}

    def test_no_unlock_locations_when_the_option_is_off(self) -> None:
        names = [l.name for l in self.multiworld.get_locations(1) if l.name.startswith("Unlock - ")]
        self.assertEqual([], names,
                         "`enforce_travel_locks` returns on its first line when the option is off, so these "
                         "are checks nothing can ever send")


class TestTheDedupGuardNamesASetSomethingWrites(unittest.TestCase):

    def test_it_uses_checked_locations(self) -> None:
        source = (pathlib.Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")
        code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith("#"))
        self.assertNotIn("in ctx.locations_checked", code,
                         "nothing in this client or CommonClient writes `locations_checked`")


if __name__ == "__main__":
    unittest.main()
