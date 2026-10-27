"""Chobin never carries a Shadow: his later fights only exist late in the story, but logic sees his manor early."""
from __future__ import annotations

import unittest

from ..game_data import missable_trainers, shadow_mirrors, trainer_roster


class TestChobinIsFenced(unittest.TestCase):
    def test_the_set_is_every_chobin_row(self) -> None:
        rows = {t["index"] for t in trainer_roster.TRAINERS_BY_NAME["CHOBIN"]}
        self.assertEqual(rows, set(missable_trainers.CHOBIN_TRAINER_INDICES))

    def test_no_way_of_placing_a_shadow_can_use_him(self) -> None:
        chobin = missable_trainers.CHOBIN_TRAINER_INDICES
        for allow in (False, True):
            self.assertLessEqual(chobin, missable_trainers.shadow_expansion_excluded_trainer_indices(allow))
        self.assertFalse(chobin & missable_trainers.missable_shadow_host_indices())
        self.assertLessEqual(chobin, shadow_mirrors.mirror_excluded_trainer_indices())
        self.assertFalse(chobin & missable_trainers.REFIGHTABLE_FINAL_SHADOW_HOSTS)


if __name__ == "__main__":
    unittest.main()
