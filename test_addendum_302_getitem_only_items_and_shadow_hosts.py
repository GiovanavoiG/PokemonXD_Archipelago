"""ADDENDUM 302 (2026-09-20) -- two halves of one instruction.

Player: "If shadow_catch_progression is on, exclude missable trainers from the pool that can receive generated
shadows. Add an item '99 master balls' - don't add it to the pool, but add it so we can !getitem 99 master
balls".

HALF ONE WAS ALREADY TRUE, AND STRONGER THAN ASKED. ADDENDUM 236 passes
`missable_trainers.shadow_expansion_excluded_trainer_indices()` into `build_shadow_expansion_plans`, and that
helper returns `FILLER_ONLY_TRAINER_INDICES` -- every occurrence of every trainer the workbook marks missable,
plus the one-shot and post-goal sets. So a generated Shadow never lands on a missable trainer at all, whatever
`shadow_catch_progression` says. Measured on a real world at expansion 44: 0 of 44 hosts inside any of the six
fenced sets, 0 census-missable, 0 without a region.

THE GAP WAS THE WIRING, NOT THE RULE. ADDENDUM 236's own tests call `build_shadow_expansion_plans` directly and
hand it the excluded set, which proves the randomizer honours a set it is given -- not that the world hands it
one. Those are different claims, and only the second is what the player is relying on. The world-level classes
below assert the second, under the option that makes it matter.

NOT MADE CONDITIONAL. The instruction says "if shadow_catch_progression is on"; the guarantee is currently
unconditional, and narrowing it to that option would be a regression wearing the shape of the request. A
generated Shadow on a missable trainer is a catch that can be lost from the seed whether or not the catch is
progression-eligible -- with the option off it is a filler check the player can never clear, which is the
ADDENDUM 237 shape, not an acceptable one.

HALF TWO IS A NEW CATEGORY, AND THE POINT OF IT IS WHERE IT IS *NOT*. `!getitem` resolves through
`World.item_name_to_id`, built from ITEM_TABLE, so the item has to be in the table. Being in the table is also
what ordinarily puts an item into seeds -- three separate passes reach into ITEM_TABLE's source dicts. The
category is merged into ITEM_TABLE directly and into none of those dicts, so no pass can reach it. That is a
property of four pieces of code that do not mention each other, which is why it is asserted four times here
and again at import in items.py.
"""
from __future__ import annotations

import unittest

from BaseClasses import ItemClassification

from . import PokemonXDTestBase
from .. import items as I
from ..game_data import census_repeat_column as C
from ..game_data import missable_trainers as MT
from ..game_data import trainer_placements as TP

GETITEM_ONLY = "99 Master Balls"


# ------------------------------------------------------------------------------------------------------------
# Half one: generated Shadows and missable trainers
# ------------------------------------------------------------------------------------------------------------
class _ShadowHostBase(PokemonXDTestBase):
    def _hosts(self) -> "list[int]":
        plans = self.multiworld.worlds[self.player]._shadow_expansion_plans or []
        return sorted({int(plan["trainer_index"]) for plan in plans})

    def _assert_hosts_are_clean(self) -> None:
        hosts = self._hosts()
        self.assertTrue(hosts, "the expansion produced no hosts -- this test would pass vacuously")
        for host in hosts:
            self.assertNotIn(host, MT.MISSABLE_TRAINER_INDICES, host)
            self.assertNotIn(host, MT.FILLER_ONLY_TRAINER_INDICES, host)
            self.assertNotIn(host, MT.POST_GOAL_TRAINER_INDICES, host)
            self.assertFalse(C.CENSUS_REPEAT_AND_MISSABLE.get(host, (None, False))[1], host)
            placement = TP.PLACEMENTS.get(host)
            self.assertTrue(placement and placement.region,
                            f"host {host} has no region -- its catch location could not be reached")


class TestWithShadowCatchProgressionOn(_ShadowHostBase):
    """The condition the player named."""

    options = {"shadow_pokemon_expansion": 44, "shadow_catch_progression": True,
               "shuffle_trainer_defeats": True}

    def test_no_generated_shadow_sits_on_a_missable_trainer(self) -> None:
        self._assert_hosts_are_clean()

    def test_the_exclusion_does_not_starve_the_setting(self) -> None:
        """A fence that silently delivers fewer Shadows than asked is its own bug -- see ADDENDUM 236."""
        self.assertEqual(44, len(self.multiworld.worlds[self.player]._shadow_expansion_plans or []))

    def test_every_generated_shadow_has_a_catch_host_recorded(self) -> None:
        world = self.multiworld.worlds[self.player]
        self.assertEqual(len(world._shadow_expansion_plans or []),
                         sum(len(v) for v in world._shadow_catch_expansion_hosts.values()))


class TestWithShadowCatchProgressionOff(_ShadowHostBase):
    """The guarantee is unconditional, and this is what keeps it that way -- see the module docstring for why
    narrowing it to the option would be a regression."""

    options = {"shadow_pokemon_expansion": 44, "shadow_catch_progression": False,
               "shuffle_trainer_defeats": True}

    def test_the_fence_holds_with_the_option_off_too(self) -> None:
        self._assert_hosts_are_clean()


class TestTheWorldActuallyPassesTheExclusionSet(unittest.TestCase):
    """ADDENDUM 236's own tests hand the randomizer an excluded set directly. This is the other half of that
    claim: that the world builds one and passes it at the real call site."""

    def test_the_call_site_names_the_helper(self) -> None:
        import os

        source = open(os.path.join(os.path.dirname(MT.__file__), "..", "__init__.py"),
                      encoding="utf-8").read()
        call = source.index("build_shadow_expansion_plans(")
        body = source[call:source.index(")\n", source.index("level_multiplier", call))]
        self.assertIn("shadow_expansion_excluded_trainer_indices()", body)

    def test_the_helper_covers_every_missable_index(self) -> None:
        self.assertTrue(
            set(MT.MISSABLE_TRAINER_INDICES) <= set(MT.shadow_expansion_excluded_trainer_indices()))


# ------------------------------------------------------------------------------------------------------------
# Half two: an item that exists to be asked for
# ------------------------------------------------------------------------------------------------------------
class TestTheItemIsRequestable(unittest.TestCase):
    """WIDENED BY ADDENDUM 336 (2026-09-24). This half was written against one name; the category has two now
    ("99 Rare Candies", same rule, player's words: "the same rule as 99 master balls"). Every statement that
    is about the CATEGORY loops over `GETITEM_ONLY_ITEM_NAMES`, so a third bundle is covered the day it is
    added rather than the day someone remembers to widen a test. The two statements that are genuinely about
    the Master Ball stay named."""

    def test_they_are_in_the_table_getitem_resolves_against(self) -> None:
        for name in I.GETITEM_ONLY_ITEM_NAMES:
            self.assertIn(name, I.ITEM_TABLE, name)

    def test_each_delivers_ninety_nine_of_a_real_verified_bag_item(self) -> None:
        for name in I.GETITEM_ONLY_ITEM_NAMES:
            data = I.ITEM_TABLE[name]
            self.assertEqual(99, data.quantity, name)
            self.assertIsNotNone(data.game_item_id, name)
            self.assertTrue(data.game_item_id_verified, name)

    def test_each_shares_its_id_with_the_single_item_it_bundles(self) -> None:
        """A bundle is a bulk delivery of a real Bag item, not a new kind of one -- which is what lets it
        route to the same pocket with no client change."""
        for name, single in (("99 Master Balls", "Master Ball"), ("99 Rare Candies", "Rare Candy")):
            self.assertEqual(I.ITEM_TABLE[single].game_item_id, I.ITEM_TABLE[name].game_item_id, name)

    def test_their_ids_are_frozen_rather_than_riding_the_auto_counter(self) -> None:
        """items.py's own paste-it-immediately convention -- ADDENDUM 270 exists because two ids did not."""
        for name in I.GETITEM_ONLY_ITEM_NAMES:
            self.assertIn(name, I._FROZEN_ITEM_OFFSETS, name)
            self.assertEqual(I._FROZEN_ITEM_OFFSETS[name], I.ITEM_TABLE[name].id_offset, name)

    def test_the_ordinary_master_ball_is_untouched(self) -> None:
        master = I.ITEM_TABLE["Master Ball"]
        self.assertEqual(1, master.quantity)
        self.assertEqual("progression", master.classification.name)

    def test_the_ordinary_rare_candy_is_untouched(self) -> None:
        """ADDENDUM 336. The single Rare Candy is ordinary filler and IS drawn from the pool -- sharing an id
        with the bundle is fine, sharing a name would not be."""
        candy = I.ITEM_TABLE["Rare Candy"]
        self.assertEqual(1, candy.quantity)
        self.assertIn("Rare Candy", I.FILLER_ITEMS)
        self.assertIn("Rare Candy", I.MEDICINE_ITEMS)


class TestNoPoolPassCanReachIt(unittest.TestCase):
    """Four statements of one property, because it is a property of four unrelated passes."""

    def test_none_is_progression_or_useful(self) -> None:
        for name in I.GETITEM_ONLY_ITEM_NAMES:
            self.assertEqual("filler", I.ITEM_TABLE[name].classification.name, name)

    def test_each_is_outside_every_source_dict(self) -> None:
        for name in I.GETITEM_ONLY_ITEM_NAMES:
            for dict_name in ("FILLER_ITEMS", "USEFUL_ITEMS", "KEY_ITEMS_ALL"):
                self.assertNotIn(name, getattr(I, dict_name), f"{name} / {dict_name}")

    def test_none_is_in_the_random_filler_pool(self) -> None:
        for name in I.GETITEM_ONLY_ITEM_NAMES:
            self.assertNotIn(name, I._RANDOM_FILLER_POOL, name)

    def test_none_belongs_to_an_item_group(self) -> None:
        """A group name is itself resolvable by !getitem, so membership would make it drawable by asking for
        something else."""
        for name in I.GETITEM_ONLY_ITEM_NAMES:
            for group, names in I.ITEM_NAME_GROUPS.items():
                self.assertNotIn(name, names, f"{name} / {group}")


class TestItNeverEntersASeed(PokemonXDTestBase):
    options = {"shuffle_trainer_defeats": True, "progression_locations": 2}

    def test_the_item_pool_does_not_contain_them(self) -> None:
        pool = {item.name for item in self.multiworld.itempool}
        for name in I.GETITEM_ONLY_ITEM_NAMES:
            self.assertNotIn(name, pool, name)

    def test_no_location_holds_one(self) -> None:
        for location in self.multiworld.get_locations(self.player):
            if location.item:
                self.assertNotIn(location.item.name, I.GETITEM_ONLY_ITEM_NAMES, location.name)

    def test_the_random_filler_draw_never_produces_one(self) -> None:
        world = self.multiworld.worlds[self.player]
        drawn = {world.get_filler_item_name() for _ in range(2000)}
        self.assertEqual(frozenset(), drawn & I.GETITEM_ONLY_ITEM_NAMES)
        self.assertGreater(len(drawn), 1, "the draw must actually be varying")

    def test_but_the_world_can_still_build_each_on_request(self) -> None:
        """This is what !getitem does."""
        world = self.multiworld.worlds[self.player]
        for name in I.GETITEM_ONLY_ITEM_NAMES:
            self.assertIn(name, world.item_name_to_id, name)
            item = world.create_item(name)
            self.assertEqual(name, item.name)
            self.assertEqual(ItemClassification.filler, item.classification)


if __name__ == "__main__":
    unittest.main()
