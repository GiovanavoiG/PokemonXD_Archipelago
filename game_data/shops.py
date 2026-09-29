"""Pokemon XD -- the ten shop rooms, as AP locations (ADDENDUM 176, 2026-09-13).

Shop checks are named after the SHOP, not the berry: "Gateon Port Shop AP Item 1". ADDENDUM 142 validated
the live room id, which made that possible -- when a dummy berry's Bag quantity goes up, the room the player
is standing in says which shop it was. The 104 locations ADDENDUM 111 shipped were named for the berry
because the berry was the only identity the client could see.

The ten rooms are the player's own `RoomAndStoryByteData` compilation, and each shop's region is its room's
region, so Gateon Port's shop is open from the start and the Outskirt Stand's is not. Each shop has its own
slot count (ADDENDUM 178) rather than a flat 12; see the comment above `SHOPS` for where those come from.

"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Shop:
    room_id: int
    name: str          # the display name used in location names -- frozen forever by the location id
    region: str        # a regions.REGION_NAMES entry
    slot_count: int = 0       # stock lines chest/shop randomization actually converts
    confirmed: bool = False   # this room id is trusted enough to create locations for
    excluded: bool = False    # ADDENDUM 238: confirmed, but deliberately produces NO checks. Different from
                              # "unconfirmed" -- the room id is known, the player just wants it out.
    short_label: str = ""     # ADDENDUM 234: the <=7-char tag the live rename puts on this shop's dummy
                              # berries ("GATEON #3"). The budget is the shortest shop berry's own name
                              # length, 10 characters, because the rename overwrites a packed string-table
                              # entry. See item_name_strings.py.
    source: str = ""          # why it is trusted -- "live" (a `!room` reading) or "player" (they vouched)
    note: str = ""
    # ADDENDUM 395: other room ids that ARE this shop. `room_id` stays the canonical one -- every per-room
    # piece of state keys off it -- and an alias only has to make the live writers and the purchase credit
    # recognise the place.
    aliases: "tuple[int, ...]" = ()


# PER-SHOP SLOT COUNTS (ADDENDUM 178), replacing a flat cap of 12 applied to both an 18-line shop and a
# 4-line vending machine: slots past a shop's real stock never fired, and a shop over 12 lines stopped
# creating checks at 12. Each count is that shop's stock lines from Bulbapedia's XD shop-sales listing,
# minus the ids this project never converts (items.SHOP_EXCLUDED_ITEM_IDS: the three Agate Scents and the
# per-shop Poke Snack). It reconciles with an independent count a year earlier: ADDENDUM 110 summed the
# same listing at 117 lines, of which 3 Scents and 6 Poke Snacks leave 108 randomizable; the numbers here
# give 113 and 104, and the difference is exactly the one shop with no room id -- a Gateon Port Herb Shop
# on 2F, 4 lines, none excluded. Where the listing's "(N items)" parenthetical disagrees with its own list
# the list was counted: Mt. Battle says 16 and lists 18, Realgam's Battle CD shop says 7 and lists 9.
#
# Still secondary: Bulbapedia, not a census of the ISO, and the mart-to-room mapping is unconfirmed
# (ADDENDUM 127 found 21 marts in `pocket_menu.rel` against these 10 rooms, consistent with shops
# restocking as the story advances). Too high leaves unreachable filler-only locations, too low stops
# crediting purchases; neither breaks a seed, since a purchase past the count still completes in
# ShopPurchaseTracker and just creates no check.

# WHICH ROOMS CREATE CHECKS. "Confirmed" has two sources: a live `!room` reading (rooms 21 and 156) or the
# player vouching from their `RoomAndStoryByteData` compilation (the other eight). Both create checks;
# `source` records which, so if a shop stays silent in play the eight "player" rooms are where to look and
# 21/156 are the control. A wrong room id leaves EXCLUDED locations in a real region, so the seed spends
# filler on checks nobody can reach. To park one again, set `confirmed=False` and clear `source`; its ids
# stay frozen in locations.py so re-promoting renumbers nothing. Room 119 holding both the Pyrite vending
# machine and chest 93 is not a contradiction -- chest_table really does put chest 93 in room 119.
#
# The ten rooms, in room-id order. Names are frozen by their location ids the moment they ship.
SHOPS: "tuple[Shop, ...]" = (
    Shop(21, "Mt. Battle Shop", "Mt. Battle", slot_count=18, short_label="MTBTL", confirmed=True, source="live",
         note="ram_client.KNOWN_ROOM_IDS: 'Mt. Battle (inside) -- shop'"),
    Shop(50, "Realgam Tower Shop", "Realgam Tower", slot_count=12, short_label="RLGAM", confirmed=True, source="player"),
    # ADDENDUM 238: excluded at the player's instruction. `excluded` keeps the row -- room id, slot count,
    # label, stock research -- while dropping it from CONFIRMED_SHOPS, so room 61 creates no locations and
    # `is_shop_room(61)` is False; a berry bought there credits nothing rather than the wrong thing. Its
    # nine frozen location ids are not reassigned (ADDENDUM 26). The ISO patch is deliberately unchanged:
    # marts 16/17/18 still get their dummy berries, because the rotation is global and skipping them would
    # shift every later assignment out of step with `game_data/shop_stock.py`'s RAM-verified table.
    Shop(61, "Realgam Battle Sim Shop", "Realgam Tower", slot_count=9, short_label="BTLSIM", confirmed=True,
         excluded=True, source="player",
         note="the Battle CD shop. Excluded outright at the player's instruction -- see the comment above"),
    Shop(103, "Phenac City Shop", "Phenac City (Post-Sixes)", slot_count=12, short_label="PHENAC", confirmed=True, source="player",
         note="REGION CORRECTED with the promotion: this row said 'Phenac City' on my own claim that the shop "
              "is usable on the first visit, which I never had a source for. The player's own room table puts "
              "103 in Phenac City (Post-Sixes), so it now agrees with their data rather than my guess -- and "
              "the later region is the safe direction if the guess was wrong"),
    Shop(104, "Phenac City Shop 2F", "Phenac City (Post-Sixes)", slot_count=6, short_label="PHENC2F", confirmed=True, source="player",
         note="the other floor of 103's building; region follows the player's own room table, same as 103"),
    Shop(119, "Pyrite Vending Machine", "Pyrite Town", slot_count=4, short_label="VENDING", confirmed=True, source="player",
         note="room 119 also holds chest 93, which is fine rather than a conflict -- see the retraction in the "
              "section comment above"),
    Shop(121, "Pyrite Town Shop", "Pyrite Town", slot_count=12, short_label="PYRITE", confirmed=True, source="player"),
    Shop(134, "Agate Village Shop", "Agate Village", slot_count=9, short_label="AGATE", confirmed=True, source="player",
         note="the shop whose Scents are excluded from randomization outright (ADDENDUM 110) -- item ids "
              "513/514/515, which the player confirmed correct in ADDENDUM 177"),
    Shop(156, "Gateon Port Shop", "Gateon Port", slot_count=15, short_label="GATEON", confirmed=True, source="live",
         note="ram_client.KNOWN_ROOM_IDS: 'Gateon Port shop'"),
    # ADDENDUM 394. WAS 164, and 164 is the EXTERIOR. Player, with a live `!room` reading: "Inside outskirt
    # stand is showing as room 163." The counter is inside, so 163 is the shop.
    #
    # The symptom was the one the section comment above predicted for a `source="player"` id, plus one nobody
    # had thought of: "It worked temporarily and then broke. It likely worked because i stepped through 164
    # (outside) and then went inside and it broke." The renamer writes on a room CHANGE, so walking through the
    # exterior renamed the shelf correctly, and stepping inside fired it again with the not-a-shop fallback --
    # which is why this looked intermittent rather than simply absent.
    #
    # `source="live"` now: this is a measured reading, like rooms 21 and 156, not a vouched one.
    # ADDENDUM 395: BOTH ids. 394 moved this to 163 on a live reading, and the player then saw 164 from the
    # same spot: "Wait, now outskirt stand is showing as room 164. I think Outskirt stand might be a weird
    # case - just make both count as shop room for writes." A read that flips between two ids is exactly the
    # "sometimes working, sometimes not" that survived 394, and the stand is one place either way.
    Shop(163, "Outskirt Stand Shop", "Outskirt Stand", slot_count=8, short_label="OUTSKRT", confirmed=True, source="live",
         aliases=(164,),
         note="the only shop in a LATE region -- Outskirt Stand sits behind the whole key-item chain, so these "
              "eight are the deepest shop checks in the seed. Room 163 is the INSIDE; 164 is the exterior and "
              "stays in chest_regions' room map as Outskirt Stand"),
)

# Only confirmed shops get locations and get credited. ADDENDUM 238: `excluded` drops out here, the single
# place that decides what becomes a location and what `is_shop_room` answers True for. An excluded shop is
# still confirmed, so it stays out of UNCONFIRMED_SHOPS -- "we don't know" and "we don't want it" are
# different states.
CONFIRMED_SHOPS: "tuple[Shop, ...]" = tuple(
    shop for shop in SHOPS if shop.confirmed and not shop.excluded
)
EXCLUDED_SHOPS: "tuple[Shop, ...]" = tuple(shop for shop in SHOPS if shop.excluded)
UNCONFIRMED_SHOPS: "tuple[Shop, ...]" = tuple(shop for shop in SHOPS if not shop.confirmed)

# Aliases resolve to the SAME Shop object, so `shop_for_room` answers for either id while `shop.room_id`
# stays the one canonical key every per-room tracker uses.
SHOPS_BY_ROOM: "dict[int, Shop]" = {shop.room_id: shop for shop in CONFIRMED_SHOPS}
for _shop in CONFIRMED_SHOPS:
    for _alias in _shop.aliases:
        assert _alias not in SHOPS_BY_ROOM, f"room {_alias} is already a shop; it cannot alias {_shop.name}"
        SHOPS_BY_ROOM[_alias] = _shop
del _shop, _alias


def canonical_shop_room(room_id: "int | None") -> "int | None":
    """The id every per-room tracker should key on: an alias collapses onto its shop's own room.

    Without this, a room read that flips between a shop's two ids splits `purchased_by_room` and
    `slots_credited` across both, so a line bought under one id would not count as bought under the other and
    the shelf's NO CHECK greying would flicker with the read."""
    shop = SHOPS_BY_ROOM.get(room_id) if room_id is not None else None
    return shop.room_id if shop is not None else room_id
SHOP_ROOM_IDS: "frozenset[int]" = frozenset(SHOPS_BY_ROOM)

# Every room in the table, confirmed or not -- diagnostics and the promotion workflow only. Never used to
# create a location or credit a check.
# ADDENDUM 395: aliases count as rooms in the table. `SHOP_ROOM_IDS` includes them, and this set is the
# superset that one is checked against.
ALL_SHOP_ROOM_IDS: "frozenset[int]" = frozenset(
    room for shop in SHOPS for room in (shop.room_id, *shop.aliases)
)


# ADDENDUM 311 -- Agate Village Pit Stop. The client learns the disabled room from slot_data and calls
# `set_disabled_shop_rooms`; after that the room stops being a shop to every live check -- no purchase
# credited, no shelf line renamed or repriced. The NAMES stay in the datapackage like any absent location.
AGATE_PIT_STOP_SHOP_NAME = "Agate Village Shop"
AGATE_PIT_STOP_ROOM_ID = 134

_disabled_rooms: "set[int]" = set()


def set_disabled_shop_rooms(room_ids: "set[int] | frozenset[int] | list[int]") -> None:
    _disabled_rooms.clear()
    _disabled_rooms.update(int(r) for r in room_ids)


def is_disabled_shop_room(room_id: "int | None") -> bool:
    return room_id is not None and room_id in _disabled_rooms


def shop_location_name(shop_name: str, slot: int) -> str:
    """"{Shop Name} AP Item {n}" -- the player's own requested format, verbatim."""
    return f"{shop_name} AP Item {slot}"


def shop_location_names(shop: Shop) -> "tuple[str, ...]":
    """One name per randomized stock line in THAT shop -- see the section comment above SHOPS."""
    return tuple(shop_location_name(shop.name, slot) for slot in range(1, shop.slot_count + 1))


def all_shop_location_names() -> "tuple[str, ...]":
    """Only CONFIRMED shops -- see the section comment above SHOPS."""
    return tuple(name for shop in CONFIRMED_SHOPS for name in shop_location_names(shop))


def slot_count_for_room(room_id: "int | None") -> int:
    """How many checks that room's shop can credit. 0 for anything that is not a confirmed shop room."""
    shop = shop_for_room(room_id)
    return 0 if shop is None else shop.slot_count


def shop_for_room(room_id: "int | None") -> "Shop | None":
    """The shop in a room, or None. None is a real answer: a dummy berry can go up outside any shop (a gift, a
    pickup), and crediting a guess would send a check for a purchase that never happened."""
    if room_id is None or room_id in _disabled_rooms:
        return None
    return SHOPS_BY_ROOM.get(room_id)


def location_name_to_shop_and_slot() -> "dict[str, tuple[Shop, int]]":
    out: "dict[str, tuple[Shop, int]]" = {}
    for shop in CONFIRMED_SHOPS:
        for slot in range(1, shop.slot_count + 1):
            out[shop_location_name(shop.name, slot)] = (shop, slot)
    return out


assert len(ALL_SHOP_ROOM_IDS) == sum(1 + len(shop.aliases) for shop in SHOPS), (
    "two shops share a room id, or an alias repeats one"
)
assert canonical_shop_room(164) == 163, "the Outskirt Stand's exterior must collapse onto its interior"
assert len(set(shop.name for shop in SHOPS)) == len(SHOPS), "two shops share a display name"
assert len(all_shop_location_names()) == sum(shop.slot_count for shop in CONFIRMED_SHOPS)
assert all(shop.slot_count > 0 for shop in SHOPS), (
    "every shop needs a real slot count -- a zero would silently create no checks for it"
)
# The reconciliation above, asserted rather than only written down. Both totals count every row in SHOPS,
# excluded ones included: this fences the stock research, not what ships as checks.
# ADDENDUM 238c: 104 -> 105 and 108 -> 109, because Agate went from 8 lines to 9 -- not a new discovery, but
# a UNION across a shop's tiers re-derived from `shop_stock.VANILLA_MARTS`. A single-shelf listing sees one
# tier, and Agate's shelf gains a Poke Ball when Aidan's email arrives and a Great Ball after the ONBS crisis.
assert sum(shop.slot_count for shop in SHOPS) == 105
UNMAPPED_SHOP_LINE_COUNT = 4   # the Gateon Port Herb Shop (2F) -- no room id in the player's compilation
assert sum(shop.slot_count for shop in SHOPS) + UNMAPPED_SHOP_LINE_COUNT == 109
assert CONFIRMED_SHOPS, "at least one shop must be confirmed or the category ships empty"
assert all(shop.source in ("live", "player") for shop in CONFIRMED_SHOPS), (
    "a confirmed shop must record WHY it is trusted -- see the section comment above SHOPS"
)
assert all(not shop.source for shop in UNCONFIRMED_SHOPS), (
    "an unconfirmed shop has no confirmation source to record"
)
# UNCONFIRMED_SHOPS is empty right now. Deliberately not asserted empty: parking a bad room id is the cheap
# way to withdraw one, and an assertion that nothing is parked would turn using it into a crash.


# ADDENDUM 234: every live rename must fit the shortest shop berry's 10-character budget, so the label and
# the shop's own biggest slot number are checked together rather than the label alone.
from . import item_name_strings as _ins  # noqa: E402  (deliberately after SHOPS, which it validates)

SHOP_SHORT_LABELS: "dict[int, str]" = {s.room_id: s.short_label for s in CONFIRMED_SHOPS if s.short_label}


def short_label_for_room(room_id: "int | None") -> "str | None":
    """ADDENDUM 395: resolved through `shop_for_room`, so an ALIAS answers too. Keying the dict directly
    returned None for the Outskirt Stand's second room id, and a None label is what sends `desired_names`
    down its generic `AP ITEM NN` fallback -- the exact symptom this was meant to fix."""
    if room_id is None or room_id in _disabled_rooms:
        return None
    shop = shop_for_room(room_id)
    return (shop.short_label or None) if shop is not None else None


def live_name_for_slot(room_id: int, slot: int) -> "str | None":
    """"GATEON 03" -- what one shelf LINE is renamed to while the player stands in this shop.

    ADDENDUM 235: the number is the dummy berry's own index, the same one the Bag shows as "AP ITEM 03", not
    an AP slot number -- see `ram_client.ItemNameRenamer.desired_names`. This is the one place the format is
    written down and what the import-time budget check below measures. None for a room with no label."""
    label = SHOP_SHORT_LABELS.get(room_id)
    return None if label is None else f"{label} {slot:02d}"


for _shop in CONFIRMED_SHOPS:
    assert _shop.short_label, f"{_shop.name} has no short_label -- the live rename would have nothing to write"
    # Numbered by BERRY (1-20), not by this shop's own stock, so 20 is the widest number that can appear.
    _worst = live_name_for_slot(_shop.room_id, 20)
    assert len(_worst) <= _ins.SHOP_BERRY_NAME_BUDGET, (
        f"{_shop.name}'s worst-case live name {_worst!r} is {len(_worst)} characters, over the "
        f"{_ins.SHOP_BERRY_NAME_BUDGET}-character budget of the shortest shop berry"
    )

assert SHOPS_BY_ROOM[AGATE_PIT_STOP_ROOM_ID].name == AGATE_PIT_STOP_SHOP_NAME
