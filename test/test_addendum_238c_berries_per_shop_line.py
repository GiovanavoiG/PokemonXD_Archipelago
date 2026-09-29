"""ADDENDUM 238c (2026-09-15) -- berries are dealt PER SHOP LINE, and a shop's later shelves are gated.

Player: "Take option 2 - berries per shop line." and, on Phenac 1F, "these don't change, but are only
accessible after music disc and mayor note."

TWO CHANGES, and the second one is the one with teeth.

1. `xd_rel_format.apply_mart_randomization` no longer walks one global rotation across the shared item pool.
   Given `mart_groups` it walks SHOPS, and within a shop assigns a berry to each distinct shelf LINE the
   first time that line is seen, reusing it in every later tier. The defect it fixes was not cosmetic: a
   shop's tiers are different slices of the pool, so a restock used to move EVERY line onto a fresh berry.
   Pyrite's ONBS restock genuinely adds a Poke Ball and a Great Ball, and both landed on berries the old
   shelf had already used -- neither became a check -- while three unchanged X-items landed on fresh berries
   and did.

2. Because check N is now literally "the Nth line this shop ever offers", a restock-only line is NOT on the
   opening shelf, and the room rule alone no longer covers it. `rules._set_shop_tier_rules` puts Agate's
   check 9 (its Great Ball) and Pyrite's checks 11-12 behind the ONBS crisis, and Agate's check 8 behind
   Mt. Battle. Without this, a progression item on one of those is an unwinnable seed.
"""
import unittest

from . import PokemonXDTestBase
from .. import rules
from ..game_data import shop_stock as S
from ..game_data import shops
from ..tools import xd_rel_format


class TestALineKeepsItsBerry(unittest.TestCase):
    def test_a_line_present_in_two_tiers_has_one_number_in_both(self) -> None:
        """The whole point. Agate's Potion line is in all three of its marts and must be check 1 in each."""
        for shop, item_id in (("Agate Village Shop", 13), ("Pyrite Town Shop", 22)):
            entry = S.SHOP_MART_TIERS[shop]
            numbers = set()
            for mart in entry["marts"]:
                first, _last, items = S.VANILLA_MARTS[mart]
                labels = iter(S.MART_LINE_NUMBERS[mart])
                for item in items:
                    if item in S._PRESERVED_ITEM_IDS:
                        continue
                    n = next(labels)
                    if item == item_id:
                        numbers.add(n)
            self.assertEqual(len(numbers), 1, f"{shop} item {item_id} took {numbers}")

    def test_every_shop_numbers_its_lines_1_to_n_with_no_gaps(self) -> None:
        """Player: "change the labels so the ones that start available start from 1." Under this model that
        is structural rather than a renumbering pass -- the opening shelf is always 1..n."""
        for shop in S.SHOP_MART_TIERS:
            lines = S.shop_lines(shop)
            self.assertEqual([n for n, _item, _mart in lines],
                             list(range(1, len(lines) + 1)), shop)
            opening = S.SHOP_MART_TIERS[shop]["marts"][0]
            self.assertEqual(S.MART_LINE_NUMBERS[opening],
                             tuple(range(1, len(S.MART_LINE_NUMBERS[opening]) + 1)), shop)

    def test_the_three_shops_the_player_walked_through(self) -> None:
        """Agate is the one confirmed four ways over in live play, so it is the one pinned by item name."""
        agate = [(n, item) for n, item, _mart in S.shop_lines("Agate Village Shop")]
        self.assertEqual(agate, [(1, 13), (2, 22), (3, 14), (4, 15), (5, 16), (6, 17), (7, 18),
                                 (8, 4), (9, 3)])
        # 1-7 open, 8 (Poke Ball) with Aidan's email, 9 (Great Ball) with the ONBS crisis.
        self.assertEqual(S.shop_line_count("Agate Village Shop"), 9)
        self.assertEqual(S.shop_line_count("Pyrite Town Shop"), 12)
        self.assertEqual(S.shop_line_count("Phenac City Shop"), 12)

    def test_the_counts_match_what_shops_py_allocates(self) -> None:
        for shop in shops.CONFIRMED_SHOPS:
            expected = S.shop_line_count(shop.name)
            if expected == 0:
                continue  # marts not identified yet -- see UNRESOLVED_SHOPS
            self.assertEqual(shop.slot_count, expected, shop.name)


class TestPokeSnacksStillNeverCount(unittest.TestCase):
    """Standing instruction, re-asserted against the NEW numbering: "do not involve poke snacks in checks
    whatsoever". Six marts carry one (1, 8, 13, 14, 15, 19)."""

    def test_no_mart_numbers_a_preserved_line(self) -> None:
        for mart, (_first, _last, items) in S.VANILLA_MARTS.items():
            preserved = sum(1 for item in items if item in S._PRESERVED_ITEM_IDS)
            self.assertEqual(len(items) - preserved, len(S.MART_LINE_NUMBERS[mart]), mart)

    def test_a_snack_does_not_consume_a_line_number(self) -> None:
        """Mart 19's Snack sits between the Scents and the end; the nine numbers must be 1..9 regardless."""
        self.assertEqual(sorted(S.MART_LINE_NUMBERS[19]), list(range(1, 10)))


class TestTheGrouping(unittest.TestCase):
    def test_mart_groups_covers_every_shop_including_the_excluded_one(self) -> None:
        """The Battle CD room creates no locations, but its slots still have to be patched or it sells real
        items. Excluding a shop from CHECKS is not excluding it from the patch."""
        self.assertEqual({key for key, _marts in S.MART_GROUPS}, set(S.SHOP_MART_TIERS))
        self.assertIn("Realgam Battle Sim Shop", dict(S.MART_GROUPS))

    def test_no_pool_slot_is_claimed_by_two_shops(self) -> None:
        """Aliased marts (9/10/11, 7/20) are the same slice reached twice by ONE shop, which is fine. Two
        DIFFERENT shops on one slot would mean a shelf line answering to two check numberings."""
        owner = {}
        for key, marts in S.MART_GROUPS:
            for mart in marts:
                first, last, _items = S.VANILLA_MARTS[mart]
                for slot in range(first, last + 1):
                    self.assertEqual(owner.setdefault(slot, key), key, slot)

    def test_every_mart_now_belongs_to_a_shop(self) -> None:
        """ADDENDUM 238d closed the last three. The single-mart fallback in apply_mart_randomization is kept
        anyway -- it is what stops an unidentified shop selling real items -- but nothing needs it today."""
        named = {m for _key, marts in S.MART_GROUPS for m in marts}
        self.assertEqual(named, set(S.VANILLA_MARTS))
        self.assertEqual(S.UNRESOLVED_MARTS, ())


class TestPhenacIsOneShelf(unittest.TestCase):
    """The contradiction ADDENDUM 238b could not resolve, closed by the player's own stock table: Phenac 1F
    lists exactly mart 1's thirteen lines, and the ONLY "after meeting Duking in Pyrite Town" note on it sits
    on the POKE SNACK line -- the same note Agate's Snack line carries. It is the game-wide Snack unlock, not
    a mart swap. So Phenac 1F never restocks, its whole shelf sits behind the room's own key-item chain, and
    there is no longer an ordering conflict to resolve."""

    def test_phenac_first_floor_has_one_tier(self) -> None:
        self.assertEqual(S.SHOP_MART_TIERS["Phenac City Shop"]["marts"], (1,))
        self.assertEqual(S.gated_shop_lines("Phenac City Shop"), [])

    def test_mart_14_belongs_to_gateon_not_phenac(self) -> None:
        """It was freed by the Phenac correction and ADDENDUM 238d gave it a home by elimination."""
        self.assertEqual(S.SHOP_MART_TIERS["Gateon Port Shop"]["marts"], (6, 14, 15))


class TestTheRotationRaisesRatherThanAliasing(unittest.TestCase):
    """Two failures that must be loud, because both would silently merge two checks into one."""

    class _FakeRel:
        def __init__(self, pool): self.pool = pool

    def _apply(self, pool, marts, groups, dummy, excluded=frozenset()):
        import struct
        data = bytearray(struct.pack(f">{len(pool)}H", *pool))
        rel = self._FakeRel(pool)
        out = bytearray(data)
        original = {
            "number_of_marts": xd_rel_format.number_of_marts,
            "mart_item_slots": xd_rel_format.mart_item_slots,
            "mart_item_slot_offset": xd_rel_format.mart_item_slot_offset,
        }
        rel.data = bytes(data)
        xd_rel_format.number_of_marts = lambda r: len(marts)
        xd_rel_format.mart_item_slots = lambda r, i: range(marts[i][0], marts[i][1] + 1)
        xd_rel_format.mart_item_slot_offset = lambda r, s: s * 2
        try:
            xd_rel_format.apply_mart_randomization(out, rel, dummy, excluded, mart_groups=groups)
        finally:
            for name, fn in original.items():
                setattr(xd_rel_format, name, fn)
        import struct as _s
        return list(_s.unpack(f">{len(pool)}H", bytes(out)))

    def test_two_groups_on_one_slot_raise(self) -> None:
        with self.assertRaises(ValueError) as caught:
            self._apply([4, 13], [(0, 1)], [("A", (0,)), ("B", (0,))], [133, 134])
        self.assertIn("two shops", str(caught.exception))

    def test_a_group_with_more_lines_than_berries_raises(self) -> None:
        with self.assertRaises(ValueError) as caught:
            self._apply([4, 13, 22], [(0, 2)], [("A", (0,))], [133, 134])
        self.assertIn("share a berry", str(caught.exception))

    def test_a_repeated_line_reuses_its_berry_across_tiers(self) -> None:
        """Two marts, one shop: mart 0 sells Poke Ball + Potion, mart 1 sells Potion + Great Ball. Potion
        keeps berry 0 in both; Great Ball, the genuinely new line, takes the next one."""
        out = self._apply([4, 13, 13, 3], [(0, 1), (2, 3)], [("A", (0, 1))], [133, 134, 135])
        self.assertEqual(out, [133, 134, 134, 135])


class TestTheLaterShelvesAreGated(unittest.TestCase):
    def test_the_gates_name_real_regions_and_a_real_item(self) -> None:
        from .. import items, regions
        for shop in S.SHOP_MART_TIERS:
            for _numbers, gate in S.gated_shop_lines(shop):
                for name in gate["regions"]:
                    self.assertIn(name, regions.REGION_NAMES, name)
                for name in gate["items"]:
                    self.assertIn(items.requirement_to_pool_item(name), items.ITEM_TABLE, name)

    def test_exactly_the_restock_only_lines_are_gated(self) -> None:
        gated = {(shop, n) for shop in S.SHOP_MART_TIERS
                 for numbers, _gate in S.gated_shop_lines(shop) for n in numbers}
        self.assertEqual(gated, {("Agate Village Shop", 8), ("Agate Village Shop", 9),
                                 ("Pyrite Town Shop", 11), ("Pyrite Town Shop", 12),
                                 # ADDENDUM 238d: Gateon's two restocks, 7-11 behind the ONBS crisis and
                                 # 12-15 behind Gorigan. Its opening shelf (1-6) stays on the room rule.
                                 ("Gateon Port Shop", 7), ("Gateon Port Shop", 8),
                                 ("Gateon Port Shop", 9), ("Gateon Port Shop", 10),
                                 ("Gateon Port Shop", 11), ("Gateon Port Shop", 12),
                                 ("Gateon Port Shop", 13), ("Gateon Port Shop", 14),
                                 ("Gateon Port Shop", 15)})

    def test_the_opening_shelf_is_never_gated_beyond_its_room(self) -> None:
        """A shop's first tier is reachable as soon as the room is; gating it again would be wrong and would
        also quietly re-introduce the ADDENDUM 182 class of over-tight logic."""
        for shop in S.SHOP_MART_TIERS:
            opening = set(S.MART_LINE_NUMBERS[S.SHOP_MART_TIERS[shop]["marts"][0]])
            for numbers, _gate in S.gated_shop_lines(shop):
                self.assertFalse(opening & set(numbers), shop)

    def test_rules_has_the_pass_wired_in(self) -> None:
        import inspect
        self.assertIn("_set_shop_tier_rules", inspect.getsource(rules.set_all_rules))


class TestTheClientCreditsByLineNumber(unittest.TestCase):
    """The bug this redesign introduced into the CLIENT, and the fix.

    `ShopPurchaseTracker` credited "the next uncredited slot in this room" (ADDENDUM 176: the berry is the
    signal, the room is the identity). That was right when a berry was an arbitrary position in a global
    rotation -- nothing about berry 7 said which line it was. Under per-shop-line assignment berry index k+1
    IS shelf line k+1, so a running count is actively wrong: buying Agate's Antidote (line 3) first would
    credit line 1, and buying lines 3, 5, 7 in that order would credit 1, 2, 3."""

    def _buy(self, berry, room, quantity=1, berry_ids=None):
        from .. import ram_client
        from . import test_addendum_111_shop_randomization as h
        tracker = ram_client.ShopPurchaseTracker()
        polls = [{berry: 0}] + [{berry: quantity}] * 4
        results, _clear = h._poll_sequence(
            tracker, polls, berry_ids=berry_ids or [berry], room_id=room)
        return tracker, results[-1]

    def test_the_berry_names_the_line_regardless_of_purchase_order(self) -> None:
        from ..items import USELESS_BERRY_IDS
        for index in (0, 2, 6):
            _tracker, fired = self._buy(USELESS_BERRY_IDS[index], 134)
            self.assertEqual(fired, [f"Agate Village Shop AP Item {index + 1}"])

    def test_buying_three_of_one_line_is_still_one_check(self) -> None:
        """`delta` is ignored now. Under the running counter a delta of 3 meant three slots; under line
        numbering it means the player bought the same shelf line three times."""
        from ..items import USELESS_BERRY_IDS
        _tracker, fired = self._buy(USELESS_BERRY_IDS[0], 134, quantity=3)
        self.assertEqual(fired, ["Agate Village Shop AP Item 1"])

    def test_a_berry_above_the_shops_line_count_credits_nothing(self) -> None:
        """Agate has 9 lines. Berry index 9 (the 10th) cannot be one of them, but it can still reach the Bag
        in a shop -- a gift opened there, a field pickup carried in -- so it is counted, not guessed at."""
        from ..items import USELESS_BERRY_IDS
        tracker, fired = self._buy(USELESS_BERRY_IDS[9], 134)
        self.assertEqual(fired, [])
        self.assertEqual(tracker.purchases_outside_a_shop, 1)

    def test_the_line_number_ignores_the_polled_subset(self) -> None:
        """`berry_ids` exists so a caller can poll a subset. Taking the index within that subset would make
        the same berry mean line 1 in one call and line 7 in another -- which is exactly the bug that the
        ADDENDUM 111 cap test caught."""
        from ..items import USELESS_BERRY_IDS
        berry = USELESS_BERRY_IDS[4]
        _tracker, fired = self._buy(berry, 134, berry_ids=[berry])
        self.assertEqual(fired, ["Agate Village Shop AP Item 5"])


class TestTheChestBerriesVanillaShopSource(unittest.TestCase):
    """AN OLD OPEN QUESTION, closed by reading the mart table: "the six chest berries (169-174) were never
    verified to have no other in-game source."

    Four of them do. Mt. Battle's mart (9/10/11) sells Ganlon (169), Salac (170), Petaya (171) and Apicot
    (172) in vanilla. That is exactly the shape of a false positive -- a shop purchase that `ChestBerryTracker`
    mistakes for a chest opening, the same class of bug ADDENDUM 236 fixed for purifications.

    It cannot fire, for two independent reasons, and both are pinned here because either one silently
    changing would reopen it."""

    def test_the_patcher_overwrites_all_four_when_shops_are_randomized(self) -> None:
        from ..game_data import chest_berries
        mt_battle = S.VANILLA_MARTS[9][2]
        overlap = [i for i in mt_battle if i in chest_berries.CHEST_BERRY_IDS]
        self.assertEqual(overlap, [169, 170, 171, 172])
        # Every one of those slots is patchable, so with randomize_shops on they all become shop berries.
        self.assertEqual(len(S.MART_LINE_NUMBERS[9]), len(mt_battle))

    def test_the_shop_room_pairs_with_no_chest_so_it_drops_even_with_shops_off(self) -> None:
        """The reason that still holds when randomize_shops is OFF and Mt. Battle really does sell them.
        `ChestBerryTracker` identifies a chest by (room, berry) and DROPS an unmatched pair -- counting it in
        `berries_in_a_room_with_no_such_chest` -- rather than crediting the first room that would match."""
        from ..game_data import chest_berries, shops
        mt_battle_shop_room = shops.SHOPS_BY_ROOM[21].room_id
        for berry in (169, 170, 171, 172):
            self.assertIsNone(chest_berries.chest_for(mt_battle_shop_room, berry))


class TestTheGatesActuallyBiteWhereTheyShould(PokemonXDTestBase):
    """ADDENDUM 239b -- the gates verified against a REAL generated world, not against the table that
    declares them.

    Player: "ensure that we have logic in place for WHEN items are gained - aidan's message being after mt
    battle and ONBS crisis being after data rom/id card & cave spot." This walks the key-item ladder and
    checks what opens when."""

    options = {"shuffle_trainer_defeats": True}

    def _state(self, held):
        from BaseClasses import CollectionState
        state = CollectionState(self.multiworld)
        for name in held:
            state.collect(self.multiworld.worlds[1].create_item(name), prevent_sweep=True)
        state.sweep_for_advancements()
        return state

    def _reach(self, location_name, held):
        location = self.multiworld.get_location(location_name, 1)
        return location.can_reach(self._state(held))

    def test_every_shop_opens_exactly_when_its_room_does(self) -> None:
        """The floor under everything else: no shop's first line is reachable earlier or later than the rest
        of the locations filed in its region."""
        from ..game_data import shops as shop_table
        by_region = {}
        for location in self.multiworld.get_locations(1):
            by_region.setdefault(location.parent_region.name, []).append(location)
        empty = self._state([])
        for shop in shop_table.CONFIRMED_SHOPS:
            first = self.multiworld.get_location(shop_table.shop_location_name(shop.name, 1), 1)
            peers = [l for l in by_region[first.parent_region.name] if " AP Item " not in l.name]
            if not peers:
                continue
            self.assertEqual(first.can_reach(empty), peers[0].can_reach(empty), shop.name)

    def test_the_onbs_tiers_are_blocked_without_the_data_rom(self) -> None:
        """The player's own requirement, measured. Agate Village and Gateon Port both sit BEFORE the Data ROM
        in the region chain, so their ONBS lines are the ones where this gate really bites: the room is
        reachable and the line is not."""
        everything_but_the_rom = ["Machine Part", "Music Disc", "Mayor's Note", "Elevator Key", "System Lever"]
        for room_line, gated_line in (("Agate Village Shop AP Item 1", "Agate Village Shop AP Item 9"),
                                      ("Gateon Port Shop AP Item 1", "Gateon Port Shop AP Item 7"),
                                      ("Gateon Port Shop AP Item 1", "Gateon Port Shop AP Item 11")):
            self.assertTrue(self._reach(room_line, everything_but_the_rom), room_line)
            self.assertFalse(self._reach(gated_line, everything_but_the_rom), gated_line)
            self.assertTrue(self._reach(gated_line, [*everything_but_the_rom, "Data ROM & ID Card"]),
                            gated_line)

    def test_gorigans_gateon_tier_needs_the_system_lever(self) -> None:
        """The strictest gate in the game: Gateon's last four lines need the whole chain plus the lever."""
        everything_but_the_lever = ["Machine Part", "Data ROM & ID Card", "Music Disc", "Mayor's Note",
                                    "Elevator Key"]
        for line in ("Gateon Port Shop AP Item 12", "Gateon Port Shop AP Item 15"):
            self.assertTrue(self._reach("Gateon Port Shop AP Item 1", everything_but_the_lever))
            self.assertFalse(self._reach(line, everything_but_the_lever), line)
            self.assertTrue(self._reach(line, [*everything_but_the_lever, "System Lever"]), line)

    def test_the_two_non_binding_gates_are_non_binding_ON_PURPOSE(self) -> None:
        """Recorded so a future reader does not "fix" them.

        Agate line 8 is gated on Mt. Battle (Aidan's email) and Pyrite lines 11-12 on the ONBS crisis, and
        BOTH open at the same moment their room does. That is correct, not a missing rule:

          * `("Agate Village", "Mt. Battle", ())` carries no requirement, so anyone who can stand in the Agate
            shop can walk to Mt. Battle, trigger the email and come back. AP logic asks whether the player CAN
            get something, and they can.
          * Pyrite Town itself is already behind the Data ROM (`("Cipher Lab", "Pyrite Town", ("Data ROM",))`),
            and so is Poke Spots -- so anyone standing in the Pyrite shop has already met every ONBS
            requirement.

        The rules stay wired anyway: they cost nothing, they document the real in-game condition, and if the
        region graph ever gains a requirement on those edges they start biting on their own."""
        just_the_part = ["Machine Part"]
        self.assertTrue(self._reach("Agate Village Shop AP Item 1", just_the_part))
        self.assertTrue(self._reach("Agate Village Shop AP Item 8", just_the_part))

        with_rom = ["Machine Part", "Data ROM & ID Card"]
        for line in ("Pyrite Town Shop AP Item 1", "Pyrite Town Shop AP Item 11",
                     "Pyrite Town Shop AP Item 12"):
            self.assertTrue(self._reach(line, with_rom), line)

    def test_no_gated_line_is_ever_reachable_before_its_own_room(self) -> None:
        """The one invariant that must hold for every gate, binding or not -- a line cannot open before the
        shop it is in."""
        from ..game_data import shop_stock as stock
        from ..game_data import shops as shop_table
        ladders = [
            [], ["Machine Part"], ["Machine Part", "Data ROM & ID Card"],
            ["Machine Part", "Data ROM & ID Card", "Music Disc", "Mayor's Note"],
            ["Machine Part", "Data ROM & ID Card", "Music Disc", "Mayor's Note", "Elevator Key"],
            ["Machine Part", "Data ROM & ID Card", "Music Disc", "Mayor's Note", "Elevator Key",
             "System Lever"],
        ]
        for shop in stock.SHOP_MART_TIERS:
            gated = stock.gated_shop_lines(shop)
            if not gated:
                continue
            room_line = shop_table.shop_location_name(shop, 1)
            for held in ladders:
                room_open = self._reach(room_line, held)
                for numbers, _gate in gated:
                    for number in numbers:
                        line = shop_table.shop_location_name(shop, number)
                        if self._reach(line, held):
                            self.assertTrue(room_open, f"{line} opened before {room_line}")


class TestWhereTheNumbersSitOnTheShelf(unittest.TestCase):
    """ADDENDUM 259 (2026-09-17). Player, looking at a live Agate shelf: "Poke ball and great ball actually
    get moved to the top of the list -- so it'd be poke ball (item 8) great ball item 9, then item 1. Is this
    presentable this way?"

    The observation is correct and it is not a bug. A line's number is fixed by WHEN THE GAME FIRST OFFERS IT
    (ADDENDUM 238c's rule, which the player set: "numbering start at 1 on whatever is available first"), while
    the game reorders its own shelf when a shop restocks -- it promotes the Balls to the top. Those are two
    different orderings, and nothing can make them agree in every tier, because the game changes its mind
    between tiers and a check number is not allowed to.

    Nothing about CORRECTNESS depends on the display order: the berry is written per pool SLOT, so the berry
    the player buys off the top line is berry 8, which credits line 8, which is `Agate Village Shop AP Item
    8`. The live rename writes that number onto the line itself, so finding a given check is a lookup, not a
    count.

    What IS worth pinning, and is the reason this class exists, is the property that makes the current anchor
    the better of the two available ones: **every shop's opening shelf reads 1, 2, 3 ...** Only a RESTOCKED
    tier is ever out of order. Anchoring numbers to the final tier's shelf instead would buy a tidy endgame
    shelf at the cost of an out-of-order opening one -- for most of the playthrough -- and would break the
    player's own stated rule, so this is the trade being defended."""

    def _shelf(self, mart: int) -> "list[int]":
        """The line numbers of one mart's patchable slots, in the order the shop displays them."""
        from ..items import SHOP_EXCLUDED_ITEM_IDS

        first, last, items = S.VANILLA_MARTS[mart]
        numbers = iter(S.MART_LINE_NUMBERS[mart])
        out = []
        for _slot, item in zip(range(first, last + 1), items):
            if item in SHOP_EXCLUDED_ITEM_IDS or not 1 <= item < xd_rel_format.ITEM_REMAP_THRESHOLD_ID:
                continue
            out.append(next(numbers))
        return out

    def test_the_first_shelf_a_player_ever_sees_reads_one_two_three(self) -> None:
        """The guarantee the story-order anchor buys, and the one a future renumbering would have to keep."""
        for shop, entry in S.SHOP_MART_TIERS.items():
            marts = entry["marts"]
            if not marts:
                continue
            shelf = self._shelf(marts[0])
            self.assertEqual(sorted(shelf), shelf,
                             f"{shop}'s opening shelf is out of order: {shelf}")
            self.assertEqual(list(range(1, len(shelf) + 1)), shelf,
                             f"{shop}'s opening shelf must be 1..N with no gaps: {shelf}")

    def test_a_later_tier_may_reorder_and_that_is_the_games_doing_not_ours(self) -> None:
        """The other half of the same fact, asserted rather than left implicit -- if a future patcher change
        ever made every tier ascending, this would fail and someone would have to come back here and find out
        WHY, rather than assuming the reordering had simply been fixed."""
        reordered = [
            (shop, mart)
            for shop, entry in S.SHOP_MART_TIERS.items()
            for mart in entry["marts"][1:]
            if self._shelf(mart) != sorted(self._shelf(mart))
        ]
        self.assertTrue(reordered, "no restocked tier reorders any more -- has the mart table changed?")
        # The Agate case the player reported, named explicitly so it is greppable from their message.
        self.assertIn(("Agate Village Shop", 19), reordered)
        self.assertEqual([8, 9, 1, 2, 3, 4, 5, 6, 7], self._shelf(19),
                         "Agate's final shelf: Poke Ball (8), Great Ball (9), then 1..7")

    def test_a_line_keeps_its_number_across_every_tier_of_its_shop(self) -> None:
        """The property being bought with the out-of-order shelf, and the one that makes it worth it. A
        number that moved between tiers would make one frozen location name mean two different shelf lines at
        two different points in the same playthrough."""
        for shop, entry in S.SHOP_MART_TIERS.items():
            number_of_item: "dict[int, int]" = {}
            for mart in entry["marts"]:
                first, last, items = S.VANILLA_MARTS[mart]
                numbers = iter(S.MART_LINE_NUMBERS[mart])
                from ..items import SHOP_EXCLUDED_ITEM_IDS

                for _slot, item in zip(range(first, last + 1), items):
                    if item in SHOP_EXCLUDED_ITEM_IDS or not 1 <= item < xd_rel_format.ITEM_REMAP_THRESHOLD_ID:
                        continue
                    n = next(numbers)
                    previous = number_of_item.setdefault(item, n)
                    self.assertEqual(previous, n,
                                     f"{shop}: item {item} is line {previous} in one tier and {n} in another")


if __name__ == "__main__":
    unittest.main()
