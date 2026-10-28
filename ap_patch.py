"""The AP patch's shared block: `patch.c`'s `AP` struct at START_DATA_MEMORY, as the client writes it.

`assets/patch.diff` (`tools/iso_patcher.write_start_dol_patch`) carries the C code that reads this block. The game
never writes `flags` or `give`, so the client owns both, but the block is plain RAM: a cold boot or a reset clears it.
`ApPatchSync` therefore compares both against slot data and the received items every poll and rewrites whatever
disagrees.

Offsets are patch.c's structs under PPC EABI natural alignment. `ClientPokemonGetParam` holds a pointer, so
`GiveAPItems` is 4-aligned and each of its 128 entries is 16 bytes:
  0x000  u16 flags              0x002  u8 deathLink     0x003  u8 escape
  0x004  CheckedAPItems         (0x78A bytes, the game's to write)
  0x790  GiveAPItems            u16 pokemonCounter, pokemon[128] from 0x794,
                                u16 purifyCounter at 0xF94, u16 purified[128] from 0xF96
"""
from __future__ import annotations

import struct
from typing import Any, Iterable, Mapping

from . import ram_client

AP_DATA_BASE = 0x81700000
FLAGS_ADDRESS = AP_DATA_BASE + 0x000
GIVE_PURIFY_COUNTER_ADDRESS = AP_DATA_BASE + 0xF94
GIVE_PURIFIED_ADDRESS = AP_DATA_BASE + 0xF96
NUMBER_OF_SHADOW_POKEMON = 0x80

# patch.c's AP_ENABLE_* bit numbers. Only the ones an option decides are ever set: POKEMON_CHECKS makes a snag
# keep nothing, and ITEM_CHECKS and USE_LEVELUP_MOVES have no option behind them yet.
FLAG_ITEM_CHECKS = 0
FLAG_POKEMON_CHECKS = 1
FLAG_PURIFY_CHECKS = 2
FLAG_DEATH_LINK = 3
FLAG_USE_LEVELUP_MOVES = 4


def flags_from_slot_data(slot_data: Mapping[str, Any]) -> int:
    """`ap->flags` for this seed."""
    flags = 0
    if slot_data.get("purification_unlocks"):
        flags |= 1 << FLAG_PURIFY_CHECKS
    return flags


def purify_unlock_ddpks_from_slot_data(slot_data: Mapping[str, Any]) -> "dict[int, tuple[int, ...]]":
    """{national dex: the Shadow ids (DDPK indices) its `Purify Unlock` opens}."""
    return {int(dex): tuple(sorted(int(i) for i in ids))
            for dex, ids in dict(slot_data.get("purify_unlock_ddpks") or {}).items()}


def purify_unlock_block(shadow_ids: Iterable[int]) -> bytes:
    """`give.purifyCounter` followed by `give.purified[128]`: sorted, deduplicated, zero-padded."""
    ids = sorted({int(i) for i in shadow_ids if 0 < int(i) < NUMBER_OF_SHADOW_POKEMON})
    return struct.pack(f">H{NUMBER_OF_SHADOW_POKEMON}H", len(ids), *ids, *([0] * (NUMBER_OF_SHADOW_POKEMON - len(ids))))


class ApPatchSync:
    """Keeps `ap->flags` and `ap->give.purified` equal to what this seed and its received items say.

    Read every poll, written only on a mismatch, so a reset that zeroes the block is repaired on the next poll.
    Inert until `configure` names a seed that has the `purification_unlocks` slot data key: an older seed's ISO
    may not carry the patch at all, and then nothing may be written there."""

    def __init__(self) -> None:
        self.enabled = False
        self.flags = 0
        self.ddpks_by_dex: "dict[int, tuple[int, ...]]" = {}
        self.rewrites = 0
        self._ever_written = False

    def configure(self, slot_data: Mapping[str, Any]) -> None:
        self.enabled = "purification_unlocks" in slot_data
        self.flags = flags_from_slot_data(slot_data)
        self.ddpks_by_dex = purify_unlock_ddpks_from_slot_data(slot_data)
        self._ever_written = False

    def shadow_ids_for(self, unlocked_dex: Iterable[int]) -> "list[int]":
        return sorted({ddpk for dex in unlocked_dex for ddpk in self.ddpks_by_dex.get(int(dex), ())})

    def poll(self, unlocked_dex: Iterable[int]) -> "str | None":
        """One read of each field, and a write of whichever disagrees. Returns a line worth logging when it
        restored a block the game had lost (a reset), else None. Raises on a read/write failure."""
        if not self.enabled:
            return None
        want_flags = struct.pack(">H", self.flags)
        want_give = purify_unlock_block(self.shadow_ids_for(unlocked_dex))
        wrote = False
        if ram_client.read_bytes(FLAGS_ADDRESS, 2) != want_flags:
            ram_client.write_bytes(FLAGS_ADDRESS, want_flags)
            wrote = True
        if ram_client.read_bytes(GIVE_PURIFY_COUNTER_ADDRESS, len(want_give)) != want_give:
            # The list before its counter, so the game never counts past entries that are not there yet.
            ram_client.write_bytes(GIVE_PURIFIED_ADDRESS, want_give[2:])
            ram_client.write_bytes(GIVE_PURIFY_COUNTER_ADDRESS, want_give[:2])
            wrote = True
        if not wrote:
            return None
        self.rewrites += 1
        restored = self._ever_written
        self._ever_written = True
        count = struct.unpack_from(">H", want_give)[0]
        if restored:
            return f"AP patch block was cleared (a reset?) -- re-applied flags and {count} purification unlock(s)."
        return f"AP patch block written: flags 0x{self.flags:04X}, {count} purification unlock(s)."
