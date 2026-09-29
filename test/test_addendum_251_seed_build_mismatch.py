"""ADDENDUM 251 (2026-09-16) -- a seed and the installed apworld can now tell each other apart.

ADDENDA 245/246 diagnosed a player's "unwinnable" seed. It was not a logic error. The seed was rolled the same
day three changes landed -- ADDENDUM 237 retired 52 duplicate Overworld Items, 238 excluded the Battle CD
shop's 9 lines, 242 renamed a chest -- and 63 of its 685 rows named locations the installed build no longer
had. FIVE held progression, including the Mayor's Note, which is why the player reported "there's nothing in
the SS Libra except for the chests".

Nothing anywhere noticed. The client connected, the dead ids were never sent, and the player found out hours
in. This addendum is the notice.

TWO MECHANISMS, DELIBERATELY. The id-set comparison needs no slot data and therefore works on seeds generated
before this existed -- including the reported one. The fingerprint catches what the id set cannot: a RENAME
that carries its id across, which both ADDENDUM 242 and ADDENDUM 246 did, leaving the id set identical while
still invalidating an in-flight seed.
"""
from __future__ import annotations

import ast
import pathlib
import unittest

from .. import locations


CLIENT_SOURCE = (pathlib.Path(__file__).resolve().parent.parent / "Client.py").read_text(encoding="utf-8")


class TestTheFingerprint(unittest.TestCase):
    def test_it_is_short_stable_and_hex(self) -> None:
        value = locations.LOCATION_TABLE_FINGERPRINT
        self.assertEqual(16, len(value))
        self.assertTrue(all(c in "0123456789abcdef" for c in value))
        self.assertEqual(value, locations.location_table_fingerprint(), "it must be deterministic")

    def test_it_covers_names_as_well_as_ids(self) -> None:
        """The whole reason it exists alongside the id comparison. ADDENDUM 242 and ADDENDUM 246 both renamed
        a location and CARRIED ITS ID, so an id-only digest would have been byte-identical across a change
        that invalidates every in-flight seed."""
        import hashlib

        table = locations.LOCATION_TABLE
        ids_only = hashlib.sha256(
            "\n".join(str(d.id_offset) for _n, d in sorted(table.items())).encode()
        ).hexdigest()[:16]
        self.assertNotEqual(ids_only, locations.LOCATION_TABLE_FINGERPRINT)

        renamed = dict(table)
        first = sorted(renamed)[0]
        renamed["ZZZ renamed but same id"] = renamed.pop(first)
        payload = "\n".join(f"{n}\t{d.id_offset}" for n, d in sorted(renamed.items()))
        self.assertNotEqual(locations.LOCATION_TABLE_FINGERPRINT,
                            hashlib.sha256(payload.encode()).hexdigest()[:16],
                            "a rename that keeps its id must change the fingerprint")

    def test_it_is_derived_not_hand_written(self) -> None:
        """A hand-bumped version constant is only correct while someone remembers to bump it, and the changes
        that strand items are exactly the ones that do not feel like a version bump."""
        import inspect

        source = inspect.getsource(locations.location_table_fingerprint)
        self.assertIn("LOCATION_TABLE", source)


class TestItReachesTheSeed(unittest.TestCase):
    def test_fill_slot_data_sends_it(self) -> None:
        world_source = (pathlib.Path(__file__).resolve().parent.parent / "__init__.py").read_text("utf-8")
        self.assertIn('slot_data["location_table_fingerprint"]', world_source)
        self.assertIn('slot_data["location_count"]', world_source)


class _FakeContext:
    """The three attributes the check reads, and nothing else."""

    def __init__(self, missing, checked=()):
        self.missing_locations = set(missing)
        self.checked_locations = set(checked)
        self._seed_only_location_ids = None
        self._build_only_location_count = 0
        self._seed_fingerprint = None
        self.warnings: "list[str]" = []


class TestTheComparison(unittest.TestCase):
    """The method is exercised directly, unbound, against a fake context -- Client.py cannot be imported in
    this sandbox (CommonClient -> MultiServer -> websockets.extensions), the same documented limitation
    test_addendum_109 and test_addendum_181 both work around."""

    @classmethod
    def setUpClass(cls) -> None:
        tree = ast.parse(CLIENT_SOURCE)
        wanted = {"_warn_about_a_seed_from_another_build", "print_seed_location_check"}
        funcs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name in wanted]
        assert len(funcs) == len(wanted), "the ADDENDUM 251 methods are gone"
        module = ast.Module(body=funcs, type_ignores=[])
        ast.fix_missing_locations(module)
        cls.namespace = {
            "LOCATION_NAME_TO_ID": dict(locations.get_location_name_to_id(3_820_000)),
            "LOCATION_TABLE_FINGERPRINT": locations.LOCATION_TABLE_FINGERPRINT,
            "logger": type("L", (), {
                "warning": staticmethod(lambda msg: _FakeContext.sink.append(msg)),
                "info": staticmethod(lambda msg: _FakeContext.sink.append(msg)),
            })(),
        }
        exec(compile(module, "<addendum251>", "exec"), cls.namespace)

    def setUp(self) -> None:
        _FakeContext.sink = []
        self.check = self.namespace["_warn_about_a_seed_from_another_build"]
        self.report = self.namespace["print_seed_location_check"]
        self.ids = sorted(self.namespace["LOCATION_NAME_TO_ID"].values())

    def test_a_matching_seed_says_nothing(self) -> None:
        ctx = _FakeContext(self.ids)
        self.check(ctx, {"location_table_fingerprint": locations.LOCATION_TABLE_FINGERPRINT})
        self.assertEqual([], _FakeContext.sink)

    def test_an_empty_id_set_says_nothing_rather_than_guessing(self) -> None:
        ctx = _FakeContext([])
        self.check(ctx, {})
        self.assertEqual([], _FakeContext.sink)

    def test_ids_the_build_does_not_have_are_loud(self) -> None:
        """The unwinnable case. Modelled on the real seed: locations that no longer exist."""
        ctx = _FakeContext(self.ids + [9_999_001, 9_999_002, 9_999_003])
        self.check(ctx, {})
        blob = " ".join(_FakeContext.sink)
        self.assertIn("3 of this seed's", blob)
        self.assertIn("NEVER fire", blob)
        self.assertIn("version mismatch, not a logic error", blob)
        self.assertEqual([9_999_001, 9_999_002, 9_999_003], ctx._seed_only_location_ids)

    def test_ids_the_seed_does_not_have_are_silent(self) -> None:
        """The harmless direction. Options differ, or this build gained locations -- nothing is lost, and
        warning about it would train the player to ignore the warning that matters."""
        ctx = _FakeContext(self.ids[:-50])
        self.check(ctx, {"location_table_fingerprint": locations.LOCATION_TABLE_FINGERPRINT})
        self.assertEqual([], _FakeContext.sink)
        self.assertEqual(50, ctx._build_only_location_count)

    def test_a_rename_is_caught_by_the_fingerprint_alone(self) -> None:
        """Identical id set, different table -- exactly what ADDENDUM 242 and 246 did. The id comparison is
        blind to this and the fingerprint is the only thing that sees it."""
        ctx = _FakeContext(self.ids)
        self.check(ctx, {"location_table_fingerprint": "0000000000000000"})
        blob = " ".join(_FakeContext.sink)
        self.assertIn("different build", blob)
        self.assertIn("RENAME", blob)

    def test_a_seed_with_no_fingerprint_still_gets_the_id_comparison(self) -> None:
        """Seeds rolled before this addendum carry no fingerprint. They are the ones that most need the
        check, so the id comparison may never depend on it."""
        ctx = _FakeContext(self.ids + [9_999_001])
        self.check(ctx, {})
        self.assertIn("do not exist in the installed apworld", " ".join(_FakeContext.sink))

    def test_seedcheck_reports_even_when_nothing_is_wrong(self) -> None:
        ctx = _FakeContext(self.ids)
        self.check(ctx, {"location_table_fingerprint": locations.LOCATION_TABLE_FINGERPRINT})
        _FakeContext.sink = []
        self.report(ctx)
        blob = " ".join(_FakeContext.sink)
        self.assertIn("Every location in this seed exists", blob)
        self.assertIn(locations.LOCATION_TABLE_FINGERPRINT, blob)

    def test_seedcheck_before_connecting_says_so(self) -> None:
        ctx = _FakeContext([])
        self.report(ctx)
        self.assertIn("Not connected yet", " ".join(_FakeContext.sink))


class TestItWarnsAndNeverRefuses(unittest.TestCase):
    def test_the_check_cannot_stop_the_connection(self) -> None:
        """The standing rule: "Make sure NEVER to block sending items -- that was what ruined the run." A
        mismatched seed is usually still playable for hours, and `!checked` exists. The player gets the facts
        and makes the call."""
        tree = ast.parse(CLIENT_SOURCE)
        func = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name == "_warn_about_a_seed_from_another_build")
        self.assertFalse([n for n in ast.walk(func) if isinstance(n, ast.Raise)],
                         "the mismatch check must never raise")
        for node in ast.walk(func):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                self.assertNotIn(node.func.attr, {"close", "disconnect", "exit"})


if __name__ == "__main__":
    unittest.main()
