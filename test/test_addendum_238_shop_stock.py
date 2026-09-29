"""ADDENDUM 238. Every shop's real stock, its tiers, and the berry labels each tier introduces.

Player: "check EVERY shop for stock that isn't available immediately" and, on Agate: "Agate does show mart 5,
which adds label 4 after receiving aidan's email - this happens after the first mt battle visit."
"""
from __future__ import annotations

import unittest

from ..game_data import shop_stock as S
from ..game_data import shops
from ..items import SHOP_EXCLUDED_ITEM_IDS, USELESS_BERRY_IDS


class TestTheRotationIsReproducible(unittest.TestCase):
    """The whole design rests on the world being able to derive, at generation time, the same berry->slot
    assignment the patcher writes. If that ever stops holding, every shop check points at the wrong line."""

    def test_the_simulation_matches_the_ram_verified_labels(self) -> None:
        self.assertEqual(S.MART_LABELS, S._simulate_rotation())

    def test_every_label_is_a_real_berry_index(self) -> None:
        for mart, labels in S.MART_LABELS.items():
            for label in labels:
                self.assertTrue(1 <= label <= len(USELESS_BERRY_IDS), f"mart {mart}: {label}")

    def test_excluded_ids_never_became_a_label(self) -> None:
        """The Scents and the Poke Snack are preserved, so they must occupy slots with no label."""
        for mart, (first, last, items) in S.VANILLA_MARTS.items():
            kept = sum(1 for i in items if i in SHOP_EXCLUDED_ITEM_IDS)
            self.assertEqual(len(items) - kept, len(S.MART_LABELS[mart]), f"mart {mart}")


class TestAgateMatchesWhatThePlayerSaw(unittest.TestCase):
    """The one shop whose tier ladder is confirmed from live play rather than inferred."""

    def test_the_middle_tier_is_what_the_player_reported(self) -> None:
        """Player: "checks 4-11 are available and 1-3 are not"."""
        self.assertEqual((4, 5, 6, 7, 8, 9, 10, 11), S.MART_LABELS[12])

    def test_the_early_tier_lacks_label_four(self) -> None:
        """Player: "Agate does show mart 5, which adds label 4 after receiving aidan's email"."""
        self.assertNotIn(4, S.MART_LABELS[5])
        self.assertIn(4, S.MART_LABELS[12])

    def test_labels_one_to_three_appear_only_in_the_last_tier(self) -> None:
        """Player: "1-3 will not open till later - therefore needing a later sphere of logic"."""
        for label in (1, 2, 3):
            self.assertNotIn(label, S.MART_LABELS[5])
            self.assertNotIn(label, S.MART_LABELS[12])
            self.assertIn(label, S.MART_LABELS[19])

    def test_the_gate_is_recorded(self) -> None:
        self.assertIn(("Agate Village Shop", 12), S.TIER_GATES)

    def test_agate_has_thirteen_distinct_lines_across_its_tiers(self) -> None:
        distinct = {label for mart in S.SHOP_MART_TIERS["Agate Village Shop"]["marts"]
                    for label in S.MART_LABELS[mart]}
        self.assertEqual(13, len(distinct))
        self.assertGreater(len(distinct), shops.SHOPS_BY_ROOM[134].slot_count,
                           "Agate needs more locations than its current slot_count once lines are checks")


class TestTierStructure(unittest.TestCase):
    def test_an_aliased_mart_introduces_nothing(self) -> None:
        """Marts 7/20 and 9/10/11 are the same pool slice -- one stock list reached twice, not a restock."""
        self.assertEqual(S.MART_LABELS[7], S.MART_LABELS[20])
        self.assertEqual(S.MART_LABELS[9], S.MART_LABELS[10])
        self.assertEqual(S.MART_LABELS[9], S.MART_LABELS[11])
        for shop in ("Gateon Port Herb Shop", "Mt. Battle Shop"):
            tiers = S.new_labels_by_tier(shop)
            self.assertTrue(tiers[0][1], "the first tier must introduce its lines")
            for _mart, new in tiers[1:]:
                self.assertEqual((), new, f"{shop}: an alias must introduce nothing")

    def test_the_battle_sim_tiers_are_disjoint(self) -> None:
        """Three 3-line marts that share no label -- a genuine ladder, not aliases."""
        a, b, c = (set(S.MART_LABELS[m]) for m in (16, 17, 18))
        self.assertEqual(set(), a & b)
        self.assertEqual(set(), a & c)
        self.assertEqual(set(), b & c)

    def test_the_unresolved_marts_are_recorded_rather_than_guessed(self) -> None:
        assigned = {m for entry in S.SHOP_MART_TIERS.values() for m in entry["marts"]}
        self.assertEqual(set(), assigned & set(S.UNRESOLVED_MARTS))
        self.assertEqual(set(S.VANILLA_MARTS), assigned | set(S.UNRESOLVED_MARTS))

    def test_every_confirmed_shop_is_a_real_room(self) -> None:
        for name, entry in S.SHOP_MART_TIERS.items():
            if entry["room"] is None:
                continue
            if entry.get("excluded"):
                # 2026-09-15, player: "Exclude the whole battle CD shop." The mart mapping is kept so the
                # three-tier structure is not lost, but the room is no longer a shop room.
                self.assertNotIn(entry["room"], shops.SHOPS_BY_ROOM, name)
                continue
            self.assertIn(entry["room"], shops.SHOPS_BY_ROOM, name)


class TestPokeSnacksAreNeverACheck(unittest.TestCase):
    """Player: "do not involve poke snacks in checks whatsoever" / "Ensure poke snacks do not affect any
    shop." It holds by construction -- the Snack is in SHOP_EXCLUDED_ITEM_IDS, so the patcher never converts
    it and it never gets a shelf label -- but it is asserted here because it is a standing instruction and a
    silent regression would turn a Snack line into a buyable check."""

    def test_the_snack_is_excluded_from_conversion(self) -> None:
        from ..items import POKE_SNACK_ITEM_ID
        self.assertIn(POKE_SNACK_ITEM_ID, SHOP_EXCLUDED_ITEM_IDS)

    def test_no_snack_line_carries_a_label(self) -> None:
        self.assertTrue(S._snack_and_scent_lines_have_no_label())

    def test_the_marts_that_stock_snacks_drop_exactly_that_many_lines(self) -> None:
        from ..items import POKE_SNACK_ITEM_ID
        carrying = [m for m, (_f, _l, items) in S.VANILLA_MARTS.items() if POKE_SNACK_ITEM_ID in items]
        self.assertTrue(carrying, "expected several marts to stock a Poke Snack")
        for mart in carrying:
            _f, _l, items = S.VANILLA_MARTS[mart]
            snacks = sum(1 for i in items if i == POKE_SNACK_ITEM_ID)
            scents = sum(1 for i in items if i in SHOP_EXCLUDED_ITEM_IDS and i != POKE_SNACK_ITEM_ID)
            self.assertEqual(len(items) - snacks - scents, len(S.MART_LABELS[mart]), f"mart {mart}")


class TestThePlayerSurvey(unittest.TestCase):
    """The mart-to-shop mapping the player read off the shelves, and the gates they reported."""

    def test_the_shops_they_identified(self) -> None:
        # ADDENDUM 238c: Phenac 1F is mart 1 ALONE. The player's own stock table lists exactly mart 1's
        # thirteen lines and puts its only "after meeting Duking in Pyrite Town" note on the POKE SNACK line
        # -- the same note Agate's Snack line carries, so it is the game-wide Snack unlock, not a restock.
        # The earlier (14, 1) reading mistook that per-line note for a mart swap; mart 14 is unassigned again.
        self.assertEqual((1,), S.SHOP_MART_TIERS["Phenac City Shop"]["marts"])
        self.assertNotIn("Phenac City Shop", [n for n, e in S.SHOP_MART_TIERS.items()
                                              if 14 in e["marts"]])
        self.assertEqual((2,), S.SHOP_MART_TIERS["Phenac City Shop 2F"]["marts"])
        self.assertEqual((3, 13), S.SHOP_MART_TIERS["Pyrite Town Shop"]["marts"])

    def test_phenac_needs_its_whole_key_item_chain_before_any_line(self) -> None:
        """A gate on the ROOM, so it applies to the first tier too, not just restocks."""
        for shop in ("Phenac City Shop", "Phenac City Shop 2F"):
            reqs = S.SHOP_ACCESS_REQUIREMENTS[shop]
            self.assertIn("Music Disc", reqs)
            self.assertIn("Mayor's Note", reqs)
            self.assertIn("Realgam Tower", reqs)

    def test_the_onbs_crisis_gates_two_shops_identically(self) -> None:
        # ADDENDUM 238c: the flat "requires" tuple is now split into "regions" and "items", because rules.py
        # builds a real access rule from these and has to know which is which. "Poke Spots (Cave)" was also
        # not a region the region table has -- the Cave Poke Spot lives in "Poke Spots".
        agate = S.TIER_GATES[("Agate Village Shop", 19)]
        pyrite = S.TIER_GATES[("Pyrite Town Shop", 13)]
        self.assertEqual(agate["regions"], pyrite["regions"])
        self.assertEqual(agate["items"], pyrite["items"])
        # ADDENDUM 239b added the region graph's own name for the event alongside the player's two, so the
        # gate follows the graph if that edge ever gains a requirement. Today all three are equivalent.
        self.assertEqual(agate["regions"], ("Pyrite Town", "Poke Spots", "Pyrite Town (ONBS)"))
        self.assertEqual(agate["items"], ("Data ROM",))
        from .. import regions as _regions   # ADDENDUM 250: relative -- see test_addendum_201's own note
        for name in agate["regions"]:
            self.assertIn(name, _regions.REGION_NAMES)

    def test_gateon_is_no_longer_parked(self) -> None:
        """ADDENDUM 238d: the player's Gateon stock table matched mart 15 line for line, and marts 6 and 14
        were the only ones left unclaimed, so the ladder is 6 -> 14 -> 15 by elimination. PENDING_TIER_GATES
        is gone -- both gates are now real entries in TIER_GATES and wired into rules.py."""
        self.assertEqual(S.UNRESOLVED_SHOPS, ())
        self.assertEqual(S.UNRESOLVED_MARTS, ())
        self.assertEqual(S.SHOP_MART_TIERS["Gateon Port Shop"]["marts"], (6, 14, 15))
        self.assertFalse(hasattr(S, "PENDING_TIER_GATES"))
        self.assertEqual(S.TIER_GATES[("Gateon Port Shop", 15)]["items"], ("System Lever",))

    def test_every_mart_is_either_assigned_or_openly_unresolved(self) -> None:
        assigned = {m for e in S.SHOP_MART_TIERS.values() for m in e["marts"]}
        self.assertEqual(set(S.VANILLA_MARTS), assigned | set(S.UNRESOLVED_MARTS))

