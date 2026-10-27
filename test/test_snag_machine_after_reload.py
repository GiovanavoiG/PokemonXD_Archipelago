"""A crash or reload that leaves the HQ Lab past 0x03 without the Snag Machine gets it back."""
from __future__ import annotations

import inspect
import unittest
from types import SimpleNamespace
from unittest import mock

from .. import Client
from .. import ram_client as rc


class TestSnagMachineAfterReload(unittest.TestCase):
    def _run(self, owned, lab, due=True, stable=True):
        ctx = SimpleNamespace(_snag_machine_check_due=due, block_base=0x80479300, randomize_travel_locations=False,
                              missable_shadow_pusher=SimpleNamespace(rng=None))
        writes = []
        with mock.patch.object(Client, "open_kaminko_on_map", lambda ctx: writes.append("kaminko") or True), \
                mock.patch.object(rc, "hand_shadow_to_miror", lambda base, i, rng: writes.append(("naps", i)) or True), \
                mock.patch.object(rc, "read_snag_machine", lambda base: owned), \
                mock.patch.object(rc, "read_story_byte", lambda base: lab), \
                mock.patch.object(rc, "write_snag_machine", lambda base, on: writes.append(on) or True):
            Client.check_snag_machine_after_reload(ctx, stable)
        return writes, ctx._snag_machine_check_due

    def test_missing_past_0x03_is_given(self) -> None:
        self.assertEqual(([True, "kaminko", ("naps", 1)], False), self._run(False, 0x04))

    def test_at_or_below_0x03_is_left_alone(self) -> None:
        self.assertEqual(([], False), self._run(False, 0x03))

    def test_already_owned_is_left_alone(self) -> None:
        self.assertEqual(([], False), self._run(True, 0x20))

    def test_waits_for_a_reading(self) -> None:
        self.assertEqual(([], True), self._run(None, 0x20))
        self.assertEqual(([], True), self._run(False, None))
        self.assertEqual(([], True), self._run(False, 0x20, stable=False))

    def test_only_once_per_load(self) -> None:
        self.assertEqual(([], False), self._run(False, 0x20, due=False))

    def test_travel_shuffle_reads_the_lab_s_own_progress(self) -> None:
        ctx = SimpleNamespace(randomize_travel_locations=True, block_base=0,
                              area_story_memory=SimpleNamespace(highest_by_region={"Pokemon HQ Lab": 0x05}))
        self.assertEqual(0x05, Client._hq_lab_progress(ctx))

    def test_kaminko_bit_is_or_ed_in(self) -> None:
        from .. import travel_locations as tl
        mem = {0x1000 + tl.TRAVEL_RECORD_OFFSET_FROM_BLOCK_BASE + 0x0F: 0x29}
        with mock.patch.object(rc, "read_bytes", lambda a, n: bytes([mem.get(a, 0)])), \
                mock.patch.object(rc, "write_bytes", lambda a, d: mem.__setitem__(a, d[0])):
            self.assertTrue(Client.open_kaminko_on_map(SimpleNamespace(block_base=0x1000)))
        self.assertEqual(0x2A, mem[0x1000 + tl.TRAVEL_RECORD_OFFSET_FROM_BLOCK_BASE + 0x0F])

    def test_naps_shadow_goes_to_miror_b(self) -> None:
        import random
        size, block = rc.SHADOW_MONITOR_RECORD_SIZE, 0x80479300
        base = block - rc.SAVEDATA_HERO_OFFSET - rc.RECORD_TRAINER_NAME_OFFSET + rc.SHADOW_MONITOR_SAVEDATA_OFFSET
        mem = bytearray(size)
        mem[rc.SHADOW_RECORD_SELF_ID_OFFSET + 1] = 1
        at = base + size

        def read(a, n):
            if a == block + rc.HERO_TRAINER_ID_FROM_BLOCK_BASE:
                return bytes(4)
            return bytes(mem[a - at:a - at + n])

        def write(a, d):
            mem[a - at:a - at + len(d)] = d
        with mock.patch.object(rc, "read_bytes", read), mock.patch.object(rc, "write_bytes", write):
            self.assertTrue(rc.hand_shadow_to_miror(block, 1, random.Random(1)))
            self.assertEqual(rc.SHADOW_MONITOR_FLED, mem[0] >> 5)
            self.assertNotEqual(0, int.from_bytes(mem[rc.SHADOW_RECORD_PID_OFFSET:rc.SHADOW_RECORD_PID_OFFSET + 4], "big"))
            self.assertFalse(rc.hand_shadow_to_miror(block, 1))          # already his
            mem[0] = (3 << 5)
            self.assertFalse(rc.hand_shadow_to_miror(block, 1))          # snagged: left alone

    def test_the_debug_command_exists(self) -> None:
        self.assertTrue(hasattr(Client.PokemonXDCommandProcessor, "_cmd_openkaminko"))

    def test_armed_by_a_new_save_and_by_a_rewind(self) -> None:
        src = inspect.getsource(Client)
        self.assertIn("ctx._snag_machine_check_due = True\n    lost = ", src)
        self.assertIn("continue\n                    ctx._snag_machine_check_due = True", src)
        self.assertIn("check_snag_machine_after_reload(ctx, block_is_stable)", src)


if __name__ == "__main__":
    unittest.main()
