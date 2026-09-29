"""ADDENDUM 239 (2026-09-15) -- live, in-RAM item DESCRIPTIONS, so a shop line says what it will send.

ADDENDUM 234 shipped the name half. Descriptions are not in `common_rel`: `Items.cs` resolves a name id
(entry +0x10) through CommonRelStringTable but a description id (entry +0x14) through a separate
StringTable -- for XD/US, `pocket_menu.fsys` -> a `.msg` table. Everything below is measured against three
real 24 MB MEM1 dumps taken with a shop menu open (`dump_gateon_shopmenu_20260915.bin`,
`agate_shopmenu_20260915.bin`, `reboot_shopmenu_20260915.bin`).

  * The magic `\\x02GUS` at +0x04 occurs EXACTLY ONCE in all 24 MB, in every dump, which is what makes
    locating the table at runtime a search rather than a guess.
  * Header +0x10 is a 5331 scalar that is NOT the entry count (0x18 + 5331*8 runs past the string data) and
    +0x14 is 0x8E3C; neither is needed. The pair table at +0x18 is SELF-TERMINATING, running up to the
    smallest string offset any pair names, 0x1248 here. 582 pairs in three id blocks: 10001-10345 (item
    descriptions), 15001-15122, 50001-50115.
  * Description id = 10000 + (name id - 5000): item 148's name id is 5115 (RAZZ BERRY) so its description id
    is 10115. `10000 + item_id` is WRONG and looks right for a while -- 10001 is Master Ball and 10013 is
    Potion, but 10148 is Soothe Bell, not Razz Berry.
  * Per-entry OFFSETS are identical in all three dumps; only the BASE moves, seen at 0x809CECC0, 0x8099DC60,
    0x80D81B60 and 0x809AECA0. Every u32 in MEM1 holding the base was searched in all three and none holds
    it twice, so 0x809E3288 (logged as a pointer slot in the first live test) was session state, as is the
    header's own +0x0C. Hence constants below for the offsets, and a search for the base.

The table is not always resident: `reboot_phenac.bin`, `gateon_indoors.bin` and
`dump_gateon_shop_20260915.bin` (standing in a shop, menu closed) hold no magic, while
`shop_closed_20260915.bin`, taken just after closing the menu, still does. It loads on menu open, lingers
briefly, and is RELOADED FROM DISC on every open, which wipes any edit -- so a write must happen while the
menu is open and be redone each time the table reappears, unlike the name rename, which writes on a room
change before any menu exists. `ram_client.ItemDescriptionWriter` is built around that.

Budgets are per entry and in BYTES: an entry runs from its own offset to the next offset in sorted order,
and all twenty shop berries have 88 (86 of content plus the 2-byte terminator). Never write outside
`[offset, offset + budget)` -- the first live test did, and replaced the cancel button's text. Line breaks
are `FF FF 00`, THREE bytes, an odd length that breaks 2-byte alignment for everything after it; vanilla
descriptions are three lines of roughly 18-20 characters, and `wrap_description` budgets in bytes so a
break costs its real 3.
"""
from __future__ import annotations

import struct

MSG_MAGIC = b"\x02GUS"
MSG_MAGIC_OFFSET = 0x04
MSG_PAIR_TABLE_OFFSET = 0x18
MSG_PAIR_SIZE = 8

STRING_TERMINATOR = b"\x00\x00"
LINE_BREAK = b"\xff\xff\x00"
LINE_BREAK_BYTES = len(LINE_BREAK)

# The window the table has ever been seen in, widened on both sides. Orders the search only --
# `find_table_base` always falls back to the whole region, because four observations are not a bound.
LIKELY_BASE_LOW = 0x80900000
LIKELY_BASE_HIGH = 0x80E00000
MEM1_START = 0x80000000
MEM1_END = 0x81800000

# ADDENDUM 352: the same window, measured instead of estimated, because shop descriptions took too long to
# update. `MSG_MAGIC` was searched across all 163 full MEM1 dumps in the corpus; the table is resident in 18
# of them, exactly once each, at 12 distinct bases:
#
#     0x80946140  0x80989BA0 (x2)  0x8098C0C0  0x8098E220  0x8099DC60  0x809AECA0 (x4)
#     0x809CECC0  0x809FBE60  0x80A35180  0x80D3B4C0 (x2)  0x80D81B60  0x80DCB500 (x2)
#
# Two clusters with nothing between them, which one 5 MB window could not express: eleven in
# 0x8094xxxx-0x80A3xxxx, five in 0x80D3xxxx-0x80DCxxxx. Searching those first is 26 chunks instead of 80,
# which fits one scan slice. Still an ORDERING, never a bound -- each band is followed by the rest of the
# old window and then the rest of MEM1.
MEASURED_BAND_LOW_START = 0x80940000
MEASURED_BAND_LOW_END = 0x80A40000
MEASURED_BAND_HIGH_START = 0x80D30000
MEASURED_BAND_HIGH_END = 0x80DD0000

# {game_item_id: (offset of its description entry within the table, that entry's byte budget, description id)}
# Read out of the three shop-menu dumps -- identical in all three -- by resolving each item's own +0x14 field
# in the Items table and looking that id up in the pair table. NOT computed as 10000 + item_id.
ITEM_DESCRIPTION_ENTRIES: "dict[int, tuple[int, int, int]]" = {
    # --- shop berries (items.USELESS_BERRY_IDS) -- all 88 bytes ---
    148: (0x003B0B, 88, 10115),
    149: (0x003B63, 88, 10116),
    150: (0x003BBB, 88, 10117),
    151: (0x003C13, 88, 10118),
    152: (0x003C6B, 88, 10119),
    153: (0x003CC3, 88, 10120),
    154: (0x003D1B, 88, 10121),
    155: (0x003D73, 88, 10122),
    156: (0x003DCB, 88, 10123),
    157: (0x003E23, 88, 10124),
    158: (0x003E7B, 88, 10125),
    159: (0x003ED3, 88, 10126),
    160: (0x003F2B, 88, 10127),
    162: (0x003FDB, 88, 10129),
    163: (0x004033, 88, 10130),
    164: (0x00408B, 88, 10131),
    165: (0x0040E3, 88, 10132),
    166: (0x00413B, 88, 10133),
    167: (0x004193, 88, 10134),
    168: (0x0041EB, 88, 10135),
    # --- chest berries -- measured in the same pass so a chest-side follow-up needs no second one ---
    161: (0x003F83, 88, 10128),
    169: (0x004243, 90, 10136),
    170: (0x00429D, 86, 10137),
    171: (0x0042F3, 90, 10138),
    172: (0x00434D, 90, 10139),
    173: (0x0043A7, 114, 10140),
    174: (0x004419, 104, 10141),
}

# The smallest budget across the SHOP berries -- the ceiling for any text that must work on all twenty.
SHOP_BERRY_DESCRIPTION_BUDGET = 88


def entry_offset(game_item_id: int) -> "int | None":
    entry = ITEM_DESCRIPTION_ENTRIES.get(game_item_id)
    return None if entry is None else entry[0]


def budget_bytes(game_item_id: int) -> "int | None":
    entry = ITEM_DESCRIPTION_ENTRIES.get(game_item_id)
    return None if entry is None else entry[1]


def looks_like_table(header: bytes) -> bool:
    """True when `header` (at least MSG_MAGIC_OFFSET + 4 bytes from a candidate base) carries the magic.

    Content-agnostic on purpose: it confirms the table is where we think it is, not what it says. A "does it
    still read the vanilla text" check would pass on a fresh load and fail on every re-verify after a write."""
    return (len(header) >= MSG_MAGIC_OFFSET + len(MSG_MAGIC)
            and header[MSG_MAGIC_OFFSET:MSG_MAGIC_OFFSET + len(MSG_MAGIC)] == MSG_MAGIC)


def search_chunk_for_base(chunk: bytes, chunk_start_address: int) -> "int | None":
    """The address of the table if this chunk contains its magic, else None. `chunk_start_address` is where
    `chunk` begins in MEM1; scanning in chunks keeps a caller on a memory bridge from holding 24 MB."""
    index = chunk.find(MSG_MAGIC)
    while index >= 0:
        base = chunk_start_address + index - MSG_MAGIC_OFFSET
        if base >= MEM1_START:
            return base
        index = chunk.find(MSG_MAGIC, index + 1)
    return None


def parse_pair_table(table_bytes: bytes) -> "list[tuple[int, int]]":
    """[(string id, offset within the table)], read from a copy of the table's head. The pair table is
    SELF-TERMINATING, running from +0x18 up to the smallest offset any pair names -- the only stopping rule,
    since the header's +0x10 scalar is 5331, not the entry count, and trusting it walks into the strings."""
    pairs: "list[tuple[int, int]]" = []
    lowest = 1 << 30
    index = 0
    while MSG_PAIR_TABLE_OFFSET + index * MSG_PAIR_SIZE + MSG_PAIR_SIZE <= min(lowest, len(table_bytes)):
        string_id, offset = struct.unpack_from(
            ">II", table_bytes, MSG_PAIR_TABLE_OFFSET + index * MSG_PAIR_SIZE)
        if not (1 <= string_id < 200_000 and 0x100 < offset < 0x200000):
            break
        pairs.append((string_id, offset))
        lowest = min(lowest, offset)
        index += 1
    return pairs


def budgets_from_pairs(pairs: "list[tuple[int, int]]", table_size: int) -> "dict[int, tuple[int, int]]":
    """{string id: (offset, byte budget)}. A budget is the distance to the next offset in SORTED order; the
    pair list is not sorted by offset, and assuming it was hands two entries each other's space."""
    offsets = sorted({offset for _sid, offset in pairs})
    following = {offset: offsets[i + 1] for i, offset in enumerate(offsets[:-1])}
    following[offsets[-1]] = table_size if offsets else 0
    return {sid: (offset, following[offset] - offset) for sid, offset in pairs}


def encode_lines(lines: "list[str]", budget: int) -> "bytes | None":
    """The exact bytes to write over one entry, or None if they do not fit. Zero-padded to `budget` so the
    entry keeps its length and nothing after it moves; padding goes after the terminator, where the game's
    reader has stopped. Never a byte outside `[offset, offset + budget)`."""
    body = LINE_BREAK.join(line.encode("utf-16-be") for line in lines)
    blob = body + STRING_TERMINATOR
    if len(blob) > budget:
        return None
    return blob + b"\x00" * (budget - len(blob))


# Vanilla's widest line in this table is 19-20 characters ("raises the power of", "GROUND-type moves."), so
# 20 is measured rather than chosen. Separate from the byte budget and both bind: three full 20-character
# lines are 126 bytes against an 86-byte allowance, so real capacity is about 40 characters.
DESCRIPTION_LINE_WIDTH = 20
ELLIPSIS = "..."


def encoded_size(lines: "list[str]") -> int:
    """Exactly what `encode_lines` will produce for these lines, terminator included. A line break is THREE
    bytes, not two; every budget decision goes through here rather than counting characters, because that
    one byte per break is what put AP text over the cancel button the first time."""
    return (sum(len(line) for line in lines) * 2
            + max(0, len(lines) - 1) * LINE_BREAK_BYTES
            + len(STRING_TERMINATOR))


def _split_words(text: str, line_width: int) -> "list[str]":
    """Words, with anything longer than a line hard-split rather than dropped."""
    words: "list[str]" = []
    for word in text.split():
        while len(word) > line_width:
            words.append(word[:line_width])
            word = word[line_width:]
        if word:
            words.append(word)
    return words


def fit_lines(lines: "list[str]", budget: int, line_width: int = DESCRIPTION_LINE_WIDTH,
              force_mark: bool = False) -> "list[str]":
    """Shrink `lines` until `encoded_size` fits `budget`, marking the result if anything was lost. Whole
    lines go from the end first, then the last line a character at a time. The mark matters: a truncated
    item name is fine, a DIFFERENT item's name because the tail was cut is not."""
    out = [line for line in lines if line]
    if not out:
        return []
    lost = force_mark
    while len(out) > 1 and encoded_size(out) > budget:
        out.pop()
        lost = True
    while out and encoded_size(out) > budget:
        if not out[-1]:
            out.pop()
            break
        out[-1] = out[-1][:-1]
        lost = True
    out = [line for line in out if line]
    if lost and out:
        tail = out[-1]
        marked = (tail[:line_width - len(ELLIPSIS)] if len(tail) + len(ELLIPSIS) > line_width else tail)
        out[-1] = marked + ELLIPSIS
        while out and encoded_size(out) > budget:
            out[-1] = out[-1][:-1]
    return [line for line in out if line]


def wrap_description(text: str, budget: int, max_lines: int = 3,
                     line_width: int = DESCRIPTION_LINE_WIDTH) -> "list[str]":
    """Break `text` into at most `max_lines` lines of at most `line_width` characters fitting `budget` BYTES.

    Short text uses fewer lines rather than spreading to fill `max_lines`. Everything that could overrun goes
    through `fit_lines`, so the byte budget is enforced in one place."""
    if budget <= len(STRING_TERMINATOR) or line_width <= 0:
        return []
    words = _split_words(text, line_width)
    if not words:
        return []

    lines: "list[str]" = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if len(candidate) <= line_width:
            current = candidate
            continue
        lines.append(current)
        current = word
        if len(lines) >= max_lines:
            current = ""
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    lines = lines[:max_lines]

    # `fit_lines` may drop more, so it is told whether PACKING already lost words and adds its own.
    return fit_lines(lines, budget, line_width, force_mark=" ".join(lines) != " ".join(words))


def describe_ap_item(item_name: str, player_name: "str | None", budget: int) -> "list[str]":
    """The lines to show for a shop line that will send `item_name` to `player_name`.

    An item for the player themselves gets every line for its own name; one for someone else spends the
    first line on who it is going to, the part a player cannot infer from the shelf. The header is laid out
    first and the name gets what is left, so a long player name eats into the item name rather than pushing
    the entry over budget."""
    if not player_name:
        return wrap_description(item_name, budget, max_lines=3)
    header = f"To {player_name}"[:DESCRIPTION_LINE_WIDTH]
    remaining = budget - encoded_size([header]) - LINE_BREAK_BYTES + len(STRING_TERMINATOR)
    body = wrap_description(item_name, max(0, remaining), max_lines=2)
    return fit_lines([header, *body], budget) if body else fit_lines([header], budget)


# ADDENDUM 283: two lines, because three did not fit. These are the only description lines in the project
# that are CONSTANT rather than composed, so they never met a budget check -- at three lines they measured
# 104 and 92 bytes against a smallest-entry budget of 86, `encode_lines` returned None, and the shelf kept
# its vanilla text. The caller still routes both through `fit_lines`, which turns a future overrun into an
# ellipsis instead of silence; these fit natively so it never fires, and `test_addendum_283` asserts that.
UNKNOWN_DESCRIPTION_LINES = ["Not scouted yet.", "Reconnect to see."]
NO_CHECK_DESCRIPTION_LINES = ["Already bought.", "Sends nothing now."]

#: Every entry in the table, so a constant is measured against the WORST case and not the shop berries alone.
SMALLEST_DESCRIPTION_BUDGET = min(entry[1] for entry in ITEM_DESCRIPTION_ENTRIES.values())
