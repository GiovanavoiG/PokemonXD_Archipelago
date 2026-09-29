"""ADDENDUM 152 (2026-09-11): the player's room/story compilation, and missable trainers.

Player: "I've compiled some info. This isn't done yet, but record this and make sure the missable trainers are
excluded from useful/progressive items."

The second half is the load-bearing one. ADDENDUM 150 made per-trainer defeat checks eligible to hold
progression -- correct for a fight you will certainly have, and an unwinnable seed for one you can walk past.
That is not a modelling risk like the sphere approximations elsewhere; it happens every single time the fight
is skipped. So missable trainers are excluded at EVERY setting of an option whose whole point is to exclude
nothing, which is a deliberate exception and needs tests that say so.
"""
from __future__ import annotations

import unittest

from BaseClasses import LocationProgressType

from . import PokemonXDTestBase
from .. import locations, ram_client as rc
from ..game_data import missable_trainers, trainer_roster


class TestTheMissableList(unittest.TestCase):
    def test_it_holds_the_forty_seven_the_player_identified(self) -> None:
        """EXPANDED 2026-09-13 (ADDENDUM 167) from {8, 51} to the player's full compiled list. Pinned as a
        count plus spot checks rather than the whole literal set, so the set can be corrected without
        rewriting an assertion that merely restates it."""
        self.assertEqual(len(missable_trainers.MISSABLE_TRAINER_INDICES), 47)
        self.assertTrue({8, 51}.issubset(missable_trainers.MISSABLE_TRAINER_INDICES),
                        "the original two must survive the expansion")

    def test_every_missable_index_is_a_real_roster_trainer(self) -> None:
        for index in sorted(missable_trainers.MISSABLE_TRAINER_INDICES):
            self.assertIn(index, trainer_roster.TRAINERS_BY_INDEX, index)

    def test_only_occurrence_one_is_fenced_except_biden(self) -> None:
        """The player's list reads "Name 1" throughout -- occurrence 1 only -- with Biden the single name they
        listed twice. A later occurrence sneaking in would silently fence a trainer that can always be fought."""
        later = {
            index for index in missable_trainers.MISSABLE_TRAINER_INDICES
            if trainer_roster.TRAINERS_BY_INDEX[index]["occurrence"] != 1
        }
        self.assertEqual(later, {148}, "only Biden 2 may be a non-first occurrence")

    def test_all_six_sixes_are_fenced_with_the_corrected_names(self) -> None:
        """The player's list said "redsix" (no such trainer), listed Greesix twice, and omitted Browsix. The
        roster's real six are RESIX, BLUSIX, BROWSIX, YELLOSIX, PURPSIX, GREESIX at indices 33-38."""
        sixes = {33, 34, 35, 36, 37, 38}
        self.assertTrue(sixes.issubset(missable_trainers.MISSABLE_TRAINER_INDICES))
        self.assertEqual(
            {trainer_roster.TRAINERS_BY_INDEX[i]["name"] for i in sixes},
            {"RESIX", "BLUSIX", "BROWSIX", "YELLOSIX", "PURPSIX", "GREESIX"},
        )

    def test_index_8_is_aferds_first_fight(self) -> None:
        trainer = trainer_roster.TRAINERS_BY_INDEX[8]
        self.assertEqual((trainer["name"], trainer["occurrence"]), ("AFERD", 1))

    def test_index_51_is_digor_and_he_is_fought_only_once(self) -> None:
        """A trainer with a second encounter would have a fallback; Digor does not."""
        trainer = trainer_roster.TRAINERS_BY_INDEX[51]
        self.assertEqual(trainer["name"], "DIGOR")
        self.assertEqual(trainer["total_with_name"], 1)

    def test_the_names_resolve_through_the_roster_not_a_hardcoded_string(self) -> None:
        """A regeneration that renumbered an occurrence suffix would leave a hardcoded name matching nothing,
        silently un-protecting the check."""
        names = missable_trainers.missable_trainer_location_names()
        self.assertEqual(len(names), len(missable_trainers.MISSABLE_TRAINER_INDICES))
        self.assertIn("Defeat - Aferd #1", names)
        self.assertIn("Defeat - Digor", names)
        self.assertIn("Defeat - Browsix #1", names)

    def test_every_resolved_name_is_a_real_location(self) -> None:
        for name in missable_trainers.missable_trainer_location_names():
            self.assertIn(name, locations.LOCATION_TABLE, name)
            self.assertIn(name, locations.UNIQUE_TRAINER_DEFEAT_LOCATION_NAMES, name)

    def test_an_unknown_index_is_skipped_rather_than_crashing_generation(self) -> None:
        original = missable_trainers.MISSABLE_TRAINER_INDICES
        try:
            missable_trainers.MISSABLE_TRAINER_INDICES = frozenset({8, 999999})
            self.assertEqual(missable_trainers.missable_trainer_location_names(),
                             {"Defeat - Aferd #1"})
        finally:
            missable_trainers.MISSABLE_TRAINER_INDICES = original


class _UniqueModeBase(PokemonXDTestBase):
    def progress_type(self, name: str):
        return self.multiworld.get_location(name, self.player).progress_type


class TestExcludedEvenAtTheMostPermissiveSetting(_UniqueModeBase):
    options = {
        "randomize_chests": True,
        "shuffle_trainer_defeats": True,
        "trainer_defeat_mode": 1,
        "progression_locations": 2,
    }

    def test_the_players_missable_compilation_is_the_fence_again(self) -> None:
        """INVERTED 2026-09-13 (ADDENDUM 171), RE-APPLIED 2026-09-14 (ADDENDUM 185).

        171 emptied the fence on the player's "Story trainers are NOT missable". 185 puts it back on their
        correction to that: "all of those Sixes are marked missable - can you check the excel spreadsheet
        again? they shouldn't be carrying anything important." The workbook's own "Missable?" column has 47
        rows set, including 33-38, so the data was right and only its application had been withdrawn."""
        fenced = missable_trainers.filler_only_trainer_location_names()
        # WIDENED 2026-09-14 (ADDENDUM 188): the workbook's 47 rows name 46 TRAINERS, and every occurrence of
        # those trainers is fenced -- 101 locations, not 47. See that module's own section comment.
        # ADDENDUM 362 (2026-09-26): minus whatever `trainer_roster` has RETIRED. Those indices are still
        # fenced -- the fence is on the trainer, and every one of them is still a fight no item may depend on
        # -- but a retired label is not a location, so it has no progress type to assert and the name helper
        # leaves it out. One today: `Defeat - Chobin #7`.
        self.assertEqual(
            len(fenced),
            len(missable_trainers.FILLER_ONLY_TRAINER_INDICES)
            - len(trainer_roster.RETIRED_UNIQUE_DEFEAT_LOCATIONS
                  & {trainer_roster.trainer_label(trainer_roster.TRAINERS_BY_INDEX[i])
                     for i in missable_trainers.FILLER_ONLY_TRAINER_INDICES}),
        )
        self.assertGreater(len(fenced), len(missable_trainers.MISSABLE_TRAINER_INDICES))
        for name in fenced:
            self.assertEqual(self.progress_type(name), LocationProgressType.EXCLUDED, name)

    def test_an_ordinary_trainer_check_is_not(self) -> None:
        """Without this the test above could pass because everything is excluded."""
        self.assertEqual(self.progress_type("Defeat - Bardo"), LocationProgressType.DEFAULT)

    def test_every_occurrence_of_a_missable_trainer_is_fenced(self) -> None:
        """INVERTED 2026-09-14 (ADDENDUM 188). This used to assert the opposite -- that Resix #2 stayed an
        ordinary check because only #1 is in the workbook. That reading was mine, not the player's, and it left
        54 fights against trainers they had told us can be missed fully progression-eligible. A trainer you can
        walk past is one you can walk past every time you would have met them."""
        for name in ("Defeat - Aferd #1", "Defeat - Aferd #2", "Defeat - Aferd #5",
                     "Defeat - Digor", "Defeat - Resix #1", "Defeat - Resix #6",
                     "Defeat - Browsix #1", "Defeat - Browsix #4",
                     "Defeat - Zook #1", "Defeat - Zook #2", "Defeat - Laken #3"):
            self.assertEqual(self.progress_type(name), LocationProgressType.EXCLUDED, name)

    def test_the_missable_list_is_the_applied_fence_widened_to_every_occurrence(self) -> None:
        """ADDENDUM 171 kept the 47-entry field compilation as data while withdrawing it as a rule; ADDENDUM
        185 re-applied it; ADDENDUM 188 widened it from those 47 OCCURRENCES to all 101 occurrences of the 46
        trainers they name.

        WIDENED AGAIN 2026-09-14 (ADDENDUM 192) to 150, and the reason is that `Missable?` was never the only
        column. The workbook's `Repeat?` column marks 88 rows "earlier (N of M)" -- a fight with a later
        occurrence, which therefore does not come back -- and only 20 of those are also marked in `Missable?`.
        `Defeat - Chobin #3` is the row the player named: blank in `Missable?`, "earlier (3 of 7)" next to it.
        The fence is now the union of both columns, the name expansion over both, the 37 rows with no region
        data, and the goal fight (ADDENDUM 193). See game_data/census_repeat_column.py."""
        self.assertEqual(len(missable_trainers.MISSABLE_TRAINER_INDICES), 47)
        self.assertEqual(len(missable_trainers.FILLER_ONLY_TRAINER_INDICES), 150)   # ADDENDUM 341 lifted 337's +Wakin/+Gonzap
        self.assertTrue(missable_trainers.MISSABLE_TRAINER_INDICES
                        <= missable_trainers.FILLER_ONLY_TRAINER_INDICES,
                        "the workbook's own rows must all survive the widening")
        for index in (33, 34, 35, 36, 37, 38):
            self.assertIn(index, missable_trainers.FILLER_ONLY_TRAINER_INDICES,
                          "the six Sixes are the correction ADDENDUM 185 acted on")

    def test_the_mt_battle_deck_index_space_is_not_the_story_rosters(self) -> None:
        """Guards the mistake ADDENDUM 171's first cut made. MT_BATTLE_ALL_TRAINER_INDICES is range(1, 101) --
        the Mt. Battle DECK's own numbering -- so using it against the story roster fences story trainers 1-100
        by number. "Defeat - Bardo" (story index 32) coming back EXCLUDED was the tell. The two spaces are
        provably separate: Mt. Battle's surnames have zero overlap with the story roster's."""
        from ..game_data import mtbattle_trainer_data

        mt_only = {n.upper() for n in getattr(mtbattle_trainer_data, "MT_BATTLE_ONLY_SURNAMES", ())}
        story_names = {t["name"].upper() for t in trainer_roster.TRAINERS}
        self.assertEqual(mt_only & story_names, set(),
                         "Mt. Battle's deck and the story roster must share no names")
        self.assertEqual(self.progress_type("Defeat - Bardo"), LocationProgressType.DEFAULT,
                         "a story trainer must never be fenced by a Mt. Battle deck index")

    def test_the_locations_still_exist_and_can_still_be_checked(self) -> None:
        """Excluded means "no progression or useful item", not "removed" -- beating the trainer still sends."""
        all_names = {loc.name for loc in self.multiworld.get_locations(self.player)}
        for name in missable_trainers.filler_only_trainer_location_names():
            self.assertIn(name, all_names)


class TestStillExcludedAtEverySetting(_UniqueModeBase):
    options = {
        "randomize_chests": True,
        "shuffle_trainer_defeats": True,
        "trainer_defeat_mode": 1,
        "progression_locations": 1,
    }

    def test_world_checks_setting_does_not_re_open_them(self) -> None:
        """ADDENDUM 171: walks the fenced set (Mt. Battle's ladder), not the retired missable list."""
        for name in missable_trainers.filler_only_trainer_location_names():
            self.assertEqual(self.progress_type(name), LocationProgressType.EXCLUDED, name)


class TestRoomTable(unittest.TestCase):
    def test_the_players_compilation_is_recorded(self) -> None:
        for room_id in (1, 7, 8, 10, 11, 20, 21, 125, 126, 132,
                        138, 139, 140, 141, 143, 146, 156, 158, 160, 169, 173, 910):
            self.assertIn(room_id, rc.KNOWN_ROOM_IDS, room_id)

    def test_the_four_hq_lab_interior_rooms_are_distinct_names(self) -> None:
        """140 used to be the only "interior" -- the lab actually has four."""
        names = [rc.KNOWN_ROOM_IDS[i] for i in (138, 139, 140, 141)]
        self.assertEqual(len(set(names)), 4)
        for name in names:
            self.assertIn("interior", name)

    def test_kaminkos_inside_and_outside_are_not_the_same_room(self) -> None:
        self.assertNotEqual(rc.KNOWN_ROOM_IDS[169], rc.KNOWN_ROOM_IDS[173])

    def test_the_map_screen_is_named_so_it_is_not_mistaken_for_a_place(self) -> None:
        self.assertIn("map screen", rc.KNOWN_ROOM_IDS[910])

    def test_every_room_id_is_within_what_the_reader_accepts(self) -> None:
        for room_id in rc.KNOWN_ROOM_IDS:
            self.assertGreater(room_id, 0, room_id)
            self.assertLessEqual(room_id, rc.ROOM_ID_MAX_PLAUSIBLE, room_id)

    def test_the_chest_rooms_named_really_do_hold_chests(self) -> None:
        """Cross-checks the player's own chest labelling against the ISO's treasure table."""
        from ..game_data import chest_table

        for room_id in (8, 10, 143, 158):
            self.assertTrue(chest_table.chests_in_room(room_id),
                            f"room {room_id} is labelled with chests but the ISO table has none")


class TestStoryLandmarks(unittest.TestCase):
    def test_the_new_transitions_are_recorded(self) -> None:
        for value in (0x10, 0x16, 0x17, 0x19, 0x23, 0x24, 0x26):
            self.assertIn(value, rc.STORY_BYTE_LANDMARKS, hex(value))

    def test_the_earlier_observations_were_not_overwritten(self) -> None:
        """ADDENDUM 140's lesson: a later reading replacing an earlier one is how a retraction starts."""
        for value in (0x0F, 0x11, 0x20, 0x21, 0x25, 0x28, 0x2B, 0x2D, 0x2F):
            self.assertIn(value, rc.STORY_BYTE_LANDMARKS, hex(value))

    def test_the_conflicting_purification_entry_is_labelled_rather_than_silently_kept(self) -> None:
        """0x25 says "first purification", the new compilation says 0x21 -> 0x23. Both stay; the older one
        has to admit it is the older one."""
        self.assertIn("EARLIER", rc.STORY_BYTE_LANDMARKS[0x25])
        self.assertIn("purified", rc.STORY_BYTE_LANDMARKS[0x23])

    def test_every_landmark_is_a_plausible_story_value(self) -> None:
        for value in rc.STORY_BYTE_LANDMARKS:
            self.assertLessEqual(value, rc.STORY_BYTE_MAX_PLAUSIBLE, hex(value))


if __name__ == "__main__":
    unittest.main()
