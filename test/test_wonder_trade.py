"""Wonder trades: XD's records against the shared pool format, and the pool protocol, both ways."""
from __future__ import annotations

import asyncio
import copy
import json
import pathlib
import struct
import unittest
from types import SimpleNamespace
from unittest import mock

from .. import ram_client as rc
from .. import wonder_trade_client as wtc
from ..game_data import wonder_trade as wt
from ..game_data import wonder_trade_tables as tables
from .local_dumps import DUMPS

DUMP = "loc_kaminko.bin"
BLOCK = 0x80479380


def _dump_records() -> "list[bytes]":
    path = DUMPS / DUMP
    if not path.is_file():
        return []
    mem = path.read_bytes()
    out = []
    for slot in range(3):
        a = BLOCK - 0x10 + slot * 0xC4 - rc.MEM1_START
        out.append(mem[a:a + 0xC4])
    for slot in range(12):
        a = rc.box_record_address(BLOCK, slot) - rc.MEM1_START
        out.append(mem[a:a + 0xC4])
    return [r for r in out if r[:2] != b"\x00\x00"]


def _record(internal=279, level=26, pid=0x12345678, tid=0xF82496DE, moves=((33, 35, 0), (0, 0, 0)), item=0,
            shadow=0, flags=0x10) -> bytes:
    r = bytearray(rc.EMPTY_BOX_RECORD)
    struct.pack_into(">H", r, wt.OFF_SPECIES, internal)
    struct.pack_into(">H", r, wt.OFF_ITEM, item)
    r[wt.OFF_LEVEL] = level
    r[wt.OFF_MET_LEVEL] = 5
    r[wt.OFF_BALL] = 4
    r[wt.OFF_FLAGS] = flags
    r[wt.OFF_VERSION], r[wt.OFF_LANGUAGE] = 11, 2
    struct.pack_into(">I", r, wt.OFF_EXP, wt.exp_total(tables.SPECIES.get(internal, (0, 0))[1], level))
    struct.pack_into(">I", r, wt.OFF_TRAINER_ID, tid)
    struct.pack_into(">I", r, wt.OFF_PID, pid)
    r[wt.OFF_OT_NAME:wt.OFF_OT_NAME + 22] = wt.encode_name("Gioig")
    r[wt.OFF_NICKNAME:wt.OFF_NICKNAME + 22] = wt.encode_name("SCEPTILE")
    for i, (m, pp, ups) in enumerate(list(moves) + [(0, 0, 0)] * (4 - len(moves))):
        struct.pack_into(">HBB", r, wt.OFF_MOVES + 4 * i, m, pp, ups)
    for k in range(6):
        r[wt.OFF_IVS + k] = 10 + k
        struct.pack_into(">H", r, wt.OFF_EVS + 2 * k, 20 * k)
    struct.pack_into(">H", r, wt.OFF_SHADOW_ID, shadow)
    return bytes(r)


class TestTheTables(unittest.TestCase):
    def test_every_species_once_and_items_both_ways(self) -> None:
        self.assertEqual(set(range(1, 387)), {row[0] for row in tables.SPECIES.values()})
        self.assertEqual(234, tables.GEN3_TO_MODERN_ITEM[200])        # Leftovers
        self.assertEqual(200, tables.MODERN_TO_GEN3_ITEM[234])

    def test_the_live_tables_are_where_the_client_looks(self) -> None:
        path = DUMPS / DUMP
        if not path.is_file():
            self.skipTest("the MEM1 dumps are not on this machine")
        mem = path.read_bytes()
        with mock.patch.object(rc, "read_bytes", lambda a, n: mem[a - rc.MEM1_START:a - rc.MEM1_START + n]):
            curves = rc.live_species_curves()
            pp = rc.live_move_base_pp()
            self.assertEqual(0xF82496DE, rc.hero_trainer_id(BLOCK))
        self.assertEqual({i: row[1] for i, row in tables.SPECIES.items()}, curves)
        self.assertEqual(35, pp[33])          # Tackle
        self.assertEqual(5, pp[354])          # Psycho Boost


class TestRecordsFromTheDumps(unittest.TestCase):
    def test_send_then_receive_gives_the_same_pokemon_back(self) -> None:
        records = _dump_records()
        if not records:
            self.skipTest("the MEM1 dumps are not on this machine")
        for record in records:
            payload = wt.record_to_payload(record)
            wt.check_payload_shape(payload)
            back = wt.payload_to_record(json.loads(wt.dump_payload(payload)), record, None, None)
            for lo, hi in ((0x00, 0x02), (0x0E, 0x12), (0x20, 0x2C), (0x38, 0x7A), (0x80, 0x90), (0x92, 0x9A),
                           (0x9C, 0xB3)):
                self.assertEqual(record[lo:hi].hex(), back[lo:hi].hex(), (hex(lo), payload["nickname"]))

    def test_stats_come_out_as_the_game_computed_them(self) -> None:
        records = [r for r in _dump_records() if not wt.is_shadow(r)]
        if not records:
            self.skipTest("the MEM1 dumps are not on this machine")
        for record in records:
            payload = wt.record_to_payload(record)
            back = wt.payload_to_record(payload, record, None, None)
            self.assertEqual(record[wt.OFF_STATS:wt.OFF_STATS + 12], back[wt.OFF_STATS:wt.OFF_STATS + 12])


class TestSending(unittest.TestCase):
    def test_the_payload_has_every_field_the_others_need(self) -> None:
        payload = wt.record_to_payload(_record())
        self.assertEqual(254, payload["species"])
        self.assertEqual(15, payload["game"])
        self.assertEqual(wt.METLOC_IN_GAME_TRADE, payload["location_met"])
        self.assertEqual(0xF82496DE, payload["trainer"]["id"])
        self.assertEqual([[33, 35, 0], [0, 0, 0], [0, 0, 0], [0, 0, 0]], payload["moves"])
        self.assertEqual([10, 11, 12, 15, 13, 14], payload["ivs"])      # XD keeps Speed last
        self.assertNotIn("item", payload)

    def test_shadow_moves_are_dropped_and_a_pokemon_left_with_none_stays(self) -> None:
        payload = wt.record_to_payload(_record(moves=((360, 5, 0), (33, 35, 0))))
        self.assertEqual([33, 35, 0], payload["moves"][0])
        with self.assertRaises(wt.TradeError):
            wt.record_to_payload(_record(moves=((360, 5, 0),)))

    def test_eggs_and_xd_only_species_stay(self) -> None:
        with self.assertRaises(wt.TradeError):
            wt.record_to_payload(_record(flags=0x80))
        with self.assertRaises(wt.TradeError):
            wt.record_to_payload(_record(internal=413))                # Bonsly
        with self.assertRaises(wt.TradeError):
            wt.record_to_payload(_record(internal=0))

    def test_items_this_seed_reuses_never_leave(self) -> None:
        for item in (50, 51, 148, 161, 169, 175):
            self.assertNotIn("item", wt.record_to_payload(_record(item=item)))
        self.assertEqual(234, wt.record_to_payload(_record(item=200))["item"])

    def test_experience_goes_out_on_the_vanilla_curve(self) -> None:
        record = bytearray(_record(level=30))
        struct.pack_into(">I", record, wt.OFF_EXP, wt.exp_total(4, 30))           # this seed made it Fast
        payload = wt.record_to_payload(bytes(record), seed_curve=4)
        self.assertEqual(wt.exp_total(3, 30), payload["experience"])               # Sceptile is Medium Slow
        self.assertEqual(30, wt.level_for_exp(3, payload["experience"]))


class TestReceiving(unittest.TestCase):
    def _payload(self, **over):
        payload = wt.record_to_payload(_record())
        payload.update(over)
        return payload

    def test_reserved_items_are_dropped(self) -> None:
        for modern in (tables.GEN3_TO_MODERN_ITEM[50], tables.GEN3_TO_MODERN_ITEM[161]):
            record = wt.payload_to_record(self._payload(item=modern), None, None, None)
            self.assertEqual(0, struct.unpack_from(">H", record, wt.OFF_ITEM)[0])
        record = wt.payload_to_record(self._payload(item=234), None, None, None)
        self.assertEqual(200, struct.unpack_from(">H", record, wt.OFF_ITEM)[0])

    def test_a_crystal_payload_has_its_item_read_as_generation_three(self) -> None:
        tid, dvs, species = 0x1234, 0xABCD, 25
        crystal = {"version": "1", "personality": (tid << 16) | (dvs << 8) | species, "nickname": "PIKACHU",
                   "language": "English", "species": species, "experience": 1000, "ability": 0,
                   "ivs": [21] * 6, "evs": [0] * 6, "conditions": [0] * 6, "pokerus": 0, "location_met": 254,
                   "level_met": 5, "game": 0, "ball": 4, "moves": [[84, 30, 0], [0, 0, 0], [0, 0, 0], [0, 0, 0]],
                   "trainer": {"name": "GOLD", "id": tid, "female": False}, "item": 200}
        self.assertTrue(wt.looks_like_crystal(crystal))
        record = wt.payload_to_record(crystal, None, None, None)
        self.assertEqual(200, struct.unpack_from(">H", record, wt.OFF_ITEM)[0])    # Leftovers, not modern 200
        self.assertFalse(wt.looks_like_crystal(self._payload()))

    def test_the_level_follows_the_seeds_curve(self) -> None:
        payload = self._payload(experience=wt.exp_total(3, 40))
        record = wt.payload_to_record(payload, None, 4, None)
        self.assertEqual(40, record[wt.OFF_LEVEL])
        self.assertEqual(40, wt.level_for_exp(4, struct.unpack_from(">I", record, wt.OFF_EXP)[0]))

    def test_moves_xd_lacks_go_and_pp_is_capped(self) -> None:
        payload = self._payload(moves=[[400, 5, 0], [33, 99, 3], [0, 0, 0], [0, 0, 0]])
        record = wt.payload_to_record(payload, None, None, lambda move, ups: 35 * (5 + ups) // 5)
        self.assertEqual((33, 56, 3), struct.unpack_from(">HBB", record, wt.OFF_MOVES))
        self.assertIsNone(wt.parse_entry([1, json.dumps(self._payload(moves=[[400, 5, 0]] * 4))]))

    def test_it_arrives_as_no_one_s_shadow_with_full_hp(self) -> None:
        record = wt.payload_to_record(self._payload(), _record(shadow=0x53), None, None)
        self.assertFalse(wt.is_shadow(record))
        self.assertEqual(struct.unpack_from(">H", record, wt.OFF_STATS)[0], struct.unpack_from(">H", record, wt.OFF_HP)[0])
        self.assertEqual(0, struct.unpack_from(">H", record, wt.OFF_RIBBONS)[0])

    def test_junk_never_raises(self) -> None:
        for entry in (None, [], [1], [1, "not json"], [1, "[]"], [1, json.dumps({"species": 999})],
                      [1, json.dumps({"species": 25})], [1, json.dumps({"species": "25", "moves": [[1, 1, 1]]})]):
            self.assertIsNone(wt.parse_entry(entry))


class TestAgainstEmerald(unittest.TestCase):
    """Emerald's own reader and writer, from the Archipelago install the suite runs in."""

    def setUp(self) -> None:
        try:
            from worlds.pokemon_emerald import util as emerald
        except Exception:
            self.skipTest("Pokemon Emerald's world is not importable here")
        self.emerald = emerald

    def test_emerald_takes_what_xd_sends_and_hands_it_back_unchanged(self) -> None:
        records = _dump_records() or [_record(), _record(internal=145, item=200)]
        for record in records:
            blob = wt.dump_payload(wt.record_to_payload(record))
            data = self.emerald.json_to_pokemon_data(blob)
            back = json.loads(self.emerald.pokemon_data_to_json(data))
            sent = json.loads(blob)
            for key in ("species", "personality", "experience", "ability", "ivs", "evs", "conditions", "pokerus",
                        "location_met", "level_met", "game", "ball", "moves", "item"):
                self.assertEqual(sent.get(key), back.get(key), key)
            self.assertEqual(sent["trainer"]["id"], back["trainer"]["id"])

    def test_xd_takes_what_emerald_sends(self) -> None:
        sent = json.loads(wt.dump_payload(wt.record_to_payload(_record(item=200))))
        blob = self.emerald.pokemon_data_to_json(self.emerald.json_to_pokemon_data(json.dumps(sent)))
        parsed = wt.parse_entry([3, blob])
        self.assertIsNotNone(parsed)
        record = wt.payload_to_record(parsed[1], None, None, None)
        self.assertEqual(279, struct.unpack_from(">H", record, 0)[0])
        self.assertEqual(200, struct.unpack_from(">H", record, wt.OFF_ITEM)[0])


SHADOW_MOVES_EVERYWHERE = ((360, 5, 0), (33, 35, 2), (355, 5, 0), (89, 10, 1))   # Shadow moves in slots 1 and 3


class TestShadowMovesNeverLeave(unittest.TestCase):
    def test_every_shadow_move_is_trimmed_with_its_pp(self) -> None:
        payload = wt.record_to_payload(_record(moves=SHADOW_MOVES_EVERYWHERE))
        self.assertEqual([[33, 35, 2], [89, 10, 1], [0, 0, 0], [0, 0, 0]], payload["moves"])
        for move_id, _pp, _ups in payload["moves"]:
            self.assertLessEqual(move_id, wt.MAX_MOVE)

    def test_emerald_gets_only_the_ordinary_moves(self) -> None:
        try:
            from worlds.pokemon_emerald import util as emerald
        except Exception:
            self.skipTest("Pokemon Emerald's world is not importable here")
        blob = wt.dump_payload(wt.record_to_payload(_record(moves=SHADOW_MOVES_EVERYWHERE)))
        back = json.loads(emerald.pokemon_data_to_json(emerald.json_to_pokemon_data(blob)))
        self.assertEqual([[33, 35, 2], [89, 10, 1], [0, 0, 0], [0, 0, 0]], back["moves"])


CRYSTAL_UTIL = pathlib.Path("/tmp/claude-0/-home-claude/ed964a6f-a62c-5162-8c9c-af104820d6b4/scratchpad/wt/cr/worlds/"
                            "pokemon_crystal/util_wonder_trade.py")


@unittest.skipUnless(CRYSTAL_UTIL.is_file(), "needs Pokemon Crystal's wonder trade module")
class TestAgainstCrystal(unittest.TestCase):
    """Crystal's own reader and writer (gerbiljames/Archipelago, pokecrystal)."""

    def setUp(self) -> None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("crystal_wonder_trade", CRYSTAL_UTIL)
        self.crystal = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.crystal)

    def test_crystal_takes_what_xd_sends(self) -> None:
        payload = wt.record_to_payload(_record(internal=25, moves=SHADOW_MOVES_EVERYWHERE))   # Pikachu: Crystal has it
        blob = wt.dump_payload(payload)
        self.assertTrue(self.crystal.trade_is_eligible([7, blob], 1))
        mon = self.crystal.json_to_pokemon_data(blob)["party_mon"]
        self.assertEqual([33, 89, 0, 0], list(mon[self.crystal.MON_MOVES:self.crystal.MON_MOVES + 4]))

    def test_a_pokemon_with_only_later_moves_waits_for_another_game(self) -> None:
        blob = wt.dump_payload(wt.record_to_payload(_record(internal=25, moves=((300, 10, 0), (360, 5, 0)))))
        self.assertFalse(self.crystal.trade_is_eligible([7, blob], 1))

    def test_xd_takes_what_crystal_sends(self) -> None:
        start = self.crystal.json_to_pokemon_data(wt.dump_payload(wt.record_to_payload(_record(internal=25))))
        blob = self.crystal.pokemon_data_to_json(start["party_mon"], start["nickname"], start["ot"], 0x1234, False)
        parsed = wt.parse_entry([0x1234, blob])
        self.assertIsNotNone(parsed)
        self.assertTrue(wt.looks_like_crystal(parsed[1]))
        record = wt.payload_to_record(parsed[1], None, None, None)
        self.assertEqual(25, struct.unpack_from(">H", record, 0)[0])
        self.assertEqual(33, struct.unpack_from(">H", record, wt.OFF_MOVES)[0])


# ---------------------------------------------------------------------------------------------------------------
# The protocol, against a server that applies Set the way MultiServer does.

class FakeServer:
    def __init__(self) -> None:
        self.value: "dict | None" = None
        self.clients = []
        self.drop = lambda message: False

    async def handle(self, client, messages) -> None:
        for message in messages:
            if message["cmd"] != "Set":
                continue
            if self.value is None:
                self.value = copy.deepcopy(message.get("default"))
            original = copy.copy(self.value)
            for op in message["operations"]:
                if op["operation"] == "update":
                    self.value.update(copy.deepcopy(op["value"]))
                elif op["operation"] == "pop":
                    self.value.pop(op["value"], None)
            reply = {"cmd": "SetReply", "key": message["key"], "value": copy.deepcopy(self.value),
                     "original_value": original, **{k: v for k, v in message.items()
                                                     if k not in ("cmd", "key", "operations", "default")}}
            for other in self.clients:
                other.stored_data[message["key"]] = copy.deepcopy(self.value)
                if other is client and message.get("want_reply") and not self.drop(message):
                    asyncio.get_event_loop().call_soon(other.wonder_trade.on_set_reply, reply)


def _ctx(server: FakeServer, slot: int):
    ctx = SimpleNamespace(slot=slot, team=0, block_base=BLOCK, stored_data={}, saved=0)
    ctx.wonder_trade = wtc.WonderTrade()
    ctx._save_local_state = lambda: setattr(ctx, "saved", ctx.saved + 1)

    async def send_msgs(messages):
        await server.handle(ctx, messages)
    ctx.send_msgs = send_msgs
    server.clients.append(ctx)
    return ctx


class FakeBoxes:
    def __init__(self, records: "dict[int, bytes]") -> None:
        self.records = dict(records)

    def read(self, block, slot):
        return self.records.get(slot, rc.EMPTY_BOX_RECORD)

    def write(self, block, slot, record):
        self.records[slot] = record
        return True

    def first_empty(self, block):
        return next(i for i in range(240) if self.read(block, i)[:2] == b"\x00\x00")


class TestTheProtocol(unittest.TestCase):
    def setUp(self) -> None:
        self.boxes = FakeBoxes({0: _record(), 1: _record(internal=145, pid=7, moves=((84, 30, 0),))})
        patches = [
            mock.patch.object(rc, "read_box_record", self.boxes.read),
            mock.patch.object(rc, "write_box_record", self.boxes.write),
            mock.patch.object(rc, "first_empty_box_slot", self.boxes.first_empty),
            mock.patch.object(rc, "live_species_curves", lambda: {i: row[1] for i, row in tables.SPECIES.items()}),
            mock.patch.object(rc, "live_move_base_pp", lambda: {m: 35 for m in range(1, 355)}),
            mock.patch.object(rc, "hero_trainer_id", lambda block: 0xF82496DE),
            mock.patch.object(rc, "read_shadow_monitor", lambda block: {0x53}),
            mock.patch.object(wt, "LOCK_TTL_MS", 0),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _run(self, coro):
        return asyncio.run(coro)

    async def _poll(self, ctx, times=1):
        for _ in range(times):
            ctx.wonder_trade.next_try = 0.0
            await ctx.wonder_trade.poll(ctx, lambda: True)

    def test_a_send_posts_once_then_leaves_the_box(self) -> None:
        async def go():
            server = FakeServer()
            ctx = _ctx(server, 1)
            self.assertIn("Sending", ctx.wonder_trade.prepare_send(ctx, 1, 1))
            self.assertEqual(wtc.POSTING, ctx.wonder_trade.state)
            await self._poll(ctx)
            return server, ctx
        server, ctx = self._run(go())
        offers = {k: v for k, v in server.value.items() if k != "_lock"}
        self.assertEqual(1, len(offers))
        self.assertEqual(1, offers["0"][0])
        self.assertEqual(254, json.loads(offers["0"][1])["species"])
        self.assertEqual(0, server.value["_lock"])
        self.assertEqual(b"\x00\x00", self.boxes.records[0][:2])
        self.assertEqual(wtc.AWAITING, ctx.wonder_trade.state)

    def test_two_games_swap_both_ways(self) -> None:
        async def go():
            server = FakeServer()
            a, b = _ctx(server, 1), _ctx(server, 2)
            a.wonder_trade.prepare_send(a, 1, 1)
            await self._poll(a)
            # The other player's Pokemon, as Emerald would post it.
            other = wt.record_to_payload(_record(internal=25 if 25 in tables.SPECIES else 25, pid=99, tid=5))
            server.value["5"] = [7, wt.dump_payload(other)]
            for c in server.clients:
                c.stored_data[wt.pool_key(0)] = copy.deepcopy(server.value)
            await self._poll(a)                       # claims it
            self.assertEqual(wtc.RECEIVED, a.wonder_trade.state)
            await self._poll(a, times=1 + wtc.WRITE_CONFIRM_POLLS)
            return server, a
        server, a = self._run(go())
        self.assertEqual(wtc.IDLE, a.wonder_trade.state)
        self.assertNotIn("5", server.value)
        self.assertIn("0", server.value)              # ours stays for someone else
        slot = next(i for i, r in self.boxes.records.items() if struct.unpack_from(">I", r, wt.OFF_PID)[0] == 99)
        self.assertEqual(0, slot)                     # the first free slot: where ours left
        self.assertIn(99, a.wonder_trade.received_pids)
        self.assertEqual(1, a.wonder_trade.received)

    def test_it_never_takes_its_own(self) -> None:
        async def go():
            server = FakeServer()
            a = _ctx(server, 1)
            a.wonder_trade.prepare_send(a, 1, 1)
            await self._poll(a, times=3)
            return a
        a = self._run(go())
        self.assertEqual(wtc.AWAITING, a.wonder_trade.state)

    def test_a_shadow_must_be_purified_first(self) -> None:
        self.boxes.records[2] = _record(shadow=0x60)
        self.boxes.records[3] = _record(shadow=0x53)
        ctx = _ctx(FakeServer(), 1)
        self.assertIn("purify", ctx.wonder_trade.prepare_send(ctx, 1, 3))
        self.assertIn("Sending", ctx.wonder_trade.prepare_send(ctx, 1, 4))

    def test_a_pokemon_moved_before_it_left_is_never_traded(self) -> None:
        async def go():
            server = FakeServer()
            ctx = _ctx(server, 1)
            ctx.wonder_trade.prepare_send(ctx, 1, 1)
            self.boxes.records[0] = _record(pid=0xBEEF)       # the player put something else there
            await self._poll(ctx)
            return server, ctx
        server, ctx = self._run(go())
        self.assertEqual(wtc.IDLE, ctx.wonder_trade.state)
        self.assertEqual([], [k for k in server.value if k != "_lock"])
        self.assertEqual(0xBEEF, struct.unpack_from(">I", self.boxes.records[0], wt.OFF_PID)[0])

    def test_a_lost_reply_never_posts_twice(self) -> None:
        async def go():
            server = FakeServer()
            ctx = _ctx(server, 1)
            ctx.wonder_trade.prepare_send(ctx, 1, 1)
            # The post lands, but its answer never comes back.
            server.drop = lambda m: any(k != "_lock" for op in m["operations"] if op["operation"] == "update"
                                        for k in op["value"])
            with mock.patch.object(wt, "REPLY_TIMEOUT_S", 0.01):
                await self._poll(ctx)
            self.assertEqual(wtc.POSTING, ctx.wonder_trade.state)
            server.drop = lambda m: False
            await self._poll(ctx, times=2)
            return server, ctx
        server, ctx = self._run(go())
        self.assertEqual(wtc.AWAITING, ctx.wonder_trade.state)
        self.assertEqual(1, len([k for k in server.value if k != "_lock"]))

    def test_a_fresh_lock_is_respected(self) -> None:
        async def go():
            server = FakeServer()
            ctx = _ctx(server, 1)
            ctx.wonder_trade.prepare_send(ctx, 1, 1)
            import time
            server.value = {"_lock": int(time.time_ns() / 1_000_000)}
            with mock.patch.object(wt, "LOCK_TTL_MS", 5000):
                await self._poll(ctx)
            return server, ctx
        server, ctx = self._run(go())
        self.assertEqual(wtc.POSTING, ctx.wonder_trade.state)
        self.assertEqual([], [k for k in server.value if k != "_lock"])
        self.assertGreater(ctx.wonder_trade.cooldown_ms, wt.BASE_COOLDOWN_MS)

    def test_state_survives_a_restart(self) -> None:
        t = wtc.WonderTrade()
        t.state, t.blob, t.received_pids = wtc.AWAITING, "{}", {5}
        u = wtc.WonderTrade()
        u.load_json(json.loads(json.dumps(t.to_json())))
        self.assertEqual((wtc.AWAITING, "{}", {5}), (u.state, u.blob, u.received_pids))
        u.load_json({"state": "received"})
        self.assertEqual(wtc.IDLE, u.state)


class TestTradedPokemonAreNotCatches(unittest.TestCase):
    def test_a_species_only_a_traded_pokemon_holds_is_left_out(self) -> None:
        records = {rc.box_record_address(BLOCK, 0): _record(internal=25, pid=99),
                   rc.box_record_address(BLOCK, 1): _record(internal=279, pid=5),
                   rc.box_record_address(BLOCK, 2): _record(internal=279, pid=98)}

        def read(address, length):
            return records.get(address, rc.EMPTY_BOX_RECORD)[:length]
        with mock.patch.object(rc, "read_bytes", read):
            self.assertEqual({25}, rc.traded_only_species(BLOCK, {99, 98}))
            self.assertEqual(set(), rc.traded_only_species(BLOCK, set()))

    def test_the_client_filters_catches_and_purifications(self) -> None:
        import inspect
        from .. import Client
        catches = inspect.getsource(Client.check_species_catches)
        self.assertIn("traded_only_species", catches)
        self.assertIn("r.pid not in _traded", inspect.getsource(Client.check_purifications))


if __name__ == "__main__":
    unittest.main()
