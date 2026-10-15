"""ADDENDUM 421 (2026-10-05) -- the holes a Machine Part could slip through, closed.

A Machine Part was reported as never received in a multiworld. These are the holes it could slip through.

1. The Machine Part's in-game effect is the 0x15 -> 0x16 story byte (the Gateon parts shop), not the Bag, so
   clearing the Bag never undid it. With location shuffle off the early areas are held at 0x15 until it arrives.
2. The save buffer's address is chosen at boot, so a reset or another boot's save state moved it under a live
   hook and every read and write -- the key-item clears included -- went to the old address.
3. A held step was remembered only in memory; it is persisted now, for both item holds.
"""
import struct
import unittest
from pathlib import Path

from .. import ram_client as rc
from ..game_data import chest_regions
from .test_addendum_229_map_backout_restore import BLOCK, _LiveByte

CLIENT = (Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")
GATEON, LAB, AGATE, UNLISTED_GATEON = 153, 138, 125, 154


class TestTheTable(unittest.TestCase):
    def test_the_bytes_are_the_ladders(self):
        self.assertTrue(rc._machine_part_ladder_agrees())
        self.assertEqual(0x15, rc.MACHINE_PART_HOLD_FLOOR)
        self.assertEqual((0x16, 0x18), rc.MACHINE_PART_HOLD_BAND)

    def test_the_fence_is_the_early_game(self):
        hold = rc.MachinePartStoryHold()
        self.assertEqual("Gateon Port", chest_regions.region_for_room(GATEON))
        self.assertEqual("Pokemon HQ Lab", chest_regions.region_for_room(LAB))
        self.assertTrue(hold.in_place(GATEON))
        self.assertTrue(hold.in_place(LAB))
        self.assertTrue(hold.in_place(UNLISTED_GATEON))
        self.assertFalse(hold.in_place(AGATE))
        self.assertFalse(hold.in_place(None))


class _Base(unittest.TestCase):
    start = 0x15

    def setUp(self):
        self.live = _LiveByte(self.start)
        self.hold = rc.MachinePartStoryHold(enabled=True, write_log=rc.StoryByteWriteLog())

    def tearDown(self):
        self.live.restore_module()

    def poll(self, room):
        return self.hold.poll(BLOCK, self.live.value, room)


class TestWithoutThePart(_Base):
    def test_the_parts_shop_is_pulled_back(self):
        self.live.value = 0x16
        note = self.poll(GATEON)
        self.assertEqual(0x15, self.live.value)
        self.assertIn("Machine Part", note)

    def test_the_lab_memo_tier_is_pulled_back(self):
        self.live.value = 0x17
        self.poll(LAB)
        self.assertEqual(0x15, self.live.value)
        self.assertEqual(0x17, self.hold.declined_value)

    def test_agate_and_later_are_progress_not_a_hold(self):
        self.live.value = 0x19
        self.poll(LAB)
        self.assertEqual(0x19, self.live.value)
        self.live.value = 0x51        # Gateon's second visit
        self.poll(GATEON)
        self.assertEqual(0x51, self.live.value)

    def test_agate_itself_is_outside_the_fence(self):
        self.live.value = 0x17
        self.poll(AGATE)
        self.assertEqual(0x17, self.live.value)


class TestThePartArrives(_Base):
    def test_the_held_step_is_given_back(self):
        self.live.value = 0x17
        self.poll(LAB)
        self.hold.item_held = True
        self.assertIn("0x17", self.poll(LAB))
        self.assertEqual(0x17, self.live.value)

    def test_no_invented_progress_without_a_hold(self):
        self.hold.item_held = True
        self.assertIsNone(self.poll(GATEON))
        self.assertEqual(0x15, self.live.value)
        self.assertIsNone(self.hold.fallback_grant(True), "the parts shop simply runs again")


class TestTheClientWiring(unittest.TestCase):
    def test_vanilla_travel_only(self):
        self.assertIn("self.machine_part_hold.enabled = self.key_item_shuffle and not self.randomize_travel_locations",
                      CLIENT)

    def test_it_runs_with_the_other_holds(self):
        loop = CLIENT.split("                        await check_scooter_hold(ctx)", 1)[1]
        self.assertLess(loop.index("await check_machine_part_hold(ctx)"), loop.index("await check_area_story_memory(ctx)"))

    def test_both_held_steps_survive_a_restart(self):
        self.assertIn('"story_item_holds": {hold.ITEM: hold.declined_value', CLIENT)
        self.assertIn('held_steps = slot_state.get("story_item_holds", {})', CLIENT)
        body = CLIENT.split("def _poll_item_story_hold", 1)[1].split("\nasync def ", 1)[0]
        # ADDENDUM 441: the disc room's flag is part of what is compared.
        self.assertIn("if (hold.declined_value, getattr(hold, \"lowered\", None)) != before:\n        ctx._save_local_state()", body)


class _Mem:
    def __init__(self):
        self.mem = bytearray(rc.MEM1_SIZE)
        self._r = rc.read_bytes
        rc.read_bytes = lambda a, n: bytes(self.mem[a - rc.MEM1_START:a - rc.MEM1_START + n])

    def restore(self):
        rc.read_bytes = self._r

    def boot(self, block):
        struct.pack_into(">I", self.mem, rc.SAVEDATA_NOW_POINTER - rc.MEM1_START, block - 0x180)
        off = block + rc.MONEY_DISPLAY_MARKER_OFFSET - rc.MEM1_START
        self.mem[off:off + 8] = b"\x01" * 8


class TestTheSaveDataMoving(unittest.TestCase):
    def setUp(self):
        self.mem = _Mem()

    def tearDown(self):
        self.mem.restore()

    def test_the_same_block_is_quiet(self):
        self.mem.boot(0x804794C0)
        watch = rc.BlockBaseWatch()
        self.assertEqual(0x804794C0, rc.live_block_base())
        for _ in range(5):
            self.assertIsNone(watch.poll(0x804794C0))

    def test_a_reset_is_noticed_on_the_second_agreeing_poll(self):
        self.mem.boot(0x804794C0)
        self.mem.boot(0x80479100)              # the reset: same buffer, a new boot-time offset
        watch = rc.BlockBaseWatch()
        self.assertIsNone(watch.poll(0x804794C0))
        self.assertEqual(0x80479100, watch.poll(0x804794C0))
        self.assertEqual(1, watch.moves)

    def test_a_pointer_to_nothing_valid_is_not_a_move(self):
        struct.pack_into(">I", self.mem.mem, rc.SAVEDATA_NOW_POINTER - rc.MEM1_START, 0x80479000)
        watch = rc.BlockBaseWatch()
        for _ in range(3):
            self.assertIsNone(watch.poll(0x804794C0), "title screen / mid-boot")
        struct.pack_into(">I", self.mem.mem, rc.SAVEDATA_NOW_POINTER - rc.MEM1_START, 0)
        self.assertIsNone(watch.poll(0x804794C0))

    def test_the_client_re_resolves_on_a_move(self):
        self.assertIn("moved_to = ctx.block_base_watch.poll(ctx.block_base)", CLIENT)
        window = CLIENT.split("moved_to = ctx.block_base_watch.poll(ctx.block_base)", 1)[1][:600]
        self.assertIn("ctx.block_base = None", window)
        self.assertIn("ctx.block_stability.reset()", window)
        self.assertLess(CLIENT.index("moved_to = ctx.block_base_watch.poll"),
                        CLIENT.index("ctx.block_base = ram_client.resolve_block_base(landmark)"))


class TestTheBootOffsetFromTheDol(unittest.TestCase):
    """Real dumps, when present: the pointer names the block every time, across boots a month apart."""

    DUMPS = Path("/mnt/user-data/uploads/PokemonXD-working/bridge/dumps")

    def test_against_real_dumps(self):
        dumps = sorted(self.DUMPS.glob("*.bin")) if self.DUMPS.is_dir() else []
        dumps = [d for d in dumps if d.stat().st_size == rc.MEM1_SIZE]
        if not dumps:
            self.skipTest("no full MEM1 dumps on this machine")
        mem_holder = _Mem()
        try:
            seen = set()
            for path in dumps:
                mem_holder.mem[:] = path.read_bytes()
                block = rc.live_block_base()
                self.assertIsNotNone(block, path.name)
                seen.add(block)
            self.assertGreater(len(seen), 1, "the dumps should span more than one boot")
        finally:
            mem_holder.restore()


if __name__ == "__main__":
    unittest.main()
