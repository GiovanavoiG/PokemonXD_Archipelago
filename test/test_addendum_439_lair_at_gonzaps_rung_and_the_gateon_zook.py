"""ADDENDUM 439 (2026-10-08) -- the Key Lair at 0x64, and Zook's Gateon fight sending nothing.

Player: "I lied. put it to 64, so drop it one (two after the shift)."
Then: "Also, zook (any) sent at the gateon fight, which is wrong. Make sure that doesn't happen."
"""
from __future__ import annotations

import unittest

from BaseClasses import LocationProgressType

from . import PokemonXDTestBase
from .. import ram_client as rc
from ..game_data import missable_autosend as ma, repeatable_trainers as rt, story_bytes as sb
from ..game_data import trainer_roster as tr

LAIR = "Cipher Key Lair"


class TestTheFloor(unittest.TestCase):
    def test_gonzaps_rung(self) -> None:
        self.assertEqual(0x64, sb.AREA_ENTRY_FLOOR_OVERRIDES[LAIR])
        self.assertEqual(0x64, sb.area_entry_floor(LAIR))
        self.assertEqual(800, sb.story_value_for_byte(0x64))
        self.assertEqual(0x64, rc.AreaStoryByteMemory().target_for(LAIR))

    def test_zooks_fight_is_ahead_of_the_arrival(self) -> None:
        zook = [t for t in sb.TRANSITIONS if t.after == 0x65]
        self.assertEqual(1, len(zook))
        self.assertEqual(sb.area_entry_floor(LAIR), zook[0].before)

    def test_reachable_and_inside_the_window(self) -> None:
        window = sb.REGION_STORY_WINDOW[LAIR]
        self.assertTrue(sb.byte_is_reachable(0x64))
        self.assertLessEqual(window.floor, 0x64)
        self.assertLessEqual(0x64, window.ceiling)

    def test_the_unlock_floor_did_not_move(self) -> None:
        self.assertEqual(0x5D, sb.area_unlock_floor(LAIR))


class TestZooksBackstop(unittest.TestCase):
    def test_sent_only_past_his_fight(self) -> None:
        self.assertEqual(("Cipher Key Lair", 0x67), ma.FLOOR_SKIPPED_CHECKS["Defeat Zook (Any)"])
        self.assertEqual(0x67, ma.AUTO_SEND_AT_STORY_BYTE["Defeat Zook (Any)"])
        self.assertEqual((("Cipher Key Lair", 0x67),), ma.AUTO_SEND_AREA_CAPS["Defeat Zook (Any)"])
        self.assertGreater(0x67, 0x65, "only reachable through his fight's rung")
        self.assertIn("ZOOK", rt.ALWAYS_FILLER_SURNAMES)


class TestInAWorld(PokemonXDTestBase):
    options = {"shuffle_trainer_defeats": True, "trainer_defeat_mode": 1, "randomize_travel_locations": True}

    def test_zook_is_excluded(self) -> None:
        location = self.multiworld.get_location("Defeat Zook (Any)", self.player)
        self.assertEqual(LocationProgressType.EXCLUDED, location.progress_type)


# --- the Gateon fight -----------------------------------------------------------------------------------------

# What a real seed ships: Zook #1 is one Shadow and nothing else, so it has NO fingerprint (`_build_trainer_fingerprints`
# skips a team with no ordinary species); Zook #2's four ordinary species do.
FINGERPRINTS = {"Defeat - Zook #2": {"species": ["DODUO", "SWABLU", "SOLROCK", "NATU"], "base_party_size": 4}}
QUEUE: "dict[str, list[str | None]]" = {"ZOOK": []}


def _fight(tracker, species, watched_here=frozenset(), fingerprints=FINGERPRINTS):
    seen, fired = [], []
    for hp in (50, 6, 0, 0):
        frame = [rc.BattleRosterRecord(0x804A8000 + i * 0xC4, "ZOOK", name, hp) for i, name in enumerate(species)]
        fired += tracker.poll(QUEUE, lambda n: f"Defeat {n} Trainers", records=frame, count_location_max=10,
                              team_fingerprints=fingerprints, non_player_fights=tr.NON_PLAYER_FIGHTS,
                              watched_here=watched_here)
        seen += tracker.last_confirmed_surnames
    tracker.poll(QUEUE, lambda n: f"Defeat {n} Trainers", records=[], count_location_max=10,
                 team_fingerprints=fingerprints, non_player_fights=tr.NON_PLAYER_FIGHTS, watched_here=watched_here)
    return seen, fired


class TestTheGateonFightSendsNothing(unittest.TestCase):
    def test_the_real_seed_has_no_fingerprint_for_it(self) -> None:
        team = tr.TRAINERS_BY_INDEX[9]["team"]
        self.assertTrue(all(slot.get("dpkm_index") is None for slot in team), "Zook #1 is Shadow-only")

    def test_by_room(self) -> None:
        for room in (153, 147, 158):
            self.assertIn("ZOOK", rc.watched_fight_surnames(room), room)
            self.assertIn("ARDOS", rc.watched_fight_surnames(room), room)
        tracker = rc.TrainerBattleDefeatTracker()
        seen, fired = _fight(tracker, ("ZANGOOSE",), watched_here=rc.watched_fight_surnames(153))
        self.assertEqual(([], []), (seen, fired))
        self.assertEqual(0, tracker.wins_by_surname.get("ZOOK", 0))

    def test_by_elimination_when_the_room_is_unknown(self) -> None:
        tracker = rc.TrainerBattleDefeatTracker()
        seen, fired = _fight(tracker, ("ZANGOOSE",))
        self.assertEqual(([], []), (seen, fired))
        self.assertEqual("Defeat - Zook #1", tracker.last_ignored_fight)

    def test_the_lair_fight_still_counts(self) -> None:
        self.assertEqual(frozenset(), rc.watched_fight_surnames(64) & {"ZOOK"})
        tracker = rc.TrainerBattleDefeatTracker()
        seen, fired = _fight(tracker, ("DODUO", "SWABLU", "SOLROCK", "NATU", "SNEASEL"),
                             watched_here=rc.watched_fight_surnames(64))
        self.assertEqual(["ZOOK"], seen)
        self.assertEqual(["Defeat 1 Trainers"], fired)

    def test_the_played_fights_are_never_in_a_watched_room(self) -> None:
        for room in (64, 65, 66, 67, 68, 70):       # the Key Lair: Zook's fight
            self.assertNotIn("ZOOK", rc.watched_fight_surnames(room), room)
        for room in range(73, 89):                  # Citadark: Ardos's fight
            self.assertNotIn("ARDOS", rc.watched_fight_surnames(room), room)
        for room in (165, 166, 167):                # Snagem: Biden's fight
            self.assertEqual(frozenset(), rc.watched_fight_surnames(room), room)
        self.assertIn("BIDEN", rc.watched_fight_surnames(64))
        self.assertEqual(frozenset(), rc.watched_fight_surnames(None))
        self.assertEqual(frozenset(), rc.watched_fight_surnames(rc.MAP_SCREEN_ROOM_ID))

    def test_wired_into_the_client(self) -> None:
        from pathlib import Path
        source = (Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")
        self.assertIn("watched_here=ram_client.watched_fight_surnames(", source)


if __name__ == "__main__":
    unittest.main()
