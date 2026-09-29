"""ADDENDUM 261 (2026-09-17). The `LocationInfo` reply does not hold dicts, and never did.

Player: "shop descriptions do not have the AP item that it's sending listed at all - the title is fine as
is, but can we modify the description to have what we're sending out listed?"

The title being fine is the clue that narrows it: `ItemNameRenamer` writes the shelf LABEL and was working,
so RAM writes, the room, the berry numbering and the shop tables were all fine. Only the half that needs the
SERVER's answer was dead.

ADDENDUM 239 read the reply as a list of dicts:

    name = ID_TO_LOCATION_NAME.get(entry["location"])
    player = entry.get("player")

`NetUtils.allowlist` contains `NetworkItem`, so the JSON decoder's object hook has already turned every entry
into a namedtuple by the time any client sees it -- which is why `CommonClient.process_server_cmd` does
`NetworkItem(*item)` over the very same list. Subscripting a namedtuple by string raises `TypeError` on the
FIRST entry, and one `try` around the whole loop threw away every entry after it too.

WHY IT WAS SILENT, which is the part worth keeping. The branch is wrapped -- correctly; a malformed cosmetic
packet must never take down a client that is also delivering items -- and its failure goes through
`_note_warn`, which ADDENDUM 181 deliberately puts behind `!verbose`. So the feature failed completely and
reported it nowhere the player would look, which is why it read as never built rather than broken.

WHY NO TEST CAUGHT IT. `Client.py` cannot be imported here (`CommonClient` -> `MultiServer` ->
`websockets.extensions`), so everything in it is checked by reading its source as text -- and the old code is
perfectly well-formed Python that a structural test passes without hesitation. A shape bug is precisely what
that kind of test cannot see. The fix moves the twelve lines that actually decide something into
`shop_scout.py`, which has no Archipelago imports and can therefore be handed the real namedtuple.

The lesson, recorded because it generalises past this bug: **a wrapped cosmetic failure still needs to be
legible somewhere the player will actually look.** `!shops` is that place now.
"""
from __future__ import annotations

import os
import pathlib
import unittest

from .. import shop_scout


try:  # the real thing, so this test is about the real shape and not a guess at it
    from NetUtils import NetworkItem
except ImportError:  # pragma: no cover - only if the Archipelago root is missing
    NetworkItem = None


_CLIENT_SOURCE = pathlib.Path(__file__).resolve().parent.parent / "Client.py"

# A small, self-contained world: two shop lines and one location that is not a shop line at all.
_NAMES = {
    2001: "Agate Village Shop AP Item 3",
    2002: "Gateon Port Shop AP Item 1",
    2003: "Defeat - Chobin",
}
_ITEMS = {77: "Rare Candy", 88: "Progressive Sword"}
_PLAYERS = {1: "dbg", 2: "Dovah"}


def _run(records, own_slot=1):
    return shop_scout.scouted_shop_items(
        records,
        _NAMES.get,
        lambda item_id, _player: _ITEMS.get(item_id, f"item {item_id}"),
        _PLAYERS.get,
        own_slot,
    )


class TestTheRealReplyShape(unittest.TestCase):

    @unittest.skipIf(NetworkItem is None, "Archipelago's NetUtils is not importable here")
    def test_a_namedtuple_reply_is_read(self) -> None:
        """THE BUG. This is the exact shape the decoder produces and the exact shape the old code raised on.

        `NetworkItem` is (item, location, player, flags), and in a `LocationInfo` reply `player` is the
        RECEIVING player -- see that field's own comment in NetUtils."""
        scouted, problems = _run([
            NetworkItem(77, 2001, 1, 0),      # ours
            NetworkItem(88, 2002, 2, 0),      # someone else's
        ])
        self.assertEqual([], problems)
        self.assertEqual({
            "Agate Village Shop AP Item 3": ("Rare Candy", None),
            "Gateon Port Shop AP Item 1": ("Progressive Sword", "Dovah"),
        }, scouted)

    @unittest.skipIf(NetworkItem is None, "Archipelago's NetUtils is not importable here")
    def test_the_old_dict_subscript_would_have_raised_on_this_very_record(self) -> None:
        """Pins the cause rather than only the symptom. If `NetworkItem` ever does become subscriptable by
        name, this test failing is the signal to come back and simplify, not a false alarm."""
        with self.assertRaises(TypeError):
            NetworkItem(77, 2001, 1, 0)["location"]  # type: ignore[index]

    def test_a_plain_list_reply_is_read_the_same_way(self) -> None:
        """What arrives if a future decoder stops applying the object hook. Same field order as
        `NetworkItem`, because that is what the server packs."""
        scouted, problems = _run([[77, 2001, 1, 0]])
        self.assertEqual([], problems)
        self.assertEqual(("Rare Candy", None), scouted["Agate Village Shop AP Item 3"])

    def test_a_dict_reply_is_still_read(self) -> None:
        """ADDENDUM 239's own assumption. Accepted rather than rejected -- the point is to stop CARING which
        of the three shapes turns up, not to swap one assumption for another."""
        scouted, problems = _run([{"item": 88, "location": 2002, "player": 2, "flags": 0}])
        self.assertEqual([], problems)
        self.assertEqual(("Progressive Sword", "Dovah"), scouted["Gateon Port Shop AP Item 1"])


class TestOneBadRecordDoesNotCostTheRest(unittest.TestCase):

    def test_a_broken_entry_is_reported_and_the_good_ones_survive(self) -> None:
        """The second half of the fix, and the one that would have made the original bug a one-line report
        instead of a silent hole. The old branch had a single `try` around the whole loop, so entry one
        failing discarded entries two through fifty-two AND left nothing to say about it."""
        scouted, problems = _run([
            object(),                              # no fields at all
            [77, 2001, 1, 0],                      # fine
            {"item": None, "location": 2002},      # no item id
        ])
        self.assertIn("Agate Village Shop AP Item 3", scouted)
        self.assertEqual(1, len(scouted))
        self.assertEqual(2, len(problems))
        self.assertTrue(any("Gateon Port Shop AP Item 1" in p for p in problems),
                        f"a problem must name the line it lost: {problems}")

    def test_a_non_shop_location_is_skipped_without_being_called_a_problem(self) -> None:
        """A scout reply can legitimately carry locations that are not shop lines. Those are not errors, and
        counting them as such would bury the real ones."""
        scouted, problems = _run([[77, 2003, 1, 0], [77, 999999, 1, 0]])
        self.assertEqual({}, scouted)
        self.assertEqual([], problems)


class TestAnItemForYourselfCarriesNoPlayerName(unittest.TestCase):

    def test_own_slot_yields_none(self) -> None:
        """Not cosmetic trivia: `describe_ap_item` spends its first line on the recipient when there is one,
        so a wrong answer here costs a third of the description for every line in the game."""
        scouted, _ = _run([[77, 2001, 4, 0]], own_slot=4)
        self.assertEqual(("Rare Candy", None), scouted["Agate Village Shop AP Item 3"])

    def test_another_slot_yields_their_name(self) -> None:
        scouted, _ = _run([[88, 2002, 2, 0]], own_slot=4)
        self.assertEqual(("Progressive Sword", "Dovah"), scouted["Gateon Port Shop AP Item 1"])


class TestTheClientWiring(unittest.TestCase):
    """Structural, against the source -- `Client.py` is not importable here, which is the whole reason the
    decision-making moved out of it."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.source = _CLIENT_SOURCE.read_text(encoding="utf-8")

    def test_the_branch_delegates_instead_of_parsing_inline(self) -> None:
        self.assertIn("shop_scout.scouted_shop_items(", self.source)

    def test_nothing_subscripts_a_scout_record_by_name_any_more(self) -> None:
        """The literal shape of the bug, fenced.

        Checked against CODE only, with comment lines stripped: this addendum's own explanation quotes the
        broken expressions verbatim a few lines above the fix, and a raw string search finds the explanation
        and reports it as the thing it warns about. (The same trap ADDENDUM 260's ordering test hit.)"""
        code = "\n".join(line for line in self.source.splitlines()
                         if not line.lstrip().startswith("#"))
        for forbidden in ('entry["location"]', 'entry["item"]', 'entry.get("player")'):
            self.assertNotIn(forbidden, code,
                             "a LocationInfo record is a NetworkItem, not a dict -- parse it through "
                             "shop_scout so the tests can see the shape")

    def test_a_failed_scout_is_reported_where_the_player_will_see_it(self) -> None:
        """`_note_warn` is `!verbose`-gated (ADDENDUM 181), which is correct for noise and wrong for "a
        feature you asked for is off". The empty-scout-with-problems case goes to `logger.warning`."""
        start = self.source.index('elif cmd == "LocationInfo":')
        body = self.source[start:self.source.index('elif cmd == "Connected":', start)]
        self.assertIn("logger.warning(", body)
        self.assertIn("elif problems:", body)

    def test_there_is_a_command_that_shows_the_whole_chain(self) -> None:
        """Four stages have to hold for a shelf line to name its AP item, and before this addendum none of
        them could be inspected. Every one is cosmetic, therefore wrapped, therefore quiet."""
        self.assertIn("def _cmd_shops(self)", self.source)
        start = self.source.index("def _cmd_shops(self)")
        body = self.source[start:self.source.index("\n    def ", start + 10)]
        for stage in ("scouted_shop_items", "item_name_renamer", "item_description_writer", "shop_tracker"):
            self.assertIn(stage, body, f"`!shops` must report the {stage} stage")

    def test_the_problem_list_is_initialised_so_the_command_cannot_raise(self) -> None:
        self.assertIn("self.shop_scout_problems", self.source)


if __name__ == "__main__":
    unittest.main()


class TestTheClassificationSidecar(unittest.TestCase):
    """ADDENDUM 261 also captures each line's item CLASS, because the scout reply is the only place a client
    can learn it -- nothing else tells it what class an item on another player's location belongs to.

    Recorded now rather than when pricing is built, for a specific reason: `flags` is already in the record
    being parsed, and the alternative is a second scout later. Read today only by `!shops`."""

    def test_progression_is_read_from_the_flags_bit(self) -> None:
        classes: "dict[str, str]" = {}
        _run([[77, 2001, 1, 0b001], [88, 2002, 2, 0b000]])  # without the sidecar: no crash, no capture
        _, problems = shop_scout.scouted_shop_items(
            [[77, 2001, 1, 0b001], [88, 2002, 2, 0b000]],
            _NAMES.get,
            lambda item_id, _p: _ITEMS.get(item_id, ""),
            _PLAYERS.get,
            1,
            classes,
        )
        self.assertEqual([], problems)
        self.assertEqual({"Agate Village Shop AP Item 3": "progression",
                          "Gateon Port Shop AP Item 1": "filler"}, classes)

    def test_every_class_maps(self) -> None:
        self.assertEqual("progression", shop_scout.classify(0b001))
        self.assertEqual("useful", shop_scout.classify(0b010))
        self.assertEqual("trap", shop_scout.classify(0b100))
        self.assertEqual("filler", shop_scout.classify(0))
        self.assertEqual("filler", shop_scout.classify(None))

    def test_progression_wins_when_several_bits_are_set(self) -> None:
        """A progression item that is also marked useful is progression. Getting this backwards would price
        the most important lines as if they were ordinary."""
        self.assertEqual("progression", shop_scout.classify(0b011))

    def test_the_sidecar_is_optional(self) -> None:
        """Nothing that exists today needs both answers, and the parser must stay usable without it."""
        scouted, problems = _run([[77, 2001, 1, 0b001]])
        self.assertEqual([], problems)
        self.assertIn("Agate Village Shop AP Item 3", scouted)
