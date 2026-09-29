"""Turning a `LocationInfo` reply into shop-shelf descriptions.

`args["locations"]` does not hold dicts: `NetUtils.allowlist` includes `NetworkItem`, so the JSON decoder's
object hook makes every entry a `NetworkItem` namedtuple before any client sees it. Indexing one by string
raises on the first entry and throws away the whole reply, which is how every shelf line came to read "Not
scouted yet" with nothing logged -- the failure went to `_note_warn`, which sits behind `!verbose`.

The parsing lives here rather than in Client.py because Client.py cannot be imported in this project's test
environment (`CommonClient` -> `MultiServer` -> `websockets.extensions`), so its contents can only be checked
by reading source text, and a shape bug is invisible to that. This module is Archipelago-free: it takes
`NetworkItem`-shaped records and lookup callables, so a test can hand it the real namedtuple or a fake.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable


# What marks a location as a shop shelf line. `shops.shop_location_name` builds every one of them as
# f"{shop} AP Item {n}", so this is the one substring that identifies the whole category.
SHOP_LOCATION_MARKER = " AP Item "


def _field(record: Any, name: str, index: int) -> "Any | None":
    """Read one field of a scout record, whatever shape it arrived in: `NetworkItem` by attribute, a bare
    list/tuple by position (matching NetworkItem's field order), a dict by key. Assuming one shape and raising
    on the others is the bug this module exists for, and its failure mode is silence."""
    if isinstance(record, dict):
        return record.get(name)
    value = getattr(record, name, None)
    if value is not None:
        return value
    if isinstance(record, (list, tuple)) and len(record) > index:
        return record[index]
    return None


# Archipelago's `NetworkItem.flags` bitfield; bit 0 is "logical advancement". Copied rather than imported so
# this module stays Archipelago-free.
ITEM_FLAG_PROGRESSION = 0b001
ITEM_FLAG_USEFUL = 0b010
ITEM_FLAG_TRAP = 0b100


def classify(flags: "int | None") -> str:
    """"progression" / "useful" / "trap" / "filler", from a scout record's flags. The scout reply is the only
    place a client can learn the class of an item on someone else's location, and per-line pricing keys off
    it, so it is recorded at parse time rather than re-derived."""
    if not flags:
        return "filler"
    if flags & ITEM_FLAG_PROGRESSION:
        return "progression"
    if flags & ITEM_FLAG_USEFUL:
        return "useful"
    if flags & ITEM_FLAG_TRAP:
        return "trap"
    return "filler"


def scouted_shop_items(
    records: "Iterable[Any]",
    location_name_for_id: "Callable[[int], str | None]",
    item_name_for: "Callable[[int, int | None], str]",
    player_name_for: "Callable[[int], str | None]",
    own_slot: "int | None",
    classifications: "dict[str, str] | None" = None,
) -> "tuple[dict[str, tuple[str, str | None]], list[str]]":
    """Return `({shop location name: (item name, other player's name or None)}, [problems])`.

    Each record is handled on its own so one unreadable entry cannot discard the other fifty, and anything
    that fails is described in `problems` rather than dropped -- `!shops` can then say "scouted 47 of 52
    lines, 5 unreadable" instead of the shelf silently reading "Not scouted yet."

    `classifications`, when given, is filled in alongside from each record's `flags`. Kept out of the return
    value because it answers a different question than the description does, and nothing needs both.

    `player` in a `LocationInfo` reply is the RECEIVING player, not the sender (see `NetworkItem.player` in
    NetUtils). A line going to ourselves carries no player name, which lets `describe_ap_item` spend all three
    description lines on the item name instead of one on a recipient."""
    out: "dict[str, tuple[str, str | None]]" = {}
    problems: "list[str]" = []
    for record in records or []:
        try:
            location_id = _field(record, "location", 1)
            if location_id is None:
                problems.append(f"no location id in {record!r}")
                continue
            name = location_name_for_id(int(location_id))
            if name is None or SHOP_LOCATION_MARKER not in name:
                continue  # not a shop line -- not a problem, just not ours
            item_id = _field(record, "item", 0)
            if item_id is None:
                problems.append(f"{name}: no item id")
                continue
            player = _field(record, "player", 2)
            out[name] = (
                item_name_for(int(item_id), player),
                None if player == own_slot else player_name_for(player),
            )
            if classifications is not None:
                classifications[name] = classify(_field(record, "flags", 3))
        except Exception as exc:  # noqa: BLE001 - one bad record must not cost the other fifty
            problems.append(f"{record!r}: {exc}")
    return out, problems
