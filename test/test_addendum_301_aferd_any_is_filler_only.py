"""ADDENDUM 301 (2026-09-20) -- Aferd (Any) is filler-only, and the exclusion mechanism audited end to end.

Player: "Exclude Aferd(Any) from progression/useful items. Also double check that mechanism - my guess is
there's another field that controls it or a multiplier."

THE CHANGE IS ONE LINE. `AFERD` joins `repeatable_trainers.ALWAYS_FILLER_SURNAMES`, which feeds
`ALWAYS_FILLER_LOCATIONS`, which `locations.create_regions_and_locations` turns into
`LocationProgressType.EXCLUDED` before `create_items` runs. That is the whole path.

THE AUDIT IS THE REST OF THIS FILE, because "it is marked EXCLUDED" and "nothing good can land on it" are two
different claims and only the second one is what was asked for. Four fields were checked:

  1. `progress_type` -- set in `create_regions_and_locations`, BEFORE `create_items`. This ordering is load-
     bearing: the world sizes its own useful/filler pools from the count of non-EXCLUDED locations, so an
     exclusion applied later (in `set_rules`, say) is invisible to that arithmetic and surfaces as
     `FillError: Not enough filler items for excluded locations`.
  2. Archipelago's own fill -- `distribute_items_restrictive` buckets locations by `progress_type` and fills
     EXCLUDED ones from `filleritempool` alone. `usefulitempool` is only ever merged into `restitempool`,
     which is poured into DEFAULT locations. So useful is blocked by the same flag that blocks progression,
     which is not obvious from the flag's name and is the thing worth pinning.
  3. `allow_excluded` -- `fill_restrictive` HAS an escape hatch that flips EXCLUDED locations to DEFAULT and
     retries progression into them under fill pressure. It defaults False and core fill never passes True, so
     it cannot fire here. It is named because it is the one way this guarantee could ever be weakened.
  4. `priority_locations` -- a player's yaml cannot promote a world-excluded location; Archipelago refuses and
     logs a warning instead.

AND THE FIELD THAT LOOKED LIKE THE ANSWER AND IS NOT. `missable_trainers.FILLER_ONLY_TRAINER_INDICES` contains
Aferd #2, so it is tempting to read ADDENDUM 252's anchor derivation as having consulted the wrong witness.
It did not. That set holds EVERY occurrence of every surname the workbook marks missable, so all 35 any-defeat
anchors are in it by construction and membership carries no information about the anchor itself. The census
missable column is the right witness and `_build()` already reads it. This is written down because it is a
false positive worth only finding once.

SO AFERD IS A RULING, NOT A DERIVATION, and the module says so where the ruling lives. Its anchor is occurrence
69 -- Aferd #2, Pokemon HQ Lab, census-safe, sphere zero. Nothing about it was broken; the player decided it
should not host progression, and this is the lever that decides that.
"""
from __future__ import annotations

import unittest

from BaseClasses import ItemClassification, LocationProgressType

from . import PokemonXDTestBase
from ..game_data import missable_trainers as MT
from ..game_data import repeatable_trainers as RT

AFERD_ANY = "Defeat Aferd (Any)"


class TestTheRuling(unittest.TestCase):
    def test_aferd_is_in_the_ruling_table_with_a_reason(self) -> None:
        self.assertIn("AFERD", RT.ALWAYS_FILLER_SURNAMES)
        self.assertTrue(RT.ALWAYS_FILLER_SURNAMES["AFERD"].strip())

    def test_the_ruling_reaches_the_location_name(self) -> None:
        self.assertEqual(AFERD_ANY, RT.location_name("AFERD"))
        self.assertIn(AFERD_ANY, RT.ALWAYS_FILLER_LOCATIONS)

    def test_the_anchor_is_the_fight_the_ruling_names(self) -> None:
        """If the census is ever regenerated and Aferd's anchor moves to a different occurrence, the reason
        recorded beside the ruling stops describing it."""
        row = next(r for r in RT.REPEATABLE_TRAINERS if r["surname"] == "AFERD")
        self.assertEqual(69, row["anchor_index"])
        self.assertEqual("Pokemon HQ Lab", row["region"])

    def test_the_ruling_was_not_derivable(self) -> None:
        """Stated so nobody later "fixes" the derivation to produce it. The census says this anchor is safe --
        Aferd is here because the player said so, which is a different kind of fact."""
        row = next(r for r in RT.REPEATABLE_TRAINERS if r["surname"] == "AFERD")
        self.assertFalse(row["anchor_is_missable"])

    def test_the_named_occurrences_were_already_filler_and_stay_that_way(self) -> None:
        """"keep our current checks & keep them filler" from ADDENDUM 252, unchanged by this."""
        for index in (8, 69, 70, 146, 223):
            self.assertIn(index, MT.FILLER_ONLY_TRAINER_INDICES, index)


class TestTheFalsePositive(unittest.TestCase):
    """The audit's negative result, kept so it is not re-derived as a bug report."""

    def test_every_any_defeat_anchor_is_in_the_filler_only_set(self) -> None:
        for row in RT.REPEATABLE_TRAINERS:
            self.assertIn(row["anchor_index"], MT.FILLER_ONLY_TRAINER_INDICES, row["location"])

    def test_and_most_of_those_anchors_are_census_safe(self) -> None:
        """Which is what proves the previous test carries no information: if membership meant "missable",
        these would all be missable, and they are not."""
        safe = [r for r in RT.REPEATABLE_TRAINERS if not r["anchor_is_missable"]]
        self.assertGreater(len(safe), len(RT.REPEATABLE_TRAINERS) // 2)


class TestTheOrderingThatMakesTheExclusionCountable(unittest.TestCase):
    def test_the_exclusion_is_applied_where_create_items_can_see_it(self) -> None:
        """Marked in create_regions_and_locations, not in set_rules. See this module's docstring for the
        FillError that the other order produces."""
        source = open(RT.__file__.replace("game_data/repeatable_trainers.py", "locations.py"),
                      encoding="utf-8").read()
        self.assertIn("repeatable_trainers.ALWAYS_FILLER_LOCATIONS", source)
        marked = source.index("repeatable_trainers.ALWAYS_FILLER_LOCATIONS")
        self.assertLess(source.index("def create_regions_and_locations"), marked)


class TestInARealWorld(PokemonXDTestBase):
    options = {"shuffle_trainer_defeats": True, "progression_locations": 2}

    def _aferd(self):
        return self.multiworld.get_location(AFERD_ANY, self.player)

    def test_the_location_still_exists(self) -> None:
        """Excluded, not deleted -- it still sends, and still clears with !checked."""
        names = {loc.name for loc in self.multiworld.get_locations(self.player)}
        self.assertIn(AFERD_ANY, names)

    def test_it_is_excluded(self) -> None:
        self.assertIs(LocationProgressType.EXCLUDED, self._aferd().progress_type)

    def test_its_sibling_any_defeats_are_not_all_excluded(self) -> None:
        """Without this the test above could pass by excluding the whole category."""
        live = [loc for loc in self.multiworld.get_locations(self.player)
                if loc.name in set(RT.LOCATION_NAMES)]
        open_ones = [l for l in live if l.progress_type is not LocationProgressType.EXCLUDED]
        self.assertTrue(open_ones)


class TestFillReallyLeavesItAlone(PokemonXDTestBase):
    """The claim the player actually made -- not "it is flagged", but "nothing good lands on it"."""

    options = {"shuffle_trainer_defeats": True, "progression_locations": 2}

    def test_fill_places_only_filler_there(self) -> None:
        from Fill import distribute_items_restrictive

        distribute_items_restrictive(self.multiworld)
        item = self.multiworld.get_location(AFERD_ANY, self.player).item
        self.assertIsNotNone(item, "the location must still receive something")
        self.assertNotIn(ItemClassification.progression, item.classification)
        self.assertNotIn(ItemClassification.useful, item.classification)

    def test_the_run_actually_placed_progression_somewhere(self) -> None:
        """Guards the test above against passing because fill did nothing at all."""
        from Fill import distribute_items_restrictive

        distribute_items_restrictive(self.multiworld)
        placed = [loc for loc in self.multiworld.get_locations(self.player)
                  if loc.item and ItemClassification.progression in loc.item.classification]
        self.assertTrue(placed)


class TestArchipelagosOwnGuarantees(unittest.TestCase):
    """Fields 2-4 of the audit, asserted against the installed Archipelago rather than remembered."""

    def test_excluded_locations_are_filled_from_the_filler_pool_alone(self) -> None:
        import inspect

        import Fill

        source = inspect.getsource(Fill.distribute_items_restrictive)
        self.assertIn("remaining_fill(multiworld, excludedlocations, filleritempool", source)
        self.assertIn("restitempool = filleritempool + usefulitempool", source)
        self.assertLess(source.index("excludedlocations, filleritempool"),
                        source.index("restitempool = filleritempool + usefulitempool"),
                        "useful items must not be in the pool the excluded pass draws from")

    def test_the_escape_hatch_is_off_by_default(self) -> None:
        import inspect

        import Fill

        signature = inspect.signature(Fill.fill_restrictive)
        self.assertIs(False, signature.parameters["allow_excluded"].default)
        caller = inspect.getsource(Fill.distribute_items_restrictive)
        self.assertNotIn("allow_excluded=True", caller)

    def test_a_players_priority_locations_cannot_promote_a_world_exclusion(self) -> None:
        import inspect

        import Main

        source = inspect.getsource(Main.main)
        self.assertIn("if location.progress_type != LocationProgressType.EXCLUDED:", source)


if __name__ == "__main__":
    unittest.main()
