"""ADDENDUM 243 (2026-09-16) -- the fence for the bug class that has now bitten four times.

Player: "Go ahead and build the fence."

TWO INDEPENDENT TABLES PRODUCE `Defeat -` LOCATIONS.

  * `trainer_defeat.TRAINER_DEFEAT_ROSTER` -- 66 rows, hand-maintained, (region, name, surname).
  * `game_data/trainer_placements.PLACEMENTS` -- 232 rows, generated from the player's workbook,
    index -> (region, required_items, required_regions).

A fight can be correctly regioned in one and wrongly in the other, and nothing checked that they agreed. That
has now been found FOUR times, each as a separate one-off investigation:

  ADDENDUM 185 -- the Phenac tier, where a seed placed the Music Disc behind itself.
  ADDENDUM 211 -- Exol, filed under plain "Pyrite Town" in the roster and "Pyrite Town (ONBS)" in the
                  occurrences.
  ADDENDUM 241 -- Miror B.'s first fight, which the occurrence table had placed in "Poke Spots" all along.
  ADDENDUM 242 -- Gonzap, who ADDENDUM 211 had explicitly looked at and called "almost certainly correct
                  as-is". He was not: the roster opened him on the Machine Part while the fight needs the
                  Elevator Key tier, and his location is NOT missable, so progression really could land there.

ADDENDUM 211's existing sweep only covers CIPHER-NAMED rows, which is precisely why Exol, Miror B and Gonzap
all walked past it. This closes the class instead of the instances.

WHAT IS ASSERTED, AND WHY IT IS ONE-SIDED. The rule is NOT "the two tables must agree". Twelve rows disagree
on purpose, with the roster deliberately LATER than the occurrence table -- ADDENDUM 185 moved the five Sixes
to "Phenac City (Post-Sixes)" precisely to be over-strict, and that over-strictness is load-bearing. Logic
that is too tight costs the generator placement room and can never break a seed; logic that is too LOOSE is
what makes a seed unwinnable. So the fence is directional: the roster's effective gate must be **no earlier
than** the occurrence table's, and anything stricter is allowed.

EFFECTIVE GATE, NOT REGION NAME. Comparing region strings reports two dozen false positives, because the
occurrence table often expresses a gate through `required_items` while sitting in an earlier region -- the
ADDENDUM 185 Phenac rows carry ('Music Disc', "Mayor's Note") in plain "Phenac City". Each side is therefore
resolved to the earliest rung of the real key-item ladder at which its WHOLE gate is satisfied, in a real
generated world.
"""
import collections
import unittest

from . import PokemonXDTestBase

# The key-item chain, in the order the region graph consumes it. Each rung holds everything before it, so a
# gate's "opens at" is just the first index whose state satisfies it.
LADDER: "list[tuple[str, list[str]]]" = [
    ("sphere 0", []),
    ("Machine Part", ["Machine Part"]),
    ("Data ROM & ID Card", ["Machine Part", "Data ROM & ID Card"]),
    ("Music Disc", ["Machine Part", "Data ROM & ID Card", "Music Disc"]),
    ("Mayor's Note", ["Machine Part", "Data ROM & ID Card", "Music Disc", "Mayor's Note"]),
    ("Elevator Key", ["Machine Part", "Data ROM & ID Card", "Music Disc", "Mayor's Note", "Elevator Key"]),
    ("System Lever", ["Machine Part", "Data ROM & ID Card", "Music Disc", "Mayor's Note", "Elevator Key",
                      "System Lever"]),
]


class TestTheRosterIsNeverLooserThanTheOccurrenceTable(PokemonXDTestBase):
    """The fence. One assertion, and the four addenda above are all instances of it failing."""

    # Cumulative mode is the one where the 66 curated roster locations actually exist; in unique mode they are
    # replaced by the per-trainer roster and never created.
    options = {"shuffle_trainer_defeats": True, "trainer_defeat_mode": 0}

    @classmethod
    def _rungs(cls, world_test):
        from BaseClasses import CollectionState
        from .. import items as _items
        out = []
        rungs = list(LADDER) + [("Robo Kyogre parts",
                                 LADDER[-1][1] + [_items.MACGUFFIN_ITEM_NAME] * 8)]
        for label, held in rungs:
            state = CollectionState(world_test.multiworld)
            for name in held:
                state.collect(world_test.multiworld.worlds[1].create_item(name), prevent_sweep=True)
            state.sweep_for_advancements()
            out.append((label, state))
        return out

    def _opens_at(self, states, region, required_items=(), required_regions=()):
        from .. import items
        wanted = [items.requirement_to_pool_item(name) for name in required_items]
        for index, (_label, state) in enumerate(states):
            if region and not state.can_reach(region, player=self.player):
                continue
            if any(not state.can_reach(name, player=self.player) for name in required_regions):
                continue
            if any(not state.has(name, self.player) for name in wanted):
                continue
            return index
        return len(states)

    def _pairs(self):
        """[(location name, roster region, occurrence placement)] for every row present in BOTH tables.

        The join is behavioural, not a guess: the roster lists a surname's rows in queue order and
        `TrainerBattleDefeatTracker` dispatches each win to the next unfinished row in that queue, so roster
        row k for a surname IS occurrence k."""
        from .. import trainer_defeat
        from ..game_data import trainer_placements, trainer_roster

        by_index = {t["index"]: (t["name"].upper(), t["occurrence"]) for t in trainer_roster.TRAINERS}
        placed = {}
        for index, placement in trainer_placements.PLACEMENTS.items():
            key = by_index.get(index)
            if key is not None:
                placed[key] = placement

        seen = collections.Counter()
        out = []
        for region, name, surname in trainer_defeat.TRAINER_DEFEAT_ROSTER:
            seen[surname.upper()] += 1
            placement = placed.get((surname.upper(), seen[surname.upper()]))
            if placement is not None and placement.region is not None:
                out.append((name, region, placement))
        return out

    def test_no_roster_row_opens_earlier_than_its_occurrence_row(self) -> None:
        """THE FENCE. A roster row that opens EARLIER than the occurrence table says is logic claiming a fight
        is available before it is -- which is how a progression item lands somewhere the player cannot reach
        yet. Every one of ADDENDUM 185 / 211 / 241 / 242 would have failed here on the day it shipped."""
        states = self._rungs(self)
        offenders = []
        for name, roster_region, placement in self._pairs():
            roster_at = self._opens_at(states, roster_region)
            occurrence_at = self._opens_at(states, placement.region, placement.required_items,
                                           placement.required_regions)
            if roster_at < occurrence_at:
                offenders.append(
                    f"{name}: roster says {roster_region!r} (opens at {states[roster_at][0]}) but the "
                    f"occurrence table says {placement.region!r} (opens at {states[occurrence_at][0]})"
                )
        self.assertEqual(offenders, [], "\n".join(["", *offenders]))

    def test_the_fence_is_actually_comparing_something(self) -> None:
        """A fence that silently compares nothing passes forever. This pins the size of the compared set, so
        a future change that breaks the join (a renamed surname, a reshaped table) fails loudly here rather
        than quietly turning the assertion above into a no-op."""
        pairs = self._pairs()
        self.assertEqual(len(pairs), 41)

    def test_the_deliberate_over_strict_rows_are_still_allowed(self) -> None:
        """The fence must stay ONE-SIDED. ADDENDUM 185 moved the five Sixes to "Phenac City (Post-Sixes)" to be
        deliberately later than the fight really is, and that over-strictness is what stopped a seed gating the
        Music Disc behind itself. A symmetrical "the two tables must agree" rule would demand undoing it."""
        states = self._rungs(self)
        stricter = [
            name for name, roster_region, placement in self._pairs()
            if self._opens_at(states, roster_region)
            > self._opens_at(states, placement.region, placement.required_items, placement.required_regions)
        ]
        self.assertIn("Defeat - Cipher Peon Browsix", stricter)
        self.assertEqual(len(stricter), 12)


class TestTheFourKnownInstances(PokemonXDTestBase):
    """Each addendum's own row, pinned by name. The fence above would catch a regression on any of them, but
    these say WHICH ones were wrong, so a future reader does not have to reconstruct it from the diff."""

    options = {"shuffle_trainer_defeats": True, "trainer_defeat_mode": 0}

    def _roster_region(self, location_name):
        from .. import trainer_defeat
        rows = [region for region, name, _surname in trainer_defeat.TRAINER_DEFEAT_ROSTER
                if name == location_name]
        self.assertEqual(len(rows), 1, location_name)
        return rows[0]

    def test_gonzap_addendum_242(self) -> None:
        """RE-RETARGETED BY ADDENDUM 341 -- and this is the test predicting its own future correctly.

        ADDENDUM 337 fenced Gonzap and rewrote this test to assert the fence's REASON, ending with: "if the
        Snag Machine ruling is ever lifted, this line fails and ADDENDUM 242's progression-eligible reading
        comes back." ADDENDUM 341 lifted it, this line failed, and the original reading is back.

        The REGION half -- which is what ADDENDUM 243 is actually about -- was never touched by either."""
        from .. import locations
        from ..game_data import missable_trainers

        self.assertEqual(self._roster_region("Defeat - Snagem Head Gonzap"), "Snagem Hideout")
        self.assertNotIn("Defeat - Snagem Head Gonzap", locations._MISSABLE_NAMED_TRAINER_LOCATIONS,
                         "ADDENDUM 242's reading restored: his fight is not missable and no longer "
                         "client-blocked, so his check can hold progression")
        self.assertNotIn(145, missable_trainers.MISSABLE_TRAINER_INDICES,
                         "the workbook still says his fight cannot be walked past")
        self.assertNotIn(145, missable_trainers.FILLER_ONLY_TRAINER_INDICES,
                         "ADDENDUM 341 un-fenced him: his fight is neither missable nor client-blocked, so "
                         "ADDENDUM 242's progression-eligible reading holds again")

    def test_smarton_addendum_242(self) -> None:
        """Moved for correctness, not for safety: this one IS missable, so it is EXCLUDED and never holds
        progression. Recorded because the cross-check report first called it an unwinnable-seed risk and that
        was wrong."""
        from .. import locations
        self.assertEqual(self._roster_region("Defeat - Cipher Peon Smarton"), "SS Libra")
        self.assertIn("Defeat - Cipher Peon Smarton", locations._MISSABLE_NAMED_TRAINER_LOCATIONS)

    def test_miror_b_addendum_241(self) -> None:
        self.assertEqual(self._roster_region("Defeat - Wanderer Miror B. (1st)"), "Poke Spots")

    def test_exol_addendum_211(self) -> None:
        self.assertEqual(self._roster_region("Defeat - Cipher Commander Exol"), "Pyrite Town (ONBS)")

    def test_the_phenac_rows_addendum_185(self) -> None:
        from .. import trainer_defeat
        phenac = [name for region, name, _s in trainer_defeat.TRAINER_DEFEAT_ROSTER
                  if region == "Phenac City (Post-Sixes)"]
        self.assertEqual(len(phenac), 22)


if __name__ == "__main__":
    unittest.main()
