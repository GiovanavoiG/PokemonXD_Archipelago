"""
Pokemon XD: Gale of Darkness -- Archipelago apworld.

generate_output() writes a small `.appxd` seed file, `tools/iso_patcher.py` applies the one thing RAM cannot
(trainer-team species) to the player's own ISO copy, and `Client.py` drives the rest over the Dolphin bridge.

Levels compose in one order everywhere: path scaling sets the base, Enhanced Difficulty's 1.33x multiplies
it. Never apply the multiplier twice.
"""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from typing import Any

from BaseClasses import LocationProgressType
from Options import OptionError
from worlds.AutoWorld import World
from worlds.LauncherComponents import (Component, SuffixIdentifier, Type, components, icon_paths,
                                      launch)

from . import catch_sources, items, locations, regions, rules, species
from .items import (
    CHEST_DUMMY_GAME_ITEM_ID,
    CHEST_DUMMY_GAME_ITEM_NAME,
    ITEM_NAME_GROUPS,
    ITEM_TABLE,
    SHOP_EXCLUDED_ITEM_IDS,
    USELESS_BERRY_ID_TO_NAME,
    USELESS_BERRY_IDS,
    PokemonXDItem,
)
from .locations import LOCATION_NAME_GROUPS, LOCATION_TABLE
from .options import PokemonXDOptions
from .web_world import PokemonXDWebWorld


def launch_client(*args: str) -> None:
    """Launch the Pokemon XD client (mirrors worlds/tww's run_client). `args` is accepted for symmetry with
    the other `launch_*` functions here; CommonClient's entry point has nothing to do with it."""
    print("Running Pokemon XD Client")
    from .Client import main

    launch(main, name="PokemonXDClient", args=args)


def launch_client_or_patch(*args: str) -> None:
    """The one Launcher entry point for Pokemon XD: a `.appxd` argument patches the player's ISO and stops,
    no argument connects. Patching deliberately does not chain into the client -- the ISO still has to be
    loaded in Dolphin, so a client started the instant patching finished had nothing to hook."""
    seed_path = args[0] if args and str(args[0]).endswith(".appxd") else None

    if seed_path:
        from .launcher_patch import prompt_and_patch

        # prompt_and_patch has already told the player what to do next, or reported the cancel.
        prompt_and_patch(seed_path)
        return

    try:
        launch_client()
    except ImportError:
        # dolphin_memory_engine isn't installed here. A silent no-op would look like a broken button.
        from Utils import messagebox

        messagebox(
            "Pokemon XD Client - Error",
            "Could not start the Pokemon XD client: the dolphin_memory_engine package isn't installed.\n\n"
            "Install it (e.g. \"pip install dolphin_memory_engine\") and try again.",
            error=True,
        )


# `ap:` URI, not a file path: kvui resolves it with pkgutil.get_data, which reads out of a zipped
# .apworld too (ADDENDUM 271). `__name__`, since the package name differs between those two cases.
icon_paths["Pokemon XD"] = f"ap:{__name__}/assets/launcher_icon.png"

components.append(
    Component(
        "Pokemon XD Client",
        icon="Pokemon XD",
        func=launch_client_or_patch,
        component_type=Type.CLIENT,
        # Matches PokemonXDContainer.patch_file_ending (patch.py); hardcoded to avoid a worlds.Files import.
        file_identifier=SuffixIdentifier(".appxd"),
        # No `description=` on purpose -- the player asked for no subtitle line. Do not re-add one unasked.
    )
)


class PokemonXDWorld(World):
    """
    Pokemon XD: Gale of Darkness is a GameCube-exclusive Pokemon spin-off centered on capturing corrupted
    "Shadow Pokemon" from the criminal organization Cipher and purifying them.
    """

    game = "Pokemon XD Gale of Darkness"
    web = PokemonXDWebWorld()

    options_dataclass = PokemonXDOptions
    options: PokemonXDOptions

    # Arbitrary base id: ids only need to be unique within this game, not across worlds.
    base_id = 3_820_000

    item_name_to_id = items.get_item_name_to_id(base_id)
    location_name_to_id = locations.get_location_name_to_id(base_id)

    item_name_groups = ITEM_NAME_GROUPS
    location_name_groups = LOCATION_NAME_GROUPS

    origin_region_name = "Menu"

    def generate_early(self) -> None:
        # Cached on self: fill_slot_data() and generate_output() both need it and race each other.
        self._shadow_species_assignment: dict[str, Any] | None = None
        # Always populated (ADDENDUM 43), option or no option.
        self._pokespot_species_assignment: list[dict[str, Any]] | None = None
        self._obtainable_species_dex: set[int] | None = None
        # ADDENDUM 155: cached here, not in generate_output() -- it and fill_slot_data() race in one pool.
        self._trainer_team_pools: Any | None = None
        self._trainer_species_by_dpkm_index: dict[int, int] | None = None
        self._trainer_team_fingerprints: dict[str, list[str]] | None = None
        # ADDENDUM 299: this seed's tier ordering, from pre_output(). None means "use the intended path".
        self._path_tier_by_region: "dict[str, int] | None" = None
        self._build_trainer_team_shuffle()

        # The real bound is this seed's expansion setting (83 vanilla + the expansion's add), not the option's
        # 127 ceiling, so it is checked here rather than in the Range.
        _vanilla_shadow_count = 83
        try:
            from .game_data.shadow_regions import total_shadow_count

            _counted = total_shadow_count()
            if _counted:
                _vanilla_shadow_count = _counted
        except Exception:  # noqa: BLE001 -- a missing census must not take generation down over a bound check
            pass
        _purifiable = _vanilla_shadow_count + int(self.options.shadow_pokemon_expansion)
        if int(self.options.purification_progression_cap) > _purifiable:
            raise OptionError(
                f"Pokemon XD ({self.player_name}): 'Purification Checks That Can Hold Progression' is "
                f"{int(self.options.purification_progression_cap)}, but this seed only contains "
                f"{_purifiable} Shadow Pokemon to purify ({_vanilla_shadow_count} vanilla + "
                f"{int(self.options.shadow_pokemon_expansion)} from 'Shadow Pokemon Expansion'). Lower the "
                f"cap to at most {_purifiable}, or raise 'Shadow Pokemon Expansion'."
            )

        # The Machine Part is sphere zero in every mode: it repairs the scooter AND progresses the HQ Lab,
        # where the Snag Machine comes from. It gated 573 of 677 locations with travel randomization off and 0
        # of 675 with it on (ADDENDUM 106 opens Agate), where fill put it in sphere 6-7.
        if items.requirement_to_pool_item("Machine Part") in items.GATING_KEY_ITEM_NAMES and \
                bool(getattr(self.options, "key_item_shuffle", 1)):
            self.multiworld.early_items[self.player][
                items.requirement_to_pool_item("Machine Part")
            ] = 1

        # ADDENDUM 162: a goal needing more Parts than exist is unwinnable; caught here, not in fill.
        if self.options.robo_kyogre_parts_unlock_citadark:
            required = int(self.options.robo_kyogre_parts_required)
            available = int(self.options.robo_kyogre_parts_available)
            if required > available:
                raise OptionError(
                    f"Pokemon XD ({self.player_name}): Citadark Isle needs {required} Robo Kyogre Parts, but "
                    f"only {available} exist in this multiworld, so it could never be reached. Raise "
                    f"'Robo Kyogre Parts Available' to at least {required}, or lower "
                    f"'Robo Kyogre Parts Required'."
                )

        # `shuffle_overworld_items` is gone: Overworld Items are always checks, so the old "both off" guard
        # cannot fire. The count check stays -- too few holdable locations surfaces as a FillError deep in
        # fill.
        progression_item_count = sum(
            1 for data in ITEM_TABLE.values() if data.classification == items.ItemClassification.progression
        )
        available_location_count = 1 + len(locations.LOCATION_NAME_GROUPS["Overworld Items"])  # Eevee, always
        if self.options.shuffle_trainer_defeats:
            # Only NAMED defeat locations count; cumulative buckets are EXCLUDED and never hold progression.
            available_location_count += len(locations.LOCATION_NAME_GROUPS["Trainer Defeats"])
        if progression_item_count > available_location_count:
            raise OptionError(
                f"{self.player_name}'s Pokemon XD Gale of Darkness world has {progression_item_count} "
                f"progression items but only {available_location_count} locations able to hold one with "
                "the current shuffle_trainer_defeats setting -- enable it (the world isn't yet balanced for "
                "single-category play at this item-pool size)."
            )

        # Shadow species randomization (ADDENDUM 17) only changes which species stands at a Shadow encounter.
        # The pool loads UNCONDITIONALLY: the obtainable-species set decides which "Catch - {species}"
        # locations exist at all (ADDENDUM 43). Here, not generate_output(), because fill_slot_data() runs
        # first.
        from .game_data.real_shadow_data import load_real_shadow_pool
        from .tools.xd_species_index import INTERNAL_INDEX_TO_NATIONAL_DEX, national_dex_for

        shadow_pool = load_real_shadow_pool()

        # ADDENDUM 198: the LEVEL must settle before the SPECIES. The shuffle evolves each pick against
        # PokemonInstance.level, and the pool carries VANILLA levels -- a Shadow fielded at 66 was evolved as
        # a 17.
        if shadow_pool is not None:
            from .game_data.real_trainer_data import real_shadow_census
            from .randomizer.enhanced_difficulty import (
                cap_for_option as _ed_cap,
                shadow_level_assignment,
            )

            # ADDENDUM 287: this gate must match generate_output()'s. A test compares them as text.
            _ed_scale = bool(self.options.enhanced_difficulty_level_scaling)
            _path_scale = bool(self.options.path_level_scaling)
            if _ed_cap(self.options.enhanced_difficulty.value) != 0 or _ed_scale or _path_scale:
                _census = real_shadow_census()
                if _census:
                    # Must be the PATH average: shadow_level_assignment joins on it.
                    if _path_scale:
                        from .game_data.real_trainer_data import real_trainer_team_census
                        from .randomizer.path_level_scaling import build_path_level_plan
                        _team = real_trainer_team_census()
                        if _team:
                            _, _by_trainer = build_path_level_plan(_team)
                            _census = [
                                {**_record, "team_avg_level": float(_by_trainer[_record["trainer_index"]])}
                                if _record.get("trainer_index") in _by_trainer else _record
                                for _record in _census
                            ]
                    # Path levels are already scaled, so the multiplier must not be applied again here.
                    _shadow_dpkm_levels, _ = shadow_level_assignment(
                        _census, scale_levels=_ed_scale and not _path_scale,
                    )
                    for _trainer in shadow_pool.trainers:
                        for _mon in _trainer.team:
                            _final = _shadow_dpkm_levels.get(_mon.index)
                            if _final is not None:
                                _mon.level = _final

        shadow_obtainable_dex: set[int] = set()
        # ADDENDUM 183: recorded now because the shadow pool is shuffled IN PLACE -- re-loading it at
        # set_rules time returns vanilla species and gates the wrong ones. Labels, not regions.
        self._shadow_catch_labels: dict[int, list[str]] = {}
        self._shadow_catch_expansion_hosts: dict[int, list[int]] = {}
        if shadow_pool is not None:
            if self.options.randomize_shadow_species:
                from .game_data.real_trainer_data import real_species_pool
                from .randomizer.team_shuffle import TeamShuffleOptions, shuffle_teams

                # Snapshot vanilla species and location name first: shuffle_teams() reassigns in place.
                original_by_index = {
                    mon.index: (mon.species_id, trainer.name)
                    for trainer in shadow_pool.trainers
                    for mon in trainer.team
                }
                # legendary_safe=False: Shadows randomize into anything; the dedup keeps the map one-to-one.
                shuffle_teams(
                    [shadow_pool],
                    real_species_pool(),
                    TeamShuffleOptions(legendary_safe=False),
                    self.random,
                )
                entries: list[dict[str, Any]] = []
                for trainer in shadow_pool.trainers:
                    for mon in trainer.team:
                        original_species_index, location_name = original_by_index[mon.index]
                        orig_dex, orig_name = INTERNAL_INDEX_TO_NATIONAL_DEX.get(original_species_index, (None, None))
                        new_dex, new_name = INTERNAL_INDEX_TO_NATIONAL_DEX.get(mon.species_id, (None, None))
                        entries.append({
                            "dpkm_index": mon.index,
                            "location": location_name,
                            "original_species_index": original_species_index,
                            "original_dex": orig_dex,
                            "original_name": orig_name,
                            "new_species_index": mon.species_id,
                            "new_dex": new_dex,
                            "new_name": new_name,
                        })
                self._shadow_species_assignment = {"pool": shadow_pool, "entries": entries}
            # Each slot's CURRENT species_id, shuffled or vanilla: what a player can really get this seed.
            for trainer in shadow_pool.trainers:
                for mon in trainer.team:
                    dex = national_dex_for(mon.species_id)
                    if dex is not None:
                        shadow_obtainable_dex.add(dex)
                        # This slot's fixed AP location name. A list, so callers take the earliest.
                        self._shadow_catch_labels.setdefault(dex, []).append(trainer.name)

        # ADDENDUM 99: built HERE, because generate_early has already decided which "Catch - {species}"
        # locations exist. Rebuilding it later off the same self.random would change the plan.
        self._shadow_expansion_plans: list[dict[str, Any]] | None = None
        if self.options.shadow_pokemon_expansion > 0:
            from .game_data.real_shadow_data import vanilla_shadow_species
            from .game_data.real_trainer_data import MT_BATTLE_TRAINER_INDICES, real_species_pool, real_trainer_free_slot_census
            from .game_data.real_moveset_data import load_level_up_moves
            from .randomizer.shadow_expansion import build_shadow_expansion_plans
            from .randomizer.enhanced_difficulty import ENHANCED_DIFFICULTY_LEVEL_MULTIPLIER

            expansion_free_slot_census = real_trainer_free_slot_census()
            expansion_species_pool = real_species_pool()
            expansion_excluded_species = vanilla_shadow_species()

            # ADDENDUM 199: exclude the POST-SHUFFLE Shadow species, not just the vanilla 83 -- with the
            # shuffle on, the vanilla list fences off nothing that exists (16 of 44 generated Shadows
            # duplicated a live one, seed 4242). Union, not replacement: shadow_species.py's table is still
            # keyed by vanilla species.
            if self._shadow_species_assignment and expansion_excluded_species is not None:
                expansion_excluded_species = expansion_excluded_species | {
                    entry["new_species_index"]
                    for entry in self._shadow_species_assignment["entries"]
                    if entry.get("new_species_index") is not None
                }
            # ADDENDUM 325: the gift Eevee line goes to every player; a Shadow on one reads as a purification.
            if expansion_excluded_species is not None:
                from .species import EEVEELUTION_DEX_NUMBERS
                from .tools.xd_species_index import internal_index_for_national_dex

                _gift_line = {133} | set(EEVEELUTION_DEX_NUMBERS)
                expansion_excluded_species = expansion_excluded_species | {
                    index for index in (internal_index_for_national_dex(dex) for dex in _gift_line)
                    if index is not None
                }
            from .game_data import missable_trainers  # ADDENDUM 236 -- the exclusion set below
            expansion_level_up_moves = load_level_up_moves()
            if (
                expansion_free_slot_census
                and expansion_species_pool
                and expansion_excluded_species is not None
                and expansion_level_up_moves
            ):
                # A no-op frozenset(): MT_BATTLE_TRAINER_INDICES is permanently empty by design (ADDENDUM 92).
                self._shadow_expansion_plans = build_shadow_expansion_plans(
                    expansion_free_slot_census,
                    expansion_species_pool,
                    expansion_level_up_moves,
                    expansion_excluded_species,
                    self.options.shadow_pokemon_expansion.value,
                    self.random,
                    # ADDENDUM 236: was empty, so catches landed on re-fightable and missable trainers.
                    excluded_trainer_indices=frozenset(
                        (MT_BATTLE_TRAINER_INDICES if self.options.exclude_mt_battle_trainers else frozenset())
                    ) | missable_trainers.shadow_expansion_excluded_trainer_indices(),
                    # ADDENDUM 198: carries the 1.33x onto a generated Shadow, matching its team.
                    level_multiplier=(
                        ENHANCED_DIFFICULTY_LEVEL_MULTIPLIER
                        if self.options.enhanced_difficulty_level_scaling else 1.0
                    ),
                )
                for plan in self._shadow_expansion_plans:
                    for mon in plan["new_pokemon"]:
                        dex = national_dex_for(mon["species"])
                        if dex is not None:
                            shadow_obtainable_dex.add(dex)
                            # A generated Shadow is keyed by its HOST TRAINER's index, never a label.
                            self._shadow_catch_expansion_hosts.setdefault(dex, []).append(
                                int(plan["trainer_index"])
                            )

        # Poke Spot reassignment (ADDENDUM 43): always on, no toggle. Prefers species the Shadow pool does not
        # already cover, and is cached for the same two readers.
        from .game_data.pokespot_data import assign_pokespot_species

        self._pokespot_species_assignment = assign_pokespot_species(shadow_obtainable_dex, self.random)
        pokespot_obtainable_dex = {entry["new_dex"] for entry in self._pokespot_species_assignment}

        # What a player can catch this seed; locations.create_regions_and_locations decides the "Catch -
        # {species}" set from it. None means don't trim -- the 11 Poke Spot species alone would gut the list.
        self._obtainable_species_dex: set[int] | None = (
            None if shadow_pool is None
            else shadow_obtainable_dex | pokespot_obtainable_dex | {133}  # 133 = Eevee, always guaranteed
        )

    def _build_trainer_team_shuffle(self) -> None:
        """Runs the ordinary-trainer team shuffle once and derives the per-trainer team fingerprints.

        The live battle roster gives a trainer's SURNAME and the species on the field, nothing else -- enough
        for the 109 uniquely-named trainers, but not for MIROR B. (nine), CHOBIN (seven) and the rest, where
        counting defeats and dispatching in story order breaks on an out-of-order rematch. Only DPKM slots
        are fingerprinted, and only ambiguous surnames, since each entry costs slot_data bytes."""
        from .game_data.real_trainer_data import dpkm_species_assignment, load_real_trainer_pools
        from .game_data import trainer_roster
        from .randomizer.team_shuffle import TeamShuffleOptions, shuffle_teams
        from .randomizer.enhanced_difficulty import ENHANCED_DIFFICULTY_LEVEL_MULTIPLIER
        from .game_data.species_base_hp import max_hp_band
        from .tools.xd_species_index import national_dex_for

        real_census = load_real_trainer_pools()
        if real_census is not None:
            species_pool, trainer_pools = real_census
            shuffle_teams(trainer_pools, species_pool, TeamShuffleOptions(legendary_safe=True), self.random)

            # The evolution pass does NOT run here: it needs the final level, and since ADDENDUM 299 the ramp
            # follows this seed's sphere order, which fill decides. It lives in pre_output() -- after fill,
            # before generate_output and fill_slot_data, single-threaded.
            self._trainer_team_pools = trainer_pools
            self._trainer_species_by_dpkm_index = dpkm_species_assignment(trainer_pools)

        self._build_trainer_fingerprints()

    def _build_trainer_fingerprints(self, final_levels: "dict[int, int] | None" = None) -> None:
        """The fingerprints, split out of the shuffle so they can be rebuilt.

        They have to be: `pre_output` re-levels every member and re-resolves its evolution, so a fingerprint
        built before that describes species the ISO does not contain. `final_levels` is {dpkm_index: the
        level shipped} and REPLACES the census's vanilla level: max HP is the client's primary axis, and a
        vanilla-level band cannot hold a scaled HP."""
        from .game_data import trainer_roster
        from .game_data.species_base_hp import max_hp_band
        from .randomizer.enhanced_difficulty import ENHANCED_DIFFICULTY_LEVEL_MULTIPLIER
        from .tools.xd_species_index import national_dex_for

        assignment = self._trainer_species_by_dpkm_index or {}
        fingerprints: dict[str, dict[str, Any]] = {}
        for trainer in trainer_roster.TRAINERS:
            if trainer["total_with_name"] < 2:
                continue  # unambiguous by surname alone -- nothing to discriminate
            names: list[str] = []
            levels: list[int] = []
            hp_bands: dict[str, list[int]] = {}
            hp_bands_enhanced: dict[str, list[int]] = {}
            shadow_slots = 0
            for slot in trainer["team"]:
                dpkm_index = slot.get("dpkm_index")
                if dpkm_index is None:
                    shadow_slots += 1  # a DDPK/Shadow slot -- see this method's docstring
                    continue
                # Both are the game's MASTER internal species index, so both go through `national_dex_for`.
                # NOT national_dex_for_live_species, which is live RAM's compacted index with slots 252-276
                # squeezed out: on deck data it mis-names every Gen III species.
                internal = assignment.get(dpkm_index, slot.get("species"))
                # The level this seed really ships: a vanilla-level band cannot hold a path-scaled HP.
                level = slot.get("level") if final_levels is None else final_levels.get(
                    dpkm_index, slot.get("level"))
                if isinstance(level, int) and level > 0:
                    levels.append(level)
                if internal is None:
                    continue
                dex = national_dex_for(internal)
                name = species.NATIONAL_DEX.get(dex) if dex is not None else None
                if not name:
                    continue
                name = name.upper()
                names.append(name)
                # ADDENDUM 157: max-HP band at this level. All 386 species covered; a gap means an unknown.
                if isinstance(level, int) and level > 0 and dex is not None:
                    band = max_hp_band(dex, level)
                    if band:
                        hp_bands[name] = list(band)
                    # Both lists ship and agree: the client tests against EITHER, and seeds rely on it.
                    enhanced_level = level if final_levels is not None else max(
                        1, min(100, math.floor(level * ENHANCED_DIFFICULTY_LEVEL_MULTIPLIER))
                    )
                    enhanced_band = max_hp_band(dex, enhanced_level)
                    if enhanced_band:
                        hp_bands_enhanced[name] = list(enhanced_band)
            if not names:
                continue
            fingerprints[trainer_roster.trainer_label(trainer)] = {
                "species": sorted(set(names)),
                # ADDENDUM 156: both level sets ship so a match cannot depend on the seed's difficulty.
                # `enhanced` is floor(level * the multiplier), recomputed here because the plan races this.
                "levels": sorted(levels),
                "levels_enhanced": sorted(levels) if final_levels is not None else sorted(
                    max(1, min(100, math.floor(level * ENHANCED_DIFFICULTY_LEVEL_MULTIPLIER)))
                    for level in levels
                ),
                # base_party_size is a LOWER BOUND, never equality: padding only ADDs. hp_bands is [lowest,
                # highest MaxHP] at this level -- a band, because the deck's IVs/EVs are unknown.
                "hp_bands": hp_bands,
                "hp_bands_enhanced": hp_bands_enhanced,
                "base_party_size": len(names),
                # Shadow slots are not fingerprinted, but the count keeps base_party_size honest.
                "shadow_slots": shadow_slots,
            }
        self._trainer_team_fingerprints = fingerprints or None

    # pre_output is the only hook that is after fill, before both generate_output and write_multidata, and
    # single-threaded. generate_early cannot own it: the ramp now depends on this seed's sphere order.
    def pre_output(self) -> None:
        self._path_tier_by_region = self._resolve_path_tier_order()
        self._apply_final_levels_and_evolution()

    def _resolve_path_tier_order(self) -> "dict[str, int] | None":
        """`{region: tier index}` for this seed, or None to keep the intended path.

        None whenever the answer would be a guess: the option is off, or the sphere walk found nothing.
        Callers then fall back to each region's own `story_bytes.region_floor`, keeping the old ramp."""
        if not bool(self.options.path_level_scaling):
            return None
        try:
            from .randomizer.path_level_scaling import region_by_trainer_index, sphere_tier_order

            wanted = set(region_by_trainer_index().values())
            spheres = self._region_spheres(wanted)
            if not spheres:
                return None
            return sphere_tier_order(spheres, wanted)
        except Exception:
            # A level ramp is not worth failing a generation over; the intended path is still correct.
            return None

    def _region_spheres(self, wanted: "set[str]") -> "dict[str, int]":
        """`{region: the sphere it first becomes reachable in}`, walked over the filled multiworld.

        Regions are recorded BEFORE each sphere's items are collected, so a region opened BY sphere N's items
        is N+1. Deterministic despite iterating sets: only `first[region]`, an integer, escapes."""
        from BaseClasses import CollectionState

        state = CollectionState(self.multiworld)
        locations = set(self.multiworld.get_filled_locations())
        first: "dict[str, int]" = {}
        index = 0
        while True:
            for region in wanted:
                if region not in first and state.can_reach_region(region, self.player):
                    first[region] = index
            sphere = {location for location in locations if location.can_reach(state)}
            if not sphere:
                break
            locations -= sphere
            for location in sphere:
                state.collect(location.item, True)
            index += 1
        return first

    def _apply_final_levels_and_evolution(self) -> None:
        """Re-level every ordinary member and re-resolve its evolution against the level the ISO will carry.

        `final_ordinary_levels` composes the path ramp, the ADDENDUM 295 per-team spread and Enhanced
        Difficulty's multiplier, and that composition lives in one place -- do not add a second. The
        fingerprints are rebuilt afterwards, because this changes both the species and the levels."""
        trainer_pools = self._trainer_team_pools
        if trainer_pools is None:
            return
        from .game_data.real_trainer_data import (
            dpkm_species_assignment,
            load_real_trainer_pools,
            real_trainer_team_census,
        )
        from .randomizer.path_level_scaling import final_ordinary_levels
        from .randomizer.team_shuffle import resolve_natural_evolution

        ed_scaling = bool(self.options.enhanced_difficulty_level_scaling)
        path_scaling = bool(self.options.path_level_scaling)
        final_levels: "dict[int, int]" = {}
        if ed_scaling or path_scaling:
            census = real_trainer_team_census()
            real = load_real_trainer_pools()
            if census and real is not None:
                species_pool, _pools = real
                final_levels = final_ordinary_levels(
                    census, path_scaling=path_scaling, ed_scaling=ed_scaling,
                    tier_by_region=self._path_tier_by_region,
                )
                for pool in trainer_pools:
                    for trainer in pool.trainers:
                        for mon in trainer.team:
                            level = final_levels.get(mon.index)
                            if level is None:
                                continue
                            mon.level = level
                            mon.species_id = resolve_natural_evolution(
                                mon.species_id, level, species_pool,
                            )
                self._trainer_species_by_dpkm_index = dpkm_species_assignment(trainer_pools)
        self._relevel_generated_shadows()
        self._build_trainer_fingerprints(final_levels or None)

    # ADDENDUM 339: a generated Shadow took its trainer's VANILLA team average, because the expansion scales
    # the census average by Enhanced Difficulty alone -- so generated levels climbed with TRAINER INDEX while
    # their teams followed this seed's sphere order. On a real filled seed 22 of 25 were off their team:
    # MESIN/TORKIN 20 vs 49-51, JAVION/TEKOT 14 vs 25-27, EXINN/GRECK 21-22 vs 16-18. Re-matched here through
    # path_level_by_trainer, the source generate_output uses for the 83 vanilla Shadows. The species is NOT
    # re-evolved: the obtainable set and `Catch -` locations key off generate_early's choice.
    def _relevel_generated_shadows(self) -> None:
        """Re-level the expansion's Shadows to their trainer's path-scaled team, in place. No-op when path
        scaling is off -- the expansion's own Enhanced Difficulty handling is then already correct."""
        plans = self._shadow_expansion_plans
        if not plans or not bool(self.options.path_level_scaling):
            return
        from .randomizer.enhanced_difficulty import ENHANCED_DIFFICULTY_LEVEL_MULTIPLIER
        from .randomizer.path_level_scaling import level_by_trainer_index

        by_trainer = level_by_trainer_index(tier_by_region=self._path_tier_by_region)
        if bool(self.options.enhanced_difficulty_level_scaling):
            by_trainer = {index: max(1, min(100, int(level * ENHANCED_DIFFICULTY_LEVEL_MULTIPLIER)))
                          for index, level in by_trainer.items()}
        self._generated_shadows_relevelled = 0
        for plan in plans:
            level = by_trainer.get(int(plan["trainer_index"]))
            if level is None:
                # No known region, so no place on the ramp -- the expansion's vanilla average stands.
                continue
            for mon in plan["new_pokemon"]:
                if mon["level"] != level:
                    self._generated_shadows_relevelled += 1
                mon["level"] = level

    def create_regions(self) -> None:
        regions.create_and_connect_regions(self)

    def create_items(self) -> None:
        item_pool: list[PokemonXDItem] = []

        # Only true progression items are force-added -- the only ones with a logic dependency. Forcing every
        # "useful" item in is what broke overworld-items-only generation (9 locations, 15 mandatory items).
        # Travel Unlocks and the MacGuffin are the exceptions: each only matters when its own option is on.
        macguffin_count = (
            int(self.options.robo_kyogre_parts_available)
            if self.options.robo_kyogre_parts_unlock_citadark
            else 0
        )
        for _ in range(macguffin_count):
            item_pool.append(self.create_item(items.MACGUFFIN_ITEM_NAME))

        include_travel_unlocks = bool(self.options.randomize_travel_locations)
        # ADDENDUM 168: with the shuffle off the key items stay vanilla; the graph still gates on them.
        shuffle_key_items = bool(getattr(self.options, "key_item_shuffle", 1))
        shuffle_scooter_upgrade = bool(getattr(self.options, "shuffle_scooter_upgrade", 0))
        for name, data in ITEM_TABLE.items():
            if data.classification.name == "progression":
                if name in items.TRAVEL_UNLOCK_ITEMS and not include_travel_unlocks:
                    continue
                if name == items.MACGUFFIN_ITEM_NAME:
                    continue  # ADDENDUM 162 -- its count is the option's, added above, not one-each here
                # ADDENDUM 168: the names the player dropped. Their five LOCATIONS stay.
                if name in items.ITEMS_REMOVED_FROM_POOL:
                    continue
                if name in items.NEVER_SHUFFLED_KEY_ITEM_NAMES:
                    continue  # left vanilla in every mode -- see that set's own comment
                if name in items.GATING_KEY_ITEM_NAMES and not shuffle_key_items:
                    continue  # vanilla placement; the graph still gates on it
                # ADDENDUM 273: off means the item is never created and regions.py drops the SS Libra edge.
                if name in items.OPTION_GATED_PROGRESSION_ITEMS and not shuffle_scooter_upgrade:
                    continue
                item_pool.append(self.create_item(name))

        # ADDENDUM 150: useful items had never once been placed. Fill.py only puts them on DEFAULT or PRIORITY
        # locations, and with 19 non-EXCLUDED locations against 19 progression items there were none -- each
        # dropped draw also starved the filler EXCLUDED locations need. Force-added now, capped by real room.
        unfilled = self.multiworld.get_unfilled_locations(self.player)
        total_locations = len(unfilled)
        default_capacity = sum(
            1 for location in unfilled
            if location.progress_type != LocationProgressType.EXCLUDED
        )
        # Useful items may repeat, up to USEFUL_ITEM_MAX_COPIES each -- one copy apiece is ~120 items against
        # several hundred DEFAULT locations. Not unlimited, or nothing is left for filler.
        useful_budget = max(0, default_capacity - len(item_pool))
        if useful_budget:
            # ITEMS_REMOVED_FROM_POOL was only checked by the progression pass, so `useful` names slipped in.
            useful_names = sorted(
                name for name, data in ITEM_TABLE.items()
                if data.classification.name == "useful"
                and name not in items.ITEMS_REMOVED_FROM_POOL
            )
            self.random.shuffle(useful_names)
            draws = (useful_names * items.USEFUL_ITEM_MAX_COPIES)[:useful_budget]
            for name in draws:
                item_pool.append(self.create_item(name))

        # The rest is filler, which EXCLUDED locations require one each of; the cap keeps that supply intact.
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
        slot_data: dict[str, Any] = dict(
            self.options.as_dict(
                "randomize_shadow_species",
                "randomize_chests", "shuffle_trainer_movesets", "shuffle_trainer_defeats",
                "trainer_defeat_check_count", "trainer_defeat_mode",
                "shadow_pokemon_expansion", "enhanced_difficulty",
                "exclude_mt_battle_trainers", "randomize_travel_locations", "randomize_shops", "goal",
                "death_link",  # ADDENDUM 351 -- the client turns the DeathLink tag on from this
                "agate_village_pit_stop",  # ADDENDUM 311 -- the client stops treating Agate's shop as a shop
                # ADDENDUM 196: both options are gone -- the area memory arms off randomize_travel_locations.
                "key_item_shuffle",
                "shuffle_scooter_upgrade",
                "robo_kyogre_parts_unlock_citadark", "robo_kyogre_parts_required",
                # Only the toggle travels; the per-seed plans are heavy and only iso_patcher.py needs them.
            )
        )
        if self._trainer_team_fingerprints:
            # ADDENDUM 155: {location -> that trainer's real species}, ambiguous surnames only -- which Dosk.
            slot_data["trainer_team_fingerprints"] = self._trainer_team_fingerprints
        if self._shadow_species_assignment is not None:
            # Per-seed dex -> location map for the client's live detection, preferred over shadow_species.py's
            # static vanilla map. Also backs !shadowdex, so the original name and dex ride along.
            slot_data["shadow_species_map"] = [
                {
                    "location": entry["location"],
                    "original_dex": entry["original_dex"],
                    "original_name": entry["original_name"],
                    "new_dex": entry["new_dex"],
                    "new_name": entry["new_name"],
                }
                for entry in self._shadow_species_assignment["entries"]
            ]
        # ADDENDUM 318: the GENERATED Shadows' species, so the purification scan sees the whole set.
        if getattr(self, "_shadow_expansion_plans", None):
            from .tools.xd_species_index import national_dex_for as _dex_for
            _generated_dex = sorted({
                dex for plan in self._shadow_expansion_plans for mon in plan["new_pokemon"]
                if (dex := _dex_for(mon["species"])) is not None
            })
            if _generated_dex:
                slot_data["generated_shadow_dex"] = _generated_dex
        if self._pokespot_species_assignment is not None:
            # ADDENDUM 43: spoiler only -- catch locations are detected by species identity, wherever caught.
            slot_data["pokespot_species_map"] = [
                {
                    "pool": entry["pool"],
                    "slot_index": entry["slot_index"],
                    "vanilla_dex": entry["vanilla_dex"],
                    "vanilla_name": entry["vanilla_name"],
                    "new_dex": entry["new_dex"],
                    "new_name": entry["new_name"],
                }
                for entry in self._pokespot_species_assignment
            ]
        # ADDENDUM 310: "Catch - {species}" -> where it is caught this seed, for /catches; a datapackage name
        # cannot carry it. ADDENDUM 251: the location-table fingerprint, sent unconditionally.
        slot_data["catch_sources"] = catch_sources.sources_by_location(self)
        slot_data["location_table_fingerprint"] = locations.LOCATION_TABLE_FINGERPRINT
        slot_data["location_count"] = len(locations.LOCATION_TABLE)
        return slot_data

    def extend_hint_information(self, hint_data: "dict[int, dict[int, str]]") -> None:
        """Every "Catch - {species}" hint names who holds that species this seed and where. The per-seed
        half a location name cannot carry; see catch_sources.py."""
        texts = catch_sources.sources_by_location(self)
        if not texts:
            return
        by_id: "dict[int, str]" = {}
        for name, text in texts.items():
            location = self.multiworld.get_location(name, self.player)
            if location.address is not None:
                by_id[location.address] = text
        if by_id:
            hint_data.setdefault(self.player, {}).update(by_id)

    def generate_output(self, output_directory: str) -> None:
        # Follows worlds/tww: this writes a small, inspectable seed file, never an ISO or a diff.
        from .game_data.real_moveset_data import load_level_up_moves
        from .game_data.real_trainer_data import (
            MT_BATTLE_TRAINER_INDICES,
            dpkm_species_assignment,
            load_real_trainer_pools,
            real_species_pool,
            real_trainer_team_census,
        )
        from .game_data.mtbattle_trainer_data import MT_BATTLE_ALL_TRAINER_INDICES, mtbattle_team_census
        from .game_data.trainer_census import load_trainer_census, serialize_trainer_pools
        from .patch import PokemonXDContainer
        from .game_data.real_trainer_data import real_shadow_census
        from .randomizer.enhanced_difficulty import (
            ENHANCED_DIFFICULTY_LEVEL_MULTIPLIER,
            adjust_team_census_for_reserved_slots,
            build_enhanced_difficulty_plan,
            cap_for_option as _enhanced_difficulty_cap,
            shadow_level_assignment,
        )
        # ADDENDUM 266: the ramp comes from story_bytes' entry floors, not a hand-written ordering.
        from .randomizer.path_level_scaling import (
            FIRST_TIER_LEVEL as PATH_FIRST_TIER_LEVEL,
            LAST_TIER_LEVEL as PATH_LAST_TIER_LEVEL,
            MIN_LEVEL as PATH_MIN_LEVEL,
            MAX_LEVEL as PATH_MAX_LEVEL,
            build_mt_battle_path_level_plan,
            build_path_level_plan,
            mt_battle_ramp_top,
            final_ordinary_levels,
            level_by_trainer_index as path_level_by_trainer,
            describe as describe_path_ramp,
        )

        def _path_scaled(level: "int | float") -> int:
            """Enhanced Difficulty's multiplier applied over a path level. Floored, matching
            `enhanced_difficulty._scaled_level` -- the two must round the same way."""
            return max(1, min(100, int(level * ENHANCED_DIFFICULTY_LEVEL_MULTIPLIER)))
        # ADDENDUM 99: built once in generate_early(); this reuses self._shadow_expansion_plans.
        from .randomizer.team_shuffle import TeamShuffleOptions, assign_movesets, shuffle_teams

        seed_data: dict[str, Any] = {
            "player": self.player,
            "player_name": self.player_name,
            "seed_name": self.multiworld.seed_name,
            "game": self.game,
            "location_to_game_item_id": {},
            "trainer_team_assignments": None,
            # {dpkm_index: new_internal_species_index}, byte-exact keys into DeckData_Story.bin. From the
            # ISO-extracted roster, not trainer_census.json, which has no join key back to real bytes.
            "trainer_species_by_dpkm_index": None,
            # A constant id, not per-seed: every chest gets the same reserved item. None when off.
            "chest_dummy_item_id": None,
            "shuffled_key_item_chest_ids": [],   # ADDENDUM 177 -- see the write below
            # A rotating LIST of useless berries (26 since ADDENDUM 117 dropped Enigma Berry), not one id --
            # the rotation identifies each shop at runtime. Excluded: Agate's Scents and Poke Snack.
            "shop_dummy_item_ids": None,
            "shop_excluded_item_ids": None,
            # {str(game_item_id): vanilla display name} for every dummy this seed plants. iso_patcher uses the
            # keys as the rename list and the values as apply_item_name_rename's expected-original-name check.
            "item_rename_target_names": None,
            # Every item with a known game_item_id, the "valid id" universe for the read-only shop scan.
            "known_item_id_names": {
                str(data.game_item_id): name
                for name, data in items.ITEM_TABLE.items()
                if data.game_item_id is not None
            },
            # {dpkm_index: [4 move ids, 0-padded]}. iso_patcher writes them into DeckData_Story.bin's DPKM
            # 'moves' field at offset +0x14, in the same pass as the species write.
            "trainer_moves_by_dpkm_index": None,
            # {"{pool}:{slot_index}": species index}, the shape apply_pokespot_species() consumes.
            "pokespot_species_by_slot": None,
            # ADDENDUM 285: only the percentage travels. The plan's input is the ISO's OWN base-experience
            # table, which the patcher has open and generation does not -- shipping 386 species' values per
            # seed is the mismatch class ADDENDUM 245 came from. 100 is vanilla and writes nothing.
            "experience_rate": 100,
            # ADDENDUM 291: a plain flag -- the work happens at patch time against the ISO's own move table.
            "disable_move_animations": False,
            # Same: the stats table and in-use DDPK catch-rate overrides are read off the ISO at patch time.
            "max_catch_rate": False,
            # The shape write_shadow_multi_trainer_patch() consumes: trainer_index plus its new_pokemon.
            "new_shadow_pokemon_plans": None,
            # {"level_assignment", "new_dpkm_entries", "team_slot_plan"}. Ordinary slots only, never Shadow.
            "enhanced_difficulty_plan": None,
            # Same shape, against Mt. Battle's own DeckData_Hundred.bin census and trainer_index namespace.
            "mt_battle_enhanced_difficulty_plan": None,
            "notes": [],
        }

        for location in self.multiworld.get_locations(self.player):
            item = location.item
            if item is None or item.player != self.player:
                # Unfilled, or another player's item -- their own game's output handles it.
                continue
            item_data = ITEM_TABLE.get(item.name)
            seed_data["location_to_game_item_id"][location.name] = {
                "item_name": item.name,
                "game_item_id": item_data.game_item_id if item_data else None,
            }

        # ADDENDUM 155: consumes generate_early()'s cached result; re-shuffling would break the fingerprints.
        trainer_pools = self._trainer_team_pools
        if trainer_pools is not None:
            seed_data["trainer_team_assignments"] = serialize_trainer_pools(trainer_pools)
            seed_data["trainer_species_by_dpkm_index"] = {
                str(dpkm_index): new_species
                for dpkm_index, new_species in (self._trainer_species_by_dpkm_index or {}).items()
            }

            # Runs AFTER shuffle_teams(), so movesets are drawn for each slot's FINAL species. Only ordinary
            # (DPKM) pools are in trainer_pools, so "Shadow Pokemon keep their moves" holds without a check.
            if self.options.shuffle_trainer_movesets:
                level_up_moves = load_level_up_moves()
                if level_up_moves is not None:
                    # move_count omitted on purpose -- assign_movesets' own MOVESET_SHUFFLE_DEFAULT_MOVE_COUNT
                    # (4 since ADDENDUM 217). It was 3 from ADDENDUM 35 for a measured DeckData_Story.bin LZSS
                    # budget overflow that black-screened the game. Do not pin a number here.
                    moves_assignment = assign_movesets(trainer_pools, level_up_moves, self.random)
                    seed_data["trainer_moves_by_dpkm_index"] = {
                        str(dpkm_index): moves for dpkm_index, moves in moves_assignment.items()
                    }
                    seed_data["notes"].append(
                        "shuffle_trainer_movesets: all 4 move slots on each ordinary trainer Pokemon are "
                        "randomized among moves its species could plausibly know by that level, including its "
                        "level-1 move. This was capped at 3 slots (and excluded level-1 moves) from ADDENDUM "
                        "35/75 until ADDENDUM 217 re-measured the DeckData_Story.bin compression budget and "
                        "found 4 now fits. A slot with fewer than 4 real learnable moves at its level is left "
                        "empty, same as many vanilla Pokemon already are."
                    )
                else:
                    seed_data["notes"].append(
                        "shuffle_trainer_movesets is enabled but no real level-up-moveset ISO data was "
                        "available in this build -- trainer movesets were NOT shuffled for this seed. See "
                        "pokemon_xd/game_data/real_moveset_data.py: drop a real pokemon_xd/data/"
                        "species_level_up_moves.json (extracted from a real ISO via tools/xd_rel_format.py) "
                        "in to enable this."
                    )
        else:
            seed_data["notes"].append(
                "No real trainer census data available in this build -- trainer-team species were NOT "
                "randomized for this seed, and tools/iso_patcher.py will have nothing to patch. See "
                "pokemon_xd/game_data/real_trainer_data.py: drop a real pokemon_xd/data/"
                "deckdata_story_trainers.json (extracted from a real ISO via tools/xd_deck_format.py) in "
                "to enable this."
            )
            # Preview only: no dpkm_index join key, so it is not appliable to a real ISO.
            legacy_census = load_trainer_census()
            if legacy_census is not None:
                legacy_species_pool, legacy_pools = legacy_census
                shuffle_teams(legacy_pools, legacy_species_pool, TeamShuffleOptions(legendary_safe=True), self.random)
                seed_data["trainer_team_assignments"] = serialize_trainer_pools(legacy_pools)
                seed_data["notes"].append(
                    "trainer_team_assignments above is from the hand-transcribed (partial, 68-trainer) census "
                    "for preview purposes only -- it is NOT what would be patched into an ISO."
                )

        # Merges into the SAME trainer_species_by_dpkm_index dict; the index spaces are disjoint.
        if self._shadow_species_assignment is not None:
            shadow_assignment = dpkm_species_assignment([self._shadow_species_assignment["pool"]])
            if seed_data["trainer_species_by_dpkm_index"] is None:
                seed_data["trainer_species_by_dpkm_index"] = {}
            for dpkm_index, new_species in shadow_assignment.items():
                seed_data["trainer_species_by_dpkm_index"][str(dpkm_index)] = new_species
            # Spoiler list. iso_patcher.py only reads trainer_species_by_dpkm_index above.
            seed_data["shadow_species_assignment"] = self._shadow_species_assignment["entries"]
        elif self.options.randomize_shadow_species:
            seed_data["notes"].append(
                "randomize_shadow_species is enabled but no real Shadow Pokemon ISO data was available in "
                "this build -- Shadow Pokemon species were NOT randomized for this seed. See "
                "pokemon_xd/game_data/real_shadow_data.py: drop a real pokemon_xd/data/"
                "deckdata_dark_pokemon.json (extracted from a real ISO) in to enable this."
            )

        # A fixed dummy id, not per-seed: every chest gets the same reserved item (Rabuta Berry since ADDENDUM
        # 31), so the chest patch is identical across seeds. A missing value means chests off.
        if self.options.randomize_chests:
            seed_data["chest_dummy_item_id"] = CHEST_DUMMY_GAME_ITEM_ID
            # ADDENDUM 177: the five key-item chests KeyItemShuffle pools must be dummied too, or the player
            # gets the real key item AND the shuffled one, and every gate on them falls to the vanilla copy.
            # In the seed so the ISO and the location table follow one list.
            from .game_data import key_item_chests

            seed_data["shuffled_key_item_chest_ids"] = sorted(
                key_item_chests.chest_ids_to_convert(bool(self.options.key_item_shuffle))
            )
            # ADDENDUM 218: per-chest berry identity, fixed rather than seed-random -- the client must
            # identify a chest without the seed's table. In the seed anyway, so both come from one
            # computation.
            from .game_data import chest_berries

            seed_data["chest_berry_assignment"] = {
                str(chest): [berry, quantity]
                for chest, (berry, quantity) in sorted(chest_berries.CHEST_BERRY_ASSIGNMENT.items())
            }

        # Shop randomization (ADDENDUM 110/111). USELESS_BERRY_IDS is a DIFFERENT reserved set from chests'
        # Rabuta Berry -- reusing Rabuta would corrupt ChestCountTracker. The order identifies each shop.
        if self.options.randomize_shops:
            seed_data["shop_dummy_item_ids"] = list(USELESS_BERRY_IDS)
            seed_data["shop_excluded_item_ids"] = sorted(SHOP_EXCLUDED_ITEM_IDS)
            # ADDENDUM 311: read by iso_patcher's shop pass; only meaningful when that pass runs at all.
            seed_data["agate_village_pit_stop"] = bool(self.options.agate_village_pit_stop)

        # Covers whichever dummies this seed plants: shop berries, chest berries, both or neither.
        item_rename_targets: dict[int, str] = {}
        if self.options.randomize_shops:
            item_rename_targets.update(USELESS_BERRY_ID_TO_NAME)
        if self.options.randomize_chests:
            # ADDENDUM 218: all seven reserved chest berries now, not just the historical single dummy.
            item_rename_targets.update(items.CHEST_BERRY_ID_TO_NAME)
        if item_rename_targets:
            seed_data["item_rename_target_names"] = {
                str(item_id): name for item_id, name in sorted(item_rename_targets.items())
            }

        # ADDENDUM 43: reuses generate_early()'s cached assignment, same reason as the Shadow merge above.
        if self._pokespot_species_assignment is not None:
            seed_data["pokespot_species_by_slot"] = {
                f"{entry['pool']}:{entry['slot_index']}": entry["new_species_index"]
                for entry in self._pokespot_species_assignment
            }
            # Human-readable spoiler list, same role as shadow_species_assignment above.
            seed_data["pokespot_species_assignment"] = self._pokespot_species_assignment

        # Shadow Pokemon Expansion (ADDENDUM 70). Reuses self._shadow_expansion_plans; rebuilding it off the
        # same self.random would disagree with this seed's locations. shadow_slots_consumed_by_trainer is what
        # ED's census subtracts before padding -- same pre-patch free-slot count, expansion writes first.
        shadow_slots_consumed_by_trainer: dict[int, int] = {}
        if self.options.shadow_pokemon_expansion > 0:
            if self._shadow_expansion_plans is not None:
                shadow_expansion_plans = self._shadow_expansion_plans
                seed_data["new_shadow_pokemon_plans"] = shadow_expansion_plans
                shadow_slots_consumed_by_trainer = {
                    p["trainer_index"]: len(p["new_pokemon"]) for p in shadow_expansion_plans
                }
                added_count = sum(len(p["new_pokemon"]) for p in shadow_expansion_plans)
                seed_data["notes"].append(
                    f"shadow_pokemon_expansion: {added_count} brand-new Shadow Pokemon added across "
                    f"{len(shadow_expansion_plans)} trainers (requested "
                    f"{self.options.shadow_pokemon_expansion.value}, clamped to the real 44-slot disc-format "
                    "ceiling and to however much real free-team-slot capacity this build's trainer census "
                    "actually has). Trainers with a free team slot are filled round-robin, one new Shadow "
                    "Pokemon per eligible trainer per pass, spreading new content across as many different "
                    "trainers as possible before any trainer gets a second one. Each new Shadow Pokemon's "
                    "species also got its own \"Catch - {species}\" location this seed (ADDENDUM 99)."
                )
            else:
                seed_data["notes"].append(
                    "shadow_pokemon_expansion is enabled but the real ISO data it needs (trainer free-slot "
                    "census, species pool, vanilla Shadow species list, and/or level-up moveset data) wasn't "
                    "fully available in this build -- no new Shadow Pokemon were added for this seed."
                )

        # Enhanced Difficulty: ordinary-only padding plus a level boost, never touching
        # DeckData_DarkPokemon.bin. ADDENDUM 197 split it into a Choice and a Toggle, so this runs when EITHER
        # is on.
        ed_added_members = _enhanced_difficulty_cap(self.options.enhanced_difficulty)
        ed_scale_levels = bool(self.options.enhanced_difficulty_level_scaling)
        # ADDENDUM 266: levels follow the INTENDED path, not the order a player really reaches areas in --
        # that order is unknown at patch time. Runs through the SAME block as ED, because two writers of
        # `level_assignment` disagree: path sets the base level, ED's 1.33x multiplies it.
        seed_data["experience_rate"] = int(self.options.experience_rate.value)
        # ADDENDUM 384: the formula divisor the patcher will write, chosen here so the seed carries the
        # decision rather than the patcher re-deriving it from the rate.
        from .game_data.species_stats import choose_exp_divisor
        seed_data["exp_divisor"] = choose_exp_divisor(int(self.options.experience_rate.value))
        seed_data["disable_move_animations"] = bool(self.options.disable_move_animations)
        seed_data["max_catch_rate"] = bool(self.options.max_catch_rate)

        path_scale_levels = bool(self.options.path_level_scaling)
        if ed_added_members != 0 or ed_scale_levels or path_scale_levels:
            ed_team_census = real_trainer_team_census()
            ed_species_pool = real_species_pool()
            ed_level_up_moves = load_level_up_moves()
            if ed_team_census and ed_species_pool and ed_level_up_moves:
                # Subtract the expansion's claim before ED plans padding, or trainers are over-committed.
                ed_team_census = adjust_team_census_for_reserved_slots(ed_team_census, shadow_slots_consumed_by_trainer)
                # A no-op frozenset(): MT_BATTLE_TRAINER_INDICES is permanently empty here.
                enhanced_difficulty_plan = build_enhanced_difficulty_plan(
                    ed_team_census,
                    ed_species_pool,
                    ed_level_up_moves,
                    self.random,
                    excluded_trainer_indices=MT_BATTLE_TRAINER_INDICES if self.options.exclude_mt_battle_trainers else frozenset(),
                    max_added_members=ed_added_members,
                    scale_levels=ed_scale_levels,
                )
                # ADDENDUM 198: vanilla Shadows match their trainer's team average, then scale. Their levels
                # live in DPKM records the DDPK table points at, disjoint from every listed slot. ADDENDUM
                # 266: the path ramp is applied AFTER ED and overrides it.
                path_averages: "dict[int, float]" = {}
                if path_scale_levels:
                    # ADDENDUM 269: one shared composer, so the evolution pass and this write cannot disagree.
                    # ADDENDUM 299: all four calls take pre_output()'s tier ordering, passed, never
                    # re-derived.
                    _tier_order = self._path_tier_by_region
                    path_levels = final_ordinary_levels(
                        ed_team_census, path_scaling=True, ed_scaling=ed_scale_levels,
                        tier_by_region=_tier_order,
                    )
                    _raw_path, path_averages = build_path_level_plan(
                        ed_team_census, tier_by_region=_tier_order,
                    )
                    if ed_scale_levels:
                        path_averages = {index: float(_path_scaled(level))
                                         for index, level in path_averages.items()}
                    enhanced_difficulty_plan["level_assignment"].update(path_levels)
                    # ADDENDUM 383: the padded members have to follow the ramp too. ADDENDUM 339 fixed this
                    # for the expansion's generated Shadows (`_relevel_generated_shadows`) and stopped there,
                    # so Enhanced Difficulty's own additions kept the level `build_enhanced_difficulty_plan`
                    # gave them: the trainer's VANILLA team average, times the multiplier. With path scaling
                    # on, that is a baseline the originals no longer use -- trainer 147's team of four went
                    # from 26 to 62 while its new member arrived at 34. Same `path_averages` the note below
                    # counts, keyed through `team_slot_plan` because an entry does not carry its trainer.
                    _relevelled_additions = 0
                    for _entry, _slot in zip(enhanced_difficulty_plan["new_dpkm_entries"],
                                             enhanced_difficulty_plan["team_slot_plan"]):
                        _average = path_averages.get(int(_slot["trainer_index"]))
                        if _average is None:
                            continue        # no known region, so no place on the ramp: vanilla stands
                        _level = max(PATH_MIN_LEVEL, min(PATH_MAX_LEVEL, int(_average)))
                        if _entry["level"] != _level:
                            _relevelled_additions += 1
                        _entry["level"] = _level
                    if _relevelled_additions:
                        seed_data["notes"].append(
                            f"path_level_scaling: re-levelled {_relevelled_additions} Enhanced Difficulty "
                            "team additions to their trainer's place on the ramp, not its vanilla average."
                        )
                    seed_data["notes"].append(
                        "path_level_scaling: re-levelled "
                        f"{len(path_levels)} team members across {len(path_averages)} trainers by their "
                        "region's own place on the game's intended path (its story-byte floor), from level "
                        f"{PATH_FIRST_TIER_LEVEL} in the opening areas to {PATH_LAST_TIER_LEVEL} at Citadark "
                        "Isle. Trainers with no known placement kept their vanilla levels."
                    )
                    seed_data["notes"].extend(describe_path_ramp(tier_by_region=_tier_order))

                shadow_census = real_shadow_census()
                if shadow_census:
                    # A Shadow matches its trainer's TEAM AVERAGE, so a re-levelled team must be re-matched.
                    if path_scale_levels:
                        # Every trainer with a known region, not just the census: nine carry a Shadow and no
                        # ordinary member, and kept vanilla levels -- 11, 17, 46, 57 among the ramp's fives.
                        by_trainer = path_level_by_trainer(tier_by_region=_tier_order)
                        if ed_scale_levels:
                            by_trainer = {index: _path_scaled(level)
                                          for index, level in by_trainer.items()}
                        # ADDENDUM 370: `level_source` marks records based on a TIER LEVEL rather than a team
                        # average, so they are not floored at the vanilla Shadow level -- without it 57 of 83
                        # kept vanilla levels on moved teams.
                        shadow_census = [
                            {**record,
                             "team_avg_level": float(by_trainer[record["trainer_index"]]),
                             "level_source": "path"}
                            if record.get("trainer_index") in by_trainer else record
                            for record in shadow_census
                        ]
                    shadow_dpkm_levels, shadow_ddpk_levels = shadow_level_assignment(
                        # Path levels are already scaled, so the multiplier must not apply twice.
                        shadow_census, scale_levels=ed_scale_levels and not path_scale_levels,
                    )
                    enhanced_difficulty_plan["level_assignment"].update(shadow_dpkm_levels)
                    enhanced_difficulty_plan["shadow_level_assignment"] = shadow_ddpk_levels
                    seed_data["notes"].append(
                        f"enhanced_difficulty: matched {len(shadow_dpkm_levels)} vanilla Shadow Pokemon to "
                        f"their trainer's own team average level"
                        + (f" and scaled them to {ENHANCED_DIFFICULTY_LEVEL_MULTIPLIER}x"
                           if ed_scale_levels else " (level scaling is off, so they were matched but not "
                                                   "boosted)")
                        + ". A Shadow on a team that has no ordinary members keeps its own level, there "
                          "being no team to average."
                    )
                    # ADDENDUM 316: seven Shadows share a trainer with another fight; earliest wins.
                    from .game_data.shadow_holders import describe_resolution
                    # ADDENDUM 370: the level actually written, not the holder's vanilla team average.
                    seed_data["notes"].extend(describe_resolution(shadow_ddpk_levels))
                seed_data["enhanced_difficulty_plan"] = enhanced_difficulty_plan
                seed_data["notes"].append(
                    f"enhanced_difficulty: scaled the level of "
                    f"{len(enhanced_difficulty_plan['level_assignment'])} existing team members to "
                    f"{ENHANCED_DIFFICULTY_LEVEL_MULTIPLIER}x their original level (rounded down) and added "
                    f"{len(enhanced_difficulty_plan['new_dpkm_entries'])} new ordinary team members across "
                    f"{len(set(s['trainer_index'] for s in enhanced_difficulty_plan['team_slot_plan']))} "
                    "trainers, by a fixed ramp in ascending trainer-index order: the first few trainers are "
                    "left alone entirely, the next several each get a small bonus, and every trainer after "
                    "that has its whole remaining team filled, always capped by that trainer's own free team "
                    "slots. Ordinary Pokemon only -- no new Shadow Pokemon are ever added by this option."
                )
            else:
                seed_data["notes"].append(
                    "enhanced_difficulty is enabled but the real ISO data it needs (trainer team census, "
                    "species pool, and/or level-up moveset data) wasn't fully available in this build -- no "
                    "level boosts or new team members were added for this seed."
                )

            # Mt. Battle extension (ADDENDUM 93): same toggle, separate call, Mt. Battle's own
            # DeckData_Hundred.bin census and trainer_index namespace, never merged with ed_team_census.
            # exclude_mt_battle_trainers gates the PADDING only.
            mt_team_census = mtbattle_team_census()
            mt_species_pool = real_species_pool()
            mt_level_up_moves = load_level_up_moves()
            if mt_team_census and mt_species_pool and mt_level_up_moves:
                # ADDENDUM 388: "Excludes Mt Battle from enhanced difficulty" now means BOTH halves of that
                # option. It gated the padding only, so the default configuration -- this toggle is on by
                # default -- still multiplied every Mt. Battle level by 1.33 while the option read as though
                # it had not: measured 9..70 mean 48.5 becoming 11..93 mean 64.0. Path scaling is a separate
                # option and is deliberately NOT gated here.
                mt_excluded_from_ed = bool(self.options.exclude_mt_battle_trainers)
                mt_ed_scale_levels = ed_scale_levels and not mt_excluded_from_ed
                mt_battle_enhanced_difficulty_plan = build_enhanced_difficulty_plan(
                    mt_team_census,
                    mt_species_pool,
                    mt_level_up_moves,
                    self.random,
                    excluded_trainer_indices=(
                        MT_BATTLE_ALL_TRAINER_INDICES if mt_excluded_from_ed else frozenset()
                    ),
                    # Mt. Battle has no permanently-excluded trainer, so the default must be overridden here.
                    permanently_excluded_trainer_indices=frozenset(),
                    max_added_members=ed_added_members,
                    scale_levels=mt_ed_scale_levels,
                )
                # Mt. Battle is one tier, so it keeps its own 1-to-100 ramp from the path's starting point.
                if path_scale_levels:
                    mt_levels, mt_averages = build_mt_battle_path_level_plan(mt_team_census)
                    if mt_ed_scale_levels:
                        mt_levels = {index: _path_scaled(level) for index, level in mt_levels.items()}
                    mt_battle_enhanced_difficulty_plan["level_assignment"].update(mt_levels)
                    # ADDENDUM 388, the other half: ADDENDUM 383 did this for the story roster and Mt. Battle
                    # was never given the same treatment. A padded member kept the level ED derived from its
                    # trainer's VANILLA average while its team-mates moved onto the ramp, so trainer 75 fielded
                    # five level-40 Pokemon and one at 64 -- and 33 apart once ED's multiplier was on top.
                    # 235 members across the mountain, every one of them off the ramp.
                    _mt_relevelled_additions = 0
                    for _entry, _slot in zip(mt_battle_enhanced_difficulty_plan["new_dpkm_entries"],
                                             mt_battle_enhanced_difficulty_plan["team_slot_plan"]):
                        _average = mt_averages.get(int(_slot["trainer_index"]))
                        if _average is None:
                            continue        # not on the ramp, so its vanilla level stands
                        _level = max(PATH_MIN_LEVEL, min(PATH_MAX_LEVEL, int(_average)))
                        if mt_ed_scale_levels:
                            _level = _path_scaled(_level)
                        if _entry["level"] != _level:
                            _mt_relevelled_additions += 1
                        _entry["level"] = _level
                    if _mt_relevelled_additions:
                        seed_data["notes"].append(
                            f"path_level_scaling (Mt. Battle): re-levelled {_mt_relevelled_additions} "
                            "Enhanced Difficulty team additions to their trainer's place on Mt. Battle's "
                            "ramp, not its vanilla average."
                        )
                    seed_data["notes"].append(
                        f"path_level_scaling (Mt. Battle): re-levelled {len(mt_levels)} team members along "
                        "Mt. Battle's own 1-to-100 order, starting at its place on the intended path and "
                        f"climbing to {mt_battle_ramp_top(mt_team_census)} at trainer 100."
                    )
                seed_data["mt_battle_enhanced_difficulty_plan"] = mt_battle_enhanced_difficulty_plan
                seed_data["notes"].append(
                    f"enhanced_difficulty (Mt. Battle): scaled the level of "
                    f"{len(mt_battle_enhanced_difficulty_plan['level_assignment'])} existing Mt. Battle team "
                    f"members to {ENHANCED_DIFFICULTY_LEVEL_MULTIPLIER}x their original level (rounded down) "
                    f"and added "
                    f"{len(mt_battle_enhanced_difficulty_plan['new_dpkm_entries'])} new ordinary team members "
                    f"across {len(set(s['trainer_index'] for s in mt_battle_enhanced_difficulty_plan['team_slot_plan']))} "
                    "of Mt. Battle's 100 trainers, by the same ramp rule as the main story roster, keyed off "
                    "Mt. Battle's own 1-100 trainer order. Shadow Pokemon are never added to Mt. Battle by any "
                    "option."
                    + (
                        " exclude_mt_battle_trainers is enabled, so no NEW team members were added to any Mt. "
                        "Battle trainer this seed -- only the flat level boost above was applied."
                        if self.options.exclude_mt_battle_trainers else ""
                    )
                )
            else:
                seed_data["notes"].append(
                    "enhanced_difficulty is enabled but the real Mt. Battle ISO census data it needs "
                    "(data/mtbattle_trainer_census.json) wasn't fully available in this build -- Mt. Battle "
                    "trainer levels/team sizes were left untouched."
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
