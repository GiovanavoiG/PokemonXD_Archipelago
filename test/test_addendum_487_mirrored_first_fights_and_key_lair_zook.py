"""ADDENDUM 487 (2026-10-13).

1. Player: "clerr/belish/dosk/dert/raling/labet/doby can be opened with the mirrors. Leave the rest as is." Their first
   fights may host a Shadow, and the second fight always carries its mirror. Then: "You can open Cail with the mirrors
   too." -- his first fight hosts, his second and third carry the copy.
2. Player: "Zook is still rematching us ... Beating him puts it from 64 to 65, but returning put me back at 64." The
   Key Lair's floor is banked off Zook's defeat itself, wherever it is fought.
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from .. import Client, ram_client as rc
from ..game_data import missable_trainers as mt, shadow_mirrors as sm, trainer_roster as tr
from ..game_data import story_bytes as sb


class TestTheOpenedHosts(unittest.TestCase):
    def test_exactly_the_named_trainers(self) -> None:
        from ..game_data import trainer_placements as tp
        names = {tr.TRAINERS_BY_INDEX[i]["name"].upper() for i in sm.MIRRORED_SHADOW_HOSTS}
        self.assertEqual({"CLERR", "BELISH", "DOSK", "DERT", "RALING", "LABET", "DOBY", "CAIL"}, names)
        for host, partners in sm.MIRRORED_SHADOW_HOSTS.items():
            self.assertEqual(1, tr.TRAINERS_BY_INDEX[host]["occurrence"])
            # Every LATER row with a region is a partner -- the copy is in every fight a late player could meet.
            later = sorted(i for i, t in tr.TRAINERS_BY_INDEX.items()
                           if t["name"] == tr.TRAINERS_BY_INDEX[host]["name"] and i != host
                           and tp.PLACEMENTS.get(i) is not None and tp.PLACEMENTS[i].region is not None)
            self.assertEqual(later, sorted(partners), host)

    def test_hosts_open_partners_closed(self) -> None:
        excluded = mt.shadow_expansion_excluded_trainer_indices()
        self.assertFalse(set(sm.MIRRORED_SHADOW_HOSTS) & excluded)
        self.assertTrue(sm.mirrored_partner_rows() <= excluded, "a partner only ever carries the copy")

    def test_the_rest_stay_as_they_were(self) -> None:
        for index in (173, 191, 193, 194, 202, 18, 124, 125, 127, 166, 128, 165, 112, 118):
            self.assertIn(index, mt.shadow_expansion_excluded_trainer_indices(), index)

    def test_the_census_cap(self) -> None:
        census = [{"trainer_index": 22, "free_slots": 5, "avg_level": 20}, {"trainer_index": 82, "free_slots": 2,
                                                                            "avg_level": 25},
                  {"trainer_index": 300, "free_slots": 4, "avg_level": 9}]
        capped = {r["trainer_index"]: r["free_slots"] for r in sm.cap_census_for_mirrored_hosts(census)}
        self.assertEqual({22: 2, 82: 2, 300: 4}, capped)
        cail = [{"trainer_index": 62, "free_slots": 4}, {"trainer_index": 90, "free_slots": 3},
                {"trainer_index": 126, "free_slots": 1}]
        self.assertEqual(1, sm.cap_census_for_mirrored_hosts(cail)[0]["free_slots"], "the tightest partner")

    def test_the_partner_copy_is_placed_first_and_past_the_level_rule(self) -> None:
        census = [{"trainer_index": 22, "free_slots": 2, "avg_level": 40.0},
                  {"trainer_index": 82, "free_slots": 2, "avg_level": 10.0},   # far below the 1.5x rule
                  {"trainer_index": 230, "free_slots": 3, "avg_level": 50.0}]
        shadows = [{}, {}]
        sm.plan_mirrors(census, [(22, shadows[0]), (22, shadows[1])], {22: 2})
        for shadow in shadows:
            self.assertEqual(82, shadow["mirror_trainer_indices"][0])
            self.assertNotIn("mirror_required_missing", shadow)


class TestInRealSeeds(unittest.TestCase):
    def test_every_shadow_on_a_first_fight_is_mirrored_on_the_second(self) -> None:
        from test.general import setup_multiworld
        from worlds.AutoWorld import AutoWorldRegister

        world_type = AutoWorldRegister.world_types["Pokemon XD Gale of Darkness"]
        hosted = 0
        for seed in range(4870, 4890):
            options = {"shadow_pokemon_expansion": 44}
            if seed % 2:
                options.update({"remove_citadark_shadows": True, "remove_greevil_shadows": True})
            world = setup_multiworld(world_type, ("generate_early",), seed=seed, options=options).worlds[1]
            plans = [(int(p["trainer_index"]), m) for p in (world._shadow_expansion_plans or ()) for m in p["new_pokemon"]]
            plans += [(int(p["trainer_index"]), s) for p in world._nightmare_relocations for s in p["shadows"]]
            for host, shadow in plans:
                self.assertNotIn(host, sm.mirrored_partner_rows(), seed)
                if host in sm.MIRRORED_SHADOW_HOSTS:
                    hosted += 1
                    for partner in sm.MIRRORED_SHADOW_HOSTS[host]:
                        self.assertIn(partner, shadow["mirror_trainer_indices"], (seed, host))
                    self.assertNotIn("mirror_required_missing", shadow)
        self.assertGreater(hosted, 0, "the opened first fights do get Shadows")


class TestKeyLairZook(unittest.TestCase):
    def _ctx(self, travel=True, surnames=("ZOOK",)):
        ctx = SimpleNamespace(randomize_travel_locations=travel, block_base=0x80400000,
                              trainer_defeat_tracker=SimpleNamespace(last_confirmed_surnames=set(surnames)),
                              area_story_memory=rc.AreaStoryByteMemory(), area_story_memory_path=None)
        return ctx

    def _run(self, ctx, live):
        with mock.patch.object(rc, "read_story_byte", return_value=live), \
                mock.patch.object(Client, "_note"):
            Client._bank_key_lair_zook(ctx)

    def test_the_win_banks_the_floor_and_the_next_visit_is_past_him(self) -> None:
        ctx = self._ctx()
        self.assertEqual(0x64, ctx.area_story_memory.target_for("Cipher Key Lair"), "the player's report")
        self._run(ctx, 0x65)
        self.assertEqual(0x65, ctx.area_story_memory.highest_by_region["Cipher Key Lair"])
        self.assertEqual(0x66, ctx.area_story_memory.target_for("Cipher Key Lair"))

    def test_seen_before_the_script_moves_the_byte(self) -> None:
        ctx = self._ctx()
        self._run(ctx, 0x64)
        self.assertEqual(0x66, ctx.area_story_memory.target_for("Cipher Key Lair"))

    def test_not_his_gateon_fight_not_vanilla_travel_never_lowered(self) -> None:
        ctx = self._ctx()
        self._run(ctx, 0x12)
        self.assertNotIn("Cipher Key Lair", ctx.area_story_memory.highest_by_region)
        ctx = self._ctx(travel=False)
        self._run(ctx, 0x65)
        self.assertNotIn("Cipher Key Lair", ctx.area_story_memory.highest_by_region)
        ctx = self._ctx(surnames=("BIDEN",))
        self._run(ctx, 0x65)
        self.assertNotIn("Cipher Key Lair", ctx.area_story_memory.highest_by_region)
        ctx = self._ctx()
        ctx.area_story_memory.highest_by_region["Cipher Key Lair"] = 0x69
        self._run(ctx, 0x65)
        self.assertEqual(0x69, ctx.area_story_memory.highest_by_region["Cipher Key Lair"])

    def test_wired_into_the_defeat_check(self) -> None:
        body = Client.__dict__["check_trainer_defeats"].__code__.co_names
        self.assertIn("_bank_key_lair_zook", body)

    def test_the_rule_it_feeds(self) -> None:
        self.assertEqual(0x66, sb.dynamic_region_floor("Cipher Key Lair", {"Cipher Key Lair": 0x65}))


if __name__ == "__main__":
    unittest.main()
