"""ADDENDUM 435 (2026-10-08) -- legendary options, text and battle speed, the white-out latch, and Citadark's weight.

Player: "Let's add an option to enable legendaries as NORMAL pokemon trainers can have, an option to DISABLE
legendaries as shadow pokemon, and an option to make sure shadow lugia is shuffled. ... We found out how to wipe us
midbattle, so implement that. ... Build the instant text option if it doesn't exist. Citadark with location shuffle
off can be parts-only, but see if you can TRY to make it so that it'll have you complete most of the story most of
the time."
"""
from __future__ import annotations

import pathlib
import random
import struct
import unittest

from . import PokemonXDTestBase
from .. import items, options, ram_client as rc, regions
from ..game_data import shadow_legendaries as SL, text_speed as TS
from ..game_data.real_shadow_data import load_real_shadow_pool
from ..game_data.real_trainer_data import LEGENDARY_NATIONAL_DEX, real_species_pool
from ..tools.xd_species_index import INTERNAL_INDEX_TO_NATIONAL_DEX

ROOT = pathlib.Path(__file__).resolve().parent.parent
CLIENT = (ROOT / "Client.py").read_text(encoding="utf-8")
DOL = pathlib.Path("/mnt/user-data/uploads/PokemonXD-working/main_dol.bin")
RAM_DUMP = pathlib.Path("/mnt/user-data/uploads/PokemonXD-working/bridge/dumps/battle1.bin")
PART = items.MACGUFFIN_ITEM_NAME


def _dex(species: int) -> "int | None":
    return INTERNAL_INDEX_TO_NATIONAL_DEX.get(species, (None, None))[0]


class TestTheOptions(unittest.TestCase):
    def test_they_exist_with_their_defaults_and_are_in_the_template(self):
        fields = options.PokemonXDOptions.__dataclass_fields__
        text = (ROOT / "data" / "reference_template.yaml").read_text()
        for name, default in (("no_legendary_shadows", 0), ("shuffle_shadow_lugia", 0),
                              ("legendary_trainer_pokemon", 0), ("text_speed", 0), ("hold_b_to_advance", 0),
                              ("battle_speed", 0), ("citadark_story_weight", 85)):
            self.assertIn(name, fields)
            self.assertEqual(default, fields[name].type.default, name)
            self.assertIn(f"  {name}:", text)


# --- Shadow legendaries ------------------------------------------------------------------------------------------

class TestThePasses(unittest.TestCase):
    def setUp(self):
        self.pool = load_real_shadow_pool()
        if self.pool is None:
            self.skipTest("no Shadow data in this build")
        self.species = real_species_pool()
        self.original = {mon.index: mon.species_id for t in self.pool.trainers for mon in t.team}

    def _species(self):
        return [mon.species_id for t in self.pool.trainers for mon in t.team]

    def test_vanilla_has_four_legendary_shadows(self):
        legendary = sorted(_dex(s) for s in self._species() if _dex(s) in LEGENDARY_NATIONAL_DEX)
        self.assertEqual([144, 145, 146, 249], legendary)

    def test_removal_leaves_no_legendary_and_keeps_species_unique(self):
        self.assertEqual(4, SL.remove_legendary_shadows(self.pool, self.species, random.Random(1)))
        species = self._species()
        self.assertFalse([s for s in species if _dex(s) in LEGENDARY_NATIONAL_DEX])
        self.assertEqual(len(species), len(set(species)))

    def test_lugia_can_be_exempt(self):
        SL.remove_legendary_shadows(self.pool, self.species, random.Random(2),
                                    exempt=frozenset({SL.LUGIA_SPECIES_INDEX}))
        self.assertIn(SL.LUGIA_SPECIES_INDEX, self._species())
        self.assertEqual(1, sum(1 for s in self._species() if _dex(s) in LEGENDARY_NATIONAL_DEX))

    def test_lugia_trades_places_when_species_are_vanilla(self):
        for seed in range(20):
            pool = load_real_shadow_pool()
            original = {mon.index: mon.species_id for t in pool.trainers for mon in t.team}
            landed = SL.place_shadow_lugia(pool, original, random.Random(seed), randomized=False)
            now = {mon.index: mon.species_id for t in pool.trainers for mon in t.team}
            home = SL.vanilla_lugia_index(original)
            self.assertNotEqual(home, landed)
            self.assertEqual(SL.LUGIA_SPECIES_INDEX, now[landed])
            self.assertEqual(original[landed], now[home])
            self.assertEqual(sorted(original.values()), sorted(now.values()))   # a swap, nothing lost

    def test_lugia_replaces_a_shadow_when_species_are_randomized(self):
        for mon in (m for t in self.pool.trainers for m in t.team):
            if mon.species_id == SL.LUGIA_SPECIES_INDEX:
                mon.species_id = 1      # as the shuffle would: Lugia is on no candidate list
        landed = SL.place_shadow_lugia(self.pool, self.original, random.Random(3), randomized=True)
        self.assertNotEqual(SL.vanilla_lugia_index(self.original), landed)
        self.assertEqual(1, self._species().count(SL.LUGIA_SPECIES_INDEX))


class _World(PokemonXDTestBase):
    def _entries(self):
        assignment = self.multiworld.worlds[self.player]._shadow_species_assignment
        return assignment["entries"] if assignment else []

    def _shadow_dex(self):
        return {e["new_dex"] for e in self._entries()}


class TestNoLegendaryShadowsRandomized(_World):
    options = {"no_legendary_shadows": True, "randomize_shadow_species": True}

    def test_no_legendary_shadow(self):
        self.assertTrue(self._entries())
        self.assertFalse(self._shadow_dex() & LEGENDARY_NATIONAL_DEX)


class TestNoLegendaryShadowsVanilla(_World):
    options = {"no_legendary_shadows": True, "randomize_shadow_species": False}

    def test_the_four_legendaries_are_replaced_and_nothing_else_moves(self):
        moved = [e for e in self._entries() if e["new_species_index"] != e["original_species_index"]]
        self.assertEqual({144, 145, 146, 249}, {e["original_dex"] for e in moved})
        self.assertFalse(self._shadow_dex() & LEGENDARY_NATIONAL_DEX)


class TestShuffleShadowLugiaRandomized(_World):
    options = {"shuffle_shadow_lugia": True, "randomize_shadow_species": True, "no_legendary_shadows": True}

    def test_lugia_is_a_shadow_away_from_greevil_and_the_only_legendary(self):
        lugia = [e for e in self._entries() if e["new_dex"] == 249]
        self.assertEqual(1, len(lugia))
        self.assertNotEqual(249, lugia[0]["original_dex"])
        self.assertEqual({249}, self._shadow_dex() & LEGENDARY_NATIONAL_DEX)
        self.assertIn(249, self.multiworld.worlds[self.player]._shadow_catch_labels)


class TestShuffleShadowLugiaVanilla(_World):
    options = {"shuffle_shadow_lugia": True, "randomize_shadow_species": False}

    def test_a_swap_and_new_moves_only_for_the_two(self):
        moved = [e for e in self._entries() if e["new_species_index"] != e["original_species_index"]]
        self.assertEqual(2, len(moved))
        self.assertIn(249, {e["new_dex"] for e in moved})
        self.assertIn(249, {e["original_dex"] for e in moved})


class TestDefaultsLeaveShadowsAlone(_World):
    options = {"randomize_shadow_species": False}

    def test_no_assignment(self):
        self.assertEqual([], self._entries())


class TestLegendaryTrainerPokemon(_World):
    options = {"legendary_trainer_pokemon": True}

    def test_ordinary_teams_can_field_legendaries(self):
        species = self.multiworld.worlds[self.player]._trainer_species_by_dpkm_index or {}
        legendary = [s for s in species.values() if _dex(int(s)) in LEGENDARY_NATIONAL_DEX]
        self.assertTrue(legendary)
        self.assertNotIn(SL.LUGIA_SPECIES_INDEX, [int(s) for s in species.values()])


class TestOrdinaryTeamsStayNonLegendaryByDefault(_World):
    def test_none(self):
        species = self.multiworld.worlds[self.player]._trainer_species_by_dpkm_index or {}
        self.assertFalse([s for s in species.values() if _dex(int(s)) in LEGENDARY_NATIONAL_DEX])


# --- Text and battle speed ----------------------------------------------------------------------------------------

class TestTheWords(unittest.TestCase):
    def test_off_is_nothing(self):
        self.assertEqual((), TS.dol_patch_words(0, False, 0))

    def test_instant_text_alone(self):
        words = dict((a, (o, n)) for a, o, n in TS.dol_patch_words(TS.TEXT_SPEED_INSTANT, False, 0))
        self.assertEqual((TS.LI_R19_1, TS.LBZ_R19_SPEED), words[TS.NO_HELD_BRANCH_ADDRESS])
        self.assertEqual((0x03000000, 0x7F000000), words[TS.SPEED_BYTE_ADDRESS])

    def test_fast_text_needs_no_byte_change(self):
        words = TS.dol_patch_words(TS.TEXT_SPEED_FAST, False, 0)
        self.assertEqual([TS.NO_HELD_BRANCH_ADDRESS], [a for a, _o, _n in words])

    def test_hold_b_with_instant_text_loads_the_byte_in_the_rewrite(self):
        words = dict((a, n) for a, _o, n in TS.dol_patch_words(TS.TEXT_SPEED_INSTANT, True, 0))
        self.assertEqual(TS.LBZ_R19_SPEED, words[TS.HOLD_B_BLOCK_ADDRESS + 16])
        self.assertNotIn(TS.NO_HELD_BRANCH_ADDRESS, words.keys() - {TS.HOLD_B_BLOCK_ADDRESS + 0x44})
        plain = dict((a, n) for a, _o, n in TS.dol_patch_words(0, True, 0))
        self.assertEqual(TS.LI_R19_1, plain.get(TS.HOLD_B_BLOCK_ADDRESS + 16, TS.LI_R19_1))

    def test_the_rewrite_keeps_the_call_target(self):
        def target(address, word):
            offset = word & 0x03FFFFFC
            if offset & 0x02000000:
                offset -= 0x04000000
            return address + offset
        old = target(0x80109604, TS.HOLD_B_VANILLA[10])
        new = target(TS.HOLD_B_BLOCK_ADDRESS + 8, TS.HOLD_B_PATCHED[2])
        self.assertEqual(old, new)

    def test_battle_speed(self):
        self.assertEqual(((TS.BATTLE_WAIT_ADDRESS, 0x05000001, 0x03000001),), TS.dol_patch_words(0, False, 1))
        self.assertEqual(((TS.BATTLE_WAIT_ADDRESS, 0x05000001, 0x02000001),), TS.dol_patch_words(0, False, 2))


def _dol_word(data: bytes, address: int) -> "int | None":
    for i in range(18):
        off, addr, size = (struct.unpack_from(">I", data, base + i * 4)[0] for base in (0, 0x48, 0x90))
        if size and addr <= address < addr + size:
            return struct.unpack_from(">I", data, off + address - addr)[0]
    return None


@unittest.skipUnless(DOL.is_file(), "needs the real main.dol")
class TestAgainstTheRealDol(unittest.TestCase):
    def test_every_expected_word_is_the_games(self):
        data = DOL.read_bytes()
        for combo in ((2, True, 2), (1, False, 1), (2, False, 0)):
            for address, expected, _new in TS.dol_patch_words(*combo):
                self.assertEqual(expected, _dol_word(data, address), hex(address))


@unittest.skipUnless(RAM_DUMP.is_file(), "needs a RAM dump")
class TestAgainstARunningGame(unittest.TestCase):
    def test_the_same_words_are_in_memory(self):
        data = RAM_DUMP.read_bytes()
        for address, expected, _new in TS.dol_patch_words(2, True, 2):
            self.assertEqual(expected, struct.unpack_from(">I", data, address - 0x80000000)[0], hex(address))


class TestThePatcherAppliesIt(unittest.TestCase):
    def test_wired(self):
        source = (ROOT / "tools" / "iso_patcher.py").read_text()
        self.assertIn('_game_data_module("text_speed").dol_patch_words(', source)
        self.assertIn('seed.get("hold_b_to_advance")', source)


class TestTheSeedCarriesIt(PokemonXDTestBase):
    options = {"text_speed": 2, "hold_b_to_advance": True, "battle_speed": 1}

    def test_keys(self):
        from .test_addendum_429_nightmare_greevil_and_trade_evolutions import _seed

        seed = _seed(self.multiworld.worlds[self.player])
        self.assertEqual((2, True, 1), (seed["text_speed"], seed["hold_b_to_advance"], seed["battle_speed"]))


# --- Death Link and the white-out latch ---------------------------------------------------------------------------

class TestTheLatchArmsOnALoss(unittest.TestCase):
    def test_a_loss_arms_and_waits_for_the_lab(self):
        latch = rc.WhiteoutLatch()
        self.assertTrue(latch.arm_from_battle())
        self.assertFalse(latch.arm_from_battle())
        self.assertIsNone(latch.note_region("Pyrite Town"))     # still where the battle was
        self.assertTrue(latch.armed)
        self.assertTrue(latch.holds_floor_for("Pokemon HQ Lab"))
        latch.note_region("Pokemon HQ Lab")
        self.assertIsNotNone(latch.note_region("Agate Village"))
        self.assertFalse(latch.armed)

    def test_the_bridge_does_not_count_a_loss_arming_as_the_flag(self):
        latch = rc.WhiteoutLatch()
        bridge = rc.DeathLinkBridge(enabled=True, whiteout_latch=latch)
        latch.arm_from_battle()
        original = rc.read_annihilation_flag, rc.party_is_wiped
        rc.read_annihilation_flag = lambda: None
        rc.party_is_wiped = lambda base: False
        try:
            send, _note = bridge.poll(0x80000000, battle_wiped=True)
        finally:
            rc.read_annihilation_flag, rc.party_is_wiped = original
        self.assertTrue(send)
        self.assertEqual((1, 0), (bridge.sends_by_battle, bridge.sends_by_flag))

    def test_the_client_watches_battles_with_death_link_off_too(self):
        start = CLIENT.index("ADDENDUM 435: polled whether or not Death Link is on")
        block = CLIENT[start:start + 900]
        self.assertIn("ctx.battle_party_watch.poll(ctx.block_base, in_battle)", block)
        self.assertIn("ctx.whiteout_latch.arm_from_battle()", block)
        self.assertNotIn("if ctx.death_link_bridge.enabled:", block)

    def test_the_mid_battle_kill_is_wired(self):
        self.assertIn("in_battle=in_battle", CLIENT)
        self.assertIn("battle_written = wipe_battle_party(block_base)",
                      (ROOT / "ram_client.py").read_text())


# --- Citadark: Parts-only in vanilla travel, the story weight, and the story given back ----------------------------

class _Byte:
    def __init__(self, test, value):
        self.value = value
        for name in ("read_story_byte", "poke_story_byte"):
            test.addCleanup(setattr, rc, name, getattr(rc, name))
        rc.read_story_byte = lambda base: self.value
        rc.poke_story_byte = self._poke

    def _poke(self, base, value):
        self.value = value
        return True


class TestTheStoryComesBack(unittest.TestCase):
    GATEON = min(rc.GATEON_ROOM_IDS)

    def _ride(self, byte, vanilla=True):
        override = rc.StoryByteOverride(armed=True, return_story_after_citadark=vanilla)
        override.poll(0, self.GATEON)                           # lift in Gateon
        self.assertEqual(rc.STORY_OVERRIDE_VALUE, byte.value)
        override.poll(0, min(rc.CITADARK_ROOM_IDS))             # the ride
        return override

    def test_an_early_ride_gives_the_story_back(self):
        byte = _Byte(self, 0x30)
        override = self._ride(byte)
        self.assertEqual(rc.CITADARK_ENTRY_FLOOR, byte.value)
        self.assertEqual(0x30, override.pre_ride_byte)
        byte.value = 0x73                                       # the island moved on
        override.poll(0, min(rc.CITADARK_ROOM_IDS) + 1)
        override.poll(0, self.GATEON)                           # back on the Robo Kyogre: the story first...
        self.assertEqual(0x30, byte.value)
        override.poll(0, self.GATEON)                           # ...then Gateon's own lift
        self.assertIsNone(override.pre_ride_byte)
        self.assertEqual(0x73, override.citadark_mark)
        self.assertEqual(rc.STORY_OVERRIDE_VALUE, byte.value)   # lifted again inside Gateon...
        self.assertEqual(0x30, override.saved_byte)             # ...and owing the real story on the way out

    def test_the_next_ride_resumes_the_island(self):
        byte = _Byte(self, 0x30)
        override = self._ride(byte)
        byte.value = 0x74
        override.poll(0, rc.MAP_SCREEN_ROOM_ID)
        override.poll(0, 1)                                     # whited out to the lab
        self.assertEqual(0x30, byte.value)
        override.poll(0, self.GATEON)
        override.poll(0, min(rc.CITADARK_ROOM_IDS))
        self.assertEqual(0x74, byte.value)

    def test_a_win_is_never_lowered(self):
        byte = _Byte(self, 0x30)
        override = self._ride(byte)
        byte.value = rc.VICTORY_STORY_BYTE
        override.poll(0, self.GATEON)
        self.assertEqual(rc.VICTORY_STORY_BYTE, byte.value)

    def test_location_shuffle_is_unchanged(self):
        byte = _Byte(self, 0x30)
        override = self._ride(byte, vanilla=False)
        self.assertIsNone(override.pre_ride_byte)

    def test_a_late_ride_owes_nothing(self):
        byte = _Byte(self, 0x72)
        override = self._ride(byte)
        self.assertIsNone(override.pre_ride_byte)

    def test_the_client_arms_and_persists_it(self):
        self.assertIn("self.story_byte_override.return_story_after_citadark = not self.randomize_travel_locations",
                      CLIENT)
        self.assertIn('"citadark_pre_ride_byte": self.story_byte_override.pre_ride_byte', CLIENT)
        self.assertIn('"citadark_mark": self.story_byte_override.citadark_mark', CLIENT)


def _late_parts(world) -> int:
    late = set(world.LATE_STORY_REGIONS)
    return sum(1 for location in world.multiworld.get_locations(world.player)
               if location.item is not None and location.item.name == PART and location.parent_region.name in late)


class TestVanillaRidesFromGateon(PokemonXDTestBase):
    options = {"randomize_travel_locations": False, "citadark_story_weight": 100}

    def test_the_edge_and_the_bound_parts(self):
        world = self.multiworld.worlds[self.player]
        self.assertEqual(["Gateon Port -> Citadark Isle"],
                         [e.name for e in self.multiworld.get_region("Citadark Isle", self.player).entrances])
        available = int(world.options.robo_kyogre_parts_available)
        required = int(world.options.robo_kyogre_parts_required)
        self.assertEqual(available - required + 1, world._story_bound_parts)
        self.assertEqual(world._story_bound_parts, _late_parts(world))
        placed = [l for l in self.multiworld.get_locations(self.player) if l.item is not None and l.item.name == PART]
        self.assertTrue(all(l.locked for l in placed))
        self.assertFalse(set(l.name for l in placed) & set(world._citadark_reliant_locations))


class TestWeightZero(PokemonXDTestBase):
    options = {"randomize_travel_locations": False, "citadark_story_weight": 0}

    def test_nothing_bound(self):
        self.assertEqual(0, self.multiworld.worlds[self.player]._story_bound_parts)


class TestShuffleNeverBinds(PokemonXDTestBase):
    options = {"randomize_travel_locations": True, "citadark_story_weight": 100}

    def test_nothing_bound(self):
        self.assertEqual(0, self.multiworld.worlds[self.player]._story_bound_parts)


class TestTheTable(unittest.TestCase):
    def test_it_is_still_gateon(self):
        self.assertEqual({"Citadark Isle": "Gateon Port"}, regions.TRAVEL_SHUFFLE_PARTS_SOURCE)


if __name__ == "__main__":
    unittest.main()
