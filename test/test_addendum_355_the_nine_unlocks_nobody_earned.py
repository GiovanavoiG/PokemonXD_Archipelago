"""ADDENDUM 355 (2026-09-25): nine unlocks nobody earned.

Player, with a screenshot of nine `Unlock -` checks firing on arrival at Gateon Port: "No, I did not earn
those nine unlocks. I went to an area past them so it gave me all of them." Then: "Let's figure out those
early unlocks."

WHAT THE OLD GATE ASKED. ADDENDUM 268's `_story_byte_was_earned_here` compared the player's CURRENT region's
unlock floor against the threshold and credited when `floor < threshold`. It was written for the failure of
its own day -- reaching Citadark (floor 0x6E) by item credited Phenac (0x3E), Pyrite, Mt. Battle and the rest
at once -- and it fixed that failure.

WHY IT IS ONE-SIDED. `floor < threshold` refuses a LATE region crediting an EARLY unlock. It says nothing
about an EARLY region crediting a LATE one, and that direction is the larger hole, because the earliest
regions qualify for EVERYTHING. Gateon Port's floor is 0x0F. From Gateon, every threshold in the game is
above the floor, so every unlock qualified the moment the global byte was high -- and it was high, honestly,
from play in the Snagem Hideout. The player walked into an early town and was paid for the whole map.

WHY THE BYTE ALONE CANNOT ANSWER IT, which is why the fix is a change of question rather than a tighter
comparison. `Unlock -` locations exist ONLY when `randomize_travel_locations` is on, and that is exactly the
mode where this client FORGES the story byte on every arrival (ADDENDUM 177). The high-water that follows is
honest -- the game advanced it -- but it advanced from a value we invented, in a place the player reached by
item. With travel shuffle on, the story byte is not a path.

THE NEW RULE, which is about the DESTINATION rather than about where the player happens to stand:

    `Unlock - D` is earned when the GAME moved the story byte to D's own threshold while the player was in D.

That is `AreaStoryByteMemory.highest_by_region`, which this project already maintains and already refuses to
bank anything this client wrote (ADDENDA 229/275/277) or anything carried in from another area (ADDENDUM
288). A mark exists only where the game moved the byte itself.

AND IT DOES NOT REOPEN ADDENDUM 270, which is the trap. That addendum tightened the old guard to strict `<`
precisely so a travel item could not pay out its own check -- "you unlock the icon and then go". A rule of
"have you been to D" would hand that straight back, because in a shuffled seed arriving at D is exactly what
the item buys. This rule cannot: arriving writes D's entry floor, and that write is ours, so no mark comes of
it. The item gets you there; the mark still has to be earned.

THE THREE CASES ARE THE WHOLE DESIGN:
  * travel to Pyrite and walk out again -- we wrote 0x30, nothing banked, no credit;
  * travel to Pyrite and play until the game advances the byte -- Pyrite's mark rises, credit;
  * play the Snagem Hideout instead -- Snagem's mark rises, Pyrite's does not, and Pyrite is NOT credited no
    matter how high the global byte goes.

THE ONE RISK, stated rather than hidden: a destination whose byte never advances while the player is in it
would hold its check forever, silently. `!unlocks` exists for that -- it prints every destination's
threshold, its mark and the verdict, so a stranded check is a row a player can read and report.

SUPERSEDED IN PART, 2026-09-25 (ADDENDUM 356). The rule below asks for the mark in D ITSELF. That fixes the
failure this addendum is about, but it fixes it the wrong way round -- the player, reading it back: "They
should be logically gated behind the area before them - that's where they're unlocked." Asking for the mark
in D made every `Unlock - D` check wait on `Travel Unlock - D`, which is ADDENDUM 270's self-credit deferred
rather than prevented. ADDENDUM 356 moves the witness one rung down the ladder. Everything else here -- the
diagnosis, why the byte alone cannot answer it, and why `observe()`'s guards are what make any of this safe --
stands, which is why this file is retargeted rather than retired.

A NOTE ON WHAT THE NINE EARLY SENDS COST: nothing in the seed's logic. `Unlock -` locations hang off Menu
with no access rule, so the generator already treats them as sphere 0 and puts no progression behind them.
The failure was a wrong story, not a broken seed.
"""
from __future__ import annotations

import pathlib
import re
import unittest

from .. import travel_locations
from ..game_data import story_bytes


ROOT = pathlib.Path(__file__).resolve().parent.parent
CLIENT = (ROOT / "Client.py").read_text(encoding="utf-8")
RAM = (ROOT / "ram_client.py").read_text(encoding="utf-8")


def _function(source: str, header: str) -> str:
    """The named function's own text.

    `re`, not `source.index("\\ndef ")`: what follows these two is `async def`, and bounding on the plain
    form swallows `enforce_travel_locks` whole. That mistake was made once while writing this addendum and
    deleted 170 lines of the client, so the slicing is stated here rather than repeated inline."""
    start = source.index(header)
    following = re.search(r"^(?:async )?def ", source[start + len(header):], re.M)
    assert following is not None, header
    return source[start:start + len(header) + following.start()]


class TestTheWitnessRegionsResolve(unittest.TestCase):
    """Every destination must have somewhere that counts as "the player has been here". A destination whose
    witness set is empty could never be credited at all, which is the one way this rule could lose a check
    outright rather than merely holding it."""

    def test_every_gated_destination_has_a_witness(self) -> None:
        for name in travel_locations.TRAVEL_LOCATION_NAMES:
            if travel_locations.vanilla_unlock_story_byte(name) is None:
                continue
            self.assertTrue(travel_locations.unlock_witness_regions(name), name)

    def test_the_witness_is_a_whole_area_group(self) -> None:
        """A group, not a single region: Pyrite's ONBS interior and Phenac's Mayor's House have separate
        marks, and a rule watching only the outdoor tier would hold a check earned indoors.

        RETARGETED 2026-09-25 (ADDENDUM 356): the group is the PREDECESSOR's, not the destination's -- see
        that addendum. The group-shaped-ness, which is what this test is actually about, is unchanged."""
        witnesses = travel_locations.unlock_witness_regions("Realgam Tower")
        self.assertEqual(set(story_bytes.AREA_GROUPS["Phenac City"]), set(witnesses))
        self.assertNotIn("Realgam Tower", witnesses, "ADDENDUM 356: never the destination's own group")

    def test_every_witness_region_is_a_region_the_memory_can_mark(self) -> None:
        """A witness that no room maps to would be a mark that never arrives -- exactly the stranded-check
        hazard, introduced by the fix itself."""
        from ..game_data import chest_regions

        # `ROOM_TO_REGION` is the table the client's room tracker resolves through, and it is what decides
        # which region `observe()` is ever called with. A witness region absent from its values could never
        # be marked by any room the player can stand in.
        reachable = set(chest_regions.ROOM_TO_REGION.values())
        self.assertTrue(reachable)
        for name in travel_locations.TRAVEL_LOCATION_NAMES:
            if travel_locations.vanilla_unlock_story_byte(name) is None:
                continue
            self.assertTrue(set(travel_locations.unlock_witness_regions(name)) & reachable, name)

    def test_the_helper_never_raises_on_a_name_it_does_not_know(self) -> None:
        self.assertEqual((), travel_locations.unlock_witness_regions("Not A Place"))


class TestTheGateAsksAboutTheDestination(unittest.TestCase):
    """Structural -- `Client.py` is not importable here."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.mark = _function(CLIENT, "def _unlock_mark_for")
        cls.gate = _function(CLIENT, "def _unlock_is_earned")

    def test_the_credit_calls_it_with_the_destination(self) -> None:
        """The whole change in one line: the gate takes the DESTINATION now. 268's took only a threshold,
        because the other half of its question was the player's live position."""
        self.assertIn("if not _unlock_is_earned(ctx, name, threshold):", CLIENT)

    def test_it_compares_a_mark_and_nothing_else(self) -> None:
        code = re.sub(r'""".*?"""', "", self.gate, flags=re.S)
        self.assertIn("mark is not None and mark >= threshold", code)
        for gone in ("area_unlock_floor", "area_entry_floor", "read_room_id", "MAP_SCREEN_ROOM_ID"):
            self.assertNotIn(gone, code, gone)

    def test_the_mark_comes_from_the_area_memory(self) -> None:
        code = re.sub(r'""".*?"""', "", self.mark, flags=re.S)
        self.assertIn("ctx.area_story_memory.highest_by_region", code)
        self.assertIn("unlock_witness_regions(destination)", code)

    def test_it_takes_the_highest_of_the_group(self) -> None:
        self.assertIn("max(seen) if seen else None", self.mark)

    def test_an_absent_mark_holds_and_never_credits(self) -> None:
        self.assertIn("mark is not None", self.gate)

    def test_a_failed_read_holds_too(self) -> None:
        """ADDENDUM 226/267's standing rule: "ask again next poll", never "credit anyway"."""
        code = re.sub(r'""".*?"""', "", self.mark, flags=re.S)
        after = code[code.index("except Exception:"):]
        self.assertIn("return None", after)


class TestTheGloballyHighByteIsNoLongerEnough(unittest.TestCase):
    """The player's failure, stated as an arithmetic fact about the tables rather than as a story.

    Gateon Port's floor sits at or before EVERY threshold in the game. Under 268's `floor < threshold` that
    made Gateon qualify for all of them at once, which is why nine fired together. Nothing about the tables
    changed -- the rule did -- so this has to keep reading the same way and still be harmless."""

    def test_gateon_still_sits_below_almost_every_threshold(self) -> None:
        gateon = story_bytes.area_unlock_floor("Gateon Port")
        self.assertIsNotNone(gateon)
        below = [name for name in travel_locations.TRAVEL_LOCATION_NAMES
                 if (t := travel_locations.vanilla_unlock_story_byte(name)) is not None and gateon < t]
        self.assertGreaterEqual(len(below), 9,
                                "if this ever drops, the failure this addendum fixes has been masked rather "
                                "than fixed, and the reasoning needs redoing")

    def test_and_the_gate_no_longer_consults_that_number(self) -> None:
        gate = re.sub(r'""".*?"""', "", _function(CLIENT, "def _unlock_is_earned"), flags=re.S)
        mark = re.sub(r'""".*?"""', "", _function(CLIENT, "def _unlock_mark_for"), flags=re.S)
        for body in (gate, mark):
            self.assertNotIn("area_unlock_floor", body)


class TestTheMarkCannotBeOurOwnWrite(unittest.TestCase):
    """ADDENDUM 270's finding, which is what shaped this design: a travel item must not pay out its own
    check. Under the new rule that is guaranteed by `observe()`, so `observe()`'s guards are load-bearing for
    THIS addendum and are pinned here as well as in their own."""

    @classmethod
    def setUpClass(cls) -> None:
        at = RAM.index("class AreaStoryByteMemory")
        start = RAM.index("    def observe(", at)
        cls.body = RAM[start:RAM.index("\n    def ", start + 10)]

    def test_a_write_in_the_air_is_not_a_mark(self) -> None:
        self.assertIn("self._write_outstanding", self.body)  # ADDENDUM 229

    def test_a_committed_write_of_ours_is_not_a_mark_either(self) -> None:
        self.assertIn("self.last_written_target", self.body)  # ADDENDA 275/277

    def test_a_byte_carried_in_from_elsewhere_is_not_a_mark(self) -> None:
        self.assertIn("self._last_observed_region", self.body)  # ADDENDUM 288

    def test_arriving_writes_exactly_the_value_that_would_have_self_credited(self) -> None:
        """Why the three guards above are the whole safety argument: for every destination, the value written
        on arrival IS the threshold its own check is gated on."""
        for name in travel_locations.TRAVEL_LOCATION_NAMES:
            threshold = travel_locations.vanilla_unlock_story_byte(name)
            if threshold is None:
                continue
            region = (travel_locations.TRAVEL_UNLOCK_STORY_REGION.get(name)
                      or travel_locations.TRAVEL_LOCATION_TARGET_REGION.get(name))
            self.assertEqual(story_bytes.area_unlock_floor(region), threshold, name)


class TestTheDiagnosticExists(unittest.TestCase):
    """The mitigation for this rule's one risk. A check held by a mark that never arrives has to be a row a
    player can read, not silence."""

    def test_the_command_is_there(self) -> None:
        self.assertIn("def _cmd_unlocks(self)", CLIENT)

    def test_it_prints_the_threshold_the_mark_and_a_verdict(self) -> None:
        body = CLIENT[CLIENT.index("def _cmd_unlocks(self)"):CLIENT.index("def _cmd_storybyte")]
        self.assertIn("_unlock_mark_for(ctx, name)", body)
        self.assertIn("_unlock_is_earned(ctx, name, threshold)", body)
        self.assertIn("HELD", body)
        self.assertIn("SENT", body)

    def test_it_says_so_when_the_seed_has_no_such_checks(self) -> None:
        body = CLIENT[CLIENT.index("def _cmd_unlocks(self)"):CLIENT.index("def _cmd_storybyte")]
        self.assertIn("if not ctx.randomize_travel_locations:", body)

    def test_it_reads_nothing_and_writes_nothing(self) -> None:
        """A diagnostic that could move the byte, or send a check, would be a worse bug than the one it is
        there to surface."""
        body = CLIENT[CLIENT.index("def _cmd_unlocks(self)"):CLIENT.index("def _cmd_storybyte")]
        for forbidden in ("poke_story_byte", "write_story_byte", "_send_checks", "check_locations"):
            self.assertNotIn(forbidden, body, forbidden)


class TestTheSupersededGateIsGone(unittest.TestCase):
    """Prose references survive on purpose -- the addendum trail is how this project explains itself. A
    definition or a call does not."""

    def test_no_definition_and_no_call(self) -> None:
        self.assertNotIn("def _story_byte_was_earned_here", CLIENT)
        self.assertNotIn("_story_byte_was_earned_here(", CLIENT)

    def test_the_trail_still_names_it(self) -> None:
        self.assertIn("_story_byte_was_earned_here", CLIENT)


class TestTheLocationsWereNeverInLogic(unittest.TestCase):
    """What the nine early sends actually cost. If these ever gain a real access rule, the claim in this
    addendum's docstring stops being true and this test is where that surfaces."""

    def test_every_unlock_location_is_a_real_location_name(self) -> None:
        from .. import locations

        for name in travel_locations.TRAVEL_LOCATION_NAMES:
            if travel_locations.vanilla_unlock_story_byte(name) is None:
                continue
            location_name = travel_locations.travel_unlock_location_name(name)
            self.assertIn(location_name, locations.LOCATION_TABLE, location_name)


if __name__ == "__main__":
    unittest.main()
