"""ADDENDUM 324 -- the ship is behind the cleared Phenac, and two floors move.

Player, in three messages:
  * "We can still get SS Libra unlock before Phenac, which lets us access phenac out of logic - please ensure
     that SS Libra is ALWAYS unlocked after phenac - logically, phenac should always contain something to lead
     either to the ss libra, or indirectly lead to the ss libra."
  * "Also, make Snagem's new floor 0x63."
  * "And make Cipher Key Lair's floor 0x64."
"""
import unittest

from . import PokemonXDTestBase
from .. import travel_locations as tl
from ..game_data import story_bytes as sb


class TestTheShipIsBehindTheClearedTown(unittest.TestCase):
    def test_it_is_a_hard_prerequisite_now(self) -> None:
        self.assertEqual(("Phenac City (Post-Sixes)",), tl.required_regions_for("SS Libra"))

    def test_the_toothless_adjacency_is_gone(self) -> None:
        """It named plain "Phenac City", which is open from turn one -- the clause could never fail."""
        self.assertNotIn("SS Libra", tl.TRAVEL_LOCATION_ADJACENCY)

    def test_it_is_not_satisfiable_by_an_item(self) -> None:
        """An adjacency is an OR a sibling travel item can satisfy; a prerequisite is an AND about a place."""
        self.assertEqual((), tl.TRAVEL_LOCATION_ADJACENCY.get("SS Libra", tl.AdjacencyRequirement()).sibling_items)

    def test_the_gate_matches_the_vanilla_chain(self) -> None:
        from .. import regions

        self.assertIn(("Phenac City (Post-Sixes)", "SS Libra (stranded)", ("Elevator Key",)),
                      regions.REGION_EDGES)


class TestInARealTravelSeed(PokemonXDTestBase):
    options = {"randomize_travel_locations": True, "key_item_shuffle": True}

    def _reach(self, region):
        return self.multiworld.state.can_reach(region, player=self.player)

    def test_the_ship_needs_phenac_cleared(self) -> None:
        self.collect_by_name(["Travel Unlock - SS Libra", "Travel Unlock - Phenac City"])
        self.assertTrue(self._reach("Phenac City"))
        self.assertFalse(self._reach("SS Libra"), "the town being open is not the town being done")
        self.collect_by_name(["Music Disc", "Mayor's Note"])
        self.assertTrue(self._reach("SS Libra"))

    def test_everything_past_the_ship_inherits_it(self) -> None:
        """The player's second sentence: Phenac leads to the ship, so it leads to what the ship leads to."""
        self.collect_by_name(["Travel Unlock - SS Libra"])
        self.assertFalse(self._reach("SS Libra"))


class TestSnagemsFloor(unittest.TestCase):
    def test_it_is_0x62_again(self) -> None:
        """ADDENDUM 350 RETRACTS THIS ADDENDUM'S CHANGE, and the retraction is the point of the test.

        The player asked for 0x63 because entering at 0x62 did not build the hideout reliably. It did not,
        but not for the reason either of us assumed: a story write set the byte and left the variable's low
        three bits alone, so 0x62 meant 784..791 and only sometimes cleared 790. 0x63 meant 792..799, which
        always cleared it -- and never satisfied `hero_main`'s `== 790`, so Gonzap's scene could not run.
        With the write fixed, 0x62 is exactly 790 and does both jobs."""
        self.assertEqual(0x62, sb.SNAGEM_BASE_FLOOR)
        self.assertEqual(0x62, sb.region_floor("Snagem Hideout"))
        self.assertEqual(0x62, sb.area_entry_floor("Snagem Hideout"))

    def test_0x63_is_no_longer_named_as_the_unlocks_own_byte(self) -> None:
        opens = [t for t in sb.TRANSITIONS if "Snagem Hideout" in t.opens_regions]
        self.assertEqual(1, len(opens))
        self.assertEqual(0x62, opens[0].after)
        self.assertEqual((), opens[0].passthrough)
        self.assertTrue(sb.floor_is_accounted_for(0x62))


class TestTheKeyLairsFloor(unittest.TestCase):
    def test_the_icon_enters_at_the_overridden_floor(self) -> None:
        """This addendum's contribution is that the Lair has an OVERRIDE at all -- an icon value that wins over
        the area's first tier (0x5D, the exterior). ADDENDUM 371 raised the value from 0x64 to 0x67 on the
        player's instruction; the property this addendum established is that the override is what
        `area_entry_floor` returns, so it is asserted that way rather than against a literal in two places."""
        self.assertEqual(0x67, sb.AREA_ENTRY_FLOOR_OVERRIDES["Cipher Key Lair"])
        self.assertEqual(sb.AREA_ENTRY_FLOOR_OVERRIDES["Cipher Key Lair"],
                         sb.area_entry_floor("Cipher Key Lair"))
        self.assertGreater(sb.area_entry_floor("Cipher Key Lair"),
                           sb.region_floor("Cipher Key Lair (exterior)"),
                           "an override that does not beat the area's first tier is not an override")

    def test_the_icon_still_unlocks_at_the_exterior(self) -> None:
        """Crediting `Unlock - Cipher Key Lair` at 0x64 would be ADDENDUM 247's bug in reverse."""
        self.assertEqual(0x5D, sb.area_unlock_floor("Cipher Key Lair"))
        self.assertEqual(0x5D, tl.vanilla_unlock_story_byte("Cipher Key Lair"))

    def test_the_conditional_rule_is_gone(self) -> None:
        """RETARGETED 2026-09-26 (ADDENDUM 364) and again 2026-09-27 (ADDENDUM 371). The rule this addendum
        deleted was conditional on Snagem reaching 0x63 with a floor of 0x64 -- the same value as the override
        that replaced it, which is what made it dead. ADDENDUM 364 then added a rule at 0x67 on the Lair's OWN
        mark, and ADDENDUM 371 made 0x67 the floor outright, which killed that one for the identical reason.
        So the Lair has no rule again, and this is asserted by what makes a rule dead rather than by a literal
        -- which is why the same test survived both changes."""
        rules = [r for r in sb.AREA_FLOOR_RULES if r.target == "Cipher Key Lair"]
        # ADDENDUM 371: stated against the entry floor rather than against 0x64, because the floor moved and
        # the rule that is forbidden is "one that cannot bind", whatever the floor happens to be.
        self.assertEqual([], [r for r in rules if r.floor <= sb.area_entry_floor("Cipher Key Lair")],
                         "a rule at or below the entry floor is the dead rule this addendum removed")
        self.assertEqual([], [r for r in rules if any(area != "Cipher Key Lair" for area, _ in r.requires)],
                         "the Lair's floor must not depend on another area having progressed -- that is the "
                         "Snagem coupling ADDENDUM 332 removed")

    def test_no_other_destination_is_overridden(self) -> None:
        """ADDENDUM 331 added the second entry. The set is asserted whole rather than by membership so a
        THIRD override cannot arrive unnoticed -- an icon entering somewhere other than where the ladder says
        is exactly what this table is for and exactly what it must not do by accident."""
        # ADDENDUM 334 added Cipher Lab; ADDENDUM 350 removed it again, once the ladder itself was corrected
        # to the value the lab's own script tests for -- an override that equals what it overrides is a no-op
        # this table should not carry.
        self.assertEqual({"Cipher Key Lair", "Phenac City"}, set(sb.AREA_ENTRY_FLOOR_OVERRIDES))

    def test_an_override_must_name_a_real_byte(self) -> None:
        for value in sb.AREA_ENTRY_FLOOR_OVERRIDES.values():
            self.assertTrue(sb.floor_is_accounted_for(value))
