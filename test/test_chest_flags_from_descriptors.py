"""The chest flags come from the game's own flag descriptor table, not from measured clusters."""
from __future__ import annotations

import struct
import unittest

from ..game_data import chest_flags as cf
from .local_dumps import DUMPS

DESCRIPTOR_TABLE_IN_COMMON_REL = 0x80B282F4 - 0x80B18DC0


class TestTheDescriptorTable(unittest.TestCase):
    def test_the_table_matches_common_rel(self) -> None:
        path = DUMPS / "a263_commonrel.bin"
        if not path.is_file():
            self.skipTest("the common.rel dump is not on this machine")
        rel = path.read_bytes()
        for flag_id, position in cf.CHEST_FLAG_BITS.items():
            raw = rel[DESCRIPTOR_TABLE_IN_COMMON_REL + 6 * flag_id:][:6]
            self.assertEqual(1, raw[0] & 0x3F, flag_id)                   # one bit wide
            self.assertEqual(0x18, (raw[0] >> 3) & 0x18, flag_id)         # the save block's flag group
            self.assertEqual(position, struct.unpack(">H", raw[2:4])[0], flag_id)

    def test_every_live_sample_agrees(self) -> None:
        self.assertEqual((0x10734, 0x01), cf.chest_byte_offset_and_mask(1))     # measured
        self.assertEqual((0x10734, 0x10), cf.chest_byte_offset_and_mask(4))     # predicted, then measured
        self.assertEqual((0x10778, 0x40), cf.chest_byte_offset_and_mask(80))    # measured
        self.assertEqual((0x107B3, 0x08), cf.chest_byte_offset_and_mask(87))    # opened live; the old model read +0x107AF
        self.assertEqual((0x107B3, 0x10), cf.chest_byte_offset_and_mask(88))

    def test_the_inverse_finds_every_chest_flag_and_nothing_else(self) -> None:
        for chest_id in cf.flagged_chest_ids():
            offset, mask = cf.chest_byte_offset_and_mask(chest_id)
            self.assertEqual(cf.CHEST_FLAG_IDS[chest_id], cf.flag_at_byte_bit(offset, mask.bit_length() - 1))
        self.assertIsNone(cf.flag_at_byte_bit(0x10700, 0))


if __name__ == "__main__":
    unittest.main()
