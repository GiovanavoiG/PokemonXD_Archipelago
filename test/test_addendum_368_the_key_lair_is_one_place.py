"""ADDENDA 368/369 (2026-09-26): the Key Lair is one place, and Biden belongs to Snagem.

Player, reporting a real multiworld: "User reported this multiworld gave them Cipher Key Lair as a first
unlock - but Zook has level 50 pokemon. Why?"

Then three rulings, in the order they arrived:
  * "Key lair interior and exterior should be the same place."                      -> ADDENDUM 368
  * "Just scale biden to snagem, both of his teams. He doesn't matter in key lair." -> ADDENDUM 369
  * "Also, just scale zook to key lair (which is now just one place)."              -> satisfied by 368

WHAT THE SEED SHIPPED, off its own `notes` rather than reasoned about:

    tier  3/15 (this seed's order): level 14 -- Cipher Key Lair
    tier 15/15 (this seed's order): level 50 -- Cipher Key Lair (exterior)

Zook #2 (147) and Biden #2 (148) stand in the exterior and were the ONLY two trainers in that seed at 50 or
above. The exterior is the Lair doorway, which is where a travel-unlock arrival lands, so the first fight the
player could not avoid was the one region of the place the ordering had put last.

THREE CORRECT DECISIONS COMPOSED INTO A WRONG ONE. ADDENDUM 329 gave the exterior its own floor so the icon's
0x64 could not reach the ramp; ADDENDUM 299 reorders tiers by the sphere each region is first reachable in, and
the travel item makes only `Cipher Key Lair` reachable; and ADDENDUM 299's own "regions that share a floor are
the same PLACE and are never levelled apart" safeguard could not fire, because after 329 no two trainer-bearing
regions shared a floor. `test_tier_groups_are_never_split` had already noticed and was SKIPPING itself.

THE LAST TEST IN THIS MODULE IS THE ONE THAT MATTERS: it replays this seed's own sphere assignment and asserts
the two halves of the Lair cannot come apart again.
"""
import unittest
from unittest import mock

from ..game_data import real_trainer_data as rtd, story_bytes as sb, trainer_placements as tp
from ..randomizer import path_level_scaling as pls


EXTERIOR = "Cipher Key Lair (exterior)"
INTERIOR = "Cipher Key Lair"
DEEP = "Cipher Key Lair (deep)"


def _known() -> "set[str]":
    return {region for region in pls.region_by_trainer_index().values() if region}


class TestTheMergeTable(unittest.TestCase):
    def test_the_exterior_borrows_the_interiors_floor_and_not_the_other_way_round(self) -> None:
        """The direction is the decision. 0x64 is when you get INSIDE, which keeps the Lair above Outskirt
        Stand (0x5F) and Snagem Hideout (0x62) where the story puts it. Merging downward onto 0x5D would have
        dragged the Lair's seventeen interior fights below the hideout -- a second wrong answer, not a fix."""
        self.assertEqual(INTERIOR, pls.PATH_FLOOR_MERGES[EXTERIOR])
        self.assertEqual(0x5D, sb.region_floor(EXTERIOR))
        self.assertEqual(0x64, sb.region_floor(INTERIOR))
        self.assertEqual(0x64, pls._path_floor(EXTERIOR))
        self.assertGreater(pls._path_floor(EXTERIOR), sb.region_floor("Snagem Hideout"))
        self.assertGreater(pls._path_floor(EXTERIOR), sb.region_floor("Outskirt Stand"))

    def test_the_interior_is_not_itself_merged(self) -> None:
        """Merges do not chain, so a target that is also a source would silently only take the first hop. The
        import-time fence refuses it; this states it as the property."""
        for source, target in pls.PATH_FLOOR_MERGES.items():
            self.assertNotIn(target, pls.PATH_FLOOR_MERGES, f"{source} -> {target} -> ...")

    def test_every_key_lair_region_lands_on_one_floor(self) -> None:
        """`AREA_GROUPS` already knows the Lair is three regions. All three now answer the ramp with one
        number, including `(deep)`, which holds no trainer today and whose own floor (0x6A) would give it a rung
        of its own the day the census moves one in."""
        self.assertEqual(("Cipher Key Lair (exterior)", "Cipher Key Lair", "Cipher Key Lair (deep)"),
                         sb.AREA_GROUPS["Cipher Key Lair"])
        self.assertEqual(0x6A, sb.region_floor(DEEP))
        self.assertEqual({0x64}, {pls._path_floor(name) for name in sb.AREA_GROUPS["Cipher Key Lair"]})

    def test_the_merge_moves_a_real_trainer(self) -> None:
        """ADDENDA 247/298: a condition that cannot bind reads as a guarantee. Lifting the table has to change
        a level, or the table should not exist."""
        known = _known()
        self.assertIn(EXTERIOR, known, "nothing is placed in the exterior, so the merge cannot bite")
        with mock.patch.object(pls, "PATH_FLOOR_MERGES", {}):
            before = pls.level_by_trainer_index()
            before_tiers = pls.path_tiers(known)
        after = pls.level_by_trainer_index()
        self.assertNotEqual(before, after)
        self.assertEqual(len(before_tiers) - 1, len(pls.path_tiers(known)),
                         "the merge retires exactly one rung, the exterior's 0x5D")


class TestZookAndBiden(unittest.TestCase):
    def setUp(self) -> None:
        self.known = _known()
        self.tiers = pls.path_tiers(self.known)
        self.levels = pls.level_by_trainer_index()

    def _level_of(self, region: str) -> int:
        return pls.level_for_tier(pls.tier_index(region, self.tiers, self.known), len(self.tiers))

    def test_zook_two_is_levelled_as_the_lair(self) -> None:
        """"Also, just scale zook to key lair (which is now just one place)." He needs no override of his own:
        he is placed in the exterior and the exterior IS the Lair now."""
        self.assertEqual(EXTERIOR, tp.PLACEMENTS[147].region)
        self.assertNotIn(147, pls.RAMP_REGION_OVERRIDES)
        self.assertEqual(self._level_of(INTERIOR), self.levels[147])

    def test_zook_one_stays_off_the_ramp(self) -> None:
        """The other Zook is trainer 9 in Gateon Port, which ADDENDUM 367 took off the ramp -- an always-open
        region cannot say when a fight happens. "Scale zook to key lair" is about the level-50 fight the player
        reported, and moving the early Gateon fight to the Lair's band would be the opposite of the complaint."""
        self.assertEqual("Gateon Port", tp.PLACEMENTS[9].region)
        self.assertIn("Gateon Port", pls.PATH_EXCLUDED_REGIONS)
        self.assertIsNone(self.levels.get(9))

    def test_both_bidens_are_levelled_at_the_snagem_hideout(self) -> None:
        """"Just scale biden to snagem, both of his teams." One row in `RAMP_REGION_OVERRIDES` and one row
        already in the placements (ADDENDUM 330 moved Biden #1 there), which is why the table has one entry and
        not two."""
        snagem = self._level_of("Snagem Hideout")
        self.assertEqual(snagem, self.levels[143])
        self.assertEqual(snagem, self.levels[148])
        self.assertEqual("Snagem Hideout", tp.PLACEMENTS[143].region)
        self.assertEqual({148}, set(pls.RAMP_REGION_OVERRIDES))

    def test_bidens_placement_is_untouched(self) -> None:
        """The narrow point of ADDENDUM 369. Biden #2 still STANDS at the Lair doorway -- that row drives the
        access rules, the live region report and ADDENDUM 327's anchor derivation. Only his level band moved."""
        self.assertEqual(EXTERIOR, tp.PLACEMENTS[148].region)
        self.assertEqual("Snagem Hideout", pls.region_by_trainer_index()[148])

    def test_nobody_else_is_moved_by_the_override(self) -> None:
        """A per-trainer override is the kind of thing that quietly moves a neighbour, so the diff is measured
        rather than assumed: exactly Biden #2's rows change when the table is lifted."""
        with mock.patch.object(pls, "RAMP_REGION_OVERRIDES", {}):
            before = pls.level_by_trainer_index()
        moved = {index for index in before if before[index] != self.levels.get(index)}
        self.assertEqual({148}, moved)

    def test_no_trainer_is_at_fifty_outside_citadark(self) -> None:
        """The player's symptom, stated as the thing they would notice. 50 is the top of the ramp, and after
        these two addenda the only region holding it is the last one."""
        regions = pls.region_by_trainer_index()
        top = {regions[index] for index, level in self.levels.items() if level >= 50}
        self.assertEqual({"Citadark Isle"}, top)


class TestTheSphereOrderingCannotSplitThePlaceAgain(unittest.TestCase):
    """The regression proper. Everything above would still hold if `sphere_tier_order` were handed this seed's
    spheres and split the Lair anyway, because the merge could in principle have been bypassed there."""

    def setUp(self) -> None:
        self.known = _known()

    def test_this_seeds_own_spheres_keep_the_lair_together(self) -> None:
        """Replaying the reported seed: the travel item made `Cipher Key Lair` reachable in sphere 1 while the
        exterior was only reachable at the end of the story chain. That is the exact input that produced tier 3
        and tier 15 for one building."""
        spheres = {region: 9 for region in self.known}
        spheres[INTERIOR] = 1     # the first travel unlock
        spheres[EXTERIOR] = 99    # reachable only down the story chain from SS Libra
        order = pls.sphere_tier_order(spheres, self.known)
        self.assertEqual(order[EXTERIOR], order[INTERIOR],
                         "the Lair came apart again -- this is the reported bug")

    def test_it_holds_with_the_two_swapped(self) -> None:
        spheres = {region: 9 for region in self.known}
        spheres[EXTERIOR] = 1
        spheres[INTERIOR] = 99
        order = pls.sphere_tier_order(spheres, self.known)
        self.assertEqual(order[EXTERIOR], order[INTERIOR])

    def test_the_group_rule_is_live_again_rather_than_skipping(self) -> None:
        """ADDENDUM 299's safeguard is only a safeguard while some tier really holds more than one region.
        `test_tier_groups_are_never_split` was skipping itself with "no multi-region tier in the real table";
        this asserts the table it needs now exists."""
        tiers = pls.path_tiers(self.known)
        by_tier: "dict[int, list[str]]" = {}
        for region in sorted(self.known):
            index = pls.tier_index(region, tiers, self.known)
            if index is not None:
                by_tier.setdefault(index, []).append(region)
        multi = [names for names in by_tier.values() if len(names) > 1]
        self.assertTrue(multi, "no multi-region tier -- ADDENDUM 299's grouping rule is undemonstrable again")
        self.assertIn(sorted([EXTERIOR, INTERIOR]), [sorted(names) for names in multi])

    def test_the_ramp_still_spans_eight_to_fifty(self) -> None:
        """A retired rung re-spaces the curve; it must not move the endpoints."""
        tiers = pls.path_tiers(self.known)
        self.assertEqual(pls.FIRST_TIER_LEVEL, pls.level_for_tier(0, len(tiers)))
        self.assertEqual(pls.LAST_TIER_LEVEL, pls.level_for_tier(len(tiers) - 1, len(tiers)))

    def test_chobin_one_is_still_level_five(self) -> None:
        """ADDENDUM 281's pin, re-checked because every re-spacing of this ramp has been a chance to lose it."""
        census = {row["trainer_index"]: row for row in rtd.real_trainer_team_census()}
        levels, _averages = pls.build_path_level_plan([census[i] for i in sorted(census)])
        self.assertEqual(5, pls.PINNED_TRAINER_LEVELS[15])
        for dpkm in census[15]["member_levels"]:
            self.assertEqual(5, levels[dpkm])
