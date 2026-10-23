"""ADDENDUM 489 (2026-10-13) -- trainer-defeat hints name where the fight is, like the catch hints.
"""
from __future__ import annotations

import re

from . import PokemonXDTestBase
from .. import defeat_hints


def _hints(test) -> "dict[str, str]":
    hint_data: "dict[int, dict[int, str]]" = {}
    test.multiworld.worlds[test.player].extend_hint_information(hint_data)
    names = {loc.address: loc.name for loc in test.multiworld.get_locations(test.player) if loc.address is not None}
    return {names[address]: text for address, text in hint_data.get(test.player, {}).items()}


class TestUniqueDefeatHints(PokemonXDTestBase):
    options = {"shuffle_trainer_defeats": True, "trainer_defeat_mode": "unique", "randomize_travel_locations": True}

    def test_every_defeat_check_has_its_area(self) -> None:
        hints = _hints(self)
        defeats = [loc for loc in self.multiworld.get_locations(self.player)
                   if loc.address is not None and loc.name.startswith("Defeat")]
        self.assertTrue(defeats)
        for loc in defeats:
            self.assertIn(loc.name, hints, loc.name)
            if loc.parent_region.name != "Unique Trainer Defeats":
                self.assertTrue(hints[loc.name].startswith(loc.parent_region.name), "the logic's region comes first")

    def test_a_single_fight_names_its_one_area(self) -> None:
        hints = _hints(self)
        self.assertEqual("Phenac City", hints["Defeat - Exinn"])
        self.assertEqual("Cipher Key Lair", hints["Defeat - Acrod"])
        # A kept forced second fight names its own area only.
        self.assertEqual("Cipher Lab", hints["Defeat - Naps #2"])
        self.assertNotIn("Defeat - Miror B. #2", hints)
        self.assertNotIn("Defeat - Resix #2", hints)

    def test_any_names_every_area_it_can_fire_in(self) -> None:
        hints = _hints(self)
        self.assertEqual("Cipher Lab or Citadark Isle", hints["Defeat Lovrina (Any)"])
        self.assertEqual("Phenac City (Post-Sixes) or Cipher Lab", hints["Defeat Resix (Any)"])
        # Watched fights are not places to win them: Ardos and Zook at Gateon, Biden at the Key Lair.
        self.assertEqual("Citadark Isle", hints["Defeat Ardos (Any)"])
        self.assertNotIn("Gateon Port", hints["Defeat Zook (Any)"])
        self.assertEqual("Snagem Hideout", hints["Defeat Biden (Any)"])
        # Either of Miror B.'s two places is enough.
        self.assertTrue({"Poke Spots", "Outskirt Stand"} <= set(hints["Defeat Miror B. (Any)"].split(" or ")))

    def test_catch_hints_are_kept(self) -> None:
        hints = _hints(self)
        self.assertTrue(any(name.startswith("Catch - ") and text.startswith("Shadow: ") for name, text in hints.items()))


class TestCumulativeCountsHaveNoPlace(PokemonXDTestBase):
    options = {"shuffle_trainer_defeats": True, "trainer_defeat_mode": "cumulative",
               "trainer_defeat_check_count": 20}

    def test_counts_get_no_text(self) -> None:
        self.assertEqual({}, defeat_hints.defeat_hint_texts(self.multiworld.worlds[self.player]))
        hints = _hints(self)
        self.assertFalse([name for name in hints if re.fullmatch(r"Defeat \d+ Trainers", name)])
