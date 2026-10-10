"""ADDENDUM 461 (2026-10-10) -- with Randomize Starter on, the first Chobin fight is one the starter can win.

Player: "If we have random starter on, can you make it so that the first Chobin fight has a pokemon that we can
guaranteed hit for at least half its health (or close to it)? Account for immunity abilities (Levitate, Soundproof,
Flash Fire, Volt Absorb, Water Absorb, Soundproof, WONDER GUARD CAN ONLY BE HIT BY SUPEREFFECTIVE) and type
immunities. Also ensure our starter CANT ONLY HAVE explosion/selfdestruct as its attacks. Run battle sims if you
can and ensure we can win."
"""
from __future__ import annotations

import json
import pathlib
import random
import tempfile
import unittest
import zipfile

from . import PokemonXDTestBase
from ..game_data import battle_sim as bs
from ..game_data import first_battle as fb
from ..game_data import starter as S
from ..game_data.real_moveset_data import load_level_up_moves
from ..game_data.real_trainer_data import load_real_trainer_pools
from ..game_data.trainer_roster import TRAINERS_BY_INDEX
from ..randomizer.path_level_scaling import PINNED_TRAINER_LEVELS
from ..randomizer.team_shuffle import EXCLUDED_MOVE_IDS
from ..tools.xd_species_index import internal_index_for_national_dex

TACKLE, SCRATCH, EMBER, WATER_GUN, THUNDERSHOCK, MUD_SLAP, GROWL = 33, 10, 52, 55, 84, 189, 45
EXPLOSION, SELFDESTRUCT, COUNTER, HYPER_VOICE = 153, 120, 68, 304


def _internal(dex: int) -> int:
    return internal_index_for_national_dex(dex)


class TestTheBattleData(unittest.TestCase):
    """`data/battle_data.json` is XD's own table, so it is pinned against Generation III facts."""

    def test_types_and_abilities(self):
        cases = {
            92: ((bs.GHOST, bs.POISON), (bs.LEVITATE,)),              # Gastly
            292: ((bs.BUG, bs.GHOST), (bs.WONDER_GUARD,)),            # Shedinja
            37: ((bs.FIRE, bs.FIRE), (bs.FLASH_FIRE,)),               # Vulpix
            170: ((bs.WATER, bs.ELECTRIC), (bs.VOLT_ABSORB, 35)),     # Chinchou
            131: ((bs.WATER, bs.ICE), (bs.WATER_ABSORB, bs.SHELL_ARMOR)),   # Lapras
            293: ((bs.NORMAL, bs.NORMAL), (bs.SOUNDPROOF,)),          # Whismur
            280: ((bs.PSYCHIC, bs.PSYCHIC), (bs.SYNCHRONIZE, bs.TRACE)),    # Ralts
        }
        for dex, (types, abilities) in cases.items():
            internal = _internal(dex)
            self.assertEqual(types, bs.species_types(internal), dex)
            self.assertEqual(abilities, bs.species_abilities(internal), dex)

    def test_moves(self):
        self.assertEqual((bs.NORMAL, 35, 95), bs.move_row(TACKLE)[:3])
        self.assertEqual((bs.NORMAL, 250, 100, bs.E_EXPLOSION), bs.move_row(EXPLOSION)[:4])
        self.assertEqual((bs.NORMAL, 200, 100, bs.E_EXPLOSION), bs.move_row(SELFDESTRUCT)[:4])
        self.assertEqual(-5, bs.move_row(COUNTER)[5])
        self.assertEqual(1, bs.move_row(HYPER_VOICE)[7], "Hyper Voice is sound-based")
        self.assertEqual(35, bs.move_row(TACKLE)[8], "PP")

    def test_stat_formula(self):
        """Eevee at 10 with perfect IVs: HP 55 base -> (110+31)*10//100 + 20 = 34."""
        self.assertEqual(34, bs.stat_values(133, 10, (31,) * 6)["hp"])
        self.assertEqual(1, bs.stat_values(_internal(292), 50, (31,) * 6)["hp"], "Shedinja always has 1 HP")


class TestTheGuarantee(unittest.TestCase):
    def _fraction(self, starter_dex, moves, foe_dex):
        return bs.guaranteed_fraction(bs.Side(_internal(starter_dex), 10, tuple(moves)),
                                      bs.Side(_internal(foe_dex), 5))[0]

    def test_type_immunities(self):
        self.assertEqual(0.0, self._fraction(133, [TACKLE], 92), "Normal cannot touch a Ghost")
        self.assertEqual(0.0, self._fraction(4, [SCRATCH], 355), "Duskull is a Ghost too")
        self.assertEqual(0.0, self._fraction(25, [THUNDERSHOCK], 74), "Electric cannot touch Ground")

    def test_ability_immunities(self):
        self.assertEqual(0.0, self._fraction(4, [EMBER], 37), "Flash Fire")
        self.assertEqual(0.0, self._fraction(7, [WATER_GUN], 131), "Water Absorb")
        self.assertEqual(0.0, self._fraction(25, [THUNDERSHOCK], 170), "Volt Absorb")
        self.assertEqual(0.0, self._fraction(258, [MUD_SLAP], 343), "Levitate (Baltoy)")
        self.assertEqual(0.0, self._fraction(293, [HYPER_VOICE], 293), "Soundproof")

    def test_wonder_guard_takes_only_super_effective(self):
        self.assertEqual(0.0, self._fraction(133, [TACKLE], 292))
        self.assertEqual(0.0, self._fraction(7, [WATER_GUN], 292), "neutral is not enough")
        self.assertEqual(1.0, self._fraction(4, [EMBER], 292), "Fire is super effective on Bug/Ghost")

    def test_trace_copies_the_starter(self):
        """Ralts can Trace a Vulpix's Flash Fire, so Ember is not a guarantee against it."""
        self.assertEqual(0.0, self._fraction(37, [EMBER], 280))

    def test_explosion_alone_guarantees_nothing(self):
        self.assertEqual(0.0, self._fraction(74, [EXPLOSION, SELFDESTRUCT], 191))
        self.assertGreater(self._fraction(74, [EXPLOSION, TACKLE], 191), 0)

    def test_the_vanilla_sunkern_against_eevee(self):
        """Eevee's Tackle on the vanilla Sunkern: the arithmetic the rest stands on, done by hand.
        Eevee Atk (110+0)*10//100+5 = 16, x0.9 = 14; Sunkern Def (60+31)*5//100+5 = 9, HP (60+31)*5//100+15 = 19.
        (6*35*14//9)//50+2 = 8, STAB 12, x0.85 = 10 -> 10/19."""
        self.assertAlmostEqual(10 / 19, self._fraction(133, [TACKLE], 191), places=4)


class TestTheStarterAlwaysHasAReliableAttack(unittest.TestCase):
    def test_every_species(self):
        level_up = load_level_up_moves()
        for dex in range(1, 387):
            for seed in (dex, dex + 1000):
                moves = S.starter_moves(random.Random(seed), _internal(dex), level_up)
                self.assertTrue(any(S.is_reliable_attack(m) for m in moves), f"dex {dex}: {moves}")
                self.assertFalse(set(moves) & EXCLUDED_MOVE_IDS, f"dex {dex} got Pound: {moves}")
                self.assertEqual(len(moves), len(set(moves)))
                self.assertLessEqual(len(moves), 4)

    def test_explosion_and_selfdestruct_do_not_count(self):
        self.assertFalse(S.is_reliable_attack(EXPLOSION))
        self.assertFalse(S.is_reliable_attack(SELFDESTRUCT))
        self.assertFalse(S.is_reliable_attack(COUNTER))
        moves = S.ensure_attacking([SELFDESTRUCT, EXPLOSION], 74, [(1, TACKLE), (1, 111)])
        self.assertIn(TACKLE, moves)
        self.assertIn(EXPLOSION, moves, "Explosion may stay -- it just cannot be the only attack")

    def test_a_full_set_loses_a_status_move_first(self):
        moves = S.ensure_attacking([SELFDESTRUCT, GROWL, 111, EXPLOSION], 74, [(1, TACKLE)])
        self.assertEqual([SELFDESTRUCT, GROWL, TACKLE, EXPLOSION], moves)


class TestTheFight(unittest.TestCase):
    def test_it_is_the_tutorial_fight(self):
        trainer = TRAINERS_BY_INDEX[fb.FIRST_CHOBIN_TRAINER_INDEX]
        self.assertEqual(("CHOBIN", 1), (trainer["name"], trainer["occurrence"]))
        self.assertEqual([fb.FIRST_CHOBIN_DPKM_INDEX], [slot["dpkm_index"] for slot in trainer["team"]])
        self.assertEqual(fb.FOE_LEVEL, PINNED_TRAINER_LEVELS[fb.FIRST_CHOBIN_TRAINER_INDEX])

    def test_the_foe_never_gets_a_cheap_win(self):
        for move in (EXPLOSION, SELFDESTRUCT, COUNTER, 243, 49, 82, 162, 117, 194, 195):   # MC, Sonicboom, Rage...
            self.assertFalse(fb.foe_move_is_safe(move, 133), move)
        shedinja = _internal(292)
        for move in (EMBER, 92, 77, 73, 201, 48, 207):   # Toxic, PoisonPowder, Leech Seed, Sandstorm, Supersonic
            self.assertFalse(fb.foe_move_is_safe(move, shedinja), move)
        self.assertTrue(fb.foe_move_is_safe(TACKLE, shedinja))


class TestEveryStarterWins(unittest.TestCase):
    """The battle sims the player asked for, for every species the option can roll."""

    @classmethod
    def setUpClass(cls):
        species_pool, _ = load_real_trainer_pools()
        cls.candidates = fb.candidate_species(species_pool, allow_legendary=False)
        cls.learnsets = load_level_up_moves()
        cls.plans = {}
        for dex in range(1, 387):
            internal = _internal(dex)
            moves = S.starter_moves(random.Random(dex), internal, cls.learnsets)
            cls.plans[dex] = (internal, moves, fb.plan(internal, moves, cls.candidates, random.Random(dex),
                                                        cls.learnsets))

    def test_a_plan_for_every_species(self):
        for dex, (_internal_, _moves, entry) in self.plans.items():
            self.assertIsNotNone(entry, dex)
            self.assertIn(entry["species"], self.candidates)
            self.assertTrue(entry["moves"], dex)
            self.assertTrue(all(fb.foe_move_is_safe(m, _internal_) for m in entry["moves"]), dex)

    def test_half_its_health_for_almost_every_starter(self):
        """Measured 360 of 386 at 50%. The rest have nothing stronger than Tackle or Scratch on a low Attack stat
        (Caterpie, Magikarp, Shuckle, Unown's 30-power Hidden Power) and no level-5 Pokemon in the pool can be
        guaranteed half; they get the best the pool offers instead."""
        at_half = sum(1 for _i, _m, e in self.plans.values() if e["fraction"] >= 0.5)
        self.assertGreaterEqual(at_half, 350)
        for dex, (_i, _m, entry) in self.plans.items():
            self.assertGreater(entry["fraction"], 0.1, f"dex {dex}: {entry}")

    def test_the_starter_wins(self):
        """An independent re-run: fresh RNG, more fights than the generation-time gate."""
        worst = []
        for dex, (internal, moves, entry) in self.plans.items():
            rate = fb.gate(internal, moves, entry["species"], entry["moves"], random.Random(dex * 31 + 7),
                           battles=400)
            worst.append((rate, dex))
            self.assertGreaterEqual(rate, 0.97, f"dex {dex}: {entry} -> {rate}")
        self.assertGreaterEqual(sum(r for r, _d in worst) / len(worst), 0.995)


def _seed(world) -> dict:
    world.pre_output()
    with tempfile.TemporaryDirectory() as tmp:
        world.generate_output(tmp)
        with zipfile.ZipFile(next(pathlib.Path(tmp).glob("*.appxd"))) as zf:
            return json.loads(zf.read("seed.json"))


class TestInAWorld(PokemonXDTestBase):
    options = {"randomize_starter": "true_random"}

    def test_the_seed_carries_the_plan(self):
        world = self.multiworld.worlds[self.player]
        entry = world._first_chobin
        self.assertIsNotNone(entry)
        self.assertEqual(entry["species"], world._trainer_species_by_dpkm_index[fb.FIRST_CHOBIN_DPKM_INDEX])
        seed = _seed(world)
        self.assertEqual(entry["species"], seed["trainer_species_by_dpkm_index"][str(fb.FIRST_CHOBIN_DPKM_INDEX)])
        shipped = seed["trainer_moves_by_dpkm_index"][str(fb.FIRST_CHOBIN_DPKM_INDEX)]
        self.assertEqual(list(entry["moves"]), [m for m in shipped if m])
        self.assertEqual(4, len(shipped))
        self.assertEqual(seed["starter"]["moves"], list(world._starter["moves"]))
        self.assertTrue(any("First Chobin" in note for note in seed["notes"]))
        self.assertGreaterEqual(entry["win_rate"], fb.MIN_WIN_RATE)


class TestPathScalingKeepsIt(PokemonXDTestBase):
    options = {"randomize_starter": "random_no_legendary", "path_level_scaling": True,
               "enhanced_difficulty_level_scaling": True}

    def test_level_and_species_survive_pre_output(self):
        """Enhanced Difficulty's multiplier lifts the pinned 5 to 6 (existing behaviour, not this addendum's); the
        fight is then re-planned at 6, and what ships is that plan."""
        world = self.multiworld.worlds[self.player]
        seed = _seed(world)
        entry = world._first_chobin
        self.assertEqual(entry, {k: v for k, v in seed["first_chobin"].items()})
        self.assertEqual(entry["species"], seed["trainer_species_by_dpkm_index"][str(fb.FIRST_CHOBIN_DPKM_INDEX)])
        levels = (seed.get("enhanced_difficulty_plan") or {}).get("level_assignment") or {}
        self.assertEqual(levels.get(str(fb.FIRST_CHOBIN_DPKM_INDEX), fb.FOE_LEVEL), entry["level"])
        shipped = seed["trainer_moves_by_dpkm_index"][str(fb.FIRST_CHOBIN_DPKM_INDEX)]
        self.assertEqual(list(entry["moves"]), [m for m in shipped if m])
        self.assertGreaterEqual(entry["win_rate"], fb.MIN_WIN_RATE)


class TestOnlySnagemAndWillieHostShadows(unittest.TestCase):
    """Same turn, player: "Remove everyone here as shadow candidates except the Snagem trainers and Willie." """

    def test_the_fence(self):
        from ..game_data import missable_indices as mi
        from ..game_data import missable_trainers as mt

        excluded = mt.shadow_expansion_excluded_trainer_indices()
        refused = {13, 21, 22, 66, 67, 68}
        self.assertEqual(refused, set(mt.SHADOW_HOST_REFUSED))
        self.assertEqual(["BOST", "CIDA", "DOSK", "RALING", "LABET", "DOBY"],
                         [TRAINERS_BY_INDEX[i]["name"] for i in (13, 21, 22, 66, 67, 68)])
        self.assertLessEqual(refused, excluded)
        allowed = mi.PLAYER_RULED_UNMISSABLE - refused
        self.assertEqual({135, 136, 137, 138, 141, 142, 143}, set(allowed))
        self.assertFalse(allowed & excluded, "Snagem and Willie stay Shadow candidates")
        self.assertEqual({"WILLIE"}, {TRAINERS_BY_INDEX[i]["name"] for i in allowed} - {
            TRAINERS_BY_INDEX[i]["name"] for i in (136, 137, 138, 141, 142, 143)})


class TestTheRefusedNeverHost(PokemonXDTestBase):
    options = {"shadow_pokemon_expansion": 44, "remove_citadark_shadows": True}

    def test_no_plan_or_relocation_targets_them(self):
        from ..game_data import missable_trainers as mt

        world = self.multiworld.worlds[self.player]
        hosts = {int(plan["trainer_index"]) for plan in (world._shadow_expansion_plans or [])}
        hosts |= {int(plan["trainer_index"]) for plan in (getattr(world, "_nightmare_relocations", None) or [])}
        self.assertTrue(hosts)
        self.assertFalse(hosts & mt.SHADOW_HOST_REFUSED)


class TestOffLeavesItAlone(PokemonXDTestBase):
    options = {"randomize_starter": "off"}

    def test_no_plan(self):
        world = self.multiworld.worlds[self.player]
        self.assertIsNone(world._first_chobin)


if __name__ == "__main__":
    unittest.main()
