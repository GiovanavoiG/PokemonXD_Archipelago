"""World-map descriptions show the level of each place's first-visit trainers.

The world map's place texts are one message file, loaded into RAM while the map screen is open. Each entry is the
place name, a line break (0xFFFF then a one-byte parameter, 0x00 for a new line), one or two lines of description,
and a 2-byte terminator:

    PHENAC CITY <FFFF 00> A gorgeous city in the desert that <FFFF 00> overflows with bounteous water. <0000>

The client rewrites, in place, the LAST line of every entry whose name is one of the places below with
"First visit: trainers Lv NN", space-padded to that line's exact length, so nothing moves and no byte outside the line
changes. A line holding a control code (a player's name, say) is left alone, as is a place whose name is "???".
The levels come from the seed (`fill_slot_data`'s `map_place_levels`).
"""
from __future__ import annotations

NEWLINE = b"\xff\xff\x00"
TERMINATOR = b"\x00\x00"

#: In-game place name -> the logic regions whose trainers it averages over.
PLACE_REGIONS: "dict[str, tuple[str, ...]]" = {
    "OUTSKIRT STAND": ("Outskirt Stand",),
    "SNAGEM HIDEOUT": ("Snagem Hideout",),
    "KAMINKO'S HOUSE": ("Kaminko's House", "Kaminko's House (Robo Groudon)"),
    "PHENAC CITY": ("Phenac City", "Phenac City (Mayor's House)", "Phenac City (Post-Sixes)"),
    "PYRITE TOWN": ("Pyrite Town", "Pyrite Town (ONBS)"),
    "AGATE VILLAGE": ("Agate Village", "Relic Forest"),
    "POKéMON HQ LAB": ("Pokemon HQ Lab",),
    "GATEON PORT": ("Gateon Port",),
    "CIPHER LAB": ("Cipher Lab",),
    "MT. BATTLE": ("Mt. Battle",),
    "S.S. LIBRA": ("SS Libra", "SS Libra (stranded)"),
    "REALGAM TOWER": ("Realgam Tower",),
    "CIPHER KEY LAIR": ("Cipher Key Lair", "Cipher Key Lair (exterior)", "Cipher Key Lair (deep)"),
    "CITADARK ISLE": ("Citadark Isle",),
}

#: The UTF-16 bytes the client searches RAM for to find the loaded file.
SEARCH_ANCHOR = "OUTSKIRT STAND".encode("utf-16-be") + NEWLINE


def level_line(level: int, budget: int) -> "str | None":
    """The text for a line `budget` characters long, or None when even the short form does not fit."""
    for text in (f"First visit: trainers Lv {level}", f"First visit: Lv {level}", f"1st visit Lv {level}"):
        if len(text) <= budget:
            return text.ljust(budget)
    return None


def _read_line(data: bytes, at: int) -> "tuple[int, int, bool] | None":
    """(end, next, ends_entry) for the line starting at `at`: `end` is where its text stops, `next` where the next
    line starts, `ends_entry` True at the terminator. None when the line holds any other control code."""
    i = at
    while i + 2 <= len(data):
        pair = data[i:i + 2]
        if pair == TERMINATOR:
            return i, i + 2, True
        if pair == b"\xff\xff":
            if data[i + 2:i + 3] == b"\x00":
                return i, i + 3, False
            return None
        i += 2
    return None


def rewrite(data: bytearray, levels: "dict[str, int]") -> int:
    """Rewrite every listed place's last description line in `data` (a RAM window) in place. Returns the entries
    changed; an entry already showing its level is left as it is."""
    changed = 0
    for name, level in levels.items():
        head = name.encode("utf-16-be") + NEWLINE
        at = data.find(head)
        while at >= 0:
            start = at + len(head)
            lines = []
            pos = start
            ok = True
            while ok:
                read = _read_line(bytes(data), pos)
                if read is None:
                    ok = False
                    break
                end, nxt, last = read
                lines.append((pos, end))
                pos = nxt
                if last or len(lines) > 3:
                    break
            if ok and lines:
                line_start, line_end = lines[-1]
                budget = (line_end - line_start) // 2
                text = level_line(int(level), budget)
                if text is not None:
                    new = text.encode("utf-16-be")
                    if bytes(data[line_start:line_end]) != new:
                        data[line_start:line_end] = new
                        changed += 1
            at = data.find(head, at + 1)
    return changed
