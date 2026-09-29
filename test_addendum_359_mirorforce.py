"""ADDENDUM 359 (2026-09-25): !mirorforce.

Player: "wire in a command called !mirorforce that takes an argument. example: '!mirorforce pyrite' would
put him in pyrite. do the same for realgam, oasis, rock, and cave."

WHAT IT ACTS ON. ADDENDUM 358 decompiled `underTakerCallBackFunc` and then watched a whole cycle live. The
force is a change of RULE, not of counter: the step threshold (cfg+0x00) to 1 so every step rolls, the hit
weight (cfg+0x02) up to the modulus (cfg+0x06) so every roll is a hit, and every place weight but the
target's to 0 so the weighted pick can only land there. Those are u16s in a config struct loaded from disc
-- RAM, not save data -- and they are put back as soon as he appears.

THE ONE THING IT MUST NEVER DO is write the accumulator in a loop. Flag 1449 is bits 9..24 of word 49;
flag 1450 (signal) is bits 25..28 of THE SAME WORD and 1451 (stay timer) starts at bit 29. A flag write is
a read-modify-write of the whole word, so holding the accumulator reverts any signal change the game made
in between -- the exact value the force is waiting on. An earlier attempt did that at 10Hz and froze the
game. `test_the_accumulator_is_never_written` is that, as an assertion.
"""
from __future__ import annotations

import pathlib
import re
import struct
import unittest
from unittest import mock

from .. import ram_client as rc


ROOT = pathlib.Path(__file__).resolve().parent.parent
CLIENT = (ROOT / "Client.py").read_text(encoding="utf-8")

# The descriptors measured live on the player's save (ADDENDUM 358).
DESCRIPTORS = {1191: (1, 1144), 1415: (1, 1535), 1449: (16, 1577), 1450: (4, 1593),
               1451: (16, 1597), 1452: (16, 1613), 964: (12, 917)}
DESC_TABLE, GROUP_TABLE, STORAGE, CFG = 0x80100000, 0x80200000, 0x80300000, 0x80400000
GROUP_SIZE = 384
PLACE_TABLE = [(3, 119), (3, 58), (1, 90), (1, 91), (1, 92), (1, 163), (0, 162)]


class FakeMem:
    """A MEM1 that answers the pointer chain, so the real code runs unmodified."""

    def __init__(self):
        self.mem = {}
        self.writes = []          # set up FIRST: every helper below records into it
        self.w32(rc.GS_DESCRIPTOR_PTR, DESC_TABLE)
        self.w32(rc.GS_GROUP_TABLE_PTR, GROUP_TABLE)
        self.w32(rc.MIROR_DATA_PTR, CFG)
        # entries are 8 bytes and the selector is a BYTE OFFSET: 24 is entry 3.
        self.w32(GROUP_TABLE + 24, GROUP_SIZE)
        self.w32(GROUP_TABLE + 24 + 4, STORAGE)
        for fid, (width, bitpos) in DESCRIPTORS.items():
            self.mem[DESC_TABLE + fid * 6] = (width & 0x3F) | (0x18 << 3)
            self.mem[DESC_TABLE + fid * 6 + 1] = 0
            self.w16(DESC_TABLE + fid * 6 + 2, bitpos)
        for off, value in ((0x00, 100), (0x02, 16), (0x04, 8), (0x06, 32), (0x08, 10), (0x0A, 1000)):
            self.w16(CFG + off, value)
        for name, off in rc.MIROR_FLAG_OFFS.items():
            self.w32(CFG + off, {"start": 1191, "accumulator": 1449, "signal": 1450,
                                 "place": 1452, "timer": 1451, "suppress": 1415}[name])
        self.w32(CFG + 0x28, 72); self.w32(CFG + 0x2C, 80)
        for i, (weight, pid) in enumerate(PLACE_TABLE):
            rec = CFG + rc.MIROR_PLACE_TABLE_OFF + i * rc.MIROR_PLACE_STRIDE
            self.w16(rec, weight); self.w16(rec + 2, pid)
        for fid, value in ((1191, 1), (1415, 0), (1449, 40), (1450, 5), (1451, 0), (1452, 0), (964, 760)):
            self.set_flag(fid, value)
        self.writes = []

    def read(self, address, length):
        return bytes(self.mem.get(address + i, 0) for i in range(length))

    def write(self, address, data):
        self.writes.append((address, bytes(data)))
        for i, b in enumerate(data):
            self.mem[address + i] = b

    def w32(self, a, v): self.write(a, struct.pack(">I", v))
    def w16(self, a, v): self.write(a, struct.pack(">H", v))
    def r16(self, a): return struct.unpack(">H", self.read(a, 2))[0]

    def set_flag(self, fid, value):
        width, bitpos = DESCRIPTORS[fid]
        word, off = bitpos >> 5, bitpos & 31
        both = (struct.unpack(">I", self.read(STORAGE + word * 4 + 4, 4))[0] << 32) \
            | struct.unpack(">I", self.read(STORAGE + word * 4, 4))[0]
        both = (both & ~(((1 << width) - 1) << off)) | (value << off)
        self.write(STORAGE + word * 4, struct.pack(">I", both & 0xFFFFFFFF))
        self.write(STORAGE + word * 4 + 4, struct.pack(">I", (both >> 32) & 0xFFFFFFFF))

    def __enter__(self):
        self._patch = mock.patch.multiple(rc, read_bytes=self.read, write_bytes=self.write)
        self._patch.start()
        self.writes = []
        return self

    def __exit__(self, *exc):
        self._patch.stop()


class TestTheFlagReader(unittest.TestCase):
    """The lookup that was wrong for most of ADDENDUM 358 and produced a screen of confident nonsense."""

    def test_the_selector_is_a_byte_offset_not_an_index(self):
        with FakeMem():
            self.assertEqual((1, 1144, STORAGE), rc._gs_descriptor(1191))

    def test_a_flag_that_does_not_fit_its_group_is_refused(self):
        """The one-line guard that turns this failure into an error instead of a garbage read."""
        with FakeMem() as m:
            m.w32(GROUP_TABLE + 24, 100)          # 800 bits, but flag 1764 lives at bit 1956
            self.assertIsNone(rc._gs_descriptor(1452))

    def test_a_storage_pointer_outside_mem1_is_refused(self):
        with FakeMem() as m:
            m.w32(GROUP_TABLE + 24 + 4, 0)
            self.assertIsNone(rc._gs_descriptor(1191))
            self.assertIsNone(rc.gs_flag_get(1191))

    def test_reads_and_writes_round_trip_including_the_straddling_fields(self):
        with FakeMem():
            for fid in (1191, 1415, 1449, 1450, 1451, 1452, 964):
                width = DESCRIPTORS[fid][0]
                for value in (0, 1, (1 << width) - 1, ((1 << width) - 1) // 3):
                    self.assertTrue(rc.gs_flag_set(fid, value), fid)
                    self.assertEqual(value, rc.gs_flag_get(fid), fid)

    def test_a_write_touches_only_the_words_the_field_occupies(self):
        """The freeze, as an assertion. 1449 is bits 9..24 of word 49; writing it must not rewrite word 50,
        which carries 1452 (place) among everything else in bits 1600..1631."""
        with FakeMem() as m:
            for fid in (1449, 1450, 1452, 1191):
                width, bitpos = DESCRIPTORS[fid]
                word, off = bitpos >> 5, bitpos & 31
                m.writes = []
                rc.gs_flag_set(fid, 1)
                touched = {a for a, _ in m.writes if a >= STORAGE}
                expected = {STORAGE + word * 4}
                if off + width > 32:
                    expected.add(STORAGE + (word + 1) * 4)
                self.assertEqual(expected, touched, f"flag {fid}")

    def test_a_value_too_wide_for_the_field_is_refused_rather_than_truncated(self):
        with FakeMem():
            self.assertFalse(rc.gs_flag_set(1450, 16))     # 4 bits
            self.assertEqual(5, rc.gs_flag_get(1450))      # unchanged


class TestArming(unittest.TestCase):
    def test_the_five_names_are_exactly_what_was_asked_for(self):
        self.assertEqual({"pyrite", "realgam", "rock", "oasis", "cave"}, set(rc.MIROR_PLACE_IDS))

    def test_gateon_is_not_offered_because_its_weight_is_zero(self):
        """Offering it would be offering something the game's own weighted pick can never choose."""
        self.assertNotIn(162, {pid for pid, _ in rc.MIROR_PLACE_IDS.values()})
        self.assertEqual(0, dict((pid, w) for w, pid in PLACE_TABLE)[162])

    def test_arming_rewrites_the_rules_not_the_counter(self):
        with FakeMem() as m:
            force = rc.MirorForce()
            ok, message = force.arm("pyrite")
            self.assertTrue(ok, message)
            self.assertEqual(1, m.r16(CFG + rc.MIROR_THRESHOLD_OFF), "every step must roll")
            self.assertEqual(m.r16(CFG + rc.MIROR_MODULUS_OFF), m.r16(CFG + rc.MIROR_HIT_OFF),
                             "every roll must be a hit")
            self.assertEqual(8, rc.gs_flag_get(1450), "signal one below the spawn level of 9")
            for i, (weight, pid) in enumerate(PLACE_TABLE):
                rec = CFG + rc.MIROR_PLACE_TABLE_OFF + i * rc.MIROR_PLACE_STRIDE
                # the target keeps its own weight; every other weight goes to 0 so the pick must land
                self.assertEqual(weight if pid == 119 else 0, m.r16(rec), pid)

    def test_the_accumulator_is_never_written_while_armed(self):
        """THE FREEZE, stated precisely. 1449 shares word 49 with the signal (bits 25..28) and the stay
        timer (from bit 29), so a flag write is a read-modify-write of all three. Holding it in a loop
        reverts whatever the game just did to its neighbours -- which is the value the force is waiting on.

        NARROWED by ADDENDUM 359a: the ban is on writing it WHILE ARMED. `restore` makes exactly one write,
        once, to undo an underflow the game's own double-read of the threshold causes -- that is a
        single-shot repair on the way out, not a loop racing the game."""
        with FakeMem() as m:
            before = rc.gs_flag_get(1449)
            force = rc.MirorForce()
            force.arm("cave")
            writes_during_arm = [a for a, _ in m.writes if a >= STORAGE]
            m.writes = []
            for _ in range(20):
                force.poll()
            self.assertEqual([], [a for a, _ in m.writes if a >= STORAGE],
                             "poll must not write save data at all while it is waiting")
            self.assertEqual(before, rc.gs_flag_get(1449))
        # And arming touches the signal's word only for the signal, never for the accumulator's own sake.
        self.assertTrue(writes_during_arm, "arming does write the signal")

    def test_the_only_accumulator_write_is_the_underflow_repair(self):
        source = (ROOT / "ram_client.py").read_text(encoding="utf-8")
        body = source[source.index("class MirorForce"):]
        self.assertEqual(1, body.count('gs_flag_set(ids["accumulator"]'),
                         "exactly one accumulator write, in restore()")
        self.assertIn("def restore", body[:body.index('gs_flag_set(ids["accumulator"]')])

    def test_it_refuses_when_the_start_flag_is_clear(self):
        with FakeMem() as m:
            m.set_flag(1191, 0)
            ok, message = rc.MirorForce().arm("pyrite")
            self.assertFalse(ok)
            self.assertIn("first-Miror-B.-fight", message)

    def test_it_refuses_when_he_is_already_out(self):
        with FakeMem() as m:
            m.set_flag(1452, 119)
            ok, message = rc.MirorForce().arm("cave")
            self.assertFalse(ok)
            self.assertIn("already out", message)

    def test_it_clears_suppress_because_that_is_gate_two(self):
        with FakeMem() as m:
            m.set_flag(1415, 1)
            self.assertTrue(rc.MirorForce().arm("rock")[0])
            self.assertEqual(0, rc.gs_flag_get(1415))

    def test_arming_twice_does_not_stack_and_lose_the_originals(self):
        with FakeMem() as m:
            force = rc.MirorForce()
            force.arm("pyrite")
            force.arm("cave")
            force.restore()
            self.assertEqual(100, m.r16(CFG + rc.MIROR_THRESHOLD_OFF))
            self.assertEqual(16, m.r16(CFG + rc.MIROR_HIT_OFF))
            for i, (weight, _) in enumerate(PLACE_TABLE):
                rec = CFG + rc.MIROR_PLACE_TABLE_OFF + i * rc.MIROR_PLACE_STRIDE
                self.assertEqual(weight, m.r16(rec))


class TestTheRestoreRace(unittest.TestCase):
    """ADDENDUM 359a, measured live: an accumulator of 65449 after a force.

    The callback reads the threshold TWICE -- 0x80295C90 to decide whether to roll, 0x80295DA4 to subtract
    it. Restoring 100 between those two makes the game subtract 100 from a value that only had to beat 1,
    and the field is unsigned 16-bit, so it wraps to ~65449 and then rolls on every step for 650 of them."""

    def test_an_underflowed_accumulator_is_cleared_on_restore(self):
        with FakeMem() as m:
            force = rc.MirorForce()
            self.assertTrue(force.arm("pyrite")[0])
            m.set_flag(1449, 65449)                 # what the race leaves behind
            force.restore()
            self.assertEqual(0, rc.gs_flag_get(1449))
            self.assertEqual(100, m.r16(CFG + rc.MIROR_THRESHOLD_OFF))

    def test_an_ordinary_accumulator_is_left_alone(self):
        """Below the threshold it is honest progress toward the next roll, and throwing it away would cost
        the player walking they had already done."""
        with FakeMem() as m:
            force = rc.MirorForce()
            force.arm("cave")
            m.set_flag(1449, 40)
            force.restore()
            self.assertEqual(40, rc.gs_flag_get(1449))

    def test_restore_without_an_arm_touches_nothing(self):
        with FakeMem() as m:
            m.writes = []
            rc.MirorForce().restore()
            self.assertEqual([], m.writes)


class TestResolving(unittest.TestCase):
    def test_the_appearance_restores_everything(self):
        with FakeMem() as m:
            force = rc.MirorForce()
            force.arm("pyrite")
            self.assertIsNone(force.poll())
            m.set_flag(1452, 119)                      # the GAME places him
            message = force.poll()
            self.assertIn("Pyrite Colosseum", message)
            self.assertFalse(force.active)
            self.assertEqual(100, m.r16(CFG + rc.MIROR_THRESHOLD_OFF))
            self.assertEqual(16, m.r16(CFG + rc.MIROR_HIT_OFF))
            for i, (weight, _) in enumerate(PLACE_TABLE):
                self.assertEqual(weight, m.r16(CFG + rc.MIROR_PLACE_TABLE_OFF + i * 8))

    def test_it_reports_where_he_actually_landed_not_where_we_asked(self):
        """The validation in `_appearMirabo` can reject the pick and fall back, so the target is a request
        rather than a guarantee. Saying 'Pyrite' when he went to a Poke Spot would be a lie."""
        with FakeMem() as m:
            force = rc.MirorForce()
            force.arm("pyrite")
            m.set_flag(1452, 92)
            self.assertIn("place id 92", force.poll())

    def test_the_timeout_names_the_gate_that_refused(self):
        """A timeout that says "something blocked it" is a shrug. With the roll guaranteed, the signal is
        a witness: at the spawn level the SPAWN was refused; below it the callback never rolled."""
        cases = [
            ({"suppress": 1}, "suppress flag is set"),
            ({"start": 0}, "first-fight flag"),
            ({"signal": 9}, "SPAWN was refused"),
            ({"signal": 8}, "never moved off"),
        ]
        for overrides, expected in cases:
            with self.subTest(overrides=overrides), FakeMem() as m:
                force = rc.MirorForce()
                self.assertTrue(force.arm("cave")[0])
                for fid, value in (("suppress", 1415), ("start", 1191), ("signal", 1450)):
                    if fid in overrides:
                        m.set_flag(value, overrides[fid])
                force.armed_at -= rc.MIROR_FORCE_TIMEOUT + 1
                message = force.poll()
                self.assertIn(expected, message, overrides)
                self.assertFalse(force.active)
                self.assertEqual(100, m.r16(CFG + rc.MIROR_THRESHOLD_OFF), "restored regardless")
                self.assertEqual(16, m.r16(CFG + rc.MIROR_HIT_OFF), "restored regardless")

    def test_polling_an_unarmed_force_does_nothing_at_all(self):
        with FakeMem() as m:
            m.writes = []
            self.assertIsNone(rc.MirorForce().poll())
            self.assertEqual([], m.writes)

    def test_an_unreadable_tick_holds_rather_than_restoring(self):
        """A bad read is 'ask again next poll', not 'give up' -- ADDENDUM 226/267's standing rule."""
        with FakeMem() as m:
            force = rc.MirorForce()
            force.arm("oasis")
            m.w32(rc.MIROR_DATA_PTR, 0)
            self.assertIsNone(force.poll())
            self.assertTrue(force.active)


class TestTheClientWiring(unittest.TestCase):
    """Structural -- `Client.py` is not importable here."""

    def test_the_command_exists_and_takes_an_argument(self):
        self.assertIn('def _cmd_mirorforce(self, place: str = "") -> None:', CLIENT)

    def test_the_context_owns_one(self):
        self.assertIn("self.miror_force = ram_client.MirorForce()", CLIENT)

    def test_the_poll_loop_ticks_it_and_cannot_be_broken_by_it(self):
        start = CLIENT.index("_miror = ctx.miror_force.poll()")
        body = CLIENT[start - 400:start + 900]
        self.assertIn("try:", body)
        self.assertIn("except Exception:", body)

    def test_it_never_sends_a_check_or_writes_the_story_byte(self):
        """Cosmetic debug commands must never be able to cost a check -- the standing rule."""
        body = CLIENT[CLIENT.index("def _cmd_mirorforce"):CLIENT.index("def _cmd_unlocks")]
        for forbidden in ("_send_checks", "check_locations", "poke_story_byte", "write_story_byte"):
            self.assertNotIn(forbidden, body, forbidden)


if __name__ == "__main__":
    unittest.main()
