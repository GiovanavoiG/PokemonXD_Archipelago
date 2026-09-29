"""ADDENDUM 233. Every Shadow Pokemon gets at least one move that actually deals damage.

Player: "just ensure every shadow pokemon has at least one attacking move, drawn uniformly is fine."

WHY THIS MATTERS AND WHY IT IS NOT JUST A NICETY. A Shadow Pokemon cannot use the ordinary moves on its DPKM
entry until the heart gauge opens, so the (up to) four ids in its DDPK record are its entire offense for most
of the time a player owns it. A generated Shadow whose DDPK moveset is all status moves is not "weaker" -- it
has no way to deal damage at all.

The base-power table these tests lean on was measured out of the real vanilla `common_rel.rel` move table
(pointer index 124 -> 0xA2710, stride 0x38, base power at +0x19), not taken from move names or a wiki. See
`game_data/shadow_move_slots.py` for the read and its provenance.
"""
from __future__ import annotations

import random
import struct
import unittest

from ..game_data import shadow_move_slots as sms
from ..randomizer.shadow_expansion import REAL_SHADOW_MOVE_IDS
from ..tools import iso_patcher
from ..tools import xd_deck_format as deck_format


class TestMeasuredShadowMovePowers(unittest.TestCase):
    def test_tables_cover_exactly_the_real_shadow_move_ids(self) -> None:
        self.assertEqual(set(sms.SHADOW_MOVE_BASE_POWER), set(REAL_SHADOW_MOVE_IDS))
        self.assertEqual(set(sms.SHADOW_MOVE_CATEGORY), set(REAL_SHADOW_MOVE_IDS))

    def test_the_split_is_clean_356_to_366_attack_367_to_373_do_not(self) -> None:
        """The whole reason slot 0 can carry the guarantee on its own."""
        for move in range(356, 367):
            self.assertTrue(sms.is_attacking(move), f"move {move} should be a damaging Shadow move")
            self.assertGreater(sms.SHADOW_MOVE_BASE_POWER[move], 0)
        for move in range(367, 374):
            self.assertFalse(sms.is_attacking(move), f"move {move} should be a status Shadow move")
            self.assertEqual(sms.SHADOW_MOVE_BASE_POWER[move], 0)

    def test_every_slot_zero_move_is_an_attack(self) -> None:
        for move in sms.MOVES_LEGAL_IN_SLOT[0]:
            self.assertTrue(sms.is_attacking(move), f"slot-0 move {move} deals no damage")

    def test_unknown_ids_are_not_treated_as_attacks(self) -> None:
        """An ordinary move id must not read as a Shadow attack -- that is the mistake the DDPK writer's own
        fence exists to catch."""
        for ordinary in (1, 33, 52, 200, 354):
            self.assertFalse(sms.is_attacking(ordinary))
        self.assertFalse(sms.has_attacking_move([33, 52]))


class TestChooseShadowMovesAlwaysAttacks(unittest.TestCase):
    def test_every_draw_has_an_attack_and_no_illegal_placement(self) -> None:
        rng = random.Random(20260915)
        for _ in range(5000):
            for count in (1, 2, 3, 4):
                moves = sms.choose_shadow_moves(rng, count)
                self.assertTrue(sms.has_attacking_move(moves),
                                f"{moves} (count={count}) has no damaging move")
                self.assertEqual([], sms.illegal_placements(moves), f"{moves} sits in a wrong slot")

    def test_the_draw_is_still_uniform_over_slot_zero(self) -> None:
        """The player asked for the guarantee, not for a reweighting -- every slot-0 move must still show up."""
        rng = random.Random(7)
        seen = {sms.choose_shadow_moves(rng, 2)[0] for _ in range(4000)}
        self.assertEqual(seen, set(sms.MOVES_LEGAL_IN_SLOT[0]))


def _synthetic_ddpk(entries: int = 4) -> bytes:
    data = bytearray(0x20 + entries * 0x18)
    data[0x00:0x04] = b"DECK"
    data[0x10:0x14] = b"DDPK"
    struct.pack_into(">I", data, 0x14, entries * 0x18)
    struct.pack_into(">I", data, 0x18, entries)
    return bytes(data)


class TestDdpkWriterRefusesAnUnarmedShadow(unittest.TestCase):
    """The fence sits at the single point every generator funnels through, so it catches callers this
    addendum has not seen."""

    def setUp(self) -> None:
        self.blob = _synthetic_ddpk()
        self.ddpk = deck_format.DarkPokemonFile(self.blob)

    def _assignment(self, shadow_moves):
        return [{"ddpk_index": 1, "story_deck_index": 40, "shadow_level": 30,
                 "shadow_moves": shadow_moves}]

    def test_an_all_status_moveset_is_refused(self) -> None:
        with self.assertRaises(ValueError) as caught:
            iso_patcher.apply_dark_pokemon_edit(self.blob, self.ddpk, self._assignment([368, 372]))
        self.assertIn("status", str(caught.exception))

    def test_an_ordinary_dpkm_moveset_is_refused(self) -> None:
        """`entry["moves"][:2]` -- the exact shape three call sites used to pass."""
        with self.assertRaises(ValueError) as caught:
            iso_patcher.apply_dark_pokemon_edit(self.blob, self.ddpk, self._assignment([33, 52]))
        self.assertIn("not Shadow move ids", str(caught.exception))

    def test_a_real_moveset_is_written_unchanged(self) -> None:
        out = iso_patcher.apply_dark_pokemon_edit(self.blob, self.ddpk, self._assignment([356, 372]))
        written = deck_format.DarkPokemonFile(out).ddpk_full(1)
        self.assertEqual([356, 372, 0, 0], written["shadow_moves"])
        self.assertTrue(sms.has_attacking_move(written["shadow_moves"]))

    def test_an_empty_moveset_is_still_allowed(self) -> None:
        """Callers that deliberately leave the slots blank are not this fence's business."""
        out = iso_patcher.apply_dark_pokemon_edit(self.blob, self.ddpk, self._assignment([]))
        self.assertEqual([0, 0, 0, 0], deck_format.DarkPokemonFile(out).ddpk_full(1)["shadow_moves"])


class TestGeneratedShadowPlansCarryAnAttack(unittest.TestCase):
    def test_every_generated_shadow_in_a_real_plan_can_attack(self) -> None:
        from ..game_data.real_trainer_data import real_species_pool, real_trainer_free_slot_census
        from ..randomizer.shadow_expansion import build_shadow_expansion_plans

        census = real_trainer_free_slot_census()
        pool = real_species_pool()
        if not census or not pool:
            self.skipTest("real ISO census data isn't present in this build")
        plans = build_shadow_expansion_plans(
            census, pool, {}, excluded_species=set(), target_count=40, rng=random.Random(11))
        generated = [mon for plan in plans for mon in plan["new_pokemon"]]
        self.assertTrue(generated, "expected this plan to generate at least one Shadow Pokemon")
        for mon in generated:
            self.assertTrue(sms.has_attacking_move(mon["shadow_moves"]),
                            f"generated Shadow {mon} has no damaging Shadow move")
            self.assertEqual([], sms.illegal_placements(mon["shadow_moves"]))
