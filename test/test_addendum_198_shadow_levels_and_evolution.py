"""ADDENDUM 198. Shadows get the team average then the scaling, and EVERYTHING evolves.

Player, two asks in one message:
 1. "with level scaling on, both vanilla and generated shadow pokemon get matched to the trainer team's
    average level and then scaled, as well as normal pokemon."
 2. "can we double check that every randomized/padded/shadow pokemon will be evolved if it's at a level it
    could evolve at? Double check it for three stage evolutions: for example, if a beldum is level 80,
    replace it with metagross rather than metang."
"""
from __future__ import annotations

import random
import struct
import math
import unittest

from ..game_data.evolution_data import NATIONAL_DEX_LEVEL_EVOLUTIONS
from ..game_data.real_trainer_data import real_shadow_census, real_species_pool
from ..randomizer.enhanced_difficulty import (
    ENHANCED_DIFFICULTY_LEVEL_MULTIPLIER,
    FILL_THE_TEAM,
    build_enhanced_difficulty_plan,
    shadow_level_assignment,
)
from ..randomizer.team_shuffle import (
    PokemonInstance,
    Species,
    TeamShuffleOptions,
    TeamShuffler,
    resolve_natural_evolution,
)
from ..tools import iso_patcher
from ..tools import xd_deck_format as deck_format
from ..tools.xd_species_index import INTERNAL_INDEX_TO_NATIONAL_DEX, NATIONAL_DEX_TO_INTERNAL_INDEX


def _name(internal_index: int) -> str:
    entry = INTERNAL_INDEX_TO_NATIONAL_DEX.get(internal_index)
    return entry[1] if entry else f"?{internal_index}"


class TestThreeStageEvolution(unittest.TestCase):
    """The player's own example, plus the rest of the three-stage lines in the game."""

    def setUp(self) -> None:
        self.pool = real_species_pool()

    def _evolve(self, dex: int, level: int) -> str:
        return _name(resolve_natural_evolution(NATIONAL_DEX_TO_INTERNAL_INDEX[dex], level, self.pool))

    def test_beldum_at_eighty_is_a_metagross(self) -> None:
        self.assertEqual("METAGROSS", self._evolve(374, 80))

    def test_beldum_stops_at_each_real_threshold(self) -> None:
        """Metang at 20, Metagross at 45 -- one level below each must not cross it."""
        self.assertEqual("BELDUM", self._evolve(374, 19))
        self.assertEqual("METANG", self._evolve(374, 20))
        self.assertEqual("METANG", self._evolve(374, 44))
        self.assertEqual("METAGROSS", self._evolve(374, 45))

    def test_every_three_stage_line_reaches_its_final_form(self) -> None:
        """Not just Beldum. Any species whose chain is two hops must make both at a high enough level."""
        two_hop = [
            dex for dex in NATIONAL_DEX_LEVEL_EVOLUTIONS
            if NATIONAL_DEX_LEVEL_EVOLUTIONS[dex][0] in NATIONAL_DEX_LEVEL_EVOLUTIONS
        ]
        self.assertGreater(len(two_hop), 15, "expected many three-stage lines to exist")
        for dex in two_hop:
            middle, _ = NATIONAL_DEX_LEVEL_EVOLUTIONS[dex]
            final, _ = NATIONAL_DEX_LEVEL_EVOLUTIONS[middle]
            start = NATIONAL_DEX_TO_INTERNAL_INDEX.get(dex)
            want = NATIONAL_DEX_TO_INTERNAL_INDEX.get(final)
            if start is None or want is None or start not in self.pool:
                continue
            got = resolve_natural_evolution(start, 100, self.pool)
            self.assertEqual(want, got,
                             f"{_name(start)} at level 100 should be {_name(want)}, got {_name(got)}")

    def test_the_three_lines_added_by_this_addendum(self) -> None:
        """Both Nidoran lines and Lileep were missing from the table entirely -- found by auditing it."""
        self.assertEqual((30, 16), NATIONAL_DEX_LEVEL_EVOLUTIONS[29])
        self.assertEqual((33, 16), NATIONAL_DEX_LEVEL_EVOLUTIONS[32])
        self.assertEqual((346, 40), NATIONAL_DEX_LEVEL_EVOLUTIONS[345])
        self.assertEqual("NIDORINA", self._evolve(29, 30))
        self.assertEqual("CRADILY", self._evolve(345, 60))


class TestShadowsEvolveToo(unittest.TestCase):
    """Shadows were the one exception, for a dedup reason that is fixed rather than worked around."""

    def _shuffler(self) -> TeamShuffler:
        return TeamShuffler(TeamShuffleOptions(legendary_safe=False), random.Random(3), real_species_pool())

    def test_a_high_level_shadow_is_evolved(self) -> None:
        """Force the pick to Beldum while keeping the REAL pool -- the chain needs Metang in it to continue.

        (Written the other way round first, with a one-species pool, and it returned METANG: proof that
        `resolve_natural_evolution` stops the moment the next stage is absent from the pool. Harmless here --
        `test_no_evolution_target_is_missing_from_the_pool` below shows no real chain has that hole -- but
        worth knowing, so the note stays.)
        """
        beldum = NATIONAL_DEX_TO_INTERNAL_INDEX[374]
        shuffler = self._shuffler()
        shuffler._candidate_species_ids = lambda original, is_shadow: [beldum]
        mon = PokemonInstance(index=1, species_id=beldum, level=80, is_shadow=True)
        shuffler.shuffle_pokemon_instance(mon)
        self.assertEqual("METAGROSS", _name(mon.species_id))

    def test_no_evolution_target_is_missing_from_the_pool(self) -> None:
        """A chain truncates silently if a middle stage is not in the pool, so nothing may be.

        `PERMANENTLY_EXCLUDED_SPECIES_INDICES` is the way that could happen -- excluding a species that some
        other species evolves through would cap that whole line one stage early, with no error anywhere.
        """
        from ..game_data.evolution_data import national_dex_to_internal_level_evolutions

        pool = real_species_pool()
        missing = sorted(
            f"{_name(source)} -> {_name(target)}"
            for source, (target, _level) in national_dex_to_internal_level_evolutions().items()
            if target not in pool
        )
        self.assertEqual([], missing)

    def test_the_dedup_is_on_the_evolved_species(self) -> None:
        """Two different pre-evolutions that share a final stage must not both become it."""
        pool = real_species_pool()
        shuffler = TeamShuffler(TeamShuffleOptions(legendary_safe=False), random.Random(11), pool)
        seen: set[int] = set()
        for index in range(1, 40):
            mon = PokemonInstance(index=index, species_id=NATIONAL_DEX_TO_INTERNAL_INDEX[374],
                                  level=90, is_shadow=True)
            shuffler.shuffle_pokemon_instance(mon)
            self.assertNotIn(mon.species_id, seen,
                             f"{_name(mon.species_id)} was handed out twice as a Shadow")
            seen.add(mon.species_id)


class TestShadowLevelsMatchThenScale(unittest.TestCase):
    def setUp(self) -> None:
        self.census = real_shadow_census()
        self.assertIsNotNone(self.census)

    def test_matching_happens_before_scaling(self) -> None:
        """A Shadow takes its TEAM'S level and is scaled from there, not scaled from its own.

        RETARGETED (ADDENDUM 315). This used to pick its example by literal value -- "a level-17 Shadow on a
        team averaging 50" -- and every row that matched was a Sixes Shadow attributed to the wrong fight: the
        census joined DDPK to its LAST holding trainer, so the Cipher Lab Shadows were matched to the level-50
        rematch tail. With that fixed no such row exists, and a test that asserts the property rather than the
        old numbers is the one that survives the next correction to the data."""
        matched, _ = shadow_level_assignment(self.census, scale_levels=False)
        scaled, _ = shadow_level_assignment(self.census, scale_levels=True)
        rows = [r for r in self.census
                if r["team_avg_level"] is not None
                and r["team_avg_level"] > r["shadow_level"]]
        self.assertTrue(rows, "no Shadow's team average differs from its own level -- nothing to measure")
        for row in rows:
            # ADDENDUM 317: the base is the team average, floored at the Shadow's own vanilla level.
            expected = max(row["team_avg_level"], row["shadow_level"])
            self.assertEqual(math.floor(expected), matched[row["dpkm_index"]], row)
            self.assertEqual(math.floor(expected * ENHANCED_DIFFICULTY_LEVEL_MULTIPLIER),
                             scaled[row["dpkm_index"]], row)

    def test_both_halves_are_written_and_agree(self) -> None:
        dpkm, ddpk = shadow_level_assignment(self.census)
        self.assertEqual(83, len(dpkm))
        self.assertEqual(83, len(ddpk))
        by_ddpk = {r["ddpk_index"]: r for r in self.census}
        for ddpk_index, level in ddpk.items():
            self.assertEqual(level, dpkm[by_ddpk[ddpk_index]["dpkm_index"]],
                             "the DDPK shadow_level byte and its DPKM record must not disagree")

    def test_a_shadow_with_no_ordinary_teammates_keeps_its_own_level(self) -> None:
        """Nine Shadows have no team to average -- Hordel's, Greevil's six. Inventing one would be a guess."""
        orphan = next(r for r in self.census if r["team_avg_level"] is None)
        matched, _ = shadow_level_assignment(self.census, scale_levels=False)
        self.assertEqual(orphan["shadow_level"], matched[orphan["dpkm_index"]])

    def test_shadow_dpkm_records_never_collide_with_ordinary_ones(self) -> None:
        """The property that lets Shadow levels ride the existing {dpkm_index: level} channel."""
        from ..game_data.real_trainer_data import real_trainer_team_census

        ordinary = {i for t in real_trainer_team_census() for i in t["member_levels"]}
        shadow = {r["dpkm_index"] for r in self.census}
        self.assertEqual(set(), ordinary & shadow)

    def test_the_plan_carries_both_and_the_ordinary_half_is_untouched(self) -> None:
        census = [{"trainer_index": 20, "free_slots": 2, "avg_level": 30, "member_levels": {900: 30}}]
        plan = build_enhanced_difficulty_plan(
            census, {1: Species(species_id=1)}, {1: [(1, 33)]}, random.Random(5),
            permanently_excluded_trainer_indices=frozenset(),
            max_added_members=FILL_THE_TEAM, scale_levels=True,
        )
        dpkm, _ = shadow_level_assignment(self.census)
        plan["level_assignment"].update(dpkm)
        self.assertEqual(int(30 * ENHANCED_DIFFICULTY_LEVEL_MULTIPLIER), plan["level_assignment"][900])
        self.assertEqual(1 + len(dpkm), len(plan["level_assignment"]))


def _synthetic_ddpk(entries: int = 6) -> bytes:
    """A real-format DECK/DDPK blob: outer DECK wrapper, DDPK section header, `entries` 0x18-byte records."""
    data = bytearray(0x20 + entries * 0x18)
    data[0x00:0x04] = b"DECK"
    data[0x10:0x14] = b"DDPK"
    struct.pack_into(">I", data, 0x14, entries * 0x18)
    struct.pack_into(">I", data, 0x18, entries)
    for index in range(1, entries):
        off = 0x20 + index * 0x18
        data[off + 0x02] = 5           # shadow_level
        data[off + 0x03] = 1           # in_use
        struct.pack_into(">H", data, off + 0x06, index * 3)   # story_deck_index
    return bytes(data)


class TestApplyShadowLevelBoost(unittest.TestCase):
    """The byte writer itself -- offset math proven against a real-format blob, not just called."""

    def test_it_writes_the_shadow_level_byte_and_nothing_else(self) -> None:
        blob = _synthetic_ddpk()
        ddpk = deck_format.DarkPokemonFile(blob)
        out = iso_patcher.apply_shadow_level_boost(blob, ddpk, {2: 66, 4: 99})
        self.assertEqual(len(blob), len(out), "an in-place byte write must not resize the section")
        after = deck_format.DarkPokemonFile(out)
        self.assertEqual(66, after.ddpk_full(2)["shadow_level"])
        self.assertEqual(99, after.ddpk_full(4)["shadow_level"])
        self.assertEqual(5, after.ddpk_full(1)["shadow_level"], "an untouched entry must stay put")
        for index in range(1, 6):
            self.assertEqual(deck_format.DarkPokemonFile(blob).ddpk_full(index)["story_deck_index"],
                             after.ddpk_full(index)["story_deck_index"],
                             "every other field of the record must be untouched")
            self.assertEqual(1, after.ddpk_full(index)["in_use"])

    def test_it_clamps_to_the_real_level_range(self) -> None:
        blob = _synthetic_ddpk()
        ddpk = deck_format.DarkPokemonFile(blob)
        out = deck_format.DarkPokemonFile(iso_patcher.apply_shadow_level_boost(blob, ddpk, {1: 0, 2: 250}))
        self.assertEqual(1, out.ddpk_full(1)["shadow_level"])
        self.assertEqual(100, out.ddpk_full(2)["shadow_level"])

    def test_an_out_of_range_index_is_refused_not_written_past(self) -> None:
        blob = _synthetic_ddpk()
        ddpk = deck_format.DarkPokemonFile(blob)
        with self.assertRaises(ValueError):
            iso_patcher.apply_shadow_level_boost(blob, ddpk, {999: 50})
