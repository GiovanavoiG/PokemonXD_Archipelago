"""Consolidated regression coverage for ADDENDUM 111 (2026-09-11, shop randomization REDESIGN).

This file merges the five previously separate ADDENDUM 111 test modules into one:

  * test_addendum_111_useless_berries.py           -- items.py's reserved constants
  * test_addendum_111_shop_randomization_option.py -- the "Randomize Shops" YAML option's world wiring
  * test_addendum_111_client_wiring.py             -- Client.py's poll-loop wiring
  * test_addendum_111_shop_purchase_tracker.py     -- ram_client.ShopPurchaseTracker's debounce behaviour
  * test_addendum_111_mart_rel_helpers.py          -- tools/xd_rel_format.apply_mart_randomization

The player request this addendum implements: "utilize all of our individual useless berries as dummy
items... Make it so purchasing each item ONCE sends an AP check - we can change the order of the berries
between each shop so that we can identify each unique shop at runtime." Collectively this supersedes
ADDENDUM 110's single-SHOP_DUMMY_GAME_ITEM_ID/ShopCountTracker design, whose test modules are already gone.

WHAT THE MERGE DROPPED, AND WHY (54 test functions -> 32). Nothing that covered a distinct behaviour, an
error/skip path, a bounds check or a live-reported regression was removed; every dropped test's assertions
and its docstring's reasoning were folded into the test that kept the behaviour:

  * Constant-equals-literal assertions with no behaviour behind them -- the separate
    `AGATE_VILLAGE_SCENT_ITEM_IDS == {513, 514, 515}` and `POKE_SNACK_ITEM_ID == 511` checks (both are
    re-asserted by the SHOP_EXCLUDED_ITEM_IDS composition test), the standalone
    `CHEST_DUMMY_GAME_ITEM_ID == 161` check, the standalone `len(...) == 26` counts, and the standalone
    "check_shops is defined" string-presence check (the no-op test already indexes on that exact
    signature and fails loudly if it moves).
  * `USELESS_BERRY_IDS[0] == 148 / [-1] == 174 / 161 not in ...` -- subsumed by the exact-set test, which
    now also pins first/last/sorted order, because seed.json ships the list in order.
  * Redundant near-identical parameter variations of apply_mart_randomization's rotation
    (`test_excluded_slots_never_consume_a_rotation_step`, `test_rotation_continues_across_mart_boundaries`)
    -- the kept representative uses the same fixture with an exclusion AND spans both marts, so it already
    proves both properties; their reasoning lives in its docstring. The N=1 degenerate case, the sentinel
    bound, the no-mutation guard and both ADDENDUM 127/128 safety-bound tests were all KEPT.
  * Pairs of assertions about one scenario that were split across two tests were merged into one test
    (e.g. option-off location absence + collateral sanity; confirmed-purchase firing + per-berry baseline
    reset; the two ADDENDUM 148 block-stability-gate assertions; the ProgressionLocations=0 escape hatch's
    two halves).

DELIBERATELY NOT DROPPED even though they look small: the Enigma Berry removal check (a live player
report, and the SECOND time that item has been pulled for being bugged in-game), every ShopPurchaseTracker
debounce/glitch/cap path, both mart write-bound tests (ADDENDUM 127's live junk slot 34888 and ADDENDUM
128's declared-pool-size bound -- these are the ones standing between a patch pass and a corrupt ISO), and
both ProgressionLocations behaviours.

WHY THIS FILE STUBS `dolphin_memory_engine`: same reason as test_chest_count_tracker_debounce.py --
`ram_client.py` does `import dolphin_memory_engine as dme` at module level, and that real package isn't
installable in every environment this project's tests run in. The tracker tests never touch `dme` at all;
they monkeypatch `ram_client.read_pocket` and `ram_client.clear_item` instead.

WHY THE CLIENT TESTS DO NOT IMPORT `Client.py` DIRECTLY: same documented sandbox limitation as
test_sync_travel_locations.py/test_addendum_109_getitem_command.py -- `Client.py` -> `CommonClient` ->
`MultiServer` -> `websockets.extensions` fails to import in this sandbox, independent of anything this
addendum changed. Those are text-level structural sanity checks, the established pattern for every other
Client.py-touching addendum in this project.

WHY THE MART TESTS DO NOT CONSTRUCT A REAL `RelFile`: see the FakeRel docstring below -- same reasoning as
this project's other real-REL tests (chest/Poke Spot tables): no synthetic/fixture REL binary exists
anywhere in this codebase, and every mart helper only ever calls `rel.data`/`rel.get_pointer()`/
`rel.get_value_at_pointer()`, so a minimal duck-typed fake exercises the real offset arithmetic/walk logic
just as faithfully without needing a real REL header.
"""
from __future__ import annotations

import json
import os
import struct
import sys
import tempfile
import types
import time
import unittest

NOTE_353 = """ADDENDUM 353 removed the `if _looks_ingame():` gate from the main loop entirely -- the catch and
        purification scans read the save-resident `Pokemon` records now and need no menu to have been opened
        -- so this anchors on the END of the stability block instead. The property is unchanged and slightly
        stronger: the call must sit inside `if block_is_stable:` and before that branch closes."""
import zipfile
from pathlib import Path
from unittest import mock

if "dolphin_memory_engine" not in sys.modules:
    _stub = types.ModuleType("dolphin_memory_engine")
    _stub.hook = lambda: None
    _stub.un_hook = lambda: None
    _stub.is_hooked = lambda: False
    _stub.read_bytes = lambda address, length: b""
    _stub.write_bytes = lambda address, data: None
    sys.modules["dolphin_memory_engine"] = _stub

from . import PokemonXDTestBase
from .. import items, locations, ram_client
from ..tools import xd_rel_format as rel_format


# --------------------------------------------------------------------------------------------------
# Shared fixtures
# --------------------------------------------------------------------------------------------------

RAZZ = 148
BLUK = 149


# ADDENDUM 176: the tracker credits a SHOP now, so every poll needs a room. 156 is the Gateon Port shop.
GATEON_SHOP_ROOM = 156
MT_BATTLE_SHOP_ROOM = 21
NOT_A_SHOP_ROOM = 138          # Pokemon HQ Lab interior -- a real room with no shop in it


def _poll_sequence(
    tracker: "ram_client.ShopPurchaseTracker",
    quantities_per_poll: "list[dict[int, int]]",
    berry_ids: "list[int]" = (RAZZ, BLUK),
    room_id: "int | None" = GATEON_SHOP_ROOM,
) -> "tuple[list[list[str]], list[tuple]]":
    """Runs tracker.poll() once per entry in `quantities_per_poll` ({item_id: quantity}, only non-zero ids
    need to be listed -- everything else in `berry_ids` implicitly reads as 0 that poll), with `read_pocket`
    patched to hand back one synthetic BagSlot per non-zero entry (regardless of the irrelevant pocket_base
    argument passed) and `clear_item` patched to just record its call args. Returns (newly_crossed results per
    poll, recorded clear_item call arg tuples).

    ShopPurchaseTracker's own `_batch_item_quantities` helper calls `read_pocket` ONCE per poll for all
    watched berries at once, unlike the old ADDENDUM 110 scalar tracker's per-item `find_item_quantity`."""
    results = []
    clear_calls: list[tuple] = []

    # ADDENDUM 259: the confirm window is a DURATION now (`_CONFIRM_SECONDS`), not only a poll count, so these
    # sequences have to advance a clock or nothing would ever confirm -- a tight loop takes no real time at
    # all. One second per poll is exactly POLL_INTERVAL_INGAME, so every expectation below is unchanged in
    # meaning and these tests now pin the real 1s cadence instead of a bare count. A tracker the caller built
    # with its own clock is left alone.
    # Kept ON the tracker, so a test that calls this helper twice against the SAME tracker (the
    # second-purchase-after-clearing case) carries on from where the first sequence left the clock instead of
    # silently freezing it at that value.
    fake_clock = getattr(tracker, "_test_clock", None)
    if fake_clock is None:
        fake_clock = {"t": 0.0}
        tracker._test_clock = fake_clock
        tracker.clock = lambda: fake_clock["t"]

    def fake_read_pocket(pocket_base: int, max_slots: int, _polls=iter(quantities_per_poll)):
        quantities = next(_polls)
        return [
            ram_client.BagSlot(index=i, address=0, item_id=item_id, quantity=qty)
            for i, (item_id, qty) in enumerate(quantities.items())
            if qty > 0
        ]

    with mock.patch.object(ram_client, "read_pocket", side_effect=fake_read_pocket):
        with mock.patch.object(ram_client, "clear_item", side_effect=lambda *a: clear_calls.append(a) or True):
            for _ in quantities_per_poll:
                results.append(tracker.poll(block_base=0, room_id=room_id,
                                            berry_ids=list(berry_ids)))
                fake_clock["t"] += 1.0
    return results, clear_calls


class FakeRel:
    """Duck-typed stand-in for xd_rel_format.RelFile -- see module docstring for why this is used instead of a
    real one. `pointers`/`values_at_pointer` are plain {pointer_table_index: result} dicts."""

    def __init__(self, data: bytes, pointers: dict[int, int], values_at_pointer: dict[int, int]) -> None:
        self.data = data
        self._pointers = pointers
        self._values = values_at_pointer

    def get_pointer(self, index: int) -> int:
        return self._pointers[index]

    def get_value_at_pointer(self, index: int) -> int:
        return self._values[index]


def _build_synthetic_mart_data() -> FakeRel:
    """Two synthetic marts sharing one flat MartItems pool:
      - Mart 0 (FirstItemIndex=0): pool slots 0,1,2 = [111, 513 (Joy Scent), 222], slot 3 = sentinel (0).
      - Mart 1 (FirstItemIndex=4): pool slots 4,5 = [333, 444], slot 6 = sentinel (0).
    MartStartIndexes base = 0x10, MartItems pool base = 0x40 -- identical fixture shape to the ADDENDUM 110
    mart-helper tests, reused here since apply_mart_randomization's read-side walk is unchanged."""
    data = bytearray(0x60)
    start_base = 0x10
    items_base = 0x40
    # ADDENDUM 128: FirstItemIndex is the SECOND halfword (+2) of each 4-byte entry (reference randomizer's
    # Pokemarts.cs); the first halfword is deliberately filled with a decoy value that would send the walk
    # somewhere wrong if the code ever read +0 again.
    struct.pack_into(">HH", data, start_base + 0 * 4, 9, 0)  # Mart 0: FirstItemIndex = 0
    struct.pack_into(">HH", data, start_base + 1 * 4, 9, 4)  # Mart 1: FirstItemIndex = 4
    pool_values = [111, 513, 222, 0, 333, 444, 0]
    for i, value in enumerate(pool_values):
        struct.pack_into(">H", data, items_base + i * 2, value)
    return FakeRel(
        bytes(data),
        pointers={
            rel_format.MART_START_INDEXES_POINTER: start_base,
            rel_format.MART_ITEMS_POINTER: items_base,
        },
        values_at_pointer={
            rel_format.NUMBER_OF_MARTS_POINTER: 2,
            rel_format.NUMBER_OF_MART_ITEMS_POINTER: 5,
        },
    )


def _read_item_ids(rel_bytes: bytes, pointers: dict[int, int], values: dict[int, int]) -> dict[int, int]:
    patched = FakeRel(rel_bytes, pointers, values)
    return {slot["pool_index"]: slot["item_id"] for slot in rel_format.read_all_mart_slots(patched)}


# --------------------------------------------------------------------------------------------------
# items.py -- the reserved useless-berry and shop-exclusion constants (pure data, no Dolphin needed)
# --------------------------------------------------------------------------------------------------


class TestUselessBerrySpecs(unittest.TestCase):
    """`USELESS_BERRY_SPECS`/`USELESS_BERRY_IDS`/`USELESS_BERRY_ID_TO_NAME` -- all useless berries used as
    per-slot dummy items, 26 as of Enigma Berry's ADDENDUM 117 removal (was 27)."""

    def test_ids_are_exactly_the_pruned_razz_through_starf_range_in_order(self) -> None:
        """The exact roster, in order: Razz Berry (148) through Starf Berry (174), minus Rabuta Berry (161,
        reserved as the sole chest dummy item) and Enigma Berry (175, bugged -- see the next test). Order is
        load-bearing, not cosmetic: generate_output() ships `list(items.USELESS_BERRY_IDS)` into seed.json and
        apply_mart_randomization rotates through that list positionally, so a reshuffle silently changes which
        berry lands in which shop slot."""
        # NARROWED 2026-09-15 (ADDENDUM 218, player: "The shops do not need every dummy berry"). Ganlon (169)
        # through Starf (174) moved to items.CHEST_BERRY_SPECS, where they give each chest its own identity.
        expected = set(range(148, 169)) - {161}
        self.assertEqual(set(items.USELESS_BERRY_IDS), expected)
        self.assertEqual(items.USELESS_BERRY_IDS[0], 148)   # Razz Berry
        self.assertEqual(items.USELESS_BERRY_IDS[-1], 168)  # Liechi Berry
        self.assertEqual(list(items.USELESS_BERRY_IDS), sorted(items.USELESS_BERRY_IDS))
        # No chest berry may ever double as a shop dummy -- a purchase would register as a chest opening.
        self.assertFalse(set(items.CHEST_BERRY_IDS) & set(items.USELESS_BERRY_IDS))

    def test_enough_shop_berries_remain_for_the_biggest_shop(self) -> None:
        """ADDENDUM 218 took six berries out of this list for chest identity. `apply_mart_randomization`
        assigns `dummy_item_ids[i % len(dummy_item_ids)]`, so within-shop uniqueness holds only while this
        list is longer than the biggest shop -- Mt. Battle, 18 slots. This is the floor that narrowing must
        never cross, and crossing it would break shop identification silently rather than loudly."""
        from ..game_data import shops

        biggest = max(shop.slot_count for shop in shops.SHOPS)
        self.assertGreaterEqual(
            len(items.USELESS_BERRY_IDS), biggest,
            f"the biggest shop has {biggest} slots but only {len(items.USELESS_BERRY_IDS)} shop berries "
            f"remain -- a berry would repeat inside one shop and two slots would be indistinguishable",
        )

    def test_enigma_berry_was_removed_2026_09_11_for_being_bugged_in_game(self) -> None:
        # ADDENDUM 117 follow-up, player request: "remove Enigma berry as one of our dummies, as it's bugged
        # in-game" -- the second time this specific item has been pulled for being bugged (ADDENDUM 31 already
        # swapped it out as CHEST_DUMMY_GAME_ITEM_ID for the same reason).
        self.assertNotIn(175, items.USELESS_BERRY_IDS)
        self.assertNotIn("Enigma Berry", items.USELESS_BERRY_ID_TO_NAME.values())

    def test_specs_ids_and_id_to_name_are_internally_consistent(self) -> None:
        """All three views of the roster must agree: same length (26), unique names, unique ids, and
        USELESS_BERRY_ID_TO_NAME round-trips every (name, id) pair in USELESS_BERRY_SPECS. A mismatch here
        means a berry is reachable through one view and invisible through another."""
        # 20 since ADDENDUM 218 took six for chest identity; was 26.
        self.assertEqual(len(items.USELESS_BERRY_SPECS), 20)
        self.assertEqual(len(items.USELESS_BERRY_IDS), 20)
        self.assertEqual(len(items.USELESS_BERRY_ID_TO_NAME), 20)
        names = [name for name, _id in items.USELESS_BERRY_SPECS]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(len(items.USELESS_BERRY_IDS), len(set(items.USELESS_BERRY_IDS)))
        for name, game_item_id in items.USELESS_BERRY_SPECS:
            self.assertEqual(items.USELESS_BERRY_ID_TO_NAME[game_item_id], name)

    def test_no_useless_berry_id_is_ever_a_real_pool_item_or_a_named_berry(self) -> None:
        """Same guarantee CHEST_DUMMY_GAME_ITEM_ID already has: never placed as a real AP item, so its Bag
        quantity can only ever move via the shop-purchase mechanism this addendum builds. Checked against both
        the whole ITEM_TABLE and, specifically, the named berry roster (_BERRY_NAMES) -- a useless berry that
        leaked into the named roster would be both a real pool item and a shop dummy at once."""
        real_game_item_ids = {data.game_item_id for data in items.ITEM_TABLE.values() if data.game_item_id is not None}
        self.assertTrue(real_game_item_ids.isdisjoint(items.USELESS_BERRY_IDS))
        named_berry_ids = {items.ITEM_TABLE[name].game_item_id for name in items._BERRY_NAMES}
        self.assertTrue(named_berry_ids.isdisjoint(items.USELESS_BERRY_IDS))

    def test_shop_excluded_item_ids_are_the_scents_plus_poke_snack_and_disjoint_from_everything_else(self) -> None:
        """`SHOP_EXCLUDED_ITEM_IDS` -- the three researched Agate Village Scent items (513/514/515) plus Poke
        Snack (511), which shop randomization must leave alone. They must also be disjoint from every real
        pool item and from both dummy-item sets, or an excluded slot would collide with a real check."""
        self.assertEqual(items.AGATE_VILLAGE_SCENT_ITEM_IDS, frozenset({513, 514, 515}))
        self.assertEqual(items.POKE_SNACK_ITEM_ID, 511)
        self.assertEqual(items.SHOP_EXCLUDED_ITEM_IDS, frozenset({511, 513, 514, 515}))
        real_game_item_ids = {data.game_item_id for data in items.ITEM_TABLE.values() if data.game_item_id is not None}
        self.assertTrue(items.SHOP_EXCLUDED_ITEM_IDS.isdisjoint(real_game_item_ids))
        self.assertTrue(items.SHOP_EXCLUDED_ITEM_IDS.isdisjoint(items.USELESS_BERRY_IDS))
        self.assertNotIn(items.CHEST_DUMMY_GAME_ITEM_ID, items.SHOP_EXCLUDED_ITEM_IDS)


# --------------------------------------------------------------------------------------------------
# The "Randomize Shops" YAML option -- world-level wiring (locations.py, item pool, generate_output)
# --------------------------------------------------------------------------------------------------


class TestShopRandomizationOptionOff(PokemonXDTestBase):
    """Default (option off) -- no "Buy Shop Item - ..." locations should exist in this world at all, and
    generate_output() must leave both shop fields None/empty, the same "skip cleanly" contract
    chest_dummy_item_id already has."""

    # ADDENDUM 196: shops now default ON, and this class is the option-OFF twin, so it must say so.
    options = {"randomize_chests": True, "shuffle_trainer_defeats": True, "randomize_shops": False}

    def test_no_shop_purchase_locations_exist_and_other_content_is_unaffected(self) -> None:
        """Also sanity checks this option doesn't touch anything else -- Agate Village's real overworld-item
        location still exists in this world (still gated behind the ordinary memo chain by default, same as
        without this option -- see test_travel_locations_option.py's own equivalent check)."""
        all_names = {loc.name for loc in self.multiworld.get_locations(self.player)}
        for name in (locations.SHOP_ITEM_LOCATIONS[0], locations.SHOP_ITEM_LOCATIONS[-1]):
            self.assertNotIn(name, all_names)
        self.assertIn("Agate Bridge Chest", all_names)   # ADDENDUM 335: the old probe was retired

    def test_generate_output_leaves_shop_fields_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            self.world.generate_output(tmp_dir)
            appxd_files = list(Path(tmp_dir).glob("*.appxd"))
            with zipfile.ZipFile(appxd_files[0]) as zf:
                seed_data = json.loads(zf.read("seed.json"))
        self.assertFalse(seed_data.get("shop_dummy_item_ids"))
        self.assertFalse(seed_data.get("shop_excluded_item_ids"))


class TestShopRandomizationOptionOn(PokemonXDTestBase):
    options = {
        "randomize_chests": True,
        "shuffle_trainer_defeats": True,
        "randomize_shops": True,
    }

    def test_every_shop_item_location_exists_and_is_in_its_own_name_group(self) -> None:
        """RETARGETED 2026-09-13 (ADDENDUM 176): one location per (SHOP, slot) pair rather than per (berry,
        occurrence), one per randomized stock line in that shop. They still live in their own "Shop Purchases" group
        and must not leak into "Overworld Items"."""
        from ..game_data import shops

        all_names = {loc.name for loc in self.multiworld.get_locations(self.player)}
        for name in locations.SHOP_ITEM_LOCATIONS:
            self.assertIn(name, all_names)
        self.assertEqual(len(locations.SHOP_ITEM_LOCATIONS),
                         sum(shop.slot_count for shop in shops.CONFIRMED_SHOPS))
        self.assertIn(locations.SHOP_ITEM_LOCATIONS[0], locations.LOCATION_NAME_GROUPS["Shop Purchases"])
        self.assertNotIn(locations.SHOP_ITEM_LOCATIONS[0], locations.LOCATION_NAME_GROUPS["Overworld Items"])

    def test_shop_item_locations_can_hold_progression_by_default(self) -> None:
        """CHANGED 2026-09-11 (ADDENDUM 150). These used to be asserted EXCLUDED unconditionally. The player
        asked for the opposite -- "ensure that every check can be progressive/useful/not filler" -- so at
        `ProgressionLocations`' default they are DEFAULT, and rules.py gives each occurrence a real region
        rule instead of leaving it reachable from turn one. The old behaviour is still available and is
        covered by the ProgressionLocations tiers in test_addendum_150."""
        from BaseClasses import LocationProgressType

        loc = self.multiworld.get_location(locations.SHOP_ITEM_LOCATIONS[0], self.player)
        self.assertEqual(loc.progress_type, LocationProgressType.DEFAULT)

    def test_a_shop_is_gated_by_its_own_towns_region(self) -> None:
        """REPLACED 2026-09-13 (ADDENDUM 176). This used to be "occurrence number gates reachability", and its
        own docstring had already recorded the model breaking down: `_SHOP_OCCURRENCE_REGIONS` opened with
        "Outskirt Stand" as "this world's first shop", which stopped being true when ADDENDUM 168 made Outskirt
        Stand a late region, so occurrence 1 was the DEEPEST of the four rather than the shallowest.

        There is nothing left to model. A shop is in a town, so it is gated by that town -- the Gateon Port
        shop is open from the start because Gateon Port is, and the Outskirt Stand shop is not because Outskirt
        Stand is behind the whole key-item chain. That spread is asserted directly against the graph."""
        from ..game_data import shops

        gateon = shops.shop_location_name("Gateon Port Shop", 1)
        mt_battle = shops.shop_location_name("Mt. Battle Shop", 1)
        self.assertTrue(self.can_reach_location(gateon), "Gateon Port is always open")
        self.assertFalse(self.can_reach_location(mt_battle), "Mt. Battle is behind the Machine Part")
        self.collect_key_item_chain(1)
        self.assertTrue(self.can_reach_location(mt_battle))
    def test_this_option_never_changes_the_real_item_pool(self) -> None:
        # Shop randomization only ever converts existing shop slots into checks -- it must never add or remove
        # any real AP item from the pool (unlike, say, randomize_travel_locations, which does add items).
        item_names = sorted(item.name for item in self.multiworld.itempool)
        self.assertFalse(any("Shop" in name or "AP Item" in name for name in item_names))

    def test_generate_output_writes_shop_dummy_item_ids_and_exclusions(self) -> None:
        """The real generate_output() seed.json payload, now shop_dummy_item_ids (PLURAL, the whole rotation
        list in order) plus shop_excluded_item_ids -- superseding the single-dummy-item field."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            self.world.generate_output(tmp_dir)
            appxd_files = list(Path(tmp_dir).glob("*.appxd"))
            self.assertEqual(len(appxd_files), 1)
            with zipfile.ZipFile(appxd_files[0]) as zf:
                seed_data = json.loads(zf.read("seed.json"))

        self.assertEqual(seed_data.get("shop_dummy_item_ids"), list(items.USELESS_BERRY_IDS))
        self.assertEqual(
            sorted(seed_data.get("shop_excluded_item_ids") or []),
            sorted(items.SHOP_EXCLUDED_ITEM_IDS),
        )

    def test_fill_slot_data_includes_randomize_shops(self) -> None:
        slot_data = self.world.fill_slot_data()
        self.assertIn("randomize_shops", slot_data)
        self.assertTrue(slot_data["randomize_shops"])


# REMOVED 2026-09-15 (ADDENDUM 237): this class set `progression_locations: 0` to check that shop purchases
# went back to EXCLUDED at the most conservative setting. That setting is gone (see options.py), so the
# "escape hatch" it documented no longer exists. Shop locations' own access rules are unchanged and still
# covered by the tests above.
class TestShopClientWiring(unittest.TestCase):
    """The wiring SHAPE (unconditional poll alongside check_chests(), not gated behind _looks_ingame(), no-op
    when randomize_shops is off) is unchanged from ADDENDUM 110 -- only the tracker class name changed."""

    def setUp(self) -> None:
        client_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "Client.py")
        with open(client_path, encoding="utf-8") as f:
            self.source = f.read()

    def test_shop_tracker_is_instantiated_on_the_context(self) -> None:
        """And the superseded ADDENDUM 110 ShopCountTracker is gone -- leaving both behind would mean two
        trackers racing for the same Bag slots."""
        self.assertIn("self.shop_tracker = ram_client.ShopPurchaseTracker()", self.source)
        self.assertNotIn("ram_client.ShopCountTracker()", self.source)

    def test_randomize_shops_defaults_false_and_is_read_from_slot_data(self) -> None:
        self.assertIn("self.randomize_shops: bool = False", self.source)
        self.assertIn('self.randomize_shops = bool(slot_data.get("randomize_shops", False))', self.source)

    def test_check_shops_is_defined_and_no_ops_when_the_option_is_off(self) -> None:
        start = self.source.index("async def check_shops(ctx: PokemonXDContext) -> None:")
        rest = self.source[start:]
        end = rest.index("\nasync def ", 1)
        body = rest[:end]
        self.assertIn("not ctx.randomize_shops", body)
        # ADDENDUM 176: the poll takes the room id too, since the room is what names the shop.
        self.assertIn("ctx.shop_tracker.poll(ctx.block_base, room_id)", body)
        self.assertIn("read_room_id", body)

    def test_check_shops_is_polled_alongside_check_chests_inside_the_block_stability_gate(self) -> None:
        """Shops must be polled on the same ticks chests are, never on a different schedule.

        RE-INDENTED 2026-09-11 (ADDENDUM 148): both calls moved one level deeper, inside the
        `if block_is_stable:` gate that stops the block-derived trackers being polled while the save menu is
        rewriting the save block. If one of the two were ever left outside the gate, that one would go back to
        being polled mid-rewrite -- the exact bug the gate was added for -- so this checks both the literal
        adjacency/indentation of the two calls AND that the gate precedes both."""
        self.assertIn("await check_chests(ctx)\n                        await check_shops(ctx)", self.source)
        gate = self.source.index("if block_is_stable:")
        # UPDATED 2026-09-17 (ADDENDUM 262): `check_chests` has two call sites now as well, for the same
        # reason `check_shops` grew a second one -- the fast sub-poll. Same requirement, same shape as the
        # shops assertion below: the main-loop call is inside the gate, the sub-loop call re-polls stability
        # itself. A bare `index(...)` would just find whichever is defined first in the file.
        chest_sites = [i for i in range(len(self.source))
                       if self.source.startswith("await check_chests(ctx)", i)]
        self.assertTrue(any(site > gate for site in chest_sites))
        # UPDATED 2026-09-17 (ADDENDUM 259). There are TWO `await check_shops(ctx)` call sites now -- the main
        # loop's, and the shop fast-poll sub-loop's -- so a bare `source.index(...)` finds whichever happens to
        # be defined first in the file and stops testing anything. The requirement is unchanged and now has to
        # hold for BOTH: neither call site may poll a save block that is being rewritten. The main-loop call
        # inherits the gate; the sub-loop call cannot (it runs during the sleep, after the gate has gone out of
        # scope), so it re-polls `block_stability` itself and that is what is checked here.
        call_sites = [i for i in range(len(self.source))
                      if self.source.startswith("await check_shops(ctx)", i)]
        self.assertEqual(2, len(call_sites),
                         "a third check_shops call site needs its own block-stability story")
        self.assertTrue(any(site > gate for site in call_sites),
                        "the main-loop call must sit inside the `if block_is_stable:` gate")
        window = self.source[self.source.index("async def fast_poll_window"):]
        window = window[:window.index("\nasync def ", 1)]
        self.assertIn("await check_shops(ctx)", window)
        self.assertIn("await check_chests(ctx)", window)
        self.assertIn("ctx.block_stability.poll(ctx.block_base)", window,
                      "the sub-loop is outside the main gate, so it must re-poll stability itself")

    def test_check_shops_is_not_gated_behind_looks_ingame(self) -> None:
        """Same "BLOCK_BASE-relative only, runs unconditionally" requirement check_chests() already has.

        %s""" % NOTE_353
        idx_call = self.source.index("await check_shops(ctx)")
        idx_end = self.source.index("elif not ctx._block_churn_logged:", idx_call)
        self.assertGreater(idx_end, idx_call, "check_shops(ctx) must sit inside the stability block")
        window = self.source[idx_call:idx_end]
        self.assertNotIn("if _looks_ingame():", window,
                         "check_shops(ctx) must not be gated on the party menu having been opened")

    def test_the_main_loop_has_no_party_menu_gate_left(self) -> None:
        """ADDENDUM 353. The only surviving `_looks_ingame()` call is inside `check_purifications`, around
        the one correlation that genuinely is unsafe against an all-zero PARTY_BASE."""
        start = self.source.index("if block_is_stable:")
        end = self.source.index("elif not ctx._block_churn_logged:", start)
        self.assertNotIn("_looks_ingame", self.source[start:end])


# --------------------------------------------------------------------------------------------------
# ram_client.ShopPurchaseTracker -- per-berry debounce, independence, and Bag clearing
# --------------------------------------------------------------------------------------------------


class TestShopPurchaseTrackerDebounce(unittest.TestCase):
    """Mirrors test_chest_count_tracker_debounce.py's structure closely (same ADDENDUM 98/99 confirm-streak
    debounce, reused verbatim per berry) -- these tests focus on the real behavioral differences from the
    superseded ShopCountTracker: per-berry independence (one berry's purchase never affects another's tracked
    state), and clearing only the confirmed berry's own Bag slot."""

    def test_first_poll_only_baselines_every_watched_berry_never_fires(self) -> None:
        tracker = ram_client.ShopPurchaseTracker()
        results, clear_calls = _poll_sequence(tracker, [{RAZZ: 5, BLUK: 2}])
        self.assertEqual(results, [[]])
        self.assertEqual(tracker.last_seen_quantity, {RAZZ: 5, BLUK: 2})
        self.assertEqual(tracker.slots_credited, {})
        self.assertEqual(clear_calls, [])

    def test_genuine_increase_confirmed_after_streak_clears_and_rebaselines_only_that_berry(self) -> None:
        """A real purchase: Razz Berry rises from 0 to 3 (bought 3 at once) and HOLDS at 3 -- must fire exactly
        once, on the poll completing the confirm streak, AND clear only Razz Berry's Bag slot. Razz's own
        baseline then resets to 0 (because it was cleared, NOT to the 3 last seen), while Bluk's baseline is
        left completely untouched at its own real value."""
        tracker = ram_client.ShopPurchaseTracker()
        polls = [{RAZZ: 0, BLUK: 0}, {RAZZ: 3, BLUK: 0}, {RAZZ: 3, BLUK: 0}, {RAZZ: 3, BLUK: 0}, {RAZZ: 3, BLUK: 0}]
        results, clear_calls = _poll_sequence(tracker, polls)
        self.assertEqual(results[:4], [[], [], [], []])
        # SUPERSEDED 2026-09-15 (ADDENDUM 238c/238d). This used to expect THREE checks -- buying 3 units
        # credited the shop's next three slots, because a berry was an arbitrary position in a global rotation
        # and the only honest identity was "the Nth purchase in this room". The patcher now deals berries per
        # shop LINE, so berry index k+1 IS shelf line k+1. Razz is index 0, so this is three copies of line 1:
        # ONE check, and `delta` is deliberately ignored.
        self.assertEqual(results[4], ["Gateon Port Shop AP Item 1"])
        self.assertEqual(tracker.slots_credited[GATEON_SHOP_ROOM], 1)
        self.assertEqual(len(clear_calls), 1)
        self.assertEqual(clear_calls[0][-1], RAZZ)  # clear_item(pocket_base, slot_count, item_id)
        self.assertEqual(tracker.last_seen_quantity[RAZZ], 0)  # cleared -- NOT 3
        self.assertEqual(tracker.last_seen_quantity[BLUK], 0)  # untouched, still its own real baseline

    def test_two_different_berries_are_tracked_fully_independently(self) -> None:
        # Razz confirms a purchase on poll 4 while Bluk is mid-debounce (candidate seen but not yet confirmed)
        # -- Bluk's own pending streak must be unaffected by Razz's confirmation/clear in the same poll.
        tracker = ram_client.ShopPurchaseTracker()
        polls = [
            {RAZZ: 0, BLUK: 0},
            {RAZZ: 1, BLUK: 0},
            {RAZZ: 1, BLUK: 0},
            {RAZZ: 1, BLUK: 5},  # Bluk's candidate first appears here
            {RAZZ: 1, BLUK: 5},
        ]
        results, clear_calls = _poll_sequence(tracker, polls)
        # Razz's candidate is first seen on poll index1 (0, then 1,1,1,1 -- 4 consecutive matching polls at
        # indices 1-4), confirming on index4; Bluk's candidate is first seen later, on index3, so it's only
        # reached streak=2 by index4 -- nowhere near confirmed yet.
        self.assertEqual(results[:4], [[], [], [], []])
        self.assertEqual(results[4], ["Gateon Port Shop AP Item 1"])
        self.assertEqual(len(clear_calls), 1)
        self.assertEqual(clear_calls[0][-1], RAZZ)

    def test_a_second_purchase_after_clearing_is_detected_fresh_from_the_zero_baseline(self) -> None:
        tracker = ram_client.ShopPurchaseTracker()
        _poll_sequence(tracker, [{RAZZ: 0}, {RAZZ: 1}, {RAZZ: 1}, {RAZZ: 1}, {RAZZ: 1}])
        self.assertEqual(tracker.slots_credited[GATEON_SHOP_ROOM], 1)
        self.assertEqual(tracker.last_seen_quantity[RAZZ], 0)
        results, clear_calls = _poll_sequence(tracker, [{RAZZ: 2}, {RAZZ: 2}, {RAZZ: 2}, {RAZZ: 2}], berry_ids=[RAZZ])
        self.assertEqual(results[:3], [[], [], []])
        # SUPERSEDED 2026-09-15 (ADDENDUM 238c/238d): this used to expect slots 2 and 3, because a second
        # purchase advanced a running counter. Berry index 0 is shelf LINE 1 in every shop now, so buying Razz
        # again is buying the same line again -- no new check, and idempotent by construction rather than by
        # luck. The detection, the Bag clear and the re-baseline all still happen, which is what this test is
        # really guarding: the player is never blocked, only the check is not duplicated.
        self.assertEqual(results[3], [])
        self.assertEqual(tracker.slots_credited[GATEON_SHOP_ROOM], 1)
        self.assertEqual(len(clear_calls), 1)

    def test_spike_then_revert_glitch_fires_nothing_and_never_clears(self) -> None:
        tracker = ram_client.ShopPurchaseTracker()
        results, clear_calls = _poll_sequence(tracker, [{RAZZ: 0}, {RAZZ: 5}, {RAZZ: 0}], berry_ids=[RAZZ])
        self.assertEqual(results, [[], [], []])
        self.assertEqual(tracker.slots_credited, {})
        self.assertEqual(clear_calls, [])

    def test_decrease_is_accepted_as_new_baseline_without_firing_or_clearing(self) -> None:
        tracker = ram_client.ShopPurchaseTracker()
        _poll_sequence(tracker, [{RAZZ: 5}], berry_ids=[RAZZ])
        results, clear_calls = _poll_sequence(tracker, [{RAZZ: 2}], berry_ids=[RAZZ])
        self.assertEqual(results, [[]])
        self.assertEqual(tracker.last_seen_quantity[RAZZ], 2)
        self.assertEqual(clear_calls, [])

    def test_slot_count_is_capped_per_shop_but_the_purchase_still_clears(self) -> None:
        """ADDENDUM 176: the cap is per SHOP now. Past it, no new check is created -- but the purchase itself
        and the dummy-item removal still happen, which is the "never block the player" half of the design and
        the reason a cap that is slightly wrong in either direction is safe."""
        from ..game_data import shops
        from ..items import USELESS_BERRY_IDS

        # REWRITTEN 2026-09-15 (ADDENDUM 238c/238d). The cap used to be reached by a running counter, so the
        # test primed `slots_credited` to the shop's stock count and bought anything. Now a berry names its own
        # line, so "past the cap" means a berry whose INDEX exceeds this shop's line count -- which can still
        # reach the Bag here (a gift opened in a shop, a field pickup carried in). Gateon has 15 lines, so
        # berry index 15 (the 16th) is the first one that cannot be one of them.
        cap = shops.SHOPS_BY_ROOM[GATEON_SHOP_ROOM].slot_count
        over_cap_berry = USELESS_BERRY_IDS[cap]
        tracker = ram_client.ShopPurchaseTracker()
        results, clear_calls = _poll_sequence(
            tracker,
            [{over_cap_berry: 0}, {over_cap_berry: 1}, {over_cap_berry: 1},
             {over_cap_berry: 1}, {over_cap_berry: 1}],
            berry_ids=[over_cap_berry],
        )
        self.assertEqual(results[4], [])  # past this shop's lines -- no new location names
        self.assertNotIn(GATEON_SHOP_ROOM, tracker.slots_credited)
        self.assertEqual(tracker.purchases_outside_a_shop, 1)
        self.assertEqual(len(clear_calls), 1)  # purchase still happened and is still cleared from the Bag

    def test_a_berry_rising_outside_any_shop_credits_nothing_but_still_clears(self) -> None:
        """A dummy berry can arrive from a gift or a field pickup. Crediting a guess would send a check for a
        purchase that never happened; not clearing would leave the tracker unable to tell held stock from a new
        purchase. So: no check, still cleared, and counted separately rather than vanishing."""
        tracker = ram_client.ShopPurchaseTracker()
        results, clear_calls = _poll_sequence(
            tracker, [{RAZZ: 0}, {RAZZ: 1}, {RAZZ: 1}, {RAZZ: 1}, {RAZZ: 1}],
            berry_ids=[RAZZ], room_id=NOT_A_SHOP_ROOM,
        )
        self.assertEqual(results[4], [])
        self.assertEqual(tracker.slots_credited, {})
        self.assertEqual(tracker.purchases_outside_a_shop, 1)
        self.assertEqual(len(clear_calls), 1)

    def test_an_unreadable_room_leaves_the_purchase_pending_rather_than_eating_it(self) -> None:
        """read_room_id returns None rather than a guess when its four replicated copies disagree (ADDENDUM
        142). A purchase is confirmed about two seconds after it happens, so the player is still standing in
        the shop -- None means a transient read failure, not "not in a shop". Clearing here would silently eat
        the check, so the increase stays pending and a later poll with a readable room credits it."""
        tracker = ram_client.ShopPurchaseTracker()
        results, clear_calls = _poll_sequence(
            tracker, [{RAZZ: 0}, {RAZZ: 1}, {RAZZ: 1}, {RAZZ: 1}, {RAZZ: 1}],
            berry_ids=[RAZZ], room_id=None,
        )
        self.assertEqual(results[4], [])
        self.assertEqual(clear_calls, [], "must NOT clear -- the purchase has not been credited yet")
        self.assertEqual(tracker.last_seen_quantity[RAZZ], 0, "baseline untouched, so it retries")

        # Now the room reads. The confirm streak was already satisfied while the room was unreadable, so the
        # very next poll credits -- the pending state was preserved, not thrown away and re-earned.
        results, clear_calls = _poll_sequence(
            tracker, [{RAZZ: 1}], berry_ids=[RAZZ], room_id=MT_BATTLE_SHOP_ROOM,
        )
        self.assertEqual(results[0], ["Mt. Battle Shop AP Item 1"])
        self.assertEqual(len(clear_calls), 1)


# --------------------------------------------------------------------------------------------------
# tools/xd_rel_format.apply_mart_randomization -- dummy-id rotation and write bounds
# --------------------------------------------------------------------------------------------------


class TestApplyMartRandomizationRotation(unittest.TestCase):
    """`apply_mart_randomization` was rewritten to rotate through a LIST of dummy item ids (all useless
    berries in production -- 26 as of Enigma Berry's ADDENDUM 117 removal, was 27) via a global,
    deterministic counter, instead of writing one fixed id everywhere (ADDENDUM 110's now-superseded
    version). The read-side mart/pointer-table helpers (mart_first_item_index, mart_item_slots,
    read_all_mart_slots) are UNCHANGED by this addendum."""

    def test_every_non_excluded_slot_gets_a_rotating_dummy_id_in_global_walk_order(self) -> None:
        """5 real slots (pool indices 0,1,2,4,5), one excluded (1, item 513) -> 4 real slots patched, rotating
        through 3 dummy ids: 0->901 (rotation 0), 2->902 (rotation 1), 4->903 (rotation 2), 5->901 (rotation
        3, wraps back to index 0 of the 3-item list).

        Two properties in one fixture. (a) The excluded slot consumes NO rotation step -- if it did, mart 1's
        first real slot would land on a different dummy id. (b) The counter is GLOBAL and continues across the
        mart boundary rather than resetting per mart: slot 4 is mart 1's first slot and still takes rotation
        2, not rotation 0. That continuation is what gives each mart a different "starting offset" into the
        dummy id list for free, which is what lets the player identify each unique shop at runtime."""
        rel = _build_synthetic_mart_data()
        rel_bytes = bytearray(rel.data)
        count = rel_format.apply_mart_randomization(
            rel_bytes, rel, dummy_item_ids=[901, 902, 903], excluded_item_ids=frozenset({513})
        )
        self.assertEqual(count, 4)
        slots = _read_item_ids(bytes(rel_bytes), rel._pointers, rel._values)
        self.assertEqual(slots[0], 901)
        self.assertEqual(slots[1], 513)  # untouched, and consumed no rotation step
        self.assertEqual(slots[2], 902)
        self.assertEqual(slots[4], 903)  # mart 1's first slot -- counter continued, did not reset
        self.assertEqual(slots[5], 901)  # wrapped back to the first dummy id

    def test_sentinel_slots_are_never_touched_or_counted(self) -> None:
        rel = _build_synthetic_mart_data()
        rel_bytes = bytearray(rel.data)
        rel_format.apply_mart_randomization(rel_bytes, rel, dummy_item_ids=[999], excluded_item_ids=frozenset())
        self.assertEqual(struct.unpack_from(">H", rel_bytes, 0x40 + 3 * 2)[0], 0)
        self.assertEqual(struct.unpack_from(">H", rel_bytes, 0x40 + 6 * 2)[0], 0)

    def test_original_rel_data_is_never_mutated_only_the_bytearray_copy(self) -> None:
        rel = _build_synthetic_mart_data()
        original = bytes(rel.data)
        rel_bytes = bytearray(rel.data)
        rel_format.apply_mart_randomization(rel_bytes, rel, dummy_item_ids=[999], excluded_item_ids=frozenset())
        self.assertEqual(rel.data, original)

    def test_a_single_dummy_id_list_degenerates_to_the_old_write_everywhere_behavior(self) -> None:
        # Sanity check that a length-1 list (the old ADDENDUM 110 shape) still behaves like writing one fixed
        # id to every real slot -- confirms this is a strict generalization, not a behavior change for N=1.
        rel = _build_synthetic_mart_data()
        rel_bytes = bytearray(rel.data)
        count = rel_format.apply_mart_randomization(rel_bytes, rel, dummy_item_ids=[999], excluded_item_ids=frozenset())
        self.assertEqual(count, 5)
        slots = _read_item_ids(bytes(rel_bytes), rel._pointers, rel._values)
        self.assertEqual([slots[0], slots[1], slots[2], slots[4], slots[5]], [999, 999, 999, 999, 999])


class TestApplyMartRandomizationSafetyBounds(unittest.TestCase):
    """ADDENDUM 127 (2026-09-11): the first successful live decode of the real pocket_menu.rel showed a few
    junk slot values (e.g. 34888) past one mart's real end -- apply_mart_randomization must never overwrite a
    slot whose original id isn't a real vanilla item id, nor one past the pool's declared size (+ one sentinel
    per mart), and neither kind consumes a rotation step."""

    def test_out_of_range_original_id_is_left_untouched_and_does_not_consume_rotation(self) -> None:
        rel = _build_synthetic_mart_data()
        data = bytearray(rel.data)
        struct.pack_into(">H", data, 0x40 + 2 * 2, 34888)  # pool slot 2: junk id, way past 0x251
        rel = FakeRel(bytes(data), rel._pointers, rel._values)
        rel_bytes = bytearray(rel.data)
        count = rel_format.apply_mart_randomization(rel_bytes, rel, dummy_item_ids=[901, 902, 903], excluded_item_ids=frozenset())
        self.assertEqual(count, 4)
        slots = _read_item_ids(bytes(rel_bytes), rel._pointers, rel._values)
        self.assertEqual(slots[2], 34888)  # untouched
        # rotation: slot0 -> 901, slot1 -> 902, (slot2 skipped), slot4 -> 903, slot5 -> 901
        self.assertEqual([slots[0], slots[1], slots[4], slots[5]], [901, 902, 903, 901])

    def test_slots_past_the_declared_pool_size_plus_sentinels_are_left_untouched(self) -> None:
        # NumberOfMartItems=5, NumberOfMarts=2 -> write bound = pool index 7; make mart 1's walk run past it by
        # removing its sentinel (slot 6) and planting in-range ids at 6..9, then a sentinel at 10.
        rel = _build_synthetic_mart_data()
        data = bytearray(rel.data)
        for i, v in zip(range(6, 10), (100, 101, 102, 103)):
            struct.pack_into(">H", data, 0x40 + i * 2, v)
        struct.pack_into(">H", data, 0x40 + 10 * 2, 0)
        rel = FakeRel(bytes(data), rel._pointers, rel._values)
        rel_bytes = bytearray(rel.data)
        rel_format.apply_mart_randomization(rel_bytes, rel, dummy_item_ids=[999], excluded_item_ids=frozenset())
        # ADDENDUM 128: the walk itself now stops at the limit (mart_slot_limit), so read the raw pool bytes
        # rather than the (now correctly shorter) census.
        raw = [struct.unpack_from(">H", rel_bytes, 0x40 + i * 2)[0] for i in range(11)]
        self.assertEqual(raw[6], 999)  # index 6 < 7: patched
        self.assertEqual(raw[7:10], [101, 102, 103])  # >= 7: untouched
        self.assertEqual(rel_format.mart_item_slots(rel, 1), [4, 5, 6])


if __name__ == "__main__":
    unittest.main()
