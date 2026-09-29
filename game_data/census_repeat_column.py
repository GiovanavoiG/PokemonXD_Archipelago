"""The `Repeat?` and `Missable?` columns of the player's trainer census workbook, transcribed verbatim.

Generated from `pokemon_xd_trainers.xlsx`, sheet "Trainers", one entry per data row in index order, read with
openpyxl rather than by hand. The sheet's single `EXAMPLE` row is dropped; the remaining 232 match the roster.
Nothing here is inferred, normalised or corrected, so the fence downstream derives from what the workbook says
rather than from anyone's reading of it. missable_trainers.py asserts these totals back against the sheet.

`Repeat?` values:

    None                  fought once; no repeat question
    "final"               the last occurrence, the one the game lets you re-fight
    "earlier (N of M)"    occurrence N of M and not the last, so it is gone once the story moves past it

An "earlier" fight is missable by construction, and the two columns barely overlap: 88 rows are "earlier", 47
are marked `Missable?`, and only 20 are both. Reading one without the other leaves 68 one-shot fights eligible
for progression items.
"""
from __future__ import annotations

# trainer_index -> (Repeat? cell, Missable? cell was set)
CENSUS_REPEAT_AND_MISSABLE: "dict[int, tuple[str | None, bool]]" = {
       1: (None, False),   # Defeat - Hordel
       2: ('earlier (1 of 9)', False),   # Defeat - Miror B. #1
       3: ('earlier (2 of 9)', False),   # Defeat - Miror B. #2
       4: ('earlier (3 of 9)', False),   # Defeat - Miror B. #3
       5: ('earlier (4 of 9)', False),   # Defeat - Miror B. #4
       6: ('earlier (5 of 9)', False),   # Defeat - Miror B. #5
       7: ('earlier (6 of 9)', False),   # Defeat - Miror B. #6
       8: ('earlier (1 of 5)', True),   # Defeat - Aferd #1
       9: ('earlier (1 of 2)', True),   # Defeat - Zook #1
      10: ('earlier (1 of 2)', False),   # Defeat - Ardos #1
      11: (None, False),   # Defeat - Berk
      12: (None, False),   # Defeat - Cyle
      13: (None, True),   # Defeat - Bost
      14: (None, False),   # Defeat - Kilen
      15: ('earlier (1 of 7)', False),   # Defeat - Chobin #1
      16: ('earlier (1 of 3)', True),   # Defeat - Laken #1
      17: ('earlier (1 of 2)', False),   # Defeat - Naps #1
      18: ('earlier (2 of 7)', False),   # Defeat - Chobin #2
      19: ('earlier (1 of 3)', False),   # Defeat - Clerr #1
      20: ('earlier (1 of 3)', False),   # Defeat - Belish #1
      21: ('earlier (1 of 3)', True),   # Defeat - Cida #1
      22: ('earlier (1 of 3)', True),   # Defeat - Dosk #1
      23: ('earlier (1 of 3)', True),   # Defeat - Hebon #1
      24: (None, False),   # Defeat - Gorps
      25: (None, False),   # Defeat - Jols
      26: (None, False),   # Defeat - Ladi
      27: (None, False),   # Defeat - Cron
      28: ('earlier (1 of 2)', False),   # Defeat - Eagun #1
      29: ('earlier (2 of 3)', False),   # Defeat - Cida #2
      30: (None, False),   # Defeat - Miru
      31: (None, False),   # Defeat - Cridel
      32: (None, False),   # Defeat - Bardo
      33: ('earlier (1 of 6)', True),   # Defeat - Resix #1
      34: ('earlier (1 of 6)', True),   # Defeat - Blusix #1
      35: ('earlier (1 of 6)', True),   # Defeat - Browsix #1
      36: ('earlier (1 of 6)', True),   # Defeat - Yellosix #1
      37: ('earlier (1 of 6)', True),   # Defeat - Purpsix #1
      38: ('earlier (1 of 6)', True),   # Defeat - Greesix #1
      39: ('earlier (2 of 6)', False),   # Defeat - Resix #2
      40: ('earlier (2 of 6)', False),   # Defeat - Blusix #2
      41: ('earlier (2 of 6)', False),   # Defeat - Browsix #2
      42: ('earlier (2 of 6)', False),   # Defeat - Yellosix #2
      43: ('earlier (2 of 6)', False),   # Defeat - Purpsix #2
      44: ('earlier (2 of 6)', False),   # Defeat - Greesix #2
      45: (None, False),   # Defeat - Corla
      46: (None, False),   # Defeat - Javion
      47: (None, False),   # Defeat - Tekot
      48: (None, False),   # Defeat - Mesak
      49: (None, False),   # Defeat - Nexir
      50: (None, False),   # Defeat - Solox
      51: (None, True),   # Defeat - Digor
      52: (None, False),   # Defeat - Crink
      53: (None, True),   # Defeat - Morbit
      54: (None, True),   # Defeat - Meda
      55: (None, True),   # Defeat - Elrok
      56: (None, True),   # Defeat - Coffy
      57: (None, False),   # Defeat - Cabol
      58: (None, True),   # Defeat - Nopia
      59: (None, False),   # Defeat - Klots
      60: ('final', False),   # Defeat - Naps #2
      61: ('earlier (1 of 2)', False),   # Defeat - Lovrina #1
      62: ('earlier (1 of 4)', False),   # Defeat - Cail #1
      63: ('earlier (1 of 2)', False),   # Defeat - Dobit #1
      64: ('earlier (1 of 3)', True),   # Defeat - Finol #1
      65: ('earlier (1 of 3)', False),   # Defeat - Dert #1
      66: ('earlier (1 of 3)', True),   # Defeat - Raling #1
      67: ('earlier (1 of 3)', True),   # Defeat - Labet #1
      68: ('earlier (1 of 3)', True),   # Defeat - Doby #1
      69: ('earlier (2 of 5)', False),   # Defeat - Aferd #2
      70: ('earlier (3 of 5)', False),   # Defeat - Aferd #3
      71: ('earlier (2 of 3)', False),   # Defeat - Laken #2
      72: ('earlier (7 of 9)', False),   # Defeat - Miror B. #7
      73: (None, False),   # Defeat - Rett
      74: (None, True),   # Defeat - Mocor
      75: (None, False),   # Defeat - Mesin
      76: (None, True),   # Defeat - Elox
      77: (None, True),   # Defeat - Rixor
      78: (None, False),   # Defeat - Torkin
      79: (None, True),   # Defeat - Dilly
      80: ('earlier (2 of 3)', False),   # Defeat - Clerr #2
      81: ('earlier (2 of 3)', False),   # Defeat - Belish #2
      82: ('earlier (2 of 3)', False),   # Defeat - Dosk #2
      83: ('earlier (2 of 3)', False),   # Defeat - Hebon #2
      84: (None, False),   # Defeat - Lobar
      85: (None, True),   # Defeat - Edlos
      86: (None, False),   # Defeat - Feldas
      87: (None, False),   # Defeat - Exol
      88: (None, False),   # Defeat - Exinn
      89: (None, False),   # Defeat - Gonrag
      90: ('earlier (2 of 4)', False),   # Defeat - Cail #2
      91: (None, True),   # Defeat - Pellim
      92: (None, True),   # Defeat - Fenton
      93: (None, True),   # Defeat - Forgs
      94: (None, True),   # Defeat - Kapen
      95: (None, True),   # Defeat - Ezoor
      96: (None, True),   # Defeat - Ertlig
      97: (None, False),   # Defeat - Greck
      98: (None, False),   # Defeat - Eloin
      99: (None, False),   # Defeat - Fasin
     100: (None, False),   # Defeat - Fostin
     101: (None, False),   # Defeat - Ezin
     102: (None, False),   # Defeat - Faltly
     103: (None, False),   # Defeat - Egrog
     104: ('earlier (1 of 2)', False),   # Defeat - Snattle #1
     105: ('earlier (1 of 2)', True),   # Defeat - Eroll #1
     106: ('earlier (1 of 2)', True),   # Defeat - Equin #1
     107: ('earlier (2 of 3)', False),   # Defeat - Finol #2
     108: ('earlier (2 of 3)', False),   # Defeat - Dert #2
     109: ('earlier (2 of 3)', False),   # Defeat - Raling #2
     110: ('earlier (2 of 3)', False),   # Defeat - Labet #2
     111: ('earlier (2 of 3)', False),   # Defeat - Doby #2
     112: ('earlier (3 of 6)', False),   # Defeat - Resix #3
     113: ('earlier (3 of 6)', False),   # Defeat - Blusix #3
     114: ('earlier (3 of 6)', False),   # Defeat - Browsix #3
     115: ('earlier (3 of 6)', False),   # Defeat - Yellosix #3
     116: ('earlier (3 of 6)', False),   # Defeat - Purpsix #3
     117: ('earlier (3 of 6)', False),   # Defeat - Greesix #3
     118: ('earlier (4 of 6)', False),   # Defeat - Resix #4
     119: ('earlier (4 of 6)', False),   # Defeat - Blusix #4
     120: ('earlier (4 of 6)', False),   # Defeat - Browsix #4
     121: ('earlier (4 of 6)', False),   # Defeat - Yellosix #4
     122: ('earlier (4 of 6)', False),   # Defeat - Purpsix #4
     123: ('earlier (4 of 6)', False),   # Defeat - Greesix #4
     124: ('earlier (3 of 7)', False),   # Defeat - Chobin #3
     125: ('earlier (4 of 7)', False),   # Defeat - Chobin #4
     126: ('earlier (3 of 4)', False),   # Defeat - Cail #3
     127: ('earlier (5 of 7)', False),   # Defeat - Chobin #5
     128: ('earlier (1 of 2)', False),   # Defeat - Smarton #1
     129: (None, False),   # Defeat - Quelor
     130: (None, False),   # Defeat - Teslor
     131: (None, False),   # Defeat - Nopel
     132: (None, False),   # Defeat - Kalus
     133: (None, False),   # Defeat - Justy
     134: ('earlier (8 of 9)', False),   # Defeat - Miror B. #8
     135: ('earlier (1 of 2)', True),   # Defeat - Willie #1
     136: (None, True),   # Defeat - Fudlo
     137: (None, True),   # Defeat - Gaply
     138: (None, True),   # Defeat - Jinok
     139: (None, False),   # Defeat - Agrev
     140: (None, False),   # Defeat - Jedo
     141: (None, True),   # Defeat - Golit
     142: (None, True),   # Defeat - Hobble
     143: ('earlier (1 of 2)', True),   # Defeat - Biden #1
     144: (None, False),   # Defeat - Wakin
     145: (None, False),   # Defeat - Gonzap
     146: ('earlier (4 of 5)', False),   # Defeat - Aferd #4
     147: ('final', False),   # Defeat - Zook #2
     148: ('final', True),   # Defeat - Biden #2
     149: (None, False),   # Defeat - Grezle
     150: (None, False),   # Defeat - Humah
     151: (None, True),   # Defeat - Ibsol
     152: (None, False),   # Defeat - Kollo
     153: (None, False),   # Defeat - Gorog
     154: (None, True),   # Defeat - Jelstin
     155: (None, False),   # Defeat - Lok
     156: (None, False),   # Defeat - Kleto
     157: (None, False),   # Defeat - Flipis
     158: (None, False),   # Defeat - Targ
     159: (None, False),   # Defeat - Hospel
     160: (None, False),   # Defeat - Snidle
     161: (None, True),   # Defeat - Fudler
     162: (None, False),   # Defeat - Angic
     163: (None, False),   # Defeat - Acrod
     164: ('final', False),   # Defeat - Smarton #2
     165: ('earlier (1 of 2)', False),   # Defeat - Gorigan #1
     166: ('earlier (6 of 7)', False),   # Defeat - Chobin #6
     167: ('final', False),   # Defeat - Chobin #7
     168: (None, False),   # Defeat - Abson
     169: (None, False),   # Defeat - Haben
     170: (None, False),   # Defeat - Furgy
     171: (None, False),   # Defeat - Golos
     172: (None, False),   # Defeat - Jetsal
     173: ('final', False),   # Defeat - Lovrina #2
     174: (None, False),   # Defeat - Bastil
     175: (None, False),   # Defeat - Litnar
     176: (None, False),   # Defeat - Grason
     177: (None, False),   # Defeat - Grupel
     178: (None, False),   # Defeat - Kimly
     179: (None, False),   # Defeat - Nalix
     180: (None, False),   # Defeat - Ibran
     181: (None, False),   # Defeat - Kulig
     182: (None, False),   # Defeat - Jargo
     183: (None, False),   # Defeat - Kolest
     184: (None, False),   # Defeat - Kolin
     185: (None, False),   # Defeat - Karbon
     186: (None, False),   # Defeat - Petro
     187: (None, False),   # Defeat - Jaymi
     188: (None, False),   # Defeat - Gromlet
     189: (None, False),   # Defeat - Geftal
     190: (None, False),   # Defeat - Leden
     191: ('final', False),   # Defeat - Snattle #2
     192: (None, False),   # Defeat - Kleef
     193: ('final', False),   # Defeat - Ardos #2
     194: ('final', False),   # Defeat - Gorigan #2
     195: (None, False),   # Defeat - Kolax
     196: (None, False),   # Defeat - Eldes
     197: (None, False),   # Defeat - Kaller
     198: (None, False),   # Defeat - Loket
     199: ('earlier (1 of 3)', False),   # Defeat - Greevil #1
     200: ('earlier (2 of 3)', False),   # Defeat - Greevil #2
     201: ('final', False),   # Defeat - Greevil #3
     202: ('final', False),   # Defeat - Laken #3
     203: ('earlier (5 of 6)', False),   # Defeat - Resix #5
     204: ('earlier (5 of 6)', False),   # Defeat - Blusix #5
     205: ('earlier (5 of 6)', False),   # Defeat - Browsix #5
     206: ('earlier (5 of 6)', False),   # Defeat - Yellosix #5
     207: ('earlier (5 of 6)', False),   # Defeat - Purpsix #5
     208: ('earlier (5 of 6)', False),   # Defeat - Greesix #5
     209: ('final', False),   # Defeat - Resix #6
     210: ('final', False),   # Defeat - Blusix #6
     211: ('final', False),   # Defeat - Browsix #6
     212: ('final', False),   # Defeat - Yellosix #6
     213: ('final', False),   # Defeat - Purpsix #6
     214: ('final', False),   # Defeat - Greesix #6
     215: ('final', False),   # Defeat - Cail #4
     216: ('final', False),   # Defeat - Finol #3
     217: ('final', False),   # Defeat - Dert #3
     218: ('final', False),   # Defeat - Raling #3
     219: ('final', False),   # Defeat - Labet #3
     220: ('final', False),   # Defeat - Doby #3
     221: ('final', False),   # Defeat - Miror B. #9
     222: ('final', False),   # Defeat - Eagun #2
     223: ('final', False),   # Defeat - Aferd #5
     224: ('final', False),   # Defeat - Eroll #2
     225: ('final', False),   # Defeat - Equin #2
     226: ('final', False),   # Defeat - Willie #2
     227: ('final', False),   # Defeat - Cida #3
     228: ('final', False),   # Defeat - Clerr #3
     229: ('final', False),   # Defeat - Belish #3
     230: ('final', False),   # Defeat - Dosk #3
     231: ('final', False),   # Defeat - Hebon #3
     232: ('final', False),   # Defeat - Dobit #2
}

WORKBOOK_ROW_COUNT = 232
WORKBOOK_MISSABLE_COUNT = 47
WORKBOOK_EARLIER_COUNT = 88
WORKBOOK_FINAL_COUNT = 35
WORKBOOK_BLANK_REPEAT_COUNT = 109


def is_a_one_shot_fight(index: int) -> bool:
    """True when the workbook says this occurrence can be permanently walked past. Either column is enough --
    `Missable?` is the player's field note, "earlier (N of M)" is the structural fact."""
    entry = CENSUS_REPEAT_AND_MISSABLE.get(index)
    if entry is None:
        return False
    repeat, missable = entry
    return bool(missable) or (repeat is not None and repeat.startswith("earlier"))
