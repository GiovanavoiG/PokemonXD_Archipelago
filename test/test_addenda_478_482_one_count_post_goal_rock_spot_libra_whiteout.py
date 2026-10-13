"""ADDENDA 478-482 (2026-10-13).

478 -- one count per purified Pokemon, ever; the fixes only fill holes.
479 -- no checks on Shadows that are only reachable after the goal.
480 -- the Poke Spots enter at the news point (0x37) and a watcher repairs a byte that falls below it.
481 -- SS Libra needs only the Phenac unlock (and the Scooter Upgrade when shuffled), not Phenac cleared.
482 -- a Death Link received outside battle whites the player out on the overworld.
"""
from __future__ import annotations

import random
import unittest
from unittest import mock

from .. import ram_client as rc

TID = 0x12345678
QUILAVA, TYPHLOSION, CYNDAQUIL = 156, 157, 155


def _rec(slot, dex, shadow_id, purified=True, source="box"):
    return rc.ShadowRecord(source, slot, dex, shadow_id, rc.PURIFIED_FLAG_VALUE if purified else 0, level=40,
                           trainer_id=TID, pid=0x1000 + shadow_id if shadow_id else 0x9000 + slot, cur_hp=50,
                           max_hp=50)


def _scan(t, records, owned=(), shadow_dex=(QUILAVA, TYPHLOSION, CYNDAQUIL), **kw):
    # An ordinary party member: the save's own trainer id, which rule 2 needs before it will infer anything.
    records = list(records) + [rc.ShadowRecord("party", 5, 263, 0, 0, level=10, trainer_id=TID, pid=0xABCD,
                                               cur_hp=20, max_hp=20)]
    out = []
    for _ in range(rc.PURIFICATION_SCAN_CONFIRM_SCANS):
        out += t.observe_records(list(records), seed_shadow_dex=set(shadow_dex), trusted_owned_dex=set(owned), **kw)
    return out


# --- 478 ------------------------------------------------------------------------------------------------------

class TestFamilies(unittest.TestCase):
    def test_a_line_is_one_family(self) -> None:
        self.assertEqual(rc.evolution_family(QUILAVA), rc.evolution_family(TYPHLOSION))
        self.assertEqual(CYNDAQUIL, rc.evolution_family(TYPHLOSION))
        self.assertEqual(rc.evolution_family(133), rc.evolution_family(197), "Eevee's branches")
        self.assertEqual(rc.evolution_family(172), rc.evolution_family(26), "Pichu -> Raichu")
        self.assertNotEqual(rc.evolution_family(1), rc.evolution_family(4))
        self.assertEqual(9999, rc.evolution_family(9999))


class TestOneCountPerPokemon(unittest.TestCase):
    def test_infernos_pair_counts_twice_not_three_times(self) -> None:
        t = rc.PurificationCountTracker()
        self.assertEqual(1, len(_scan(t, [_rec(0, TYPHLOSION, 10)])))           # the Quilava, already evolved
        self.assertEqual(1, len(_scan(t, [_rec(0, TYPHLOSION, 10), _rec(1, TYPHLOSION, 44)])))
        for _ in range(5):
            self.assertEqual([], _scan(t, [_rec(0, TYPHLOSION, 10), _rec(1, TYPHLOSION, 44)]))
        self.assertEqual(2, t.total_purified)
        self.assertEqual(0, t.caught_up, "nothing to repair: each id counted itself")

    def test_an_id_less_record_of_a_counted_family_is_not_counted_again(self) -> None:
        t = rc.PurificationCountTracker()
        _scan(t, [_rec(0, QUILAVA, 10)])
        self.assertEqual([], _scan(t, [_rec(5, TYPHLOSION, 0, purified=False)], owned={TYPHLOSION}))
        self.assertEqual(1, t.total_purified)

    def test_a_count_made_without_an_id_is_claimed_by_it_later(self) -> None:
        t = rc.PurificationCountTracker()
        self.assertEqual(1, len(_scan(t, [_rec(5, QUILAVA, 0, purified=False)], owned={QUILAVA})))
        self.assertEqual([CYNDAQUIL], t.species_only_families)
        self.assertEqual([], _scan(t, [_rec(0, TYPHLOSION, 10)]), "the same Pokemon, evolved, with its id")
        self.assertEqual(1, t.total_purified)
        self.assertEqual(1, t.claimed_species_only)
        self.assertEqual([], t.species_only_families)

    def test_a_flip_without_a_purified_record_counts_nothing(self) -> None:
        t = rc.PurificationCountTracker()
        for record in (None, _rec(0, QUILAVA, 0, purified=False), _rec(0, QUILAVA, 10, purified=False)):
            with mock.patch.object(rc.NamedPurificationTracker, "poll", return_value=[(QUILAVA, 0)]), \
                    mock.patch.object(rc, "_read_shadow_record", return_value=record):
                self.assertEqual([], t.poll(0x80400000))
        self.assertEqual(3, t.flip_deferred)
        self.assertEqual(0, t.total_purified)

    def test_flip_and_scan_agree_on_one_pokemon(self) -> None:
        t = rc.PurificationCountTracker()
        with mock.patch.object(rc.NamedPurificationTracker, "poll", return_value=[(999, 0)]), \
                mock.patch.object(rc, "_read_shadow_record", return_value=_rec(0, QUILAVA, 10, source="party")):
            self.assertEqual(1, len(t.poll(0x80400000)))
            self.assertEqual([], t.poll(0x80400000))
        self.assertEqual([], _scan(t, [_rec(3, TYPHLOSION, 10)]))
        self.assertEqual(1, t.total_purified)

    def test_the_ledger_round_trips(self) -> None:
        t = rc.PurificationCountTracker()
        _scan(t, [_rec(5, QUILAVA, 0, purified=False)], owned={QUILAVA})
        back = rc.PurificationCountTracker()
        back.load_json(t.to_json())
        self.assertEqual([CYNDAQUIL], back.species_only_families)
        self.assertEqual(0, back.legacy_unclaimed)
        self.assertEqual([], _scan(back, [_rec(0, TYPHLOSION, 10)]))

    def test_an_older_state_gets_bounded_wildcards(self) -> None:
        t = rc.PurificationCountTracker()
        t.load_json({"total_purified": 3, "purified_species": [QUILAVA, 1, 4], "purified_shadow_ids": [7]})
        self.assertEqual(2, t.legacy_unclaimed)
        self.assertEqual([], _scan(t, [_rec(0, TYPHLOSION, 10)]), "Quilava's family was counted without an id")
        self.assertEqual(1, len(_scan(t, [_rec(0, TYPHLOSION, 10), _rec(1, 25, 11)])), "Pikachu's never was")
        self.assertEqual(4, t.total_purified)


class TestNeverMoreChecksThanPokemon(unittest.TestCase):
    """The property the player asked for, driven at random: N distinct purified Pokemon, seen in any order, by
    flip and scan, in party and box, before and after evolving, with and without their ids -- never more than N
    counts. And when each one is eventually seen by its id, exactly N."""

    LINES = [(1, 2, 3), (4, 5, 6), (7, 8, 9), (155, 156, 157), (152, 153, 154), (92, 93, 94), (147, 148, 149)]

    def test_random_histories(self) -> None:
        rng = random.Random(478)
        for trial in range(300):
            t = rc.PurificationCountTracker()
            if rng.random() < 0.3:
                t.load_json(t.to_json())
            pokemon = []
            for shadow_id in range(1, rng.randint(2, 9)):
                line = rng.choice(self.LINES)
                pokemon.append([shadow_id, list(line[rng.randrange(len(line) - 1):])])   # species now, later
            shadow_dex = {s for line in self.LINES for s in line}
            for _ in range(40):
                p = rng.choice(pokemon)
                if rng.random() < 0.2 and len(p[1]) > 1:
                    p[1].pop(0)                                                       # it evolves
                dex = p[1][0]
                roll = rng.random()
                if roll < 0.3:
                    with mock.patch.object(rc.NamedPurificationTracker, "poll",
                                           return_value=[(rng.choice(list(shadow_dex)), 0)]), \
                            mock.patch.object(rc, "_read_shadow_record",
                                              return_value=_rec(0, dex, p[0], source="party")
                                              if rng.random() < 0.7 else None):
                        t.poll(0x80400000)
                elif roll < 0.45:
                    _scan(t, [_rec(rng.randrange(30), dex, 0, purified=False)], owned=shadow_dex,
                          shadow_dex=shadow_dex)
                else:
                    _scan(t, [_rec(rng.randrange(30), dex, p[0])], shadow_dex=shadow_dex)
                self.assertLessEqual(t.total_purified, len(pokemon), trial)
                if rng.random() < 0.1:
                    t.load_json(t.to_json())
            for p in pokemon:
                _scan(t, [_rec(0, p[1][0], p[0])], shadow_dex=shadow_dex)
            self.assertLessEqual(t.total_purified, len(pokemon), trial)
            self.assertGreaterEqual(t.total_purified, len(pokemon) - sum(
                1 for line in self.LINES if sum(1 for p in pokemon if p[1][0] in line) > 1), trial)



# --- 479 ------------------------------------------------------------------------------------------------------

from . import PokemonXDTestBase  # noqa: E402
from .. import locations, species  # noqa: E402
from ..game_data import shadow_regions  # noqa: E402


class TestWhichShadowsArePostGoal(unittest.TestCase):
    def test_greevils_seven_and_the_dragonite(self) -> None:
        self.assertEqual(frozenset(range(73, 81)), shadow_regions.POST_GOAL_SHADOW_DDPKS)
        self.assertEqual(locations.POST_GOAL_VANILLA_SHADOW_COUNT, len(shadow_regions.POST_GOAL_SHADOW_DDPKS))
        for ddpk in range(73, 80):
            self.assertTrue(set(shadow_regions.shadow_carriers()[ddpk]) <= {199, 200})
        self.assertEqual(75, len(shadow_regions.shadow_regions_in_graph_order(include_post_goal=False)))
        self.assertEqual(83, len(shadow_regions.shadow_regions_in_graph_order()), "the census itself is unchanged")


class _PostGoal(PokemonXDTestBase):
    def _names(self):
        return {loc.name for loc in self.multiworld.get_locations(self.player)}


class TestNoChecksForThem(_PostGoal):
    options = {"shadow_pokemon_expansion": 0, "randomize_shadow_species": True}

    def test_no_purify_rung_past_the_pre_goal_shadows(self) -> None:
        names = self._names()
        self.assertIn(locations.purification_location_name(75), names)
        self.assertNotIn(locations.purification_location_name(76), names)
        self.assertEqual(75, self.multiworld.worlds[self.player]._purification_location_count)

    def test_no_catch_for_a_species_only_they_carry(self) -> None:
        world = self.multiworld.worlds[self.player]
        self.assertTrue(world._post_goal_only_dex, "Greevil's seven are species of their own")
        names = self._names()
        for dex in world._post_goal_only_dex:
            self.assertNotIn(species.location_name_for_species(dex), names, dex)
        for dex, ddpks in world._shadow_catch_ddpks.items():
            self.assertFalse(set(ddpks) & shadow_regions.POST_GOAL_SHADOW_DDPKS, dex)

    def test_the_trainers_keep_their_shadows(self) -> None:
        """Nothing is taken off Greevil -- only the checks go."""
        world = self.multiworld.worlds[self.player]
        self.assertEqual(frozenset(), frozenset(world._shadow_removal_trainers))
        entries = world._shadow_species_assignment["entries"]
        from ..game_data.shadow_regions import ddpk_for_dpkm
        on_greevil = [e for e in entries if ddpk_for_dpkm().get(e["dpkm_index"]) in range(73, 80)]
        self.assertEqual(7, len(on_greevil))


class TestMovedOffGreevilTheyKeepTheirChecks(_PostGoal):
    options = {"shadow_pokemon_expansion": 0, "remove_greevil_shadows": True}

    def test_seven_more_rungs(self) -> None:
        world = self.multiworld.worlds[self.player]
        self.assertEqual(82, world._purification_location_count, "only the Dragonite is still post-goal")
        self.assertLessEqual(len(world._post_goal_only_dex), 1)



class TestShuffledLugiaNeverLandsWithoutChecks(_PostGoal):
    options = {"shuffle_shadow_lugia": True, "randomize_shadow_species": True}

    def test_lugia_has_its_checks(self) -> None:
        world = self.multiworld.worlds[self.player]
        self.assertIn(249, world._shadow_catch_labels)
        self.assertNotIn(249, world._post_goal_only_dex)
        self.assertIn(species.location_name_for_species(249), self._names())

    def test_the_exclusion_holds_for_every_draw(self) -> None:
        from ..game_data import shadow_legendaries as sl
        from ..game_data.shadow_regions import ddpk_for_dpkm
        post_goal = frozenset(d for d, ddpk in ddpk_for_dpkm().items() if ddpk in shadow_regions.POST_GOAL_SHADOW_DDPKS)

        class _Mon:
            def __init__(self, index, species_id):
                self.index, self.species_id = index, species_id

        for seed in range(200):
            mons = [_Mon(d, 1000 + d) for d in ddpk_for_dpkm()]
            home = next(m for m in mons if ddpk_for_dpkm()[m.index] == 73)
            home.species_id = sl.LUGIA_SPECIES_INDEX
            with mock.patch.object(sl, "_shadow_mons", return_value=mons), \
                    mock.patch.object(sl, "vanilla_lugia_index", return_value=home.index):
                landed = sl.place_shadow_lugia(None, {}, random.Random(seed), randomized=True,
                                               exclude_indices=post_goal)
            self.assertNotIn(landed, post_goal)


# --- 480 ------------------------------------------------------------------------------------------------------

from ..game_data import story_bytes as sb  # noqa: E402


class TestTheRockSpotGuard(unittest.TestCase):
    def test_still_entered_at_the_news_point(self) -> None:
        self.assertEqual(0x37, sb.area_entry_floor("Poke Spots"))

    def test_the_broken_window_is_repaired(self) -> None:
        for byte in (0x35, 0x36):
            bump = sb.live_bump_for("Poke Spots", byte, travel_shuffle=True, scooter_shuffle=False)
            self.assertIsNotNone(bump, hex(byte))
            self.assertEqual(0x37, bump.becomes)

    def test_never_touches_progress_past_it(self) -> None:
        for byte in (0x37, 0x38, 0x3B, 0x50):
            self.assertIsNone(sb.live_bump_for("Poke Spots", byte, travel_shuffle=True, scooter_shuffle=False))
        self.assertIsNone(sb.live_bump_for("Pyrite Town", 0x35, travel_shuffle=True, scooter_shuffle=False),
                          "only while standing at a spot")
        self.assertIsNone(sb.live_bump_for("Poke Spots", 0x35, travel_shuffle=False, scooter_shuffle=True),
                          "vanilla travel: the story plays as written")

    def test_the_bumper_writes_it_and_the_mark_follows(self) -> None:
        writes = []
        bumper = rc.LiveStoryByteBumper()
        with mock.patch.object(rc, "poke_story_byte", side_effect=lambda base, value: writes.append(value)):
            result = bumper.poll(0x80400000, "Poke Spots", 0x35, travel_shuffle=True, scooter_shuffle=False)
            self.assertEqual(0x37, result[0])
            self.assertIsNone(bumper.poll(0x80400000, "Poke Spots", 0x37, travel_shuffle=True,
                                          scooter_shuffle=False))
            # Something puts it back below the news later on -- even all the way to 0x35: repaired again.
            self.assertEqual(0x37, bumper.poll(0x80400000, "Poke Spots", 0x35, travel_shuffle=True,
                                               scooter_shuffle=False)[0])
            # A write that never lands (read straight back at 0x35) is still not fought every tick.
            self.assertIsNone(bumper.poll(0x80400000, "Poke Spots", 0x35, travel_shuffle=True,
                                          scooter_shuffle=False))
        self.assertEqual([0x37, 0x37], writes)
        self.assertEqual(1, bumper.declined_write_failed)
        memory = rc.AreaStoryByteMemory()
        memory.highest_by_region = {"Poke Spots": 0x35}
        self.assertEqual(0x37, memory.target_for("Poke Spots"))



# --- 481 ------------------------------------------------------------------------------------------------------

class TestSSLibraBehindThePhenacUnlock(PokemonXDTestBase):
    options = {"randomize_travel_locations": True, "key_item_shuffle": True, "shuffle_scooter_upgrade": True}

    def _reach(self, region):
        return self.multiworld.state.can_reach(region, player=self.player)

    def test_the_unlock_and_the_scooter_and_nothing_else(self) -> None:
        from .. import items
        self.collect_by_name(["Travel Unlock - SS Libra", "Travel Unlock - Phenac City"])
        self.assertTrue(self._reach("Phenac City"))
        self.assertFalse(self._reach("Phenac City (Post-Sixes)"), "Phenac is not cleared")
        self.assertFalse(self._reach("SS Libra"), "the Scooter Upgrade is shuffled")
        self.collect_by_name([items.SCOOTER_ITEM_NAME])
        self.assertTrue(self._reach("SS Libra"))

    def test_not_without_phenac(self) -> None:
        from .. import items
        self.collect_by_name(["Travel Unlock - SS Libra", items.SCOOTER_ITEM_NAME])
        self.assertFalse(self._reach("SS Libra"))


if __name__ == "__main__":
    unittest.main()
