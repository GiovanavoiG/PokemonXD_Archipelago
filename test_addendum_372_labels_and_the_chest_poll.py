"""ADDENDUM 372 (2026-09-27): five chest labels, and the chest poll's two real gaps.

Player, in one message:

  * "Rename 'Cipher Lab Chest 1' to 'Lovrina Defeat Item'."
  * "There is a chest in the Key Lair named Snagem 3F Chest 1 - please rename to 'Cipher Key Lair 1F Central
    Chest'."                                          <- NOT DONE; see `TestTheOneThatWasNotDone` below.
  * "Swap 'Gonzap's Room Chest' and 'Snagem 2F Chest 1'."
  * "Bonsly room Shiny and chest 1 are swapped."
  * "Please speed up the chest polling in every situation, as users are still missing chests if they leave
    quickly."

THE ID IS FROZEN, THE LABEL IS NOT -- and for a SWAP that sentence has a direction that matters. A location's
id belongs to the CHEST, not to the string: chest 103 keeps 1515 and chest 105 keeps 1517, and the labels cross
over between them. Getting that backwards would move two ids and silently re-point two checks.

THE POLLING HALF. What I measured before changing anything, driving `ChestBerryTracker` over the real chest
tables -- open a chest, then poll from somewhere else entirely, at 0.02 / 0.05 / 0.1 / 1.0s, flagged and
unflagged, and with the room unreadable for the whole run: every case CREDITED. So ADDENDUM 345 holds and
nothing is dropped. The real complaint is the hard edge on latency -- a chest with no measured open-flag has no
second witness and waits out `_CONFIRM_SECONDS` (2.0s), and a player who leaves, closes Dolphin or ends the
session inside those two seconds loses it for real.

The rate moved anyway (0.1 -> 0.05, free: every chest window is a wall-clock floor since ADDENDA 259/262), but
the two things that were actually costing polls were not the number:

  1. An incoming item ENDED the window before `check_chests` ran, so in a multiworld delivering an item most
     ticks -- which is exactly when a player is moving fast -- the chest half ran at the outer 1.0s rate.
  2. The map screen skipped the window entirely, and opening the map is how a player leaves a room fastest.
"""
from __future__ import annotations

import pathlib
import re
import unittest

from .. import locations as L
from ..game_data import chest_names as cn, chest_regions, chest_table

CLIENT = (pathlib.Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")
WINDOW = CLIENT[CLIENT.index("async def fast_poll_window"):]
WINDOW = WINDOW[:WINDOW.index("\nasync def ", 1)]

NAME_BY_CHEST = {ids[0]: name for ids, name in cn.CHEST_LOCATION_NAME_OVERRIDES.items() if len(ids) == 1}
IDS = L.get_location_name_to_id(0)


class TestTheLabels(unittest.TestCase):
    def test_the_cipher_lab_rename(self) -> None:
        self.assertEqual("Lovrina Defeat Item", NAME_BY_CHEST[17])
        self.assertNotIn("Cipher Lab Chest 1", IDS, "the old label must not still resolve")

    def test_the_gonzap_swap(self) -> None:
        self.assertEqual("Gonzap Room Chest", NAME_BY_CHEST[103])
        self.assertEqual("Snagem 2F Chest 1", NAME_BY_CHEST[105])

    def test_the_bonsly_swap(self) -> None:
        self.assertEqual("Bonsly Room Shiny Chest", NAME_BY_CHEST[30])
        self.assertEqual("Bonsly Room Chest 1", NAME_BY_CHEST[38])

    def test_every_swapped_id_stayed_with_its_own_chest(self) -> None:
        """The assertion the whole rename rests on. These are the ids those chests held before this addendum,
        recorded here as literals rather than derived, because a table that derives them from the current
        labels would agree with itself however wrong it was."""
        for chest, location_id in ((17, 1644), (30, 1502), (38, 1509), (103, 1515), (105, 1517)):
            self.assertEqual(location_id, IDS[NAME_BY_CHEST[chest]],
                             f"chest {chest} changed location id -- a swap must move labels, never ids")

    def test_no_two_locations_share_an_id(self) -> None:
        """A label swap done in one table and not the other is how two names end up on one id."""
        self.assertEqual(len(IDS), len(set(IDS.values())))

    def test_a_swap_moves_no_room_region_or_gate(self) -> None:
        """Both swapped pairs are within one room, which is what makes them purely cosmetic."""
        room = {entry["chest"]: entry["room"] for entry in chest_table.CHESTS}
        self.assertEqual(room[103], room[105])
        self.assertEqual(room[30], room[38])
        for a, b in ((103, 105), (30, 38)):
            self.assertEqual(chest_regions.region_for_room(room[a]),
                             chest_regions.region_for_room(room[b]))

    def test_the_names_still_agree_with_the_iso_rooms(self) -> None:
        """`chest_names` fences every label against the real table at import, so this asserts the fence covers
        the rows that moved rather than re-deriving it."""
        for chest in (17, 30, 38, 103, 105):
            self.assertIn(chest, cn.CHEST_NAME_EXPECTED_ROOM)
        self.assertEqual(8, cn.CHEST_NAME_EXPECTED_ROOM[17])
        self.assertEqual(166, cn.CHEST_NAME_EXPECTED_ROOM[103])
        self.assertEqual(166, cn.CHEST_NAME_EXPECTED_ROOM[105])

    def test_the_two_clients_still_build_the_same_string(self) -> None:
        """`chest_names` exists because `locations.py` and `ram_client.py` format the name independently and a
        one-character difference silently rejects every chest check. A rename is exactly when that can drift."""
        from .. import ram_client as rc

        for chest in (17, 30, 38, 103, 105):
            self.assertIn(NAME_BY_CHEST[chest], rc.CHEST_LOCATION_NAMES)
            self.assertIn(NAME_BY_CHEST[chest], IDS)


class TestTheOneThatWasNotDone(unittest.TestCase):
    """"There is a chest in the Key Lair named Snagem 3F Chest 1 - please rename to 'Cipher Key Lair 1F Central
    Chest'."

    NOT RENAMED, AND THIS TEST IS WHY RATHER THAN AN OVERSIGHT. Chest 106 is in ROOM 167, and room 167 is
    `Snagem Hideout` in `chest_regions` -- which is the table the chest's ACCESS RULE reads. Two of the
    player's own compilations put it there independently (the ADDENDUM 167 room list and the ADDENDUM 219 name
    list), and the Cipher Key Lair's rooms are 64-68 and 70, all of which are full.

    So renaming 106 alone would produce a location literally called "Cipher Key Lair 1F Central Chest" that
    Archipelago requires the SNAGEM HIDEOUT to reach -- the exact failure `chest_names` warns about ("a
    location name that disagrees with its own region reads as a bug forever after"), and since ADDENDA 332/371
    decoupled the Lair from Snagem, a gating mismatch as well as a naming one.

    The two readings are a rename (label only) or a re-region (room 167 moves to the Lair, which moves the
    gate for BOTH chests in it, 106 and 107 -- and the player asked about only one). That is a logic change on
    a physical-geography question, so it is left for the player to settle rather than guessed at.

    This test pins the CURRENT state so the ambiguity cannot be resolved by accident: if room 167 ever moves,
    the label has to move with it."""

    def test_chest_106_is_still_consistent_with_itself(self) -> None:
        room = {entry["chest"]: entry["room"] for entry in chest_table.CHESTS}
        self.assertEqual(167, room[106])
        region = chest_regions.region_for_room(167)
        self.assertEqual("Snagem Hideout", region)
        self.assertEqual("Snagem 3F Chest 1", NAME_BY_CHEST[106],
                         "chest 106's label and its region must name the same place -- rename it only when "
                         "room 167 moves to the Cipher Key Lair, and move chest 107 with it")

    def test_the_key_lairs_first_floor_is_full(self) -> None:
        """Why "1F Central" cannot just be a sixth room-64 chest that was missed: room 64 holds exactly the
        four already named, so the chest the player met is not an unnamed one."""
        room_64 = sorted(e["chest"] for e in chest_table.CHESTS if e["room"] == 64)
        self.assertEqual([43, 44, 49, 56], room_64)
        for chest in room_64:
            self.assertTrue(NAME_BY_CHEST[chest].startswith("Cipher Key Lair 1F"))


class TestTheChestPollIsFasterAndNoLongerStarved(unittest.TestCase):
    """Structural, against the source -- `Client.py` pulls in CommonClient (and websockets through it), which
    is not importable here. The established pattern for every Client.py-touching addendum in this project."""

    def _value(self, name: str) -> float:
        match = re.search(rf"^{name} = ([0-9.]+)", CLIENT, re.M)
        self.assertIsNotNone(match, f"{name} is not defined at module level any more")
        return float(match.group(1))

    def test_the_sub_poll_matches_the_map_screens_rate(self) -> None:
        """The map screen is the one place in this client that was already racing a thumb. A chest opened on
        the way out is the same race, so it gets the same interval."""
        self.assertEqual(self._value("POLL_INTERVAL_MAP_SCREEN"), self._value("POLL_INTERVAL_FAST"))
        self.assertLess(self._value("POLL_INTERVAL_FAST"), self._value("POLL_INTERVAL_INGAME"))

    def test_an_incoming_item_no_longer_ends_the_window_without_polling_chests(self) -> None:
        """Gap 1. The `watcher_event` branch used to `return 0.0` immediately, so a player receiving an item
        most ticks got the chest half cut off at the first sub-tick."""
        wake = WINDOW[WINDOW.index("Something was queued for us"):]
        wake = wake[:wake.index("return 0.0")]
        self.assertIn("check_chests", wake,
                      "the wake path returns the budget without polling chests -- in a busy multiworld that "
                      "is the chest poll running at the outer 1.0s rate")
        self.assertIn("block_stability.poll", wake,
                      "that poll must still sit behind ADDENDUM 148's gate like every other chest poll")

    def test_the_map_screen_enters_the_window_too(self) -> None:
        """Gap 2. Opening the map is how a player leaves a room fastest, and it was the one situation the
        window explicitly skipped."""
        call = "sleep_time = await fast_poll_window(ctx, sleep_time)"
        self.assertIn(call, CLIENT)
        before = CLIENT[:CLIENT.index(call)]
        guard = before[before.rindex("\n", 0, before.rindex("\n")) + 1:]
        self.assertNotIn("MAP_SCREEN_ROOM_ID", guard,
                         "the window is gated off the map screen again -- that is the situation the player's "
                         "report is about")

    def test_every_chest_window_is_still_a_clock_and_not_a_poll_count(self) -> None:
        """WHY THE RATE CHANGE IS FREE, and ADDENDUM 228's trap restated: a faster poll must not shorten any
        window. All three of the chest tracker's are real durations."""
        from .. import ram_client as rc

        self.assertIsInstance(rc.ChestBerryTracker._CONFIRM_SECONDS, float)
        self.assertIsInstance(rc.ChestBerryTracker._MAX_PENDING_SECONDS, float)
        self.assertIsInstance(rc.ChestBerryTracker._FLAG_CORROBORATION_SECONDS, float)

    def test_the_window_still_only_spends_time_the_loop_was_going_to_wait(self) -> None:
        """The invariant that makes all of this additive: the sub-loop is handed the sleep and returns what is
        left of it. If it ever stopped doing that, the outer tick would slow down and every confirm window
        sized against it would stretch."""
        self.assertIn("return max(0.0, remaining)", WINDOW)
        self.assertIn("remaining -= tick", WINDOW)
        self.assertRegex(WINDOW, r"tick = min\(POLL_INTERVAL_FAST, remaining\)")


class TestNothingIsDroppedAtAnyRate(unittest.TestCase):
    """The measurement the polling change was based on, kept as a test so "nothing is dropped" stays a fact.

    Drives the real tracker over the real chest tables: open a chest, then poll from a DIFFERENT room for the
    rest of the run, at several sub-poll rates. ADDENDUM 345 promised this and the rate change must not
    undo it."""

    def setUp(self) -> None:
        from .test_addendum_345_a_chest_opened_on_the_way_out import _World, _a_chest
        self._World, self._a_chest = _World, _a_chest

    def _run(self, with_flag: bool, seconds_each: float, leave: bool) -> "list[str]":
        from .. import ram_client as rc
        from ..game_data import chest_berries

        picked = self._a_chest(with_flag)
        if picked is None:
            self.skipTest("no such chest in this build")
        chest, room, berry = picked
        world = self._World()
        tracker = rc.ChestBerryTracker(clock=world.clock)
        world.install(self, tracker)
        elsewhere = next(r for r in sorted(set(chest_berries.CHEST_TO_ROOM.values())) if r != room)
        world.bag[berry] = 0
        tracker._poll(0x80479000, room, frozenset(), chest_berries)
        world.now += seconds_each
        if with_flag:
            world.open_chest(chest)
        world.bag[berry] = 1
        got: "list[str]" = []
        # Long enough for the slowest path (`_MAX_PENDING_SECONDS`, 4.0s) to settle at any rate.
        for _ in range(int(12.0 / seconds_each)):
            got += tracker._poll(0x80479000, (elsewhere if leave else room), frozenset(), chest_berries)
            world.now += seconds_each
        return got

    def test_leaving_immediately_still_credits_at_every_rate(self) -> None:
        for with_flag in (True, False):
            for rate in (0.02, 0.05, 0.1, 1.0):
                with self.subTest(flagged=with_flag, rate=rate):
                    self.assertTrue(self._run(with_flag, rate, leave=True),
                                    "a chest opened on the way out was not credited -- ADDENDUM 345's "
                                    "promise, which the rate change must not undo")

    def test_staying_still_credits_at_every_rate(self) -> None:
        for with_flag in (True, False):
            for rate in (0.05, 1.0):
                with self.subTest(flagged=with_flag, rate=rate):
                    self.assertTrue(self._run(with_flag, rate, leave=False))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
