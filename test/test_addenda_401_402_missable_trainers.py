"""ADDENDA 401-402 (2026-10-02) -- missable trainer checks are no longer something a player can lose.

Missable checks are treated as bad: once the story passes an area's cap, every missable trainer defeat in that
area is received, and the rematch checks of SPECIFICALLY missable trainers are removed -- losing those locations
is fine. Each such trainer keeps its (Any) check; ALL of its numbered fights go, not just the later ones.

WHY NOW. Universal Tracker shows a check as in logic the moment its region is reachable. A fight the player has
already walked past forever is still "in logic" to it, permanently -- the one thing a tracker cannot be allowed
to say. Removing what can be lost, and sending the rest when the story closes it, is what makes the tracker's
answer true.

ADDENDUM 401 -- THE REMOVAL. A trainer is in scope when any of its rows is on the 47-row missable list
AND it fights more than once: 20 surnames. ALL of their numbered `Defeat - X #N` locations go, the missable #1 and
the later fights alike -- 75. Kept: each one's `Defeat X (Any)`, which fires on whichever fight is won. The 26
one-shot missables have no number and are not rematches, so they stay. Retired through the same door as
`Chobin #7` (ADDENDUM 362): out of the table with frozen ids left behind, out of the client's dispatch queue,
out of the missable fence.

ADDENDUM 402 -- THE AUTO-SEND. The 26 one-shots, plus `Defeat Biden (Any)` -- the one surname EVERY one of whose
fights is missable -- are sent by the client once the story passes the cap of the area each fight lives in. The
byte compared is `StoryProgressWitness.high_water`, the highest byte the GAME wrote, never the live byte the client
writes itself on a map hover. Bost is the one fight in an area with no window (Gateon Port); he releases at 0x19,
the byte that ends the opening Gateon stretch, chosen early on purpose because early is harmless and late is not.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from BaseClasses import LocationProgressType

from . import PokemonXDTestBase
from .. import locations as L
from .. import ram_client as rc
from ..game_data import missable_autosend, missable_indices, missable_trainers, repeatable_trainers
from ..game_data import story_bytes, trainer_placements, trainer_roster

HERE = Path(__file__).resolve().parent.parent
REMOVED = trainer_roster.REMOVED_MISSABLE_DEFEAT_LOCATIONS
SCHEDULE = missable_autosend.AUTO_SEND_AT_STORY_BYTE


def _surnames_in_scope() -> "set[str]":
    return {
        trainer_roster.TRAINERS_BY_INDEX[i]["name"].upper()
        # ADDENDUM 460: the fights reclassified as unmissable keep the removal they had, so they stay in scope here.
        for i in missable_indices.MISSABLE_TRAINER_INDICES | missable_indices.CONFIRMED_UNMISSABLE
        if i in trainer_roster.TRAINERS_BY_INDEX and trainer_roster.TRAINERS_BY_INDEX[i]["total_with_name"] > 1
    }


# ============================================================================================================
# ADDENDUM 401
# ============================================================================================================
class TestWhatWasRemoved(unittest.TestCase):
    def test_the_expected_numbers(self) -> None:
        """ADDENDUM 406 narrowed 75 to 21: only the MISSABLE fights go; the mandatory/non-missable rematches are
        still counted."""
        self.assertEqual(39, len(missable_indices.MISSABLE_TRAINER_INDICES))  # ADDENDUM 440: +4 Phenac invasion; 460: -13 reclassified unmissable
        self.assertEqual(20, len(_surnames_in_scope()))
        # ADDENDUM 409: the Sixes' #2 is at Phenac (missable, behind the Disc and the Note) -- their missable fight is
        # now their #2, and it is KEPT as a check. 21 missable fights of in-scope surnames, six of them kept.
        self.assertEqual(6, len(trainer_roster.KEPT_MISSABLE_DEFEAT_LOCATIONS))
        # ADDENDUM 436 retired ADDENDUM 411's link: Ardos vs Zook is a fight the player only watches.
        self.assertEqual(frozenset(), trainer_roster.LINKED_MISSABLE_DEFEAT_LOCATIONS)
        self.assertEqual(15, len(REMOVED))
        self.assertEqual(21, len(REMOVED) + len(trainer_roster.KEPT_MISSABLE_DEFEAT_LOCATIONS))

    def test_the_missable_fights_go_and_the_mandatory_rematches_stay(self) -> None:
        for name in ("Defeat - Dosk #1", "Defeat - Aferd #1",
                     "Defeat - Biden #1", "Defeat - Biden #2"):
            self.assertIn(name, REMOVED, name)
            self.assertNotIn(name, L.LOCATION_TABLE, name)
        # ADDENDUM 409: the Sixes' #1 is at the Cipher Lab and their #2 at Phenac (missable, behind the Disc and Note).
        # Resix #1 is no longer missable at all; Resix #2 is missable but kept as a check.
        for name in ("Defeat - Resix #1", "Defeat - Resix #2"):
            self.assertNotIn(name, REMOVED, name)
            self.assertIn(name, L.LOCATION_TABLE, name)
        self.assertIn("Defeat - Resix #2", trainer_roster.KEPT_MISSABLE_DEFEAT_LOCATIONS)
        for name in ("Defeat - Laken #3",):
            self.assertNotIn(name, REMOVED, name)
            self.assertIn(name, L.LOCATION_TABLE, name)
        # ADDENDUM 436: Ardos, Zook and Biden have no numbered checks at all -- one (Any) each.
        for name in ("Defeat - Zook #2", "Defeat - Ardos #2"):
            self.assertIn(name, trainer_roster.RULED_OUT_DEFEAT_LOCATIONS, name)
            self.assertNotIn(name, L.LOCATION_TABLE, name)
        # ADDENDUM 409 removed all of Cida's, Clerr's, Belish's, Dosk's, Hebon's and Aferd's rematches, and all the
        # Sixes' other fights. These were mandatory rematches 406 kept; they are gone now as deliberate removals,
        # not because they are missable.
        for name in ("Defeat - Dosk #2", "Defeat - Dosk #3", "Defeat - Resix #6", "Defeat - Aferd #5"):
            self.assertNotIn(name, REMOVED, name)
            self.assertIn(name, trainer_roster.RULED_OUT_DEFEAT_LOCATIONS, name)
            self.assertNotIn(name, L.LOCATION_TABLE, name)

    def test_exactly_the_missable_fights_of_in_scope_surnames(self) -> None:
        expected = {
            trainer_roster.trainer_label(row)
            for surname in _surnames_in_scope()
            for row in trainer_roster.TRAINERS_BY_NAME[next(
                n for n in trainer_roster.TRAINERS_BY_NAME if n.upper() == surname)]
            # ADDENDUM 460: the fights reclassified as unmissable keep their numbered-check removal.
            if row["index"] in (missable_indices.MISSABLE_TRAINER_INDICES | missable_indices.CONFIRMED_UNMISSABLE)
        }
        # ADDENDUM 409: the Sixes' #2 is at Phenac (missable, behind the Disc and the Note), and it is kept.
        self.assertLessEqual(trainer_roster.KEPT_MISSABLE_DEFEAT_LOCATIONS, expected)
        kept = trainer_roster.KEPT_MISSABLE_DEFEAT_LOCATIONS | trainer_roster.LINKED_MISSABLE_DEFEAT_LOCATIONS
        self.assertEqual(expected - kept, set(REMOVED))   # ADDENDUM 411: Zook #1 kept, linked to Ardos #1

    def test_one_shot_missables_are_not_touched(self) -> None:
        for name in ("Defeat - Digor", "Defeat - Bost", "Defeat - Fudler"):
            self.assertNotIn(name, REMOVED)
            self.assertIn(name, L.LOCATION_TABLE)

    def test_a_trainer_that_is_not_missable_keeps_its_rematches(self) -> None:
        """Scope is SPECIFICALLY missable trainers. Miror B. fights many times and is not on the list."""
        self.assertFalse(any(n.startswith("Defeat - Miror B.") for n in REMOVED))
        self.assertIn("Defeat - Miror B. #2", L.LOCATION_TABLE)


class TestRetiredThroughTheSameDoorAsChobin(unittest.TestCase):
    def test_out_of_the_table_with_the_id_left_behind(self) -> None:
        live = {data.id_offset for data in L.LOCATION_TABLE.values()}
        for name in REMOVED:
            self.assertNotIn(name, L.LOCATION_TABLE, name)
            self.assertIn(name, L._FROZEN_LOCATION_OFFSETS, name)
            self.assertNotIn(L._FROZEN_LOCATION_OFFSETS[name], live, f"{name}'s id was handed to another location")

    def test_out_of_the_dispatch_queue(self) -> None:
        """ADDENDUM 406: every surname in scope queues exactly its non-missable fights -- one label per team the
        player cannot miss, so skipping the missable fight costs nothing. Biden queues nothing."""
        # ADDENDUM 409 trimmed most in-scope surnames further (Aferd's rematches, the Sixes' other fights, ...).
        # Those queue only what the trim left; the untouched ones (Zook, Laken, Biden)
        # still queue exactly one label per non-missable team.
        trimmed = {"AFERD", "CIDA", "HEBON", "DOSK", "DOBY", "LABET", "RALING", "FINOL", "EROLL", "EQUIN", "WILLIE"}
        trimmed |= trainer_roster.SIXES
        missable_labels = {
            trainer_roster.trainer_label(trainer_roster.TRAINERS_BY_INDEX[i])
            for i in missable_indices.MISSABLE_TRAINER_INDICES
        }
        for surname in _surnames_in_scope():
            queue = trainer_roster.UNIQUE_SURNAME_TO_LOCATION_QUEUE[surname]
            self.assertFalse(set(queue) & trainer_roster.REMOVED_DEFEAT_LOCATIONS, surname)
            needs = [label for label in queue if label not in missable_labels]
            if surname in trimmed or surname in ("ZOOK", "BIDEN"):   # ADDENDUM 436: one (Any), no numbered labels
                self.assertLessEqual(len(needs), trainer_roster._NON_MISSABLE_TEAM_COUNTS[surname], surname)
            else:
                self.assertEqual(len(queue), trainer_roster._NON_MISSABLE_TEAM_COUNTS[surname], surname)
        self.assertEqual({"ZOOK", "LAKEN", "BIDEN"}, _surnames_in_scope() - trimmed)
        self.assertEqual([], trainer_roster.UNIQUE_SURNAME_TO_LOCATION_QUEUE["ZOOK"])
        self.assertEqual([], trainer_roster.UNIQUE_SURNAME_TO_LOCATION_QUEUE["BIDEN"])
        # ADDENDUM 409 removed Aferd's rematches; his only other fight, #1, is missable, so nothing is left.
        self.assertEqual([], trainer_roster.UNIQUE_SURNAME_TO_LOCATION_QUEUE["AFERD"])

    def test_out_of_the_missable_fence(self) -> None:
        self.assertFalse(set(missable_trainers.missable_trainer_location_names()) & REMOVED)
        self.assertFalse(set(missable_trainers.filler_only_trainer_location_names()) & REMOVED)


class TestTheAnyChecksStay(unittest.TestCase):
    def test_each_in_scope_surname_still_has_its_any(self) -> None:
        for surname in _surnames_in_scope():
            any_name = repeatable_trainers.SURNAME_TO_LOCATION.get(surname)
            self.assertIsNotNone(any_name, surname)
            self.assertIn(any_name, L.LOCATION_TABLE, any_name)


class TestTheListModuleImportsNothing(unittest.TestCase):
    def test_it_cannot_cycle(self) -> None:
        """The reason it exists: `trainer_roster` reads it, and `missable_trainers` imports `trainer_roster` back."""
        source = (HERE / "game_data" / "missable_indices.py").read_text(encoding="utf-8")
        imports = [l for l in source.splitlines() if l.startswith(("import ", "from "))]
        self.assertEqual(["from __future__ import annotations"], imports)

    def test_there_is_one_copy(self) -> None:
        self.assertIs(missable_trainers.MISSABLE_TRAINER_INDICES, missable_indices.MISSABLE_TRAINER_INDICES)


class TestInAUniqueModeSeed(PokemonXDTestBase):
    options = {"shuffle_trainer_defeats": True, "trainer_defeat_mode": 1}

    def test_no_removed_fight_exists(self) -> None:
        created = {location.name for location in self.multiworld.get_locations(self.player)}
        self.assertFalse(created & REMOVED)

    def test_the_any_checks_and_one_shots_do(self) -> None:
        created = {location.name for location in self.multiworld.get_locations(self.player)}
        self.assertIn("Defeat Dosk (Any)", created)
        self.assertIn("Defeat Biden (Any)", created)
        self.assertIn("Defeat - Digor", created)


# ============================================================================================================
# ADDENDUM 402
# ============================================================================================================
class TestTheSchedule(unittest.TestCase):
    def test_thirty_three_checks(self) -> None:
        # ADDENDUM 409: the Sixes' #2 is at Phenac (missable, behind the Disc and the Note) -- six kept checks join
        # the 26 one-shots. ADDENDUM 436: Biden's (Any) is not missable any more, so it is not scheduled.
        # ADDENDUM 438: + Zook's (Any), which the Key Lair's raised entry floor can step over.
        self.assertEqual(32, len(SCHEDULE))  # ADDENDUM 440: +4 Phenac invasion; 460: - Bost and five Snagem fights
        self.assertLessEqual(trainer_roster.KEPT_MISSABLE_DEFEAT_LOCATIONS, set(SCHEDULE))

    def test_every_surviving_missable_fight_is_scheduled(self) -> None:
        one_shots = {
            trainer_roster.trainer_label(trainer_roster.TRAINERS_BY_INDEX[i])
            for i in missable_indices.MISSABLE_TRAINER_INDICES if i in trainer_roster.TRAINERS_BY_INDEX
        } - REMOVED
        # ADDENDUM 409: the 26 one-shots plus the Sixes' six kept #2 fights (missable, behind the Disc and the Note).
        # ADDENDUM 411: Zook #1 survives too, but is NOT scheduled -- Ardos #1, a fight nobody can miss, sends it.
        self.assertEqual(trainer_roster.LINKED_MISSABLE_DEFEAT_LOCATIONS, one_shots - set(SCHEDULE))
        one_shots -= trainer_roster.LINKED_MISSABLE_DEFEAT_LOCATIONS
        self.assertEqual(31, len(one_shots))  # ADDENDUM 440: +4 Phenac invasion; 460: - Bost and five Snagem fights
        self.assertEqual(6, len(one_shots & trainer_roster.KEPT_MISSABLE_DEFEAT_LOCATIONS))
        self.assertLessEqual(one_shots, set(SCHEDULE))

    def test_every_scheduled_name_is_a_real_location(self) -> None:
        for name in SCHEDULE:
            self.assertIn(name, L.LOCATION_TABLE, name)

    def test_only_the_fully_missable_any_is_scheduled(self) -> None:
        """ADDENDUM 436: Biden's Snagem fight is not missable, so no (Any) can be lost to a missed
        fight. ADDENDUM 438: Zook's can be lost to the Key Lair's entry floor instead, so it is sent once the Lair
        moves past him."""
        scheduled_any = {n for n in SCHEDULE if n.endswith("(Any)")}
        self.assertEqual(set(missable_autosend.FLOOR_SKIPPED_CHECKS), scheduled_any)

    def test_a_cap_is_the_areas_own_ceiling(self) -> None:
        """One source: moving an area's cap moves its auto-send with it."""
        digor = trainer_placements.PLACEMENTS[51]
        self.assertEqual(story_bytes.REGION_STORY_WINDOW[digor.region].ceiling, SCHEDULE["Defeat - Digor"])

    def test_bost_is_the_only_override_and_the_phenac_cipher_fights_wait_for_snattle(self) -> None:
        # ADDENDUM 436: missable Phenac trainers send upon defeating Snattle (ONLY Cipher members).
        self.assertEqual({"Defeat - Bost": 0x19}, missable_autosend.CAP_OVERRIDES)
        phenac = [n for n in ("Pellim", "Fenton", "Forgs", "Kapen", "Ezoor", "Ertlig")] \
            + [f"{n} #2" for n in ("Resix", "Blusix", "Browsix", "Yellosix", "Purpsix", "Greesix")]
        for name in phenac:
            self.assertEqual(missable_autosend.SNATTLE_DEFEATED, SCHEDULE[f"Defeat - {name}"], name)
        self.assertIsNone(story_bytes.REGION_STORY_WINDOW.get("Gateon Port"),
                          "if Gateon ever gains a window, Bost should use it and this override should go")

    def test_every_release_byte_is_one_the_game_rests_on(self) -> None:
        for name, cap in SCHEDULE.items():
            self.assertTrue(story_bytes.byte_is_reachable(cap), f"{name} at 0x{cap:02X}")


class TestEarlyIsHarmless(PokemonXDTestBase):
    """The design leans early everywhere. That is only safe if nothing scheduled can hold anything that matters."""

    options = {"shuffle_trainer_defeats": True, "trainer_defeat_mode": 1}

    def test_every_scheduled_check_is_filler_only(self) -> None:
        for location in self.multiworld.get_locations(self.player):
            if location.name in SCHEDULE:
                self.assertIs(LocationProgressType.EXCLUDED, location.progress_type, location.name)


class TestTheSender(unittest.TestCase):
    SCHED = {"A": 0x2F, "B": 0x41, "C": 0x41}

    def setUp(self) -> None:
        self.sender = rc.MissableAutoSender(self.SCHED)
        self.seed = {"A", "B", "C"}

    def test_nothing_before_any_credible_progress(self) -> None:
        self.assertEqual([], self.sender.due(-1, self.seed, set()))
        self.assertEqual([], self.sender.due(None, self.seed, set()))

    def test_nothing_before_the_cap_and_everything_at_it(self) -> None:
        self.assertEqual([], self.sender.due(0x2E, self.seed, set()))
        self.assertEqual(["A"], self.sender.due(0x2F, self.seed, set()))
        self.assertEqual(["A", "B", "C"], self.sender.due(0x41, self.seed, set()))

    def test_an_unknown_seed_releases_nothing(self) -> None:
        """A name outside the seed is a disconnect (ADDENDUM 322). Not knowing the seed is not permission."""
        self.assertEqual([], self.sender.due(0x7F, None, set()))

    def test_it_never_names_a_location_the_seed_lacks(self) -> None:
        self.assertEqual(["A"], self.sender.due(0x7F, {"A"}, set()))

    def test_already_checked_is_not_re_sent(self) -> None:
        self.assertEqual(["B", "C"], self.sender.due(0x41, self.seed, {"A"}))

    def test_the_real_schedule_is_the_default(self) -> None:
        self.assertEqual(SCHEDULE, rc.MissableAutoSender().schedule)

    def test_describe_reads_without_a_seed(self) -> None:
        lines = rc.MissableAutoSender(self.SCHED).describe(None, set())
        self.assertTrue(any("0x2F" in line for line in lines))


class TestTheClientUsesTheWitness(unittest.TestCase):
    """The live byte is written by this client on every map hover. Reading it would release all 27 at once."""

    def setUp(self) -> None:
        self.source = (HERE / "Client.py").read_text(encoding="utf-8")
        start = self.source.index("async def check_missable_autosend(")
        self.body = self.source[start:self.source.index("\nasync def ", start + 10)]

    def test_it_never_reads_the_live_byte_directly(self) -> None:
        self.assertNotIn("read_story_byte", self.body)
        self.assertIn("story_progress", self.body)

    def test_it_polls_the_witness_itself_when_travel_randomization_is_off(self) -> None:
        self.assertIn("_witness_story_progress(ctx)", self.body)

    def test_it_runs_in_the_poll_loop(self) -> None:
        self.assertIn("await check_missable_autosend(ctx)", self.source)

    def test_it_goes_through_the_one_send_funnel(self) -> None:
        self.assertIn("await _send_checks(ctx, due)", self.body)
