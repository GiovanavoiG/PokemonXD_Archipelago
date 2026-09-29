"""ADDENDUM 390 (2026-09-28) -- Death Link sends on the game's own annihilation flag, not a window nobody measured.

Player: "Is deathlink functioning? got reports that we weren't SENDING deathlinks at all" -- then, on being
offered a money-based white-out fingerprint: "Wouldn't this fail if we have no money? Can we base it off of the
actual whiteout code that runs that we found before?"

Right on both counts. `fightEncountAnnihilationRecovery` calls `heroDecPokedoru(maxPartyLevel * 16)` and that
CLAMPS, so a broke player produces no money signature at all. And the real function has a better signal in it.

WHAT WAS ACTUALLY WRONG. Every other link in the chain checks out -- the option reaches slot data, the client
arms the DeathLink tag, `send_death` is CommonContext's own, the poll runs every tick, `read_party` reads the
live `Pokemon` objects rather than the display cache, a fainted member still counts as occupied, and an
unreadable party returns None rather than False. The send was edge-triggered on OBSERVING the party at all-zero
HP, and ADDENDUM 351 asserted that "a party sits at zero HP for the whole of a losing battle's end sequence"
without ever capturing it. A white-out heals the party in the same sequence that ends the battle, so that
window may simply not exist to be seen.

THE SIGNAL, READ OUT OF THE WHITE-OUT ITSELF. `fightEncountCheckZenmetu` (0x801F0D9C) guards on three things
and the second is a latch:

    encounter = fightGetEncountData(...)     # 0x801F19CC
    if encounter->zenmetuFlag: return        # 0x801F16B8

Both accessors are short enough to read whole, and they resolve against this project's own measured SDA base:

    0x801F19CC   lwz r4, -29856(r13)  /  lwz r0, 0(r4)  /  mulli r0, r3, 60  /  lwz r3, -29852(r13)
    0x801F16B8   lbz r3, 4(r3)

That the function refuses to run again while the flag is set is what proves it PERSISTS -- so unlike the HP
window it cannot be missed between polls.

ALSO FIXED, found while reading:

  * `receive()` set `_ours` BEFORE checking whether it had wiped anything, so a death arriving while the party
    was already down latched the loop fence with no wipe behind it, suppressing the next genuine white-out.
  * `describe()` was dead code -- nothing called it. `sends` sat at zero with no way for a player to report a
    number, which is exactly why this arrived as "we weren't sending at all". `!deathlink` calls it now.

Flag 803 was considered and rejected: `GSflagOff(803)` is in the white-out, but a DOL-wide search for
`li r3,803` finds it cleared in six places and set in one, so it is battle state and not a white-out marker.
"""
from __future__ import annotations

import pathlib
import unittest

from .. import ram_client as rc


class TestTheAddressesComeFromTheDisassembly(unittest.TestCase):
    def test_the_two_pointers_are_the_sda_displacements(self) -> None:
        self.assertEqual(rc.MIROR_SDA_BASE - 29856, rc.ENCOUNTER_COUNT_PTR)
        self.assertEqual(rc.MIROR_SDA_BASE - 29852, rc.ENCOUNTER_RECORDS_PTR)
        self.assertEqual(0x804E8980, rc.ENCOUNTER_COUNT_PTR)
        self.assertEqual(0x804E8984, rc.ENCOUNTER_RECORDS_PTR)

    def test_the_record_shape_is_the_one_the_accessors_use(self) -> None:
        self.assertEqual(60, rc.ENCOUNTER_RECORD_STRIDE, "mulli r0, r3, 60")
        self.assertEqual(0x04, rc.ENCOUNTER_ZENMETU_FLAG_OFFSET, "lbz r3, 4(r3)")


class TestTheFlagReadRefusesRatherThanGuessing(unittest.TestCase):
    """None, never False. "I cannot see the battle state" must not read as "you are fine" any more than it may
    read as "you died" -- the same rule `party_is_wiped` already follows."""

    def setUp(self) -> None:
        self.saved = rc.read_bytes
        self.mem: "dict[int, bytes]" = {}
        rc.read_bytes = lambda address, length: self.mem.get(
            address, b"\x00" * length)[:length].ljust(length, b"\x00")

    def tearDown(self) -> None:
        rc.read_bytes = self.saved

    def _u32(self, address: int, value: int) -> None:
        self.mem[address] = value.to_bytes(4, "big")

    def test_uninitialised_pointers_give_no_answer(self) -> None:
        self.assertIsNone(rc.read_annihilation_flag())

    def test_a_records_pointer_outside_mem1_gives_no_answer(self) -> None:
        self._u32(rc.ENCOUNTER_COUNT_PTR, 0x80500000)
        self._u32(0x80500000, 4)
        self._u32(rc.ENCOUNTER_RECORDS_PTR, 0x00001234)
        self.assertIsNone(rc.read_annihilation_flag())

    def test_an_implausible_count_gives_no_answer(self) -> None:
        self._u32(rc.ENCOUNTER_COUNT_PTR, 0x80500000)
        self._u32(0x80500000, 999999)
        self._u32(rc.ENCOUNTER_RECORDS_PTR, 0x80600000)
        self.assertIsNone(rc.read_annihilation_flag())

    def _sane_tables(self, count: int = 4, records: int = 0x80600000) -> int:
        self._u32(rc.ENCOUNTER_COUNT_PTR, 0x80500000)
        self._u32(0x80500000, count)
        self._u32(rc.ENCOUNTER_RECORDS_PTR, records)
        return records

    def test_all_clear_reads_false(self) -> None:
        self._sane_tables()
        self.assertIs(False, rc.read_annihilation_flag())

    def test_a_set_flag_on_any_record_reads_true(self) -> None:
        records = self._sane_tables(count=4)
        for index in range(4):
            self.setUp()
            records = self._sane_tables(count=4)
            self.mem[records + index * rc.ENCOUNTER_RECORD_STRIDE
                     + rc.ENCOUNTER_ZENMETU_FLAG_OFFSET] = b"\x01"
            self.assertIs(True, rc.read_annihilation_flag(), f"record {index}")

    def test_it_reads_the_flag_field_and_not_its_neighbours(self) -> None:
        records = self._sane_tables(count=1)
        for offset in (0x00, 0x01, 0x02, 0x03, 0x05, 0x06):
            self.mem[records + offset] = b"\xFF"
        self.assertIs(False, rc.read_annihilation_flag(),
                      "only +0x04 is the annihilation flag")


class _Bridge(unittest.TestCase):
    """Drives `DeathLinkBridge.poll` with both signals under test control."""

    def setUp(self) -> None:
        self.saved = (rc.party_is_wiped, rc.read_annihilation_flag, rc.wipe_party)
        self.wiped: "bool | None" = False
        self.flag: "bool | None" = False
        self.wrote = 1
        rc.party_is_wiped = lambda block_base: self.wiped
        rc.read_annihilation_flag = lambda: self.flag
        rc.wipe_party = lambda block_base: self.wrote
        self.bridge = rc.DeathLinkBridge()
        self.bridge.enabled = True

    def tearDown(self) -> None:
        rc.party_is_wiped, rc.read_annihilation_flag, rc.wipe_party = self.saved

    def poll(self):
        return self.bridge.poll(0x80000000)


class TestTheFlagSendsADeath(_Bridge):
    def test_a_white_out_the_hp_window_never_showed_still_sends(self) -> None:
        """The reported bug, as a test: the party is never observed at zero, and a death goes out anyway."""
        self.wiped = False
        self.flag = True
        should_send, note = self.poll()
        self.assertTrue(should_send)
        self.assertIn("annihilation flag", note or "")
        self.assertEqual(1, self.bridge.sends_by_flag)
        self.assertEqual(0, self.bridge.sends_by_hp)

    def test_it_is_edge_triggered_because_the_flag_is_a_latch(self) -> None:
        self.flag = True
        self.assertTrue(self.poll()[0])
        for _ in range(10):
            self.assertFalse(self.poll()[0], "a latch held for many polls must be one death")
        self.assertEqual(1, self.bridge.sends)

    def test_it_re_arms_once_the_white_out_is_over(self) -> None:
        self.flag = True
        self.assertTrue(self.poll()[0])
        self.flag = False
        self.poll()
        self.flag = True
        self.assertTrue(self.poll()[0], "a second white-out is a second death")
        self.assertEqual(2, self.bridge.sends)

    def test_the_hp_edge_still_works_on_its_own(self) -> None:
        """Kept deliberately: if the flag is wrong on some build, this degrades to the old behaviour rather
        than to nothing."""
        self.flag = False
        self.wiped = True
        should_send, note = self.poll()
        self.assertTrue(should_send)
        self.assertEqual(1, self.bridge.sends_by_hp)
        self.assertIn("0 HP", note or "")

    def test_both_signals_at_once_are_one_death(self) -> None:
        self.wiped = True
        self.flag = True
        self.assertTrue(self.poll()[0])
        self.assertFalse(self.poll()[0])
        self.assertEqual(1, self.bridge.sends)

    def test_no_answer_from_either_sends_nothing(self) -> None:
        self.wiped = None
        self.flag = None
        for _ in range(5):
            self.assertFalse(self.poll()[0])
        self.assertEqual(0, self.bridge.sends)

    def test_an_unreadable_party_does_not_release_the_fence(self) -> None:
        """`wiped is None` while the flag is still set is "no answer", and must not look like recovery."""
        self.flag = True
        self.assertTrue(self.poll()[0])
        self.wiped = None
        self.poll()
        self.assertFalse(self.poll()[0], "the same white-out must not fire twice")


class TestTheLoopFence(_Bridge):
    def test_a_received_death_is_not_rebroadcast(self) -> None:
        self.bridge.receive(0x80000000, "someone else died")
        self.wiped = True
        self.flag = True
        self.assertFalse(self.poll()[0])
        self.assertEqual(1, self.bridge.suppressed)
        self.assertEqual(0, self.bridge.sends)

    def test_the_fence_comes_down_when_both_signals_clear(self) -> None:
        self.bridge.receive(0x80000000)
        self.wiped = True
        self.flag = True
        self.poll()
        self.wiped = False
        self.flag = False
        self.poll()
        self.wiped = True
        self.flag = True
        self.assertTrue(self.poll()[0], "a later real white-out must still send")

    def test_a_receive_that_wiped_nothing_does_not_latch_the_fence(self) -> None:
        """The bug: `_ours` was set before checking `written`, so a death arriving while the party was already
        down fenced a white-out that had nothing to do with it."""
        self.wrote = 0
        self.bridge.receive(0x80000000)
        self.wiped = True
        self.flag = True
        should_send, _note = self.poll()
        self.assertTrue(should_send, "nothing was wiped, so there is nothing of ours to fence")
        self.assertEqual(0, self.bridge.suppressed)

    def test_a_receive_that_did_wipe_still_fences(self) -> None:
        self.wrote = 3
        self.bridge.receive(0x80000000)
        self.wiped = True
        self.flag = True
        self.assertFalse(self.poll()[0])


class TestItIsObservable(unittest.TestCase):
    def test_describe_names_both_signals(self) -> None:
        bridge = rc.DeathLinkBridge()
        bridge.enabled = True
        text = bridge.describe()
        self.assertIn("annihilation flag", text)
        self.assertIn("0 HP", text)

    def test_it_says_when_the_flag_cannot_be_read(self) -> None:
        bridge = rc.DeathLinkBridge()
        bridge.enabled = True
        bridge.flag_readable = False
        self.assertIn("NOT readable", bridge.describe())

    def test_off_says_off(self) -> None:
        self.assertIn("off for this seed", rc.DeathLinkBridge().describe())

    def test_a_command_finally_calls_it(self) -> None:
        """It existed since ADDENDUM 351 and nothing reached it, which is why `sends == 0` was invisible."""
        source = (pathlib.Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")
        self.assertIn("def _cmd_deathlink(", source)
        self.assertIn("death_link_bridge.describe()", source)

    def test_the_command_reports_the_flag_too(self) -> None:
        source = (pathlib.Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")
        start = source.index("def _cmd_deathlink(")
        body = source[start:start + 2000]
        self.assertIn("read_annihilation_flag()", body)


if __name__ == "__main__":
    unittest.main()
