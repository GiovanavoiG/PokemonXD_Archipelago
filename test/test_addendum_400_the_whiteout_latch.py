"""ADDENDUM 400 (2026-10-01) -- the white-out latch: one event, two jobs.

Four problems: white-outs were not sending DeathLinks; an incoming DeathLink should kill IN battle too; dying
sends the player back to the HQ Lab and breaks story order; and a white-out needs to lock the HQ Lab's floor.

Three of those four are the same event seen from different places, so one latch serves them. The fourth
(killing IN battle) is NOT in this addendum -- see the last section.

WHY THE SEND WAS MISSING, and why ADDENDUM 390 did not fix it. 390 added the annihilation flag as a second
signal and reasoned that it "is a latch and cannot be missed between polls". The flag is a latch. The SAMPLER
was not: `DeathLinkBridge.poll` is driven from the main loop at `POLL_INTERVAL_INGAME`, which is ONE SECOND.
A white-out's whole window is the end-of-battle sequence -- `fightEncountCheckZenmetu` sets `zenmetuFlag`,
`fightEncountAnnihilationRecovery` heals the party, both inside that sequence -- and at 1 Hz the client can
sit between polls across the entire thing. 390 measured the signal and never measured the rate it was read
at, which is why the fix shipped and the symptom came back unchanged.

The signal is sampled in `fast_poll_window` now, at `POLL_INTERVAL_FAST` (0.05s), out of time the loop was
already going to spend waiting. Twenty looks a second instead of one. Two supporting changes come with it:

  * `read_annihilation_flag` takes the records array in ONE bulk read rather than `count` single-byte reads.
    64 round trips at 1 Hz is a diagnostic; at 20 Hz it is a load.
  * `fast_poll_window` no longer returns early when chests AND shops are both off. The latch is not a Death
    Link feature -- it also keeps a white-out from walking the story byte backwards -- so neither the window
    nor the latch is gated on an option.

WHY HQ LAB REGRESSED. A white-out teleports the player to the HQ Lab carrying whatever byte they had. The lab
has no `area_entry_floor` at all, and ADDENDUM 279 declines to bank a byte that merely arrived with the player
-- so the lab's own mark stays at whatever it genuinely reached, which early-game is 0x17 or lower.
`AreaStoryByteMemory.target_for` offers that mark as a candidate, `max()` picks it because it is the only
candidate, and the byte is written DOWN. A player who whited out at 0x5F comes back to 0x17.

The latch holds that one write off until the player leaves. Disarm is on LEAVING, not on a timer: they may
stand in the lab as long as they like, and the write is wrong for all of it.

WHAT IS NOT HERE: killing a received Death Link IN battle. `wipe_party` writes the OVERWORLD party struct,
which is what this project has located; XD fights out of a battle-side copy, and the address of the player's
in-battle HP has not been found. `BATTLE_ROSTER_*` is the OPPOSING trainer's roster (ADDENDUM 393), not ours.
Writing a guessed address during a battle is how you corrupt a save, so the receive path still does what it
did -- sets the overworld party to 0 HP, which lands as a white-out when the battle resolves -- and finding
the battle-side party is left as its own piece of work with its own live capture.
"""
from __future__ import annotations

import unittest

from .. import ram_client as rc


class _Latch(unittest.TestCase):
    def setUp(self) -> None:
        self.latch = rc.WhiteoutLatch()
        self._saved = rc.read_annihilation_flag
        self.flag: "bool | None" = False
        rc.read_annihilation_flag = lambda: self.flag

    def tearDown(self) -> None:
        rc.read_annihilation_flag = self._saved


class TestItArmsAndDisarms(_Latch):
    def test_it_starts_disarmed(self) -> None:
        self.assertFalse(self.latch.armed)
        self.assertEqual(0, self.latch.arms)

    def test_a_clear_flag_does_nothing(self) -> None:
        self.assertFalse(self.latch.sample())
        self.assertFalse(self.latch.armed)

    def test_an_unreadable_flag_is_not_a_white_out(self) -> None:
        """None means "I cannot see the battle state", which may not read as "you died"."""
        self.flag = None
        self.assertFalse(self.latch.sample())
        self.assertFalse(self.latch.armed)

    def test_a_set_flag_arms_it(self) -> None:
        self.flag = True
        self.assertTrue(self.latch.sample())
        self.assertTrue(self.latch.armed)
        self.assertEqual(1, self.latch.arms)

    def test_holding_the_flag_counts_as_one_white_out(self) -> None:
        """The flag is held for the whole end-of-battle sequence, which at 20 Hz is many samples."""
        self.flag = True
        for _ in range(40):
            self.latch.sample()
        self.assertEqual(1, self.latch.arms)

    def test_a_read_that_raises_is_not_a_white_out(self) -> None:
        def _boom():
            raise RuntimeError("MEM1 transiently unreadable")

        rc.read_annihilation_flag = _boom
        self.assertFalse(self.latch.sample())
        self.assertFalse(self.latch.armed)

    def test_the_flag_clearing_does_not_disarm_it(self) -> None:
        """The flag clears long before the player walks out of the lab. Disarming there would hand the floor
        write back while they are still standing in it, which is the whole bug."""
        self.flag = True
        self.latch.sample()
        self.flag = False
        self.latch.sample()
        self.assertTrue(self.latch.armed)

    def test_leaving_the_respawn_area_disarms_it(self) -> None:
        self.flag = True
        self.latch.sample()
        self.assertIsNone(self.latch.note_region("Pokemon HQ Lab"), "still in the lab")
        self.assertTrue(self.latch.armed)
        note = self.latch.note_region("Gateon Port")
        self.assertIsNotNone(note)
        self.assertFalse(self.latch.armed)

    def test_an_unknown_region_does_not_disarm_it(self) -> None:
        """None is "we could not read the room", not "they left"."""
        self.flag = True
        self.latch.sample()
        self.latch.note_region(None)
        self.assertTrue(self.latch.armed)


class TestTheFloorHold(_Latch):
    def test_it_holds_nothing_while_disarmed(self) -> None:
        self.assertFalse(self.latch.holds_floor_for("Pokemon HQ Lab"))
        self.assertEqual(0, self.latch.floor_writes_held)

    def test_it_holds_the_respawn_area_once_armed(self) -> None:
        self.flag = True
        self.latch.sample()
        self.assertTrue(self.latch.holds_floor_for("Pokemon HQ Lab"))
        self.assertEqual(1, self.latch.floor_writes_held)

    def test_it_holds_nothing_else(self) -> None:
        """A white-out must not freeze the floor of every area the player then walks through."""
        self.flag = True
        self.latch.sample()
        for region in ("Gateon Port", "Agate Village", "Phenac City", "Citadark Isle"):
            self.assertFalse(self.latch.holds_floor_for(region), region)

    def test_the_respawn_list_is_data(self) -> None:
        self.assertIn("Pokemon HQ Lab", rc.WHITEOUT_RESPAWN_REGIONS)


class TestTheAreaMemoryHonoursIt(unittest.TestCase):
    """`target_for` has to decline ABOVE the candidates, not filter them -- the mark IS the candidate here."""

    def setUp(self) -> None:
        self.memory = rc.AreaStoryByteMemory()
        self.memory.highest_by_region["Pokemon HQ Lab"] = 0x17
        self.memory.visited.add("Pokemon HQ Lab")

    def test_without_a_latch_the_mark_is_still_the_floor(self) -> None:
        self.assertEqual(0x17, self.memory.target_for("Pokemon HQ Lab"))

    def test_an_armed_latch_declines_the_write_entirely(self) -> None:
        latch = rc.WhiteoutLatch()
        latch.armed = True
        self.memory.whiteout_latch = latch
        self.assertIsNone(self.memory.target_for("Pokemon HQ Lab"),
                          "the lab's early mark must not be offered as a floor after a white-out")

    def test_a_disarmed_latch_changes_nothing(self) -> None:
        self.memory.whiteout_latch = rc.WhiteoutLatch()
        self.assertEqual(0x17, self.memory.target_for("Pokemon HQ Lab"))

    def test_other_areas_are_untouched_by_an_armed_latch(self) -> None:
        latch = rc.WhiteoutLatch()
        latch.armed = True
        self.memory.whiteout_latch = latch
        self.memory.highest_by_region["Agate Village"] = 0x20
        self.memory.visited.add("Agate Village")
        self.assertEqual(0x20, self.memory.target_for("Agate Village"))


class TestTheBridgeReadsTheLatch(unittest.TestCase):
    """The bridge's own 1 Hz read was the thing that missed. With a latch wired it asks the latch instead."""

    def setUp(self) -> None:
        self.bridge = rc.DeathLinkBridge()
        self.bridge.enabled = True
        self.latch = rc.WhiteoutLatch()
        self.bridge.whiteout_latch = self.latch
        self._party = rc.party_is_wiped
        self._flag = rc.read_annihilation_flag
        rc.party_is_wiped = lambda _b: False
        rc.read_annihilation_flag = lambda: False

    def tearDown(self) -> None:
        rc.party_is_wiped = self._party
        rc.read_annihilation_flag = self._flag

    def test_an_armed_latch_fires_a_send_even_though_the_direct_read_says_clear(self) -> None:
        """Exactly the failure seen in play: the flag has already cleared by the time the slow loop looks."""
        self.latch.armed = True
        should_send, note = self.bridge.poll(0x80000000)
        self.assertTrue(should_send)
        self.assertIn("annihilation flag", note)
        self.assertEqual(1, self.bridge.sends_by_flag)

    def test_it_sends_once_per_white_out_not_once_per_poll(self) -> None:
        self.latch.armed = True
        self.assertTrue(self.bridge.poll(0x80000000)[0])
        for _ in range(30):
            self.assertFalse(self.bridge.poll(0x80000000)[0])
        self.assertEqual(1, self.bridge.sends)

    def test_a_received_death_is_still_not_re_sent(self) -> None:
        """The loop fence has to survive the new signal, or every incoming death echoes forever."""
        rc_wipe = rc.wipe_party
        rc.wipe_party = lambda _b: 3
        try:
            self.bridge.receive(0x80000000, "tester")
        finally:
            rc.wipe_party = rc_wipe
        self.latch.armed = True
        should_send, _ = self.bridge.poll(0x80000000)
        self.assertFalse(should_send)
        self.assertEqual(1, self.bridge.suppressed)

    def test_without_a_latch_it_falls_back_to_the_direct_read(self) -> None:
        self.bridge.whiteout_latch = None
        rc.read_annihilation_flag = lambda: True
        self.assertTrue(self.bridge.poll(0x80000000)[0])


class TestTheFastWindowSamplesIt(unittest.TestCase):
    def test_the_window_opens_for_a_seed_with_chests_and_shops_off(self) -> None:
        from pathlib import Path

        source = (Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")
        window = source[source.index("async def fast_poll_window("):]
        window = window[:window.index("async def check_trainer_defeats(")]
        self.assertIn("ctx.whiteout_latch.sample()", window,
                      "the latch has to be sampled in the fast window, which is the whole fix")

    def test_the_outer_loop_samples_it_too(self) -> None:
        """The fast window is an optimisation, not the only path -- it returns early on a lost hook."""
        from pathlib import Path

        source = (Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")
        self.assertGreaterEqual(source.count("whiteout_latch.sample()"), 2)

    def test_the_disarm_runs_before_the_area_memory_poll(self) -> None:
        from pathlib import Path

        source = (Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")
        disarm = source.index("ctx.whiteout_latch.note_region(current_region)")
        poll = source.index("ctx.area_story_memory.poll(ctx.block_base, hovered_region")
        self.assertLess(disarm, poll,
                        "disarming after the poll leaves one more tick of held floor in the new area")
