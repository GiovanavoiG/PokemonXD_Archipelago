from . import PokemonXDTestBase


class TestKraneMemoGating(PokemonXDTestBase):
    def test_citadark_isle_requires_ein_file_s(self) -> None:
        """The final event location should not be reachable without the full Krane Memo chain + Ein File S.

        only_check_listed=True is used because several *other* locations in this skeleton also partially
        depend on holding some Krane Memos (region gating), so a blanket "every other location must be
        reachable without these items" check (assertAccessDependency's default) doesn't hold here.
        """
        self.assertAccessDependency(
            ["Citadark Isle - Defeat Cipher Boss"],
            [["Krane Memo 1", "Krane Memo 2", "Krane Memo 3", "Krane Memo 4", "Krane Memo 5", "Ein File S"]],
            only_check_listed=True,
        )
