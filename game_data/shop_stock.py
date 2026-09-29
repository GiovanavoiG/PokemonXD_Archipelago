"""What every shop stocks, and when.

`pocket_menu.fsys`'s mart REL holds 21 marts over one shared 184-entry item pool; a mart is a (first, last)
slice of it. Some share a slice outright (9/10/11 are byte-identical, so are 7/20), some are one shop's stock
at different points in the story.

`_simulate_rotation` re-derives what `xd_rel_format.apply_mart_randomization` writes: marts in ascending
index, slots in ascending pool order, excluded ids skipped without consuming a rotation step, shared slices
walked more than once with the last pass winning (191 steps over 166 slots). Checked against the patched pool
dumped from live RAM (`bridge/dumps/agate_shopmenu_20260915.bin`, pool base 0x80500DCE): 166 of 166 agree,
and the assertion at the bottom re-runs it every import. The rotation is global, not per shop, so labels
repeat within a shop and a check has to be (room, berry).
"""
from __future__ import annotations

# mart index -> (first pool slot, last pool slot, vanilla item ids in slot order).
# Read from the real vanilla `pocket_menu.fsys` mart REL (ISO offset 579916224), not transcribed by hand.
VANILLA_MARTS: "dict[int, tuple[int, int, tuple[int, ...]]]" = {
     0: (  0,  11, (21, 23, 24, 298, 302, 303, 304, 305, 308, 313, 321, 326)),
     1: ( 25,  37, (4, 3, 2, 22, 21, 14, 15, 16, 17, 18, 23, 24, 511)),
     2: ( 39,  44, (63, 64, 65, 66, 67, 70)),
     3: ( 46,  55, (22, 23, 24, 73, 74, 75, 76, 77, 78, 79)),
     4: ( 71,  74, (26, 27, 28, 29)),
     5: ( 76,  85, (13, 22, 14, 15, 16, 17, 18, 513, 514, 515)),
     6: (113, 118, (13, 14, 15, 16, 17, 18)),
     7: (150, 153, (30, 31, 32, 33)),
     8: (155, 163, (2, 6, 8, 10, 22, 21, 23, 24, 511)),
     9: (165, 182, (317, 301, 312, 323, 318, 185, 180, 183, 196, 179, 187, 198, 186, 219, 169, 170, 171, 172)),
    10: (165, 182, (317, 301, 312, 323, 318, 185, 180, 183, 196, 179, 187, 198, 186, 219, 169, 170, 171, 172)),
    11: (165, 182, (317, 301, 312, 323, 318, 185, 180, 183, 196, 179, 187, 198, 186, 219, 169, 170, 171, 172)),
    12: ( 87,  97, (4, 13, 22, 14, 15, 16, 17, 18, 513, 514, 515)),
    13: ( 57,  69, (4, 3, 22, 23, 24, 73, 74, 75, 76, 77, 78, 79, 511)),
    14: (120, 131, (4, 3, 13, 22, 14, 15, 16, 17, 18, 23, 24, 511)),
    15: (133, 148, (4, 3, 2, 13, 22, 21, 20, 19, 14, 15, 16, 17, 18, 23, 24, 511)),
    16: ( 13,  15, (535, 536, 537)),
    17: ( 17,  19, (542, 546, 550)),
    18: ( 21,  23, (558, 559, 563)),
    19: ( 99, 111, (4, 3, 13, 22, 14, 15, 16, 17, 18, 513, 514, 515, 511)),
    20: (150, 153, (30, 31, 32, 33)),
}

# Ids the patcher never overwrites: the Poke Snack and the three Agate Scents.
_PRESERVED_ITEM_IDS: "frozenset[int]" = frozenset({511, 513, 514, 515})

# mart index -> the dummy-berry LABEL (1-20, the berry's index in items.USELESS_BERRY_IDS) in each of its
# patchable slots, in shelf order. Verified against live RAM; re-derived by the assertion below.
MART_LABELS: "dict[int, tuple[int, ...]]" = {
     0: (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12),
     1: (13, 14, 15, 16, 17, 18, 19, 20, 1, 2, 3, 4),
     2: (5, 6, 7, 8, 9, 10),
     3: (11, 12, 13, 14, 15, 16, 17, 18, 19, 20),
     4: (1, 2, 3, 4),
     5: (5, 6, 7, 8, 9, 10, 11),
     6: (12, 13, 14, 15, 16, 17),
     7: (8, 9, 10, 11),
     8: (2, 3, 4, 5, 6, 7, 8, 9),
     9: (6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 1, 2, 3),
    10: (6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 1, 2, 3),
    11: (6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 1, 2, 3),
    12: (4, 5, 6, 7, 8, 9, 10, 11),
    13: (12, 13, 14, 15, 16, 17, 18, 19, 20, 1, 2, 3),
    14: (4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14),
    15: (15, 16, 17, 18, 19, 20, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    16: (10, 11, 12),
    17: (13, 14, 15),
    18: (16, 17, 18),
    19: (19, 20, 1, 2, 3, 4, 5, 6, 7),
    20: (8, 9, 10, 11),
}

# Which marts belong to which shop, in story order. "confidence": "confirmed" means preserved vanilla stock
# identifies the mart, "counted" means matched only by line count against shops.py, "unresolved" means the
# data cannot split it.
SHOP_MART_TIERS: "dict[str, dict]" = {
    # ---- confirmed by the player from live play ----
    "Phenac City Shop": {
        "room": 103, "marts": (1,), "confidence": "player",
        "why": "ADDENDUM 238c: the player's own stock table for Phenac 1F lists exactly mart 1's thirteen "
               "lines -- Poke Ball, Great Ball, Ultra Ball, Antidote, Awakening, Burn Heal, Full Heal, Hyper "
               "Potion, Ice Heal, Parlyz Heal, Revive, Super Potion, Poke Snack -- and the ONLY 'after meeting "
               "Duking in Pyrite Town' annotation on that table sits on the POKE SNACK LINE. The identical note "
               "appears on Agate's Snack line too, so it is the game-wide Poke Snack unlock, not a mart swap. "
               "The earlier reading (14 -> 1) mistook that per-line note for a restock. Phenac 1F has ONE "
               "state; mart 14 belongs to some other shop and is back in UNRESOLVED_MARTS. Player, "
               'confirming: "these don\'t change, but are only accessible after music disc and mayor note"',
    },
    "Phenac City Shop 2F": {
        "room": 104, "marts": (2,), "confidence": "player",
        "why": 'player, correcting themselves mid-survey: "Wait no, you\'re right. 2F is mart 2." Mart 2 is '
               "the six vitamins. Recorded because the first answer said mart 6, and mart 6 going back to "
               "unassigned is what re-opened the Gateon ladder below",
    },
    "Pyrite Town Shop": {
        "room": 121, "marts": (3, 13), "confidence": "player",
        "why": 'player: "Pyrite is 3>13"',
    },
    # ---- confirmed by preserved vanilla stock ----
    "Agate Village Shop": {
        "room": 134, "marts": (5, 12, 19), "confidence": "confirmed",
        "why": "the three Agate Scents (513/514/515) are preserved in exactly these three marts",
    },
    "Pyrite Vending Machine": {
        "room": 119, "marts": (4,), "confidence": "confirmed",
        "why": "the only mart holding the four drinks (Fresh Water/Soda Pop/Lemonade/Moomoo Milk)",
    },
    "Gateon Port Herb Shop": {
        "room": None, "marts": (7, 20), "confidence": "confirmed", "excluded": True,
        "why": "the only marts holding the four herbs; 7 and 20 are the SAME pool slice, so this is one "
               "stock list reached twice, not a restock -- it introduces no second set of lines. "
               "EXCLUDED 2026-09-17 by the player's decision (\"Herb shop is fine as excluded\"): it has no "
               "room id in the RoomAndStoryByteData compilation, so the client could never identify a "
               "purchase there, and `shops.SHOPS` has no row for it -- it creates no locations. Its four "
               "slots are still PATCHED, exactly like the Battle CD shop's nine (see that row): a shop left "
               "unpatched would sell its real items, which is the one outcome worse than selling a dud. The "
               "flag is recorded here rather than left implicit so that 'no room id' reads as a decision "
               "instead of an oversight -- and so that supplying a room id later is a deliberate reversal "
               "rather than an accident",
    },
    # ---- closed by the player's own stock tables for these three rooms ----
    "Outskirt Stand Shop": {
        "room": 164, "marts": (8,), "confidence": "player",
        "why": "the player's table lists Full Heal, Hyper Potion, Nest Ball, Net Ball, Revive, Super Potion, "
               "Timer Ball, Ultra Ball and a Poke Snack -- mart 8's nine lines exactly, and nothing on it is "
               "annotated except the Snack, so it is a single shelf that never restocks",
    },
    "Realgam Tower Shop": {
        "room": 50, "marts": (0,), "confidence": "player",
        "why": "the player's table lists Hyper Potion, Full Heal, Revive and nine TMs (10/14/15/16/17/20/25/"
               "33/38) -- mart 0 exactly, the only TM shop in the table -- plus a Poke Snack, which mart 0 does "
               "NOT carry. Immaterial to checks (a Snack is never one) but recorded: it means the Snack line is "
               "not always part of the mart slice. Nothing else is annotated, so this shelf never restocks",
    },
    "Gateon Port Shop": {
        "room": 156, "marts": (6, 14, 15), "confidence": "elimination",
        "why": "mart 15 is the player's table read straight off: Poke Ball, Great Ball, Ultra Ball, Potion, "
               "Super Potion, Hyper Potion, Max Potion, Full Restore, five status heals, Full Heal, Revive and "
               "a Poke Snack -- sixteen lines, fifteen buyable, exactly what shops.py allocates. The two "
               "earlier tiers are forced BY ELIMINATION rather than matched: with 0, 1, 2, 3, 4, 5, 7, 8, 9, "
               "10, 11, 12, 13, 16, 17, 18, 19, 20 all now having a confirmed home, marts 6 and 14 are the "
               "only ones left and Gateon is the only shop still needing earlier tiers. 6 + 5 + 4 = 15, "
               "which is the right total. SEE THE CAVEAT ON TIER_GATES BELOW -- the player's per-item "
               "conditions do not split cleanly across these three marts",
    },
    # ---- matched on line count alone; NOT proven, and one guess of this kind has already been wrong ----
    "Mt. Battle Shop": {
        "room": 21, "marts": (9, 10, 11), "confidence": "counted",
        "why": "18 lines of TMs and held items, matching shops.py; all three marts are the same slice",
    },
    "Realgam Battle Sim Shop": {
        "room": 61, "marts": (16, 17, 18), "confidence": "counted", "excluded": True,
        "why": "three disjoint 3-line Battle CD marts summing to the 9 lines shops.py records. EXCLUDED "
               "2026-09-15 at the player's instruction (\"Exclude the whole battle CD shop\") -- the row is "
               "kept so the mart mapping and the three-tier structure survive, but shops.py marks the room "
               "unconfirmed so it creates no locations and credits no purchase",
    },
}

# Every mart has a home. Gateon's earlier tiers were deduced -- 6 and 14 are what is left once every other
# shop is placed, and 6 + 5 + 4 = 15 buyable lines is what shops.py allocates -- and its Super Potion, Full
# Heal, Revive and Poke Ball arrive with mart 14, which is why TIER_GATES uses the latest condition in a tier.
UNRESOLVED_MARTS: "tuple[int, ...]" = ()
UNRESOLVED_SHOPS: "tuple[str, ...]" = ()

# What opens each later tier, from the player's live play. A tier with no entry has no known gate and must
# not be given a guessed one.
TIER_GATES: "dict[tuple[str, int], dict]" = {
    ("Agate Village Shop", 12): {
        "event": "Aidan's email, received after the first Mt. Battle visit",
        "regions": ("Mt. Battle",),
        "items": (),
        "adds": "a Poke Ball line",
    },
    ("Agate Village Shop", 19): {
        "event": "solving the ONBS crisis",
        "regions": ("Pyrite Town", "Poke Spots", "Pyrite Town (ONBS)"),
        "items": ("Data ROM",),
        "adds": "a Great Ball line",
    },
    ("Gateon Port Shop", 14): {
        "event": "solving the ONBS crisis",
        "regions": ("Pyrite Town", "Poke Spots", "Pyrite Town (ONBS)"),
        "items": ("Data ROM",),
        "adds": "a Poke Ball line and a Great Ball line, plus Super Potion, Full Heal and Revive -- the last "
                "three are unannotated on the player's table and are gated here only because they share a "
                "mart with the Great Ball (see the elimination caveat above)",
    },
    ("Gateon Port Shop", 15): {
        "event": "defeating Gorigan at the end of Cipher Key Lair",
        "regions": ("Cipher Key Lair",),
        "items": ("System Lever",),
        "adds": "a Max Potion line and a Full Restore line, plus Ultra Ball and Hyper Potion",
    },
    ("Pyrite Town Shop", 13): {
        "event": "solving the ONBS crisis",
        "regions": ("Pyrite Town", "Poke Spots", "Pyrite Town (ONBS)"),
        "items": ("Data ROM",),
        "adds": "a Poke Ball line and a Great Ball line",
    },
}
# "regions" and "items" are split because rules.py has to tell them apart; "Data ROM" resolves through
# `items.requirement_to_pool_item` to the combined Data ROM & ID Card item. The ONBS entries also name
# "Pyrite Town (ONBS)", which changes nothing today but keeps the gate tight if that edge gains a requirement.


def gated_shop_lines(shop: str) -> "list[tuple[tuple[int, ...], dict]]":
    """[(line numbers this tier introduces, its gate)] for the tiers of `shop` that are not open from the
    start. Opening-shelf lines are reachable as soon as the room is and do not appear here. rules.py needs
    this, or a restock-only line lands in logic long before the restock."""
    entry = SHOP_MART_TIERS.get(shop)
    if entry is None:
        return []
    out = []
    seen: "set[int]" = set()
    for index, mart in enumerate(entry["marts"]):
        numbers = set(MART_LINE_NUMBERS[mart])
        fresh = tuple(sorted(numbers - seen))
        seen |= numbers
        if index == 0 or not fresh:
            continue
        gate = TIER_GATES.get((shop, mart))
        if gate is None:
            continue
        out.append((fresh, gate))
    return out


# What it takes to reach the shop at all. This gates the room, so it applies to every line including the
# first tier; `shops.py` files both Phenac rooms under "Phenac City (Post-Sixes)".
SHOP_ACCESS_REQUIREMENTS: "dict[str, tuple[str, ...]]" = {
    "Phenac City Shop": ("Music Disc", "Mayor's Note", "Realgam Tower", "Phenac City"),
    "Phenac City Shop 2F": ("Music Disc", "Mayor's Note", "Realgam Tower", "Phenac City"),
}


# Poke Snacks are never a check, by construction: the Snack is in `items.SHOP_EXCLUDED_ITEM_IDS`, so it never
# becomes a berry and never gets a label. Marts 1, 8, 13, 14, 15 and 19 carry one.

# What `iso_patcher` hands `apply_mart_randomization`: one entry per shop, marts oldest tier first, including
# the excluded Battle CD room, whose slots still need patching so it does not sell real items. Grouping this
# way gives one berry per shelf line for the whole game, so "check N" is the Nth line the shop ever offers.
MART_GROUPS: "tuple[tuple[str, tuple[int, ...]], ...]" = tuple(
    (name, tuple(entry["marts"])) for name, entry in SHOP_MART_TIERS.items()
)


def _simulate_grouped() -> "dict[int, tuple[int, ...]]":
    """mart index -> the 1-based line number of each patchable slot, in shelf order; the line number is the
    check number. Mirrors `apply_mart_randomization`'s grouped path, including the fallback that turns an
    unassigned mart into its own single-mart group."""
    from ..items import SHOP_EXCLUDED_ITEM_IDS
    from ..tools.xd_rel_format import ITEM_REMAP_THRESHOLD_ID

    def patchable(mart: int) -> "list[tuple[int, int]]":
        first, last, items = VANILLA_MARTS[mart]
        out = []
        for slot, item in zip(range(first, last + 1), items):
            if item in SHOP_EXCLUDED_ITEM_IDS or not 1 <= item < ITEM_REMAP_THRESHOLD_ID:
                continue
            out.append((slot, item))
        return out

    groups = list(MART_GROUPS)
    named = {m for _key, marts in groups for m in marts}
    groups.extend((f"mart {m}", (m,)) for m in sorted(VANILLA_MARTS) if m not in named)

    line_of_slot: "dict[int, int]" = {}
    owner: "dict[int, str]" = {}
    for key, marts in groups:
        assigned: "dict[int, int]" = {}
        for mart in marts:
            for slot, item in patchable(mart):
                previous = owner.setdefault(slot, key)
                assert previous == key, f"pool slot {slot} claimed by both {previous!r} and {key!r}"
                if item not in assigned:
                    assigned[item] = len(assigned) + 1
                line_of_slot[slot] = assigned[item]
    out: "dict[int, tuple[int, ...]]" = {}
    for mart, (first, last, _items) in VANILLA_MARTS.items():
        out[mart] = tuple(line_of_slot[s] for s in range(first, last + 1) if s in line_of_slot)
    return out


MART_LINE_NUMBERS: "dict[int, tuple[int, ...]]" = _simulate_grouped()


def shop_line_count(shop: str) -> int:
    """How many checks this shop has: the number of distinct lines it ever offers, across every tier."""
    entry = SHOP_MART_TIERS.get(shop)
    if entry is None:
        return 0
    return max((n for mart in entry["marts"] for n in MART_LINE_NUMBERS[mart]), default=0)


def shop_lines(shop: str) -> "list[tuple[int, int, int]]":
    """[(line number, vanilla item id, the mart that first offers it)] in check order, for one shop."""
    entry = SHOP_MART_TIERS.get(shop)
    if entry is None:
        return []
    seen: "dict[int, tuple[int, int, int]]" = {}
    for mart in entry["marts"]:
        first, _last, items = VANILLA_MARTS[mart]
        numbers = iter(MART_LINE_NUMBERS[mart])
        for item in items:
            if item in _PRESERVED_ITEM_IDS:
                continue
            n = next(numbers)
            seen.setdefault(n, (n, item, mart))
    return [seen[n] for n in sorted(seen)]


def _simulate_rotation() -> "dict[int, tuple[int, ...]]":
    """Re-derive MART_LABELS from the vanilla mart table and the patcher's own rotation."""
    from ..items import SHOP_EXCLUDED_ITEM_IDS, USELESS_BERRY_IDS
    from ..tools.xd_rel_format import ITEM_REMAP_THRESHOLD_ID

    vanilla: "dict[int, int]" = {}
    for first, last, items in VANILLA_MARTS.values():
        for slot, item in zip(range(first, last + 1), items):
            vanilla[slot] = item
    patched = dict(vanilla)
    rotation = 0
    for mart in sorted(VANILLA_MARTS):
        first, last, _items = VANILLA_MARTS[mart]
        for slot in range(first, last + 1):
            original = vanilla.get(slot)
            if original is None or original in SHOP_EXCLUDED_ITEM_IDS:
                continue
            if not 1 <= original < ITEM_REMAP_THRESHOLD_ID:
                continue
            patched[slot] = USELESS_BERRY_IDS[rotation % len(USELESS_BERRY_IDS)]
            rotation += 1
    label_of = {berry: i + 1 for i, berry in enumerate(USELESS_BERRY_IDS)}
    out: "dict[int, tuple[int, ...]]" = {}
    for mart, (first, last, _items) in VANILLA_MARTS.items():
        out[mart] = tuple(label_of[patched[s]] for s in range(first, last + 1) if patched[s] in label_of)
    return out


def new_labels_by_tier(shop: str) -> "list[tuple[int, tuple[int, ...]]]":
    """[(mart, labels this tier introduces)] in story order. A tier that introduces nothing is an alias of an
    earlier one, not a restock -- the herb shop and Mt. Battle are both that shape."""
    entry = SHOP_MART_TIERS.get(shop)
    if entry is None:
        return []
    seen: "set[int]" = set()
    out = []
    for mart in entry["marts"]:
        labels = MART_LABELS[mart]
        out.append((mart, tuple(x for x in labels if x not in seen)))
        seen.update(labels)
    return out


assert _simulate_rotation() == MART_LABELS, (
    "the berry rotation no longer reproduces the labels verified against live RAM -- the world and the "
    "patcher have desynced, and every shop check would point at the wrong line"
)


def _snack_and_scent_lines_have_no_label() -> bool:
    """No preserved id ever became a shelf label -- the Poke Snack fence, and the Scents with it."""
    from ..items import SHOP_EXCLUDED_ITEM_IDS

    for mart, (first, last, items) in VANILLA_MARTS.items():
        preserved = sum(1 for item in items if item in SHOP_EXCLUDED_ITEM_IDS)
        if len(items) - preserved != len(MART_LABELS[mart]):
            return False
    return True


assert _snack_and_scent_lines_have_no_label(), (
    "a preserved line (Poke Snack or Agate Scent) picked up a shelf label -- it would become a buyable check"
)


# Agate Village Pit Stop: medicines and balls instead of AP items. A mart is a fixed-size slice, so each
# Agate mart takes as many lines from the front of this list as it has patchable slots -- 7, 8 and 9, the
# Scents staying. Asserted below so a shorter mart cannot silently drop a ball.
AGATE_PIT_STOP_SHOP = "Agate Village Shop"
# ADDENDUM 387 moved the Revive up. Player: "Add revives to the agate village pit stop in place of
# something, prior to the expansion. Maybe hyper potions." The order matters because a mart takes lines from
# the FRONT: Agate's three marts are 7, 8 and 9 lines, so anything past position 7 is only on the shelf
# after a restock. The Revive sat at 8 and the smallest shelf therefore never carried one -- the item you
# most want at a pit stop was the one gated behind the expansion. It now takes the Hyper Potion's place at
# 6, and the Hyper Potion takes its old spot; nothing left the list.
AGATE_PIT_STOP_STOCK: "tuple[int, ...]" = (
    4,   # Poke Ball
    3,   # Great Ball
    2,   # Ultra Ball
    13,  # Potion
    22,  # Super Potion
    24,  # Revive       -- ADDENDUM 387: promoted here so every Agate mart carries one
    23,  # Full Heal
    21,  # Hyper Potion -- ADDENDUM 387: takes the Revive's old slot, so it needs mart 12 (Aidan's email)
    20,  # Max Potion   -- from mart 19 (the ONBS restock)
)


def agate_pit_stop_marts() -> "tuple[int, ...]":
    return tuple(SHOP_MART_TIERS[AGATE_PIT_STOP_SHOP]["marts"])


def _patchable_count(mart: int) -> int:
    return sum(1 for item in VANILLA_MARTS[mart][2] if item not in _PRESERVED_ITEM_IDS)


assert all(_patchable_count(m) <= len(AGATE_PIT_STOP_STOCK) for m in agate_pit_stop_marts()), (
    "an Agate mart has more patchable lines than the Pit Stop stock -- a line would be left selling a berry"
)
assert min(_patchable_count(m) for m in agate_pit_stop_marts()) >= 3, (
    "the smallest Agate mart must still carry all three balls"
)
# ADDENDUM 387: the point of the reorder, asserted rather than left to the comment above. Every Agate mart,
# including the smallest, must reach the Revive.
assert all(24 in AGATE_PIT_STOP_STOCK[:_patchable_count(m)] for m in agate_pit_stop_marts()), (
    "an Agate mart is too short to reach the Revive -- move it further forward in AGATE_PIT_STOP_STOCK"
)
