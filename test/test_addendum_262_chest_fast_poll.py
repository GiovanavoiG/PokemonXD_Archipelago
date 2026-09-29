"""ADDENDUM 262 (2026-09-17): the chest poll joins the fast window, and one of its windows runs backwards.

Player: "Can we separate the chest opening poll and make that faster as well?"

ADDENDUM 259 built the fast sub-poll for shops. Adding chests to it is a small change with one genuinely
dangerous corner, and this file is mostly about that corner.

**THE TWO HALVES ARE GATED DIFFERENTLY.** A shop check can only happen in a shop room, so `check_shops` keeps
its room gate and nothing outside a shop pays for it. A chest can be opened ANYWHERE, so `check_chests` has no
room to gate on and runs every sub-tick. It is affordable on its own merits -- one `read_room_id` plus one
bulk Bag read -- not by inheriting the shop argument.

**AND `ChestBerryTracker` HAS TWO WINDOWS THAT NEED OPPOSITE TREATMENT**, which is the part worth being
careful about:

  * `_CONFIRM_SECONDS` (was `_CONFIRM_STREAK` alone) -- the debounce. Like every other window in `ram_client`,
    cutting it short risks a PHANTOM check, so the fix is a floor: both the agreeing reads and the real
    seconds must be satisfied. A clock floor can only delay a credit, never advance one.

  * `_MAX_PENDING_SECONDS` (was `_MAX_PENDING_POLLS` alone) -- the deadline on a pickup waiting for a readable
    room. This one runs the OTHER WAY. Cutting it short does not risk a phantom; it ABANDONS A CHECK THE
    PLAYER ALREADY EARNED, which is the one outcome this project treats as unacceptable. At the sub-poll's
    0.1s tick, a bare count of 4 polls would abandon a real pickup after four tenths of a second.

Treating both as "a window, in polls" -- which is what they looked like -- would have turned a latency
improvement into silently lost checks, with no error and nothing in any log. That is the specific mistake
these tests exist to make impossible.
"""
from __future__ import annotations

import pathlib
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

from .. import ram_client as rc
from ..game_data import chest_berries


BLOCK = 0x80479000


class _Bag:
    """A fake Bag plus a clock the test drives, so a 'poll' can be any duration it likes."""

    def __init__(self) -> None:
        self.quantities: "dict[int, int]" = {}
        self.t = 0.0
        self._find, self._clear = rc.find_item_quantity, rc.clear_item
        rc.find_item_quantity = lambda base, slots, item_id: self.quantities.get(item_id, 0)

        def fake_clear(base, slots, item_id):
            self.quantities[item_id] = 0
            return True

        rc.clear_item = fake_clear

    def restore(self) -> None:
        rc.find_item_quantity, rc.clear_item = self._find, self._clear

    def tracker(self) -> "rc.ChestBerryTracker":
        return rc.ChestBerryTracker(clock=lambda: self.t)

    def run(self, tracker, room, ticks, step):
        out: "list[str]" = []
        for _ in range(ticks):
            out.extend(tracker.poll(BLOCK, room_id=room, already_checked=frozenset()))
            self.t += step
        return out


def _a_real_chest() -> "tuple[int, int, int, str]":
    """(chest id, its room, its berry, its AP location name) for some chest this client can credit."""
    for chest, (berry, _q) in chest_berries.CHEST_BERRY_ASSIGNMENT.items():
        name = rc.CHEST_ID_TO_LOCATION.get(chest)
        if name:
            return chest, chest_berries.CHEST_TO_ROOM[chest], berry, name
    raise unittest.SkipTest("no creditable chest in the table")


class TestTheDebounceIsAFloor(unittest.TestCase):
    """The safe direction: a faster poll must not be able to credit a chest sooner than the real window."""

    def setUp(self) -> None:
        self.bag = _Bag()
        self.addCleanup(self.bag.restore)
        _chest, self.room, self.berry, self.name = _a_real_chest()

    def test_a_fast_tick_cannot_credit_on_a_single_read(self) -> None:
        """RETARGETED BY ADDENDUM 375, which removed the clock this test was named after.

        The original property -- "reads alone never beat the clock" -- no longer exists to be tested, because
        the reads ARE the debounce now. What survives, and is the thing a faster poll could actually break, is
        the floor underneath it: one sighting of a rise never credits, however fast the sub-poll runs. That is
        `_MIN_CONFIRM_STREAK`'s whole job (see `CONFIRM_WINDOW_SECONDS["chest_berry"]`), and at a fast tick it
        is the ONLY thing left, which makes this a more important test than the one it replaces rather than a
        weaker one."""
        for step in (0.02, 0.05, 0.1, 1.0):
            with self.subTest(step=step):
                tracker = self.bag.tracker()
                self.bag.quantities[self.berry] = 0
                self.bag.run(tracker, self.room, ticks=1, step=step)      # baseline
                self.bag.quantities[self.berry] = 1
                self.assertEqual([], self.bag.run(tracker, self.room, ticks=1, step=step),
                                 "a single read credited a chest -- the streak floor is gone")
                self.assertGreaterEqual(tracker._CONFIRM_STREAK, 2)

    def test_and_it_does_credit_on_the_very_next_read(self) -> None:
        """ADDENDUM 375: the second agreeing read is the whole wait. At ADDENDUM 372's 0.05s sub-poll that is
        one tenth of a second, which is the answer to "just send it the moment we get it"."""
        tracker = self.bag.tracker()
        step = 0.05                                             # ADDENDUM 372's sub-poll rate
        self.bag.quantities[self.berry] = 0
        self.bag.run(tracker, self.room, ticks=1, step=step)
        self.bag.quantities[self.berry] = 1
        self.assertEqual([], self.bag.run(tracker, self.room, ticks=1, step=step))
        self.assertEqual([self.name], self.bag.run(tracker, self.room, ticks=1, step=step))

    def test_at_the_ordinary_one_second_cadence_nothing_changed(self) -> None:
        """Regression fence. At POLL_INTERVAL_INGAME the two floors coincide and a pickup credits on the same
        poll it always did."""
        tracker = self.bag.tracker()
        self.bag.run(tracker, self.room, ticks=1, step=1.0)
        self.bag.quantities[self.berry] = 1
        self.assertEqual([self.name], self.bag.run(tracker, self.room, ticks=3, step=1.0))


class TestTheAbandonDeadlineRunsTheOtherWay(unittest.TestCase):
    """THE DANGEROUS ONE. Every other window here guards against firing too early. This one bounds how long a
    REAL pickup is held before being thrown away, so shrinking it costs the player a check they earned."""

    def setUp(self) -> None:
        self.bag = _Bag()
        self.addCleanup(self.bag.restore)
        _chest, self.room, self.berry, self.name = _a_real_chest()

    def test_a_fast_poll_does_not_abandon_a_pickup_early(self) -> None:
        """THE BUG THIS ADDENDUM WOULD OTHERWISE HAVE SHIPPED. With a bare `_MAX_PENDING_POLLS` of 4, twenty
        sub-ticks at 0.1s -- two real seconds -- would abandon a pickup whose room is momentarily unreadable.
        The player opened a chest and the check simply never fires, with nothing logged."""
        tracker = self.bag.tracker()
        self.bag.run(tracker, None, ticks=1, step=0.1)
        self.bag.quantities[self.berry] = 1
        self.bag.run(tracker, None, ticks=40, step=0.1)          # 4 seconds of unreadable room... at 0.1s
        self.assertEqual(0, tracker.abandoned_pickups,
                         "%.1fs of polling is inside the %.1fs deadline -- nothing may be abandoned yet"
                         % (4.0, tracker._MAX_PENDING_SECONDS))
        # And it is still there to be credited the moment the room comes back.
        self.assertEqual([self.name], self.bag.run(tracker, self.room, ticks=1, step=0.1))

    def test_it_still_abandons_once_the_real_deadline_has_passed(self) -> None:
        """The other half: the deadline is a deadline, not a removal of one. An indefinitely held pickup would
        resolve against whatever room the player eventually wandered into -- the ADDENDUM 226 bug."""
        tracker = self.bag.tracker()
        self.bag.run(tracker, None, ticks=1, step=1.0)
        self.bag.quantities[self.berry] = 1
        self.bag.run(tracker, None, ticks=12, step=1.0)
        self.assertGreater(tracker.abandoned_pickups, 0)
        self.assertEqual([], self.bag.run(tracker, self.room, ticks=2, step=1.0),
                         "an expired pickup must not credit a room reached later")

    def test_both_floors_have_to_be_exhausted_not_either(self) -> None:
        """Pinned as a relationship rather than by outcome. `waited > polls` alone is what made this
        dangerous; `elapsed > seconds` alone would abandon on the very first poll of a slow tick."""
        source = pathlib.Path(rc.__file__).read_text(encoding="utf-8")
        # ADDENDUM 345 inverted this `if` (the deadline now falls through to the room history instead of
        # dropping the pickup), so the polarity is no longer part of the contract. The CONJUNCTION is: both
        # floors, never either one alone.
        conjunction = 'entry["waited"] > self._MAX_PENDING_POLLS and waited_long_enough'
        self.assertIn(conjunction, source,
                      "abandonment must require BOTH the poll count and the real duration")


class TestTheWindowsComeFromOnePlace(unittest.TestCase):

    def test_both_chest_windows_are_declared_durations(self) -> None:
        """`CONFIRM_WINDOW_SECONDS` is where ADDENDUM 228 put these, and a second copy of a number is how two
        copies drift apart."""
        self.assertEqual(rc.CONFIRM_WINDOW_SECONDS["chest_berry"],
                         rc.ChestBerryTracker._CONFIRM_SECONDS)
        self.assertEqual(rc.CONFIRM_WINDOW_SECONDS["chest_pending"],
                         rc.ChestBerryTracker._MAX_PENDING_SECONDS)

    def test_the_default_clock_is_monotonic(self) -> None:
        import time as _time

        self.assertIs(_time.monotonic, rc.ChestBerryTracker().clock)


class TestTheClientWiring(unittest.TestCase):
    """Structural -- `Client.py` is not importable in this environment."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (pathlib.Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")
        start = cls.source.index("async def fast_poll_window")
        cls.body = cls.source[start:][:cls.source[start:].index("\nasync def ", 1)]

    def test_the_window_runs_chests_with_no_room_gate(self) -> None:
        """The whole point. A chest can be opened anywhere, so gating the chest half on a shop room -- the
        obvious copy-paste -- would make this change do nothing at all."""
        self.assertIn("if ctx.randomize_chests:\n                await check_chests(ctx)", self.body)

    def test_the_window_still_gates_shops_on_a_shop_room(self) -> None:
        self.assertIn("ctx.randomize_shops and ram_client.is_shop_room(room_id)", self.body)

    def test_it_no_ops_when_neither_option_is_on(self) -> None:
        """A seed with neither chests nor shops randomized must not spin a sub-loop for nothing."""
        self.assertIn("if not ctx.randomize_shops and not ctx.randomize_chests:", self.body)

    def test_the_map_screen_is_excluded(self) -> None:
        """While the window was shop-only this held by accident -- a room cannot be both the map screen and a
        shop. The chest half has no room gate, so the exclusion is now explicit, and it matters: the map
        screen's own fast tick is a race against the player's thumb (ADDENDUM 210) and nothing may spend it."""
        self.assertIn("if ctx.room_tracker.current != ram_client.MAP_SCREEN_ROOM_ID:", self.source)


if __name__ == "__main__":
    unittest.main()
