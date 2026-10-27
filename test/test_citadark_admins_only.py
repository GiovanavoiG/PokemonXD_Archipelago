"""Citadark Admins Only: only Lovrina, Snattle, Ardos, Gorigan, Eldes and Greevil fight on Citadark Isle."""
from __future__ import annotations

import pathlib
import struct
import unittest

from . import PokemonXDTestBase
from .. import locations, options, rules
from ..game_data import citadark_admins as CA
from ..game_data import nightmare_citadark as NC
from ..game_data import trainer_roster
from ..game_data.catch_rate_exclusions import citadark_trainer_indices
from ..game_data.trainer_beaten_flags import TRAINER_BEATEN_FLAGS
from ..trainer_defeat import TRAINER_DEFEAT_ROSTER

MAPS = pathlib.Path("/mnt/user-data/uploads/PokemonXD-working/bridge/dumps/maps")
ADMIN_SURNAMES = {"LOVRINA", "SNATTLE", "ARDOS", "GORIGAN", "ELDES", "GREEVIL"}


class TestTheSets(unittest.TestCase):
    def test_option_exists(self):
        self.assertIn("citadark_admins_only", options.PokemonXDOptions.__dataclass_fields__)

    def test_admins_and_the_rest_are_the_whole_island(self):
        self.assertEqual(citadark_trainer_indices(), CA.ADMIN_TRAINER_INDICES | CA.REMOVED_TRAINER_INDICES)
        names = {trainer_roster.TRAINERS_BY_INDEX[i]["name"].upper() for i in CA.ADMIN_TRAINER_INDICES}
        self.assertEqual(ADMIN_SURNAMES, names)
        for index in CA.REMOVED_TRAINER_INDICES:
            self.assertNotIn(trainer_roster.TRAINERS_BY_INDEX[index]["name"].upper(), ADMIN_SURNAMES)

    def test_beaten_variables_agree_with_the_beaten_flag_table(self):
        for index, variables in CA.BEATEN_VARIABLES.items():
            if index in TRAINER_BEATEN_FLAGS:
                self.assertIn(TRAINER_BEATEN_FLAGS[index], variables, index)
        self.assertNotIn(1358, CA.beaten_variables(), "Lovrina's own marker is never touched")

    def test_shadow_removal_takes_the_rest(self):
        self.assertEqual(CA.REMOVED_TRAINER_INDICES, NC.shadow_removal_trainers(False, False, False, admins_only=True))
        self.assertEqual(16, len(NC.removed_shadow_ddpks(CA.REMOVED_TRAINER_INDICES)))
        # Nightmare Citadark already moves every island Shadow but Lugia's; the two together move the same set.
        self.assertEqual(NC.nightmare_trainer_indices(),
                         NC.shadow_removal_trainers(True, False, False, admins_only=True))

    def test_removed_named_checks_are_island_surnames(self):
        roster = {surname for region, _loc, surname in TRAINER_DEFEAT_ROSTER if region == "Citadark Isle"}
        self.assertLessEqual(CA.REMOVED_NAMED_SURNAMES, roster)
        self.assertFalse({s.upper() for s in CA.REMOVED_NAMED_SURNAMES} & ADMIN_SURNAMES)


def _rel(room: str) -> bytes:
    from ..tools import iso_patcher as ip
    return ip._room_entry((MAPS / f"{room}.fsys").read_bytes(), 28)[1]


@unittest.skipUnless((MAPS / "D6_fort_1F.fsys").is_file(), "needs the Citadark room archives")
class TestTheFloorEdit(unittest.TestCase):
    def test_the_six_are_hidden_and_moved(self):
        for room, characters in CA.HIDDEN_CHARACTERS.items():
            rel = _rel(room)
            self.assertFalse(CA.is_hidden(rel, room))
            out = CA.hide_characters(rel, room)
            self.assertEqual(len(rel), len(out))
            self.assertTrue(CA.is_hidden(out, room))
            base = CA.character_table_offset(rel)
            changed = {i for i in range(len(rel)) if rel[i] != out[i]}
            allowed = set()
            for index, _name, _talk, _trainer in characters:
                at = base + index * CA.CHARACTER_RECORD_SIZE
                self.assertEqual(rel[at] & 0x7F, out[at])
                self.assertEqual(CA.HIDDEN_Y, struct.unpack_from(">f", out, at + 0x1C)[0])
                allowed |= {at, *range(at + 0x1C, at + 0x20)}
            self.assertLessEqual(changed, allowed, f"{room}: only those records' flags and height change")

    def test_a_different_record_is_refused(self):
        rel = bytearray(_rel("D6_fort_1F"))
        base = CA.character_table_offset(bytes(rel))
        struct.pack_into(">H", rel, base + CA.CHARACTER_RECORD_SIZE + 8, 999)
        with self.assertRaises(ValueError):
            CA.hide_characters(bytes(rel), "D6_fort_1F")

    def test_end_to_end_on_an_iso(self):
        import tempfile
        from ..tools import iso_patcher as ip
        from .test_addendum_456_candy_box_to_citadark_entry import _iso
        rooms = sorted(CA.HIDDEN_CHARACTERS)
        iso = _iso([(f"{room}.fsys".encode(), (MAPS / f"{room}.fsys").read_bytes()) for room in rooms])
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "copy.iso"
            path.write_bytes(iso)
            result = ip.write_citadark_admins_only_patch(path)
            self.assertTrue(result["applied"], result["reason"])
            self.assertEqual(rooms, result["rooms"])
            reader = ip.open_reader(path)
            try:
                fst = ip.parse_fst(reader)
                for room in rooms:
                    off, length, _rec = ip.find_by_basename(fst, room + ".fsys")
                    container = reader.read(off, length)
                    rel = ip._room_entry(container, 28)[1]
                    self.assertTrue(CA.is_hidden(rel, room))
                    self.assertEqual(ip._room_entry(container, 14)[1],
                                     ip._room_entry((MAPS / f"{room}.fsys").read_bytes(), 14)[1], "script untouched")
            finally:
                reader.close()
            again = ip.write_citadark_admins_only_patch(path)
            self.assertEqual((True, "already patched"), (again["applied"], again["reason"]))

    def test_the_patcher_runs_it(self):
        from ..tools import iso_patcher as ip
        src = pathlib.Path(ip.__file__).read_text(encoding="utf-8")
        self.assertIn("write_citadark_admins_only_patch(output_path)", src)


def _labels(indices) -> "set[str]":
    return {trainer_roster.trainer_label(trainer_roster.TRAINERS_BY_INDEX[i]) for i in indices}


class TestUniqueMode(PokemonXDTestBase):
    options = {"citadark_admins_only": True, "shuffle_trainer_defeats": True, "trainer_defeat_mode": 1}

    def test_no_checks_for_the_rest(self):
        names = {loc.name for loc in self.multiworld.get_locations(self.player)}
        self.assertFalse(names & _labels(CA.REMOVED_TRAINER_INDICES))
        admins = _labels(CA.ADMIN_TRAINER_INDICES) & set(locations.LOCATION_NAME_TO_ID if hasattr(
            locations, "LOCATION_NAME_TO_ID") else self.multiworld.worlds[self.player].location_name_to_id)
        self.assertTrue(admins & names, "the admins keep theirs")

    def test_the_tally_skips_them(self):
        world = self.multiworld.worlds[self.player]
        on = sum(n for _ways, n in rules._trainer_count_groups(world))
        world.options.citadark_admins_only = options.CitadarkAdminsOnly(0)
        try:
            off = sum(n for _ways, n in rules._trainer_count_groups(world))
        finally:
            world.options.citadark_admins_only = options.CitadarkAdminsOnly(1)
        self.assertEqual(len(CA.REMOVED_TRAINER_INDICES), off - on)

    def test_their_shadows_moved_elsewhere(self):
        world = self.multiworld.worlds[self.player]
        self.assertLessEqual(CA.REMOVED_TRAINER_INDICES, world._shadow_removal_trainers)
        moved = [s for plan in world._nightmare_relocations for s in plan["shadows"]]
        self.assertEqual(16, len(moved))
        hosts = {int(plan["trainer_index"]) for plan in world._nightmare_relocations}
        self.assertFalse(hosts & citadark_trainer_indices())

    def test_slot_data_carries_it(self):
        self.assertTrue(self.multiworld.worlds[self.player].fill_slot_data()["citadark_admins_only"])


class TestCumulativeMode(PokemonXDTestBase):
    options = {"citadark_admins_only": True, "shuffle_trainer_defeats": True, "trainer_defeat_mode": 0}

    def test_no_named_checks_for_the_rest(self):
        names = {loc.name for loc in self.multiworld.get_locations(self.player)}
        removed = {loc for region, loc, surname in TRAINER_DEFEAT_ROSTER
                   if region == "Citadark Isle" and surname in CA.REMOVED_NAMED_SURNAMES}
        self.assertFalse(names & removed)


class TestWithNightmare(PokemonXDTestBase):
    options = {"citadark_admins_only": True, "nightmare_citadark": True, "shuffle_trainer_defeats": True,
               "trainer_defeat_mode": 1}

    def test_together(self):
        world = self.multiworld.worlds[self.player]
        self.assertEqual(NC.nightmare_trainer_indices(), world._shadow_removal_trainers)
        names = {loc.name for loc in self.multiworld.get_locations(self.player)}
        self.assertFalse(names & _labels(CA.REMOVED_TRAINER_INDICES))


class TestTheClient(unittest.TestCase):
    def setUp(self):
        self.src = (pathlib.Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")

    def test_reads_the_option_and_marks_them(self):
        self.assertIn('slot_data.get("citadark_admins_only", False)', self.src)
        body = self.src.split("def check_citadark_admins_only", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("beaten_variables()", body)
        self.assertIn("gs_flag_get(variable) == 0", body, "only writes what is not set")
        self.assertIn("gs_flag_set(variable, 1)", body)

    def test_runs_in_the_save_block_gate_before_the_beaten_flag_witness(self):
        at = self.src.index("check_citadark_admins_only(ctx)\n")
        self.assertLess(at, self.src.index("await check_trainer_beaten_flags(ctx)"))
        gate = self.src.rfind("if block_is_stable:", 0, at)
        self.assertGreater(gate, self.src.rfind("await check_shop_prices(ctx)", 0, at))

    def test_the_witness_ignores_them(self):
        body = self.src.split("async def check_trainer_beaten_flags", 1)[1].split("\nasync def ", 1)[0]
        self.assertIn("REMOVED_TRAINER_INDICES", body)


if __name__ == "__main__":
    unittest.main()
