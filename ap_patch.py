"""The AP patch's memory block: what the C patch records, and the feature flags the client writes for it.

The patch hooks the game's capture, purification, battle-result and white-out paths and logs what they did into
a block of MEM1 the game never touches (US: 0x81700000). The layout below is the C patch's `AP` struct as the
GameCube EABI lays it out -- u16 aligned to 2, u32 and pointers to 4, big-endian:

    +0x000  u16   flags                     written by the client (`feature_flags`)
    +0x002  u8    deathLink                 written by the client; the patch whites the player out, then clears it
    +0x003  u8    escape                    unused
    +0x004  CheckedAPItems
            +0x004  u16  beatTrainerCounter
            +0x006  u16  beatTrainerBattleIndex[450]   the battle index of every battle won (result 2)
            +0x38A  u16  purifyCounter
            +0x38C  u16  purified[128]
            +0x48C  u16  pokemonCounter
            +0x48E  {u8 level, pad, u16 species, u16 shadowIndex}[128]   every capture, Shadow or wild
    +0x790  GiveAPItems                     client -> game; not used yet

Counters only ever grow while the game runs, and the patch does not bound them. The whole block is plain RAM, so
it is gone on a power cycle (a soft reset or a save state keeps whatever it held).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Callable, Optional, Sequence

#: US (GXXE01) only. The patch has no EU/JP addresses yet.
AP_BLOCK_ADDRESS = 0x81700000

FLAGS_OFFSET = 0x000
DEATH_LINK_OFFSET = 0x002

BEAT_TRAINER_COUNTER_OFFSET = 0x004
BEAT_TRAINER_INDICES_OFFSET = 0x006
BEAT_TRAINER_CAPACITY = 450

CHECK_PURIFY_COUNTER_OFFSET = 0x38A
CHECK_PURIFIED_OFFSET = 0x38C
SHADOW_CAPACITY = 0x80

CATCH_COUNTER_OFFSET = 0x48C
CATCHES_OFFSET = 0x48E
CATCH_ENTRY_SIZE = 6
CATCH_LEVEL_OFFSET = 0x0
CATCH_SPECIES_OFFSET = 0x2
CATCH_SHADOW_INDEX_OFFSET = 0x4

#: Everything the client reads: the flags through the end of the catch log.
CHECKS_READ_SIZE = CATCHES_OFFSET + SHADOW_CAPACITY * CATCH_ENTRY_SIZE   # 0x78E

# `AP_ENABLE_*` in the patch: bit n of `flags`.
FLAG_ITEM_CHECKS = 1 << 0
FLAG_POKEMON_CHECKS = 1 << 1      # the patch WITHHOLDS every capture -- only once the client can give Pokemon
FLAG_PURIFY_CHECKS = 1 << 2       # the patch BLOCKS purification until `give.purified` allows it
FLAG_DEATH_LINK = 1 << 3


def feature_flags(*, item_checks: bool, pokemon_checks: bool, purify_checks: bool, death_link: bool) -> int:
    return ((FLAG_ITEM_CHECKS if item_checks else 0)
            | (FLAG_POKEMON_CHECKS if pokemon_checks else 0)
            | (FLAG_PURIFY_CHECKS if purify_checks else 0)
            | (FLAG_DEATH_LINK if death_link else 0))


@dataclass(frozen=True)
class CaughtPokemon:
    level: int
    species: int          # the game's live species index, not a dex number -- see `national_dex`
    shadow_index: int     # 0 for a wild catch


@dataclass(frozen=True)
class ApPatchBlock:
    flags: int
    death_link: int
    beaten_battles: "tuple[int, ...]"
    purified: "tuple[int, ...]"
    caught: "tuple[CaughtPokemon, ...]"


def _u16(raw: bytes, offset: int) -> int:
    return struct.unpack_from(">H", raw, offset)[0]


def parse(raw: bytes) -> "ApPatchBlock | None":
    """The block, or None when it cannot be the patch's: a counter past its array means the patch is not
    installed (or the game has not booted) and these bytes are something else -- never checks."""
    if len(raw) < CHECKS_READ_SIZE:
        return None
    beaten_count = _u16(raw, BEAT_TRAINER_COUNTER_OFFSET)
    purified_count = _u16(raw, CHECK_PURIFY_COUNTER_OFFSET)
    caught_count = _u16(raw, CATCH_COUNTER_OFFSET)
    if beaten_count > BEAT_TRAINER_CAPACITY or purified_count > SHADOW_CAPACITY or caught_count > SHADOW_CAPACITY:
        return None
    caught = []
    for i in range(caught_count):
        at = CATCHES_OFFSET + i * CATCH_ENTRY_SIZE
        caught.append(CaughtPokemon(
            level=raw[at + CATCH_LEVEL_OFFSET],
            species=_u16(raw, at + CATCH_SPECIES_OFFSET),
            shadow_index=_u16(raw, at + CATCH_SHADOW_INDEX_OFFSET),
        ))
    return ApPatchBlock(
        flags=_u16(raw, FLAGS_OFFSET),
        death_link=raw[DEATH_LINK_OFFSET],
        beaten_battles=tuple(_u16(raw, BEAT_TRAINER_INDICES_OFFSET + 2 * i) for i in range(beaten_count)),
        purified=tuple(_u16(raw, CHECK_PURIFIED_OFFSET + 2 * i) for i in range(purified_count)),
        caught=tuple(caught),
    )


def read_block() -> "ApPatchBlock | None":
    from . import ram_client
    return parse(ram_client.read_bytes(AP_BLOCK_ADDRESS, CHECKS_READ_SIZE))


def write_flags(flags: int) -> None:
    from . import ram_client
    ram_client.write_bytes(AP_BLOCK_ADDRESS + FLAGS_OFFSET, struct.pack(">H", flags & 0xFFFF))


def write_death_link(pending: bool) -> None:
    from . import ram_client
    ram_client.write_bytes(AP_BLOCK_ADDRESS + DEATH_LINK_OFFSET, b"\x01" if pending else b"\x00")


def caught_dex(block: ApPatchBlock) -> "set[int]":
    """National Dex numbers of everything the patch saw captured. An unknown species index is skipped."""
    from .tools.xd_species_index import national_dex_for_live_species

    out: "set[int]" = set()
    for entry in block.caught:
        dex = national_dex_for_live_species(entry.species) if entry.species else None
        if dex is not None:
            out.add(dex)
    return out


# --- Trainer defeats ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Opponent:
    surname: str          # upper case, as the location queues are keyed
    identity: str         # what makes this team distinct from the surname's others -- see `resolve_battle`
    mt_battle_only: bool  # a Mt. Battle trainer with no story fight of the same name
    story_index: "int | None" = None   # the `trainer_roster.TRAINERS` row, for a story fight


def _story_identity(index: int) -> str:
    """`story:<n>`, n the lowest index of a same-name trainer fielding a byte-identical team. A label means "the Nth
    distinct team you have beaten", so two fights with one team (Chobin #4 and #5) are one identity."""
    from .game_data import trainer_roster

    trainer = trainer_roster.TRAINERS_BY_INDEX[index]
    signature = trainer_roster.team_signature(trainer)
    same = [t["index"] for t in trainer_roster.TRAINERS_BY_NAME[trainer["name"]]
            if trainer_roster.team_signature(t) == signature]
    return f"story:{min(same)}"


def resolve_battle(battle: int) -> "Opponent | None":
    """The trainer a won battle was against, or None for a battle with no checks behind it (the tutorial, the
    colosseums, Battle CDs, an index this table does not know, and the fights the player only watches)."""
    from .game_data import battle_index as battles, trainer_roster
    from .game_data.missable_indices import NON_PLAYER_FIGHT_INDICES
    from .game_data.mtbattle_trainer_data import MT_BATTLE_SURNAMES_SHARED_WITH_STORY, MT_BATTLE_TRAINER_NAMES

    found = battles.BATTLE_OPPONENTS.get(battle)
    if found is None:
        return None
    deck, index = found
    if deck == battles.STORY_DECK:
        if index in NON_PLAYER_FIGHT_INDICES or index not in trainer_roster.TRAINERS_BY_INDEX:
            return None
        return Opponent(trainer_roster.TRAINERS_BY_INDEX[index]["name"].upper(), _story_identity(index), False,
                        story_index=index)
    name = MT_BATTLE_TRAINER_NAMES.get(index)
    if name in MT_BATTLE_SURNAMES_SHARED_WITH_STORY:
        # Mt. Battle Area 1 is story content: Miru, Cridel and Bardo are the same characters as story 30-32.
        story = trainer_roster.TRAINERS_BY_NAME.get(name)
        if story:
            return Opponent(name, _story_identity(story[0]["index"]), False)
    return Opponent(name or f"MT. BATTLE #{index}", f"mt:{index}", True)


@dataclass
class PatchDefeatTracker:
    """Turns the patch's won-battle log into "Defeat" locations.

    The log is replayed from wherever this last read it, and from the start whenever it shrinks (a new boot, or a
    save state from earlier). Replays are harmless because dispatch is by distinct TEAM, and the beaten teams are
    saved with the slot: a team already beaten checks off nothing and does not move the running count."""

    beaten: "dict[str, list[str]]" = field(default_factory=dict)
    defeat_count: int = 0
    rematches_ignored: int = 0
    replays: int = 0
    #: Surnames won against in the entries read by the LAST poll.
    last_confirmed_surnames: "set[str]" = field(default_factory=set)
    #: Wins per surname across the whole log as it stands now, rematches included.
    wins_by_surname: "dict[str, int]" = field(default_factory=dict)
    #: Story trainer rows won against, across the whole log as it stands now.
    story_wins: "set[int]" = field(default_factory=set)
    unknown_battles: "set[int]" = field(default_factory=set)
    _consumed: int = 0
    _log_length: int = 0
    dirty: bool = False

    def poll(
        self,
        battles: "Sequence[int]",
        queue_by_upper: "dict[str, Sequence[Optional[str]]]",
        count_location_name: "Callable[[int], str]",
        count_location_max: "int | None" = None,
        exclude_mt_battle: bool = False,
        resolve: "Callable[[int], Opponent | None]" = resolve_battle,
    ) -> "list[str]":
        """Locations newly earned by the log entries not read before. `count_location_max` caps the cumulative
        "Defeat N Trainers" names (0 for none); `exclude_mt_battle` keeps Mt. Battle-only wins out of the count and
        the queues, though they are still reported in `last_confirmed_surnames` for the goal."""
        if len(battles) < self._consumed:
            self._consumed = 0
            self.replays += 1
        fresh = battles[self._consumed:]
        self._consumed = len(battles)
        self._log_length = len(battles)

        wins: "dict[str, int]" = {}
        story_wins: "set[int]" = set()
        for battle in battles:
            opponent = resolve(battle)
            if opponent is not None:
                wins[opponent.surname] = wins.get(opponent.surname, 0) + 1
                if opponent.story_index is not None:
                    story_wins.add(opponent.story_index)
        self.wins_by_surname = wins
        self.story_wins = story_wins

        self.last_confirmed_surnames = set()
        completed: "list[str]" = []
        for battle in fresh:
            opponent = resolve(battle)
            if opponent is None:
                self.unknown_battles.add(battle)
                continue
            self.last_confirmed_surnames.add(opponent.surname)
            if opponent.mt_battle_only and exclude_mt_battle:
                continue
            teams = self.beaten.setdefault(opponent.surname, [])
            if opponent.identity in teams:
                self.rematches_ignored += 1
                continue
            teams.append(opponent.identity)
            self.dirty = True
            self.defeat_count += 1
            if count_location_max is None or self.defeat_count <= count_location_max:
                completed.append(count_location_name(self.defeat_count))
            queue = queue_by_upper.get(opponent.surname) or ()
            position = len(teams) - 1
            if position < len(queue) and queue[position] is not None:
                completed.append(queue[position])
        return completed

    def beaten_team_counts(self) -> "dict[str, int]":
        return {surname: len(teams) for surname, teams in self.beaten.items() if teams}

    def describe(self) -> str:
        return (f"Patch battle log: {self._log_length} win(s) logged this boot, {self.defeat_count} distinct "
                f"team(s) beaten, {self.rematches_ignored} rematch(es) ignored, {self.replays} replay(s)"
                + (f", {len(self.unknown_battles)} battle(s) with no trainer check" if self.unknown_battles else "")
                + ".")

    def to_json(self) -> dict:
        return {"beaten": {surname: list(teams) for surname, teams in self.beaten.items()},
                "defeat_count": self.defeat_count}

    def load_json(self, data: "dict | None") -> None:
        if not isinstance(data, dict):
            return
        beaten = data.get("beaten") or {}
        self.beaten = {str(surname): [str(team) for team in teams] for surname, teams in beaten.items()}
        self.defeat_count = int(data.get("defeat_count") or 0)
