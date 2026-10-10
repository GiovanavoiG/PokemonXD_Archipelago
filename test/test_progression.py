from BaseClasses import CollectionState

from .. import items as _items
from . import PokemonXDTestBase


class TestKraneMemoGating(PokemonXDTestBase):
    # ADDENDUM 435: with the Parts gate on, Citadark is the Parts-only ride from Gateon in both travel modes, so the
    # key-item chain is measured with the gate off -- the one configuration where the chain is still the way in.
    options = {"robo_kyogre_parts_unlock_citadark": False}
    # RETARGETED 2026-09-13 (ADDENDUM 168). The class name is kept so the file's history stays findable, but
    # there is no Krane Memo gating left to test: the memos are no longer items (items.ITEMS_REMOVED_FROM_POOL)
    # and regions.py's memo ladder was replaced by REGION_EDGES, an explicit graph gated on the real story key
    # items. Ein File S went the same way -- it is not an item in the game at all, so the victory event's
    # `state.has("Ein File S")` access_rule is gone too.
    def test_citadark_isle_victory_requires_the_whole_key_item_chain(self) -> None:
        """The final event location should not be reachable without everything that gates Citadark Isle.

        RETARGETED 2026-09-13 (ADDENDUM 168), was "requires the full Krane Memo chain + Ein File S". Victory
        is now nothing but *reaching* Citadark Isle -- the boss rule is gone and the in-game win is detected by
        Client.py -- so what this protects is that the last region is still the last region: the deepest edge
        in regions.REGION_EDGES needs the System Lever, which sits behind the Mayor's Note, which sits behind
        the Music Disc, and so on back to the Machine Part. Dropping ANY one of the five must close the island.

        only_check_listed=True is kept for the same reason as before: most of this world's other locations also
        sit in regions gated on some prefix of this chain, so assertAccessDependency's default "every other
        location must be reachable without these items" check does not hold here.
        """
        self.assertAccessDependency(
            ["Citadark Isle - Defeat Cipher Boss"],
            [list(self.KEY_ITEM_CHAIN)],
            only_check_listed=True,
        )

    def test_each_single_link_of_the_chain_is_individually_load_bearing(self) -> None:
        """NEW 2026-09-13 (ADDENDUM 168), the half the old memo test could not express.

        `MEMOS_REQUIRED` was a count, so "5 memos" was one requirement wearing five hats and no individual memo
        was separately load-bearing. REGION_EDGES names distinct items on distinct edges, so each one can --
        and must -- be checked on its own: holding four of the five and missing any one must leave Citadark
        Isle shut. Without this, a future edit that collapsed two gates onto one item would pass the test
        above unnoticed.
        """
        victory = "Citadark Isle - Defeat Cipher Boss"
        # ADDENDUM 418: with travel shuffle off the Data ROM & ID Card gates Pyrite Town again, so it is
        # load-bearing for the win like every other link. (Travel mode: see TestTheDataRomIsNotOnThePathToTheWin.)
        for missing in list(self.KEY_ITEM_CHAIN):
            with self.subTest(missing=missing):
                state = CollectionState(self.multiworld)
                self.collect_all_but(list(self.KEY_ITEM_CHAIN), state)
                for name in self.KEY_ITEM_CHAIN:
                    if name != missing:
                        state.collect(self.get_item_by_name(name))
                self.assertFalse(
                    state.can_reach(victory, "Location", self.player),
                    f"Citadark Isle opened without the {missing}",
                )


class TestTheDataRomIsNotOnThePathToTheWin(PokemonXDTestBase):
    """ADDENDUM 406 -- player: "Poke spots do NOT need the data rom. Also, Cipher Lab is not gated by Data Rom -
    just Lovrina, her defeat item, and chest 23." With nothing else gated by it, the win does not need it.

    ADDENDUM 418 narrowed this to travel shuffle ON. Off, Pyrite Town is behind the ROM again -- player: "Every
    pyrite town item in vanilla locations should also be gated behind Data Rom & ID Card" -- so the win needs it
    (TestTheDataRomIsOnThePathInVanillaTravel below)."""

    options = {"key_item_shuffle": True, "randomize_travel_locations": True}

    def _without_the_rom(self):
        state = CollectionState(self.multiworld)
        for item in self.multiworld.itempool:
            if item.player == self.player and item.name != _items.COMBINED_KEY_ITEM_NAME:
                state.collect(item, True)
        state.sweep_for_advancements()
        return state

    def test_every_other_link_wins_without_it(self) -> None:
        state = self._without_the_rom()
        self.assertTrue(state.can_reach("Citadark Isle - Defeat Cipher Boss", "Location", self.player))
        for name in ("Defeat - Lovrina #1", "Cipher Lab Krane Chest", "Lovrina Defeat Item", "Defeat - Naps #2"):
            if name in {l.name for l in self.multiworld.get_locations(self.player)}:
                self.assertFalse(state.can_reach(name, "Location", self.player), name)


class TestTheDataRomIsOnThePathInVanillaTravel(TestTheDataRomIsNotOnThePathToTheWin):
    options = {"key_item_shuffle": True, "randomize_travel_locations": False}

    def test_every_other_link_wins_without_it(self) -> None:
        state = self._without_the_rom()
        # ADDENDUM 435: the win itself is the Parts-only ride from Gateon now, so whether it needs the ROM depends on
        # where this seed's Parts landed (Citadark Story Weight puts most of them past Pyrite). Pyrite is the gate.
        self.assertFalse(state.can_reach("Pyrite Town", "Region", self.player))
        self.assertTrue(state.can_reach("Cipher Lab", "Region", self.player))
