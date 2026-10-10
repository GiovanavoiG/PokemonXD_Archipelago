"""ADDENDUM 432 (2026-10-08) -- every Shadow gated by the FIGHT that carries it; purifications counted.

Player: "Make sure purification counts are logically gated behind areas that provide us enough shadow pokemon?
E.g. if agate, gateon and the lab only give us 13 shadow pokemon, any purifications past 13 should be logically
gated behind other areas. ... Lovrina had a shadow pokemon catch in logic too early - it thought it was behind
cipher lab (her first appearance) but it was actually in her citadark team ... The same happened with Ardos ...
Fix Ardos, Zook, Lovrina and Biden" -- then: "make sure to fix that for just any character who appears multiple
times, miror b etc".
"""
from __future__ import annotations

import unittest

from BaseClasses import CollectionState

from . import PokemonXDTestBase
from .. import items, rules
from ..game_data import load_json_data_file, missable_trainers, shadow_regions as SR
from ..game_data import trainer_placements, trainer_roster


def _regions(ddpk: int) -> "set[str]":
    return {gate.region for gate in SR.gates_for_ddpk(ddpk)}


class TestTheGates(unittest.TestCase):
    def test_every_vanilla_shadow_has_a_gate(self):
        dark = load_json_data_file("deckdata_dark_pokemon.json")
        self.assertEqual(83, len(dark))
        for entry in dark:
            self.assertTrue(SR.gates_for_ddpk(entry["ddpk_index"]), entry)

    def test_the_named_cases(self):
        self.assertEqual({"Citadark Isle"}, _regions(48))                  # Lovrina's Farfetch'd
        self.assertEqual({"Citadark Isle"}, _regions(49))                  # Lovrina's Altaria
        self.assertEqual({"Cipher Lab"}, _regions(12))                     # Lovrina's Delcatty: her Lab fight
        for ddpk in (63, 64, 65):
            self.assertEqual({"Citadark Isle"}, _regions(ddpk))            # Ardos's three
        self.assertEqual({"Cipher Key Lair (exterior)"}, _regions(30))     # Zook's Zangoose, not Gateon
        zook = SR.gates_for_ddpk(30)[0]
        self.assertIn("Snagem Hideout", zook.required_regions)

    def test_every_multi_appearance_trainer(self):
        """"just any character who appears multiple times, miror b etc" -- Snattle, Gorigan, Smarton, Miror B."""
        self.assertEqual({"Citadark Isle"}, _regions(61) | _regions(62))   # Snattle, not Phenac
        self.assertEqual({"Citadark Isle"}, _regions(66) | _regions(67))   # Gorigan, not the Key Lair
        self.assertEqual({"Cipher Key Lair"}, _regions(41))                # Smarton, not the SS Libra
        self.assertEqual({"Citadark Isle"}, _regions(80))                  # Miror B.'s post-game Dragonite
        self.assertEqual({"Outskirt Stand"}, _regions(13))                 # Miror B.'s Nosepass row

    def test_a_gate_is_always_a_row_that_carries_the_shadow(self):
        carriers = SR.shadow_carriers()
        for ddpk, rows in carriers.items():
            for gate in SR.gates_for_ddpk(ddpk):
                if gate.source.startswith("fallback"):
                    self.assertTrue(all(trainer_placements.region_for(i) is None or i in SR.NO_SNAG_TRAINER_INDICES
                                        for i in rows), ddpk)
                    continue
                index = int(gate.source.split("#")[1])
                self.assertIn(index, rows)
                self.assertNotIn(index, SR.NO_SNAG_TRAINER_INDICES)
                self.assertEqual(trainer_placements.region_for(index), gate.region)

    def test_the_no_snag_rows(self):
        names = {trainer_roster.TRAINERS_BY_INDEX[i]["name"] for i in SR.NO_SNAG_TRAINER_INDICES}
        self.assertEqual({"ZOOK", "ARDOS", "BIDEN"}, names)
        # ADDENDUM 433, player: "Biden's KEY LAIR fight is uncatchable. Snagem is fine."
        self.assertIn(148, SR.NO_SNAG_TRAINER_INDICES)
        self.assertNotIn(143, SR.NO_SNAG_TRAINER_INDICES)
        self.assertEqual("Cipher Key Lair (exterior)", trainer_placements.region_for(148))
        self.assertEqual("Snagem Hideout", trainer_placements.region_for(143))
        self.assertTrue(SR.NO_SNAG_TRAINER_INDICES <= missable_trainers.shadow_expansion_excluded_trainer_indices())


class _Counted(PokemonXDTestBase):
    """Purify N against a hand-built state: exactly the Shadows its reachable fights carry."""

    def _state_without(self, held_back: "set[str]") -> CollectionState:
        state = CollectionState(self.multiworld)
        for item in self.multiworld.itempool:
            if item.player == self.player and item.name not in held_back and item.advancement:
                state.collect(item, True)
        return state

    def _available(self, state) -> int:
        total = 0
        for ways, count in rules._purification_shadow_groups(self.multiworld.worlds[self.player]):
            if any(all(state.can_reach(r, player=self.player) for r in regions)
                   and all(state.has(i, self.player) for i in held) for regions, held in ways):
                total += count
        return total

    def _reachable(self, state, n: int) -> bool:
        return self.multiworld.get_location(f"Purify {n} Shadow Pokemon", self.player).can_reach(state)

    def _assert_boundary(self, state):
        n = self._available(state)
        if n >= 1:
            self.assertTrue(self._reachable(state, n), n)
        total = self.multiworld.worlds[self.player]._purification_location_count
        if n < total:
            self.assertFalse(self._reachable(state, n + 1), n)
        return n


class TestLocationShuffleCounts(_Counted):
    options = {"randomize_travel_locations": True, "shadow_pokemon_expansion": 20, "randomize_shadow_species": True,
               "robo_kyogre_parts_unlock_citadark": True}

    def test_only_the_early_areas(self):
        unlocks = {name for name in items.ITEM_TABLE if name.startswith("Travel Unlock - ")}
        state = self._state_without(unlocks | {items.MACGUFFIN_ITEM_NAME})
        n = self._assert_boundary(state)
        self.assertLess(n, 40, "with no travel unlocks, most Shadows are out of reach")
        self.assertFalse(state.can_reach("Citadark Isle", player=self.player))

    def test_one_unlock_at_a_time(self):
        unlocks = sorted(name for name in items.ITEM_TABLE if name.startswith("Travel Unlock - "))
        for keep in unlocks:
            with self.subTest(keep=keep):
                self._assert_boundary(self._state_without(set(unlocks) - {keep} | {items.MACGUFFIN_ITEM_NAME}))

    def test_everything_reaches_every_purification(self):
        state = self.multiworld.get_all_state(False)
        total = self.multiworld.worlds[self.player]._purification_location_count
        self.assertEqual(total, self._available(state))
        self.assertTrue(self._reachable(state, total))


class TestVanillaChainCounts(_Counted):
    options = {"randomize_travel_locations": False, "robo_kyogre_parts_unlock_citadark": True}

    def test_without_the_parts_the_citadark_shadows_do_not_count(self):
        state = self._state_without({items.MACGUFFIN_ITEM_NAME})
        n = self._assert_boundary(state)
        total = self.multiworld.worlds[self.player]._purification_location_count
        # Every Citadark Shadow waits -- the island's 36, Ardos's and Lovrina's included, and the post-game Dragonite.
        self.assertLessEqual(n, total - 37)


class TestRemovalCounts(_Counted):
    options = {"randomize_travel_locations": True, "remove_citadark_shadows": True, "remove_greevil_shadows": True,
               "robo_kyogre_parts_unlock_citadark": True}

    def test_moved_shadows_count_where_they_now_are(self):
        state = self._state_without({items.MACGUFFIN_ITEM_NAME})
        self.assertFalse(state.can_reach("Citadark Isle", player=self.player))
        total = self.multiworld.worlds[self.player]._purification_location_count
        # Only Miror B.'s post-game Dragonite still waits on the end game; the island's own 36 moved away.
        self.assertEqual(total - 1, self._assert_boundary(state))


if __name__ == "__main__":
    unittest.main()


class TestTheTrainerTallyCounts(PokemonXDTestBase):
    """The same flaw in the cumulative "Defeat N Trainers" ladder, fixed the same way."""
    options = {"randomize_travel_locations": True, "shuffle_trainer_defeats": True, "trainer_defeat_mode": 0,
               "trainer_defeat_check_count": 114}

    def _available(self, state) -> int:
        total = 0
        for ways, count in rules._trainer_count_groups(self.multiworld.worlds[self.player]):
            if any(all(state.can_reach(r, player=self.player) for r in regions)
                   and all(state.has(i, self.player) for i in held) for regions, held in ways):
                total += count
        return total

    def test_the_boundary_with_one_unlock_at_a_time(self):
        unlocks = sorted(name for name in items.ITEM_TABLE if name.startswith("Travel Unlock - "))
        for keep in [None] + unlocks:
            with self.subTest(keep=keep):
                state = CollectionState(self.multiworld)
                for item in self.multiworld.itempool:
                    if item.player == self.player and item.advancement and (
                            not item.name.startswith("Travel Unlock - ") or item.name == keep):
                        state.collect(item, True)
                n = self._available(state)
                names = [loc.name for loc in self.multiworld.get_locations(self.player)
                         if loc.name.startswith("Defeat ") and loc.name.endswith(" Trainers")]
                self.assertTrue(names)
                by_count = {int(name.split()[1]): name for name in names}
                if n in by_count:
                    self.assertTrue(self.multiworld.get_location(by_count[n], self.player).can_reach(state))
                if n + 1 in by_count:
                    self.assertFalse(self.multiworld.get_location(by_count[n + 1], self.player).can_reach(state))
