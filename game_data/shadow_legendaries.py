"""ADDENDUM 435 -- legendaries and the Shadow roster.

Player: "an option to DISABLE legendaries as shadow pokemon, and an option to make sure shadow lugia is shuffled."

Two passes over the vanilla Shadow pool (`real_shadow_data.load_real_shadow_pool`), run after the species shuffle
(when it is on) and before anything reads the pool -- the catch labels, the obtainable-species set and the
expansion's exclusions all follow whatever these leave.

  * `remove_legendary_shadows` -- every Shadow that is a legendary becomes a random non-legendary species, evolved
    for its level, that no other Shadow already is (the client's species -> location map stays one-to-one). With
    the shuffle off that is Shadow Lugia and the three birds; with it on, whatever the shuffle drew.
  * `place_shadow_lugia` -- Lugia is a Shadow somewhere other than Greevil's first battle. The species shuffle never
    moves it (ADDENDUM 101 keeps Lugia out of the species table, and a slot the shuffler cannot look up is left as
    it was), so in both modes Lugia trades places with a random Shadow.

Both are pure: a pool, an RNG, and the species table in; the pool mutated in place and a count out.
"""
from __future__ import annotations

import random

from ..randomizer.team_shuffle import Species, TrainerPool, resolve_natural_evolution
from ..tools.xd_species_index import INTERNAL_INDEX_TO_NATIONAL_DEX
from .real_trainer_data import LEGENDARY_NATIONAL_DEX

LUGIA_SPECIES_INDEX = 249

#: Eevee and its five evolutions: the story gives every player an Eevee, so a Shadow of that line reads as a
#: purification the moment the gift arrives (ADDENDUM 325's rule for generated Shadows, applied here too).
_GIFT_LINE_DEX = frozenset({133, 134, 135, 136, 196, 197})


def is_legendary_species(species_index: int) -> bool:
    dex, _name = INTERNAL_INDEX_TO_NATIONAL_DEX.get(species_index, (None, None))
    return dex in LEGENDARY_NATIONAL_DEX


def _shadow_mons(pool: TrainerPool):
    return [mon for trainer in pool.trainers for mon in trainer.team]


def remove_legendary_shadows(pool: TrainerPool, species_pool: "dict[int, Species]", rng: random.Random,
                             exempt: "frozenset[int]" = frozenset()) -> int:
    """Replace every legendary Shadow (except species in `exempt`) with a distinct non-legendary. Returns how many."""
    from .evolution_data import family_of_internal

    mons = _shadow_mons(pool)
    used = {mon.species_id for mon in mons}
    # ADDENDUM 486: one Shadow per evolution line -- the replacement must not share a line with any other Shadow.
    lines = {family_of_internal(mon.species_id) for mon in mons}
    candidates = [sid for sid, sp in species_pool.items()
                  if not sp.is_legendary and not is_legendary_species(sid)
                  and INTERNAL_INDEX_TO_NATIONAL_DEX.get(sid, (None, None))[0] not in _GIFT_LINE_DEX]
    replaced = 0
    for mon in mons:
        if not is_legendary_species(mon.species_id) or mon.species_id in exempt:
            continue
        order = list(candidates)
        rng.shuffle(order)
        for candidate in order:
            evolved = resolve_natural_evolution(candidate, mon.level, species_pool, rng)
            if evolved in used or is_legendary_species(evolved) or family_of_internal(evolved) in lines:
                continue
            dex = INTERNAL_INDEX_TO_NATIONAL_DEX.get(evolved, (None, None))[0]
            if dex in _GIFT_LINE_DEX:
                continue
            used.discard(mon.species_id)
            lines.discard(family_of_internal(mon.species_id))
            mon.species_id = evolved
            used.add(evolved)
            lines.add(family_of_internal(evolved))
            replaced += 1
            break
    return replaced


def vanilla_lugia_index(original_species_by_index: "dict[int, int]") -> "int | None":
    """The DPKM index of Greevil's Shadow Lugia, from the pool's vanilla species snapshot."""
    for index, species in original_species_by_index.items():
        if species == LUGIA_SPECIES_INDEX:
            return index
    return None


def place_shadow_lugia(pool: TrainerPool, original_species_by_index: "dict[int, int]", rng: random.Random,
                       randomized: bool, exclude_indices: "frozenset[int]" = frozenset()) -> "int | None":
    """Put Lugia on a Shadow slot other than its vanilla one. Returns the DPKM index it landed on, or None when
    there is no Lugia slot to move from (a build without the Shadow data).

    The species shuffle never touches Lugia's own slot -- Lugia is not in the species table it draws from, and
    `TeamShuffler` leaves a slot it cannot look up exactly as it was -- which is why Shadow Lugia stayed at
    Greevil's first battle in every randomized seed. So in both modes Lugia TRADES places with a random Shadow:
    that slot's species goes to Greevil, Lugia goes there. `randomized` is kept for the record; the move is the same."""
    home = vanilla_lugia_index(original_species_by_index)
    if home is None:
        return None
    mons = _shadow_mons(pool)
    by_index = {mon.index: mon for mon in mons}
    # ADDENDUM 479: never onto a slot with no checks (Greevil's six, Miror B.'s post-game Dragonite) -- Lugia moved
    # there would be a Shadow nobody can be asked to purify.
    others = [mon for mon in mons if mon.index != home and mon.index not in exclude_indices]
    if not others or home not in by_index:
        return None
    for mon in others:
        if mon.species_id == LUGIA_SPECIES_INDEX:
            return mon.index               # already away from home
    target = rng.choice(others)
    lugia = by_index[home]
    if lugia.species_id == LUGIA_SPECIES_INDEX:
        lugia.species_id, target.species_id = target.species_id, LUGIA_SPECIES_INDEX
    else:
        target.species_id = LUGIA_SPECIES_INDEX
    return target.index
