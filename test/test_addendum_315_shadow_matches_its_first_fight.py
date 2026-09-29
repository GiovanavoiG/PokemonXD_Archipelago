"""ADDENDUM 315 -- a Shadow is matched to the team it is SNAGGED from, not to a later rematch.

Player, reading a generated seed: "Why does Resix have a level 16 carvanha but a level 50 seadra? The levels
don't add up."

`real_shadow_census` joined DDPK -> holding trainer with a plain assignment, so when the same Shadow is carried
by several occurrences of one trainer the LAST one won. For the six Sixes that is the deep rematch tail (whose
ordinary members are level 50 and which `trainer_placements` marks filler-only, with no region at all), while
the fight the Shadow is really snagged in is the Cipher Lab one."""
import unittest

from ..game_data import load_json_data_file, real_trainer_data as rtd
from ..game_data import trainer_placements as tp
from ..randomizer.enhanced_difficulty import shadow_level_assignment

SIXES_SHADOWS = (3, 4, 5, 6, 7, 14)


def _owners() -> "dict[int, list[int]]":
    out: "dict[int, list[int]]" = {}
    for trainer in load_json_data_file("deckdata_story_trainers.json") or []:
        for slot in trainer.get("team", []):
            if slot.get("kind") == "DDPK" and slot.get("ddpk_index") is not None:
                out.setdefault(slot["ddpk_index"], []).append(trainer["index"])
    return out


class TestTheJoinTakesTheEarliestFight(unittest.TestCase):
    def setUp(self) -> None:
        self.census = {r["ddpk_index"]: r for r in rtd.real_shadow_census() or []}
        self.owners = _owners()

    def test_every_shadow_is_owned_by_its_lowest_trainer_index(self) -> None:
        for ddpk, holders in self.owners.items():
            self.assertEqual(min(holders), self.census[ddpk]["trainer_index"], ddpk)

    def test_the_seven_shared_shadows_are_the_population_this_is_about(self) -> None:
        shared = {k for k, v in self.owners.items() if len(v) > 1}
        self.assertEqual(7, len(shared))
        self.assertTrue(set(SIXES_SHADOWS) <= shared)

    def test_resix_is_matched_to_his_cipher_lab_team(self) -> None:
        """The reported case: holders 33 / 112 / 203, averages 14 / 20 / 50."""
        row = self.census[14]
        self.assertEqual(33, row["trainer_index"])
        self.assertEqual(14.0, row["team_avg_level"])

    def test_no_shadow_is_matched_to_a_trainer_with_no_placement(self) -> None:
        """The tail occurrences are filler-only and have no region, so they also carry no path-scaling tier --
        matching to one is how a Shadow ends up at a level nothing else in its area shares."""
        for ddpk in SIXES_SHADOWS:
            index = self.census[ddpk]["trainer_index"]
            self.assertIsNotNone(tp.region_for(index), f"ddpk {ddpk} -> trainer {index}")

    def test_none_of_them_comes_out_near_fifty(self) -> None:
        _dpkm, ddpk_levels = shadow_level_assignment(rtd.real_shadow_census())
        for ddpk in SIXES_SHADOWS:
            self.assertLess(ddpk_levels[ddpk], 25, f"ddpk {ddpk} is still matched to a rematch team")


class TestTheRestOfTheCensusIsUnchanged(unittest.TestCase):
    def test_single_holder_shadows_keep_their_trainer(self) -> None:
        owners = _owners()
        census = {r["ddpk_index"]: r for r in rtd.real_shadow_census() or []}
        single = [k for k, v in owners.items() if len(v) == 1]
        self.assertGreater(len(single), 70)
        for ddpk in single:
            self.assertEqual(owners[ddpk][0], census[ddpk]["trainer_index"])

    def test_shadows_with_no_holder_still_have_none(self) -> None:
        census = rtd.real_shadow_census()
        self.assertTrue(any(r["team_avg_level"] is None for r in census),
                        "the all-Shadow trainers must still have no team to match")
