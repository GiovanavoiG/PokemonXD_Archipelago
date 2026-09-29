"""ADDENDUM 334 (2026-09-24): the Cipher Lab's first visit starts outside.

Player: "Upon loading into cipher lab exterior - if it's our first visit, please write the story byte to 0x25
and then back to 0x26 upon entry."

Asked where "entry" is, and what becomes of ADDENDUM 314's 0x27: the bump fires while the player is still
standing outside, a beat after the load, and 0x27 is kept for return visits.

ROOM 11 IS THE EXTERIOR, and it is the player's own measurement -- `room_story_compilation.md` records it as
"Outside the Cipher Lab (first visit)" against rooms 1/7/8/10 for the inside. `chest_regions` files all of
them under `Cipher Lab`, so the region key the client already dispatches on covers the whole place and no new
room table was needed.

THE THREE PIECES, each doing one job:
  * `AREA_ENTRY_FLOOR_OVERRIDES["Cipher Lab"] = 0x25`  -- where the icon drops a first visit.
  * `LiveStoryByteBump("Cipher Lab", 0x25, 0x26)`      -- the beat afterwards, in place.
  * `AreaFloorRule("Cipher Lab", 0x27, ...)`           -- 0x27 back for every visit after the first.

ADDENDUM 350 (2026-09-25) REDUCED THAT TO TWO, by reading `D1_out.fsys` instead of inferring from play.
The exterior map gates its arrival scene on `storyvar(964) == 310` and ends it with `write(964, 320)`;
310 is byte 0x26 and 320 is byte 0x28. So the icon drops a first visit at 0x26 -- the value the map tests
for -- the bump is deleted because the game's own scene does what it was doing, and the return-visit rule
writes 0x28 on the lab's own mark at 0x28. The player's sentence is unchanged in effect: the first visit
starts outside and the byte moves on entry. What moved is who moves it.

Everything below about room 11, the region key and the rule-must-bind fence is untouched by that.
"""
import unittest

from .. import ram_client as rc
from ..game_data import chest_regions, story_bytes


class TestTheExteriorIsRoom11(unittest.TestCase):
    def test_every_lab_room_resolves_to_the_region_the_bump_names(self) -> None:
        """A bump keyed on a region never fires if no room maps to it."""
        rooms = sorted(room for room, region in chest_regions.ROOM_TO_REGION.items()
                       if region == "Cipher Lab")
        self.assertIn(11, rooms, "room 11 is 'Outside the Cipher Lab (first visit)'")
        for room in rooms:
            self.assertEqual("Cipher Lab", chest_regions.region_for_room(room), room)

    def test_the_lab_is_a_declared_place(self) -> None:
        """ADDENDUM 334 declared it. Without a group, a rule cannot name it as a CONDITION -- which is what
        the ADDENDUM 212 fence caught on the first Cipher Lab rule this project ever wrote."""
        self.assertEqual(("Cipher Lab",), story_bytes.AREA_GROUPS["Cipher Lab"])


class TestTheLoadHalf(unittest.TestCase):
    def test_a_first_visit_is_entered_outside(self) -> None:
        """ADDENDUM 350: at 0x26, which is story value 310 -- the value D1_out's `hero_main` tests for by
        equality before it will run the arrival."""
        self.assertEqual(0x26, story_bytes.area_entry_floor("Cipher Lab"))
        self.assertEqual(310, story_bytes.story_value_for_byte(0x26))

    def test_that_byte_is_one_the_ladder_accounts_for(self) -> None:
        """The same fence every other floor in the module passes -- 0x26 is the `after` of 0x25 -> 0x26."""
        self.assertTrue(story_bytes.floor_is_accounted_for(0x26))

    def test_the_window_opens_where_the_icon_drops_you(self) -> None:
        """ADDENDUM 314 kept these apart because it believed the lab was entered a rung above the unlock.
        The script says they are the same rung, so there is nothing left to hold apart."""
        self.assertEqual(0x26, story_bytes.region_floor("Cipher Lab"))
        self.assertEqual(0x26, story_bytes.REGION_STORY_WINDOW["Cipher Lab"].floor)
        self.assertEqual(0x26, story_bytes.area_unlock_floor("Cipher Lab"),
                         "`Unlock - Cipher Lab` still credits at the game's own byte")


class TestTheEntryHalfIsTheGamesNow(unittest.TestCase):
    """ADDENDUM 350 deleted the bump. Player: "I'd like to see if we can avoid it."

    It was carrying 0x25 to 0x26 a beat after the load -- the right destination by the wrong road, and only
    reliable by luck: before the twelve-bit write, "0x26" meant 304..311 and only hit 310 when the save's low
    three bits happened to be 6. Dropping the icon straight on 0x26 makes the map's own `hero_main` fire, and
    `brother_enter` advances the story to 320 itself."""

    def test_the_lab_has_no_live_bump_any_more(self) -> None:
        self.assertEqual([], [b for b in story_bytes.LIVE_STORY_BYTE_BUMPS if b.region == "Cipher Lab"])
        for scooter in (False, True):
            for travel in (False, True):
                self.assertIsNone(story_bytes.live_bump_for("Cipher Lab", 0x25, travel, scooter))
                self.assertIsNone(story_bytes.live_bump_for("Cipher Lab", 0x26, travel, scooter))

    def test_the_beat_it_carried_is_in_the_ladder_instead(self) -> None:
        """Read from the game rather than played, and recorded as such."""
        step = next(t for t in story_bytes.TRANSITIONS if (t.before, t.after) == (0x26, 0x28))
        self.assertIn("READ FROM THE GAME", step.note)
        self.assertEqual(310, story_bytes.story_value_for_byte(0x26))
        self.assertEqual(320, story_bytes.story_value_for_byte(0x28))

    def test_the_other_bumps_are_untouched(self) -> None:
        self.assertEqual({"Pokemon HQ Lab", "SS Libra", "Phenac City"},
                         {b.region for b in story_bytes.LIVE_STORY_BYTE_BUMPS})


class TestTheReturnVisit(unittest.TestCase):
    def test_nothing_raises_it_until_the_lab_has_a_mark(self) -> None:
        self.assertIsNone(story_bytes.dynamic_region_floor("Cipher Lab", {}))

    def test_the_arrival_being_behind_them_restores_the_lab_itself(self) -> None:
        """The mark that satisfies this is 0x28 -- the byte `brother_enter` writes when the scene finishes,
        so "the first visit really happened" is the game's word rather than ours (ADDENDUM 277)."""
        self.assertEqual(0x28, story_bytes.dynamic_region_floor("Cipher Lab", {"Cipher Lab": 0x28}))
        self.assertEqual(0x28, story_bytes.dynamic_region_floor("Cipher Lab", {"Cipher Lab": 0x2A}))
        self.assertIsNone(story_bytes.dynamic_region_floor("Cipher Lab", {"Cipher Lab": 0x26}),
                          "the arrival byte itself is not the arrival being over")

    def test_another_areas_mark_does_not_satisfy_it(self) -> None:
        self.assertIsNone(story_bytes.dynamic_region_floor("Cipher Lab", {"Mt. Battle": 0x26}))

    def test_the_whole_sequence_through_the_area_memory(self) -> None:
        """The player's sentence, as the client will actually run it."""
        memory = rc.AreaStoryByteMemory()
        self.assertEqual(0x26, memory.target_for("Cipher Lab"), "first visit -- outside, on 310")
        memory.observe("Cipher Lab", 0x28)                      # brother_enter wrote 320 during the visit
        self.assertEqual(0x28, memory.target_for("Cipher Lab"), "every visit after -- the lab itself")

    def test_real_progress_still_outranks_both(self) -> None:
        """`target_for` takes the max, so a player deep in the lab is never dragged back to either value."""
        memory = rc.AreaStoryByteMemory()
        memory.observe("Cipher Lab", 0x2E)
        self.assertEqual(0x2E, memory.target_for("Cipher Lab"))


class TestTheRuleIsNotDead(unittest.TestCase):
    def test_its_floor_is_above_the_entry_floor(self) -> None:
        """ADDENDUM 247's fence, stated for the rule this addendum adds: a rule at or below the entry floor
        can never bind, so the condition it carries would be silently ignored."""
        rule = next(r for r in story_bytes.AREA_FLOOR_RULES if r.target == "Cipher Lab")
        self.assertGreater(rule.floor, story_bytes.area_entry_floor("Cipher Lab"))
        self.assertEqual((("Cipher Lab", 0x28),), rule.requires)
