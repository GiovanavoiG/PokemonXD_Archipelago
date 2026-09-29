"""ADDENDUM 201. The chest-open flag model was fitted in one cluster and extrapolated across five others.

Player: "the chest inside worked and sent its location, but the chest outside the HQ lab did not."

The chest inside is chest 3, flag 1886. The chest outside is chest 1, room 143, flag 1136. ADDENDUM 173
measured two chests, brute-forced a bit layout, and cross-checked it four ways -- and every chest in every one
of those checks carries a flag in 1862..1944. The chest flag ids are not one run; they fall in six clusters,
and the model reaches the other five by arithmetic alone.

These tests pin the boundary, not the model: what is measured, what is not, and that the client refuses to
answer for the part that is not. The measurement that would extend the boundary is a pair of dumps around one
below-anchor chest -- see the `!chestflags` command."""
from __future__ import annotations

import unittest

from .. import ram_client
from ..game_data import chest_flags


class TestTheEvidenceOnlyCoversOneCluster(unittest.TestCase):
    def test_every_directly_evidenced_chest_is_in_the_validated_range(self) -> None:
        for flag_id in chest_flags.DIRECTLY_EVIDENCED_FLAG_IDS:
            self.assertTrue(chest_flags.flag_is_validated(flag_id), flag_id)

    def test_the_five_evidence_chests_are_the_ones_addendum_173_measured(self) -> None:
        """Named here so a future edit to the table cannot quietly widen what counts as measured."""
        self.assertEqual(
            {chest_flags.CHEST_FLAG_IDS[c] for c in (3, 40, 95, 96, 97)},
            set(chest_flags.DIRECTLY_EVIDENCED_FLAG_IDS),
        )

    def test_the_flag_ids_really_do_fall_in_separate_clusters(self) -> None:
        """The premise. If the ids were one contiguous run there would be nothing to extrapolate across."""
        ids = sorted({f for f in chest_flags.CHEST_FLAG_IDS.values() if f})
        gaps = [b - a for a, b in zip(ids, ids[1:]) if b - a > 40]
        self.assertGreaterEqual(len(gaps), 4, "expected several large gaps between flag-id clusters")

    def test_the_hq_lab_exterior_chest_is_the_reported_one(self) -> None:
        """Chest 1, room 143, is the chest the player reported. UPDATED by ADDENDUM 204: it is no longer
        unvalidated -- it was measured live and now resolves to BB+0x10734 mask 0x01. The fence assertion that
        used to live here moved to a chest in a cluster nobody has measured yet; see
        `test_a_chest_in_a_still_unmeasured_cluster_is_unvalidated` below."""
        # FIXED 2026-09-16 (ADDENDUM 250). This line used to reach the table through
        # `__import__("pokemon_xd.game_data.chest_table", ...)` -- an ABSOLUTE import of the world package,
        # which only resolves when the apworld is installed as a top-level package. Under the ordinary
        # `worlds/pokemon_xd` layout the world is already registered from there, so importing it again by a
        # second path makes AutoWorld raise "Game ... already registered" and this test ERRORED rather than
        # ran. A relative import is what every other test in this directory uses and it works in both layouts.
        from ..game_data import chest_table

        self.assertEqual(143, next(c["room"] for c in chest_table.CHESTS if c["chest"] == 1))
        self.assertTrue(chest_flags.chest_flag_is_validated(1))

    def test_a_chest_in_a_still_unmeasured_cluster_is_unvalidated(self) -> None:
        """Chest 43 (Cipher Key Lair, flag 1192) is in cluster 1192-1198, which has no measurement.
        (Was chest 29 until ADDENDUM 204 measured cluster 1440-1455.)"""
        self.assertEqual(1192, chest_flags.CHEST_FLAG_IDS[43])
        self.assertFalse(chest_flags.chest_flag_is_validated(43))

    def test_the_chest_that_worked_is_validated(self) -> None:
        self.assertTrue(chest_flags.chest_flag_is_validated(3))


class TestTheClientRefusesRatherThanGuesses(unittest.TestCase):
    def test_an_unvalidated_chest_gets_no_answer_from_a_block_full_of_ones(self) -> None:
        """The dangerous direction: a stray set bit must not become a check for a chest nobody opened."""
        first, length = ram_client.chest_flag_span()
        block = b"\xff" * length
        for chest_id in chest_flags.unvalidated_chest_ids():
            self.assertIsNone(ram_client.chest_is_open_in_block(block, chest_id), chest_id)

    def test_a_validated_chest_still_decodes_from_the_same_block(self) -> None:
        first, length = ram_client.chest_flag_span()
        block = b"\xff" * length
        self.assertTrue(ram_client.chest_is_open_in_block(block, 3))
        self.assertTrue(ram_client.chest_is_open_in_block(block, 40))

    def test_open_chest_ids_never_reports_an_unvalidated_chest(self) -> None:
        first, length = ram_client.chest_flag_span()
        reported = set(ram_client.open_chest_ids(b"\xff" * length))
        self.assertEqual(set(), reported & set(chest_flags.unvalidated_chest_ids()))

    def test_the_undetectable_list_is_non_empty_and_names_real_locations(self) -> None:
        names = ram_client.undetectable_chest_locations()
        self.assertGreater(len(names), 0)
        for name in names:
            self.assertIn(name, ram_client.CHEST_LOCATION_NAMES)

    def test_a_chest_from_an_unmeasured_cluster_is_on_the_undetectable_list(self) -> None:
        """Was chest 1 until ADDENDUM 204 measured it; chest 43 now carries the same assertion."""
        self.assertIn(
            ram_client.CHEST_ID_TO_LOCATION[43], ram_client.undetectable_chest_locations()
        )
        self.assertNotIn(
            ram_client.CHEST_ID_TO_LOCATION[1], ram_client.undetectable_chest_locations()
        )


class TestTheInverseDecoderRoundTrips(unittest.TestCase):
    """`!chestflags` names set bits with `flag_at_byte_bit`; if it disagreed with the forward function the
    diagnostic would mislead exactly when it is being trusted most."""

    def test_every_chest_flag_survives_the_round_trip(self) -> None:
        for chest_id, flag_id in chest_flags.CHEST_FLAG_IDS.items():
            if not flag_id:
                continue
            offset, mask = chest_flags.flag_byte_offset_and_mask(flag_id)
            self.assertEqual(
                flag_id, chest_flags.flag_at_byte_bit(offset, mask.bit_length() - 1), chest_id
            )


if __name__ == "__main__":
    unittest.main()


class TestManualCheckCoversThem(unittest.TestCase):
    """The player has to have a way through TODAY. `!checked` used to offer Overworld Items only; an
    undetectable chest belongs on that list for exactly as long as it stays undetectable.

    Checked against Client.py's SOURCE rather than by importing it -- that module pulls in Archipelago's
    CommonClient (and websockets through it), which is not importable in this test environment. Same approach
    ADDENDUM 181's logging fence already uses on the same file."""

    @classmethod
    def setUpClass(cls) -> None:
        from pathlib import Path

        cls.source = (Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")

    def test_the_manual_check_list_includes_the_undetectable_chests(self) -> None:
        self.assertIn(
            "self._overworld_location_names + self._undetectable_chest_location_names()",
            self.source,
            "!checked no longer offers the chests this client cannot detect",
        )

    def test_the_offer_is_gone_entirely(self) -> None:
        """REWRITTEN 2026-09-15 (ADDENDUM 226). ADDENDUM 201 offered the unmeasured-flag chests to `!checked`
        so a player could hand-mark a check that could not fire. ADDENDUM 218 made every chest detectable, so
        the category is empty -- and an offer list containing chests the client is about to send itself is
        worse than no list, because a fuzzy match marks the WRONG location and that cannot be undone."""
        block = self.source.split("def _undetectable_chest_location_names", 1)[1].split("\n    def ", 1)[0]
        self.assertIn("return []", block)
        self.assertNotIn("ram_client.undetectable_chest_locations()", block,
                         "the list must be empty, not merely gated")

    def test_it_offers_exactly_the_undetectable_set(self) -> None:
        """The data half, which IS importable: only chests that genuinely cannot fire, never a detectable one."""
        offered = set(ram_client.undetectable_chest_locations())
        self.assertIn(ram_client.CHEST_ID_TO_LOCATION[43], offered)    # cluster 1192-1198, unmeasured
        self.assertNotIn(ram_client.CHEST_ID_TO_LOCATION[1], offered)  # measured by ADDENDUM 204
        self.assertNotIn(ram_client.CHEST_ID_TO_LOCATION[3], offered)
        self.assertNotIn(ram_client.CHEST_ID_TO_LOCATION[40], offered)

    def test_the_connect_notice_is_gone(self) -> None:
        """REMOVED 2026-09-15 (ADDENDUM 226). ADDENDUM 201 warned at connect that N chests had no measured
        open-flag position; ADDENDUM 205 softened it to a footnote about tie-break order. ADDENDUM 218 took
        the flag array out of chest identity altogether, so an unmeasured position costs nothing at all and
        the notice was pointing the player at a problem that no longer exists."""
        self.assertNotIn("have no measured open-flag position", self.source)
        self.assertNotIn("cannot be detected by this client", self.source)
        self.assertNotIn("opening them will NOT send a check", self.source)
