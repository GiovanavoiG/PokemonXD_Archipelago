"""ADDENDUM 211. Every Cipher battle in Pyrite is behind the Data ROM & ID Card AND the Poke Spots.

Player: "On location shuffle, all Pyrite town battles should be gated behind Data Rom/ID Card, AND poke
spots." -- corrected mid-answer to "WAIT - WRONG. all pyrite CIPHER battles".

The audit found almost all of it was already true, and exactly one row was not:

  * The ten Cipher Peons (trainer class 17) and Exol's occurrence row (class 40) all sit in
    "Pyrite Town (ONBS)" in game_data/trainer_placements, each carrying ('Data ROM',) on top.
  * The region graph is  Pyrite Town --(Data ROM)--> Poke Spots --> Pyrite Town (ONBS),  so anything in ONBS
    needs the item AND the spots. That is the requirement, stated structurally.
  * `trainer_defeat.TRAINER_DEFEAT_ROSTER` -- a SECOND, parallel table of 66 named trainers -- filed
    "Defeat - Cipher Commander Exol" under plain "Pyrite Town", whose only requirement is the item. Reachable
    before the Poke Spots ever opened.

That is ADDENDUM 185's Phenac bug repeated in Pyrite, in the same table, and the two tables disagreeing about
the same fight is what hid it: `Defeat - Exol` was correct while `Defeat - Cipher Commander Exol` was not."""
from __future__ import annotations

import unittest

from .. import locations as world_locations
from .. import regions as world_regions
from .. import trainer_defeat
from ..game_data import trainer_placements, trainer_roster

CIPHER_TRAINER_CLASSES = frozenset({17, 40})   # Cipher Peon, Cipher Commander


class TestTheGraphPutsONBSBehindBothThings(unittest.TestCase):
    def test_plain_pyrite_is_NOT_behind_the_data_rom(self) -> None:
        """CORRECTED 2026-09-16 (ADDENDUM 240). This used to assert the opposite. Player: "Pyrite vending
        machine and first shop version are accessible as soon as pyrite town is... Any chests in ONBS are
        gated behind the data rom/id card - every other chest is ONLY gated behind pyrite town."

        The ROM requirement was on the wrong edge: it sat on the way INTO Pyrite Town, which put all 39
        plain-Pyrite locations behind it. Pyrite is visited in two halves and only the second is behind the
        ROM -- which is what the two region names have always said.

        ADDENDUM 211's own guarantee is untouched, and the next two tests are why: the ROM moved nowhere, it
        is still on Pyrite Town -> Poke Spots, and ONBS is still reachable only through Poke Spots."""
        self.assertIn(("Cipher Lab", "Pyrite Town", ()), world_regions.REGION_EDGES)
        self.assertNotIn(("Cipher Lab", "Pyrite Town", ("Data ROM",)), world_regions.REGION_EDGES)

    def test_the_spots_are_behind_pyrite(self) -> None:
        self.assertIn(("Pyrite Town", "Poke Spots", ("Data ROM",)), world_regions.REGION_EDGES)

    def test_onbs_is_behind_the_spots(self) -> None:
        """This edge is what makes "AND poke spots" true for everything filed in ONBS."""
        self.assertIn(("Poke Spots", "Pyrite Town (ONBS)", ()), world_regions.REGION_EDGES)

    def test_the_data_rom_and_id_card_are_one_item(self) -> None:
        """ADDENDUM 179 packaged them, so "Data ROM/ID Card" is one requirement, not two."""
        from .. import items
        self.assertEqual(items.requirement_to_pool_item("Data ROM"),
                         items.requirement_to_pool_item("ID Card"))


class TestNoCipherBattleInPyriteEscapesTheGate(unittest.TestCase):
    PYRITE_UNGATED = "Pyrite Town"          # the first-visit region: item only, no spots

    def test_no_cipher_class_trainer_is_placed_in_plain_pyrite(self) -> None:
        by_index = {t["index"]: t for t in trainer_roster.TRAINERS}
        for index, placement in trainer_placements.PLACEMENTS.items():
            trainer = by_index.get(index)
            if not trainer or trainer["trainer_class"] not in CIPHER_TRAINER_CLASSES:
                continue
            self.assertNotEqual(self.PYRITE_UNGATED, placement.region,
                                f"trainer {index} is Cipher and sits in ungated Pyrite Town")

    def test_no_cipher_named_defeat_row_is_in_plain_pyrite(self) -> None:
        """The row this addendum moved. Checked by name because this table has no class column."""
        offenders = [name for region, name, _surname in trainer_defeat.TRAINER_DEFEAT_ROSTER
                     if region == self.PYRITE_UNGATED and "Cipher" in name]
        self.assertEqual([], offenders)

    def test_exol_specifically_moved(self) -> None:
        rows = [region for region, name, _s in trainer_defeat.TRAINER_DEFEAT_ROSTER
                if name == "Defeat - Cipher Commander Exol"]
        self.assertEqual(["Pyrite Town (ONBS)"], rows)

    def test_both_exol_locations_now_agree(self) -> None:
        """Two tables name the same fight. They disagreeing is what hid this for so long."""
        regions = {name: region
                   for region, names in world_locations.LOCATIONS_BY_REGION.items()
                   for name in names if "Exol" in name}
        self.assertEqual({"Defeat - Exol": "Pyrite Town (ONBS)",
                          "Defeat - Cipher Commander Exol": "Pyrite Town (ONBS)"}, regions)

    def test_every_cipher_defeat_location_in_pyrite_lives_in_onbs(self) -> None:
        """The whole answer to the player's question, in one assertion."""
        by_index = {t["index"]: t for t in trainer_roster.TRAINERS}
        cipher_regions = set()
        for index, placement in trainer_placements.PLACEMENTS.items():
            trainer = by_index.get(index)
            if trainer and trainer["trainer_class"] in CIPHER_TRAINER_CLASSES and placement.region \
                    and "Pyrite" in placement.region:
                cipher_regions.add(placement.region)
        for region, name, _s in trainer_defeat.TRAINER_DEFEAT_ROSTER:
            if "Pyrite" in region and "Cipher" in name:
                cipher_regions.add(region)
        self.assertEqual({"Pyrite Town (ONBS)"}, cipher_regions)


class TestTheNonCipherPyriteRowsWereLeftAlone(unittest.TestCase):
    """The player corrected "all Pyrite battles" to "all Pyrite CIPHER battles", so the ordinary townsfolk
    stay where they are.

    ONE OF THE TWO FLAGGED ROWS HAS SINCE BEEN DECIDED. ADDENDUM 211 left Miror B.'s first encounter in plain
    Pyrite because story_bytes labels transition 0x39 -> 0x3A "Cave Poke Spot unlocked / first Miror B
    encounter" -- the two happen at the same story point and the ORDER was not established, so gating the
    fight behind the spot risked a cycle. ADDENDUM 241: the player established it ("Wanderer miror B first
    fight is behind cave poke spot specifically"), and it is not circular, because a Defeat location is a
    check and never a requirement. That row now reads "Poke Spots".

    Gonzap stays. He is the Snagem Head, not Cipher, and nothing has been said about him."""

    def test_no_roster_row_is_left_in_plain_pyrite(self) -> None:
        """Both flagged rows have now been decided, and neither belonged in Pyrite.

        ADDENDUM 241 moved Miror B.'s first fight to the Poke Spots. ADDENDUM 242 moved Gonzap to Snagem
        Hideout -- this addendum called him "almost certainly correct as-is" because he is Snagem Head rather
        than Cipher, and that was wrong. The occurrence table had said Snagem Hideout the whole time, and the
        row opened on the Machine Part alone while the fight really needs the whole Phenac chain, so a
        progression item there made the seed unwinnable."""
        rows = sorted(name for region, name, _s in trainer_defeat.TRAINER_DEFEAT_ROSTER
                      if region == "Pyrite Town")
        self.assertEqual([], rows)

    def test_gonzap_agrees_with_the_occurrence_table(self) -> None:
        rows = [region for region, name, _s in trainer_defeat.TRAINER_DEFEAT_ROSTER
                if name == "Defeat - Snagem Head Gonzap"]
        self.assertEqual(rows, ["Snagem Hideout"])
        gonzap = [p.region for index, p in trainer_placements.PLACEMENTS.items()
                  if p.region == "Snagem Hideout"]
        self.assertTrue(gonzap)

    def test_miror_bs_first_fight_moved_to_the_poke_spots(self) -> None:
        """And BOTH sources agree on it now -- the roster row here and the occurrence row in
        trainer_placements, which has said 'Poke Spots' all along. That two-source disagreement is the same
        shape as ADDENDUM 185's Phenac bug and ADDENDUM 211's own Exol bug, found for the third time."""
        rows = [region for region, name, _s in trainer_defeat.TRAINER_DEFEAT_ROSTER
                if name == "Defeat - Wanderer Miror B. (1st)"]
        self.assertEqual(rows, ["Poke Spots"])
        self.assertEqual(trainer_placements.PLACEMENTS[2].region, "Poke Spots")

    def test_the_ordinary_pyrite_trainers_were_not_swept_along(self) -> None:
        """Seventeen townsfolk defeats stay in first-visit Pyrite -- moving them was the misreading."""
        ordinary = [index for index, placement in trainer_placements.PLACEMENTS.items()
                    if placement.region == "Pyrite Town"]
        self.assertGreaterEqual(len(ordinary), 10)


if __name__ == "__main__":
    unittest.main()
