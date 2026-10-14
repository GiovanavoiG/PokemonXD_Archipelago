"""ADDENDUM 440 (2026-10-08) -- the Phenac invasion trainers, and Purification Rate.

Player (with Bulbapedia's Phenac "Invasion" table -- Quelor, Teslor, Nopel, Kalus): "Exclude all of these trainers,
mark them missable, send them when Phenac is done, do not give them shadows. Please add an option, similar to exp
scaling, that scales how much the shadow gauge decreases from things like battle/scent usage."
"""
from __future__ import annotations

import json
import os
import pathlib
import tempfile
import unittest
import zipfile

from BaseClasses import LocationProgressType

from . import PokemonXDTestBase
from ..game_data import missable_autosend as ma, missable_indices as mi, missable_trainers as mt
from ..game_data import trainer_roster as tr
from ..tools import iso_patcher, xd_deck_format as df

INVASION = {129: "QUELOR", 130: "TESLOR", 131: "NOPEL", 132: "KALUS", 133: "JUSTY"}   # 441: + Justy
DARK_DUMP = "/mnt/user-data/uploads/PokemonXD-working/bridge/dumps/deck_dark_1.bin"


class TestTheInvasionTrainers(unittest.TestCase):
    def test_the_rows(self) -> None:
        for index, name in INVASION.items():
            trainer = tr.TRAINERS_BY_INDEX[index]
            self.assertEqual(name, trainer["name"])
            self.assertEqual(1, trainer["total_with_name"])
        self.assertEqual(set(INVASION), set(mi.PHENAC_INVASION_INDICES))

    def test_missable_and_never_a_shadow_host(self) -> None:
        for index in INVASION:
            self.assertIn(index, mi.MISSABLE_TRAINER_INDICES)
            self.assertIn(index, mt.FILLER_ONLY_TRAINER_INDICES)
            self.assertIn(index, mt.shadow_expansion_excluded_trainer_indices())
            team = tr.TRAINERS_BY_INDEX[index]["team"]
            self.assertTrue(all(slot.get("kind") == "DPKM" for slot in team), "no vanilla Shadow either")

    def test_sent_when_snattle_falls(self) -> None:
        for index in INVASION:
            label = tr.trainer_label(tr.TRAINERS_BY_INDEX[index])
            self.assertEqual(ma.SNATTLE_DEFEATED, ma.AUTO_SEND_AT_STORY_BYTE[label], label)
            self.assertEqual((("Phenac City (Post-Sixes)", ma.SNATTLE_DEFEATED),), ma.AUTO_SEND_AREA_CAPS[label])


class TestInAWorld(PokemonXDTestBase):
    options = {"shuffle_trainer_defeats": True, "trainer_defeat_mode": 1, "shadow_pokemon_expansion": 44}

    def test_excluded(self) -> None:
        for index in INVASION:
            label = tr.trainer_label(tr.TRAINERS_BY_INDEX[index])
            location = self.multiworld.get_location(label, self.player)
            self.assertEqual(LocationProgressType.EXCLUDED, location.progress_type, label)

    def test_no_generated_shadow_lands_on_them(self) -> None:
        world = self.multiworld.worlds[self.player]
        hosts = {host for hosts in (world._shadow_catch_expansion_hosts or {}).values() for host in hosts}
        self.assertTrue(hosts, "the expansion placed something, so the fence was exercised")
        self.assertFalse(hosts & set(INVASION))


# --- Purification Rate ---------------------------------------------------------------------------------------

class _FakeDdpk:
    def __init__(self, entries: int, data_off: int = 0x20) -> None:
        self.ddpk_entries = entries
        self.ddpk_data = data_off


def _blob(records):
    buf = bytearray(0x20 + len(records) * 0x18)
    for i in range(len(buf)):
        buf[i] = (i * 7) & 0xFF
    for index, (in_use, gauge) in enumerate(records):
        off = 0x20 + index * 0x18
        buf[off + 0x03] = in_use
        buf[off + 0x08:off + 0x0A] = gauge.to_bytes(2, "big")
    return buf


class TestTheGaugeArithmetic(unittest.TestCase):
    def test_scaled(self) -> None:
        self.assertEqual(2000, iso_patcher.scaled_heart_gauge(2000, 100))
        self.assertEqual(1000, iso_patcher.scaled_heart_gauge(2000, 200))
        self.assertEqual(200, iso_patcher.scaled_heart_gauge(2000, 1000))
        self.assertEqual(1200, iso_patcher.scaled_heart_gauge(12000, 1000))
        self.assertEqual(667, iso_patcher.scaled_heart_gauge(2000, 300), "rounded up, never sooner")
        self.assertEqual(1, iso_patcher.scaled_heart_gauge(1, 1000))
        self.assertEqual(2000, iso_patcher.scaled_heart_gauge(2000, 50), "never slower than vanilla")

    def test_only_in_use_entries_and_only_the_gauge(self) -> None:
        records = [(0, 2000), (1, 2000), (0, 4000), (1, 12000)]
        blob = _blob(records)
        out, (scaled, in_use) = iso_patcher.apply_heart_gauge_rate(bytes(blob), _FakeDdpk(len(records)), 400)
        self.assertEqual((2, 2), (scaled, in_use))
        changed = [i for i, (a, b) in enumerate(zip(blob, out)) if a != b]
        allowed = {0x20 + 1 * 0x18 + 8, 0x20 + 1 * 0x18 + 9, 0x20 + 3 * 0x18 + 8, 0x20 + 3 * 0x18 + 9}
        self.assertLessEqual(set(changed), allowed)
        self.assertEqual(500, int.from_bytes(out[0x20 + 0x18 + 8:0x20 + 0x18 + 10], "big"))
        self.assertEqual(3000, int.from_bytes(out[0x20 + 3 * 0x18 + 8:0x20 + 3 * 0x18 + 10], "big"))
        self.assertEqual(4000, int.from_bytes(out[0x20 + 2 * 0x18 + 8:0x20 + 2 * 0x18 + 10], "big"), "free slot")

    def test_refuses_to_run_off_the_end(self) -> None:
        blob = _blob([(0, 0), (1, 2000)])
        with self.assertRaises(ValueError):
            iso_patcher.apply_heart_gauge_rate(bytes(blob), _FakeDdpk(5), 200)

    def test_the_gauges_are_no_longer_edited(self) -> None:
        """SUPERSEDED by ADDENDUM 450. Player: "Editing the shadow gauge is breaking it." The seed patch no longer
        calls the gauge writer; the reductions are scaled in main.dol instead (test_addendum_450)."""
        source = (pathlib.Path(iso_patcher.__file__)).read_text(encoding="utf-8")
        self.assertNotIn("gauge = write_heart_gauge_rate_patch(output_path, purification_rate)", source)
        self.assertIn("purification_rate_patch.dol_patch_words(purification_rate)", source)


@unittest.skipUnless(os.path.exists(DARK_DUMP), "no real DeckData_DarkPokemon dump in this workspace")
class TestAgainstTheRealFile(unittest.TestCase):
    def test_every_vanilla_gauge(self) -> None:
        with open(DARK_DUMP, "rb") as handle:
            decompressed = df.lzss_decode(handle.read())
        ddpk = df.DarkPokemonFile(decompressed)
        out, (scaled, in_use) = iso_patcher.apply_heart_gauge_rate(decompressed, ddpk, 250)
        after = df.DarkPokemonFile(out)
        self.assertEqual(in_use, scaled)
        self.assertGreater(in_use, 50)
        for index in range(1, ddpk.ddpk_entries):
            before = ddpk.ddpk_full(index)
            now = after.ddpk_full(index)
            if before["in_use"]:
                self.assertEqual(iso_patcher.scaled_heart_gauge(before["heart_gauge"], 250), now["heart_gauge"])
                self.assertEqual({k: v for k, v in before.items() if k != "heart_gauge"},
                                 {k: v for k, v in now.items() if k != "heart_gauge"})
            else:
                self.assertEqual(before, now)


class TestTheOption(PokemonXDTestBase):
    options = {"purification_rate": 300}

    def test_the_seed_carries_it(self) -> None:
        world = self.multiworld.worlds[self.player]
        world.pre_output()
        with tempfile.TemporaryDirectory() as tmp:
            world.generate_output(tmp)
            with zipfile.ZipFile(next(pathlib.Path(tmp).glob("*.appxd"))) as zf:
                seed = json.loads(zf.read("seed.json"))
        self.assertEqual(300, seed["purification_rate"])


class TestTheDefault(PokemonXDTestBase):
    def test_vanilla_by_default(self) -> None:
        self.assertEqual(100, int(self.multiworld.worlds[self.player].options.purification_rate.value))


if __name__ == "__main__":
    unittest.main()


# --- the Candy Box teaches every move it passes -------------------------------------------------------------------
from ..game_data import candy_box as CB   # noqa: E402

REAL_DOL = pathlib.Path("/mnt/user-data/uploads/PokemonXD-working/main_dol.bin")


def _dol_reader():
    import struct
    data = REAL_DOL.read_bytes()
    offs = struct.unpack(">18I", data[0:72]); addrs = struct.unpack(">18I", data[72:144])
    sizes = struct.unpack(">18I", data[144:216])

    def word(address):
        for o, b, z in zip(offs, addrs, sizes):
            if z and b <= address < b + z:
                return struct.unpack_from(">I", data, o + address - b)[0]
        raise KeyError(hex(address))
    return word


class TestTheLearnHooks(unittest.TestCase):
    def test_layout(self) -> None:
        self.assertEqual(CB.TABLE_OFFSET + 416, CB.LEARN_OFFSET, "right after the level table")
        self.assertLessEqual(CB.LEARN_END_OFFSET, CB.CAVE_SIZE)
        self.assertEqual(CB.LEARN_END_OFFSET - CB.LEARN_OFFSET, 4 * len(CB.learn_code()))
        self.assertEqual(0, CB.learn_code()[0], "the saved level starts empty")
        self.assertEqual(((CB.CAVE_ADDRESS, CB.LEARN_END_OFFSET, CB.CAVE_VANILLA_SHA1),), CB.vanilla_digests())

    def test_the_three_hooks(self) -> None:
        words = {a: (e, n) for a, e, n in CB.dol_patch_words()}
        self.assertEqual((CB.LVUP_STATUS_WORD, CB._b(CB.LVUP_STATUS_ADDRESS, CB.CAVE_ADDRESS + CB.LEARN_WRAP_OFFSET, True)),
                         words[CB.LVUP_STATUS_ADDRESS])
        self.assertEqual((CB.LEARN_LEVEL_WORD, CB._b(CB.LEARN_LEVEL_ADDRESS, CB.CAVE_ADDRESS + CB.LEARN_START_OFFSET, True)),
                         words[CB.LEARN_LEVEL_ADDRESS])
        self.assertEqual((CB.LEARN_LOOP_WORD, CB._b(CB.LEARN_LOOP_ADDRESS, CB.CAVE_ADDRESS + CB.LEARN_NEXT_OFFSET)),
                         words[CB.LEARN_LOOP_ADDRESS])

    def test_the_vanilla_words_decode_to_what_they_replace(self) -> None:
        self.assertEqual(CB._b(CB.LVUP_STATUS_ADDRESS, CB.GET_LVUP_STATUS, True), CB.LVUP_STATUS_WORD)
        self.assertEqual(CB._b(CB.LEARN_LEVEL_ADDRESS, 0x80146FA4, True), CB.LEARN_LEVEL_WORD)   # pokemonBiosGetLevel
        self.assertEqual(CB._bne(CB.LEARN_LOOP_ADDRESS, CB.LEARN_LOOP_BODY), CB.LEARN_LOOP_WORD)

    @unittest.skipUnless(REAL_DOL.is_file(), "needs the player's main.dol")
    def test_against_the_real_dol(self) -> None:
        word = _dol_reader()
        for address, expected, _new in CB.dol_patch_words():
            if expected is not None:
                self.assertEqual(expected, word(address), hex(address))
        # The loop the hooks bend: pokemonGetOboeWazaDataId(pkm, r28, &cursor) at +0x1F8, `mr r27,r3`, the
        # zero test, and the evolution check right after.
        self.assertEqual(CB._b(0x800A5B8C, 0x80140E34, True), word(0x800A5B8C))
        self.assertEqual(0x7F84E378, word(CB.LEARN_LOOP_CALL + 4), "mr r4,r28 -- the level is r28")
        self.assertEqual(0x38A10008, word(CB.LEARN_LOOP_CALL + 8), "the cursor is the byte at 8(r1)")
        self.assertEqual(0x80610014, word(CB.LEARN_LOOP_CALL), "the Pokemon is at 20(r1)")
        self.assertEqual(0x7C7C1B78, word(CB.LEARN_LEVEL_ADDRESS + 8), "mr r28,r3 after the level")
        self.assertEqual(0x88630011, word(0x80146FB4), "pokemonBiosGetLevel reads +0x11")

    def test_simulated_range(self) -> None:
        """Routine B's arithmetic, in Python: the first level is old + 1, never past the new one, and the game's
        own level when nothing was saved."""
        def first(old, new):
            return new if old == 0 else (old + 1 if old + 1 <= new else new)
        self.assertEqual(6, first(5, 100))
        self.assertEqual(6, first(5, 6), "a Rare Candy: exactly the vanilla level")
        self.assertEqual(100, first(0, 100))
