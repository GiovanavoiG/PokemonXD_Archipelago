"""
Trainer-team (species) randomization -- decision logic only: which species goes where.

A live RAM write to a trainer's species does not stick (species are re-read from save/ISO data every turn
transition), so the edit has to land in the trainer's DPKM/DDPK team data before the battle loads.
`game_data/iso_format.py` is the byte-level layer, and the real roster comes from its `read_trainer_pool()`
against the player's own ISO -- no census is built in.

"""

from __future__ import annotations

import itertools
import random
from dataclasses import dataclass, field


@dataclass
class Species:
    species_id: int
    is_legendary: bool = False
    # what this evolves into and the minimum level for it; None = no evolution, or a non-level one (stone).
    evolves_into: int | None = None
    evolves_at_level: int | None = None


@dataclass
class PokemonInstance:
    index: int  # stable slot identity; the trainer tables revisit some slots, so the level boost keys on it
    species_id: int
    level: int
    item_id: int | None = None
    is_shadow: bool = False
    # the slot's real vanilla moveset (4 ids, 0 = empty) when known; read-only input for `assign_movesets`.
    moves: list[int] | None = None


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
    shuffle_held_items: bool = False
    held_item_pool: list[int] = field(default_factory=list)
    banned_weak_items: set[int] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.level_boost_percent = max(0, min(100, self.level_boost_percent))


def resolve_natural_evolution(species_id: int, level: int, species_pool: dict[int, Species]) -> int:
    """Highest-stage form `species_id` could naturally have reached by `level` -- a level-70 Houndour (evolves
    at 24) becomes Houndoom, a level-40 Charmander becomes Charizard, not Charmeleon. Unchanged when there is no
    chain data or the level misses the next threshold. Module-level so `enhanced_difficulty` can reuse it."""
    current = species_id
    for _ in range(6):  # no real chain exceeds 3 stages; the bound only guards a malformed/cyclic pool
        sp = species_pool.get(current)
        if sp is None or sp.evolves_into is None:
            return current
        if sp.evolves_at_level is not None and level < sp.evolves_at_level:
            return current
        current = sp.evolves_into
    return current


class TeamShuffler:
    """Stateful across a whole run: a shadow species must not be reused by any later trainer, and a slot index
    must not be level-boosted twice when the trainer tables visit it more than once."""

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
        # ADDENDUM 363: the list depends only on `legendary_safe` (fixed here) and `original.is_legendary`, so
        # building it per instance meant 808 walks of all 386 species per seed, 22% of a world generation, for
        # two distinct results. Nothing reassigns `species_pool` or `options`, so there is nothing to invalidate.
        self._base_candidates: "dict[bool, list[int]]" = {
            legendary: [
                sid for sid, sp in self.species_pool.items()
                if (sp.is_legendary == legendary or not self.options.legendary_safe)
            ]
            for legendary in (False, True)
        }

    def _candidate_species_ids(self, original: Species, is_shadow: bool) -> list[int]:
        # Precomputed in __init__; returned read-only, and copied only on the shadow path, which filters it.
        candidates = self._base_candidates[original.is_legendary]
        if is_shadow:
            candidates = [sid for sid in candidates if sid not in self._picked_shadow_species]
            if not candidates:
                # More shadow slots than species. Dedup is a nicety, not correctness, so allow reuse.
                candidates = list(self.species_pool.keys())
        return candidates or list(self.species_pool.keys())

    def _boosted_level(self, mon: PokemonInstance) -> int:
        if self.options.level_boost_percent <= 0 or mon.index in self._leveled_slot_indices:
            return mon.level
        self._leveled_slot_indices.add(mon.index)
        boosted = mon.level + (mon.level * self.options.level_boost_percent) // 100
        return max(1, min(100, boosted))

    def _apply_natural_evolution(self, species_id: int, level: int) -> int:
        return resolve_natural_evolution(species_id, level, self.species_pool)

    def _claim_shadow_species(self, evolved_species_id: int, level: int, candidates: list[int]) -> int:
        """Reserve `evolved_species_id` for this shadow slot, or find another candidate whose evolved form is
        free. The dedup set holds POST-evolution species, so two pre-evolutions sharing a final stage cannot
        both claim it; candidates are tried in `self.rng`'s shuffled order, and if all are taken the first pick
        is reused."""
        if evolved_species_id not in self._picked_shadow_species:
            self._picked_shadow_species.add(evolved_species_id)
            return evolved_species_id
        retry = list(candidates)
        self.rng.shuffle(retry)
        for candidate in retry:
            evolved = self._apply_natural_evolution(candidate, level)
            if evolved not in self._picked_shadow_species:
                self._picked_shadow_species.add(evolved)
                return evolved
        self._picked_shadow_species.add(evolved_species_id)
        return evolved_species_id

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
        new_level = self._boosted_level(mon)
        # Shadows evolve too; the dedup keys on the evolved species, so shared final stages cannot collide.
        new_species_id = self._apply_natural_evolution(new_species_id, new_level)
        if mon.is_shadow:
            new_species_id = self._claim_shadow_species(new_species_id, new_level, candidates)
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
    """Mutates `pools` in place. `seed_rng` should be `world.random`, so results are per-seed deterministic."""
    TeamShuffler(options, seed_rng, species_pool).shuffle_trainer_pools(pools)


# Move slots randomized per ordinary trainer Pokemon. The ceiling is DeckData_Story.bin's fixed 16615-byte
# allocated compressed-size budget, and getting it wrong once shipped a black screen on the main menu. Each
# figure below is a full-census edit of the real deck bytes (bridge/dumps/deck_story_1.bin) re-compressed with
# the shipped lazy-matching LZSS encoder. ADDENDUM 35 (2026-09-08), uniform-random 4 moves: 16788-16870 bytes
# over 10 trials, a structural 175-255 byte overflow (species-only fits at ~16085); 3 moves, 15937-16021 over
# 12. An optimal-parse encoder only reached 16798, and lifting the budget needs the FSYS relocation ADDENDUM 28
# reverted. ADDENDUM 217 re-measured 4 moves at 16124-16203, 412+ under budget every trial: what changed is
# compressibility, since ADDENDUM 100's latest-levelup-first selection makes neighbouring slots share moves the
# 4096-byte window can find. An overflow is a refused patch -- patch_entry_decompressed raises ValueError
# rather than writing past the budget -- not a brick. Re-measure first.
MOVESET_SHUFFLE_DEFAULT_MOVE_COUNT = 4

# Move id 1 (Pound) caused a repeatable real-hardware freeze -- an endless DVDOpen retry on its hit-effect
# resource `wzx_hataku_damage.fsys` -- on newly-added slots for trainer 26, two seeds, two species. Root cause
# unconfirmed (Pound was fine in isolation); excluded as a cheap stopgap.
EXCLUDED_MOVE_IDS: frozenset[int] = frozenset({1})  # Pound

# Gen 1-3 status (non-damaging) move ids, best-effort. Standard move numbering, which this game's raw ids match
# (Pound=1, Scratch=10, Perish Song=195, cross-checked against real extracted learnsets). Only used to prefer
# damaging moves, so a wrong id costs quality, never correctness.
STATUS_MOVE_IDS: frozenset[int] = frozenset({
    14, 18, 28, 39, 43, 45, 46, 47, 48, 50, 54, 73, 74, 77, 78, 79, 81, 86, 92, 95, 96, 97, 100, 102, 103, 104,
    105, 106, 107, 108, 109, 110, 111, 112, 113, 114, 115, 116, 118, 119, 133, 134, 135, 137, 139, 142, 144,
    147, 148, 150, 151, 156, 159, 160, 164, 166, 169, 170, 171, 174, 176, 178, 180, 182, 184, 186, 187, 191,
    193, 194, 195, 197, 199, 201, 203, 204, 207, 208, 212, 213, 214, 215, 219, 220, 226, 227, 230, 234, 235,
    236, 240, 241, 244, 254, 256, 258, 259, 260, 261, 262, 266, 267, 268, 269, 270, 271, 272, 273, 274, 275,
    277, 278, 281, 285, 286, 287, 288, 289, 293, 294, 297, 298, 300, 303, 312, 313, 316, 319, 320, 321, 322,
    334, 335, 336, 339, 346, 347, 349,
})


def choose_moveset(
    species_id: int,
    level: int,
    learnset: list[tuple[int, int]],
    rng: random.Random,
    # Defaulted rather than required so no caller can silently pin an old cap.
    move_count: int = MOVESET_SHUFFLE_DEFAULT_MOVE_COUNT,
) -> list[int]:
    """Shared move-selection core for assign_movesets() and the two grown-DPKM paths
    (enhanced_difficulty._moveset_for, shadow_expansion._moveset_for). Returns up to `move_count` distinct ids,
    never 0-padded, or `[]` when the species has no usable learnset. Candidates legal at `level` split into
    damaging (non-`STATUS_MOVE_IDS`) and status, each taken highest-learn-level first and damaging exhausted
    first, ties ordered by `rng`. At `level >= 30` the lowest-priority pick is swapped for a
    `move_data.TM_ATTACKING_MOVES` move whose type is not already covered."""
    from ..game_data.move_data import MOVE_TYPES, TM_ATTACKING_MOVES

    # ADDENDUM 75 also excluded every species' positionally-first learnset entry, after three real-hardware
    # freezes were all exactly that; ADDENDUM 131's FstGuard fixed the cause, so 217 dropped it. Pound stays.
    exclude = EXCLUDED_MOVE_IDS

    def build_candidate_levels(respect_level: bool) -> dict[int, int]:
        # {move_id: highest qualifying level it's learned at} -- the level is what the priority sort needs.
        result: dict[int, int] = {}
        for lvl, move in learnset:
            if not move or move in exclude:
                continue
            if respect_level and lvl > level:
                continue
            if move not in result or lvl > result[move]:
                result[move] = lvl
        return result

    candidate_levels = build_candidate_levels(respect_level=True)
    if not candidate_levels:
        candidate_levels = build_candidate_levels(respect_level=False)
    if not candidate_levels:
        return []

    def take_latest_first(pool: list[int], count: int) -> list[int]:
        """Up to `count` moves, highest level first; moves tied at one level are shuffled via `rng` first."""
        if count <= 0 or not pool:
            return []
        pool_by_level_desc = sorted(pool, key=lambda mv: candidate_levels[mv], reverse=True)
        picked: list[int] = []
        for _lvl, group in itertools.groupby(pool_by_level_desc, key=lambda mv: candidate_levels[mv]):
            group_list = list(group)
            rng.shuffle(group_list)
            for mv in group_list:
                if len(picked) >= count:
                    return picked
                picked.append(mv)
        return picked

    damaging = [mv for mv in candidate_levels if mv not in STATUS_MOVE_IDS]
    status = [mv for mv in candidate_levels if mv in STATUS_MOVE_IDS]

    chosen = take_latest_first(damaging, move_count)
    if len(chosen) < move_count:
        chosen += take_latest_first(status, move_count - len(chosen))

    if level >= 30 and chosen:
        existing_types = {MOVE_TYPES[mv] for mv in chosen if mv in MOVE_TYPES}
        tm_options = [
            mv for mv in TM_ATTACKING_MOVES
            if mv not in chosen and MOVE_TYPES.get(mv) not in existing_types
        ]
        if tm_options:
            # Replace the lowest-priority pick rather than exceed move_count: the slot count is an LZSS budget.
            chosen[-1] = rng.choice(tm_options)

    return sorted(set(chosen))


def assign_movesets(
    pools: list[TrainerPool],
    level_up_moves: dict[int, list[tuple[int, int]]],
    rng: random.Random,
    move_count: int = MOVESET_SHUFFLE_DEFAULT_MOVE_COUNT,
) -> dict[int, list[int]]:
    """Up to `move_count` distinct moves per slot across `pools`, from the slot's CURRENT species' real
    level-up learnset at or below `mon.level` -- run after `shuffle_teams` so moves follow the new species;
    falls back to the full learnset when nothing qualifies. Only ordinary DPKM slots belong here, so "shadow
    Pokemon keep their moves" holds by this never being called with them, not by a check.

    Returns {dpkm_index: [move_count ids, 0-padded]}, what `tools/iso_patcher.py` writes into
    DeckData_Story.bin's DPKM moves field (offset +0x14). A species with no recorded level-up moves at all
    (Bonsly, Munchlax) is absent from the dict, so its vanilla moves stay. Do not change `move_count` without
    re-measuring a full-census edit against the real 16615-byte budget."""
    assignment: dict[int, list[int]] = {}
    for pool in pools:
        for trainer in pool.trainers:
            for mon in trainer.team:
                learnset = level_up_moves.get(mon.species_id, [])
                chosen = choose_moveset(mon.species_id, mon.level, learnset, rng, move_count)
                if not chosen:
                    continue  # no learnset data for this species -- leave this slot's moves alone
                assignment[mon.index] = chosen + [0] * (move_count - len(chosen))
    return assignment
