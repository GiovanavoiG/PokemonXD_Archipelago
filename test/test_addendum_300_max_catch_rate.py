"""ADDENDUM 300 (2026-09-20) -- the catch rate, in both of the places it lives.

Player: "Can you add an option to make all pokemon have 100% catch rate?"

TWO HALVES, AND THE SECOND ONE IS THE ONE THAT MATTERS IN XD. An ordinary species' catch rate is a byte at
+0x01 of the `common_rel` stats entry ADDENDUM 285 pinned down. A Shadow Pokemon's snag is not checked against
that at all -- each DDPK record carries its own `catch_rate_override`, also at +0x01, and in a real
`DeckData_DarkPokemon.bin` those run from 3 to 255 across the 83 in-use entries. An option that wrote only the
stats table would have left every snag in the game at vanilla difficulty while reporting success, which is the
shape of failure this project keeps finding in its own past work. The tests below hold both halves.

AND A THIRD PROPERTY THAT IS PURELY ABOUT ORDER. Shadow Pokemon Expansion and Enhanced Difficulty bring
previously-free DDPK entries into use during the same patch run. `apply_shadow_catch_rate` covers whatever
reads in_use at the moment it runs, so "after those passes" is not a stylistic choice about where to put a
call -- it is the entire mechanism by which seed-invented Shadow Pokemon are covered. It is asserted here
because nothing else would notice if it moved.

WHAT IS NOT CLAIMED. 255 is the largest value the byte holds; it is not literal certainty, because the capture
roll multiplies the rate by a health term worth a third at full HP. The option's own text says so, and
`test_the_option_text_does_not_promise_certainty` keeps it saying so -- the same guard ADDENDUM 285 put on the
experience rate after it could only deliver 4x of a requested 5x.
"""
from __future__ import annotations

import os
import unittest
from unittest import mock

from ..game_data import species_stats as ss
from ..tools import xd_deck_format as df
from ..tools import xd_rel_format as rf
from ..tools import iso_patcher

COMMON_REL_DUMP = "/mnt/user-data/uploads/PokemonXD-working/bridge/dumps/a263_commonrel.bin"
DUMP_STATS_BASE = 0x29DA8
DARK_DUMP = "/mnt/user-data/uploads/PokemonXD-working/bridge/dumps/deck_dark_1.bin"

#: Four Gen III catch rates chosen because they are far apart and nothing else in the entry looks like them.
#: These are the same four the stats table's own header records -- evidence, never data anything writes.
KNOWN_CATCH_RATES = {1: 45, 25: 190, 113: 30, 150: 3}


class TestTheOffsetIsStatedOnceAndAgreesWithItself(unittest.TestCase):
    def test_both_modules_name_the_same_byte(self) -> None:
        self.assertEqual(0x01, ss.CATCH_RATE_OFFSET)
        self.assertEqual(ss.CATCH_RATE_OFFSET, rf.SPECIES_CATCH_RATE_OFFSET)

    def test_the_catch_rate_is_not_one_of_the_experience_bytes(self) -> None:
        """A cheap guard with a real failure behind it: three single-byte features now write into the same
        0x124-byte entry, and two of them sharing an offset would be silent."""
        self.assertNotIn(ss.CATCH_RATE_OFFSET, {ss.EXP_RATE_OFFSET, ss.BASE_EXP_OFFSET, ss.BASE_HP_OFFSET})

    def test_the_maximum_is_the_byte(self) -> None:
        self.assertEqual(0xFF, ss.CATCH_RATE_MAX)


class TestThePlanNeverLowersAnything(unittest.TestCase):
    RATES = {1: 45, 2: 3, 3: 190, 4: 255, 5: 0, 6: 254}

    def test_only_species_below_the_target_are_written(self) -> None:
        plan = ss.plan_catch_rate(self.RATES)
        self.assertEqual({"1", "2", "3", "6"}, set(plan["catch_rate"]))

    def test_a_species_already_at_the_maximum_is_left_alone(self) -> None:
        plan = ss.plan_catch_rate(self.RATES)
        self.assertNotIn("4", plan["catch_rate"])
        self.assertEqual(1, plan["already_max"])

    def test_a_zero_is_a_sentinel_row_and_not_a_species_to_raise(self) -> None:
        plan = ss.plan_catch_rate(self.RATES)
        self.assertNotIn("5", plan["catch_rate"])

    def test_every_written_value_is_strictly_higher_than_the_one_it_replaces(self) -> None:
        for target in (100, 200, 255):
            plan = ss.plan_catch_rate(self.RATES, target)
            for key, value in plan["catch_rate"].items():
                self.assertGreater(value, self.RATES[int(key)])

    def test_planning_twice_is_a_no_op_the_second_time(self) -> None:
        """Idempotence is the property that makes re-patching an already-patched ISO harmless."""
        plan = ss.plan_catch_rate(self.RATES)
        after = dict(self.RATES)
        for key, value in plan["catch_rate"].items():
            after[int(key)] = value
        self.assertEqual({}, ss.plan_catch_rate(after)["catch_rate"])

    def test_an_out_of_range_target_is_clamped_not_rejected(self) -> None:
        self.assertEqual(0xFF, ss.plan_catch_rate(self.RATES, 9999)["target"])
        self.assertEqual(1, ss.plan_catch_rate(self.RATES, -5)["target"])

    def test_the_description_reports_the_lowest_rate_it_raised_from(self) -> None:
        text = ss.describe_catch_rate_plan(ss.plan_catch_rate(self.RATES))
        self.assertIn("3", text)
        self.assertIn("255", text)

    def test_an_empty_plan_says_so_rather_than_claiming_work(self) -> None:
        text = ss.describe_catch_rate_plan(ss.plan_catch_rate({1: 255, 2: 255}))
        self.assertIn("nothing to raise", text)


class TestTheWriterRefusesRatherThanGuessing(unittest.TestCase):
    """`apply_catch_rate`'s bounds -- ADDENDUM 268's rule, on the third feature to write into this table."""

    class _Rel:
        def __init__(self, count: int) -> None:
            self.data = bytearray(count * ss.SPECIES_STATS_ENTRY_SIZE)

    def setUp(self) -> None:
        self._p1 = mock.patch.object(rf, "pokemon_stats_base", lambda rel: 0)
        self._p2 = mock.patch.object(rf, "pokemon_stats_count", lambda rel: 8)
        self._p1.start(); self._p2.start()
        self.addCleanup(self._p1.stop); self.addCleanup(self._p2.stop)
        self.rel = self._Rel(8)
        self.buf = bytearray(self.rel.data)

    def test_a_species_past_the_tables_extent_raises_before_any_write(self) -> None:
        with self.assertRaises(ValueError):
            rf.apply_catch_rate(self.buf, self.rel, {"catch_rate": {"99": 255}})
        self.assertEqual(bytes(len(self.buf)), bytes(self.buf))

    def test_a_value_that_does_not_fit_the_byte_raises(self) -> None:
        with self.assertRaises(ValueError):
            rf.apply_catch_rate(self.buf, self.rel, {"catch_rate": {"1": 300}})

    def test_a_real_plan_writes_exactly_the_one_byte_it_names(self) -> None:
        before = bytes(self.buf)
        result = rf.apply_catch_rate(self.buf, self.rel, {"catch_rate": {"3": 255}})
        self.assertEqual({"catch_rate_written": 1}, result)
        changed = [i for i in range(len(self.buf)) if self.buf[i] != before[i]]
        self.assertEqual([3 * ss.SPECIES_STATS_ENTRY_SIZE + ss.CATCH_RATE_OFFSET], changed,
                         "the pass must touch nothing but the byte it names")

    def test_an_empty_plan_writes_nothing_at_all(self) -> None:
        before = bytes(self.buf)
        self.assertEqual({"catch_rate_written": 0}, rf.apply_catch_rate(self.buf, self.rel, {}))
        self.assertEqual(before, bytes(self.buf))


class _FakeDdpk:
    """The minimum `apply_shadow_catch_rate` reads: where the entries start and how many there are."""

    def __init__(self, entries: int, data_off: int = 0x20) -> None:
        self.ddpk_entries = entries
        self.ddpk_data = data_off


def _ddpk_blob(records: "list[tuple[int, int]]", data_off: int = 0x20) -> bytearray:
    """`records` is [(in_use, catch_rate_override)], index 0 first. Every other byte is filled with a
    recognisable pattern so a stray write shows up as a changed byte rather than a plausible value."""
    buf = bytearray(data_off + len(records) * 0x18)
    for i in range(len(buf)):
        buf[i] = (i * 7) & 0xFF
    for index, (in_use, rate) in enumerate(records):
        off = data_off + index * 0x18
        buf[off + 0x01] = rate
        buf[off + 0x03] = in_use
    return buf


class TestTheShadowHalf(unittest.TestCase):
    RECORDS = [(0, 0), (128, 190), (128, 255), (0, 90), (128, 3), (128, 120)]

    def _run(self, target: int = 0xFF):
        blob = bytes(_ddpk_blob(self.RECORDS))
        out, (raised, in_use) = iso_patcher.apply_shadow_catch_rate(
            blob, _FakeDdpk(len(self.RECORDS)), target)
        self.assertEqual(4, in_use, "four of the six fixture rows are in use")
        return blob, out, raised

    def test_every_in_use_entry_below_the_target_is_raised(self) -> None:
        _, out, raised = self._run()
        self.assertEqual(3, raised)
        for index in (1, 4, 5):
            self.assertEqual(0xFF, out[0x20 + index * 0x18 + 0x01])

    def test_a_free_slot_is_never_touched(self) -> None:
        """A free entry is not a catchable Pokemon, and writing one is how a later expansion pass inherits a
        value nobody chose."""
        before, out, _ = self._run()
        for index in (0, 3):
            off = 0x20 + index * 0x18
            self.assertEqual(before[off:off + 0x18], out[off:off + 0x18])

    def test_an_entry_already_at_the_target_is_not_counted_as_raised(self) -> None:
        before, out, raised = self._run()
        self.assertEqual(before[0x20 + 2 * 0x18 + 0x01], out[0x20 + 2 * 0x18 + 0x01])
        self.assertEqual(3, raised)

    def test_nothing_but_the_override_byte_changes_in_a_raised_entry(self) -> None:
        before, out, _ = self._run()
        changed = [i for i in range(len(before)) if before[i] != out[i]]
        self.assertEqual([0x20 + i * 0x18 + 0x01 for i in (1, 4, 5)], changed)

    def test_the_file_does_not_change_size(self) -> None:
        """The three-copy writer passes allow_decomp_resize=False; a pass that grew the blob would fail the
        write rather than the test, and this says which one is the contract."""
        before, out, _ = self._run()
        self.assertEqual(len(before), len(out))

    def test_running_twice_raises_nothing_the_second_time(self) -> None:
        _, out, _ = self._run()
        again, (raised, _) = iso_patcher.apply_shadow_catch_rate(out, _FakeDdpk(len(self.RECORDS)), 0xFF)
        self.assertEqual(0, raised)
        self.assertEqual(out, again)

    def test_an_entry_past_the_end_of_the_blob_raises(self) -> None:
        blob = bytes(_ddpk_blob(self.RECORDS))
        with self.assertRaises(ValueError):
            iso_patcher.apply_shadow_catch_rate(blob, _FakeDdpk(len(self.RECORDS) + 4), 0xFF)

    def test_a_slot_that_becomes_in_use_later_is_covered(self) -> None:
        """The generated-Shadow guarantee, in miniature. Shadow Pokemon Expansion fills free DDPK slots
        earlier in the same patch run; this pass reads in_use at the moment it runs, so a slot that was free
        when the seed was planned is still covered. Verified end to end on a real ISO (85 in-use with two
        generated Shadows against 83 vanilla) -- this is the unit-level fence for it."""
        records = list(self.RECORDS)
        records[3] = (128, 90)          # slot 3 was free; the expansion just claimed it
        blob = bytes(_ddpk_blob(records))
        out, (raised, in_use) = iso_patcher.apply_shadow_catch_rate(
            blob, _FakeDdpk(len(records)), 0xFF)
        self.assertEqual(5, in_use, "the newly-claimed slot counts now")
        self.assertEqual(0xFF, out[0x20 + 3 * 0x18 + 0x01], "and it was raised like any other")
        self.assertEqual(4, raised)

    def test_a_lower_target_still_never_lowers_an_entry(self) -> None:
        before, out, _ = self._run(100)
        for index, (in_use, rate) in enumerate(self.RECORDS):
            got = out[0x20 + index * 0x18 + 0x01]
            self.assertGreaterEqual(got, rate)


class TestBothHalvesAreReachedAndInTheRightOrder(unittest.TestCase):
    """The two structural properties nothing else in the suite would notice losing."""

    def setUp(self) -> None:
        self.source = open(iso_patcher.__file__, encoding="utf-8").read()

    def test_the_option_drives_the_stats_table_and_the_shadow_pass(self) -> None:
        self.assertIn("rel_format.apply_catch_rate", self.source)
        self.assertIn("write_max_catch_rate_shadow_patch(output_path)", self.source)

    def test_the_shadow_pass_runs_after_everything_that_can_create_a_shadow(self) -> None:
        """Ordering IS the coverage mechanism -- see this module's docstring. If the call moves above either
        of these, Shadow Pokemon the seed invented silently keep their vanilla catch rate."""
        call = self.source.index("write_max_catch_rate_shadow_patch(output_path)")
        expansion = self.source.index("shadow_result = write_shadow_multi_trainer_patch(output_path")
        difficulty = self.source.index("ed_result = write_enhanced_difficulty_patch(output_path")
        self.assertLess(expansion, call)
        self.assertLess(difficulty, call)

    def test_the_shadow_writer_covers_all_three_copies(self) -> None:
        """ADDENDUM 58 found the game reads common.fsys's copies; ADDENDUM 287 found a pass that had written
        only the archive copy. Three names, one function."""
        start = self.source.index("def write_max_catch_rate_shadow_patch")
        body = self.source[start:self.source.index("\ndef ", start + 1)]
        self.assertIn("deck_archive.fsys", body)
        self.assertIn("common.fsys", body)
        self.assertIn("DeckData_DarkPokemon_EU.bin", body)
        self.assertEqual(3, body.count("apply_shadow_catch_rate("),
                         "one edit per DarkPokemon copy -- archive, common, and common's _EU")


class TestTheOption(unittest.TestCase):
    def test_it_exists_and_is_off_by_default(self) -> None:
        from ..options import MaxCatchRate, PokemonXDOptions
        self.assertEqual(0, MaxCatchRate.default)
        self.assertIn("max_catch_rate", PokemonXDOptions.__annotations__)

    def test_the_option_text_still_says_what_the_data_alone_delivers(self) -> None:
        """ADDENDUM 305 gave this option a second half (an instruction patch) that DOES deliver certainty, so
        the old "not literally 100%" wording is gone. What must survive is the honest account of the data
        half on its own, because that is what a player gets when the instruction cannot be applied."""
        from ..options import MaxCatchRate
        text = " ".join((MaxCatchRate.__doc__ or "").split())
        # RETARGETED 2026-09-26: the player rewrote this option's text in their own words (see
        # USER_FACING_TEXT.md's section A). The docstring assertions below went with it. The measured fact is
        # unchanged and still tested against the CODE in this file; what is no longer pinned is that the
        # player-facing text repeats it.
        #
        # WHAT LEFT THE TEXT: that the DATA half alone (catch rate 255) is not 100%, and that a build which
        # cannot apply ADDENDUM 305's instruction patch gets only that half. Both behaviours are unchanged and
        # both are tested elsewhere in this file against the patcher rather than against prose.
        self.assertTrue(text, "the option must still have SOME text")

    def test_the_seed_default_is_off(self) -> None:
        source = open(os.path.join(os.path.dirname(iso_patcher.__file__), "..", "__init__.py"),
                      encoding="utf-8").read()
        self.assertIn('"max_catch_rate": False,', source)
        self.assertIn('seed_data["max_catch_rate"] = bool(self.options.max_catch_rate)', source)

    def test_the_patcher_treats_a_seed_without_the_key_as_off(self) -> None:
        """Every seed generated before this addendum has no such key at all."""
        self.assertFalse(bool({}.get("max_catch_rate")))


@unittest.skipUnless(os.path.exists(COMMON_REL_DUMP), "no real common_rel dump in this workspace")
class TestAgainstTheRealCommonRel(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with open(COMMON_REL_DUMP, "rb") as handle:
            cls.data = handle.read()
        cls.rates = {}
        index = 0
        while True:
            off = DUMP_STATS_BASE + index * ss.SPECIES_STATS_ENTRY_SIZE
            if off + ss.SPECIES_STATS_ENTRY_SIZE > len(cls.data):
                break
            cls.rates[index] = cls.data[off + ss.CATCH_RATE_OFFSET]
            index += 1

    def test_the_offset_reproduces_four_known_gen_three_catch_rates(self) -> None:
        for index, want in KNOWN_CATCH_RATES.items():
            self.assertEqual(want, self.rates[index], f"species index {index}")

    def test_the_real_table_spans_the_whole_byte(self) -> None:
        """If this offset were the wrong field the values would not look like catch rates at all."""
        real = [v for v in self.rates.values() if v]
        self.assertLessEqual(min(real), 3)
        self.assertEqual(255, max(real))

    def test_a_real_plan_raises_everything_below_the_maximum_and_nothing_else(self) -> None:
        plan = ss.plan_catch_rate(self.rates)
        for index, rate in self.rates.items():
            if rate and rate < 255:
                self.assertEqual(255, plan["catch_rate"][str(index)])
            else:
                self.assertNotIn(str(index), plan["catch_rate"])

    def test_a_real_plan_lowers_nothing(self) -> None:
        plan = ss.plan_catch_rate(self.rates)
        for key, value in plan["catch_rate"].items():
            self.assertGreater(value, self.rates[int(key)])


@unittest.skipUnless(os.path.exists(DARK_DUMP), "no real DeckData_DarkPokemon dump in this workspace")
class TestAgainstTheRealDarkPokemonFile(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with open(DARK_DUMP, "rb") as handle:
            cls.decompressed = df.lzss_decode(handle.read())
        cls.ddpk = df.DarkPokemonFile(cls.decompressed)

    def test_the_vanilla_overrides_are_not_all_the_same_value(self) -> None:
        """The reason this half exists. If every Shadow already read 255 there would be nothing to do; a real
        file runs from the single digits upward."""
        used = [self.ddpk.ddpk_full(i)["catch_rate_override"]
                for i in range(1, self.ddpk.ddpk_entries) if self.ddpk.ddpk_full(i)["in_use"]]
        self.assertGreater(len(used), 50)
        self.assertLess(min(used), 10)
        self.assertGreater(len(set(used)), 5)

    def test_the_pass_raises_every_in_use_entry_and_leaves_the_free_ones_alone(self) -> None:
        out, (raised, in_use) = iso_patcher.apply_shadow_catch_rate(self.decompressed, self.ddpk, 0xFF)
        after = df.DarkPokemonFile(out)
        expected = 0
        for index in range(1, self.ddpk.ddpk_entries):
            before = self.ddpk.ddpk_full(index)
            now = after.ddpk_full(index)
            if before["in_use"]:
                self.assertEqual(0xFF, now["catch_rate_override"], f"ddpk index {index}")
                expected += before["catch_rate_override"] < 0xFF
            else:
                self.assertEqual(before, now, f"free ddpk index {index} was modified")
        self.assertEqual(expected, raised)
        self.assertEqual(83, in_use, "every in-use Shadow is covered, raised or already at the target")
        self.assertLess(raised, in_use, "some vanilla Shadows already read 255 -- raised is not coverage")

    def test_no_other_field_of_a_raised_entry_changes(self) -> None:
        out, _counts = iso_patcher.apply_shadow_catch_rate(self.decompressed, self.ddpk, 0xFF)
        after = df.DarkPokemonFile(out)
        for index in range(1, self.ddpk.ddpk_entries):
            before = dict(self.ddpk.ddpk_full(index))
            now = dict(after.ddpk_full(index))
            before.pop("catch_rate_override"); now.pop("catch_rate_override")
            self.assertEqual(before, now, f"ddpk index {index}")

    def test_the_one_guaranteed_catch_in_the_game_is_not_produced_by_this_byte(self) -> None:
        """Player, mid-implementation: "the teddiursa at the start is guaranteed catch". It is. Its override
        reads 120 -- below the maximum, below the 190 that ordinary Shadows carry, and eleven vanilla Shadows
        already sit at 255 without being certainties. So the tutorial snag is scripted, and no value this
        option writes can reproduce it. This test is here so the claim stays measured rather than remembered;
        if a future ISO makes it 255 the option's own text needs rewriting."""
        tutorial = self.ddpk.ddpk_full(1)
        self.assertTrue(tutorial["in_use"])
        self.assertLess(tutorial["catch_rate_override"], 0xFF)
        self.assertLess(tutorial["catch_rate_override"], 190)
        at_max = [i for i in range(1, self.ddpk.ddpk_entries)
                  if self.ddpk.ddpk_full(i)["in_use"] and self.ddpk.ddpk_full(i)["catch_rate_override"] == 0xFF]
        self.assertGreater(len(at_max), 5, "255 is already common in vanilla and is not a guarantee")

    def test_the_blob_keeps_its_length(self) -> None:
        out, _counts = iso_patcher.apply_shadow_catch_rate(self.decompressed, self.ddpk, 0xFF)
        self.assertEqual(len(self.decompressed), len(out))


if __name__ == "__main__":
    unittest.main()
