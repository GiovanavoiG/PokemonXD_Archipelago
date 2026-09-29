"""Poke Spot wild-encounter roster, and the generation-time species reassignment that fills it.

The 11 vanilla slots across 4 pools, reassigned to species this seed's Shadow pool does not already cover so
the two features between them put as much of the 386-species "Catch - {species}" category in reach as
possible. Hardcoded rather than re-read from a REL, because generation has no ISO access: decoded from the
real `common.fsys` -> `common_rel.rel` Poke Spot tables (pointers in
`xd_rel_format.POKESPOT_POOL_POINTERS`) and cross-checked against two independent vanilla-roster write-ups,
which agreed once this game's internal-index quirk (`tools/xd_species_index.py`) was accounted for.

Only the species field is reassigned -- level range, encounter percentage and steps-per-snack keep their
vanilla values, so this dataclass does not carry them. Entry order matches the REL array order (index 0 =
highest encounter percentage in the pool), which is what `xd_rel_format.pokespot_species_offset` expects.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .real_trainer_data import LEGENDARY_NATIONAL_DEX
from ..species import NATIONAL_DEX
from ..tools.xd_species_index import internal_index_for_national_dex


@dataclass(frozen=True)
class PokeSpotSlot:
    pool: str  # "rock" | "oasis" | "cave" | "all" -- matches tools/xd_rel_format.py's POKESPOT_POOL_POINTERS
    slot_index: int  # 0-based index within that pool's own REL array
    vanilla_species_index: int  # internal species index (xd_species_index.py) of the real vanilla occupant
    vanilla_dex: int  # that occupant's National Dex number
    vanilla_name: str  # that occupant's display name


# 3 slots each for Rock/Oasis/Cave, 2 for the "All"-spot bonus pool. Bonsly and Munchlax sit outside
# species.py's 1-386 NATIONAL_DEX range, so those two slots only ever get a "Catch -" location by reassignment.
VANILLA_POKESPOT_SLOTS: list[PokeSpotSlot] = [
    PokeSpotSlot("rock", 0, 27, 27, "Sandshrew"),
    PokeSpotSlot("rock", 1, 207, 207, "Gligar"),
    PokeSpotSlot("rock", 2, 332, 328, "Trapinch"),
    PokeSpotSlot("oasis", 0, 187, 187, "Hoppip"),
    PokeSpotSlot("oasis", 1, 231, 231, "Phanpy"),
    PokeSpotSlot("oasis", 2, 311, 283, "Surskit"),
    PokeSpotSlot("cave", 0, 41, 41, "Zubat"),
    PokeSpotSlot("cave", 1, 382, 304, "Aron"),
    PokeSpotSlot("cave", 2, 194, 194, "Wooper"),
    PokeSpotSlot("all", 0, 413, 387, "Bonsly"),
    PokeSpotSlot("all", 1, 414, 388, "Munchlax"),
]


def assign_pokespot_species(
    already_obtainable_dex: set[int],
    rng: random.Random,
    *,
    legendary_safe: bool = True,
) -> list[dict]:
    """Reassign all 11 `VANILLA_POKESPOT_SLOTS` to distinct new species from `species.NATIONAL_DEX` (1-386,
    the only species that can have a "Catch -" location), avoiding `already_obtainable_dex` -- normally this
    seed's Shadow obtainable-species set, passed in by `generate_early`.

    `legendary_safe=True` is a flat "never place a legendary at a Poke Spot" filter, not
    `team_shuffle.TeamShuffleOptions.legendary_safe`'s legendary-for-legendary swap: there is no "was this
    slot originally legendary" when the point is coverage.

    Returns one dict per slot, in slot order, with the vanilla fields plus `new_species_index` (this game's
    internal index, what `xd_rel_format.apply_pokespot_species` writes) and `new_dex`/`new_name` for the
    spoiler preview and the obtainable-species set."""
    already_obtainable = set(already_obtainable_dex)
    slots = VANILLA_POKESPOT_SLOTS

    def candidate_pool(*, allow_obtainable: bool, allow_legendary: bool) -> list[int]:
        return [
            dex for dex in NATIONAL_DEX
            if (allow_obtainable or dex not in already_obtainable)
            and (allow_legendary or dex not in LEGENDARY_NATIONAL_DEX)
        ]

    # The Shadow exclusion is absolute and the ladder relaxes legendaries only. The purification scan counts
    # "a Shadow species owned as an ordinary Pokemon" as a purification, which is only sound if a Shadow
    # species can never be caught wild -- so if legendaries alone cannot fill 11 slots this raises rather than
    # overlapping, because an overlap would cost the player a wrong check.
    chosen: list[int] = []
    for allow_legendary in ((not legendary_safe), True):
        if len(chosen) >= len(slots):
            break
        pool = [dex for dex in candidate_pool(allow_obtainable=False, allow_legendary=allow_legendary)
                if dex not in chosen]
        rng.shuffle(pool)
        chosen.extend(pool[: len(slots) - len(chosen)])
    if len(chosen) < len(slots):
        raise ValueError(
            f"only {len(chosen)} species are available for {len(slots)} Poke Spot slots without reusing a "
            f"Shadow species ({len(already_obtainable)} are Shadow-obtainable this seed) -- overlapping would "
            "break the purification scan's 'a Shadow species owned as an ordinary Pokemon was purified' rule"
        )

    entries: list[dict] = []
    for slot, new_dex in zip(slots, chosen):
        new_species_index = internal_index_for_national_dex(new_dex)
        entries.append({
            "pool": slot.pool,
            "slot_index": slot.slot_index,
            "vanilla_species_index": slot.vanilla_species_index,
            "vanilla_dex": slot.vanilla_dex,
            "vanilla_name": slot.vanilla_name,
            "new_species_index": new_species_index,
            "new_dex": new_dex,
            "new_name": NATIONAL_DEX[new_dex],
        })
    return entries
