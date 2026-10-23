"""ADDENDUM 436 (2026-10-08) -- fights the player only watches, the Phenac Cipher fights, and Biden.

Missable Phenac trainers send upon defeating Snattle (Cipher members ONLY); Bost stays as he is. Biden is NOT
missable in Snagem with the current settings, so his check moves off the Key Lair defeat and onto Snagem.

The two fights where the player does not act are Ardos vs Zook in Gateon and Zook vs Biden in the Key Lair. Those
fights DO NOT send a check, their #1/#2 checks are removed, and the check for Ardos, Zook and Biden sends upon
defeating them in Citadark, the Key Lair and Snagem respectively.
"""
from __future__ import annotations

import pathlib
import unittest

from BaseClasses import LocationProgressType

from . import PokemonXDTestBase
from .. import locations as L, ram_client as rc
from ..game_data import missable_autosend as ma, missable_indices as mi, repeatable_trainers as rt
from ..game_data import shadow_regions, story_bytes, trainer_placements, trainer_roster as tr

CLIENT = (pathlib.Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")


class TestTheWatchedFights(unittest.TestCase):
    def test_the_three_rows(self):
        self.assertEqual({9, 10, 148}, set(mi.NON_PLAYER_FIGHT_INDICES))
        names = {tr.TRAINERS_BY_INDEX[i]["name"] for i in mi.NON_PLAYER_FIGHT_INDICES}
        self.assertEqual({"ZOOK", "ARDOS", "BIDEN"}, names)
        # The same three rows the Shadow fence calls unsnaggable (ADDENDA 432/433).
        self.assertEqual(set(shadow_regions.NO_SNAG_TRAINER_INDICES), set(mi.NON_PLAYER_FIGHT_INDICES))

    def test_the_client_table(self):
        self.assertEqual((("Defeat - Zook #1", "Defeat - Zook #2"), frozenset({"Defeat - Zook #1"})),
                         tr.NON_PLAYER_FIGHTS["ZOOK"])
        self.assertEqual((("Defeat - Ardos #1", "Defeat - Ardos #2"), frozenset({"Defeat - Ardos #1"})),
                         tr.NON_PLAYER_FIGHTS["ARDOS"])
        self.assertEqual((("Defeat - Biden #1", "Defeat - Biden #2"), frozenset({"Defeat - Biden #2"})),
                         tr.NON_PLAYER_FIGHTS["BIDEN"])

    def test_wired_into_the_defeat_poll(self):
        self.assertIn("non_player_fights=trainer_roster.NON_PLAYER_FIGHTS", CLIENT)


class TestOneCheckEach(unittest.TestCase):
    def test_no_numbered_checks(self):
        for surname in ("Ardos", "Zook", "Biden"):
            for n in (1, 2):
                label = f"Defeat - {surname} #{n}"
                self.assertNotIn(label, L.LOCATION_TABLE, label)
                self.assertIn(label, tr.RULED_OUT_DEFEAT_LOCATIONS, label)
            self.assertEqual([], tr.UNIQUE_SURNAME_TO_LOCATION_QUEUE[surname.upper()])
        self.assertEqual({}, tr.DEFEAT_LINKS)

    def test_each_any_sits_where_its_fight_is(self):
        rows = {row["surname"]: row for row in rt.REPEATABLE_TRAINERS}
        expected = {"ARDOS": (193, "Citadark Isle"), "ZOOK": (147, "Cipher Key Lair (exterior)"),
                    "BIDEN": (143, "Snagem Hideout")}
        for surname, (index, region) in expected.items():
            self.assertEqual(index, rows[surname]["anchor_index"], surname)
            self.assertEqual(region, rows[surname]["region"], surname)
            self.assertEqual(mi.SINGLE_CHECK_FIGHTS[surname], index)
            self.assertNotIn(index, mi.NON_PLAYER_FIGHT_INDICES)

    def test_biden_is_not_missable_and_not_filler(self):
        self.assertIn(143, mi.WORKBOOK_MISSABLE_OVERRULED)
        self.assertNotIn("BIDEN", rt.ALWAYS_FILLER_SURNAMES)
        self.assertNotIn("Defeat Biden (Any)", ma.AUTO_SEND_AT_STORY_BYTE)
        self.assertNotIn("Defeat - Biden #2", ma.AUTO_SEND_AT_STORY_BYTE)


FINGERPRINTS = {
    "Defeat - Zook #1": {"species": ["MEDITITE", "ZUBAT"], "base_party_size": 2},
    "Defeat - Zook #2": {"species": ["DODUO", "SWABLU", "SOLROCK"], "base_party_size": 3},
}
QUEUE: "dict[str, list[str | None]]" = {"ZOOK": []}


def _fight(tracker, species, surname="ZOOK"):
    seen, fired = [], []
    for hp in (50, 6, 0, 0):
        frame = [rc.BattleRosterRecord(0x804A8000 + i * 0xC4, surname, name, hp) for i, name in enumerate(species)]
        fired += tracker.poll(QUEUE, lambda n: f"Defeat {n} Trainers", records=frame, count_location_max=10,
                              team_fingerprints=FINGERPRINTS, non_player_fights=tr.NON_PLAYER_FIGHTS)
        seen += tracker.last_confirmed_surnames
    tracker.poll(QUEUE, lambda n: f"Defeat {n} Trainers", records=[], count_location_max=10,
                 team_fingerprints=FINGERPRINTS, non_player_fights=tr.NON_PLAYER_FIGHTS)
    return seen, fired


class TestTheTrackerIgnoresAWatchedFight(unittest.TestCase):
    def test_gateon_counts_for_nothing_and_the_lair_counts(self):
        tracker = rc.TrainerBattleDefeatTracker()
        seen, fired = _fight(tracker, ("MEDITITE", "ZUBAT"))           # Ardos beats Zook at Gateon
        self.assertEqual(([], []), (seen, fired))
        self.assertEqual(1, tracker.non_player_fights_ignored)
        self.assertEqual("Defeat - Zook #1", tracker.last_ignored_fight)
        self.assertEqual(0, tracker.wins_by_surname.get("ZOOK", 0))
        seen, fired = _fight(tracker, ("DODUO", "SWABLU", "SOLROCK"))   # the player beats Zook at the Key Lair
        self.assertEqual(["ZOOK"], seen)
        self.assertEqual(["Defeat 1 Trainers"], fired)

    def test_without_fingerprints_nothing_is_ignored(self):
        tracker = rc.TrainerBattleDefeatTracker()
        seen = []
        for hp in (50, 6, 0, 0):
            frame = [rc.BattleRosterRecord(0x804A8000, "ZOOK", "MEDITITE", hp)]
            tracker.poll(QUEUE, lambda n: f"Defeat {n} Trainers", records=frame, count_location_max=0,
                         team_fingerprints=None, non_player_fights=tr.NON_PLAYER_FIGHTS)
            seen += tracker.last_confirmed_surnames
        self.assertEqual(["ZOOK"], seen)

    def test_another_trainer_is_untouched(self):
        tracker = rc.TrainerBattleDefeatTracker()
        seen, _fired = _fight(tracker, ("MEDITITE", "ZUBAT"), surname="LAKEN")
        self.assertEqual(["LAKEN"], seen)


class TestThePhenacCipherFightsWaitForSnattle(unittest.TestCase):
    def test_every_missable_cipher_fight_in_phenac(self):
        self.assertEqual(0x48, ma.SNATTLE_DEFEATED)
        self.assertTrue(story_bytes.byte_is_reachable(ma.SNATTLE_DEFEATED))
        snattle = [t for t in story_bytes.TRANSITIONS if t.after == ma.SNATTLE_DEFEATED]
        self.assertTrue(any("Snattle defeated" in t.what for t in snattle))
        self.assertEqual(set(story_bytes.AREA_GROUPS["Phenac City"]), set(ma.PHENAC_AREA_REGIONS))
        released = {name for name, cap in ma.AUTO_SEND_AT_STORY_BYTE.items() if cap == ma.SNATTLE_DEFEATED}
        # ADDENDUM 440/441: the Cipher fights + the four invasion trainers + Justy. The Sixes' six #2 fights are
        # numbered rematch checks, no longer locations, so 6 Cipher fights remain: 11.
        self.assertEqual(11, len(released))
        for index in mi.MISSABLE_TRAINER_INDICES:
            trainer = tr.TRAINERS_BY_INDEX[index]
            label = tr.trainer_label(trainer)
            if label not in ma.AUTO_SEND_AT_STORY_BYTE:
                continue
            in_phenac = trainer_placements.region_for(index) in ma.PHENAC_AREA_REGIONS
            cipher = trainer["trainer_class"] == ma.CIPHER_PEON_CLASS
            invasion = index in mi.PHENAC_INVASION_INDICES   # ADDENDUM 440
            self.assertEqual((in_phenac and cipher) or invasion, label in released, label)

    def test_bost_unchanged(self):
        # ADDENDUM 460: Bost is unmissable -- an ordinary check now, never auto-sent.
        self.assertNotIn("Defeat - Bost", ma.AUTO_SEND_AT_STORY_BYTE)


class TestInAWorld(PokemonXDTestBase):
    options = {"shuffle_trainer_defeats": True, "trainer_defeat_mode": 1}

    def test_the_three_checks(self):
        created = {location.name: location for location in self.multiworld.get_locations(self.player)}
        self.assertEqual("Citadark Isle", created["Defeat Ardos (Any)"].parent_region.name)
        self.assertEqual("Cipher Key Lair (exterior)", created["Defeat Zook (Any)"].parent_region.name)
        self.assertEqual("Snagem Hideout", created["Defeat Biden (Any)"].parent_region.name)
        self.assertNotEqual(LocationProgressType.EXCLUDED, created["Defeat Biden (Any)"].progress_type)
        for label in ("Defeat - Zook #1", "Defeat - Ardos #1", "Defeat - Biden #2"):
            self.assertNotIn(label, created)


if __name__ == "__main__":
    unittest.main()
