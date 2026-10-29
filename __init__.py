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
import logging
import random
from collections.abc import Mapping
from typing import Any

from BaseClasses import ItemClassification, LocationProgressType
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
from .game_data import load_json_data_file
from .game_data.catch_rate_exclusions import catch_rate_excluded_trainer_indices, citadark_trainer_indices

#: ADDENDUM 448: Catch Rate Scaling is a choice, and the world picks the number. Location Scaled raises every Shadow's
#: catch rate toward 255 along the seed's area order, and the last areas keep this share of that boost (ADDENDUM 442's
#: formula): a Shadow at the very end with a vanilla rate of 3 lands near 79, one at 45 near 108.
CATCH_RATE_LOCATION_SCALED_KEEP_PERCENT = 30
from .options import PokemonXDOptions
from .web_world import PokemonXDWebWorld


def launch_client(*args: str) -> None:
    """Launch the Pokemon XD client. `args` is accepted for symmetry with the other `launch_*` functions here;
    CommonClient's entry point has nothing to do with it."""
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
        # No `description=` on purpose -- the component has no subtitle line. Do not re-add one.
    )
)


# ADDENDUM 396: the location-starvation guard's message.
#
# Every fill failure in a 500-seed random-option roll -- 20 `Not enough locations for progression items`
# and 1 `Remaining locations are invalid` -- had one thing in common: more progression items than
# non-EXCLUDED locations to hold them. Zero false positives and zero false negatives against that roll, so
# the count IS the diagnosis, and the two error shapes are the same starvation seen from either side of
# fill's own bookkeeping. Which one Archipelago raises depends only on whether its accessibility sweep
# happened to hand a placement back (locations left over -> `Remaining locations are invalid`) or not
# (none left -> `Not enough locations`). Neither is worth telling apart from here.
#
# The levers are listed in descending order of the room they actually open, and only the ones this seed
# has turned off are named -- a refusal that lists a lever already on reads as a bug in the refusal.
_CAPACITY_LEVERS: "tuple[tuple[str, str, str], ...]" = (
    # (option attribute, the value that opens it, what to say)
    ("shuffle_trainer_defeats", "on", "'Shuffle Trainer Defeats' (the largest single source of locations)"),
    ("randomize_shops", "on", "'Randomize Shops'"),
)


def _capacity_refusal(world, needed: int, capacity: int) -> str:
    """The message for a seed whose progression items outnumber the locations allowed to hold them."""
    suggestions: "list[str]" = []
    for attribute, _state, phrasing in _CAPACITY_LEVERS:
        if not bool(getattr(world.options, attribute, 0)):
            suggestions.append(f"turn on {phrasing}")

    # ADDENDUM 449: `progression_locations` is gone, so these two are the levers it used to fold together.
    catches_on = bool(getattr(world.options, "shadow_catch_progression", 0))
    if not catches_on:
        suggestions.append(
            "turn on 'Shadow Pokemon Catch Checks Can Hold Progression' (hundreds of catch locations are "
            "filler-only without it)"
        )
    elif int(getattr(world.options, "purification_progression_cap", 0)) < 1:
        suggestions.append("raise 'Purification Checks That Can Hold Progression' above 0")

    if not suggestions:
        # Nothing this guard knows how to widen is still closed. Say so rather than inventing advice.
        remedy = (
            "every location category this world can widen is already enabled, so the item pool itself is "
            "the problem -- lower 'Robo Kyogre Parts Available', or report this combination"
        )
    elif len(suggestions) == 1:
        remedy = suggestions[0]
    else:
        remedy = ", or ".join([", ".join(suggestions[:-1]), suggestions[-1]])

    return (
        f"Pokemon XD ({world.player_name}): this seed has {needed} progression items but only {capacity} "
        f"location(s) allowed to hold one, so it cannot be filled. To open up "
        f"{needed - capacity} more, {remedy}."
    )


# ============================================================================================================
# ADDENDUM 403 -- Universal Tracker.
# ============================================================================================================
# UT never sees the original seed. It REGENERATES this world on the player's machine -- generate_early through
# generate_basic, no fill -- and asks the result which locations are in logic. Anything this world rolls with its
# own RNG (the Shadow species shuffle, which species are obtainable and so which `Catch -` checks exist and how
# each is gated, the expansion, the team shuffle, the Poke Spot pool, the Citadark weighting) would roll
# differently there, and UT would track a different world than the one being played.
#
# Rather than ship each of those results across separately -- and keep a second copy of every decision in sync
# with the first -- the world's own RNG is re-seeded from one number at the top of `generate_early`, that number
# goes in slot data, and UT re-seeds from it. Every later `self.random` draw then replays exactly, because the
# options are restored too and the code is the same code. One number and the options; nothing else to keep in
# step. Every randomizer here already takes the world's RNG as an argument (none reach for the global `random`
# or the multiworld's), which is what makes this sound -- `test_addendum_403` keeps it that way.
#
# `ut_can_gen_without_yaml`: the player does not need a YAML for UT. Every option that shapes generation travels
# in slot data, so UT builds the world from that alone.
UT_SLOT_DATA_KEY = "universal_tracker"
UT_SLOT_DATA_FORMAT = 1
#: 53 bits, not 64: slot data is JSON, and a consumer that parses numbers as doubles (any JavaScript tracker)
#: would silently round a larger integer -- and a rounded seed regenerates a different world with no error.
UT_SEED_BITS = 53


def ut_option_names() -> "tuple[str, ...]":
    """Every option this world defines itself -- the ones that can shape generation. The per-game common ones
    (local items, hints, plando, start inventory) are Archipelago's and never reach a rule here."""
    from Options import PerGameCommonOptions

    common = set(PerGameCommonOptions.type_hints)
    return tuple(name for name in PokemonXDOptions.type_hints if name not in common)


# Data Storage keys the client writes the player's current room id and area name to, on every room change.
ROOM_ID_KEY_TEMPLATE = "pokemon_xd_room_{team}_{slot}"
ROOM_AREA_KEY_TEMPLATE = "pokemon_xd_area_{team}_{slot}"


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

    # ADDENDUM 403: Universal Tracker regenerates from slot data alone -- see the block above the class.
    ut_can_gen_without_yaml = True

    @staticmethod
    def interpret_slot_data(slot_data: "dict[str, Any]") -> "dict[str, Any]":
        """Static, and returns the slot data unchanged: that is UT's signal to skip its own first generation and
        regenerate once from what the server sent, handing it back as `multiworld.re_gen_passthrough`."""
        return slot_data

    def _ut_passthrough(self) -> "dict[str, Any] | None":
        """This world's slot data, when Universal Tracker is regenerating it; None in a real generation."""
        passthrough = getattr(self.multiworld, "re_gen_passthrough", None) or {}
        data = passthrough.get(self.game) if isinstance(passthrough, dict) else None
        return data if isinstance(data, dict) else None

    def _seed_world_rng(self) -> None:
        """ADDENDUM 403. Re-seed `self.random` from one recorded number -- see the block above the class."""
        slot_data = self._ut_passthrough()
        recorded = slot_data.get(UT_SLOT_DATA_KEY) if slot_data else None
        if isinstance(recorded, dict) and "seed" in recorded:
            # Universal Tracker. The options first: everything after this reads them, and UT built this world
            # from an empty YAML, so until now they are all defaults.
            for name, value in (recorded.get("options") or {}).items():
                current = getattr(self.options, name, None)
                if current is not None:
                    setattr(self.options, name, type(current).from_any(value))
            seed = int(recorded["seed"])
        else:
            # A real generation -- or UT on a seed made before this addendum, which has nothing to restore and so
            # can only track an approximation of it. Said nowhere louder than here, because there is nothing the
            # player can do about it but regenerate.
            seed = self.random.getrandbits(UT_SEED_BITS)
        self._ut_seed: int = seed
        self.random = random.Random(seed)

    def _adjust_option(self, name: str, value: int, why: str) -> None:
        """ADDENDUM 406: move one option to the nearest valid value and say so, instead of refusing the YAML."""
        option = getattr(self.options, name)
        before = int(option)
        option.value = value
        self.option_adjustments = getattr(self, "option_adjustments", [])
        self.option_adjustments.append((name, before, value))
        logging.warning(
            f"Pokemon XD ({self.player_name}): '{option.display_name}' was {before}; using {value} instead -- {why}."
        )

    def generate_early(self) -> None:
        # ADDENDUM 403: FIRST, before any option is read or any number drawn. In a real generation this draws one
        # seed from the RNG Archipelago handed us and re-seeds from it; inside Universal Tracker it restores the
        # options and that same seed from slot data instead. Either way every draw below is reproducible.
        self._seed_world_rng()
        # ADDENDUM 443: the starter, from its own RNG so the option never moves any other draw.
        from .game_data import starter as starter_data

        self._starter: "dict | None" = starter_data.plan(random.Random(self._ut_seed ^ 0x57A27E5),
                                                         int(self.options.randomize_starter))
        self.starter_dex: int = self._starter["dex"] if self._starter else starter_data.VANILLA_STARTER_DEX
        self.starter_line_dex: "frozenset[int]" = (frozenset(self._starter["line"]) if self._starter
                                                   else starter_data.evolution_line(starter_data.VANILLA_STARTER_DEX))
        self._first_chobin: "dict | None" = None   # ADDENDUM 461, set by _secure_first_chobin
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
        # ADDENDUM 423: Nightmare Citadark. Decided before the team shuffle, whose fingerprints describe these
        # trainers by the teams they will really field.
        self._nightmare_teams: "dict[int, str] | None" = None
        self._nightmare_removed_dex: "frozenset[int]" = frozenset()
        self._nightmare_removed_dpkm: "frozenset[int]" = frozenset()
        # ADDENDUM 424: where the displaced Shadows went -- `nightmare_citadark.plan_relocations`' shape. Planned in
        # the Shadow pass below, which owns the free-slot census and the level rules they share with the expansion.
        self._nightmare_relocations: "list[dict]" = []
        # ADDENDUM 431: whose Shadows leave them -- Nightmare Citadark's trainers, and/or the two removal options.
        # A slot a Nightmare team does not replace keeps an ordinary copy of its Pokemon (`_shadow_vacated_slots`).
        self._shadow_removal_trainers: "frozenset[int]" = frozenset()
        self._shadow_vacated_slots: "list[dict]" = []
        from .game_data import nightmare_citadark

        if self.options.nightmare_citadark:
            self._nightmare_teams = nightmare_citadark.assign_teams(self.random)
        elif self.options.nightmare_greevil:
            # Greevil's final story battle (200) and his post-game rematch (201) take Nightmare teams. The final
            # battle's six Shadows are relocated (`shadow_removal_trainers`).
            self._nightmare_teams = nightmare_citadark.assign_teams(
                self.random, set(nightmare_citadark.NIGHTMARE_GREEVIL_TRAINERS))
        self._shadow_removal_trainers = nightmare_citadark.shadow_removal_trainers(
            bool(self.options.nightmare_citadark), bool(self.options.remove_citadark_shadows),
            bool(self.options.remove_greevil_shadows),
            nightmare_greevil=bool(self.options.nightmare_greevil) and not bool(self.options.nightmare_citadark),
            admins_only=bool(self.options.citadark_admins_only))
        if self._shadow_removal_trainers:
            # ADDENDUM 424/431: these Shadows leave their trainers but not the seed.
            self._nightmare_removed_dex = nightmare_citadark.removed_shadow_national_dex(self._shadow_removal_trainers)
            self._nightmare_removed_dpkm = nightmare_citadark.removed_shadow_dpkm_indices(
                self._shadow_removal_trainers)
            self._shadow_vacated_slots = nightmare_citadark.vacated_slots(
                self._shadow_removal_trainers, frozenset(self._nightmare_teams or ()))
        self._build_trainer_team_shuffle()

        # The real bound is this seed's expansion setting (83 vanilla + the expansion's add), not the option's
        # 127 ceiling, so it is checked here rather than in the Range.
        _vanilla_shadow_count = locations.PRE_GOAL_VANILLA_SHADOW_COUNT
        try:
            from .game_data.shadow_regions import shadow_regions_in_graph_order

            # ADDENDUM 423/424: the Shadows still at their vanilla holders -- Nightmare Citadark's relocated ones are
            # counted with the expansion's, on the ladder past this point. ADDENDUM 479: and only those that can be
            # had before the goal -- Greevil's and Miror B.'s post-game Dragonite have no checks.
            _counted = len(shadow_regions_in_graph_order(self._nightmare_removed_dex, include_post_goal=False))
            if _counted:
                _vanilla_shadow_count = _counted
        except Exception:  # noqa: BLE001 -- a missing census must not take generation down over a bound check
            pass
        # Read by rules.py: where the vanilla purification ladder ends and the expansion's begins.
        self._vanilla_shadow_count = _vanilla_shadow_count
        # ADDENDUM 424: Nightmare Citadark's relocated Shadows still exist, one each, on new holders.
        _relocated_count = len(self._nightmare_removed_dpkm)
        _purifiable = _vanilla_shadow_count + _relocated_count + int(self.options.shadow_pokemon_expansion)
        # ADDENDUM 406: settings that cannot all be true are ADJUSTED, not refused: available Kyogre Parts round up
        # to the amount required, and the purification cap rounds down to the number of Shadows that can exist.
        # Every adjustment is logged and written back into the options, so slot data -- and Universal Tracker's replay of it -- carries the value actually used.
        if int(self.options.purification_progression_cap) > _purifiable:
            self._adjust_option(
                "purification_progression_cap", _purifiable,
                f"only {_purifiable} Shadow Pokemon exist to purify ({_vanilla_shadow_count} vanilla + "
                + (f"{_relocated_count} moved off Citadark Isle + " if _relocated_count else "")
                + f"{int(self.options.shadow_pokemon_expansion)} from 'Shadow Pokemon Expansion')",
            )

        # Start With Miror Radar and Poke Spots needs Location Shuffle: it works by starting with the Poke Spots' unlock.
        if bool(self.options.start_with_poke_spots) and not bool(self.options.randomize_travel_locations):
            self._adjust_option(
                "start_with_poke_spots", 0,
                "it needs 'Randomize Travel Locations/Location Shuffle' on",
            )

        # The Nightmare options field level-100 teams, so they bring Reduce Citadark Grind with them when it is off.
        if (bool(self.options.nightmare_citadark) or bool(self.options.nightmare_greevil)) \
                and int(self.options.reduce_citadark_grind) == 0:
            self._adjust_option(
                "reduce_citadark_grind", 1,
                "'Nightmare Citadark' and 'Nightmare Greevil' turn it on",
            )

        # Citadark Admins Only takes the island's other trainers out of the cumulative tally, so a count past what
        # the rest of the game can reach is brought down to it.
        if bool(self.options.citadark_admins_only) and int(self.options.trainer_defeat_mode) == 0:
            from .rules import _trainer_count_groups

            _countable = sum(many for _ways, many in _trainer_count_groups(self))
            if int(self.options.trainer_defeat_check_count) > _countable:
                self._adjust_option(
                    "trainer_defeat_check_count", _countable,
                    f"with 'Citadark Admins Only' on, {_countable} trainers can be counted on",
                )

        # The Machine Part is sphere zero in every mode: it repairs the scooter and, with travel randomization off,
        # opens Agate Village -- 573 of 677 locations sit behind it there. It has nothing to do with the Snag Machine,
        # which the HQ Lab hands over first (0x0F, before Gateon's Machine Part at 0x16; ADDENDUM 483, issue #6).
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
                self._adjust_option(
                    "robo_kyogre_parts_available", required,
                    f"Citadark Isle needs {required} Robo Kyogre Parts, so at least that many must exist",
                )

        # ADDENDUM 396: the old count guard that stood here is retired, not moved. It compared every
        # progression ROW IN `ITEM_TABLE` (34) against the whole "Overworld Items" name group (51) plus the
        # trainer defeats, so its floor was 52 against a ceiling of 34 and it could never fire -- the
        # condition-that-cannot-bind ADDENDA 247 and 298 refuse. Worse, both of its numbers were the wrong
        # ones: the table's progression rows are not this seed's pool (travel unlocks, key items, the
        # scooter upgrade and the MacGuffin all come and go with their own options), and a name group is
        # not a location count (most of those locations are created EXCLUDED). The real check lives in
        # create_items, where both honest numbers exist. See `_capacity_refusal`.

        # Shadow species randomization (ADDENDUM 17) only changes which species stands at a Shadow encounter.
        # The pool loads UNCONDITIONALLY: the obtainable-species set decides which "Catch - {species}"
        # locations exist at all (ADDENDUM 43). Here, not generate_output(), because fill_slot_data() runs
        # first.
        from .game_data.real_shadow_data import load_real_shadow_pool
        from .tools.xd_species_index import INTERNAL_INDEX_TO_NATIONAL_DEX, national_dex_for

        shadow_pool = load_real_shadow_pool()
        # ADDENDUM 424: Nightmare Citadark's displaced Shadows stay in the pool -- they are relocated, not removed,
        # so they shuffle, level and count like every other. Their hosts are planned here, before the levels
        # settle, because the level is the host's.
        if shadow_pool is not None and self._nightmare_removed_dpkm:
            self._nightmare_relocations = self._plan_nightmare_relocations()

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
        # ADDENDUM 424: a relocated Shadow takes its HOST's level, whatever its Citadark census row said.
        _relocated_level = {shadow["dpkm_index"]: shadow["level"]
                            for plan in self._nightmare_relocations for shadow in plan["shadows"]}
        _relocated_host = {shadow["dpkm_index"]: int(plan["trainer_index"])
                           for plan in self._nightmare_relocations for shadow in plan["shadows"]}
        _relocated_dex_by_dpkm: "dict[int, int]" = {}
        if shadow_pool is not None and _relocated_level:
            for _trainer in shadow_pool.trainers:
                for _mon in _trainer.team:
                    if _mon.index in _relocated_level:
                        _mon.level = _relocated_level[_mon.index]

        shadow_obtainable_dex: set[int] = set()
        # ADDENDUM 479: species at a post-goal Shadow slot, and species any other Shadow slot (or the expansion, or
        # a relocation) hands out. A species ONLY at post-goal slots gets no `Catch - X`.
        _post_goal_shadow_dex: set[int] = set()
        _pre_goal_shadow_dex: set[int] = set()
        # ADDENDUM 183: recorded now because the shadow pool is shuffled IN PLACE -- re-loading it at
        # set_rules time returns vanilla species and gates the wrong ones. Labels, not regions.
        self._shadow_catch_labels: dict[int, list[str]] = {}
        # ADDENDUM 432: the vanilla Shadow (DDPK) behind each label -- what the catch and purification gates key on.
        self._shadow_catch_ddpks: dict[int, list[int]] = {}
        self._shadow_catch_expansion_hosts: dict[int, list[int]] = {}
        if shadow_pool is not None:
            from .game_data.real_trainer_data import real_species_pool
            from .randomizer.team_shuffle import TeamShuffleOptions, shuffle_teams
            from .game_data import shadow_legendaries

            # Snapshot vanilla species and location name first: every pass below reassigns in place.
            original_by_index = {
                mon.index: (mon.species_id, trainer.name)
                for trainer in shadow_pool.trainers
                for mon in trainer.team
            }
            _species_changed = False
            if self.options.randomize_shadow_species:
                # legendary_safe=False: Shadows randomize into anything; the dedup keeps the map one-to-one.
                shuffle_teams(
                    [shadow_pool],
                    real_species_pool(),
                    TeamShuffleOptions(legendary_safe=False),
                    self.random,
                )
                _species_changed = True
            # ADDENDUM 435: No Legendary Shadows, then Shuffle Shadow Lugia (which the first exempts Lugia from).
            if self.options.no_legendary_shadows:
                _exempt = (frozenset({shadow_legendaries.LUGIA_SPECIES_INDEX})
                           if self.options.shuffle_shadow_lugia else frozenset())
                if shadow_legendaries.remove_legendary_shadows(shadow_pool, real_species_pool(), self.random,
                                                               exempt=_exempt):
                    _species_changed = True
            if self.options.shuffle_shadow_lugia:
                from .game_data.shadow_regions import ddpk_for_dpkm as _ddpk_for_dpkm, is_post_goal_ddpk

                # ADDENDUM 479: the post-goal slots still at their own trainers -- no checks there.
                _post_goal_dpkm = frozenset(dpkm for dpkm, ddpk in _ddpk_for_dpkm().items()
                                            if is_post_goal_ddpk(ddpk) and dpkm not in _relocated_host)
                if shadow_legendaries.place_shadow_lugia(
                        shadow_pool, {i: sp for i, (sp, _n) in original_by_index.items()}, self.random,
                        randomized=bool(self.options.randomize_shadow_species),
                        exclude_indices=_post_goal_dpkm) is not None:
                    _species_changed = True
            if _species_changed:
                entries: list[dict[str, Any]] = []
                for trainer in shadow_pool.trainers:
                    for mon in trainer.team:
                        original_species_index, location_name = original_by_index[mon.index]
                        if mon.index in _relocated_host:
                            from .catch_sources import _host_label

                            location_name = _host_label(_relocated_host[mon.index]) or location_name
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
                        if mon.index in _relocated_host:
                            # ADDENDUM 424: gated where it now is -- its host, keyed like a generated Shadow.
                            self._shadow_catch_expansion_hosts.setdefault(dex, []).append(_relocated_host[mon.index])
                            _relocated_dex_by_dpkm[mon.index] = dex
                            continue
                        from .game_data.shadow_regions import ddpk_for_dpkm, is_post_goal_ddpk

                        _ddpk = ddpk_for_dpkm().get(mon.index)
                        if _ddpk is not None and is_post_goal_ddpk(_ddpk):
                            # ADDENDUM 479: still a Shadow this seed holds (the Poke Spots keep away from its
                            # species), but no check of its own -- only after the goal could it be purified.
                            _post_goal_shadow_dex.add(dex)
                            continue
                        _pre_goal_shadow_dex.add(dex)
                        # This slot's fixed AP location name. A list, so callers take the earliest.
                        self._shadow_catch_labels.setdefault(dex, []).append(trainer.name)
                        if _ddpk is not None:
                            self._shadow_catch_ddpks.setdefault(dex, []).append(_ddpk)

        # ADDENDUM 99: built HERE, because generate_early has already decided which "Catch - {species}"
        # locations exist. Rebuilding it later off the same self.random would change the plan.
        self._shadow_expansion_plans: list[dict[str, Any]] | None = None
        if self.options.shadow_pokemon_expansion > 0:
            from .game_data.real_shadow_data import vanilla_shadow_species
            from .game_data.real_trainer_data import MT_BATTLE_TRAINER_INDICES, real_species_pool, real_trainer_free_slot_census
            from .game_data.real_moveset_data import load_level_up_moves
            from .randomizer.shadow_expansion import build_shadow_expansion_plans
            from .randomizer.enhanced_difficulty import ENHANCED_DIFFICULTY_LEVEL_MULTIPLIER

            # ADDENDUM 487: a mirrored first fight hosts no more than its second fight has room to copy.
            from .game_data.shadow_mirrors import cap_census_for_mirrored_hosts

            expansion_free_slot_census = cap_census_for_mirrored_hosts(real_trainer_free_slot_census())
            # ADDENDUM 424: the relocated Shadows took their slots first.
            if expansion_free_slot_census and self._nightmare_relocations:
                _taken = {int(p["trainer_index"]): len(p["shadows"]) for p in self._nightmare_relocations}
                expansion_free_slot_census = [
                    {**row, "free_slots": int(row["free_slots"]) - _taken.get(int(row["trainer_index"]), 0)}
                    for row in expansion_free_slot_census
                ]
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

                _gift_line = {133} | set(EEVEELUTION_DEX_NUMBERS) | set(self.starter_line_dex)   # ADDENDUM 443
                expansion_excluded_species = expansion_excluded_species | {
                    index for index in (internal_index_for_national_dex(dex) for dex in _gift_line)
                    if index is not None
                }
            # ADDENDUM 486: the species whose evolution LINES are taken -- this seed's real Shadows (post-shuffle when
            # Randomize Shadow Species ran) and the gift line. Not the vanilla 83 once shuffled: excluding their lines
            # as well would leave too few lines for the expansion.
            _line_reserved = None
            if expansion_excluded_species is not None:
                _current_shadows = ({entry["new_species_index"] for entry in self._shadow_species_assignment["entries"]
                                     if entry.get("new_species_index") is not None}
                                    if self._shadow_species_assignment else set(vanilla_shadow_species()))
                _line_reserved = _current_shadows | {
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
                    ) | missable_trainers.shadow_expansion_excluded_trainer_indices(
                        allow_missable_hosts=bool(self.options.missable_trainer_shadows))
                    # ADDENDUM 423/424: Nightmare Citadark adds nothing to the island -- its teams are fixed, and
                    # Greevil's first fight stays Lugia alone.
                    | (citadark_trainer_indices() if self.options.nightmare_citadark
                       else frozenset(self._nightmare_teams or ()))
                    # ADDENDUM 431: a trainer whose Shadows were removed gets none back from the expansion.
                    | self._shadow_removal_trainers,
                    # ADDENDUM 198: carries the 1.33x onto a generated Shadow, matching its team.
                    level_multiplier=(
                        ENHANCED_DIFFICULTY_LEVEL_MULTIPLIER
                        if self.options.enhanced_difficulty_level_scaling else 1.0
                    ),
                    line_reserved_species=_line_reserved,   # ADDENDUM 486
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

        # ADDENDUM 467: every other occurrence of a host trainer gets the same Shadow (same DDPK record), in a slot no
        # host claimed. Planned last, so it only ever takes what is left; ED reserves these slots too.
        self._shadow_mirror_slots: "dict[int, int]" = {}
        try:
            from .game_data import shadow_mirrors
            from .game_data.real_trainer_data import real_trainer_free_slot_census as _free_census

            _host_shadows: "list[tuple[int, dict]]" = []
            _host_taken: "dict[int, int]" = {}
            for _plan in self._nightmare_relocations:
                for _shadow in _plan["shadows"]:
                    _host_shadows.append((int(_plan["trainer_index"]), _shadow))
                _host_taken[int(_plan["trainer_index"])] = (
                    _host_taken.get(int(_plan["trainer_index"]), 0) + len(_plan["shadows"]))
            for _plan in (self._shadow_expansion_plans or ()):
                for _mon in _plan["new_pokemon"]:
                    _host_shadows.append((int(_plan["trainer_index"]), _mon))
                _host_taken[int(_plan["trainer_index"])] = (
                    _host_taken.get(int(_plan["trainer_index"]), 0) + len(_plan["new_pokemon"]))
            if _host_shadows:
                self._shadow_mirror_slots = shadow_mirrors.plan_mirrors(
                    _free_census(), _host_shadows, _host_taken,
                    excluded=frozenset(self._shadow_removal_trainers) | frozenset(self._nightmare_teams or ()))
        except Exception:
            self._shadow_mirror_slots = {}
            for _plan in self._nightmare_relocations:
                for _shadow in _plan["shadows"]:
                    _shadow["mirror_trainer_indices"] = []
            for _plan in (self._shadow_expansion_plans or ()):
                for _mon in _plan["new_pokemon"]:
                    _mon["mirror_trainer_indices"] = []

        # Missable Trainer Shadows: the Shadows this seed put on missable one-shot fights, by host. The client hands
        # each to Miror B. once its area's story cap passes without it being met.
        self._missable_shadow_hosts: "dict[int, list[dict[str, Any]]]" = {}
        if self.options.missable_trainer_shadows:
            from .game_data.missable_trainers import missable_shadow_host_indices
            from .tools.xd_species_index import internal_index_for_national_dex as _internal_for

            _missable_hosts = missable_shadow_host_indices()
            _relocated_ddpk_by_dex: "dict[int, int]" = {}
            for _plan in self._nightmare_relocations:
                for _shadow in _plan["shadows"]:
                    _moved_dex = _relocated_dex_by_dpkm.get(int(_shadow["dpkm_index"]))
                    if _moved_dex is not None:
                        _relocated_ddpk_by_dex[int(_moved_dex)] = int(_shadow["ddpk_index"])
            for _dex, _hosts in sorted(self._shadow_catch_expansion_hosts.items()):
                for _host in _hosts:
                    if int(_host) not in _missable_hosts:
                        continue
                    _species = _internal_for(int(_dex))
                    _name = INTERNAL_INDEX_TO_NATIONAL_DEX.get(_species, (None, None))[1] if _species else None
                    self._missable_shadow_hosts.setdefault(int(_host), []).append(
                        {"dex": int(_dex), "species": _species, "name": str(_name).title() if _name else f"#{_dex}",
                         "ddpk": _relocated_ddpk_by_dex.get(int(_dex))})

        # ADDENDUM 415: one `Purify N` per Shadow this seed REALLY holds -- the vanilla count plus what the expansion
        # actually placed, which can fall short of the request when hosts run out. create_regions reads this.
        self._purification_location_count = _vanilla_shadow_count + sum(
            len(plan["new_pokemon"]) for plan in (self._shadow_expansion_plans or ())
        ) + sum(len(plan["shadows"]) for plan in self._nightmare_relocations)

        # Poke Spot reassignment (ADDENDUM 43): always on, no toggle. Prefers species the Shadow pool does not
        # already cover, and is cached for the same two readers.
        from .game_data.pokespot_data import assign_pokespot_species

        self._pokespot_species_assignment = assign_pokespot_species(shadow_obtainable_dex, self.random)
        pokespot_obtainable_dex = {entry["new_dex"] for entry in self._pokespot_species_assignment}

        # What a player can catch this seed; locations.create_regions_and_locations decides the "Catch -
        # {species}" set from it. None means don't trim -- the 11 Poke Spot species alone would gut the list.
        # ADDENDUM 479: minus the species only a post-goal Shadow carries -- no check for those.
        self._post_goal_only_dex: "set[int]" = (
            _post_goal_shadow_dex - _pre_goal_shadow_dex - set(self._shadow_catch_expansion_hosts)
            - pokespot_obtainable_dex - {self.starter_dex})
        # Poke Spot Catch Checks off: a species only the Poke Spots give has no check.
        if not bool(getattr(self.options, "pokespot_catch_checks", 1)):
            pokespot_obtainable_dex = set()
        self._obtainable_species_dex: set[int] | None = (
            None if shadow_pool is None
            else (shadow_obtainable_dex - self._post_goal_only_dex) | pokespot_obtainable_dex
            | {self.starter_dex}  # the starter, always guaranteed
        )

        # Shadow Move TMs: which TMs teach which Shadow move. Its own RNG, drawn only when the option is on, so a seed
        # without it rolls exactly as before.
        self._shadow_move_tms: "list[tuple[int, int]]" = []
        if int(getattr(self.options, "shadow_move_tms", 0)) > 0:
            import random as _random
            from .game_data.tm_moves import plan_shadow_move_tms

            self._shadow_move_tms = plan_shadow_move_tms(
                _random.Random(self.random.getrandbits(64)), int(self.options.shadow_move_tms))

    def _assign_shadow_movesets(self, seed_data: dict) -> None:
        """ADDENDUM 427: legal ordinary moves for every Shadow whose species was randomized, written through the
        same `trainer_moves_by_dpkm_index` channel the ordinary members use. Level: a relocated Shadow's host
        level, else the level pass's final value for its DPKM record, else the pool's own."""
        assignment = getattr(self, "_shadow_species_assignment", None)
        if not assignment:
            return
        # ADDENDUM 462: Shadow Pokemon Inherit Replaced Moves -- the pre-427 behaviour, back as a choice. Every Shadow
        # keeps its DPKM record's vanilla ordinary moves (the replaced Shadow's), so nothing is written here.
        if bool(getattr(self.options, "shadow_inherited_moves", 0)):
            seed_data["notes"].append("Shadow movesets: Shadow Pokemon keep the moves of the Shadows they replaced "
                                      "(Shadow Pokemon Inherit Replaced Moves).")
            return
        # ADDENDUM 435: the assignment also exists for No Legendary Shadows / Shuffle Shadow Lugia alone; then only
        # the Shadows whose species actually moved get new moves.
        every_entry = bool(self.options.randomize_shadow_species)
        from .game_data.real_moveset_data import load_level_up_moves
        from .randomizer.team_shuffle import choose_moveset, MOVESET_SHUFFLE_DEFAULT_MOVE_COUNT

        learnsets = load_level_up_moves()
        if learnsets is None:
            return
        final_levels = {int(k): int(v) for k, v in
                        ((seed_data.get("enhanced_difficulty_plan") or {}).get("level_assignment") or {}).items()}
        for plan in self._nightmare_relocations:
            for shadow in plan["shadows"]:
                final_levels[int(shadow["dpkm_index"])] = int(shadow["level"])
        pool_levels = {mon.index: mon.level for trainer in assignment["pool"].trainers for mon in trainer.team}
        moves_out = seed_data.setdefault("trainer_moves_by_dpkm_index", {}) or {}
        seed_data["trainer_moves_by_dpkm_index"] = moves_out
        written = 0
        for entry in assignment["entries"]:
            dpkm, species = int(entry["dpkm_index"]), entry.get("new_species_index")
            if species is None:
                continue
            if not every_entry and species == entry.get("original_species_index"):
                continue
            level = final_levels.get(dpkm, pool_levels.get(dpkm))
            if not level:
                continue
            moves = choose_moveset(species, level, learnsets.get(species, []), self.random)
            if moves:
                moves_out[str(dpkm)] = moves + [0] * (MOVESET_SHUFFLE_DEFAULT_MOVE_COUNT - len(moves))
                written += 1
        if written:
            seed_data["notes"].append(f"Shadow movesets: {written} Shadow Pokemon given legal ordinary moves.")

    def _story_team_species(self) -> "dict[int, set[int]]":
        """ADDENDUM 425: {trainer index: the ordinary species it fields this seed} -- shuffled and evolved."""
        assignment = self._trainer_species_by_dpkm_index or {}
        return {
            trainer["index"]: {assignment.get(slot["dpkm_index"], slot["species"])
                               for slot in trainer.get("team", ()) if slot.get("kind") == "DPKM"}
            for trainer in (load_json_data_file("deckdata_story_trainers.json") or ())
        }

    def _plan_nightmare_relocations(self) -> "list[dict]":
        """ADDENDUM 424: hosts for the Shadows Nightmare Citadark displaces. Same fence as the expansion's
        (ADDENDUM 236: no missable or re-fightable trainer, no Mt. Battle when it is excluded) plus all of Citadark,
        and the expansion's level rule. Empty when the free-slot census is missing from this build."""
        from .game_data import missable_trainers, nightmare_citadark
        from .game_data.real_trainer_data import MT_BATTLE_TRAINER_INDICES, real_trainer_free_slot_census
        from .randomizer.enhanced_difficulty import ENHANCED_DIFFICULTY_LEVEL_MULTIPLIER

        from .game_data.shadow_mirrors import cap_census_for_mirrored_hosts

        census = cap_census_for_mirrored_hosts(real_trainer_free_slot_census())   # ADDENDUM 487
        if not census:
            return []
        excluded = (
            (frozenset(MT_BATTLE_TRAINER_INDICES) if self.options.exclude_mt_battle_trainers else frozenset())
            | missable_trainers.shadow_expansion_excluded_trainer_indices(
                allow_missable_hosts=bool(self.options.missable_trainer_shadows))
            | citadark_trainer_indices()
        )
        return nightmare_citadark.plan_relocations(
            self.random, census, excluded,
            level_multiplier=(ENHANCED_DIFFICULTY_LEVEL_MULTIPLIER
                              if self.options.enhanced_difficulty_level_scaling else 1.0),
            trainers=self._shadow_removal_trainers,
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
            # ADDENDUM 435: Legendary Trainer Pokemon lifts the legendary-for-legendary rule for ordinary teams.
            shuffle_teams(trainer_pools, species_pool,
                          TeamShuffleOptions(legendary_safe=not self.options.legendary_trainer_pokemon), self.random)
            # ADDENDUM 461: with a random starter, re-draw Chobin #1's one Pokemon so the starter can beat it.
            self._secure_first_chobin(trainer_pools, species_pool)

            # The evolution pass does NOT run here: it needs the final level, and since ADDENDUM 299 the ramp
            # follows this seed's sphere order, which fill decides. It lives in pre_output() -- after fill,
            # before generate_output and fill_slot_data, single-threaded.
            self._trainer_team_pools = trainer_pools
            self._trainer_species_by_dpkm_index = dpkm_species_assignment(trainer_pools)

        self._build_trainer_fingerprints()

    def _randomize_mt_battle_teams(self, plan: dict, species_pool, level_up_moves, seed_data: dict) -> "dict[int, int]":
        """Every Mt. Battle member re-rolled for the level it is fought at (`randomizer/mt_battle_shuffle.py`), with
        a moveset for its new species. Writes the plan's `species_assignment` and `moves_assignment` and returns the
        species. Its own RNG, so the rest of the seed's output is drawn the same with this on or off."""
        from .randomizer import mt_battle_shuffle

        trainers = load_json_data_file("mtbattle_trainer_census.json") or []
        rng = random.Random(self._ut_seed ^ 0x3B477E)
        levels = {int(k): int(v) for k, v in plan.get("level_assignment", {}).items()}
        species = mt_battle_shuffle.shuffle_species(
            trainers, levels, species_pool, rng, legendary_safe=not self.options.legendary_trainer_pokemon)
        plan["species_assignment"] = species
        plan["moves_assignment"] = mt_battle_shuffle.movesets(species, levels, trainers, level_up_moves, rng)
        seed_data["mt_battle_team_assignments"] = [
            {"trainer_index": int(t["index"]),
             "team": [{"species": species.get(int(s["dpkm_index"]), int(s["species"])),
                       "level": levels.get(int(s["dpkm_index"]), int(s["level"]))}
                      for s in t.get("team", ()) if s.get("kind") == "DPKM"]}
            for t in trainers
        ]
        seed_data["notes"].append(
            f"Mt. Battle: randomized {len(species)} team members' species and {len(plan['moves_assignment'])} "
            "movesets, by the story's rules.")
        return species

    def _first_chobin_slots(self, trainer_pools) -> "list":
        from .game_data.first_battle import FIRST_CHOBIN_DPKM_INDEX

        return [mon for pool in trainer_pools for trainer in pool.trainers for mon in trainer.team
                if mon.index == FIRST_CHOBIN_DPKM_INDEX and not mon.is_shadow]

    def _secure_first_chobin(self, trainer_pools, species_pool, level: "int | None" = None) -> None:
        """ADDENDUM 461: Chobin #1 (story trainer 15, DPKM 25) gets a Pokemon the randomized starter is sure to hurt
        for about half its HP and beats in simulated battle -- `game_data/first_battle.py`. Only with Randomize
        Starter on, and from its own RNG, like the starter: the option moves no other draw except the moveset
        chooser's, which now sees a different species for this one slot."""
        self._first_chobin: "dict | None" = getattr(self, "_first_chobin", None) if level is not None else None
        if not getattr(self, "_starter", None):
            return
        from .game_data import first_battle
        from .game_data.real_moveset_data import load_level_up_moves

        slots = self._first_chobin_slots(trainer_pools)
        learnsets = load_level_up_moves()
        if not slots or learnsets is None:
            return
        entry = first_battle.plan(
            self._starter["internal"], list(self._starter["moves"]),
            first_battle.candidate_species(species_pool, bool(self.options.legendary_trainer_pokemon)),
            random.Random(self._ut_seed ^ 0xC40B1), learnsets, level=level or slots[0].level,
        )
        if entry is None:
            return
        for mon in slots:
            mon.species_id = entry["species"]
        self._first_chobin = entry

    def _reassert_first_chobin(self, trainer_pools) -> bool:
        """After `_apply_final_levels_and_evolution` re-levels and re-evolves every member: Chobin #1 is pinned at 5
        and nothing evolves by 5, so this normally only confirms. If a future change moves either, the fight is
        re-planned at the level the ISO will carry rather than shipped against the wrong number."""
        entry = getattr(self, "_first_chobin", None)
        if not entry:
            return False
        slots = self._first_chobin_slots(trainer_pools)
        if not slots:
            return False
        if any(mon.level != entry["level"] for mon in slots):
            from .game_data.real_trainer_data import load_real_trainer_pools

            real = load_real_trainer_pools()
            if real is not None:
                self._secure_first_chobin(trainer_pools, real[0], level=slots[0].level)
                return True
        changed = False
        for mon in slots:
            if mon.species_id != self._first_chobin["species"]:
                mon.species_id = self._first_chobin["species"]
                changed = True
        return changed

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
            # ADDENDUM 423: a Nightmare Citadark trainer fields six Orre Colosseum members at level 100 and no
            # Shadow, whatever its deck row said.
            team_slots = trainer["team"]
            nightmare_source = (self._nightmare_teams or {}).get(trainer["index"]) \
                if getattr(self, "_nightmare_teams", None) else None
            if nightmare_source is not None:
                from .game_data.nightmare_citadark import NIGHTMARE_LEVEL, team_species
                team_slots = [{"species": sp, "level": NIGHTMARE_LEVEL} for sp in team_species(nightmare_source)]
            for slot in team_slots:
                dpkm_index = slot.get("dpkm_index")
                if dpkm_index is None and nightmare_source is None:
                    shadow_slots += 1  # a DDPK/Shadow slot -- see this method's docstring
                    continue
                # Both are the game's MASTER internal species index, so both go through `national_dex_for`.
                # NOT national_dex_for_live_species, which is live RAM's compacted index with slots 252-276
                # squeezed out: on deck data it mis-names every Gen III species.
                internal = slot.get("species") if dpkm_index is None else assignment.get(dpkm_index, slot.get("species"))
                # The level this seed really ships: a vanilla-level band cannot hold a path-scaled HP.
                level = slot.get("level") if (final_levels is None or dpkm_index is None) else final_levels.get(
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

    def _catch_progress_by_trainer(self) -> "dict[int, int]":
        """ADDENDUM 441: {trainer index: 0..1000}, how far along THIS seed's area order the trainer's region opens.
        The same tiers the path ramp uses (`sphere_tier_order` over the sphere walk), computed here even when Path
        Level Scaling is off. With travel shuffle off the sphere order is the story's, so both modes share one
        rule; an empty walk falls back to the intended path."""
        from .randomizer.path_level_scaling import region_by_trainer_index, sphere_tier_order

        by_trainer = region_by_trainer_index()
        tiers = getattr(self, "_path_tier_by_region", None)
        if not tiers:
            wanted = set(by_trainer.values())
            try:
                spheres = self._region_spheres(wanted)
            except Exception:
                spheres = {}
            tiers = sphere_tier_order(spheres, wanted)
        top = max(tiers.values(), default=0)
        if top <= 0:
            return {}
        from .game_data import trainer_placements

        out = {index: round(1000 * tiers[region] / top) for index, region in by_trainer.items() if region in tiers}
        # Every Shadow gets a step. A region with no tier is one of the always-open starting areas (HQ Lab, Gateon,
        # Kaminko's), so it sits at the start; a fight with no known region gets the end's smaller boost.
        for index, placement in trainer_placements.PLACEMENTS.items():
            if index not in out:
                out[index] = 0 if placement.region is not None else 1000
        return out

    def _region_spheres(self, wanted: "set[str]") -> "dict[str, int]":
        """`{region: the sphere it first becomes reachable in}`, walked over the filled multiworld.

        Regions are recorded BEFORE each sphere's items are collected, so a region opened BY sphere N's items
        is N+1. Deterministic despite iterating sets: only `first[region]`, an integer, escapes.

        ADDENDUM 483 (issue #13): the walk is a playthrough-style sweep of the WHOLE multiworld, so it is now done
        once for every Pokemon XD slot together (cached on the multiworld) and stops as soon as every wanted region
        of every such slot is placed. Neither changes an answer: the spheres do not depend on whose regions are
        watched, and nothing after the last wanted region is recorded anyway."""
        key = frozenset(wanted)
        cache = getattr(self.multiworld, "_pokemon_xd_region_spheres", None)
        if cache is None or cache[0] != key:
            players = sorted(player for player, world in self.multiworld.worlds.items() if world.game == self.game)
            cache = (key, self._walk_region_spheres(key, players))
            self.multiworld._pokemon_xd_region_spheres = cache
        return dict(cache[1].get(self.player, {}))

    def _walk_region_spheres(self, wanted: "frozenset[str]", players: "list[int]") -> "dict[int, dict[str, int]]":
        from BaseClasses import CollectionState

        state = CollectionState(self.multiworld)
        locations = set(self.multiworld.get_filled_locations())
        first: "dict[int, dict[str, int]]" = {player: {} for player in players}
        goal = len(wanted) * len(players)
        index = 0
        while True:
            for player in players:
                seen = first[player]
                for region in wanted:
                    if region not in seen and state.can_reach_region(region, player):
                        seen[region] = index
            if sum(len(seen) for seen in first.values()) >= goal:
                break      # every wanted region of every slot is placed -- the rest of the sweep records nothing
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
        from .randomizer.team_shuffle import pick_distinct_species, resolve_natural_evolution

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
                        seen: "set[int]" = set()
                        for mon in trainer.team:
                            level = final_levels.get(mon.index)
                            if level is not None:
                                mon.level = level
                                mon.species_id = resolve_natural_evolution(
                                    mon.species_id, level, species_pool, self.random,
                                )
                            # ADDENDUM 425: re-evolving can merge two team-mates into one species (two picks
                            # that both end at Golem); the later one is re-rolled, still at its own level.
                            if mon.species_id in seen:
                                legendary = bool(getattr(species_pool.get(mon.species_id), "is_legendary", False))
                                candidates = [sid for sid, sp in species_pool.items()
                                              if sp.is_legendary == legendary]
                                mon.species_id = pick_distinct_species(
                                    self.random, candidates, mon.level, species_pool, seen)
                            seen.add(mon.species_id)
                self._trainer_species_by_dpkm_index = dpkm_species_assignment(trainer_pools)
        if self._reassert_first_chobin(trainer_pools):   # ADDENDUM 461
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
        relocations = getattr(self, "_nightmare_relocations", None) or []
        if not (plans or relocations) or not bool(self.options.path_level_scaling):
            return
        from .randomizer.enhanced_difficulty import ENHANCED_DIFFICULTY_LEVEL_MULTIPLIER
        from .randomizer.path_level_scaling import level_by_trainer_index

        by_trainer = level_by_trainer_index(tier_by_region=self._path_tier_by_region)
        if bool(self.options.enhanced_difficulty_level_scaling):
            by_trainer = {index: max(1, min(100, int(level * ENHANCED_DIFFICULTY_LEVEL_MULTIPLIER)))
                          for index, level in by_trainer.items()}
        self._generated_shadows_relevelled = 0
        from .game_data.real_moveset_data import load_level_up_moves
        from .randomizer.team_shuffle import choose_moveset
        learnsets = load_level_up_moves() if plans else None
        # ADDENDUM 424: Nightmare Citadark's relocated Shadows sit on hosts exactly like generated ones.
        for plan in relocations:
            level = by_trainer.get(int(plan["trainer_index"]))
            if level is not None:
                for shadow in plan["shadows"]:
                    shadow["level"] = level
        for plan in plans or ():
            level = by_trainer.get(int(plan["trainer_index"]))
            if level is None:
                # No known region, so no place on the ramp -- the expansion's vanilla average stands.
                continue
            for mon in plan["new_pokemon"]:
                if mon["level"] != level:
                    self._generated_shadows_relevelled += 1
                    # ADDENDUM 426: its ordinary moves were picked for the old level; a level-up move above the
                    # new one is a move it could not know.
                    if learnsets is not None:
                        picked = choose_moveset(mon["species"], level, learnsets.get(mon["species"], []),
                                                self.random)
                        if picked:
                            mon["moves"] = picked
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
                # Start With Miror Radar and Poke Spots: the Poke Spots' unlock is starting inventory, not a pool item.
                if (include_travel_unlocks and bool(self.options.start_with_poke_spots)
                        and name == items.TRAVEL_UNLOCK_POKE_SPOTS_ITEM_NAME):
                    self.multiworld.push_precollected(self.create_item(name))
                    continue
                if name == items.MACGUFFIN_ITEM_NAME:
                    continue  # ADDENDUM 162 -- its count is the option's, added above, not one-each here
                # ADDENDUM 168: the names dropped from the pool. Their five LOCATIONS stay.
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
        # ADDENDUM 483 (issue #5): the Master Ball, once, as a useful item. It used to ride the progression pass.
        for name in items.GUARANTEED_USEFUL_ITEM_NAMES:
            if name not in items.ITEMS_REMOVED_FROM_POOL:
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
        # ADDENDUM 396: `item_pool` is progression-only at this point, and `default_capacity` is the real,
        # post-exclusion count of locations able to hold one. This is the only place in the world where both
        # numbers exist, so the refusal belongs here rather than in generate_early -- computing it earlier
        # would mean reimplementing locations.py's exclusion ladder and keeping two copies of it honest.
        if len(item_pool) > default_capacity:
            raise OptionError(_capacity_refusal(self, len(item_pool), default_capacity))

        useful_budget = max(0, default_capacity - len(item_pool))
        if useful_budget:
            # ITEMS_REMOVED_FROM_POOL was only checked by the progression pass, so `useful` names slipped in.
            useful_names = sorted(
                name for name, data in ITEM_TABLE.items()
                if data.classification.name == "useful"
                and name not in items.ITEMS_REMOVED_FROM_POOL
                and name not in items.GUARANTEED_USEFUL_ITEM_NAMES
            )
            self.random.shuffle(useful_names)
            draws = (useful_names * items.USEFUL_ITEM_MAX_COPIES)[:useful_budget]
            for name in draws:
                item_pool.append(self.create_item(name))

        # The rest is filler, which EXCLUDED locations require one each of; the cap keeps that supply intact.
        while len(item_pool) < total_locations:
            item_pool.append(self.create_filler())

        # ADDENDUM 470: the Citadark Story Weight Parts are decided HERE and held out of the pool, then placed by
        # pre_fill. Archipelago's own test (`test_itempool_not_modified`) forbids changing the itempool after
        # create_items, which is what pre_fill used to do. `get_pre_fill_items` hands them to every all-state.
        self._story_bound_part_items = self._withhold_story_bound_parts(item_pool)
        for item in self._story_bound_part_items:
            item_pool.remove(item)

        self.multiworld.itempool += item_pool

    def _withhold_story_bound_parts(self, item_pool: "list[PokemonXDItem]") -> "list[PokemonXDItem]":
        """ADDENDUM 435's roll, made in create_items (ADDENDUM 470): on `citadark_story_weight` percent of
        location-shuffle-off seeds, `available - required + 1` Parts are kept for the late story."""
        if self.options.randomize_travel_locations or not self.options.robo_kyogre_parts_unlock_citadark:
            return []
        weight = int(self.options.citadark_story_weight)
        if weight <= 0 or self.random.randrange(100) >= weight:
            return []
        parts = [item for item in item_pool if item.name == items.MACGUFFIN_ITEM_NAME]
        bind = len(parts) - int(self.options.robo_kyogre_parts_required) + 1
        if bind <= 0 or bind > len(parts):
            return []
        return parts[:bind]

    def get_pre_fill_items(self) -> "list[PokemonXDItem]":
        """ADDENDUM 470: the Story-Weight Parts not yet placed -- in no itempool, so every all-state needs them."""
        if getattr(self, "_hide_bound_parts", False):
            return []
        return [item for item in getattr(self, "_story_bound_part_items", None) or () if item.location is None]

    def create_item(self, name: str) -> PokemonXDItem:
        return items.create_item(self, name)

    def get_filler_item_name(self) -> str:
        return items.get_random_filler_item_name(self)

    def create_filler(self) -> PokemonXDItem:
        name = self.get_filler_item_name()
        if name == items.MASTER_BALL_ITEM_NAME:
            # An extra Master Ball drawn as filler is filler, so it can sit on any location.
            return PokemonXDItem(name, ItemClassification.filler, self.item_name_to_id[name], self.player)
        return self.create_item(name)

    def set_rules(self) -> None:
        rules.set_all_rules(self)

    def pre_fill(self) -> None:
        """ADDENDUM 430: no Robo Kyogre Part may sit on Citadark Isle or on anything that needs it -- zero Parts,
        ever.

        Logic alone forbids only the Parts the gate COUNTS: with more available than required, the spare ones
        were legal on the island. So: with every entrance into Citadark Isle closed, sweep this multiworld with
        every item, and any of this player's locations still unreachable is Citadark-reliant -- the island, its
        chests and trainers, and anything whose rule needs them (late purification counts, the goal). Each gets
        an item rule refusing this player's Parts. Run here, after every world's rules exist, and only when Parts
        are actually in the pool."""
        self._citadark_reliant_locations = frozenset()
        if not any(item.player == self.player and item.name == items.MACGUFFIN_ITEM_NAME
                   for item in [*self.multiworld.itempool, *(getattr(self, "_story_bound_part_items", None) or ())]):
            return
        from worlds.generic.Rules import add_item_rule

        citadark = self.multiworld.get_region("Citadark Isle", self.player)
        saved = [(entrance, entrance.access_rule) for entrance in citadark.entrances]
        try:
            for entrance, _rule in saved:
                entrance.access_rule = lambda state: False
            state = self.multiworld.get_all_state()
            reliant = frozenset(location.name for location in self.multiworld.get_locations(self.player)
                                if location.item is None and not location.can_reach(state))
        finally:
            for entrance, rule in saved:
                entrance.access_rule = rule
        part, player = items.MACGUFFIN_ITEM_NAME, self.player
        for name in reliant:
            add_item_rule(self.multiworld.get_location(name, self.player),
                          lambda item, _part=part, _player=player: not (item.player == _player and item.name == _part))
        self._citadark_reliant_locations = reliant
        self._bind_parts_to_late_story()

    #: ADDENDUM 435: the late story, for Citadark Story Weight -- from the stranded SS Libra on, Citadark excluded.
    LATE_STORY_REGIONS: "tuple[str, ...]" = (
        "SS Libra (stranded)", "Kaminko's House (Robo Groudon)", "SS Libra", "Cipher Key Lair (exterior)",
        "Outskirt Stand", "Snagem Hideout", "Cipher Key Lair", "Cipher Key Lair (deep)",
    )

    def _bind_parts_to_late_story(self) -> None:
        """ADDENDUM 435. With location shuffle off, Citadark can be Parts-only, but it should still have you
        complete most of the story most of the time; exceptions are fine.

        With location shuffle off, Citadark needs only the Parts (regions.TRAVEL_SHUFFLE_PARTS_SOURCE). On
        `citadark_story_weight` percent of seeds, `available - required + 1` Parts are placed now in this world's
        late-story locations -- so at most `required - 1` can be anywhere else, and the ride waits on the late
        story. The rest of the Parts, and every Part on the other seeds, go wherever fill puts them. A seed with
        too few late locations places the held Parts anywhere in this world instead (ADDENDUM 470; noted in the
        spoiler log) -- they are in no itempool, so they cannot be handed back to the ordinary fill."""
        # ADDENDUM 470: the roll and the choice of Parts happened in create_items (`_withhold_story_bound_parts`);
        # those Parts are in no itempool, so this places them and touches nothing else. Idempotent: a second
        # pre_fill (some harnesses run the step twice) finds nothing left to place.
        chosen = list(getattr(self, "_story_bound_part_items", None) or ())
        pending = [item for item in chosen if item.location is None]
        self._story_bound_parts = 0
        if not chosen:
            return
        if pending:
            late = [location for region in self.LATE_STORY_REGIONS
                    for location in self.multiworld.get_region(region, self.player).locations
                    if location.item is None and location.address is not None
                    and location.progress_type != LocationProgressType.EXCLUDED
                    and location.name not in self._citadark_reliant_locations
                    and not location.name.startswith("Story - Krane Memo")]
            if len(late) < len(pending):
                self._story_bind_note = (f"Citadark Story Weight: only {len(late)} late-story location(s) for "
                                         f"{len(pending)} Robo Kyogre Parts -- placed anywhere in this world.")
                late = []
            self.random.shuffle(late)
            self._place_bound_parts(late, pending, allow_partial=True, name="late-story")
        # Anything the late story could not hold still has to be placed somewhere -- it is in no itempool. Any of
        # this world's own fillable, non-Citadark-reliant locations: ordinary fill would have done the same.
        rest = [item for item in chosen if item.location is None]
        if rest:
            anywhere = [location for location in self.multiworld.get_locations(self.player)
                        if location.item is None and location.address is not None
                        and location.progress_type != LocationProgressType.EXCLUDED
                        and location.name not in self._citadark_reliant_locations]
            self.random.shuffle(anywhere)
            self._place_bound_parts(anywhere, rest, allow_partial=False, name="fallback")
        late_names = {location.name for region in self.LATE_STORY_REGIONS
                      for location in self.multiworld.get_region(region, self.player).locations}
        self._story_bound_parts = sum(1 for item in chosen
                                      if item.location is not None and item.location.name in late_names)

    def _place_bound_parts(self, locations: list, parts: list, allow_partial: bool, name: str) -> None:
        from Fill import fill_restrictive

        if not locations or not parts:
            return
        # The state every OTHER item gives: the Parts being placed are left out, or the fill would let a Part sit
        # behind itself. `_hide_bound_parts` takes them out of `get_pre_fill_items` for this one all-state.
        self._hide_bound_parts = True
        try:
            state = self.multiworld.get_all_state(False)
        finally:
            self._hide_bound_parts = False
        for item in [i for i in (getattr(self, "_story_bound_part_items", None) or ()) if i.location is None
                     and i not in parts]:
            self.collect(state, item)
        # fill_restrictive pops from the lists it is given, so it gets copies.
        fill_restrictive(self.multiworld, state, list(locations), list(parts), single_player_placement=True,
                         lock=True, allow_partial=allow_partial, name=f"Pokemon XD {name} Robo Kyogre Parts")

    def _map_place_levels(self) -> "dict[str, int]":
        """{in-game place name: the level of its first visit's trainers in this seed}, for the world-map text.

        A place's trainers are fought across the whole story (Chobin at Kaminko's from Lv 6 to Lv 50, Laken at Gateon
        from 7 to 66), so an average of all of them describes no visit. The first visit is each trainer's first
        appearance (no rematch rows), in the place's earliest region (the one whose trainers are lowest), and the
        level shown is the median there, so one late fight that shares the region (Ardos at Gateon) cannot drag it.
        Levels are the ones this seed's teams really carry."""
        import statistics

        from .game_data import map_level_text, trainer_placements, trainer_roster

        levels = self._final_trainer_levels()
        out: "dict[str, int]" = {}
        for place, regions in map_level_text.PLACE_REGIONS.items():
            by_region: "dict[str, list[float]]" = {}
            any_row: "dict[str, list[float]]" = {}
            for index, level in levels.items():
                region = trainer_placements.region_for(index)
                if region not in regions:
                    continue
                any_row.setdefault(region, []).append(level)
                trainer = trainer_roster.TRAINERS_BY_INDEX.get(index) or {}
                if int(trainer.get("occurrence", 1) or 1) > 1:
                    continue
                by_region.setdefault(region, []).append(level)
            by_region = by_region or any_row   # a place of rematch rows only still gets a level
            if not by_region:
                continue
            first = min(by_region.values(), key=statistics.median)
            out[place] = max(1, min(100, int(round(statistics.median(first)))))
        return out

    def _shadow_rescues(self) -> "list[dict[str, Any]]":
        """The Cave Poke Spot Miror B. Shadow, for the client's hand-off to his pool (see fill_slot_data)."""
        from .tools.xd_species_index import INTERNAL_INDEX_TO_NATIONAL_DEX, internal_index_for_national_dex

        ddpk = 29
        dex = next((int(d) for d, ddpks in (getattr(self, "_shadow_catch_ddpks", None) or {}).items()
                    if ddpk in {int(x) for x in ddpks}), None)
        internal = internal_index_for_national_dex(dex) if dex is not None else None
        name = INTERNAL_INDEX_TO_NATIONAL_DEX.get(internal, (None, None))[1] if internal else None
        return [{
            "label": "Miror B. at the Cave Poke Spot",
            "cap": 0x3C,
            "areas": [["Poke Spots", 0x3C]],
            "message": "{name}, Miror B.'s Shadow from the Cave Poke Spot, is with him now -- catch it from his team.",
            "shadows": [{"species": internal, "name": str(name).title() if name else "His Shadow", "ddpk": ddpk,
                         "dex": dex}],
        }]

    def _final_trainer_levels(self) -> "dict[int, float]":
        """{trainer index: average level of its ordinary team} as this seed ships it: the story deck's final teams
        after the path ramp and Enhanced Difficulty (`pre_output`), else the same composition recomputed."""
        import re

        out: "dict[int, float]" = {}
        for pool in getattr(self, "_trainer_team_pools", None) or ():
            if "Story" not in str(getattr(pool, "name", "")):
                continue
            for trainer in pool.trainers:
                match = re.match(r"Trainer #(\d+)", str(trainer.name))
                values = [int(mon.level) for mon in trainer.team if getattr(mon, "level", None)]
                if match and values:
                    out[int(match.group(1))] = sum(values) / len(values)
        if out:
            return out
        from .game_data.real_trainer_data import real_trainer_team_census

        levels: "dict[int, float]" = {}
        if bool(self.options.path_level_scaling):
            from .randomizer.path_level_scaling import level_by_trainer_index

            levels = {i: float(v) for i, v in
                      level_by_trainer_index(tier_by_region=getattr(self, "_path_tier_by_region", None)).items()}
        for row in real_trainer_team_census() or ():
            levels.setdefault(int(row["trainer_index"]), float(row["avg_level"]))
        if bool(self.options.enhanced_difficulty_level_scaling):
            from .randomizer.enhanced_difficulty import ENHANCED_DIFFICULTY_LEVEL_MULTIPLIER
            levels = {i: min(100.0, v * ENHANCED_DIFFICULTY_LEVEL_MULTIPLIER) for i, v in levels.items()}
        return levels

    def fill_slot_data(self) -> Mapping[str, Any]:
        slot_data: dict[str, Any] = dict(
            self.options.as_dict(
                "randomize_shadow_species",
                "shuffle_trainer_defeats",
                "trainer_defeat_check_count", "trainer_defeat_mode",
                "shadow_pokemon_expansion", "enhanced_difficulty",
                "exclude_mt_battle_trainers", "randomize_travel_locations", "randomize_shops", "goal",
                "death_link",  # ADDENDUM 351 -- the client turns the DeathLink tag on from this
                "agate_village_pit_stop",  # ADDENDUM 311 -- the client stops treating Agate's shop as a shop
                "reduce_citadark_grind",  # ADDENDUM 427 -- the client describes the Candy Box at Gateon
                "purification_checks",  # ADDENDUM 415 -- off: the client sends no `Purify N`
                # ADDENDUM 196: both options are gone -- the area memory arms off randomize_travel_locations.
                "key_item_shuffle",
                "nightmare_citadark",  # ADDENDUM 423
                "nightmare_greevil", "trade_evolutions_by_level",  # ADDENDUM 429
                "remove_citadark_shadows", "remove_greevil_shadows",  # ADDENDUM 431
                "citadark_admins_only",  # the client marks the other Citadark trainers beaten
                "no_legendary_shadows", "shuffle_shadow_lugia", "legendary_trainer_pokemon",  # ADDENDUM 435
                "text_speed", "hold_b_to_advance", "battle_speed", "citadark_story_weight",  # ADDENDUM 435
                "shuffle_scooter_upgrade",
                "robo_kyogre_parts_unlock_citadark", "robo_kyogre_parts_required",
                "disable_move_animations",  # ADDENDUM 454 -- the client's live guard
                # Everything else that decides which locations exist or what logic needs, for trackers.
                "robo_kyogre_parts_available", "pokespot_catch_checks", "shadow_catch_progression",
                "citadark_progression_chance", "mt_battle_progression_checks", "purification_progression_cap",
                "randomize_starter", "path_level_scaling", "map_trainer_levels", "enhanced_difficulty_level_scaling",
                "catch_rate_scaling", "catch_rate_exclude_citadark", "catch_rate_exclude_greevil",
                "shadow_inherited_moves", "infinite_tms", "single_master_ball",
                "all_pokemon_learn_all_tms", "shadow_move_tms", "physical_special_split",
                "update_moves_to_gen_9",
                # Only the toggle travels; the per-seed plans are heavy and only iso_patcher.py needs them.
            )
        )
        # Every option this world defines, so a tracker can rebuild which locations exist and what logic needs.
        for _name, _value in self.options.as_dict(*ut_option_names()).items():
            slot_data.setdefault(_name, _value)
        # ADDENDUM 453/454: the Ability Swap is on Gateon's last shelf in every seed (a Bag USE item; the patch does it).
        slot_data["ability_patch"] = True
        slot_data["candy_box"] = True   # item 50 is a Candy Box in every seed
        if self._trainer_team_fingerprints:
            # ADDENDUM 155: {location -> that trainer's real species}, ambiguous surnames only -- which Dosk.
            slot_data["trainer_team_fingerprints"] = self._trainer_team_fingerprints
        if self._shadow_species_assignment is not None:
            # Per-seed dex -> location map for the client's live detection, preferred over shadow_species.py's
            # static vanilla map. Also backs /shadowdex, so the original name and dex ride along.
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
        if bool(getattr(self.options, "map_trainer_levels", 0)):
            try:
                slot_data["map_place_levels"] = self._map_place_levels()
            except Exception:
                pass   # cosmetic: never worth failing a generation over
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
        # ADDENDUM 443: the starter and its line -- the client's "owned without purifying" set.
        slot_data["starter_dex"] = int(self.starter_dex)
        slot_data["starter_line_dex"] = sorted(self.starter_line_dex)
        # For trackers: how many "Purify N" checks this seed has, and the Data Storage key the client keeps the
        # current room in ({team} and {slot} filled from the connection).
        slot_data["purification_location_count"] = int(getattr(self, "_purification_location_count", 0) or 0)
        slot_data["room_id_key"] = ROOM_ID_KEY_TEMPLATE
        slot_data["room_area_key"] = ROOM_AREA_KEY_TEMPLATE
        # Missable Trainer Shadows: each missable host's label and the Shadows on it, for the client's hand-off to
        # Miror B. once that fight's area cap passes.
        slot_data["missable_trainer_shadows"] = bool(self.options.missable_trainer_shadows)
        # Vanilla bug: lose to Miror B. at the Cave Poke Spot and his Shadow (DDPK 29, Voltorb in vanilla) is never met
        # again. Once the story is past that fight the client hands it to his pool if it was never snagged.
        slot_data["shadow_rescues"] = self._shadow_rescues()
        # Shadow Move TMs: [{"tm": "TM05", "move": "Shadow Rush"}, ...].
        from .game_data.tm_moves import SHADOW_MOVE_NAMES
        slot_data["shadow_move_tm_list"] = [
            {"tm": f"TM{tm:02d}", "move": SHADOW_MOVE_NAMES[move]}
            for tm, move in getattr(self, "_shadow_move_tms", [])
        ]
        from .game_data.missable_autosend import AUTO_SEND_ONE_SHOT_INDICES
        slot_data["missable_shadow_hosts"] = [
            {"label": AUTO_SEND_ONE_SHOT_INDICES[host], "trainer_index": int(host),
             "shadows": [{"species": entry["species"], "name": entry["name"], "ddpk": entry.get("ddpk"),
                          "dex": entry.get("dex")}
                         for entry in shadows]}
            for host, shadows in sorted(getattr(self, "_missable_shadow_hosts", {}).items())
            if host in AUTO_SEND_ONE_SHOT_INDICES and shadows
        ]
        slot_data["location_table_fingerprint"] = locations.LOCATION_TABLE_FINGERPRINT
        slot_data["location_count"] = len(locations.LOCATION_TABLE)
        # ADDENDUM 404: the option is gone but the key stays -- the client gates its chest detector on it, and a
        # client from this build connecting to an older seed still needs to read the old value.
        slot_data["randomize_chests"] = True
        # ADDENDUM 403: what Universal Tracker needs to regenerate this exact world -- see the block above the class.
        slot_data[UT_SLOT_DATA_KEY] = {
            "format": UT_SLOT_DATA_FORMAT,
            "seed": self._ut_seed,
            "options": self.options.as_dict(*ut_option_names()),
        }
        return slot_data

    def extend_hint_information(self, hint_data: "dict[int, dict[int, str]]") -> None:
        """Every "Catch - {species}" hint names who holds that species this seed and where. The per-seed
        half a location name cannot carry; see catch_sources.py. Every trainer-defeat hint names the area(s) it is
        fought in (defeat_hints.py, ADDENDUM 489)."""
        texts = catch_sources.sources_by_location(self)
        # ADDENDUM 489: the trainer-defeat checks name where they are fought, the same way.
        from .defeat_hints import defeat_hint_texts
        for name, text in defeat_hint_texts(self).items():
            texts.setdefault(name, text)
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
        # This writes a small, inspectable seed file, never an ISO or a diff.
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
            evolve_for_final_levels,
            PERMANENTLY_EXCLUDED_TRAINER_INDICES,
            settle_padding_members,
            cap_for_option as _enhanced_difficulty_cap,
            shadow_level_assignment,
        )
        # ADDENDUM 266: the ramp comes from story_bytes' entry floors, not a hand-written ordering.
        from .randomizer.path_level_scaling import (
            FIRST_TIER_LEVEL as PATH_FIRST_TIER_LEVEL,
            LAST_TIER_LEVEL as PATH_LAST_TIER_LEVEL,
            CITADARK_LEVEL as PATH_CITADARK_LEVEL,
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
            # ADDENDUM 440: the heart-gauge percentage; the patcher scales every in-use DDPK record's gauge.
            "purification_rate": 100,
            # ADDENDUM 443: None keeps Eevee; otherwise {"dex", "internal", "moves"}.
            "starter": None,
            # ADDENDUM 463: a plain flag -- the patcher changes one main.dol word so a TM is kept like an HM.
            "infinite_tms": False,
            "all_tms_learnable": False,
            "shadow_move_tms": [],
            # Plain flags -- the patcher writes each move's Generation IX category (the split) and its other
            # Generation IX fields (gen9_moves) into common_rel's move table.
            "physical_special_split": False,
            "gen9_moves": False,
            # A plain flag -- the patcher changes one main.dol float, the people module's 30.0, to 60.0.
            "increased_walk_speed": False,
            "quick_purification_ceremony": False,
            # ADDENDUM 441: 0 is vanilla. With it on, {trainer index: 0..1000 progress} travels too.
            "catch_rate_scaling": 0,
            "catch_rate_progress_by_trainer": None,
            # ADDENDUM 291/454: a plain flag -- the patcher writes main.dol's waza_func_data animation pointers.
            "disable_move_animations": False,
            "skip_opening_movie": False,
            # Same: the stats table and in-use DDPK catch-rate overrides are read off the ISO at patch time.
            "max_catch_rate": False,
            "max_catch_rate_excluded_trainers": [],   # ADDENDUM 416
            # ADDENDUM 423: {citadark trainer index: the team's patch entry}, or None when off.
            "nightmare_citadark_teams": None,
            # ADDENDUM 424: [{"trainer_index": host, "shadows": [{ddpk_index, dpkm_index, species, level}]}].
            "nightmare_shadow_relocations": None,
            "shadow_vacated_slots": None,
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

            # Runs AFTER shuffle_teams(), so movesets are drawn for each slot's FINAL species. ADDENDUM 427: always,
            # not behind an option -- the TM/move functionality is separate from the enhanced difficulty options
            # and is on by default.
            level_up_moves = load_level_up_moves()
            if level_up_moves is not None:
                # move_count omitted on purpose -- assign_movesets' own MOVESET_SHUFFLE_DEFAULT_MOVE_COUNT
                # (4 since ADDENDUM 217). It was 3 from ADDENDUM 35 for a measured DeckData_Story.bin LZSS
                # budget overflow that black-screened the game. Do not pin a number here.
                moves_assignment = assign_movesets(trainer_pools, level_up_moves, self.random)
                seed_data["trainer_moves_by_dpkm_index"] = {
                    str(dpkm_index): moves for dpkm_index, moves in moves_assignment.items()
                }
                # ADDENDUM 461: Chobin #1's moves are the ones the battle sims were run against.
                if getattr(self, "_first_chobin", None):
                    from .game_data import first_battle
                    from .randomizer.team_shuffle import MOVESET_SHUFFLE_DEFAULT_MOVE_COUNT

                    first = self._first_chobin
                    seed_data["trainer_moves_by_dpkm_index"][str(first_battle.FIRST_CHOBIN_DPKM_INDEX)] = (
                        list(first["moves"]) + [0] * (MOVESET_SHUFFLE_DEFAULT_MOVE_COUNT - len(first["moves"])))
                    seed_data["first_chobin"] = dict(first)
                    seed_data["notes"].append(first_battle.describe(first))
                seed_data["notes"].append(
                    "movesets: every ordinary trainer Pokemon's moves are drawn from what its species can know "
                    "at its level in Gen III, plus one TM/HM, tutor or egg move it can learn (ADDENDUM 426/427)."
                )
            else:
                seed_data["notes"].append(
                    "No level-up moveset data in this build -- trainer movesets were NOT rebuilt for this seed."
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
        # 31), so the chest patch is identical across seeds. ADDENDUM 404: always present now.
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
        # ADDENDUM 427: Gateon's Gorigan tier sells a Rare Candy and a Candy Box. ADDENDUM 437: shops randomized or not.
        seed_data["reduce_citadark_grind"] = bool(self.options.reduce_citadark_grind)
        seed_data["candy_box"] = True   # the Candy Box works in every seed; the option adds the Gateon shelf
        # ADDENDUM 456: `equal_to_citadark_entry` -- the Candy Box levels to the lowest level on any Citadark Isle
        # trainer. The patcher reads that level off the patched ISO (after Enhanced Difficulty, Path Level Scaling and
        # every other team pass), so the seed carries only the mode and which trainers count as Citadark.
        if int(self.options.reduce_citadark_grind.value) == 2:
            from .game_data import trainer_placements as _placements
            seed_data["candy_box_target"] = "citadark_entry"
            seed_data["citadark_trainer_indices"] = sorted(
                index for index, placement in _placements.PLACEMENTS.items()
                if placement.region == "Citadark Isle")
        seed_data["ability_patch"] = True   # ADDENDUM 453: regardless of options

        # Covers whichever dummies this seed plants: shop berries, chest berries, both or neither.
        item_rename_targets: dict[int, str] = {}
        if self.options.randomize_shops:
            item_rename_targets.update(USELESS_BERRY_ID_TO_NAME)
        # ADDENDUM 404: chests are always checks
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

        # Only the Sixes' Cipher Lab fights field their Shadows (shadow_mirrors.SIXES_PHENAC_SHADOW_SLOTS).
        from .game_data.shadow_mirrors import SIXES_PHENAC_SHADOW_SLOTS
        seed_data["ordinary_shadow_slots"] = [{"row": row, "ddpk_index": ddpk} for row, ddpk in SIXES_PHENAC_SHADOW_SLOTS]
        # Missable Trainer Shadows: Miror B. brings two Shadows at the Poke Spots once two are waiting.
        seed_data["miror_b_two_shadows"] = bool(self.options.missable_trainer_shadows)
        # Shadow Pokemon Expansion (ADDENDUM 70). Reuses self._shadow_expansion_plans; rebuilding it off the
        # same self.random would disagree with this seed's locations. shadow_slots_consumed_by_trainer is what
        # ED's census subtracts before padding -- same pre-patch free-slot count, expansion writes first.
        shadow_slots_consumed_by_trainer: dict[int, int] = {}
        # ADDENDUM 424: Nightmare Citadark's relocated Shadows hold their host slots too.
        _relocation_slots = {int(p["trainer_index"]): len(p["shadows"]) for p in self._nightmare_relocations}
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
        seed_data["purification_rate"] = int(self.options.purification_rate.value)   # ADDENDUM 440
        # ADDENDUM 441: catches harden along this seed's own area order (the sphere walk, both travel modes).
        # ADDENDUM 447/448: one option -- off, location_scaled (the world's own percentage) or guaranteed_catches (the
        # old Max Catch Rate) -- with the Citadark/Greevil exclusions applying to both. The patcher's seed keys are
        # unchanged: a percentage for the scaled pass, a flag for the guarantee.
        catch_choice = self.options.catch_rate_scaling
        catch_scaled = catch_choice == catch_choice.option_location_scaled
        catch_guaranteed = catch_choice == catch_choice.option_guaranteed_catches
        catch_excluded = catch_rate_excluded_trainer_indices(
            bool(self.options.catch_rate_exclude_citadark),
            bool(self.options.catch_rate_exclude_greevil),
        ) if (catch_scaled or catch_guaranteed) else frozenset()
        seed_data["catch_rate_scaling"] = CATCH_RATE_LOCATION_SCALED_KEEP_PERCENT if catch_scaled else 0
        if seed_data["catch_rate_scaling"]:
            seed_data["catch_rate_progress_by_trainer"] = {
                str(index): permille for index, permille in sorted(self._catch_progress_by_trainer().items())
                if index not in catch_excluded}
        # ADDENDUM 429: the species table's trade evolutions become level-ups (and the Candy Box table knows).
        seed_data["trade_evolutions_by_level"] = bool(self.options.trade_evolutions_by_level)
        # ADDENDUM 451: friendship evolutions are level-ups in every seed (no option).
        seed_data["friendship_evolutions_by_level"] = True
        # ADDENDUM 435: what Citadark Story Weight did this seed.
        if getattr(self, "_story_bound_parts", 0):
            seed_data["notes"].append(f"Citadark Story Weight: {self._story_bound_parts} Robo Kyogre Parts placed in "
                                      "the late story (SS Libra onward).")
        elif getattr(self, "_story_bind_note", None):
            seed_data["notes"].append(self._story_bind_note)
        # ADDENDUM 384: the formula divisor the patcher will write, chosen here so the seed carries the
        # decision rather than the patcher re-deriving it from the rate.
        from .game_data.species_stats import choose_exp_divisor
        seed_data["exp_divisor"] = choose_exp_divisor(int(self.options.experience_rate.value))
        seed_data["disable_move_animations"] = bool(self.options.disable_move_animations)
        seed_data["skip_opening_movie"] = bool(self.options.skip_opening_movie)
        # ADDENDUM 454: every world-map place keeps one description (the client's story-byte writes made the
        # hovered text flip). Every seed; a seed without the key is left alone.
        seed_data["map_descriptions_constant"] = True
        # ADDENDUM 435: the text and battle-pacing patches (main.dol).
        seed_data["text_speed"] = int(self.options.text_speed)
        seed_data["hold_b_to_advance"] = bool(self.options.hold_b_to_advance)
        seed_data["battle_speed"] = int(self.options.battle_speed)
        seed_data["increased_walk_speed"] = bool(getattr(self.options, "increased_walk_speed", 0))
        seed_data["quick_purification_ceremony"] = bool(getattr(self.options, "quick_purification_ceremony", 0))
        seed_data["max_catch_rate"] = bool(catch_guaranteed)   # ADDENDUM 447/448
        seed_data["infinite_tms"] = bool(getattr(self.options, "infinite_tms", 0))   # ADDENDUM 463
        seed_data["all_tms_learnable"] = bool(getattr(self.options, "all_pokemon_learn_all_tms", 0))
        seed_data["physical_special_split"] = bool(getattr(self.options, "physical_special_split", 0))
        seed_data["gen9_moves"] = bool(getattr(self.options, "update_moves_to_gen_9", 0))
        seed_data["escape_rope"] = True   # a key item that takes you to the world map, in every seed
        seed_data["kaminko_trainers"] = bool(self.options.kaminko_missable_trainers)
        seed_data["citadark_admins_only"] = bool(self.options.citadark_admins_only)
        seed_data["shadow_move_tms"] = [[int(tm), int(move)] for tm, move in getattr(self, "_shadow_move_tms", [])]
        seed_data["shadow_engine_fixes"] = True   # ADDENDUM 465: snagged Shadows stay gone; the Shadow list's species
        # ADDENDUM 443: the starter's species (internal index) and four moves, five main.dol immediates.
        if self._starter:
            seed_data["starter"] = {"dex": self._starter["dex"], "internal": self._starter["internal"],
                                    "moves": list(self._starter["moves"])}
            seed_data["notes"].append(
                f"Starter: {species.NATIONAL_DEX.get(self._starter['dex'], self._starter['dex'])} "
                f"(moves {', '.join(str(m) for m in self._starter['moves'])}).")
        if self._nightmare_teams:
            from .game_data.nightmare_citadark import seed_entry

            seed_data["nightmare_citadark_teams"] = {
                str(trainer): seed_entry(key) for trainer, key in sorted(self._nightmare_teams.items())}
        if self._nightmare_relocations:
            seed_data["nightmare_shadow_relocations"] = self._nightmare_relocations
        if self._shadow_vacated_slots and self._nightmare_relocations:
            # ADDENDUM 431: the slots that keep an ordinary copy of the Pokemon whose Shadow moved away.
            seed_data["shadow_vacated_slots"] = self._shadow_vacated_slots
        # ADDENDUM 416: the trainers whose Shadows keep their vanilla catch rate under Max Catch Rate. Trainer
        # indices, not DDPK indices -- the expansion's Shadows get their DDPK slots at patch time, so the patcher
        # resolves the slots off the patched DeckData_Story.bin itself.
        seed_data["max_catch_rate_excluded_trainers"] = (
            sorted(catch_excluded) if seed_data["max_catch_rate"] else [])

        path_scale_levels = bool(self.options.path_level_scaling)
        if ed_added_members != 0 or ed_scale_levels or path_scale_levels:
            ed_team_census = real_trainer_team_census()
            ed_species_pool = real_species_pool()
            ed_level_up_moves = load_level_up_moves()
            if ed_team_census and ed_species_pool and ed_level_up_moves:
                # Subtract the expansion's claim before ED plans padding, or trainers are over-committed.
                _reserved = dict(shadow_slots_consumed_by_trainer)
                for _host, _count in _relocation_slots.items():
                    _reserved[_host] = _reserved.get(_host, 0) + _count
                # ADDENDUM 467: the copies of those Shadows on the hosts' other occurrences hold slots as well.
                for _host, _count in (getattr(self, "_shadow_mirror_slots", None) or {}).items():
                    _reserved[_host] = _reserved.get(_host, 0) + _count
                ed_team_census = adjust_team_census_for_reserved_slots(ed_team_census, _reserved)
                # A no-op frozenset(): MT_BATTLE_TRAINER_INDICES is permanently empty here.
                enhanced_difficulty_plan = build_enhanced_difficulty_plan(
                    ed_team_census,
                    ed_species_pool,
                    ed_level_up_moves,
                    self.random,
                    excluded_trainer_indices=MT_BATTLE_TRAINER_INDICES if self.options.exclude_mt_battle_trainers else frozenset(),
                    # ADDENDUM 423: Nightmare Citadark's trainers are a fixed six at level 100 -- no padding and
                    # no multiplier. The patch replaces every slot anyway; this keeps the plan honest.
                    permanently_excluded_trainer_indices=(
                        PERMANENTLY_EXCLUDED_TRAINER_INDICES | frozenset(self._nightmare_teams or ())
                    ),
                    max_added_members=ed_added_members,
                    scale_levels=ed_scale_levels,
                    # ADDENDUM 425: padding never repeats a species its team already fields.
                    team_species_by_trainer=self._story_team_species(),
                    allow_legendaries=bool(self.options.legendary_trainer_pokemon),   # ADDENDUM 435
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
                        f"{PATH_FIRST_TIER_LEVEL} in the opening areas to {PATH_LAST_TIER_LEVEL} at the last "
                        f"area before Citadark Isle, which always comes last at {PATH_CITADARK_LEVEL}. Trainers "
                        "with no known placement kept their vanilla levels."
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
                # ADDENDUM 425: padding re-levelled onto the ramp re-evolves at its final level, stays distinct.
                _settled = settle_padding_members(
                    enhanced_difficulty_plan, ed_species_pool, ed_level_up_moves, self.random,
                    self._story_team_species(), allow_legendaries=bool(self.options.legendary_trainer_pokemon))
                if _settled:
                    seed_data["notes"].append(
                        f"enhanced_difficulty: {_settled} team additions re-evolved at their final level.")
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
                    allow_legendaries=bool(self.options.legendary_trainer_pokemon),   # ADDENDUM 435
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
                # ADDENDUM 425: Mt. Battle's species are never randomized, so a member whose level the plan raises
                # kept its vanilla, lower-level form. Evolve it for the level it is really fought at, then settle
                # the padding against the teams as they now stand.
                if self.options.exclude_mt_battle_trainers:
                    _mt_species = {
                        slot["dpkm_index"]: slot["species"]
                        for trainer in (load_json_data_file("mtbattle_trainer_census.json") or ())
                        for slot in trainer.get("team", ()) if slot.get("kind") == "DPKM"
                    }
                    _mt_evolved = evolve_for_final_levels(
                        _mt_species, mt_battle_enhanced_difficulty_plan["level_assignment"], mt_species_pool,
                        self.random)
                    mt_battle_enhanced_difficulty_plan["species_assignment"] = _mt_evolved
                else:
                    _mt_evolved = self._randomize_mt_battle_teams(
                        mt_battle_enhanced_difficulty_plan, mt_species_pool, mt_level_up_moves, seed_data)
                _mt_team_species = {
                    trainer["index"]: {_mt_evolved.get(slot["dpkm_index"], slot["species"])
                                       for slot in trainer.get("team", ()) if slot.get("kind") == "DPKM"}
                    for trainer in (load_json_data_file("mtbattle_trainer_census.json") or ())
                }
                settle_padding_members(mt_battle_enhanced_difficulty_plan, mt_species_pool, mt_level_up_moves,
                                       self.random, _mt_team_species,
                                       allow_legendaries=bool(self.options.legendary_trainer_pokemon))
                if _mt_evolved:
                    seed_data["notes"].append(
                        f"Mt. Battle: {len(_mt_evolved)} members evolved for the level they are fought at.")
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

        # ADDENDUM 427: Shadows get legal movesets. A Shadow's four ordinary moves are its DPKM
        # record's, and with its species randomized they were the replaced Shadow's -- often moves the new species
        # cannot know. Drawn here, after every level pass, for the species and level it is really fought at, by
        # the same rule as every other trainer Pokemon. A vanilla-species Shadow keeps the moves the game gave it.
        self._assign_shadow_movesets(seed_data)

        # Mt. Battle's teams are randomized whenever its trainers are checks. With no level option on, nothing above
        # built a Mt. Battle plan, so one that changes only species and moves is built here.
        if not self.options.exclude_mt_battle_trainers and seed_data["mt_battle_enhanced_difficulty_plan"] is None:
            _mt_pool, _mt_moves = real_species_pool(), load_level_up_moves()
            if _mt_pool and _mt_moves and load_json_data_file("mtbattle_trainer_census.json"):
                _plan = {"level_assignment": {}, "new_dpkm_entries": [], "team_slot_plan": []}
                self._randomize_mt_battle_teams(_plan, _mt_pool, _mt_moves, seed_data)
                seed_data["mt_battle_enhanced_difficulty_plan"] = _plan

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
