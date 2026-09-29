from . import PokemonXDTestBase
from Fill import distribute_items_restrictive


class TestRealFillBoth(PokemonXDTestBase):
    # REPURPOSED 2026-09-07 (ADDENDUM 33): this used to pair shuffle_overworld_items with shuffle_shadow_captures
    # -- that option (and the "Shadow Defeat" location category it gated) has been deleted outright, per player
    # request, with no substitute check put in its place. Now pairs overworld items with ordinary trainer
    # defeats instead, still exercising the "two categories enabled together" fill path this class was meant to
    # cover. Overworld Items no longer has its own toggle (REMOVED 2026-09-08 -- see options.py) so this class
    # now just exercises "trainer defeats also on" against the always-on Overworld Items category.
    options = {"shuffle_trainer_defeats": True}

    def test_real_fill(self) -> None:
        distribute_items_restrictive(self.multiworld)


# REMOVED 2026-09-15 (ADDENDUM 237): TestRealFillOverworldOnly covered a fill with trainer defeats off, so
# that only the "Overworld Items" group could hold progression. That group is now 29 locations rather than 81
# -- the census retired 52 of them as duplicates of the per-chest locations, with no client detector between
# them -- and a fill restricted to it is no longer possible or desirable. The `overworld_only` setting it
# leaned on is gone with it. The real-fill coverage that matters is TestRealFill above, unchanged.
