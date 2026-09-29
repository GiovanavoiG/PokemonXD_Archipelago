from test.bases import WorldTestBase

from .. import items as _items


class PokemonXDTestBase(WorldTestBase):
    game = "Pokemon XD Gale of Darkness"

    # ========================================================================================================
    # RETARGETED 2026-09-13 (ADDENDUM 168) -- the shared "walk the chain forward" helper
    # ========================================================================================================
    # WHY THIS EXISTS: before ADDENDUM 168 every test that needed to open up the map did it the same way --
    # `self.collect_by_name([f"Krane Memo {n}" for n in range(1, 6)])` -- because regions.py chained seven
    # regions behind accumulating Krane Memos (`MEMOS_REQUIRED`). That ladder is gone: the Krane Memos are no
    # longer items at all (items.ITEMS_REMOVED_FROM_POOL), their five LOCATIONS survive as ordinary AP checks,
    # and regions.REGION_EDGES now gates 21 real regions on the real story key items.
    #
    # KEY_ITEM_CHAIN is the memo ladder's replacement, in the order regions.REGION_EDGES actually consumes it.
    # Holding the first N of these opens the graph to exactly the same depth the first N memos used to:
    #
    # UPDATED 2026-09-13 (ADDENDUM 169), then REVERSED the same day. ADDENDUM 169 briefly moved Agate Village
    # into the always-open row (("Menu", "Agate Village", ()) in every mode, with the Machine Part on the
    # Agate -> Mt. Battle edge). The player corrected that within the day -- "Leave Agate, Kaminko and Gateon
    # locked by default if travel randomization is off. Let them unlock normally." -- so with travel
    # randomization OFF the graph walks the vanilla route and the Machine Part is back on
    # ("Gateon Port", "Agate Village", ("Machine Part",)). ADDENDUM 106's four-always-open rule now lives ONLY
    # in the randomize_travel_locations-on branch of regions.py, which still connects Menu -> Agate Village
    # unconditionally. The chain itself never changed through any of this; only which regions the first link
    # buys did, so no test that walks it needed a different prefix.
    #
    #   (none)            Pokemon HQ Lab, Kaminko's House, Gateon Port    <- always-open start (option off)
    #   Machine Part      Agate Village, Mt. Battle, Cipher Lab
    #   + Data ROM        Pyrite Town, Poke Spots, Pyrite Town (ONBS), Realgam Tower, Phenac City
    #   + Music Disc      Phenac City (Mayor's House)
    #   + Mayor's Note    Phenac City (Post-Sixes) ... Outskirt Stand, Snagem Hideout, Cipher Key Lair
    #   + System Lever    Cipher Key Lair (deep), Citadark Isle
    #
    # The Elevator Key and Gonzap's Key are deliberately NOT here: they are in
    # items.NEVER_SHUFFLED_KEY_ITEM_NAMES, never enter the pool, and regions.py therefore drops them from its
    # edge rules (naming an item that was never created makes every region past that edge unreachable -- see
    # regions.py's own ADDENDUM 168 comment about exactly that failure).
    # ADDENDUM 179: "Data ROM" is no longer a pool item -- it ships packaged with the ID Card as one item, so
    # receiving one without the other cannot strand the player inside the Cipher Lab. The chain's SHAPE is
    # unchanged (five links, same order, same regions opened); only the second link's name moved. Resolved from
    # items.COMBINED_KEY_ITEM_NAME rather than typed, so the next packaging change is one edit there.
    # ADDENDUM 273/274: the Scooter Upgrade is NOT here. It is gated on `shuffle_scooter_upgrade`, which is
    # OFF by default, so in a default seed the item is never created and `regions.py` drops it from the SS
    # Libra edge -- the chain is exactly what it was. Tests that want the gate turn the option on and collect
    # the item themselves (see test_addendum_273_*), which is the honest shape: a chain link that only exists
    # under an option does not belong in the shared fixture.
    KEY_ITEM_CHAIN = ("Machine Part", _items.COMBINED_KEY_ITEM_NAME, "Music Disc", "Mayor's Note",
                      "System Lever")

    def collect_key_item_chain(self, count: "int | None" = None) -> "list[str]":
        """Collect the first `count` items of KEY_ITEM_CHAIN (all of them by default) and return their names.

        The direct replacement for the pre-ADDENDUM-168 `collect_by_name([f"Krane Memo {n}" ...])` idiom: the
        full chain opens Citadark Isle, one short of the full chain stops at Cipher Key Lair, and so on up the
        table above.
        """
        names = list(self.KEY_ITEM_CHAIN if count is None else self.KEY_ITEM_CHAIN[:count])
        if names:
            self.collect_by_name(names)
        return names
