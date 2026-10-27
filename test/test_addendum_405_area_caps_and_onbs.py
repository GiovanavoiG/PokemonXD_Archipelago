"""ADDENDUM 405 (2026-10-03) -- missables wait on THEIR area, and the ONBS raid does not name the Data ROM.

Checks are sent AT the story cap for each area, and only when THAT AREA's floor reaches it. Pyrite Town's 2nd
visit (the ONBS raid) is not gated behind the Data ROM at all, only behind Pyrite Town and the Poke Spots.

PER AREA. ADDENDUM 402 released every missable off one number, the global witness high-water mark. With travel
randomization on that is the wrong number: every area keeps its own story byte, so the player can push Phenac to
0x4E while the Cipher Lab still sits at 0x28 with all six of its fights waiting -- and 402 would have sent them.
Now each check is judged by `story_bytes.area_progress` for its own area only: the marks `AreaStoryByteMemory`
banked there, plus the floor a satisfied rule now imposes on it. AT the cap releases; one below does not.

THE ONBS RAID. Eleven fights and three chests named ('Data ROM',) on top of their region. They no longer do. The
region still says "Pyrite Town and the Poke Spots", because `Pyrite Town (ONBS)` hangs off `Poke Spots`.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from BaseClasses import CollectionState

from . import PokemonXDTestBase
from .. import ram_client as rc
from ..game_data import chest_regions, missable_autosend, story_bytes, trainer_placements

AREA_CAPS = missable_autosend.AUTO_SEND_AREA_CAPS
ALL_NAMES = set(missable_autosend.AUTO_SEND_AT_STORY_BYTE)


def _live_name(region: str) -> str:
    """A name `AreaStoryByteMemory.observe` is really called with for this region's area."""
    from ..game_data import chest_regions as cr

    area = story_bytes.area_of(region)
    members = set(story_bytes.AREA_GROUPS.get(area, (area,)))
    live = sorted({cr.region_for_room(room) for room in range(1200)} - {None})
    for name in live:
        if name in members:
            return name
    raise AssertionError(f"no room resolves into the {area} area")


class TestTheScheduleHasAnAreaForEveryCheck(unittest.TestCase):
    def test_same_names_both_ways(self) -> None:
        self.assertEqual(ALL_NAMES, set(AREA_CAPS))

    def test_every_one_shot_waits_on_one_area(self) -> None:
        for name, caps in AREA_CAPS.items():
            if "(Any)" not in name:
                self.assertEqual(1, len(caps), name)
                self.assertEqual(missable_autosend.AUTO_SEND_AT_STORY_BYTE[name], caps[0][1], name)

    def test_biden_is_not_scheduled(self) -> None:
        # ADDENDUM 436: his Snagem fight is not missable, so his (Any) is never auto-sent.
        self.assertNotIn("Defeat Biden (Any)", AREA_CAPS)

    def test_every_cap_can_be_banked_by_its_own_area(self) -> None:
        """A cap above the area's guard ceiling could never become that area's mark: the check would never go."""
        for name, caps in AREA_CAPS.items():
            for region, cap in caps:
                ceiling = story_bytes.AREA_GUARD_CEILINGS.get(_live_name(region))
                if ceiling is not None:
                    self.assertLessEqual(cap, ceiling, f"{name}: {region} 0x{cap:02X} > guard 0x{ceiling:02X}")


class TestTheAreaMemoryReleasesAtTheCap(unittest.TestCase):
    """Driven through the real `observe()`, the only thing that raises a mark."""

    def test_at_the_cap_and_not_one_below(self) -> None:
        for name, caps in AREA_CAPS.items():
            if len(caps) != 1:
                continue
            region, cap = caps[0]
            live = _live_name(region)
            below, at = rc.AreaStoryByteMemory(), rc.AreaStoryByteMemory()
            below.observe(live, cap - 1)
            at.observe(live, cap)
            sender = rc.MissableAutoSender()
            self.assertNotIn(name, sender.due(None, {name}, set(),
                                              lambda r, m=below.highest_by_region: story_bytes.area_progress(r, m)))
            self.assertEqual([name], sender.due(None, {name}, set(),
                                                lambda r, m=at.highest_by_region: story_bytes.area_progress(r, m)))


class TestOnlyThatAreasFloor(unittest.TestCase):
    def setUp(self) -> None:
        self.sender = rc.MissableAutoSender()
        self.seed = set(ALL_NAMES)

    def _due(self, marks):
        return self.sender.due(0x7F, self.seed, set(), lambda r: story_bytes.area_progress(r, marks))

    def test_another_area_far_ahead_releases_nothing_here(self) -> None:
        """The case 402 got wrong: a huge global byte, the lab untouched. The witness says 0x7F; nothing goes."""
        due = self._due({"Snagem Hideout": 0x63, "Pyrite Town": 0x3D, "Cipher Key Lair": 0x6E})
        self.assertFalse([n for n in due if "Digor" in n or "Coffy" in n])
        self.assertNotIn("Defeat - Fudlo", due)              # Snagem at 0x63, one below its cap
        self.assertNotIn("Defeat - Mocor", due)              # Pyrite at 0x3D, one below
        self.assertIn("Defeat - Ibsol", due)                 # the Key Lair itself passed 0x69

    def test_nothing_is_known_so_nothing_goes(self) -> None:
        """The static first-visit floor is not progress: Phenac's (0x41) already equals its cap."""
        self.assertEqual([], self._due({}))
        self.assertEqual(0x41, story_bytes.area_entry_floor("Phenac City"))

    def test_a_satisfied_rule_is_that_areas_floor(self) -> None:
        """Gateon's 0x51 rule fires on Gateon 0x16 and Phenac 0x4E: from then on Gateon is entered at 0x51,
        so Bost's chance in Gateon is gone even though the player never walked back in."""
        marks = {"Gateon Port": 0x16, "Phenac City (Post-Sixes)": 0x4E}
        self.assertEqual(0x51, story_bytes.area_progress("Gateon Port", marks))
        # ADDENDUM 460: Bost was Gateon's one missable; now unmissable, nothing in Gateon is auto-sent any more.
        self.assertNotIn("Defeat - Bost", self._due(marks))


class TestVanillaTravelStillUsesTheOneByte(unittest.TestCase):
    def test_no_area_callable_means_the_global_byte(self) -> None:
        sender = rc.MissableAutoSender()
        self.assertIn("Defeat - Digor", sender.due(0x2F, set(ALL_NAMES), set()))
        self.assertNotIn("Defeat - Digor", rc.MissableAutoSender().due(0x2E, set(ALL_NAMES), set()))


class TestTheClientPassesTheAreaMemory(unittest.TestCase):
    def setUp(self) -> None:
        self.source = (Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")

    def test_the_tick_hands_over_the_per_area_reader(self) -> None:
        body = self.source.split("async def check_missable_autosend", 1)[1].split("\nasync def ", 1)[0]
        self.assertIn("_missable_area_progress(ctx)", body)

    def test_the_reader_is_the_area_memory_and_only_with_travel_on(self) -> None:
        body = self.source.split("def _missable_area_progress", 1)[1].split("\nasync def ", 1)[0]
        self.assertIn("if not ctx.randomize_travel_locations:", body)
        self.assertIn("highest_by_region", body)
        self.assertNotIn("high_water", body)

    def test_the_command_shows_the_same_thing(self) -> None:
        body = self.source.split("def _cmd_missables", 1)[1].split("\n    def ", 1)[0]
        self.assertIn("_missable_area_progress(self.ctx)", body)


class TestOnbsNamesNoItem(unittest.TestCase):
    def test_no_onbs_fight_carries_the_rom(self) -> None:
        onbs = [p for p in trainer_placements.PLACEMENTS.values() if p.region == "Pyrite Town (ONBS)"]
        self.assertTrue(onbs)
        for placement in onbs:
            self.assertNotIn("Data ROM", placement.required_items)

    def test_the_eleven_are_the_ones_that_did(self) -> None:
        self.assertEqual(11, len(trainer_placements.PLACEMENT_ITEM_REMOVALS["Data ROM"]))

    def test_no_onbs_chest_is_item_gated(self) -> None:
        for chest in (98, 99, 100):
            self.assertEqual("Pyrite Town" if chest == 100 else "Pyrite Town (ONBS)", chest_regions.CHEST_TO_REGION[chest])
            self.assertNotIn(chest, chest_regions.CHEST_ITEM_GATES)

    def test_onbs_still_needs_pyrite_and_the_spots(self) -> None:
        from .. import regions

        self.assertIn(("Poke Spots", "Pyrite Town (ONBS)", ()), regions.REGION_EDGES)
        self.assertIn(("Pyrite Town", "Poke Spots", ()), regions.REGION_EDGES)   # ADDENDUM 406


class _OnbsIsJustItsRegion:
    """Every ONBS location opens exactly when its region does -- nothing of its own on top."""

    def test_no_location_has_a_rule_of_its_own(self) -> None:
        """The location-level rule alone, with NOTHING held: if it says no, the location asks for more than its
        region. Region reachability is exercised by the test below and by the graph itself."""
        empty = CollectionState(self.multiworld)
        onbs = self.multiworld.get_region("Pyrite Town (ONBS)", self.player)
        self.assertTrue(onbs.locations)
        for location in onbs.locations:
            self.assertTrue(location.access_rule(empty), f"{location.name} still names an item")

    def test_locations_open_with_the_region(self) -> None:
        state = CollectionState(self.multiworld)
        for item in self.multiworld.itempool:
            if item.player == self.player:
                state.collect(item, prevent_sweep=True)
        state.sweep_for_advancements()
        onbs = self.multiworld.get_region("Pyrite Town (ONBS)", self.player)
        self.assertTrue(onbs.can_reach(state))
        for location in onbs.locations:
            self.assertTrue(location.can_reach(state), location.name)


class TestOnbsVanillaTravel(_OnbsIsJustItsRegion, PokemonXDTestBase):
    options = {"randomize_travel_locations": False}


class TestOnbsTravelShuffle(_OnbsIsJustItsRegion, PokemonXDTestBase):
    options = {"randomize_travel_locations": True}
