"""ADDENDUM 362 (2026-09-26): a defeat check per UNIQUE TEAM, and Laken/Hebon ruled filler-only.

Two player requests in one message: *"Please exclude laken and hebon from progression items. Also, send the
trainer fight checks by how many UNIQUE teams we've defeated them with - for example, miror b 3 would send
after defeating 3 of his unique teams."*

THE BUG THE SECOND ONE FIXES. Every confirmed win consumed the next queue entry. That is fine for a trainer
met once per story beat and wrong for one who can be re-fought on demand: beating Miror B.'s FIRST team three
times at a colosseum checked off #1, #2 and #3 without the later encounters ever happening. ADDENDUM 359 made
those rematches easy to reach, which is what turned a latent flaw into something the player hit.

THE THREE RULINGS THIS RECORDS, all answers to questions put to the player before any of it was built:

  1. Chobin's occurrences 4 and 5 field byte-identical teams -- the only such pair in all 232 roster rows, so
     he has 7 labels and 6 earnable ones. Asked whether to let the shared team count twice or to delete the
     surplus label, the player chose: *"Strict unique, and delete Chobin #7."*
  2. The cumulative "Defeat N Trainers" counter follows the same rule -- a rematch does not advance it either.
  3. An unidentifiable win falls back to *"the team you actually saw"* rather than advancing blindly or
     refusing to advance at all.

WHY THE RETIREMENT IS DERIVED. `trainer_roster._surplus_labels` recomputes the collision from the deck data
every import, so a corrected roster row moves the retirement instead of leaving a stale hand-typed name. The
signature is VANILLA deck data on purpose: it decides which locations EXIST, and location ids are frozen, so a
signature that read this seed's rolled options would give two seeds different location sets.
"""
from __future__ import annotations

import unittest

from .. import locations, ram_client as rc
from ..game_data import missable_trainers, repeatable_trainers, trainer_roster
from . import PokemonXDTestBase

try:
    from BaseClasses import LocationProgressType
except ImportError:  # pragma: no cover - only when run outside an Archipelago checkout
    LocationProgressType = None


# ============================================================================================================
# Ruling 1: Laken and Hebon
# ============================================================================================================
class TestLakenAndHebonAreFillerOnly(unittest.TestCase):
    def test_both_are_ruled_always_filler(self) -> None:
        for surname in ("LAKEN", "HEBON"):
            self.assertIn(surname, repeatable_trainers.ALWAYS_FILLER_SURNAMES, surname)
            self.assertIn(repeatable_trainers.location_name(surname),
                          repeatable_trainers.ALWAYS_FILLER_LOCATIONS)

    def test_the_ruling_was_needed_because_the_derivation_would_not_have_caught_it(self) -> None:
        """Both anchors are census-safe -- not missable, real region -- so this is a RULING and the file says
        so. If a roster correction ever makes an anchor missable, the module's own import fence would demand
        the entry anyway and this test would stop meaning anything; assert the shape so that is visible."""
        rows = {row["surname"]: row for row in repeatable_trainers.REPEATABLE_TRAINERS}
        for surname in ("LAKEN", "HEBON"):
            self.assertFalse(rows[surname]["anchor_is_missable"], surname)
            self.assertIsNotNone(rows[surname]["region"], surname)

    def test_every_numbered_occurrence_was_already_fenced_before_this(self) -> None:
        """The audit that decided the (Any) lever was the only one to touch. Laken #1 and Hebon #1 are in the
        player's missable compilation, and FILLER_ONLY_TRAINER_INDICES fences EVERY occurrence of a missable
        surname -- so all six numbered checks were excluded already and the ruling adds the two that were not."""
        fenced = missable_trainers.filler_only_trainer_indices()
        for surname in ("LAKEN", "HEBON"):
            indices = [i for i, row in trainer_roster.TRAINERS_BY_INDEX.items()
                       if row["name"] == surname]
            self.assertEqual(len(indices), 3, surname)
            for index in indices:
                self.assertIn(index, fenced, f"{surname} occurrence {index}")

    def test_neither_appears_in_the_cumulative_mode_named_roster(self) -> None:
        """The other half of the audit: the 66-name curated queue has no entry for either, so there was no
        third surface to close."""
        from .. import trainer_defeat

        for surname in ("Laken", "Hebon"):
            self.assertIsNone(trainer_defeat.SURNAME_TO_LOCATION_QUEUE.get(surname), surname)


class TestTheRulingReachesTheGeneratedWorld(PokemonXDTestBase):
    options = {"shuffle_trainer_defeats": True, "progression_locations": 2}

    def test_no_laken_or_hebon_check_can_hold_progression_at_the_most_permissive_setting(self) -> None:
        checked = 0
        for location in self.multiworld.get_locations(self.player):
            if "Laken" in location.name or "Hebon" in location.name:
                self.assertEqual(location.progress_type, LocationProgressType.EXCLUDED, location.name)
                checked += 1
        self.assertGreaterEqual(checked, 2, "no Laken/Hebon locations were found to check at all")


# ============================================================================================================
# Ruling 1b: the surplus label
# ============================================================================================================
class TestTheSurplusLabelIsRetired(unittest.TestCase):
    def test_chobin_four_and_five_really_are_identical(self) -> None:
        """The measurement the retirement rests on. If this ever stops holding, the retirement is wrong."""
        four = trainer_roster.TRAINERS_BY_INDEX[125]
        five = trainer_roster.TRAINERS_BY_INDEX[127]
        self.assertEqual(trainer_roster.team_signature(four), trainer_roster.team_signature(five))

    def test_he_is_the_only_one_in_the_whole_roster(self) -> None:
        collided = [
            surname for surname, rows in trainer_roster.TRAINERS_BY_NAME.items()
            if len({trainer_roster.team_signature(r) for r in rows}) != len(rows)
        ]
        self.assertEqual(collided, ["CHOBIN"])

    def test_miror_b_has_nine_distinct_teams_so_the_players_example_works(self) -> None:
        self.assertEqual(trainer_roster.DISTINCT_TEAM_COUNTS["MIROR B."], 9)
        self.assertEqual(len(trainer_roster.UNIQUE_SURNAME_TO_LOCATION_QUEUE["MIROR B."]), 9)

    def test_the_tail_is_what_is_retired_not_the_duplicate(self) -> None:
        """A label now means "the Nth distinct team you beat", so the survivors must be contiguous. Dropping
        #5 would leave a gap and imply the rest still name occurrences."""
        self.assertEqual(trainer_roster.RETIRED_UNIQUE_DEFEAT_LOCATIONS, {"Defeat - Chobin #7"})
        self.assertEqual(
            trainer_roster.UNIQUE_SURNAME_TO_LOCATION_QUEUE["CHOBIN"],
            [f"Defeat - Chobin #{n}" for n in range(1, 7)],
        )

    def test_it_is_gone_from_the_seed_but_its_id_is_not_reused(self) -> None:
        self.assertNotIn("Defeat - Chobin #7", locations.LOCATION_TABLE)
        self.assertIn("Defeat - Chobin #7", locations._FROZEN_LOCATION_OFFSETS)
        tombstone = locations._FROZEN_LOCATION_OFFSETS["Defeat - Chobin #7"]
        live = {data.id_offset for data in locations.LOCATION_TABLE.values()}
        self.assertNotIn(tombstone, live, "a retired id was handed to another location")

    def test_every_surviving_label_has_a_team_that_can_earn_it(self) -> None:
        """The invariant the whole retirement exists to restore, asserted over all 144 surnames rather than
        the one that failed it."""
        for surname, labels in trainer_roster.UNIQUE_SURNAME_TO_LOCATION_QUEUE.items():
            self.assertEqual(len(labels), trainer_roster.DISTINCT_TEAM_COUNTS[surname], surname)

    def test_the_roster_list_still_names_all_232_battles(self) -> None:
        """Retiring a LOCATION must not retire the fact that the trainer exists -- the roster list is what a
        trainer index resolves through and what the ids were frozen against."""
        self.assertEqual(len(locations.UNIQUE_TRAINER_DEFEAT_LOCATION_NAMES), 232)
        self.assertEqual(len(locations.ACTIVE_UNIQUE_TRAINER_DEFEAT_LOCATION_NAMES), 231)


# ============================================================================================================
# Ruling 2 and 3: what a win does
# ============================================================================================================
QUEUE = {"MIROR B.": [f"Defeat - Miror B. #{n}" for n in (1, 2, 3)]}
FINGERPRINTS = {
    "Defeat - Miror B. #1": {"species": ["LUDICOLO", "LOUDRED"], "base_party_size": 2,
                             "hp_bands": {"LUDICOLO": [40, 60]}},
    "Defeat - Miror B. #2": {"species": ["LUDICOLO", "GOLBAT"], "base_party_size": 2,
                             "hp_bands": {"LUDICOLO": [90, 120]}},
    "Defeat - Miror B. #3": {"species": ["ARMALDO", "SUDOWOODO"], "base_party_size": 2,
                             "hp_bands": {"ARMALDO": [150, 200]}},
}


def _win(tracker, species, hp_top=50, queue=QUEUE, fingerprints=FINGERPRINTS, cap=0):
    """One complete fight: alive -> dropping -> confirmed dead -> roster clears and the surname re-arms."""
    fired = []
    for hp in (hp_top, max(1, hp_top // 8), 0, 0):
        frame = [rc.BattleRosterRecord(0x804A8000 + i * 0xC4, "MIROR B.", name, hp)
                 for i, name in enumerate(species)]
        fired += tracker.poll(queue, lambda n: f"Defeat {n} Trainers", records=frame,
                              count_location_max=cap, team_fingerprints=fingerprints)
    tracker.poll(queue, lambda n: f"Defeat {n} Trainers", records=[], count_location_max=cap,
                 team_fingerprints=fingerprints)
    return fired


def _confirmed_surnames(tracker, species, hp_top=50):
    """`last_confirmed_surnames` is reset every poll -- it means "confirmed on THIS poll" -- so it has to be
    collected as the fight runs rather than read after it."""
    seen = []
    for hp in (hp_top, max(1, hp_top // 8), 0, 0):
        frame = [rc.BattleRosterRecord(0x804A8000 + i * 0xC4, "MIROR B.", name, hp)
                 for i, name in enumerate(species)]
        tracker.poll(QUEUE, lambda n: f"Defeat {n} Trainers", records=frame,
                     count_location_max=0, team_fingerprints=FINGERPRINTS)
        seen += tracker.last_confirmed_surnames
    tracker.poll(QUEUE, lambda n: f"Defeat {n} Trainers", records=[], count_location_max=0,
                 team_fingerprints=FINGERPRINTS)
    return seen


class TestUniqueTeamDispatch(unittest.TestCase):
    def test_the_players_own_example(self) -> None:
        """"miror b 3 would send after defeating 3 of his unique teams." Three teams, three checks, in the
        order they were beaten."""
        tracker = rc.TrainerBattleDefeatTracker()
        fired = _win(tracker, ("LUDICOLO", "LOUDRED"), hp_top=50)
        fired += _win(tracker, ("LUDICOLO", "GOLBAT"), hp_top=100)
        fired += _win(tracker, ("ARMALDO", "SUDOWOODO"), hp_top=170)
        self.assertEqual(fired, ["Defeat - Miror B. #1", "Defeat - Miror B. #2", "Defeat - Miror B. #3"])

    def test_grinding_one_rematch_yields_exactly_one_check(self) -> None:
        """The regression. Before this, the same colosseum fight five times checked off #1, #2 and #3 and then
        ran out of queue."""
        tracker = rc.TrainerBattleDefeatTracker()
        fired = []
        for _ in range(5):
            fired += _win(tracker, ("LUDICOLO", "LOUDRED"), hp_top=50)
        self.assertEqual(fired, ["Defeat - Miror B. #1"])
        self.assertEqual(tracker.rematches_ignored, 4)

    def test_beating_them_out_of_order_still_fills_the_queue_from_the_front(self) -> None:
        """A label is a count, not an occurrence, so the third team beaten takes #3 even if it was fought
        first -- and nothing is ever skipped or left unreachable."""
        tracker = rc.TrainerBattleDefeatTracker()
        fired = _win(tracker, ("ARMALDO", "SUDOWOODO"), hp_top=170)
        fired += _win(tracker, ("LUDICOLO", "LOUDRED"), hp_top=50)
        self.assertEqual(fired, ["Defeat - Miror B. #1", "Defeat - Miror B. #2"])

    def test_a_win_past_the_end_of_the_queue_still_counts_but_dispatches_nothing(self) -> None:
        tracker = rc.TrainerBattleDefeatTracker()
        for species, hp in ((("LUDICOLO", "LOUDRED"), 50), (("LUDICOLO", "GOLBAT"), 100),
                            (("ARMALDO", "SUDOWOODO"), 170)):
            _win(tracker, species, hp_top=hp)
        self.assertEqual(_win(tracker, ("MAGIKARP",), hp_top=15), [])
        self.assertEqual(tracker.defeat_count, 4)


class TestRulingTwoTheCumulativeCounter(unittest.TestCase):
    def test_a_rematch_does_not_advance_the_running_total(self) -> None:
        """The player's choice: "Count unique teams only." A rematch must not farm the bucket either."""
        tracker = rc.TrainerBattleDefeatTracker()
        for _ in range(4):
            _win(tracker, ("LUDICOLO", "LOUDRED"), hp_top=50)
        self.assertEqual(tracker.defeat_count, 1)

    def test_and_the_bucket_names_follow_it(self) -> None:
        tracker = rc.TrainerBattleDefeatTracker()
        fired = _win(tracker, ("LUDICOLO", "LOUDRED"), hp_top=50, cap=None)
        fired += _win(tracker, ("LUDICOLO", "LOUDRED"), hp_top=50, cap=None)
        self.assertEqual([n for n in fired if n.endswith(" Trainers")], ["Defeat 1 Trainers"])

    def test_a_rematch_is_still_a_confirmed_defeat_for_everything_else(self) -> None:
        """`last_confirmed_surnames` feeds ADDENDUM 252's "(Any)" checks and ADDENDUM 94's goal detection,
        both of which ask "was this trainer beaten" -- a question a rematch answers. Only counting is gated."""
        tracker = rc.TrainerBattleDefeatTracker()
        seen = _confirmed_surnames(tracker, ("LUDICOLO", "LOUDRED"))
        seen += _confirmed_surnames(tracker, ("LUDICOLO", "LOUDRED"))
        self.assertEqual(seen.count("MIROR B."), 2)
        self.assertEqual(tracker.defeat_count, 1, "the second win was a rematch and must not have counted")


class TestRulingThreeTheFallback(unittest.TestCase):
    def test_an_unidentifiable_team_still_advances_the_first_time(self) -> None:
        """"Fall back to the team you actually saw." Never stalls a check."""
        tracker = rc.TrainerBattleDefeatTracker()
        self.assertEqual(_win(tracker, ("MAGIKARP", "WOBBUFFET"), hp_top=30),
                         ["Defeat - Miror B. #1"])
        self.assertEqual(tracker.fingerprint_matches, 0)

    def test_and_is_recognised_as_a_rematch_the_second_time(self) -> None:
        tracker = rc.TrainerBattleDefeatTracker()
        _win(tracker, ("MAGIKARP", "WOBBUFFET"), hp_top=30)
        self.assertEqual(_win(tracker, ("MAGIKARP", "WOBBUFFET"), hp_top=30), [])

    def test_a_seed_with_no_fingerprints_at_all_still_gets_rematch_protection(self) -> None:
        """Seeds generated before ADDENDUM 155 ship no fingerprints. They lose identification, not the rule."""
        tracker = rc.TrainerBattleDefeatTracker()
        self.assertEqual(_win(tracker, ("LUDICOLO", "LOUDRED"), fingerprints=None),
                         ["Defeat - Miror B. #1"])
        self.assertEqual(_win(tracker, ("LUDICOLO", "LOUDRED"), fingerprints=None), [])

    def test_hp_drift_within_a_band_is_not_a_new_team(self) -> None:
        """The fallback signature buckets MaxHP, because the deck's IVs/EVs were never extracted and two
        sightings of one team can differ by a few points. Without the band this hands out a spare check."""
        tracker = rc.TrainerBattleDefeatTracker()
        _win(tracker, ("MAGIKARP",), hp_top=30, fingerprints=None)
        self.assertEqual(_win(tracker, ("MAGIKARP",), hp_top=31, fingerprints=None), [])


# ============================================================================================================
# The dict that was being carried between fights
# ============================================================================================================
class TestMaxHpIsPurgedWhenTheRosterClears(unittest.TestCase):
    def test_a_later_fight_does_not_inherit_an_earlier_ones_max_hp(self) -> None:
        """A pre-existing bug this rule surfaced. `_max_hp_seen` keeps the highest HP ever seen for a slot,
        which is only MaxHP within ONE fight -- carried across, a level-50 rematch poisons the reading of the
        level-30 team fought next, which is exactly the shape of a Miror B. colosseum rematch."""
        tracker = rc.TrainerBattleDefeatTracker()
        _win(tracker, ("LUDICOLO", "GOLBAT"), hp_top=100)
        self.assertEqual(tracker._max_hp_seen, {})
        _win(tracker, ("LUDICOLO", "LOUDRED"), hp_top=50)
        self.assertEqual(tracker._beaten_team_ids["MIROR B."],
                         ["occ:Defeat - Miror B. #2", "occ:Defeat - Miror B. #1"])


# ============================================================================================================
# Persistence
# ============================================================================================================
class TestTheLedgerSurvivesARestart(unittest.TestCase):
    def test_a_round_trip_keeps_the_rule_working(self) -> None:
        """Without this a client restart sees every rematch as a first win and hands out the checks the rule
        exists to withhold -- the game keeps no record of which of a trainer's teams you have beaten."""
        first = rc.TrainerBattleDefeatTracker()
        _win(first, ("LUDICOLO", "LOUDRED"), hp_top=50)
        second = rc.TrainerBattleDefeatTracker()
        second.load_json(first.to_json())
        self.assertEqual(_win(second, ("LUDICOLO", "LOUDRED"), hp_top=50), [])
        self.assertEqual(_win(second, ("LUDICOLO", "GOLBAT"), hp_top=100), ["Defeat - Miror B. #2"])

    def test_it_is_json_safe(self) -> None:
        import json

        tracker = rc.TrainerBattleDefeatTracker()
        _win(tracker, ("LUDICOLO", "LOUDRED"), hp_top=50)
        self.assertEqual(json.loads(json.dumps(tracker.to_json())), tracker.to_json())

    def test_junk_degrades_to_nothing_beaten_rather_than_raising(self) -> None:
        for junk in (None, {}, [], "beaten", {"beaten_teams": None}, {"beaten_teams": {"X": [1, 2]}},
                     {"beaten_teams": {7: ["a"]}}):
            tracker = rc.TrainerBattleDefeatTracker()
            tracker.load_json(junk)
            self.assertEqual(tracker.beaten_team_counts(), {})

    def test_the_client_persists_and_reloads_it(self) -> None:
        """Structural: Client.py is not importable under test (websockets is not a package here), so the
        wiring is asserted on the source, next to the purification tracker it sits beside."""
        import pathlib

        source = (pathlib.Path(__file__).resolve().parents[1] / "Client.py").read_text()
        self.assertIn('"trainer_teams": self.trainer_defeat_tracker.to_json()', source)
        self.assertIn('self.trainer_defeat_tracker.load_json(slot_state["trainer_teams"])', source)


# ============================================================================================================
# The wrapper that was deleted
# ============================================================================================================
class TestTheDeadDispatchWrapperIsGone(unittest.TestCase):
    def test_choose_queue_entry_is_not_a_method_any_more(self) -> None:
        """It only ever wrapped `_fingerprint_score` to pick an unclaimed index, and dispatch is now pure
        counting -- a method that merely agrees with the code that replaced it is the dead-rule shape this
        project refuses (ADDENDA 247/298). The scoring it wrapped is untouched."""
        self.assertFalse(hasattr(rc.TrainerBattleDefeatTracker, "_choose_queue_entry"))
        self.assertTrue(hasattr(rc.TrainerBattleDefeatTracker, "_fingerprint_score"))
        self.assertTrue(hasattr(rc.TrainerBattleDefeatTracker, "_resolve_occurrence"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
