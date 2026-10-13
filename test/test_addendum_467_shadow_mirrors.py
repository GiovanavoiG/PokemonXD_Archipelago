"""ADDENDUM 467 (2026-10-11) -- a Shadow given to a trainer goes on every occurrence of that trainer.

Player: "If you're giving them a shadow pokemon, give it to the #1, #2, etc., the same pokemon. Then, if it's caught
from ANY, remove it from all."

The copies share the host's DDPK index, so the save's one Shadow record covers them all and ADDENDUM 465's patch
skips it on every row once it is snagged.
"""
from __future__ import annotations

import os
import random
import tempfile
import unittest
from pathlib import Path

from . import PokemonXDTestBase
from ..game_data import missable_trainers, nightmare_citadark as nc, shadow_mirrors as sm
from ..game_data.catch_rate_exclusions import citadark_trainer_indices
from ..game_data.real_trainer_data import PERMANENTLY_EXCLUDED_TRAINER_INDICES, real_trainer_free_slot_census
from ..game_data.shadow_regions import NO_SNAG_TRAINER_INDICES
from ..game_data.trainer_roster import TRAINERS_BY_INDEX
from ..tools import iso_patcher
from ..tools import xd_deck_format as deck_format

DECK_DUMP = "/mnt/user-data/uploads/PokemonXD-working/bridge/dumps/deck_archive_full1.bin"
FENCE = missable_trainers.shadow_expansion_excluded_trainer_indices() | citadark_trainer_indices()


def _name(index: int) -> str:
    return TRAINERS_BY_INDEX[index]["name"].upper()


class TestOccurrences(unittest.TestCase):
    def test_same_name_rows_in_order(self) -> None:
        self.assertEqual([21, 29, 227], sm.occurrences_of(29))             # Cida #1-#3
        self.assertEqual([17, 60], sm.occurrences_of(17))                  # Naps #1-#2
        self.assertEqual(6, len(sm.occurrences_of(33)))                    # Resix
        for index in TRAINERS_BY_INDEX:
            rows = sm.occurrences_of(index)
            self.assertIn(index, rows)
            self.assertEqual({_name(index)}, {_name(i) for i in rows})

    def test_the_fences(self) -> None:
        blocked = sm.mirror_excluded_trainer_indices()
        for fence in (missable_trainers.POST_GOAL_TRAINER_INDICES, citadark_trainer_indices(), NO_SNAG_TRAINER_INDICES,
                      PERMANENTLY_EXCLUDED_TRAINER_INDICES, sm.MIROR_B_POKE_SPOT_ROWS):
            self.assertTrue(frozenset(fence) <= blocked)
        self.assertIn(15, blocked)                                         # Chobin #1, before the Snag Machine
        self.assertIn(999, sm.mirror_excluded_trainer_indices({999}))


class TestThePlan(unittest.TestCase):
    CENSUS = [{"trainer_index": i, "free_slots": n} for i, n in ((21, 2), (29, 3), (227, 1), (17, 1), (60, 1))]

    def test_copies_go_to_every_other_occurrence(self) -> None:
        shadow = {}
        used = sm.plan_mirrors(self.CENSUS, [(29, shadow)], {29: 1})
        self.assertEqual([21, 227], shadow["mirror_trainer_indices"])
        self.assertEqual({21: 1, 227: 1}, used)

    def test_a_row_without_room_is_left_out(self) -> None:
        a, b, c = {}, {}, {}
        used = sm.plan_mirrors(self.CENSUS, [(29, a), (29, b), (21, c)], {29: 2, 21: 1})
        self.assertEqual([21, 227], a["mirror_trainer_indices"])           # Cida #1: 2 - 1 host = 1 left
        self.assertEqual([], b["mirror_trainer_indices"])                  # ... which `a` took, and #3's one
        self.assertEqual([29], c["mirror_trainer_indices"])                # Cida #2: 3 - 2 hosts = 1 left
        self.assertEqual({227: 1, 21: 1, 29: 1}, used)

    def test_host_claims_and_exclusions(self) -> None:
        shadow = {}
        sm.plan_mirrors(self.CENSUS, [(17, shadow)], {60: 1})              # Naps #2 is full of its own host
        self.assertEqual([], shadow["mirror_trainer_indices"])
        shadow = {}
        sm.plan_mirrors(self.CENSUS, [(29, shadow)], {}, excluded={227})
        self.assertEqual([21], shadow["mirror_trainer_indices"])

    def test_disabled_or_no_census(self) -> None:
        shadow = {"mirror_trainer_indices": [1]}
        self.assertEqual({}, sm.plan_mirrors(None, [(29, shadow)], {}))
        self.assertEqual([], shadow["mirror_trainer_indices"])
        sm.SHADOW_MIRRORS_ENABLED = False
        try:
            shadow = {}
            self.assertEqual({}, sm.plan_mirrors(self.CENSUS, [(29, shadow)], {}))
            self.assertEqual([], shadow["mirror_trainer_indices"])
        finally:
            sm.SHADOW_MIRRORS_ENABLED = True

    def test_the_level_fence(self) -> None:
        census = real_trainer_free_slot_census()
        shadow = {}
        sm.plan_mirrors(census, [(167, shadow)], {167: 1})                 # Chobin #7, level 38
        self.assertNotIn(18, shadow["mirror_trainer_indices"])             # Chobin #2's level-6 team
        self.assertIn(124, shadow["mirror_trainer_indices"])               # Chobin #3, level 26: within 1.5x
        sm.MAX_LEVEL_RATIO = None
        try:
            shadow = {}
            sm.plan_mirrors(census, [(167, shadow)], {167: 1})
            self.assertIn(18, shadow["mirror_trainer_indices"])
        finally:
            sm.MAX_LEVEL_RATIO = 1.5
        level = {row["trainer_index"]: row["avg_level"] for row in census}
        for host in TRAINERS_BY_INDEX:
            if host in FENCE or host not in level:
                continue
            shadow = {}
            sm.plan_mirrors(census, [(host, shadow)], {host: 1})
            for other in shadow["mirror_trainer_indices"]:
                self.assertGreaterEqual(level[other] * 1.5, level[host], (host, other))

    def test_deterministic(self) -> None:
        census = real_trainer_free_slot_census()
        hosts = sorted(t for t in TRAINERS_BY_INDEX if t not in FENCE and len(sm.occurrences_of(t)) > 1)
        first = [(h, {}) for h in hosts]
        second = [(h, {}) for h in hosts]
        self.assertEqual(sm.plan_mirrors(census, first, {}), sm.plan_mirrors(census, second, {}))
        self.assertEqual([s["mirror_trainer_indices"] for _, s in first],
                         [s["mirror_trainer_indices"] for _, s in second])


def _all_shadows(world):
    for plan in world._nightmare_relocations:
        for shadow in plan["shadows"]:
            yield int(plan["trainer_index"]), shadow
    for plan in world._shadow_expansion_plans or ():
        for mon in plan["new_pokemon"]:
            yield int(plan["trainer_index"]), mon


class _SeedChecks:
    def test_every_shadow_carries_its_copies(self) -> None:
        world = self.multiworld.worlds[self.player]
        shadows = list(_all_shadows(world))
        self.assertTrue(shadows)
        blocked = sm.mirror_excluded_trainer_indices(
            frozenset(world._shadow_removal_trainers) | frozenset(world._nightmare_teams or ()))
        any_copy = False
        for host, shadow in shadows:
            mirrors = shadow["mirror_trainer_indices"]
            any_copy |= bool(mirrors)
            self.assertEqual(len(mirrors), len(set(mirrors)))
            self.assertNotIn(host, mirrors)
            for other in mirrors:
                self.assertEqual(_name(host), _name(other))
                self.assertNotIn(other, blocked)
        self.assertTrue(any_copy, "no Shadow was copied anywhere on this seed")

    def test_no_row_is_over_committed(self) -> None:
        from .test_addendum_423_nightmare_citadark import _seed_data
        world = self.multiworld.worlds[self.player]
        free = {row["trainer_index"]: row["free_slots"] for row in real_trainer_free_slot_census()}
        used: "dict[int, int]" = {}
        for host, shadow in _all_shadows(world):
            used[host] = used.get(host, 0) + 1
            for other in shadow["mirror_trainer_indices"]:
                used[other] = used.get(other, 0) + 1
        seed = _seed_data(world)
        for step in (seed.get("enhanced_difficulty_plan") or {}).get("team_slot_plan", ()):
            used[int(step["trainer_index"])] = used.get(int(step["trainer_index"]), 0) + 1
        for trainer, count in used.items():
            self.assertLessEqual(count, free.get(trainer, 0), trainer)
        copies = sum(len(s["mirror_trainer_indices"]) for _, s in _all_shadows(world))
        self.assertEqual(copies, sum(world._shadow_mirror_slots.values()))

    def test_the_seed_carries_them_to_the_patcher(self) -> None:
        from .test_addendum_423_nightmare_citadark import _seed_data
        world = self.multiworld.worlds[self.player]
        seed = _seed_data(world)
        for plan in seed.get("new_shadow_pokemon_plans") or ():
            for mon in plan["new_pokemon"]:
                self.assertIn("mirror_trainer_indices", mon)
        for plan in seed.get("nightmare_shadow_relocations") or ():
            for shadow in plan["shadows"]:
                self.assertIn("mirror_trainer_indices", shadow)


class TestExpansionAndRemoval(_SeedChecks, PokemonXDTestBase):
    options = {"shadow_pokemon_expansion": 44, "remove_citadark_shadows": True, "enhanced_difficulty": 3}


class TestNightmare(_SeedChecks, PokemonXDTestBase):
    options = {"nightmare_citadark": True, "shadow_pokemon_expansion": 44, "enhanced_difficulty": 3,
               "randomize_shadow_species": True}


# --- the patch --------------------------------------------------------------------------------------------------

def _real_entries():
    data = Path(DECK_DUMP).read_bytes()
    entries = iso_patcher.parse_fsys(data)

    def dec(name):
        e = entries[name]
        return deck_format.lzss_decode(data[e["data_off"]:e["data_off"] + 0x10 + e["comp_size"]])

    return dec


def _refs(deck) -> "dict[int, list[tuple[int, int]]]":
    refs: "dict[int, list[tuple[int, int]]]" = {}
    for trainer in deck.all_trainers():
        mask = deck.data[deck.dtnr_data + trainer["index"] * 0x38 + 4]
        for m in trainer["team"]:
            if m["kind"] == "DDPK":
                refs.setdefault(m["ddpk_index"], []).append((trainer["index"], (mask >> m["slot"]) & 1))
    return refs


class TestTheMirrorWriter(unittest.TestCase):
    def test_lowest_free_slot_mask_and_skip(self) -> None:
        from .test_addendum_423_nightmare_citadark import _deck, _record
        records = [bytes(0x20)] + [_record(10 + i, 60) for i in range(1, 8)]
        story = _deck({1: {"ai": 1, "slots": [1, 2]}, 2: {"ai": 2, "slots": [3, 4, 5, 6, 7, 1]}}, records,
                      [bytes(0x20)] * 3)
        deck = deck_format.DeckFile(story)
        buf = bytearray(story)
        written, skipped = iso_patcher._write_mirror_slots(buf, deck, {}, 9, [1, 2, 40])
        self.assertEqual(([1], [2, 40]), (written, skipped))
        after = deck_format.DeckFile(bytes(buf))
        member = [m for m in after.trainer(1)["team"] if m["kind"] == "DDPK"]
        self.assertEqual([(9, 2)], [(m["ddpk_index"], m["slot"]) for m in member])
        self.assertEqual(1 << 2, after.data[after.dtnr_data + 1 * 0x38 + 4] & (1 << 2))
        self.assertEqual(story[deck.dtnr_data + 2 * 0x38:][:0x38], bytes(buf[deck.dtnr_data + 2 * 0x38:][:0x38]))


@unittest.skipUnless(os.path.exists(DECK_DUMP), "needs a real deck_archive.fsys dump")
class TestOnTheRealDeck(unittest.TestCase):
    def test_relocations_land_on_every_occurrence(self) -> None:
        dec = _real_entries()
        story, colo, dark = dec("DeckData_Story.bin"), dec("DeckData_Colosseum.bin"), dec("DeckData_DarkPokemon.bin")
        keys = nc.assign_teams(random.Random(467))
        out, _ = iso_patcher.apply_nightmare_citadark_edit(
            story, {"DeckData_Colosseum.bin": colo}, {t: nc.seed_entry(k) for t, k in keys.items()})
        census = real_trainer_free_slot_census()
        plan = nc.plan_relocations(random.Random(467), census, FENCE)
        hosts = [(int(p["trainer_index"]), s) for p in plan for s in p["shadows"]]
        taken: "dict[int, int]" = {}
        for host, _ in hosts:
            taken[host] = taken.get(host, 0) + 1
        sm.plan_mirrors(census, hosts, taken, excluded=frozenset(keys))
        self.assertTrue(any(s["mirror_trainer_indices"] for _, s in hosts))
        out, levels = iso_patcher.apply_nightmare_relocation_edit(out, dark, plan)
        self.assertEqual(35, len(levels))
        refs = _refs(deck_format.DeckFile(out))
        for host, shadow in hosts:
            expect = sorted([host] + shadow["mirror_trainer_indices"])
            self.assertEqual(expect, sorted(t for t, _ in refs[shadow["ddpk_index"]]), shadow["ddpk_index"])
            self.assertTrue(all(bit for _, bit in refs[shadow["ddpk_index"]]))

    def test_the_expansion_writes_them_end_to_end(self) -> None:
        from .test_addendum_423_nightmare_citadark import _fsys
        from .test_addendum_424_relocated_citadark_shadows import _two_file_iso
        dec = _real_entries()
        story, dark = dec("DeckData_Story.bin"), dec("DeckData_DarkPokemon.bin")
        census = real_trainer_free_slot_census()
        free = {row["trainer_index"]: row["free_slots"] for row in census}
        level = {row["trainer_index"]: row["avg_level"] for row in census}
        hosts_rows = [29, 17, 33]                                          # Cida #2, Naps #1, Resix #1
        plans = [{"trainer_index": t, "new_pokemon": [{"species": 25 + i, "level": 30, "moves": [33, 0, 0, 0]}]}
                 for i, t in enumerate(hosts_rows)]
        sm.plan_mirrors(census, [(p["trainer_index"], p["new_pokemon"][0]) for p in plans],
                        {t: 1 for t in hosts_rows})
        for p in plans:
            mirrors = p["new_pokemon"][0]["mirror_trainer_indices"]
            self.assertEqual([t for t in sm.occurrences_of(p["trainer_index"])
                              if t != p["trainer_index"] and free.get(t, 0) > 0
                              and t not in sm.mirror_excluded_trainer_indices()
                              and (p["trainer_index"] not in level or level[t] * 1.5 >= level[p["trainer_index"]])],
                             mirrors)
        deck_archive = _fsys([(b"DeckData_Story.bin", story), (b"DeckData_DarkPokemon.bin", dark)])
        common = _fsys([(b"DeckData_DarkPokemon.bin", dark), (b"DeckData_DarkPokemon_EU.bin", dark)])
        iso = _two_file_iso([(b"deck_archive.fsys", deck_archive), (b"common.fsys", common)])
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "copy.iso"
            path.write_bytes(iso)
            result = iso_patcher.write_shadow_multi_trainer_patch(path, plans)
            reader = iso_patcher.open_reader(path)
            try:
                fst = iso_patcher.parse_fst(reader)
                off, length, _ = iso_patcher.find_by_basename(fst, "deck_archive.fsys")
                container = reader.read(off, length)
            finally:
                reader.close()
        e = iso_patcher.parse_fsys(container)["DeckData_Story.bin"]
        raw = container[e["data_off"]:e["data_off"] + 0x10 + e["comp_size"]]
        deck = deck_format.DeckFile(deck_format.lzss_decode(raw))
        refs = _refs(deck)
        self.assertEqual({}, result["mirrors_skipped"])
        for p in plans:
            mon = p["new_pokemon"][0]
            found = [ddpk for ddpk, rows in refs.items() if (p["trainer_index"], 1) in rows]
            new = [d for d in found if d in result["mirrors_written"]]
            self.assertEqual(1, len(new), p["trainer_index"])
            self.assertEqual(sorted([p["trainer_index"]] + mon["mirror_trainer_indices"]),
                             sorted(t for t, bit in refs[new[0]] if bit))
            self.assertEqual(mon["mirror_trainer_indices"], result["mirrors_written"][new[0]])


class TestThePatcherReportsIt(unittest.TestCase):
    def test_summary_keys(self) -> None:
        source = Path(iso_patcher.__file__).read_text(encoding="utf-8")
        body = source.split("def apply_patch(", 1)[1]
        self.assertIn('summary["shadow_mirror_slots"]', body)
        self.assertIn('summary["shadow_mirror_skipped"]', body)


if __name__ == "__main__":
    unittest.main()
