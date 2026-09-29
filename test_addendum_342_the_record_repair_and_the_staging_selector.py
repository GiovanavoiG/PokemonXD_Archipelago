"""ADDENDUM 342 (2026-09-25): the freeze was save data, and the Wakin patches are retracted.

ADDENDUM 341 shipped two script patches and then a third attempt, all built to explain a hard freeze on the
fade to black after Gonzap. All of them were aimed at the wrong thing.

Six MEM1 dumps settled it. The very first frozen dump has instr 355 at `10 00 00 ea` and instr 439 at
`0b 00 02 97` -- BOTH STOCK -- so Wakin was not in that run at all, and it froze at the same fade with the
same script-VM state as every other freeze. What separated freeze from no-freeze was story record
`+0x37..+0x84`:

    both runs that completed:   00 00 08 00 00 00 00 00 | ff x14 | 00 x56
    all four freezes:           ff x78

Six for six, independent of which script bytes were patched. That range was filled with 0xFF by this
project's own live bit-bisection and never restored.

WHAT THIS FILE GUARDS. The repair is a write into SAVE DATA, which is the most dangerous thing in this
module, so the tests below are mostly about what it must REFUSE to do: it writes only over the exact damaged
pattern, only inside the hideout, only once, and never a byte outside its own 78-byte window. The staging
selector gets the same treatment -- the two arrangements must be mutually exclusive, because writing both
would leave `preprocess` with a retargeted branch AND a replaced line marker.
"""
from __future__ import annotations

import os
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

from .. import ram_client

FIXTURE = Path(__file__).with_name("data_addendum_341_snagem_2f_script.bin")
SCRIPT = FIXTURE.read_bytes()
BLOCK = 0x80479120          # where the save block sat in the dumps; the code must not depend on this


class _FakeBlock:
    """A sparse stand-in for the save block, recording every write."""

    def __init__(self, window: bytes, base: int = BLOCK, size: int = 0x1800000):
        self.base = base
        self.cells = bytearray(size)
        start = base + ram_client.SNAGEM_RECORD_FIX_OFFSET - ram_client.MEM1_START
        self.cells[start:start + len(window)] = window
        self.writes: "list[tuple[int, bytes]]" = []

    def read_bytes(self, address: int, length: int) -> bytes:
        start = address - ram_client.MEM1_START
        if start < 0 or start + length > len(self.cells):
            raise IndexError(address)
        return bytes(self.cells[start:start + length])

    def write_bytes(self, address: int, data: bytes) -> None:
        self.writes.append((address, bytes(data)))
        start = address - ram_client.MEM1_START
        self.cells[start:start + len(data)] = data

    def install(self, test: unittest.TestCase) -> None:
        dme = sys.modules["dolphin_memory_engine"]
        for name in ("read_bytes", "write_bytes"):
            test.addCleanup(setattr, dme, name, getattr(dme, name))
        dme.read_bytes = self.read_bytes
        dme.write_bytes = self.write_bytes


def _clear_env(test: unittest.TestCase) -> None:
    for key in ("POKEMON_XD_SNAGEM_STAGE", "POKEMON_XD_SNAGEM_REPAIR"):
        test.addCleanup(os.environ.pop, key, None)
        os.environ.pop(key, None)


def _force_repair(test: unittest.TestCase) -> None:
    """ADDENDUM 350 turned the repair OFF by default -- the freeze it was written for turned out to be the
    Snagem floor sitting on 0x63, a byte with no story value behind it, and a wholesale 0x4E-byte write over
    save data is not something to run unasked on saves that were never damaged.

    The machinery below is still correct and still reachable with POKEMON_XD_SNAGEM_REPAIR=1, so these tests
    switch it on rather than being deleted. `TestTheRepairIsOffByDefault` is what pins the default."""
    _clear_env(test)
    os.environ["POKEMON_XD_SNAGEM_REPAIR"] = "1"


class TestTheRepairIsOffByDefault(unittest.TestCase):
    """ADDENDUM 350. The one thing in this file that changed."""

    def setUp(self):
        _clear_env(self)

    def test_the_flag_is_off(self):
        self.assertFalse(ram_client.SNAGEM_RECORD_REPAIR)
        self.assertFalse(ram_client.snagem_record_repair_enabled())

    def test_a_damaged_window_is_left_alone_unless_asked(self):
        mem = _FakeBlock(ram_client.SNAGEM_RECORD_DAMAGED); mem.install(self)
        self.assertEqual(ram_client.snagem_record_state(BLOCK), "damaged",
                         "premise: this window really does look damaged")
        self.assertFalse(ram_client.repair_snagem_record(BLOCK))
        self.assertEqual(mem.writes, [])

    def test_it_can_still_be_asked_for(self):
        mem = _FakeBlock(ram_client.SNAGEM_RECORD_DAMAGED); mem.install(self)
        os.environ["POKEMON_XD_SNAGEM_REPAIR"] = "1"
        self.assertTrue(ram_client.snagem_record_repair_enabled())
        self.assertTrue(ram_client.repair_snagem_record(BLOCK))

    def test_the_staging_selector_is_off_too(self):
        """Same reason: with the story variable written in full, the game reaches Gonzap's scene through its
        own `preprocess` and picks the arrangement its own flags call for."""
        self.assertIsNone(ram_client.SNAGEM_2F_STAGE)
        self.assertIsNone(ram_client.snagem_2f_stage())
        os.environ["POKEMON_XD_SNAGEM_STAGE"] = "a"
        self.assertEqual("a", ram_client.snagem_2f_stage())


class TestTheRepairedWindowMatchesTheDumps(unittest.TestCase):
    def test_it_is_the_pattern_from_both_runs_that_completed(self):
        self.assertEqual(ram_client.SNAGEM_RECORD_FIX_BYTES.hex(),
                         "0000080000000000" + "ff" * 14 + "00" * 56)

    def test_it_covers_exactly_plus_0x37_through_plus_0x84(self):
        self.assertEqual(len(ram_client.SNAGEM_RECORD_FIX_BYTES), 0x4E)
        self.assertEqual(ram_client.SNAGEM_RECORD_FIX_OFFSET,
                         ram_client.STORY_RECORD_OFFSET + 0x37)

    def test_the_damaged_pattern_is_the_same_length_and_all_ff(self):
        self.assertEqual(len(ram_client.SNAGEM_RECORD_DAMAGED),
                         len(ram_client.SNAGEM_RECORD_FIX_BYTES))
        self.assertEqual(set(ram_client.SNAGEM_RECORD_DAMAGED), {0xFF})

    def test_damaged_and_repaired_are_not_the_same(self):
        self.assertNotEqual(ram_client.SNAGEM_RECORD_DAMAGED, ram_client.SNAGEM_RECORD_FIX_BYTES)


class TestTheRepairRefusesMoreThanItAccepts(unittest.TestCase):
    def setUp(self):
        _force_repair(self)

    def test_it_repairs_the_exact_damaged_pattern(self):
        mem = _FakeBlock(ram_client.SNAGEM_RECORD_DAMAGED); mem.install(self)
        self.assertEqual(ram_client.snagem_record_state(BLOCK), "damaged")
        self.assertTrue(ram_client.repair_snagem_record(BLOCK))
        self.assertEqual(ram_client.snagem_record_state(BLOCK), "repaired")

    def test_it_writes_one_block_at_one_address_and_nothing_else(self):
        mem = _FakeBlock(ram_client.SNAGEM_RECORD_DAMAGED); mem.install(self)
        ram_client.repair_snagem_record(BLOCK)
        self.assertEqual(len(mem.writes), 1)
        address, data = mem.writes[0]
        self.assertEqual(address, BLOCK + ram_client.SNAGEM_RECORD_FIX_OFFSET)
        self.assertEqual(data, ram_client.SNAGEM_RECORD_FIX_BYTES)

    def test_an_already_repaired_window_is_left_alone(self):
        mem = _FakeBlock(ram_client.SNAGEM_RECORD_FIX_BYTES); mem.install(self)
        self.assertFalse(ram_client.repair_snagem_record(BLOCK))
        self.assertEqual(mem.writes, [])

    def test_anything_that_is_neither_pattern_is_left_alone(self):
        """The whole point. A window that is neither damaged nor repaired is somebody's real save."""
        for label, window in (
            ("one byte short of damaged", b"\xff" * 77 + b"\x00"),
            ("one byte short of repaired", ram_client.SNAGEM_RECORD_FIX_BYTES[:-1] + b"\x01"),
            ("all zeroes", bytes(len(ram_client.SNAGEM_RECORD_FIX_BYTES))),
            ("plausible progress", bytes(range(len(ram_client.SNAGEM_RECORD_FIX_BYTES)))),
        ):
            with self.subTest(window=label):
                mem = _FakeBlock(window); mem.install(self)
                self.assertIsNone(ram_client.snagem_record_state(BLOCK))
                self.assertFalse(ram_client.repair_snagem_record(BLOCK))
                self.assertEqual(mem.writes, [])

    def test_the_repair_can_be_switched_off_without_a_rebuild(self):
        mem = _FakeBlock(ram_client.SNAGEM_RECORD_DAMAGED); mem.install(self)
        os.environ["POKEMON_XD_SNAGEM_REPAIR"] = "0"
        self.assertFalse(ram_client.snagem_record_repair_enabled())
        self.assertFalse(ram_client.repair_snagem_record(BLOCK))
        self.assertEqual(mem.writes, [])

    def test_unreadable_memory_reports_none_rather_than_raising(self):
        dme = sys.modules["dolphin_memory_engine"]
        self.addCleanup(setattr, dme, "read_bytes", dme.read_bytes)

        def boom(address, length):
            raise RuntimeError("not hooked")

        dme.read_bytes = boom
        self.assertIsNone(ram_client.snagem_record_state(BLOCK))
        self.assertFalse(ram_client.repair_snagem_record(BLOCK))


class TestTheRepairIsScopedToTheHideout(unittest.TestCase):
    def setUp(self):
        _force_repair(self)

    def _room(self):
        return sorted(ram_client.SNAGEM_ROOM_IDS)[0]

    def test_it_does_not_fire_outside_the_hideout(self):
        mem = _FakeBlock(ram_client.SNAGEM_RECORD_DAMAGED); mem.install(self)
        patcher = ram_client.SnagemScriptPatcher()
        patcher.poll(BLOCK, 1)
        patcher.poll(BLOCK, None)
        self.assertEqual(mem.writes, [])
        self.assertFalse(patcher.repaired)

    def test_it_fires_once_inside_and_not_again(self):
        mem = _FakeBlock(ram_client.SNAGEM_RECORD_DAMAGED); mem.install(self)
        self.addCleanup(setattr, ram_client, "dump_mem1", ram_client.dump_mem1)
        ram_client.dump_mem1 = lambda: bytes(mem.cells)
        patcher = ram_client.SnagemScriptPatcher()
        note = patcher.poll(BLOCK, self._room())
        self.assertIsNotNone(note)
        self.assertIn("record", note)
        self.assertTrue(patcher.repaired)
        before = len(mem.writes)
        patcher.poll(BLOCK, self._room())
        self.assertEqual(len(mem.writes), before, "it must not rewrite the window every tick")

    def test_a_missing_block_base_is_survived(self):
        mem = _FakeBlock(ram_client.SNAGEM_RECORD_DAMAGED); mem.install(self)
        self.addCleanup(setattr, ram_client, "dump_mem1", ram_client.dump_mem1)
        ram_client.dump_mem1 = lambda: bytes(mem.cells)
        patcher = ram_client.SnagemScriptPatcher()
        patcher.poll(None, self._room())
        self.assertEqual(mem.writes, [])


class TestTheStagingSelector(unittest.TestCase):
    def setUp(self):
        _clear_env(self)

    def test_there_are_exactly_two_arrangements(self):
        self.assertEqual(set(ram_client.SNAGEM_2F_STAGE_PATCHES), {"a", "b"})

    def test_selecting_one_stage_actively_restores_the_other(self):
        """Both stages must always appear in the patch list -- the unselected one with patched == stock, so
        switching stages puts the other site back rather than leaving two overlapping edits in the script."""
        for stage in ("a", "b"):
            with self.subTest(stage=stage):
                os.environ["POKEMON_XD_SNAGEM_STAGE"] = stage
                patches = ram_client.snagem_2f_patches()
                active = {o for o, e, p in patches if p != e}
                for offset, _e, _p in ram_client.SNAGEM_2F_STAGE_PATCHES[stage]:
                    self.assertIn(offset, active)
                other = "b" if stage == "a" else "a"
                for offset, expected, _p in ram_client.SNAGEM_2F_STAGE_PATCHES[other]:
                    self.assertNotIn(offset, active)
                    self.assertIn((offset, expected, expected), patches)

    def test_no_stage_selected_leaves_preprocess_entirely_alone(self):
        os.environ["POKEMON_XD_SNAGEM_STAGE"] = "off"
        self.assertIsNone(ram_client.snagem_2f_stage())
        active = {o for o, e, p in ram_client.snagem_2f_patches() if p != e}
        for stage in ram_client.SNAGEM_2F_STAGE_PATCHES.values():
            for offset, _e, _p in stage:
                self.assertNotIn(offset, active)

    def test_an_unrecognised_override_means_leave_alone_rather_than_crash(self):
        os.environ["POKEMON_XD_SNAGEM_STAGE"] = "banana"
        self.assertIsNone(ram_client.snagem_2f_stage())

    def test_every_stage_site_holds_its_stock_byte_in_the_real_script(self):
        for stage, patches in ram_client.SNAGEM_2F_STAGE_PATCHES.items():
            for offset, expected, patched in patches:
                with self.subTest(stage=stage, offset=hex(offset)):
                    self.assertEqual(SCRIPT[offset], expected)
                    self.assertNotEqual(expected, patched, "a stage patch that changes nothing is a bug")

    def test_the_stage_sites_are_the_instructions_the_addendum_names(self):
        self.assertEqual(ram_client.SNAGEM_2F_STAGE_PATCHES["a"][0][0], ram_client._instr(158) + 3)
        self.assertEqual({o for o, _e, _p in ram_client.SNAGEM_2F_STAGE_PATCHES["b"]},
                         {ram_client._instr(159), ram_client._instr(159) + 3})

    def test_forcing_a_retargets_the_jumpif_to_the_next_instruction(self):
        """159 is instr 158's own fall-through, so the branch becomes a no-op that still pops its condition."""
        offset, _expected, patched = ram_client.SNAGEM_2F_STAGE_PATCHES["a"][0]
        self.assertEqual(SCRIPT[offset - 3:offset], b"\x0b\x00\x00")
        self.assertEqual(patched, 159)

    def test_forcing_b_turns_a_line_marker_into_a_jump_to_200(self):
        """A line marker is debug-only and has no stack effect, so replacing it whole is safe."""
        self.assertEqual(SCRIPT[ram_client._instr(159):ram_client._instr(159) + 4], b"\x10\x00\x00\x7a")
        by_offset = dict((o, p) for o, _e, p in ram_client.SNAGEM_2F_STAGE_PATCHES["b"])
        self.assertEqual(by_offset[ram_client._instr(159)], 0x0C)       # JUMP
        self.assertEqual(by_offset[ram_client._instr(159) + 3], 200)    # -> instr 200


class TestTheRetraction(unittest.TestCase):
    def setUp(self):
        _clear_env(self)

    def test_the_story_gate_is_the_only_unconditional_patch(self):
        self.assertEqual(ram_client.SNAGEM_2F_SCRIPT_PATCHES,
                         ((ram_client._instr(321) + 3, 0x67, 0x42),))

    def test_instr_439_is_no_longer_forced(self):
        """ADDENDUM 341's `0x0B -> 0x0C`. It left a value on the VM stack and did not stop the freeze."""
        sites = {o for o, _e, _p in ram_client.snagem_2f_patches()}
        self.assertNotIn(ram_client._instr(439), sites)
        self.assertIn((ram_client._instr(439), b"\x0b\x00\x02\x97"),
                      ram_client.SNAGEM_2F_SCRIPT_ANCHORS,
                      "left alone means it can be anchored whole now")

    def test_instr_355_is_no_longer_overwritten(self):
        """The follow-up that called yachino_battle from hero_main. With the record repaired, gonza_battle
        reaches yachino_battle by itself at instr 664 -- doing both made Wakin fight twice."""
        sites = {o for o, _e, _p in ram_client.snagem_2f_patches()}
        for byte in range(4):
            self.assertNotIn(ram_client._instr(355) + byte, sites)

    def test_the_three_scriptcalls_that_define_the_encounter_are_anchored(self):
        anchors = dict(ram_client.SNAGEM_2F_SCRIPT_ANCHORS)
        self.assertEqual(anchors[ram_client._instr(356)], b"\x07\x00\x01\x73")   # -> gonza_battle
        self.assertEqual(anchors[ram_client._instr(358)], b"\x07\x00\x05\x9a")   # -> snatch_put
        self.assertEqual(anchors[ram_client._instr(664)], b"\x07\x00\x04\x20")   # -> yachino_battle

    def test_those_scriptcalls_really_are_in_the_fixture(self):
        for index, expected in ((356, b"\x07\x00\x01\x73"),
                                (358, b"\x07\x00\x05\x9a"),
                                (664, b"\x07\x00\x04\x20")):
            at = ram_client._instr(index)
            self.assertEqual(SCRIPT[at:at + 4], expected, index)


if __name__ == "__main__":
    unittest.main()


class TestAddendum343TheStop(unittest.TestCase):
    """The patch has to come back out, and the stop has to survive a reload.

    `hero_main` is a polling loop whose last instruction jumps to its own top. Vanilla ends the encounter by
    advancing the story variable (instr 2104 of `snatch_put` is `CALL 0x83(800, 964)`), which makes the gate
    at instr 321 false. While that gate is patched the vanilla stop cannot fire, so the fight restarts on
    every tick the player stands in the zone -- which is exactly what the player reported. The client has to
    do the stop itself.
    """

    def setUp(self):
        _clear_env(self)
        self.script_mem = None

    def _room(self):
        return sorted(ram_client.SNAGEM_ROOM_IDS)[0]

    def _install_script(self, script: bytes, snag_owned: bool):
        """A memory image holding the script AND a save block whose Snag Machine sites agree."""
        cells = bytearray(0x1800000)
        blob = 0x8099E160
        start = blob - ram_client.MEM1_START
        cells[start:start + len(script)] = script
        flag = ram_client.SNAG_MACHINE_FLAG_BIT if snag_owned else 0x00
        record = ram_client.SNAG_MACHINE_RECORD_BIT if snag_owned else 0x00
        cells[BLOCK + ram_client.SNAG_MACHINE_FLAG_OFFSET - ram_client.MEM1_START] = flag
        cells[BLOCK + ram_client.STORY_RECORD_OFFSET
              + ram_client.SNAG_MACHINE_RECORD_BYTE_OFFSET - ram_client.MEM1_START] = record

        writes: "list[tuple[int, bytes]]" = []

        def read_bytes(address, length):
            i = address - ram_client.MEM1_START
            if i < 0 or i + length > len(cells):
                raise IndexError(address)
            return bytes(cells[i:i + length])

        def write_bytes(address, data):
            writes.append((address, bytes(data)))
            i = address - ram_client.MEM1_START
            cells[i:i + len(data)] = data

        dme = sys.modules["dolphin_memory_engine"]
        for name in ("read_bytes", "write_bytes"):
            self.addCleanup(setattr, dme, name, getattr(dme, name))
        dme.read_bytes = read_bytes
        dme.write_bytes = write_bytes
        self.addCleanup(setattr, ram_client, "dump_mem1", ram_client.dump_mem1)
        ram_client.dump_mem1 = lambda: bytes(cells)
        return blob, cells, writes

    def _clean_script(self) -> bytes:
        out = bytearray(SCRIPT)
        for offset, expected, _patched in ram_client.snagem_2f_patches():
            out[offset] = expected
        return bytes(out)

    def test_it_patches_while_the_scene_is_still_to_come(self):
        blob, cells, _w = self._install_script(self._clean_script(), snag_owned=False)
        patcher = ram_client.SnagemScriptPatcher()
        self.assertFalse(patcher.finished(BLOCK))
        self.assertIsNotNone(patcher.poll(BLOCK, self._room()))
        for offset, _e, patched in ram_client.snagem_2f_patches():
            self.assertEqual(cells[blob + offset - ram_client.MEM1_START], patched, hex(offset))

    def test_owning_the_snag_machine_stops_it_and_restores_every_byte(self):
        """The reload-proof half: the Snag Machine is what `snatch_put` grants, read from the save."""
        blob, cells, _w = self._install_script(self._clean_script(), snag_owned=False)
        patcher = ram_client.SnagemScriptPatcher()
        patcher.poll(BLOCK, self._room())
        # the scene happens: snatch_put hands over the Snag Machine
        cells[BLOCK + ram_client.SNAG_MACHINE_FLAG_OFFSET
              - ram_client.MEM1_START] = ram_client.SNAG_MACHINE_FLAG_BIT
        cells[BLOCK + ram_client.STORY_RECORD_OFFSET + ram_client.SNAG_MACHINE_RECORD_BYTE_OFFSET
              - ram_client.MEM1_START] = ram_client.SNAG_MACHINE_RECORD_BIT
        note = patcher.poll(BLOCK, self._room())
        self.assertIsNotNone(note)
        self.assertIn("restored to stock", note)
        for offset, expected, _p in ram_client.snagem_2f_patches():
            self.assertEqual(cells[blob + offset - ram_client.MEM1_START], expected, hex(offset))

    def test_a_beaten_gonzap_stops_it_without_waiting_for_the_item(self):
        """The live half, which arrives before `snatch_put` does."""
        blob, cells, _w = self._install_script(self._clean_script(), snag_owned=False)
        patcher = ram_client.SnagemScriptPatcher()
        patcher.poll(BLOCK, self._room())
        note = patcher.poll(BLOCK, self._room(), {"gonzap"})
        self.assertIsNotNone(note)
        self.assertIn("restored to stock", note)
        gate = ram_client.SNAGEM_2F_SCRIPT_PATCHES[0]
        self.assertEqual(cells[blob + gate[0] - ram_client.MEM1_START], gate[1])

    def test_the_surname_latch_is_sticky(self):
        """The tracker reports a surname on exactly one poll, so a single sighting has to be enough."""
        self._install_script(self._clean_script(), snag_owned=False)
        patcher = ram_client.SnagemScriptPatcher()
        patcher.poll(BLOCK, self._room(), {"GONZAP"})
        self.assertTrue(patcher.gonzap_seen)
        patcher.poll(BLOCK, self._room(), set())
        self.assertTrue(patcher.gonzap_seen, "one sighting must not be forgotten on the next tick")

    def test_an_unrelated_surname_does_not_stop_it(self):
        self._install_script(self._clean_script(), snag_owned=False)
        patcher = ram_client.SnagemScriptPatcher()
        patcher.poll(BLOCK, self._room(), {"SMARTON", "WAKIN"})
        self.assertFalse(patcher.gonzap_seen)
        self.assertFalse(patcher.finished(BLOCK))

    def test_it_never_re_patches_after_a_reload(self):
        """A fresh patcher, a freshly loaded script, and a save that already owns the Snag Machine."""
        blob, cells, writes = self._install_script(self._clean_script(), snag_owned=True)
        patcher = ram_client.SnagemScriptPatcher()
        for _ in range(5):
            patcher.poll(BLOCK, self._room())
        gate = ram_client.SNAGEM_2F_SCRIPT_PATCHES[0]
        self.assertEqual(cells[blob + gate[0] - ram_client.MEM1_START], gate[1])
        self.assertEqual(patcher.applications, 0)
        self.assertEqual([a for a, _d in writes], [], "a finished scene must not be written to at all")

    def test_restoring_is_announced_once_not_every_tick(self):
        self._install_script(self._clean_script(), snag_owned=False)
        patcher = ram_client.SnagemScriptPatcher()
        patcher.poll(BLOCK, self._room())
        first = patcher.poll(BLOCK, self._room(), {"GONZAP"})
        self.assertIsNotNone(first)
        for _ in range(3):
            self.assertIsNone(patcher.poll(BLOCK, self._room()))

    def test_a_disagreeing_snag_machine_read_is_not_a_stop(self):
        """`read_snag_machine` returns None when its two sites disagree. A "do not know" must not strand the
        player mid-scene with the gate already removed."""
        blob, cells, _w = self._install_script(self._clean_script(), snag_owned=False)
        cells[BLOCK + ram_client.SNAG_MACHINE_FLAG_OFFSET
              - ram_client.MEM1_START] = ram_client.SNAG_MACHINE_FLAG_BIT
        self.assertIsNone(ram_client.read_snag_machine(BLOCK))
        self.assertFalse(ram_client.snagem_scene_completed(BLOCK))
        patcher = ram_client.SnagemScriptPatcher()
        self.assertFalse(patcher.finished(BLOCK))

    def test_the_force_override_keeps_it_patching_for_a_re_test(self):
        blob, cells, _w = self._install_script(self._clean_script(), snag_owned=True)
        os.environ["POKEMON_XD_SNAGEM_FORCE"] = "1"
        patcher = ram_client.SnagemScriptPatcher()
        self.assertFalse(patcher.finished(BLOCK))
        self.assertIsNotNone(patcher.poll(BLOCK, self._room()))
        gate = ram_client.SNAGEM_2F_SCRIPT_PATCHES[0]
        self.assertEqual(cells[blob + gate[0] - ram_client.MEM1_START], gate[2])

    def test_restore_refuses_a_blob_that_fails_the_anchors(self):
        broken = bytearray(self._clean_script())
        broken[0x0270] = 0x00
        blob, cells, writes = self._install_script(bytes(broken), snag_owned=True)
        self.assertIsNone(ram_client.restore_snagem_2f_script(blob))
        self.assertEqual(writes, [])

    def test_describe_says_which_state_it_is_in(self):
        self._install_script(self._clean_script(), snag_owned=False)
        patcher = ram_client.SnagemScriptPatcher()
        self.assertIn("armed", patcher.describe())
        patcher.poll(BLOCK, self._room())
        patcher.poll(BLOCK, self._room(), {"GONZAP"})
        self.assertIn("stopped", patcher.describe())

    def test_the_client_hands_over_the_confirmed_surnames(self):
        source = (Path(__file__).resolve().parents[1] / "Client.py").read_text(encoding="utf-8")
        self.assertIn("last_confirmed_surnames", source)
        self.assertIn("snagem_script_patcher.poll(ctx.block_base, room_id, confirmed_surnames)", source)
