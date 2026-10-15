"""ADDENDUM 409 (2026-10-03) -- a trim of the trainer-defeat roster.

  * The Sixes fight at many points: their #1 is at Cipher Lab and their #2 at Phenac (missable, behind the disc
    and the note). All their other fights are removed.
  * Cail's rematches are removed, and his normal fight is at Pyrite.
  * The rematches of Cida, Clerr, Belish, Dosk, Hebon, Aferd, Eagun, Finol, Dert, Raling, Labet, Doby, Eroll,
    Equin, Willie and Dobit are removed.
  * Miror B. keeps only one rematch (so up to Miror B. #2). His #1 and #2 can be at either the Outskirt Stand or
    the cave Poke Spot interchangeably, or the Colosseum if his radar fires.
  * Hordel is not a check, so he is removed as one, but he stays randomized.

Only CHECKS go. The fights stay in the game and the trainer data is randomized exactly as before; a removed label
leaves the location table and the dispatch queue, and its frozen id stays behind inert (ADDENDUM 242).
"""
from __future__ import annotations

import unittest

from BaseClasses import CollectionState

from . import PokemonXDTestBase
from .. import locations as L
from .. import trainer_defeat as TD
from ..game_data import missable_autosend, missable_indices, trainer_placements, trainer_roster as TR

SIXES = ("Resix", "Blusix", "Browsix", "Yellosix", "Purpsix", "Greesix")
SIXES_FIRST = (33, 34, 35, 36, 37, 38)
SIXES_SECOND = (39, 40, 41, 42, 43, 44)
QUEUE = TR.UNIQUE_SURNAME_TO_LOCATION_QUEUE


class TestTheRuledOutLabelsAreGone(unittest.TestCase):
    def test_every_ruled_out_label_is_not_a_location(self) -> None:
        self.assertEqual(70, len(TR.RULED_OUT_DEFEAT_LOCATIONS))   # ADDENDUM 436: + six Ardos/Zook/Biden labels
        for name in TR.RULED_OUT_DEFEAT_LOCATIONS:
            self.assertNotIn(name, L.LOCATION_TABLE, name)

    def test_every_ruled_out_label_is_out_of_the_dispatch_queue(self) -> None:
        queued = {name for labels in QUEUE.values() for name in labels}
        self.assertFalse(queued & TR.RULED_OUT_DEFEAT_LOCATIONS)

    def test_every_ruled_out_frozen_id_is_kept_and_not_reused(self) -> None:
        live = {data.id_offset for data in L.LOCATION_TABLE.values()}
        for name in TR.RULED_OUT_DEFEAT_LOCATIONS | TD.RULED_OUT_NAMED_LOCATIONS:
            self.assertIn(name, L._FROZEN_LOCATION_OFFSETS, name)
            self.assertNotIn(L._FROZEN_LOCATION_OFFSETS[name], live, f"{name}'s id was handed to another location")

    def test_the_ruled_out_set_is_exactly_the_list(self) -> None:
        keep_one = {"CAIL", "CIDA", "CLERR", "BELISH", "DOSK", "HEBON", "AFERD", "EAGUN", "FINOL", "DERT", "RALING",
                    "LABET", "DOBY", "EROLL", "EQUIN", "WILLIE", "DOBIT"}
        keep_two = {s.upper() for s in SIXES} | {"MIROR B."}
        expected = set()
        for trainer in TR.TRAINERS:
            surname = trainer["name"].upper()
            if (surname == "HORDEL" or (surname in keep_one and trainer["occurrence"] >= 2)
                    or (surname in keep_two and trainer["occurrence"] >= 3)
                    or surname in {"ARDOS", "ZOOK", "BIDEN"}):   # ADDENDUM 436: one (Any) each
                expected.add(TR.trainer_label(trainer))
        self.assertEqual(expected, set(TR.RULED_OUT_DEFEAT_LOCATIONS))


class TestTheSurvivingQueues(unittest.TestCase):
    def test_the_sixes_keep_one_and_two(self) -> None:
        # "Make their #1 at Cipher Lab, and make their #2 at Phenac ... Remove all their other fights."
        self.assertEqual(["Defeat - Resix #1", "Defeat - Resix #2"], QUEUE["RESIX"])
        for six in SIXES:
            self.assertEqual([f"Defeat - {six} #1", f"Defeat - {six} #2"], QUEUE[six.upper()], six)

    def test_cail_keeps_his_normal_fight_at_pyrite(self) -> None:
        # "Remove Cail's rematches, and his normal fight is at pyrite." ADDENDUM 410 then took his lone #1 ("Any
        # trainers that only have 'any' and '#1', just remove the #1"), so the fight at Pyrite is checked by
        # `Defeat Cail (Any)`, which is regioned there.
        from ..game_data import repeatable_trainers as RT

        self.assertEqual([], QUEUE["CAIL"])
        self.assertNotIn("Defeat - Cail #1", L.LOCATION_TABLE)
        row = next(r for r in RT.REPEATABLE_TRAINERS if r["surname"] == "CAIL")
        self.assertEqual("Pyrite Town", row["region"])

    def test_miror_b_keeps_one_rematch(self) -> None:
        # "Make Miror B only have one rematch (so up to miror B 2)."
        self.assertEqual(["Defeat - Miror B. #1", "Defeat - Miror B. #2"], QUEUE["MIROR B."])

    def test_the_fully_trimmed_surnames_queue_nothing(self) -> None:
        # Their #1 is missable (removed by ADDENDA 401/406) and every rematch is removed.
        for surname in ("CIDA", "DOSK", "HEBON", "AFERD"):
            self.assertEqual([], QUEUE[surname], surname)
            self.assertIn(f"Defeat - {surname.title()} #1", TR.REMOVED_MISSABLE_DEFEAT_LOCATIONS, surname)

    def test_the_surnames_left_with_their_first_fight(self) -> None:
        # ADDENDUM 410: these were left with (Any) + #1, two checks on one win -- the #1 went.
        for surname in ("CLERR", "BELISH", "EAGUN", "DERT", "DOBIT"):
            self.assertEqual([], QUEUE[surname], surname)
            self.assertIn(f"Defeat - {surname.title()} #1", TR.ANY_DUPLICATE_DEFEAT_LOCATIONS, surname)


class TestHordel(unittest.TestCase):
    """"Hordel is not a check, so remove him, but keep him randomized.\""""

    def test_he_is_not_a_location(self) -> None:
        self.assertIn("Defeat - Hordel", TR.RULED_OUT_DEFEAT_LOCATIONS)
        self.assertNotIn("Defeat - Hordel", L.LOCATION_TABLE)
        self.assertEqual([], QUEUE["HORDEL"])

    def test_he_is_still_in_the_trainer_data_the_randomizer_reads(self) -> None:
        from ..game_data.real_trainer_data import PERMANENTLY_EXCLUDED_TRAINER_INDICES

        trainer = TR.TRAINERS_BY_INDEX[1]
        self.assertEqual("HORDEL", trainer["name"])
        self.assertTrue(trainer["team"], "his team is what the randomizer rolls")
        self.assertIn(1, trainer_placements.PLACEMENTS)
        self.assertNotIn(1, PERMANENTLY_EXCLUDED_TRAINER_INDICES, "keep him randomized")


class TestTheSixesPlacements(unittest.TestCase):
    def test_their_first_fight_is_at_cipher_lab_and_not_missable(self) -> None:
        for index in SIXES_FIRST:
            trainer = TR.TRAINERS_BY_INDEX[index]
            name = TR.trainer_label(trainer)
            self.assertEqual(1, trainer["occurrence"], name)
            self.assertEqual("Cipher Lab", trainer_placements.region_for(index), name)
            self.assertEqual("Cipher Lab", L.LOCATION_TABLE[name].region, name)
            self.assertNotIn(index, missable_indices.MISSABLE_TRAINER_INDICES, name)
            self.assertNotIn(name, missable_autosend.AUTO_SEND_AT_STORY_BYTE, name)

    def test_their_second_fight_is_at_phenac_missable_and_auto_sent(self) -> None:
        for index in SIXES_SECOND:
            trainer = TR.TRAINERS_BY_INDEX[index]
            name = TR.trainer_label(trainer)
            self.assertEqual(2, trainer["occurrence"], name)
            self.assertEqual("Phenac City (Post-Sixes)", trainer_placements.region_for(index), name)
            self.assertEqual("Phenac City (Post-Sixes)", L.LOCATION_TABLE[name].region, name)
            self.assertIn(index, missable_indices.MISSABLE_TRAINER_INDICES, name)
            self.assertIn(name, TR.KEPT_MISSABLE_DEFEAT_LOCATIONS, name)
            self.assertNotIn(name, TR.REMOVED_DEFEAT_LOCATIONS, name)
            # ADDENDUM 436: released when Snattle is defeated, like every missable Cipher fight in Phenac.
            self.assertEqual(missable_autosend.SNATTLE_DEFEATED, missable_autosend.AUTO_SEND_AT_STORY_BYTE[name], name)

    def test_the_kept_set_is_exactly_the_sixes_second_fights(self) -> None:
        self.assertEqual({f"Defeat - {six} #2" for six in SIXES}, set(TR.KEPT_MISSABLE_DEFEAT_LOCATIONS))


class TestMirorBTwoPlacement(unittest.TestCase):
    def test_it_is_placed_and_needs_both_spots(self) -> None:
        # "His 1 and 2 can be in either outskirt stand or cave spot interchangeably" -- #2 needs a second meeting.
        placement = trainer_placements.PLACEMENTS[3]
        self.assertEqual(("MIROR B.", 2), (TR.TRAINERS_BY_INDEX[3]["name"], TR.TRAINERS_BY_INDEX[3]["occurrence"]))
        self.assertEqual("Outskirt Stand", placement.region)
        self.assertEqual(("Poke Spots",), placement.required_regions)
        self.assertEqual("Outskirt Stand", L.LOCATION_TABLE["Defeat - Miror B. #2"].region)


class TestTheNamedRematches(unittest.TestCase):
    def test_the_two_named_rematches_are_retired(self) -> None:
        # "Remove Eagun's rematch." / "Make Miror B only have one rematch (so up to miror B 2)."
        self.assertEqual({"Defeat - Legendary Trainer Eagun", "Defeat - Wanderer Miror B. (final)"},
                         set(TD.RULED_OUT_NAMED_LOCATIONS))
        queued = {name for labels in TD.SURNAME_TO_LOCATION_QUEUE.values() for name in labels}
        for name in TD.RULED_OUT_NAMED_LOCATIONS:
            self.assertNotIn(name, L.LOCATION_TABLE, name)
            self.assertNotIn(name, queued, name)
            self.assertIn(name, TD.TRAINER_DEFEAT_LOCATION_NAMES, "kept in the roster as the record")
        self.assertEqual(["Defeat - Myth Trainer Eagun"], TD.SURNAME_TO_LOCATION_QUEUE["Eagun"])
        self.assertEqual(["Defeat - Wanderer Miror B. (1st)", "Defeat - Wanderer Miror B. (rematch)"],
                         TD.SURNAME_TO_LOCATION_QUEUE["Miror B."])


def _state_without(test: PokemonXDTestBase, withheld: str) -> CollectionState:
    state = CollectionState(test.multiworld)
    for item in test.multiworld.itempool:
        if item.player == test.player and item.name != withheld:
            state.collect(item, True)
    state.sweep_for_advancements()
    return state


class TestInAGeneratedWorld(PokemonXDTestBase):
    options = {"shuffle_trainer_defeats": True, "key_item_shuffle": True}

    def test_no_ruled_out_label_is_created(self) -> None:
        created = {location.name for location in self.multiworld.get_locations(self.player)}
        self.assertFalse(created & TR.RULED_OUT_DEFEAT_LOCATIONS)
        self.assertFalse(created & TD.RULED_OUT_NAMED_LOCATIONS)
        self.assertNotIn("Defeat - Hordel", created)

    def test_resix_two_needs_the_mayors_note(self) -> None:
        # Their #2 is at Phenac: missable, behind the disc and the note.
        self.assertIn("Mayor's Note", {item.name for item in self.multiworld.itempool})
        location = self.multiworld.get_location("Defeat - Resix #2", self.player)
        self.assertFalse(location.can_reach(_state_without(self, "Mayor's Note")))
        self.assertTrue(location.can_reach(_state_without(self, "")))

    def test_resix_two_needs_the_music_disc(self) -> None:
        location = self.multiworld.get_location("Defeat - Resix #2", self.player)
        self.assertFalse(location.can_reach(_state_without(self, "Music Disc")))


class TestMirorBTwoInATravelShuffledWorld(PokemonXDTestBase):
    """With travel randomization the two places open independently, so "needs both" is observable."""

    options = {"shuffle_trainer_defeats": True, "key_item_shuffle": True, "randomize_travel_locations": True}

    def test_it_needs_both_places(self) -> None:
        location = self.multiworld.get_location("Defeat - Miror B. #2", self.player)
        self.assertTrue(location.can_reach(_state_without(self, "")))
        withheld_any = False
        for region, unlock in (("Poke Spots", "Travel Unlock - Poke Spots"),
                               ("Outskirt Stand", "Travel Unlock - Outskirt Stand")):
            if unlock not in {item.name for item in self.multiworld.itempool}:
                continue
            withheld_any = True
            state = _state_without(self, unlock)
            self.assertFalse(state.can_reach(region, "Region", self.player), f"{unlock} does not gate {region}")
            self.assertFalse(location.can_reach(state), f"reachable without {region}")
        self.assertTrue(withheld_any, "neither travel unlock is in the pool, so nothing was tested")


if __name__ == "__main__":
    unittest.main()
