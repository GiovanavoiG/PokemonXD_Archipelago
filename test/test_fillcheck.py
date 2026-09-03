from . import PokemonXDTestBase
from Fill import distribute_items_restrictive


class TestRealFillBoth(PokemonXDTestBase):
    options = {"shuffle_overworld_items": True, "shuffle_shadow_captures": True}

    def test_real_fill(self) -> None:
        distribute_items_restrictive(self.multiworld)


class TestRealFillOverworldOnly(PokemonXDTestBase):
    # 2026-09-03: the Bulbapedia-sourced overworld-item expansion (9 -> 48 real locations) means this
    # combination is now comfortably safe on its own (49 available incl. the guaranteed Eevee catch, vs. 19
    # progression items) -- previously (skeleton era, 9 real overworld locations) this combination correctly
    # raised OptionError instead. See __init__.py's generate_early() comment.
    options = {"shuffle_overworld_items": True, "shuffle_shadow_captures": False}

    def test_real_fill(self) -> None:
        distribute_items_restrictive(self.multiworld)


class TestRealFillShadowOnly(PokemonXDTestBase):
    # 2026-09-03, second correction: the real, sourced Shadow Capture roster expansion (9-location sample ->
    # 83 real locations, see locations.py's module docstring and data/shadow_pokemon_list.json) makes this
    # combination safe too now (84 available incl. the guaranteed Eevee catch, comfortably vs. 19 progression
    # items) -- this class used to be TestShadowOnlyRaisesOptionError, asserting the OLD skeleton-era 9-location
    # sample correctly raised OptionError. That assertion is no longer true (confirmed live: the OptionError
    # stopped firing the moment the roster grew), so this now tests the positive case instead, mirroring
    # TestRealFillOverworldOnly above.
    options = {"shuffle_overworld_items": False, "shuffle_shadow_captures": True}

    def test_real_fill(self) -> None:
        distribute_items_restrictive(self.multiworld)
