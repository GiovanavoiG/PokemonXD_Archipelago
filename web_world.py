"""The shop dummy berries, in one place.

`items.py` and `ram_client.py` used to keep hand-copied copies of this list and they drifted: the client still
counted berries 169-174 as shop berries after they moved to `chest_berries.py`. That is not cosmetic --
`ShopPurchaseTracker` clears a watched berry from the Bag as soon as it confirms an increase, unconditionally,
even outside a shop, so two trackers watched the same slot and whichever cleared it first reset the other's
baseline and the chest check never arrived. It could also credit the wrong check: shop room 119 (Pyrite
Vending Machine) also holds chest 93.

Both modules import from here now, so there is nothing to keep in sync by hand.
"""
from __future__ import annotations

# The 20 berries the shop patch plants in mart slots. Disjoint from `chest_berries.CHEST_BERRY_IDS` and from
# the 15 pool berries 133-147 that Archipelago can send. Rabuta (161) and Ganlon (169) through Starf (174) are
# chest berries; Enigma (175) is in neither set, being bugged in-game.
SHOP_BERRY_SPECS: "list[tuple[str, int]]" = [
    ("Razz Berry", 148), ("Bluk Berry", 149), ("Nanab Berry", 150), ("Wepear Berry", 151),
    ("Pinap Berry", 152), ("Pomeg Berry", 153), ("Kelpsy Berry", 154), ("Qualot Berry", 155),
    ("Hondew Berry", 156), ("Grepa Berry", 157), ("Tamato Berry", 158), ("Cornn Berry", 159),
    ("Magost Berry", 160), ("Nomel Berry", 162), ("Spelon Berry", 163), ("Pamtre Berry", 164),
    ("Watmel Berry", 165), ("Durin Berry", 166), ("Belue Berry", 167), ("Liechi Berry", 168),
]

SHOP_BERRY_IDS: "list[int]" = [game_item_id for _name, game_item_id in SHOP_BERRY_SPECS]
SHOP_BERRY_ID_TO_NAME: "dict[int, str]" = {gid: name for name, gid in SHOP_BERRY_SPECS}

# This module imports nothing on purpose: `ram_client.py` reaches it directly and must not pull in
# `chest_berries.py` (which imports `items`) behind it. `items.py` asserts shop/chest disjointness.
assert len(set(SHOP_BERRY_IDS)) == len(SHOP_BERRY_IDS), "duplicate shop berry id"
assert len(SHOP_BERRY_IDS) == 20, (
    "the shop berry count changed -- `xd_rel_format.apply_mart_randomization` rotates through this list and "
    "needs it longer than the biggest shop (Mt. Battle, 18 lines) or a berry repeats inside one mart"
)
