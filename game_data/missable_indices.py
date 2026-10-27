"""The list of permanently-missable trainer fights, and nothing else.

ADDENDUM 401: split out of `missable_trainers.py` so `trainer_roster.py` can read it. `trainer_roster` needs the
list to retire the missable trainers' numbered fights from its dispatch queue, and `missable_trainers` cannot be
imported from there -- its module-level census checks import `trainer_roster` back, so the import would land on a
half-built module. This file imports nothing, so anything can import it. `missable_trainers` re-exports the name
unchanged, so every existing reader keeps working and there is still exactly one copy of the list.
"""
from __future__ import annotations

# Index 8 (Aferd 1) is also in `real_trainer_data.PERMANENTLY_EXCLUDED_TRAINER_INDICES`, but for another
# reason: that set governs what the ISO patcher does TO a trainer, this one what AP may place ON the check.
# Index 51 (Digor) has total_with_name 1, so there is no later encounter to fall back on.
MISSABLE_TRAINER_INDICES: "frozenset[int]" = frozenset({
    # From the compiled list, resolved against trainer_roster.py's 232 trainers. "Name 1" means
    # occurrence 1 only, so Dosk 2/3 stay eligible; Biden is listed twice, hence both its occurrences.
    # One correction, confirmed 2026-09-13: the six "Sixes" are RESIX, BLUSIX, BROWSIX, YELLOSIX, PURPSIX,
    # GREESIX (occurrence-1 indices 33-38). The list said "redsix" (no such trainer), GREESIX twice, no BROWSIX.
    8,    # Aferd 1
    51,   # Digor
    23,   # Hebon 1
    9,    # Zook 1
    # ADDENDUM 409: the Sixes' #1 is at Cipher Lab and their #2 at Phenac (missable, behind the disc and the
    # note). The Sixes' missable fight is the Phenac one, #2 (39-44); #1 (33-38) at the lab is not.
    39, 40, 41, 42, 43, 44,   # Resix 2, Blusix 2, Browsix 2, Yellosix 2, Purpsix 2, Greesix 2
    16,   # Laken 1
    53,   # Morbit
    54,   # Meda
    55,   # Elrok
    56,   # Coffy
    58,   # Nopia
    64,   # Finol 1
    74,   # Mocor
    76,   # Elox
    77,   # Rixor
    79,   # Dilly
    85,   # Edlos
    94,   # Kapen
    92,   # Fenton
    91,   # Pellim
    93,   # Forgs
    95,   # Ezoor
    96,   # Ertlig
    105,  # Eroll 1
    106,  # Equin 1
    148,  # Biden 2
    151,  # Ibsol
    152,  # Kollo
    154,  # Jelstin
    159,  # Hospel
    161,  # Fudler
    # ADDENDUM 460: Bost, Dosk, Cida, Labet, Raling, Doby, Willie and everyone in Snagem are unmissable.
    # Removed from this list: Bost (13), Cida 1 (21), Dosk 1 (22), Raling 1 (66), Labet 1 (67), Doby 1 (68),
    # Willie 1 (135), and the Snagem Hideout fights Fudlo (136), Gaply (137), Jinok (138), Golit (141),
    # Hobble (142), Biden 1 (143). See CONFIRMED_UNMISSABLE below.
    # ADDENDUM 440 (from Bulbapedia's Phenac "Invasion" table): these trainers are excluded, marked missable, sent
    # when Phenac is done, and never given Shadows. The four Prestige Precept Center trainers
    # ahead of Justy -- see PHENAC_INVASION_INDICES below.
    129,  # Quelor
    130,  # Teslor
    131,  # Nopel
    132,  # Kalus
    # ADDENDUM 441: Justy is excluded too. The PRE Gym's leader right after them. Mandatory
    # (0x46 -> 0x47), so nothing can walk past him -- listed here for the same treatment: excluded, never a Shadow
    # host, and sent at Snattle's defeat as a backstop, a step after the game's own 0x47.
    133,  # Justy
})

# ADDENDUM 440: the Phenac invasion trainers. Missable (above), so excluded and never a Shadow host
# (`missable_trainers.UNREDOABLE_TRAINER_INDICES`); auto-sent when Snattle falls (`missable_autosend.cap_for`).
PHENAC_INVASION_INDICES: "frozenset[int]" = frozenset({129, 130, 131, 132, 133})   # 441: + Justy
assert PHENAC_INVASION_INDICES <= MISSABLE_TRAINER_INDICES


# ADDENDUM 436. The two fights where the player doesn't act are Ardos vs Zook in Gateon and Zook vs Biden in the
# Key Lair. Those fights DO NOT send a check, the #1/#2 checks are removed, and the checks for Ardos, Zook and Biden
# send upon their defeat in Citadark, the Key Lair and Snagem respectively.
#
# Deck rows of the fights the player only WATCHES: Zook #1 and Ardos #1 at Gateon Port fight each other, and Biden #2
# is the team Zook beats at the Cipher Key Lair. The client recognises a win against one of these by its team
# fingerprint and ignores it outright -- no check, no (Any), no tally (`TrainerBattleDefeatTracker`).
NON_PLAYER_FIGHT_INDICES: "frozenset[int]" = frozenset({
    9,     # Zook #1, Gateon Port -- Ardos vs Zook
    10,    # Ardos #1, Gateon Port -- Ardos vs Zook
    148,   # Biden #2, Cipher Key Lair (exterior) -- Zook vs Biden
})

# The one fight per surname that sends that trainer's single check, `Defeat X (Any)`. Their numbered checks are gone.
SINGLE_CHECK_FIGHTS: "dict[str, int]" = {
    "ARDOS": 193,   # Citadark Isle
    "ZOOK": 147,    # Cipher Key Lair (exterior)
    "BIDEN": 143,   # Snagem Hideout
}

# ADDENDUM 436: rows the workbook's `Missable?` column (and the list above) mark that are NOT missable with this
# world's settings -- Biden is not missable in Snagem with the current settings.
# Both lists stay as compiled -- they still fence the row from progression and Shadow hosting, which
# costs nothing -- and the readers that decide "can this CHECK be lost" subtract these: the (Any) anchor
# (`repeatable_trainers`) and the auto-send schedule (`missable_autosend`).
# ADDENDUM 460: the "unmissable" set -- each is fought once, and none can be walked past with this
# world's settings. They come off the list above, the workbook's `Missable?` column is overruled for them, and they
# may host a generated or relocated Shadow (each is its own deck row, never re-fought: a rematch is a later row).
CONFIRMED_UNMISSABLE: "frozenset[int]" = frozenset({
    13,    # Bost, Gateon Port
    21,    # Cida #1, Agate Village
    22,    # Dosk #1, Agate Village
    66,    # Raling #1, Pyrite Town
    67,    # Labet #1, Pyrite Town
    68,    # Doby #1, Pyrite Town
    135,   # Willie #1, Outskirt Stand
    136, 137, 138, 141, 142,   # Fudlo, Gaply, Jinok, Golit, Hobble -- Snagem Hideout
    143,   # Biden #1, Snagem Hideout (ADDENDUM 436)
})
assert not CONFIRMED_UNMISSABLE & MISSABLE_TRAINER_INDICES

WORKBOOK_MISSABLE_OVERRULED: "frozenset[int]" = frozenset({143}) | CONFIRMED_UNMISSABLE   # 436: Biden #1; 460
