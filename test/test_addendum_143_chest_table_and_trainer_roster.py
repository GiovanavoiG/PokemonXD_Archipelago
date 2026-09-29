"""ADDENDUM 143 (2026-09-11): the chest-by-room table and the named trainer roster.

Both are GENERATED from the player's own ISO, so these tests guard the shape and the specific facts that were
cross-checked by hand -- not the generator, which is not shipped."""
from __future__ import annotations

import unittest

from ..game_data import chest_table, trainer_roster


class TestChestTable(unittest.TestCase):
    def test_the_table_matches_the_treasure_table_it_came_from(self) -> None:
        self.assertEqual(len(chest_table.CHESTS), 115)
        self.assertEqual(len(chest_table.CHESTS_BY_ROOM), 58)

    def test_every_chest_has_the_fields_a_descriptor_needs(self) -> None:
        for chest in chest_table.CHESTS:
            for key in ("chest", "room", "item", "qty", "model", "x", "y", "z"):
                self.assertIn(key, chest)

    def test_chest_indices_are_unique_so_they_can_be_labelled_against(self) -> None:
        indices = [c["chest"] for c in chest_table.CHESTS]
        self.assertEqual(len(indices), len(set(indices)))

    def test_the_id_card_chest_is_where_the_iso_and_the_live_game_both_say(self) -> None:
        """Chest 18, room 8, item 506 -- the Cipher Lab. Room 8 is also one of the three rooms whose id was
        cross-validated against live memory in ADDENDUM 142, so this row ties both findings together."""
        chest = next(c for c in chest_table.CHESTS if c["chest"] == 18)
        self.assertEqual((chest["room"], chest["item"]), (8, 506))
        self.assertIn(18, chest_table.DESCRIPTORS)

    def test_lookup_by_room(self) -> None:
        cipher = chest_table.chests_in_room(8)
        self.assertEqual(len(cipher), 5)
        self.assertEqual(sorted(c["chest"] for c in cipher), [17, 18, 19, 21, 22])
        self.assertEqual(chest_table.chests_in_room(None), [])
        self.assertEqual(chest_table.chests_in_room(999999), [])

    def test_lookup_returns_a_copy_so_callers_cannot_corrupt_the_table(self) -> None:
        got = chest_table.chests_in_room(8)
        got.clear()
        self.assertEqual(len(chest_table.chests_in_room(8)), 5)

    def test_describe_includes_the_coordinates_that_separate_two_chests_in_one_room(self) -> None:
        a, b = (c for c in chest_table.chests_in_room(8) if c["chest"] in (17, 18))
        self.assertNotEqual((a["x"], a["y"], a["z"]), (b["x"], b["y"], b["z"]))
        text = chest_table.describe_chest(a)
        self.assertIn("#17", text)
        self.assertIn("x=", text)
        self.assertIn("z=", text)

    def test_describe_surfaces_a_hand_written_descriptor_when_there_is_one(self) -> None:
        text = chest_table.describe_chest(next(c for c in chest_table.CHESTS if c["chest"] == 18))
        self.assertIn("ID Card", text)

    def test_the_fenced_key_item_chests_are_all_present_and_countable(self) -> None:
        """24 chests hold an id >= 500 and are excluded from randomization (ADDENDUM 134). The count has to
        stay consistent with locations.CHEST_LOCATION_COUNT or the seed breaks.

        RETARGETED 2026-09-13 (ADDENDUM 168): the key-item fence is no longer the ONLY thing that removes a
        chest. chest_regions.EXCLUDED_ROOMS drops two whole rooms, and one of their chests (115, item id 0 x10
        in the room 175 debug room) is below KEY_ITEM_ID_FLOOR, so the fence never saw it. The other two
        chests in dropped rooms (9 and 114) are key items and were already fenced, which is why the count moved
        by exactly one. Both subtractions are asserted so a future room exclusion cannot silently rebalance
        this against CHEST_LOCATION_COUNT.
        """
        from .. import locations
        from ..game_data import chest_regions
        from ..tools import xd_rel_format as rel

        fenced = [c for c in chest_table.CHESTS if c["item"] >= rel.KEY_ITEM_ID_FLOOR]
        self.assertEqual(len(fenced), 24)
        in_dropped_rooms = [c for c in chest_table.CHESTS
                            if c["item"] < rel.KEY_ITEM_ID_FLOOR and c["room"] in chest_regions.EXCLUDED_ROOMS]
        self.assertEqual([c["chest"] for c in in_dropped_rooms], [115])
        # ADDENDUM 174: compares against CHEST_COVERED_CHEST_COUNT now -- see that addendum and
        # test_addendum_134 for why the chest count and the location count legitimately differ by one.
        # ADDENDUM 177: plus the five fenced chests KeyItemShuffle converts -- see test_addendum_134.
        from ..game_data import key_item_chests

        self.assertEqual(len(chest_table.CHESTS) - len(fenced) - len(in_dropped_rooms)
                         + len(key_item_chests.SHUFFLED_KEY_ITEM_CHESTS),
                         locations.CHEST_COVERED_CHEST_COUNT)


class TestTrainerRoster(unittest.TestCase):
    def test_every_trainer_in_the_iso_roster_is_present_and_named(self) -> None:
        self.assertEqual(len(trainer_roster.TRAINERS), 232)
        self.assertTrue(all(t["name"] for t in trainer_roster.TRAINERS))

    def test_indices_are_unique(self) -> None:
        indices = [t["index"] for t in trainer_roster.TRAINERS]
        self.assertEqual(len(indices), len(set(indices)))

    def test_the_uniquely_named_count_is_what_makes_per_trainer_checks_viable(self) -> None:
        """109 trainers can be identified from the battle roster's surname alone; the rest need the
        occurrence counter, exactly like the existing hand-curated queue."""
        self.assertEqual(len(trainer_roster.UNIQUELY_NAMED), 109)
        for name in trainer_roster.UNIQUELY_NAMED:
            self.assertEqual(len(trainer_roster.TRAINERS_BY_NAME[name]), 1)

    def test_known_trainers_decoded_correctly(self) -> None:
        """Spot-checks against names this project already knew from live play, so a future regeneration that
        silently shifts the string-table offset gets caught."""
        for name in ("BARDO", "CHOBIN", "MIROR B.", "AFERD", "MIRU"):
            self.assertIn(name, trainer_roster.TRAINERS_BY_NAME, name)
        self.assertEqual(trainer_roster.TRAINERS_BY_INDEX[32]["name"], "BARDO")

    def test_occurrence_numbering_is_dense_and_in_index_order(self) -> None:
        for name, group in trainer_roster.TRAINERS_BY_NAME.items():
            ordered = sorted(group, key=lambda t: t["index"])
            self.assertEqual([t["occurrence"] for t in ordered], list(range(1, len(group) + 1)), name)
            self.assertTrue(all(t["total_with_name"] == len(group) for t in group), name)

    def test_labels_are_unique_across_the_whole_roster(self) -> None:
        """They are candidate Archipelago location names, so a collision would silently merge two checks."""
        labels = [trainer_roster.trainer_label(t) for t in trainer_roster.TRAINERS]
        self.assertEqual(len(labels), len(set(labels)))

    def test_a_repeated_trainer_is_numbered_and_a_unique_one_is_not(self) -> None:
        miror = trainer_roster.TRAINERS_BY_NAME["MIROR B."]
        self.assertEqual(len(miror), 9)
        self.assertIn("#1", trainer_roster.trainer_label(miror[0]))
        solo = trainer_roster.TRAINERS_BY_INDEX[32]
        self.assertEqual(trainer_roster.trainer_label(solo), "Defeat - Bardo")

    def test_teams_survived_the_regeneration(self) -> None:
        for trainer in trainer_roster.TRAINERS:
            self.assertEqual(len(trainer["team"]), trainer["party_size"])
            self.assertGreaterEqual(trainer["party_size"], 1)
            self.assertLessEqual(trainer["party_size"], 6)


if __name__ == "__main__":
    unittest.main()
