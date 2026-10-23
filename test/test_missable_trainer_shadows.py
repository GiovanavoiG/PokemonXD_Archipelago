"""Missable Trainer Shadows: Shadows on auto-sent missable fights, handed to Miror B. once their area closes."""
from __future__ import annotations

import os
import random
import struct
import unittest
from pathlib import Path
from unittest import mock

from . import PokemonXDTestBase
from .. import ram_client
from ..game_data import missable_autosend, missable_trainers, shadow_engine, shadow_regions

CLIENT = (Path(__file__).resolve().parents[1] / "Client.py").read_text(encoding="utf-8")


class TestTheHostList(unittest.TestCase):
    def test_hosts_are_auto_sent_one_shots(self) -> None:
        hosts = missable_trainers.missable_shadow_host_indices()
        self.assertTrue(hosts)
        self.assertLessEqual(hosts, set(missable_autosend.AUTO_SEND_ONE_SHOT_INDICES))
        self.assertFalse(hosts & shadow_regions.NO_SNAG_TRAINER_INDICES)

    def test_every_one_shot_label_is_in_the_schedule(self) -> None:
        for index, label in missable_autosend.AUTO_SEND_ONE_SHOT_INDICES.items():
            self.assertIn(label, missable_autosend.AUTO_SEND_AT_STORY_BYTE, index)

    def test_the_fence_only_opens_with_the_option(self) -> None:
        hosts = missable_trainers.missable_shadow_host_indices()
        closed = missable_trainers.shadow_expansion_excluded_trainer_indices()
        opened = missable_trainers.shadow_expansion_excluded_trainer_indices(allow_missable_hosts=True)
        self.assertLessEqual(hosts, closed)
        self.assertFalse(hosts & opened)
        self.assertEqual(closed - hosts, opened)


SIZE = ram_client.SHADOW_MONITOR_RECORD_SIZE
BLOCK = 0x80800000
TABLE = (BLOCK - ram_client.SAVEDATA_HERO_OFFSET - ram_client.RECORD_TRAINER_NAME_OFFSET
         + ram_client.SHADOW_MONITOR_SAVEDATA_OFFSET)
TRAINER_ID = 0x1234ABCD


class _Memory:
    def __init__(self) -> None:
        self.cells: "dict[int, int]" = {}
        for k in range(ram_client.SHADOW_MONITOR_RECORDS):
            self.write(TABLE + k * SIZE + ram_client.SHADOW_RECORD_SELF_ID_OFFSET, struct.pack(">H", k))
            self.write(TABLE + k * SIZE + ram_client.SHADOW_RECORD_SPECIES_OFFSET, struct.pack(">H", 1000 + k))
            self.write(TABLE + k * SIZE + 0x24, struct.pack(">I", 2000))
        self.write(BLOCK + ram_client.HERO_TRAINER_ID_FROM_BLOCK_BASE, struct.pack(">I", TRAINER_ID))

    def read(self, address: int, length: int) -> bytes:
        return bytes(self.cells.get(address + i, 0) for i in range(length))

    def write(self, address: int, data: bytes) -> None:
        for i, b in enumerate(data):
            self.cells[address + i] = b

    def record(self, k: int) -> bytes:
        return self.read(TABLE + k * SIZE, SIZE)


class TestTheHandOff(unittest.TestCase):
    LABEL = next(iter(missable_autosend.AUTO_SEND_ONE_SHOT_INDICES.values()))

    def _run(self, memory: _Memory, shadows, progress: int):
        pusher = ram_client.MissableShadowPusher([{"label": self.LABEL, "shadows": shadows}], rng=random.Random(5))
        with mock.patch.object(ram_client, "read_bytes", memory.read), \
                mock.patch.object(ram_client, "write_bytes", memory.write):
            return pusher, pusher.poll(BLOCK, progress)

    def test_nothing_moves_before_the_cap(self) -> None:
        memory = _Memory()
        cap = missable_autosend.AUTO_SEND_AT_STORY_BYTE[self.LABEL]
        _, moved = self._run(memory, [{"species": 1010, "name": "Aipom", "ddpk": None}], cap - 1)
        self.assertEqual([], moved)
        self.assertEqual(0, memory.record(10)[0] >> 5)

    def test_an_unmet_shadow_goes_to_miror_b_with_a_pid_and_ivs(self) -> None:
        memory = _Memory()
        cap = missable_autosend.AUTO_SEND_AT_STORY_BYTE[self.LABEL]
        _, moved = self._run(memory, [{"species": 1010, "name": "Aipom", "ddpk": None}], cap)
        self.assertEqual(["Aipom sent to Miror B. from a missable trainer."], moved)
        record = memory.record(10)
        self.assertEqual(ram_client.SHADOW_MONITOR_FLED, record[0] >> 5)
        self.assertTrue(record[1] & ram_client.SHADOW_RECORD_UPDATE_BIT)
        pid = struct.unpack_from(">I", record, ram_client.SHADOW_RECORD_PID_OFFSET)[0]
        self.assertNotEqual(0, pid)
        tid, sid = TRAINER_ID >> 16, TRAINER_ID & 0xFFFF
        self.assertGreaterEqual(tid ^ sid ^ (pid >> 16) ^ (pid & 0xFFFF), 8)
        ivs = record[ram_client.SHADOW_RECORD_IVS_OFFSET:ram_client.SHADOW_RECORD_IVS_OFFSET + 6]
        self.assertTrue(all(iv < 32 for iv in ivs))
        self.assertNotEqual(0, struct.unpack_from(">I", record, ram_client.SHADOW_RECORD_ESCAPE_TIME_OFFSET)[0])
        self.assertEqual(2000, struct.unpack_from(">I", record, 0x24)[0])   # heart gauge untouched

    def test_a_met_shadow_keeps_its_pid(self) -> None:
        memory = _Memory()
        memory.write(TABLE + 12 * SIZE, bytes((0x20, 0x20)))
        memory.write(TABLE + 12 * SIZE + ram_client.SHADOW_RECORD_PID_OFFSET, struct.pack(">I", 0xDEADBEEF))
        cap = missable_autosend.AUTO_SEND_AT_STORY_BYTE[self.LABEL]
        _, moved = self._run(memory, [{"species": 1012, "name": "Sceptile", "ddpk": None}], cap)
        self.assertEqual(["Sceptile sent to Miror B. from a missable trainer."], moved)
        record = memory.record(12)
        self.assertEqual(2, record[0] >> 5)
        self.assertEqual(0xDEADBEEF, struct.unpack_from(">I", record, ram_client.SHADOW_RECORD_PID_OFFSET)[0])

    def test_snagged_purified_and_already_his_are_left_alone(self) -> None:
        for status in (2, 3, 4):
            memory = _Memory()
            memory.write(TABLE + 14 * SIZE, bytes((status << 5, 0x21)))
            before = memory.record(14)
            cap = missable_autosend.AUTO_SEND_AT_STORY_BYTE[self.LABEL]
            _, moved = self._run(memory, [{"species": 1014, "name": "X", "ddpk": None}], cap)
            self.assertEqual([], moved)
            self.assertEqual(before, memory.record(14))

    def test_a_ddpk_wins_over_the_species(self) -> None:
        memory = _Memory()
        cap = missable_autosend.AUTO_SEND_AT_STORY_BYTE[self.LABEL]
        self._run(memory, [{"species": 1020, "name": "X", "ddpk": 30}], cap)
        self.assertEqual(2, memory.record(30)[0] >> 5)
        self.assertEqual(0, memory.record(20)[0] >> 5)

    def test_an_ambiguous_species_is_not_guessed(self) -> None:
        memory = _Memory()
        memory.write(TABLE + 21 * SIZE + ram_client.SHADOW_RECORD_SPECIES_OFFSET, struct.pack(">H", 1020))
        cap = missable_autosend.AUTO_SEND_AT_STORY_BYTE[self.LABEL]
        pusher, moved = self._run(memory, [{"species": 1020, "name": "X", "ddpk": None}], cap)
        self.assertEqual([], moved)
        self.assertIn("X", pusher.unmatched)

    def test_a_table_that_does_not_prove_itself_is_not_touched(self) -> None:
        memory = _Memory()
        for k in range(ram_client.SHADOW_MONITOR_RECORDS):
            memory.write(TABLE + k * SIZE + ram_client.SHADOW_RECORD_SELF_ID_OFFSET, b"\0\0")
        cap = missable_autosend.AUTO_SEND_AT_STORY_BYTE[self.LABEL]
        _, moved = self._run(memory, [{"species": 1010, "name": "X", "ddpk": 10}], cap)
        self.assertEqual([], moved)


class TestTheClient(unittest.TestCase):
    def test_it_runs_after_the_auto_send_inside_the_gate(self) -> None:
        gated = CLIENT.split("if block_is_stable:", 1)[1].split("elif not ctx._block_churn_logged:", 1)[0]
        self.assertLess(gated.index("await check_missable_autosend(ctx)"), gated.index("await check_missable_shadows(ctx)"))

    def test_it_says_what_it_sent(self) -> None:
        self.assertIn("logger.info(miror_b_handoff_line)", CLIENT)
        from pathlib import Path as _P
        rc = (_P(__file__).resolve().parents[1] / "ram_client.py").read_text(encoding="utf-8")
        self.assertIn('"{name} sent to Miror B. from a missable trainer."', rc)


class TestMirorBTwoAtOnce(unittest.TestCase):
    DOL = "/mnt/user-data/uploads/PokemonXD-working/main_dol.bin"

    def test_the_word_is_the_vanilla_threshold(self) -> None:
        (address, old, new), = shadow_engine.MIROR_B_TWO_SHADOWS_WORDS
        self.assertEqual(0x38000007, old)
        self.assertEqual(0x38000002, new)
        if not os.path.exists(self.DOL):
            self.skipTest("no main.dol here")
        data = Path(self.DOL).read_bytes()
        offs = struct.unpack(">18I", data[0:72])
        addrs = struct.unpack(">18I", data[72:144])
        sizes = struct.unpack(">18I", data[144:216])
        for o, b, z in zip(offs, addrs, sizes):
            if z and b <= address < b + z:
                self.assertEqual(old, struct.unpack_from(">I", data, o + address - b)[0])
                return
        self.fail("address not in main.dol")


class TestTheWorldWithItOn(PokemonXDTestBase):
    options = {"missable_trainer_shadows": True, "shadow_pokemon_expansion": 44}

    def test_hosts_and_slot_data(self) -> None:
        world = self.multiworld.worlds[self.player]
        data = world.fill_slot_data()
        self.assertTrue(data["missable_trainer_shadows"])
        hosts = data["missable_shadow_hosts"]
        self.assertTrue(hosts)
        allowed = missable_trainers.missable_shadow_host_indices()
        for host in hosts:
            self.assertIn(host["trainer_index"], allowed)
            self.assertEqual(missable_autosend.AUTO_SEND_ONE_SHOT_INDICES[host["trainer_index"]], host["label"])
            for shadow in host["shadows"]:
                self.assertTrue(shadow["name"])

    def test_their_catches_hold_no_progression(self) -> None:
        from BaseClasses import LocationProgressType
        from ..species import location_name_for_species

        world = self.multiworld.worlds[self.player]
        hosted = [dex for dex, hosts in world._shadow_catch_expansion_hosts.items()
                  if any(int(h) in world._missable_shadow_hosts for h in hosts)]
        self.assertTrue(hosted)
        for dex in hosted:
            location = self.multiworld.get_location(location_name_for_species(dex), self.player)
            self.assertEqual(LocationProgressType.EXCLUDED, location.progress_type)


class TestTheWorldWithItOff(PokemonXDTestBase):
    options = {"shadow_pokemon_expansion": 44, "missable_trainer_shadows": False}

    def test_no_missable_hosts(self) -> None:
        world = self.multiworld.worlds[self.player]
        data = world.fill_slot_data()
        self.assertFalse(data["missable_trainer_shadows"])
        self.assertEqual([], data["missable_shadow_hosts"])
        allowed = missable_trainers.missable_shadow_host_indices()
        for plan in world._shadow_expansion_plans or ():
            self.assertNotIn(int(plan["trainer_index"]), allowed)


class TestTheKeyLairWaitsForGorigan(unittest.TestCase):
    """The Key Lair's window closes on walking in, before Ibsol, Jelstin or Fudler can be fought."""

    def test_they_wait_for_gorigan(self) -> None:
        for name in ("Defeat - Ibsol", "Defeat - Jelstin", "Defeat - Fudler"):
            self.assertEqual(0x6B, missable_autosend.AUTO_SEND_AT_STORY_BYTE[name])
            self.assertEqual((("Cipher Key Lair", 0x6B),), missable_autosend.AUTO_SEND_AREA_CAPS[name])

    def test_walking_in_sends_nothing(self) -> None:
        sender = ram_client.MissableAutoSender()
        due = sender.due(0x69, set(missable_autosend.AUTO_SEND_AT_STORY_BYTE), set())
        self.assertFalse({"Defeat - Ibsol", "Defeat - Jelstin", "Defeat - Fudler"} & set(due))


class TestTheCaveSpotRescue(PokemonXDTestBase):
    """Losing Miror B.'s Cave Poke Spot fight in vanilla leaves his Shadow (DDPK 29) unmeetable; the client hands it
    to his pool once the story is past that fight."""

    def test_slot_data_carries_it(self) -> None:
        rescues = self.multiworld.worlds[self.player].fill_slot_data()["shadow_rescues"]
        self.assertEqual(1, len(rescues))
        rescue = rescues[0]
        self.assertEqual(0x3C, rescue["cap"])
        self.assertEqual([["Poke Spots", 0x3C]], rescue["areas"])
        self.assertEqual(29, rescue["shadows"][0]["ddpk"])

    def test_the_pusher_takes_it_without_an_auto_send_label(self) -> None:
        rescue = self.multiworld.worlds[self.player].fill_slot_data()["shadow_rescues"]
        pusher = ram_client.MissableShadowPusher(rescue)
        self.assertTrue(pusher)
        self.assertEqual(0x3C, pusher.timer.schedule[rescue[0]["label"]])

    def test_it_moves_a_lost_fight_shadow(self) -> None:
        rescue = self.multiworld.worlds[self.player].fill_slot_data()["shadow_rescues"]
        memory = _Memory()
        memory.write(TABLE + 29 * SIZE, bytes((0x20, 0x20)))          # status 1: met, lost to
        pusher = ram_client.MissableShadowPusher(rescue, rng=random.Random(1))
        with mock.patch.object(ram_client, "read_bytes", memory.read), \
                mock.patch.object(ram_client, "write_bytes", memory.write):
            self.assertEqual([], pusher.poll(BLOCK, 0x3A))
            moved = pusher.poll(BLOCK, 0x3C)
        self.assertEqual(1, len(moved))
        self.assertIn("Cave Poke Spot", moved[0])
        self.assertEqual(2, memory.record(29)[0] >> 5)


class TestStartWithPokeSpots(PokemonXDTestBase):
    options = {"start_with_poke_spots": True, "randomize_travel_locations": True}

    def test_the_unlock_is_starting_inventory(self) -> None:
        from .. import items as I

        name = I.TRAVEL_UNLOCK_POKE_SPOTS_ITEM_NAME
        self.assertIn(name, [item.name for item in self.multiworld.precollected_items[self.player]])
        self.assertNotIn(name, [item.name for item in self.multiworld.itempool if item.player == self.player])


class TestShadowMonitorCatches(unittest.TestCase):
    def test_snagged_and_purified_species_are_read(self) -> None:
        memory = _Memory()
        memory.write(TABLE + 5 * SIZE, bytes((3 << 5, 0)))
        memory.write(TABLE + 6 * SIZE, bytes((4 << 5, 0)))
        memory.write(TABLE + 7 * SIZE, bytes((2 << 5, 0)))
        with mock.patch.object(ram_client, "read_bytes", memory.read):
            self.assertEqual({1005, 1006}, ram_client.read_snagged_shadow_species(BLOCK))

    def test_the_client_needs_two_reads(self) -> None:
        body = CLIENT[CLIENT.index("async def check_shadow_monitor_catches"):CLIENT.index("async def check_purifications")]
        self.assertIn("confirmed = current & ctx._shadow_monitor_last", body)

    def test_it_runs_inside_the_gate(self) -> None:
        gated = CLIENT.split("if block_is_stable:\n                        # FIRST", 1)[1].split(
            "elif not ctx._block_churn_logged:", 1)[0]
        self.assertIn("await check_shadow_monitor_catches(ctx)", gated)


class TestStartWithPokeSpotsLogic(PokemonXDTestBase):
    options = {"start_with_poke_spots": True, "randomize_travel_locations": True}

    def test_the_spots_are_open_from_the_start(self) -> None:
        self.assertTrue(self.multiworld.state.can_reach("Poke Spots", "Region", self.player))

    def test_miror_bs_cave_shadow_is_in_logic_from_the_start(self) -> None:
        from ..species import location_name_for_species

        world = self.multiworld.worlds[self.player]
        dex = next(int(d) for d, ddpks in world._shadow_catch_ddpks.items() if 29 in {int(x) for x in ddpks})
        location = self.multiworld.get_location(location_name_for_species(dex), self.player)
        self.assertTrue(location.can_reach(self.multiworld.state))


class TestStartWithPokeSpotsNeedsLocationShuffle(PokemonXDTestBase):
    options = {"start_with_poke_spots": True, "randomize_travel_locations": False}

    def test_the_option_is_turned_off(self) -> None:
        world = self.multiworld.worlds[self.player]
        self.assertFalse(bool(world.options.start_with_poke_spots))
        self.assertIn(("start_with_poke_spots", 1, 0), world.option_adjustments)

    def test_the_spots_are_not_open_from_the_start(self) -> None:
        self.assertFalse(self.multiworld.state.can_reach("Poke Spots", "Region", self.player))


class TestMissableShadowCatchesAreProgression(PokemonXDTestBase):
    options = {"missable_trainer_shadows": True, "shadow_pokemon_expansion": 40, "shadow_catch_progression": True}

    def test_hosted_catches_are_gated_like_any_shadow_and_can_hold_progression(self) -> None:
        from BaseClasses import LocationProgressType

        from .. import locations as L
        from .. import rules as R
        from ..species import location_name_for_species

        world = self.multiworld.worlds[self.player]
        hosts = set(getattr(world, "_missable_shadow_hosts", {}) or {})
        if not hosts:
            self.skipTest("no Shadow landed on a missable trainer this seed")
        gates, _unplaceable = R._catch_gates_for_species(world)
        filler = L.miror_b_filler_location_names(world)
        checked = 0
        for dex, rows in (world._shadow_catch_expansion_hosts or {}).items():
            if not any(int(r) in hosts for r in rows):
                continue
            for r in rows:
                if int(r) in hosts:
                    self.assertIn(shadow_regions.gate_for_trainer_index(int(r)), gates[int(dex)])
            name = location_name_for_species(int(dex))
            location = self.multiworld.get_location(name, self.player)
            self.assertNotIn(name, filler)
            self.assertIsNot(LocationProgressType.EXCLUDED, location.progress_type)
            checked += 1
        self.assertTrue(checked)
