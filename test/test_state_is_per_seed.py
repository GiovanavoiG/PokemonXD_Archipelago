"""A client that switches seed or slot in one run starts that seed's ledgers clean."""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from .. import Client
from .. import ram_client as rc


def _context(path: str) -> "Client.PokemonXDContext":
    ctx = object.__new__(Client.PokemonXDContext)
    ctx._local_state_loaded_for = None
    ctx.purification_tracker = rc.PurificationCountTracker()
    ctx.trainer_defeat_tracker = rc.TrainerBattleDefeatTracker()
    ctx.species_catch_tracker = rc.SpeciesCatchTracker()
    ctx.krane_memo_tracker = rc.KraneMemoTracker()
    ctx._shadow_monitor_last = set()
    ctx.music_disc_hold = rc.MusicDiscStoryHold()
    ctx.machine_part_hold = rc.MachinePartStoryHold()
    ctx.lab_memo_hold = rc.LabMemoStoryHold()
    ctx.story_byte_override = rc.StoryByteOverride()
    ctx._always_open_gate_latched = False
    ctx._state_file_path = lambda: path
    return ctx


class TestASecondSeedStartsClean(unittest.TestCase):
    def test_purifications_from_another_seed_do_not_block_this_ones(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            ctx = _context(os.path.join(folder, "state.json"))
            ctx.seed_name, ctx.slot = "A", 1
            ctx._load_local_state()
            ctx.purification_tracker.observe_monitor(set(range(1, 30)))
            ctx.krane_memo_tracker.awarded = {1, 2, 3}
            ctx.lab_memo_hold.lab_reached = True
            with mock.patch.object(Client, "_note_warn", lambda *a, **k: None):
                ctx._save_local_state()

                ctx.seed_name = "B"
                ctx._load_local_state()
                self.assertEqual(0, ctx.purification_tracker.total_purified)
                self.assertFalse(ctx.purification_tracker.purified_shadow_ids)
                self.assertFalse(ctx.krane_memo_tracker.awarded)
                self.assertFalse(ctx.lab_memo_hold.lab_reached)
                crossed = ctx.purification_tracker.observe_monitor(set(range(1, 31)))
                self.assertEqual(30, len(crossed))

                ctx.seed_name = "A"
                ctx._load_local_state()
                self.assertEqual(29, ctx.purification_tracker.total_purified)

    def test_reconnecting_to_the_same_seed_keeps_the_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            ctx = _context(os.path.join(folder, "state.json"))
            ctx.seed_name, ctx.slot = "A", 1
            ctx._load_local_state()
            ctx.purification_tracker.observe_monitor({1, 2, 3})
            ctx._load_local_state()
            self.assertEqual(3, ctx.purification_tracker.total_purified)


class TestCountsTheServerNeverGot(unittest.TestCase):
    def test_every_count_without_a_checked_location_is_sent_again(self) -> None:
        from types import SimpleNamespace

        tracker = rc.PurificationCountTracker()
        tracker.total_purified = 30
        ids = {n: Client.LOCATION_NAME_TO_ID[rc.purification_location_name(n)] for n in range(1, 31)}
        ctx = SimpleNamespace(purification_tracker=tracker, checked_locations={ids[1]}, pending_check_ids={ids[2]})
        missing = Client.purification_counts_not_sent(ctx)
        self.assertEqual([rc.purification_location_name(n) for n in range(3, 31)], missing)

    def test_it_runs_in_check_purifications(self) -> None:
        import inspect

        body = inspect.getsource(Client.check_purifications)
        self.assertIn("purification_counts_not_sent(ctx)", body)


if __name__ == "__main__":
    unittest.main()
