"""ADDENDUM 314 -- the Cipher Lab is entered at 0x27. RETRACTED BY ADDENDUM 350 (see TestTheFloor).

Player: "Cipher lab reported to not have its story byte written properly in location shuffle" -> "Cipher lab is
cursor index 4, location id 8" (which is what the table already had, ruling out the lookup) -> "Let's change the
cipher lab floor to 0x27."."""
import unittest

from ..game_data import map_destinations as md
from ..game_data import story_bytes as sb


class TestTheFloor(unittest.TestCase):
    """RETARGETED BY ADDENDUM 350, which read the lab's own field script instead of inferring from play.

    `D1_out.fsys` gates its arrival scene on `storyvar(964) == 310` and ends it with `write(964, 320)`.
    310 is byte 0x26 and 320 is byte 0x28, so this addendum's 0x27 -- and ADDENDUM 334's 0x25 -- were both
    off by a rung, and 0x27 is not a byte the game can hold at all. What ADDENDUM 314 was reporting (the lab
    not being written properly in location shuffle) was real; the value it reached for was not."""

    def test_the_lab_is_entered_at_0x28_on_a_return_visit(self) -> None:
        self.assertEqual(0x26, sb.region_floor("Cipher Lab"))
        self.assertEqual(0x28, sb.dynamic_region_floor("Cipher Lab", {"Cipher Lab": 0x28}),
                         "once the arrival scene has written 0x28 itself, a return visit is to the lab")

    def test_the_first_visit_starts_outside_at_0x26(self) -> None:
        """0x26 is story value 310 -- what the exterior map tests for, by equality."""
        self.assertEqual(0x26, sb.area_entry_floor("Cipher Lab"))
        self.assertEqual(310, sb.story_value_for_byte(0x26))
        self.assertIsNone(sb.dynamic_region_floor("Cipher Lab", {}),
                          "nothing raises it until the lab has a mark of its own")

    def test_0x27_is_gone_because_it_never_existed(self) -> None:
        self.assertIsNone(sb.story_value_for_byte(0x27))
        self.assertNotIn(0x27, sb.UNREACHABLE_BYTES_IN_LADDER,
                         "and it is no longer named anywhere in the ladder either")

    def test_the_unlock_is_the_players_own_observation(self) -> None:
        """Their 2026-09-13 compilation observed 0x25 -> 0x26. That is now the transition verbatim."""
        transition = next(t for t in sb.TRANSITIONS if "Cipher Lab" in t.opens_regions)
        self.assertEqual((0x25, 0x26), (transition.before, transition.after))
        self.assertEqual((), transition.passthrough)

    def test_no_hole_opened_between_mt_battle_and_the_lab(self) -> None:
        mt, lab = sb.REGION_STORY_WINDOW["Mt. Battle"], sb.REGION_STORY_WINDOW["Cipher Lab"]
        self.assertEqual(0x24, mt.floor)
        self.assertEqual(0x26, lab.floor)
        self.assertEqual(mt.ceiling + 1, lab.floor)

    def test_every_byte_between_the_windows_belongs_to_one_of_them(self) -> None:
        mt, lab = sb.REGION_STORY_WINDOW["Mt. Battle"], sb.REGION_STORY_WINDOW["Cipher Lab"]
        self.assertEqual(mt.ceiling + 1, lab.floor)


class TestTheLookupWasNeverTheProblem(unittest.TestCase):
    def test_the_destination_id_is_the_players_reading(self) -> None:
        self.assertEqual("Cipher Lab", md.region_for_location_id(8))

    def test_the_cursor_index_is_not_a_key(self) -> None:
        """It moved 6 -> 4 between two readings while the id held; nothing may resolve on it."""
        self.assertEqual(4, md.BY_LOCATION_ID[8].cursor_index)
        self.assertEqual(8, md.BY_LOCATION_ID[8].location_id)
