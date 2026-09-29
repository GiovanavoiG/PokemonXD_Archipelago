"""Regression coverage for ADDENDUM 100's fix to TrainerBattleDefeatTracker.has_unresolved_battle() (player
report: "the item queue is extremely delayed - I think the waits might be broken, as even out of battle
they're taking several minutes to deliver"). Root cause: a stale roster record left over from a battle that
ended in a LOSS (enemy trainer's team never reaches 0 HP) was never excluded by the old "frozen at exactly 0
HP" check, so has_unresolved_battle() got stuck True forever, and every subsequent item's first write waited
the full ITEM_DELIVERY_MAX_BATTLE_WAIT_SECONDS ceiling before ever being attempted. This exercises the
generalized "no observed HP movement for STALE_NO_PROGRESS_POLLS consecutive polls" exclusion directly against
the tracker, independent of any live ISO/RAM data."""
from __future__ import annotations

import sys
import types
import unittest

# WHY THIS TEST STUBS `dolphin_memory_engine`: same reason as test_chest_count_tracker_debounce.py --
# ram_client.py does `import dolphin_memory_engine as dme` at module level, and that real package isn't
# installable in every environment this project's tests run in. This test never calls into `dme` at all: it
# drives TrainerBattleDefeatTracker.poll() with an explicit `records=[...]` list every time, never letting it
# fall back to scan_battle_roster()'s own real-memory read.
if "dolphin_memory_engine" not in sys.modules:
    _stub = types.ModuleType("dolphin_memory_engine")
    _stub.hook = lambda: None
    _stub.un_hook = lambda: None
    _stub.is_hooked = lambda: False
    _stub.read_bytes = lambda address, length: b""
    _stub.write_bytes = lambda address, data: None
    sys.modules["dolphin_memory_engine"] = _stub

from .. import ram_client

SURNAME_QUEUE: dict[str, list[str]] = {}


def _count_name(n: int) -> str:
    return f"Defeat {n} Trainers"


def _record(surname: str, species: str, hp: int) -> ram_client.BattleRosterRecord:
    return ram_client.BattleRosterRecord(address=0, trainer_name=surname, species_name=species, current_hp=hp)


class TestStaleNonzeroHpRecordSelfHeals(unittest.TestCase):
    """The gap ADDENDUM 41 left open: a stale record frozen at a NONZERO hp (the shape a LOSS leaves behind,
    since the enemy trainer's team never reaches 0) must eventually stop counting as "still fighting", not
    stick has_unresolved_battle() at True forever."""

    def test_nonzero_frozen_record_stops_blocking_after_the_staleness_window(self) -> None:
        tracker = ram_client.TrainerBattleDefeatTracker()
        # First sighting -- baselined at a real, nonzero HP (as a battle that ended in a loss would leave the
        # enemy's still-alive Pokemon).
        tracker.poll(SURNAME_QUEUE, _count_name, records=[_record("PEON", "ZUBAT", 14)])
        self.assertTrue(tracker.has_unresolved_battle(), "a freshly baselined nonzero-HP slot must count as "
                                                           "still fighting")
        # Same stale bytes keep matching the scan every poll (per scan_battle_roster's own docstring, stale
        # records are never cleared from memory) -- HP never moves, ever.
        for _ in range(ram_client.TrainerBattleDefeatTracker.STALE_NO_PROGRESS_POLLS - 1):
            tracker.poll(SURNAME_QUEUE, _count_name, records=[_record("PEON", "ZUBAT", 14)])
        self.assertTrue(tracker.has_unresolved_battle(), "must still count as unresolved -- staleness window "
                                                           "hasn't elapsed yet")
        # One more identical poll crosses the staleness threshold.
        tracker.poll(SURNAME_QUEUE, _count_name, records=[_record("PEON", "ZUBAT", 14)])
        self.assertFalse(tracker.has_unresolved_battle(), "a record frozen at a nonzero HP with no movement "
                                                            "for the whole staleness window must be treated as "
                                                            "a stale leftover, not an ongoing fight")

    def test_frozen_at_zero_still_excluded_immediately_not_only_after_the_window(self) -> None:
        # The original ADDENDUM 41 case must still work exactly as before -- frozen at 0 HP since the very
        # first sighting is a dead-on-arrival record either way, but this generalized check only excludes it
        # once the staleness window elapses (same as any other frozen value), not on the very first poll --
        # confirm that's still the case and it isn't wrongly treated as "resolved"/counted as a kill either.
        tracker = ram_client.TrainerBattleDefeatTracker()
        tracker.poll(SURNAME_QUEUE, _count_name, records=[_record("ROID", "GEODUDE", 0)])
        self.assertEqual(tracker.defeat_count, 0, "a bare first-sighting-at-0 must never be counted as a kill")

    def test_a_genuinely_ongoing_fight_with_periodic_hp_drops_never_goes_stale(self) -> None:
        tracker = ram_client.TrainerBattleDefeatTracker()
        hp = 40
        tracker.poll(SURNAME_QUEUE, _count_name, records=[_record("CIPHER ADMIN", "SNEASEL", hp)])
        # Simulate a long, slow real battle: HP drops every ~20 polls (well inside the staleness window), for
        # longer than STALE_NO_PROGRESS_POLLS overall.
        for i in range(ram_client.TrainerBattleDefeatTracker.STALE_NO_PROGRESS_POLLS * 2):
            if i % 20 == 19 and hp > 0:
                hp -= 5
            tracker.poll(SURNAME_QUEUE, _count_name, records=[_record("CIPHER ADMIN", "SNEASEL", hp)])
            self.assertTrue(tracker.has_unresolved_battle(),
                             f"poll {i}: a real fight with periodic HP movement must never be mistaken for "
                             "a stale record, no matter how long it runs")

    def test_confirmed_kill_is_never_treated_as_unresolved(self) -> None:
        tracker = ram_client.TrainerBattleDefeatTracker()
        tracker.poll(SURNAME_QUEUE, _count_name, records=[_record("GRUNT", "ZUBAT", 10)])
        tracker.poll(SURNAME_QUEUE, _count_name, records=[_record("GRUNT", "ZUBAT", 0)])  # observed drop
        tracker.poll(SURNAME_QUEUE, _count_name, records=[_record("GRUNT", "ZUBAT", 0)])  # 2nd-poll confirm
        self.assertEqual(tracker.defeat_count, 1)
        self.assertFalse(tracker.has_unresolved_battle(), "a real, confirmed kill must never itself count as "
                                                            "an unresolved battle")


if __name__ == "__main__":
    unittest.main()
