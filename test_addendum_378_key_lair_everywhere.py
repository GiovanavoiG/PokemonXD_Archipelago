"""ADDENDUM 378 (2026-09-27): "Key Lab" becomes "Key Lair" everywhere, and the basement stops being 5F.

Player: "Rename Cipher Key Lair 5F Chest to Cipher Key Lair Basement Chest. Rename the item 'Travel Unlock -
Cipher Key Lab' to 'Travel Unlock - Cipher Key Lair'. Make every 'Key Lab' reference 'Key Lair'. Also, the fix
for Cipher Key Lair 1F Chest 3 worked - remove the debug message."

ONE EDIT DID THE ITEM, THE LOCATION AND THE REGION. `TRAVEL_LOCATION_NAMES` is built from the bit table in
`travel_locations`, and the `Travel Unlock - {name}` item, the `Unlock - {name}` check and regions.py's
`Travel Gateway - {name}` region are all derived from those names. So the rename is the one key, and its
POSITION is what preserves the ids -- `items._table` numbers by index into that order.

The name was always the odd one out: ADDENDUM 91 confirmed the icon and the region are the same place, and every
other travel name already matched its region. `TRAVEL_LOCATION_TARGET_REGION` now has an identity row for it,
like eight of its nine neighbours.

WHAT WAS DELIBERATELY NOT RENAMED: three comment lines that QUOTE the player verbatim ("And make Cipher Key
Lab's floor 0x64"). Editing a quotation falsifies the record, and this project's documentation rests on those
being exact.
"""
from __future__ import annotations

import pathlib
import re
import unittest

from .. import items as I, locations as L, travel_locations as tl
from ..game_data import chest_names as cn

IDS = L.get_location_name_to_id(0)
WORLD = pathlib.Path(__file__).resolve().parent.parent


class TestTheNewNames(unittest.TestCase):
    def test_the_travel_destination_is_the_region_name(self) -> None:
        self.assertIn("Cipher Key Lair", tl.TRAVEL_LOCATION_NAMES)
        self.assertNotIn("Cipher Key Lab", tl.TRAVEL_LOCATION_NAMES)
        self.assertEqual("Cipher Key Lair", tl.TRAVEL_LOCATION_TARGET_REGION["Cipher Key Lair"])

    def test_the_item_the_location_and_the_gateway_all_followed(self) -> None:
        """The point of renaming the source key rather than four strings."""
        self.assertIn("Travel Unlock - Cipher Key Lair", I.ITEM_TABLE)
        self.assertNotIn("Travel Unlock - Cipher Key Lab", I.ITEM_TABLE)
        self.assertIn("Unlock - Cipher Key Lair", IDS)
        self.assertNotIn("Unlock - Cipher Key Lab", IDS)

    def test_the_basement_chest(self) -> None:
        self.assertEqual("Cipher Key Lair Basement Chest", cn.CHEST_LOCATION_NAME_OVERRIDES[(54,)])
        self.assertIn("Cipher Key Lair Basement Chest", IDS)
        self.assertNotIn("Cipher Key Lair 5F Chest", IDS)

    def test_no_live_string_still_says_key_lab(self) -> None:
        """Every remaining occurrence in the shipped modules must be a COMMENT that quotes the player. A live
        string or an unquoted mention would mean one of the four derived names did not follow the rename.

        The `test/` tree is excluded: these modules discuss the rename by name, including this one's own
        docstring, and a test that fails on its own prose is a test about itself."""
        offenders: "list[str]" = []
        for path in sorted(WORLD.rglob("*.py")):
            if "test" in path.relative_to(WORLD).parts:
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
                if "Key Lab" not in line:
                    continue
                stripped = line.strip()
                quoting = "0x64" in line or "Make every" in line
                if not (stripped.startswith("#") and quoting):
                    offenders.append(f"{path.relative_to(WORLD)}:{number}: {stripped[:90]}")
        self.assertEqual([], offenders)

    def test_the_player_quotes_were_left_verbatim(self) -> None:
        """The other half, so "sweep everything" cannot later be taken literally. Three comment lines quote the
        player's own words from ADDENDUM 324 and they must keep saying "Cipher Key Lab" -- editing a quotation
        falsifies the record that this project's documentation is built on."""
        quoted = 0
        for path in sorted(WORLD.rglob("*.py")):
            if "test" in path.relative_to(WORLD).parts:
                continue
            quoted += path.read_text(encoding="utf-8").count("Cipher Key Lab's floor 0x64")
        self.assertEqual(3, quoted, "the verbatim player quotes were swept along with the prose")


class TestEveryIdSurvived(unittest.TestCase):
    """The renames are identity changes to Archipelago, so this is the part that matters. The numbers are
    literals recorded from before the rename, not derived -- a table that derived them from the current names
    would agree with itself however wrong it was."""

    def test_the_location_ids(self) -> None:
        self.assertEqual(1426, IDS["Unlock - Cipher Key Lair"])
        self.assertEqual(1462, IDS["Cipher Key Lair Basement Chest"])

    def test_the_item_id(self) -> None:
        self.assertEqual(247, I.ITEM_TABLE["Travel Unlock - Cipher Key Lair"].id_offset)

    def test_the_travel_order_is_unchanged_apart_from_the_name(self) -> None:
        """`items._table` numbers by index, so a reorder here silently renumbers every travel unlock."""
        self.assertEqual(
            ["Snagem Hideout", "Outskirt Stand", "Poke Spots", "Pyrite Town", "Phenac City", "Realgam Tower",
             "Cipher Key Lair", "Cipher Lab", "Mt. Battle", "SS Libra", "Orre Colosseum"],
            list(tl.TRAVEL_LOCATION_NAMES),
        )

    def test_the_frozen_item_table_agrees_with_the_live_one(self) -> None:
        """The whole frozen table, not just the row that moved -- a rename is exactly when a nearby id shifts."""
        source = (WORLD / "items.py").read_text(encoding="utf-8")
        frozen = {m.group(1): int(m.group(2)) for m in re.finditer(r"^\s*'([^']+)': (\d+),", source, re.M)}
        disagreeing = {name: (value, I.ITEM_TABLE[name].id_offset) for name, value in frozen.items()
                       if name in I.ITEM_TABLE and I.ITEM_TABLE[name].id_offset != value}
        self.assertEqual({}, disagreeing)

    def test_no_two_locations_share_an_id(self) -> None:
        self.assertEqual(len(IDS), len(set(IDS.values())))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
