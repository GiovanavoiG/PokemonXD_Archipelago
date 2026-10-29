"""Better AI: each listed story trainer's DTNR +0x28 AI row becomes `better_ai.BETTER_AI_INDEX`."""

from __future__ import annotations

import unittest

from ..game_data import better_ai
from ..tools import iso_patcher
from ..tools import xd_deck_format as deck_format
from .test_addendum_423_nightmare_citadark import _deck


def _story() -> bytes:
    trainers = {i: {"ai": i, "slots": [0]} for i in range(1, 6)}
    return _deck(trainers, [bytes(0x20)], [bytes(0x20)] * (better_ai.BETTER_AI_INDEX + 1))


class TestTheEdit(unittest.TestCase):
    def test_listed_trainers_take_the_row(self) -> None:
        out, changed = iso_patcher.apply_better_ai_edit(_story(), {1: 1, 2: 2, 3: 3}, better_ai.BETTER_AI_INDEX)
        deck = deck_format.DeckFile(out)
        self.assertEqual([1, 2, 3], changed)
        self.assertEqual([better_ai.BETTER_AI_INDEX] * 3 + [4, 5], [deck.trainer(i)["ai_index"] for i in range(1, 6)])

    def test_skipped_trainers_keep_theirs(self) -> None:
        out, changed = iso_patcher.apply_better_ai_edit(_story(), {1: 1, 2: 2}, better_ai.BETTER_AI_INDEX, {2})
        self.assertEqual([1], changed)
        self.assertEqual(2, deck_format.DeckFile(out).trainer(2)["ai_index"])

    def test_already_patched_changes_nothing(self) -> None:
        once, _ = iso_patcher.apply_better_ai_edit(_story(), {1: 1}, better_ai.BETTER_AI_INDEX)
        twice, changed = iso_patcher.apply_better_ai_edit(once, {1: 1}, better_ai.BETTER_AI_INDEX)
        self.assertEqual([], changed)
        self.assertEqual(once, twice)

    def test_a_different_disc_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            iso_patcher.apply_better_ai_edit(_story(), {1: 9}, better_ai.BETTER_AI_INDEX)

    def test_a_row_past_the_table_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            iso_patcher.apply_better_ai_edit(_story(), {1: 1}, 999)

    def test_the_shipped_extraction_is_read(self) -> None:
        vanilla = iso_patcher._vanilla_ai_index_by_trainer()
        self.assertEqual(232, len(vanilla))
        self.assertEqual(better_ai.BETTER_AI_INDEX, vanilla[better_ai.BETTER_AI_INDEX])
