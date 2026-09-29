"""ADDENDUM 341 (2026-09-25): the Snagem 2F script gates the fight, so the client patches the script.

ADDENDUM 337 fenced Wakin and Gonzap on the theory that the Snag Machine was the blocker. It was not.
Decompiling `S2_building_2F_2`'s bytecode showed the encounter never reads the per-area story byte at all:

    hero_main (a POLLING LOOP -- its last instruction jumps back to its own top):
        if NOT(story >= 790):                        exit     <- a global story variable
        call snatchdan_battle_check
        CALL 0x19(player, 17.0, 130.0, 14.0, 99.0)            a position test
        if result == 1:                              exit
        set_flag(2280,1) ; set_flag(2279,0)
        call gonza_battle:
            if flag(1293) == <value>:  -> yachino_battle (WAKIN) then Gonzap
            else:                      -> Gonzap alone at CALL 0x11, instr 660

Neither operand is reachable: the story variable is nowhere in MEM1 as an integer holding a ladder value
(searched every width, endianness, alignment, fixed and block-relative, across seven dumps), and `CALL 0x84`
returns a multi-bit value rather than a boolean -- the flag-1293 branch was tested live against 0 and against
1 and was false both times. Removing the Snag Machine, which ADDENDUM 340 made possible, changed nothing.

So the client patches two bytes of the loaded script. Both confirmed in play: Wakin fights, then Gonzap.

WHAT THIS FILE GUARDS, and the fixture it uses. `data_addendum_341_snagem_2f_script.bin` is the RESIDENT
script lifted byte-for-byte out of a real MEM1 dump taken standing in the room -- not the disc copy, which
differs (the loader relocates the FTBL name pointers). So the anchors are tested against what the client will
actually see, and a change that only works against the disc bytes fails here.

THE ANCHORS ARE THE POINT. Writing into a map script on a guessed address is how this project would corrupt a
save, so `looks_like_snagem_2f_script` must reject everything that is not this exact script, and the patch
must refuse to write when it does.
"""
from __future__ import annotations

import struct
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
BLOB = 0x8099E160          # where it sat in the dump; the code must not depend on this


def _clean(script: bytes = SCRIPT) -> bytes:
    """The fixture with every patch site forced back to its stock byte.

    The dump this fixture came from already had the story gate patched, so "a clean script" has to be
    constructed rather than assumed -- otherwise the write-count assertions below silently test nothing."""
    out = bytearray(script)
    for offset, expected, _patched in ram_client.snagem_2f_patches():
        out[offset] = expected
    return bytes(out)


CLEAN = _clean()


def _writes_expected() -> int:
    return sum(1 for _o, e, p in ram_client.snagem_2f_patches() if p != e)


class _FakeMem:
    """MEM1-shaped sparse memory holding the real script at `base`, recording every write."""

    def __init__(self, base: int = BLOB, script: bytes = SCRIPT, size: int = 0x1800000):
        self.base = base
        self.size = size
        self.cells = bytearray(size)
        self.cells[base - ram_client.MEM1_START: base - ram_client.MEM1_START + len(script)] = script
        self.writes: "list[tuple[int, bytes]]" = []

    def dump(self) -> bytes:
        return bytes(self.cells)

    def read_bytes(self, address: int, length: int) -> bytes:
        start = address - ram_client.MEM1_START
        if start < 0 or start + length > self.size:
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


class TestTheFixtureIsTheRealThing(unittest.TestCase):
    def test_it_is_a_tcod_container_of_the_right_size(self):
        self.assertEqual(SCRIPT[:4], b"TCOD")
        self.assertEqual(struct.unpack_from(">I", SCRIPT, 4)[0], ram_client.SNAGEM_2F_SCRIPT_SIZE)
        self.assertEqual(len(SCRIPT), ram_client.SNAGEM_2F_SCRIPT_SIZE)

    def test_every_patch_site_currently_holds_a_value_the_patch_recognises(self):
        for offset, expected, patched in ram_client.snagem_2f_patches():
            self.assertIn(SCRIPT[offset], (expected, patched), hex(offset))


class TestAnchors(unittest.TestCase):
    def _read(self, base=BLOB, script=SCRIPT):
        def read(address, length):
            start = address - base
            if start < 0 or start + length > len(script):
                raise IndexError(address)
            return script[start:start + length]
        return read

    def test_the_real_script_passes_every_anchor(self):
        self.assertTrue(ram_client.looks_like_snagem_2f_script(self._read(), BLOB))

    def test_there_are_several_independent_anchors(self):
        """One anchor is a coincidence waiting to happen. Container, sections and instructions."""
        offsets = {o for o, _ in ram_client.SNAGEM_2F_SCRIPT_ANCHORS}
        self.assertGreaterEqual(len(offsets), 10)
        self.assertIn(0x0000, offsets)      # container magic
        self.assertIn(0x0270, offsets)      # the CODE section tag
        self.assertIn(0x0790, offsets)      # an instruction beside the story gate
        self.assertIn(0x0968, offsets)      # an instruction beside the Wakin branch

    def test_no_anchor_covers_a_byte_the_patch_writes(self):
        """An anchor over a patched byte would make the patch un-re-verifiable after it is applied."""
        patched = {offset for offset, _e, _p in ram_client.SNAGEM_2F_SCRIPT_PATCHES}
        for stage in ram_client.SNAGEM_2F_STAGE_PATCHES:
            patched |= {offset for offset, _e, _p in ram_client.SNAGEM_2F_STAGE_PATCHES[stage]}
        for offset, expected in ram_client.SNAGEM_2F_SCRIPT_ANCHORS:
            for i in range(len(expected)):
                self.assertNotIn(offset + i, patched, f"anchor at {hex(offset)} covers a patch site")

    def test_the_anchors_still_hold_after_the_patch_is_applied(self):
        patched = bytearray(SCRIPT)
        for offset, _expected, new in ram_client.snagem_2f_patches():
            patched[offset] = new
        self.assertTrue(ram_client.looks_like_snagem_2f_script(self._read(script=bytes(patched)), BLOB))

    def test_a_single_wrong_byte_at_any_anchor_is_rejected(self):
        for offset, expected in ram_client.SNAGEM_2F_SCRIPT_ANCHORS:
            with self.subTest(anchor=hex(offset)):
                broken = bytearray(SCRIPT)
                broken[offset] ^= 0xFF
                self.assertFalse(
                    ram_client.looks_like_snagem_2f_script(self._read(script=bytes(broken)), BLOB))

    def test_a_wrong_size_field_is_rejected(self):
        broken = bytearray(SCRIPT)
        struct.pack_into(">I", broken, 4, 0x1234)
        self.assertFalse(ram_client.looks_like_snagem_2f_script(self._read(script=bytes(broken)), BLOB))

    def test_a_bare_tcod_header_is_rejected(self):
        """The dumps contain other resident TCOD blobs. Magic alone must never be enough."""
        fake = b"TCOD" + struct.pack(">I", ram_client.SNAGEM_2F_SCRIPT_SIZE) + bytes(len(SCRIPT) - 8)
        self.assertFalse(ram_client.looks_like_snagem_2f_script(self._read(script=fake), BLOB))

    def test_an_unreadable_address_is_rejected_rather_than_raising(self):
        def boom(address, length):
            raise RuntimeError("not hooked")
        self.assertFalse(ram_client.looks_like_snagem_2f_script(boom, BLOB))


class TestFindingTheScript(unittest.TestCase):
    def test_it_is_found_in_a_memory_image(self):
        mem = _FakeMem()
        self.assertEqual(ram_client.find_snagem_2f_script(mem.dump()), BLOB)

    def test_it_is_found_wherever_it_sits(self):
        """The address is never hardcoded -- a map archive's load address is not ours to assume."""
        for base in (0x80500000, 0x80900000, 0x81000000):
            with self.subTest(base=hex(base)):
                mem = _FakeMem(base=base)
                self.assertEqual(ram_client.find_snagem_2f_script(mem.dump()), base)

    def test_a_decoy_tcod_blob_earlier_in_memory_is_skipped(self):
        """Exactly the real situation: other TCOD containers are resident, one of them at a lower address."""
        mem = _FakeMem()
        decoy = 0x804ED948 - ram_client.MEM1_START
        mem.cells[decoy:decoy + 8] = b"TCOD" + struct.pack(">I", ram_client.SNAGEM_2F_SCRIPT_SIZE)
        self.assertEqual(ram_client.find_snagem_2f_script(mem.dump()), BLOB)

    def test_absent_script_returns_none(self):
        blank = bytes(0x200000)
        self.assertIsNone(ram_client.find_snagem_2f_script(blank))


class TestPatching(unittest.TestCase):
    def test_a_clean_script_is_patched_and_the_bytes_land(self):
        mem = _FakeMem(script=CLEAN); mem.install(self)
        written = ram_client.patch_snagem_2f_script(BLOB)
        self.assertEqual(written, _writes_expected())
        self.assertGreater(written, 0, "a clean script must actually need writing")
        for offset, _expected, new in ram_client.snagem_2f_patches():
            self.assertEqual(mem.read_bytes(BLOB + offset, 1)[0], new, hex(offset))

    def test_it_writes_only_the_patch_sites(self):
        mem = _FakeMem(script=CLEAN); mem.install(self)
        ram_client.patch_snagem_2f_script(BLOB)
        allowed = {BLOB + o for o, _e, _p in ram_client.snagem_2f_patches()}
        for address, data in mem.writes:
            self.assertIn(address, allowed)
            self.assertEqual(len(data), 1)

    def test_patching_twice_is_a_no_op_the_second_time(self):
        mem = _FakeMem(script=CLEAN); mem.install(self)
        ram_client.patch_snagem_2f_script(BLOB)
        before = len(mem.writes)
        self.assertEqual(ram_client.patch_snagem_2f_script(BLOB), 0)
        self.assertEqual(len(mem.writes), before)

    def test_it_refuses_to_write_when_the_anchors_fail(self):
        broken = bytearray(SCRIPT)
        broken[0x0270] = 0x00                      # break the CODE section tag
        mem = _FakeMem(script=bytes(broken)); mem.install(self)
        self.assertIsNone(ram_client.patch_snagem_2f_script(BLOB))
        self.assertEqual(mem.writes, [], "it wrote into something it did not recognise")

    def test_it_refuses_when_a_patch_site_holds_an_unexpected_value(self):
        broken = bytearray(CLEAN)
        broken[ram_client.SNAGEM_2F_SCRIPT_PATCHES[0][0]] = 0x5A
        mem = _FakeMem(script=bytes(broken)); mem.install(self)
        self.assertIsNone(ram_client.patch_snagem_2f_script(BLOB))
        self.assertEqual(mem.writes, [])


class TestThePatcherAcrossPolls(unittest.TestCase):
    def _snagem_room(self):
        return sorted(ram_client.SNAGEM_ROOM_IDS)[0]

    def test_it_does_nothing_outside_the_hideout(self):
        mem = _FakeMem(); mem.install(self)
        patcher = ram_client.SnagemScriptPatcher()
        self.assertIsNone(patcher.poll(None, 1))
        self.assertIsNone(patcher.poll(None, None))
        self.assertEqual(mem.writes, [])

    def test_it_patches_on_the_first_poll_inside_and_says_so_once(self):
        mem = _FakeMem(script=CLEAN); mem.install(self)
        sys.modules["dolphin_memory_engine"].read_bytes = mem.read_bytes
        patcher = ram_client.SnagemScriptPatcher()
        self.addCleanup(setattr, ram_client, "dump_mem1", ram_client.dump_mem1)
        ram_client.dump_mem1 = mem.dump
        note = patcher.poll(None, self._snagem_room())
        self.assertIsNotNone(note)
        self.assertEqual(patcher.applications, 1)
        self.assertIsNone(patcher.poll(None, self._snagem_room()), "it must not re-announce every tick")
        self.assertEqual(patcher.applications, 1)

    def test_leaving_and_returning_re_patches_a_freshly_loaded_script(self):
        """The real failure mode: the script is re-read from disc on every map entry, so the patch dies."""
        mem = _FakeMem(script=CLEAN); mem.install(self)
        self.addCleanup(setattr, ram_client, "dump_mem1", ram_client.dump_mem1)
        ram_client.dump_mem1 = mem.dump
        patcher = ram_client.SnagemScriptPatcher()
        room = self._snagem_room()
        patcher.poll(None, room)
        self.assertEqual(patcher.applications, 1)
        patcher.poll(None, 1)                                     # walk out
        start = BLOB - ram_client.MEM1_START                        # the map reloads from disc
        mem.cells[start:start + len(CLEAN)] = CLEAN
        self.assertIsNotNone(patcher.poll(None, room))            # walk back in
        self.assertEqual(patcher.applications, 2)
        for offset, _e, new in ram_client.snagem_2f_patches():
            self.assertEqual(mem.read_bytes(BLOB + offset, 1)[0], new)

    def test_it_never_raises_when_memory_is_unreadable(self):
        dme = sys.modules["dolphin_memory_engine"]
        self.addCleanup(setattr, dme, "read_bytes", dme.read_bytes)

        def boom(address, length):
            raise RuntimeError("not hooked")

        dme.read_bytes = boom
        self.addCleanup(setattr, ram_client, "dump_mem1", ram_client.dump_mem1)
        ram_client.dump_mem1 = boom
        patcher = ram_client.SnagemScriptPatcher()
        self.assertIsNone(patcher.poll(None, self._snagem_room()))

    def test_describe_never_raises(self):
        self.assertIsInstance(ram_client.SnagemScriptPatcher().describe(), str)


class TestTheRulingIsLifted(unittest.TestCase):
    def test_wakin_and_gonzap_can_hold_progression_again(self):
        from ..game_data import missable_trainers

        self.assertEqual(missable_trainers.SNAG_MACHINE_BLOCKED_TRAINER_INDICES, frozenset())
        for index in (144, 145):
            self.assertNotIn(index, missable_trainers.FILLER_ONLY_TRAINER_INDICES, index)

    def test_the_client_constructs_the_patcher(self):
        source = (Path(__file__).resolve().parents[1] / "Client.py").read_text(encoding="utf-8")
        self.assertIn("SnagemScriptPatcher()", source)
        self.assertIn("snagem_script_patcher.poll(ctx.block_base, room_id, confirmed_surnames)", source)


if __name__ == "__main__":
    unittest.main()
