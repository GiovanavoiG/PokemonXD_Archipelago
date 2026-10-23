"""ADDENDUM 483 (2026-10-13) -- the GitHub issues (palex00, filed against 1bb3728).

#1  the Mt. Battle goal is in generation logic.
#2  cumulative "Defeat N Trainers" counts each unmissable trainer once; thresholds past that are filler-only.
#3  (already fixed by ADDENDUM 470 -- pre_fill no longer touches the itempool.)
#4  "Krane Memos"/"Voice Cases" groups replaced by "Key Items".
#5  the Master Ball is useful, still exactly one per seed; the placeholder rule is gone.
#6  the Snag Machine needs no Machine Part -- the game gives it without one. Shadow catches
    and the purification ladder are not behind it (vanilla travel still gates Agate Village, so purifying, on it).
#7  client messages name client commands with `/`.
#8  the debug catch command is `/catchscan`, so `/catches` no longer replaces it.
#9  world_version 0.1.4, no compatible_version in the source manifest.
#10 option texts and the game page.
#11 web_world points at this repository.
#12 a .gitignore for compiled Python.
#13 the region sphere walk is shared across Pokemon XD slots and stops early -- same answers.
#14 test_addendum_301 builds its path with os.path.
"""
from __future__ import annotations

import json
import pathlib
import re
import unittest
from collections import Counter

from BaseClasses import CollectionState, ItemClassification, LocationProgressType

from . import PokemonXDTestBase
from .. import items, locations, rules, species

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _state_without(test, drop):
    state = CollectionState(test.multiworld)
    for item in test.multiworld.itempool:
        if item.player == test.player and item.name not in drop and item.advancement:
            state.collect(item, True)
    return state


# --- #1 -------------------------------------------------------------------------------------------------------

class TestMtBattleGoalTravelShuffle(PokemonXDTestBase):
    options = {"goal": "win_mt_battle", "randomize_travel_locations": True}

    def test_the_goal_needs_mt_battle(self) -> None:
        state = _state_without(self, {"Travel Unlock - Mt. Battle"})
        self.assertFalse(state.can_reach_region("Mt. Battle", self.player))
        self.assertFalse(self.multiworld.can_beat_game(state), "the issue's repro")
        state.collect(self.get_item_by_name("Travel Unlock - Mt. Battle"), True)
        self.assertTrue(self.multiworld.can_beat_game(state))

    def test_the_event_sits_on_mt_battle(self) -> None:
        event = self.multiworld.get_location(locations.MT_BATTLE_EVENT_LOCATION_NAME, self.player)
        self.assertEqual("Mt. Battle", event.parent_region.name)
        self.assertEqual("Victory", event.item.name)
        names = {loc.name for loc in self.multiworld.get_locations(self.player)}
        self.assertNotIn(locations.EVENT_LOCATION_NAME, names)


class TestMtBattleGoalVanilla(PokemonXDTestBase):
    options = {"goal": "win_mt_battle", "randomize_travel_locations": False, "key_item_shuffle": True}

    def test_the_goal_needs_the_machine_part_and_not_citadark(self) -> None:
        self.assertFalse(self.multiworld.can_beat_game(_state_without(self, {"Machine Part"})))
        parts = _state_without(self, {items.MACGUFFIN_ITEM_NAME, "System Lever"})
        self.assertTrue(self.multiworld.can_beat_game(parts), "Citadark Isle is not the goal any more")


class TestDefaultGoalUnchanged(PokemonXDTestBase):
    def test_the_event_stays_at_citadark(self) -> None:
        event = self.multiworld.get_location(locations.EVENT_LOCATION_NAME, self.player)
        self.assertEqual("Citadark Isle", event.parent_region.name)


# --- #2 -------------------------------------------------------------------------------------------------------

class TestCumulativeTrainerTally(PokemonXDTestBase):
    options = {"shuffle_trainer_defeats": True, "trainer_defeat_mode": "cumulative",
               "trainer_defeat_check_count": 114}

    def test_only_unmissable_trainers_count_once_each(self) -> None:
        from ..game_data import missable_trainers as mt, trainer_placements as tp, trainer_roster as tr
        groups = rules._trainer_count_groups(self.multiworld.worlds[self.player])
        countable = sum(many for _ways, many in groups)
        names = {str(tr.TRAINERS_BY_INDEX[i]["name"]).upper() for i, p in tp.PLACEMENTS.items()
                 if p.region is not None and i not in mt.MISSABLE_TRAINER_INDICES
                 and i not in mt.POST_GOAL_TRAINER_INDICES}
        self.assertEqual(len(names), countable)
        self.assertLess(countable, len(tp.PLACEMENTS), "the issue: all 232 rows used to count")
        for ways, _many in groups:
            for regions_needed, _items in ways:
                self.assertNotIn(None, regions_needed)

    def test_thresholds_past_the_honest_count_are_filler_only(self) -> None:
        countable = sum(many for _ways, many in rules._trainer_count_groups(self.multiworld.worlds[self.player]))
        locs = {int(loc.name.split()[1]): loc for loc in self.multiworld.get_locations(self.player)
                if re.fullmatch(r"Defeat \d+ Trainers", loc.name)}
        self.assertEqual(114, len(locs))
        for count, loc in locs.items():
            expected = LocationProgressType.EXCLUDED if count > countable else LocationProgressType.DEFAULT
            self.assertEqual(expected, loc.progress_type, count)


# --- #4 / #5 / #8 / #9 / #11 / #12 / #14 ------------------------------------------------------------------------

class TestSmallFixes(PokemonXDTestBase):
    def test_key_items_group(self) -> None:
        from .. import PokemonXDWorld
        groups = PokemonXDWorld.item_name_groups
        self.assertNotIn("Krane Memos", groups)
        self.assertNotIn("Voice Cases", groups)
        self.assertEqual(set(items.GATING_KEY_ITEM_NAMES), groups["Key Items"])
        self.assertIn("Machine Part", groups["Key Items"])

    def test_one_useful_master_ball(self) -> None:
        balls = [i for i in self.multiworld.itempool if i.player == self.player and i.name == "Master Ball"]
        self.assertEqual(1, len(balls))
        self.assertEqual(ItemClassification.useful, balls[0].classification)
        self.assertNotIn("Colosseum Clear Reward", (ROOT / "rules.py").read_text(encoding="utf-8"))

    def test_catches_is_defined_once(self) -> None:
        client = (ROOT / "Client.py").read_text(encoding="utf-8")
        self.assertEqual(1, client.count("def _cmd_catches("))
        self.assertEqual(1, client.count("def _cmd_catchscan("))

    def test_manifest(self) -> None:
        manifest = json.loads((ROOT / "archipelago.json").read_text(encoding="utf-8"))
        self.assertEqual("0.1.6", manifest["world_version"])
        self.assertNotIn("compatible_version", manifest)

    def test_web_world(self) -> None:
        text = (ROOT / "web_world.py").read_text(encoding="utf-8")
        self.assertIn("https://github.com/GiovanavoiG/PokemonXD_Archipelago/issues", text)
        self.assertNotIn("Your Name Here", text)

    def test_gitignore(self) -> None:
        text = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("__pycache__/", text)

    def test_301_builds_its_path_portably(self) -> None:
        text = (ROOT / "test" / "test_addendum_301_aferd_any_is_filler_only.py").read_text(encoding="utf-8")
        self.assertNotIn('replace("game_data/repeatable_trainers.py"', text)


# --- #6 -------------------------------------------------------------------------------------------------------

class TestSnagMachineNeedsNoMachinePart(PokemonXDTestBase):
    options = {"randomize_travel_locations": True, "key_item_shuffle": True}

    def test_shadow_catches_and_purifications_do_not_need_it(self) -> None:
        world = self.multiworld.worlds[self.player]
        gates, _ = rules._catch_gates_for_species(world)
        shadow = {species.location_name_for_species(d) for d, g in gates.items() if g and "pokespot" not in g}
        state = _state_without(self, {"Machine Part"})
        catches = [loc for loc in self.multiworld.get_locations(self.player) if loc.name in shadow]
        self.assertTrue(catches)
        self.assertTrue(all(loc.can_reach(state) for loc in catches))
        purify = [loc for loc in self.multiworld.get_locations(self.player) if loc.name.startswith("Purify ")]
        self.assertTrue(all(loc.can_reach(state) for loc in purify))
        self.assertFalse(hasattr(rules, "_has_snag_machine"))


class TestVanillaPurifyStillBehindTheMachinePart(PokemonXDTestBase):
    options = {"randomize_travel_locations": False, "key_item_shuffle": True}

    def test_through_agate(self) -> None:
        state = _state_without(self, {"Machine Part"})
        self.assertFalse(state.can_reach_region("Agate Village", self.player))
        purify = [loc for loc in self.multiworld.get_locations(self.player) if loc.name.startswith("Purify ")]
        self.assertFalse(any(loc.can_reach(state) for loc in purify))


# --- #7 -------------------------------------------------------------------------------------------------------

class TestClientCommandsUseSlash(unittest.TestCase):
    def test_no_client_command_is_named_with_bang(self) -> None:
        client = (ROOT / "Client.py").read_text(encoding="utf-8")
        commands = sorted(set(re.findall(r"def _cmd_(\w+)\(", client)), key=len, reverse=True)
        pattern = re.compile(r"(?<![\w!])!(" + "|".join(commands) + r")\b")
        offenders = []
        for path in ROOT.rglob("*.py"):
            if "test" in path.parts or path.name == "items.py":   # items.py names the SERVER's !getitem / !hint
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if pattern.search(line):
                    offenders.append(f"{path.name}:{number}")
        self.assertEqual([], offenders)


# --- #10 ------------------------------------------------------------------------------------------------------

class TestTexts(unittest.TestCase):
    def test_options(self) -> None:
        text = (ROOT / "options.py").read_text(encoding="utf-8")
        self.assertNotIn("generation fails if it is", text)
        self.assertNotIn("Shuffle Trainer Movesets", text)

    def test_game_page(self) -> None:
        text = (ROOT / "docs" / "en_Pokemon XD Gale of Darkness.md").read_text(encoding="utf-8")
        self.assertNotIn("Shadow Pokemon defeats", text)
        self.assertNotIn("1-386", text)
        self.assertIn("Mt. Battle", text)


# --- #13 ------------------------------------------------------------------------------------------------------

def _old_region_spheres(multiworld, player, wanted):
    """The pre-483 walk, verbatim in effect: the whole sweep, for one player."""
    state = CollectionState(multiworld)
    remaining = set(multiworld.get_filled_locations())
    first = {}
    index = 0
    while True:
        for region in wanted:
            if region not in first and state.can_reach_region(region, player):
                first[region] = index
        sphere = {location for location in remaining if location.can_reach(state)}
        if not sphere:
            break
        remaining -= sphere
        for location in sphere:
            state.collect(location.item, True)
        index += 1
    return first


class TestTheSharedSphereWalk(unittest.TestCase):
    def test_same_answers_for_two_slots(self) -> None:
        from Fill import distribute_items_restrictive
        from test.general import gen_steps, setup_multiworld
        from worlds.AutoWorld import AutoWorldRegister

        from ..randomizer.path_level_scaling import region_by_trainer_index

        world_type = AutoWorldRegister.world_types["Pokemon XD Gale of Darkness"]
        for seed, opts in ((4831, {"randomize_travel_locations": True}), (4832, {})):
            multiworld = setup_multiworld([world_type, world_type], gen_steps, seed=seed, options=opts)
            distribute_items_restrictive(multiworld)
            wanted = set(region_by_trainer_index().values())
            for player in (1, 2):
                expected = _old_region_spheres(multiworld, player, wanted)
                got = multiworld.worlds[player]._region_spheres(wanted)
                self.assertEqual(expected, got, (seed, player))
            self.assertTrue(hasattr(multiworld, "_pokemon_xd_region_spheres"), "computed once, shared")


if __name__ == "__main__":
    unittest.main()
