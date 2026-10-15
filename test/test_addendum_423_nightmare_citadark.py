"""ADDENDUM 423 (2026-10-06) -- Nightmare Citadark.

The Nightmare_Citadark option replaces every Citadark trainer's team with one of these teams at level 100: XD +
Colosseum teams, no Shadow Pokemon at all while the option is enabled, always six, and the AI copied from those
trainers in their respective games. Every trainer has a unique team, their moves are NOT overwritten by the TM
enhanced difficulty, and they stay at 100 rather than being scaled higher by other options.
"""
from __future__ import annotations

import json
import os
import random
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path

from . import PokemonXDTestBase
from ..game_data import nightmare_citadark as nc
from ..tools import iso_patcher
from ..tools import xd_deck_format as deck_format

DECK_DUMP = "/mnt/user-data/uploads/PokemonXD-working/bridge/dumps/deck_archive_full1.bin"
COLO_COMMON = "/mnt/user-data/uploads/PokemonXD-working/colo_fs/files/common.fsys"


# --- the pool ---------------------------------------------------------------------------------------------------

class TestThePool(unittest.TestCase):
    def test_forty_four_teams_of_six(self) -> None:
        self.assertEqual(28, len(nc.XD_ORRE_COLOSSEUM_TEAMS))
        self.assertEqual(16, len(nc.COLOSSEUM_ORRE_LV100_TEAMS))
        self.assertEqual(44, len(set(nc.TEAM_KEYS)))
        for key in nc.TEAM_KEYS:
            self.assertEqual(6, len(nc.team_species(key)), key)

    def test_every_trainer_gets_a_different_team(self) -> None:
        trainers = nc.nightmare_trainer_indices()
        self.assertEqual(33, len(trainers))           # ADDENDUM 424: Greevil's Lugia fight stays
        self.assertNotIn(nc.GREEVIL_LUGIA_TRAINER, trainers)
        for seed in range(200):
            teams = nc.assign_teams(random.Random(seed))
            self.assertEqual(set(trainers), set(teams))
            self.assertEqual(len(teams), len(set(teams.values())), seed)

    def test_too_many_trainers_is_refused_not_repeated(self) -> None:
        with self.assertRaises(ValueError):
            nc.assign_teams(random.Random(0), range(45))

    def test_colosseum_sets_are_explicit_and_in_range(self) -> None:
        for row, team in nc.COLOSSEUM_ORRE_LV100_TEAMS.items():
            for member in team:
                self.assertEqual(6, len(member.ivs))
                self.assertEqual(6, len(member.evs))
                self.assertEqual(4, len(member.moves))
                self.assertTrue(all(0 <= v <= 31 for v in member.ivs), row)
                self.assertTrue(all(0 <= v <= 252 for v in member.evs), row)
                self.assertLessEqual(sum(member.evs), 510, row)
                self.assertTrue(all(0 <= m <= 354 for m in member.moves), row)    # no Shadow moves
                self.assertIn(member.gender, (0, 1, 2))
                self.assertIn(member.ability, (0, 1))
                self.assertLess(member.nature, 25)
                self.assertLess(member.ai_role, 79)          # both games' role tables have 79 rows

    def test_seed_entries(self) -> None:
        xd = nc.seed_entry("xd:41")
        self.assertEqual({"key": "xd:41", "deck": "DeckData_Colosseum.bin", "trainer": 41,
                          "species": list(nc.XD_ORRE_COLOSSEUM_TEAMS[41])}, xd)
        colo = nc.seed_entry("colo:559")
        self.assertEqual(6, len(colo["sets"]))
        self.assertEqual(nc.dtai_row(nc.COLOSSEUM_ORRE_LV100_AI_STYLES[559]).hex(), colo["ai_row"])
        self.assertEqual(json.loads(json.dumps(colo)), colo)

    def test_thirty_five_shadows_leave_citadark(self) -> None:
        self.assertEqual(35, len(nc.removed_shadow_ddpks()))
        self.assertEqual(35, len(nc.removed_shadow_dpkm_indices()))
        self.assertNotIn(73, nc.removed_shadow_ddpks())               # Shadow Lugia, DDPK 73


@unittest.skipUnless(os.path.exists(DECK_DUMP), "needs a real deck_archive.fsys dump")
class TestTheXDTablesMatchTheDisc(unittest.TestCase):
    def test_species(self) -> None:
        data = Path(DECK_DUMP).read_bytes()
        entry = iso_patcher.parse_fsys(data)["DeckData_Colosseum.bin"]
        deck = deck_format.DeckFile(deck_format.lzss_decode(
            data[entry["data_off"]:entry["data_off"] + 0x10 + entry["comp_size"]]))
        for index, species in nc.XD_ORRE_COLOSSEUM_TEAMS.items():
            team = sorted(deck.trainer(index)["team"], key=lambda m: m["slot"])
            self.assertEqual(list(species), [m["species"] for m in team], index)


@unittest.skipUnless(os.path.exists(COLO_COMMON), "needs Pokemon Colosseum's common.fsys")
class TestTheColosseumTableMatchesTheDisc(unittest.TestCase):
    """Rows 559-574 of Colosseum's Trainer table (0x34/row), members from TrainerPokemonData (0x50/row)."""

    def test_every_field(self) -> None:
        data = Path(COLO_COMMON).read_bytes()
        entry = iso_patcher.parse_fsys(data)["common_rel"]
        rel = deck_format.lzss_decode(data[entry["data_off"]:entry["data_off"] + 0x10 + entry["comp_size"]])
        trainers, members = 0x92ED0, 0x9FE28
        for row, team in nc.COLOSSEUM_ORRE_LV100_TEAMS.items():
            first = struct.unpack_from(">H", rel, trainers + row * 0x34 + 4)[0]
            for k, member in enumerate(team):
                r = rel[members + (first + k) * 0x50:members + (first + k) * 0x50 + 0x50]
                self.assertEqual(100, r[4])
                self.assertEqual(0, r[3])                                   # no Shadow
                self.assertEqual(member.species, struct.unpack_from(">H", r, 0x0A)[0])
                self.assertEqual(member.item, struct.unpack_from(">I", r, 0x10)[0])
                self.assertEqual(member.happiness, struct.unpack_from(">h", r, 0x08)[0])
                self.assertEqual(member.ai_role, r[6])
                self.assertEqual(member.ivs, tuple(r[0x1C:0x22]))
                self.assertEqual(member.evs, struct.unpack_from(">6H", r, 0x22))
                self.assertEqual(member.moves, tuple(struct.unpack_from(">H", r, 0x30 + 8 * j + 6)[0]
                                                     for j in range(4)))
                self.assertEqual((member.ability, member.gender, member.nature), (r[0], r[1], r[2]))


# --- generation -------------------------------------------------------------------------------------------------

def _seed_data(world) -> dict:
    with tempfile.TemporaryDirectory() as tmp_dir:
        world.generate_output(tmp_dir)
        with zipfile.ZipFile(next(Path(tmp_dir).glob("*.appxd"))) as zf:
            return json.loads(zf.read("seed.json"))


class TestOff(PokemonXDTestBase):
    options = {"nightmare_citadark": False}

    def test_nothing_changes(self) -> None:
        world = self.multiworld.worlds[self.player]
        self.assertIsNone(world._nightmare_teams)
        self.assertEqual(75, world._vanilla_shadow_count)   # RETARGETED BY ADDENDUM 479 (was 83)
        self.assertNotIn("nightmare_removed_shadow_dex", world.fill_slot_data())
        self.assertIsNone(_seed_data(world)["nightmare_citadark_teams"])


class TestOn(PokemonXDTestBase):
    options = {"nightmare_citadark": True, "shadow_pokemon_expansion": 30, "catch_rate_scaling": "guaranteed_catches",
               "catch_rate_exclude_citadark": True, "catch_rate_exclude_greevil": True,
               "enhanced_difficulty": 3, "enhanced_difficulty_level_scaling": True, "path_level_scaling": True}

    def test_unique_teams_on_every_citadark_trainer(self) -> None:
        teams = self.multiworld.worlds[self.player]._nightmare_teams
        self.assertEqual(set(nc.nightmare_trainer_indices()), set(teams))
        self.assertEqual(33, len(set(teams.values())))

    def test_every_shadow_still_counts(self) -> None:
        """ADDENDUM 424: 48 stay put (47 off Citadark, plus Lugia), 35 move, and the expansion adds its own."""
        world = self.multiworld.worlds[self.player]
        # RETARGETED BY ADDENDUM 479: 46 -- Lugia and the post-game Dragonite stay put but have no rungs.
        self.assertEqual(46, world._vanilla_shadow_count)
        purify = [loc for loc in self.multiworld.get_locations(self.player) if loc.name.startswith("Purify ")]
        self.assertEqual(46 + 35 + 30, len(purify))
        self.assertNotIn("nightmare_removed_shadow_dex", world.fill_slot_data())

    def test_catch_exclusions_kept_for_lugia(self) -> None:
        options = self.multiworld.worlds[self.player].options
        self.assertTrue(options.catch_rate_exclude_citadark)
        self.assertTrue(options.catch_rate_exclude_greevil)

    def test_no_expansion_shadow_lands_on_citadark(self) -> None:
        from ..game_data.catch_rate_exclusions import citadark_trainer_indices
        plans = self.multiworld.worlds[self.player]._shadow_expansion_plans or ()
        self.assertTrue(plans)
        self.assertFalse({int(p["trainer_index"]) for p in plans} & set(citadark_trainer_indices()))

    def test_only_lugia_waits_on_citadark(self) -> None:
        from .. import rules
        weights = rules._purification_weights_for(self.multiworld.worlds[self.player])
        self.assertEqual(46, sum(weights.values()))
        # RETARGETED BY ADDENDUM 432: Lugia, and Miror B.'s post-game Dragonite, which was filed at the Poke Spots by
        # name and is now held to the end game. RETARGETED AGAIN BY ADDENDUM 479: neither has a rung any more.
        self.assertIsNone(weights.get("Citadark Isle"))

    def test_seed_data(self) -> None:
        world = self.multiworld.worlds[self.player]
        seed_data = _seed_data(world)
        carried = seed_data["nightmare_citadark_teams"]
        self.assertEqual({str(t): nc.seed_entry(k) for t, k in world._nightmare_teams.items()}, carried)
        self.assertIn(nc.GREEVIL_LUGIA_TRAINER, seed_data["max_catch_rate_excluded_trainers"])
        # "make sure they're 100 and not scaled higher": Enhanced Difficulty neither pads nor re-levels them.
        plan = seed_data["enhanced_difficulty_plan"]
        padded = {int(step["trainer_index"]) for step in plan["team_slot_plan"]}
        self.assertFalse(padded & set(nc.nightmare_trainer_indices()))


class TestFingerprints(PokemonXDTestBase):
    options = {"nightmare_citadark": True}

    def test_citadark_fights_are_described_by_their_new_teams(self) -> None:
        world = self.multiworld.worlds[self.player]
        prints = world._trainer_team_fingerprints or {}
        from ..game_data import trainer_roster
        checked = 0
        for trainer in trainer_roster.TRAINERS:
            key = (world._nightmare_teams or {}).get(trainer["index"])
            label = trainer_roster.trainer_label(trainer)
            if key is None or label not in prints:
                continue
            checked += 1
            self.assertEqual([100] * 6, prints[label]["levels"], label)
        self.assertGreater(checked, 0)


# --- the patch --------------------------------------------------------------------------------------------------

def _deck(trainers: "dict[int, dict]", records: "list[bytes]", dtai_rows: "list[bytes]") -> bytes:
    """A real-format DECK: `trainers` = {index: {"ai": n, "slots": [dpkm...], "mask": m, "combo": bytes}}."""
    count = max(trainers) + 1
    dtnr = bytearray(0x10 + count * 0x38)
    dtnr[0:4] = b"DTNR"
    struct.pack_into(">II", dtnr, 4, len(dtnr), count)
    for index, t in trainers.items():
        base = 0x10 + index * 0x38
        dtnr[base + 0x04] = t.get("mask", 0)
        dtnr[base + 0x05] = 1
        for slot, value in enumerate(t["slots"]):
            struct.pack_into(">H", dtnr, base + 0x1C + slot * 2, value)
        struct.pack_into(">H", dtnr, base + 0x28, t["ai"])
        dtnr[base + 0x2C:base + 0x38] = t.get("combo", bytes(12))
    dpkm = bytearray(0x10) + b"".join(records)
    dpkm[0:4] = b"DPKM"
    struct.pack_into(">II", dpkm, 4, len(dpkm), len(records))
    dtai = bytearray(0x10) + b"".join(dtai_rows)
    dtai[0:4] = b"DTAI"
    struct.pack_into(">II", dtai, 4, len(dtai), len(dtai_rows))
    dstr = bytearray(0x10)
    dstr[0:4] = b"DSTR"
    struct.pack_into(">I", dstr, 4, 0x10)
    head = bytearray(0x10)
    head[0:4] = b"DECK"
    return bytes(head + dtnr + dpkm + dtai + dstr)


def _record(species: int, level: int, moves=(1, 2, 3, 4), role: int = 1) -> bytes:
    r = bytearray(0x20)
    struct.pack_into(">H", r, 0, species)
    r[2] = level
    r[6] = role
    struct.pack_into(">HHHH", r, 0x14, *moves)
    r[0x1D] = 0x40
    return bytes(r)


def _fixture():
    # Story: trainer 1 (citadark stand-in) with three members incl. a Shadow slot; trainer 2 untouched.
    story_records = [bytes(0x20)] + [_record(10 + i, 40) for i in range(1, 6)]
    story = _deck({1: {"ai": 1, "slots": [1, 2, 7], "mask": 0b100}, 2: {"ai": 2, "slots": [3, 4]}},
                  story_records, [bytes(0x20), b"\x26" + bytes(31), b"\x27" + bytes(31)])
    # Source: trainer 1 a six-member team with combos and a rich AI row.
    src_records = [bytes(0x20)] + [_record(100 + i, 60, moves=(50 + i, 60, 70, 80), role=16) for i in range(6)]
    source = _deck({1: {"ai": 1, "slots": [1, 2, 3, 4, 5, 6], "combo": bytes.fromhex("0009000a0000000050500000")}},
                   src_records, [bytes(0x20), bytes.fromhex("4f3a0000737374737373720" + "0" * 41)])
    return story, source


class TestTheEdit(unittest.TestCase):
    def test_an_xd_team_is_copied_whole_at_level_100(self) -> None:
        story, source = _fixture()
        teams = {1: {"deck": "Src", "trainer": 1, "species": [100, 101, 102, 103, 104, 105]}}
        out, result = iso_patcher.apply_nightmare_citadark_edit(story, {"Src": source}, teams)
        self.assertEqual({"trainers_replaced": 1, "members_added": 6}, result)
        deck, src = deck_format.DeckFile(out), deck_format.DeckFile(source)
        trainer = deck.trainer(1)
        self.assertEqual(6, trainer["party_size"])
        self.assertTrue(all(m["kind"] == "DPKM" for m in trainer["team"]))
        for slot, member in enumerate(sorted(trainer["team"], key=lambda m: m["slot"])):
            got = deck.data[deck.dpkm_data + member["dpkm_index"] * 0x20:][:0x20]
            want = bytearray(src.data[src.dpkm_data + (slot + 1) * 0x20:][:0x20])
            want[2] = 100
            self.assertEqual(bytes(want), got)      # moves, role, combo flags: exactly the source's
        base = deck.dtnr_data + 0x38
        self.assertEqual(bytes.fromhex("0009000a0000000050500000"), deck.data[base + 0x2C:base + 0x38])
        self.assertEqual(src.data[src.dtai_data + 0x20:][:0x20], deck.data[deck.dtai_data + 0x20:][:0x20])

    def test_nothing_else_moves(self) -> None:
        story, source = _fixture()
        teams = {1: {"deck": "Src", "trainer": 1, "species": [100, 101, 102, 103, 104, 105]}}
        out, _ = iso_patcher.apply_nightmare_citadark_edit(story, {"Src": source}, teams)
        before, after = deck_format.DeckFile(story), deck_format.DeckFile(out)
        self.assertEqual(before.data[before.dtnr_data + 2 * 0x38:][:0x38], after.data[after.dtnr_data + 2 * 0x38:][:0x38])
        self.assertEqual(before.data[before.dpkm_data:before.dtai_hdr], after.data[after.dpkm_data:after.dpkm_data + 6 * 0x20])
        self.assertEqual(before.data[before.dtai_data + 0x40:][:0x20], after.data[after.dtai_data + 0x40:][:0x20])

    def test_a_colosseum_team_is_built_from_its_sets(self) -> None:
        story, source = _fixture()
        entry = nc.seed_entry("colo:559")
        out, _ = iso_patcher.apply_nightmare_citadark_edit(story, {"Src": source}, {1: entry})
        deck = deck_format.DeckFile(out)
        members = sorted(deck.trainer(1)["team"], key=lambda m: m["slot"])
        for member, s in zip(members, nc.COLOSSEUM_ORRE_LV100_TEAMS[559]):
            full = deck.dpkm_full(member["dpkm_index"])
            self.assertEqual((s.species, 100, s.happiness, s.item, s.ai_role, list(s.ivs), list(s.evs), list(s.moves)),
                             (full["species"], full["level"], full["happiness"], full["item"], full["ai_role"],
                              full["ivs"], full["evs"], full["moves"]))
            byte = full["nature_gender_ability"]
            self.assertEqual((s.nature, s.gender, s.ability), (byte >> 3, (byte >> 1) & 3, byte & 1))
            self.assertEqual(0, full["combo_bitfield"])
        base = deck.dtnr_data + 0x38
        self.assertEqual(bytes(12), deck.data[base + 0x2C:base + 0x38])
        self.assertEqual(bytes.fromhex(entry["ai_row"]), deck.data[deck.dtai_data + 0x20:][:0x20])

    def test_refusals(self) -> None:
        story, source = _fixture()
        wrong = {1: {"deck": "Src", "trainer": 1, "species": [1, 2, 3, 4, 5, 6]}}
        with self.assertRaisesRegex(ValueError, "not\nthe seed's|not the seed's"):
            iso_patcher.apply_nightmare_citadark_edit(story, {"Src": source}, wrong)
        with self.assertRaisesRegex(ValueError, "no team"):
            iso_patcher.apply_nightmare_citadark_edit(
                story, {"Src": source}, {9: {"deck": "Src", "trainer": 1, "species": [100] * 6}})
        shared = _deck({1: {"ai": 1, "slots": [1]}, 2: {"ai": 1, "slots": [2]}},
                       [bytes(0x20), _record(1, 5), _record(2, 5)], [bytes(0x20), bytes(0x20)])
        with self.assertRaisesRegex(ValueError, "shared"):
            iso_patcher.apply_nightmare_citadark_edit(
                shared, {"Src": source}, {1: {"deck": "Src", "trainer": 1, "species": [100, 101, 102, 103, 104, 105]}})


@unittest.skipUnless(os.path.exists(DECK_DUMP), "needs a real deck_archive.fsys dump")
class TestOnTheRealDeck(unittest.TestCase):
    def test_all_thirty_four(self) -> None:
        data = Path(DECK_DUMP).read_bytes()
        entries = iso_patcher.parse_fsys(data)

        def dec(name):
            e = entries[name]
            return deck_format.lzss_decode(data[e["data_off"]:e["data_off"] + 0x10 + e["comp_size"]])

        story, colo = dec("DeckData_Story.bin"), dec("DeckData_Colosseum.bin")
        keys = nc.assign_teams(random.Random(423))
        out, result = iso_patcher.apply_nightmare_citadark_edit(
            story, {"DeckData_Colosseum.bin": colo}, {t: nc.seed_entry(k) for t, k in keys.items()})
        self.assertEqual(33, result["trainers_replaced"])
        before, after = deck_format.DeckFile(story), deck_format.DeckFile(out)
        for index in range(before.dtnr_entries):
            if index in keys:
                trainer = after.trainer(index)
                self.assertEqual(list(nc.team_species(keys[index])),
                                 [m["species"] for m in sorted(trainer["team"], key=lambda m: m["slot"])])
                self.assertEqual({100}, {m["level"] for m in trainer["team"]})
                self.assertEqual(0, after.data[after.dtnr_data + index * 0x38 + 4])
            else:
                self.assertEqual(before.data[before.dtnr_data + index * 0x38:][:0x38],
                                 after.data[after.dtnr_data + index * 0x38:][:0x38], index)
        self.assertEqual(before.data[before.dstr_hdr:], after.data[after.dstr_hdr:])


def _fsys(entries: "list[tuple[bytes, bytes]]") -> bytes:
    """A real-format FSYS holding each (name, decompressed) as an LZSS entry with headroom."""
    count = len(entries)
    records_at, names_at = 0x60 + 4 * count + 0x10, 0x400
    blobs, data_at = [], 0x800
    fsys = bytearray(data_at)
    fsys[0:4] = b"FSYS"
    struct.pack_into(">I", fsys, 0x0C, count)
    name_cursor = names_at
    for i, (name, payload) in enumerate(entries):
        stream = deck_format.lzss_encode(payload)
        comp = len(stream) + 256
        blob = b"LZSS" + struct.pack(">II", len(payload), comp) + bytes(4) + stream + bytes(comp - len(stream))
        record = records_at + i * 0x70
        struct.pack_into(">I", fsys, 0x60 + 4 * i, record)
        struct.pack_into(">I", fsys, record + 0x04, data_at + sum(len(b) for b in blobs))
        struct.pack_into(">I", fsys, record + 0x08, len(payload))
        struct.pack_into(">I", fsys, record + 0x14, comp)
        struct.pack_into(">I", fsys, record + 0x24, name_cursor)
        fsys[name_cursor:name_cursor + len(name) + 1] = name + b"\x00"
        name_cursor += len(name) + 1
        blobs.append(blob)
    return bytes(fsys) + b"".join(blobs)


class TestTheWrite(unittest.TestCase):
    """Through `write_nightmare_citadark_patch` on a synthetic ISO, the path `apply_patch` takes."""

    def test_writes_and_reads_back(self) -> None:
        from .test_write_enhanced_difficulty_patch_iso import _build_synthetic_iso
        story, source = _fixture()
        iso = _build_synthetic_iso(_fsys([(b"DeckData_Story.bin", story), (b"DeckData_Colosseum.bin", source)]))
        entry = nc.seed_entry("colo:567")
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "copy.iso"
            path.write_bytes(iso)
            result = iso_patcher.write_nightmare_citadark_patch(path, {1: entry})
            self.assertEqual(1, result["trainers_replaced"])
            reader = iso_patcher.open_reader(path)
            try:
                fst = iso_patcher.parse_fst(reader)
                off, length, _ = iso_patcher.find_by_basename(fst, "deck_archive.fsys")
                container = reader.read(off, length)
            finally:
                reader.close()
        entries = iso_patcher.parse_fsys(container)
        e = entries["DeckData_Story.bin"]
        deck = deck_format.DeckFile(deck_format.lzss_decode(container[e["data_off"]:e["data_off"] + 0x10 + e["comp_size"]]))
        self.assertEqual([m.species for m in nc.COLOSSEUM_ORRE_LV100_TEAMS[567]],
                         [m["species"] for m in sorted(deck.trainer(1)["team"], key=lambda m: m["slot"])])
        c = entries["DeckData_Colosseum.bin"]
        self.assertEqual(source, deck_format.lzss_decode(container[c["data_off"]:c["data_off"] + 0x10 + c["comp_size"]]))


class TestWiring(unittest.TestCase):
    def test_last_story_deck_pass(self) -> None:
        source = Path(iso_patcher.__file__).read_text(encoding="utf-8")
        body = source[source.index("def apply_patch("):]
        mt = body.index("write_enhanced_difficulty_mt_battle_patch(output_path")
        nightmare = body.index("write_nightmare_citadark_patch(")
        rel = body.index("Chest randomization, Poke Spot species and the AP Item rename")
        self.assertLess(mt, nightmare)
        self.assertLess(nightmare, rel)


if __name__ == "__main__":
    unittest.main()
