"""Regression coverage for the "Randomize Travel Locations" YAML option (ADDENDUM 104, 2026-09-09) -- both the
item-gated region graph (regions.py) and the "Catch - {species}" area gating that rides on the same
`state.can_reach()` mechanism (rules.py).

RETARGETED 2026-09-13 (ADDENDUM 168). Every "with no memos" / "collect N Krane Memos" step in this file is now
a prefix of PokemonXDTestBase.KEY_ITEM_CHAIN, because the memo ladder is gone and regions.REGION_EDGES gates
21 real regions on the real story key items. Two of the retargets are more than a rename, and are called out
where they happen:

  * **Outskirt Stand is no longer the always-open first region** -- it is now reached via Cipher Key Lair
    (exterior), late. The always-open start is Pokemon HQ Lab / Kaminko's House / Gateon Port.
  * **Phenac City is no longer unconditionally open either**, which turns ADDENDUM 105's disclosed limitation
    (the SS Libra adjacency rule being trivially satisfiable) into a rule that actually bites.
"""
from __future__ import annotations

from . import PokemonXDTestBase
from ..locations import trainer_defeat_count_location_name
from ._chest_samples import DEEPEST_CHEST, EARLIEST_CHEST
from ..options import TrainerDefeatCheckCount
from .. import items, rules, species, travel_locations

# The trainer thresholds, so a probe can be picked from the bucket it really belongs to rather than from a
# number that was true under the pre-ADDENDUM-168 region order.
_TRAINER_THRESHOLDS = rules._cumulative_region_thresholds(rules._TRAINER_WEIGHT_BY_REGION)


def _first_count_in_bucket(region_name: str) -> int:
    """The lowest cumulative-trainer count rules.py maps into `region_name`."""
    for count in range(1, TrainerDefeatCheckCount.range_end + 1):
        if rules._region_for_sphere_count(_TRAINER_THRESHOLDS, count) == region_name:
            return count
    raise AssertionError(f"no trainer threshold lands in {region_name!r}")


class TestTravelLocationsOptionOff(PokemonXDTestBase):
    """Default (option off) -- must be byte-for-byte unaffected by ADDENDUM 104's changes."""

    # ADDENDUM 196: the named-66 "Defeat - {trainer}" locations this class probes exist only in CUMULATIVE
    # mode, which stopped being the default when the player's YAML became the template.
    options = {"randomize_chests": True, "shuffle_trainer_defeats": True, "trainer_defeat_mode": 0}

    def test_no_travel_unlock_items_in_the_pool(self) -> None:
        item_names = {item.name for item in self.multiworld.itempool}
        for name in travel_locations.TRAVEL_LOCATION_NAMES:
            self.assertNotIn(travel_locations.travel_unlock_item_name(name), item_names)

    def test_the_always_open_start_is_reachable_and_outskirt_stand_is_not(self) -> None:
        """RETARGETED 2026-09-13 (ADDENDUM 168), was "Outskirt Stand still reachable from the start with no
        memos" (asserted via an always-open-region chest).

        Outskirt Stand was this world's always-open first region; ADDENDUM 168's real graph reaches it through
        Cipher Key Lair (exterior), which is deep. The always-open start is now Pokemon HQ Lab, Kaminko's House
        and Gateon Port, and the sphere logic still has to have SOMETHING in sphere 0 -- the real chest census
        gives Pokemon HQ Lab real chests, so EARLIEST_CHEST stays reachable with nothing collected.

        The second half is the change actually worth protecting, and is new here: Outskirt Stand must NOT be
        reachable from the start any more. A silent revert to the old always-open node would otherwise look
        identical to a passing suite.
        """
        self.assertTrue(self.can_reach_location(EARLIEST_CHEST))
        for region_name in ("Pokemon HQ Lab", "Kaminko's House", "Gateon Port"):
            self.assertTrue(self.multiworld.state.can_reach(region_name, player=self.player), region_name)
        self.assertFalse(self.multiworld.state.can_reach("Outskirt Stand", player=self.player),
                         "Outskirt Stand is a LATE region as of ADDENDUM 168")

    def test_agate_village_needs_the_machine_part_with_the_option_off(self) -> None:
        """RETARGETED 2026-09-13 (ADDENDUM 169), then REVERSED later the SAME DAY, and RENAMED with it -- the
        old name (`test_agate_village_is_open_with_the_option_off_but_mt_battle_is_not`) asserted the exact
        opposite of the behaviour the player asked for, so leaving it in place would have been worse than the
        rename.

        WHY THE SAME-DAY FLIP IS NOT CHURN. ADDENDUM 169's first cut read the player's standing instruction
        ("the only locations I want open by default are Kaminko, Gateon, Agate and Pokemon HQ Lab") as applying
        in every mode, and put `("Menu", "Agate Village", ())` into regions.REGION_EDGES. The player corrected
        that within the day: "Leave Agate, Kaminko and Gateon locked by default if travel randomization is off.
        Let them unlock normally." The instruction was always about randomize_travel_locations, where every
        OTHER destination is a receivable item and these four are the exceptions -- with travel randomization
        OFF there are no destination items to be an exception to, so there is nothing to open "by default" and
        the player simply walks the vanilla route. So the four-always-open rule now lives ONLY in the
        randomize_travel_locations-on branch of regions.py, and its option-on twin is
        TestTravelLocationsOptionOn.test_the_four_always_open_areas_are_reachable_with_nothing_collected.

        WHAT SURVIVED, and is asserted first: Pokemon HQ Lab, Kaminko's House and Gateon Port are still
        reachable with nothing collected. They are no longer wired to Menu individually -- they chain off
        Pokemon HQ Lab with empty requirements -- so "reachable with nothing" is a property of the chain now
        and worth pinning rather than assuming.

        WHAT CAME BACK: the Machine Part gates Agate Village, exactly as this test asserted before ADDENDUM
        169 touched it. Both directions are asserted, because each without the other is a different bug: Agate
        silently unlocked again (the vanilla route collapses and the player's correction is undone), or the
        Machine Part silently demoted to flavour. Mt. Battle is checked alongside it, since it now INHERITS the
        Machine Part through Agate instead of naming it -- an edge that is easy to lose without noticing.
        """
        # The guarantee that survived the reversal: the vanilla route's first three stops cost nothing.
        for region_name in ("Pokemon HQ Lab", "Kaminko's House", "Gateon Port"):
            self.assertTrue(self.multiworld.state.can_reach(region_name, player=self.player), region_name)

        # ...and Agate is behind the Machine Part again, with its own content and Kaminko Mansion's Chobin
        # (bucketed into Agate Village by trainer_defeat.py) behind it.
        self.assertFalse(self.multiworld.state.can_reach("Agate Village", player=self.player),
                         "the Machine Part must gate Agate Village again with the option off")
        self.assertFalse(self.multiworld.state.can_reach("Mt. Battle", player=self.player))
        self.assertFalse(self.can_reach_location("Agate Bridge Chest"))
        self.assertFalse(self.can_reach_location("Defeat - Researcher Chobin"))

        self.collect_key_item_chain(1)  # the Machine Part -- Gateon Port -> Agate Village
        self.assertTrue(self.multiworld.state.can_reach("Agate Village", player=self.player))
        self.assertTrue(self.can_reach_location("Agate Bridge Chest"))
        self.assertTrue(self.can_reach_location("Defeat - Researcher Chobin"))
        self.assertTrue(self.multiworld.state.can_reach("Mt. Battle", player=self.player),
                        "Mt. Battle inherits the Machine Part through Agate Village")


class TestTravelLocationsOptionOn(PokemonXDTestBase):
    options = {
        "randomize_chests": True,
        "shuffle_trainer_defeats": True,
        "randomize_travel_locations": True,
        # ADDENDUM 196: the named-66 and the cumulative ladder are both probed below, so the mode is pinned;
        # and the Parts gate now defaults ON while DEEPEST_CHEST sits in Citadark, which these tests reach
        # without ever collecting a Part.
        "trainer_defeat_mode": 0,
        "robo_kyogre_parts_unlock_citadark": False,
        # Raised to the ceiling so every bucket the tests below probe really has a location in it. (ADDENDUM
        # 168: the original reason was "so a threshold inside Mt. Battle's bucket exists" -- Mt. Battle's block
        # now starts at count 5, but keeping the ceiling costs nothing and the Pyrite Town probe wants room.)
        "trainer_defeat_check_count": TrainerDefeatCheckCount.range_end,
    }

    def test_every_travel_unlock_item_is_in_the_pool(self) -> None:
        item_names = {item.name for item in self.multiworld.itempool}
        for name in travel_locations.TRAVEL_LOCATION_NAMES:
            self.assertIn(travel_locations.travel_unlock_item_name(name), item_names)

    def test_every_travel_unlock_item_is_progression(self) -> None:
        for name in travel_locations.TRAVEL_LOCATION_NAMES:
            item_name = travel_locations.travel_unlock_item_name(name)
            self.assertEqual(items.ITEM_TABLE[item_name].classification.name, "progression")

    def test_receiving_a_destinations_unlock_is_an_independent_path_in(self) -> None:
        """RETARGETED 2026-09-13 (ADDENDUM 168), was "receiving Mt. Battle unlock makes Mt. Battle reachable
        with no memos"; RETARGETED BACK to Mt. Battle the same day (ADDENDUM 169); and now RETARGETED to Pyrite
        Town again, still the same day, because ADDENDUM 169 was itself partly reversed.

        SAME-DAY REVERSAL, and why the probe keeps moving. The property under test never changed: receiving a
        destination's own `Travel Unlock` item is an ADDITIONAL entrance into that destination, working with
        zero key items collected. What changes is which destination this seed can actually demonstrate it on --
        a probe only proves anything if the region is CLOSED before the unlock arrives.

          * ADDENDUM 168 hung Mt. Battle off Agate Village while this option's own block already connected
            Menu -> Agate Village unconditionally (ADDENDUM 106), so Mt. Battle was open turn one and the probe
            moved to Pyrite Town.
          * ADDENDUM 169 put the Machine Part on the Agate -> Mt. Battle edge, which closed Mt. Battle again,
            so the probe moved back.
          * The player then corrected ADDENDUM 169 ("Leave Agate, Kaminko and Gateon locked by default if
            travel randomization is off. Let them unlock normally."), which moved the Machine Part back onto
            Gateon Port -> Agate Village. With this option ON, Menu -> Agate Village is still unconditional --
            that branch is where ADDENDUM 106's four-always-open rule now exclusively lives -- and Mt. Battle
            hangs off Agate with no requirement of its own, so Mt. Battle is open turn one once more.

        Pyrite Town is the probe that survives all of this, because it sits behind the Data ROM twice over
        (Mt. Battle -> Cipher Lab takes it when travel randomization is on, Cipher Lab -> Pyrite Town takes it
        again) and has no adjacency requirement, so the unlock item ALONE must be enough. Mt. Battle's
        turn-one reachability is asserted rather than merely described, so this docstring cannot go stale
        without the test saying so -- and so that the day Mt. Battle closes again, whoever sees the failure
        knows the probe may move back here rather than that something broke. (Same class of care as ADDENDUM
        162/164 took in test_a_gated_species_becomes_reachable_only_once_its_area_is below: pick a probe the
        seed can actually exercise instead of one that passes vacuously.)
        """
        # RETARGETED 2026-09-14 (ADDENDUM 190). The whole "which destination can serve as the probe" problem
        # above is gone, and the reason is worth keeping: every destination with a travel unlock is now
        # CLOSED until its item arrives, because the client holds its map bit clear. Mt. Battle no longer
        # hangs off Agate at all in this mode, so it is a fine probe again -- and the assertion below is the
        # opposite of the one this test used to make about it.
        self.assertFalse(self.multiworld.state.can_reach("Mt. Battle", player=self.player),
                         "with travel randomization ON the client re-locks Mt. Battle until its item "
                         "arrives, so the graph must not offer the Agate Village chain edge")
        self.collect_by_name("Travel Unlock - Mt. Battle")
        self.assertTrue(self.multiworld.state.can_reach("Mt. Battle", player=self.player))

        probe = trainer_defeat_count_location_name(_first_count_in_bucket("Pyrite Town"))
        self.assertFalse(self.multiworld.state.can_reach("Pyrite Town", player=self.player),
                         "the probe must be CLOSED with nothing collected or the unlock proves nothing")
        self.assertFalse(self.can_reach_location(probe))

        # Pyrite needs its unlock AND the Data ROM -- the requirement its suppressed chain edge carried.
        self.collect_by_name("Travel Unlock - Pyrite Town")
        self.collect_by_name(_pool_item("Data ROM"))
        self.assertTrue(self.multiworld.state.can_reach("Pyrite Town", player=self.player))
        self.assertTrue(self.can_reach_location(probe))
    def test_receiving_realgam_tower_unlock_does_not_grant_citadark_isle(self) -> None:
        # The extra travel-item path only ever reaches the ONE target region it's wired to (travel_locations.
        # TRAVEL_LOCATION_TARGET_REGION) -- it must never leak into unlocking the rest of the memo-gated chain
        # past that point.
        self.collect_by_name("Travel Unlock - Realgam Tower")
        self.assertFalse(self.can_reach_location(DEEPEST_CHEST))  # a Citadark Isle chest specifically

    def test_the_story_chain_is_not_a_second_way_in(self) -> None:
        """INVERTED 2026-09-14 (ADDENDUM 190). This test used to assert the exact contract that was the bug.

        It was written as "the travel-item path is additive, never a replacement, so walking the chain must
        still open the whole world", which was ADDENDUM 104's design and true when written. ADDENDUM 171 then
        made the client HOLD every not-yet-received destination's map bit clear on every tick, so the story
        unlock is taken back as fast as the game grants it -- and this test went on pinning the old promise,
        which is why the graph kept it for nineteen addenda.

        The property now is the opposite one, and it is the player's: key items alone get you nowhere the map
        will not take you."""
        self.collect_key_item_chain()
        self.assertFalse(self.can_reach_location(DEEPEST_CHEST),
                         "the key-item chain walked into Citadark Isle without a single travel unlock")
        for destination in ("Mt. Battle", "Cipher Lab", "Pyrite Town", "Poke Spots", "Realgam Tower",
                            "Phenac City", "SS Libra", "Outskirt Stand", "Snagem Hideout", "Cipher Key Lair"):
            self.collect_by_name(travel_locations.travel_unlock_item_name(destination))
        self.assertTrue(self.can_reach_location(DEEPEST_CHEST),
                        "with every unlock AND every key item, the whole world must open")
        self.assertTrue(self.can_reach_location(
            trainer_defeat_count_location_name(TrainerDefeatCheckCount.range_end)))

    def test_gateon_port_is_not_a_travel_unlock_item(self) -> None:
        # ADDENDUM 106 (2026-09-10, player request: "the only locations I want open by default are Kaminko,
        # Gateon, Agate and Pokemon HQ Lab") -- Gateon Port moved to always-open, no item at all.
        item_names = {item.name for item in self.multiworld.itempool}
        self.assertNotIn("Travel Unlock - Gateon Port", item_names)

    def test_the_four_always_open_areas_are_reachable_with_nothing_collected(self) -> None:
        """ADDENDUM 106, player request: "the only locations I want open by default are Kaminko, Gateon, Agate
        and Pokemon HQ Lab." All four must be reachable turn one, with zero items collected.

        RETARGETED 2026-09-13 (ADDENDUM 168) from location-level to REGION-level, which is the level the
        guarantee now lives at. ADDENDUM 168 gave three of the four areas real regions of their own (Pokemon HQ
        Lab, Kaminko's House, Gateon Port, all unconditional off Menu) and Agate Village kept this option's own
        unconditional gateway.

        ADDENDUM 169 (2026-09-13) briefly moved ("Menu", "Agate Village", ()) into regions.REGION_EDGES itself,
        making all four areas unconditional in EVERY mode, and this docstring said so. REVERSED later the same
        day, on the player's correction ("Leave Agate, Kaminko and Gateon locked by default if travel
        randomization is off. Let them unlock normally."): the four-always-open rule is a randomize_travel_
        locations rule and nothing else, so THIS class's option is once again exactly what makes the assertion
        below pass, via the unconditional Menu -> Agate Village connection in regions.py's travel block. The
        option-off twin of this test asserts the opposite for Agate and the same for the other three:
        TestTravelLocationsOptionOff.test_agate_village_needs_the_machine_part_with_the_option_off.

        RESOLVED 2026-09-13, later the same day. This test used to end by asserting that "Gateon Port - Krabby
        Club Basement Item" and "Outskirt Stand - HQ Lab Potions" were still filed in the pre-168 "Outskirt
        Stand" location bucket -- a deliberate tripwire, placed so that the day someone re-bucketed them the
        test would say so rather than quietly passing. ADDENDUM 169's `_REBUCKET_BY_NAME` in locations.py is
        that day: each location now lives in the region its own NAME states. So the assertion flips from
        "still mis-filed" to the real guarantee the player asked for -- the always-open areas hold checks that
        are reachable with nothing collected, at LOCATION level and not merely at region level.
        """
        for region_name in ("Pokemon HQ Lab", "Kaminko's House", "Gateon Port", "Agate Village"):
            self.assertTrue(self.multiworld.state.can_reach(region_name, player=self.player), region_name)
        self.assertTrue(self.can_reach_location("Defeat - Researcher Chobin"))  # Kaminko Mansion / Agate Village
        self.assertTrue(self.can_reach_location("Agate Bridge Chest"))  # Agate Village's own content

        from ..locations import LOCATION_TABLE

        for name, expected_region in (
            # ADDENDUM 237: was "Gateon Port - Krabby Club Basement Item", retired as a duplicate of the
            # per-chest location below. The probe only needs A Gateon Port location; the chest is
            # the one that is actually detectable.
            ("Krabby Klub Basement Chest", "Gateon Port"),
            # ADDENDUM 237: "Outskirt Stand - HQ Lab Potions" was retired -- the census matched it to chest
            # 3, which holds the same three Potions. The Eevee gift survives (a hand-over, not a box) and
            # still carries the re-bucket this test exists to prove.
            ("Outskirt Stand - Eevee Gift", "Pokemon HQ Lab"),
        ):
            self.assertEqual(LOCATION_TABLE[name].region, expected_region, name)
        # The point of the re-bucket: these are checkable with nothing collected, not just filed correctly.
        self.assertTrue(self.can_reach_location("Krabby Klub Basement Chest"))
        # ADDENDUM 237: the reachability probe is a chest now. "Outskirt Stand - Eevee Gift" is still filed
        # in this region (asserted above, which is what the re-bucket test is about) but carries its own
        # access rule, so it is not the right thing to assert is reachable with nothing collected.
        self.assertTrue(self.can_reach_location("Outside HQ Lab"))


def _pool_item(requirement: str) -> str:
    """ADDENDUM 190: the edge tables name what the GAME needs; this is what actually enters the pool."""
    from ..items import requirement_to_pool_item

    return requirement_to_pool_item(requirement)


class TestTravelLocationAdjacency(PokemonXDTestBase):
    """ADDENDUM 105 (2026-09-10, player question: "Did you ensure that outskirt stand is logically locked
    behind one of the places we discussed, and that the SS Libra location is also logically behind phenac
    city?") -- exercises the gateway ENTRANCE's own access_rule directly (via can_reach_entrance) rather than
    overall region reachability. That distinction matters here: both "Outskirt Stand" and "Phenac City" are
    ALSO the base story chain's own unconditionally-open first two links (regions.MEMOS_REQUIRED[0] ==
    MEMOS_REQUIRED[1] == 0, a deliberate anti-"restrictive-start" design choice -- see regions.py's own
    comment), so state.can_reach() on either region name is trivially True from turn one regardless of
    whether this fix does anything. Checking the gateway entrance in isolation is the only way to see the new
    adjacency constraint actually take effect.

    RETARGETED 2026-09-13 (ADDENDUM 168): that entire caveat is obsolete in the best way. Neither Outskirt Stand
    nor Phenac City is unconditionally open any more -- Outskirt Stand is late (via Cipher Key Lair (exterior))
    and Phenac City needs the Machine Part and the Data ROM -- so the adjacency rules ADDENDUM 105 added are now
    load-bearing rather than trivially satisfied. The entrance-level checks are kept anyway, because testing the
    rule in isolation is still the right way to test the rule."""

    options = {"randomize_travel_locations": True}

    def test_outskirt_stand_needs_the_item(self) -> None:
        """RETARGETED 2026-09-14 (ADDENDUM 190), from the gateway ENTRANCE to the region itself.

        These tests checked `can_reach_entrance("Menu -> Travel Gateway - X")` because the gateway was one
        entrance off Menu and the region itself was reachable another way anyway -- the story chain -- so only
        the entrance could show the adjacency rule working. Two things changed. The chain no longer walks into
        these regions at all, so region reachability IS the rule now; and a region prerequisite is expressed
        as the entrance's SOURCE rather than as a `can_reach` call inside it, which means there is more than
        one entrance per gateway and no single name to assert on. Asserting on the region is both more honest
        and less brittle."""
        self.assertFalse(self.multiworld.state.can_reach("Outskirt Stand", player=self.player))

    def test_outskirt_stand_stays_closed_on_the_item_alone_with_no_real_neighbor_yet(self) -> None:
        # No sibling travel item, and Pyrite Town isn't reachable yet -- the item alone must not be enough.
        # This is the concrete behaviour the player was asking about in ADDENDUM 105.
        self.collect_by_name("Travel Unlock - Outskirt Stand")
        self.assertFalse(self.multiworld.state.can_reach("Outskirt Stand", player=self.player))

    def test_outskirt_stand_opens_once_pyrite_town_is_reachable(self) -> None:
        # RETARGETED 2026-09-14 (ADDENDUM 190): Pyrite Town is now reached with its own travel unlock plus the
        # Data ROM its suppressed chain edge carried, not by walking the key-item chain. The adjacency
        # requirement being tested -- Outskirt Stand needs a real neighbour, and Pyrite Town is one -- is
        # unchanged.
        self.collect_by_name("Travel Unlock - Outskirt Stand")
        self.collect_by_name("Travel Unlock - Pyrite Town")
        self.collect_by_name(_pool_item("Data ROM"))
        self.assertTrue(self.multiworld.state.can_reach("Pyrite Town", player=self.player))
        self.assertTrue(self.multiworld.state.can_reach("Outskirt Stand", player=self.player))

    def test_outskirt_stand_opens_via_a_sibling_travel_item_alone(self) -> None:
        # The Poke Spots and Snagem Hideout are the two other real destinations in Outskirt Stand's own
        # confirmed in-location travel menu (ADDENDUM 85) -- HOLDING either one's item counts as "you could
        # have got here from a real neighbour", whether or not that neighbour is itself reachable yet. That
        # OR-branch is why this gateway keeps an entrance off Menu alongside its Pyrite Town one.
        # RETARGETED by ADDENDUM 293. The sibling used to be an unreachable place as well as a held item,
        # because Snagem's own gateway was sourced at SS Libra -- so holding its item opened nothing. That
        # prerequisite is withdrawn ("Snagem is no longer gated behind SS libra"), and Snagem now opens on
        # its item alone, which makes it a poor witness for "a HELD item is enough on its own".
        #
        # The Poke Spots are the other sibling in Outskirt Stand's own confirmed travel menu, and they are
        # still gated on the Data ROM their suppressed chain edge carries -- so the OR-branch under test is
        # demonstrated the way it was meant to be: the item is held, the place is NOT reachable, and
        # Outskirt Stand opens anyway.
        self.collect_by_name(["Travel Unlock - Outskirt Stand", "Travel Unlock - Poke Spots"])
        self.assertFalse(self.multiworld.state.can_reach("Poke Spots", player=self.player),
                         "the sibling is a held ITEM, not a reachable place -- otherwise this proves nothing")
        self.assertTrue(self.multiworld.state.can_reach("Outskirt Stand", player=self.player))

    def test_ss_libra_needs_the_item(self) -> None:
        self.assertFalse(self.multiworld.state.can_reach("SS Libra", player=self.player))

    def test_ss_libra_really_requires_phenac_city_now(self) -> None:
        """The constraint the player asked for: "the SS Libra location is also logically behind phenac city".

        RETARGETED 2026-09-14 (ADDENDUM 190), and again (ADDENDUM 324) -- player: "We can still get SS Libra
        unlock before Phenac, which lets us access phenac out of logic ... ensure that SS Libra is ALWAYS
        unlocked after phenac." Reaching plain "Phenac City" is no longer enough, because that region is open
        from turn one; the gate is the CLEARED town, `Phenac City (Post-Sixes)`, which needs the Music Disc
        and the Mayor's Note. Every step of the ladder is asserted so a future loosening shows up here."""
        self.collect_by_name("Travel Unlock - SS Libra")
        self.assertFalse(self.multiworld.state.can_reach("SS Libra", player=self.player),
                         "the item alone must not be enough")
        self.collect_by_name("Travel Unlock - Phenac City")
        self.assertTrue(self.multiworld.state.can_reach("Phenac City", player=self.player))
        self.assertFalse(self.multiworld.state.can_reach("SS Libra", player=self.player),
                         "standing in Phenac is not clearing Phenac")
        self.collect_by_name("Music Disc")
        self.assertFalse(self.multiworld.state.can_reach("SS Libra", player=self.player),
                         "half the town is not the town")
        self.collect_by_name("Mayor's Note")
        self.assertTrue(self.multiworld.state.can_reach("Phenac City (Post-Sixes)", player=self.player))
        self.assertTrue(self.multiworld.state.can_reach("SS Libra", player=self.player))


class TestCatchPokemonAreaGating(PokemonXDTestBase):
    """ADDENDUM 104's "Catch - {species}" gating -- rides on the same region objects as the sphere logic, so
    this is exercised with randomize_travel_locations on (the fastest, most direct way to flip a specific
    region reachable without wrestling with the approximate memo-count thresholds)."""

    options = {"randomize_travel_locations": True}

    def test_eevee_is_always_exempt_from_area_gating(self) -> None:
        # locations.GUARANTEED_SPECIES_LOCATION -- must stay reachable with nothing collected at all, even
        # though this addendum's own gating mechanism exists and even if Eevee happens to appear on some named
        # trainer's real team.
        self.assertTrue(self.can_reach_location("Catch - Eevee"))

    def test_a_gated_species_becomes_reachable_only_once_every_part_of_its_gate_is(self) -> None:
        """REWRITTEN 2026-09-13 (ADDENDUM 183). This used to read `rules._SPECIES_TO_REGION` -- the ordinary-
        trainer census -- and grant one travel-unlock item. That table no longer drives catch rules at all
        (ADDENDUM 182 found it was the wrong population: it is built from DPKM team slots, and every species
        with a catch location comes from the DDPK shadow table or a Poke Spot). The contract to test now is the
        one the player specified: the snag floor AND the holding trainer's own region, ANDed.

        Order-independence, which the two earlier fixes to this test were both about, is preserved by the same
        means: a candidate is only accepted once it has been checked to be unreachable on an empty state and
        reachable after granting the whole gate, rather than assumed to be either.
        """
        from .. import rules

        gates, unplaceable = rules._catch_gates_for_species(self.multiworld.worlds[self.player])
        regions_with_a_travel_item = set(travel_locations.TRAVEL_LOCATION_TARGET_REGION.values())

        target = None
        for dex, sources in gates.items():
            if dex == rules._GUARANTEED_EEVEE_DEX or len(sources) != 1:
                continue  # a species with two sources is an OR, and a poor subject for a single-gate test
            gate = sources[0]
            if gate == "pokespot" or gate.required_items or gate.required_regions:
                continue
            needed = {gate.region, *rules._SNAG_FLOOR_REGIONS}
            if not needed <= regions_with_a_travel_item:
                continue  # nothing would flip it reachable, so it cannot exercise the gate
            name = species.location_name_for_species(dex)
            try:
                self.multiworld.get_location(name, 1)
            except KeyError:
                continue
            if self.can_reach_location(name):
                continue  # already open on an empty state -- proves nothing
            target = (name, needed)
            break

        self.assertIsNotNone(
            target,
            "no shadow-sourced species location found whose whole gate is travel-unlockable and which is "
            "closed on an empty state, so this seed's data cannot exercise the gate",
        )
        location_name, needed = target

        # ADDENDUM 190: a travel unlock is no longer sufficient on its own for the three destinations whose
        # suppressed chain edge carried a Data ROM requirement -- Cipher Lab, Pyrite Town and the Poke Spots,
        # two of which ARE the snag floor. Granted up front because it is an item, not a place, so it cannot
        # affect which REGIONS the assertions below are really testing.
        self.collect_by_name(_pool_item("Data ROM"))

        # Granting the trainer's own region is NOT enough on its own -- the snag floor is ANDed, not implied.
        gate_region = next(iter(needed - set(rules._SNAG_FLOOR_REGIONS)), None)
        if gate_region is not None:
            for travel_name, region_name in travel_locations.TRAVEL_LOCATION_TARGET_REGION.items():
                if region_name == gate_region:
                    self.collect_by_name(travel_locations.travel_unlock_item_name(travel_name))
                    break
            self.assertFalse(
                self.can_reach_location(location_name),
                "reaching the holding trainer's region must not be enough on its own -- Pyrite Town and the "
                "Miror Radar's Poke Spots chest are ANDed with it",
            )

        for region_name in rules._SNAG_FLOOR_REGIONS:
            for travel_name, target_region in travel_locations.TRAVEL_LOCATION_TARGET_REGION.items():
                if target_region == region_name:
                    self.collect_by_name(travel_locations.travel_unlock_item_name(travel_name))
                    break
        self.assertTrue(self.can_reach_location(location_name))
