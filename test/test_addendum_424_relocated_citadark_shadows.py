"""ADDENDUM 424 (2026-10-06) -- Greevil keeps Lugia; the other Citadark Shadows move instead of vanishing; and the
Colosseum teams' own trainer AI, decoded and translated exactly.

Player: "Greevil's first team is just shadow lugia - don't replace that one. Also, now that those 36 shadow pokemon
aren't in those spots, can they be shuffled/added into the rest of the trainers?" ... "Obviously still only give
the shadow pokemon to non-missable trainers." ... "Also, can you please try to decipher the colosseum trainer AI?
Work hard at it. It'd be nice to have it be exact."
"""
from __future__ import annotations

import os
import random
import struct
import tempfile
import unittest
from pathlib import Path

from . import PokemonXDTestBase
from ..game_data import missable_trainers, nightmare_citadark as nc
from ..game_data.catch_rate_exclusions import citadark_trainer_indices
from ..game_data.real_trainer_data import PERMANENTLY_EXCLUDED_TRAINER_INDICES, real_trainer_free_slot_census
from ..tools import iso_patcher
from ..tools import xd_deck_format as deck_format

DECK_DUMP = "/mnt/user-data/uploads/PokemonXD-working/bridge/dumps/deck_archive_full1.bin"
COLO_COMMON = "/mnt/user-data/uploads/PokemonXD-working/colo_fs/files/common.fsys"
COLO_DOL = "/mnt/user-data/uploads/PokemonXD-working/colo_fs/sys/main.dol"
FENCE = missable_trainers.shadow_expansion_excluded_trainer_indices() | citadark_trainer_indices()


class TestThePlan(unittest.TestCase):
    def _plan(self, seed: int, multiplier: float = 1.0):
        return nc.plan_relocations(random.Random(seed), real_trainer_free_slot_census(), FENCE, multiplier)

    def test_every_displaced_shadow_lands_once(self) -> None:
        for seed in range(25):
            plan = self._plan(seed)
            ddpks = [s["ddpk_index"] for p in plan for s in p["shadows"]]
            self.assertEqual(sorted(nc.removed_shadow_ddpks()), sorted(ddpks), seed)

    def test_only_on_non_missable_trainers_off_citadark(self) -> None:
        for seed in range(25):
            hosts = {p["trainer_index"] for p in self._plan(seed)}
            self.assertFalse(hosts & missable_trainers.shadow_expansion_excluded_trainer_indices(), seed)
            self.assertFalse(hosts & citadark_trainer_indices(), seed)
            self.assertFalse(hosts & PERMANENTLY_EXCLUDED_TRAINER_INDICES, seed)

    def test_spread_and_within_free_slots(self) -> None:
        free = {row["trainer_index"]: row["free_slots"] for row in real_trainer_free_slot_census()}
        eligible = [t for t, n in free.items() if t not in FENCE and t not in PERMANENTLY_EXCLUDED_TRAINER_INDICES and n]
        for seed in range(25):
            plan = self._plan(seed)
            for p in plan:
                self.assertLessEqual(len(p["shadows"]), free[p["trainer_index"]])
            if len(eligible) >= 35:
                self.assertEqual(35, len(plan), seed)          # round-robin: one each before any gets two

    def test_host_level_and_the_multiplier(self) -> None:
        average = {row["trainer_index"]: row["avg_level"] for row in real_trainer_free_slot_census()}
        for p in self._plan(3, 1.33):
            for s in p["shadows"]:
                self.assertEqual(max(1, min(100, round(average[p["trainer_index"]] * 1.33))), s["level"])

    def test_refuses_rather_than_drops(self) -> None:
        with self.assertRaises(ValueError):
            nc.plan_relocations(random.Random(0), [{"trainer_index": 2, "free_slots": 3, "avg_level": 10.0}],
                                frozenset())


class TestGeneration(PokemonXDTestBase):
    options = {"nightmare_citadark": True, "shadow_pokemon_expansion": 44, "enhanced_difficulty": 3,
               "randomize_shadow_species": True}

    def test_relocations_and_the_expansion_share_slots_honestly(self) -> None:
        world = self.multiworld.worlds[self.player]
        free = {row["trainer_index"]: row["free_slots"] for row in real_trainer_free_slot_census()}
        used: "dict[int, int]" = {}
        for p in world._nightmare_relocations:
            used[p["trainer_index"]] = used.get(p["trainer_index"], 0) + len(p["shadows"])
        for p in world._shadow_expansion_plans or ():
            used[p["trainer_index"]] = used.get(p["trainer_index"], 0) + len(p["new_pokemon"])
        for trainer, count in used.items():
            self.assertLessEqual(count, free[trainer], trainer)
        self.assertEqual(35, sum(len(p["shadows"]) for p in world._nightmare_relocations))

    def test_catch_gates_follow_the_host(self) -> None:
        world = self.multiworld.worlds[self.player]
        hosts = {p["trainer_index"] for p in world._nightmare_relocations}
        seen = {h for hs in world._shadow_catch_expansion_hosts.values() for h in hs}
        self.assertTrue(hosts <= seen)
        from ..game_data import shadow_regions
        for labels in world._shadow_catch_labels.values():
            for label in labels:
                gate = shadow_regions.gate_for_label(shadow_regions.trainer_label_from_location(label))
                if gate is not None and gate.region == "Citadark Isle":
                    self.assertIn("GREEVIL", label.upper())          # Lugia, and only Lugia

    def test_seed_data_and_ed_leaves_them_room(self) -> None:
        from .test_addendum_423_nightmare_citadark import _seed_data
        world = self.multiworld.worlds[self.player]
        seed = _seed_data(world)
        self.assertEqual(world._nightmare_relocations, seed["nightmare_shadow_relocations"])
        free = {row["trainer_index"]: row["free_slots"] for row in real_trainer_free_slot_census()}
        padded: "dict[int, int]" = {}
        for step in seed["enhanced_difficulty_plan"]["team_slot_plan"]:
            padded[int(step["trainer_index"])] = padded.get(int(step["trainer_index"]), 0) + 1
        for p in world._nightmare_relocations:
            host = p["trainer_index"]
            expansion = sum(len(e["new_pokemon"]) for e in world._shadow_expansion_plans or ()
                            if e["trainer_index"] == host)
            self.assertLessEqual(len(p["shadows"]) + expansion + padded.get(host, 0), free[host], host)


class TestPathScaling(PokemonXDTestBase):
    options = {"nightmare_citadark": True, "path_level_scaling": True}

    def test_relocated_levels_follow_the_ramp(self) -> None:
        from ..randomizer.path_level_scaling import level_by_trainer_index
        world = self.multiworld.worlds[self.player]
        world.pre_output()
        ramp = level_by_trainer_index(tier_by_region=world._path_tier_by_region)
        for p in world._nightmare_relocations:
            if p["trainer_index"] in ramp:
                for s in p["shadows"]:
                    self.assertEqual(ramp[p["trainer_index"]], s["level"])


# --- the patch --------------------------------------------------------------------------------------------------

def _dark(entries: "dict[int, int]", count: int = 8) -> bytes:
    """A DeckData_DarkPokemon.bin: {ddpk_index: story_deck_index} in use, level 40."""
    data = bytearray(0x20 + count * 0x18)
    data[0:4] = b"DECK"
    data[0x10:0x14] = b"DDPK"
    struct.pack_into(">II", data, 0x14, 0x10 + count * 0x18, count)
    for index, dpkm in entries.items():
        off = 0x20 + index * 0x18
        data[off + 2] = 40
        data[off + 3] = 0x80
        struct.pack_into(">I", data, off + 4, dpkm)
    return bytes(data)


def _story():
    from .test_addendum_423_nightmare_citadark import _deck, _record
    records = [bytes(0x20)] + [_record(10 + i, 60) for i in range(1, 6)]
    # trainer 1: the old holder, now holding nothing of DDPK 2; trainer 2: a host with two members.
    return _deck({1: {"ai": 1, "slots": [1]}, 2: {"ai": 2, "slots": [3, 4]}}, records,
                 [bytes(0x20), bytes(0x20), bytes(0x20)])


class TestTheEdit(unittest.TestCase):
    def test_hangs_the_shadow_on_the_host(self) -> None:
        story, dark = _story(), _dark({2: 5})
        out, levels = iso_patcher.apply_nightmare_relocation_edit(
            story, dark, [{"trainer_index": 2, "shadows": [{"ddpk_index": 2, "dpkm_index": 5, "level": 17}]}])
        deck = deck_format.DeckFile(out)
        team = deck.trainer(2)["team"]
        self.assertEqual(3, len(team))
        shadow = [m for m in team if m["kind"] == "DDPK"]
        self.assertEqual([2], [m["ddpk_index"] for m in shadow])
        self.assertEqual(17, deck.dpkm_species_level(5)[1])
        self.assertEqual({2: 17}, levels)

    def test_refusals(self) -> None:
        story = _story()
        with self.assertRaisesRegex(ValueError, "not the in-use Shadow"):
            iso_patcher.apply_nightmare_relocation_edit(
                story, _dark({2: 4}), [{"trainer_index": 2, "shadows": [{"ddpk_index": 2, "dpkm_index": 5, "level": 9}]}])
        with self.assertRaisesRegex(ValueError, "free slot"):
            iso_patcher.apply_nightmare_relocation_edit(
                story, _dark({i: 5 for i in range(1, 8)}),
                [{"trainer_index": 2, "shadows": [{"ddpk_index": i, "dpkm_index": 5, "level": 9} for i in range(1, 6)]}])
        from .test_addendum_423_nightmare_citadark import _deck, _record
        held = _deck({1: {"ai": 1, "slots": [2], "mask": 1}, 2: {"ai": 2, "slots": [3]}},
                     [bytes(0x20)] + [_record(10 + i, 60) for i in range(1, 6)], [bytes(0x20)] * 3)
        with self.assertRaisesRegex(ValueError, "still on"):
            iso_patcher.apply_nightmare_relocation_edit(
                held, _dark({2: 5}), [{"trainer_index": 2, "shadows": [{"ddpk_index": 2, "dpkm_index": 5, "level": 9}]}])


def _two_file_iso(files: "list[tuple[bytes, bytes]]") -> bytes:
    """A GameCube image with an FST of root + the given files, laid out back to back."""
    count = len(files) + 1
    names = b"".join(name + b"\x00" for name, _ in files)
    fst = bytearray(count * 12) + names
    fst[0] = 1
    struct.pack_into(">I", fst, 8, count)
    cursor, name_off, blobs = 0x8000, 0, []
    for i, (name, blob) in enumerate(files, start=1):
        base = i * 12
        struct.pack_into(">I", fst, base, name_off)            # flag 0 in the top byte, name offset below
        struct.pack_into(">II", fst, base + 4, cursor, len(blob))
        blobs.append((cursor, blob))
        cursor += (len(blob) + 0x7FFF) & ~0x7FFF
        name_off += len(name) + 1
    iso = bytearray(cursor)
    struct.pack_into(">II", iso, 0x424, 0x440, len(fst))
    iso[0x440:0x440 + len(fst)] = fst
    for at, blob in blobs:
        iso[at:at + len(blob)] = blob
    return bytes(iso)


class TestTheWrite(unittest.TestCase):
    """Teams, relocation and all three DDPK copies through `write_nightmare_citadark_patch`."""

    def test_end_to_end(self) -> None:
        from .test_addendum_423_nightmare_citadark import _fixture, _fsys
        story, source = _fixture()               # trainer 1 holds DDPK 7 in slot 2 (mask 0b100); trainer 2 hosts
        dark = _dark({7: 5})
        deck_archive = _fsys([(b"DeckData_Story.bin", story), (b"DeckData_Colosseum.bin", source),
                              (b"DeckData_DarkPokemon.bin", dark)])
        common = _fsys([(b"DeckData_DarkPokemon.bin", dark), (b"DeckData_DarkPokemon_EU.bin", dark)])
        iso = _two_file_iso([(b"deck_archive.fsys", deck_archive), (b"common.fsys", common)])
        teams = {1: {"deck": "DeckData_Colosseum.bin", "trainer": 1, "species": [100, 101, 102, 103, 104, 105]}}
        relocations = [{"trainer_index": 2, "shadows": [{"ddpk_index": 7, "dpkm_index": 5, "level": 23}]}]
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "copy.iso"
            path.write_bytes(iso)
            result = iso_patcher.write_nightmare_citadark_patch(path, teams, relocations)
            self.assertEqual((1, 1), (result["trainers_replaced"], result["shadows_relocated"]))
            reader = iso_patcher.open_reader(path)
            try:
                fst = iso_patcher.parse_fst(reader)
                containers = {}
                for name in ("deck_archive.fsys", "common.fsys"):
                    off, length, _ = iso_patcher.find_by_basename(fst, name)
                    containers[name] = reader.read(off, length)
            finally:
                reader.close()

        def entry(container: bytes, name: str) -> bytes:
            e = iso_patcher.parse_fsys(container)[name]
            return deck_format.lzss_decode(container[e["data_off"]:e["data_off"] + 0x10 + e["comp_size"]])

        deck = deck_format.DeckFile(entry(containers["deck_archive.fsys"], "DeckData_Story.bin"))
        self.assertEqual([7], [m["ddpk_index"] for m in deck.trainer(2)["team"] if m["kind"] == "DDPK"])
        self.assertFalse([m for m in deck.trainer(1)["team"] if m["kind"] == "DDPK"])
        self.assertEqual(23, deck.dpkm_species_level(5)[1])
        for container, name in (("deck_archive.fsys", "DeckData_DarkPokemon.bin"),
                                ("common.fsys", "DeckData_DarkPokemon.bin"),
                                ("common.fsys", "DeckData_DarkPokemon_EU.bin")):
            self.assertEqual(23, deck_format.DarkPokemonFile(entry(containers[container], name)).ddpk_full(7)["shadow_level"])


@unittest.skipUnless(os.path.exists(DECK_DUMP), "needs a real deck_archive.fsys dump")
class TestOnTheRealDeck(unittest.TestCase):
    def test_teams_then_relocations(self) -> None:
        data = Path(DECK_DUMP).read_bytes()
        entries = iso_patcher.parse_fsys(data)

        def dec(name):
            e = entries[name]
            return deck_format.lzss_decode(data[e["data_off"]:e["data_off"] + 0x10 + e["comp_size"]])

        story, colo, dark = dec("DeckData_Story.bin"), dec("DeckData_Colosseum.bin"), dec("DeckData_DarkPokemon.bin")
        keys = nc.assign_teams(random.Random(424))
        out, _ = iso_patcher.apply_nightmare_citadark_edit(
            story, {"DeckData_Colosseum.bin": colo}, {t: nc.seed_entry(k) for t, k in keys.items()})
        plan = nc.plan_relocations(random.Random(424), real_trainer_free_slot_census(), FENCE)
        out, levels = iso_patcher.apply_nightmare_relocation_edit(out, dark, plan)
        self.assertEqual(35, len(levels))
        deck = deck_format.DeckFile(out)
        refs: "dict[int, list[int]]" = {}
        for trainer in deck.all_trainers():
            for m in trainer["team"]:
                if m["kind"] == "DDPK":
                    refs.setdefault(m["ddpk_index"], []).append(trainer["index"])
        hosts = {s["ddpk_index"]: p["trainer_index"] for p in plan for s in p["shadows"]}
        for ddpk, host in hosts.items():
            self.assertEqual([host], refs.get(ddpk), ddpk)
        self.assertEqual([nc.GREEVIL_LUGIA_TRAINER], refs.get(73))          # Lugia never moved
        self.assertEqual(83, len(refs))                                    # every vanilla Shadow on exactly a trainer
        greevil = deck.trainer(nc.GREEVIL_LUGIA_TRAINER)
        self.assertEqual(1, greevil["party_size"])


# --- the Colosseum AI ----------------------------------------------------------------------------------------------

def _xd_fields(row: bytes) -> dict:
    """Read an XD DTAI row back through `DeckTrainerAI`'s accessors (bit and byte positions from XD's code)."""
    bit = lambda b, n: (row[b] >> n) & 1
    return {
        "SelRandom": bit(0, 7), "WeakPoint": bit(0, 6), "OrderOut": bit(0, 5), "AceBoss": bit(0, 4),
        "KeyPlayer": bit(0, 3), "Zokusei": bit(0, 2), "Tokusei": bit(0, 1), "WazaDamage": bit(0, 0),
        "Joutai": bit(1, 1), "WazaRisk": bit(1, 2), "WazaHit": bit(1, 3), "Part": bit(1, 4), "WazaInit": bit(1, 5),
        "WazaRnd": bit(1, 6), "DefRnd": bit(1, 7), "AbiMax": row[0x0C], "AbiMin": row[0x0D], "Irekae": row[0x0E],
        "Item": row[0x0F], "WazaAvg": row[0x10], "Stroke": row[0x11], "NokoriHp": row[0x12], "WazaPP": row[0x13],
        "ZokuseiId": (row[0x14], row[0x15]), "ZokuseiVal": (row[0x16], row[0x17]),
        "WazaTypeId": (struct.unpack_from(">H", row, 0x18)[0], struct.unpack_from(">H", row, 0x1A)[0]),
        "WazaTypeVal": (row[0x1C], row[0x1D]), "LastRevise": row[0x1E],
    }


_COLOSSEUM_NAMES = ["SelRandom", "WeakPoint", "OrderOut", "AceBoss", "KeyPlayer", "Joutai", "Combo", "Irekae", "Item",
                    "ParamExpect", "ParamStore", "Zokusei", "Tokusei", "NokoriHp", "WazaDamage", "AbiMax", "AbiMin",
                    "DefRnd", "WazaRnd", "WazaInit", "Part", "WazaHit", "WazaAvg", "WazaRisk", "WazaPP", "LastRevise"]
_FLAGS = ("SelRandom", "WeakPoint", "OrderOut", "AceBoss", "KeyPlayer", "Zokusei", "Tokusei", "WazaDamage", "Joutai",
          "WazaRisk", "WazaHit", "Part", "WazaInit", "WazaRnd", "DefRnd")


def _colosseum_fields(row: bytes) -> dict:
    """A Colosseum TrainerAIData row (0x28 bytes) through its accessors: byte (id - 31), then the pairs at 0x20."""
    out = dict(zip(_COLOSSEUM_NAMES, row[:26]))
    pairs = row[0x20:0x28]
    out.update({"ZokuseiId": (pairs[0], pairs[2]), "ZokuseiVal": (pairs[1], pairs[3]),
                "WazaTypeId": (pairs[4], pairs[6]), "WazaTypeVal": (pairs[5], pairs[7])})
    return out


class TestTheStyles(unittest.TestCase):
    def test_every_style_reads_back(self) -> None:
        for team, style in nc.COLOSSEUM_ORRE_LV100_AI_STYLES.items():
            xd = _xd_fields(nc.dtai_row(style))
            names = {"random_lead": "SelRandom", "lead_into_weakness": "WeakPoint", "send_in_listed_order": "OrderOut",
                     "ace_last": "AceBoss", "key_member": "KeyPlayer", "type_matchups": "Zokusei",
                     "abilities": "Tokusei", "damage_estimates": "WazaDamage", "random_target": "DefRnd",
                     "random_move": "WazaRnd", "opening_move_bias": "WazaInit", "follow_roles": "Part",
                     "check_accuracy": "WazaHit", "weigh_risk": "WazaRisk", "status_aware": "Joutai"}
            self.assertEqual({names[t] for t in style.traits}, {f for f in _FLAGS if xd[f]}, team)
            self.assertEqual((style.stage_max, style.stage_min, style.switch_pct, style.item_pct, style.accuracy_pct,
                              style.low_hp_pct, style.last_pp_pct, style.spread),
                             (xd["AbiMax"], xd["AbiMin"], xd["Irekae"], xd["Item"], xd["WazaAvg"], xd["NokoriHp"],
                              xd["WazaPP"], xd["LastRevise"]), team)
            self.assertEqual(0, xd["Stroke"])

    def test_round_one_single(self) -> None:
        xd = _xd_fields(nc.dtai_row(nc.COLOSSEUM_ORRE_LV100_AI_STYLES[559]))
        self.assertEqual((100, 0, 80, 50, 10, 2), (xd["Irekae"], xd["Item"], xd["WazaAvg"], xd["NokoriHp"],
                                                   xd["WazaPP"], xd["LastRevise"]))
        self.assertEqual(((9, 9), (50, 50)), (xd["ZokuseiId"], xd["ZokuseiVal"]))

    def test_the_one_with_type_preferences(self) -> None:
        xd = _xd_fields(nc.dtai_row(nc.COLOSSEUM_ORRE_LV100_AI_STYLES[573]))
        self.assertEqual(((13, 13), (0, 0)), (xd["ZokuseiId"], xd["ZokuseiVal"]))      # shun Electric moves
        self.assertEqual(((6, 7), (100, 100)), (xd["WazaTypeId"], xd["WazaTypeVal"]))  # favour move kinds 6 and 7

    def test_every_colosseum_team_has_its_ai(self) -> None:
        self.assertEqual(set(nc.COLOSSEUM_ORRE_LV100_TEAMS), set(nc.COLOSSEUM_ORRE_LV100_AI_STYLES))
        for key in nc.TEAM_KEYS:
            entry = nc.seed_entry(key)
            if key.startswith("colo:"):
                self.assertEqual(64, len(entry["ai_row"]))


@unittest.skipUnless(os.path.exists(COLO_COMMON), "needs Pokemon Colosseum's common.fsys")
class TestTheStylesMatchTheDisc(unittest.TestCase):
    """Each style plays as the Colosseum disc's own AI row for that team does, field by field the XD engine reads."""

    def test_rows(self) -> None:
        data = Path(COLO_COMMON).read_bytes()
        entry = iso_patcher.parse_fsys(data)["common_rel"]
        rel = deck_format.lzss_decode(data[entry["data_off"]:entry["data_off"] + 0x10 + entry["comp_size"]])
        trainers, ai = 0x92ED0, 0x9D560
        for team, style in nc.COLOSSEUM_ORRE_LV100_AI_STYLES.items():
            index = struct.unpack_from(">H", rel, trainers + team * 0x34 + 6)[0]
            colo = _colosseum_fields(rel[ai + index * 0x28:ai + index * 0x28 + 0x28])
            xd = _xd_fields(nc.dtai_row(style))
            for name in _FLAGS:
                self.assertEqual(bool(colo[name]), bool(xd[name]), (team, name))
            for name in ("AbiMax", "AbiMin", "Irekae", "Item", "WazaAvg", "NokoriHp", "WazaPP", "LastRevise",
                         "ZokuseiId", "WazaTypeId"):
                self.assertEqual(colo[name], xd[name], (team, name))
            for name in ("ZokuseiVal", "WazaTypeVal"):
                # Colosseum turns a weight into a percentage as v*100/255, XD as v*100/100.
                self.assertEqual(tuple(v * 100 // 255 for v in colo[name]), xd[name], (team, name))



@unittest.skipUnless(os.path.exists(COLO_DOL), "needs Pokemon Colosseum's main.dol")
class TestTheColosseumAccessors(unittest.TestCase):
    """The decoding's footing: Colosseum's status getter sends AI field id N to an accessor reading byte N-31."""

    def _word(self, dol: bytes, address: int) -> int:
        for i in range(18):
            off, addr, size = (struct.unpack_from(">I", dol, base + i * 4)[0] for base in (0, 0x48, 0x90))
            if size and addr <= address < addr + size:
                return struct.unpack_from(">I", dol, off + address - addr)[0]
        raise KeyError(hex(address))

    def test_fields_31_to_56(self) -> None:
        dol = Path(COLO_DOL).read_bytes()
        table = 0x803757D8
        for field in range(31, 57):
            case = self._word(dol, table + field * 4)
            branch = self._word(dol, case)
            self.assertEqual(18, branch >> 26)
            offset = branch & 0x03FFFFFC
            if offset & 0x02000000:
                offset -= 0x04000000
            accessor = case + offset
            # cmplwi r3,0 ; bne +12 ; li r3,0 ; blr ; lbz r3,N(r3) ; blr
            self.assertEqual(0x88630000 | (field - 31), self._word(dol, accessor + 0x10), field)


if __name__ == "__main__":
    unittest.main()
