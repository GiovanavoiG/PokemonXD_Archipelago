"""ADDENDUM 399 (2026-10-01) -- the patcher checks its input before it touches it.

Player: "User reported ' ValueError: trainer 87 only has 0 free team slots(s), but 1 new shadow pokemon were
         requested for it' with this yaml." ... "User reported their ISO dump may have been bad"

THE GENERATOR WAS INNOCENT. `data/deckdata_story_trainers.json` gives trainer 87 `party_size` 4 with members
in slots [0,1,2,3] -- two free. The seed's expansion plan asked for one. Across eight seeds on that player's
exact yaml, no trainer was over-assigned, and the census only ever lists trainers with at least one free slot.
The plan and the census agreed with each other; the ISO was the thing that disagreed with both.

The error came from `write_shadow_multi_trainer_patch`, which reads the trainer out of the ISO in front of it
and found all six slots used. Two things produce that:

  * a bad or non-matching dump -- a different revision, a bad rip, or something already modified;
  * an already-patched ISO handed back in. That yaml had `enhanced_difficulty: fill_enemy_team`, which pads
    EVERY trainer to six. Trainer 87 lands at exactly 6/6 after one patch (4 vanilla + 1 expansion + 1 pad),
    so a second pass finds nowhere to put anything and dies on that trainer specifically.

Before this, NOTHING in the patcher looked at its input -- no disc id read, no hash, no structural check.
Grepped for it: the only "already patched" strings in `iso_patcher.py` are per-sub-patch idempotence checks.
The first thing that noticed a foreign disc was a ValueError three thousand lines deep about team slots.

TWO LAYERS, cheapest first.

  1. DISC ID. Six bytes at offset 0. Catches a PAL or Japanese disc, or an entirely different game, for the
     cost of one read. It cannot catch a re-patch -- a patched XD disc still says GXXE01.

  2. CENSUS AGREEMENT. Decode `DeckData_Story.bin` and compare every census trainer's real free-slot count
     against what the extract says. This is the layer that catches the reported case, and it catches revision
     drift and bad dumps with the same comparison. Tolerance is zero: the census is an exact extract, not a
     sample, so one honest mismatch means the discs differ.

WHERE IT RUNS: in `apply_patch`, BEFORE `chunked_copy`. A refusal should cost the player nothing, and a
half-written output ISO is worse than no output at all. It reads the SOURCE, which is the disc they picked.

WHAT IT WILL NOT DO: guess. A build shipping without the trainer extract has nothing to compare against, so
layer two silently does not run rather than inventing a verdict (ADDENDUM 243 -- no second source of truth,
and no invented one either).
"""
from __future__ import annotations

import unittest
from pathlib import Path

from ..tools import iso_patcher as ip


class TestTheDiscId(unittest.TestCase):
    def test_the_expected_id_is_the_ntsc_u_one(self) -> None:
        """GXX = XD, E = NTSC-U, 01 = Nintendo. Asserted so a typo here cannot silently reject every disc."""
        self.assertEqual(b"GXXE01", ip.EXPECTED_DISC_ID)
        self.assertEqual(6, len(ip.EXPECTED_DISC_ID))

    def test_an_unreadable_file_is_refused_rather_than_crashing(self) -> None:
        refusal = ip.disc_id_refusal(Path("/nonexistent/not-an-iso.iso"))
        self.assertIsNotNone(refusal)
        self.assertIn("GameCube", refusal)

    def test_a_wrong_id_names_what_it_found_and_what_it_wanted(self) -> None:
        class _FakeReader:
            def read(self, _off, _length): return b"GXXP01"   # PAL
            def close(self): pass

        real = ip.open_reader
        ip.open_reader = lambda _p: _FakeReader()
        try:
            refusal = ip.disc_id_refusal(Path("some-pal-disc.iso"))
        finally:
            ip.open_reader = real
        self.assertIsNotNone(refusal)
        self.assertIn("GXXP01", refusal)
        self.assertIn("GXXE01", refusal)
        self.assertIn("NTSC-U", refusal)

    def test_the_right_id_passes(self) -> None:
        class _FakeReader:
            def read(self, _off, _length): return b"GXXE01"
            def close(self): pass

        real = ip.open_reader
        ip.open_reader = lambda _p: _FakeReader()
        try:
            self.assertIsNone(ip.disc_id_refusal(Path("clean.iso")))
        finally:
            ip.open_reader = real


class TestTheCensusLayer(unittest.TestCase):
    """`preflight_refusal` composes the two layers; the disc-id half is stubbed to passing here."""

    def setUp(self) -> None:
        self._real = ip.disc_id_refusal
        ip.disc_id_refusal = lambda _p: None

    def tearDown(self) -> None:
        ip.disc_id_refusal = self._real

    def test_no_census_means_layer_two_does_not_run(self) -> None:
        """A build without the extract must patch exactly as it did before, not refuse everything."""
        self.assertIsNone(ip.preflight_refusal(Path("x.iso"), None))
        self.assertIsNone(ip.preflight_refusal(Path("x.iso"), []))

    def test_an_agreeing_iso_passes(self) -> None:
        real = ip.census_disagreement
        ip.census_disagreement = lambda _p, _c: []
        try:
            self.assertIsNone(ip.preflight_refusal(Path("x.iso"), [{"trainer_index": 87, "free_slots": 2}]))
        finally:
            ip.census_disagreement = real

    def test_the_reported_case_is_named_in_the_refusal(self) -> None:
        """Trainer 87, census 2, ISO 0 -- the exact numbers from the report."""
        real = ip.census_disagreement
        ip.census_disagreement = lambda _p, _c: [(87, 2, 0)]
        try:
            refusal = ip.preflight_refusal(Path("mine.iso"), [{"trainer_index": 87, "free_slots": 2}])
        finally:
            ip.census_disagreement = real
        self.assertIsNotNone(refusal)
        self.assertIn("trainer 87", refusal)
        self.assertIn("expected 2 free team slot(s), found 0", refusal)
        self.assertIn("already been patched", refusal)
        self.assertIn("fill_enemy_team", refusal)

    def test_tolerance_is_zero_and_named(self) -> None:
        self.assertEqual(0, ip.CENSUS_MISMATCH_TOLERANCE)

    def test_a_wholly_different_disc_says_so(self) -> None:
        census = [{"trainer_index": i, "free_slots": 2} for i in range(1, 9)]
        real = ip.census_disagreement
        ip.census_disagreement = lambda _p, _c: [(i, 2, 0) for i in range(1, 9)]
        try:
            refusal = ip.preflight_refusal(Path("other.iso"), census)
        finally:
            ip.census_disagreement = real
        self.assertIn("8 of 8 trainers differ", refusal)
        self.assertIn("wholly different disc", refusal)
        self.assertIn("+3 more", refusal, "only the first five are listed, the rest counted")

    def test_a_missing_trainer_reads_as_no_team_rather_than_a_negative_number(self) -> None:
        real = ip.census_disagreement
        ip.census_disagreement = lambda _p, _c: [(87, 2, -1)]
        try:
            refusal = ip.preflight_refusal(Path("x.iso"), [{"trainer_index": 87, "free_slots": 2}])
        finally:
            ip.census_disagreement = real
        self.assertIn("no team at all", refusal)
        self.assertNotIn("-1", refusal)

    def test_an_undecodable_deck_is_reported_not_swallowed(self) -> None:
        def _boom(_p, _c):
            raise RuntimeError("lzss stream ended early")

        real = ip.census_disagreement
        ip.census_disagreement = _boom
        try:
            refusal = ip.preflight_refusal(Path("truncated.iso"), [{"trainer_index": 1, "free_slots": 1}])
        finally:
            ip.census_disagreement = real
        self.assertIn("corrupt or truncated", refusal)
        self.assertIn("lzss stream ended early", refusal)


class TestItRunsBeforeTheCopy(unittest.TestCase):
    def test_apply_patch_refuses_ahead_of_chunked_copy(self) -> None:
        """A refusal must cost the player nothing -- no half-written output ISO to clean up."""
        source = (Path(__file__).resolve().parent.parent / "tools" / "iso_patcher.py").read_text(
            encoding="utf-8")
        body = source[source.index("def apply_patch("):]
        preflight_at = body.index("preflight_refusal(source_path")
        copy_at = body.index("chunked_copy(source_path, output_path)")
        self.assertLess(preflight_at, copy_at,
                        "the pre-flight has to come before the copy, or a rejected ISO still writes output")

    def test_the_census_lookup_cannot_take_the_patch_down(self) -> None:
        """A missing or broken extract disables layer two; it must never raise out of apply_patch."""
        source = (Path(__file__).resolve().parent.parent / "tools" / "iso_patcher.py").read_text(
            encoding="utf-8")
        body = source[source.index("def apply_patch("):source.index("def apply_patch(") + 4000]
        self.assertIn("except Exception:", body)
        self.assertIn("_census = None", body)


class TestCensusDisagreementRunsForReal(unittest.TestCase):
    """The other tests stub `census_disagreement`. This one RUNS it, against a fake ISO.

    Added because the first draft of that function opened with `from ..game_data import deck_format`, which
    does not exist -- `deck_format` is bound at module scope from `xd_deck_format`. Every stubbed test still
    passed, and `preflight_refusal`'s broad `except` would have reported "corrupt or truncated dump" for every
    valid ISO on the planet. A function that is only ever stubbed is a function nobody has run.
    """

    class _Reader:
        def read(self, _off, _length): return b"\x00" * max(_length, 0x10)
        def close(self): pass

    class _Deck:
        """Trainer 87 full, trainer 88 matching the census, trainer 99 absent."""
        _TEAMS = {
            87: [{"slot": s} for s in range(6)],          # 0 free -- the reported case
            88: [{"slot": s} for s in range(4)],          # 2 free -- agrees
        }

        def __init__(self, _blob): pass

        def trainer(self, index):
            team = self._TEAMS.get(index)
            return None if team is None else {"team": team}

    def _run(self, census):
        patched = {
            "open_reader": lambda _p: self._Reader(),
            "parse_fst": lambda _r: object(),
            "find_by_basename": lambda _f, _n: (0, 0x40, 0),
            "parse_fsys": lambda _b: {"DeckData_Story.bin": {"data_off": 0, "comp_size": 0}},
        }
        saved = {k: getattr(ip, k) for k in patched}
        saved_decode, saved_deckfile = ip.deck_format.lzss_decode, ip.deck_format.DeckFile
        for k, v in patched.items():
            setattr(ip, k, v)
        ip.deck_format.lzss_decode = lambda raw: raw
        ip.deck_format.DeckFile = self._Deck
        try:
            return ip.census_disagreement(Path("fake.iso"), census)
        finally:
            for k, v in saved.items():
                setattr(ip, k, v)
            ip.deck_format.lzss_decode, ip.deck_format.DeckFile = saved_decode, saved_deckfile

    def test_a_matching_trainer_produces_no_disagreement(self) -> None:
        self.assertEqual([], self._run([{"trainer_index": 88, "free_slots": 2}]))

    def test_the_reported_trainer_is_caught_with_its_real_numbers(self) -> None:
        self.assertEqual([(87, 2, 0)], self._run([{"trainer_index": 87, "free_slots": 2}]))

    def test_an_absent_trainer_is_reported_as_minus_one(self) -> None:
        self.assertEqual([(99, 1, -1)], self._run([{"trainer_index": 99, "free_slots": 1}]))

    def test_results_come_back_in_trainer_order(self) -> None:
        found = self._run([
            {"trainer_index": 99, "free_slots": 1},
            {"trainer_index": 87, "free_slots": 2},
            {"trainer_index": 88, "free_slots": 2},
        ])
        self.assertEqual([87, 99], [row[0] for row in found])

    def test_it_composes_into_a_real_refusal(self) -> None:
        """End to end, with only the disc-id layer stubbed."""
        saved = ip.disc_id_refusal
        ip.disc_id_refusal = lambda _p: None
        try:
            found = self._run([{"trainer_index": 87, "free_slots": 2}])
            self.assertEqual([(87, 2, 0)], found)
        finally:
            ip.disc_id_refusal = saved


class TestTheTestSeamStaysATestSeam(unittest.TestCase):
    """`_skip_preflight` must never be reachable from a player path."""

    def test_it_defaults_to_off(self) -> None:
        import inspect

        signature = inspect.signature(ip.apply_patch)
        self.assertIn("_skip_preflight", signature.parameters)
        self.assertIs(False, signature.parameters["_skip_preflight"].default)

    def test_the_launcher_never_passes_it(self) -> None:
        launcher = (Path(__file__).resolve().parent.parent / "launcher_patch.py").read_text(encoding="utf-8")
        self.assertNotIn("_skip_preflight", launcher)

    def test_exactly_one_test_uses_it(self) -> None:
        """A second user of this seam is a second ISO nobody is checking. Make adding one deliberate."""
        here = Path(__file__).resolve().parent
        users = sorted(
            path.name for path in here.glob("test_*.py")
            if path.name != Path(__file__).name
            and "_skip_preflight=True" in path.read_text(encoding="utf-8")
        )
        self.assertEqual(["test_addendum_128_shop_pass_end_to_end.py"], users)
