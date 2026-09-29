"""ADDENDUM 184 (2026-09-14): three corrections from the player, all about WHEN a place is really usable.

  1. "You can purify in Agate Village. Don't worry about the purification chamber unlock."
  2. "Kaminko Manor's chests are ALL inaccessible until story byte 0x53, which is after the first SS Libra
     visit/after completing Phenac city. You can visit early, but the chests are actually mid-game, not early
     game."
  3. "Some of our second visits need special adjustment if randomize_travel is on." -- followed by five rules,
     each of which is a row in story_bytes.AREA_FLOOR_RULES and a test below.

(1) and (2) are logic corrections and change which sphere a check lands in. (3) is a CLIENT correction -- it
changes what byte the area memory writes when the player picks a destination off the map, and touches no
Archipelago rule at all.
"""
from __future__ import annotations

import unittest

from . import PokemonXDTestBase
from .. import locations, ram_client, rules
from ..game_data import chest_regions, shadow_regions, story_bytes


class TestPurificationFloor(unittest.TestCase):
    """(1) Where a shadow is SNAGGED and where it can be PURIFIED are different questions."""

    def test_no_threshold_sits_earlier_than_agate_village(self) -> None:
        from .. import regions as region_module

        order = list(region_module.REGION_NAMES)
        floor_at = order.index(shadow_regions.PURIFICATION_FLOOR_REGION)
        for region in shadow_regions.purification_weights(locations.PURIFICATION_LOCATION_COUNT):
            self.assertGreaterEqual(
                order.index(region), floor_at,
                f"{region} is earlier than {shadow_regions.PURIFICATION_FLOOR_REGION}, so a purification "
                f"threshold would be claimed reachable before anywhere that purifies",
            )

    def test_the_always_open_regions_no_longer_carry_any_of_the_ladder(self) -> None:
        """The exact shape of ADDENDUM 182's F2: thresholds 1-7 were filed under Pokemon HQ Lab and Gateon
        Port, which are open from the start."""
        weights = shadow_regions.purification_weights(locations.PURIFICATION_LOCATION_COUNT)
        for region in story_bytes.ALWAYS_OPEN_REGIONS:
            self.assertNotIn(region, weights)

    def test_the_weights_still_sum_to_the_ladder_length(self) -> None:
        """rules.py asserts this at import; clamping regions must move thresholds, never drop them."""
        weights = shadow_regions.purification_weights(locations.PURIFICATION_LOCATION_COUNT)
        self.assertEqual(sum(weights.values()), locations.PURIFICATION_LOCATION_COUNT)
        self.assertEqual(sum(rules._PURIFICATION_WEIGHT_BY_REGION.values()),
                         locations.PURIFICATION_LOCATION_COUNT)


class TestPurificationFloorInAWorld(PokemonXDTestBase):
    options = {"progression_locations": 2, "purification_progression_cap": 15}

    def test_the_first_threshold_is_closed_until_agate_village_is_reachable(self) -> None:
        """The seed that motivated this put the Machine Part on 'Purify 2 Shadow Pokemon' -- and the Machine
        Part is the key to Agate Village."""
        first = self.multiworld.get_location(locations.purification_location_name(1), self.player)
        self.assertFalse(first.can_reach(self.multiworld.state))
        self.collect_key_item_chain(1)  # Machine Part -> Agate Village
        self.assertTrue(self.multiworld.state.can_reach("Agate Village", player=self.player))
        self.assertTrue(first.can_reach(self.multiworld.state))


class TestKaminkoManorIsMidGame(unittest.TestCase):
    """(2) The manor is walkable from the start and its contents are not."""

    KAMINKO_ROOMS = (169, 171, 172, 173)

    def test_every_kaminko_room_is_in_the_0x53_tier(self) -> None:
        for room in self.KAMINKO_ROOMS:
            self.assertEqual(chest_regions.ROOM_TO_REGION[room], "Kaminko's House (Robo Groudon)", f"room {room}")

    def test_that_tier_really_opens_at_0x53(self) -> None:
        self.assertEqual(story_bytes.region_floor("Kaminko's House (Robo Groudon)"), 0x53)

    def test_no_chest_is_left_in_the_always_open_kaminko_bucket(self) -> None:
        self.assertNotIn("Kaminko's House", set(chest_regions.CHEST_TO_REGION.values()))

    def test_the_named_manor_pickup_moved_with_the_chests(self) -> None:
        """They are inside the same building. Realgam Tower's 0x41 was five story transitions too early.

        ADDENDUM 237: this used to check TWO pickups. "Kaminko's House - R&D Lab Basement" was retired as a
        duplicate of the per-chest locations in the same manor; the diary pages survived, as a gift rather
        than a box.

        ADDENDUM 335: and now the diary pages are retired too -- the player played every uncertain Overworld
        Item and none of them exist. So there is no NAMED manor pickup left to check, and the property the
        test is really about is asserted on what remains: the manor's own CHESTS sit in the manor's late
        region and not in Realgam Tower, which is the move ADDENDUM 184 made."""
        placed = locations.LOCATIONS_BY_REGION["Kaminko's House (Robo Groudon)"]
        self.assertTrue(placed, "the manor tier must still hold its chests")
        realgam = locations.LOCATIONS_BY_REGION["Realgam Tower"]
        for name in placed:
            self.assertNotIn(name, realgam)

    def test_the_rd_lab_downstairs_opens_inside_that_tier_s_window(self) -> None:
        """0x55 is "Kaminko's downstairs opened". If it fell outside the window, the basement pickup would need
        a tier of its own rather than riding along with the catwalk."""
        window = story_bytes.REGION_STORY_WINDOW["Kaminko's House (Robo Groudon)"]
        self.assertTrue(window.contains(0x55), f"window is 0x{window.floor:02X}-0x{window.ceiling:02X}")


class TestSecondVisitFloorRules(unittest.TestCase):
    """(3) The five rules the player wrote, each asserted at its own byte."""

    def test_phenac_no_longer_waits_on_realgam_for_its_floor(self) -> None:
        """RETARGETED BY ADDENDUM 331, and the retarget IS the bug report.

        These two tests used to assert that Phenac's 0x41 floor arrives only once BOTH marks are in --
        `Phenac City >= 0x3F` and `Realgam Tower >= 0x41` -- which was ADDENDUM 187's rule and was right for
        the game's own route. With travel locations shuffled it is not a route the player necessarily takes:
        Realgam is its own destination behind its own unlock item, so a player can hold Phenac and never earn
        a Realgam mark at all. The rule then never bound, the hover fell back to the entry floor, and every
        return trip rebuilt the town at 0x3E -- the LOCKED first visit. Player: "the return trip doesn't kick
        us out again".

        So the conditional rule is gone and the floor is unconditional. What is asserted now is that no mark
        anywhere is needed for Phenac to be entered at the open town."""
        self.assertIsNone(story_bytes.dynamic_region_floor("Phenac City", {}),
                          "no AREA_FLOOR_RULES entry should name Phenac any more")
        self.assertIsNone(story_bytes.dynamic_region_floor("Phenac City",
                                                           {"Phenac City": 0x3F, "Realgam Tower": 0x41}))
        self.assertEqual(0x41, story_bytes.area_entry_floor("Phenac City"))

    def test_phenacs_window_floor_is_untouched_by_the_override(self) -> None:
        """The window still describes the GAME -- 0x3E is the locked town you first walk into. Only the byte
        the icon enters at moved, and `area_unlock_floor` (what credits `Unlock - Phenac City`) did not move
        at all."""
        self.assertEqual(0x3E, story_bytes.region_floor("Phenac City"))
        self.assertEqual(0x3E, story_bytes.area_unlock_floor("Phenac City"))
        self.assertGreater(story_bytes.area_entry_floor("Phenac City"),
                           story_bytes.region_floor("Phenac City"))

    def test_phenacs_first_visit_window_covers_the_lockdown(self) -> None:
        """0x3E -> 0x3F is the first visit and it ends by forcing the player to Realgam, so both values have
        to sit inside the window or the memory would write a byte the game has no state for."""
        window = story_bytes.REGION_STORY_WINDOW["Phenac City"]
        self.assertTrue(window.contains(0x3E))
        self.assertTrue(window.contains(0x3F))

    def test_gateon_gets_a_floor_of_0x51_once_phenac_is_finished(self) -> None:
        self.assertEqual(0x10, story_bytes.region_floor("Gateon Port"),  # ADDENDUM 279/379: first visit
                          "Gateon is always-open and has no static window -- the rule is its only floor")
        marks = {"Gateon Port": 0x16}
        self.assertIsNone(story_bytes.dynamic_region_floor("Gateon Port", marks),
                          "half the condition must not be enough")
        marks["Phenac City (Post-Sixes)"] = 0x4E
        self.assertEqual(story_bytes.dynamic_region_floor("Gateon Port", marks), 0x51)

    def test_a_phenac_sub_tier_counts_as_phenac(self) -> None:
        """0x4E is earned in the Post-Sixes tier, which is its own region. Without AREA_GROUPS this rule would
        silently never fire."""
        self.assertIn("Phenac City (Post-Sixes)", story_bytes.AREA_GROUPS["Phenac City"])
        marks = {"Gateon Port": 0x16, "Phenac City (Post-Sixes)": 0x4E}
        self.assertEqual(story_bytes.highest_in_area("Phenac City", marks), 0x4E)

    def test_kaminko_gets_its_rule_tier_once_gateon_and_the_lab_both_say_so(self) -> None:
        """TIGHTENED 2026-09-18 (ADDENDUM 277). Gateon 0x52 alone was a SINGLE witness, and a Gateon mark is
        exactly what the pre-277 bug could fabricate -- one bad mark there handed Kaminko 0x53 on every hover,
        in an always-open area reachable from the start. Player: "Kaminko is also being written too early -
        should only be written to after HQ Lab is at 0x0F as well" (0x12 corrected to 0x0F in play)."""
        lab = {"Pokemon HQ Lab": 0x0F}
        self.assertIsNone(story_bytes.dynamic_region_floor("Kaminko's House", {"Gateon Port": 0x51, **lab}))
        self.assertIsNone(story_bytes.dynamic_region_floor("Kaminko's House", {"Gateon Port": 0x52}),
                          "Gateon alone is no longer enough")
        # ADDENDUM 338 (2026-09-24), retracted by ADDENDUM 350; player was: "Instead of writing to 0x53, kaminko should write to 0x54
        # with the gateon/lab condition." Only the VALUE moved -- both witnesses above are untouched, which
        # is what ADDENDUM 277 tightened and what this test is really for.
        self.assertEqual(story_bytes.dynamic_region_floor("Kaminko's House",
                                                          {"Gateon Port": 0x52, **lab}), 0x53)

    def test_gateon_inherits_0x57_when_kaminko_forces_the_player_back(self) -> None:
        """Player: "If Kaminko reaches 0x56, we get FORCED BACK TO GATEON - this is FINE. we want Gateon to
        then inherit this story byte - it will be 0x57 as we enter"."""
        marks = {"Gateon Port": 0x52, "Kaminko's House": 0x56}
        self.assertEqual(story_bytes.dynamic_region_floor("Gateon Port", marks), 0x57)

    def test_ss_libra_no_longer_gets_0x5a_from_gateon(self) -> None:
        """RETARGETED 2026-09-18 (ADDENDUM 273). The rule this asserted is deleted -- the real ship is behind
        `items.SCOOTER_ITEM_NAME` now, and a floor RULE cannot express holding an Archipelago item. Kept as an
        inverted assertion rather than deleted, so that re-adding the rule (and thereby handing the ship back
        to anyone who walks Gateon far enough) fails loudly."""
        self.assertIsNone(story_bytes.dynamic_region_floor("SS Libra", {"Gateon Port": 0x5A}))

    def test_the_key_lair_has_no_rule_at_all_and_enters_at_0x67(self) -> None:
        """RETARGETED TWICE. ADDENDUM 324, player: "And make Cipher Key Lair's floor 0x64" -- which deleted the
        conditional 0x64 rule this originally asserted. ADDENDUM 371, player: "make the key lair floor 0x67 by
        default" -- which deleted ADDENDUM 364's conditional 0x67 rule the same way.

        Kept as an inverted assertion both times, the shape ADDENDUM 273 used when the SS Libra rule went away:
        the Lair's floor must be a value, not a condition. A conditional rule reappearing here would mean the
        Lair can be entered BELOW its floor again, and this fails loudly if one comes back."""
        marks = {"Cipher Key Lair (exterior)": 0x5D, "Snagem Hideout": 0x63, "Cipher Key Lair": 0x65}
        self.assertIsNone(story_bytes.dynamic_region_floor("Cipher Key Lair", marks))
        self.assertEqual(0x67, story_bytes.area_entry_floor("Cipher Key Lair"))

    def test_every_rule_names_regions_and_areas_that_exist(self) -> None:
        from .. import regions as region_module

        known = set(region_module.REGION_NAMES) | {"Relic Forest"}
        for rule in story_bytes.AREA_FLOOR_RULES:
            self.assertIn(rule.target, known, rule.what)
            for area, _minimum in rule.requires:
                self.assertIn(area, story_bytes.AREA_GROUPS, rule.what)
        for area, members in story_bytes.AREA_GROUPS.items():
            for member in members:
                self.assertIn(member, known, f"{area} names an unknown region {member!r}")

    def test_every_rule_floor_is_a_byte_the_story_table_actually_reaches(self) -> None:
        """A floor that no transition ever lands on would write the game into a state it has no script for.

        WIDENED 2026-09-14 (ADDENDUM 212). TRANSITIONS starts at 0x10 -- the opening hour was played before the
        player began recording -- so a rule about the early game has nothing in the table to match. Rather than
        inventing transitions to satisfy this test, those values are listed one at a time in
        `story_bytes.EARLY_FLOORS_NOT_YET_IN_TRANSITIONS`. The fence keeps its teeth: a typo'd floor still
        fails, because membership is checked rather than everything below 0x10 being waived."""
        for rule in story_bytes.AREA_FLOOR_RULES:
            self.assertTrue(story_bytes.floor_is_accounted_for(rule.floor),
                            f"0x{rule.floor:02X} ({rule.what})")

    def test_the_early_allowlist_only_covers_the_unrecorded_stretch(self) -> None:
        """ADDENDUM 212. The allowlist is a statement about what TRANSITIONS has not recorded yet, so a value
        at or above the recorded ladder has no business being in it -- that would be waiving the real fence."""
        for value in story_bytes.EARLY_FLOORS_NOT_YET_IN_TRANSITIONS:
            self.assertLess(value, story_bytes.LOWEST_RECORDED_STORY_BYTE,
                            f"0x{value:02X} is inside the recorded ladder and must be a real transition")

    def test_a_typo_below_the_ladder_is_still_rejected(self) -> None:
        """The fence would be worthless if it simply allowed anything below 0x10."""
        # ADDENDUM 288: 0x0E is now on the allowlist (the player moved the lab pass-through onto it), so
        # the example of a value the fence still rejects moves down one.
        self.assertFalse(story_bytes.floor_is_accounted_for(0x0C))
        self.assertFalse(story_bytes.floor_is_accounted_for(0x01))


class TestTheMemoryUsesThoseFloors(unittest.TestCase):
    """The one consumer: ram_client.AreaStoryByteMemory. No Archipelago rule is involved."""

    def test_gateon_enters_at_its_own_mark_until_its_rule_fires(self) -> None:
        """RETARGETED 2026-09-18 (ADDENDUM 278). This asserted None with the comment "an always-open area with
        no satisfied rule has nothing honest to write". That premise was wrong, and it is what the player
        reported: the area's OWN high-water mark is the most honest thing there is -- it is where they left
        it. Writing nothing meant the room was built from whatever byte they walked in carrying.

        The rule still outranks the mark the moment it fires, which is the half that was always right."""
        memory = ram_client.AreaStoryByteMemory()
        memory.observe("Gateon Port", 0x16)
        self.assertEqual(memory.target_for("Gateon Port"), 0x16, "where they left it")
        memory.observe("Phenac City (Post-Sixes)", 0x4E)
        self.assertEqual(memory.target_for("Gateon Port"), 0x51, "and the rule raises it when satisfied")

    def test_an_area_never_seen_is_still_silent(self) -> None:
        """The half ADDENDUM 278 did NOT change. No mark and no rule means nothing is known, and a write on
        no knowledge is the guess this project never makes."""
        # ADDENDUM 279 gave Gateon a floor, so the silent case needs a region with neither floor nor mark.
        self.assertIsNone(ram_client.AreaStoryByteMemory().target_for("Not A Real Region"))

    def test_the_remembered_high_water_mark_still_wins_when_it_is_higher(self) -> None:
        memory = ram_client.AreaStoryByteMemory()
        memory.observe("Gateon Port", 0x5A)
        memory.observe("Phenac City", 0x4E)
        self.assertEqual(memory.target_for("Gateon Port"), 0x5A)

    def test_a_rule_can_only_ever_raise_a_floor(self) -> None:
        """Too early means the player walks it off; too late means content is skipped for good. Nothing here
        may send an area backwards."""
        memory = ram_client.AreaStoryByteMemory()
        memory.observe("Cipher Key Lair", 0x67)
        memory.observe("Cipher Key Lair (exterior)", 0x5D)
        memory.observe("Snagem Hideout", 0x63)
        self.assertEqual(memory.target_for("Cipher Key Lair"), 0x67)

    def test_kaminko_becomes_writable_at_its_rule_tier_and_the_readout_says_why(self) -> None:
        """REVISED by ADDENDUM 293, and the revision is a reversal of the first two assertions.

        This used to assert that the manor's own mark (0x20) was its target -- ADDENDUM 278's rule, that an
        area's high-water mark is a floor in its own right. The player has since asked for the opposite at
        this one area: "after Kaminko reaches 0x03, stop writing its floor until it hits one of our gates
        that modifies it". 0x20 is not a byte the manor asked for; it is whatever the player was carrying
        when they last wandered past. So the answer between the front door and the 0x53 tier is now NO
        ANSWER, and `poll` writes nothing.

        WHAT THIS TEST STILL PROVES, unchanged, is the half ADDENDUM 184 and 277 care about: Gateon's 0x52
        alone does not open the manor's rule tier, and the lab's Snag Machine rung is the second witness that
        does. Only the value in the middle moved, from "the mark" to "nothing at all".

        ADDENDUM 338 moved the rule's own value 0x53 -> 0x54; ADDENDUM 350 moved it back, because 0x54
        is not a byte the game can hold. The condition is
        untouched, so every assertion here still measures what it was written to measure."""
        memory = ram_client.AreaStoryByteMemory()
        memory.observe("Kaminko's House", 0x20)
        # ADDENDUM 293: paused, where ADDENDUM 278 would have answered 0x20.
        self.assertIsNone(memory.target_for("Kaminko's House"))
        memory.observe("Gateon Port", 0x52)
        self.assertIsNone(memory.target_for("Kaminko's House"),
                          "ADDENDUM 277: Gateon alone still does not satisfy the rule, so the pause holds")
        memory.observe("Pokemon HQ Lab", 0x0F)
        self.assertEqual(memory.target_for("Kaminko's House"), 0x53,   # ADDENDUM 350
                         "the rule binds, the pause lifts, and writing resumes -- ADDENDUM 293")
        text = "\n".join(memory.describe())
        self.assertIn("second-visit floors in effect", text)
        self.assertIn("0x53", text)   # ADDENDUM 350 -- the readout names the rule's own value


if __name__ == "__main__":
    unittest.main()
