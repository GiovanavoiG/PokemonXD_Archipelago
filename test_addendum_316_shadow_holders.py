"""ADDENDUM 316 -- who holds each Shadow is decided once, up front, and every level reads that.

Player: "Can we preemptively do the determination of which trainers get shadows, then use that to determine the
occurrence, that team's level, and match it to that?"

ADDENDUM 315 fixed the symptom (Resix's Shadow matched to his level-50 rematch tail). This pins the structure
that prevents the next one: `game_data/shadow_holders.py` resolves the fight, and the census, the level
assignment and the expansion all read the same answer."""
import unittest

from ..game_data import real_trainer_data as rtd
from ..game_data import shadow_holders as sh
from ..game_data import trainer_placements as tp
from ..randomizer.enhanced_difficulty import shadow_level_assignment


class TestTheResolution(unittest.TestCase):
    def setUp(self) -> None:
        self.holders = sh.vanilla_shadow_holders()

    def test_every_vanilla_shadow_has_a_holder(self) -> None:
        census = rtd.real_shadow_census()
        self.assertEqual(83, len(census))
        for row in census:
            self.assertIn(row["ddpk_index"], self.holders, row)

    def test_the_holder_is_the_earliest_fight_carrying_it(self) -> None:
        for ddpk, rows in sh.shadows_held_more_than_once().items():
            self.assertEqual(min(rows), self.holders[ddpk].trainer_index, ddpk)

    def test_the_occurrence_comes_with_it(self) -> None:
        """The player asked for the occurrence, not just the trainer row."""
        holder = self.holders[14]
        self.assertEqual((33, "RESIX", 1), (holder.trainer_index, holder.surname, holder.occurrence))
        self.assertEqual(6, holder.total_with_name)
        self.assertEqual("Cipher Lab", holder.region)
        self.assertEqual(14.0, holder.team_avg_level)

    def test_an_all_shadow_trainer_has_no_average_rather_than_a_zero(self) -> None:
        orphans = [h for h in self.holders.values() if h.team_avg_level is None]
        self.assertTrue(orphans)
        for holder in orphans:
            self.assertEqual((), holder.team_levels)

    def test_the_holders_region_agrees_with_the_placement_census(self) -> None:
        for holder in self.holders.values():
            self.assertEqual(tp.region_for(holder.trainer_index), holder.region)


class TestTheCensusIsNowAReader(unittest.TestCase):
    def test_the_census_carries_the_resolved_fight(self) -> None:
        holders = sh.vanilla_shadow_holders()
        for row in rtd.real_shadow_census():
            holder = holders[row["ddpk_index"]]
            self.assertEqual(holder.trainer_index, row["trainer_index"])
            self.assertEqual(holder.team_avg_level, row["team_avg_level"])
            self.assertEqual(holder.occurrence, row["occurrence"])
            self.assertEqual(holder.region, row["region"])

    def test_levels_follow_the_resolved_teams_average(self) -> None:
        import math
        census = rtd.real_shadow_census()
        matched, _ = shadow_level_assignment(census, scale_levels=False)
        for row in census:
            if row["team_avg_level"] is not None:
                # ADDENDUM 317 floors the base at the Shadow's vanilla level.
                expected = math.floor(max(row["team_avg_level"], row["shadow_level"]))
                self.assertEqual(expected, matched[row["dpkm_index"]], row)


class TestGeneratedShadowsUseTheSameDoor(unittest.TestCase):
    def test_a_host_trainers_average_is_the_same_number_both_ways(self) -> None:
        """`shadow_expansion` levels a generated Shadow from the free-slot census' `avg_level`. It must be the
        same average `shadow_holders` reports for that trainer, or the two populations are levelled by two
        different rules."""
        census = rtd.real_trainer_free_slot_census()
        self.assertTrue(census)
        for row in census:
            holder = sh.holder_for_trainer_index(row["trainer_index"])
            self.assertIsNotNone(holder, row)
            self.assertAlmostEqual(row["avg_level"], holder.team_avg_level, places=6, msg=row)

    def test_a_host_is_one_occurrence_not_a_surname(self) -> None:
        holder = sh.holder_for_trainer_index(203)
        self.assertEqual(("RESIX", 5), (holder.surname, holder.occurrence))


class TestItIsWrittenIntoTheSeed(unittest.TestCase):
    def test_every_ambiguous_shadow_is_described(self) -> None:
        lines = sh.describe_resolution()
        self.assertEqual(len(sh.shadows_held_more_than_once()), len(lines))
        self.assertTrue(any("Resix #1" in line for line in lines), lines)
        for line in lines:
            self.assertIn("also carried by trainer(s)", line)
