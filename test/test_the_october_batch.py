"""Shadow move cap, Icy Wind weight, Poke Spot odds, map text, Mt. Battle checks, Perr's Machine Part, purify patch."""
from __future__ import annotations

import random
import struct
import unittest

from . import PokemonXDTestBase
from ..game_data import map_level_text, mtbattle_trainer_data, purify_anyone, move_tutor, npc_battle_scripts
from ..randomizer import team_shuffle
from ..tools import iso_patcher


class TestShadowMoveCap(unittest.TestCase):
    def test_four_moves_become_two(self) -> None:
        self.assertEqual([358, 367, 0, 0], iso_patcher.capped_shadow_moves([358, 367, 373, 369]))

    def test_two_status_moves_keep_an_attacking_one(self) -> None:
        status = [m for m in (367, 368, 369, 370, 371, 372, 373) if not iso_patcher._shadow_move_slots.is_attacking(m)]
        attack = [m for m in (356, 357, 358, 359, 360) if iso_patcher._shadow_move_slots.is_attacking(m)]
        if len(status) < 2 or not attack:
            self.skipTest("no status pair in the table")
        out = iso_patcher.capped_shadow_moves([status[0], status[1], attack[0], 0])
        self.assertEqual(2, len([m for m in out if m]))
        self.assertTrue(iso_patcher._shadow_move_slots.has_attacking_move([m for m in out if m]))

    def test_two_moves_are_left_alone(self) -> None:
        self.assertEqual([356, 369, 0, 0], iso_patcher.capped_shadow_moves([356, 369, 0, 0]))


class TestIcyWindWeight(unittest.TestCase):
    def test_icy_wind_is_picked_far_less_than_an_equal_share(self) -> None:
        rng = random.Random(7)
        pool = [team_shuffle.ICY_WIND, 1, 2, 3]
        picks = [team_shuffle._pick_extra_move(rng, pool) for _ in range(4000)]
        share = picks.count(team_shuffle.ICY_WIND) / len(picks)
        self.assertLess(share, 0.15)
        self.assertGreater(share, 0.02)

    def test_icy_wind_alone_can_be_dropped(self) -> None:
        rng = random.Random(1)
        results = {team_shuffle._pick_extra_move(rng, [team_shuffle.ICY_WIND]) for _ in range(50)}
        self.assertEqual({None, team_shuffle.ICY_WIND}, results)


class TestMapLevelText(unittest.TestCase):
    def _entry(self, name: str, *lines: str) -> bytes:
        out = name.encode("utf-16-be")
        for line in lines:
            out += map_level_text.NEWLINE + line.encode("utf-16-be")
        return out + map_level_text.TERMINATOR

    def test_the_last_line_is_replaced_in_place(self) -> None:
        a = self._entry("PHENAC CITY", "A gorgeous city in the desert that", "overflows with bounteous water.")
        b = self._entry("PYRITE TOWN", "A noble town.", "x")
        data = bytearray(b"\x00\x00" + a + b)
        before = len(data)
        self.assertEqual(1, map_level_text.rewrite(data, {"PHENAC CITY": 33, "PYRITE TOWN": 20}))
        self.assertEqual(before, len(data))
        self.assertIn("First visit: trainers Lv 33".encode("utf-16-be"), bytes(data))
        self.assertIn(b"x".decode().encode("utf-16-be"), bytes(data))   # too short a line is left alone

    def test_a_line_with_a_control_code_is_left_alone(self) -> None:
        raw = ("CIPHER KEY LAIR".encode("utf-16-be") + map_level_text.NEWLINE + "was wrecked by ".encode("utf-16-be")
               + b"\xff\xff\x05" + ".".encode("utf-16-be") + map_level_text.TERMINATOR)
        data = bytearray(raw)
        self.assertEqual(0, map_level_text.rewrite(data, {"CIPHER KEY LAIR": 60}))
        self.assertEqual(raw, bytes(data))


class TestPatchWords(unittest.TestCase):
    def test_purify_words_only_change_the_compared_constant(self) -> None:
        for address, vanilla, new in purify_anyone.dol_patch_words():
            self.assertEqual(vanilla >> 16, new >> 16, hex(address))
            self.assertEqual(0xFFFF, new & 0xFFFF)

    def test_tutor_unlock_is_one_nop(self) -> None:
        ((address, vanilla, new),) = move_tutor.unlock_all_patch_words()
        self.assertEqual((0x8005E484, 0x41800048, 0x60000000), (address, vanilla, new))

    def test_npc_script_patches_touch_no_anchor_byte(self) -> None:
        for anchors, patches in ((npc_battle_scripts.AFERD_SCRIPT_ANCHORS, npc_battle_scripts.AFERD_SCRIPT_PATCHES),
                                 (npc_battle_scripts.HEBON_SCRIPT_ANCHORS, npc_battle_scripts.HEBON_SCRIPT_PATCHES),
                                 (npc_battle_scripts.LAKEN_SCRIPT_ANCHORS,
                                  npc_battle_scripts.LAKEN_SCRIPT_PATCHES + npc_battle_scripts.LAKEN_REMATCH_PATCHES)):
            anchored = {offset + i for offset, data in anchors for i in range(len(data))}
            for offset, stock, patched in patches:
                self.assertNotIn(offset, anchored)
                self.assertNotEqual(stock, patched)


class TestPokeSpotEqualOdds(unittest.TestCase):
    def test_three_entries_share_one_hundred(self) -> None:
        from ..tools import xd_rel_format as rel_format

        data = bytearray(0x200)
        bases = {"rock": 0x00, "oasis": 0x40, "cave": 0x80}
        for pool, base in bases.items():
            for i, pct in enumerate((50, 30, 20)):
                struct.pack_into(">I", data, base + i * rel_format.POKESPOT_ENTRY_SIZE
                                 + rel_format.POKESPOT_ENCOUNTER_PERCENTAGE_OFFSET, pct)

        class _Rel:
            pass

        old_base, old_count = rel_format.pokespot_pool_base, rel_format.pokespot_pool_count
        rel_format.pokespot_pool_base = lambda rel, pool: bases[pool]
        rel_format.pokespot_pool_count = lambda rel, pool: 3
        try:
            changed = rel_format.apply_pokespot_equal_odds(data, _Rel())
        finally:
            rel_format.pokespot_pool_base, rel_format.pokespot_pool_count = old_base, old_count
        self.assertEqual(9, changed)
        for base in bases.values():
            odds = [struct.unpack_from(">I", data, base + i * rel_format.POKESPOT_ENTRY_SIZE
                                       + rel_format.POKESPOT_ENCOUNTER_PERCENTAGE_OFFSET)[0] for i in range(3)]
            self.assertEqual([34, 33, 33], odds)


class TestPokeSpotVisitorsEqualToo(unittest.TestCase):
    def test_every_pokemon_is_one_in_five(self) -> None:
        from ..tools import xd_rel_format as rel_format

        data = bytearray(0x200)
        bases = {"rock": 0x00, "oasis": 0x40, "cave": 0x80, "all": 0xC0}
        counts = {"rock": 3, "oasis": 3, "cave": 3, "all": 2}
        vanilla = {"rock": (50, 35, 15), "oasis": (50, 35, 15), "cave": (50, 35, 15), "all": (30, 10)}
        for pool, base in bases.items():
            for i, pct in enumerate(vanilla[pool]):
                struct.pack_into(">I", data, base + i * rel_format.POKESPOT_ENTRY_SIZE
                                 + rel_format.POKESPOT_ENCOUNTER_PERCENTAGE_OFFSET, pct)

        class _Rel:
            pass

        old_base, old_count = rel_format.pokespot_pool_base, rel_format.pokespot_pool_count
        rel_format.pokespot_pool_base = lambda rel, pool: bases[pool]
        rel_format.pokespot_pool_count = lambda rel, pool: counts[pool]
        try:
            rel_format.apply_pokespot_equal_odds(data, _Rel())
        finally:
            rel_format.pokespot_pool_base, rel_format.pokespot_pool_count = old_base, old_count

        def odds(pool):
            return [struct.unpack_from(">I", data, bases[pool] + i * rel_format.POKESPOT_ENTRY_SIZE
                                       + rel_format.POKESPOT_ENCOUNTER_PERCENTAGE_OFFSET)[0]
                    for i in range(counts[pool])]

        visitors = odds("all")
        self.assertEqual([20, 20], visitors)
        regular_share = (100 - sum(visitors)) / 100
        for pool in ("rock", "oasis", "cave"):
            for pct in odds(pool):
                self.assertAlmostEqual(0.20, regular_share * pct / 100, delta=0.01)


class TestSixesShadowsOnlyAtTheCipherLab(unittest.TestCase):
    def test_their_catches_are_gated_by_the_cipher_lab_rows_alone(self) -> None:
        from ..game_data import shadow_mirrors, shadow_regions

        for row, ddpk in shadow_mirrors.SIXES_PHENAC_SHADOW_SLOTS:
            gates = shadow_regions.gates_for_ddpk(ddpk)
            self.assertTrue(gates)
            self.assertNotIn(row, shadow_regions.shadow_carriers()[ddpk])
            self.assertTrue(all(g.region == "Cipher Lab" for g in gates))
            self.assertTrue(all(int(g.source.split("#")[1]) in range(33, 39) for g in gates))

    def test_the_phenac_slot_becomes_an_ordinary_copy(self) -> None:
        import os
        from ..game_data import shadow_mirrors
        from ..tools import xd_deck_format as deck_format

        base = "/mnt/user-data/uploads/PokemonXD-working/bridge/dumps/"
        if not (os.path.isfile(base + "deck_story_1.bin") and os.path.isfile(base + "deck_dark_1.bin")):
            self.skipTest("deck dumps not on disk")
        story = deck_format.lzss_decode(open(base + "deck_story_1.bin", "rb").read())
        dark = deck_format.lzss_decode(open(base + "deck_dark_1.bin", "rb").read())
        slots = [{"row": r, "ddpk_index": d} for r, d in shadow_mirrors.SIXES_PHENAC_SHADOW_SLOTS]
        new, written, skipped = iso_patcher.apply_ordinary_copy_edit(story, dark, slots)
        self.assertEqual(6, len(written))
        self.assertEqual([], skipped)
        deck = deck_format.DeckFile(new)
        for row, _ddpk in shadow_mirrors.SIXES_PHENAC_SHADOW_SLOTS:
            team = deck.trainer(row)["team"]
            self.assertFalse([m for m in team if m["kind"] == "DDPK"])
            levels = {m["level"] for m in team}
            self.assertLessEqual(max(levels) - min(levels), 2)
        for row in range(33, 39):
            self.assertTrue([m for m in deck.trainer(row)["team"] if m["kind"] == "DDPK"])


class TestMtBattleChecksOff(PokemonXDTestBase):
    options = {"shuffle_trainer_defeats": True, "trainer_defeat_mode": "unique"}

    def test_none_with_the_exclusion_on(self) -> None:
        names = {loc.name for loc in self.multiworld.get_locations(self.player)}
        self.assertFalse(names & set(mtbattle_trainer_data.MT_BATTLE_DEFEAT_LOCATION_NAMES))

    def test_perr_is_a_check_in_gateon(self) -> None:
        location = self.multiworld.get_location("Gateon Port - Perr's Machine Part", self.player)
        self.assertEqual("Gateon Port", location.parent_region.name)


class TestMtBattleChecksOn(PokemonXDTestBase):
    options = {"shuffle_trainer_defeats": True, "trainer_defeat_mode": "unique", "exclude_mt_battle_trainers": False,
               "mt_battle_progression_checks": 10}

    def test_ninety_seven_with_the_first_ten_open_to_progression(self) -> None:
        from BaseClasses import LocationProgressType

        locations = [self.multiworld.get_location(n, self.player)
                     for n in mtbattle_trainer_data.MT_BATTLE_DEFEAT_LOCATION_NAMES]
        self.assertEqual(97, len(locations))
        open_ones = [loc.name for loc in locations if loc.progress_type != LocationProgressType.EXCLUDED]
        self.assertEqual(list(mtbattle_trainer_data.MT_BATTLE_DEFEAT_LOCATION_NAMES[:10]), open_ones)
        self.assertTrue(all(loc.parent_region.name == "Mt. Battle" for loc in locations))


class TestPokeSpotCatchChecksOff(PokemonXDTestBase):
    options = {"pokespot_catch_checks": False}

    def test_no_check_for_a_poke_spot_only_species(self) -> None:
        from .. import species

        world = self.multiworld.worlds[self.player]
        spot_dex = {entry["new_dex"] for entry in world._pokespot_species_assignment}
        names = {loc.name for loc in self.multiworld.get_locations(self.player)}
        always = {133, int(world.starter_dex)}   # Eevee's and the starter's checks exist whatever the spots hold
        for dex in spot_dex - always:
            self.assertNotIn(species.location_name_for_species(dex), names)


class TestExtraMasterBalls(PokemonXDTestBase):
    options = {"single_master_ball": False, "filler_weight_master_ball": 100,
               "filler_weight_poke_balls": 0, "filler_weight_medicine": 0, "filler_weight_status_heals": 0,
               "filler_weight_berries": 0, "filler_weight_battle_items": 0, "filler_weight_treasure": 0,
               "filler_weight_flutes": 0, "filler_weight_tms": 0, "filler_weight_evolution_stones": 0,
               "filler_weight_currency": 0}

    def test_the_filler_is_master_balls_and_filler(self) -> None:
        from BaseClasses import ItemClassification

        balls = [item for item in self.multiworld.itempool
                 if item.player == self.player and item.name == "Master Ball"]
        self.assertGreater(len(balls), 1)
        self.assertTrue(any(item.classification == ItemClassification.filler for item in balls))


class TestTrackerSlotData(PokemonXDTestBase):
    options = {"randomize_travel_locations": True}

    def test_the_tracker_keys_are_there(self) -> None:
        data = self.multiworld.worlds[self.player].fill_slot_data()
        for key in ("robo_kyogre_parts_unlock_citadark", "robo_kyogre_parts_required", "randomize_travel_locations",
                    "randomize_shops", "agate_village_pit_stop", "shuffle_trainer_defeats", "trainer_defeat_mode",
                    "trainer_defeat_check_count", "purification_checks", "key_item_shuffle", "shuffle_scooter_upgrade",
                    "exclude_mt_battle_trainers", "mt_battle_progression_checks", "pokespot_catch_checks",
                    "shadow_catch_progression", "purification_progression_cap", "goal", "purification_location_count",
                    "room_id_key", "room_area_key"):
            self.assertIn(key, data, key)

    def test_client_and_world_agree_on_the_room_keys(self) -> None:
        from .. import Client, ROOM_AREA_KEY_TEMPLATE, ROOM_ID_KEY_TEMPLATE

        self.assertEqual(ROOM_ID_KEY_TEMPLATE, Client.ROOM_ID_KEY_TEMPLATE)
        self.assertEqual(ROOM_AREA_KEY_TEMPLATE, Client.ROOM_AREA_KEY_TEMPLATE)


class TestStoryByteGoalIsGated(unittest.TestCase):
    """The story-byte goal backstop waits for a settled save block and a held reading."""

    def setUp(self) -> None:
        from pathlib import Path
        self.client = (Path(__file__).resolve().parents[1] / "Client.py").read_text(encoding="utf-8")

    def test_it_runs_inside_the_block_stability_gate(self) -> None:
        gated = self.client.split("if block_is_stable:", 1)[1].split("elif not ctx._block_churn_logged:", 1)[0]
        self.assertIn("await check_victory_story_byte(ctx)", gated)
        self.assertEqual(1, self.client.count("await check_victory_story_byte(ctx)"))

    def test_a_single_reading_does_not_goal(self) -> None:
        import asyncio
        from types import SimpleNamespace
        from unittest import mock
        from .. import Client

        calls = []

        async def declare():
            calls.append(1)

        ctx = SimpleNamespace(finished_game=False, block_base=1, goal=0, victory_story_streak=0,
                              declare_goal_complete=declare)
        with mock.patch.object(Client.ram_client, "story_byte_says_won", side_effect=[True, False, True, True]):
            for _ in range(4):
                asyncio.run(Client.check_victory_story_byte(ctx))
        self.assertEqual([], calls)
        with mock.patch.object(Client.ram_client, "story_byte_says_won", return_value=True):
            asyncio.run(Client.check_victory_story_byte(ctx))
        self.assertEqual([1], calls)


class TestEveryOptionIsInSlotData(PokemonXDTestBase):
    def test_every_world_option(self) -> None:
        from .. import ut_option_names

        data = self.multiworld.worlds[self.player].fill_slot_data()
        for name in ut_option_names():
            self.assertIn(name, data, name)
