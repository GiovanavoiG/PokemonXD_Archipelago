"""ADDENDUM 329 (2026-09-23): a map-icon instruction must never re-order the level ramp.

Player: "With path scaling, Biden in Snagem was level 40 but the rest of snagem was 15/16 - is this due to
his fight in the Key Lair? did it scale him to key lair levels? Can we fix this issue here and in other areas
too?"

It did. `path_level_scaling._path_floor` asked `story_bytes.area_entry_floor`, which answers the MAP-ICON
question -- one number for a whole `AREA_GROUPS` place, and since ADDENDUM 324 an `AREA_ENTRY_FLOOR_OVERRIDES`
entry on top of it. The player's "make Cipher Key Lair's floor 0x64" therefore told every Key Lair region,
including the exterior at 0x5D, that it entered at 0x64 -- above Outskirt Stand and above Snagem.

These tests are the fence rather than a re-statement of today's numbers: the ordering assertions are written
against `region_floor` so they keep holding if a floor moves, and the override assertion is written against
the whole `AREA_ENTRY_FLOOR_OVERRIDES` table so a SECOND override cannot do this again quietly.
"""
from . import PokemonXDTestBase
from ..game_data import story_bytes as sb
from ..game_data import trainer_placements as tp
from ..randomizer import path_level_scaling as pls


class TestTheRampAsksTheRegion(PokemonXDTestBase):

    def _trainer_regions(self) -> "set[str]":
        return set(pls.region_by_trainer_index().values())

    def test_the_exterior_keeps_its_own_story_floor_but_shares_the_lairs_tier(self) -> None:
        """SUPERSEDED IN PART BY ADDENDUM 368 (2026-09-26), on the player's ruling: "Key lair interior and
        exterior should be the same place."

        This test used to assert the opposite -- `exterior < interior` -- and that was right about the STORY
        and wrong about the PLAYER. It stayed right about the story: `region_floor` still says 0x5D and 0x64,
        and ADDENDUM 329's whole finding (the icon's 0x64 must not reach the ramp) is untouched. What changed is
        that the ramp now asks `_path_floor`, which merges the doorway onto the building, because a seed that
        handed the Lair out as a first travel unlock levelled its doorway at 50 and its inside at 14.

        So both halves are asserted here rather than one replacing the other: the region's own floor is
        unchanged, and the ramp's floor is the Lair's."""
        self.assertEqual(0x5D, sb.region_floor("Cipher Key Lair (exterior)"))
        self.assertEqual(0x64, sb.region_floor("Cipher Key Lair"))
        self.assertEqual(0x64, pls._path_floor("Cipher Key Lair (exterior)"))
        self.assertEqual(0x64, pls._path_floor("Cipher Key Lair"))
        regions = self._trainer_regions()
        tiers = pls.path_tiers(regions)
        exterior = pls.tier_index("Cipher Key Lair (exterior)", tiers, regions)
        interior = pls.tier_index("Cipher Key Lair", tiers, regions)
        self.assertIsNotNone(exterior)
        self.assertEqual(exterior, interior,
                         "ADDENDUM 368: the doorway and the inside of one building are one tier")

    def test_the_back_half_is_in_story_order_and_the_lair_is_one_rung(self) -> None:
        """ADDENDUM 329 measured the story order of the back half and ADDENDUM 368 merged two of its rungs, so
        the measurement and the ramp are asserted separately.

        The story order is a fact about the game and does not move: 0x5D outside the Lair, 0x5F Outskirt Stand,
        0x62 Snagem Hideout, 0x64 inside the Lair. The ramp now collapses the first and last of those into the
        one place they are, which puts the whole Lair last of the four -- above Snagem, which is when you get
        inside it. That is the direction ADDENDUM 368 chose deliberately; merging the other way would have
        dragged the Lair's seventeen interior fights below the hideout."""
        self.assertEqual([0x5D, 0x5F, 0x62, 0x64],
                         [sb.region_floor(n) for n in ("Cipher Key Lair (exterior)", "Outskirt Stand",
                                                       "Snagem Hideout", "Cipher Key Lair")])
        regions = self._trainer_regions()
        tiers = pls.path_tiers(regions)
        order = {name: pls.tier_index(name, tiers, regions)
                 for name in ("Cipher Key Lair (exterior)", "Outskirt Stand", "Snagem Hideout",
                              "Cipher Key Lair")}
        self.assertLess(order["Outskirt Stand"], order["Snagem Hideout"], order)
        self.assertLess(order["Snagem Hideout"], order["Cipher Key Lair"], order)
        self.assertEqual(order["Cipher Key Lair (exterior)"], order["Cipher Key Lair"], order)

    def test_both_bidens_sit_in_the_snagem_band_and_zook_sits_at_the_lair(self) -> None:
        """THE PLAYER SPLIT THIS TEST IN TWO (2026-09-26): "Just scale biden to snagem, both of his teams. He
        doesn't matter in key lair", and "just scale zook to key lair (which is now just one place)".

        It used to assert that trainers 143 and 147 both landed at or below the Snagem band, which was the
        ADDENDUM 329 complaint stated as fights. Two things have happened since. ADDENDUM 330 found the two
        Biden rows swapped, so the Biden the player actually meets in the hideout is 143 and it is placed there;
        and ADDENDUM 369 takes Biden #2 (148) out of the ramp's view of the Lair doorway, leaving Zook #2 (147)
        as the one fight there.

        It also needed to be split for a second reason: it was passing for the wrong cause. Gonzap #1 is the
        hideout boss and his ace spreads to 48, above the Snagem tier's own 43, so "at or below the highest
        Snagem level" was satisfied by 47 <= 48 rather than by Zook being in the band at all. Both halves below
        are stated against the TIER LEVEL, which is the number the ramp actually decides."""
        census = {row["trainer_index"]: row for row in __import__(
            "worlds.pokemon_xd.game_data.real_trainer_data", fromlist=["x"]
        ).real_trainer_team_census()}
        by_index = pls.level_by_trainer_index()
        regions = self._trainer_regions()
        tiers = pls.path_tiers(regions)
        snagem = pls.level_for_tier(pls.tier_index("Snagem Hideout", tiers, regions), len(tiers))
        lair = pls.level_for_tier(pls.tier_index("Cipher Key Lair", tiers, regions), len(tiers))
        self.assertLess(snagem, lair, "the hideout comes before the inside of the Lair")

        for index in (143, 148):
            self.assertEqual(snagem, by_index[index],
                             f"ADDENDUM 369: both Biden fights are levelled at the Snagem Hideout, not the "
                             f"Lair -- trainer {index}")
        self.assertEqual(lair, by_index[147],
                         "ADDENDUM 368: Zook #2 stands at the Lair and is levelled as the Lair")

        # And the reported shape is still gone: no Biden member outranks the hideout's own band.
        levels, _averages = pls.build_path_level_plan([census[i] for i in sorted(census)])
        snagem_rows = [index for index, place in tp.PLACEMENTS.items()
                       if place.region == "Snagem Hideout" and index in census]
        band = [levels[d] for index in snagem_rows for d in census[index]["member_levels"] if d in levels]
        self.assertTrue(band)
        for index in (143, 148):
            for dpkm in census[index]["member_levels"]:
                self.assertLessEqual(levels[dpkm], max(band),
                                     f"trainer {index} outranks the hideout it is fought in")

    def test_an_icon_override_can_never_move_a_tier_again(self) -> None:
        """The fence. `AREA_ENTRY_FLOOR_OVERRIDES` is a statement about where an icon drops you; the ramp is a
        statement about where a region sits. Adding a second override must not change one level."""
        regions = self._trainer_regions()
        before = pls.path_tiers(regions)
        before_levels = pls.level_by_trainer_index()
        original = dict(sb.AREA_ENTRY_FLOOR_OVERRIDES)
        try:
            sb.AREA_ENTRY_FLOOR_OVERRIDES["Pyrite Town"] = 0x6E
            sb.AREA_ENTRY_FLOOR_OVERRIDES["Agate Village"] = 0x6E
            self.assertEqual(before, pls.path_tiers(regions))
            self.assertEqual(before_levels, pls.level_by_trainer_index())
        finally:
            sb.AREA_ENTRY_FLOOR_OVERRIDES.clear()
            sb.AREA_ENTRY_FLOOR_OVERRIDES.update(original)

    def test_every_tier_is_a_real_region_floor_and_the_ramp_is_monotone(self) -> None:
        """Derived, not typed: each tier must BE some trainer region's own floor, and the ordering must be the
        ordering of those floors."""
        regions = self._trainer_regions()
        tiers = pls.path_tiers(regions)
        real = [floor for floor in tiers if floor is not None]
        self.assertEqual(real, sorted(real))
        for floor in real:
            self.assertIn(floor, {pls._path_floor(name) for name in regions
                                  if name not in sb.ALWAYS_OPEN_REGIONS})
        for name in regions:
            index = pls.tier_index(name, tiers, regions)
            if name in pls.PATH_EXCLUDED_REGIONS:
                # ADDENDUM 366: an excluded region has no place on the ramp on purpose -- Chobin is fought in
                # Kaminko's House across the whole story, so "where is it" cannot answer "when is it".
                self.assertIsNone(index, f"{name} is excluded and must have no tier")
                continue
            self.assertIsNotNone(index, f"{name} has no place on the ramp")
            if name in sb.ALWAYS_OPEN_REGIONS:
                self.assertEqual(0, index)
            else:
                # ADDENDUM 368: the ramp's floor, which is `region_floor` everywhere except a merged region.
                self.assertEqual(pls._path_floor(name), tiers[index])

    def test_regions_only_share_a_tier_when_they_share_a_floor(self) -> None:
        """ADDENDUM 299's grouping rule, restated as the thing it always meant. Before this addendum Pyrite
        Town (0x30) and Pyrite Town (ONBS) (0x3C) shared a tier despite having different floors, because the
        area collapse handed both of them Pyrite's number."""
        regions = self._trainer_regions()
        tiers = pls.path_tiers(regions)
        by_tier: "dict[int, list[str]]" = {}
        for name in sorted(regions):
            by_tier.setdefault(pls.tier_index(name, tiers, regions), []).append(name)
        for index, names in by_tier.items():
            if index is None:
                continue   # ADDENDUM 367: excluded regions have no tier, so they share nothing
            if index == 0 and any(n in sb.ALWAYS_OPEN_REGIONS for n in names):
                continue   # the deliberate always-open collapse, see path_tiers
            # ADDENDUM 368: the ramp's floor. Two regions that the merge table declares one PLACE share a
            # tier on purpose, and `test_addendum_368` pins that the table is the only thing that can do it.
            floors = {pls._path_floor(name) for name in names}
            self.assertEqual(1, len(floors),
                             f"tier {index} holds regions with different floors: {names} -> {floors}")

