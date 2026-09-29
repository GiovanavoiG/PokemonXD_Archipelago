"""ADDENDUM 196. The generated template IS the player's own YAML.

Player: "Fold the Story_Byte yaml option into location shuffle - it is a feature built exclusively for
location shuffle. I've given you a yaml - make this the default yaml."

So the template Archipelago writes for this world is no longer whatever falls out of options.py -- it is a
file the player curated: their option order, their wording, their defaults. `data/reference_template.yaml` is
that file, checked in verbatim, and this test is what keeps options.py from drifting away from it.

THREE THINGS ARE PINNED, and deliberately not a fourth. The option SET, the option ORDER, and each option's
DEFAULT all have to match. The description prose is not compared line-for-line -- AP reflows docstrings and a
whitespace difference should not fail a build -- but the set/order/default triple is what makes a generated
template recognisably the player's file, and all three are things a casual edit to options.py would silently
change.
"""
from __future__ import annotations

import re
import unittest

from ..game_data import load_json_data_file  # noqa: F401  (proves the data dir is importable)
from ..options import PokemonXDOptions

_TEMPLATE = "reference_template.yaml"
_COMMON = {
    "progression_balancing", "accessibility", "local_items", "non_local_items", "start_inventory",
    "start_hints", "start_location_hints", "exclude_locations", "priority_locations", "item_links",
    "plando_items", "plando_texts", "death_link", "game",
}


def _reference() -> "list[tuple[str, str | None]]":
    """[(option_name, default_keyword_or_value)] in the player's own order, world options only."""
    from importlib.resources import files

    package = (__package__ or "pokemon_xd.test").rsplit(".", 1)[0]
    text = files(package).joinpath("data", _TEMPLATE).read_text(encoding="utf-8-sig")
    body = text.split("Pokemon XD Gale of Darkness:\n", 1)[1]
    out: "list[tuple[str, str | None]]" = []
    current: "str | None" = None
    for line in body.splitlines():
        header = re.match(r"^  ([a-z_][a-z0-9_]*):\s*$", line)
        if header:
            current = header.group(1)
            if current not in _COMMON:
                out.append([current, None])
            continue
        if out and current == out[-1][0]:
            value = re.match(r"^\s*'?([\w\-]+)'?:\s*50\s*$", line)
            if value:
                out[-1][1] = value.group(1)
    return [(name, default) for name, default in out]


def _actual_default(cls) -> str:
    default = getattr(cls, "default", None)
    options = getattr(cls, "options", None)
    if options:
        for keyword, value in options.items():
            if value == default:
                return keyword
    return str(default)


class TestGeneratedTemplateMatchesThePlayersYaml(unittest.TestCase):
    def setUp(self) -> None:
        self.reference = _reference()
        self.actual = [n for n in PokemonXDOptions.type_hints if n not in _COMMON]

    def test_the_option_set_matches(self) -> None:
        self.assertEqual(sorted(name for name, _d in self.reference), sorted(self.actual),
                         "options.py and the player's template disagree about which options exist")

    def test_the_option_order_matches(self) -> None:
        """Order is not cosmetic: generate_yaml_templates emits the template in dataclass field order."""
        self.assertEqual([name for name, _d in self.reference], self.actual)

    def test_every_default_matches(self) -> None:
        mismatches = []
        for name, wanted in self.reference:
            if wanted is None:
                continue
            actual = _actual_default(PokemonXDOptions.type_hints[name])
            if actual != wanted:
                mismatches.append(f"{name}: options.py says {actual!r}, the template says {wanted!r}")
        self.assertEqual([], mismatches)

    def test_the_folded_and_removed_options_are_gone(self) -> None:
        self.assertNotIn("story_byte_area_memory", PokemonXDOptions.type_hints)
        self.assertNotIn("include_traps", PokemonXDOptions.type_hints)
