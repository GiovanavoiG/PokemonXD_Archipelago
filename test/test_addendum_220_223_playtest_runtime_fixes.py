"""Playtest pass, 2026-09-15 -- ADDENDA 220, 221, 222 and 223.

220: "Save menu is still sending duplicate purifications. Let's identify purifications by species under the
      hood at purification-time, but just increment the count for the checks."
221: "Party AND PC scanning are inconsistent at best. See if we can find a more consistent spot/area to
      search."
222: "Our item delivery system is better, but still a touch inconsistent."
223: "Shadow bolt was generated on a shadow pokemon (pidgey) - when trying to use it, it failed saying it had
      no PP - it shouldn't need PP."
"""
import random
import unittest

from .. import ram_client as rc
from ..game_data import shadow_move_slots as sms


class TestPurificationsAreCountedOncePerSpecies(unittest.TestCase):
    class _Fake:
        def __init__(self, queue):
            self.queue = list(queue)

        def poll(self, *args, **kwargs):
            return self.queue.pop(0) if self.queue else []

    def tracker(self, queue):
        t = rc.PurificationCountTracker()
        t.tracker = self._Fake(queue)
        return t

    def test_the_same_species_is_never_counted_twice(self):
        """The player's own example: the same Totodile must not be scanned twice."""
        t = self.tracker([[(158, 0)], [(158, 0)], [(158, 0)]])
        first = t.poll(0)
        self.assertEqual(len(first), 1)
        self.assertEqual(t.poll(0), [])
        self.assertEqual(t.poll(0), [])
        self.assertEqual(t.total_purified, 1)
        self.assertEqual(t.duplicate_species_rejected, 2)

    def test_different_species_each_advance_the_count(self):
        t = self.tracker([[(158, 0)], [(7, 1)], [(1, 2)]])
        names = [t.poll(0) for _ in range(3)]
        self.assertEqual([len(n) for n in names], [1, 1, 1])
        self.assertEqual(t.total_purified, 3)
        self.assertEqual(t.duplicate_species_rejected, 0)

    def test_the_checks_are_still_the_cumulative_ladder(self):
        """"just increment the count for the checks" -- the species is the identity, the count is the reward."""
        t = self.tracker([[(158, 0)], [(7, 1)]])
        self.assertEqual(t.poll(0), [rc.purification_location_name(1)])
        self.assertEqual(t.poll(0), [rc.purification_location_name(2)])

    def test_a_species_seen_past_the_cap_is_still_recorded(self):
        """Otherwise it could be counted later if the cap ever moved, which is the same duplicate by a
        slower route."""
        t = self.tracker([[(900 + i, 0)] for i in range(rc.PURIFICATION_LOCATION_COUNT + 2)])
        for _ in range(rc.PURIFICATION_LOCATION_COUNT + 2):
            t.poll(0)
        self.assertEqual(t.total_purified, rc.PURIFICATION_LOCATION_COUNT)
        self.assertEqual(len(t.purified_species), rc.PURIFICATION_LOCATION_COUNT + 2)

    def test_the_ledger_round_trips_through_json(self):
        """It has to outlive a client restart, or a species purified in an earlier session looks brand new to
        a fresh client and the duplicate comes straight back."""
        t = self.tracker([[(158, 0)], [(7, 1)]])
        t.poll(0)
        t.poll(0)
        restored = rc.PurificationCountTracker()
        restored.load_json(t.to_json())
        self.assertEqual(restored.purified_species, {158, 7})
        self.assertEqual(restored.total_purified, 2)

    def test_a_corrupt_ledger_degrades_rather_than_raising(self):
        for junk in ({}, {"purified_species": "no"}, {"total_purified": None}):
            t = rc.PurificationCountTracker()
            t.load_json(junk)
            self.assertEqual(t.purified_species, set())


class TestCatchScanningSeparatesItsSources(unittest.TestCase):
    """ADDENDUM 221. ADDENDUM 147 unioned the save-block party into the box snapshot, which put party-shaped
    data through a guard whose premise is one-slot-at-a-time box movement."""

    def test_a_multi_slot_recap_refresh_no_longer_distrusts_the_poll(self):
        """A battle refreshes several party recap records at once. Under the union that was ">1 new species in
        one poll" -- the save-menu glitch signature -- so the poll was discarded and the streak reset, for as
        long as it kept being true."""
        t = rc.SpeciesCatchTracker()
        t.poll(set(), {25}, set())
        fired = []
        for _ in range(6):
            fired += t.poll(set(), {25}, {133, 134, 135})
        self.assertEqual(sorted(set(fired)), [133, 134, 135])
        self.assertEqual(t.distrusted_polls, 0)

    def test_the_box_guard_still_catches_a_glitch_snapshot(self):
        """The guard must not have been weakened -- it is what stops ADDENDUM 146's wrong catches.

        RETARGETED BY ADDENDUM 333. "Gaining several species at once" is no longer the glitch signature: a
        box that gains and loses nothing is a double Shadow snag with a full party, and treating it as a
        glitch locked the tracker for the rest of the session. The signature is the box reading as a
        DIFFERENT snapshot of itself, which gains AND loses -- asserted here, and the pure-gain case is
        asserted below to still fire nothing on the ordinary window."""
        t = rc.SpeciesCatchTracker()
        t.poll(set(), {25}, set())
        fired = []
        for _ in range(6):
            fired += t.poll(set(), {133, 134, 135}, set())
        self.assertEqual(fired, [])
        self.assertGreater(t.distrusted_polls, 0)

    def test_a_pure_gain_burst_is_trusted_but_waits_out_the_long_window(self):
        """ADDENDUM 333. Trusted, so the baseline advances and nothing locks -- but the ordinary four-poll
        window is deliberately not enough for species a multi-gain poll introduced."""
        t = rc.SpeciesCatchTracker()
        t.poll(set(), {25}, set())
        fired = []
        for _ in range(t._CONFIRM_STREAK + 1):
            fired += t.poll(set(), {25, 133, 134, 135}, set())
        self.assertEqual(fired, [])
        self.assertEqual(0, t.distrusted_polls)
        for _ in range(t._MULTI_GAIN_CONFIRM_STREAK):
            fired += t.poll(set(), {25, 133, 134, 135}, set())
        self.assertEqual([133, 134, 135], sorted(fired), "and they do arrive, just later")

    def test_a_box_gain_and_loss_together_is_still_distrusted(self):
        t = rc.SpeciesCatchTracker()
        t.poll(set(), {25}, set())
        t.poll(set(), {133}, set())
        self.assertGreater(t.distrusted_polls, 0)

    def test_the_party_struct_is_still_trusted_immediately(self):
        t = rc.SpeciesCatchTracker()
        t.poll(set(), set(), set())
        self.assertEqual(t.poll({25}, set(), set()), [25])

    def test_a_recap_candidate_still_has_to_hold(self):
        """Not subject to guard 2, but not free either -- it still serves the confirm streak."""
        t = rc.SpeciesCatchTracker()
        t.poll(set(), set(), set())
        self.assertEqual(t.poll(set(), set(), {133}), [])

    def test_the_two_argument_form_still_works(self):
        """Compatibility: a caller that has not been updated must keep measuring what it used to."""
        t = rc.SpeciesCatchTracker()
        t.poll(set(), {25})
        self.assertEqual(t.poll({133}, {25}), [133])


class TestDeliveryConfirmsOnThePeak(unittest.TestCase):
    """ADDENDUM 222. The confirm asked "does the player still have it?" when the question is "did our write
    land?" -- different answers the moment the player uses the item."""

    BLOCK = 0x80479000

    def test_the_read_window_is_the_whole_shared_pocket_array(self):
        """REWRITTEN 2026-09-15 (ADDENDUM 231). `delivery_read_slot_count` returned only a COUNT and left the
        caller to supply a base -- and every caller supplied the narrow WRITE base, which for a berry is array
        slot 82. A 190-slot read from there skipped the low slots the game actually fills and ran past the end
        of the array. `resolve_item_read_window` returns base AND count together so that cannot be expressed."""
        array_base = self.BLOCK + rc.POKEBALL_POCKET_OFFSET
        for item_id in (161, 300, 5):
            base, slots = rc.resolve_item_read_window(self.BLOCK, item_id)
            self.assertEqual(base, array_base, f"id {item_id} must read from the ARRAY base")
            self.assertEqual(slots, rc.POKEBALL_POCKET_ARRAY_SLOT_COUNT)
            self.assertLessEqual(base + slots * 4, self.BLOCK + rc.MONEY_OFFSET,
                                 f"id {item_id}'s read runs past the end of the array")

    def test_pockets_that_are_their_own_array_are_unchanged(self):
        """Only the Poke Ball/TM/Berries array has sub-windows carved out of a bigger confirmed array. The
        others already read at full extent, and widening them would be inventing a range."""
        for item_id in (13, 68, 225, 503):
            self.assertEqual(rc.resolve_item_read_window(self.BLOCK, item_id),
                             rc.resolve_item_pocket(self.BLOCK, item_id))

    def test_an_unknown_id_has_no_window(self):
        self.assertIsNone(rc.resolve_item_read_window(self.BLOCK, None))

    def test_the_old_count_only_helper_is_gone(self):
        """Deleted rather than kept: its SHAPE was the bug, so leaving it callable invites the same
        mispairing back."""
        self.assertFalse(hasattr(rc, "delivery_read_slot_count"))

    def test_the_client_confirms_against_a_peak(self):
        import pathlib

        source = (pathlib.Path(rc.__file__).resolve().parent / "Client.py").read_text(encoding="utf-8")
        self.assertIn("peak = max(ctx._delivery_peak.get(idx, 0), current)", source)
        self.assertIn("if peak >= baseline + quantity:", source)
        self.assertNotIn("if current >= baseline + quantity:", source,
                         "the current-value test is what looped forever on a consumed item")

    def test_both_halves_of_the_comparison_use_the_same_window(self):
        """The baseline and the current reading must be measured over the same window, or widening one makes
        things worse rather than better. UPDATED (ADDENDUM 231) for the base+count helper."""
        import pathlib

        source = (pathlib.Path(rc.__file__).resolve().parent / "Client.py").read_text(encoding="utf-8")
        self.assertEqual(
            source.count("ram_client.resolve_item_read_window(ctx.block_base, game_item_id)"), 2,
            "once for the baseline, once for the current value",
        )
        self.assertNotIn("delivery_read_slot_count", source)


class TestGeneratedShadowsKeepTheirRealMoves(unittest.TestCase):
    """Player, 2026-09-15: "The 4 move set would include two normal moves right? Currently the generated
    pokemon are getting their actual moves properly, so make sure that still works."

    The two move sets are SEPARATE STRUCTURES, which is the thing worth pinning: a generated Shadow Pokemon's
    four ORDINARY moves live in its DPKM entry in DeckData_Story.bin (its real learnset moves, what it uses
    once purified), and its two SHADOW moves live in a DDPK entry in DeckData_DarkPokemon.bin (what it uses
    while it is still a Shadow). Raising the ordinary count from 3 to 4 (ADDENDUM 217) and fixing shadow-move
    slot legality (ADDENDUM 223) touch different fields, and neither may disturb the other."""

    @classmethod
    def setUpClass(cls):
        import random

        from ..game_data import real_trainer_data as rtd
        from ..game_data.real_moveset_data import load_level_up_moves
        from ..randomizer import shadow_expansion

        cls.learnsets = load_level_up_moves()
        if not cls.learnsets:
            raise unittest.SkipTest("no real ISO-extracted learnset data in this build")
        plans = shadow_expansion.build_shadow_expansion_plans(
            rtd.real_trainer_free_slot_census(), rtd.real_species_pool(),
            cls.learnsets, set(), 44, random.Random(7),
        )
        cls.mons = [m for p in plans for m in p["new_pokemon"]]

    def test_ordinary_and_shadow_moves_are_separate_fields(self):
        for mon in self.mons:
            self.assertIn("moves", mon)
            self.assertIn("shadow_moves", mon)
            self.assertFalse(set(mon["moves"]) & set(mon["shadow_moves"]),
                             "a Shadow move leaked into the ordinary moveset")

    def test_most_generated_shadows_get_a_full_four_ordinary_moves(self):
        """Not all: a species with fewer legal learnset moves at its level gets what it has, same as the many
        vanilla Pokemon that ship with fewer than four. 'Most' is the honest assertion."""
        full = [m for m in self.mons if len(m["moves"]) == 4]
        self.assertGreater(len(full), len(self.mons) * 0.8,
                           "the 4-move change is not reaching generated Shadow Pokemon")

    def test_every_ordinary_move_is_one_that_species_could_really_know(self):
        """The player's "getting their actual moves properly". Every ordinary move is either from the species'
        own level-up learnset at or below its level, or ADDENDUM 100's level-30+ strong-TM bonus move."""
        from ..game_data.move_data import TM_ATTACKING_MOVES

        for mon in self.mons:
            learnset = self.learnsets.get(mon["species"], [])
            by_level = {move for level, move in learnset if level <= mon["level"]}
            whole = {move for _level, move in learnset}
            for move in mon["moves"]:
                if not move:
                    continue
                if move in by_level or move in (whole if not by_level else set()):
                    continue
                self.assertIn(move, TM_ATTACKING_MOVES,
                              f"species {mon['species']} got move {move}, which is neither in its learnset "
                              f"nor a TM bonus move")
                self.assertGreaterEqual(mon["level"], 30,
                                        "the TM bonus is a level-30+ rule (ADDENDUM 100)")

    def test_every_generated_shadow_gets_exactly_two_shadow_moves(self):
        for mon in self.mons:
            self.assertEqual(len(mon["shadow_moves"]), 2)

    def test_no_generated_shadow_has_an_illegal_shadow_move_placement(self):
        """The end-to-end statement of ADDENDUM 223 against the real generator, not just the helper."""
        for mon in self.mons:
            self.assertEqual(sms.illegal_placements(mon["shadow_moves"]), [],
                             f"species {mon['species']}: {mon['shadow_moves']}")


class TestShadowMovesAreSlotLegal(unittest.TestCase):
    """ADDENDUM 223. The player's Pidgey had move 364 in slot 1; 364 appears only in slot 0 in all 83 vanilla
    entries."""

    def test_the_players_own_case_is_now_detected(self):
        self.assertEqual(sms.illegal_placements([356, 364]), [(1, 364)])

    def test_the_secondary_moves_are_barred_from_slot_zero(self):
        for move in (367, 368, 369, 370, 371, 372, 373):
            self.assertFalse(sms.is_legal_in_slot(move, 0), move)
            self.assertNotIn(move, sms.MOVES_LEGAL_IN_SLOT[0])

    def test_the_slot_zero_only_moves_are_barred_from_later_slots(self):
        for move in (356, 363, 364, 365, 366):
            self.assertTrue(sms.is_legal_in_slot(move, 0), move)
            for slot in (1, 2, 3):
                self.assertFalse(sms.is_legal_in_slot(move, slot), (move, slot))

    def test_every_vanilla_entry_passes_its_own_rule(self):
        """The table is measured FROM the vanilla data, so this is a round-trip check on the transcription --
        a typo'd row would make a real vanilla Shadow Pokemon look illegal."""
        for move, slots in sms.SHADOW_MOVE_OBSERVED_SLOTS.items():
            for slot in slots:
                self.assertIn(move, sms.MOVES_LEGAL_IN_SLOT[slot])

    def test_the_generator_only_produces_legal_placements(self):
        rng = random.Random(0)
        for _ in range(500):
            moves = sms.choose_shadow_moves(rng, 2)
            self.assertEqual(len(moves), 2)
            self.assertEqual(len(set(moves)), 2, "the two moves should be distinct")
            self.assertEqual(sms.illegal_placements(moves), [], moves)

    def test_the_old_uniform_sample_would_have_failed_this(self):
        """States the bug as a fact rather than a story: sampling from all 18 ids produces illegal placements
        at a high rate, which is what the player's patch showed at 14 of 44."""
        rng = random.Random(0)
        bad = sum(1 for _ in range(500)
                  if sms.illegal_placements(rng.sample(sms.ALL_SHADOW_MOVE_IDS, 2)))
        self.assertGreater(bad, 100, "the old approach really was producing illegal placements in bulk")

    def test_shadow_expansion_uses_the_slot_aware_chooser(self):
        import inspect

        from ..randomizer import shadow_expansion

        source = inspect.getsource(shadow_expansion)
        self.assertIn("shadow_move_slots.choose_shadow_moves(rng, 2)", source)
        self.assertNotIn("rng.sample(REAL_SHADOW_MOVE_IDS, 2)", source)

    def test_the_patcher_rotates_each_slot_through_its_own_list(self):
        import pathlib

        from ..tools import iso_patcher

        source = pathlib.Path(iso_patcher.__file__).read_text(encoding="utf-8")
        self.assertNotIn("shadow_move_pool", source,
                         "the single shared rotation drew slot 0 and slot 1 from the same list")
        self.assertEqual(source.count("[slot0_pool[i % len(slot0_pool)], slot1_pool[i % len(slot1_pool)]]"), 2,
                         "both copies of DarkPokemon must be written identically")


if __name__ == "__main__":
    unittest.main()
