"""ADDENDUM 311 -- Agate Village Pit Stop, per-category filler weights, stones and TMs demoted to filler.

Player: "Can you add an option called 'Agate Village Pit Stop' that, instead of giving Agate AP items, gives a
list of purchasable medicines/poke balls/great balls/ultra balls? Also, can we add a suite of options to control
what item categories (TMs, medicine, pokeballs, stones etc) are allowed in the filler pool and what their weights
are for appearing? Also, move evolution stones from progressive to filler, and tms to filler."""
import collections
import random
import struct
import unittest

from . import PokemonXDTestBase
from .. import items, options
from ..game_data import shop_stock as S
from ..game_data import shops
from ..tools import xd_rel_format as rel_format
from .test_addendum_111_shop_randomization import FakeRel

AGATE_NAMES = set(shops.shop_location_names(shops.SHOPS_BY_ROOM[shops.AGATE_PIT_STOP_ROOM_ID]))


# ------------------------------------------------------------------------------------------------ stones / TMs
class TestStonesAndTmsAreFiller(unittest.TestCase):
    def test_classification(self) -> None:
        for name in list(items.STONE_ITEMS) + list(items.TM_ITEMS):
            self.assertEqual("filler", items.ITEM_TABLE[name].classification.name, name)
            self.assertIn(name, items.FILLER_ITEMS, name)
            self.assertNotIn(name, items.USEFUL_ITEMS, name)
            self.assertNotIn(name, items.KEY_ITEMS_ALL, name)

    def test_ids_did_not_move(self) -> None:
        """The frozen offsets are keyed by name, so a reclassification must not renumber anything."""
        self.assertEqual(items.ITEM_TABLE["TM01"].id_offset, items._FROZEN_ITEM_OFFSETS["TM01"])
        self.assertEqual(items.ITEM_TABLE["Sun Stone"].id_offset, items._FROZEN_ITEM_OFFSETS["Sun Stone"])


class TestNoStoneIsForcedIntoTheSeed(PokemonXDTestBase):
    def test_no_stone_or_tm_is_progression_or_useful(self) -> None:
        for item in self.multiworld.itempool:
            if item.player == self.player and (item.name in items.STONE_ITEMS or item.name in items.TM_ITEMS):
                self.assertFalse(item.advancement or item.useful, item.name)


# ------------------------------------------------------------------------------------------ filler categories
class _World:
    def __init__(self, seed: int = 1, **weights: int) -> None:
        self.random = random.Random(seed)

        class _Opt:
            def __init__(self, value: int) -> None:
                self.value = value

        class _Options:
            pass

        self.options = _Options()
        for key, value in weights.items():
            setattr(self.options, f"filler_weight_{key}", _Opt(value))


def _category_of(name: str) -> str:
    for key, names in items.FILLER_CATEGORIES:
        if name in names:
            return key
    raise AssertionError(name)


class TestFillerCategories(unittest.TestCase):
    def test_option_defaults_match_the_item_table(self) -> None:
        for key, _names in items.FILLER_CATEGORIES:
            option = options.PokemonXDOptions.type_hints[f"filler_weight_{key}"]
            self.assertEqual(items.FILLER_CATEGORY_DEFAULT_WEIGHTS[key], option.default, key)

    def test_the_named_categories_exist(self) -> None:
        keys = {key for key, _n in items.FILLER_CATEGORIES}
        self.assertTrue({"tms", "medicine", "poke_balls", "evolution_stones"} <= keys)

    def test_weights_are_category_shares(self) -> None:
        world = _World(3, **items.FILLER_CATEGORY_DEFAULT_WEIGHTS)
        drawn = collections.Counter(_category_of(items.get_random_filler_item_name(world)) for _ in range(30000))
        total = sum(items.FILLER_CATEGORY_DEFAULT_WEIGHTS.values())
        for key, weight in items.FILLER_CATEGORY_DEFAULT_WEIGHTS.items():
            self.assertAlmostEqual(drawn[key] / 30000, weight / total, delta=0.015, msg=key)

    def test_zero_removes_a_category(self) -> None:
        weights = dict(items.FILLER_CATEGORY_DEFAULT_WEIGHTS, tms=0, poke_balls=0)
        world = _World(5, **weights)
        drawn = {_category_of(items.get_random_filler_item_name(world)) for _ in range(5000)}
        self.assertNotIn("tms", drawn)
        self.assertNotIn("poke_balls", drawn)

    def test_a_single_category(self) -> None:
        world = _World(6, **{key: (1 if key == "evolution_stones" else 0) for key in items.FILLER_CATEGORY_DEFAULT_WEIGHTS})
        drawn = {items.get_random_filler_item_name(world) for _ in range(500)}
        self.assertEqual(set(items.STONE_ITEMS), drawn)

    def test_all_zero_falls_back_instead_of_failing(self) -> None:
        world = _World(7, **{key: 0 for key in items.FILLER_CATEGORY_DEFAULT_WEIGHTS})
        self.assertEqual(items.FILLER_FALLBACK_ITEM_NAME, items.get_random_filler_item_name(world))


class TestWeightsReachARealSeed(PokemonXDTestBase):
    options = {f"filler_weight_{key}": 0 for key in items.FILLER_CATEGORY_DEFAULT_WEIGHTS} | {
        "filler_weight_tms": 100}

    def test_filler_is_tms(self) -> None:
        filler = [i.name for i in self.multiworld.itempool
                  if i.player == self.player and i.classification.name == "filler"]
        self.assertTrue(filler)
        self.assertTrue(all(name in items.TM_ITEMS for name in filler), collections.Counter(filler).most_common(5))


# ------------------------------------------------------------------------------------------------ Pit Stop
class TestPitStopLocations(PokemonXDTestBase):
    options = {"randomize_shops": True, "agate_village_pit_stop": True}

    def test_agate_has_no_checks_and_the_other_shops_do(self) -> None:
        names = {l.name for l in self.multiworld.get_locations(self.player)}
        self.assertFalse(names & AGATE_NAMES)
        self.assertIn("Gateon Port Shop AP Item 1", names)

    def test_seed_and_slot_data_carry_the_flag(self) -> None:
        self.assertTrue(self.multiworld.worlds[self.player].fill_slot_data()["agate_village_pit_stop"])


class TestPitStopOff(PokemonXDTestBase):
    options = {"randomize_shops": True}

    def test_agate_keeps_its_checks(self) -> None:
        names = {l.name for l in self.multiworld.get_locations(self.player)}
        self.assertEqual(AGATE_NAMES, names & AGATE_NAMES)


class TestTheClientStopsTreatingAgateAsAShop(unittest.TestCase):
    def tearDown(self) -> None:
        shops.set_disabled_shop_rooms(set())

    def test_disable_and_restore(self) -> None:
        from .. import ram_client
        room = shops.AGATE_PIT_STOP_ROOM_ID
        self.assertTrue(ram_client.is_shop_room(room))
        shops.set_disabled_shop_rooms({room})
        self.assertFalse(ram_client.is_shop_room(room))
        self.assertIsNone(shops.shop_for_room(room))
        self.assertIsNone(ram_client.shop_location_name_for_room(room, 1))
        self.assertEqual(0, ram_client.shop_slot_count_for_room(room))
        self.assertIsNone(shops.short_label_for_room(room))
        self.assertTrue(ram_client.is_shop_room(156), "only Agate is disabled")
        shops.set_disabled_shop_rooms(set())
        self.assertTrue(ram_client.is_shop_room(room))


def _real_layout_rel() -> "tuple[FakeRel, dict, dict]":
    """The real mart table's shape: every vanilla mart at its real pool offset, sentinels in the gaps."""
    pool_len = 1 + max(last for _f, last, _i in S.VANILLA_MARTS.values()) + 1
    start_base, items_base = 0x10, 0x100
    data = bytearray(items_base + pool_len * 2 + 0x10)
    for mart, (first, _last, _items) in S.VANILLA_MARTS.items():
        struct.pack_into(">HH", data, start_base + mart * 4, 0, first)
    for first, _last, vanilla in S.VANILLA_MARTS.values():
        for i, item in enumerate(vanilla):
            struct.pack_into(">H", data, items_base + (first + i) * 2, item)
    pointers = {rel_format.MART_START_INDEXES_POINTER: start_base, rel_format.MART_ITEMS_POINTER: items_base}
    values = {rel_format.NUMBER_OF_MARTS_POINTER: len(S.VANILLA_MARTS),
              rel_format.NUMBER_OF_MART_ITEMS_POINTER: pool_len}
    return FakeRel(bytes(data), pointers, values), pointers, values


class TestPitStopPatch(unittest.TestCase):
    def _patch(self, pit_stop: bool) -> "dict[int, list[int]]":
        rel, pointers, values = _real_layout_rel()
        out = bytearray(rel.data)
        rel_format.apply_mart_randomization(out, rel, list(items.USELESS_BERRY_IDS),
                                            frozenset(items.SHOP_EXCLUDED_ITEM_IDS), mart_groups=list(S.MART_GROUPS))
        if pit_stop:
            rel_format.apply_mart_fixed_stock(out, rel, S.agate_pit_stop_marts(), S.AGATE_PIT_STOP_STOCK,
                                              frozenset(items.SHOP_EXCLUDED_ITEM_IDS))
        patched = FakeRel(bytes(out), pointers, values)
        by_mart: "dict[int, list[int]]" = collections.defaultdict(list)
        for slot in rel_format.read_all_mart_slots(patched):
            by_mart[slot["mart_index"]].append(slot["item_id"])
        return by_mart

    def test_agate_sells_the_stock_and_keeps_its_scents(self) -> None:
        by_mart = self._patch(True)
        for mart in S.agate_pit_stop_marts():
            shelf = [i for i in by_mart[mart] if i]
            real = [i for i in shelf if i not in S._PRESERVED_ITEM_IDS]
            self.assertEqual(list(S.AGATE_PIT_STOP_STOCK[:len(real)]), real, f"mart {mart}")
            self.assertTrue({513, 514, 515} <= set(shelf), f"mart {mart} lost a Scent")
            self.assertFalse(set(shelf) & set(items.USELESS_BERRY_IDS), f"mart {mart} still sells a berry")
            self.assertTrue({4, 3, 2} <= set(real), "all three balls on every Agate shelf")

    def test_every_other_mart_is_byte_identical(self) -> None:
        off, on = self._patch(False), self._patch(True)
        for mart in S.VANILLA_MARTS:
            if mart not in S.agate_pit_stop_marts():
                self.assertEqual(off[mart], on[mart], f"mart {mart}")

    def test_the_restocks_add_hyper_potion_then_max_potion(self) -> None:
        """RETARGETED by ADDENDUM 387. This asserted that mart 5 had no Revive, which was true and was the
        problem: the opening shelf of a PIT STOP could not sell the one item a pit stop is for. The Revive
        and the Hyper Potion swapped places, so what arrives on the restock is now the Hyper Potion.

        The shape of the test is unchanged on purpose -- something must still arrive with each restock, or
        the three marts have stopped being three tiers."""
        by_mart = self._patch(True)
        m5, m12, m19 = S.agate_pit_stop_marts()
        self.assertIn(24, by_mart[m5], "the Revive is the point of ADDENDUM 387 -- it belongs on every shelf")
        self.assertNotIn(21, by_mart[m5])
        self.assertIn(21, by_mart[m12])
        self.assertIn(20, by_mart[m19])


if __name__ == "__main__":
    unittest.main()
