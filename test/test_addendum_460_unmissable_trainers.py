"""ADDENDUM 460 (2026-10-10) -- trainers treated as unmissable.

Bost, Dosk, Cida, Labet, Raling, Doby, Willie and everyone in the Snagem Hideout are unmissable. They can host
generated Shadows where that will NOT spawn them infinitely (all of Snagem and Willie are fine; the others are
checked). Bost, Dosk, Cida, Labet, Doby, Raling and all the Snagem trainers can hold progression in their (Any) or
one-time defeat checks.
"""
from __future__ import annotations

import unittest

from BaseClasses import LocationProgressType

from . import PokemonXDTestBase
from ..game_data import missable_autosend as ma
from ..game_data import missable_indices as mi
from ..game_data import missable_trainers as mt
from ..game_data import repeatable_trainers as rt
from ..game_data import trainer_roster as tr

RULED = {13: "BOST", 21: "CIDA", 22: "DOSK", 66: "RALING", 67: "LABET", 68: "DOBY", 135: "WILLIE",
         136: "FUDLO", 137: "GAPLY", 138: "JINOK", 141: "GOLIT", 142: "HOBBLE", 143: "BIDEN"}


class TestTheUnmissableSet(unittest.TestCase):
    def test_the_rows(self) -> None:
        self.assertEqual(set(RULED), set(mi.CONFIRMED_UNMISSABLE))
        for index, name in RULED.items():
            self.assertEqual(name, tr.TRAINERS_BY_INDEX[index]["name"])
        self.assertFalse(mi.CONFIRMED_UNMISSABLE & mi.MISSABLE_TRAINER_INDICES)
        self.assertLessEqual(mi.CONFIRMED_UNMISSABLE, mi.WORKBOOK_MISSABLE_OVERRULED)

    def test_not_auto_sent(self) -> None:
        for name in ("Defeat - Bost", "Defeat - Fudlo", "Defeat - Gaply", "Defeat - Jinok", "Defeat - Golit",
                     "Defeat - Hobble"):
            self.assertNotIn(name, ma.AUTO_SEND_AT_STORY_BYTE, name)

    def test_numbered_rematch_checks_stay_removed(self) -> None:
        """The earlier removal of their numbered rematch checks still stands -- the (Any) is the check."""
        for name in ("Defeat - Cida #1", "Defeat - Dosk #1", "Defeat - Raling #1", "Defeat - Labet #1",
                     "Defeat - Doby #1", "Defeat - Willie #1"):
            self.assertIn(name, tr.REMOVED_DEFEAT_LOCATIONS, name)

    def test_shadow_hosts(self) -> None:
        excluded = mt.shadow_expansion_excluded_trainer_indices()
        # ADDENDUM 466 reopened ADDENDUM 461's refusals: every unmissable row may host a Shadow again, Bost included -- a
        # same-team rematch no longer rebuilds a snagged Shadow (ADDENDUM 465).
        self.assertFalse(mi.CONFIRMED_UNMISSABLE & excluded)
        for later in (29, 227, 82, 230, 109, 218, 110, 219, 111, 220, 226):
            self.assertIn(later, excluded, f"rematch row {later} stays off the host list")

    def test_each_first_fight_has_its_own_later_rows(self) -> None:
        """A Shadow on #1 is not re-offered, because the rematches are other rows."""
        for index in (21, 22, 66, 67, 68, 135):
            name = tr.TRAINERS_BY_INDEX[index]["name"]
            rows = [r for r in tr.TRAINERS_BY_NAME[next(n for n in tr.TRAINERS_BY_NAME if n == name)]]
            self.assertGreater(len(rows), 1, name)
            first = tr.team_signature(tr.TRAINERS_BY_INDEX[index])
            for row in rows:
                if row["index"] != index:
                    self.assertNotEqual(first, tr.team_signature(row), (name, row["index"]))

    def test_willie_stays_filler(self) -> None:
        self.assertIn("WILLIE", rt.ALWAYS_FILLER_SURNAMES)


class TestProgressionInAUniqueSeed(PokemonXDTestBase):
    options = {"shuffle_trainer_defeats": True, "trainer_defeat_mode": "unique"}

    def test_their_checks_can_hold_progression(self) -> None:
        created = {loc.name: loc for loc in self.multiworld.get_locations(self.player)}
        for name in ("Defeat - Bost", "Defeat - Fudlo", "Defeat - Gaply", "Defeat - Jinok", "Defeat - Golit",
                     "Defeat - Hobble", "Defeat Cida (Any)", "Defeat Dosk (Any)", "Defeat Raling (Any)",
                     "Defeat Labet (Any)", "Defeat Doby (Any)", "Defeat Biden (Any)"):
            self.assertIn(name, created, name)
            self.assertNotEqual(LocationProgressType.EXCLUDED, created[name].progress_type, name)
        self.assertEqual(LocationProgressType.EXCLUDED, created["Defeat Willie (Any)"].progress_type)


class TestShadowExpansionMayUseThem(PokemonXDTestBase):
    options = {"shadow_pokemon_expansion": 44}

    def test_hosts_never_include_an_excluded_row(self) -> None:
        """ADDENDUM 466: Bost may host now; the rows still excluded never do."""
        world = self.multiworld.worlds[self.player]
        hosts = {int(plan["trainer_index"]) for plan in (world._shadow_expansion_plans or [])}
        self.assertTrue(hosts)
        self.assertFalse(hosts & mt.shadow_expansion_excluded_trainer_indices())


if __name__ == "__main__":
    unittest.main()
