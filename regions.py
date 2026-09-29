"""
Region graph for the Pokemon XD: Gale of Darkness apworld.

An explicit edge list rather than an ordered chain, because regions branch. With `randomize_travel_locations`
off, a region needs its predecessor plus whatever key item its story transition needs; with it on, each
destination's `Travel Unlock` item is an additional entrance ANDed with those gates and the two confirmed
adjacency rules.
"""

from BaseClasses import Region

from . import travel_locations
from . import items
from .items import PokemonXDItem, ItemClassification
from .locations import PokemonXDLocation, LOCATIONS_BY_REGION, EVENT_LOCATION_NAME, create_regions_and_locations

# The gates are the key items and the story order (game_data/story_bytes.py, game_data/key_items.py).
REGION_EDGES: "tuple[tuple[str, str, tuple[str, ...]], ...]" = (
    # (from, to, required item names) -- "Menu" means "open from the start"
    ("Menu", "Pokemon HQ Lab", ()),
    # The vanilla progression line: HQ > Kaminko > HQ > Gateon > HQ > Agate. The "four always open" rule is
    # only about travel-randomization mode and lives in the travel block below.
    ("Pokemon HQ Lab", "Kaminko's House", ()),
    ("Kaminko's House", "Gateon Port", ()),
    ("Gateon Port", "Agate Village", ("Machine Part",)),
    ("Agate Village", "Mt. Battle", ()),
    # Vanilla unlocks Cipher Lab at Mt. Battle; with travel randomization on it keys off the Data ROM. The
    # ROM's vanilla home is Cipher Lab chest 17, so requiring it in vanilla-placement mode would gate the
    # region behind itself -- hence the split in `_edge_rule`.
    ("Mt. Battle", "Cipher Lab", ()),
    # Pyrite is visited in two halves and only the second is behind the Data ROM. Requiring the ROM on this
    # edge put all 39 plain-Pyrite locations behind it.
    ("Cipher Lab", "Pyrite Town", ()),
    ("Pyrite Town", "Poke Spots", ("Data ROM",)),
    ("Poke Spots", "Pyrite Town (ONBS)", ()),
    ("Pyrite Town (ONBS)", "Realgam Tower", ()),
    ("Realgam Tower", "Phenac City", ()),
    # Three tiers rather than one region: chest 80 holds the Music Disc and chest 78 the Mayor's Note, so a
    # single "needs both" region would gate both items behind themselves.
    ("Phenac City", "Phenac City (Mayor's House)", ("Music Disc",)),
    ("Phenac City (Mayor's House)", "Phenac City (Post-Sixes)", ("Music Disc", "Mayor's Note")),
    ("Phenac City (Post-Sixes)", "SS Libra (stranded)", ("Elevator Key",)),
    ("SS Libra (stranded)", "Kaminko's House (Robo Groudon)", ()),
    # The ship needs the Scooter Upgrade in both travel modes. Named directly rather than through
    # `requirement_to_pool_item`: it is not a vanilla key item with a packaging story.
    ("Kaminko's House (Robo Groudon)", "SS Libra", (items.SCOOTER_ITEM_NAME,)),
    ("SS Libra", "Cipher Key Lair (exterior)", ()),
    ("Cipher Key Lair (exterior)", "Outskirt Stand", ()),
    ("Outskirt Stand", "Snagem Hideout", ()),
    # Gonzap's Key is deliberately not required: no chest in the treasure table holds it or a Shadow Ball, so
    # it gates no AP location at all.
    ("Snagem Hideout", "Cipher Key Lair", ()),
    ("Cipher Key Lair", "Cipher Key Lair (deep)", ("System Lever",)),
    ("Cipher Key Lair (deep)", "Citadark Isle", ()),
)

# With travel shuffle ON, re-source these edges. `SS Libra -> Cipher Key Lair (exterior)` was the one edge
# still running through the ship, putting the Scooter Upgrade in front of the exterior, the deep tier and
# Citadark; the ship's predecessor implies everything that path did. Not applied with shuffle off: there the
# ladder is the only route to 0x62 and `ram_client.ScooterStoryHold` pins the story byte at 0x5A until the
# Scooter arrives, so the fill could place the Scooter in Snagem and strand the run. With shuffle on, hovering
# Snagem makes `AreaStoryByteMemory` write `story_bytes.SNAGEM_BASE_FLOOR` (0x62) and they walk in.
TRAVEL_SHUFFLE_REROUTED_EDGES: "dict[str, str]" = {
    "Cipher Key Lair (exterior)": "Kaminko's House (Robo Groudon)",
}

# Every region the graph names, in a stable order (first appearance).
REGION_NAMES: "tuple[str, ...]" = tuple(
    dict.fromkeys([edge[1] for edge in REGION_EDGES])
)

# A reroute has to name a real edge and a real region, or it is a typo that silently changes nothing.
assert all(target in REGION_NAMES and source in REGION_NAMES
           for target, source in TRAVEL_SHUFFLE_REROUTED_EDGES.items()), (
    "ADDENDUM 293: a rerouted edge names a region the graph does not have"
)
assert all(any(edge[1] == target for edge in REGION_EDGES)
           for target in TRAVEL_SHUFFLE_REROUTED_EDGES), (
    "ADDENDUM 293: a rerouted edge names a target nothing connects to, so the reroute would do nothing"
)

# Retired. Kept so older slot data and the tests that referenced them still import.
REGION_CHAIN: list[str] = list(REGION_NAMES)
MEMOS_REQUIRED: list[int] = [0] * len(REGION_CHAIN)


def create_and_connect_regions(world) -> None:
    menu = Region("Menu", world.player, world.multiworld)
    world.multiworld.regions.append(menu)

    regions = create_regions_and_locations(world)

    # The Parts are a key, not a finish line: they gate the Citadark Isle entrance, not the goal.
    parts_for_citadark = (int(world.options.robo_kyogre_parts_required)
                          if world.options.robo_kyogre_parts_unlock_citadark else 0)
    travel_shuffle = bool(world.options.randomize_travel_locations)

    # Create any graph region locations.py did not already make (it only makes regions that hold locations).
    for region_name in REGION_NAMES:
        if region_name not in regions:
            region = Region(region_name, world.player, world.multiworld)
            world.multiworld.regions.append(region)
            regions[region_name] = region

    # An access rule may only name an item that actually enters the pool: `all_state` never holds one that was
    # never created, so naming it makes every region past that edge unreachable -- the Elevator Key gate once
    # took out Outskirt Stand, Snagem, the Key Lair and Citadark at once.
    shuffle_key_items = bool(getattr(world.options, "key_item_shuffle", 1))
    # Independent of the above and of travel randomization: one option covering both travel modes.
    shuffle_scooter = bool(getattr(world.options, "shuffle_scooter_upgrade", 0))

    def _item_is_in_the_pool(item_name: str) -> bool:
        if item_name in items.NEVER_SHUFFLED_KEY_ITEM_NAMES:
            return False
        if item_name in items.ITEMS_REMOVED_FROM_POOL:
            return False
        if item_name in items.GATING_KEY_ITEM_NAMES:
            return shuffle_key_items
        # The Scooter follows its own option, which is what makes `shuffle_scooter_upgrade` off mean "SS Libra
        # is ungated" rather than "sealed".
        if item_name in items.OPTION_GATED_PROGRESSION_ITEMS:
            return shuffle_scooter
        return True

    def _required_items(required: "tuple[str, ...]", target: str) -> "tuple[str, ...]":
        """The pool item names one edge into `target` really needs, after translation and pool filtering."""
        # REGION_EDGES names "Data ROM" because that is what the game requires; the ROM and the ID Card ship
        # as one item. Translating here keeps the table a description of the game, not of the item pool.
        names = [items.requirement_to_pool_item(name) for name in required]
        names = [name for name in dict.fromkeys(names) if _item_is_in_the_pool(name)]
        # The Cipher Lab / Data ROM split -- see REGION_EDGES' own comment for why this cannot be one rule.
        data_rom = items.requirement_to_pool_item("Data ROM")
        if target == "Cipher Lab" and travel_shuffle and _item_is_in_the_pool(data_rom):
            names = [data_rom]
        return tuple(names)

    def _edge_rule(required: "tuple[str, ...]", target: str):
        """The access rule for one edge. `None` means unconditional, which AP wants rather than a lambda that
        always returns True."""
        names = _required_items(required, target)
        parts = parts_for_citadark if target == "Citadark Isle" else 0
        if not names and not parts:
            return None

        def rule(state, names=names, parts=parts):
            for item_name in names:
                if not state.has(item_name, world.player):
                    return False
            if parts and state.count(items.MACGUFFIN_ITEM_NAME, world.player) < parts:
                return False
            return True

        return rule

    # With travel randomization on the story chain is not a second way in: Client.enforce_travel_locks holds
    # every not-yet-received destination's map bit clear each tick. Measured before this, a travel-shuffle
    # world holding every progression item except the twelve travel unlocks still reached all 675 locations.
    # So the chain edge is suppressed for regions whose bit is really held clear (derived from the client's own
    # exempt set, so the two cannot drift), and its item requirement moves onto the gateway. Regions with no
    # unlock of their own keep chaining, which keeps the Music Disc, Mayor's Note, System Lever and Parts
    # load-bearing.
    gateway_only: "frozenset[str]" = (
        travel_locations.gateway_only_regions() if travel_shuffle else frozenset()
    )
    gateway_extra_items: "dict[str, tuple[str, ...]]" = {}

    # `gateway_only` is one region per destination, but a map icon often covers several
    # (`story_bytes.AREA_GROUPS`). A sibling tier is reached through the game once the icon let you into the
    # area, so its chain edge must survive and gain the destination's item; suppressing it strands it, since
    # the gateway connects to its own target only.
    sibling_travel_item: "dict[str, str]" = (
        travel_locations.travel_item_by_sibling_region() if travel_shuffle else {}
    )

    for source, target, required in REGION_EDGES:
        if target in gateway_only:
            carried = _required_items(required, target)
            if carried:
                gateway_extra_items[target] = carried
            continue
        # Applied here, not in REGION_EDGES: the game's own route to the Key Lair really does run through the
        # ship. What changes is the route AP may assume, in the mode where the client delivers the other one.
        if travel_shuffle:
            source = TRAVEL_SHUFFLE_REROUTED_EDGES.get(target, source)
        origin = menu if source == "Menu" else regions[source]
        rule = _edge_rule(required, target)
        needed_item = sibling_travel_item.get(target)
        if needed_item is not None:
            def rule(state, _base=rule, _item=needed_item, _player=world.player):
                if not state.has(_item, _player):
                    return False
                return True if _base is None else _base(state)
        if rule is None:
            origin.connect(regions[target], name=f"{source} -> {target}")
        else:
            origin.connect(regions[target], name=f"{source} -> {target}", rule=rule)

    # Checked live by the client when it detects a species, not by walking anywhere, so it hangs off Menu.
    menu.connect(regions["Pokemon Storage"], name="Menu -> Pokemon Storage")

    # Same for the 32 cumulative purification-count locations: checked off the purification-count tracker.
    menu.connect(regions["Shadow Pokemon Purification"], name="Menu -> Shadow Pokemon Purification")

    # No "Chest Opening", "Shop Purchases" or "Travel Unlocks" region any more: chests, shop lines and unlock
    # checks are places, so locations.py files each in the region that contains it. The chest bucket was once
    # created but never connected, leaving all 90 chest locations unreachable.

    # The 232 cumulative trainer-defeat counts are counts, not places, so this bucket stays -- wired up
    # explicitly because it is the same shape as that orphaned one. The 66 named "Defeat - {trainer}"
    # locations live in real story regions.
    menu.connect(regions["Trainer Defeat Count"], name="Menu -> Trainer Defeat Count")
    # In cumulative mode this region exists but holds no locations, which is harmless.
    if "Unique Trainer Defeats" in regions:
        menu.connect(regions["Unique Trainer Defeats"], name="Menu -> Unique Trainer Defeats")

    # No locations and no chain edge: the travel gateway is the only way in and nothing depends on reaching
    # it. Created unconditionally so TRAVEL_LOCATION_TARGET_REGION always resolves; unreachable with travel
    # randomization off, which costs nothing for an empty region.
    orre = Region(travel_locations.ORRE_COLOSSEUM_REGION, world.player, world.multiworld)
    world.multiworld.regions.append(orre)
    regions[travel_locations.ORRE_COLOSSEUM_REGION] = orre

    # Agate Village's sub-area: no extra requirement, since reaching Agate already implies reaching it.
    relic_forest = Region("Relic Forest", world.player, world.multiworld)
    world.multiworld.regions.append(relic_forest)
    regions["Agate Village"].connect(relic_forest, name="Agate Village -> Relic Forest")
    regions["Relic Forest"] = relic_forest  # so the travel-gateway block below can look it up

    # Mt. Battle is an ordinary REGION_EDGES entry: the story-byte compilation puts it at 0x23 -> 0x24,
    # straight off Agate Village. Creating it a second time here is what the region cache rejects.

    # Each TRAVEL_LOCATION_BITS destination gets a small empty "gateway" region connecting unconditionally
    # into whichever region TRAVEL_LOCATION_TARGET_REGION names. Every `state.can_reach` elsewhere benefits
    # for free: can_reach does not care which entrance got you there.
    if world.options.randomize_travel_locations:
        # Region prerequisites are entrances, not `can_reach` calls inside an entrance rule: a rule sees the
        # reachability from the PREVIOUS pass, so a chain of them resolves one link per pass. Measured on the
        # first cut, `all_state` called SS Libra, Snagem and the Key Lair unreachable while holding every item
        # in the pool, and took four passes to settle. A hard prerequisite
        # (`TRAVEL_LOCATION_REQUIRED_REGIONS`) is an AND -- one entrance, sourced there; an adjacency
        # (`TRAVEL_LOCATION_ADJACENCY`) is an OR -- one entrance per branch.
        for name, target_region_name in travel_locations.TRAVEL_LOCATION_TARGET_REGION.items():
            gateway = Region(f"Travel Gateway - {name}", world.player, world.multiworld)
            world.multiworld.regions.append(gateway)
            item_name = travel_locations.travel_unlock_item_name(name)
            adjacency = travel_locations.TRAVEL_LOCATION_ADJACENCY.get(name)
            # Hard region prerequisites, never satisfiable by an item -- without this the Snagem travel item
            # opened Snagem with no SS Libra, and the Key Lair item opened the Key Lair with no Snagem.
            required_regions = travel_locations.required_regions_for(name)
            # An AND of several regions cannot be one entrance, and none has needed more than one. Asserted
            # so adding a second fails loudly instead of silently dropping one.
            assert len(required_regions) <= 1, (
                f"{name}: more than one hard prerequisite region needs a different shape than one entrance"
            )
            # The item the suppressed chain edge carried: flying to Pyrite Town does not hand you the ID Card.
            carried_items = gateway_extra_items.get(target_region_name, ())
            base_source = regions[required_regions[0]] if required_regions else menu

            def _has_all(state, names):
                for one in names:
                    if not state.has(one, world.player):
                        return False
                return True

            def _entry_rule(extra_any=()):
                """Hold the unlock item, plus whatever the suppressed chain edge required, plus (when given)
                any ONE of `extra_any`."""
                def rule(state, item_name=item_name, carried_items=carried_items, extra_any=tuple(extra_any)):
                    if not state.has(item_name, world.player):
                        return False
                    if not _has_all(state, carried_items):
                        return False
                    if not extra_any:
                        return True
                    for one in extra_any:
                        if state.has(one, world.player):
                            return True
                    return False
                return rule

            if adjacency is None:
                base_source.connect(gateway, name=f"{base_source.name} -> Travel Gateway - {name}",
                                    rule=_entry_rule())
            else:
                # One entrance per OR-branch. The sibling-item branch keeps the base source (its requirement
                # is an item, not a place); each adjacency region becomes its own entrance.
                if adjacency.sibling_items:
                    siblings = tuple(travel_locations.travel_unlock_item_name(sib)
                                     for sib in adjacency.sibling_items)
                    base_source.connect(
                        gateway,
                        name=f"{base_source.name} -> Travel Gateway - {name} (sibling)",
                        rule=_entry_rule(siblings),
                    )
                for region_name in adjacency.regions:
                    regions[region_name].connect(
                        gateway,
                        name=f"{region_name} -> Travel Gateway - {name}",
                        rule=_entry_rule(),
                    )

            gateway.connect(regions[target_region_name], name=f"Travel Gateway - {name} -> {target_region_name}")

        # Kaminko, Gateon, Agate and Pokemon HQ Lab are the four open by default in this mode. Gateon and HQ
        # already sit in the always-open "Outskirt Stand" bucket, but Kaminko Mansion's content is bucketed
        # under "Agate Village", so Agate needs this extra entrance alongside its chain edge.
        menu.connect(regions["Agate Village"], name="Menu -> Agate Village (always open)")

    citadark = regions["Citadark Isle"]

    # The win condition is an event: capture/defeat the Cipher Boss.
    boss_region = citadark
    victory_location = PokemonXDLocation(world.player, EVENT_LOCATION_NAME, None, boss_region)
    victory_location.place_locked_item(
        PokemonXDItem("Victory", ItemClassification.progression, None, world.player)
    )
    # Ein File S does not exist as an item in the game and is out of the pool, so victory depends on nothing
    # but reaching Citadark Isle, which the Parts already gate. Real win detection is in Client.py: Greevil's
    # rematch, or story byte 0x78 as a backstop.
    boss_region.locations.append(victory_location)

    world.multiworld.completion_condition[world.player] = lambda state: state.has("Victory", world.player)
