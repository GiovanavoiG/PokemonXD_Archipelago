"""ADDENDUM 285 (2026-09-19) -- the experience rate, and the byte that caps it.

Player: "I still feel as though I'm receiving really low xp for defeating things - are there any fields in the
structs for trainer pokemon that we don't know the meaning of?" then "let's make an exp rate option for normal
or scaled exp - allow options between 1 and 5x - can we use decimals?"

THE ANSWER TO THE FIRST QUESTION IS NO, AND THAT IS WHY THE SECOND ONE NEEDED A HUNT. The DPKM record is 32
bytes and all 32 are named -- censused against every one of the 823 records in a real DeckData_Story.bin with
zero unnamed bytes carrying data. Experience is a property of the SPECIES. This file covers the two bytes that
carry it, located as `game_data/species_stats.py` describes and confirmed against pokemon-ngc-rando's own
`XDPokemon.cs`.

THE TESTS THAT MATTER MOST ARE THE ONES THAT SAY WHAT CANNOT HAPPEN:
  * at 100 nothing is written at all -- not "the same values written back";
  * no base-experience value is ever lowered and no levelling curve is ever made slower;
  * nothing is ever written outside the table's own declared extent;
  * and an unproven table is refused rather than written to.

The dump-backed class at the end re-derives the whole feature from the player's real `common_rel` on every run
where that dump is present, and skips (not silently passes) where it is not -- the ADDENDUM 239 standard.
"""
import os
import unittest

from ..game_data import species_stats as ss

DUMP = "/mnt/user-data/uploads/PokemonXD-working/bridge/dumps/a263_commonrel.bin"
#: Located by requiring 22 species to agree on the recorded base-HP offset. See the module docstring.
DUMP_STATS_BASE = 0x29DA8


def _fake_species(n: int = 40) -> "dict[int, tuple[int, int]]":
    """A spread that exercises both levers: values that can be multiplied and values already at the cap."""
    out = {}
    for i in range(1, n + 1):
        base = 20 + (i * 6) % 236          # 20..255
        rate = i % 6
        out[i] = (base, rate)
    out[n + 1] = (255, ss.EXP_RATE_FAST)   # a Chansey: no headroom in the byte at all
    return out


class TestTheLayoutIsWrittenDown(unittest.TestCase):
    def test_the_two_experience_offsets(self) -> None:
        self.assertEqual(0x00, ss.EXP_RATE_OFFSET)
        self.assertEqual(0x05, ss.BASE_EXP_OFFSET)
        self.assertEqual(0x124, ss.SPECIES_STATS_ENTRY_SIZE)

    def test_base_exp_is_a_byte_and_the_module_says_so(self) -> None:
        """The whole reason the curve lever exists. If this ever becomes a u16 the planner should be
        revisited, not silently left clamping."""
        self.assertEqual(0xFF, ss.BASE_EXP_MAX)

    def test_all_six_curves_have_a_total_and_a_name(self) -> None:
        self.assertEqual(6, len(ss.EXP_RATE_TOTAL_TO_100))
        self.assertEqual(set(ss.EXP_RATE_TOTAL_TO_100), set(ss.EXP_RATE_NAMES))

    def test_erratic_is_the_fastest_and_fluctuating_the_slowest(self) -> None:
        totals = ss.EXP_RATE_TOTAL_TO_100
        self.assertEqual(ss.EXP_RATE_ERRATIC, min(totals, key=totals.get))
        self.assertEqual(ss.EXP_RATE_FLUCTUATING, max(totals, key=totals.get))


class TestOneHundredWritesNothing(unittest.TestCase):
    """ADDENDUM 169's rule: an option that is off touches nothing. Not 'writes the same value back'."""

    def test_the_plan_is_empty(self) -> None:
        plan = ss.plan_experience_rate(_fake_species(), 100)
        self.assertEqual({}, plan["base_exp"])
        self.assertEqual({}, plan["exp_rate"])
        self.assertEqual(1.0, plan["achieved_mean"])

    def test_describe_says_vanilla(self) -> None:
        self.assertIn("vanilla", ss.describe_plan(ss.plan_experience_rate(_fake_species(), 100)))


class TestNothingIsEverMadeWorse(unittest.TestCase):
    def test_no_base_exp_is_lowered_at_any_rate(self) -> None:
        species = _fake_species()
        for rate in range(100, 501, 7):
            plan = ss.plan_experience_rate(species, rate)
            for key, value in plan["base_exp"].items():
                self.assertGreater(value, species[int(key)][0], f"rate {rate} lowered species {key}")

    def test_no_curve_is_ever_made_slower(self) -> None:
        species = _fake_species()
        for rate in range(100, 501, 7):
            plan = ss.plan_experience_rate(species, rate)
            for key, value in plan["exp_rate"].items():
                was = species[int(key)][1]
                self.assertGreater(ss.curve_speedup(was, value), 1.0,
                                   f"rate {rate} moved species {key} to a slower curve")

    def test_no_base_exp_exceeds_the_byte(self) -> None:
        for rate in (150, 250, 500):
            for value in ss.plan_experience_rate(_fake_species(), rate)["base_exp"].values():
                self.assertLessEqual(value, 0xFF)
                self.assertGreaterEqual(value, 0)

    def test_every_written_group_is_one_of_the_games_six(self) -> None:
        for value in ss.plan_experience_rate(_fake_species(), 500)["exp_rate"].values():
            self.assertIn(value, ss.EXP_RATE_TOTAL_TO_100)


class TestTheCurveIsOnlyAskedForTheShortfall(unittest.TestCase):
    def test_a_species_the_byte_can_satisfy_keeps_its_vanilla_curve(self) -> None:
        """20 * 2 = 40, comfortably inside the byte, so nothing should touch its levelling curve."""
        plan = ss.plan_experience_rate({1: (20, ss.EXP_RATE_MEDIUM_SLOW)}, 200)
        self.assertEqual({"1": 40}, plan["base_exp"])
        self.assertEqual({}, plan["exp_rate"])
        self.assertAlmostEqual(2.0, plan["achieved_mean"], places=6)

    def test_a_capped_species_gets_the_curve_instead(self) -> None:
        """A Chansey cannot give out more than 255, so the only lever left is how fast the PLAYER levels.

        RETARGETED BY ADDENDUM 349. This used to use a Fast species, on the old reading that every group had
        a faster group available. Fast has no replacement that is faster at every level, so it now correctly
        gets none -- the premise needs a group that does, and Medium Fast is the one the game's own Eevee line
        uses."""
        plan = ss.plan_experience_rate({1: (255, ss.EXP_RATE_MEDIUM_FAST)}, 500)
        self.assertEqual({}, plan["base_exp"], "255 is already the maximum -- nothing to write")
        self.assertEqual(ss.EXP_RATE_FAST, plan["exp_rate"]["1"])
        self.assertGreater(plan["achieved_mean"], 1.0)

    def test_a_group_with_no_safe_replacement_gets_no_curve(self) -> None:
        """The other half of the same correction, stated rather than implied."""
        plan = ss.plan_experience_rate({1: (255, ss.EXP_RATE_FAST)}, 500)
        self.assertEqual({}, plan["exp_rate"])

    def test_the_curve_never_overshoots_the_request(self) -> None:
        """Asking for 1.10x must not buy a 1.77x curve. Overshooting is not free -- it is a levelling change
        the player did not ask for."""
        for base, rate in ((100, ss.EXP_RATE_SLOW), (255, ss.EXP_RATE_FLUCTUATING)):
            plan = ss.plan_experience_rate({1: (base, rate)}, 110)
            self.assertLessEqual(plan["achieved_max"], 1.10 + 1e-9, f"{base}/{rate} overshot")

    def test_best_curve_within_a_budget_below_one_changes_nothing(self) -> None:
        for group in ss.EXP_RATE_TOTAL_TO_100:
            self.assertEqual(group, ss.best_curve_within(group, 0.5))
            self.assertEqual(group, ss.best_curve_within(group, 1.0))

    def test_an_unknown_group_is_left_alone_rather_than_guessed(self) -> None:
        self.assertEqual(99, ss.best_curve_within(99, 5.0))
        self.assertEqual(1.0, ss.curve_speedup(99, ss.EXP_RATE_ERRATIC))


class TestMonotonicity(unittest.TestCase):
    def test_a_higher_rate_never_delivers_less(self) -> None:
        species = _fake_species()
        last = 0.0
        for rate in range(100, 501, 10):
            mean = ss.plan_experience_rate(species, rate)["achieved_mean"]
            self.assertGreaterEqual(mean + 1e-9, last, f"rate {rate} delivered less than the rate below it")
            last = mean

    def test_out_of_range_rates_are_clamped_not_rejected(self) -> None:
        self.assertEqual(100, ss.plan_experience_rate(_fake_species(), 50)["rate_percent"])
        self.assertEqual(ss.RATE_MAX, ss.plan_experience_rate(_fake_species(), 9000)["rate_percent"])


class TestTheWriterRefusesRatherThanGuessing(unittest.TestCase):
    """`apply_experience_rate`'s own bounds, the ADDENDUM 268 rule applied to a second table."""

    class _Rel:
        def __init__(self, count: int, base: int = 0) -> None:
            self._count = count
            self._base = base
            self.data = bytearray(base + count * ss.SPECIES_STATS_ENTRY_SIZE)

    def _patched(self, count: int = 8):
        from ..tools import xd_rel_format as rf
        rel = self._Rel(count)
        buf = bytearray(rel.data)
        return rf, rel, buf

    def setUp(self) -> None:
        from unittest import mock
        from ..tools import xd_rel_format as rf
        self._p1 = mock.patch.object(rf, "pokemon_stats_base", lambda rel: 0)
        self._p2 = mock.patch.object(rf, "pokemon_stats_count", lambda rel: 8)
        self._p1.start(); self._p2.start()
        self.addCleanup(self._p1.stop); self.addCleanup(self._p2.stop)

    def test_a_species_past_the_tables_extent_raises_before_any_write(self) -> None:
        rf, rel, buf = self._patched()
        with self.assertRaises(ValueError):
            rf.apply_experience_rate(buf, rel, {"base_exp": {"99": 200}, "exp_rate": {}})

    def test_a_value_that_does_not_fit_the_byte_raises(self) -> None:
        rf, rel, buf = self._patched()
        with self.assertRaises(ValueError):
            rf.apply_experience_rate(buf, rel, {"base_exp": {"1": 300}, "exp_rate": {}})

    def test_a_group_the_game_does_not_have_raises(self) -> None:
        rf, rel, buf = self._patched()
        with self.assertRaises(ValueError):
            rf.apply_experience_rate(buf, rel, {"base_exp": {}, "exp_rate": {"1": 9}})

    def test_a_real_plan_writes_exactly_the_two_bytes_it_names(self) -> None:
        rf, rel, buf = self._patched()
        before = bytes(buf)
        result = rf.apply_experience_rate(
            buf, rel, {"base_exp": {"3": 200}, "exp_rate": {"3": ss.EXP_RATE_ERRATIC}}
        )
        self.assertEqual({"base_exp_written": 1, "exp_rate_written": 1}, result)
        entry = 3 * ss.SPECIES_STATS_ENTRY_SIZE
        self.assertEqual(200, buf[entry + ss.BASE_EXP_OFFSET])
        self.assertEqual(ss.EXP_RATE_ERRATIC, buf[entry + ss.EXP_RATE_OFFSET])
        changed = [i for i in range(len(buf)) if buf[i] != before[i]]
        self.assertEqual(sorted(changed),
                         sorted([entry + ss.BASE_EXP_OFFSET, entry + ss.EXP_RATE_OFFSET]),
                         "the pass must touch nothing but the two bytes it names")

    def test_an_unproven_table_is_refused(self) -> None:
        rf, rel, _ = self._patched()
        # Every base-HP byte in this synthetic table is zero, so nothing can agree.
        self.assertFalse(rf.verify_species_stats_table(rel, {1: 45, 4: 39}, {1: 1, 4: 4}))

    def test_agreement_below_the_threshold_is_not_enough(self) -> None:
        """One coincidental match proves nothing -- the evidence has to be many species at once."""
        rf, rel, _ = self._patched()
        rel.data[1 * ss.SPECIES_STATS_ENTRY_SIZE + ss.BASE_HP_OFFSET] = 45
        self.assertFalse(rf.verify_species_stats_table(rel, {1: 45}, {1: 1}))


class TestAgainstTheRealCommonRel(unittest.TestCase):
    """Re-derived from the player's own `common_rel` dump on every run where it is present."""

    @classmethod
    def setUpClass(cls) -> None:
        if not os.path.exists(DUMP):
            raise unittest.SkipTest("a263_commonrel.bin not available")
        with open(DUMP, "rb") as handle:
            cls.data = handle.read()
        cls.species = {}
        for index in range(1, 415):
            off = DUMP_STATS_BASE + index * ss.SPECIES_STATS_ENTRY_SIZE
            cls.species[index] = (cls.data[off + ss.BASE_EXP_OFFSET], cls.data[off + ss.EXP_RATE_OFFSET])

    def test_the_offset_reproduces_known_base_experience_yields(self) -> None:
        """The evidence the offset is right at all: Gen III yields nobody could hit by coincidence."""
        known = {1: 64, 4: 65, 7: 66, 25: 82, 113: 255, 129: 20, 143: 154, 150: 220, 202: 177, 213: 80}
        for index, expected in known.items():
            self.assertEqual(expected, self.species[index][0], f"internal index {index}")

    def test_the_curve_offset_reproduces_known_experience_groups(self) -> None:
        known = {1: ss.EXP_RATE_MEDIUM_SLOW, 25: ss.EXP_RATE_MEDIUM_FAST, 113: ss.EXP_RATE_FAST,
                 129: ss.EXP_RATE_SLOW, 150: ss.EXP_RATE_SLOW}
        for index, expected in known.items():
            self.assertEqual(expected, self.species[index][1], f"internal index {index}")

    def test_every_real_group_is_one_of_the_six(self) -> None:
        for index, (base, group) in self.species.items():
            if base:
                self.assertIn(group, ss.EXP_RATE_TOTAL_TO_100, f"internal index {index}")

    def test_the_real_ceiling_is_recorded_honestly(self) -> None:
        """The number the option's docstring quotes. If the data ever disagrees, the doc is wrong."""
        plan = ss.plan_experience_rate(self.species, 500)
        # ADDENDUM 349 moved this number, and moving it was the point. The old bound (3.0 < mean < 4.5) was
        # only reachable by counting Erratic as 1.67x faster than Medium Fast, which it is not below level 50.
        self.assertGreater(plan["achieved_mean"], 2.4)
        self.assertLess(plan["achieved_mean"], 3.0, "5x is not reachable; do not claim it is")

    def test_the_table_lever_alone_still_stops_short_of_three(self) -> None:
        """ADDENDUM 384 raised the option's ceiling, not the tables'. Asked for the new maximum with
        no divisor help, the real species table still runs out in the same place it always did."""
        plan = ss.plan_experience_rate(self.species, ss.RATE_MAX)
        self.assertLess(plan["achieved_mean"], 3.0, "the tables cannot do this alone; the divisor does")

    def test_a_doubled_rate_really_doubles_for_most_species(self) -> None:
        plan = ss.plan_experience_rate(self.species, 200)
        self.assertGreater(plan["achieved_mean"], 1.7)

    def test_the_real_plan_never_lowers_anything(self) -> None:
        for rate in (150, 300, 500):
            plan = ss.plan_experience_rate(self.species, rate)
            for key, value in plan["base_exp"].items():
                self.assertGreater(value, self.species[int(key)][0])
            for key, value in plan["exp_rate"].items():
                self.assertGreater(ss.curve_speedup(self.species[int(key)][1], value), 1.0)


class TestTheOption(unittest.TestCase):
    def test_it_exists_with_the_players_range_and_a_vanilla_default(self) -> None:
        from ..options import ExperienceRate, PokemonXDOptions
        self.assertEqual(100, ExperienceRate.range_start)
        # ADDENDUM 384 raised the ceiling from 500 to 1000. The old ceiling was set by the byte lever
        # alone; the divisor patch carries the first 7x exactly, so the tables only cover the remainder.
        self.assertEqual(1000, ExperienceRate.range_end)
        self.assertEqual(100, ExperienceRate.default)
        self.assertIn("experience_rate", PokemonXDOptions.__annotations__)

    def test_the_percent_encoding_is_stated_once(self) -> None:
        self.assertEqual(100, ss.RATE_SCALE)
        from ..options import ExperienceRate
        self.assertEqual(ss.RATE_MIN, ExperienceRate.range_start)
        self.assertEqual(ss.RATE_MAX, ExperienceRate.range_end)

    def test_the_docstring_does_not_promise_what_it_cannot_deliver(self) -> None:
        """The option must not claim a multiplier the code cannot reach.

        ADDENDUM 349 moved the honest number for the TABLE lever from "about 4x" to "about 2.6x":
        the old figure counted Erratic as a 1.67x speed-up when it is slower than Medium Fast below
        level 50. That claim is asserted ABSENT as well, so reinstating it fails here rather than in
        someone's game.

        RETARGETED 2026-09-26: the player rewrote this option's text in their own words (see
        USER_FACING_TEXT.md's section A), so what is pinned here is the CODE's ceiling, not the prose.

        ADDENDUM 384: the ceiling moved because the lever changed. The divisor in the game's own
        formula (base x level / 7) is now patched in main.dol, which is exact up to 7x, and the
        species tables cover only what is left. 1000 lands at about 991%; past that the gap opens.
        """
        from ..options import ExperienceRate
        from ..randomizer import enhanced_difficulty  # noqa: F401 -- the module that owns the ceiling

        self.assertLessEqual(ExperienceRate.range_end, ss.RATE_MAX)
        text = " ".join((ExperienceRate.__doc__ or "").split())
        self.assertNotIn("roughly 4x", text,
                         "ADDENDUM 349's correction must not come back, whoever writes the text")

if __name__ == "__main__":
    unittest.main()
