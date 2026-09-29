"""ADDENDUM 283 (2026-09-19) -- a description nobody can encode is a description nobody sees.

Player, mid-playtest: "the shop prices work, but now the descriptions are not showing AP items."

They were being written. They were being SKIPPED, silently, and for the most ordinary reason in this module:
the payload did not fit the entry. `encode_lines` returns None over budget, `_write` treats None as "leave
this entry alone" and -- correctly, for its own purposes -- does NOT record it in `_written`, so every tick
retried, every tick measured over budget, and every tick gave up. The shelf kept its vanilla berry text.

The two constants were the only description text in the project that never met a budget. Everything composed
goes through `describe_ap_item` -> `wrap_description` -> `fit_lines`, all of which take `budget` and honour
it. `UNKNOWN_DESCRIPTION_LINES` and `NO_CHECK_DESCRIPTION_LINES` were handed to `encode_lines` raw.

So this file fences the class of bug, not the instance:
  * every constant line-list in the module fits the SMALLEST entry in the whole table, natively;
  * the writer's fallback paths still run them through `fit_lines`, so a future edit that overruns degrades
    to an ellipsis rather than to silence;
  * and both fallbacks actually produce bytes through the real encoder at every berry's real budget.
"""
import unittest

from .. import ram_client
from ..game_data import item_descriptions as D
from ..items import USELESS_BERRY_IDS

#: Every constant list-of-lines the module exposes. A new one added without a budget will fail here.
CONSTANT_LINE_LISTS = {
    name: value for name, value in vars(D).items()
    if name.isupper() and isinstance(value, list) and value and all(isinstance(x, str) for x in value)
}


class TestTheConstantsFitNatively(unittest.TestCase):
    def test_the_module_exposes_the_two_fallbacks(self) -> None:
        """Guards the census below: if these are renamed, the sweep silently checks nothing."""
        self.assertIn("UNKNOWN_DESCRIPTION_LINES", CONSTANT_LINE_LISTS)
        self.assertIn("NO_CHECK_DESCRIPTION_LINES", CONSTANT_LINE_LISTS)

    def test_the_smallest_budget_is_the_smallest_budget(self) -> None:
        self.assertEqual(D.SMALLEST_DESCRIPTION_BUDGET,
                         min(entry[1] for entry in D.ITEM_DESCRIPTION_ENTRIES.values()))
        self.assertLessEqual(D.SMALLEST_DESCRIPTION_BUDGET, D.SHOP_BERRY_DESCRIPTION_BUDGET)

    def test_every_constant_fits_the_smallest_entry_in_the_table(self) -> None:
        """THE BUG, measured. Before this addendum the two fallbacks were 104 and 92 bytes against 86."""
        for name, lines in CONSTANT_LINE_LISTS.items():
            with self.subTest(name):
                self.assertLessEqual(D.encoded_size(lines), D.SMALLEST_DESCRIPTION_BUDGET,
                                     f"{name} = {lines} cannot be encoded into the smallest entry")

    def test_every_constant_survives_the_encoder_at_every_berry_budget(self) -> None:
        """`fit_lines` is a fence, not a fix: a constant that only fits because something trimmed it has
        already lost a line nobody chose to lose. These must encode untouched."""
        for name, lines in CONSTANT_LINE_LISTS.items():
            for item_id in USELESS_BERRY_IDS:
                budget = D.budget_bytes(item_id)
                if budget is None:
                    continue
                with self.subTest(name=name, item_id=item_id):
                    self.assertEqual(D.fit_lines(list(lines), budget), list(lines), "fit_lines had to trim")
                    payload = D.encode_lines(lines, budget)
                    self.assertIsNotNone(payload, f"{name} does not encode at {budget} bytes")
                    self.assertEqual(len(payload), budget)


class TestTheWriterActuallyProducesThem(unittest.TestCase):
    """End to end through `desired_lines`, which is where the raw constants were used."""

    def setUp(self) -> None:
        self.writer = ram_client.ItemDescriptionWriter()
        self.berries = list(USELESS_BERRY_IDS)
        self.gateon = 156

    def _lines(self, scouted=None, purchased=frozenset()):
        return self.writer.desired_lines(self.gateon, self.berries, scouted or {}, set(purchased))

    def test_an_unscouted_shelf_encodes(self) -> None:
        lines = self._lines()
        self.assertTrue(lines)
        for item_id, value in lines.items():
            self.assertEqual(value, D.UNKNOWN_DESCRIPTION_LINES)
            self.assertIsNotNone(D.encode_lines(value, D.budget_bytes(item_id)))

    def test_a_bought_shelf_encodes(self) -> None:
        scouted = {f"Gateon Port Shop AP Item {n}": ("Progressive Sword", None) for n in range(1, 16)}
        lines = self._lines(scouted, purchased=set(self.berries))
        self.assertTrue(lines)
        for item_id, value in lines.items():
            self.assertEqual(value, D.NO_CHECK_DESCRIPTION_LINES)
            self.assertIsNotNone(D.encode_lines(value, D.budget_bytes(item_id)))

    def test_the_fallbacks_are_still_routed_through_the_budget(self) -> None:
        """The belt-and-braces half. Shrink the budget under the constant and the writer must still hand back
        something encodable -- trimmed and marked -- rather than a payload that cannot be written."""
        item_id = self.berries[0]
        tiny = 40
        fitted = D.fit_lines(list(D.UNKNOWN_DESCRIPTION_LINES), tiny)
        self.assertLessEqual(D.encoded_size(fitted), tiny)
        self.assertIsNotNone(D.encode_lines(fitted, tiny))
        self.assertTrue(fitted[-1].endswith(D.ELLIPSIS), "a trimmed line must be marked as trimmed")
        self.assertIsNotNone(item_id)


class TestEveryProducedPayloadIsWritable(unittest.TestCase):
    """The general statement of the bug: whatever `desired_lines` returns, `_write` must be able to write."""

    def setUp(self) -> None:
        self.writer = ram_client.ItemDescriptionWriter()
        self.berries = list(USELESS_BERRY_IDS)

    def test_across_every_shop_and_every_scout_state(self) -> None:
        from ..game_data import shops
        states = (
            ({}, frozenset()),
            ({}, frozenset(self.berries)),
            ({f"{name} AP Item {n}": ("Bottle of Extremely Fancy Water", "Bobbington")
              for name in [s.name for s in shops.SHOPS_BY_ROOM.values()] for n in range(1, 21)}, frozenset()),
        )
        seen = 0
        for room_id in shops.SHOPS_BY_ROOM:
            for scouted, purchased in states:
                lines = self.writer.desired_lines(room_id, self.berries, scouted, set(purchased))
                for item_id, value in lines.items():
                    seen += 1
                    budget = D.budget_bytes(item_id)
                    self.assertIsNotNone(D.encode_lines(value, budget),
                                         f"room {room_id} item {item_id}: {value} will never be written")
        self.assertGreater(seen, 0)


if __name__ == "__main__":
    unittest.main()
