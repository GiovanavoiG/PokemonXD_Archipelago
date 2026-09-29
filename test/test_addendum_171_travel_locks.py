"""ADDENDUM 171 (2026-09-13): the vanilla travel bits are held clear, and the vanilla unlock becomes a check.

Player instruction: "Mt Battle is vanilla unlocked at story byte 0x23 > 0x24 - if random locations is on, CLEAR
that access unless we've received it as an item, then send a check. Apply this logic to every location after
kaminko/agate/gateon/hq lab."

The half that was missing before: ADDENDUM 104 only ever ADDED travel bits, so the game kept unlocking
destinations on its own and the travel items gated nothing in practice."""
from __future__ import annotations

import unittest

from .. import travel_locations as tl
from ..game_data import story_bytes
from .. import ram_client as rc


class _FakeRam:
    """One byte of the travel record per offset, so a clear can be observed without a live game."""

    def __init__(self, initial: "dict[int, int]") -> None:
        self.byte = dict(initial)
        self.writes: list[tuple[int, int]] = []

    def read(self, address: int, length: int) -> bytes:
        return bytes(self.byte.get(address + i, 0) for i in range(length))

    def write(self, address: int, data: bytes) -> None:
        for i, value in enumerate(data):
            self.byte[address + i] = value
            self.writes.append((address + i, value))


class _Patched:
    def __init__(self, ram: _FakeRam) -> None:
        self.ram = ram

    def __enter__(self) -> _FakeRam:
        self._orig = (rc.read_bytes, rc.write_bytes)
        rc.read_bytes, rc.write_bytes = self.ram.read, self.ram.write
        return self.ram

    def __exit__(self, *exc) -> None:
        rc.read_bytes, rc.write_bytes = self._orig


BASE = 0x80000000


class TestClearingABit(unittest.TestCase):
    def test_a_set_bit_is_cleared_and_reports_the_change(self) -> None:
        bit = tl.TRAVEL_LOCATION_BITS["Mt. Battle"]
        with _Patched(_FakeRam({BASE + bit.byte_offset: bit.full_bits})) as ram:
            self.assertTrue(tl.clear_travel_location_bit(BASE, "Mt. Battle"))
            self.assertEqual(ram.byte[BASE + bit.byte_offset] & bit.full_bits, 0)

    def test_clearing_an_already_clear_bit_writes_nothing(self) -> None:
        """Called every tick, so a no-op has to actually be a no-op rather than a redundant write."""
        with _Patched(_FakeRam({})) as ram:
            self.assertFalse(tl.clear_travel_location_bit(BASE, "Mt. Battle"))
            self.assertEqual(ram.writes, [])

    def test_it_never_disturbs_a_sibling_sharing_the_same_byte(self) -> None:
        """Snagem Hideout and Outskirt Stand both live at +0x08. Re-locking one must not re-lock the other --
        a blunt overwrite here would take back a destination the player legitimately received."""
        snagem = tl.TRAVEL_LOCATION_BITS["Snagem Hideout"]
        outskirt = tl.TRAVEL_LOCATION_BITS["Outskirt Stand"]
        self.assertEqual(snagem.byte_offset, outskirt.byte_offset, "premise: they share a byte")
        start = snagem.full_bits | outskirt.full_bits
        with _Patched(_FakeRam({BASE + snagem.byte_offset: start})) as ram:
            tl.clear_travel_location_bit(BASE, "Snagem Hideout")
            live = ram.byte[BASE + snagem.byte_offset]
        self.assertEqual(live & snagem.full_bits, 0, "Snagem should be clear")
        self.assertEqual(live & outskirt.full_bits, outskirt.full_bits, "Outskirt Stand must survive")

    def test_setting_then_clearing_round_trips(self) -> None:
        bit = tl.TRAVEL_LOCATION_BITS["Pyrite Town"]
        with _Patched(_FakeRam({})) as ram:
            tl.write_travel_location_bit(BASE, "Pyrite Town")
            self.assertTrue(tl.read_travel_location_unlocked(BASE, "Pyrite Town"))
            tl.clear_travel_location_bit(BASE, "Pyrite Town")
            self.assertFalse(tl.read_travel_location_unlocked(BASE, "Pyrite Town"))
            self.assertEqual(ram.byte[BASE + bit.byte_offset], 0)


class TestTheVanillaUnlockThresholds(unittest.TestCase):
    def test_mt_battle_is_the_value_the_player_quoted(self) -> None:
        """The player said "Mt Battle is vanilla unlocked at story byte 0x23 > 0x24". That number comes from
        their own play notes; this one comes from story_bytes.py's derived region floors. They agree, which is
        an independent check on the whole story table rather than just this row."""
        self.assertEqual(tl.vanilla_unlock_story_byte("Mt. Battle"), 0x24)

    def test_every_destination_but_kaminko_has_a_threshold(self) -> None:
        """Kaminko's House is one of the four exempt areas and has no story window, so it has nothing to fire
        from. Everything else must, or its check could never be earned."""
        for name in tl.TRAVEL_LOCATION_NAMES:
            threshold = tl.vanilla_unlock_story_byte(name)
            if name == "Kaminko's House":
                self.assertIsNone(threshold)
            else:
                self.assertIsNotNone(threshold, name)

    def test_the_thresholds_follow_the_story_order(self) -> None:
        """Every destination's threshold is the byte at which TRANSITIONS says its place becomes reachable.

        REWRITTEN 2026-09-16 (ADDENDUM 247). This used to assert that a HARDCODED list of seven destinations
        came out in ascending order, with "Cipher Key Lair" pinned last. That was true only while the Key Lair
        icon took its threshold from the wrong tier (0x64, the post-Snagem entry) -- the transition table says
        plainly that the Lair becomes reachable at 0x5D, BEFORE Outskirt Stand (0x5F) and Snagem (0x62), so
        the hardcoded order encoded the bug rather than the story.

        The ordering claim is now DERIVED from the same table the floors come from, which is what stops it
        going stale a fifth time (`test_sphere_logic`'s own lesson, applied here)."""
        from ..game_data import story_bytes as sb

        opened_at = {region: t.after for t in sb.TRANSITIONS for region in t.opens_regions}
        checked = 0
        for name in tl.TRAVEL_LOCATION_NAMES:
            threshold = tl.vanilla_unlock_story_byte(name)
            region = (tl.TRAVEL_UNLOCK_STORY_REGION.get(name)
                      or tl.TRAVEL_LOCATION_TARGET_REGION.get(name))
            if threshold is None or region is None:
                continue
            first_tier = next((members[0] for members in sb.AREA_GROUPS.values() if region in members), region)
            if first_tier not in opened_at:
                continue
            self.assertEqual(opened_at[first_tier], threshold,
                             f"{name}: the icon's threshold must be the byte that opens {first_tier}")
            checked += 1
        self.assertGreaterEqual(checked, 8, "the sweep found almost nothing -- it is not testing anything")

    def test_the_two_destinations_that_name_a_later_tier(self) -> None:
        """ADDENDUM 247, pinned as literals because these two are the whole reason the addendum exists.

        `map_destinations` gives the SS Libra icon `region="SS Libra"` (the scooter-upgraded ship, 0x5A) and
        the Key Lair icon `region="Cipher Key Lair"` (the post-Snagem entry, 0x64). Both places are reachable
        earlier -- the stranded ship at 0x4E and the Lair exterior at 0x5D -- and the threshold has to be when
        the ICON appears, not when its last tier does."""
        self.assertEqual(0x4E, tl.vanilla_unlock_story_byte("SS Libra"))
        self.assertEqual(0x5D, tl.vanilla_unlock_story_byte("Cipher Key Lair"))

    def test_the_three_poke_spots_share_one_unlock(self) -> None:
        """Player: "Make the Poke Spots one unlock", and later "Make sure poke spots are all one item to unlock
        them when randomized locations is on."

        FINISHED 2026-09-13 (ADDENDUM 177). The first instruction had only been half-done: the three spots
        shared a REGION, so logic treated them as one place, but each still had its own unlock ITEM and its own
        check -- meaning two of the three items changed nothing about reachability. There is one item now, and
        the three per-spot BITS live behind it (the game keeps a bit per spot, so all three must still be
        written or two map icons stay dark)."""
        spots = ("Cave Poke Spot", "Oasis Poke Spot", "Rockground Poke Spot")
        self.assertEqual(tl.TRAVEL_UNLOCK_MEMBERS["Poke Spots"], spots)
        self.assertEqual(tl.travel_unlock_members("Poke Spots"), spots)
        # One unlock name, one item, one check.
        self.assertIn("Poke Spots", tl.TRAVEL_LOCATION_NAMES)
        for spot in spots:
            self.assertNotIn(spot, tl.TRAVEL_LOCATION_NAMES)
            self.assertIn(spot, tl.TRAVEL_LOCATION_BITS, "the per-spot bit must survive")
        self.assertEqual(tl.TRAVEL_LOCATION_TARGET_REGION["Poke Spots"], "Poke Spots")
        # An ungrouped destination covers only itself, so every caller can use the helper blindly.
        self.assertEqual(tl.travel_unlock_members("Phenac City"), ("Phenac City",))

    def test_orre_colosseum_no_longer_folds_into_realgam(self) -> None:
        """UNMERGED 2026-09-14 (ADDENDUM 185, player: "Leave Orre Colosseum as a gettable location, but remove
        it/all its trainers/chests from the logic. It's a postgame area anyway."). The fold made its travel
        item a SECOND key to Realgam Tower, which every other destination does not have. Its item now opens a
        region of its own that holds nothing, while its CHECK still fires off Realgam's byte -- the two
        questions have different answers and this is the one place they do."""
        self.assertEqual(tl.TRAVEL_LOCATION_TARGET_REGION["Orre Colosseum"], tl.ORRE_COLOSSEUM_REGION)
        self.assertNotEqual(tl.ORRE_COLOSSEUM_REGION, "Realgam Tower")
        self.assertEqual(tl.TRAVEL_UNLOCK_STORY_REGION["Orre Colosseum"], "Realgam Tower")
        self.assertIsNotNone(tl.vanilla_unlock_story_byte("Orre Colosseum"),
                             "the check must stay earnable -- the player asked for it to remain gettable")


class TestTheRegionMapIsNowOneToOne(unittest.TestCase):
    def test_every_target_region_is_a_real_graph_region_except_the_postgame_one(self) -> None:
        """ADDENDUM 185: Orre Colosseum is deliberately NOT on the story graph. It is a real region that
        regions.py creates and nothing connects into, so reaching it is possible and depending on it is not."""
        from .. import regions

        for name, region in tl.TRAVEL_LOCATION_TARGET_REGION.items():
            if region == tl.ORRE_COLOSSEUM_REGION:
                self.assertNotIn(region, regions.REGION_NAMES,
                                 "the postgame region must stay off the story chain")
                continue
            self.assertIn(region, regions.REGION_NAMES, f"{name} -> {region}")

    def test_the_residual_realgam_bucket_is_gone(self) -> None:
        """Before ADDENDUM 171, five destinations folded into Realgam Tower purely because the seven-region
        skeleton had nowhere better. ADDENDUM 185 unmerged the last of them, so Realgam is now the target of
        exactly one destination -- the same as every other region on the graph."""
        realgam = {n for n, r in tl.TRAVEL_LOCATION_TARGET_REGION.items() if r == "Realgam Tower"}
        self.assertEqual(realgam, {"Realgam Tower"})

    def test_no_region_is_the_target_of_two_destinations_except_the_poke_spots(self) -> None:
        """The Poke Spots share one region on the player's own instruction; nothing else may, because a second
        key to a region nobody asked to have two keys is a logic hole rather than a feature."""
        import collections

        counts = collections.Counter(tl.TRAVEL_LOCATION_TARGET_REGION.values())
        doubled = {r for r, n in counts.items() if n > 1}
        self.assertEqual(doubled, {"Poke Spots"} if counts["Poke Spots"] > 1 else set())


class TestTheChecksExist(unittest.TestCase):
    def test_one_location_per_destination_with_a_threshold(self) -> None:
        from .. import locations

        expected = {
            tl.travel_unlock_location_name(n) for n in tl.TRAVEL_LOCATION_NAMES
            if tl.vanilla_unlock_story_byte(n) is not None
        }
        self.assertEqual(set(locations.TRAVEL_UNLOCK_LOCATION_NAMES), expected)
        for name in expected:
            self.assertIn(name, locations.LOCATION_TABLE, name)

    def test_kaminko_has_no_unlock_check(self) -> None:
        from .. import locations

        self.assertNotIn(tl.travel_unlock_location_name("Kaminko's House"),
                         locations.TRAVEL_UNLOCK_LOCATION_NAMES)

    def test_the_names_do_not_collide_with_the_item_names(self) -> None:
        """"Travel Unlock - Mt. Battle" is the ITEM; "Unlock - Mt. Battle" is the LOCATION. Two different
        things that would be very easy to conflate."""
        from .. import items, locations

        self.assertTrue(set(locations.TRAVEL_UNLOCK_LOCATION_NAMES).isdisjoint(items.ITEM_TABLE))


if __name__ == "__main__":
    unittest.main()
