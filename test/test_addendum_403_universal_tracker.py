"""ADDENDUM 403 (2026-10-02) -- Universal Tracker regenerates this world exactly.

This world is compatible with Universal Tracker, whose documentation is in
https://github.com/FarisTheAncient/Archipelago.

HOW UT WORKS. It never sees the seed. It regenerates the world on the player's machine -- generate_early through
generate_basic, no fill -- and asks which locations are in logic for the items the server says they hold. The
compliance bar is `worlds.tracker.fuzzer_hook.Hook`: for every sendable sphere of a real seed, UT's in-logic set
must equal the server's EXACTLY.

WHAT BROKE IT. This world rolls with its own RNG -- the Shadow species shuffle, which species are obtainable and so
which `Catch -` checks exist and how each is gated, the expansion, the team shuffle, the Poke Spot pool. UT rolled
all of it again with a different seed. Measured before this change, three default seeds through the real UT core:
44, 47 and 65 `Catch -` checks tracked wrong at sphere 2.

THE FIX IS ONE NUMBER. `generate_early` re-seeds `self.random` from a single recorded value FIRST, before any
option is read or any draw made, and puts that value and the world's options in slot data. Inside UT it restores
both instead, so every later draw replays. Nothing else crosses over, so there is no second copy of any decision
to keep in step. It is sound because every randomizer here takes the world's RNG as an argument -- none use the
global `random` or the multiworld's -- and the last class in this file keeps it that way.

THE HARNESS (`ut_check/` beside the apworld, not shipped): a real generation in one process, the real `TrackerCore`
regenerating from slot data alone in another with a DIFFERENT `PYTHONHASHSEED`, compared sphere by sphere the way
the fuzzer hook does. The separate hash seed is deliberate: iterating a set of strings before a random draw would
replay in-process and diverge between machines, and only a second process can see that.
"""
from __future__ import annotations

import inspect
import json
import random
import re
import unittest
from argparse import Namespace
from pathlib import Path

from BaseClasses import CollectionState, MultiWorld
from worlds.AutoWorld import call_all

from .. import PokemonXDWorld, UT_SEED_BITS, UT_SLOT_DATA_FORMAT, UT_SLOT_DATA_KEY, ut_option_names
from ..options import PokemonXDOptions

HERE = Path(__file__).resolve().parent.parent
STEPS = ("generate_early", "create_regions", "create_items", "set_rules", "connect_entrances", "generate_basic")


def _build(seed: int, options: dict, passthrough: "dict | None" = None) -> MultiWorld:
    """`test.general.setup_multiworld`, plus the one thing it cannot do: set `re_gen_passthrough` before the
    first step, which is when UT sets it."""
    mw = MultiWorld(1)
    mw.game = {1: PokemonXDWorld.game}
    mw.player_name = {1: "Tester1"}
    mw.set_seed(seed)
    if passthrough is not None:
        mw.generation_is_fake = True
        mw.re_gen_passthrough = {PokemonXDWorld.game: passthrough}
    args = Namespace()
    for key, option in PokemonXDWorld.options_dataclass.type_hints.items():
        setattr(args, key, {1: option.from_any(options.get(key, option.default))})
    mw.set_options(args)
    mw.state = CollectionState(mw)
    for step in STEPS:
        call_all(mw, step)
    return mw


def _fingerprint(mw: MultiWorld) -> dict:
    """Everything UT's answer depends on: which locations exist, and whether each is reachable from a fixed set of
    states. Rules are compared by their verdicts, because two closures cannot be compared any other way."""
    world = mw.worlds[1]
    locations = sorted(world.get_locations(), key=lambda l: l.name)
    states = []
    empty = CollectionState(mw)
    states.append(empty)
    full = CollectionState(mw)
    for item in mw.itempool:
        full.collect(item, prevent_sweep=True)
    full.sweep_for_advancements()
    states.append(full)
    # A partial state too: half the progression, in a fixed order. Empty and full alone would pass a world whose
    # rules differ only in which middle sphere a check lands in -- which is exactly where the Catch gates live.
    half = CollectionState(mw)
    progression = sorted((i for i in mw.itempool if i.advancement), key=lambda i: i.name)
    for item in progression[: len(progression) // 2]:
        half.collect(item, prevent_sweep=True)
    half.sweep_for_advancements()
    states.append(half)
    return {
        "names": [l.name for l in locations],
        "reach": [[l.can_reach(s) for l in locations] for s in states],
        "shadow": json.dumps(world._shadow_species_assignment, sort_keys=True, default=str),
        "obtainable": sorted(world._obtainable_species_dex or ()),
    }


class TestTheHooks(unittest.TestCase):
    def test_yamlless_generation_is_declared(self) -> None:
        self.assertIs(True, PokemonXDWorld.ut_can_gen_without_yaml)

    def test_interpret_slot_data_is_static_and_hands_the_data_back(self) -> None:
        """Static is UT's signal to skip its own first generation; a non-None return triggers the regen."""
        self.assertIsInstance(inspect.getattr_static(PokemonXDWorld, "interpret_slot_data"), staticmethod)
        data = {"x": 1}
        self.assertIs(data, PokemonXDWorld.interpret_slot_data(data))

    def test_it_is_not_disabled(self) -> None:
        self.assertFalse(getattr(PokemonXDWorld, "disable_ut", False))


class TestTheSlotDataRecord(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mw = _build(77, {})
        cls.record = json.loads(json.dumps(cls.mw.worlds[1].fill_slot_data()))[UT_SLOT_DATA_KEY]

    def test_its_shape(self) -> None:
        self.assertEqual(UT_SLOT_DATA_FORMAT, self.record["format"])
        self.assertIsInstance(self.record["seed"], int)
        self.assertEqual(set(ut_option_names()), set(self.record["options"]))

    def test_the_seed_survives_a_javascript_number(self) -> None:
        """A double holds 53 bits exactly. One more and a JS tracker would round it, silently, into a different
        world."""
        self.assertLess(self.record["seed"], 2 ** UT_SEED_BITS)
        self.assertLessEqual(UT_SEED_BITS, 53)

    def test_it_carries_every_option_this_world_defines(self) -> None:
        from Options import PerGameCommonOptions

        own = set(PokemonXDOptions.type_hints) - set(PerGameCommonOptions.type_hints)
        self.assertEqual(own, set(ut_option_names()))
        self.assertIn("randomize_shadow_species", own)


class TestItReplays(unittest.TestCase):
    """The in-process half of the harness: same code, same process, but a DIFFERENT multiworld seed and DEFAULT
    options on the UT side. Everything must come back identical from the slot data alone."""

    CASES = (
        (101, {}),
        (202, {"shuffle_trainer_defeats": 1, "trainer_defeat_mode": 1, "shadow_pokemon_expansion": 30,
               "randomize_travel_locations": 1}),
        (303, {"randomize_shops": 0, "randomize_chests": 0, 
               "shadow_catch_progression": 1, "citadark_progression_chance": 55, "key_item_shuffle": 1}),
    )

    def test_each_case_regenerates_exactly(self) -> None:
        for seed, options in self.CASES:
            with self.subTest(seed=seed):
                real = _build(seed, options)
                slot_data = json.loads(json.dumps(real.worlds[1].fill_slot_data()))
                ut = _build(seed + 999_983, {}, passthrough=slot_data)    # wrong seed, empty YAML -- like UT
                a, b = _fingerprint(real), _fingerprint(ut)
                self.assertEqual(a["names"], b["names"], "a different set of locations")
                self.assertEqual(a["obtainable"], b["obtainable"], "a different obtainable-species set")
                self.assertEqual(a["shadow"], b["shadow"], "a different Shadow species assignment")
                self.assertEqual(a["reach"], b["reach"], "the same locations, gated differently")

    def test_the_options_come_from_slot_data_not_the_yaml(self) -> None:
        real = _build(404, {"randomize_shops": 0, "experience_rate": 640})
        slot_data = json.loads(json.dumps(real.worlds[1].fill_slot_data()))
        ut = _build(1, {}, passthrough=slot_data)
        self.assertEqual(0, int(ut.worlds[1].options.randomize_shops))
        self.assertEqual(640, int(ut.worlds[1].options.experience_rate))

    def test_without_the_record_it_rolls_its_own(self) -> None:
        """A seed from before this addendum has no record. It must still generate -- approximately -- rather than
        refuse; the player can do nothing about it but regenerate, and a crash would tell them nothing."""
        ut = _build(5, {}, passthrough={"some_other_key": 1})
        self.assertTrue(ut.worlds[1].get_locations())


class TestEveryRandomizerTakesTheWorldsRng(unittest.TestCase):
    """What makes one seed enough. A draw from the global `random` module or the multiworld's RNG would not replay,
    and UT would track a world that differs only in that draw -- silently, and only on some seeds."""

    GLOBAL_DRAW = re.compile(r"(?<![\w.])random\.(choice|choices|shuffle|sample|randint|randrange|random|uniform)\(")
    MULTIWORLD_DRAW = re.compile(r"multiworld\.random\.")

    def test_no_world_code_draws_from_a_shared_rng(self) -> None:
        offenders = []
        for path in sorted(HERE.rglob("*.py")):
            rel = path.relative_to(HERE).as_posix()
            if rel.startswith(("test/", "tools/")) or "__pycache__" in rel:
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                code = line.split("#", 1)[0]
                if self.GLOBAL_DRAW.search(code) or self.MULTIWORLD_DRAW.search(code):
                    offenders.append(f"{rel}:{number}: {line.strip()}")
        self.assertEqual([], offenders)

    def test_the_reseed_is_the_first_thing_generate_early_does(self) -> None:
        source = inspect.getsource(PokemonXDWorld.generate_early)
        body = [l.strip() for l in source.splitlines()[1:] if l.strip() and not l.strip().startswith("#")]
        self.assertEqual("self._seed_world_rng()", body[0])

    def test_the_reseeded_rng_is_a_plain_random(self) -> None:
        mw = _build(9, {})
        self.assertIsInstance(mw.worlds[1].random, random.Random)
