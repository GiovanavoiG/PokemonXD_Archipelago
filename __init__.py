"""
Pokemon XD: Gale of Darkness -- Archipelago apworld.

============================================================================================================
STATUS: EXPERIMENTAL SKELETON. This world can generate a solo multiworld (region graph, logic, item
placement) but there is currently NO GAME CLIENT and NO generate_output implementation, so it cannot
actually be played yet. See docs/setup_en.md for what that means and what's still needed.

This exists to prove out the Archipelago World API pattern with a small, honestly-labeled slice of real
Pokemon XD content, per the APWorld Dev FAQ's recommendation to build a "trivial" apworld first
(https://github.com/ArchipelagoMW/Archipelago/blob/main/docs/apworld_dev_faq.md). It intentionally covers a
representative sample of locations/items rather than the full ~130+ check game -- see items.py and
locations.py for what's real vs. placeholder.
============================================================================================================
"""

import os
from collections.abc import Mapping
from typing import Any

from Options import OptionError
from worlds.AutoWorld import World
from worlds.LauncherComponents import Component, SuffixIdentifier, Type, components, launch

from . import items, locations, regions, rules
from .items import ITEM_NAME_GROUPS, ITEM_TABLE, PokemonXDItem
from .locations import LOCATION_NAME_GROUPS, LOCATION_TABLE
from .options import PokemonXDOptions
from .web_world import PokemonXDWebWorld


def launch_client(*args: str) -> None:
    """Launch the Pokemon XD client. Registered as a Launcher component below (mirrors worlds/tww's own
    run_client) -- guarded so that a generation-only install missing dolphin_memory_engine (a real dependency
    only the *client* needs, never generation) doesn't fail to import this whole world."""
    print("Running Pokemon XD Client")
    from .Client import main

    launch(main, name="PokemonXDClient", args=args)


try:
    import dolphin_memory_engine as _dme  # noqa: F401 -- see launch_client's docstring for why this is guarded

    components.append(
        Component(
            "Pokemon XD Client",
            func=launch_client,
            component_type=Type.CLIENT,
            # Matches PokemonXDContainer.patch_file_ending (see patch.py) -- hardcoded rather than imported
            # from there to avoid pulling patch.py (and its worlds.Files dependency) into this guarded,
            # dolphin_memory_engine-optional block just for one string constant.
            file_identifier=SuffixIdentifier(".appxd"),
        )
    )
except ImportError:
    pass


class PokemonXDWorld(World):
    """
    Pokemon XD: Gale of Darkness is a GameCube-exclusive Pokemon spin-off centered on capturing corrupted
    "Shadow Pokemon" from the criminal organization Cipher and purifying them. This is an early, incomplete
    Archipelago implementation covering a representative sample of the game's overworld items and Shadow
    Pokemon captures.
    """

    game = "Pokemon XD Gale of Darkness"
    web = PokemonXDWebWorld()

    options_dataclass = PokemonXDOptions
    options: PokemonXDOptions

    # Arbitrary base id for this world's items/locations. Per docs/world api.md, ids only need to be unique
    # *within this game*, not globally, so this doesn't need to be coordinated with any other world.
    base_id = 3_820_000

    item_name_to_id = items.get_item_name_to_id(base_id)
    location_name_to_id = locations.get_location_name_to_id(base_id)

    item_name_groups = ITEM_NAME_GROUPS
    location_name_groups = LOCATION_NAME_GROUPS

    origin_region_name = "Menu"

    def generate_early(self) -> None:
        # This skeleton's only progression items (the Krane Memo chain + Ein File S) don't have a location of
        # their own to be manually placed on -- they're only meaningful if there's somewhere in the regular
        # itempool/location fill for them to land. Disabling both shuffle categories leaves zero real
        # locations, which would otherwise silently make the game unbeatable. See the APWorld Dev FAQ's
        # "raise an exception during generate_early" guidance for this class of problem.
        if not self.options.shuffle_overworld_items and not self.options.shuffle_shadow_captures:
            raise OptionError(
                f"{self.player_name}'s Pokemon XD Gale of Darkness world has no locations: "
                "shuffle_overworld_items and shuffle_shadow_captures can't both be disabled."
            )

        # 2026-09-02: independent testing (calling Fill.distribute_items_restrictive directly -- see
        # items.py's reclassification note for why WorldTestBase.test_fill silently missed this) found that
        # with only ONE of the two shuffle categories enabled, this world's 19 progression items (12 key items
        # + 6 Evolution Stones + Master Ball) could outnumber the real locations that category provides (+1,
        # the always-included "Catch - Eevee" -- see locations.py's GUARANTEED_SPECIES_LOCATION) -- a
        # "restrictive start"-shaped FillError that previously only surfaced as a cryptic crash deep in the
        # fill algorithm, well after generation had otherwise looked fine. Converted to the same loud, early,
        # APWorld-Dev-FAQ-recommended OptionError pattern as the "both disabled" guard above, computed
        # generically from the real item/location counts rather than hardcoded, so it stays correct as either
        # roster changes size -- e.g. the 2026-09-03 overworld-item expansion (9 -> 48 real locations) made
        # shuffle_overworld_items-only generation comfortably safe (49 available vs. 19 progression) without
        # needing any change here; shuffle_shadow_captures-only (10 available vs. 19 progression) still isn't,
        # and correctly still raises.
        progression_item_count = sum(
            1 for data in ITEM_TABLE.values() if data.classification == items.ItemClassification.progression
        )
        available_location_count = 1  # "Catch - Eevee" -- always included, see locations.py
        if self.options.shuffle_overworld_items:
            available_location_count += len(locations.LOCATION_NAME_GROUPS["Overworld Items"])
        if self.options.shuffle_shadow_captures:
            available_location_count += len(locations.LOCATION_NAME_GROUPS["Shadow Captures"])
        if progression_item_count > available_location_count:
            raise OptionError(
                f"{self.player_name}'s Pokemon XD Gale of Darkness world has {progression_item_count} "
                f"progression items but only {available_location_count} locations able to hold one with "
                "the current shuffle_overworld_items/shuffle_shadow_captures settings -- enable both shuffle "
                "options (the world isn't yet balanced for single-category play at this item-pool size)."
            )

    def create_regions(self) -> None:
        regions.create_and_connect_regions(self)

    def create_items(self) -> None:
        item_pool: list[PokemonXDItem] = []

        # Only true progression items are unconditionally forced into the pool -- they're the only ones with a
        # logic dependency (see rules.py). Non-progression "useful" items (PP Up, Rare Candy, the evolution
        # stones added 2026-09-02) are nice-to-have, not logic-required, so they're folded into the same random
        # filler selection below instead of being force-included one each. (Forcing every "useful" item in
        # regardless of location count is what broke `shuffle_overworld_items`-only / `shuffle_shadow_captures`
        # -only generation once the 6 evolution stones were added -- 9 real locations, 15 would-be-mandatory
        # items. Progression-only forcing avoids that "restrictive start"-style failure mode by construction:
        # progression item count is fixed at 7 regardless of what's added to USEFUL_ITEMS/STONE_ITEMS later.)
        for name, data in ITEM_TABLE.items():
            if data.classification.name == "progression":
                item_pool.append(self.create_item(name))

        # Filler pads out the rest of the pool to match the number of locations. get_filler_item_name() below
        # draws from FILLER_ITEMS plus the non-progression "useful" items, so those still show up when there's
        # room without being guaranteed to all fit.
        total_locations = len(self.multiworld.get_unfilled_locations(self.player))
        while len(item_pool) < total_locations:
            item_pool.append(self.create_filler())

        self.multiworld.itempool += item_pool

    def create_item(self, name: str) -> PokemonXDItem:
        return items.create_item(self, name)

    def get_filler_item_name(self) -> str:
        return items.get_random_filler_item_name(self)

    def set_rules(self) -> None:
        rules.set_all_rules(self)

    def fill_slot_data(self) -> Mapping[str, Any]:
        return self.options.as_dict("shuffle_overworld_items", "shuffle_shadow_captures", "include_traps")

    def generate_output(self, output_directory: str) -> None:
        # Follows worlds/tww's precedent (also a GameCube game): the apworld itself only ever produces a
        # small, inspectable seed/placement file -- never a full ISO or a diff against one. See patch.py's
        # module docstring for why, and apply_patch.py at the repo root for the companion tool that turns
        # this file plus the player's own legally-owned ISO into a playable patched disc.
        from .game_data.trainer_census import load_trainer_census, serialize_trainer_pools
        from .patch import PokemonXDContainer
        from .randomizer.team_shuffle import TeamShuffleOptions, shuffle_teams

        seed_data: dict[str, Any] = {
            "player": self.player,
            "player_name": self.player_name,
            "seed_name": self.multiworld.seed_name,
            "game": self.game,
            "location_to_game_item_id": {},
            "trainer_team_assignments": None,
            "notes": [],
        }

        for location in self.multiworld.get_locations(self.player):
            item = location.item
            if item is None or item.player != self.player:
                # Either unfilled (shouldn't happen post-fill) or another player's item -- nothing for this
                # player's Pokemon XD ISO to receive; the owning game's own output handles it.
                continue
            item_data = ITEM_TABLE.get(item.name)
            seed_data["location_to_game_item_id"][location.name] = {
                "item_name": item.name,
                "game_item_id": item_data.game_item_id if item_data else None,
            }

        census = load_trainer_census()
        if census is not None:
            species_pool, trainer_pools = census
            shuffle_teams(
                trainer_pools,
                species_pool,
                TeamShuffleOptions(legendary_safe=True),
                self.random,
            )
            seed_data["trainer_team_assignments"] = serialize_trainer_pools(trainer_pools)
        else:
            seed_data["notes"].append(
                "No trainer census data available in this build -- trainer-team species were NOT "
                "randomized for this seed. See pokemon_xd/game_data/trainer_census.py: drop a real "
                "pokemon_xd/data/trainer_census.json (extracted from a real ISO) in to enable this."
            )

        out_path = os.path.join(
            output_directory,
            f"{self.multiworld.get_out_file_name_base(self.player)}{PokemonXDContainer.patch_file_ending}",
        )
        container = PokemonXDContainer(
            path=out_path,
            player=self.player,
            player_name=self.player_name,
            seed_data=seed_data,
        )
        container.write()
