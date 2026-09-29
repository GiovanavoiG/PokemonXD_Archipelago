"""ADDENDUM 327 -- Biden (Any) is anchored in the Snagem Hideout, and Zook (Any) stays filler-only.

Player: "Biden (Any) is only accessible through Snagem Hideout. Also, Exclude Zook (Any)."

Both of Biden's fights are missable, so `_build`'s non-missable preference had nothing to choose between and
the earliest regioned occurrence won -- Biden #1, Cipher Key Lair (exterior). The player has played it: the
fight you can actually get is #2, in the hideout. Too EARLY is the dangerous direction for an anchor, because
the fill treats the location as available in a sphere the player cannot reach it in."""
import unittest

from . import PokemonXDTestBase
from ..game_data import repeatable_trainers as rt
from ..game_data import trainer_placements as tp


def _row(surname: str) -> dict:
    return {r["surname"]: r for r in rt.REPEATABLE_TRAINERS}[surname]


class TestBidensAnchor(unittest.TestCase):
    """RETARGETED BY ADDENDUM 330 (2026-09-23), and the retarget is the result rather than a concession.

    These two tests used to assert the MECHANISM -- anchor index 148, and `ANCHOR_OVERRIDES == {"BIDEN"}`.
    ADDENDUM 330 found why the override was needed at all: the census had Biden #1's and Biden #2's regions
    swapped, so the earliest regioned occurrence was the Key Lair exterior and the derivation could not reach
    the player's answer. With `trainer_placements.PLACEMENT_REGION_OVERRIDES` correcting the swap, it reaches
    it unaided and the override is gone.

    So the player's requirement is what gets asserted, not the machinery that used to deliver it."""

    def test_it_is_the_snagem_fight(self) -> None:
        """The player's sentence, verbatim: "Biden (Any) is only accessible through Snagem Hideout"."""
        row = _row("BIDEN")
        self.assertEqual("Snagem Hideout", row["region"])
        self.assertEqual("Snagem Hideout", tp.region_for(row["anchor_index"]))

    def test_the_derivation_reaches_it_without_an_override(self) -> None:
        """The stronger form of the same claim: nothing is hand-typed for Biden any more."""
        self.assertNotIn("BIDEN", rt.ANCHOR_OVERRIDES)

    def test_any_override_still_names_a_real_regioned_occurrence(self) -> None:
        """The fence outlives its one entry -- the mechanism stays for a fight that genuinely needs it."""
        from ..game_data.trainer_roster import TRAINERS_BY_INDEX

        for surname, index in rt.ANCHOR_OVERRIDES.items():
            self.assertEqual(surname, TRAINERS_BY_INDEX[index]["name"])
            self.assertTrue(tp.region_for(index))

    def test_both_of_his_fights_are_still_recorded(self) -> None:
        """Correcting the regions changes which one anchors, not what the census knows."""
        self.assertEqual((143, 148), _row("BIDEN")["occurrences"])


class TestZookStaysExcluded(unittest.TestCase):
    def test_the_ruling_is_still_on_file(self) -> None:
        self.assertIn("ZOOK", rt.ALWAYS_FILLER_SURNAMES)
        self.assertTrue(_row("ZOOK")["always_filler"])


class TestInARealSeed(PokemonXDTestBase):
    options = {"key_item_shuffle": True}

    def _location(self, name):
        return next(l for l in self.multiworld.get_locations(self.player) if l.name == name)

    def test_biden_is_behind_the_hideout(self) -> None:
        from BaseClasses import CollectionState

        biden = self._location("Defeat Biden (Any)")
        self.assertEqual("Snagem Hideout", biden.parent_region.name)
        state = CollectionState(self.multiworld)
        state.sweep_for_advancements()
        self.assertFalse(biden.can_reach(state))

    def test_both_any_defeats_hold_filler_only(self) -> None:
        from BaseClasses import LocationProgressType

        for name in ("Defeat Biden (Any)", "Defeat Zook (Any)"):
            self.assertEqual(LocationProgressType.EXCLUDED, self._location(name).progress_type, name)
