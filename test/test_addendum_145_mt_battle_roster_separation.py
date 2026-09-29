"""ADDENDUM 145 (2026-09-11): Mt. Battle vs the 232-trainer story roster.

Player request: "Can you ensure that the mt battle trainers aren't included in that 232?" They are not -- the
two come from different deck files -- but the check turned up two things worth pinning:

  1. Three names appear in BOTH rosters (MIRU / CRIDEL / BARDO, Mt. Battle 1/2/3 and story 30/31/32, with the
     same `name_id`s). Benign -- they are the same three characters, Mt. Battle Area 1 being story content --
     but it means a surname alone cannot say which roster a defeat came from.
  2. `MT_BATTLE_FINAL_TRAINER_SURNAME` was "SOMEK", which appears nowhere in the 100 decoded Mt. Battle names.
     Index 100 is BATTLUS. Goal option 1's name-based path could never have fired.
"""
from __future__ import annotations

import json
import pathlib
import unittest

from ..game_data import mtbattle_trainer_data as mtb, trainer_roster

_CENSUS = pathlib.Path(__file__).resolve().parent.parent / "data" / "mtbattle_trainer_census.json"


class TestRostersAreSeparate(unittest.TestCase):
    def test_the_story_roster_is_232_and_the_mt_battle_census_is_100(self) -> None:
        self.assertEqual(len(trainer_roster.TRAINERS), 232)
        self.assertEqual(len(json.loads(_CENSUS.read_text())), 100)

    def test_the_two_are_not_the_same_trainers_under_different_indices(self) -> None:
        """DeckData_Story.bin and DeckData_Hundred.bin are distinct files; nothing merges them."""
        mt_name_ids = {t["name_id"] for t in json.loads(_CENSUS.read_text())}
        story_name_ids = {t["name_id"] for t in trainer_roster.TRAINERS}
        self.assertEqual(len(mt_name_ids), 100, "Mt. Battle name_ids are all distinct")
        # Exactly three are shared, and they are the three known Area 1 story trainers.
        self.assertEqual(len(mt_name_ids & story_name_ids), 3)

    def test_the_three_shared_names_are_the_ones_we_expect(self) -> None:
        shared = {"MIRU", "CRIDEL", "BARDO"}
        for name in shared:
            self.assertIn(name, trainer_roster.TRAINERS_BY_NAME, name)
            self.assertEqual(len(trainer_roster.TRAINERS_BY_NAME[name]), 1,
                             f"{name} is still a single story trainer")
        self.assertEqual([trainer_roster.TRAINERS_BY_INDEX[i]["name"] for i in (30, 31, 32)],
                         ["MIRU", "CRIDEL", "BARDO"])

    def test_no_mt_battle_only_trainer_leaked_into_the_unique_defeat_locations(self) -> None:
        """The 232 per-trainer locations must not contain a Mt. Battle-only fighter."""
        from .. import locations

        self.assertEqual(len(locations.UNIQUE_TRAINER_DEFEAT_LOCATION_NAMES), 232)
        for mt_only in ("BATTLUS", "SIVIL", "FLOSTIN", "TETIL", "LIBAL"):
            self.assertNotIn(mt_only, trainer_roster.TRAINERS_BY_NAME, mt_only)
            self.assertNotIn(f"Defeat - {mt_only.title()}",
                             locations.UNIQUE_TRAINER_DEFEAT_LOCATION_NAMES)


class TestFinalTrainerSurname(unittest.TestCase):
    def test_battlus_is_the_iso_backed_spelling_and_comes_first(self) -> None:
        self.assertEqual(mtb.MT_BATTLE_FINAL_TRAINER_SURNAMES[0], "BATTLUS")
        self.assertEqual(mtb.MT_BATTLE_FINAL_TRAINER_SURNAME, "BATTLUS")

    def test_the_old_serebii_spelling_is_still_accepted(self) -> None:
        """Keeping it costs nothing and goal completion is a one-way latch."""
        self.assertIn("SOMEK", mtb.MT_BATTLE_FINAL_TRAINER_SURNAMES)

    def test_the_first_trainer_constant_is_untouched(self) -> None:
        """MIRU was live-confirmed over the bridge; nothing in this addendum disturbs it."""
        self.assertEqual(mtb.MT_BATTLE_FIRST_TRAINER_SURNAME, "MIRU")

    def test_every_accepted_spelling_is_upper_case(self) -> None:
        """The client upper-cases both sides, but a lower-case entry here would still read as a live-confirmed
        capitalization to anyone skimming the constant."""
        self.assertTrue(all(s.isupper() for s in mtb.MT_BATTLE_FINAL_TRAINER_SURNAMES))


if __name__ == "__main__":
    unittest.main()


class TestMtBattleNames(unittest.TestCase):
    """ADDENDUM 161 (player instruction: "make that mt battle option also modify whether those trainers are
    defeat checks - exclude makes them not checks, include makes them checks").

    Acting on that needs the names, since the battle roster is the only thing the client can identify a trainer
    by. All 100 were decoded from the player's own ISO by the same pass that named the 232 story trainers."""

    def test_all_100_are_named_and_distinct(self) -> None:
        from ..game_data import mtbattle_trainer_data as mtb

        self.assertEqual(len(mtb.MT_BATTLE_TRAINER_NAMES), 100)
        self.assertEqual(len(set(mtb.MT_BATTLE_TRAINER_NAMES.values())), 100)
        self.assertEqual(sorted(mtb.MT_BATTLE_TRAINER_NAMES), list(range(1, 101)))

    def test_the_endpoints_match_what_this_project_already_knew(self) -> None:
        from ..game_data import mtbattle_trainer_data as mtb

        self.assertEqual([mtb.MT_BATTLE_TRAINER_NAMES[i] for i in (1, 2, 3)], ["MIRU", "CRIDEL", "BARDO"])
        self.assertEqual(mtb.MT_BATTLE_TRAINER_NAMES[100], "BATTLUS")
        self.assertEqual(mtb.MT_BATTLE_FIRST_TRAINER_SURNAME, mtb.MT_BATTLE_TRAINER_NAMES[1])
        self.assertIn(mtb.MT_BATTLE_TRAINER_NAMES[100], mtb.MT_BATTLE_FINAL_TRAINER_SURNAMES)

    def test_the_three_shared_with_the_story_roster_are_excluded_from_the_exclusion(self) -> None:
        """The subtle one. MIRU/CRIDEL/BARDO are Mt. Battle 1/2/3 AND story 30/31/32 -- the same characters,
        because Area 1 is story content. Adding them to the exclusion set would stop their STORY encounter
        counting too, which is not what "exclude Mt. Battle" means."""
        from ..game_data import mtbattle_trainer_data as mtb

        self.assertEqual(mtb.MT_BATTLE_SURNAMES_SHARED_WITH_STORY, frozenset({"MIRU", "CRIDEL", "BARDO"}))
        for name in mtb.MT_BATTLE_SURNAMES_SHARED_WITH_STORY:
            self.assertNotIn(name, mtb.MT_BATTLE_ONLY_SURNAMES, name)
            self.assertIn(name, trainer_roster.TRAINERS_BY_NAME, name)

    def test_the_exclusion_set_is_exactly_the_mt_battle_only_names(self) -> None:
        from ..game_data import mtbattle_trainer_data as mtb

        self.assertEqual(len(mtb.MT_BATTLE_ONLY_SURNAMES), 97)
        story = set(trainer_roster.TRAINERS_BY_NAME)
        self.assertFalse(mtb.MT_BATTLE_ONLY_SURNAMES & story,
                         "an excluded surname that is also a story trainer would silently lose story checks")
        self.assertEqual(mtb.MT_BATTLE_ONLY_SURNAMES | mtb.MT_BATTLE_SURNAMES_SHARED_WITH_STORY,
                         set(mtb.MT_BATTLE_TRAINER_NAMES.values()))


class TestExcludingMtBattleStopsThemCounting(unittest.TestCase):
    """The behaviour itself, driven through the tracker. Reuses the existing `exclude_surnames` mechanism that
    already keeps the player's own party from being counted, rather than a second parallel one."""

    @staticmethod
    def _defeat(tracker, surname, exclude):
        from .. import locations, ram_client as rc

        fired = []
        for hp in (20, 4, 0, 0):
            frame = [rc.BattleRosterRecord(0x804A8000, surname, "ZUBAT", hp)]
            fired += tracker.poll({}, locations.trainer_defeat_count_location_name,
                                  records=frame, exclude_surnames=exclude)
        return fired

    def test_a_mt_battle_win_does_not_advance_the_counter_when_excluded(self) -> None:
        from .. import ram_client as rc
        from ..game_data import mtbattle_trainer_data as mtb

        tracker = rc.TrainerBattleDefeatTracker()
        self.assertEqual(self._defeat(tracker, "BATTLUS", mtb.MT_BATTLE_ONLY_SURNAMES), [])
        self.assertEqual(tracker.defeat_count, 0)

    def test_the_same_win_does_advance_it_when_included(self) -> None:
        from .. import ram_client as rc

        tracker = rc.TrainerBattleDefeatTracker()
        self.assertEqual(self._defeat(tracker, "BATTLUS", frozenset()), ["Defeat 1 Trainers"])
        self.assertEqual(tracker.defeat_count, 1)

    def test_a_story_trainer_still_counts_either_way(self) -> None:
        from .. import ram_client as rc
        from ..game_data import mtbattle_trainer_data as mtb

        for exclude in (frozenset(), mtb.MT_BATTLE_ONLY_SURNAMES):
            tracker = rc.TrainerBattleDefeatTracker()
            self.assertEqual(self._defeat(tracker, "LOVRINA", exclude), ["Defeat 1 Trainers"])

    def test_bardo_counts_even_when_mt_battle_is_excluded(self) -> None:
        """He is story trainer 32 as well as Mt. Battle 3."""
        from .. import ram_client as rc
        from ..game_data import mtbattle_trainer_data as mtb

        tracker = rc.TrainerBattleDefeatTracker()
        self.assertEqual(self._defeat(tracker, "BARDO", mtb.MT_BATTLE_ONLY_SURNAMES), ["Defeat 1 Trainers"])


class TestTheCeiling(unittest.TestCase):
    def test_the_ladder_stops_short_of_the_final_sphere(self) -> None:
        """ADDENDUM 161 capped the trainer ladder at 114 to keep it out of an optional grind.

        RETARGETED 2026-09-13 (ADDENDUM 168), was "the ladder stops where the Mt. Battle bucket begins", which
        asserted 113 -> Cipher Key Lair and 114 -> Mt. Battle. Both numbers were positional: `_SPHERE_REGION_
        ORDER` is now `list(regions.REGION_NAMES)`, the real graph order, and ADDENDUM 168 moved Mt. Battle from
        an invented node hanging off Cipher Key Lair to a real edge off Agate Village (story byte 0x23 -> 0x24).
        Its 92-threshold block therefore begins just past Agate Village's own capacity, not at 114.

        RETARGETED AGAIN 2026-09-13 (ADDENDUM 169): Agate Village is now always open in every mode and
        absorbed the retired Relic Forest weights, so its capacity went 4 -> 10, Mt. Battle's block starts at
        11, and the 114 ceiling now lands in Pyrite Town rather than Realgam Tower. The assertion below no
        longer names either of those regions -- only the two properties that have to hold whatever the census
        says: the boundary is Agate's own capacity, and the ceiling is not the final sphere.

        Mt. Battle being early is also what defuses the original worry: reaching the Mt. Battle REGION now costs
        one key item, so no part of the ladder is gated behind the optional grind in logic terms, whatever the
        counter does in-game. What still has to hold, and is what this now asserts, is the option's own shape:
        the ceiling and default are unchanged, both fit inside the real roster, and the ceiling threshold does
        not require the final sphere -- the ladder must never be the thing that drags Citadark Isle into logic.
        """
        from .. import locations, rules
        from ..options import TrainerDefeatCheckCount

        self.assertEqual(TrainerDefeatCheckCount.range_end, 114)
        self.assertEqual(TrainerDefeatCheckCount.default, 100)
        thresholds = rules._cumulative_region_thresholds(rules._TRAINER_WEIGHT_BY_REGION)

        ceiling_region = rules._region_for_sphere_count(thresholds, TrainerDefeatCheckCount.range_end)
        self.assertLess(rules._SPHERE_REGION_ORDER.index(ceiling_region),
                        rules._SPHERE_REGION_ORDER.index("Citadark Isle"),
                        "the trainer ceiling must not require the last region in sphere order")

        # Where the 92 Mt. Battle thresholds really begin now, asserted so the move is a recorded decision
        # rather than something a reader has to rediscover from the region order.
        # RETARGETED 2026-09-13 (ADDENDUM 169): the boundary moved 4/5 -> 10/11. Agate Village absorbed the
        # retired "Relic Forest" bucket's 6 trainers (4 + 6 = 10), because Relic Forest was never in
        # regions.REGION_NAMES and so was never visited by the ordered walk at all. Read the boundary out of
        # the live table rather than copying the new numbers, so the NEXT census change is a data change here
        # too -- the hardcoded pair is what went stale.
        # RETARGETED AGAIN 2026-09-13 (ADDENDUM 175): the hardcoded 10 is gone for good. The weights are now
        # the player's own census rather than any estimate, so Agate's capacity is whatever the count says
        # (36 at the time of writing) and pinning the number here would just queue up the same staleness a
        # third time. What has to hold is the BOUNDARY: Agate's own capacity resolves to Agate, and one past
        # it resolves to the next region in graph order that carries any trainers.
        agate_capacity = dict((region, total) for total, region in thresholds)["Agate Village"]
        self.assertEqual(rules._region_for_sphere_count(thresholds, agate_capacity), "Agate Village")
        order = rules._SPHERE_REGION_ORDER
        next_with_trainers = next(
            r for r in order[order.index("Agate Village") + 1:]
            if rules._TRAINER_WEIGHT_BY_REGION.get(r, 0)
        )
        self.assertEqual(rules._region_for_sphere_count(thresholds, agate_capacity + 1), next_with_trainers)

        self.assertLessEqual(TrainerDefeatCheckCount.range_end,
                             locations.TRAINER_DEFEAT_COUNT_LOCATION_COUNT)
        self.assertLessEqual(TrainerDefeatCheckCount.default,
                             locations.TRAINER_DEFEAT_COUNT_LOCATION_COUNT)
