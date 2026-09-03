"""
Binary layouts for Pokemon XD's trainer-team data, ported from rotobash/pokemon-ngc-rando's
XDTrainerPokemon.cs and XDTrainer.cs (fetched 2026-09-02 from raw.githubusercontent.com).

SCOPE / HONESTY NOTE (read before using this against a real ISO): this module only knows how to read and
write the CONFIRMED byte ranges within an already-extracted block of trainer data. It deliberately does NOT:
  - Parse a raw GameCube ISO's file system table (FST) or locate files within it.
  - Extract or decompress FSYS archives (Pokemon XD's data files are packed inside these; whether the DPKM/
    DDPK/DTNR tables specifically sit compressed inside an FSYS archive, or as plain loose files, was not
    confirmed by the source research this session -- see pokemon-xd-feasibility.md).
  - Know the DTNR data block's real file offset within a US-release Pokemon XD ISO.

Those three gaps are exactly the part of pokemon-ngc-rando's own ISO.cs that is NOT implemented in what was
fetched this session (`Encode()` throws `NotSupportedException()` there -- the real rebuild path lives
somewhere else, possibly the separate GoD Tool repo, not yet located). Reimplementing GameCube FST/FSYS
handling from scratch, blind, risks silently corrupting a real ISO -- so this module stops at the boundary of
what's been empirically confirmed (the DPKM/DDPK/XDTrainer struct layouts) and leaves locating + extracting +
reinjecting those blocks in a real ISO as an explicit, flagged next step. See apply_patch.py at the repo root
for how this is meant to be driven once that gap is closed (most likely by using pokemon-ngc-rando itself, or
GoD Tool, as an extraction/reinjection library rather than reimplementing it here).

Every accessor below mutates ONLY the specific byte range it documents, in place on a full-entry bytearray the
caller owns -- any byte outside a named field is left completely untouched on write, even if its meaning is
unknown. This is deliberate: guessing at an unconfirmed field's meaning and writing to it is exactly the kind
of mistake that produced this session's live-RAM corruption investigation in the first place (see
pokemon-xd-ram-map.md's "shadow Taillow / trainer-battle-failure investigation" thread) -- don't repeat it
against a real ISO.

Confirmed field offsets (byte, big-endian for all multi-byte fields, matching every other confirmed structure
in this project):

DPKM (regular Pokemon team entry, 0x20 = 32 bytes):
  species        u16 @ 0x00
  level          u8  @ 0x02
  happiness      u8  @ 0x03
  held_item      u16 @ 0x04
  moves[4]       u16 @ 0x14, 0x16, 0x18, 0x1A
  shiny_flag     u8  @ 0x1C
  Everything else (0x06-0x13 IVs/EVs region, 0x1D-0x1F nature/gender/ability/gen-flag region) is confirmed to
  EXIST at those approximate offsets but not confirmed byte-exact -- left untouched by this module.

DDPK (shadow Pokemon team entry, 0x18 = 24 bytes):
  flee_after_battle    u8  @ 0x00
  catch_rate_override  u8  @ 0x01
  shadow_level         u8  @ 0x02
  in_use_flag          u8  @ 0x03  (0x80 = active slot)
  story_index          u16 @ 0x06  -- indexes back into DPKM data; the indirection mechanism itself is NOT
                                      confirmed (see module docstring in team_shuffle.py). Exposed read/write
                                      but treat writes to this field as unverified.
  aggression           u8  @ 0x14
  always_flee          u8  @ 0x15

XDTrainer (fixed trainer entry, 0x38 = 56 bytes):
  trainer_class     u8  @ 0x05
  name_id           u16 @ 0x06
  model             u8  @ 0x11
  pre_battle_text   u16 @ 0x14
  victory_text      u16 @ 0x16
  defeat_text       u16 @ 0x18
  ai_value          u16 @ 0x28
  Roster data lives at 0x1C as a variable-length array of indices into the DPKM/DDPK tables, and a "shadow
  mask" (bit flags selecting DPKM vs DDPK per slot) exists at an offset that was NOT pinned down by the source
  research -- both are exposed only as a raw byte-range accessor (`roster_raw`) rather than a structured
  field, so nothing here silently misinterprets them.
"""

from __future__ import annotations

import struct

DPKM_ENTRY_SIZE = 0x20
DDPK_ENTRY_SIZE = 0x18
XD_TRAINER_ENTRY_SIZE = 0x38


def _u16(buf: bytearray, offset: int) -> int:
    return struct.unpack_from(">H", buf, offset)[0]


def _set_u16(buf: bytearray, offset: int, value: int) -> None:
    struct.pack_into(">H", buf, offset, value & 0xFFFF)


class DpkmEntry:
    """Wraps a 0x20-byte DPKM record. `raw` is the caller's own bytearray slice -- all writes go straight
    through to it, and every byte this class doesn't name is left exactly as given."""

    def __init__(self, raw: bytearray) -> None:
        if len(raw) != DPKM_ENTRY_SIZE:
            raise ValueError(f"DPKM entry must be {DPKM_ENTRY_SIZE} bytes, got {len(raw)}")
        self.raw = raw

    @property
    def species(self) -> int:
        return _u16(self.raw, 0x00)

    @species.setter
    def species(self, value: int) -> None:
        _set_u16(self.raw, 0x00, value)

    @property
    def level(self) -> int:
        return self.raw[0x02]

    @level.setter
    def level(self, value: int) -> None:
        self.raw[0x02] = value & 0xFF

    @property
    def happiness(self) -> int:
        return self.raw[0x03]

    @happiness.setter
    def happiness(self, value: int) -> None:
        self.raw[0x03] = value & 0xFF

    @property
    def held_item(self) -> int:
        return _u16(self.raw, 0x04)

    @held_item.setter
    def held_item(self, value: int) -> None:
        _set_u16(self.raw, 0x04, value)

    @property
    def moves(self) -> tuple[int, int, int, int]:
        return (_u16(self.raw, 0x14), _u16(self.raw, 0x16), _u16(self.raw, 0x18), _u16(self.raw, 0x1A))

    @moves.setter
    def moves(self, value: tuple[int, int, int, int]) -> None:
        for i, move_id in enumerate(value[:4]):
            _set_u16(self.raw, 0x14 + i * 2, move_id)

    @property
    def shiny_flag(self) -> int:
        return self.raw[0x1C]

    @shiny_flag.setter
    def shiny_flag(self, value: int) -> None:
        self.raw[0x1C] = value & 0xFF


class DdpkEntry:
    """Wraps a 0x18-byte DDPK (shadow Pokemon) record. Same untouched-unless-named contract as DpkmEntry."""

    def __init__(self, raw: bytearray) -> None:
        if len(raw) != DDPK_ENTRY_SIZE:
            raise ValueError(f"DDPK entry must be {DDPK_ENTRY_SIZE} bytes, got {len(raw)}")
        self.raw = raw

    @property
    def flee_after_battle(self) -> int:
        return self.raw[0x00]

    @flee_after_battle.setter
    def flee_after_battle(self, value: int) -> None:
        self.raw[0x00] = value & 0xFF

    @property
    def catch_rate_override(self) -> int:
        return self.raw[0x01]

    @catch_rate_override.setter
    def catch_rate_override(self, value: int) -> None:
        self.raw[0x01] = value & 0xFF

    @property
    def shadow_level(self) -> int:
        return self.raw[0x02]

    @shadow_level.setter
    def shadow_level(self, value: int) -> None:
        self.raw[0x02] = value & 0xFF

    @property
    def in_use_flag(self) -> int:
        return self.raw[0x03]

    @in_use_flag.setter
    def in_use_flag(self, value: int) -> None:
        self.raw[0x03] = value & 0xFF

    @property
    def is_active(self) -> bool:
        return bool(self.raw[0x03] & 0x80)

    @property
    def story_index(self) -> int:
        # UNVERIFIED indirection mechanism -- see module docstring. Exposed for completeness, not yet used by
        # team_shuffle.py's write-back path.
        return _u16(self.raw, 0x06)

    @story_index.setter
    def story_index(self, value: int) -> None:
        _set_u16(self.raw, 0x06, value)

    @property
    def aggression(self) -> int:
        return self.raw[0x14]

    @aggression.setter
    def aggression(self, value: int) -> None:
        self.raw[0x14] = value & 0xFF

    @property
    def always_flee(self) -> int:
        return self.raw[0x15]

    @always_flee.setter
    def always_flee(self, value: int) -> None:
        self.raw[0x15] = value & 0xFF


class XdTrainerEntry:
    """Wraps a 0x38-byte XDTrainer record. Roster/shadow-mask bytes are exposed raw only -- see module
    docstring for why they aren't parsed into structured fields yet."""

    def __init__(self, raw: bytearray) -> None:
        if len(raw) != XD_TRAINER_ENTRY_SIZE:
            raise ValueError(f"XDTrainer entry must be {XD_TRAINER_ENTRY_SIZE} bytes, got {len(raw)}")
        self.raw = raw

    @property
    def trainer_class(self) -> int:
        return self.raw[0x05]

    @property
    def name_id(self) -> int:
        return _u16(self.raw, 0x06)

    @property
    def model(self) -> int:
        return self.raw[0x11]

    @property
    def pre_battle_text_id(self) -> int:
        return _u16(self.raw, 0x14)

    @property
    def victory_text_id(self) -> int:
        return _u16(self.raw, 0x16)

    @property
    def defeat_text_id(self) -> int:
        return _u16(self.raw, 0x18)

    @property
    def ai_value(self) -> int:
        return _u16(self.raw, 0x28)

    @property
    def roster_raw(self) -> bytearray:
        """Raw bytes from 0x1C to the end of the entry (0x38). Contains the roster index array and,
        somewhere in it, the shadow-mask bit flags -- neither is parsed here. Read-modify-write this whole
        slice if you need to touch it, and validate byte-for-byte against a real save before trusting it."""
        return self.raw[0x1C:XD_TRAINER_ENTRY_SIZE]


def read_dpkm_table(data: bytes, base_offset: int, count: int) -> list[DpkmEntry]:
    """`data` is an already-extracted block containing a contiguous DPKM table (see module docstring for why
    locating that block within a real ISO is not this module's job). Returns entries backed by fresh
    bytearrays -- mutate them and use write_dpkm_table to fold changes back into a buffer."""
    entries = []
    for i in range(count):
        start = base_offset + i * DPKM_ENTRY_SIZE
        entries.append(DpkmEntry(bytearray(data[start:start + DPKM_ENTRY_SIZE])))
    return entries


def write_dpkm_table(buf: bytearray, base_offset: int, entries: list[DpkmEntry]) -> None:
    for i, entry in enumerate(entries):
        start = base_offset + i * DPKM_ENTRY_SIZE
        buf[start:start + DPKM_ENTRY_SIZE] = entry.raw


def read_ddpk_table(data: bytes, base_offset: int, count: int) -> list[DdpkEntry]:
    entries = []
    for i in range(count):
        start = base_offset + i * DDPK_ENTRY_SIZE
        entries.append(DdpkEntry(bytearray(data[start:start + DDPK_ENTRY_SIZE])))
    return entries


def write_ddpk_table(buf: bytearray, base_offset: int, entries: list[DdpkEntry]) -> None:
    for i, entry in enumerate(entries):
        start = base_offset + i * DDPK_ENTRY_SIZE
        buf[start:start + DDPK_ENTRY_SIZE] = entry.raw


def read_trainer_table(data: bytes, base_offset: int, count: int) -> list[XdTrainerEntry]:
    entries = []
    for i in range(count):
        start = base_offset + i * XD_TRAINER_ENTRY_SIZE
        entries.append(XdTrainerEntry(bytearray(data[start:start + XD_TRAINER_ENTRY_SIZE])))
    return entries
