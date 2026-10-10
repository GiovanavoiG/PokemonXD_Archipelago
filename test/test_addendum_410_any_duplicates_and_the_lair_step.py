"""ADDENDUM 410 (2026-10-03) -- a lone #1 beside its (Any) goes, and the Key Lair floor drops one story step.

Player: "Any trainers that only have 'any' and '#1', just remove the #1. ... Also, reduce key lair's default floor
by one step, remembering that it's more than just a byte."
"""
from __future__ import annotations

import unittest

from .. import locations as L, ram_client as rc
from ..game_data import missable_trainers as mt, repeatable_trainers as rt, story_bytes as sb, trainer_roster as tr

SIX = ("Cail", "Clerr", "Belish", "Eagun", "Dert", "Dobit")
LAIR = "Cipher Key Lair"


class TestTheLoneNumberOnesAreGone(unittest.TestCase):
    def test_exactly_the_six(self) -> None:
        self.assertEqual({f"Defeat - {name} #1" for name in SIX}, set(tr.ANY_DUPLICATE_DEFEAT_LOCATIONS))

    def test_they_are_not_locations_and_their_queues_are_empty(self) -> None:
        for name in SIX:
            label = f"Defeat - {name} #1"
            self.assertIn(label, tr.REMOVED_DEFEAT_LOCATIONS)
            self.assertNotIn(label, L.ACTIVE_UNIQUE_TRAINER_DEFEAT_LOCATION_NAMES)
            self.assertNotIn(label, L.LOCATION_TABLE)
            self.assertEqual([], tr.UNIQUE_SURNAME_TO_LOCATION_QUEUE[name.upper()])

    def test_each_keeps_its_any_and_the_any_can_hold_items(self) -> None:
        """The (Any) is what still checks the fight. None of the six #1s could hold progression (all were in the
        filler-only fence), and none of the six (Any)s is always-filler -- so nothing progression-capable was lost."""
        for name in SIX:
            self.assertIn(name.upper(), rt.SURNAME_TO_LOCATION)
            self.assertNotIn(rt.SURNAME_TO_LOCATION[name.upper()], rt.ALWAYS_FILLER_LOCATIONS)
            index = next(t["index"] for t in tr.TRAINERS if tr.trainer_label(t) == f"Defeat - {name} #1")
            self.assertIn(index, mt.FILLER_ONLY_TRAINER_INDICES)

    def test_no_surname_is_left_with_any_plus_a_lone_number_one(self) -> None:
        for surname, queue in tr.UNIQUE_SURNAME_TO_LOCATION_QUEUE.items():
            if surname in rt.SURNAME_TO_LOCATION:
                self.assertFalse(len(queue) == 1 and queue[0].endswith(" #1"), surname)

    def test_a_win_against_them_still_sends_the_any(self) -> None:
        """The (Any) is dispatched off the surname, not the queue, so an empty queue still recognises the win."""
        tracker = rc.TrainerBattleDefeatTracker()
        queue = {"CAIL": []}
        count = lambda n: f"Defeat {n} Trainers"   # noqa: E731
        rec = lambda hp: rc.BattleRosterRecord(address=0, trainer_name="CAIL", species_name="Gulpin",  # noqa: E731
                                              current_hp=hp)
        tracker.poll(queue, count, records=[])
        tracker.poll(queue, count, records=[rec(20)])
        tracker.poll(queue, count, records=[rec(0)])
        sent = tracker.poll(queue, count, records=[rec(0)])
        self.assertEqual(["CAIL"], tracker.last_confirmed_surnames)
        self.assertFalse([n for n in sent if n.startswith("Defeat - ")], "no numbered check left to send")


class TestTheLairStep(unittest.TestCase):
    """One step of the STORY VARIABLE (var964, multiples of ten), not one byte: 830 -> 820. ADDENDUM 411 then took
    one more step, to 810 -- its own test module pins the floor and the write; this keeps the step arithmetic."""

    def test_a_step_is_ten_on_the_variable(self) -> None:
        self.assertEqual(830, sb.story_value_for_byte(0x67))
        self.assertEqual(820, sb.story_value_for_byte(0x66))
        self.assertEqual(810, sb.story_value_for_byte(0x65))
        self.assertEqual(10, sb.STORY_VARIABLE_STEP)

    def test_the_floor_is_now_two_steps_below_371s(self) -> None:
        # ADDENDUM 439: 800 -- three steps below 371's 830.
        self.assertEqual(830 - 3 * sb.STORY_VARIABLE_STEP, sb.story_value_for_byte(sb.area_entry_floor(LAIR)))
        self.assertEqual(800, sb.story_value_for_byte(0x64))


if __name__ == "__main__":
    unittest.main()
