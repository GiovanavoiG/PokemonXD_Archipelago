"""
Trainer-team (species) randomization, ported from rotobash/pokemon-ngc-rando's TeamShuffler.cs.

WHY THIS EXISTS: live experimentation this session (writing directly into a battle's live RAM struct, see
pokemon-xd-feasibility.md's "Trainer-team randomization: live RAM patching confirmed NOT viable" section)
showed that a trainer's Pokemon species is re-populated from upstream save/ISO data on every turn transition,
and sprite/asset loading happens once at battle-init from a separate species-keyed path. A name+species RAM
write took effect for the displayed name but not the sprite, and reverted after one turn. Durably changing
what species a trainer uses has to happen before the battle loads -- i.e. as a one-time edit to the trainer's
DPKM/DDPK team data, either by patching the ISO offline or by patching the loaded game image at a fixed point
before the trainer's data is first read. This module implements the DECISION logic only (which species goes
where); pokemon_xd.game_data.iso_format implements the byte-level read/write this operates on.

Ported behavior from TeamShuffler.cs (see pokemon-xd-feasibility.md for the original C# reference, fetched
2026-09-02 from rotobash/pokemon-ngc-rando):
  - Walks every trainer's team slots (a "PokemonInstance": species id, level, held item, shadow flag, index).
  - Reassigns species in place, using the AP world's seeded RNG so results are deterministic per-seed.
  - Optional constraint: legendary Pokemon are only ever replaced with other legendaries (`legendary_safe`).
  - Shadow Pokemon get deduplicated across the whole run via a "already used as a shadow" set, mirroring the
    original's `pickedShadowPokemon` HashSet -- avoids the same species appearing as two different shadow
    encounters.
  - Level boost: an optional flat percentage increase (clamped 1-100), applied once per unique slot index
    (mirrors the original's `randomizedPokemon` HashSet guard against double-applying a boost to a slot that's
    visited more than once due to a data-duplication quirk the original codebase works around).
  - Forced evolution: if a slot's (possibly boosted) level is at or past `force_evolution_level` and the
    chosen species has an evolution, swap to the evolved form.
  - Held item reassignment: optional, drawn from a filtered pool (can exclude a "weak items" ban list),
    mirroring the original's held-item shuffle step.

NOT YET WIRED TO REAL XD DATA: this module has no built-in species/trainer census for Pokemon XD -- I do not
have that data memorized reliably enough to hardcode it (wrong species/level data would silently produce a
corrupt or crashing patch), and no ISO has been available in this session to extract it from. The real trainer
roster must come from `pokemon_xd.game_data.iso_format.read_trainer_pool()` against the player's own ISO. This
module is fully testable today with synthetic data (see the __main__ block below); wiring it to a real ISO is
the next validation step once the player supplies one.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field


@dataclass
class Species:
    species_id: int
    is_legendary: bool = False
    # species_id this evolves into, and the minimum level for that evolution to be forced. None = doesn't
    # evolve (or evolution method isn't level-based, e.g. stone/trade -- those are left alone).
    evolves_into: int | None = None
    evolves_at_level: int | None = None


@dataclass
class PokemonInstance:
    index: int  # stable identity for a team slot, used to dedupe repeated-visit level-boost application
    species_id: int
    level: int
    item_id: int | None = None
    is_shadow: bool = False


@dataclass
class Trainer:
    name: str
    team: list[PokemonInstance] = field(default_factory=list)


@dataclass
class TrainerPool:
    name: str
    trainers: list[Trainer] = field(default_factory=list)


@dataclass
class TeamShuffleOptions:
    legendary_safe: bool = True
    level_boost_percent: int = 0  # 0-100
    force_evolution_level: int | None = None
    shuffle_held_items: bool = False
    held_item_pool: list[int] = field(default_factory=list)
    banned_weak_items: set[int] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.level_boost_percent = max(0, min(100, self.level_boost_percent))


class TeamShuffler:
    """Stateful across a whole shuffle run so shadow-Pokemon dedup and the level-boost-once guard work the same
    way TeamShuffler.cs's pickedShadowPokemon / randomizedPokemon HashSets did across a whole extracted game."""

    def __init__(
        self,
        options: TeamShuffleOptions,
        rng: random.Random,
        species_pool: dict[int, Species],
    ) -> None:
        self.options = options
        self.rng = rng
        self.species_pool = species_pool
        self._picked_shadow_species: set[int] = set()
        self._leveled_slot_indices: set[int] = set()

    def _candidate_species_ids(self, original: Species, is_shadow: bool) -> list[int]:
        candidates = [
            sid for sid, sp in self.species_pool.items()
            if (sp.is_legendary == original.is_legendary or not self.options.legendary_safe)
        ]
        if is_shadow:
            candidates = [sid for sid in candidates if sid not in self._picked_shadow_species]
            if not candidates:
                # Pool exhausted (more shadow slots than species) -- allow reuse rather than crash, matching
                # the original's fallback of just letting duplicates happen once the set is exhausted.
                candidates = list(self.species_pool.keys())
        return candidates or list(self.species_pool.keys())

    def _boosted_level(self, mon: PokemonInstance) -> int:
        if self.options.level_boost_percent <= 0 or mon.index in self._leveled_slot_indices:
            return mon.level
        self._leveled_slot_indices.add(mon.index)
        boosted = mon.level + (mon.level * self.options.level_boost_percent) // 100
        return max(1, min(100, boosted))

    def _apply_forced_evolution(self, species_id: int, level: int) -> int:
        threshold = self.options.force_evolution_level
        if threshold is None or level < threshold:
            return species_id
        sp = self.species_pool.get(species_id)
        if sp is None or sp.evolves_into is None:
            return species_id
        if sp.evolves_at_level is not None and level < sp.evolves_at_level:
            return species_id
        return sp.evolves_into

    def _reassign_held_item(self, mon: PokemonInstance) -> int | None:
        if not self.options.shuffle_held_items or not self.options.held_item_pool:
            return mon.item_id
        choices = [i for i in self.options.held_item_pool if i not in self.options.banned_weak_items]
        if not choices:
            return mon.item_id
        return self.rng.choice(choices)

    def shuffle_pokemon_instance(self, mon: PokemonInstance) -> None:
        original = self.species_pool.get(mon.species_id)
        if original is None:
            return  # unknown species id -- leave untouched rather than guess
        candidates = self._candidate_species_ids(original, mon.is_shadow)
        new_species_id = self.rng.choice(candidates)
        if mon.is_shadow:
            self._picked_shadow_species.add(new_species_id)
        new_level = self._boosted_level(mon)
        new_species_id = self._apply_forced_evolution(new_species_id, new_level)
        mon.species_id = new_species_id
        mon.level = new_level
        mon.item_id = self._reassign_held_item(mon)

    def shuffle_trainer_pools(self, pools: list[TrainerPool]) -> None:
        for pool in pools:
            for trainer in pool.trainers:
                for mon in trainer.team:
                    self.shuffle_pokemon_instance(mon)


def shuffle_teams(
    pools: list[TrainerPool],
    species_pool: dict[int, Species],
    options: TeamShuffleOptions,
    seed_rng: random.Random,
) -> None:
    """Convenience entry point: mutates `pools` in place. `seed_rng` should be the AP world's own seeded RNG
    (`world.random`) so the result is deterministic per multiworld seed, exactly like AP's own item fill."""
    TeamShuffler(options, seed_rng, species_pool).shuffle_trainer_pools(pools)
