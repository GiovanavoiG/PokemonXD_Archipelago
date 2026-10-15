"""ADDENDA 473-475 (2026-10-12).

473 -- Miror B.'s Dragonite is after the goal; the Poke Spots are entered at 0x37 so the Rock spot's tray works.
474 -- SS Libra: the Scooter Upgrade is latched; SS Libra stays shut until Phenac is cleared; Phenac never banks the
       stranded ship's byte.
475 -- Death Link sends off the game's own white-out counter.
"""
from __future__ import annotations

import pathlib
import struct
import unittest
from types import SimpleNamespace
from unittest import mock

from BaseClasses import LocationProgressType

from . import PokemonXDTestBase
from .. import locations, ram_client as rc
from ..game_data import shadow_regions, story_bytes as sb, whiteout_counter as wc
from ..tools import iso_patcher as ip

ROOT = pathlib.Path(__file__).resolve().parent.parent
CLIENT = (ROOT / "Client.py").read_text(encoding="utf-8")
DOL = pathlib.Path("/mnt/user-data/uploads/PokemonXD-working/main_dol.bin")


# --- 473 ------------------------------------------------------------------------------------------------------

class TestDragoniteIsAfterTheGoal(unittest.TestCase):
    def test_every_way_to_it_needs_the_goal(self) -> None:
        gates = shadow_regions.gates_for_ddpk(80)
        self.assertTrue(gates)
        self.assertTrue(all(shadow_regions.POST_GOAL_EVENT_ITEM in g.required_items for g in gates))

    def test_no_other_shadow_does(self) -> None:
        for ddpk in range(1, 84):
            if ddpk in shadow_regions.POST_GOAL_SHADOW_DDPKS:
                continue
            for gate in shadow_regions.gates_for_ddpk(ddpk):
                self.assertNotIn(shadow_regions.POST_GOAL_EVENT_ITEM, gate.required_items, ddpk)


class TestTheLastPurificationIsFillerOnly(PokemonXDTestBase):
    options = {"shadow_pokemon_expansion": 0, "purification_progression_cap": 127}

    def test_purify_83_is_excluded_and_82_is_not(self) -> None:
        """RETARGETED BY ADDENDUM 479: the Dragonite's rung is gone, not filler-only -- 75 rungs, none excluded."""
        names = {loc.name for loc in self.multiworld.get_locations(self.player)}
        self.assertNotIn(locations.purification_location_name(76), names)
        last = self.multiworld.get_location(locations.purification_location_name(75), self.player)
        self.assertNotEqual(LocationProgressType.EXCLUDED, last.progress_type)

    def test_the_dragonites_catch_is_excluded(self) -> None:
        from .. import species
        world = self.multiworld.worlds[self.player]
        dexes = [dex for dex, ddpks in world._shadow_catch_ddpks.items() if 80 in ddpks]
        for dex in dexes:
            if all(d in shadow_regions.POST_GOAL_SHADOW_DDPKS for d in world._shadow_catch_ddpks[dex]):
                try:
                    location = self.multiworld.get_location(species.location_name_for_species(dex), self.player)
                except KeyError:
                    continue
                self.assertEqual(LocationProgressType.EXCLUDED, location.progress_type)


class TestThePokeSpotTray(unittest.TestCase):
    def test_the_spots_are_entered_after_the_duking_news(self) -> None:
        self.assertEqual(0x37, sb.area_entry_floor("Poke Spots"))
        self.assertEqual(0x35, sb.area_unlock_floor("Poke Spots"), "the unlock check is unchanged")
        self.assertEqual(440, sb.story_value_for_byte(0x37))
        lands = {t.before: t.what for t in sb.TRANSITIONS}
        self.assertIn("Poke Snacks placed", lands[0x37])

    def test_a_stuck_mark_is_lifted(self) -> None:
        memory = rc.AreaStoryByteMemory()
        memory.highest_by_region = {"Poke Spots": 0x35}
        self.assertEqual(0x37, memory.target_for("Poke Spots"))


# --- 474 ------------------------------------------------------------------------------------------------------

class TestPhenacNeverBanksTheShipsByte(unittest.TestCase):
    def test_the_kick_from_the_stranded_ship_is_not_phenacs_mark(self) -> None:
        memory = rc.AreaStoryByteMemory()
        self.assertFalse(memory.observe("Phenac City", 0x50))
        self.assertNotIn("Phenac City", memory.highest_by_region)
        self.assertEqual(1, memory.declined_landed_byte)
        self.assertTrue(memory.observe("Phenac City", 0x4E))

    def test_an_old_file_is_clamped(self) -> None:
        memory = rc.AreaStoryByteMemory()
        memory.load_json({"schema": rc.AREA_MEMORY_SCHEMA_VERSION, "highest_by_region": {"Phenac City": 0x50},
                          "visited": ["Phenac City"]})
        self.assertEqual(0x4E, memory.highest_by_region["Phenac City"])
        self.assertTrue(memory.dirty)


class TestTheScooterLatch(unittest.TestCase):
    def _ctx(self, received, seen=False):
        ctx = SimpleNamespace(shuffle_scooter_upgrade=True, items_received=received, scooter_upgrade_seen=seen)
        ctx._save_local_state = lambda: None
        return ctx

    def test_once_seen_it_stays_held(self) -> None:
        from .. import Client, items
        item_id = next(i for i, n in Client.ITEM_ID_TO_NAME.items() if n == items.SCOOTER_ITEM_NAME)
        ctx = self._ctx([SimpleNamespace(item=item_id)])
        self.assertTrue(Client.scooter_upgrade_held(ctx))
        self.assertTrue(ctx.scooter_upgrade_seen)
        ctx.items_received = []                     # a reconnect, before the server resends anything
        self.assertTrue(Client.scooter_upgrade_held(ctx))

    def test_persisted(self) -> None:
        self.assertIn('"scooter_upgrade_seen": bool(getattr(self, "scooter_upgrade_seen", False))', CLIENT)
        self.assertIn('self.scooter_upgrade_seen = bool(slot_state.get("scooter_upgrade_seen", False))', CLIENT)


class TestSSLibraWaitsForPhenac(unittest.TestCase):
    def _ctx(self, received=(), items=()):
        return SimpleNamespace(received_travel_locations=set(received), items_received=list(items))

    def test_held_closed_until_phenac_is_unlocked(self) -> None:
        """RETARGETED BY ADDENDUM 481: the Phenac unlock, not the Sixes."""
        from .. import Client
        item_id = next(i for i, n in Client.ITEM_ID_TO_NAME.items() if n == "Travel Unlock - Phenac City")
        self.assertTrue(Client._travel_held_closed(self._ctx(), "SS Libra"))
        self.assertTrue(Client._travel_held_closed(self._ctx({"SS Libra"}), "SS Libra"))
        self.assertFalse(Client._travel_held_closed(self._ctx({"Phenac City"}), "SS Libra"))
        self.assertFalse(Client._travel_held_closed(self._ctx(items=[SimpleNamespace(item=item_id)]), "SS Libra"))
        self.assertFalse(Client._travel_held_closed(self._ctx(), "Pyrite Town"))

    def test_wired_into_both_writers(self) -> None:
        body = CLIENT.split("async def sync_travel_locations", 1)[1].split("\nasync def ", 1)[0]
        self.assertEqual(2, body.count("_travel_held_closed(ctx,"))
        body = CLIENT.split("async def enforce_travel_locks", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("_travel_held_closed(ctx, name)", body)

    def test_logic_requires_the_town(self) -> None:
        from .. import travel_locations
        self.assertEqual(("Phenac City",), travel_locations.required_regions_for("SS Libra"))   # ADDENDUM 481


# --- 475 ------------------------------------------------------------------------------------------------------

class TestTheWhiteoutHook(unittest.TestCase):
    @unittest.skipUnless(DOL.is_file(), "needs a real main.dol")
    def test_vanilla_words_match_the_real_dol(self) -> None:
        from .test_addendum_465_shadow_engine import _word_reader
        word = _word_reader(DOL.read_bytes())
        for address, vanilla, new in wc.dol_patch_words():
            if address in wc.LEGACY_HOOK_WORDS:
                self.assertEqual(new, word(address), hex(address))   # ADDENDUM 484: restored, already vanilla
            else:
                self.assertEqual(vanilla, word(address), hex(address))

    def test_the_stub_tail_branches_into_recovery(self) -> None:
        """RETARGETED BY ADDENDUM 484: the stubs sit at the TOP of each white-out branch now -- count, redo the
        replaced `li r3`, return. The recovery call itself is vanilla again."""
        for (site, vanilla, immediate), stub in zip(wc.HOOK_SITES, wc.STUB_ADDRESSES):
            words = wc.stub_words(immediate)
            self.assertEqual(vanilla, words[4], "the replaced instruction is redone")
            self.assertEqual(0x4E800020, words[5])
            hook = wc.hook_words()[site]
            disp = hook & 0x03FFFFFC
            self.assertEqual(stub, site + (disp - 0x04000000 if disp & 0x02000000 else disp))
            self.assertEqual(1, hook & 1, "a call -- the stub returns to the next instruction")

    def test_patcher_wiring(self) -> None:
        body = pathlib.Path(ip.__file__).read_text(encoding="utf-8").split("def apply_patch(", 1)[1]
        self.assertIn('_whiteout.dol_patch_words()', body)


class _Ram:
    def __init__(self, hooked=True, counter=0, legacy=False):
        self.words = {site: (word if hooked and not legacy else wc.HOOK_VANILLA_WORDS[site])
                      for site, word in wc.hook_words().items()}
        self.words.update({site: (word if legacy else wc.LEGACY_HOOK_VANILLA_WORDS[site])
                           for site, word in wc.LEGACY_HOOK_WORDS.items()})
        self.words[wc.COUNTER_ADDRESS] = counter

    def read(self, address, length):
        return struct.pack(">I", self.words[address])


class TestTheCounterWatch(unittest.TestCase):
    def test_counts_only_increases(self) -> None:
        ram = _Ram(counter=3)
        watch = rc.WhiteoutCounterWatch()
        with mock.patch.object(rc, "read_bytes", side_effect=ram.read):
            self.assertEqual(0, watch.poll())          # first read is a baseline
            self.assertEqual(0, watch.poll())
            ram.words[wc.COUNTER_ADDRESS] = 4
            self.assertEqual(1, watch.poll())
            ram.words[wc.COUNTER_ADDRESS] = 0            # a reboot
            self.assertEqual(0, watch.poll())
            ram.words[wc.COUNTER_ADDRESS] = 1
            self.assertEqual(1, watch.poll())
        self.assertEqual(2, watch.seen)

    def test_an_iso_without_the_hook_says_none(self) -> None:
        with mock.patch.object(rc, "read_bytes", side_effect=_Ram(hooked=False).read):
            self.assertIsNone(rc.WhiteoutCounterWatch().poll())


class TestTheBridgeOnTheCounter(unittest.TestCase):
    def setUp(self) -> None:
        self.bridge = rc.DeathLinkBridge(enabled=True)
        p = mock.patch.object(rc, "party_is_wiped", return_value=False)
        p.start()
        self.addCleanup(p.stop)

    def test_a_white_out_sends_once(self) -> None:
        self.assertEqual((False, None), self.bridge.poll(0x80400000, None, whiteouts=0))
        sent, note = self.bridge.poll(0x80400000, None, whiteouts=1)
        self.assertTrue(sent)
        self.assertIn("own white-out", note)
        self.assertFalse(self.bridge.poll(0x80400000, None, whiteouts=0)[0])
        self.assertEqual(1, self.bridge.sends_by_game)

    def test_the_party_never_sends_in_counter_mode(self) -> None:
        with mock.patch.object(rc, "party_is_wiped", return_value=True):
            for _ in range(5):
                self.assertFalse(self.bridge.poll(0x80400000, True, whiteouts=0)[0])
        self.assertEqual(0, self.bridge.sends)

    def test_our_death_is_not_sent_back(self) -> None:
        self.bridge._ours = True
        with mock.patch.object(rc, "party_is_wiped", return_value=True):
            self.assertFalse(self.bridge.poll(0x80400000, None, whiteouts=0)[0])
            self.assertFalse(self.bridge.poll(0x80400000, None, whiteouts=1)[0])
        self.assertEqual(1, self.bridge.suppressed)
        self.assertFalse(self.bridge._ours)
        self.assertTrue(self.bridge.poll(0x80400000, None, whiteouts=1)[0], "the next one is the player's own")

    def test_a_healed_party_drops_the_fence(self) -> None:
        """RETARGETED BY ADDENDUM 484: two conscious polls in a row, not one."""
        self.bridge._ours = True
        self.bridge.poll(0x80400000, None, whiteouts=0)      # party reads conscious
        self.assertTrue(self.bridge._ours)
        self.bridge.poll(0x80400000, None, whiteouts=0)
        self.assertFalse(self.bridge._ours)

    def test_the_client_feeds_it(self) -> None:
        self.assertIn("whiteouts = ctx.whiteout_counter.poll()", CLIENT)
        self.assertIn("whiteouts=whiteouts)", CLIENT)


if __name__ == "__main__":
    unittest.main()
