"""Regression coverage for the Goal option's live auto-detection (2026-09-09, ADDENDUM 94, player request:
"detect the battle with name 'Greevil' or the 100th mt battle trainer, then upon defeat (the function we
already have) send the goal option"; extended by ADDENDUM 95, player request: "find a walkthrough that gives
the 100th trainer's name and search for it in the file, then fire goal upon defeat").

WHY THIS TEST STUBS `dolphin_memory_engine`: `ram_client.py` (the module `TrainerBattleDefeatTracker` and
`BattleRosterRecord` live in) does `import dolphin_memory_engine as dme` at module level -- that real package
isn't installable in every environment this project's tests run in (confirmed this session: not available via
this sandbox's pip index). None of what this test exercises actually calls into `dme` at all: every `poll()`
call below passes an explicit `records=` list, bypassing `scan_battle_roster()` (the sole caller of `dme.
read_bytes`) entirely -- this is pure-Python state-machine logic (HP debounce, surname bookkeeping) with zero
live-memory access, so a no-op stub is enough to satisfy the import. `sys.modules.setdefault` means a real
`dolphin_memory_engine`, if present, is used instead and never shadowed.

WHAT THIS DOES *NOT* PROVE: whether the real Mt. Battle trainer_index-1 surname really reads as "MIRU" live, or
whether Mt. Battle's 100 fights really happen back-to-back with nothing else interleaved, are real-hardware
questions (ADDENDUM 92 live-confirmed the surname once; the back-to-back assumption is still open, see
Client.py's check_trainer_defeats docstring). This test only proves that GIVEN the battle-roster records this
project's own documentation says the real signal produces, the goal-arming arithmetic in Client.py's design
(defeat_count + 99 once "MIRU" is confirmed) and the Greevil name lookup both do what they're supposed to --
the same category of "trust the documented shape, verify the code against it" coverage this project's other
synthetic-ISO tests already provide for the write side."""
from __future__ import annotations

import sys
import types

if "dolphin_memory_engine" not in sys.modules:
    _stub = types.ModuleType("dolphin_memory_engine")
    _stub.hook = lambda: None
    _stub.un_hook = lambda: None
    _stub.is_hooked = lambda: False
    _stub.read_bytes = lambda address, length: b""
    _stub.write_bytes = lambda address, data: None
    sys.modules["dolphin_memory_engine"] = _stub

import unittest

from .. import ram_client, trainer_defeat
from ..game_data.mtbattle_trainer_data import (
    MT_BATTLE_FINAL_TRAINER_SURNAME,
    MT_BATTLE_FIRST_TRAINER_SURNAME,
    MT_BATTLE_TOTAL_TRAINER_COUNT,
)


def _rec(surname: str, species: str, hp: int) -> "ram_client.BattleRosterRecord":
    return ram_client.BattleRosterRecord(address=0, trainer_name=surname, species_name=species, current_hp=hp)


def _count_name(n: int) -> str:
    return f"Defeat {n} Trainers"


class TestGreevilLocationName(unittest.TestCase):
    def test_greevil_location_name_matches_the_real_roster_entry(self) -> None:
        self.assertEqual(trainer_defeat.GREEVIL_DEFEAT_LOCATION_NAME, "Defeat - Cipher Boss Greevil")

    @staticmethod
    def _confirm_greevil_kill(tracker: "ram_client.TrainerBattleDefeatTracker", species: str) -> list[str]:
        """One full confirmed-kill sequence against surname "Greevil" (roster-clear -> nonzero baseline -> drop
        to 0 -> confirmed on a second 0 poll), returning the `completed` list from the final, confirming poll --
        mirrors _confirm_defeat elsewhere in this file, kept local since this class needs the return value."""
        tracker.poll(trainer_defeat.SURNAME_TO_LOCATION_QUEUE, _count_name, records=[])
        tracker.poll(trainer_defeat.SURNAME_TO_LOCATION_QUEUE, _count_name, records=[_rec("Greevil", species, 15)])
        pending = tracker.poll(
            trainer_defeat.SURNAME_TO_LOCATION_QUEUE, _count_name, records=[_rec("Greevil", species, 0)]
        )
        assert pending == []  # a same-poll drop-to-0 is never itself a confirmation, see the tracker's docstring
        return tracker.poll(
            trainer_defeat.SURNAME_TO_LOCATION_QUEUE, _count_name, records=[_rec("Greevil", species, 0)]
        )

    def test_first_greevil_kill_is_a_decoy_and_does_not_dispatch_the_location(self) -> None:
        """ADDENDUM 102 (player report, live-tested: "It did not goal. Also, ensure that the first battle with
        him doesn't goal - he only has one pokemon (where lugia should be). Only goal after the second
        battle."): Greevil's real battle-roster surname is identical across both of his Citadark Isle
        encounters, so the FIRST confirmed kill (the single-Pokemon decoy battle) must produce no named
        location -- only the cumulative count bucket, same as any other ordinary trainer defeat."""
        tracker = ram_client.TrainerBattleDefeatTracker()
        completed = self._confirm_greevil_kill(tracker, "Skarmory")
        self.assertNotIn(trainer_defeat.GREEVIL_DEFEAT_LOCATION_NAME, completed)
        self.assertIn(_count_name(1), completed)  # still counts toward the generic cumulative bucket
        self.assertEqual(tracker.defeat_count, 1)

    def test_second_greevil_kill_dispatches_the_real_location(self) -> None:
        tracker = ram_client.TrainerBattleDefeatTracker()
        first = self._confirm_greevil_kill(tracker, "Skarmory")  # decoy battle
        self.assertNotIn(trainer_defeat.GREEVIL_DEFEAT_LOCATION_NAME, first)
        # The decoy battle's roster must clear (poll(records=[])) before the tracker will re-arm "Greevil" for
        # a second encounter -- see TrainerBattleDefeatTracker's own "Re-arms per surname" docstring section.
        tracker.poll(trainer_defeat.SURNAME_TO_LOCATION_QUEUE, _count_name, records=[])
        second = self._confirm_greevil_kill(tracker, "Salamence")  # the real final battle
        self.assertIn(trainer_defeat.GREEVIL_DEFEAT_LOCATION_NAME, second)
        self.assertEqual(tracker.defeat_count, 2)

    def test_a_third_greevil_kill_would_not_re_dispatch_the_already_completed_location(self) -> None:
        """The real location queue is exhausted after the second kill (same as any other fully-dispatched
        surname queue) -- a hypothetical third "Greevil" kill must not re-fire it a second time."""
        tracker = ram_client.TrainerBattleDefeatTracker()
        self._confirm_greevil_kill(tracker, "Skarmory")
        tracker.poll(trainer_defeat.SURNAME_TO_LOCATION_QUEUE, _count_name, records=[])
        self._confirm_greevil_kill(tracker, "Salamence")
        tracker.poll(trainer_defeat.SURNAME_TO_LOCATION_QUEUE, _count_name, records=[])
        third = self._confirm_greevil_kill(tracker, "Salamence")
        self.assertNotIn(trainer_defeat.GREEVIL_DEFEAT_LOCATION_NAME, third)


class TestMtBattleGoalArming(unittest.TestCase):
    """Mirrors Client.py's check_trainer_defeats arming logic exactly (see that function's own ADDENDUM 94
    section): once MT_BATTLE_FIRST_TRAINER_SURNAME is seen in `tracker.last_confirmed_surnames`, the target is
    `tracker.defeat_count + (MT_BATTLE_TOTAL_TRAINER_COUNT - 1)`; the goal fires once `tracker.defeat_count`
    reaches that target."""

    @staticmethod
    def _confirm_defeat(tracker: "ram_client.TrainerBattleDefeatTracker", surname: str, species: str) -> None:
        """Runs one trainer through the tracker's full real debounce sequence (roster-clear -> nonzero baseline
        -> drop to 0 -> confirmed on a second 0 poll) so this test exercises the same state machine Client.py
        relies on, not a shortcut around it."""
        tracker.poll(trainer_defeat.SURNAME_TO_LOCATION_QUEUE, _count_name, records=[])
        tracker.poll(trainer_defeat.SURNAME_TO_LOCATION_QUEUE, _count_name, records=[_rec(surname, species, 15)])
        tracker.poll(trainer_defeat.SURNAME_TO_LOCATION_QUEUE, _count_name, records=[_rec(surname, species, 0)])
        tracker.poll(trainer_defeat.SURNAME_TO_LOCATION_QUEUE, _count_name, records=[_rec(surname, species, 0)])

    def test_first_trainer_arms_a_target_of_defeat_count_plus_99(self) -> None:
        tracker = ram_client.TrainerBattleDefeatTracker()
        self._confirm_defeat(tracker, MT_BATTLE_FIRST_TRAINER_SURNAME, "Wurmple")
        self.assertEqual(tracker.last_confirmed_surnames, [MT_BATTLE_FIRST_TRAINER_SURNAME])
        self.assertEqual(tracker.defeat_count, 1)
        target = tracker.defeat_count + (MT_BATTLE_TOTAL_TRAINER_COUNT - 1)
        self.assertEqual(target, 100)

    def test_full_hundred_trainer_sequence_reaches_the_target_exactly_at_100(self) -> None:
        tracker = ram_client.TrainerBattleDefeatTracker()
        self._confirm_defeat(tracker, MT_BATTLE_FIRST_TRAINER_SURNAME, "Wurmple")
        target = tracker.defeat_count + (MT_BATTLE_TOTAL_TRAINER_COUNT - 1)

        for i in range(2, MT_BATTLE_TOTAL_TRAINER_COUNT):  # trainers #2..#99
            self._confirm_defeat(tracker, f"T{i}", "Zubat")
            self.assertLess(tracker.defeat_count, target, f"target reached early, at trainer #{i}")

        self._confirm_defeat(tracker, "T100", "Slaking")  # the 100th and final trainer
        self.assertEqual(tracker.defeat_count, MT_BATTLE_TOTAL_TRAINER_COUNT)
        self.assertGreaterEqual(tracker.defeat_count, target)

    def test_other_trainers_before_the_first_mt_battle_trainer_do_not_arm(self) -> None:
        """A player who has already defeated ordinary Story trainers before ever setting foot in Mt. Battle
        must not accidentally arm early -- arming is keyed strictly on seeing MT_BATTLE_FIRST_TRAINER_SURNAME
        in `last_confirmed_surnames`, never on `defeat_count` alone."""
        tracker = ram_client.TrainerBattleDefeatTracker()
        self._confirm_defeat(tracker, "Eagun", "Togepi")
        self._confirm_defeat(tracker, "Lovrina", "Nuzleaf")
        self.assertEqual(tracker.defeat_count, 2)
        self.assertNotIn(MT_BATTLE_FIRST_TRAINER_SURNAME, tracker.last_confirmed_surnames)


class TestMtBattleFinalTrainerDirectDetection(unittest.TestCase):
    """ADDENDUM 95: mirrors Client.py's check_trainer_defeats direct-name signal exactly -- a confirmed defeat
    whose surname, upper-cased, equals MT_BATTLE_FINAL_TRAINER_SURNAME completes the goal immediately, with no
    dependency on the running-count arming path at all (in particular, it must fire even if MT_BATTLE_FIRST_
    TRAINER_SURNAME was never seen this session -- e.g. a client that connected mid-Mt.-Battle-run)."""

    @staticmethod
    def _confirm_defeat(tracker: "ram_client.TrainerBattleDefeatTracker", surname: str, species: str) -> None:
        tracker.poll(trainer_defeat.SURNAME_TO_LOCATION_QUEUE, _count_name, records=[])
        tracker.poll(trainer_defeat.SURNAME_TO_LOCATION_QUEUE, _count_name, records=[_rec(surname, species, 15)])
        tracker.poll(trainer_defeat.SURNAME_TO_LOCATION_QUEUE, _count_name, records=[_rec(surname, species, 0)])
        tracker.poll(trainer_defeat.SURNAME_TO_LOCATION_QUEUE, _count_name, records=[_rec(surname, species, 0)])

    def test_final_trainer_surname_confirmed_defeat_is_detected_case_insensitively(self) -> None:
        tracker = ram_client.TrainerBattleDefeatTracker()
        # The live battle-roster text's exact capitalization for this trainer is not independently confirmed
        # (see game_data/mtbattle_trainer_data.py's own comment) -- exercise a mixed-case surname to prove the
        # comparison Client.py actually uses (case-insensitive) is what this test covers, not an exact-match
        # shortcut that would only work by coincidence.
        mixed_case_surname = MT_BATTLE_FINAL_TRAINER_SURNAME.capitalize()
        self._confirm_defeat(tracker, mixed_case_surname, "Slaking")
        confirmed_upper = {s.strip().upper() for s in tracker.last_confirmed_surnames}
        self.assertIn(MT_BATTLE_FINAL_TRAINER_SURNAME, confirmed_upper)

    def test_final_trainer_fires_without_ever_seeing_the_first_trainer_this_session(self) -> None:
        """A client that connects mid-run (MIRU was fought in an earlier session, never this one) must still
        detect the real 100th-trainer win directly -- this signal must not depend on the arming path at all."""
        tracker = ram_client.TrainerBattleDefeatTracker()
        self._confirm_defeat(tracker, "SomeOtherTrainer", "Zubat")  # some ordinary mid-run trainer, not MIRU
        self.assertNotIn(MT_BATTLE_FIRST_TRAINER_SURNAME, tracker.last_confirmed_surnames)
        self._confirm_defeat(tracker, MT_BATTLE_FINAL_TRAINER_SURNAME, "Slaking")
        confirmed_upper = {s.strip().upper() for s in tracker.last_confirmed_surnames}
        self.assertIn(MT_BATTLE_FINAL_TRAINER_SURNAME, confirmed_upper)


if __name__ == "__main__":
    unittest.main()
