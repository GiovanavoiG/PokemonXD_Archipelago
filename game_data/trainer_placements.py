"""Per-trainer regions and item gates, generated from the player's filled-in census workbook (232 rows).

`region` and `required_items` are ANDed: a trainer needs its area AND the listed items. `region=None` means
"unknown, filler only" -- 37 rows (36 marked N/A in the workbook, plus index 1, left blank). locations.py still
has to put those on the graph, so it parks them in an always-open region and marks them EXCLUDED.

Workbook free text was normalised three ways: "Cave Spot" -> "Poke Spots" (the three spots are one region
here), "Phenac Colosseum" -> "Phenac City" (what chest_regions.ROOM_TO_REGION already gives room 107), and
LOGIC text -> exact item names, because spelling matters to `state.has`. Six rows name the Elevator Key, which
items.NEVER_SHUFFLED_KEY_ITEM_NAMES keeps out of the pool; rules.py drops it when building rules, and it stays
in the data because the fight really is behind that door.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TrainerPlacement:
    """Where a trainer is, and what is needed on top of getting there.

    region           -- a regions.REGION_NAMES entry, or None for "unknown, filler only"
    required_items   -- held BEYOND reaching the region, ANDed with it, never instead of it
    required_regions -- extra regions that must also be reachable. Only Zook #2 needs it: he is at the Cipher
                        Key Lair exterior but must be fought with Snagem Hideout, which sits later.
    """
    region: "str | None"
    required_items: "tuple[str, ...]" = ()
    required_regions: "tuple[str, ...]" = ()


# GENERATED from pokemon_xd_trainers.xlsx as returned by the player. Do not hand-edit: re-export the workbook.
PLACEMENTS: "dict[int, TrainerPlacement]" = {
    1: TrainerPlacement(None, (), ()),   # Defeat - Hordel
    2: TrainerPlacement('Poke Spots', (), ()),   # Defeat - Miror B. #1
    3: TrainerPlacement(None, (), ()),   # Defeat - Miror B. #2
    4: TrainerPlacement(None, (), ()),   # Defeat - Miror B. #3
    5: TrainerPlacement(None, (), ()),   # Defeat - Miror B. #4
    6: TrainerPlacement(None, (), ()),   # Defeat - Miror B. #5
    7: TrainerPlacement(None, (), ()),   # Defeat - Miror B. #6
    8: TrainerPlacement('Pokemon HQ Lab', (), ()),   # Defeat - Aferd #1
    9: TrainerPlacement('Gateon Port', (), ()),   # Defeat - Zook #1
    10: TrainerPlacement('Gateon Port', (), ()),   # Defeat - Ardos #1
    11: TrainerPlacement('Gateon Port', (), ()),   # Defeat - Berk
    12: TrainerPlacement('Gateon Port', (), ()),   # Defeat - Cyle
    13: TrainerPlacement('Gateon Port', (), ()),   # Defeat - Bost
    14: TrainerPlacement('Gateon Port', (), ()),   # Defeat - Kilen
    15: TrainerPlacement("Kaminko's House", (), ()),   # Defeat - Chobin #1
    16: TrainerPlacement('Gateon Port', (), ()),   # Defeat - Laken #1
    17: TrainerPlacement('Pokemon HQ Lab', (), ()),   # Defeat - Naps #1
    18: TrainerPlacement("Kaminko's House", (), ()),   # Defeat - Chobin #2
    19: TrainerPlacement('Agate Village', (), ()),   # Defeat - Clerr #1
    20: TrainerPlacement('Agate Village', (), ()),   # Defeat - Belish #1
    21: TrainerPlacement('Agate Village', (), ()),   # Defeat - Cida #1
    22: TrainerPlacement('Agate Village', (), ()),   # Defeat - Dosk #1
    23: TrainerPlacement('Agate Village', (), ()),   # Defeat - Hebon #1
    24: TrainerPlacement('Agate Village', (), ()),   # Defeat - Gorps
    25: TrainerPlacement('Agate Village', (), ()),   # Defeat - Jols
    26: TrainerPlacement('Agate Village', (), ()),   # Defeat - Ladi
    27: TrainerPlacement('Agate Village', (), ()),   # Defeat - Cron
    28: TrainerPlacement('Agate Village', (), ()),   # Defeat - Eagun #1
    29: TrainerPlacement('Agate Village', (), ()),   # Defeat - Cida #2
    30: TrainerPlacement('Mt. Battle', (), ()),   # Defeat - Miru
    31: TrainerPlacement('Mt. Battle', (), ()),   # Defeat - Cridel
    32: TrainerPlacement('Mt. Battle', (), ()),   # Defeat - Bardo
    33: TrainerPlacement('Cipher Lab', (), ()),   # Defeat - Resix #1
    34: TrainerPlacement('Cipher Lab', (), ()),   # Defeat - Blusix #1
    35: TrainerPlacement('Cipher Lab', (), ()),   # Defeat - Browsix #1
    36: TrainerPlacement('Cipher Lab', (), ()),   # Defeat - Yellosix #1
    37: TrainerPlacement('Cipher Lab', (), ()),   # Defeat - Purpsix #1
    38: TrainerPlacement('Cipher Lab', (), ()),   # Defeat - Greesix #1
    39: TrainerPlacement('Cipher Lab', (), ()),   # Defeat - Resix #2
    40: TrainerPlacement('Cipher Lab', (), ()),   # Defeat - Blusix #2
    41: TrainerPlacement('Cipher Lab', (), ()),   # Defeat - Browsix #2
    42: TrainerPlacement('Cipher Lab', (), ()),   # Defeat - Yellosix #2
    43: TrainerPlacement('Cipher Lab', (), ()),   # Defeat - Purpsix #2
    44: TrainerPlacement('Cipher Lab', (), ()),   # Defeat - Greesix #2
    45: TrainerPlacement('Cipher Lab', (), ()),   # Defeat - Corla
    46: TrainerPlacement('Cipher Lab', (), ()),   # Defeat - Javion
    47: TrainerPlacement('Cipher Lab', (), ()),   # Defeat - Tekot
    48: TrainerPlacement('Cipher Lab', (), ()),   # Defeat - Mesak
    49: TrainerPlacement('Cipher Lab', (), ()),   # Defeat - Nexir
    50: TrainerPlacement('Cipher Lab', (), ()),   # Defeat - Solox
    51: TrainerPlacement('Cipher Lab', (), ()),   # Defeat - Digor
    52: TrainerPlacement('Cipher Lab', (), ()),   # Defeat - Crink
    53: TrainerPlacement('Cipher Lab', (), ()),   # Defeat - Morbit
    54: TrainerPlacement('Cipher Lab', (), ()),   # Defeat - Meda
    55: TrainerPlacement('Cipher Lab', (), ()),   # Defeat - Elrok
    56: TrainerPlacement('Cipher Lab', (), ()),   # Defeat - Coffy
    57: TrainerPlacement('Cipher Lab', (), ()),   # Defeat - Cabol
    58: TrainerPlacement('Cipher Lab', (), ()),   # Defeat - Nopia
    59: TrainerPlacement('Cipher Lab', (), ()),   # Defeat - Klots
    60: TrainerPlacement('Cipher Lab', ('ID Card',), ()),   # Defeat - Naps #2
    61: TrainerPlacement('Cipher Lab', ('Data ROM', 'ID Card'), ()),   # Defeat - Lovrina #1
    62: TrainerPlacement('Pyrite Town', (), ()),   # Defeat - Cail #1
    63: TrainerPlacement('Pyrite Town', (), ()),   # Defeat - Dobit #1
    64: TrainerPlacement('Pyrite Town', (), ()),   # Defeat - Finol #1
    65: TrainerPlacement('Pyrite Town', (), ()),   # Defeat - Dert #1
    66: TrainerPlacement('Pyrite Town', (), ()),   # Defeat - Raling #1
    67: TrainerPlacement('Pyrite Town', (), ()),   # Defeat - Labet #1
    68: TrainerPlacement('Pyrite Town', (), ()),   # Defeat - Doby #1
    69: TrainerPlacement('Pokemon HQ Lab', (), ()),   # Defeat - Aferd #2
    70: TrainerPlacement('Pokemon HQ Lab', (), ()),   # Defeat - Aferd #3
    71: TrainerPlacement('Gateon Port', (), ()),   # Defeat - Laken #2
    72: TrainerPlacement(None, (), ()),   # Defeat - Miror B. #7
    73: TrainerPlacement('Pyrite Town (ONBS)', ('Data ROM',), ()),   # Defeat - Rett
    74: TrainerPlacement('Pyrite Town (ONBS)', ('Data ROM',), ()),   # Defeat - Mocor
    75: TrainerPlacement('Pyrite Town (ONBS)', ('Data ROM',), ()),   # Defeat - Mesin
    76: TrainerPlacement('Pyrite Town (ONBS)', ('Data ROM',), ()),   # Defeat - Elox
    77: TrainerPlacement('Pyrite Town (ONBS)', ('Data ROM',), ()),   # Defeat - Rixor
    78: TrainerPlacement('Pyrite Town (ONBS)', ('Data ROM',), ()),   # Defeat - Torkin
    79: TrainerPlacement('Pyrite Town (ONBS)', ('Data ROM',), ()),   # Defeat - Dilly
    80: TrainerPlacement('Agate Village', (), ()),   # Defeat - Clerr #2
    81: TrainerPlacement('Agate Village', (), ()),   # Defeat - Belish #2
    82: TrainerPlacement('Agate Village', (), ()),   # Defeat - Dosk #2
    83: TrainerPlacement('Agate Village', (), ()),   # Defeat - Hebon #2
    84: TrainerPlacement('Pyrite Town (ONBS)', ('Data ROM',), ()),   # Defeat - Lobar
    85: TrainerPlacement('Pyrite Town (ONBS)', ('Data ROM',), ()),   # Defeat - Edlos
    86: TrainerPlacement('Pyrite Town (ONBS)', ('Data ROM',), ()),   # Defeat - Feldas
    87: TrainerPlacement('Pyrite Town (ONBS)', ('Data ROM',), ()),   # Defeat - Exol
    88: TrainerPlacement('Phenac City', ('Music Disc', "Mayor's Note"), ()),   # Defeat - Exinn
    89: TrainerPlacement('Phenac City', ('Music Disc', "Mayor's Note"), ()),   # Defeat - Gonrag
    90: TrainerPlacement('Pyrite Town', (), ()),   # Defeat - Cail #2
    91: TrainerPlacement('Phenac City', ('Music Disc', "Mayor's Note"), ()),   # Defeat - Pellim
    92: TrainerPlacement('Phenac City', ('Music Disc', "Mayor's Note"), ()),   # Defeat - Fenton
    93: TrainerPlacement('Phenac City', ('Music Disc', "Mayor's Note"), ()),   # Defeat - Forgs
    94: TrainerPlacement('Phenac City', ('Music Disc', "Mayor's Note"), ()),   # Defeat - Kapen
    95: TrainerPlacement('Phenac City', ('Music Disc', "Mayor's Note"), ()),   # Defeat - Ezoor
    96: TrainerPlacement('Phenac City', ('Music Disc', "Mayor's Note"), ()),   # Defeat - Ertlig
    97: TrainerPlacement('Phenac City', ('Music Disc', "Mayor's Note"), ()),   # Defeat - Greck
    98: TrainerPlacement('Phenac City', ('Music Disc', "Mayor's Note"), ()),   # Defeat - Eloin
    99: TrainerPlacement('Phenac City', ('Music Disc', "Mayor's Note"), ()),   # Defeat - Fasin
    100: TrainerPlacement('Phenac City', ('Music Disc', "Mayor's Note"), ()),   # Defeat - Fostin
    101: TrainerPlacement('Phenac City', ('Music Disc', "Mayor's Note"), ()),   # Defeat - Ezin
    102: TrainerPlacement('Phenac City', ('Music Disc', "Mayor's Note"), ()),   # Defeat - Faltly
    103: TrainerPlacement('Phenac City', ('Music Disc', "Mayor's Note"), ()),   # Defeat - Egrog
    104: TrainerPlacement('Phenac City', ('Music Disc', "Mayor's Note"), ()),   # Defeat - Snattle #1
    105: TrainerPlacement('Phenac City', ('Music Disc', "Mayor's Note"), ()),   # Defeat - Eroll #1
    106: TrainerPlacement('Phenac City', ('Music Disc', "Mayor's Note", 'Elevator Key'), ()),   # Defeat - Equin #1
    107: TrainerPlacement('Pyrite Town', (), ()),   # Defeat - Finol #2
    108: TrainerPlacement('Pyrite Town', (), ()),   # Defeat - Dert #2
    109: TrainerPlacement('Pyrite Town', (), ()),   # Defeat - Raling #2
    110: TrainerPlacement('Pyrite Town', (), ()),   # Defeat - Labet #2
    111: TrainerPlacement('Pyrite Town', (), ()),   # Defeat - Doby #2
    112: TrainerPlacement('Cipher Lab', (), ()),   # Defeat - Resix #3
    113: TrainerPlacement('Cipher Lab', (), ()),   # Defeat - Blusix #3
    114: TrainerPlacement('Cipher Lab', (), ()),   # Defeat - Browsix #3
    115: TrainerPlacement('Cipher Lab', (), ()),   # Defeat - Yellosix #3
    116: TrainerPlacement('Cipher Lab', (), ()),   # Defeat - Purpsix #3
    117: TrainerPlacement('Cipher Lab', (), ()),   # Defeat - Greesix #3
    118: TrainerPlacement('Cipher Lab', (), ()),   # Defeat - Resix #4
    119: TrainerPlacement('Cipher Lab', (), ()),   # Defeat - Blusix #4
    120: TrainerPlacement('Cipher Lab', (), ()),   # Defeat - Browsix #4
    121: TrainerPlacement('Cipher Lab', (), ()),   # Defeat - Yellosix #4
    122: TrainerPlacement('Cipher Lab', (), ()),   # Defeat - Purpsix #4
    123: TrainerPlacement('Cipher Lab', (), ()),   # Defeat - Greesix #4
    124: TrainerPlacement("Kaminko's House", (), ()),   # Defeat - Chobin #3
    125: TrainerPlacement("Kaminko's House", (), ()),   # Defeat - Chobin #4
    126: TrainerPlacement('Pyrite Town', (), ()),   # Defeat - Cail #3
    127: TrainerPlacement("Kaminko's House", (), ()),   # Defeat - Chobin #5
    # Items added, region left at SS Libra: a requirement can only push a check later, so both player
    # statements hold. Only bites with travel randomization, where SS Libra is flown to directly.
    128: TrainerPlacement('SS Libra', ('Music Disc', "Mayor's Note"), ()),   # Defeat - Smarton #1
    129: TrainerPlacement('Phenac City (Post-Sixes)', ('Music Disc', "Mayor's Note", 'Elevator Key'), ()),   # Defeat - Quelor
    130: TrainerPlacement('Phenac City (Post-Sixes)', ('Music Disc', "Mayor's Note", 'Elevator Key'), ()),   # Defeat - Teslor
    131: TrainerPlacement('Phenac City (Post-Sixes)', ('Music Disc', "Mayor's Note", 'Elevator Key'), ()),   # Defeat - Nopel
    132: TrainerPlacement('Phenac City (Post-Sixes)', ('Music Disc', "Mayor's Note", 'Elevator Key'), ()),   # Defeat - Kalus
    133: TrainerPlacement('Phenac City (Post-Sixes)', ('Music Disc', "Mayor's Note", 'Elevator Key'), ()),   # Defeat - Justy
    134: TrainerPlacement('Outskirt Stand', (), ()),   # Defeat - Miror B. #8
    135: TrainerPlacement('Outskirt Stand', (), ()),   # Defeat - Willie #1
    136: TrainerPlacement('Snagem Hideout', (), ()),   # Defeat - Fudlo
    137: TrainerPlacement('Snagem Hideout', (), ()),   # Defeat - Gaply
    138: TrainerPlacement('Snagem Hideout', (), ()),   # Defeat - Jinok
    139: TrainerPlacement('Snagem Hideout', (), ()),   # Defeat - Agrev
    140: TrainerPlacement('Snagem Hideout', (), ()),   # Defeat - Jedo
    141: TrainerPlacement('Snagem Hideout', (), ()),   # Defeat - Golit
    142: TrainerPlacement('Snagem Hideout', (), ()),   # Defeat - Hobble
    143: TrainerPlacement('Cipher Key Lair (exterior)', (), ()),   # Defeat - Biden #1
    144: TrainerPlacement('Snagem Hideout', (), ()),   # Defeat - Wakin
    145: TrainerPlacement('Snagem Hideout', (), ()),   # Defeat - Gonzap
    146: TrainerPlacement('Pokemon HQ Lab', (), ()),   # Defeat - Aferd #4
    147: TrainerPlacement('Cipher Key Lair (exterior)', (), ('Snagem Hideout',)),   # Defeat - Zook #2
    148: TrainerPlacement('Snagem Hideout', (), ()),   # Defeat - Biden #2
    149: TrainerPlacement('Cipher Key Lair', (), ()),   # Defeat - Grezle
    150: TrainerPlacement('Cipher Key Lair', (), ()),   # Defeat - Humah
    151: TrainerPlacement('Cipher Key Lair', (), ()),   # Defeat - Ibsol
    152: TrainerPlacement('Cipher Key Lair', (), ()),   # Defeat - Kollo
    153: TrainerPlacement('Cipher Key Lair', (), ()),   # Defeat - Gorog
    154: TrainerPlacement('Cipher Key Lair', (), ()),   # Defeat - Jelstin
    155: TrainerPlacement('Cipher Key Lair', (), ()),   # Defeat - Lok
    156: TrainerPlacement('Cipher Key Lair', (), ()),   # Defeat - Kleto
    157: TrainerPlacement('Cipher Key Lair', (), ()),   # Defeat - Flipis
    158: TrainerPlacement('Cipher Key Lair', (), ()),   # Defeat - Targ
    159: TrainerPlacement('Cipher Key Lair', (), ()),   # Defeat - Hospel
    160: TrainerPlacement('Cipher Key Lair', (), ()),   # Defeat - Snidle
    161: TrainerPlacement('Cipher Key Lair', (), ()),   # Defeat - Fudler
    162: TrainerPlacement('Cipher Key Lair', (), ()),   # Defeat - Angic
    163: TrainerPlacement('Cipher Key Lair', (), ()),   # Defeat - Acrod
    164: TrainerPlacement('Cipher Key Lair', ('System Lever',), ()),   # Defeat - Smarton #2
    165: TrainerPlacement('Cipher Key Lair', ('System Lever',), ()),   # Defeat - Gorigan #1
    166: TrainerPlacement("Kaminko's House", (), ()),   # Defeat - Chobin #6
    167: TrainerPlacement("Kaminko's House", (), ()),   # Defeat - Chobin #7
    168: TrainerPlacement('Citadark Isle', (), ()),   # Defeat - Abson
    169: TrainerPlacement('Citadark Isle', (), ()),   # Defeat - Haben
    170: TrainerPlacement('Citadark Isle', (), ()),   # Defeat - Furgy
    171: TrainerPlacement('Citadark Isle', (), ()),   # Defeat - Golos
    172: TrainerPlacement('Citadark Isle', (), ()),   # Defeat - Jetsal
    173: TrainerPlacement('Citadark Isle', (), ()),   # Defeat - Lovrina #2
    174: TrainerPlacement('Citadark Isle', (), ()),   # Defeat - Bastil
    175: TrainerPlacement('Citadark Isle', (), ()),   # Defeat - Litnar
    176: TrainerPlacement('Citadark Isle', (), ()),   # Defeat - Grason
    177: TrainerPlacement('Citadark Isle', (), ()),   # Defeat - Grupel
    178: TrainerPlacement('Citadark Isle', (), ()),   # Defeat - Kimly
    179: TrainerPlacement('Citadark Isle', (), ()),   # Defeat - Nalix
    180: TrainerPlacement('Citadark Isle', (), ()),   # Defeat - Ibran
    181: TrainerPlacement('Citadark Isle', (), ()),   # Defeat - Kulig
    182: TrainerPlacement('Citadark Isle', (), ()),   # Defeat - Jargo
    183: TrainerPlacement('Citadark Isle', (), ()),   # Defeat - Kolest
    184: TrainerPlacement('Citadark Isle', (), ()),   # Defeat - Kolin
    185: TrainerPlacement('Citadark Isle', (), ()),   # Defeat - Karbon
    186: TrainerPlacement('Citadark Isle', (), ()),   # Defeat - Petro
    187: TrainerPlacement('Citadark Isle', (), ()),   # Defeat - Jaymi
    188: TrainerPlacement('Citadark Isle', (), ()),   # Defeat - Gromlet
    189: TrainerPlacement('Citadark Isle', (), ()),   # Defeat - Geftal
    190: TrainerPlacement('Citadark Isle', (), ()),   # Defeat - Leden
    191: TrainerPlacement('Citadark Isle', (), ()),   # Defeat - Snattle #2
    192: TrainerPlacement('Citadark Isle', (), ()),   # Defeat - Kleef
    193: TrainerPlacement('Citadark Isle', (), ()),   # Defeat - Ardos #2
    194: TrainerPlacement('Citadark Isle', (), ()),   # Defeat - Gorigan #2
    195: TrainerPlacement('Citadark Isle', (), ()),   # Defeat - Kolax
    196: TrainerPlacement('Citadark Isle', (), ()),   # Defeat - Eldes
    197: TrainerPlacement('Citadark Isle', (), ()),   # Defeat - Kaller
    198: TrainerPlacement('Citadark Isle', (), ()),   # Defeat - Loket
    199: TrainerPlacement('Citadark Isle', (), ()),   # Defeat - Greevil #1
    200: TrainerPlacement('Citadark Isle', (), ()),   # Defeat - Greevil #2
    201: TrainerPlacement('Citadark Isle', (), ()),   # Defeat - Greevil #3
    202: TrainerPlacement('Gateon Port', (), ()),   # Defeat - Laken #3
    203: TrainerPlacement(None, (), ()),   # Defeat - Resix #5
    204: TrainerPlacement(None, (), ()),   # Defeat - Blusix #5
    205: TrainerPlacement(None, (), ()),   # Defeat - Browsix #5
    206: TrainerPlacement(None, (), ()),   # Defeat - Yellosix #5
    207: TrainerPlacement(None, (), ()),   # Defeat - Purpsix #5
    208: TrainerPlacement(None, (), ()),   # Defeat - Greesix #5
    209: TrainerPlacement(None, (), ()),   # Defeat - Resix #6
    210: TrainerPlacement(None, (), ()),   # Defeat - Blusix #6
    211: TrainerPlacement(None, (), ()),   # Defeat - Browsix #6
    212: TrainerPlacement(None, (), ()),   # Defeat - Yellosix #6
    213: TrainerPlacement(None, (), ()),   # Defeat - Purpsix #6
    214: TrainerPlacement(None, (), ()),   # Defeat - Greesix #6
    215: TrainerPlacement(None, (), ()),   # Defeat - Cail #4
    216: TrainerPlacement(None, (), ()),   # Defeat - Finol #3
    217: TrainerPlacement(None, (), ()),   # Defeat - Dert #3
    218: TrainerPlacement(None, (), ()),   # Defeat - Raling #3
    219: TrainerPlacement(None, (), ()),   # Defeat - Labet #3
    220: TrainerPlacement(None, (), ()),   # Defeat - Doby #3
    221: TrainerPlacement(None, (), ()),   # Defeat - Miror B. #9
    222: TrainerPlacement(None, (), ()),   # Defeat - Eagun #2
    223: TrainerPlacement(None, (), ()),   # Defeat - Aferd #5
    224: TrainerPlacement(None, (), ()),   # Defeat - Eroll #2
    225: TrainerPlacement(None, (), ()),   # Defeat - Equin #2
    226: TrainerPlacement(None, (), ()),   # Defeat - Willie #2
    227: TrainerPlacement(None, (), ()),   # Defeat - Cida #3
    228: TrainerPlacement(None, (), ()),   # Defeat - Clerr #3
    229: TrainerPlacement(None, (), ()),   # Defeat - Belish #3
    230: TrainerPlacement(None, (), ()),   # Defeat - Dosk #3
    231: TrainerPlacement(None, (), ()),   # Defeat - Hebon #3
    232: TrainerPlacement(None, (), ()),   # Defeat - Dobit #2
}


# The workbook has the two Biden rows the wrong way round, and deck order is the measurement: 143 (Biden #1)
# sits between Hobble and Wakin, all trainer_class 25 (Team Snagem) at levels 26-32; 148 (Biden #2) sits beside
# Zook #2 just before the Key Lair interior. Overridden rather than edited in place because PLACEMENTS is
# generated; the asserts reject an override naming a missing row, a region-less row, or an unchanged region.
PLACEMENT_REGION_OVERRIDES: "dict[int, str]" = {
    143: 'Snagem Hideout',               # Defeat - Biden #1 (player + deck order, 2026-09-23)
    148: 'Cipher Key Lair (exterior)',   # Defeat - Biden #2, beside Zook #2 on the post-Snagem return
}

for _index, _region in PLACEMENT_REGION_OVERRIDES.items():
    assert _index in PLACEMENTS, f"placement override names trainer {_index}, which is not in the roster"
    assert PLACEMENTS[_index].region is not None, (
        f"placement override names trainer {_index}, which the workbook left region-less -- a region-less row "
        "is filler-only by design and giving it one here would bypass that decision rather than correct it"
    )
    assert PLACEMENTS[_index].region != _region, (
        f"placement override for trainer {_index} names the region the workbook already gives it -- an "
        "override that changes nothing reads as a correction and is not one (ADDENDUM 247's dead-rule rule)"
    )
    PLACEMENTS[_index] = TrainerPlacement(
        _region, PLACEMENTS[_index].required_items, PLACEMENTS[_index].required_regions,
    )
del _index, _region


FILLER_ONLY_INDICES: "frozenset[int]" = frozenset(
    index for index, placement in PLACEMENTS.items() if placement.region is None
)

PLACED_INDICES: "frozenset[int]" = frozenset(
    index for index, placement in PLACEMENTS.items() if placement.region is not None
)

REGIONS_WITH_TRAINERS: "frozenset[str]" = frozenset(
    placement.region for placement in PLACEMENTS.values() if placement.region is not None
)


def placement_for(index: int) -> "TrainerPlacement | None":
    return PLACEMENTS.get(index)


def region_for(index: int) -> "str | None":
    placement = PLACEMENTS.get(index)
    return None if placement is None else placement.region


def trainer_count_by_region() -> "dict[str, int]":
    """Trainers per region, for rules.py's cumulative "Defeat N Trainers" weights.

    Region-less rows are not counted here; rules.py deliberately attributes them to the LAST region."""
    counts: "dict[str, int]" = {}
    for placement in PLACEMENTS.values():
        if placement.region is not None:
            counts[placement.region] = counts.get(placement.region, 0) + 1
    return counts


assert len(PLACEMENTS) == 232, f"the roster is 232 trainers; got {len(PLACEMENTS)}"
assert sorted(PLACEMENTS) == list(range(1, 233)), "trainer indices must be a contiguous 1..232"
