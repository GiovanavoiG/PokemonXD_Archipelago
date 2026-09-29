from BaseClasses import CollectionState

from . import PokemonXDTestBase


class TestKraneMemoGating(PokemonXDTestBase):
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
        for missing in self.KEY_ITEM_CHAIN:
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
