"""ADDENDUM 180 (2026-09-13): key items are reconciled every poll, not delivered once.

Player instruction: "Can we just continuously poll for key items and clear them if we shouldn't have them / write
them if we should have them and don't? I'd rather that than rely on the item delivery system."

They asked for the clearing half once before and it went unbuilt -- `key_items.POLLED_GAME_ITEM_IDS` had been
sitting unused since ADDENDUM 167 with their words in its comment. These tests cover BOTH directions, the
hand-off from give_items, and the one visible behaviour change (a used key item comes back).
"""
from __future__ import annotations

import unittest
from unittest import mock

from .. import items, ram_client as rc
from ..game_data import key_items


MACHINE_PART = 503
DATA_ROM = 505
ID_CARD = 506
MUSIC_DISC = 507
SYSTEM_LEVER = 508
MAYORS_NOTE = 509


class _FakeBag:
    """A pocket the reconciler can read and write, so both directions are exercised for real rather than by
    asserting on mock call lists. Quantities keyed by item id."""

    def __init__(self, contents: "dict[int, int] | None" = None) -> None:
        self.contents = dict(contents or {})
        self.writes: "list[int]" = []
        self.clears: "list[int]" = []

    def find_item_quantity(self, pocket_base: int, max_slots: int, item_id: int) -> int:
        return self.contents.get(item_id, 0)

    def give_item(self, pocket_base: int, item_id: int, quantity: int, max_slots: int) -> bool:
        self.contents[item_id] = self.contents.get(item_id, 0) + quantity
        self.writes.append(item_id)
        return True

    def clear_item(self, pocket_base: int, max_slots: int, item_id: int) -> bool:
        if self.contents.get(item_id, 0) <= 0:
            return False
        self.contents.pop(item_id, None)
        self.clears.append(item_id)
        return True


def _run(reconciler: "rc.KeyItemReconciler", bag: _FakeBag, should_have, managed, polls: int = 1):
    results = []
    with mock.patch.object(rc, "resolve_item_pocket", return_value=(0x1000, 20)), \
         mock.patch.object(rc, "find_item_quantity", side_effect=bag.find_item_quantity), \
         mock.patch.object(rc, "give_item", side_effect=bag.give_item), \
         mock.patch.object(rc, "clear_item", side_effect=bag.clear_item):
        for _ in range(polls):
            results.append(reconciler.poll(0, frozenset(should_have), frozenset(managed)))
    return results


class TestTheManagedSet(unittest.TestCase):
    def test_it_is_the_shuffled_pool_key_items(self) -> None:
        self.assertEqual(sorted(key_items.POLLED_GAME_ITEM_IDS),
                         [MACHINE_PART, DATA_ROM, ID_CARD, MUSIC_DISC, SYSTEM_LEVER, MAYORS_NOTE])

    def test_the_never_shuffled_items_are_excluded_by_the_data(self) -> None:
        """The Elevator Key stays in its vanilla chest and Gonzap's Key gates nothing, so neither is ever the
        reconciler's business -- excluded by KeyItem.shuffled/in_pool rather than by a condition in the client."""
        self.assertNotIn(501, key_items.POLLED_GAME_ITEM_IDS)   # Elevator Key
        self.assertNotIn(504, key_items.POLLED_GAME_ITEM_IDS)   # Gonzap's Key


class TestBothDirections(unittest.TestCase):
    def test_it_writes_an_owned_item_that_is_missing(self) -> None:
        bag = _FakeBag()
        reconciler = rc.KeyItemReconciler()
        (written, cleared), = _run(reconciler, bag, {DATA_ROM}, {DATA_ROM, MUSIC_DISC})
        self.assertEqual(written, (DATA_ROM,))
        self.assertEqual(cleared, ())
        self.assertEqual(bag.contents.get(DATA_ROM), 1)

    def test_it_clears_an_item_the_player_was_never_sent(self) -> None:
        """The gap that delivery structurally could not close: the game still hands out key items from NPC
        scripts, which ISO patching cannot dummy the way it can a chest (ADDENDUM 177)."""
        bag = _FakeBag({MACHINE_PART: 1})
        reconciler = rc.KeyItemReconciler()
        (written, cleared), = _run(reconciler, bag, set(), {MACHINE_PART})
        self.assertEqual(written, ())
        self.assertEqual(cleared, (MACHINE_PART,))
        self.assertNotIn(MACHINE_PART, bag.contents)

    def test_it_does_nothing_once_the_bag_agrees(self) -> None:
        """The whole point: a settled Bag costs one read per managed id and no writes at all."""
        bag = _FakeBag({DATA_ROM: 1})
        reconciler = rc.KeyItemReconciler()
        results = _run(reconciler, bag, {DATA_ROM}, {DATA_ROM, MUSIC_DISC}, polls=5)
        self.assertEqual(results, [((), ())] * 5)
        self.assertEqual(bag.writes, [])
        self.assertEqual(bag.clears, [])

    def test_it_never_touches_an_unmanaged_id(self) -> None:
        bag = _FakeBag({501: 1})   # the Elevator Key, sitting where the story left it
        reconciler = rc.KeyItemReconciler()
        _run(reconciler, bag, set(), {DATA_ROM})
        self.assertEqual(bag.contents.get(501), 1)


class TestItIsIdempotentAndSelfHealing(unittest.TestCase):
    def test_a_write_happens_once_not_every_poll(self) -> None:
        """A reconciler with no history would still not duplicate, because it checks before it writes."""
        bag = _FakeBag()
        reconciler = rc.KeyItemReconciler()
        _run(reconciler, bag, {SYSTEM_LEVER}, {SYSTEM_LEVER}, polls=6)
        self.assertEqual(bag.writes, [SYSTEM_LEVER])
        self.assertEqual(bag.contents[SYSTEM_LEVER], 1)

    def test_a_used_key_item_is_written_back(self) -> None:
        """The one visible behaviour change, and it follows straight from the instruction. ADDENDUM 134 confirmed
        the ID Card is consumed on use. For a gating item this is the safe direction -- Archipelago says the
        player owns it, and an item they own must not become the reason they are stuck -- but it does mean these
        stop behaving like consumables."""
        bag = _FakeBag({ID_CARD: 1})
        reconciler = rc.KeyItemReconciler()
        _run(reconciler, bag, {ID_CARD}, {ID_CARD})
        bag.contents.pop(ID_CARD)          # the player uses it
        (written, _cleared), = _run(reconciler, bag, {ID_CARD}, {ID_CARD})
        self.assertEqual(written, (ID_CARD,))
        self.assertEqual(bag.contents[ID_CARD], 1)

    def test_a_missed_poll_costs_nothing(self) -> None:
        """There is no queue to fall behind on: the state of the Bag IS the state of the feature."""
        bag = _FakeBag({MACHINE_PART: 1})
        reconciler = rc.KeyItemReconciler()
        # One poll that "never happened", then one that does -- same outcome as polling twice.
        (written, cleared), = _run(reconciler, bag, {DATA_ROM}, {MACHINE_PART, DATA_ROM})
        self.assertEqual(written, (DATA_ROM,))
        self.assertEqual(cleared, (MACHINE_PART,))


class TestItNeverGuessesAndNeverRaises(unittest.TestCase):
    def test_an_unresolvable_pocket_is_left_alone(self) -> None:
        reconciler = rc.KeyItemReconciler()
        with mock.patch.object(rc, "resolve_item_pocket", return_value=None):
            self.assertEqual(reconciler.poll(0, {DATA_ROM}, {DATA_ROM}), ((), ()))

    def test_a_failed_read_is_counted_not_acted_on(self) -> None:
        """A stale or failed read must not become a write: that is how a duplicate or a wrongly-cleared item
        would happen."""
        reconciler = rc.KeyItemReconciler()
        with mock.patch.object(rc, "resolve_item_pocket", return_value=(0x1000, 20)), \
             mock.patch.object(rc, "find_item_quantity", side_effect=RuntimeError("bad read")):
            self.assertEqual(reconciler.poll(0, {DATA_ROM}, {DATA_ROM}), ((), ()))
        self.assertEqual(reconciler.failures, 1)

    def test_a_failed_write_does_not_propagate(self) -> None:
        reconciler = rc.KeyItemReconciler()
        with mock.patch.object(rc, "resolve_item_pocket", return_value=(0x1000, 20)), \
             mock.patch.object(rc, "find_item_quantity", return_value=0), \
             mock.patch.object(rc, "give_item", side_effect=RuntimeError("bad write")):
            self.assertEqual(reconciler.poll(0, {DATA_ROM}, {DATA_ROM}), ((), ()))
        self.assertEqual(reconciler.failures, 1)

    def test_describe_says_so_when_the_feature_is_off(self) -> None:
        self.assertIn("off for this seed", rc.KeyItemReconciler().describe(set(), set())[0])


class TestTheClientWiring(unittest.TestCase):
    def setUp(self) -> None:
        import os

        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "Client.py")
        with open(path, encoding="utf-8") as handle:
            self.source = handle.read()

    def _body(self, signature: str) -> str:
        start = self.source.index(signature)
        end = self.source.index("\ndef ", start + 1)
        later = self.source.find("\nasync def ", start + 1)
        if later != -1:
            end = min(end, later)
        return self.source[start:end]

    def test_it_needs_key_item_shuffle(self) -> None:
        """With the option off the player is SUPPOSED to hold whatever the story hands them, so the whole feature
        is inert -- managed_key_item_ids returns an empty set and every caller short-circuits on it."""
        body = self._body("def managed_key_item_ids(")
        self.assertIn("if not ctx.key_item_shuffle:", body)
        self.assertIn("return frozenset()", body)

    def test_the_owned_set_is_derived_not_accumulated(self) -> None:
        """An incrementally-maintained set is a second copy of the truth that can drift. The received list is
        already authoritative and already replayed in full on reconnect."""
        body = self._body("def should_have_key_item_ids(")
        self.assertIn("for network_item in ctx.items_received:", body)
        self.assertIn("companion_game_item_ids", body)

    def test_a_packaged_item_contributes_both_ids(self) -> None:
        """ADDENDUM 179's Data ROM & ID Card must mark BOTH 505 and 506 as owned, or the reconciler would clear
        the half the packaged item delivered as a companion."""
        data = items.ITEM_TABLE[items.COMBINED_KEY_ITEM_NAME]
        self.assertEqual(data.game_item_id, DATA_ROM)
        self.assertIn(ID_CARD, data.companion_game_item_ids)
        self.assertIn(DATA_ROM, key_items.POLLED_GAME_ITEM_IDS)
        self.assertIn(ID_CARD, key_items.POLLED_GAME_ITEM_IDS)

    def test_give_items_hands_the_managed_ids_over(self) -> None:
        """Both writing would race: give_items' confirm streak reads a quantity the reconciler may have just
        written, and both would conclude they did it."""
        self.assertIn("managed_ids = managed_key_item_ids(ctx)", self.source)
        self.assertIn("if managed_ids and game_item_id in managed_ids:", self.source)

    def test_a_handed_over_item_is_marked_delivered_not_left_pending(self) -> None:
        """"Never block sending items" is the one rule this file does not bend -- leaving the index pending would
        park it in the received-items queue forever."""
        start = self.source.index("if managed_ids and game_item_id in managed_ids:")
        block = self.source[start:start + 900]
        self.assertIn("ctx.given_item_indices.add(idx)", block)
        self.assertIn("continue", block)

    def test_it_runs_inside_the_block_stability_gate(self) -> None:
        """The opposite of give_items, and deliberately so: a tick this sits out costs nothing because there is no
        queue, while reading a half-rewritten block WOULD be harmful -- a stale zero writes a duplicate and a
        stale non-zero clears an item the player legitimately owns."""
        gate = self.source.index("if block_is_stable:")
        call = self.source.index("await reconcile_key_items(ctx)")
        self.assertGreater(call, gate)
        # ADDENDUM 353: anchored on the END of the stability block, not on the `if _looks_ingame():`
        # sub-branch that used to close it -- that gate is gone from the main loop. Same property.
        self.assertLess(call, self.source.index("elif not ctx._block_churn_logged:", gate))

    def test_the_option_default_is_assumed_on_for_older_seeds(self) -> None:
        """KeyItemShuffle is a DefaultOnToggle, so a seed generated before the key reached slot_data had it ON.
        Defaulting to False would silently stop reconciling for exactly those seeds."""
        self.assertIn('slot_data.get("key_item_shuffle", True)', self.source)

    def test_there_is_a_readout(self) -> None:
        self.assertIn("def _cmd_keyitems(", self.source)


if __name__ == "__main__":
    unittest.main()
