"""ADDENDUM 204. The flag array is piecewise, and the biggest unmeasured cluster is now measured.

ADDENDUM 201 found that the chest-flag model was fitted inside one flag cluster and extrapolated across five
others, and that the original dumps contradicted the extrapolation. This addendum measured the 1130-1149
cluster live, one chest at a time, on the player's own game.

    chest 98  flag 1875  ->  position 1392     offset 483    (ADDENDUM 173's cluster)
    chest  1  flag 1136  ->  position  440     offset 696    measured
    chest  4  flag 1140  ->  position  444     offset 696    PREDICTED, then measured -- hit exactly

`position = flag_id - offset`, and the offset belongs to the CLUSTER. The chest-4 measurement is the load
-bearing one: chest 1 alone fixes the offset but says nothing about spacing, and predicting chest 4 in advance
and hitting it is what makes the other 18 chests in that cluster trustworthy rather than assumed.

These tests pin the measurements as measurements. If someone later "simplifies" this back to one formula,
the real byte/mask values below stop matching and say so."""
from __future__ import annotations

import unittest

from .. import ram_client
from ..game_data import chest_flags as cf


class TestTheLiveMeasurements(unittest.TestCase):
    """Every one of these is a byte and mask observed on real hardware, not derived."""

    MEASURED = {
        1:  (0x10734, 0x01),   # ADDENDUM 204, HQ Lab exterior -- the chest the player reported
        4:  (0x10734, 0x10),   # ADDENDUM 204, Gateon Port -- predicted before it was opened
        80: (0x10778, 0x40),   # ADDENDUM 204, Phenac room 98 -- fixes cluster 1440-1455
        98: (0x107AD, 0x01),   # ADDENDUM 204, the PDA pickup -- confirmed the model and the A200 rename
        3:  (0x107AC, 0x08),   # ADDENDUM 173
        40: (0x107B2, 0x40),   # ADDENDUM 173
    }

    def test_every_measured_chest_resolves_to_its_measured_bit(self) -> None:
        for chest_id, expected in self.MEASURED.items():
            self.assertEqual(expected, cf.chest_byte_offset_and_mask(chest_id), f"chest {chest_id}")

    def test_the_clusters_really_do_use_different_offsets(self) -> None:
        """The premise. If one offset fitted them all, none of this would have been necessary."""
        offsets = {offset for _lo, _hi, offset in cf.CLUSTER_POSITION_OFFSETS}
        self.assertEqual({464, 483, 696}, offsets)

    def test_the_offsets_are_not_monotonic(self) -> None:
        """The strongest argument against ever deriving an unmeasured cluster's offset: ordered by flag id the
        offsets run 696, 464, 483. They do not even move in one direction, so no interpolation between two
        measured clusters could have produced the third."""
        ordered = [offset for _lo, _hi, offset in
                   sorted(cf.CLUSTER_POSITION_OFFSETS, key=lambda row: row[0])]
        self.assertEqual([696, 464, 483], ordered)
        self.assertFalse(ordered == sorted(ordered) or ordered == sorted(ordered, reverse=True))

    def test_the_gaps_between_clusters_go_both_ways(self) -> None:
        """291 flag ids span 523 array slots between clusters 1 and 2; 407 span only 388 between 2 and 3. One
        gap has slots to spare, the next is short -- so some flag ids in that range are not stored at all."""
        rows = sorted(cf.CLUSTER_POSITION_OFFSETS, key=lambda row: row[0])
        (_lo1, hi1, off1), (lo2, hi2, off2), (lo3, _hi3, off3) = rows
        self.assertEqual(523 - 291, (lo2 - off2) - (hi1 - off1) - (lo2 - hi1) + 0)
        self.assertGreater((lo2 - off2) - (hi1 - off1), lo2 - hi1)   # spare slots
        self.assertLess((lo3 - off3) - (hi2 - off2), lo3 - hi2)      # short

    def test_the_spacing_within_the_measured_cluster_is_one_bit_per_flag(self) -> None:
        """Chest 1 and chest 4 are flags 1136 and 1140 -- four apart, and four bits apart."""
        p1 = cf.flag_bit_position(cf.CHEST_FLAG_IDS[1])
        p4 = cf.flag_bit_position(cf.CHEST_FLAG_IDS[4])
        self.assertEqual(4, p4 - p1)

    def test_the_old_single_line_model_would_have_got_chest_one_wrong(self) -> None:
        """Guards the regression directly: the pre-204 answer was BB+0x10752 mask 0x20, and it was wrong."""
        self.assertNotEqual((0x10752, 0x20), cf.chest_byte_offset_and_mask(1))


class TestTheFenceStillHolds(unittest.TestCase):
    """Three clusters remain unmeasured. They must stay fenced, and must NOT inherit either known offset."""

    UNMEASURED_CLUSTERS = ((1192, 1198), (1712, 1727), (2276, 2277))   # 1440-1455 measured by ADDENDUM 204

    def test_no_unmeasured_cluster_claims_a_position(self) -> None:
        for lo, hi in self.UNMEASURED_CLUSTERS:
            for flag_id in (lo, hi):
                self.assertIsNone(cf.flag_bit_position(flag_id), flag_id)

    def test_chests_in_unmeasured_clusters_are_still_unvalidated(self) -> None:
        for lo, hi in self.UNMEASURED_CLUSTERS:
            for chest_id, flag_id in cf.CHEST_FLAG_IDS.items():
                if flag_id and lo <= flag_id <= hi:
                    self.assertFalse(cf.chest_flag_is_validated(chest_id), chest_id)

    def test_the_client_still_refuses_to_answer_for_them(self) -> None:
        _first, length = ram_client.chest_flag_span()
        block = b"\xff" * length
        for chest_id in cf.unvalidated_chest_ids():
            self.assertIsNone(ram_client.chest_is_open_in_block(block, chest_id), chest_id)

    def test_the_measured_chests_are_no_longer_fenced(self) -> None:
        """The point of measuring: chest 1, the player's original report, now works."""
        for chest_id in (1, 4, 98, 3, 40):
            self.assertTrue(cf.chest_flag_is_validated(chest_id), chest_id)
        self.assertNotIn(ram_client.CHEST_ID_TO_LOCATION[1], ram_client.undetectable_chest_locations())

    def test_measuring_clusters_shrank_the_undetectable_list(self) -> None:
        """Started at 32 undetectable chest locations (ADDENDUM 201). Two clusters measured since."""
        self.assertLessEqual(len(ram_client.undetectable_chest_locations()), 12)

    def test_the_four_for_four_cluster_is_fully_covered(self) -> None:
        """1440-1455 is the only cluster where every chest is a real AP location -- 19, 29, 80 and 93."""
        for chest_id in (19, 29, 80, 93):
            self.assertTrue(cf.chest_flag_is_validated(chest_id), chest_id)
            self.assertNotIn(ram_client.CHEST_ID_TO_LOCATION[chest_id],
                             ram_client.undetectable_chest_locations())


class TestRoundTrip(unittest.TestCase):
    def test_every_validated_chest_survives_the_inverse_decoder(self) -> None:
        """`!chestflags` names set bits with flag_at_byte_bit; it has to agree with the forward mapping for
        the measured clusters, or the diagnostic misleads exactly when it is trusted."""
        for chest_id, flag_id in cf.CHEST_FLAG_IDS.items():
            if not flag_id or not cf.chest_flag_is_validated(chest_id):
                continue
            offset, mask = cf.flag_byte_offset_and_mask(flag_id)
            self.assertEqual(flag_id, cf.flag_at_byte_bit(offset, mask.bit_length() - 1), chest_id)


if __name__ == "__main__":
    unittest.main()
