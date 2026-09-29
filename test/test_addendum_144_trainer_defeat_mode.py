"""ADDENDUM 144 (2026-09-11): the case-insensitive surname fix, and the cumulative/unique trainer-defeat mode.

The casing bug is the important half. The battle roster reports NPC trainer names in UPPER case ("LOVRINA"),
`trainer_defeat.SURNAME_TO_LOCATION_QUEUE` is keyed in title case ("Lovrina"), so every one of its 58 keys
missed and the 66 named defeat locations had never fired in any seed."""
from __future__ import annotations

import unittest

from .. import locations, ram_client as rc, trainer_defeat
from ..game_data import trainer_roster

R = rc.BattleRosterRecord


def _defeat_sequence(surname: str, species: tuple[str, ...] = ("ZUBAT", "GULPIN")):
    """A roster that goes alive -> dropping -> confirmed-zero, which is what the tracker needs to fire."""
    base = 0x804A8000
    alive = [R(base + i * 0xC4, surname, s, 20) for i, s in enumerate(species)]
    dying = [R(base + i * 0xC4, surname, s, 4) for i, s in enumerate(species)]
    dead = [R(base + i * 0xC4, surname, s, 0) for i, s in enumerate(species)]
    return [alive, dying, dead, dead]


def _run(queue, frames, cap=None):
    tracker = rc.TrainerBattleDefeatTracker()
    fired: list[str] = []
    for frame in frames:
        fired += tracker.poll(queue, locations.trainer_defeat_count_location_name,
                              records=frame, count_location_max=cap)
    return tracker, fired


class TestSurnameCasing(unittest.TestCase):
    def test_the_curated_queue_is_title_case_and_the_game_is_upper(self) -> None:
        """Pins the mismatch that caused the bug, so nobody 'fixes' one side and reintroduces it."""
        self.assertTrue(all(not key.isupper() for key in trainer_defeat.SURNAME_TO_LOCATION_QUEUE))
        self.assertIn("Lovrina", trainer_defeat.SURNAME_TO_LOCATION_QUEUE)
        self.assertNotIn("LOVRINA", trainer_defeat.SURNAME_TO_LOCATION_QUEUE)

    def test_an_uppercase_surname_now_dispatches_to_the_curated_location(self) -> None:
        """The regression itself: before the fix this fired only the cumulative count, never the named one."""
        expected = trainer_defeat.SURNAME_TO_LOCATION_QUEUE["Lovrina"][0]
        _tracker, fired = _run(trainer_defeat.SURNAME_TO_LOCATION_QUEUE, _defeat_sequence("LOVRINA"))
        self.assertIn(expected, fired)

    def test_a_title_case_surname_still_works(self) -> None:
        expected = trainer_defeat.SURNAME_TO_LOCATION_QUEUE["Lovrina"][0]
        _tracker, fired = _run(trainer_defeat.SURNAME_TO_LOCATION_QUEUE, _defeat_sequence("Lovrina"))
        self.assertIn(expected, fired)

    def test_greevil_goal_detection_can_fire_at_all(self) -> None:
        """Goal 0 watches for GREEVIL_DEFEAT_LOCATION_NAME coming out of this queue. With the casing bug that
        name could never be produced, so the goal could never auto-complete."""
        frames = _defeat_sequence("GREEVIL")
        _t1, first = _run(trainer_defeat.SURNAME_TO_LOCATION_QUEUE, frames)
        # Greevil's queue starts with a decoy sentinel (ADDENDUM 102), so the real name lands on the second win.
        # ADDENDUM 362: the two encounters must field different teams, which in the real game they do -- the
        # decoy battle and the real one are separate roster entries with separate decks. Two wins against one
        # team is a rematch now, and a rematch checks off nothing.
        tracker = rc.TrainerBattleDefeatTracker()
        fired: list[str] = []
        for team in (("ZUBAT", "GULPIN"), ("SALAMENCE",)):
            for frame in _defeat_sequence("GREEVIL", team):
                fired += tracker.poll(trainer_defeat.SURNAME_TO_LOCATION_QUEUE,
                                      locations.trainer_defeat_count_location_name, records=frame)
            for frame in ([], []):  # roster clears between encounters so the surname re-arms
                tracker.poll(trainer_defeat.SURNAME_TO_LOCATION_QUEUE,
                             locations.trainer_defeat_count_location_name, records=frame)
        self.assertIn(trainer_defeat.GREEVIL_DEFEAT_LOCATION_NAME, fired)


class TestUniqueRosterQueue(unittest.TestCase):
    def test_the_queue_covers_every_trainer_exactly_once(self) -> None:
        total = sum(len(v) for v in trainer_roster.UNIQUE_SURNAME_TO_LOCATION_QUEUE.values())
        # ADDENDUM 362: every trainer except the ones whose label was retired for having no distinct team.
        self.assertEqual(
            total, len(trainer_roster.TRAINERS) - len(trainer_roster.RETIRED_UNIQUE_DEFEAT_LOCATIONS)
        )
        names = [n for v in trainer_roster.UNIQUE_SURNAME_TO_LOCATION_QUEUE.values() for n in v]
        self.assertEqual(len(names), len(set(names)))

    def test_keys_are_upper_case_like_the_game_reports_them(self) -> None:
        self.assertTrue(all(k.isupper() or not k.isalpha()
                            for k in trainer_roster.UNIQUE_SURNAME_TO_LOCATION_QUEUE))

    def test_a_repeated_trainer_dispatches_in_occurrence_order(self) -> None:
        """RETARGETED 2026-09-26 (ADDENDUM 362): each encounter now fields a DIFFERENT team, because that is
        what advances the queue. Three wins against the same team would check off one location, not three --
        see test_addendum_362 for that half."""
        queue = trainer_roster.UNIQUE_SURNAME_TO_LOCATION_QUEUE
        self.assertEqual(len(queue["MIROR B."]), 9)
        tracker = rc.TrainerBattleDefeatTracker()
        fired: list[str] = []
        teams = (("ZUBAT", "GULPIN"), ("LUDICOLO",), ("LOUDRED", "GOLBAT"))
        for _encounter in range(3):
            for frame in _defeat_sequence("MIROR B.", teams[_encounter]):
                fired += tracker.poll(queue, locations.trainer_defeat_count_location_name,
                                      records=frame, count_location_max=0)
            tracker.poll(queue, locations.trainer_defeat_count_location_name, records=[],
                         count_location_max=0)  # roster clears, surname re-arms
        self.assertEqual(fired, ["Defeat - Miror B. #1", "Defeat - Miror B. #2", "Defeat - Miror B. #3"])

    def test_unique_mode_produces_no_cumulative_names(self) -> None:
        """count_location_max=0 is how the client suppresses the bucket in unique mode."""
        _tracker, fired = _run(trainer_roster.UNIQUE_SURNAME_TO_LOCATION_QUEUE,
                               _defeat_sequence("BARDO"), cap=0)
        self.assertEqual(fired, ["Defeat - Bardo"])
        self.assertFalse(any(n.startswith("Defeat ") and n.endswith(" Trainers") for n in fired))


class TestLocationTable(unittest.TestCase):
    def test_all_232_unique_locations_are_real_frozen_locations(self) -> None:
        """RETARGETED 2026-09-26 (ADDENDUM 362). The roster list still names all 232 real trainer battles --
        that is what the ids were frozen against and what a reader resolves a trainer index through, and it
        must not shrink. What a seed CREATES is now the active subset, because a `Defeat - X #N` fires on the
        Nth unique team and one label has no distinct team left behind it."""
        self.assertEqual(len(locations.UNIQUE_TRAINER_DEFEAT_LOCATION_NAMES), 232)
        for name in locations.ACTIVE_UNIQUE_TRAINER_DEFEAT_LOCATION_NAMES:
            self.assertIn(name, locations.LOCATION_TABLE, name)
        retired = trainer_roster.RETIRED_UNIQUE_DEFEAT_LOCATIONS
        self.assertEqual(
            len(locations.ACTIVE_UNIQUE_TRAINER_DEFEAT_LOCATION_NAMES), 232 - len(retired)
        )
        for name in retired:
            self.assertIn(name, locations.UNIQUE_TRAINER_DEFEAT_LOCATION_NAMES, name)
            self.assertNotIn(name, locations.LOCATION_TABLE, name)

    def test_their_ids_are_unique_and_do_not_collide_with_anything_older(self) -> None:
        ids = [locations.LOCATION_TABLE[n] for n in locations.ACTIVE_UNIQUE_TRAINER_DEFEAT_LOCATION_NAMES]
        self.assertEqual(len(ids), len(set(ids)))
        others = {v for k, v in locations.LOCATION_TABLE.items()
                  if k not in set(locations.UNIQUE_TRAINER_DEFEAT_LOCATION_NAMES)}
        self.assertFalse(set(ids) & others, "a new per-trainer id collides with an existing frozen id")

    def test_they_do_not_collide_with_the_curated_named_locations(self) -> None:
        curated = set(trainer_defeat.TRAINER_DEFEAT_LOCATION_NAMES)
        self.assertFalse(curated & set(locations.UNIQUE_TRAINER_DEFEAT_LOCATION_NAMES))

    def test_the_names_match_what_the_dispatch_queue_will_send(self) -> None:
        """If these ever drift apart the client fires location names that do not exist in the datapackage."""
        from_queue = {n for v in trainer_roster.UNIQUE_SURNAME_TO_LOCATION_QUEUE.values() for n in v}
        # ADDENDUM 362: against the ACTIVE set. The queue is what the client dispatches against, so a retired
        # label must be absent from BOTH -- a name in the queue but not the datapackage is the exact failure
        # this test exists to catch.
        self.assertEqual(from_queue, set(locations.ACTIVE_UNIQUE_TRAINER_DEFEAT_LOCATION_NAMES))

    def test_the_region_now_holds_only_the_unplaced_trainers(self) -> None:
        """RETARGETED 2026-09-13 (ADDENDUM 175). This bucket held all 232 because the ISO roster carried no
        region data. The player's census supplied it, so 195 trainers moved to the regions they are actually
        in and only the 37 with no known region are left here -- the 36 marked N/A plus Hordel, all
        filler-only. The bucket still exists and is still reachable from the start, because AP requires every
        location to be reachable so filler can be placed on it."""
        self.assertIn("Unique Trainer Defeats", locations.LOCATIONS_BY_REGION)
        self.assertEqual(len(locations.LOCATIONS_BY_REGION["Unique Trainer Defeats"]), 37)
        self.assertEqual(
            set(locations.LOCATIONS_BY_REGION["Unique Trainer Defeats"]),
            locations._UNPLACED_TRAINER_LOCATION_NAMES,
        )

    def test_every_roster_trainer_still_has_exactly_one_location(self) -> None:
        """The re-filing must not drop or duplicate one. 232 names, spread across the real regions plus the
        leftover bucket, and each appearing once."""
        placed = sum(1 for name in locations.UNIQUE_TRAINER_DEFEAT_LOCATION_NAMES
                     if name in locations._TRAINER_REGION_BY_LOCATION)
        self.assertEqual(placed, 195)
        self.assertEqual(placed + 37, 232)


class TestOption(unittest.TestCase):
    def test_the_option_exists_with_both_modes_and_defaults_to_unique(self) -> None:
        from ..options import TrainerDefeatMode

        # FLIPPED 2026-09-14 (ADDENDUM 196): the player's own YAML is the generated template now, and it
        # picks unique -- "Unique: one check per named trainer in the game. Recommended." in their own words.
        self.assertEqual(TrainerDefeatMode.default, 1)
        self.assertEqual(TrainerDefeatMode.option_cumulative, 0)
        self.assertEqual(TrainerDefeatMode.option_unique, 1)
        self.assertEqual(TrainerDefeatMode.display_name, "Cumulative or Unique Trainer Defeats")

    def test_it_is_wired_into_the_options_dataclass(self) -> None:
        from ..options import PokemonXDOptions

        self.assertIn("trainer_defeat_mode", PokemonXDOptions.__annotations__)


if __name__ == "__main__":
    unittest.main()
