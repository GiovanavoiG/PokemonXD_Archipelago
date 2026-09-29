"""ADDENDUM 268 (2026-09-17): the Kyogre value, and where a story byte has to be earned.

Three things, from one message: "0x77 is high enough for kyogre go ahead and wire that in. Also, the attached
checks are still firing too early if another area's story byte is high enough."

## 1. STORY_OVERRIDE_VALUE 0x6E -> 0x77, and why 0x6E was wrong

0x6E was **reasoned** from the transition ladder -- it is the value the byte lands on when Robo Kyogre
unlocks -- and it did not work in play. The lesson is one this project already wrote down and then did not
apply: *the ladder records what the byte READS AFTER an event, not what the game CHECKS to allow one.* Those
are different questions, and deriving a gate from an observation table answers the wrong one. Bisected live
over the bridge instead.

## 2. 0x77 and not higher, enforced at import

`story_byte_says_won` is `>= VICTORY_STORY_BYTE (0x78)`. An override at or above that would send the seed's
goal the instant a player holding eight Parts hovered Gateon -- irreversible, from a write this client made
on their behalf. 0x77 is the largest value that cannot. The two constants are forty lines apart, so the
relationship is asserted at import rather than left to a test: the failure is silent, instant and
unrecoverable.

(The same trap nearly caught this session's own bridge work: the request was to write 0x7A to test the ride,
which with the client connected would have finished the seed.)

## 3. A high number is not the same as having been there

ADDENDUM 265 stopped the client crediting `Unlock -` checks off a byte it had just written ON THE MAP. It
could not stop this, and said so at the time: **travelling somewhere COMMITS that destination's entry floor**,
because that is what the room is built from (ADDENDUM 177). After a real trip the save file genuinely holds
that value, so "did we write this?" no longer helps -- the byte is real now, and every lower threshold clears
at once. Reaching Citadark by item credited Phenac, Pyrite, Mt. Battle and the rest in one burst.

So the fix stops asking the byte alone, and adds the player's own second condition -- these checks should only
send *"if their byte is acquired in the area you'd usually unlock a new spot"*:

> Credit only while the player's own region sits at or BEFORE the threshold on the path.

In the unmodified game that is always true: the byte reaches a destination's unlock value during a story event
in an area up to that point. It is exactly false for the failure above -- standing in Citadark (floor 0x6E) is
not where Phenac's icon (0x3E) is earned.

**Deferred, never dropped**, which is what makes it safe to be strict. `enforce_travel_locks` runs every tick,
so a held check fires the moment the player is somewhere that qualifies.
"""
from __future__ import annotations

import pathlib
import re
import sys
import types
import unittest
from unittest import mock

if "dolphin_memory_engine" not in sys.modules:
    _stub = types.ModuleType("dolphin_memory_engine")
    _stub.hook = lambda: None
    _stub.un_hook = lambda: None
    _stub.is_hooked = lambda: False
    _stub.read_bytes = lambda address, length: b""
    _stub.write_bytes = lambda address, data: None
    sys.modules["dolphin_memory_engine"] = _stub

from .. import ram_client as rc
from ..game_data import story_bytes as sb
from .. import travel_locations
from ..game_data import chest_regions, story_bytes


class TestTheKyogreValue(unittest.TestCase):

    def test_it_is_the_rung_the_bisection_was_pointing_at(self) -> None:
        """ADDENDUM 350 moved this 0x77 -> 0x76, and the bisection is the evidence FOR the move.

        0x77 covers story values 952..959 and the game only holds multiples of ten, so it is not a rung --
        it is a window sitting above the last real rung below victory, which is why a byte-only write to it
        cleared the ride threshold from any starting save. The bisection's two results bound that threshold:
        0x77 rode, so it is at or below 952; 0x6E (880) did not, so it is above 880. The only value the game
        can hold in (880, 952] is 950, which is 0x76."""
        self.assertEqual(0x76, rc.STORY_OVERRIDE_VALUE)
        self.assertEqual(950, sb.story_value_for_byte(0x76))
        self.assertIsNone(sb.story_value_for_byte(0x77), "0x77 was never a state the game could be in")
        self.assertEqual(880, sb.story_value_for_byte(0x6E), "the value that did NOT ride")

    def test_it_can_never_send_the_seeds_goal(self) -> None:
        """THE ONE THAT MATTERS. An override at or above VICTORY_STORY_BYTE completes the seed for anyone
        holding eight Parts, the instant they hover Gateon."""
        self.assertLess(rc.STORY_OVERRIDE_VALUE, rc.VICTORY_STORY_BYTE)
        self.assertFalse(rc.STORY_OVERRIDE_VALUE >= rc.VICTORY_STORY_BYTE)

    def test_the_relationship_is_asserted_at_import_not_only_here(self) -> None:
        """A test only fails when someone runs it. This one is silent, instant and unrecoverable in play, and
        the two constants are forty lines apart -- so it is also an import-time assert."""
        source = pathlib.Path(rc.__file__).read_text(encoding="utf-8")
        self.assertIn("assert STORY_OVERRIDE_VALUE < VICTORY_STORY_BYTE", source)

    def test_it_is_still_a_plausible_story_byte(self) -> None:
        """0xFF worked too, and was rejected precisely because `read_story_byte` refuses it as implausible
        (ADDENDUM 168). A value the client's own reader will not accept is not a value to write."""
        self.assertLessEqual(rc.STORY_OVERRIDE_VALUE, rc.STORY_BYTE_MAX_PLAUSIBLE)


class TestWhereAByteCountsAsEarned(unittest.TestCase):
    """The gate itself, exercised through the real region and floor tables rather than a fixture -- the whole
    claim is about how those two relate."""

    def _floor(self, region: str) -> "int | None":
        return story_bytes.area_entry_floor(region)

    def _room_in(self, region: str) -> "int | None":
        for room, name in chest_regions.ROOM_TO_REGION.items():
            if name == region:
                return room
        return None

    def test_an_early_region_can_earn_a_later_threshold(self) -> None:
        """Legitimate play: the byte advances while the player stands somewhere up to that point."""
        pyrite = self._floor("Pyrite Town")
        spots = travel_locations.vanilla_unlock_story_byte("Cave Poke Spot") or \
            travel_locations.vanilla_unlock_story_byte("Poke Spots")
        self.assertIsNotNone(pyrite)
        self.assertIsNotNone(spots)
        self.assertLessEqual(pyrite, spots,
                             "Pyrite comes before the Poke Spots, so being there must be able to earn them")

    def test_a_late_region_cannot_earn_an_early_threshold(self) -> None:
        """THE BUG. Standing in Citadark is not where Phenac's icon is earned, however high the byte reads."""
        citadark = self._floor("Citadark Isle")
        phenac = self._floor("Phenac City")
        self.assertIsNotNone(citadark)
        self.assertIsNotNone(phenac)
        self.assertGreater(citadark, phenac,
                           "if these ever stop being ordered this way the rule stops meaning anything")

    def test_every_always_open_region_qualifies_for_everything(self) -> None:
        """No floor means the start of the path. A player standing in the HQ Lab with a genuinely high byte
        earned it by playing, and must not be held back."""
        for region in ("Pokemon HQ Lab", "Kaminko's House", "Gateon Port"):
            # RETARGETED by ADDENDUM 279. This asserted the three always-open regions had NO floor, and
            # `_story_byte_was_earned_here` reads `floor is None` as "credit anything" -- so they were
            # structurally exempt from ADDENDUM 268's guard, which the register logged as making it vacuous.
            # They have real floors now, so the guard actually bites there. This is that hole closing.
            self.assertIsNotNone(self._floor(region), region)

    def test_every_unlock_threshold_is_reachable_from_somewhere(self) -> None:
        """The safety check on the whole rule: if some destination's threshold were below EVERY region's
        floor, its check could never fire from anywhere and the clamp would have eaten a location."""
        floors = [f for f in (self._floor(r) for r in set(chest_regions.ROOM_TO_REGION.values()))
                  if f is not None]
        always_open = any(self._floor(r) is None for r in set(chest_regions.ROOM_TO_REGION.values()))
        for name in travel_locations.TRAVEL_LOCATION_NAMES:
            threshold = travel_locations.vanilla_unlock_story_byte(name)
            if threshold is None:
                continue
            self.assertTrue(always_open or any(f <= threshold for f in floors),
                            f"{name}: no region is early enough to ever earn 0x{threshold:02X}")


class TestTheClientGate(unittest.TestCase):
    """Structural -- `Client.py` is not importable here.

    RETARGETED 2026-09-25 (ADDENDUM 355). ADDENDUM 268's gate was `_story_byte_was_earned_here`, which asked
    whether the player's CURRENT region sits strictly before the threshold. That rule was one-sided: it stopped
    a LATE region crediting an EARLY unlock and did nothing about the reverse, and the reverse is what the
    player hit -- nine `Unlock -` checks fired on arrival at Gateon Port (floor 0x0F, at or before every
    threshold in the game) off a high-water honestly earned in the Snagem Hideout.

    The gate is now `_unlock_is_earned`, which asks about the DESTINATION rather than about where the player
    happens to stand: did the game move the byte to D's own threshold while the player was in D. 268's own
    finding -- "a high number is not the same as having been there" -- is what this still enforces, so the
    tests below are that finding re-expressed against the mark, not new claims."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = (pathlib.Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")
        cls.helper = cls._slice(cls.source, "def _unlock_is_earned")
        cls.mark = cls._slice(cls.source, "def _unlock_mark_for")

    @staticmethod
    def _slice(source: str, header: str) -> str:
        """The named function's own text.

        `re`, not `source.index("\ndef ")`: the definitions that follow are `async def`, and bounding on the
        plain form swallows them whole."""
        start = source.index(header)
        following = re.search(r"^(?:async )?def ", source[start + len(header):], re.M)
        assert following is not None, header
        return source[start:start + len(header) + following.start()]

    def test_the_credit_consults_it(self) -> None:
        self.assertIn("if not _unlock_is_earned(ctx, name, threshold):", self.source)
        # Prose references to the retired name survive on purpose (the addendum trail). A definition or a
        # call does not.
        self.assertNotIn("def _story_byte_was_earned_here", self.source)
        self.assertNotIn("_story_byte_was_earned_here(", self.source)

    def test_it_compares_a_mark_against_the_threshold(self) -> None:
        self.assertIn("mark >= threshold", self.helper)

    def test_the_mark_is_the_area_memory_high_water_and_nothing_else(self) -> None:
        """The whole safety argument rests on this ONE source: `observe()` banks only bytes the GAME moved,
        and only in the area the player was standing in (ADDENDA 229/275/277/288). A mark read from anywhere
        else would not carry that guarantee."""
        self.assertIn("ctx.area_story_memory.highest_by_region", self.mark)
        self.assertIn("unlock_witness_regions(destination)", self.mark)

    def test_no_mark_holds(self) -> None:
        """ADDENDUM 226/267's rule again: "ask again next poll", never "credit anyway". Somewhere the player
        has never played has no mark, and that is the ordinary state, not an error."""
        self.assertIn("mark is not None", self.helper)
        self.assertIn("return None", self.mark)

    def test_nothing_it_can_raise_ever_sends_a_check(self) -> None:
        """The read walks two structures that a mid-session reload can empty. Every failure has to answer
        "no mark", which holds the check, rather than propagating out of the poll loop."""
        self.assertIn("except Exception:", self.mark)
        self.assertIn("return None", self.mark[self.mark.index("except Exception:"):])
        self.assertNotIn("except Exception", self.helper[self.helper.index("mark = _unlock_mark_for"):],
                         "the helper needs no guard of its own -- the read it makes cannot raise")


class TestThePokeSpotWriteIsBounded(unittest.TestCase):
    """ADDENDUM 268, from a separate report: a Poke Spot Castform at LEVEL 0.

    That turned out not to be this -- the live tables read min>=10 in every slot, the assignment only ever
    names the eleven real ones, and every dex 1-386 round-trips through the species index cleanly. But the
    bound was genuinely absent, and it is the one bound that WOULD have explained it: a slot index past a
    pool's real count writes a species into whatever follows the table, and if that is zero padding the game
    reads a Pokemon with min/max level 0."""

    class _Rel:
        data = b"\x00" * 0x400

        def __init__(self, count: int = 3) -> None:
            self.count = count

        def get_pointer(self, index: int) -> int:
            return 0x100

        def get_value_at_pointer(self, index: int) -> int:
            return self.count

    def test_a_slot_the_pool_does_not_have_is_refused(self) -> None:
        from ..tools import xd_rel_format as rel_format

        buf = bytearray(0x400)
        with self.assertRaises(ValueError) as caught:
            rel_format.apply_pokespot_species(buf, self._Rel(count=3), {"rock:7": 385})
        self.assertIn("outside", str(caught.exception))
        self.assertEqual(bytearray(0x400), buf, "nothing may be written before the check fails")

    def test_a_real_slot_still_writes(self) -> None:
        from ..tools import xd_rel_format as rel_format

        buf = bytearray(0x400)
        self.assertEqual(1, rel_format.apply_pokespot_species(buf, self._Rel(count=3), {"rock:2": 385}))
        self.assertEqual(385, int.from_bytes(buf[0x100 + 2 * 0xC + 2:0x100 + 2 * 0xC + 4], "big"))

    def test_a_species_index_that_cannot_be_encoded_is_refused(self) -> None:
        from ..tools import xd_rel_format as rel_format

        for bad in (0, -1, 0x10000):
            with self.assertRaises(ValueError):
                rel_format.apply_pokespot_species(bytearray(0x400), self._Rel(), {"rock:0": bad})

    def test_every_assigned_slot_is_one_the_game_really_has(self) -> None:
        """The data side of the same statement. `assign_pokespot_species` works from the fixed eleven, so
        this holds today -- pinned so a future "add more spots" change has to face the bound above."""
        from ..game_data.pokespot_data import VANILLA_POKESPOT_SLOTS

        real = {"rock": 3, "oasis": 3, "cave": 3, "all": 2}
        for slot in VANILLA_POKESPOT_SLOTS:
            self.assertIn(slot.pool, real)
            self.assertLess(slot.slot_index, real[slot.pool], f"{slot.pool}:{slot.slot_index}")


if __name__ == "__main__":
    unittest.main()
