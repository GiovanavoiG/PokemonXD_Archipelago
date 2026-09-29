"""ADDENDUM 202. The item-delivery gate reads an address that was actually measured.

Player: "I want to detect the battle end, and delay items received in battle until then." Then, after the
first live read came back: "That anchor's wrong and has not been working. Assume we're looking from scratch."

`BATTLE_STRUCT_ANCHOR_ADDRESS` read 0 in all four live dumps taken that session, two of them from inside a
real battle. Seven addenda (33/34/37/39/41/44/80) of debounces, corroboration, reverts and restorations were
built on an address that never carried the signal.

`BATTLE_UI_FLAG_ADDRESS` replaces it, measured across eleven game states and three battles on the player's own
game -- see ram_client's own section docstring for the table and the method.

These tests pin the contract, not the value: the tracker must read the measured address, must never consult
the retired one, must block on nonzero, must require a streak before clearing, and must stay bounded by
give_items()'s hard timeout -- which is the player's standing rule ("Make sure NEVER to block sending items -
that was what ruined the run") and the reason ADDENDUM 44 had to rip this gate out once already."""
from __future__ import annotations

import ast
import unittest
from pathlib import Path

from .. import ram_client


class TestTheGateReadsTheMeasuredAddress(unittest.TestCase):
    def test_the_flag_address_is_the_measured_one(self) -> None:
        self.assertEqual(0x80814A64, ram_client.BATTLE_UI_FLAG_ADDRESS)

    def test_the_retired_anchor_is_still_named_but_not_read_by_the_tracker(self) -> None:
        """Kept for `!battle` to display; must not be what the gate consults."""
        source = Path(ram_client.__file__).read_text(encoding="utf-8")
        tracker = source.split("class BattleStateTracker", 1)[1].split("\n# ---", 1)[0]
        body = tracker.split('"""', 2)[2]   # past the class docstring
        self.assertIn("read_battle_ui_flag()", body)
        self.assertNotIn("read_battle_struct_anchor()", body)

    def test_the_flag_sits_beside_the_room_id_mirror(self) -> None:
        """Why this address is plausibly stable across boots -- it is in the region that already is."""
        self.assertLess(abs(ram_client.BATTLE_UI_FLAG_ADDRESS - ram_client.ROOM_ID_MIRRORS[0]), 0x100)

    def test_the_mode_enum_is_recorded_but_nothing_gates_on_it(self) -> None:
        """Five samples and no known reset condition -- an observation, not a signal."""
        self.assertEqual(0x80874E50, ram_client.BATTLE_MODE_ENUM_ADDRESS)
        source = Path(ram_client.__file__).read_text(encoding="utf-8")
        tracker = source.split("class BattleStateTracker", 1)[1].split("\n# ---", 1)[0]
        self.assertNotIn("read_battle_mode_enum", tracker)


class TestDebounceBehaviour(unittest.TestCase):
    def setUp(self) -> None:
        self.reads: "list[int]" = []
        self._real = ram_client.read_battle_ui_flag
        ram_client.read_battle_ui_flag = lambda: self.reads.pop(0)  # type: ignore[assignment]

    def tearDown(self) -> None:
        ram_client.read_battle_ui_flag = self._real  # type: ignore[assignment]

    def test_a_nonzero_read_blocks_immediately(self) -> None:
        t = ram_client.BattleStateTracker()
        self.reads = [1]
        self.assertFalse(t.poll())

    def test_clearing_requires_the_full_streak(self) -> None:
        t = ram_client.BattleStateTracker()
        n = ram_client.BattleStateTracker.CONFIRM_POLLS
        self.reads = [0] * n
        results = [t.poll() for _ in range(n)]
        self.assertEqual([False] * (n - 1) + [True], results)

    def test_one_nonzero_read_resets_the_streak(self) -> None:
        t = ram_client.BattleStateTracker()
        self.reads = [0, 0, 1, 0]
        self.assertFalse(t.poll())
        self.assertFalse(t.poll())
        self.assertFalse(t.poll())      # back in battle -- streak reset
        self.assertFalse(t.poll())      # only one clear poll since; not enough

    def test_corroboration_can_only_add_caution(self) -> None:
        """It vetoes; it can never permit. ADDENDUM 37 made it authoritative in both directions and that had
        to be reverted in ADDENDUM 39 -- this asserts the asymmetry is still in place."""
        t = ram_client.BattleStateTracker()
        self.reads = []                 # must not even be consulted
        self.assertFalse(t.poll(corroborating_in_battle=True))
        self.assertEqual(0, t._consecutive_zero)

    def test_the_streak_is_short_enough_to_be_usable_and_long_enough_to_debounce(self) -> None:
        self.assertGreaterEqual(ram_client.BattleStateTracker.CONFIRM_POLLS, 2)
        self.assertLessEqual(ram_client.BattleStateTracker.CONFIRM_POLLS, 8)


class TestDeliveryCanNeverBeBlockedForever(unittest.TestCase):
    """The player's standing rule, and the reason ADDENDUM 44 removed this gate entirely once before:
    "Make sure NEVER to block sending items - that was what ruined the run." A better gate must not become a
    new way to lose items, so the hard per-item timeout has to survive this addendum."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")

    def test_the_hard_timeout_still_exists(self) -> None:
        self.assertIn("ITEM_DELIVERY_MAX_BATTLE_WAIT_SECONDS", self.source)

    def test_the_timeout_still_bounds_the_gate(self) -> None:
        self.assertIn(
            "if not safe_to_start_new_items and waited < ITEM_DELIVERY_MAX_BATTLE_WAIT_SECONDS",
            self.source,
            "the battle gate is no longer bounded by the per-item timeout",
        )

    def _timeout_literal(self) -> int:
        tree = ast.parse(self.source)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Assign) and len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id == "ITEM_DELIVERY_MAX_BATTLE_WAIT_SECONDS"):
                self.assertIsInstance(node.value, ast.Constant)
                return node.value.value
        self.fail("ITEM_DELIVERY_MAX_BATTLE_WAIT_SECONDS not found")

    def test_the_timeout_is_a_sane_duration(self) -> None:
        """LOOSENED 2026-09-16 (ADDENDUM 248, player: "Increase the time limit on item delivery if in battle
        to 10 minutes"). The upper bound used to be 120, which was a TUNING guard from the era when this
        ceiling was load-bearing -- ADDENDUM 100's stuck tracker made every delayed item converge on it, so
        keeping it small mattered. That root cause is fixed at its source and the ceiling is now a last
        resort, so the real invariant this class exists to protect is the only one asserted here: the wait is
        FINITE and POSITIVE, so delivery can never be blocked forever (ADDENDUM 44's standing rule).

        The generous cap stays as a typo fence -- an accidental extra zero is still a bug -- but it no longer
        pretends to be a tuning opinion."""
        value = self._timeout_literal()
        self.assertGreater(value, 0, "a zero or negative ceiling would deliver straight into a battle")
        self.assertLessEqual(value, 3600, "an hour-plus ceiling is a typo, not a decision")

    def test_the_timeout_is_the_value_the_player_asked_for(self) -> None:
        """Pinned as a literal so a change to it is deliberate rather than drift. 45 -> 600 was ADDENDUM 248;
        45 seconds was shorter than a real battle, and when this ceiling trips the item is delivered INTO the
        fight -- the exact outcome ADDENDUM 80 built the gate to prevent."""
        self.assertEqual(600, self._timeout_literal())

    def test_the_ceiling_outlasts_the_trackers_own_self_healing_window(self) -> None:
        """The ordering that makes the ceiling a last resort rather than the primary mechanism: a genuinely
        stuck tracker heals itself in ~30s (STALE_NO_PROGRESS_POLLS) long before the caller gives up on its
        answer. ADDENDUM 248 widened the gap rather than narrowing it, but the relationship is what matters,
        so it is asserted rather than described."""
        from .. import ram_client as rc

        self.assertLess(rc.TrainerBattleDefeatTracker.STALE_NO_PROGRESS_POLLS, self._timeout_literal())

    def test_the_gate_is_polled_once_per_tick_not_once_per_item(self) -> None:
        """Calling poll() per pending item would corrupt the debounce -- documented in give_items().

        Counted over the AST, not the text: the string appears in two docstrings that describe the rule, and
        a text count would pass or fail on prose edits rather than on real call sites."""
        tree = ast.parse(self.source)
        calls = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "poll"
            and isinstance(node.func.value, ast.Attribute)
            and node.func.value.attr == "battle_state_tracker"
        ]
        self.assertEqual(1, len(calls), "the battle gate must be polled exactly once per tick")


if __name__ == "__main__":
    unittest.main()
