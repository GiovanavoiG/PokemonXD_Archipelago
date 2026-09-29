"""ADDENDUM 236. Two live reports, two fixes.

Player: "shadow purifications are still sending at weird times, including in battle now." And: "when
rematching Resix etc, a user reported that rematching them allowed them to respawn their shadow pokemon even
after being caught - leading to infinite catches on rematches, which is unintended."
"""
from __future__ import annotations

import random
import unittest
from unittest import mock

from .. import ram_client
from ..game_data import census_repeat_column, missable_trainers
from ..game_data.real_trainer_data import real_species_pool, real_trainer_free_slot_census
from ..randomizer.shadow_expansion import build_shadow_expansion_plans


class TestShadowExpansionPlacement(unittest.TestCase):
    """A generated Shadow is a catch LOCATION, so its trainer must be fightable exactly once."""

    def setUp(self) -> None:
        self.census = real_trainer_free_slot_census()
        self.pool = real_species_pool()
        if not self.census or not self.pool:
            self.skipTest("real ISO census data isn't present in this build")
        self.excluded = missable_trainers.shadow_expansion_excluded_trainer_indices()
        self.refightable = {
            index for index, (repeat, _missable) in census_repeat_column.CENSUS_REPEAT_AND_MISSABLE.items()
            if repeat == "final"
        }

    def _plan(self, seed: int):
        return build_shadow_expansion_plans(
            self.census, self.pool, {}, excluded_species=set(), target_count=60,
            rng=random.Random(seed), excluded_trainer_indices=self.excluded,
        )

    def test_no_generated_shadow_lands_on_a_refightable_trainer(self) -> None:
        """The reported bug: the game lets you re-fight a `final` trainer, so its Shadow can be snagged again
        and again."""
        for seed in (3, 11, 42, 101):
            targets = {plan["trainer_index"] for plan in self._plan(seed)}
            self.assertEqual(set(), targets & self.refightable, f"seed {seed}")

    def test_no_generated_shadow_lands_on_a_missable_trainer(self) -> None:
        """Found in the same pass: a Shadow on a missable fight is a catch that can be lost for the seed."""
        for seed in (3, 11, 42, 101):
            targets = {plan["trainer_index"] for plan in self._plan(seed)}
            self.assertEqual(set(), targets & missable_trainers.MISSABLE_TRAINER_INDICES, f"seed {seed}")

    def test_the_exclusion_does_not_starve_the_setting(self) -> None:
        """The ceiling is 44; there must still be room for all of them."""
        for seed in (3, 11, 42):
            placed = sum(len(plan["new_pokemon"]) for plan in self._plan(seed))
            self.assertEqual(44, placed, f"seed {seed} placed {placed} Shadows")

    def test_the_refightable_rows_were_already_inside_the_filler_only_set(self) -> None:
        """Why this is an existing fence applied, not a new one invented."""
        self.assertTrue(self.refightable)
        self.assertTrue(self.refightable <= self.excluded)


class _Rec:
    def __init__(self, name, flag):
        self.name = name
        self.purified_flag = flag


class _Member:
    """`species` here is the NATIONAL DEX number, matching what PartyMember.national_dex returns."""

    def __init__(self, party_index, name, species):
        self.party_index = party_index
        self.name = name
        self.species = species

    @property
    def national_dex(self):
        return self.species

    @property
    def reliable_species(self):
        return ram_client.species_dex_from_name(self.name)


class TestPurificationBattleGate(unittest.TestCase):
    def test_a_battle_poll_does_no_reads_at_all_and_fires_nothing(self) -> None:
        tracker = ram_client.NamedPurificationTracker()
        with mock.patch.object(ram_client, "read_party_members",
                               side_effect=AssertionError("must not read during a battle")):
            self.assertEqual([], tracker.poll(0x1000, in_battle=True))
        self.assertEqual(1, tracker.battle_polls_skipped)

    def test_the_gate_has_a_ceiling_so_a_stuck_signal_cannot_switch_checks_off(self) -> None:
        """`has_unresolved_battle()` has a documented history of sticking True. A suppression that lasts
        forever is the same class of failure as blocking item delivery."""
        tracker = ram_client.NamedPurificationTracker()
        with mock.patch.object(ram_client, "read_party_members", return_value=[]), \
             mock.patch.object(ram_client, "correlate_party_with_recap", return_value={}):
            for _ in range(tracker.MAX_CONSECUTIVE_BATTLE_SKIPS):
                tracker.poll(0x1000, in_battle=True)
            self.assertEqual(tracker.MAX_CONSECUTIVE_BATTLE_SKIPS, tracker.battle_polls_skipped)
            tracker.poll(0x1000, in_battle=True)   # one past the ceiling -- the gate is ignored
        self.assertEqual(tracker.MAX_CONSECUTIVE_BATTLE_SKIPS, tracker.battle_polls_skipped,
                         "the gate must stop suppressing once the ceiling is reached")

    def test_the_count_tracker_passes_the_flag_through(self) -> None:
        counter = ram_client.PurificationCountTracker()
        with mock.patch.object(counter.tracker, "poll", return_value=[]) as inner:
            counter.poll(0x1000, in_battle=True)
        self.assertTrue(inner.call_args.kwargs.get("in_battle"))


class TestRecapPairingMustMatch(unittest.TestCase):
    """The mechanism behind "weird times": party slot i is paired with recap record i unconditionally, so an
    unpurified species read against a purified Pokemon's record shows a 0 -> 64 transition out of nothing."""

    def _poll(self, tracker, member_name, record_name, flag):
        member = _Member(0, member_name, ram_client.species_dex_from_name(member_name) or 216)
        with mock.patch.object(ram_client, "read_party_members", return_value=[member]), \
             mock.patch.object(ram_client, "correlate_party_with_recap",
                               return_value={0: (_Rec(record_name, flag), "name_match")}):
            return tracker.poll(0x1000)

    def test_a_record_naming_a_different_species_is_skipped(self) -> None:
        tracker = ram_client.NamedPurificationTracker()
        for _ in range(tracker._CONFIRM_STREAK + 3):
            self.assertEqual([], self._poll(tracker, "PIDGEY", "TEDDIURSA", ram_client.PURIFIED_FLAG_VALUE))
        self.assertGreater(tracker.mismatched_recap_pairings, 0)

    def test_a_matching_record_still_fires_normally(self) -> None:
        tracker = ram_client.NamedPurificationTracker()
        self._poll(tracker, "TEDDIURSA", "TEDDIURSA", 0)          # baseline at 0
        fired = []
        for _ in range(tracker._CONFIRM_STREAK):
            fired = self._poll(tracker, "TEDDIURSA", "TEDDIURSA", ram_client.PURIFIED_FLAG_VALUE)
        self.assertTrue(fired, "a real purification must still fire")

    def test_a_rename_that_has_not_propagated_delays_rather_than_fires(self) -> None:
        """The one legitimate mismatch: purification invites a rename, and the recap name updates before
        PARTY_BASE does. While the two disagree the pairing is not trusted -- and the moment PARTY_BASE
        catches up, the check fires. Delayed, never lost."""
        tracker = ram_client.NamedPurificationTracker()
        self._poll(tracker, "TEDDIURSA", "TEDDIURSA", 0)
        for _ in range(tracker._CONFIRM_STREAK + 2):
            self.assertEqual([], self._poll(tracker, "TEDDIURSA", "Fluffy",
                                            ram_client.PURIFIED_FLAG_VALUE))
        self.assertGreater(tracker.mismatched_recap_pairings, 0)
        fired = []
        for _ in range(tracker._CONFIRM_STREAK):
            fired = self._poll(tracker, "Fluffy", "Fluffy", ram_client.PURIFIED_FLAG_VALUE)
        self.assertTrue(fired, "once PARTY_BASE catches up the purification must land")

    def test_a_nicknamed_pokemon_whose_names_agree_fires_normally(self) -> None:
        """A settled nickname is self-consistent, so no species lookup is needed at all."""
        tracker = ram_client.NamedPurificationTracker()
        self._poll(tracker, "Fluffy", "Fluffy", 0)
        fired = []
        for _ in range(tracker._CONFIRM_STREAK):
            fired = self._poll(tracker, "Fluffy", "Fluffy", ram_client.PURIFIED_FLAG_VALUE)
        self.assertTrue(fired)
        self.assertEqual(0, tracker.mismatched_recap_pairings)


class TestAPartyChangeResetsPendingStreaks(unittest.TestCase):
    """Player: "depositing pokemon into the pc is also causing purification checks to send randomly." A
    deposit compacts the party, so every slot is paired with the previous occupant's recap record for a
    while."""

    def _poll(self, tracker, members, records):
        with mock.patch.object(ram_client, "read_party_members", return_value=members), \
             mock.patch.object(ram_client, "correlate_party_with_recap", return_value=records):
            return tracker.poll(0x1000)

    def test_a_deposit_cannot_complete_a_confirm_streak(self) -> None:
        tracker = ram_client.NamedPurificationTracker()
        teddi = _Member(0, "TEDDIURSA", 216)
        pidgey = _Member(1, "PIDGEY", 16)
        # A settled two-member party, both unpurified.
        for _ in range(3):
            self._poll(tracker, [teddi, pidgey],
                       {0: (_Rec("TEDDIURSA", 0), "name_match"), 1: (_Rec("PIDGEY", 0), "name_match")})
        # Teddiursa is deposited. Pidgey compacts into slot 0, but slot 0's recap record still belongs to the
        # departed (already-purified) Teddiursa -- and it was NICKNAMED, so the name check cannot help.
        pidgey_now_slot_0 = _Member(0, "PIDGEY", 16)
        fired = []
        for _ in range(tracker._CONFIRM_STREAK + 2):
            fired += self._poll(tracker, [pidgey_now_slot_0],
                                {0: (_Rec("Fluffy", ram_client.PURIFIED_FLAG_VALUE), "name_differs")})
        self.assertEqual([], fired, "a party change must not be able to complete a confirm streak")
        self.assertGreater(tracker.party_changes_seen, 0)

    def test_a_settled_party_still_confirms_normally(self) -> None:
        tracker = ram_client.NamedPurificationTracker()
        teddi = _Member(0, "TEDDIURSA", 216)
        self._poll(tracker, [teddi], {0: (_Rec("TEDDIURSA", 0), "name_match")})
        fired = []
        for _ in range(tracker._CONFIRM_STREAK):
            fired = self._poll(tracker, [teddi],
                               {0: (_Rec("TEDDIURSA", ram_client.PURIFIED_FLAG_VALUE), "name_match")})
        self.assertTrue(fired, "an unchanging party must still confirm a real purification")


class TestTheTwoSpeciesKeysAreInterchangeable(unittest.TestCase):
    """ADDENDUM 220's ledger is persisted and keyed by whatever this tracker calls a species. Falling back to
    `national_dex` is only safe if it lands in the same namespace as the name lookup it replaces."""

    def test_every_live_species_resolves_the_same_both_ways(self) -> None:
        from ..tools import xd_species_index as xi
        agree = disagree = 0
        for live in range(1, 1000):
            dex = xi.national_dex_for_live_species(live)
            name = xi.name_for_live_species(live)
            if dex is None or not name:
                continue
            by_name = ram_client.species_dex_from_name(name)
            if by_name is None:
                continue
            if by_name == dex:
                agree += 1
            else:
                disagree += 1
        self.assertGreater(agree, 300, "the species index should resolve most of the dex")
        self.assertEqual(0, disagree, "the two species keys disagree -- the persisted ledger would be re-keyed")

    def test_the_raw_field_is_NOT_in_that_namespace(self) -> None:
        """Why the old fallback was wrong: past the live-index gap the raw value is its own numbering, and
        for most values it is simply not the dex number. Found by scanning rather than by picking one, since
        the two do coincide at some values by arithmetic accident."""
        from ..tools import xd_species_index as xi
        differing = [
            live for live in range(xi.LIVE_INDEX_GAP_START, xi.LIVE_INDEX_GAP_START + 200)
            if xi.national_dex_for_live_species(live) not in (None, live)
        ]
        self.assertTrue(differing, "expected the live numbering to diverge from the dex past the gap")


class TestTheTrainerIndexNamespacesLineUp(unittest.TestCase):
    """The whole re-fightable fence rests on the workbook's Repeat? column being keyed by the SAME index as
    the DTNR-derived census. If they were different namespaces the fence would exclude the wrong trainers --
    worse than doing nothing."""

    def test_the_roster_and_the_repeat_column_cover_the_same_indices(self) -> None:
        from ..game_data import trainer_roster
        self.assertEqual(set(trainer_roster.TRAINERS_BY_INDEX),
                         set(census_repeat_column.CENSUS_REPEAT_AND_MISSABLE))

    def test_the_roster_carries_real_dtnr_team_data(self) -> None:
        """Which is what makes it the same namespace as the free-slot census, not a parallel list."""
        # ADDENDUM 250: was an absolute `__import__("pokemon_xd.game_data.trainer_roster", ...)`, which
        # double-registers the world under the ordinary worlds/ layout and made this test error instead of
        # run.
        from ..game_data import trainer_roster

        first = trainer_roster.TRAINERS_BY_INDEX[1]
        self.assertEqual("HORDEL", first["name"])
        self.assertTrue(first["team"], "roster entries must carry the trainer's real team")

