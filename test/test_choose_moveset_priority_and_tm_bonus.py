"""Regression coverage for ADDENDUM 100's rework of `team_shuffle.choose_moveset()` (player request: "for
moves - prioritize their latest damaging moves from levelups. Above level 30, teach them one strong TM
attacking move that they could learn (anything 80 BP or above that isn't the same type as attacking moves
they already have)."). Exercises `choose_moveset` directly with small synthetic learnsets -- the same
"fully testable with synthetic data" approach `team_shuffle.py`'s own module docstring describes -- rather
than a real species/ISO learnset, since only the selection LOGIC is under test here."""
from __future__ import annotations

import random
import unittest

from ..game_data.move_data import MOVE_TYPES, TM_ATTACKING_MOVES
from ..randomizer.team_shuffle import STATUS_MOVE_IDS, choose_moveset, move_power, species_move_compat

# Real move ids used across these tests (see game_data/move_data.py's own docstring for the id scheme):
GROWL = 45      # status, level 1 -- selectable again since ADDENDUM 217 lifted the first-entry exclusion
TACKLE = 33     # Normal, damaging
EMBER = 52      # Fire, damaging
LEER = 43       # status
FIRE_PUNCH = 7  # Fire, damaging
FLAME_WHEEL = 172  # Fire, damaging
# ADDENDUM 426: a species id with no entry in species_move_compat.json, so no extra (TM/tutor/egg) move is
# ever offered and these tests see the level-up ordering alone.
NO_COMPAT_SPECIES = 0


class TestLatestLevelupPriority(unittest.TestCase):
    """Covers the player's "prioritize their latest damaging moves from levelups" request."""

    def _learnset(self) -> list[tuple[int, int]]:
        return [
            (1, GROWL),         # status; eligible again since ADDENDUM 217 (was excluded by ADDENDUM 75)
            (5, TACKLE),        # damaging
            (10, EMBER),        # damaging
            (15, LEER),         # status
            (20, FIRE_PUNCH),   # damaging
            (25, FLAME_WHEEL),  # damaging
        ]

    def test_picks_the_highest_level_damaging_moves_first(self) -> None:
        # At level 40 every entry is legal; there are 4 damaging candidates (Tackle/Ember/Fire Punch/Flame
        # Wheel) for 3 slots, so the 3 HIGHEST-level ones (Flame Wheel 25, Fire Punch 20, Ember 10) must win
        # over the lowest (Tackle, level 5) -- and no status move (Leer) should appear at all while a damaging
        # candidate is still available.
        chosen = choose_moveset(
            species_id=NO_COMPAT_SPECIES, level=29, learnset=self._learnset(), rng=random.Random(1), move_count=3,
        )
        self.assertEqual(set(chosen), {EMBER, FIRE_PUNCH, FLAME_WHEEL})
        self.assertNotIn(TACKLE, chosen)  # the lowest-level damaging candidate, correctly dropped
        self.assertNotIn(LEER, chosen)    # status never fills a slot while damaging candidates remain

    def test_respects_the_level_cap_before_prioritizing(self) -> None:
        # At level 22, Flame Wheel (needs 25) isn't legal yet -- the remaining damaging candidates (Tackle,
        # Ember, Fire Punch) exactly fill 3 slots.
        chosen = choose_moveset(
            species_id=NO_COMPAT_SPECIES, level=22, learnset=self._learnset(), rng=random.Random(1), move_count=3,
        )
        self.assertEqual(set(chosen), {TACKLE, EMBER, FIRE_PUNCH})

    def test_status_moves_only_fill_slots_once_damaging_candidates_are_exhausted(self) -> None:
        # Only 2 damaging candidates legal by level 12 (Tackle, Ember), so the 3rd slot must come from status.
        # UPDATED 2026-09-15 (ADDENDUM 217): Growl is that status move. Before this addendum it was excluded
        # for being the species' positionally-first learnset entry, Leer is not legal until level 15, and the
        # 3rd slot therefore came back empty -- so this test used to assert {TACKLE, EMBER}. Restoring level-1
        # moves is exactly the behaviour change the player asked for, and this is where it shows.
        chosen = choose_moveset(
            species_id=NO_COMPAT_SPECIES, level=12, learnset=self._learnset(), rng=random.Random(1), move_count=3,
        )
        # All three legal-by-level-12 candidates (Growl 1, Tackle 5, Ember 10) exactly fill the 3 slots, so
        # this asserts the SET only -- the priority ORDER is covered by the level-40 test above, where there
        # are more candidates than slots and the ranking actually has to decide something.
        self.assertEqual(set(chosen), {TACKLE, EMBER, GROWL})

    def test_ties_at_the_same_level_are_resolved_by_rng_not_a_fixed_order(self) -> None:
        # Two damaging moves learned at the same level -- across many seeds, both orderings of "which one gets
        # dropped when only 1 of 2 fits" should show up (proves the tie isn't resolved by, say, move id order).
        # 999 is an unused id that no priority rule can rank; it exists only so the two level-10 moves are
        # the ones being tied against each other. It used to double as the ADDENDUM 75 first-entry sink.
        learnset = [(1, 999), (10, TACKLE), (10, EMBER)]
        seen_first_pick: set[int] = set()
        for seed in range(30):
            chosen = choose_moveset(
                species_id=NO_COMPAT_SPECIES, level=10, learnset=learnset, rng=random.Random(seed), move_count=1,
            )
            seen_first_pick.update(chosen)
        self.assertEqual(seen_first_pick, {TACKLE, EMBER})


class TestLevel30TmBonusMove(unittest.TestCase):
    """ADDENDUM 100's "above level 30, teach them one strong TM attacking move that they could learn", as
    ADDENDUM 426 made it true: the extra move comes only from THIS species' Gen III TM/HM, tutor or egg moves
    (XD's own species table), and below 30 from its tutor or egg moves of at most 70 power."""

    SPECIES = 4   # Charmander (internal 4): Fire level-up moves, plenty of non-Fire TMs, tutors and egg moves

    def _fire_type_learnset(self) -> list[tuple[int, int]]:
        return [(1, 999), (5, EMBER), (10, FIRE_PUNCH), (15, FLAME_WHEEL)]

    def _extra(self, chosen):
        return [m for m in chosen if m not in {999, EMBER, FIRE_PUNCH, FLAME_WHEEL}]

    def test_the_extra_move_is_one_the_species_can_learn(self) -> None:
        compat = species_move_compat()[self.SPECIES]
        for level in (12, 29, 30, 45):
            for seed in range(10):
                chosen = choose_moveset(self.SPECIES, level, self._fire_type_learnset(), random.Random(seed), 3)
                for move in self._extra(chosen):
                    sources = compat["tutor"] + compat["egg"] + (compat["tm"] if level >= 30 else [])
                    self.assertIn(move, sources, (level, seed, move))

    def test_below_30_no_tm_and_at_most_70_power(self) -> None:
        compat, power = species_move_compat()[self.SPECIES], move_power()
        for seed in range(20):
            chosen = choose_moveset(self.SPECIES, 29, self._fire_type_learnset(), random.Random(seed), 3)
            for move in self._extra(chosen):
                self.assertIn(move, compat["tutor"] + compat["egg"])
                self.assertLessEqual(power[move], 70)

    def test_at_30_exactly_one_extra_move_of_80_power(self) -> None:
        power = move_power()
        for seed in range(10):
            chosen = choose_moveset(self.SPECIES, 35, self._fire_type_learnset(), random.Random(seed), 3)
            extra = self._extra(chosen)
            self.assertEqual(1, len(extra), chosen)
            self.assertGreaterEqual(power[extra[0]], 80)

    def test_the_extra_move_never_shares_a_type(self) -> None:
        for seed in range(15):
            chosen = choose_moveset(self.SPECIES, 40, self._fire_type_learnset(), random.Random(seed), 3)
            extra = self._extra(chosen)
            self.assertTrue(extra, f"seed {seed}: no extra move")
            other_types = {MOVE_TYPES[m] for m in chosen if m not in extra and m in MOVE_TYPES}
            self.assertNotIn(MOVE_TYPES[extra[0]], other_types)

    def test_focus_punch_only_for_what_can_learn_it(self) -> None:
        """The player's report: a Pokemon that cannot learn Focus Punch used it."""
        compat = species_move_compat()
        for species in range(1, 412):
            for seed in range(3):
                chosen = choose_moveset(species, 50, [(1, TACKLE)], random.Random(seed), 4)
                if 264 in chosen:
                    self.assertIn(264, compat.get(species, {}).get("tm", []), species)

    def test_tm_bonus_never_exceeds_move_count(self) -> None:
        chosen = choose_moveset(self.SPECIES, 40, self._fire_type_learnset(), random.Random(4), 3)
        self.assertLessEqual(len(chosen), 3)

    def test_no_bonus_move_when_nothing_qualifies(self) -> None:
        chosen = choose_moveset(species_id=NO_COMPAT_SPECIES, level=50, learnset=[], rng=random.Random(5),
                                move_count=3)
        self.assertEqual(chosen, [])

    def test_no_legal_level_up_move_falls_back_to_tutor_and_egg(self) -> None:
        """ADDENDUM 426: when the only level-1 move is the excluded Pound, tutor and egg moves -- legal at any
        level -- come before level-up moves the Pokemon is too young for."""
        compat = species_move_compat()[self.SPECIES]
        chosen = choose_moveset(self.SPECIES, 5, [(1, 1), (40, 53)], random.Random(5), 4)
        self.assertTrue(chosen)
        for move in chosen:
            self.assertIn(move, compat["tutor"] + compat["egg"])


class TestMoveTypesTableSanity(unittest.TestCase):
    def test_every_tm_attacking_move_has_a_known_type(self) -> None:
        for move_id in TM_ATTACKING_MOVES:
            self.assertIn(move_id, MOVE_TYPES, f"TM move {move_id} is missing from MOVE_TYPES")

    def test_tm_attacking_moves_are_never_classified_as_status(self) -> None:
        self.assertTrue(set(TM_ATTACKING_MOVES).isdisjoint(STATUS_MOVE_IDS))

    def test_tm_attacking_moves_cover_a_spread_of_types(self) -> None:
        # Not a single-type pool -- otherwise the "isn't the same type" constraint could dead-end for a
        # species that already covers the one type on offer.
        types_covered = {MOVE_TYPES[m] for m in TM_ATTACKING_MOVES}
        self.assertGreaterEqual(len(types_covered), 8)


if __name__ == "__main__":
    unittest.main()
