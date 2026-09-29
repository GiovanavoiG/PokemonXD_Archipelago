"""ADDENDUM 356 (2026-09-25): an icon is earned in the area BEFORE the place it opens.

Player, reading back ADDENDUM 355: "What do you mean real access rule? They should be logically gated behind
the area before them - that's where they're unlocked. Is that the case?" And, in the same message: "remove
Travel Unlock - Kaminko's from the pool."

## 1. Where an unlock is earned

ADDENDUM 355 asked for the story mark in the DESTINATION itself. That fixed the reported failure -- an early
region crediting every later unlock, nine at once on arrival at Gateon Port -- but fixed it the wrong way
round. You finish the Cipher Lab and PYRITE'S icon appears; you finish Phenac and REALGAM'S does. Nobody has
ever unlocked a destination by standing in it.

And the cost of getting it backwards was concrete: with the witness set to D, every `Unlock - D` check had to
wait for `Travel Unlock - D`, because D is unreachable without it. That is ADDENDUM 270's self-credit deferred
by one story beat rather than prevented.

THE PREDECESSOR ANSWERS BOTH. It is where the byte really moves, and it is never D -- so D's own item cannot
pay out D's own check, and the check is earnable by playing the game rather than by receiving the item.

DERIVED, NOT LISTED: the area group whose `area_unlock_floor` is the largest value strictly below D's
threshold. One line of arithmetic over the function that produces the threshold in the first place (the
identity ADDENDUM 270 pinned), so there is no second table to drift. What it resolves to reads as the game
plays -- Agate -> Cipher Lab/Mt. Battle, Cipher Lab -> Pyrite, Pyrite -> Poke Spots, Poke Spots -> Phenac,
Phenac -> Realgam/Orre, Realgam -> SS Libra, SS Libra -> Cipher Key Lair, Key Lair -> Outskirt/Snagem.

## 2. The AP graph says it too

The eleven `Unlock -` checks used to sit in a synthetic "Travel Unlocks" region wired straight off Menu with
no rule. Harmless -- they are unconditionally EXCLUDED, so no progression can land on one -- but it made every
one of them read as sphere zero in the spoiler log while the client held them for real play.

They are now filed in the region each one is earned in, the same move ADDENDUM 174 made for chests and 176
for shop lines: the region IS the logic. The bucket is gone rather than merely unused, which is what makes it
immune to the orphaned-bucket regression both of those left comments about.

## 3. Travel Unlock - Kaminko's House is retired

ADDENDUM 270 found it and left the call to the player: Kaminko's House is one of the four always-open areas,
so it sat in `TRAVEL_CLEAR_EXEMPT` (never re-locked by the client) and out of `gateway_only_regions()` (chain
edge never suppressed). A progression item for a region that was already reachable without it -- "filler
wearing a key item's name". Eleven travel items now, not twelve. Frozen id 249 is retired, not reused,
exactly like 239 (Gateon Port) and the three per-spot ids ADDENDUM 177 merged.
"""
from __future__ import annotations

import pathlib
import re
import unittest

from .. import items, locations, travel_locations
from ..game_data import story_bytes


ROOT = pathlib.Path(__file__).resolve().parent.parent
CLIENT = (ROOT / "Client.py").read_text(encoding="utf-8")


def _function(source: str, header: str) -> str:
    start = source.index(header)
    following = re.search(r"^(?:async )?def ", source[start + len(header):], re.M)
    assert following is not None, header
    return source[start:start + len(header) + following.start()]


def _code(body: str) -> str:
    """The function with its docstrings stripped -- these prose blocks quote the rules they replaced."""
    return re.sub(r'""".*?"""', "", body, flags=re.S)


class TestThePredecessorLadder(unittest.TestCase):
    """The derivation, stated as the table it produces. If the story floors ever move, this is where it shows
    -- which is the point of deriving it rather than writing it down twice."""

    EXPECTED = {
        "Cipher Lab": "Agate Village",
        "Mt. Battle": "Agate Village",
        "Pyrite Town": "Cipher Lab",
        "Poke Spots": "Pyrite Town",
        "Phenac City": "Poke Spots",
        "Realgam Tower": "Phenac City",
        "Orre Colosseum": "Phenac City",
        "SS Libra": "Realgam Tower",
        "Cipher Key Lair": "SS Libra (stranded)",
        "Snagem Hideout": "Cipher Key Lair (exterior)",
        "Outskirt Stand": "Cipher Key Lair (exterior)",
    }

    def test_the_ladder_is_what_we_think_it_is(self) -> None:
        derived = {name: travel_locations.unlock_predecessor_region(name)
                   for name in travel_locations.TRAVEL_LOCATION_NAMES
                   if travel_locations.vanilla_unlock_story_byte(name) is not None}
        self.assertEqual(self.EXPECTED, derived)

    def test_every_predecessor_sits_strictly_below_the_threshold(self) -> None:
        """The property the derivation is built on, asserted rather than assumed: the area you earn D's icon
        in is EARLIER than D. A predecessor at or above the threshold would mean the ladder disagrees with
        itself."""
        for name, region in self.EXPECTED.items():
            threshold = travel_locations.vanilla_unlock_story_byte(name)
            floor = story_bytes.area_unlock_floor(region)
            self.assertIsNotNone(floor, region)
            self.assertLess(floor, threshold, f"{name} <- {region}")

    def test_no_destination_is_its_own_witness(self) -> None:
        """ADDENDUM 270's finding, as an invariant over the whole table rather than a fact about one rule.
        This is also fenced at import in travel_locations, so a future edit fails loudly rather than here."""
        for name in travel_locations.TRAVEL_LOCATION_NAMES:
            if travel_locations.vanilla_unlock_story_byte(name) is None:
                continue
            own = (travel_locations.TRAVEL_UNLOCK_STORY_REGION.get(name)
                   or travel_locations.TRAVEL_LOCATION_TARGET_REGION.get(name))
            self.assertNotIn(own, travel_locations.unlock_witness_regions(name), name)

    def test_the_witness_is_the_predecessors_whole_group(self) -> None:
        """A destination's icon can be earned in any tier of the area below it -- Pyrite's ONBS interior is
        still Pyrite. Watching only the entry tier would hold a check earned indoors."""
        self.assertEqual(set(story_bytes.AREA_GROUPS["Pyrite Town"]),
                         set(travel_locations.unlock_witness_regions("Poke Spots")))

    def test_the_entry_tier_is_the_groups_first_member(self) -> None:
        """What `unlock_predecessor_region` returns, and the assumption behind it: AREA_GROUPS lists each
        group entry-first. If that convention ever breaks, the location gets filed in an interior tier and
        the access rule gets tighter than the client's credit rule without anything saying so."""
        for name, region in self.EXPECTED.items():
            self.assertEqual(region, travel_locations.unlock_witness_regions(name)[0], name)

    def test_an_unknown_name_answers_empty_rather_than_raising(self) -> None:
        self.assertEqual((), travel_locations.unlock_witness_regions("Not A Place"))
        self.assertEqual("", travel_locations.unlock_predecessor_region("Not A Place"))


class TestTheClientCreditsFromThePredecessor(unittest.TestCase):
    """Structural -- `Client.py` is not importable here."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.gate = _function(CLIENT, "def _unlock_is_earned")
        cls.mark = _function(CLIENT, "def _unlock_mark_for")

    def test_the_mark_is_read_through_the_witness_regions(self) -> None:
        code = _code(self.mark)
        self.assertIn("unlock_witness_regions(destination)", code)
        self.assertIn("ctx.area_story_memory.highest_by_region", code)

    def test_the_comparison_is_unchanged(self) -> None:
        """ADDENDUM 356 moved WHERE the mark comes from. It did not loosen what counts as earned."""
        self.assertIn("mark is not None and mark >= threshold", _code(self.gate))

    def test_the_diagnostic_names_the_area_being_waited_on(self) -> None:
        """A held check has to say what it is held on. "No progress recorded there yet" needs a "there"."""
        body = CLIENT[CLIENT.index("def _cmd_unlocks(self)"):CLIENT.index("def _cmd_storybyte")]
        self.assertIn("unlock_predecessor_region(name)", body)
        self.assertIn("earned_in", body)


class TestTheGraphAgreesWithTheClient(unittest.TestCase):
    """One fact, one shape. The region a check is filed under and the region whose mark credits it are the
    same place -- if these ever diverge, AP's spheres and the client's behaviour are telling two stories."""

    def test_every_unlock_location_is_filed_in_its_predecessor(self) -> None:
        for location_name in locations.TRAVEL_UNLOCK_LOCATION_NAMES:
            destination = location_name[len(travel_locations.TRAVEL_UNLOCK_LOCATION_PREFIX):]
            expected = travel_locations.unlock_predecessor_region(destination)
            holding = [region for region, names in locations.LOCATIONS_BY_REGION.items()
                       if location_name in names]
            self.assertEqual([expected], holding, location_name)

    def test_the_bucket_region_is_gone(self) -> None:
        """Not merely unused. A bucket created in locations.py and never connected in regions.py is silently
        unreachable, which is the regression "Chest Opening" and "Shop Purchases" both left notes about."""
        self.assertNotIn("Travel Unlocks", locations.LOCATIONS_BY_REGION)
        for path in ("regions.py", "rules.py"):
            source = (ROOT / path).read_text(encoding="utf-8")
            live = [line for line in source.splitlines()
                    if '"Travel Unlocks"' in line and not line.lstrip().startswith("#")]
            self.assertEqual([], live, f"{path} still references the retired bucket in live code")

    def test_they_stay_filler_only(self) -> None:
        """Filing them in real regions is about the graph telling the truth, NOT about opening them to
        progression. These fire off a story-byte watch and a seed with travel shuffle off never fires them at
        all -- the same reason every other live-detected category here is EXCLUDED."""
        source = (ROOT / "locations.py").read_text(encoding="utf-8")
        self.assertIn("if is_travel_unlock:\n                location.progress_type = "
                      "LocationProgressType.EXCLUDED", source)


class TestKaminkoIsRetired(unittest.TestCase):
    """ADDENDUM 270 found it; the player made the call. An always-open region behind a progression item."""

    NAME = "Travel Unlock - Kaminko's House"

    def test_it_is_not_an_item_any_more(self) -> None:
        self.assertNotIn(self.NAME, items.ITEM_TABLE)
        self.assertNotIn(self.NAME, items.TRAVEL_UNLOCK_ITEMS)

    def test_its_id_is_a_tombstone_not_a_reuse(self) -> None:
        """The whole point of the frozen table: an id, once shipped, means the same item forever. 239
        (Gateon Port) and 242/245/248 (the merged Poke Spots) are the precedent."""
        self.assertEqual(249, items._FROZEN_ITEM_OFFSETS[self.NAME])
        live = {offset for name, offset in items._FROZEN_ITEM_OFFSETS.items() if name in items.ITEM_TABLE}
        self.assertNotIn(249, live)

    def test_the_destination_is_gone_from_both_tables(self) -> None:
        """The bit table drives the item; the target-region table drives the gateway. Leaving it in the
        second would have built an entrance behind an item that no longer exists."""
        self.assertNotIn("Kaminko's House", travel_locations.TRAVEL_LOCATION_BITS)
        self.assertNotIn("Kaminko's House", travel_locations.TRAVEL_LOCATION_TARGET_REGION)
        self.assertNotIn("Kaminko's House", travel_locations.TRAVEL_LOCATION_NAMES)

    def test_it_never_had_a_check_to_lose(self) -> None:
        """No `Unlock - Kaminko's House` ever existed: ADDENDUM 279 scoped `vanilla_unlock_story_byte` so an
        always-open area gets no threshold. So retiring the item costs the player no check."""
        self.assertIsNone(travel_locations.vanilla_unlock_story_byte("Kaminko's House"))
        self.assertNotIn(travel_locations.travel_unlock_location_name("Kaminko's House"),
                         locations.LOCATION_TABLE)

    def test_the_count_is_eleven_and_the_option_says_so(self) -> None:
        """The register's standing complaint: the docstring said 14 and was never right. A player fills in a
        YAML from that text."""
        from .. import options

        self.assertEqual(11, len(travel_locations.TRAVEL_LOCATION_NAMES))
        self.assertEqual(11, len(items.TRAVEL_UNLOCK_ITEMS))
        doc = options.RandomizeTravelLocations.__doc__ or ""
        # 2026-09-26: the player rewrote this option's text; the phrase moved to "11 of this game's travel
        # destinations". The COUNT is what this test is about, so it is asserted as a number beside the names.
        self.assertIn("11 of this game's", doc)
        for name in travel_locations.TRAVEL_LOCATION_NAMES:
            self.assertIn(name.replace("Cipher Key Lair", "Cipher Key Lair"), doc, name)
        for name in travel_locations.TRAVEL_LOCATION_NAMES:
            self.assertIn(name, doc, f"{name} missing from the option's own list")

    def test_the_exempt_set_is_empty_rather_than_a_tombstone(self) -> None:
        """A retired name parked in here would silently exempt the destination if anyone put it back in the
        bit table -- the opposite of what retiring it meant."""
        self.assertEqual(frozenset(), travel_locations.TRAVEL_CLEAR_EXEMPT)


if __name__ == "__main__":
    unittest.main()
