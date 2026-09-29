"""ADDENDUM 349 (2026-09-25) -- Eevee lost levels when it evolved.

Player: "Users and myself experienced eevee losing levels upon evolution."

A Pokemon's level is DERIVED from its experience total through its species' experience curve. Change the
curve and the same experience reads as a different level -- which is what the player saw, at the exact moment
the species changed.

Measured against the real stats table before the fix, at the shipped option values:

    rate 250%   Eevee Medium Fast -> Vaporeon Erratic    -3 -4 -4 -4 -3  0 +2   (evolving at L15..L60)
    rate 400%   Eevee Fast        -> Vaporeon Erratic    -4 -5 -6 -6 -7 -6 -3

and up to 111 of the game's 122 level-up evolution pairs ended up straddling two curves, worst case -9.

TWO INDEPENDENT DEFECTS, and the tests below are split the same way.

1. The curve was chosen PER SPECIES, from that species' own shortfall after the base-exp byte clamped at 255.
   Eevee's base exp is 92 and never clamps, so it got no curve; Vaporeon's is 196 and clamps at once, so it
   did. Nothing tied an evolution family together -- and `evolution_data.py` could not have, because it is
   deliberately level-up evolutions only and Eevee's five are stone/friendship.

2. "Fastest" was ranked by total-to-100, which called Erratic 1.67x faster than Medium Fast. Erratic needs
   `n^3*(100-n)/50` below level 50, which is MORE than Medium Fast's `n^3` for every level under 50. It is
   slower for the entire early and mid game, and the old ranking picked it for five of the six source curves.
"""
from __future__ import annotations

import unittest

from ..game_data import species_stats as ss

FAMILY_CURVE = ss.EXP_RATE_MEDIUM_FAST          # Eevee and all five Eeveelutions, in the real table
EEVEE_BASE_EXP = 92                             # measured from a263_commonrel.bin
EEVEELUTION_BASE_EXP = 196                      # Vaporeon; Jolteon/Flareon/Espeon/Umbreon are 197/198/197/197


class TestTheCurveFormulas(unittest.TestCase):
    """The domination table is derived from these, so they have to be right."""

    def test_medium_fast_is_the_cube(self):
        for n in (2, 25, 50, 100):
            self.assertEqual(n ** 3, ss.exp_total_at_level(ss.EXP_RATE_MEDIUM_FAST, n))

    def test_every_curve_reaches_its_documented_total_at_100(self):
        for curve, total in ss.EXP_RATE_TOTAL_TO_100.items():
            self.assertAlmostEqual(total, ss.exp_total_at_level(curve, 100), delta=total * 0.001,
                                   msg=ss.EXP_RATE_NAMES[curve])

    def test_erratic_is_slower_than_medium_fast_below_fifty(self):
        """The fact the old ranking missed, and the whole reason defect 2 existed."""
        for n in range(2, 50):
            self.assertGreater(ss.exp_total_at_level(ss.EXP_RATE_ERRATIC, n),
                               ss.exp_total_at_level(ss.EXP_RATE_MEDIUM_FAST, n), f"level {n}")

    def test_erratic_is_faster_at_a_hundred(self):
        """Which is why total-to-100 ranked it first. Both facts are true; only one was used."""
        self.assertLess(ss.exp_total_at_level(ss.EXP_RATE_ERRATIC, 100),
                        ss.exp_total_at_level(ss.EXP_RATE_MEDIUM_FAST, 100))

    def test_level_at_exp_inverts_exp_total_at_level(self):
        for curve in ss.EXP_RATE_TOTAL_TO_100:
            for n in range(2, 101):
                self.assertEqual(n, ss.level_at_exp(curve, ss.exp_total_at_level(curve, n)),
                                 f"{ss.EXP_RATE_NAMES[curve]} level {n}")


class TestOnlySafeReplacementsSurvive(unittest.TestCase):
    def test_a_replacement_is_never_more_expensive_at_any_level(self):
        """The safety property itself: if this holds, no Pokemon can lose a level by changing curve."""
        for current, options in ss.SAFE_CURVE_REPLACEMENTS.items():
            for replacement in options:
                for n in range(2, 101):
                    self.assertLessEqual(ss.exp_total_at_level(replacement, n),
                                         ss.exp_total_at_level(current, n),
                                         f"{ss.EXP_RATE_NAMES[current]} -> "
                                         f"{ss.EXP_RATE_NAMES[replacement]} at level {n}")

    def test_erratic_is_never_offered_as_a_replacement(self):
        for current, options in ss.SAFE_CURVE_REPLACEMENTS.items():
            self.assertNotIn(ss.EXP_RATE_ERRATIC, options, ss.EXP_RATE_NAMES[current])

    def test_exactly_three_transitions_exist(self):
        """Stated as a number so that widening it is a deliberate act with a test to update."""
        pairs = {(a, b) for a, opts in ss.SAFE_CURVE_REPLACEMENTS.items() for b in opts}
        self.assertEqual({(ss.EXP_RATE_MEDIUM_FAST, ss.EXP_RATE_FAST),
                          (ss.EXP_RATE_SLOW, ss.EXP_RATE_MEDIUM_FAST),
                          (ss.EXP_RATE_SLOW, ss.EXP_RATE_FAST)}, pairs)

    def test_best_curve_within_never_moves_anything_to_erratic(self):
        """An Erratic species stays Erratic -- that is "unchanged", not a selection. What must never happen
        is a species being MOVED onto it."""
        for current in ss.EXP_RATE_TOTAL_TO_100:
            if current == ss.EXP_RATE_ERRATIC:
                self.assertEqual(current, ss.best_curve_within(current, 99.0), "Erratic has no replacement")
                continue
            self.assertNotEqual(ss.EXP_RATE_ERRATIC, ss.best_curve_within(current, 99.0),
                                ss.EXP_RATE_NAMES[current])


class TestAFamilyIsNeverSplit(unittest.TestCase):
    """Defect 1. The planner must decide a curve per SOURCE CURVE, not per species."""

    def _eevee_line(self):
        return {133: (EEVEE_BASE_EXP, FAMILY_CURVE),
                134: (EEVEELUTION_BASE_EXP, FAMILY_CURVE),
                135: (197, FAMILY_CURVE), 136: (198, FAMILY_CURVE),
                196: (197, FAMILY_CURVE), 197: (197, FAMILY_CURVE)}

    def test_eevee_and_its_evolutions_always_end_on_one_curve(self):
        line = self._eevee_line()
        for rate in range(100, 501, 25):
            plan = ss.plan_experience_rate(line, rate)
            curves = {int(plan["exp_rate"].get(str(i), line[i][1])) for i in line}
            self.assertEqual(1, len(curves), f"rate {rate} split the Eevee line across {curves}")

    def test_evolving_never_changes_the_level_at_any_rate_or_level(self):
        """THE PLAYER'S BUG, stated directly."""
        line = self._eevee_line()
        for rate in range(100, 501, 25):
            plan = ss.plan_experience_rate(line, rate)
            eevee = int(plan["exp_rate"].get("133", FAMILY_CURVE))
            vaporeon = int(plan["exp_rate"].get("134", FAMILY_CURVE))
            for level in range(2, 101):
                got = ss.level_at_exp(vaporeon, ss.exp_total_at_level(eevee, level))
                self.assertEqual(level, got, f"rate {rate}: evolving at L{level} became L{got}")

    def test_two_species_sharing_a_curve_still_share_one(self):
        """The general rule, not just Eevee -- one species per base-exp value across the whole byte range."""
        species = {i: (base, ss.EXP_RATE_MEDIUM_FAST) for i, base in enumerate(range(20, 256, 5))}
        for rate in (150, 200, 250, 300, 400, 500):
            plan = ss.plan_experience_rate(species, rate)
            curves = {int(plan["exp_rate"].get(str(i), ss.EXP_RATE_MEDIUM_FAST)) for i in species}
            self.assertEqual(1, len(curves), f"rate {rate} split a single vanilla curve group")

    def test_no_vanilla_curve_group_is_ever_split(self):
        species = {}
        idx = 0
        for curve in ss.EXP_RATE_TOTAL_TO_100:
            for base in (20, 92, 140, 196, 255):
                species[idx] = (base, curve)
                idx += 1
        for rate in (110, 150, 200, 250, 300, 400, 500):
            plan = ss.plan_experience_rate(species, rate)
            by_source = {}
            for i, (_b, c) in species.items():
                by_source.setdefault(c, set()).add(int(plan["exp_rate"].get(str(i), c)))
            for source, landed in by_source.items():
                self.assertEqual(1, len(landed),
                                 f"rate {rate} split {ss.EXP_RATE_NAMES[source]} across {landed}")


class TestItStillDeliversAndStillNeverSlowsAnythingDown(unittest.TestCase):
    def test_rate_one_hundred_still_writes_nothing(self):
        species = {1: (92, ss.EXP_RATE_MEDIUM_FAST), 2: (196, ss.EXP_RATE_SLOW)}
        plan = ss.plan_experience_rate(species, 100)
        self.assertEqual({}, plan["base_exp"])
        self.assertEqual({}, plan["exp_rate"])

    def test_a_higher_rate_delivers_more(self):
        species = {i: (base, ss.EXP_RATE_MEDIUM_FAST) for i, base in enumerate((40, 92, 140, 196, 255))}
        seen = [ss.plan_experience_rate(species, r)["achieved_mean"] for r in (100, 150, 200, 300, 500)]
        self.assertEqual(seen, sorted(seen))
        self.assertGreater(seen[-1], 2.0)

    def test_base_exp_is_never_lowered_below_vanilla(self):
        species = {i: (base, curve) for i, (base, curve)
                   in enumerate([(92, ss.EXP_RATE_MEDIUM_FAST), (255, ss.EXP_RATE_MEDIUM_FAST),
                                 (140, ss.EXP_RATE_SLOW), (40, ss.EXP_RATE_FAST)])}
        for rate in (110, 150, 200, 300, 500):
            plan = ss.plan_experience_rate(species, rate)
            for key, value in plan["base_exp"].items():
                self.assertGreaterEqual(value, species[int(key)][0],
                                        f"rate {rate} lowered species {key}'s base experience")

    def test_the_curve_does_not_also_push_base_exp_past_the_request(self):
        """The curve is free for a species that was not going to clamp, so the byte is asked for less."""
        species = {1: (40, ss.EXP_RATE_MEDIUM_FAST)}
        plan = ss.plan_experience_rate(species, 200)
        self.assertLessEqual(plan["achieved_max"], 2.0 + 0.05)


if __name__ == "__main__":
    unittest.main()
