"""ADDENDUM 179 (2026-09-13): the Data ROM and ID Card ship as one item.

Player instruction: "Can we package receiving the ID Card and the Data Rom as one item? This stops softlocks."

The softlock is real rather than a logic nicety: the Data ROM is what lets the player LEAVE the Cipher Lab, and
the ID Card opens doors inside it, so holding one without the other can strand them in a room with no other exit.
Archipelago's logic would call that fine, because logic reasons about what is REACHABLE, never about what is
escapable. One item makes the bad state unreachable by construction.
"""
from __future__ import annotations

import unittest
from unittest import mock

from . import PokemonXDTestBase
from .. import items, ram_client as rc, regions, rules
from ..game_data import chest_regions, key_item_chests, trainer_placements


class TestTheCombinedItem(unittest.TestCase):
    def test_it_delivers_both_game_item_ids(self) -> None:
        """505 is the Data ROM and 506 the ID Card, both confirmed live (the ID Card in ADDENDUM 134)."""
        data = items.ITEM_TABLE[items.COMBINED_KEY_ITEM_NAME]
        self.assertEqual(data.game_item_id, 505)
        self.assertEqual(data.companion_game_item_ids, (506,))
        self.assertEqual(data.quantity, 1)

    def test_it_is_named_for_what_it_is(self) -> None:
        """Rather than something invented like "Cipher Lab Key Set" -- a player reading their received-items list
        should know exactly which two game items they now hold."""
        self.assertEqual(items.COMBINED_KEY_ITEM_NAME, "Data ROM & ID Card")

    def test_it_is_progression_and_must_be_placed_reachably(self) -> None:
        from BaseClasses import ItemClassification

        self.assertEqual(items.ITEM_TABLE[items.COMBINED_KEY_ITEM_NAME].classification,
                         ItemClassification.progression)
        self.assertIn(items.COMBINED_KEY_ITEM_NAME, items.GATING_KEY_ITEM_NAMES)

    def test_the_companion_field_is_declared_last(self) -> None:
        """Every _table/_bundle_table/_freeze_offsets construction in items.py is positional, so a new field
        inserted anywhere earlier would silently reinterpret `quantity` as this one. Pinned because that is a
        mistake that would look like working code."""
        import dataclasses

        names = [f.name for f in dataclasses.fields(items.ItemData)]
        self.assertEqual(names[-1], "companion_game_item_ids")
        self.assertLess(names.index("quantity"), names.index("companion_game_item_ids"))

    def test_the_freeze_carries_the_companion_ids_through(self) -> None:
        """`_freeze_offsets` rebuilds every ItemData field by field, so a new field is dropped unless it is added
        there -- which would have made the packaged item deliver only the Data ROM and quietly reintroduce the
        exact softlock it exists to prevent. ITEM_TABLE is the POST-freeze table, so reading it proves the
        passthrough."""
        self.assertEqual(items.ITEM_TABLE[items.COMBINED_KEY_ITEM_NAME].companion_game_item_ids, (506,))

    def test_nothing_else_has_companions(self) -> None:
        extras = {n for n, d in items.ITEM_TABLE.items() if d.companion_game_item_ids}
        self.assertEqual(extras, {items.COMBINED_KEY_ITEM_NAME})


class TestTheOriginalsAreOutOfThePoolNotGone(unittest.TestCase):
    def test_both_are_removed_from_the_pool(self) -> None:
        for name in items.COMBINED_KEY_ITEM_PARTS:
            self.assertIn(name, items.ITEMS_REMOVED_FROM_POOL, name)
            self.assertNotIn(name, items.GATING_KEY_ITEM_NAMES, name)

    def test_both_keep_their_item_ids(self) -> None:
        """They stay in ITEM_TABLE because ITEM_ID_TO_NAME still has to resolve them for any seed generated
        before today, and reusing their offsets would make an old seed's Data ROM arrive as something else."""
        self.assertEqual(items.ITEM_TABLE["Data ROM"].id_offset, 13)
        self.assertEqual(items.ITEM_TABLE["ID Card"].id_offset, 19)

    def test_the_translation_helper_covers_exactly_the_two(self) -> None:
        self.assertEqual(items.requirement_to_pool_item("Data ROM"), items.COMBINED_KEY_ITEM_NAME)
        self.assertEqual(items.requirement_to_pool_item("ID Card"), items.COMBINED_KEY_ITEM_NAME)
        for other in ("Music Disc", "Machine Part", "System Lever", "Mayor's Note", "Elevator Key"):
            self.assertEqual(items.requirement_to_pool_item(other), other)


class TestTheDataTablesStillDescribeTheGame(unittest.TestCase):
    """The point of translating at rule-build time rather than rewriting the tables: every table keeps saying
    what the GAME requires, which stays true, and exactly one place knows about the packaging."""

    def test_the_region_edges_still_name_the_data_rom(self) -> None:
        named = {name for _src, _dst, required in regions.REGION_EDGES for name in required}
        self.assertIn("Data ROM", named)
        self.assertNotIn(items.COMBINED_KEY_ITEM_NAME, named)

    def test_the_chest_gate_still_names_the_id_card(self) -> None:
        self.assertEqual(chest_regions.CHEST_ITEM_GATES[27], ("ID Card",))

    def test_the_trainer_census_still_names_both(self) -> None:
        named = {n for p in trainer_placements.PLACEMENTS.values() for n in p.required_items}
        self.assertIn("Data ROM", named)
        self.assertIn("ID Card", named)

    def test_the_chest_table_still_records_what_each_chest_holds(self) -> None:
        self.assertEqual(key_item_chests.SHUFFLED_KEY_ITEM_CHESTS[17], "Data ROM")
        self.assertEqual(key_item_chests.SHUFFLED_KEY_ITEM_CHESTS[18], "ID Card")


class TestOneItemOpensEverythingBothUsedTo(PokemonXDTestBase):
    options = {"randomize_chests": True, "key_item_shuffle": True, "shuffle_trainer_defeats": True,
               "trainer_defeat_mode": 1}

    def test_it_opens_the_data_rom_regions(self) -> None:
        """The Poke Spots were behind the Data ROM, and still are.

        NARROWED 2026-09-16 (ADDENDUM 240): plain Pyrite Town no longer is. The ROM requirement moved off the
        edge INTO Pyrite Town and stayed on the edge out of it, so the town opens with the story chain and
        everything past it -- the Poke Spots, Pyrite Town (ONBS), and every Cipher battle filed there -- still
        needs the item. The Poke Spots assertion below is the one that was really testing this feature."""
        self.collect_key_item_chain(1)   # the Machine Part
        self.assertTrue(self.multiworld.state.can_reach("Pyrite Town", player=self.player))
        self.assertFalse(self.multiworld.state.can_reach("Poke Spots", player=self.player))
        self.assertFalse(self.multiworld.state.can_reach("Pyrite Town (ONBS)", player=self.player))
        self.collect_by_name(items.COMBINED_KEY_ITEM_NAME)
        self.assertTrue(self.multiworld.state.can_reach("Poke Spots", player=self.player))
        self.assertTrue(self.multiworld.state.can_reach("Pyrite Town (ONBS)", player=self.player))

    def test_the_same_one_item_opens_the_id_card_chest(self) -> None:
        """Chest 27 was behind the ID Card. One item now satisfies both gates, which is the whole feature."""
        from .. import locations

        name = locations.CHEST_ID_TO_LOCATION[27]
        self.collect_key_item_chain(1)
        self.assertFalse(self.can_reach_location(name))
        self.collect_by_name(items.COMBINED_KEY_ITEM_NAME)
        self.assertTrue(self.can_reach_location(name))

    def test_a_trainer_behind_both_needs_only_the_one_item(self) -> None:
        """The census has a row reading "Behind Data Rom and ID Card". After the packaging that is one
        requirement, not two, and the rule must have deduped rather than asking for the same item twice."""
        from ..game_data import trainer_roster

        both = [i for i, p in trainer_placements.PLACEMENTS.items()
                if set(p.required_items) >= {"Data ROM", "ID Card"}]
        self.assertTrue(both, "expected a census row requiring both")
        name = trainer_roster.trainer_label(trainer_roster.TRAINERS_BY_INDEX[both[0]])
        self.collect_key_item_chain()
        self.assertTrue(self.can_reach_location(name))

    def test_exactly_one_copy_is_in_the_pool(self) -> None:
        """Two items became one, so the pool holds one -- and neither original is in it."""
        pool = [item.name for item in self.multiworld.itempool]
        self.assertEqual(pool.count(items.COMBINED_KEY_ITEM_NAME), 1)
        for part in items.COMBINED_KEY_ITEM_PARTS:
            self.assertNotIn(part, pool)


class TestWithKeyItemShuffleOff(PokemonXDTestBase):
    options = {"randomize_chests": True, "key_item_shuffle": False}

    def test_the_packaged_item_is_not_in_the_pool(self) -> None:
        """With the option off the key items sit in their vanilla chests, and ADDENDUM 168's rule applies: a rule
        naming an item that never enters the pool makes its location unreachable forever."""
        pool = [item.name for item in self.multiworld.itempool]
        self.assertNotIn(items.COMBINED_KEY_ITEM_NAME, pool)

    def test_the_gates_do_not_name_an_item_that_was_never_created(self) -> None:
        """ADDENDUM 168's rule, and the thing most likely to break when an item leaves the pool: `all_state` never
        holds an uncreated item, so a rule naming one makes its location unreachable FOREVER -- silently, on a
        location. With key_item_shuffle off the packaged item does not exist, so chest 27's gate must have been
        filtered away entirely rather than pointing at it."""
        from .. import locations

        self.assertTrue(self.can_reach_location(locations.CHEST_ID_TO_LOCATION[27]))
        self.assertTrue(self.multiworld.state.can_reach("Pyrite Town", player=self.player),
                        "the Data ROM edge must be unconditional when the item is not in the pool")


class TestCompanionDelivery(unittest.TestCase):
    """The delivery half. The standing rule on Client.py is "never block sending items" -- it ruined a run once --
    so the companion write is deliberately OUTSIDE the confirmation gate."""

    def setUp(self) -> None:
        import os

        path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "Client.py")
        with open(path, encoding="utf-8") as handle:
            self.source = handle.read()

    def test_the_companion_write_is_not_inside_the_confirmation_gate(self) -> None:
        """It runs right after give_items and outside the block-stability gate, exactly like give_items itself."""
        self.assertIn("_deliver_companion_items(ctx)", self.source)
        call = self.source.index("_deliver_companion_items(ctx)\n", self.source.index("await give_items(ctx)"))
        self.assertLess(call, self.source.index("if block_is_stable:"))

    def test_it_checks_before_every_rewrite(self) -> None:
        """What makes retrying safe rather than duplicating: a re-issue only happens while the Bag still says the
        item is missing."""
        start = self.source.index("def _deliver_companion_items(")
        body = self.source[start:self.source.index("\nasync def ", start)]
        self.assertIn("find_item_quantity", body)
        self.assertIn("if current > baseline", body)
        self.assertIn("pending.pop(companion_id, None)", body)

    def test_getitem_delivers_the_companion_too(self) -> None:
        """Otherwise the manual escape hatch would hand over half a packaged item -- precisely the state the
        packaging exists to make impossible."""
        start = self.source.index("def force_deliver")
        body = self.source[start:self.source.index("\nasync def ", start)]
        self.assertIn("companion_game_item_ids", body)
        self.assertIn("_delivery_companion_pending.pop(idx, None)", body)

    def test_a_missing_companion_is_warned_about_not_swallowed(self) -> None:
        self.assertIn("have not shown", self.source)
        self.assertIn("strand you in the Cipher Lab", self.source)


if __name__ == "__main__":
    unittest.main()
