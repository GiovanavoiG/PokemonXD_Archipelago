"""
Pokemon XD: Gale of Darkness -- Archipelago client, RAM-access layer (2026-09-03).

============================================================================================================
STATUS: this module is the low-level "talk to a live, unmodified Dolphin process running this game" layer --
hooking, block-base resolution, Bag pocket read/write, party/species detection, purification detection, and
(new this pass) item-pocket routing for delivering received AP items. See the `pokemon-xd-ram-map.md` doc in
this project for the full methodology, evidence, and open threads behind every constant and assumption below;
this file's comments summarize it but the RAM map doc is the source of truth.

**Moved into the apworld package this pass** (was the standalone `PokemonXDClient.py` at the repo root) --
now lives at `pokemon_xd/ram_client.py` specifically so `Client.py` (the actual CommonClient/AP-server
integration, new this pass, see that file) can import it directly as a package-relative module, the same way
every other GameCube world's client does (e.g. `worlds/tww/TWWClient.py` importing `.Items`/`.Locations`).
This module itself still imports NOTHING beyond the standard library plus `dolphin_memory_engine` -- it does
NOT depend on the Archipelago core (`BaseClasses`, `worlds.AutoWorld`, ...) and can still be loaded completely
standalone (see `_load_location_name_for_species` below for why that property is deliberately preserved).

WHAT'S CONFIRMED (safe to build on):
  - The whole "player state" block (money, Bag pockets incl. Poke Balls, key items, and the live party-summary
    array) is ONE contiguous allocation that moves as a single unit between game boots (by a different, non-
    deterministic offset each time -- confirmed via two independent restart tests) but is COMPLETELY STABLE
    for the entire duration of one boot, across dozens of in-game events. Resolving its current base once per
    connection (via a landmark text search) and caching it is therefore the correct, sufficient strategy --
    no pointer chain exists or is needed.
  - The Bag's Items pocket and Poke Ball pocket are both confirmed-live to be simple PACKED ARRAYS of 4-byte
    `[item id: u16BE][quantity: u16BE]` records, one slot per owned item, empty slots all-zero, new pickups
    appended to the next open slot. Both reads AND writes to these pockets have been round-trip validated live
    in-game this session (money set to an arbitrary test value; a never-before-owned item -- Moon Stone --
    added to Items; a new item -- Great Ball -- added to the *separate* Poke Ball pocket) with correct in-game
    display and no observed corruption or crash.
  - The Key Items pocket (`0x80479400`/`0x80479404` relative to the original session's block placement, i.e.
    `KEY_ITEMS_OFFSET` below) is confirmed to hold the same `[id][qty]` record shape for the two entries
    actually seen (Krane Memo 1/2), but has NOT been write-tested and its full slot count/free-slot behavior
    is unconfirmed -- treat the Items/Poke-Ball-pocket findings as a strong hypothesis for this pocket, not a
    confirmed fact, until it's actually tested the same way.
  - **CORRECTED 2026-09-02: `resolve_block_base()`'s landmark offset was wrong in the original draft** (used
    `0x28`, subtracted -- that constant actually belonged to a different struct entirely). Re-derived and fixed
    live this session by cross-checking a fresh full-memory landmark search against the independently-known
    Items-pocket address; the correct relationship is `BLOCK_BASE = trainer_name_addr + 0x40`. Also confirmed
    live: the Items pocket's real capacity is 30 slots (`ITEMS_POCKET_MAX_SLOTS`, verified by reading all-zero
    right up to the Key Items boundary), not the placeholder `8` guessed originally.

WHAT'S NOT DONE YET (see pokemon-xd-ram-map.md's "Open threads" for the full list):
  - No AP server/CommonClient integration -- this file is the memory-access layer only.
  - No incoming-item-delivery loop, and no handling yet for the delivery-order/queue behavior the user wants
    (received items shown to the player one at a time, TWW-style, so a player who was offline sees what
    arrived and in what order) -- that needs its own design (most likely a small in-memory or Bag-based queue
    plus a way to notify the player, e.g. a textbox) and hasn't been started.
  - The species-detection *reading* side (this file's job) is now implemented -- see
    "Species detection: party + PC box" below -- but nothing yet calls `SpeciesTracker.poll()` on a loop or
    turns a newly-seen species into an actual outgoing `LocationChecks` packet; that's part of the still-
    unbuilt CommonClient integration above.

WHAT'S CONFIRMED, PART 2 -- species detection (added 2026-09-02, this same boot, after the player moved
Teddiursa through PC box slots 1/2/3 to help pin down box addressing):
  - **Overworld party struct** (`0x804280E8`, see `PARTY_BASE` below): CONFIRMED live, 48-byte stride, numeric
    1-indexed National Dex # at `+0x24`. Confirmed stable across a same-boot reboot AND across two different
    save files at the exact same address (unlike BLOCK_BASE, which relocates every boot) -- safe to poll
    continuously/in the background. Only 2 of a possible 6 party slots independently confirmed; slots 2-5 are
    read using the same confirmed stride as a reasonable extrapolation, not independently tested yet.
  - **PC box storage**: still NOT confirmed as real, independently-addressable per-slot storage -- see
    pokemon-xd-ram-map.md's "PC (box storage) investigation" section. What IS confirmed: a "recap"-shaped
    record's text-anchor address shifts by a clean, consistent `BOX_SLOT_STRIDE` (196 bytes) per box slot
    moved through, verified for 3 consecutive slots (indices 0, 1, 2) this boot. What's NOT confirmed: whether
    this reflects genuine simultaneously-live storage for every slot, or a single relocating "currently
    displayed in the box UI" buffer that only reflects whichever slot was last viewed (the byte-for-byte
    identical relocation pattern documented in the ram-map doc points toward the latter). **Treat box reads as
    best-effort, not safe for unattended background polling** -- see the dedicated caveat on
    `read_box_slot_species` below before using it in any real check-detection loop.

Requires `dolphin_memory_engine` (`pip install dolphin-memory-engine`) and a running, unmodified Dolphin with
this game loaded -- same tooling used for this project's own live investigation (see
`pokemon-xd-live-bridge-notes.md`), just used directly instead of through that session's file-relay bridge
(that bridge existed only because Claude's own session had no local execute access on the user's machine --
a real client run by the player locally needs no such workaround).
============================================================================================================
"""

from __future__ import annotations

import struct
import time
from dataclasses import dataclass

import dolphin_memory_engine as dme

MEM1_START = 0x80000000
MEM1_SIZE = 0x1800000  # 24 MiB

# --- Landmark used to resolve the player-state block's current base each connection. ---
# **CORRECTED 2026-09-02, later same boot, twice.** First correction: this project's earlier assumption that
# XD's protagonist has a fixed name ("Michael") with no in-game naming screen was WRONG -- the game evidently
# does let the player choose/enter a trainer name after all. A later save created specifically for this
# project used the name "David", not "Michael", and a live re-check this boot confirmed "MICHAEL" no longer
# resolves anywhere near the real player-state block on the save currently being played.
#
# Second correction, same conversation, per the player: a hardcoded name of ANY kind is the wrong fix, not
# just "MICHAEL" specifically -- trainer name is arbitrary player input, so there is no fixed string this
# client could ever hardcode that would work for every player/save. **The real fix**: Archipelago already
# requires every player to configure a slot name for their multiworld connection. The setup instructions for
# this game should tell the player to enter that SAME string as their in-game trainer name when starting a
# new file -- at that point the client already knows its own slot name (it's part of the connection config,
# the same way any AP client knows what game/slot it's playing), so it can pass it straight in as the search
# landmark with zero guessing. `TRAINER_NAME_LANDMARK` below is now just documentation of that convention, not
# a default meant to be used as-is -- a real client should always call `resolve_block_base(landmark=slot_name)`
# with the actual connected slot name, never fall back to a guessed constant. (Practical caveat, not yet
# confirmed: XD's in-game name-entry screen almost certainly has its own length/character-set limit, the same
# way Gen 3 mainline games cap trainer names at 7 characters -- this project hasn't independently confirmed
# XD's own limit. Setup instructions should tell the player to keep their AP slot name short and
# plain-alphanumeric, e.g. matching whatever XD's name-entry screen will actually accept, since a slot name
# that can't be entered in-game verbatim can't be used as this landmark at all.)
TRAINER_NAME_LANDMARK = "DAVID"  # this project's current test save only -- NOT a safe default for a real
                                  # client; always pass the connected player's actual slot name instead

# Offsets below are all relative to BLOCK_BASE, defined (CORRECTED 2026-09-02, see below) as
# (trainer-name address + RECORD_TRAINER_NAME_OFFSET). Derived from this session's original (pre-restart)
# addresses -- see pokemon-xd-ram-map.md's Bag/party-array sections for how each was found.
#
# RECORD_TRAINER_NAME_OFFSET was WRONG in the first draft of this file (was `0x28`, subtracted from the
# landmark address) -- that value came from a different record entirely (the battle-end party-recap struct's
# own internal layout, which is NOT the same struct as the Bag/money block) and was never actually checked
# against a resolved block base until today. Empirically re-derived 2026-09-02 by cross-referencing a fresh
# full-memory landmark search against the independently-known-correct Items-pocket address (Potion/Antidote/
# Thunder Stone/Moon Stone's real live addresses, confirmed via direct RAM read that session): the trainer
# name actually sits *before* BLOCK_BASE by 0x40 bytes, not after it by 0x28. Fixed below; the formula in
# resolve_block_base() was updated to match (now adds this offset instead of subtracting it).
RECORD_TRAINER_NAME_OFFSET = 0x40          # CORRECTED 2026-09-02 (was 0x28, and was subtracted -- both wrong)
RECORD_SPECIES_NAME_OFFSET_1 = 0x3E        # first copy of the species name (UTF-16BE) -- NOT re-verified against
RECORD_SPECIES_NAME_OFFSET_2 = 0x52        # the corrected base yet; these two are from the OTHER (party-recap)
RECORD_STATS_BLOCK_OFFSET = 0x80           # struct and still relative to THAT record's own base, not BLOCK_BASE
PARTY_RECORD_STRIDE = 0xC2                 # -- provisional -- only 2 slots observed, NOT confirmed general

MONEY_OFFSET = 0x8A4                       # u32BE, plain Pokedollar total (not an [id][qty] record) -- CONFIRMED
MONEY_DISPLAY_MARKER_OFFSET = MONEY_OFFSET + 0xC  # 8 bytes of 0x01 immediately following 4 bytes of zero
                                            # padding after money -- CONFIRMED live 2026-09-02 (this exact byte
                                            # pattern, not just "nearby", at this exact relative offset) --
                                            # likely per-digit "visible" flags for a money-display widget (see
                                            # pokemon-xd-ram-map.md's money section). Used by
                                            # `_looks_like_real_block_base` as a structural validation signal --
                                            # see that function's docstring for why a bare money-range check
                                            # alone isn't enough
ITEMS_POCKET_OFFSET = 0x488                # packed [id][qty] array -- CONFIRMED (Potion/Antidote/stones/etc.)
POKEBALL_POCKET_OFFSET = 0x5AC             # packed [id][qty] array -- confirmed Poke Ball + Great Ball test
KEY_ITEMS_OFFSET = 0x500                   # packed [id][qty] array -- confirmed live (Krane Memo 1/2)

# Slot counts below are derived from the *gap* to the next known field, confirmed live 2026-09-02 by dumping
# the actual bytes between consecutive offsets and checking they're genuinely all-zero right up to the
# boundary (see pokemon-xd-ram-map.md's item-table-verification section). This bounds each pocket's storage
# allocation, but does NOT by itself prove there's no padding or an as-yet-unidentified pocket sitting inside
# that gap -- treat these as a verified UPPER bound on safe read/write range, not a confirmed "real" pocket
# capacity, except where noted.
ITEMS_POCKET_MAX_SLOTS = 30                # CONFIRMED 2026-09-02: (KEY_ITEMS_OFFSET - ITEMS_POCKET_OFFSET) / 4,
                                            # live-checked all-zero from slot 4 through slot 29 this session
KEY_ITEMS_MAX_SLOTS = 43                   # gap-derived upper bound (POKEBALL_POCKET_OFFSET - KEY_ITEMS_OFFSET) / 4
                                            # -- NOT live-checked slot-by-slot yet; real key-item count is surely
                                            # much smaller, this is just "safe not to write past"
POKEBALL_POCKET_MAX_SLOTS = 8              # STILL a guess, unconfirmed -- the gap to MONEY_OFFSET is 0x2F8
                                            # (190 slots!), implausibly large for a real Poke Ball pocket, which
                                            # strongly suggests an unidentified pocket/structure (TM case? Battle
                                            # CDs? Berries?) sits between Poke Balls and Money that hasn't been
                                            # mapped yet -- do NOT treat that gap as available Poke-Ball capacity

# --- Overworld party struct -- CONFIRMED live, safe to poll continuously. See module docstring. ---
# NOT relative to BLOCK_BASE -- a separate, independently-anchored region (0x8042xxxx vs. BLOCK_BASE's
# 0x8047xxxx) confirmed to stay at this exact address across a same-boot reboot AND across two different save
# files, unlike BLOCK_BASE, which relocates by a non-deterministic amount every boot. So -- deliberately,
# unlike everything above -- this is used as a plain constant, not resolved from a landmark each connection.
# If this ever stops matching, re-derive the same way BLOCK_BASE's landmark would be: dump live memory and
# search for a currently-owned species' name text.
#
# CONFIRMED AGAIN 2026-09-03, across a genuine full Dolphin restart forced by a real crash (not just a
# save-reload) -- this is now the second independent full-reboot confirmation of this exact address.
#
# **But: LAZILY INITIALIZED -- reads all-zero until the player opens the in-game Party/Status screen at least
# once that boot session.** Live-confirmed this same boot: reads all-zero immediately after a catch, and STILL
# all-zero after extensive PC-box-menu use (moving Pokemon between boxes) -- only becomes populated once the
# Party/Status screen is actually opened, after which it decodes correctly and (per every prior boot studied)
# stays live for the rest of the session. A caller must NOT treat an all-zero read here as "empty party" --
# treat it as "not yet initialized this session" instead (functionally: read_party_species() will just return
# an empty list either way, which is the correct fallback either way -- no special-casing needed here, but
# don't build user-facing messaging that says e.g. "no Pokemon caught yet" off of this signal alone).
PARTY_BASE = 0x804280E8
PARTY_SLOT_STRIDE = 0x30                   # 48 bytes -- confirmed live with 2 real slots (Jolteon, Teddiursa)
PARTY_SPECIES_OFFSET = 0x26                # u16BE, 1-indexed National Dex #. CORRECTED 2026-09-03 -- was
                                            # documented as u32BE at +0x24, which happened to read correctly
                                            # for every real Pokemon seen before this correction purely because
                                            # the two bytes at +0x24/+0x25 always happened to be zero in that
                                            # data. Proven wrong live: a raw-written duplicate party member
                                            # (an experiment, not a real catch) was used in a real battle, and
                                            # +0x24/+0x25 came back non-zero afterward (0x0144, cause/meaning
                                            # not yet identified -- NOT confirmed zero for real Pokemon that
                                            # have battled, so a u32 read at +0x24 can silently return a bogus
                                            # species number for any Pokemon this has happened to). The real
                                            # Dex # is confirmed to live in the low u16 (+0x26/+0x27) only --
                                            # re-verified against both original data points (135, 216) and the
                                            # corrupted one (216 still decodes correctly from +0x26 alone).
PARTY_MAX_SLOTS = 6                        # a real XD party maxes at 6 -- only 2 slots independently confirmed
                                            # live so far; slots 2-5 use the same confirmed stride/offset as a
                                            # standard extrapolation, not independently verified yet
PARTY_NAME_MAX_BYTES = 0x16                # from slot start, UTF-16BE null-terminated -- this is the CURRENT
                                            # nickname/name, continuously live-synced (unlike the recap record's
                                            # name field below, which only updates when that slot last refreshed)
PARTY_LEVEL_OFFSET = 0x17                  # u8
PARTY_MAXHP_OFFSET = 0x18                  # u16BE
PARTY_CURHP_OFFSET = 0x1A                  # u16BE

# --- PC box storage. Addressing formula CONFIRMED 2026-09-03 (see below); the species sub-field's sync timing
# is NOT yet confirmed safe -- see module docstring and pokemon-xd-ram-map.md's "PC (box storage)" sections
# before relying on the numeric species field for anything time-sensitive. ---
# Relative to BLOCK_BASE (like the Bag pockets), unlike PARTY_BASE above.
BOX_SLOT_TEXT_ANCHOR_OFFSET = 0x9B2        # Box 1 Slot 1's recap-shaped record's text-anchor offset from
                                            # BLOCK_BASE
BOX_SLOT_STRIDE = 0xC4                     # 196 bytes -- confirmed for 3 consecutive slot indices within one
                                            # box (Box1 Slot1->2->3), AND across a box boundary (see
                                            # BOX_PADDING_PER_BOX below) -- the within-box stride itself needed
                                            # no correction, only crossing a box boundary does.
BOX_PADDING_PER_BOX = 0x14                 # CONFIRMED 2026-09-03: each box boundary crossed adds this many
                                            # extra bytes on top of the naive 30*BOX_SLOT_STRIDE-per-box stride
                                            # -- i.e. box N's Slot-0 anchor is BOX_SLOT_TEXT_ANCHOR_OFFSET +
                                            # N*(30*BOX_SLOT_STRIDE + BOX_PADDING_PER_BOX), not
                                            # N*30*BOX_SLOT_STRIDE. Verified against two independent data points
                                            # (Box1->Box2, one boundary -> +0x14; Box1->Box8, seven boundaries ->
                                            # +0x8C = 7*0x14) with an exact byte-for-byte match on the resulting
                                            # text-anchor address both times. This resolves what earlier looked
                                            # like a relocating-buffer discrepancy -- it's a fixed per-box header
                                            # instead, and a full 8-box x 30-slot sweep is addressable.
BOX_SLOT_SPECIES_OFFSET = 0x30             # from the slot's own text anchor, same u32BE species field shape as
                                            # the party struct and the battle-recap record. **CAVEAT, found
                                            # 2026-09-03**: this specific sub-field can lag well behind the
                                            # name-text fields -- live-confirmed wrong (reading a stale/unrelated
                                            # species) for a slot deposited into moments earlier, while a
                                            # different slot deposited into equally recently (same save session,
                                            # so NOT simply an "old vs. new" story) read correctly. Root cause
                                            # unconfirmed -- possibly tied to which box was last viewed/
                                            # navigated to in the PC menu, not deposit order. Do not trust this
                                            # sub-field immediately after a deposit without further testing; the
                                            # name-text address formula above is solid regardless.


# --- Party "recap" record: SOLVED 2026-09-03. One 196-byte (0xC4) live slot per CURRENT party member, same
# stride as the PC box array above, relative to BLOCK_BASE (not PARTY_BASE -- this is a different block from
# the compact party struct at PARTY_BASE, which has no room for stats or a purification flag). This is the
# same record type earlier (incorrectly) dismissed elsewhere as purely a transient "just caught/evolved"
# recap -- it turns out to persist (does NOT go zero once its triggering scene closes -- confirmed via an
# idle-time re-check with no action taken) but only REFRESHES per-slot when a recap-worthy event fires for
# that specific party member (catch, evolution, battle-end, and now confirmed: purification). An
# untouched-since-boot slot can read stale/wrong data indefinitely (see PARTY_RECAP_SPECIES_OFFSET's caveat
# below) -- this is a "trust it right after it changes" source, not a "trust any single poll" source.
PARTY_RECAP_OFFSET = 0x3E                  # party index 0's (first party slot's) record base, relative to
                                            # BLOCK_BASE. Record N's base is PARTY_RECAP_OFFSET + N*PARTY_RECAP_STRIDE.
PARTY_RECAP_STRIDE = 0xC4                  # 196 bytes -- confirmed identical to BOX_SLOT_STRIDE; very likely the
                                            # same underlying allocator/array, just walked by live party position
                                            # here instead of box/slot position.
PARTY_RECAP_SPECIES_OFFSET = 0x32          # u16BE. **UNRELIABLE, do not use for species detection** -- reads
                                            # correctly for some party members and wrong for others (matches the
                                            # same stale-species signature already documented for
                                            # BOX_SLOT_SPECIES_OFFSET), and purification does NOT re-sync it even
                                            # when it refreshes the flag/stat fields below. Use read_party_species
                                            # (PARTY_BASE) for species identification instead -- this offset is
                                            # exposed only for completeness/debugging.
PARTY_RECAP_MAXHP_OFFSET = 0x42            # u16BE. Ahead of PARTY_BASE's own MaxHP on a purification event
                                            # (delayed-sync, same pattern documented elsewhere in this project) --
                                            # this is the more CURRENT value immediately after such an event.
PARTY_RECAP_STAT_OFFSETS = {               # u16BE each, confirmed against two independent purification events
    "attack": 0x44,                        # (Teddiursa, Poochyena) with values matching the player's reported
    "defense": 0x46,                       # real current stats exactly both times.
    "sp_attack": 0x48,
    "sp_defense": 0x4a,
    "speed": 0x4c,
}
PARTY_RECAP_PURIFIED_FLAG_OFFSET = 0x2e    # u16BE. **CONFIRMED 2026-09-03, the actual purification signal.**
                                            # Reads 0 before purification, 64 (0x40) immediately after --
                                            # independently confirmed for two different Pokemon (Teddiursa,
                                            # Poochyena), both times with nothing else touching this field during
                                            # the bracket, and stable (still 64, unchanged) across an idle-time
                                            # re-check for Teddiursa. This is the single cleanest, most isolated
                                            # signal found in this entire project -- prefer polling this over the
                                            # stat block for purification detection (the stat block is good
                                            # corroboration but is five separate fields that could each drift for
                                            # unrelated reasons; this is one field with one clean transition).
                                            # NOT yet confirmed: whether 64 specifically means "purified" (vs.
                                            # e.g. a small counter/enum where a later event might produce a
                                            # different nonzero value), and whether this flag is save-persisted or
                                            # session/boot-scoped (untested -- would need a reboot-and-reload
                                            # check, the same way PARTY_BASE's own stability was confirmed).


# --- Species name -> National Dex # table. SOLVED 2026-09-03, replaces the unreliable numeric species field
# on the box array and the recap record entirely (PARTY_BASE's own species field at PARTY_SPECIES_OFFSET is
# NOT affected by any of this -- it's independently confirmed correct on its own; this table is specifically
# for the box array's BOX_SLOT_SPECIES_OFFSET and the recap record's PARTY_RECAP_SPECIES_OFFSET, both of
# which read something other than National Dex # -- e.g. Ledyba read 60, Baltoy read 317).
#
# Root cause found live: the game keeps its own internal species-name string table in memory (English NTSC-U
# release), in exact National Dex order starting at BULBASAUR (#1) through DEOXYS (#386), followed by two
# special entries EGG (#387) and BAD EGG (#388), immediately followed by type names (NORMAL, FIRE, ...) and
# ability names (STENCH, DRIZZLE, ...) -- clearly the game's own menu-text asset table, not anything specific
# to a save file. The box/recap numeric species field is evidently some OTHER internal index into a DIFFERENT
# table (not simply "National Dex minus a constant" -- Ledyba's offset from its real dex# is 105, Baltoy's is
# 26, ruling out a fixed shift), which is why it was previously (and still is) unreliable to use directly.
#
# This table sidesteps the problem entirely: it's a fixed property of the English release, not something that
# needs live memory resolution at all (unlike BLOCK_BASE or PARTY_BASE) -- hardcoded here rather than walked
# from memory each session. Validated live 2026-09-03 against every species this project has independently
# confirmed the correct National Dex # for via PARTY_BASE (Jolteon, Teddiursa, Poochyena, Ledyba, Eevee,
# Sunkern, Salamence, Metagross, Houndour, Spheal, Baltoy) -- 11/11 exact matches. Use `species_dex_from_name`
# below rather than indexing this dict directly (handles an unrecognized name gracefully).
#
# NOTE ON APOSTROPHE/SYMBOL NAMES: a few entries use the game's own non-ASCII glyphs verbatim (Nidoran's
# gender symbols, Farfetch'd's apostrophe, Mr. Mime's period+space) -- these must round-trip correctly through
# the same UTF-16BE decode already used elsewhere in this file (read_bytes(...).decode("utf-16-be")) since
# that's what a name read from a box/recap record will actually produce; not independently re-verified that
# every one of these exact glyphs decodes identically from a live memory read (only the plain-ASCII names in
# this session's actual party were cross-validated) -- flag any decode mismatch on one of these specific
# entries if it comes up.
SPECIES_NAME_TO_DEX: dict[str, int] = {
    "BULBASAUR": 1,  "IVYSAUR": 2,  "VENUSAUR": 3,  "CHARMANDER": 4,
    "CHARMELEON": 5,  "CHARIZARD": 6,  "SQUIRTLE": 7,  "WARTORTLE": 8,
    "BLASTOISE": 9,  "CATERPIE": 10,  "METAPOD": 11,  "BUTTERFREE": 12,
    "WEEDLE": 13,  "KAKUNA": 14,  "BEEDRILL": 15,  "PIDGEY": 16,
    "PIDGEOTTO": 17,  "PIDGEOT": 18,  "RATTATA": 19,  "RATICATE": 20,
    "SPEAROW": 21,  "FEAROW": 22,  "EKANS": 23,  "ARBOK": 24,
    "PIKACHU": 25,  "RAICHU": 26,  "SANDSHREW": 27,  "SANDSLASH": 28,
    "NIDORAN♀": 29,  "NIDORINA": 30,  "NIDOQUEEN": 31,  "NIDORAN♂": 32,
    "NIDORINO": 33,  "NIDOKING": 34,  "CLEFAIRY": 35,  "CLEFABLE": 36,
    "VULPIX": 37,  "NINETALES": 38,  "JIGGLYPUFF": 39,  "WIGGLYTUFF": 40,
    "ZUBAT": 41,  "GOLBAT": 42,  "ODDISH": 43,  "GLOOM": 44,
    "VILEPLUME": 45,  "PARAS": 46,  "PARASECT": 47,  "VENONAT": 48,
    "VENOMOTH": 49,  "DIGLETT": 50,  "DUGTRIO": 51,  "MEOWTH": 52,
    "PERSIAN": 53,  "PSYDUCK": 54,  "GOLDUCK": 55,  "MANKEY": 56,
    "PRIMEAPE": 57,  "GROWLITHE": 58,  "ARCANINE": 59,  "POLIWAG": 60,
    "POLIWHIRL": 61,  "POLIWRATH": 62,  "ABRA": 63,  "KADABRA": 64,
    "ALAKAZAM": 65,  "MACHOP": 66,  "MACHOKE": 67,  "MACHAMP": 68,
    "BELLSPROUT": 69,  "WEEPINBELL": 70,  "VICTREEBEL": 71,  "TENTACOOL": 72,
    "TENTACRUEL": 73,  "GEODUDE": 74,  "GRAVELER": 75,  "GOLEM": 76,
    "PONYTA": 77,  "RAPIDASH": 78,  "SLOWPOKE": 79,  "SLOWBRO": 80,
    "MAGNEMITE": 81,  "MAGNETON": 82,  "FARFETCH'D": 83,  "DODUO": 84,
    "DODRIO": 85,  "SEEL": 86,  "DEWGONG": 87,  "GRIMER": 88,
    "MUK": 89,  "SHELLDER": 90,  "CLOYSTER": 91,  "GASTLY": 92,
    "HAUNTER": 93,  "GENGAR": 94,  "ONIX": 95,  "DROWZEE": 96,
    "HYPNO": 97,  "KRABBY": 98,  "KINGLER": 99,  "VOLTORB": 100,
    "ELECTRODE": 101,  "EXEGGCUTE": 102,  "EXEGGUTOR": 103,  "CUBONE": 104,
    "MAROWAK": 105,  "HITMONLEE": 106,  "HITMONCHAN": 107,  "LICKITUNG": 108,
    "KOFFING": 109,  "WEEZING": 110,  "RHYHORN": 111,  "RHYDON": 112,
    "CHANSEY": 113,  "TANGELA": 114,  "KANGASKHAN": 115,  "HORSEA": 116,
    "SEADRA": 117,  "GOLDEEN": 118,  "SEAKING": 119,  "STARYU": 120,
    "STARMIE": 121,  "MR. MIME": 122,  "SCYTHER": 123,  "JYNX": 124,
    "ELECTABUZZ": 125,  "MAGMAR": 126,  "PINSIR": 127,  "TAUROS": 128,
    "MAGIKARP": 129,  "GYARADOS": 130,  "LAPRAS": 131,  "DITTO": 132,
    "EEVEE": 133,  "VAPOREON": 134,  "JOLTEON": 135,  "FLAREON": 136,
    "PORYGON": 137,  "OMANYTE": 138,  "OMASTAR": 139,  "KABUTO": 140,
    "KABUTOPS": 141,  "AERODACTYL": 142,  "SNORLAX": 143,  "ARTICUNO": 144,
    "ZAPDOS": 145,  "MOLTRES": 146,  "DRATINI": 147,  "DRAGONAIR": 148,
    "DRAGONITE": 149,  "MEWTWO": 150,  "MEW": 151,  "CHIKORITA": 152,
    "BAYLEEF": 153,  "MEGANIUM": 154,  "CYNDAQUIL": 155,  "QUILAVA": 156,
    "TYPHLOSION": 157,  "TOTODILE": 158,  "CROCONAW": 159,  "FERALIGATR": 160,
    "SENTRET": 161,  "FURRET": 162,  "HOOTHOOT": 163,  "NOCTOWL": 164,
    "LEDYBA": 165,  "LEDIAN": 166,  "SPINARAK": 167,  "ARIADOS": 168,
    "CROBAT": 169,  "CHINCHOU": 170,  "LANTURN": 171,  "PICHU": 172,
    "CLEFFA": 173,  "IGGLYBUFF": 174,  "TOGEPI": 175,  "TOGETIC": 176,
    "NATU": 177,  "XATU": 178,  "MAREEP": 179,  "FLAAFFY": 180,
    "AMPHAROS": 181,  "BELLOSSOM": 182,  "MARILL": 183,  "AZUMARILL": 184,
    "SUDOWOODO": 185,  "POLITOED": 186,  "HOPPIP": 187,  "SKIPLOOM": 188,
    "JUMPLUFF": 189,  "AIPOM": 190,  "SUNKERN": 191,  "SUNFLORA": 192,
    "YANMA": 193,  "WOOPER": 194,  "QUAGSIRE": 195,  "ESPEON": 196,
    "UMBREON": 197,  "MURKROW": 198,  "SLOWKING": 199,  "MISDREAVUS": 200,
    "UNOWN": 201,  "WOBBUFFET": 202,  "GIRAFARIG": 203,  "PINECO": 204,
    "FORRETRESS": 205,  "DUNSPARCE": 206,  "GLIGAR": 207,  "STEELIX": 208,
    "SNUBBULL": 209,  "GRANBULL": 210,  "QWILFISH": 211,  "SCIZOR": 212,
    "SHUCKLE": 213,  "HERACROSS": 214,  "SNEASEL": 215,  "TEDDIURSA": 216,
    "URSARING": 217,  "SLUGMA": 218,  "MAGCARGO": 219,  "SWINUB": 220,
    "PILOSWINE": 221,  "CORSOLA": 222,  "REMORAID": 223,  "OCTILLERY": 224,
    "DELIBIRD": 225,  "MANTINE": 226,  "SKARMORY": 227,  "HOUNDOUR": 228,
    "HOUNDOOM": 229,  "KINGDRA": 230,  "PHANPY": 231,  "DONPHAN": 232,
    "PORYGON2": 233,  "STANTLER": 234,  "SMEARGLE": 235,  "TYROGUE": 236,
    "HITMONTOP": 237,  "SMOOCHUM": 238,  "ELEKID": 239,  "MAGBY": 240,
    "MILTANK": 241,  "BLISSEY": 242,  "RAIKOU": 243,  "ENTEI": 244,
    "SUICUNE": 245,  "LARVITAR": 246,  "PUPITAR": 247,  "TYRANITAR": 248,
    "LUGIA": 249,  "HO-OH": 250,  "CELEBI": 251,  "TREECKO": 252,
    "GROVYLE": 253,  "SCEPTILE": 254,  "TORCHIC": 255,  "COMBUSKEN": 256,
    "BLAZIKEN": 257,  "MUDKIP": 258,  "MARSHTOMP": 259,  "SWAMPERT": 260,
    "POOCHYENA": 261,  "MIGHTYENA": 262,  "ZIGZAGOON": 263,  "LINOONE": 264,
    "WURMPLE": 265,  "SILCOON": 266,  "BEAUTIFLY": 267,  "CASCOON": 268,
    "DUSTOX": 269,  "LOTAD": 270,  "LOMBRE": 271,  "LUDICOLO": 272,
    "SEEDOT": 273,  "NUZLEAF": 274,  "SHIFTRY": 275,  "TAILLOW": 276,
    "SWELLOW": 277,  "WINGULL": 278,  "PELIPPER": 279,  "RALTS": 280,
    "KIRLIA": 281,  "GARDEVOIR": 282,  "SURSKIT": 283,  "MASQUERAIN": 284,
    "SHROOMISH": 285,  "BRELOOM": 286,  "SLAKOTH": 287,  "VIGOROTH": 288,
    "SLAKING": 289,  "NINCADA": 290,  "NINJASK": 291,  "SHEDINJA": 292,
    "WHISMUR": 293,  "LOUDRED": 294,  "EXPLOUD": 295,  "MAKUHITA": 296,
    "HARIYAMA": 297,  "AZURILL": 298,  "NOSEPASS": 299,  "SKITTY": 300,
    "DELCATTY": 301,  "SABLEYE": 302,  "MAWILE": 303,  "ARON": 304,
    "LAIRON": 305,  "AGGRON": 306,  "MEDITITE": 307,  "MEDICHAM": 308,
    "ELECTRIKE": 309,  "MANECTRIC": 310,  "PLUSLE": 311,  "MINUN": 312,
    "VOLBEAT": 313,  "ILLUMISE": 314,  "ROSELIA": 315,  "GULPIN": 316,
    "SWALOT": 317,  "CARVANHA": 318,  "SHARPEDO": 319,  "WAILMER": 320,
    "WAILORD": 321,  "NUMEL": 322,  "CAMERUPT": 323,  "TORKOAL": 324,
    "SPOINK": 325,  "GRUMPIG": 326,  "SPINDA": 327,  "TRAPINCH": 328,
    "VIBRAVA": 329,  "FLYGON": 330,  "CACNEA": 331,  "CACTURNE": 332,
    "SWABLU": 333,  "ALTARIA": 334,  "ZANGOOSE": 335,  "SEVIPER": 336,
    "LUNATONE": 337,  "SOLROCK": 338,  "BARBOACH": 339,  "WHISCASH": 340,
    "CORPHISH": 341,  "CRAWDAUNT": 342,  "BALTOY": 343,  "CLAYDOL": 344,
    "LILEEP": 345,  "CRADILY": 346,  "ANORITH": 347,  "ARMALDO": 348,
    "FEEBAS": 349,  "MILOTIC": 350,  "CASTFORM": 351,  "KECLEON": 352,
    "SHUPPET": 353,  "BANETTE": 354,  "DUSKULL": 355,  "DUSCLOPS": 356,
    "TROPIUS": 357,  "CHIMECHO": 358,  "ABSOL": 359,  "WYNAUT": 360,
    "SNORUNT": 361,  "GLALIE": 362,  "SPHEAL": 363,  "SEALEO": 364,
    "WALREIN": 365,  "CLAMPERL": 366,  "HUNTAIL": 367,  "GOREBYSS": 368,
    "RELICANTH": 369,  "LUVDISC": 370,  "BAGON": 371,  "SHELGON": 372,
    "SALAMENCE": 373,  "BELDUM": 374,  "METANG": 375,  "METAGROSS": 376,
    "REGIROCK": 377,  "REGICE": 378,  "REGISTEEL": 379,  "LATIAS": 380,
    "LATIOS": 381,  "KYOGRE": 382,  "GROUDON": 383,  "RAYQUAZA": 384,
    "JIRACHI": 385,  "DEOXYS": 386,  "EGG": 387,  "BAD EGG": 388,
}


def species_dex_from_name(name: str) -> int | None:
    """Looks up a species (or EGG/BAD EGG) name -- as decoded from any UTF-16BE name field in this file, e.g.
    a box/recap record's `.name` -- against SPECIES_NAME_TO_DEX. Returns None for an unrecognized string
    (empty/garbage read, or a player-set nickname that doesn't happen to match a species name) rather than
    raising, since callers may pass an arbitrary just-read name. This is the RECOMMENDED way to get a National
    Dex # from a box array or recap record -- prefer it over BOX_SLOT_SPECIES_OFFSET / PARTY_RECAP_SPECIES_OFFSET's
    raw numeric field, which is confirmed to encode something other than National Dex # (see the section
    comment above). Does not apply to PARTY_BASE's own species field (PARTY_SPECIES_OFFSET), which is already
    independently confirmed correct and needs no lookup."""
    return SPECIES_NAME_TO_DEX.get(name.strip().upper())


# ----------------------------------------------------------------------------------------------------------
# Low-level Dolphin access
# ----------------------------------------------------------------------------------------------------------

def hook() -> bool:
    """(Re)hook to a running Dolphin process. Mirrors bridge.py's fix for a known dolphin_memory_engine issue:
    un-hook (swallowing any exception) immediately before every hook attempt, or repeated hook() calls from a
    long-running process can get stuck -- see pokemon-xd-live-bridge-notes.md's debugging journey."""
    try:
        dme.un_hook()
    except Exception:
        pass
    dme.hook()
    return dme.is_hooked()


def is_hooked() -> bool:
    """Cheap check for an already-established hook -- unlike hook() itself, does NOT un-hook/re-hook, so this
    is what a polling loop should call every tick (see hook()'s own docstring on why repeated hook() calls
    from a long-running process is a known problem)."""
    return dme.is_hooked()


def read_bytes(address: int, length: int) -> bytes:
    return dme.read_bytes(address, length)


def write_bytes(address: int, data: bytes) -> None:
    dme.write_bytes(address, data)


def dump_mem1() -> bytes:
    """Full MEM1 read, chunked (mirrors bridge.py's dump command). Slow (~seconds) -- only used for the
    one-time landmark search, never in a polling loop."""
    chunks = []
    chunk_size = 0x10000
    for offset in range(0, MEM1_SIZE, chunk_size):
        size = min(chunk_size, MEM1_SIZE - offset)
        chunks.append(read_bytes(MEM1_START + offset, size))
    return b"".join(chunks)


# ----------------------------------------------------------------------------------------------------------
# Resolving the player-state block's current base
# ----------------------------------------------------------------------------------------------------------

def _looks_like_real_block_base(candidate: int, mem: bytes) -> bool:
    """Validates a candidate BLOCK_BASE by checking for the `MONEY_DISPLAY_MARKER_OFFSET` structural signature
    (8 bytes of 0x01 at a fixed offset past money) plus a plausible money value -- see
    `resolve_block_base`'s docstring for why this check exists at all.

    **Deliberately NOT just "does money look plausible"** -- an earlier version of this check accepted any
    candidate with an in-range money value OR an empty first Items-pocket slot, and that's exactly what a
    block of unrelated all-zero padding also looks like: live-tested against a real false-positive candidate
    (money=0, empty Items slot, *not* the real block -- an all-zero neighbor of the unrelated 0x8042xxxx
    party-struct region) and it wrongly passed. The 8x0x01 marker is a much more specific signature -- live-
    tested to reject that same false positive while still accepting the real block -- because it requires a
    non-trivial, non-zero, non-random-looking exact byte run at an exact offset, not just "some plausible
    number was here.\""""
    def u32(addr: int) -> int:
        off = addr - MEM1_START
        return struct.unpack(">I", mem[off:off + 4])[0]

    money = u32(candidate + MONEY_OFFSET)
    if not (0 <= money <= 99_999_999):
        return False
    off = candidate + MONEY_DISPLAY_MARKER_OFFSET - MEM1_START
    return mem[off:off + 8] == b"\x01" * 8


def resolve_block_base(landmark: str) -> int | None:
    """One-time-per-connection full-memory scan for `landmark` (see `TRAINER_NAME_LANDMARK`'s docstring above
    -- this MUST be the actual connected player's slot name, per the setup-instructions convention described
    there, never a hardcoded guess), returning the resolved player-state block base (BLOCK_BASE, see the
    offset constants above), or None if no occurrence of the landmark validates as a real block base (e.g.
    not actually in-game yet, the player's in-game trainer name doesn't actually match their slot name, or
    XD's name-entry screen silently truncated/altered it on save creation).

    **Checks every occurrence of the landmark text, not just the first.** A landmark string can appear
    multiple times in a 24MB snapshot for reasons that have nothing to do with the real player-state block --
    confirmed live this session: searching for a trainer name found NINE occurrences in one dump (the real
    block's own copy, plus several instances of the transient "recap" record documented in
    pokemon-xd-ram-map.md, which duplicates the trainer's name too), and the *lowest-addressed* one (what a
    naive `bytes.find()` returns) was NOT the real block -- it was inside the unrelated `0x8042xxxx`
    party-struct region.

    **Multiple candidates can pass `_looks_like_real_block_base`, not just the real block.** Live-tested: of
    9 landmark occurrences, exactly 2 validated -- the real `0x8047xxxx`-region block AND a second,
    structurally-identical `0x804Axxxx`-region copy. This matches pokemon-xd-ram-map.md's already-documented
    finding that some fields (e.g. the Poke Ball pocket) have a `0x804Axxxx` mirror with different, less
    reliable sync timing than the `0x8047xxxx` copy this project has built every other confirmed offset
    against. So: among validated candidates, one in the `0x8047xxxx`-`0x8049xxxx` range is preferred; a
    candidate outside that range is only returned if nothing inside it validated (logged as a fallback, since
    that would mean this boot's layout doesn't match every previous boot studied so far).

    Confirmed methodology: see pokemon-xd-ram-map.md's restart-test section. Deliberately NOT cached beyond
    one connection's lifetime by this function itself -- callers should resolve once at connect time and
    reuse the result for as long as Dolphin stays hooked to the same boot."""
    mem = dump_mem1()
    needle = landmark.encode("utf-16-be")
    validated: list[int] = []
    idx = mem.find(needle)
    while idx != -1:
        trainer_name_addr = MEM1_START + idx
        # CORRECTED 2026-09-02: BLOCK_BASE is *after* the trainer name in memory, not before it -- see
        # RECORD_TRAINER_NAME_OFFSET's comment above for how this was found and verified.
        candidate = trainer_name_addr + RECORD_TRAINER_NAME_OFFSET
        if _looks_like_real_block_base(candidate, mem):
            validated.append(candidate)
        idx = mem.find(needle, idx + 1)
    if not validated:
        return None
    preferred = [c for c in validated if 0x80470000 <= c <= 0x8049FFFF]
    return preferred[0] if preferred else validated[0]


# ----------------------------------------------------------------------------------------------------------
# Bag pocket read/write (confirmed live for Items + Poke Ball pockets; Key Items pocket unconfirmed)
# ----------------------------------------------------------------------------------------------------------

@dataclass
class BagSlot:
    index: int
    address: int
    item_id: int
    quantity: int

    @property
    def empty(self) -> bool:
        return self.item_id == 0 and self.quantity == 0


def read_pocket(pocket_base: int, max_slots: int) -> list[BagSlot]:
    raw = read_bytes(pocket_base, max_slots * 4)
    slots = []
    for i in range(max_slots):
        item_id, qty = struct.unpack_from(">HH", raw, i * 4)
        slots.append(BagSlot(i, pocket_base + i * 4, item_id, qty))
    return slots


def write_slot(slot_address: int, item_id: int, quantity: int) -> None:
    write_bytes(slot_address, struct.pack(">HH", item_id, quantity))


def give_item(pocket_base: int, item_id: int, quantity: int, max_slots: int) -> bool:
    """Increments quantity if item_id is already present in this pocket; otherwise writes it into the first
    empty slot. Returns False if the item isn't present and the pocket is full (caller must decide what to
    do -- e.g. queue it for later, per the user's requested TWW-style delivery-queue design, NOT YET BUILT).

    NOTE: only actually validated (this session, live, in-game) for the Items and Poke Ball pockets -- see
    the module docstring. Should be re-validated the same way before trusting it against Key Items or any
    other pocket."""
    slots = read_pocket(pocket_base, max_slots)
    for slot in slots:
        if slot.item_id == item_id and not slot.empty:
            write_slot(slot.address, item_id, slot.quantity + quantity)
            return True
    for slot in slots:
        if slot.empty:
            write_slot(slot.address, item_id, quantity)
            return True
    return False  # pocket full


# ----------------------------------------------------------------------------------------------------------
# Item-pocket routing -- NEW 2026-09-03, built for Client.py's incoming-item delivery loop.
#
# Maps a real Bag `game_item_id` (see items.py / pokemon-xd-confirmed-item-ids.md) to the correct pocket
# array + a safe slot window within it, per the confirmed pocket map in that doc:
#   1. Balls (1-12)              -> Balls+TMs pocket, slots 0-11
#   2. TMs/HMs (289-346)         -> Balls+TMs pocket, slots 16-74 (the confirmed-safe TM/HM window -- NEVER
#                                    slots 75-81, confirmed "known-bad": writing a non-Ball/TM id there
#                                    produces corrupted display)
#   3. Berries 146-175 (30 of the 43 real berries) -> the Berries pocket, computed as
#      POKEBALL_POCKET_OFFSET + 82*4 (confirmed to start "at or before pocket-relative slot 82" of the
#      Balls/TMs address range), windowed to slots 82-124 so it NEVER touches the confirmed-reserved
#      129-140 sub-range.
#   4. Key items with a confirmed id (523-533: Krane Memos, Voice Cases, Disc Case) -> Key Items pocket,
#      slots 0-42.
#   5. Everything else with a confirmed id in 13-225 (medicine, vitamins, evolution stones, battle X-items,
#      repels, misc treasure, berries 133-145, held items 179-225) -> Items pocket, slots 0-29.
#   6. `game_item_id is None` (Ein File S, the 15 unresolved key items, the trap item) -> no RAM write at
#      all; `route_and_give_item` returns None rather than True/False so the caller (Client.py) can handle
#      this distinctly (announce-only for the unresolved key items, a special client-side effect for the
#      trap -- see Client.py's `_apply_trap_effect`).
# Every routing decision below only ever writes inside a range this session independently confirmed safe
# (pokemon-xd-confirmed-item-ids.md) -- nothing here guesses at an unconfirmed pocket boundary.
# ----------------------------------------------------------------------------------------------------------

BALLS_SLOT_COUNT = 12                        # pocket-relative slots 0-11
TM_HM_POCKET_RELATIVE_START = 16             # pocket-relative slot 16 ...
TM_HM_SLOT_COUNT = 59                        # ... through 74 inclusive (59 slots) -- NEVER 75-81
BERRIES_POCKET_RELATIVE_START = 82           # "at or before pocket-relative slot 82" per the confirmed doc
BERRIES_SLOT_COUNT = 43                      # 82-124 inclusive -- stops well short of the reserved 129-140
                                              # range, and comfortably covers all 30 of berries 146-175


def route_and_give_item(block_base: int, game_item_id: int | None, quantity: int = 1) -> bool | None:
    """Delivers one AP-placed item into the correct real Bag pocket. Returns True/False exactly like
    give_item() (delivered / pocket full -- caller should retry later on False), or None if `game_item_id` is
    None (nothing to write -- see the section comment above for how Client.py should handle that case
    instead)."""
    if game_item_id is None:
        return None
    if 1 <= game_item_id <= BALLS_SLOT_COUNT:
        return give_item(block_base + POKEBALL_POCKET_OFFSET, game_item_id, quantity, BALLS_SLOT_COUNT)
    if 289 <= game_item_id <= 346:
        pocket_base = block_base + POKEBALL_POCKET_OFFSET + TM_HM_POCKET_RELATIVE_START * 4
        return give_item(pocket_base, game_item_id, quantity, TM_HM_SLOT_COUNT)
    if 146 <= game_item_id <= 175:
        pocket_base = block_base + POKEBALL_POCKET_OFFSET + BERRIES_POCKET_RELATIVE_START * 4
        return give_item(pocket_base, game_item_id, quantity, BERRIES_SLOT_COUNT)
    if 523 <= game_item_id <= 533:
        return give_item(block_base + KEY_ITEMS_OFFSET, game_item_id, quantity, KEY_ITEMS_MAX_SLOTS)
    # Default: the Items pocket, which "tolerates any item id fine" per the confirmed doc -- correct for the
    # documented 13-225 range (medicine/vitamins/stones/X-items/repels/misc treasure/berries 133-145/held
    # items) and a safe fallback for anything else with a real id this table doesn't specifically special-case.
    return give_item(block_base + ITEMS_POCKET_OFFSET, game_item_id, quantity, ITEMS_POCKET_MAX_SLOTS)


# ----------------------------------------------------------------------------------------------------------
# Money (plain u32BE, not a pocket record)
# ----------------------------------------------------------------------------------------------------------

def read_money(block_base: int) -> int:
    return struct.unpack(">I", read_bytes(block_base + MONEY_OFFSET, 4))[0]


def write_money(block_base: int, value: int) -> None:
    write_bytes(block_base + MONEY_OFFSET, struct.pack(">I", value))


# ----------------------------------------------------------------------------------------------------------
# Species detection: party + PC box
#
# The end goal (per the player's request) is: notice when a species National Dex # appears somewhere the
# player owns it that wasn't seen before, and turn that into an AP location check for "Catch - {species}"
# (see pokemon_xd/locations.py / pokemon_xd/species.py -- SPECIES_LOCATION_TO_DEX is the same table run in
# reverse, name -> dex #, in case a caller ever needs that direction).
#
# Two data sources, two very different confidence levels -- read the constants' comments above before using
# either in a real always-on client:
#   - `read_party_species`: safe to poll continuously. CONFIRMED live, stable-address data source.
#   - `read_box_slot_species`: best-effort only. The underlying address formula is confirmed to shift by a
#     clean, consistent stride per box slot navigated through, but whether it holds real live data for a slot
#     that ISN'T currently being displayed in the box UI is unconfirmed and, per the ram-map doc's own
#     assessment, more likely NOT the case (it looks like a single relocating "currently viewed" buffer, not a
#     true per-slot array). Silently trusting box-address reads in an unattended background loop risks two
#     failure modes: (a) false negatives -- most of the 386-slot range simply reads stale/zero and a real catch
#     never gets detected, and (b) worse, false positives -- reading a byte-for-byte stale leftover value (or
#     genuinely unrelated data, if the "recap" buffer has been reused/repurposed for something else since) and
#     reporting a species the player doesn't actually currently have in that box slot. Until this is
#     independently confirmed (see the ram-map doc's recommended next diagnostic step), only feed
#     `read_box_slot_species` slot indices the caller has independent reason to believe are genuinely being
#     displayed right now (e.g. the player just navigated the box UI to that slot in the same input), not as a
#     blind sweep of "every slot, every poll."
# ----------------------------------------------------------------------------------------------------------

# --- CAVEAT ADDED 2026-09-03, downgrades a previously-confident claim: `species` from this struct (below) is
# NOT unconditionally reliable after all. Live-confirmed counterexample: a party member correctly showing
# name="SPHEAL", current level, and current HP (all genuinely live/correct) nonetheless read species=316 --
# which is GULPIN's real National Dex #, not Spheal's (363) -- in TWO separate dumps taken minutes apart, so
# not a one-off glitch. Cause unconfirmed (leading guess: this slot may have held a Gulpin at some earlier
# point and the species sub-field specifically never got refreshed when Spheal took over it, mirroring the
# same class of per-field independent-sync-timing bug already documented elsewhere in this project -- name/
# level/HP refreshing while a different field in the SAME struct silently doesn't). Practical fix: prefer
# `species_dex_from_name(member.name)` over `member.species` / this function's raw output wherever the name
# is still a real species name (not a player-set nickname) -- name has been correct 100% of the time across
# every structure tested in this project so far, unlike every numeric species field tried (this one, the box
# array's, and the recap record's, all now have at least one confirmed failure case). **Known remaining gap**:
# once a party member is renamed (e.g. after purification), name-based lookup no longer works (the string is
# a nickname, not a species name) and there is currently NO known-reliable field to fall back on for that
# specific case -- a real client should identify/cache a member's species via name BEFORE any rename happens,
# rather than re-deriving it from any single field after the fact.

def read_party_species(party_base: int = PARTY_BASE, max_slots: int = PARTY_MAX_SLOTS) -> list[int]:
    """Returns the National Dex # of every non-empty party slot, in slot order, from the RAW numeric field --
    see the caveat immediately above before trusting this over read_party_members()-plus-species_dex_from_name.
    An all-zero slot (the confirmed convention for "never filled") is skipped rather than returned as 0."""
    species: list[int] = []
    for i in range(max_slots):
        slot_species_addr = party_base + i * PARTY_SLOT_STRIDE + PARTY_SPECIES_OFFSET
        dex_number = struct.unpack(">H", read_bytes(slot_species_addr, 2))[0]
        if dex_number != 0:
            species.append(dex_number)
    return species


@dataclass
class PartyMember:
    """One occupied PARTY_BASE slot. `name`, `level`, `max_hp`, `current_hp` are confirmed continuously
    live-synced. `species` (the raw numeric field) is NOT unconditionally reliable -- see the caveat above
    read_party_species -- prefer `reliable_species` (name-based lookup) unless this member has been renamed."""

    party_index: int
    name: str  # current nickname if the player set one, else the species' default display name
    species: int  # raw numeric field -- see the caveat above; can be wrong even for a live, correctly-named slot
    level: int
    max_hp: int
    current_hp: int

    @property
    def reliable_species(self) -> int | None:
        """species_dex_from_name(self.name) -- returns None if `name` isn't a recognized species name (most
        likely because the player renamed this Pokemon; see the known gap noted above read_party_species)."""
        return species_dex_from_name(self.name)


def read_party_members(party_base: int = PARTY_BASE, max_slots: int = PARTY_MAX_SLOTS) -> list[PartyMember]:
    """Like read_party_species, but returns full per-slot info including the CURRENT name/nickname -- this is
    the reliable half of the two-structure correlation described in read_purified_party_members below. Skips
    empty (all-zero species) slots, same convention as read_party_species."""
    members = []
    for i in range(max_slots):
        slot_addr = party_base + i * PARTY_SLOT_STRIDE
        species = struct.unpack(">H", read_bytes(slot_addr + PARTY_SPECIES_OFFSET, 2))[0]
        if species == 0:
            continue
        name = read_bytes(slot_addr, PARTY_NAME_MAX_BYTES).decode("utf-16-be", errors="replace").split("\x00")[0]
        level = read_bytes(slot_addr + PARTY_LEVEL_OFFSET, 1)[0]
        max_hp = struct.unpack(">H", read_bytes(slot_addr + PARTY_MAXHP_OFFSET, 2))[0]
        current_hp = struct.unpack(">H", read_bytes(slot_addr + PARTY_CURHP_OFFSET, 2))[0]
        members.append(PartyMember(i, name, species, level, max_hp, current_hp))
    return members


def read_box_slot_species(block_base: int, slot_index: int, slots_per_box: int = 30) -> int | None:
    """Reads the species National Dex # at the given flat slot index (0 = Box 1 Slot 1, slots_per_box = Box 2
    Slot 1, etc.) using the CONFIRMED (2026-09-03) addressing formula, including the per-box padding term --
    see BOX_PADDING_PER_BOX's comment above. The text-anchor address itself is now trustworthy across box
    boundaries. Returns None if the read comes back zero (empty slot, OR the species sub-field hasn't synced
    yet for a just-deposited Pokemon -- see BOX_SLOT_SPECIES_OFFSET's caveat above, these two cases are NOT
    distinguishable from this read alone) or outside the valid 1-386 Dex range (would indicate something is
    still wrong, though the addressing formula itself is no longer the suspected cause).

    **Still do not use this in a blind background sweep of every slot for detecting new arrivals** -- not
    because the address might be wrong (it's confirmed now), but because the species sub-field can read stale/
    wrong data for some as-yet-uncharacterized window after a deposit (see BOX_SLOT_SPECIES_OFFSET's caveat).
    Prefer the party struct (read_party_species) for anything that needs to fire promptly and correctly; treat
    box reads as a slower-cadence or explicitly-triggered (e.g. "player just closed the PC menu") supplementary
    check until the species-field timing question above is resolved."""
    box_idx, local_slot_idx = divmod(slot_index, slots_per_box)
    text_anchor = (
        block_base
        + BOX_SLOT_TEXT_ANCHOR_OFFSET
        + box_idx * (slots_per_box * BOX_SLOT_STRIDE + BOX_PADDING_PER_BOX)
        + local_slot_idx * BOX_SLOT_STRIDE
    )
    dex_number = struct.unpack(">I", read_bytes(text_anchor + BOX_SLOT_SPECIES_OFFSET, 4))[0]
    if dex_number == 0 or dex_number > 386:
        return None
    return dex_number


@dataclass
class PartyRecapRecord:
    """One party member's 196-byte "recap" record -- see the PARTY_RECAP_* constants' comments above for the
    full derivation and caveats (in particular: `species` is NOT reliable, and any single field here should be
    read as "possibly stale" unless it's known to have just changed -- this whole record only refreshes
    per-slot on a recap-worthy event, it isn't continuously live-synced like PARTY_BASE)."""

    party_index: int
    address: int
    name: str
    species: int  # unreliable, see PARTY_RECAP_SPECIES_OFFSET
    purified_flag: int  # 0 observed pre-purification, 64 (0x40) observed post-purification (2x confirmed)
    max_hp: int
    attack: int
    defense: int
    sp_attack: int
    sp_defense: int
    speed: int


def read_party_recap_record(block_base: int, party_index: int) -> PartyRecapRecord:
    """Reads party slot `party_index`'s (0-indexed) recap record. Does NOT check whether the slot is actually
    occupied -- an empty party slot's record contents are unconfirmed/untested; callers should cross-reference
    against read_party_species (PARTY_BASE) to know which indices are real occupants."""
    address = block_base + PARTY_RECAP_OFFSET + party_index * PARTY_RECAP_STRIDE
    raw = read_bytes(address, PARTY_RECAP_STRIDE)
    name = raw[0:0x12].decode("utf-16-be", errors="replace").split("\x00")[0]
    species = struct.unpack(">H", raw[PARTY_RECAP_SPECIES_OFFSET:PARTY_RECAP_SPECIES_OFFSET + 2])[0]
    purified_flag = struct.unpack(
        ">H", raw[PARTY_RECAP_PURIFIED_FLAG_OFFSET:PARTY_RECAP_PURIFIED_FLAG_OFFSET + 2]
    )[0]
    max_hp = struct.unpack(">H", raw[PARTY_RECAP_MAXHP_OFFSET:PARTY_RECAP_MAXHP_OFFSET + 2])[0]
    stats = {
        stat_name: struct.unpack(">H", raw[off:off + 2])[0]
        for stat_name, off in PARTY_RECAP_STAT_OFFSETS.items()
    }
    return PartyRecapRecord(
        party_index=party_index,
        address=address,
        name=name,
        species=species,
        purified_flag=purified_flag,
        max_hp=max_hp,
        attack=stats["attack"],
        defense=stats["defense"],
        sp_attack=stats["sp_attack"],
        sp_defense=stats["sp_defense"],
        speed=stats["speed"],
    )


@dataclass
class PurificationTracker:
    """Watches `PARTY_RECAP_PURIFIED_FLAG_OFFSET` across the party's recap records and reports a party index
    exactly once when that flag is newly seen non-zero (matching the confirmed 0->64 transition). Deliberately
    keyed by (party_index, flag_value) rather than assuming every real transition is exactly "0 -> 64" forever
    -- only two data points exist so far (see the constant's comment above) -- but treats "flag went from its
    last-seen value to a new non-zero value" as the event, which covers the confirmed case and stays correct
    even if a later purification turns out to produce a different nonzero value.

    Usage sketch:
        tracker = PurificationTracker()
        while True:
            newly_purified = tracker.poll(block_base, occupied_party_indices=[0, 1, 2, 3])
            for party_index in newly_purified:
                ...fire whatever Archipelago check corresponds to this slot's current species...
            time.sleep(POLL_INTERVAL_SECONDS)

    NOTE: pass only currently-occupied party indices (cross-reference read_party_species) -- an empty slot's
    recap record contents are untested and could produce a false trigger."""

    last_seen_flags: dict[int, int] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.last_seen_flags is None:
            self.last_seen_flags = {}

    def poll(self, block_base: int, occupied_party_indices: list[int]) -> list[int]:
        newly_purified = []
        for party_index in occupied_party_indices:
            record = read_party_recap_record(block_base, party_index)
            previous = self.last_seen_flags.get(party_index, 0)
            if record.purified_flag != 0 and previous == 0:
                newly_purified.append(party_index)
            self.last_seen_flags[party_index] = record.purified_flag
        return newly_purified


# --- Name-correlated version, 2026-09-03. REVISED same day after a live rename test -- read this before
# trusting the function below.
#
# The first version of this function trusted PARTY_BASE's name field as ground truth and rejected the
# same-index recap record whenever the names disagreed, falling back to a full scan (or "unmatched" if even
# that failed). A live test -- purifying Ledyba and renaming it in the same action -- broke that assumption
# in a way that flipped which structure was actually "stale":
#
#   - PARTY_BASE's own `name` field did NOT update to the new nickname immediately -- it still read "LEDYBA"
#     well after the rename (species stayed correct throughout: 165, confirmed unaffected by the rename).
#   - The recap record's name field DID update immediately, to the real new nickname, as part of the same
#     write that set the purification flag and refreshed the stat block.
#   - So the first version's "trust PARTY_BASE's name, reject on mismatch" logic reported this slot
#     "unmatched" -- a real miss, caused by trusting the wrong side.
#
# The SAME test also settled the question the name-matching layer was originally built to guard against: does
# recap-slot index track live party position across a manual reorder? During this same bracket the party
# order actually changed (Ledyba and Poochyena swapped positions) with no purification event for Poochyena --
# and Poochyena's recap record (byte-for-byte: flag, every stat) was found to have moved from its old index to
# its new one, matching its new party position exactly. So recap-index DOES track current party position, even
# under a manual reorder, not just "whichever slot last had an event."
#
# Conclusion: same-index correlation is trustworthy and should be the primary signal, not a fallback. Name
# comparison is downgraded to a diagnostic annotation (did the name in this slot change since we'd expect) --
# useful for noticing a rename happened, never a reason to discard a same-index match.

def correlate_party_with_recap(
    block_base: int,
    party_base: int = PARTY_BASE,
    max_slots: int = PARTY_MAX_SLOTS,
) -> dict[int, tuple[PartyRecapRecord, str]]:
    """For every currently-occupied PARTY_BASE slot, returns its recap record at the SAME index -- confirmed
    live (2026-09-03) to track current party position even across a manual reorder, so this is trusted
    unconditionally, never rejected on a name mismatch (see the section comment above for why). Returns
    {party_index: (recap_record, name_status)}, where name_status is "name_match" (recap name == PARTY_BASE's
    current name) or "name_differs" (informational only -- e.g. PARTY_BASE hasn't caught up to a recent rename
    yet, as confirmed live; does not mean the record is wrong)."""
    members = read_party_members(party_base, max_slots)
    all_recaps = [read_party_recap_record(block_base, i) for i in range(max_slots)]
    correlation: dict[int, tuple[PartyRecapRecord, str]] = {}
    for member in members:
        same_index = all_recaps[member.party_index]
        status = "name_match" if same_index.name == member.name else "name_differs"
        correlation[member.party_index] = (same_index, status)
    return correlation


@dataclass
class NamedPurificationTracker:
    """Same purpose as PurificationTracker, but keyed by SPECIES (from the reliable PARTY_BASE, per
    read_party_members) rather than by party slot position or by name.

    **Why not position, after all**: live-tested (2026-09-03) across a real bracket where a manual party
    reorder happened in the same window as a genuine new purification (Ledyba purified+renamed, swapping
    positions with the already-purified Poochyena in the same update). A position-keyed tracker got this
    completely wrong both ways: it missed Ledyba's real new purification (the slot Ledyba moved into already
    had flag=64 on file, from Poochyena's earlier purification, so no 0->64 transition was seen there) AND
    falsely reported Poochyena as newly purified a second time (the slot Poochyena moved INTO had flag=0 on
    file, from Ledyba's old pre-purification state at that position). Keying by species instead survives this
    because species is confirmed to stay correct in PARTY_BASE through both a reorder and a rename.

    **Why not name**: name is exactly what a purification-time rename can change out from under a tracking
    key -- see correlate_party_with_recap's comment for the live-confirmed case (recap's name field updates
    immediately on a rename; PARTY_BASE's own name field does not, at least not immediately). Species is the
    one identity signal confirmed stable across every event tested so far (battle, level-up, reorder, rename).

    **Known limitation, not yet handled**: two party members of the same species would collide under this
    keying (species is not a unique-individual ID -- this project has never located anything more specific,
    like a PID/personality value, for a live party member). Not a concern for the confirmed 4-member party
    tested so far; flag this if duplicate-species parties become relevant.

    Usage sketch:
        tracker = NamedPurificationTracker()
        while True:
            newly_purified = tracker.poll(block_base)  # list of (species, party_index) tuples
            for species, party_index in newly_purified:
                ...fire whatever Archipelago check corresponds to `species`...
            time.sleep(POLL_INTERVAL_SECONDS)

    `renamed_slots` (party_index -> recap's current name) after each poll() call lists any occupied slot where
    the recap record's name currently disagrees with PARTY_BASE's -- confirmed live to mean "this slot was
    just renamed and PARTY_BASE hasn't caught up yet," not an error. Purely informational."""

    last_seen_flags: dict[int, int] = None  # type: ignore[assignment]  # keyed by species, NOT party_index
    renamed_slots: dict[int, str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.last_seen_flags is None:
            self.last_seen_flags = {}
        if self.renamed_slots is None:
            self.renamed_slots = {}

    def poll(self, block_base: int, party_base: int = PARTY_BASE, max_slots: int = PARTY_MAX_SLOTS) -> list[tuple[int, int]]:
        newly_purified: list[tuple[int, int]] = []
        self.renamed_slots = {}
        members_by_index = {m.party_index: m for m in read_party_members(party_base, max_slots)}
        for party_index, (record, name_status) in correlate_party_with_recap(block_base, party_base, max_slots).items():
            if name_status == "name_differs":
                self.renamed_slots[party_index] = record.name
            species = members_by_index[party_index].species
            previous = self.last_seen_flags.get(species, 0)
            if record.purified_flag != 0 and previous == 0:
                newly_purified.append((species, party_index))
            self.last_seen_flags[species] = record.purified_flag
        return newly_purified


# Mirrors pokemon_xd/locations.py's PURIFICATION_LOCATION_COUNT and purification_location_name -- duplicated
# here (rather than loaded from locations.py the way species.py's lookup is loaded above) because locations.py
# itself imports BaseClasses/Region from the real Archipelago package, so it can't be loaded standalone the
# way species.py can. Keep these two definitions in sync if the count or naming scheme ever changes.
PURIFICATION_LOCATION_COUNT = 32


def purification_location_name(count: int) -> str:
    return f"Purify {count} Shadow Pokemon"


@dataclass
class PurificationCountTracker:
    """Turns individual purification EVENTS (from NamedPurificationTracker) into the cumulative-count AP
    location names the player asked for -- "Purify 1 Shadow Pokemon", "Purify 2 Shadow Pokemon", ... up to
    "Purify 32 Shadow Pokemon" (PURIFICATION_LOCATION_COUNT). `poll()` returns every newly-crossed threshold
    location name this call (almost always length 0 or 1 -- a poll interval short enough to catch a single
    flag flip will essentially never catch two purifications in the same tick -- but the loop below handles
    more than one just in case a poll was missed/delayed).

    Usage sketch (once CommonClient integration exists), mirrors SpeciesTracker's:
        tracker = PurificationCountTracker()
        while True:
            newly_crossed = tracker.poll(block_base)  # list of location names, e.g. ["Purify 3 Shadow Pokemon"]
            for location_name in newly_crossed:
                ...send a LocationChecks packet for location_name...
            time.sleep(POLL_INTERVAL_SECONDS)

    **Known limitation, not fixed here** (see pokemon-xd-ram-map.md's purification-detection section and this
    project's "decisions needed" list from the 2026-09-03 apworld build): `total_purified` only counts
    purifications OBSERVED LIVE by this tracker instance during the connected session. It does NOT retroactively
    account for:
      - Shadow Pokemon already purified before this client ever connected on this save file -- no known RAM
        field holds a lifetime "Pokemon purified so far" counter (not investigated/found by this project).
      - A purified Pokemon that has since been moved to the PC -- the purification flag lives in the party
        "recap" record (see PARTY_RECAP_PURIFIED_FLAG_OFFSET), which only has live slots for the CURRENT
        party, not PC-stored members; whether an equivalent flag exists in box-slot storage is unconfirmed.
    Practical implication: connect the client near the start of a session, before purifying anything, for an
    accurate count. This is safe on the AP-protocol side regardless of the above -- the server already
    deduplicates already-checked locations, so a client that re-derives "purified so far" differently across a
    reconnect can never un-check or duplicate-check anything; it can only ever under-report a threshold it
    should already have crossed, never falsely report one early."""

    tracker: NamedPurificationTracker = None  # type: ignore[assignment]
    total_purified: int = 0

    def __post_init__(self) -> None:
        if self.tracker is None:
            self.tracker = NamedPurificationTracker()

    def poll(self, block_base: int, party_base: int = PARTY_BASE, max_slots: int = PARTY_MAX_SLOTS) -> list[str]:
        newly_purified = self.tracker.poll(block_base, party_base, max_slots)
        newly_crossed: list[str] = []
        for _ in newly_purified:
            if self.total_purified >= PURIFICATION_LOCATION_COUNT:
                break  # capped -- see class docstring
            self.total_purified += 1
            newly_crossed.append(purification_location_name(self.total_purified))
        return newly_crossed


def get_owned_species_snapshot(
    block_base: int,
    party_base: int = PARTY_BASE,
    box_slots_to_check: list[int] | None = None,
) -> set[int]:
    """Combines the confirmed-safe party read with an OPTIONAL, explicit list of box slot indices to
    best-effort check (see `read_box_slot_species`'s caveat -- deliberately NOT "all 386 slots" by default;
    pass box_slots_to_check=None, the default, to skip box reading entirely and stay on the confirmed-solid
    party-only data source). Returns the set of National Dex #s currently observed across whichever sources
    were checked."""
    owned = set(read_party_species(party_base))
    if box_slots_to_check:
        for slot_index in box_slots_to_check:
            dex_number = read_box_slot_species(block_base, slot_index)
            if dex_number is not None:
                owned.add(dex_number)
    return owned


@dataclass
class SpeciesTracker:
    """Tracks which species have been seen owned across polls and reports newly-seen ones exactly once each
    -- the actual "detect a new species -> this is a location check" logic the player asked for. Does NOT
    itself send anything to an AP server (see the module docstring's CommonClient-integration gap); `poll()`
    just tells the caller which `SPECIES_LOCATION_TO_DEX` location names just became newly justified, and the
    caller decides what to do with that (e.g. call the not-yet-written AP `LocationChecks` send).

    Usage sketch (once CommonClient integration exists):
        tracker = SpeciesTracker()
        while True:
            newly_caught = tracker.poll(block_base)  # party-only by default, see get_owned_species_snapshot
            for location_name in newly_caught:
                ...send a LocationChecks packet for location_name...
            time.sleep(POLL_INTERVAL_SECONDS)
    """

    seen_dex_numbers: set[int] = None  # type: ignore[assignment]  # set to a fresh set() in __post_init__

    def __post_init__(self) -> None:
        if self.seen_dex_numbers is None:
            self.seen_dex_numbers = set()

    def poll(
        self,
        block_base: int,
        party_base: int = PARTY_BASE,
        box_slots_to_check: list[int] | None = None,
    ) -> list[str]:
        """Takes a fresh snapshot, diffs it against everything seen on a previous poll, and returns the AP
        location names (`"Catch - {species}"`, via species.py) for whatever's newly seen this call. Updates
        internal state so each species is only ever reported once per tracker instance, no matter how many
        times it's re-observed on later polls."""
        location_name_for_species = _load_location_name_for_species()
        current = get_owned_species_snapshot(block_base, party_base, box_slots_to_check)
        newly_seen = current - self.seen_dex_numbers
        self.seen_dex_numbers |= newly_seen
        return [location_name_for_species(dex_number) for dex_number in sorted(newly_seen)]


def _load_location_name_for_species():
    """Loads `location_name_for_species` straight from pokemon_xd/species.py by file path, deliberately NOT
    via a normal `from pokemon_xd.species import ...`/`import pokemon_xd.species` -- either of those runs
    `pokemon_xd/__init__.py` first (it's a package), which pulls in the whole Archipelago-dependent world
    stack (`Options`, `worlds.AutoWorld`, ...) just to reach one small, dependency-free lookup table. species.py
    itself imports nothing beyond the standard library, so it's safe to load standalone this way -- keeping
    this file's own promise (see module docstring) that it works without Archipelago/the full apworld package
    installed. Re-loads on every call rather than caching at import time, since this is only ever called from
    an already-infrequent per-poll path, not a hot loop."""
    import importlib.util
    from pathlib import Path

    species_path = Path(__file__).resolve().parent / "pokemon_xd" / "species.py"
    spec = importlib.util.spec_from_file_location("_pokemon_xd_species_standalone", species_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.location_name_for_species


# ----------------------------------------------------------------------------------------------------------
# Manual smoke test -- run this file directly to sanity-check hooking + base resolution + pocket contents
# against a real running game, independent of any AP server. This is test tooling, not the client itself.
# ----------------------------------------------------------------------------------------------------------

def _describe_pocket(name: str, slots: list[BagSlot]) -> None:
    owned = [s for s in slots if not s.empty]
    print(f"  {name}: {len(owned)}/{len(slots)} slots used")
    for s in owned:
        print(f"    [{s.index}] item_id={s.item_id} qty={s.quantity} @ {hex(s.address)}")


def main() -> None:
    import sys

    if len(sys.argv) > 1:
        landmark = sys.argv[1]
    else:
        # No hardcoded default -- see TRAINER_NAME_LANDMARK's docstring for why guessing a name doesn't work.
        # For this manual smoke test only (a real client gets this from its own AP slot name), just ask.
        landmark = input("In-game trainer name (must match exactly, case included): ").strip()

    print("Hooking to Dolphin...")
    if not hook():
        print("Failed to hook -- is Dolphin running with the game loaded? See pokemon-xd-live-bridge-notes.md "
              "for known hooking pitfalls (Store Python / AppContainer sandboxing, stuck hook state, etc.)")
        return
    print(f"Hooked. Resolving player-state block base for trainer name {landmark!r} "
          "(one-time full-memory scan, may take a few seconds)...")
    base = resolve_block_base(landmark)
    if base is None:
        print(f"No occurrence of {landmark!r} validated as a real player-state block -- not in-game yet, the "
              "in-game trainer name doesn't actually match, or XD's name-entry screen altered it. See "
              "resolve_block_base's docstring.")
        return
    print(f"Resolved block base: {hex(base)}")
    print(f"Money: {read_money(base)}")
    _describe_pocket("Items", read_pocket(base + ITEMS_POCKET_OFFSET, ITEMS_POCKET_MAX_SLOTS))
    _describe_pocket("Poke Balls", read_pocket(base + POKEBALL_POCKET_OFFSET, POKEBALL_POCKET_MAX_SLOTS))
    _describe_pocket("Key Items", read_pocket(base + KEY_ITEMS_OFFSET, KEY_ITEMS_MAX_SLOTS))

    party_dex_numbers = read_party_species(PARTY_BASE)
    print(f"Party ({len(party_dex_numbers)} species, confirmed-safe live source): {party_dex_numbers}")
    print(
        "PC box slots NOT scanned here -- box-slot reading is provisional/best-effort only "
        "(see read_box_slot_species's docstring); call it explicitly with a known-displayed slot index "
        "if you want to sanity-check it against what's actually on screen right now."
    )


if __name__ == "__main__":
    main()
