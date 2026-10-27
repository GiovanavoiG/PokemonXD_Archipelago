"""With Kaminko Missable Trainers on, a missed trainer's check is won outside the manor, never sent at its area's cap."""
from __future__ import annotations

import asyncio
import inspect
import struct
import unittest
from types import SimpleNamespace
from unittest import mock

from .. import Client
from .. import ram_client as rc
from ..game_data import kaminko_trainers as kt
from ..game_data import trainer_roster
from ..game_data.missable_autosend import AUTO_SEND_ONE_SHOT_INDICES


class TestNoAutoSend(unittest.TestCase):
    def _ctx(self, kaminko: bool):
        seed = {Client.LOCATION_NAME_TO_ID[n] for n in rc.MissableAutoSender().schedule if n in Client.LOCATION_NAME_TO_ID}
        sent = []

        async def send(ctx, names):
            sent.extend(names)
        ctx = SimpleNamespace(block_base=0x80479300, shuffle_trainer_defeats=True, randomize_travel_locations=False,
                              kaminko_trainers=kaminko, missable_autosender=rc.MissableAutoSender(),
                              checked_locations=set(), notes=[])
        return ctx, seed, sent, send

    def _run(self, kaminko: bool) -> "list[str]":
        ctx, seed, sent, send = self._ctx(kaminko)
        with mock.patch.object(Client, "_witness_story_progress", lambda ctx: 0xFF), \
                mock.patch.object(Client, "seed_location_ids", lambda ctx: seed), \
                mock.patch.object(Client, "_send_checks", send), \
                mock.patch.object(Client, "_note", lambda ctx, text: None):
            asyncio.run(Client.check_missable_autosend(ctx))
        return sent

    def test_every_auto_sent_one_shot_is_a_kaminko_trainer(self) -> None:
        kaminko = {t for t, _b, _s in kt.KAMINKO_TRAINERS}
        self.assertLessEqual(set(AUTO_SEND_ONE_SHOT_INDICES), kaminko)
        self.assertEqual(set(AUTO_SEND_ONE_SHOT_INDICES.values()), Client.kaminko_autosend_labels())

    def test_option_off_still_sends_at_the_cap(self) -> None:
        self.assertLessEqual(Client.kaminko_autosend_labels(), set(self._run(False)))

    def test_option_on_sends_none_of_them(self) -> None:
        sent = set(self._run(True))
        self.assertFalse(sent & Client.kaminko_autosend_labels())
        self.assertEqual(set(self._run(False)) - Client.kaminko_autosend_labels(), sent)   # the rest is unchanged

    def test_the_missables_command_says_so(self) -> None:
        self.assertIn("kaminko_autosend_labels()", inspect.getsource(Client.PokemonXDCommandProcessor._cmd_missables))


class TestShadowsStayWithTheTrainer(unittest.TestCase):
    HOSTS = [{"label": AUTO_SEND_ONE_SHOT_INDICES[t], "trainer_index": t, "shadows": [{"species": 1}]}
             for t in sorted(AUTO_SEND_ONE_SHOT_INDICES)[:3]]
    RESCUE = {"label": "somewhere else", "trainer_index": -1, "shadows": [{"species": 2}]}

    def test_option_off_hands_them_to_miror_b(self) -> None:
        self.assertEqual(self.HOSTS, Client.kaminko_shadow_hosts(self.HOSTS, False))

    def test_option_on_keeps_them_for_the_rematch(self) -> None:
        self.assertEqual([], Client.kaminko_shadow_hosts(self.HOSTS, True))
        self.assertEqual([self.RESCUE], Client.kaminko_shadow_hosts(self.HOSTS + [self.RESCUE], True))

    def test_the_pusher_is_built_through_it(self) -> None:
        src = inspect.getsource(Client)
        self.assertIn("kaminko_shadow_hosts(list(slot_data.get(\"missable_shadow_hosts\") or []), self.kaminko_trainers)",
                      src)
        self.assertLess(src.index("self.kaminko_trainers = bool(slot_data.get(\"kaminko_missable_trainers\""),
                        src.index("kaminko_shadow_hosts(list(slot_data"))

    def test_the_slot_fights_the_trainers_own_battle(self) -> None:
        for trainer, battle, _src in kt.KAMINKO_TRAINERS:
            self.assertIn(trainer, trainer_roster.TRAINERS_BY_INDEX)
            self.assertGreater(battle, 0)


class TestBeatenWhereItStood(unittest.TestCase):
    def test_a_sent_defeat_check_keeps_it_away(self) -> None:
        trainer = next(iter(AUTO_SEND_ONE_SHOT_INDICES))
        label = trainer_roster.trainer_label(trainer_roster.TRAINERS_BY_INDEX[trainer])
        ctx = SimpleNamespace(kaminko_won=set(), checked_locations=set())
        with mock.patch.object(rc, "gs_flag_get", lambda flag: 0):
            self.assertFalse(Client._kaminko_trainer_beaten(ctx, trainer))
            ctx.checked_locations.add(Client.LOCATION_NAME_TO_ID[label])
            self.assertTrue(Client._kaminko_trainer_beaten(ctx, trainer))


class TestWaitsForProgress(unittest.TestCase):
    def test_unknown_progress_is_not_known(self) -> None:
        ctx = SimpleNamespace(missable_autosender=rc.MissableAutoSender(),
                              story_progress=SimpleNamespace(high_water=-1))
        with mock.patch.object(Client, "_missable_area_progress", lambda ctx: None):
            self.assertFalse(Client._kaminko_progress_known(ctx))
            ctx.story_progress.high_water = None
            self.assertFalse(Client._kaminko_progress_known(ctx))
            ctx.story_progress.high_water = 0
            self.assertTrue(Client._kaminko_progress_known(ctx))

    def test_with_travel_shuffled_it_needs_an_area_reading(self) -> None:
        ctx = SimpleNamespace(area_story_memory=SimpleNamespace(highest_by_region={}))
        with mock.patch.object(Client, "_missable_area_progress", lambda ctx: (lambda region: None)):
            self.assertFalse(Client._kaminko_progress_known(ctx))
            ctx.area_story_memory.highest_by_region["Gateon Port"] = 0x10
            self.assertTrue(Client._kaminko_progress_known(ctx))

    def test_a_fresh_load_waits_rather_than_filling_empty(self) -> None:
        slots = rc.KaminkoTrainerSlots()
        filled = []
        with mock.patch.object(slots, "_locate", lambda: {b"GVAR": 0}), \
                mock.patch.object(rc, "read_bytes", lambda a, n: b"\x00" * n), \
                mock.patch.object(slots, "_fill", lambda offsets, is_beaten: filled.append(1) or []):
            slots.blob = 0x80000000
            self.assertEqual([], slots.poll(True, lambda t: True, ready=False))
            self.assertEqual([], filled)
            slots.poll(True, lambda t: True, ready=True)
            self.assertEqual([1], filled)

    def test_the_client_passes_it(self) -> None:
        self.assertIn("ready=_kaminko_progress_known(ctx)", inspect.getsource(Client.check_kaminko_trainers))


if __name__ == "__main__":
    unittest.main()


class TestCumulativeMode(unittest.TestCase):
    """No "Defeat -" location exists in cumulative mode, so a trainer beaten where it stood is known from the win."""

    def _ctx(self):
        return SimpleNamespace(kaminko_won=set(), checked_locations=set(), trainer_team_fingerprints={},
                               trainer_defeat_tracker=rc.TrainerBattleDefeatTracker())

    def test_a_win_over_a_one_of_a_kind_trainer_keeps_it_away(self) -> None:
        ctx = self._ctx()
        with mock.patch.object(rc, "gs_flag_get", lambda flag: 0):
            self.assertFalse(Client._kaminko_trainer_beaten(ctx, 74))              # Mocor: no beaten flag
            ctx.trainer_defeat_tracker.wins_by_surname["MOCOR"] = 1
            self.assertTrue(Client._kaminko_trainer_beaten(ctx, 74))

    def test_a_shared_surname_needs_its_own_team(self) -> None:
        ctx = self._ctx()
        record = trainer_roster.TRAINERS_BY_INDEX[39]                                # Resix #2
        ctx.trainer_defeat_tracker.wins_by_surname["RESIX"] = 1
        with mock.patch.object(rc, "gs_flag_get", lambda flag: 0):
            self.assertFalse(Client._kaminko_trainer_beaten(ctx, 39))
            ctx.trainer_defeat_tracker._beaten_team_ids["RESIX"] = [f"occ:{trainer_roster.trainer_label(record)}"]
            self.assertTrue(Client._kaminko_trainer_beaten(ctx, 39))

    def test_the_sixes_second_fights_are_missed_when_snattle_falls(self) -> None:
        ctx = SimpleNamespace(missable_autosender=rc.MissableAutoSender(),
                              story_progress=SimpleNamespace(high_water=0x47))
        with mock.patch.object(Client, "_missable_area_progress", lambda ctx: None):
            self.assertFalse(Client._kaminko_trainer_missed(ctx, 39))
            ctx.story_progress.high_water = 0x48
            for trainer in range(39, 45):
                self.assertTrue(Client._kaminko_trainer_missed(ctx, trainer), trainer)


class TestTheGlobalsAreTypedIntegers(unittest.TestCase):
    """The loader leaves an added global's disc kind word (0x00000001) as it is, and the script reads that as no type:
    Miror B.'s flag and every slot's battle read as nothing until the client wrote the integer type itself."""

    def _slots(self):
        mem = {}
        gvar = 0x1000

        def read(address, length):
            return b"".join(mem.get(address + i, b"\x00") for i in range(length))

        def write(address, data):
            for i, byte in enumerate(data):
                mem[address + i] = bytes([byte])
        write(0x80000000 + gvar + 0x10, struct.pack(">I", kt.VANILLA_GVAR_COUNT + kt.GVAR_ADDED))
        for k in range(kt.GVAR_BATTLE_BASE, kt.GVAR_BATTLE_BASE + kt.GVAR_ADDED):
            write(0x80000000 + gvar + 0x20 + 8 * k, struct.pack(">II", 1, 7))      # as the disc leaves them
        slots = rc.KaminkoTrainerSlots()
        slots.blob = 0x80000000
        return slots, {b"GVAR": gvar}, read, write

    def test_untyped_globals_get_the_integer_type_and_keep_their_value(self) -> None:
        slots, offsets, read, write = self._slots()
        with mock.patch.object(rc, "read_bytes", read), mock.patch.object(rc, "write_bytes", write):
            slots._type_added_globals(offsets)
            for k in range(kt.GVAR_BATTLE_BASE, kt.GVAR_BATTLE_BASE + kt.GVAR_ADDED):
                self.assertEqual((0x0001, 0, 7), struct.unpack(">HHI", read(0x80000000 + 0x1000 + 0x20 + 8 * k, 8)))
            self.assertEqual(kt.GVAR_ADDED, slots.type_fixes)
            slots._type_added_globals(offsets)
            self.assertEqual(kt.GVAR_ADDED, slots.type_fixes)                # nothing to fix the second time

    def test_an_older_script_s_globals_are_left_as_they_are(self) -> None:
        slots, offsets, read, write = self._slots()
        write(0x80000000 + 0x1000 + 0x10, struct.pack(">I", kt.VANILLA_GVAR_COUNT + 38))
        with mock.patch.object(rc, "read_bytes", read), mock.patch.object(rc, "write_bytes", write):
            slots._type_added_globals(offsets)
            self.assertEqual(38, slots.type_fixes)
            self.assertEqual((0, 1, 7), struct.unpack(">HHI", read(0x80000000 + 0x1000 + 0x20 + 8 * (7 + 38), 8)))

    def test_writes_carry_the_type(self) -> None:
        slots, offsets, read, write = self._slots()
        with mock.patch.object(rc, "read_bytes", read), mock.patch.object(rc, "write_bytes", write):
            slots._set_gvar(offsets, kt.GVAR_MIROR, 1)
            self.assertEqual((0x0001, 0, 1),
                             struct.unpack(">HHI", read(0x80000000 + 0x1000 + 0x20 + 8 * kt.GVAR_MIROR, 8)))
