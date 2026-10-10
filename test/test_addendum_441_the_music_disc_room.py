"""ADDENDUM 441 (2026-10-09) -- the Music Disc's room holds one story step lower.

Player: "The phenac guard is slightly weird and continuously brings up the music disc dialogue in its room, and I
couldnt pick up the item. Can we try lowering the guard byte by one?"
"""
from __future__ import annotations

import unittest
from pathlib import Path

from .. import ram_client as rc
from ..game_data import story_bytes as sb
from .test_addendum_229_map_backout_restore import BLOCK, _LiveByte

CLIENT = (Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")
DISC_ROOM = 98
TOWN = 94
REALGAM = 49


class _Base(unittest.TestCase):
    start = 0x41

    def setUp(self):
        self.live = _LiveByte(self.start)
        self.log = rc.StoryByteWriteLog()
        self.hold = rc.MusicDiscStoryHold(enabled=True, write_log=self.log)

    def tearDown(self):
        self.live.restore_module()

    def poll(self, room, checked=False):
        return self.hold.poll(BLOCK, self.live.value, room, checked)


class TestTheBytes(unittest.TestCase):
    def test_one_story_step_below_the_pickup(self):
        self.assertEqual(0x3F, rc.MUSIC_DISC_ROOM_FLOOR)
        self.assertEqual(sb.story_value_for_byte(0x41) - sb.STORY_VARIABLE_STEP, sb.story_value_for_byte(0x3F))
        self.assertEqual(510, sb.story_value_for_byte(0x3F))
        self.assertTrue(sb.byte_is_reachable(0x3F))
        self.assertTrue(rc._music_disc_room_floor_is_one_step_down())
        self.assertEqual(98, rc.MUSIC_DISC_ROOM_ID)


class TestInTheRoom(_Base):
    def test_the_floor_itself_is_lowered_so_the_scene_cannot_start(self):
        note = self.poll(DISC_ROOM)
        self.assertEqual(0x3F, self.live.value)
        self.assertTrue(self.hold.lowered)
        self.assertIn("0x3F", note)
        self.assertEqual(0x3F, self.hold.last_written_value, "owned, so the area memory never banks it")
        self.assertIsNone(self.hold.declined_value, "nothing past the floor was declined")
        self.assertIsNone(self.poll(DISC_ROOM), "steady in the room")
        self.assertEqual(0x3F, self.live.value)

    def test_a_pickup_is_still_remembered(self):
        self.live.value = 0x42
        self.poll(DISC_ROOM)
        self.assertEqual(0x3F, self.live.value)
        self.assertEqual(0x42, self.hold.declined_value)

    def test_walking_out_puts_phenacs_floor_back(self):
        self.poll(DISC_ROOM)
        self.poll(TOWN)
        self.assertEqual(0x41, self.live.value)
        self.assertFalse(self.hold.lowered)
        self.assertEqual(["music disc room", "music disc room"], [e.source for e in self.log.entries])

    def test_walking_out_after_a_pickup_still_holds_at_0x41(self):
        self.live.value = 0x42
        self.poll(DISC_ROOM)
        self.poll(TOWN)
        self.assertEqual(0x41, self.live.value)
        self.assertEqual(0x42, self.hold.declined_value, "waiting for the disc")

    def test_an_ordinary_first_visit_0x3f_is_never_raised(self):
        self.live.value = 0x3F
        self.poll(TOWN)
        self.poll(DISC_ROOM)
        self.assertEqual(0x3F, self.live.value)
        self.assertFalse(self.hold.lowered)

    def test_below_the_floor_in_the_room_is_left_alone(self):
        self.live.value = 0x3E
        self.poll(DISC_ROOM)
        self.assertEqual(0x3E, self.live.value)

    def test_past_the_band_is_left_alone(self):
        self.live.value = 0x44
        self.poll(DISC_ROOM)
        self.assertEqual(0x44, self.live.value)

    def test_realgam_is_not_phenac(self):
        self.poll(DISC_ROOM)
        self.poll(REALGAM)
        self.assertEqual(0x3F, self.live.value, "outside Phenac nothing runs; the town room puts it back")
        self.poll(TOWN)
        self.assertEqual(0x41, self.live.value)


class TestTheDiscArrives(_Base):
    def test_in_the_room_the_floor_comes_back_and_the_scene_can_run(self):
        self.poll(DISC_ROOM)
        self.hold.disc_held = True
        self.poll(DISC_ROOM)
        self.assertEqual(0x41, self.live.value)
        self.assertFalse(self.hold.lowered)

    def test_a_remembered_pickup_is_given_back(self):
        self.live.value = 0x42
        self.poll(DISC_ROOM)
        self.hold.disc_held = True
        self.poll(DISC_ROOM)
        self.assertEqual(0x42, self.live.value)
        self.assertEqual(1, self.hold.grants)

    def test_with_the_disc_the_room_is_never_lowered(self):
        self.hold.disc_held = True
        self.poll(DISC_ROOM)
        self.assertEqual(0x41, self.live.value)
        self.assertFalse(self.hold.lowered)


class TestTheClient(unittest.TestCase):
    def test_the_flag_survives_a_restart(self):
        self.assertIn('"music_disc_room_lowered": self.music_disc_hold.lowered,', CLIENT)
        self.assertIn('self.music_disc_hold.lowered = bool(slot_state.get("music_disc_room_lowered", False))', CLIENT)


if __name__ == "__main__":
    unittest.main()


# --- Catch Rate Scaling ----------------------------------------------------------------------------------------------
import json, os, pathlib, tempfile, zipfile   # noqa: E402

from . import PokemonXDTestBase   # noqa: E402
from ..game_data import trainer_placements   # noqa: E402
from ..tools import iso_patcher, xd_deck_format as df   # noqa: E402

DARK_DUMP = "/mnt/user-data/uploads/PokemonXD-working/bridge/dumps/deck_dark_1.bin"
STORY_DUMP = "/mnt/user-data/uploads/PokemonXD-working/bridge/dumps/deck_story_1.bin"
PATCHER = pathlib.Path(iso_patcher.__file__).read_text(encoding="utf-8")


class TestTheArithmetic(unittest.TestCase):
    def test_the_curve(self):
        """ADDENDUM 442: a boost toward 255 that fades along the seed's area order."""
        self.assertEqual(255, iso_patcher.scaled_catch_rate(3, 30, 0), "the first areas: the highest rate")
        self.assertEqual(3 + round(252 * 0.3), iso_patcher.scaled_catch_rate(3, 30, 1000),
                         "the last: this percentage of the way -- a Regirock-style 3 becomes 79, not near-impossible")
        self.assertEqual(3 + round(252 * 0.65), iso_patcher.scaled_catch_rate(3, 30, 500))
        self.assertEqual(255, iso_patcher.scaled_catch_rate(45, 100, 1000), "100 is the highest rate everywhere")
        self.assertEqual(45, iso_patcher.scaled_catch_rate(45, 0, 1000), "never below vanilla")
        self.assertEqual(255, iso_patcher.scaled_catch_rate(255, 30, 1000))
        rates = [iso_patcher.scaled_catch_rate(45, 30, p) for p in range(0, 1001, 100)]
        self.assertEqual(sorted(rates, reverse=True), rates, "later is never easier")

    def test_earliest_holder_decides(self):
        teams = {10: [5], 40: [5, 6], 90: [7]}
        self.assertEqual({5: 100, 6: 400}, iso_patcher.ddpk_progress_from_holders(teams, {10: 100, 40: 400}))

    def test_only_in_use_records_and_only_the_rate(self):
        buf = bytearray(0x20 + 4 * 0x18)
        for i in range(len(buf)):
            buf[i] = (i * 5) & 0xFF
        for index, (in_use, rate) in enumerate([(0, 0), (1, 200), (0, 100), (1, 100)]):
            buf[0x20 + index * 0x18 + 0x01] = rate
            buf[0x20 + index * 0x18 + 0x03] = in_use

        class _F:
            ddpk_entries, ddpk_data = 4, 0x20
        out, (changed, in_use) = iso_patcher.apply_shadow_catch_scaling(bytes(buf), _F(), 50, {1: 1000, 2: 1000})
        self.assertEqual((1, 2), (changed, in_use))
        self.assertEqual(228, out[0x20 + 0x18 + 0x01], "200 + half of the 55 gap")
        self.assertEqual(100, out[0x20 + 3 * 0x18 + 0x01], "no holder known -- left alone")
        self.assertEqual(100, out[0x20 + 2 * 0x18 + 0x01], "a free record is never touched")
        changed = {i for i, (a, b) in enumerate(zip(buf, out)) if a != b}
        self.assertEqual({0x20 + 0x18 + 0x01}, changed)


class TestThePatcher(unittest.TestCase):
    def test_before_max_catch_rate_and_after_every_shadow_pass(self):
        call = PATCHER.index("scaled = write_shadow_catch_scaling_patch(output_path, catch_rate_scaling, catch_progress)")
        self.assertLess(call, PATCHER.index("catch_shadow = write_max_catch_rate_shadow_patch(output_path"))
        self.assertLess(PATCHER.index("shadow_result = write_shadow_multi_trainer_patch(output_path"), call)
        self.assertLess(PATCHER.index("ed_result = write_enhanced_difficulty_patch(output_path"), call)

    def test_all_three_copies_and_holders_off_the_patched_deck(self):
        body = PATCHER[PATCHER.index("def write_shadow_catch_scaling_patch"):PATCHER.index("def write_heart_gauge_rate_patch")]
        self.assertEqual(3, body.count("apply_shadow_catch_scaling("))
        self.assertIn('deck_entries["DeckData_Story.bin"]', body)

    @unittest.skipUnless(os.path.exists(DARK_DUMP) and os.path.exists(STORY_DUMP), "needs the deck dumps")
    def test_against_the_real_decks(self):
        deck = df.DeckFile(df.lzss_decode(open(STORY_DUMP, "rb").read()))
        teams = {t["index"]: [m["ddpk_index"] for m in t["team"] if m["kind"] == "DDPK"] for t in deck.all_trainers()}
        progress = iso_patcher.ddpk_progress_from_holders(teams, {i: min(1000, i * 4) for i in teams})
        dark = df.lzss_decode(open(DARK_DUMP, "rb").read())
        ddpk = df.DarkPokemonFile(dark)
        out, (changed, in_use) = iso_patcher.apply_shadow_catch_scaling(dark, ddpk, 60, progress)
        self.assertGreater(changed, 40)
        after = df.DarkPokemonFile(out)
        for index in range(1, ddpk.ddpk_entries):
            before, now = ddpk.ddpk_full(index), after.ddpk_full(index)
            self.assertGreaterEqual(now["catch_rate_override"], before["catch_rate_override"])
            self.assertEqual({k: v for k, v in before.items() if k != "catch_rate_override"},
                             {k: v for k, v in now.items() if k != "catch_rate_override"})


def _seed(world) -> dict:
    world.pre_output()
    with tempfile.TemporaryDirectory() as tmp:
        world.generate_output(tmp)
        with zipfile.ZipFile(next(pathlib.Path(tmp).glob("*.appxd"))) as zf:
            return json.loads(zf.read("seed.json"))


class _ScalingWorld(PokemonXDTestBase):
    def _progress(self):
        seed = _seed(self.multiworld.worlds[self.player])
        self.assertEqual(30, seed["catch_rate_scaling"])   # ADDENDUM 448: the world's own percentage
        return {int(k): v for k, v in seed["catch_rate_progress_by_trainer"].items()}

    def _check(self, progress):
        self.assertTrue(progress)
        self.assertTrue(all(0 <= v <= 1000 for v in progress.values()))
        self.assertEqual(1000, max(progress.values()))
        self.assertEqual(0, min(progress.values()))
        citadark = [v for i, v in progress.items() if trainer_placements.region_for(i) == "Citadark Isle"]
        self.assertTrue(citadark)


class TestVanillaTravel(_ScalingWorld):
    options = {"catch_rate_scaling": "location_scaled", "randomize_travel_locations": False, "path_level_scaling": False}

    def test_the_story_order(self):
        progress = self._progress()
        self._check(progress)
        by_region = {}
        for i, v in progress.items():
            by_region.setdefault(trainer_placements.region_for(i), set()).add(v)
        self.assertLess(max(by_region["Phenac City"]), min(by_region["Citadark Isle"]))
        self.assertLess(max(by_region["Cipher Lab"]), min(by_region["Phenac City"]))


class TestLocationShuffle(_ScalingWorld):
    options = {"catch_rate_scaling": "location_scaled", "randomize_travel_locations": True}

    def test_this_seeds_order(self):
        self._check(self._progress())


class TestOffByDefault(PokemonXDTestBase):
    def test_nothing_travels(self):
        seed = _seed(self.multiworld.worlds[self.player])
        self.assertEqual(0, seed["catch_rate_scaling"])
        self.assertFalse(seed.get("catch_rate_progress_by_trainer"))
