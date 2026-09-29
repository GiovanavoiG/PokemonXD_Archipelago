"""ADDENDUM 363 (2026-09-26): "fits" is measured against the REAL span in both callers, not just one.

Player, with a screenshot of the patcher's own error dialog:

    Could not patch the ISO:
    new_entry_blob (16640 bytes) is not larger than DeckData_Story.bin's real on-disk span to the next entry
    (16640 bytes) -- use the plain in-place write path instead of this function when growth isn't actually
    needed.

THE TWO MEANINGS OF "GREW". `xd_deck_format.patch_entry_decompressed` answers "does this still fit" against
the entry's OLD DECLARED `comp_size`. `iso_patcher.rebuild_fsys_container_grown` answers it against the
entry's REAL on-disk span to the next entry's `data_off`. Those differ by whatever slack sits between the
declared footprint and the next entry -- and that slack GROWS when an earlier pass in the same run shrinks the
declared comp_size in place (ADDENDUM 10 does exactly that) while leaving the container structure alone.

Inside that window an edit is simultaneously "too big for the declared allocation" and "comfortably inside the
real space". `write_deck_story_patch` believed the first, routed to the growth path, and the growth path --
correctly -- refused to relocate a container that did not need to grow.

ADDENDUM 70 FIXED THIS ONCE ALREADY, on `write_fsys_multi_entry_patch`, for this exact reason. The single-entry
function is the other caller of the same low-level pair and never got it. So the fix is not a new rule, and
the point of these tests is less "the bug is gone" than "the two callers now answer the question with the same
function and cannot drift apart a third time".

WHY THE NUMBERS WERE EQUAL. `rebuild_fsys_container_grown` pads to a 32-byte boundary before measuring
(ADDENDUM 68's alignment invariant), so any edit landing in the last 32 bytes of the real span reports as
exactly equal. 16640 vs 16640 is that rounding, not a coincidence -- and it is why the report looked like an
off-by-one rather than a mis-routed branch.
"""
from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

from ..tools import iso_patcher
from ..tools import xd_deck_format as deck_format
from .test_write_enhanced_difficulty_patch_iso import (
    _build_synthetic_iso,
    _build_synthetic_story_decompressed,
)

STORY = "DeckData_Story.bin"


def _container(story_decompressed: bytes, declared_comp_size: int, span: int) -> bytes:
    """A two-entry container whose first entry has real slack between its DECLARED footprint and the next
    entry -- the shape the whole bug lives in, and the shape the single-entry synthetic fixture elsewhere in
    this suite deliberately does not have (it holds one entry, so the "next entry" is the container's end)."""
    names = b"DeckData_Story.bin\x00Filler.bin\x00"
    story_record, filler_record = 0x64, 0x64 + 0x40
    names_off = 0x140
    story_data = 0x200
    filler_data = story_data + span

    stream = deck_format.lzss_encode(story_decompressed)
    assert len(stream) + 0x10 <= declared_comp_size + 0x10 <= span, "fixture must leave real slack"
    blob = (b"LZSS" + struct.pack(">II", len(story_decompressed), declared_comp_size) + b"\x00" * 4
            + stream + b"\x00" * (declared_comp_size - len(stream)))

    filler = b"\xAB" * 0x40
    total = filler_data + len(filler)
    fsys = bytearray(total)
    fsys[0:4] = b"FSYS"
    struct.pack_into(">I", fsys, iso_patcher.FSYS_ENTRY_COUNT_OFF, 2)
    struct.pack_into(">I", fsys, iso_patcher.FSYS_OFFSET_ARRAY_OFF, story_record)
    struct.pack_into(">I", fsys, iso_patcher.FSYS_OFFSET_ARRAY_OFF + 4, filler_record)
    for record, data, decomp, comp, name_at in (
        (story_record, story_data, len(story_decompressed), declared_comp_size, names_off),
        (filler_record, filler_data, len(filler), len(filler), names_off + len(b"DeckData_Story.bin\x00")),
    ):
        struct.pack_into(">I", fsys, record + iso_patcher.FSYS_RECORD_DATA_OFF, data)
        struct.pack_into(">I", fsys, record + iso_patcher.FSYS_RECORD_DECOMP_SIZE_OFF, decomp)
        struct.pack_into(">I", fsys, record + iso_patcher.FSYS_RECORD_COMP_SIZE_OFF, comp)
        struct.pack_into(">I", fsys, record + iso_patcher.FSYS_RECORD_NAME_OFF, name_at)
    fsys[names_off:names_off + len(names)] = names
    fsys[story_data:story_data + len(blob)] = blob
    fsys[filler_data:filler_data + len(filler)] = filler
    return bytes(fsys)


class TestTheFixtureReallyHasSlack(unittest.TestCase):
    """If this stops holding, every test below is passing for the wrong reason."""

    def test_the_declared_footprint_is_smaller_than_the_real_span(self) -> None:
        decomp = _build_synthetic_story_decompressed()
        fsys = _container(decomp, declared_comp_size=0x200, span=0x400)
        entries = iso_patcher.parse_fsys(fsys)
        start, end = iso_patcher.real_entry_span(entries, STORY, len(fsys))
        self.assertEqual(end - start, 0x400)
        self.assertLess(0x10 + entries[STORY]["comp_size"], end - start)


class TestGrewAgainstRealSpan(unittest.TestCase):
    def setUp(self) -> None:
        self.fsys = _container(_build_synthetic_story_decompressed(),
                               declared_comp_size=0x200, span=0x400)

    def test_a_blob_exactly_filling_the_real_span_is_not_growth(self) -> None:
        """The reported case, reduced. 16640 vs 16640 said "not larger than", and not-larger-than is precisely
        the condition under which nothing needs to move."""
        self.assertFalse(
            iso_patcher._grew_against_real_span(self.fsys, STORY, b"\x00" * 0x400, grew=True)
        )

    def test_a_blob_inside_the_real_span_is_not_growth_even_though_it_broke_the_declared_one(self) -> None:
        self.assertFalse(
            iso_patcher._grew_against_real_span(self.fsys, STORY, b"\x00" * 0x300, grew=True)
        )

    def test_one_byte_past_the_real_span_is_growth(self) -> None:
        self.assertTrue(
            iso_patcher._grew_against_real_span(self.fsys, STORY, b"\x00" * 0x401, grew=True)
        )

    def test_it_never_turns_a_no_into_a_yes(self) -> None:
        """Deliberately one-directional. A `grew=False` blob is padded out to the declared footprint, and
        deciding THAT case needs ADDENDUM 54's trim-and-retry, which belongs with the caller holding the
        exact-fit length to trim to."""
        for size in (0x10, 0x400, 0x4000):
            self.assertFalse(
                iso_patcher._grew_against_real_span(self.fsys, STORY, b"\x00" * size, grew=False), size
            )


class TestTheInPlaceGuard(unittest.TestCase):
    def setUp(self) -> None:
        self.fsys = _container(_build_synthetic_story_decompressed(),
                               declared_comp_size=0x200, span=0x400)

    def test_a_blob_at_exactly_the_span_is_allowed(self) -> None:
        """It ends where the next entry begins, so it cannot touch it."""
        iso_patcher._refuse_in_place_overrun(self.fsys, STORY, b"\x00" * 0x400)

    def test_a_blob_past_the_span_is_refused_rather_than_truncated(self) -> None:
        with self.assertRaises(RuntimeError) as caught:
            iso_patcher._refuse_in_place_overrun(self.fsys, STORY, b"\x00" * 0x401)
        self.assertIn("corrupting a neighboring entry", str(caught.exception))


class TestTheWholePatchNoLongerRefusesAnEditThatFits(unittest.TestCase):
    def test_an_edit_over_the_declared_size_but_inside_the_real_span_writes_in_place(self) -> None:
        """End to end through `write_deck_story_patch`, which is the function the player's dialog came from.
        Before the fix this raised ValueError out of `rebuild_fsys_container_grown`."""
        base = _build_synthetic_story_decompressed()
        # Sized from measurement, not guessed: the edit must land strictly between the declared allocation
        # and the real span, which is the only window where the two answers disagree.
        edited = base + bytes(range(256)) * 6
        edited_stream = len(deck_format.lzss_encode(edited))
        declared = edited_stream - 0x40          # too small for the edit -> patch_entry_decompressed says grew
        span = ((0x10 + edited_stream + 0x80) // 32 + 1) * 32   # comfortably bigger -> the real span fits it

        fsys = _container(base, declared_comp_size=declared, span=span)
        entries = iso_patcher.parse_fsys(fsys)
        story = entries[STORY]
        entry_raw = fsys[story["data_off"]:story["data_off"] + 0x10 + story["comp_size"]]

        encoded, _comp, grew_declared = deck_format.patch_entry_decompressed(
            entry_raw, edited, allow_grow=True, allow_decomp_resize=True
        )
        start, end = iso_patcher.real_entry_span(entries, STORY, len(fsys))
        self.assertTrue(grew_declared, "fixture must exceed the DECLARED allocation or it tests nothing")
        self.assertLessEqual(len(encoded), end - start,
                             "fixture must still fit the REAL span or it tests the wrong branch")

        iso_bytes = _build_synthetic_iso(fsys)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.iso"
            path.write_bytes(iso_bytes)
            result = iso_patcher.write_deck_story_patch(
                output_path=path,
                deck_archive_off=0x800,
                deck_archive_len=len(fsys),
                deck_archive_record_off=0x440 + 12,
                fsys_bytes=fsys,
                story_entry=story,
                entry_raw=entry_raw,
                new_decompressed=edited,
                allow_decomp_resize=True,
            )
            self.assertFalse(result["grew"], "this edit fits the real span -- nothing should have relocated")
            written = path.read_bytes()
            # The neighbour is untouched, which is the thing the guard exists to protect.
            self.assertEqual(written[0x800 + end:0x800 + end + 0x40], b"\xAB" * 0x40)


class TestBothCallersShareOneAnswer(unittest.TestCase):
    def test_neither_caller_re_implements_the_span_comparison(self) -> None:
        """The actual point of this addendum. Two hand-written copies of this comparison is what let one of
        them go unfixed from ADDENDUM 70 until the player hit it."""
        source = (Path(iso_patcher.__file__)).read_text()
        body = source[source.index("def write_deck_story_patch("):]
        body = body[:body.index("\ndef ", 1)]
        self.assertIn("_grew_against_real_span(", body)
        self.assertIn("_refuse_in_place_overrun(", body)

        multi = source[source.index("def write_fsys_multi_entry_patch("):]
        multi = multi[:multi.index("\ndef ", 1)]
        self.assertIn("_grew_against_real_span(", multi)
        self.assertIn("_refuse_in_place_overrun(", multi)


# ============================================================================================================
# The other half of ADDENDUM 363: the caches added because the suite got slow
# ============================================================================================================
# Player: "why are tests so long to run all of a sudden?"
#
# Measured: 81% of the suite's wall time was world generation (786 generations, one per test method), and
# three functions inside a generation accounted for well over half of one. All three were recomputing an
# identical answer from module-level constants. These tests exist because a cache is only safe while it still
# returns what the uncached code returned -- so each one recomputes the slow way and compares.
class TestTheCachesReturnWhatTheSlowPathReturned(unittest.TestCase):
    def test_the_surname_match_is_unchanged_for_every_real_shadow_label(self) -> None:
        from ..game_data import shadow_regions

        roster = dict(shadow_regions._roster_by_surname())
        labels = [shadow_regions.trainer_label_from_location(entry.get("trainer") or "")
                  for entry in shadow_regions._load()]
        self.assertGreater(len(labels), 50, "fixture is empty -- this would pass vacuously")
        for label in labels:
            self.assertEqual(shadow_regions._surname_of_cached(label),
                             shadow_regions._surname_of(label, roster), label)

    def test_the_roster_index_is_the_same_grouping_and_the_same_objects(self) -> None:
        """It regroups references into `trainer_roster.TRAINERS`; it never copied them. That is what makes
        caching it add no sharing that did not already exist."""
        from ..game_data import shadow_regions, trainer_roster

        cached = shadow_regions._roster_by_surname()
        expected: "dict[str, list[dict]]" = {}
        for trainer in trainer_roster.TRAINERS:
            expected.setdefault(trainer["name"].upper(), []).append(trainer)
        self.assertEqual(set(cached), set(expected))
        for surname, rows in expected.items():
            self.assertEqual(len(cached[surname]), len(rows), surname)
            for got, want in zip(cached[surname], rows):
                self.assertIs(got, want, surname)

    def test_the_region_order_helper_still_hands_out_a_private_list(self) -> None:
        """The cached value is a tuple on purpose. `_region_order` must keep returning a list a caller can
        mutate without reaching into the cache."""
        from ..game_data import shadow_regions

        first = shadow_regions._region_order()
        first.append("NOT A REGION")
        self.assertNotIn("NOT A REGION", shadow_regions._region_order())

    def test_gate_for_label_is_stable_across_repeated_calls(self) -> None:
        from ..game_data import shadow_regions

        labels = [shadow_regions.trainer_label_from_location(entry.get("trainer") or "")
                  for entry in shadow_regions._load()]
        for label in labels:
            self.assertEqual(shadow_regions.gate_for_label(label),
                             shadow_regions.gate_for_label(label), label)

    def test_the_precomputed_candidate_lists_match_the_scan_they_replaced(self) -> None:
        """`_candidate_species_ids` ran a 386-species scan once per Pokemon instance to produce one of two
        possible lists. Same lists, computed twice instead of 808 times."""
        from ..randomizer import team_shuffle

        class _Opts:
            legendary_safe = True
            level_boost_percent = 0

        class _Sp:
            def __init__(self, legendary): self.is_legendary = legendary

        pool = {i: _Sp(i % 7 == 0) for i in range(1, 400)}
        shuffler = team_shuffle.TeamShuffler(_Opts(), None, pool)
        for legendary in (False, True):
            expected = [sid for sid, sp in pool.items()
                        if (sp.is_legendary == legendary or not _Opts.legendary_safe)]
            self.assertEqual(shuffler._base_candidates[legendary], expected)
            self.assertEqual(shuffler._candidate_species_ids(_Sp(legendary), is_shadow=False), expected)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
