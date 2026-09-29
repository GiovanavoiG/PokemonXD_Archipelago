"""ADDENDUM 252 (2026-09-16) -- one progression-eligible check per re-fightable trainer.

Player: "For all our repeatable fights, can we keep our current checks & keep them filler, but add a one-time
check for ANY defeat of that trainer? This would add more progressive/unique locations."
Then: "Make the names, for example, 'Defeat Blusix (Any)' and 'Defeat Cail (Any)'."
And: "Make sure all the post-game fights are still filler - the ones at the bottom of the excel sheet."

WHY AN INDIVIDUAL FIGHT CANNOT HOLD PROGRESSION AND "ANY" CAN. Every occurrence of a re-fightable trainer is
either `earlier (N of M)` -- missable by construction, ADDENDUM 192 -- or the `final` row, which for 24 of the
35 sits in the post-game block at the bottom of the census with region `None`. "Any defeat" is earned by
whichever of them the player wins first, so it survives missing all but one.
"""
import unittest

from . import PokemonXDTestBase
from .. import locations as L, ram_client as rc, trainer_defeat as TD
from ..game_data import census_repeat_column as C, repeatable_trainers as RT, trainer_placements as P


class TestTheSet(unittest.TestCase):
    def test_thirty_five_of_them_one_per_refightable_trainer(self) -> None:
        finals = {i for i, (rep, _m) in C.CENSUS_REPEAT_AND_MISSABLE.items() if rep == "final"}
        self.assertEqual(35, len(finals))
        self.assertEqual(35, len(RT.REPEATABLE_TRAINERS))
        self.assertEqual(35, len(set(RT.LOCATION_NAMES)))

    def test_the_names_are_the_format_the_player_asked_for(self) -> None:
        self.assertIn("Defeat Blusix (Any)", RT.LOCATION_NAMES)
        self.assertIn("Defeat Cail (Any)", RT.LOCATION_NAMES)
        for name in RT.LOCATION_NAMES:
            self.assertTrue(name.startswith("Defeat ") and name.endswith(" (Any)"), name)
            self.assertNotIn("Defeat - ", name, "the (Any) names take no dash -- that is the older format")

    def test_a_surname_with_a_dot_still_reads_properly(self) -> None:
        self.assertIn("Defeat Miror B. (Any)", RT.LOCATION_NAMES)

    def test_every_one_is_a_real_location_with_a_frozen_id(self) -> None:
        for name in RT.LOCATION_NAMES:
            self.assertIn(name, L.LOCATION_TABLE, name)
            self.assertIn(name, L._FROZEN_LOCATION_OFFSETS,
                          f"{name} is unfrozen -- the next insertion above it would renumber all 35")

    def test_no_existing_id_moved_to_make_room(self) -> None:
        """ADDENDUM 26. Spot-checked against ids pinned by earlier addenda."""
        self.assertEqual(1510, L.LOCATION_TABLE["ONBS 3F Chest 1"].id_offset)
        self.assertEqual(1496, L.LOCATION_TABLE["Cipher Lab Krane Chest"].id_offset)
        self.assertEqual(1640, L._FROZEN_LOCATION_OFFSETS["Mt. Battle Shop AP Item 12"])


class TestTheAnchor(unittest.TestCase):
    """A location's region is a promise about where it can first be earned. Getting it wrong is how
    ADDENDUM 185 put the Music Disc behind itself."""

    def test_no_anchor_is_a_post_game_row(self) -> None:
        """The player's explicit instruction. Every post-game row has region `None`, so an anchor with a real
        region cannot be one -- asserted rather than relied on."""
        placements = dict(P.PLACEMENTS)
        for row in RT.REPEATABLE_TRAINERS:
            self.assertIsNotNone(placements[row["anchor_index"]].region, row["location"])
            self.assertEqual(row["region"], placements[row["anchor_index"]].region)

    def test_the_anchor_is_the_earliest_non_missable_occurrence(self) -> None:
        placements = dict(P.PLACEMENTS)
        for row in RT.REPEATABLE_TRAINERS:
            if row["always_filler"]:
                continue
            earlier_safe = [
                i for i in row["occurrences"]
                if i < row["anchor_index"]
                and not C.CENSUS_REPEAT_AND_MISSABLE[i][1]
                and placements.get(i) and placements[i].region
            ]
            self.assertEqual([], earlier_safe, f"{row['location']} skipped an earlier safe occurrence")

    def test_a_missable_anchor_is_always_filler(self) -> None:
        """The module asserts this at import; pinned here too, because it is the invariant that stops a
        progression item landing on a fight the player already walked past."""
        for row in RT.REPEATABLE_TRAINERS:
            if row["anchor_is_missable"]:
                self.assertTrue(row["always_filler"], row["location"])

    def test_every_ruling_reaches_the_location_set(self) -> None:
        """The wiring, not the count. ADDENDUM 301 added a sixth name and this test used to encode five, which
        is the shape of test that breaks on every legitimate change and catches nothing."""
        self.assertEqual({RT.location_name(surname) for surname in RT.ALWAYS_FILLER_SURNAMES},
                         set(RT.ALWAYS_FILLER_LOCATIONS))

    def test_the_rulings_that_must_be_present(self) -> None:
        """Each of these is a decision with a reason recorded beside it; losing one silently re-opens a
        location that was ruled shut. New rulings may be added -- these may not be removed."""
        for name in ("Defeat Biden (Any)", "Defeat Equin (Any)", "Defeat Eroll (Any)",
                     "Defeat Willie (Any)", "Defeat Greevil (Any)", "Defeat Aferd (Any)",
                     "Defeat Ardos (Any)", "Defeat Zook (Any)"):
            self.assertIn(name, RT.ALWAYS_FILLER_LOCATIONS, name)

    def test_every_ruling_carries_a_reason(self) -> None:
        for surname, reason in RT.ALWAYS_FILLER_SURNAMES.items():
            self.assertTrue(reason.strip(), surname)


class TestTheOldChecksAreUntouched(unittest.TestCase):
    def test_every_named_defeat_for_a_refightable_trainer_is_still_excluded(self) -> None:
        """"keep our current checks & keep them filler" -- which was already true, and must stay true."""
        repeatable = {row["surname"] for row in RT.REPEATABLE_TRAINERS}
        missable = L._MISSABLE_NAMED_TRAINER_LOCATIONS
        covered = 0
        for _region, name, surname in TD.TRAINER_DEFEAT_ROSTER:
            if surname.upper() in repeatable:
                self.assertIn(name, missable, f"{name} is no longer filler-only")
                covered += 1
        self.assertEqual(24, covered)

    def test_the_named_locations_still_exist(self) -> None:
        for _region, name, _surname in TD.TRAINER_DEFEAT_ROSTER:
            self.assertIn(name, L.LOCATION_TABLE, name)

    def test_the_cumulative_count_locations_are_untouched(self) -> None:
        self.assertEqual(232, L.TRAINER_DEFEAT_COUNT_LOCATION_COUNT)


class TestBothSidesSpellThemTheSame(unittest.TestCase):
    """The ADDENDUM 200 contract, which this adds a 36th way to break: locations.py and the client must agree
    character for character or every one of these checks is silently rejected."""

    def test_the_client_map_matches_the_location_table(self) -> None:
        for surname, name in RT.SURNAME_TO_LOCATION.items():
            self.assertIn(name, L.LOCATION_TABLE)
            self.assertEqual(surname, surname.upper(), "the client matches upper-case roster names")
        self.assertEqual(set(RT.LOCATION_NAMES), set(RT.SURNAME_TO_LOCATION.values()))


class TestTheyFollowTheTrainerDefeatToggle(PokemonXDTestBase):
    """Found by generating with the option off and counting. They fell through to the Overworld Items branch,
    so `shuffle_trainer_defeats: False` removed the 66 named locations and left all 35 of these behind --
    progression-eligible, with a client that returns immediately before it could ever check them. ADDENDUM
    237's 65 undetectable Overworld Items, in code written the same afternoon."""

    options = {"shuffle_trainer_defeats": False}

    def test_none_are_created_with_defeats_off(self) -> None:
        live = {l.name for l in self.multiworld.get_locations(1)}
        self.assertEqual(set(), live & set(RT.LOCATION_NAMES))
        self.assertEqual([], [n for n in live if n.startswith("Defeat - ")],
                         "the test's own premise -- the named ones go too")


class TestTheySurviveUniqueMode(PokemonXDTestBase):
    """Unlike the named and cumulative categories, which unique mode replaces outright. Unique mode changes
    which OCCURRENCES get a location, and "any defeat" is not an occurrence."""

    options = {"shuffle_trainer_defeats": True, "trainer_defeat_mode": 1}

    def test_all_thirty_five_still_exist(self) -> None:
        live = {l.name for l in self.multiworld.get_locations(1)}
        self.assertEqual(35, len(live & set(RT.LOCATION_NAMES)))


class TestAgainstARealWorld(PokemonXDTestBase):
    options = {"shuffle_trainer_defeats": True, "key_item_shuffle": True}

    def _state(self, held):
        from BaseClasses import CollectionState
        state = CollectionState(self.multiworld)
        for name in held:
            state.collect(self.multiworld.worlds[1].create_item(name), prevent_sweep=True)
        state.sweep_for_advancements()
        return state

    def _live(self):
        return {l.name: l for l in self.multiworld.get_locations(1) if l.name in set(RT.LOCATION_NAMES)}

    def test_all_thirty_five_are_created(self) -> None:
        self.assertEqual(35, len(self._live()))

    def test_the_five_are_excluded_and_the_rest_are_not(self) -> None:
        from BaseClasses import LocationProgressType

        live = self._live()
        for name, location in live.items():
            if name in RT.ALWAYS_FILLER_LOCATIONS:
                self.assertIs(LocationProgressType.EXCLUDED, location.progress_type, name)
            else:
                self.assertIsNot(LocationProgressType.EXCLUDED, location.progress_type, name)

    def test_the_eligible_set_is_exactly_the_unruled_remainder(self) -> None:
        """A relationship rather than a number: whatever the rulings are, everything else is eligible."""
        from BaseClasses import LocationProgressType

        live = self._live()
        eligible = {n for n, l in live.items() if l.progress_type is not LocationProgressType.EXCLUDED}
        self.assertEqual(set(live) - set(RT.ALWAYS_FILLER_LOCATIONS), eligible)
        self.assertTrue(eligible, "the rulings must never swallow the whole category")

    def test_each_one_is_reachable_from_its_own_region(self) -> None:
        """With every progression item in hand, all 35 must be reachable -- a location nothing can reach is
        the silent shape ADDENDUM 183 exists to catch."""
        everything = self.multiworld.get_all_state(False)
        for name, location in self._live().items():
            self.assertTrue(location.can_reach(everything), name)

    def test_sphere_zero_is_exactly_the_always_open_anchors(self) -> None:
        """Five anchors really are opening-hour fights -- Aferd and Naps in the HQ Lab, Ardos and Laken at
        Gateon, Chobin at Kaminko's -- and all five regions are open from the start, so those five SHOULD be
        reachable with nothing held. The Machine Part is already sphere zero (ADDENDUM 190/192), so this is
        the shape the world has, not a new one.

        Asserted as an exact set rather than "some are early": the failure worth catching is a SIXTH one
        appearing, which would mean an anchor drifted into a region that does not gate it."""
        from BaseClasses import CollectionState
        from ..game_data import story_bytes

        expected = {row["location"] for row in RT.REPEATABLE_TRAINERS
                    if row["region"] in story_bytes.ALWAYS_OPEN_REGIONS}
        self.assertEqual(5, len(expected))

        empty = CollectionState(self.multiworld)
        early = {n for n, l in self._live().items() if l.can_reach(empty)}
        self.assertEqual(expected, early)

    def test_lovrinas_carries_the_data_rom(self) -> None:
        """One of the six anchors with requirements beyond its region, checked end to end."""
        location = self._live()["Defeat Lovrina (Any)"]
        self.assertFalse(location.can_reach(self._state(["Machine Part"])))
        self.assertTrue(location.can_reach(self._state(["Machine Part", "Data ROM & ID Card"])))

    def test_no_rule_names_an_item_that_never_enters_the_pool(self) -> None:
        """ADDENDUM 168, and this is a live risk here rather than a hypothetical: Equin's anchor names the
        Elevator Key, which is NEVER_SHUFFLED. Naming it would make the location unreachable forever."""
        everything = self.multiworld.get_all_state(False)
        self.assertTrue(self._live()["Defeat Equin (Any)"].can_reach(everything))


if __name__ == "__main__":
    unittest.main()
