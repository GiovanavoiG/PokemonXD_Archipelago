"""ADDENDUM 259 (2026-09-17): the shop path gets its own poll rate, and its debounce stops depending on one.

Player: "What's the poll rate on the shop data -- can we make it only running in shops so we can make it a
fast poll?"

THE ANSWER TO THE FIRST HALF was that the shop path had no rate of its own: `check_shops()` is one call in
the single poll body, so it ran at POLL_INTERVAL_INGAME -- once a second -- in a shop and everywhere else.

THE SECOND HALF IS TWO CHANGES, and they are separable on purpose:

  1. `fast_poll_window()` spends the ordinary between-tick WAIT re-running only the shop path, at
     POLL_INTERVAL_FAST, and only while the player is standing in a shop room. The outer tick's cadence is
     untouched, so nothing else in the loop is rescaled -- which is the whole reason this is a sub-loop and
     not a second value for `sleep_time` the way the map screen's is. See POLL_INTERVAL_FAST's own comment
     for the three specific things a loop-wide speedup in a shop room would have dragged with it (the 24MB
     battle-roster scan above all).

  2. `ShopPurchaseTracker` gains a wall-clock floor on top of its existing consecutive-read floor, so the
     faster tick cannot shorten the ADDENDUM 99 window. This is the half that matters: ADDENDUM 228 pointed
     out that every confirm streak in `ram_client` counts POLLS while justifying itself in SECONDS, and
     fixed it by converting once at startup via `set_poll_interval()` -- correct exactly as long as there is
     one poll rate. This addendum introduces a second one, so the conversion is no longer sufficient and the
     duration has to be measured rather than derived.

SEPARATELY, and with its own justification: `CONFIRM_WINDOW_SECONDS["shop_purchase"]` drops 4.0 -> 2.0,
following `chest_berry` down for the identical reason (ADDENDUM 218) -- both are Bag-quantity watchers
sitting BEHIND ADDENDUM 148's block-stability gate, so the save-menu glitch the 4.0 was widened for is now
caught a line earlier and this window is the second line, not the first. That is the change that actually
shortens purchase-to-check; the fast poll only removes the up-to-one-second granularity error on top of it.
"""
from __future__ import annotations

import re
import sys
import types
import unittest
from pathlib import Path

if "dolphin_memory_engine" not in sys.modules:
    _stub = types.ModuleType("dolphin_memory_engine")
    _stub.hook = lambda: None
    _stub.un_hook = lambda: None
    _stub.is_hooked = lambda: False
    _stub.read_bytes = lambda address, length: b""
    _stub.write_bytes = lambda address, data: None
    sys.modules["dolphin_memory_engine"] = _stub

from unittest import mock

from .. import ram_client


RAZZ = 148
GATEON_SHOP_ROOM = 156


def _client_source() -> str:
    return (Path(__file__).resolve().parents[1] / "Client.py").read_text(encoding="utf-8")


class TestTheDurationFloor(unittest.TestCase):
    """The half that makes a second poll rate SAFE. Everything here is about the tracker, not the loop."""

    def _tracker(self) -> "tuple[ram_client.ShopPurchaseTracker, dict]":
        clock = {"t": 0.0}
        return ram_client.ShopPurchaseTracker(clock=lambda: clock["t"]), clock

    def _run(self, tracker, clock, quantities, step, room_id=GATEON_SHOP_ROOM):
        """Poll once per entry, advancing the injected clock by `step` seconds each time."""
        results = []

        def fake_read_pocket(pocket_base, max_slots, _polls=iter(quantities)):
            qty = next(_polls)
            return [ram_client.BagSlot(index=0, address=0, item_id=RAZZ, quantity=qty)] if qty else []

        with mock.patch.object(ram_client, "read_pocket", side_effect=fake_read_pocket):
            with mock.patch.object(ram_client, "clear_item", return_value=True):
                for _ in quantities:
                    results.append(tracker.poll(block_base=0, room_id=room_id, berry_ids=[RAZZ]))
                    clock["t"] += step
        return results

    def test_a_fast_tick_cannot_confirm_faster_than_the_window(self) -> None:
        """THE POINT OF THE WHOLE ADDENDUM. Polled ten times a second -- the shop sub-loop's rate -- the
        consecutive-read floor is satisfied almost instantly, and before this change that alone would have
        fired the check ~0.4 real seconds after a purchase instead of the several seconds ADDENDUM 99
        deliberately widened the window to. The duration floor is what stops it."""
        tracker, clock = self._tracker()
        streak = tracker._CONFIRM_STREAK
        # Baseline, then the candidate held for well past the read floor but well inside the time window.
        quantities = [0] + [1] * (streak + 3)
        results = self._run(tracker, clock, quantities, step=0.1)
        self.assertEqual([[] for _ in quantities], results,
                         "%.1fs of polling is inside the %.1fs window -- nothing may fire yet"
                         % (0.1 * (len(quantities) - 1), tracker._CONFIRM_SECONDS))

    def test_and_it_does_confirm_once_the_window_really_has_elapsed(self) -> None:
        """The mirror of the test above, and the one that proves the floor is a floor rather than a block.
        Same fast tick, held long enough for the real duration to pass."""
        tracker, clock = self._tracker()
        polls = int(tracker._CONFIRM_SECONDS / 0.1) + 3
        results = self._run(tracker, clock, [0] + [1] * polls, step=0.1)
        fired = [r for r in results if r]
        self.assertEqual([["Gateon Port Shop AP Item 1"]], fired)

    def test_at_the_ordinary_one_second_cadence_nothing_changed(self) -> None:
        """Regression fence for the change itself. At POLL_INTERVAL_INGAME the read floor and the duration
        floor coincide, and a purchase must still confirm on exactly the poll it always did -- the one
        completing `_CONFIRM_STREAK` consecutive agreeing reads."""
        tracker, clock = self._tracker()
        streak = tracker._CONFIRM_STREAK
        results = self._run(tracker, clock, [0] + [1] * streak, step=1.0)
        self.assertEqual([[]] * streak, results[:streak])
        self.assertEqual(["Gateon Port Shop AP Item 1"], results[streak])

    def test_a_reverted_candidate_drops_its_timestamp_too(self) -> None:
        """A candidate that goes away and comes back must restart its CLOCK, not just its streak. If
        `_pending_since` survived a reset, a berry that flickered up, back down and up again an hour later
        would confirm on its very first agreeing read -- a debounce that gets weaker the longer you play."""
        tracker, clock = self._tracker()
        self._run(tracker, clock, [0, 1], step=1.0)
        self.assertIn(RAZZ, tracker._pending_since)
        self._run(tracker, clock, [0], step=1.0)   # back to baseline -- candidate withdrawn
        self.assertNotIn(RAZZ, tracker._pending_since)
        self.assertNotIn(RAZZ, tracker._pending_streak)

    def test_a_confirmed_purchase_clears_its_timestamp(self) -> None:
        """Otherwise the NEXT purchase of the same line would inherit a stale start time and skip the window
        entirely -- the same class of bug as the one above, on the other side of the credit."""
        tracker, clock = self._tracker()
        self._run(tracker, clock, [0] + [1] * tracker._CONFIRM_STREAK, step=1.0)
        self.assertNotIn(RAZZ, tracker._pending_since)

    def test_the_floor_is_the_declared_window_not_a_literal(self) -> None:
        """`_CONFIRM_SECONDS` has to come from `CONFIRM_WINDOW_SECONDS`, which is the one place ADDENDUM 228
        established these durations live. A second copy of the number is how the two drift apart."""
        self.assertEqual(ram_client.CONFIRM_WINDOW_SECONDS["shop_purchase"],
                         ram_client.ShopPurchaseTracker._CONFIRM_SECONDS)

    def test_the_default_clock_is_monotonic_not_wall_time(self) -> None:
        """`time.time()` can step backwards (NTP, a manual clock change) and would make a window that never
        closes. The injectable clock exists for tests; the default must be the monotonic one."""
        import time as _time

        self.assertIs(_time.monotonic, ram_client.ShopPurchaseTracker().clock)


class TestTheWindowItself(unittest.TestCase):

    def test_shops_keep_the_post_gate_width_and_chests_are_now_shorter(self) -> None:
        """RETARGETED 2026-09-27 (ADDENDUM 373). This asserted the two were EQUAL, on the reasoning that both
        are Bag-quantity watchers behind ADDENDUM 148's gate so neither should carry a wider second line. That
        reasoning was right and is not what changed: the player asked for the CHEST wait specifically
        ("Shorten the 2 seconds"), and said nothing about shops.

        So the relationship is broken deliberately rather than by dragging shops along. A shop purchase is not
        the case the player is waiting on -- they are standing at a counter, not running out of a room -- and
        pulling its window down would be a latency change nobody asked for on the one tracker whose failure
        mode is spending money for nothing. What is asserted now is the ordering plus a real floor on each, so
        a future edit still cannot turn either one off."""
        windows = ram_client.CONFIRM_WINDOW_SECONDS
        self.assertLessEqual(windows["chest_berry"], windows["shop_purchase"])
        # ADDENDUM 375 took the chest clock to zero outright; shops keep theirs. The shop half is what this
        # addendum is about, so that is what gets the floor.
        self.assertGreaterEqual(windows["shop_purchase"], 2.0)

    def test_it_is_still_a_real_window_and_not_effectively_off(self) -> None:
        self.assertGreaterEqual(ram_client.CONFIRM_WINDOW_SECONDS["shop_purchase"], 2.0)


class TestTheSubLoop(unittest.TestCase):
    """Structural, against the SOURCE -- `Client.py` pulls in CommonClient (and websockets through it), which
    is not importable in this environment. Same established pattern as every other Client.py-touching
    addendum in this project."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = _client_source()
        start = cls.source.index("async def fast_poll_window")
        cls.body = cls.source[start:][:cls.source[start:].index("\nasync def ", 1)]

    def test_the_shop_interval_exists_and_is_faster_than_the_ordinary_one(self) -> None:
        def value(name: str) -> float:
            match = re.search(rf"^{name} = ([0-9.]+)", self.source, re.M)
            self.assertIsNotNone(match, f"{name} is not defined at module level any more")
            return float(match.group(1))

        self.assertLess(value("POLL_INTERVAL_FAST"), value("POLL_INTERVAL_INGAME"))
        self.assertGreater(value("POLL_INTERVAL_FAST"), 0.0)

    def test_the_shop_half_only_runs_in_a_shop_room(self) -> None:
        """"Only running in shops" is the player's own framing, and it is also what makes this affordable:
        nothing outside a shop pays anything at all for the shop half.

        NARROWED 2026-09-17 (ADDENDUM 262). This used to check that the LOOP only entered the window in a
        shop room. The window now also carries `check_chests`, which has no room to gate on -- a chest can be
        opened anywhere -- so the gate moved inside, onto the shop call itself. The guarantee is unchanged
        and is now checked where it actually lives.

        WIDENED 2026-09-27 (ADDENDUM 372), and it was the line arithmetic that needed it rather than the rule.
        This read exactly ONE line back from the first `check_chests` call, so it broke the moment the window
        gained a second chest poll on the `watcher_event` wake path -- whose guard spans two lines. Every
        `check_chests` call in the window is now checked, against a few lines of its enclosing context, which
        is a stronger statement than the original and survives being reformatted."""
        self.assertIn("sleep_time = await fast_poll_window(ctx, sleep_time)", self.source)
        self.assertIn("ctx.randomize_shops and ram_client.is_shop_room(room_id)", self.body)
        lines = self.body.split("\n")
        calls = [i for i, line in enumerate(lines) if "await check_chests(ctx)" in line]
        self.assertTrue(calls, "the window no longer polls chests at all")
        for index in calls:
            context = "\n".join(lines[max(0, index - 4):index])
            self.assertIn("ctx.randomize_chests", context,
                          f"the chest poll on line {index} of the window is not gated on the option")
            self.assertNotIn("is_shop_room", context,
                             "a chest can be opened anywhere -- gating the chest half on a shop room would "
                             "make this change do nothing at all")

    def test_it_replaces_the_wait_rather_than_adding_time_to_the_tick(self) -> None:
        """The sub-loop is handed `sleep_time` and returns what is LEFT of it. If it were called without
        consuming the budget, a shop room would stretch the outer tick to two seconds and every other check
        in the loop would get slower in a shop -- the exact opposite of the request."""
        call = self.source.index("fast_poll_window(ctx, sleep_time)")
        assignment = self.source.rindex("sleep_time = ", 0, call + 1)
        self.assertLess(assignment, call, "the return value must be assigned back to sleep_time")
        self.assertIn("return max(0.0, remaining)", self.body)

    def test_it_re_reads_the_room_every_sub_tick(self) -> None:
        """Walking out of a shop has to end the shop half immediately. Reusing the room the outer tick read
        would leave it firing in the overworld until the budget ran out."""
        self.assertIn("room_id = ram_client.read_room_id()", self.body)
        self.assertIn("ram_client.is_shop_room(room_id)", self.body)

    def test_it_re_polls_block_stability_itself(self) -> None:
        """It runs during the sleep, after the main loop's `if block_is_stable:` gate has gone out of scope.
        A sub-loop that skipped it would be a hole straight through ADDENDUM 148 -- the save menu can be
        opened standing in a shop like anywhere else."""
        self.assertIn("ctx.block_stability.poll(ctx.block_base)", self.body)

    def test_it_no_ops_when_shops_are_not_randomized(self) -> None:
        self.assertIn("not ctx.randomize_shops", self.body)

    def test_it_hands_the_budget_back_when_an_item_arrives(self) -> None:
        """ADDENDUM 44/80's standing rule: "Make sure NEVER to block sending items." The outer loop wakes on
        `watcher_event`, so a sub-loop that slept without watching it would delay every incoming item by up
        to a full tick for as long as the player stood in a shop."""
        self.assertIn("ctx.watcher_event.wait()", self.body)
        self.assertIn("return 0.0", self.body)

    def test_every_failure_path_returns_the_budget_instead_of_raising(self) -> None:
        """It occupies time the outer tick was going to spend waiting. Anything that escaped from here would
        reach `dolphin_sync_task`'s outer handler, which treats an exception as a LOST DOLPHIN CONNECTION --
        so a transient read failure in a shop would drop the player's connection."""
        self.assertIn("except Exception:", self.body)
        self.assertIn("return remaining", self.body)
        self.assertNotIn("raise", self.body)

    def test_it_stops_on_exit(self) -> None:
        self.assertIn("ctx.exit_event.is_set()", self.body)

    def test_the_map_screen_keeps_its_own_tick_and_is_excluded_from_the_window(self) -> None:
        """The map screen's rate is correctness rather than comfort (the area-memory write is a PRE-LOAD
        hook, ADDENDUM 177/210), so nothing may spend its sleep.

        TIGHTENED 2026-09-17 (ADDENDUM 262). While the window was shop-only this was safe by accident -- a
        room cannot be both the map screen and a shop -- so the test only pinned the ORDERING of the two
        branches. The chest half has no room gate, so that accident is gone and the exclusion has to be
        explicit."""
        map_branch = self.source.index("sleep_time = (POLL_INTERVAL_MAP_SCREEN")
        window_branch = self.source.index("sleep_time = await fast_poll_window(ctx, sleep_time)")
        self.assertLess(map_branch, window_branch, "the map interval must be chosen first")
        self.assertIn("if ctx.room_tracker.current != ram_client.MAP_SCREEN_ROOM_ID:", self.source)


if __name__ == "__main__":
    unittest.main()
