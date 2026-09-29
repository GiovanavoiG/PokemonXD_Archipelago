"""Identifying a repeated trainer by WHO WAS ON THE FIELD (ADDENDUM 155-158, 2026-09-12).

CONSOLIDATED 2026-09-12 from four files written over a single day, each of which superseded part of the last:

  * 155 -- identify by team instead of by "how many of that name have I beaten".
  * 156 -- score on several axes, not species alone; add levels for both difficulties.
  * 157 -- max HP as the axis that actually fires, since the client can already observe it. Levels stayed
           dormant: no level field has been located in the decoded battle-roster record.
  * 158 -- the Gen III species names were wrong for one day. `xd_species_index` carries two conversions for
           two index spaces; the deck needs `national_dex_for`, and the builder was calling
           `national_dex_for_live_species`. Below 252 they agree, which is why it hid.

75 tests became 36. Dropped: 157's assertions that the base-HP table STOPPED at Dex 251 (158 removed that
fence, so they asserted a misdiagnosis); 156's "the level axis is dormant" scaffolding, now one test rather
than a set; and per-axis duplicates where 156 and 157 tested the same scoring path with different data.
The save-block gate half of the old 154/155 file moved to test_addendum_148_block_stability_gate.py, where the
rest of that gate's tests already live.
"""
from __future__ import annotations

import json
import math
import pathlib
import unittest

from . import PokemonXDTestBase
from .. import ram_client as rc, species
from ..game_data import species_base_hp as sbh
from ..randomizer.enhanced_difficulty import ENHANCED_DIFFICULTY_LEVEL_MULTIPLIER
from ..tools.xd_species_index import national_dex_for, national_dex_for_live_species

T = rc.TrainerBattleDefeatTracker
_DATA = pathlib.Path(__file__).resolve().parent.parent / "data"
_NAME_TO_DEX = {name.upper(): dex for dex, name in species.NATIONAL_DEX.items()}


def _entry(species_names, levels=(), enhanced=(), bands=None, enhanced_bands=None, base=None):
    return {
        "species": list(species_names),
        "levels": list(levels),
        "levels_enhanced": list(enhanced),
        "hp_bands": bands or {},
        "hp_bands_enhanced": enhanced_bands or {},
        "base_party_size": len(species_names) if base is None else base,
        "shadow_slots": 0,
    }


# ============================================================================================================
# Which conversion deck data needs (ADDENDUM 158)
# ============================================================================================================
class TestSpeciesIndexSpaces(unittest.TestCase):
    def _real_shadow_dex(self):
        entries = json.loads((_DATA / "shadow_pokemon_list.json").read_text())
        return {_NAME_TO_DEX[e["species_name"].upper()] for e in entries
                if e["species_name"].upper() in _NAME_TO_DEX}

    def _deck_shadow_species(self):
        return {e["species"] for e in json.loads((_DATA / "deckdata_dark_pokemon.json").read_text())}

    def test_the_master_conversion_explains_every_shadow_pokemon_and_the_live_one_does_not(self) -> None:
        """The check that settled it: 83 deck species ids against the 83 real Shadow Pokemon names.
        Both halves are asserted so nobody 'simplifies' the two conversions back into one."""
        real, deck = self._real_shadow_dex(), self._deck_shadow_species()
        self.assertEqual(len(real), 83)
        master = {national_dex_for(i) for i in deck} - {None, 0}
        live = {national_dex_for_live_species(i) for i in deck} - {None, 0}
        self.assertEqual(len(master & real), len(deck), "the master conversion must be exact")
        self.assertLess(len(live & real), len(deck), "the live conversion must NOT be interchangeable")

    def test_they_agree_below_252_which_is_why_the_bug_hid(self) -> None:
        for internal in range(1, 252):
            self.assertEqual(national_dex_for(internal),
                             national_dex_for_live_species(internal), internal)

    def test_and_diverge_above_it(self) -> None:
        disagreements = sum(1 for i in range(252, 415)
                            if national_dex_for(i) != national_dex_for_live_species(i))
        self.assertGreater(disagreements, 100)

    def test_the_specific_names_that_were_wrong(self) -> None:
        """Each was cited in ADDENDUM 157 as evidence of a broken mapping. Base HP from the game's own stats
        table settles all three -- the mapping was fine, the call was wrong."""
        for internal, name, hp in ((289, "LINOONE", 78), (297, "LUDICOLO", 80), (311, "SURSKIT", 40)):
            dex = national_dex_for(internal)
            self.assertEqual(species.NATIONAL_DEX[dex].upper(), name, internal)
            self.assertEqual(sbh.base_hp(dex), hp, internal)


# ============================================================================================================
# Expected max HP (ADDENDUM 157/158)
# ============================================================================================================
class TestMaxHpExpectations(unittest.TestCase):
    def test_the_base_hp_offset_was_found_by_agreement_not_by_guessing(self) -> None:
        """Nine distinctive species had to match simultaneously -- any one alone had many false offsets in a
        0x124-byte entry."""
        for dex, expected in ((1, 45), (4, 39), (7, 44), (25, 35), (113, 250),
                              (143, 160), (242, 255), (213, 20), (202, 190)):
            self.assertEqual(sbh.base_hp(dex), expected, dex)

    def test_it_covers_every_species_including_the_ones_that_were_misnamed(self) -> None:
        for dex in range(1, 387):
            self.assertIsNotNone(sbh.base_hp(dex), dex)
        for dex, expected in ((292, 1), (321, 170), (384, 105), (386, 50), (252, 40)):
            self.assertEqual(sbh.base_hp(dex), expected, dex)

    def test_the_data_file_documents_its_own_source_and_scope(self) -> None:
        payload = json.loads((_DATA / "species_base_hp.json").read_text())
        for key in ("_source", "_verified", "_scope"):
            self.assertIn(key, payload)
        self.assertEqual(len(payload["base_hp"]), 386)

    def test_the_band_is_the_gen_iii_formula_across_the_whole_iv_ev_spread(self) -> None:
        low, high = sbh.max_hp_band(113, 50)
        self.assertEqual(low, sbh.max_hp(250, 50, 0, 0))
        self.assertEqual(high, sbh.max_hp(250, 50, 31, 255))
        self.assertEqual(high, (2 * 250 + 31 + 63) * 50 // 100 + 50 + 10)

    def test_a_higher_level_always_gives_a_disjoint_higher_band(self) -> None:
        """This is what makes max HP discriminate between a trainer's encounters at all -- and why a wide
        IV/EV band is not a problem: level moves it further than IVs and EVs ever could."""
        for dex in (1, 25, 161, 321):
            self.assertLess(sbh.max_hp_band(dex, 8)[1], sbh.max_hp_band(dex, 40)[0])

    def test_an_unknown_species_or_impossible_level_is_no_data_not_an_error(self) -> None:
        self.assertIsNone(sbh.base_hp(9999))
        self.assertIsNone(sbh.max_hp_band(9999, 50))
        for level in (0, -1, 101):
            self.assertIsNone(sbh.max_hp_band(1, level))


# ============================================================================================================
# Scoring (ADDENDUM 156/157)
# ============================================================================================================
class TestScoring(unittest.TestCase):
    def test_species_overlap_scores_and_more_overlap_scores_more(self) -> None:
        entry = _entry(["GLIGAR", "LAPRAS"])
        self.assertGreater(T._fingerprint_score(entry, {"GLIGAR"}, None), 0)
        self.assertGreater(T._fingerprint_score(entry, {"GLIGAR", "LAPRAS"}, None),
                           T._fingerprint_score(entry, {"GLIGAR"}, None))

    def test_max_hp_separates_two_encounters_that_share_every_species(self) -> None:
        """The failure the player anticipated when asking for a second axis: species alone can tie."""
        early = _entry(["ZUBAT"], bands={"ZUBAT": [20, 26]})
        late = _entry(["ZUBAT"], bands={"ZUBAT": [90, 120]})
        self.assertGreater(T._fingerprint_score(late, {"ZUBAT"}, None, {"ZUBAT": 101}),
                           T._fingerprint_score(early, {"ZUBAT"}, None, {"ZUBAT": 101}))

    def test_either_difficulty_counts_equally(self) -> None:
        """Both bands ship so a match never depends on which difficulty the seed rolled."""
        entry = _entry(["ZUBAT"], bands={"ZUBAT": [20, 26]}, enhanced_bands={"ZUBAT": [26, 34]})
        self.assertEqual(T._fingerprint_score(entry, {"ZUBAT"}, None, {"ZUBAT": 22}),
                         T._fingerprint_score(entry, {"ZUBAT"}, None, {"ZUBAT": 30}))

    def test_hp_in_neither_band_adds_nothing_and_band_edges_are_inclusive(self) -> None:
        entry = _entry(["ZUBAT"], bands={"ZUBAT": [20, 26]}, enhanced_bands={"ZUBAT": [26, 34]})
        baseline = T._fingerprint_score(entry, {"ZUBAT"}, None, None)
        self.assertEqual(T._fingerprint_score(entry, {"ZUBAT"}, None, {"ZUBAT": 400}), baseline)
        for hp in (20, 26):
            self.assertGreater(T._fingerprint_score(entry, {"ZUBAT"}, None, {"ZUBAT": hp}), baseline)

    def test_a_species_with_no_band_contributes_nothing(self) -> None:
        """Shadow slots and Enhanced Difficulty padding members both land here."""
        entry = _entry(["ZUBAT", "KYOGRE"], bands={"ZUBAT": [20, 26]})
        self.assertEqual(T._fingerprint_score(entry, {"ZUBAT", "KYOGRE"}, None, {"KYOGRE": 200}),
                         T._fingerprint_score(entry, {"ZUBAT", "KYOGRE"}, None, None))

    def test_an_unread_hp_of_zero_is_ignored(self) -> None:
        entry = _entry(["ZUBAT"], bands={"ZUBAT": [0, 26]})
        self.assertEqual(T._fingerprint_score(entry, {"ZUBAT"}, None, {"ZUBAT": 0}),
                         T._fingerprint_score(entry, {"ZUBAT"}, None, None))

    def test_levels_are_a_real_axis_even_though_nothing_observes_them_yet(self) -> None:
        """No level field has been located in the battle-roster record, so `observed_levels` is always None
        today. The axis is kept wired and tested so finding that offset is a one-line change."""
        a = _entry(["ZUBAT"], levels=[8], enhanced=[10])
        b = _entry(["ZUBAT"], levels=[40], enhanced=[53])
        self.assertGreater(T._fingerprint_score(b, {"ZUBAT"}, {40}),
                           T._fingerprint_score(a, {"ZUBAT"}, {40}))
        self.assertEqual(T._fingerprint_score(b, {"ZUBAT"}, {40}),
                         T._fingerprint_score(b, {"ZUBAT"}, {53}))

    def test_more_distinct_species_than_were_on_the_field_is_contradicted(self) -> None:
        """Enhanced Difficulty and Shadow Expansion only ever ADD members, so a candidate needing species that
        never appeared is ruled OUT -- worth scoring even with no other evidence."""
        self.assertLess(T._fingerprint_score(_entry(["ZUBAT", "GLALIE", "SEEL", "TAUROS"]), {"ZUBAT"}, None),
                        T._fingerprint_score(_entry(["ZUBAT"]), {"ZUBAT"}, None))

    def test_a_matching_team_size_alone_is_not_evidence(self) -> None:
        """A tiebreak must never invent a positive score from nothing."""
        self.assertLessEqual(T._fingerprint_score(_entry(["GLIGAR"]), {"MAGIKARP"}, None), 0)

    def test_a_smaller_team_than_the_field_is_still_consistent(self) -> None:
        self.assertGreater(T._fingerprint_score(_entry(["ZUBAT"], base=1),
                                                {"ZUBAT", "GLALIE", "SEEL"}, None), 0)

    def test_the_addendum_155_bare_list_shape_still_scores(self) -> None:
        """Seeds generated between 155 and 156 must not silently stop matching."""
        self.assertGreater(T._fingerprint_score(["GLIGAR", "LAPRAS"], {"GLIGAR"}, None), 0)

    def test_junk_never_raises(self) -> None:
        for junk in (None, 0, "GLIGAR", {"species": None}):
            self.assertIsInstance(T._fingerprint_score(junk, {"GLIGAR"}, None), int)


# ============================================================================================================
# Dispatch (ADDENDUM 155-157)
# ============================================================================================================
QUEUE3 = {"DOSK": ["Defeat - Dosk #1", "Defeat - Dosk #2", "Defeat - Dosk #3"]}
FP3 = {
    "Defeat - Dosk #1": _entry(["GLIGAR", "LAPRAS", "METAPOD"]),
    "Defeat - Dosk #2": _entry(["GLALIE", "GROUDON", "TOTODILE"]),
    "Defeat - Dosk #3": _entry(["PIDGEY", "SEEL"]),
}


def _fight(tracker, species_names, fingerprints=FP3, queue=QUEUE3, hps=(20, 4, 0, 0)):
    fired = []
    for hp in hps:
        frame = [rc.BattleRosterRecord(0x804A8000 + i * 0xC4, "DOSK", name, hp)
                 for i, name in enumerate(species_names)]
        fired += tracker.poll(queue, lambda n: f"Defeat {n} Trainers", records=frame,
                              count_location_max=0, team_fingerprints=fingerprints)
    tracker.poll(queue, lambda n: f"Defeat {n} Trainers", records=[], count_location_max=0,
                 team_fingerprints=fingerprints)  # roster clears, surname re-arms
    return fired


class TestDispatch(unittest.TestCase):
    def test_fighting_the_second_dosk_first_is_identified_as_the_second_dosk(self) -> None:
        """RETARGETED 2026-09-26 (ADDENDUM 362). Identification and dispatch used to be the same decision and
        are now two. The fingerprinter still recognises this as occurrence 2 -- `_resolve_occurrence` says so
        and `fingerprint_matches` counts it -- but the LABEL that fires is #1, because a label now means "the
        Nth distinct team you beat", and this is the first."""
        tracker = rc.TrainerBattleDefeatTracker()
        self.assertEqual(_fight(tracker, ("GLALIE", "GROUDON", "TOTODILE")), ["Defeat - Dosk #1"])
        self.assertEqual(tracker.fingerprint_matches, 1)
        self.assertEqual(
            tracker._resolve_occurrence(QUEUE3["DOSK"], {"GLALIE", "GROUDON", "TOTODILE"}, FP3),
            "Defeat - Dosk #2",
        )

    def test_the_same_team_twice_checks_off_one_location(self) -> None:
        """ADDENDUM 362, the player's own case: "miror b 3 would send after defeating 3 of his unique teams."
        Before this, three wins against one colosseum rematch consumed #1, #2 and #3."""
        tracker = rc.TrainerBattleDefeatTracker()
        self.assertEqual(_fight(tracker, ("PIDGEY", "SEEL")), ["Defeat - Dosk #1"])
        self.assertEqual(_fight(tracker, ("PIDGEY", "SEEL")), [])
        self.assertEqual(_fight(tracker, ("PIDGEY", "SEEL")), [])
        self.assertEqual(tracker.rematches_ignored, 2)
        self.assertEqual(tracker.defeat_count, 1)

    def test_the_rest_resolve_afterwards_and_nothing_is_dispatched_twice(self) -> None:
        tracker = rc.TrainerBattleDefeatTracker()
        fired = _fight(tracker, ("PIDGEY", "SEEL"))
        fired += _fight(tracker, ("GLIGAR", "LAPRAS", "METAPOD"))
        fired += _fight(tracker, ("GLALIE", "GROUDON", "TOTODILE"))
        # ADDENDUM 362: three distinct teams, so all three labels fire -- in the order they were BEATEN, not
        # the order the census lists them, because that is what a count-based label means now.
        self.assertEqual(fired, ["Defeat - Dosk #1", "Defeat - Dosk #2", "Defeat - Dosk #3"])
        self.assertEqual(len(fired), len(set(fired)))

    def test_running_out_of_locations_dispatches_nothing_rather_than_repeating(self) -> None:
        tracker = rc.TrainerBattleDefeatTracker()
        for team in (("PIDGEY",), ("GLALIE",), ("GLIGAR",)):
            _fight(tracker, team)
        self.assertEqual(_fight(tracker, ("GLIGAR",)), [])

    def test_a_partial_match_still_identifies(self) -> None:
        """The roster shows what is on the FIELD, which can be a subset of a six-slot team."""
        tracker = rc.TrainerBattleDefeatTracker()
        self.assertEqual(_fight(tracker, ("GROUDON",)), ["Defeat - Dosk #1"])
        self.assertEqual(tracker._resolve_occurrence(QUEUE3["DOSK"], {"GROUDON"}, FP3),
                         "Defeat - Dosk #2")
        # ADDENDUM 362: and identifying it is what makes the bench appearing next time NOT a second team.
        self.assertEqual(_fight(tracker, ("GLALIE", "GROUDON", "TOTODILE")), [])

    def test_extra_pokemon_on_the_field_do_not_break_the_match(self) -> None:
        """Enhanced Difficulty's padded members are chosen too late to be fingerprinted, so they appear
        unexpected. Overlap scoring absorbs them."""
        tracker = rc.TrainerBattleDefeatTracker()
        self.assertEqual(_fight(tracker, ("GLALIE", "GROUDON", "RATTATA", "TAUROS")),
                         ["Defeat - Dosk #1"])
        self.assertEqual(
            tracker._resolve_occurrence(QUEUE3["DOSK"], {"GLALIE", "GROUDON", "RATTATA", "TAUROS"}, FP3),
            "Defeat - Dosk #2",
        )

    def test_an_unrecognised_or_ambiguous_team_falls_back_to_what_was_on_the_field(self) -> None:
        """RETARGETED 2026-09-26 (ADDENDUM 362). The fallback used to be story order; it is now the observed
        team itself, the player's own choice when asked. Two candidates matching equally well is still no
        evidence, so nothing is identified -- but the win is still recognisable as a rematch next time."""
        tracker = rc.TrainerBattleDefeatTracker()
        self.assertEqual(_fight(tracker, ("MAGIKARP", "ZUBAT")), ["Defeat - Dosk #1"])
        self.assertEqual(tracker.fingerprint_matches, 0)
        self.assertEqual(_fight(tracker, ("MAGIKARP", "ZUBAT")), [])
        self.assertEqual(tracker.rematches_ignored, 1)

        same = {"Defeat - Dosk #1": _entry(["ZUBAT"]),
                "Defeat - Dosk #2": _entry(["ZUBAT"]),
                "Defeat - Dosk #3": _entry(["SEEL"])}
        tracker2 = rc.TrainerBattleDefeatTracker()
        self.assertEqual(_fight(tracker2, ("ZUBAT",), fingerprints=same), ["Defeat - Dosk #1"])
        self.assertEqual(tracker2.fingerprint_matches, 0)

    def test_a_seed_with_no_fingerprints_behaves_exactly_as_before(self) -> None:
        tracker = rc.TrainerBattleDefeatTracker()
        self.assertEqual(_fight(tracker, ("GLALIE",), fingerprints=None), ["Defeat - Dosk #1"])
        self.assertEqual(_fight(tracker, ("PIDGEY",), fingerprints=None), ["Defeat - Dosk #2"])

    def test_team_size_breaks_a_tie_species_cannot(self) -> None:
        queue = {"DOSK": ["Defeat - Dosk #1", "Defeat - Dosk #2"]}
        fingerprints = {"Defeat - Dosk #1": _entry(["ZUBAT", "GLALIE", "SEEL"]),
                        "Defeat - Dosk #2": _entry(["ZUBAT"])}
        tracker = rc.TrainerBattleDefeatTracker()
        # ADDENDUM 362: asserted on the identification, which is what the tiebreak decides. The label that
        # fires is #1 either way, so it can no longer tell the two candidates apart.
        self.assertEqual(
            tracker._resolve_occurrence(queue["DOSK"], {"ZUBAT"}, fingerprints), "Defeat - Dosk #2"
        )
        self.assertEqual(_fight(tracker, ("ZUBAT",), fingerprints=fingerprints, queue=queue),
                         ["Defeat - Dosk #1"])

    def test_max_hp_is_observed_from_the_fight_itself(self) -> None:
        """A Pokemon starts at full HP and a stale roster copy stays pinned at MaxHP, so the running maximum
        IS MaxHP -- correct on the poll the kill is confirmed, which is the only poll it is used on."""
        queue = {"DOSK": ["Defeat - Dosk #1", "Defeat - Dosk #2"]}
        fingerprints = {"Defeat - Dosk #1": _entry(["ZUBAT"], bands={"ZUBAT": [18, 24]}),
                        "Defeat - Dosk #2": _entry(["ZUBAT"], bands={"ZUBAT": [95, 130]})}
        # ADDENDUM 362: asserted on identification for the same reason as the tiebreak test above -- both
        # fights are the first distinct team their tracker has seen, so both dispatch #1, and the HP axis is
        # only visible in WHICH occurrence each is recognised as.
        tracker = rc.TrainerBattleDefeatTracker()
        self.assertEqual(
            _fight(tracker, ("ZUBAT",), fingerprints=fingerprints, queue=queue,
                   hps=(110, 80, 55, 30, 12, 0, 0)),
            ["Defeat - Dosk #1"],
        )
        self.assertEqual(tracker._beaten_team_ids["DOSK"], ["occ:Defeat - Dosk #2"])
        tracker2 = rc.TrainerBattleDefeatTracker()
        self.assertEqual(
            _fight(tracker2, ("ZUBAT",), fingerprints=fingerprints, queue=queue, hps=(21, 6, 0, 0)),
            ["Defeat - Dosk #1"],
        )
        self.assertEqual(tracker2._beaten_team_ids["DOSK"], ["occ:Defeat - Dosk #1"])

    def test_the_cumulative_counter_is_untouched_by_any_of_this(self) -> None:
        tracker = rc.TrainerBattleDefeatTracker()
        _fight(tracker, ("GROUDON",))
        self.assertEqual(tracker.defeat_count, 1)


# ============================================================================================================
# What the seed actually ships
# ============================================================================================================
class TestSeedSide(PokemonXDTestBase):
    options = {"shuffle_trainer_defeats": True, "trainer_defeat_mode": 1}

    @property
    def fingerprints(self):
        return self.multiworld.worlds[self.player]._trainer_team_fingerprints

    def test_entries_exist_for_ambiguous_surnames_only(self) -> None:
        """A trainer nothing else is named like needs no discriminator, and every entry costs slot_data bytes
        on every connection."""
        from ..game_data import trainer_roster

        self.assertTrue(self.fingerprints)
        for name in self.fingerprints:
            trainer = next(t for t in trainer_roster.TRAINERS
                           if trainer_roster.trainer_label(t) == name)
            self.assertGreater(trainer["total_with_name"], 1, name)

    def test_every_entry_is_a_real_location_carrying_every_axis(self) -> None:
        from .. import locations

        for name, entry in self.fingerprints.items():
            # ADDENDUM 362: a fingerprint for a RETIRED label is still wanted -- it is what lets the client
            # recognise a rematch against that occurrence's team -- so only the active names must be locations.
            if name in locations.ACTIVE_UNIQUE_TRAINER_DEFEAT_LOCATION_NAMES:
                self.assertIn(name, locations.LOCATION_TABLE, name)
            for key in ("species", "levels", "levels_enhanced",
                        "hp_bands", "hp_bands_enhanced", "base_party_size", "shadow_slots"):
                self.assertIn(key, entry, f"{name} is missing {key}")

    def test_every_species_name_is_real_and_every_slot_gets_a_band(self) -> None:
        """Under ADDENDUM 157's fence, Gen III slots got no band. The fence is gone because the reason for it
        was a misdiagnosis (ADDENDUM 158)."""
        valid = {name.upper() for name in species.NATIONAL_DEX.values()}
        for name, entry in self.fingerprints.items():
            for species_name in entry["species"]:
                self.assertIn(species_name, valid, f"{name}: {species_name}")
            self.assertEqual(len(entry["hp_bands"]), len(entry["species"]), name)

    def test_gen_iii_species_really_do_appear(self) -> None:
        """Otherwise the check above could pass vacuously."""
        gen3 = {species.NATIONAL_DEX[d].upper() for d in range(252, 387)}
        seen = {n for e in self.fingerprints.values() for n in e["species"]}
        self.assertTrue(seen & gen3)

    def test_repeated_encounters_with_one_name_get_different_teams(self) -> None:
        """If two encounters fingerprinted identically the client would fall back to counting -- the thing
        this exists to stop."""
        dosk = {k: (tuple(v["species"]), tuple(v["levels"]))
                for k, v in self.fingerprints.items() if k.startswith("Defeat - Dosk")}
        self.assertGreater(len(dosk), 1)
        self.assertEqual(len(set(dosk.values())), len(dosk))

    def test_the_enhanced_levels_are_the_real_transform(self) -> None:
        """Recomputed at fingerprint time rather than read from the Enhanced Difficulty plan, because that
        plan is built in generate_output which races fill_slot_data. This test keeps the two in agreement."""
        for name, entry in self.fingerprints.items():
            expected = sorted(max(1, min(100, math.floor(level * ENHANCED_DIFFICULTY_LEVEL_MULTIPLIER)))
                              for level in entry["levels"])
            self.assertEqual(entry["levels_enhanced"], expected, name)
            for vanilla, enhanced in zip(entry["levels"], entry["levels_enhanced"]):
                self.assertGreaterEqual(enhanced, vanilla, name)

    def test_every_band_is_sane_and_never_below_its_vanilla_counterpart(self) -> None:
        for name, entry in self.fingerprints.items():
            for species_name, band in entry["hp_bands"].items():
                self.assertIn(species_name, entry["species"], name)
                self.assertEqual(len(band), 2, f"{name}/{species_name}")
                self.assertLess(0, band[0], f"{name}/{species_name}")
                self.assertLessEqual(band[0], band[1], f"{name}/{species_name}")
                enhanced = entry["hp_bands_enhanced"].get(species_name)
                if enhanced:
                    self.assertGreaterEqual(enhanced[0], band[0], f"{name}/{species_name}")

    def test_base_party_size_is_the_slot_count_not_the_distinct_species_count(self) -> None:
        """The scorer compares DISTINCT species because the live roster is a set; base_party_size is the real
        slot count and is display-only. It must never be smaller than the species list."""
        for name, entry in self.fingerprints.items():
            self.assertEqual(len(entry["species"]), len(set(entry["species"])), name)
            self.assertLessEqual(len(entry["species"]), entry["base_party_size"], name)

    def test_it_all_reaches_slot_data_from_a_single_shuffle(self) -> None:
        """The shuffle moved to generate_early precisely because fill_slot_data and generate_output are
        submitted to the same thread pool and race. Re-shuffling in generate_output would produce teams that
        disagree with the fingerprints already sent to the client."""
        world = self.multiworld.worlds[self.player]
        self.assertIsNotNone(world._trainer_species_by_dpkm_index)
        shipped = world.fill_slot_data()["trainer_team_fingerprints"]
        self.assertIs(shipped, world._trainer_team_fingerprints)
        self.assertTrue(any(e.get("hp_bands") for e in shipped.values()))


class TestOptionText(unittest.TestCase):
    def test_enhanced_difficulty_says_what_it_actually_does(self) -> None:
        """It said "a flat +3 level boost" and has applied floor(level * 1.33) since ADDENDUM 100.

        MOVED 2026-09-14 (ADDENDUM 197): the 1.33x is its own option now, so the claim has to be checked
        where it is made. EnhancedDifficulty must NOT still describe level scaling -- it only adds Pokemon --
        which is asserted here too, since a stale sentence there is exactly the drift this test exists for.
        """
        from ..options import EnhancedDifficulty, EnhancedDifficultyLevelScaling

        self.assertEqual(ENHANCED_DIFFICULTY_LEVEL_MULTIPLIER, 1.33)
        self.assertIn("1.33x", EnhancedDifficultyLevelScaling.__doc__)
        self.assertNotIn("+3 level", EnhancedDifficultyLevelScaling.__doc__)
        self.assertNotIn("1.33x", EnhancedDifficulty.__doc__)


if __name__ == "__main__":
    unittest.main()
