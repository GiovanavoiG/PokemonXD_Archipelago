"""ADDENDUM 247 (2026-09-16) -- a map destination's floor is its AREA's first tier.

Player: "SS Libra's first story byte should be 0x4E - it should only get written to 0x5A after Gateon reaches
0x5A. It seems like this is not the case - investigate?"

It was not the case. `map_destinations` gives the SS Libra icon `region="SS Libra"`, whose window floor is
0x5A -- the scooter-upgraded ship. The stranded first visit is a DIFFERENT region, `SS Libra (stranded)`, at
0x4E. So the first hover wrote 0x5A and the stranded visit was skipped.

And the rule that was supposed to gate 0x5A on Gateon could never fire, because `target_for` takes the max of
the static floor and the rule floor and both were 0x5A. Its own comment admitted it: "Redundant against SS
Libra's static 0x5A window today."

`Cipher Key Lair` had the identical defect -- it names the post-Snagem tier (0x64) while its place becomes
reachable at the exterior, 0x5D -- so BOTH halves of the player's ADDENDUM 184 paragraph were dead.
"""
import unittest

from .. import ram_client as rc, travel_locations as tl
from ..game_data import map_destinations as md, story_bytes as sb


class TestEntryFloorIsTheAreasFirstTier(unittest.TestCase):
    def test_ss_libra_enters_at_the_stranded_floor(self) -> None:
        self.assertEqual(0x4E, sb.area_entry_floor("SS Libra"))
        self.assertEqual(0x5A, sb.region_floor("SS Libra"), "the REGION's own floor is untouched")

    def test_the_key_lair_enters_at_the_lair_and_unlocks_at_the_exterior(self) -> None:
        """RETARGETED (ADDENDUM 324), player: "And make Cipher Key Lair's floor 0x64."

        ADDENDUM 247's own property is what splits here rather than being dropped. The icon still APPEARS
        when the game opens the exterior (0x5D) -- crediting `Unlock - Cipher Key Lair` at 0x64 would be the
        twelve-bytes-late bug 247 fixed -- but the byte the destination is ENTERED at is now the Lair itself,
        by the player's instruction, through AREA_ENTRY_FLOOR_OVERRIDES.

        ADDENDUM 371 raised that entry value again, to 0x67 ("make the key lair floor 0x67 by default"). The
        SPLIT is this addendum's property and it is what is asserted: the icon appears at the exterior's 0x5D
        and the destination is entered above it. The region's own floor (0x64) stays what the ladder says --
        `_path_floor` reads that, not this, which is ADDENDUM 329's fence and the reason a floor change here
        cannot move a level."""
        self.assertEqual(0x67, sb.area_entry_floor("Cipher Key Lair"))
        self.assertEqual(0x5D, sb.area_unlock_floor("Cipher Key Lair"))
        self.assertEqual(0x64, sb.region_floor("Cipher Key Lair"))
        self.assertEqual(0x67, sb.AREA_ENTRY_FLOOR_OVERRIDES["Cipher Key Lair"])
        self.assertLess(sb.area_unlock_floor("Cipher Key Lair"), sb.area_entry_floor("Cipher Key Lair"))

    def test_nothing_else_moved(self) -> None:
        """The change is only ever allowed to touch a destination whose row names a later tier than its
        place's first. Every other destination must be byte-identical to `region_floor`."""
        moved = {name for name, region in
                 ((d.name, getattr(d, "region", None)) for d in tuple(md.CONFIRMED) + tuple(md.AWAITING_MEASUREMENT))
                 if region and sb.area_unlock_floor(region) != sb.region_floor(region)}
        self.assertEqual({"SS Libra", "Cipher Key Lair"}, moved)
        self.assertEqual({"SS Libra", "Cipher Key Lair"}, moved)
        # ADDENDUM 324: the only destinations whose ENTRY floor differs from their area's first tier are the
        # ones the player gave an explicit value to. An override added without this set moving would be a
        # destination silently entering somewhere other than where the ladder says.
        # ADDENDUM 331 added Phenac City: the player asked for the icon to drop them in the UNLOCKED town
        # (0x41) rather than the locked first visit (0x3E), because the conditional rule that used to lift it
        # needed a Realgam mark a location-shuffle player may never earn.
        # ADDENDUM 334 added Cipher Lab, and ADDENDUM 350 took it out again: reading `D1_out.fsys` showed the
        # arrival fires on storyvar 310 (byte 0x26), so the ladder's own window now opens exactly where the
        # icon should drop a first visit and there is nothing left to override. Its later visits are still
        # raised, by the AREA_FLOOR_RULES entry at 0x28 -- which is a different mechanism and does not belong
        # in this set.
        overridden = {name for name, region in
                      ((d.name, getattr(d, "region", None)) for d in md.CONFIRMED)
                      if region and sb.area_entry_floor(region) != sb.area_unlock_floor(region)}
        self.assertEqual({"Cipher Key Lair", "Phenac City"}, overridden)

    def test_an_always_open_place_has_its_own_first_visit_floor(self) -> None:
        """RETARGETED by ADDENDUM 279. These asserted None -- "the rules are the only floor" -- which was an
        assumption this project had never checked against play. They have first-visit bytes, reported by the
        player: lab 0x00, Kaminko 0x03, Gateon 0x0F. What this test still guards is the ADDENDUM 247 property
        it was written for: an always-open place must not accidentally inherit a LATER tier's window.

        ADDENDUM 379 moved Gateon's value to 0x10. The property is unchanged and is asserted below it: each of
        the three is its OWN early byte, never a later tier's floor."""
        self.assertEqual(0x10, sb.area_entry_floor("Gateon Port"))
        self.assertEqual(0x03, sb.area_entry_floor("Kaminko's House"))
        self.assertEqual(0x00, sb.area_entry_floor("Pokemon HQ Lab"))
        self.assertEqual(0x53, sb.region_floor("Kaminko's House (Robo Groudon)"),
                         "the later tier still has its own floor -- it just is not the entry")

    def test_an_ungrouped_region_answers_for_itself(self) -> None:
        self.assertEqual(sb.region_floor("Citadark Isle"), sb.area_entry_floor("Citadark Isle"))


class TestTheDeadRuleFence(unittest.TestCase):
    """The fence that would have caught both instances at import, years of addenda earlier."""

    def test_every_rule_can_actually_bind(self) -> None:
        for rule in sb.AREA_FLOOR_RULES:
            entry = sb.area_entry_floor(rule.target)
            if entry is None:
                continue
            self.assertGreater(rule.floor, entry,
                               f"{rule.target}'s rule floor 0x{rule.floor:02X} is not above its entry floor "
                               f"0x{entry:02X}, so the condition it carries is never consulted")

    def test_the_rule_this_addendum_revived(self) -> None:
        """ADDENDUM 273: SS Libra's GATEON-DRIVEN rule is gone from this table, so only the Key Lair's is
        asserted here.

        Its replacement is an ITEM, and no `AreaFloorRule` can express "the player holds an Archipelago item"
        -- which is why the rule was removed rather than edited. The SS Libra half of what this test used to
        cover now lives in `test_addendum_273_*`, against `AreaStoryByteMemory.target_for` directly.

        NARROWED by ADDENDUM 293. The assertion used to be "no rule targets SS Libra at all", which said
        more than ADDENDUM 273 meant and became wrong the moment the ship got a rule of a different KIND --
        the self-referential 0x5B -> 0x5D skip, which names no other area and cannot stand in for the item.
        What 273 actually removed is a rule whose condition is somewhere ELSE having progressed, and that is
        what is tested now."""
        by_target = {}
        for rule in sb.AREA_FLOOR_RULES:
            by_target.setdefault(rule.target, []).append(rule)
        foreign = [rule for rule in by_target.get("SS Libra", ())
                   if any(area != "SS Libra" for area, _ in rule.requires)]
        self.assertEqual([], foreign,
                         "the Gateon-driven rule is replaced by items.SCOOTER_ITEM_NAME (ADDENDUM 273)")
        # ADDENDUM 324: the Key Lair's rule is GONE, replaced by an unconditional entry floor of 0x64
        # (AREA_ENTRY_FLOOR_OVERRIDES). Keeping it beside the override would have been a rule whose floor is
        # not above the area's entry floor -- which this module's own fence forbids, because a rule that can
        # never bind is a condition silently ignored. So what is asserted now is that it is really gone and
        # that the value it used to impose is imposed anyway.
        # RETARGETED 2026-09-26 (ADDENDUM 364). This used to assert that NO rule targets the Key Lair, which
        # said more than ADDENDUM 324 meant -- the same over-reach ADDENDUM 293 had to narrow for the SS
        # Libra two paragraphs up. What 324 removed is a rule whose floor was 0x64, i.e. not above the entry
        # floor it was replaced by; the Lair now carries a rule at 0x67 that binds on its own mark, which is
        # the shape this fence exists to ALLOW. So what is asserted is the thing that was actually wrong:
        # no surviving Key Lair rule may sit at or below the entry floor.
        # RETARGETED AGAIN 2026-09-27 (ADDENDUM 371): "make the key lair floor 0x67 by default" made 0x67 the
        # entry floor, which killed ADDENDUM 364's 0x67 rule for the exact reason 324 killed the 0x64 one. The
        # assertion above was already written against `area_entry_floor` rather than a literal, so it caught
        # the new dead rule without being touched -- which is the point of stating a fence as a property.
        dead = [rule for rule in by_target.get("Cipher Key Lair", [])
                if rule.floor <= sb.area_entry_floor("Cipher Key Lair")]
        self.assertEqual([], dead,
                         "a Key Lair rule at or below the entry floor can never bind -- that is the dead rule "
                         "ADDENDUM 324 replaced with the override, and ADDENDUM 371 did the same to 364's")
        self.assertEqual(0x67, sb.area_entry_floor("Cipher Key Lair"))


class TestTheLadderTheMemoryActuallyWrites(unittest.TestCase):
    """The player's sentence, as a sequence of `target_for` answers."""

    def test_ss_libra_is_0x4e_until_the_scooter_arrives(self) -> None:
        """RETARGETED 2026-09-18 (ADDENDUM 273). This used to walk Gateon's byte up to 0x5A and assert SS
        Libra's floor followed, because `AreaFloorRule("SS Libra", 0x5A, (("Gateon Port", 0x5A),))` was what
        raised it. That rule is gone: the player's call was "Scooter item replaces it entirely", so late
        Gateon no longer opens the real ship on its own. The tiers and their numbers are unchanged; only what
        moves between them is."""
        mem = rc.AreaStoryByteMemory()
        self.assertEqual(0x4E, mem.target_for("SS Libra"), "cold, before anything -- the stranded visit")

        for gateon_byte in (0x51, 0x57, 0x5A):
            mem.observe("Gateon Port", gateon_byte)
            self.assertEqual(0x4E, mem.target_for("SS Libra"),
                             f"Gateon at 0x{gateon_byte:02X} must no longer open the real ship by itself")

        mem.scooter_held = True
        self.assertEqual(0x5A, mem.target_for("SS Libra"), "the Scooter -- and only the Scooter")

    def test_the_stranded_visit_still_advances_on_its_own(self) -> None:
        """Having been there, a return trip gets what the area actually reached -- not the entry floor. The
        high-water mark is keyed on the region `region_for_room` reports, which this addendum did not move.

        ADDENDUM 273: the mark still advances exactly as before; the Scooter decides whether the memory is
        ALLOWED to hand back a mark above the stranded floor, which is asserted separately below."""
        mem = rc.AreaStoryByteMemory(scooter_held=True)
        mem.observe("SS Libra", 0x5C)          # the real visit ran its course
        self.assertEqual(0x5D, mem.target_for("SS Libra"),
                         "a later visit is never dragged back to a floor -- ADDENDUM 293: 0x5D, not the 0x5C mark itself. 0x5C is a PASS-THROUGH of the 0x5B -> 0x5D transition and the ship now skips it, so a return visit lands on the far side. The property under test is unchanged -- the mark is honoured rather than discarded -- and the skip only ever raises.")
        self.assertGreater(mem.target_for("SS Libra"), 0x4E, "and never back to the entry floor")

    def test_without_the_scooter_the_stranded_visit_replays(self) -> None:
        """ADDENDUM 273, and it is a real consequence of the player's own choice of 0x4E over 0x50.

        `0x4E -> 0x50` IS the stranded visit's cutscene (kicked back to Phenac, mail sent to Pyrite). Holding
        the destination at 0x4E means that visit is re-entered at its start every time, rather than at the
        state it left off in -- which is the cost of gating at the tier BELOW the cutscene instead of above
        it. Asserted rather than left implicit, because a player reporting "SS Libra keeps replaying" should
        find this test rather than a surprise."""
        mem = rc.AreaStoryByteMemory(scooter_held=False)
        mem.observe("SS Libra", 0x50)
        self.assertEqual(0x4E, mem.target_for("SS Libra"))

    def test_the_key_lair_is_written_at_its_floor_unconditionally_now(self) -> None:
        """RETARGETED (ADDENDUM 324), and again by ADDENDUM 371. This used to be a LADDER: the icon wrote the
        exterior's 0x5D until Snagem had been cleared, and a rule then raised it to 0x64. The player replaced
        the condition with a value twice over -- "make Cipher Key Lair's floor 0x64", then "make the key lair
        floor 0x67 by default" -- so there is no rule and the destination writes the floor from the first
        visit. What still has to hold is the direction: never below the floor, and never below a mark the area
        has already reached."""
        floor = sb.area_entry_floor("Cipher Key Lair")
        self.assertEqual(0x67, floor)
        mem = rc.AreaStoryByteMemory()
        self.assertEqual(floor, mem.target_for("Cipher Key Lair"))
        mem.observe("Cipher Key Lair (exterior)", 0x5D)
        self.assertEqual(floor, mem.target_for("Cipher Key Lair"),
                         "a mark below the floor cannot lower the arrival")
        mem.observe("Cipher Key Lair", 0x69)
        self.assertGreaterEqual(mem.target_for("Cipher Key Lair"), 0x69,
                                "an area's own mark is still a floor")

    def test_no_rule_can_ever_send_an_area_backwards(self) -> None:
        """The module's standing invariant, re-checked after the floor source moved."""
        mem = rc.AreaStoryByteMemory(scooter_held=True)
        mem.observe("SS Libra", 0x5C)
        mem.observe("Gateon Port", 0x5A)
        self.assertGreaterEqual(mem.target_for("SS Libra"), 0x5C)

    def test_the_scooter_cap_is_the_one_deliberate_exception_to_that(self) -> None:
        """ADDENDUM 273, stated plainly because it genuinely narrows the invariant above.

        Every FLOOR RULE still only ever raises. The Scooter is not a floor rule -- it is a cap applied to the
        result, and without it SS Libra is held at the stranded tier even when the memory's own high-water mark
        is higher. That is the point: a mark of 0x5C can be sitting in a file from a session where the player
        DID hold the item, and a gate that only filtered the static floor would be walked straight past by it."""
        mem = rc.AreaStoryByteMemory(scooter_held=False)
        mem.observe("SS Libra", 0x5C)
        self.assertEqual(0x4E, mem.target_for("SS Libra"))
        self.assertEqual(1, mem.capped_ss_libra)
        mem.scooter_held = True
        self.assertEqual(0x5D, mem.target_for("SS Libra"),
                         "and the mark is still there once it is allowed -- ADDENDUM 293: 0x5D, not the 0x5C mark itself. 0x5C is a PASS-THROUGH of the 0x5B -> 0x5D transition and the ship now skips it, so a return visit lands on the far side. The property under test is unchanged -- the mark is honoured rather than discarded -- and the skip only ever raises.")


class TestTheUnlockChecksFireWhenTheIconAppears(unittest.TestCase):
    def test_ss_libra_and_the_key_lair_are_credited_at_the_right_byte(self) -> None:
        self.assertEqual(0x4E, tl.vanilla_unlock_story_byte("SS Libra"),
                         "0x4C -> 0x4E is literally 'SS Libra reachable'")
        self.assertEqual(0x5D, tl.vanilla_unlock_story_byte("Cipher Key Lair"),
                         "0x5B -> 0x5D is literally 'Cipher Key Lair reachable'")

    def test_every_threshold_matches_the_transition_that_opens_that_place(self) -> None:
        opened_at = {region: t.after for t in sb.TRANSITIONS for region in t.opens_regions}
        for name in tl.TRAVEL_LOCATION_NAMES:
            threshold = tl.vanilla_unlock_story_byte(name)
            region = (tl.TRAVEL_UNLOCK_STORY_REGION.get(name)
                      or tl.TRAVEL_LOCATION_TARGET_REGION.get(name))
            if threshold is None or region is None:
                continue
            first = next((m[0] for m in sb.AREA_GROUPS.values() if region in m), region)
            if first in opened_at:
                self.assertEqual(opened_at[first], threshold, name)


if __name__ == "__main__":
    unittest.main()
