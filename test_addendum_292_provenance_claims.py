"""
ADDENDUM 292 -- the citation must not claim more than the code owes.

WHY THIS TEST EXISTS. This project cites rotobash/pokemon-ngc-rando (GPLv2) in a lot of comments, and it
should: that project documents the same byte offsets, strides and `common_rel` pointer-table indices this one
writes through, and pretending otherwise would be worse than dishonest, it would be unhelpful to the next
person reading this code. But a citation and a derivation claim are different things, and for a while several
headers here made the second when only the first was true. `randomizer/team_shuffle.py` opened with "ported
from ... TeamShuffler.cs" and `game_data/iso_format.py` with "ported from ... XDTrainerPokemon.cs" -- neither
file contains a line of translated C#. A GPLv2 holder reading those headers was being TOLD the file was a
port, by us, about code that was not one. That is a claim that can only ever hurt: it does not make the
citation more honest, it makes the project look like it took something it did not take.

One comment was worse than overstated, it was false. `_candidate_species_ids` used to say its exhausted-pool
fallback matched "the original's fallback of just letting duplicates happen once the set is exhausted".
Their `TeamShuffler.cs` declares a `pickedShadowPokemon` set and never adds to it, so it has no such
fallback, and no such behaviour to match. We described someone else's code wrongly while claiming kinship
with it.

WHAT THE RULE IS NOW, and what this test enforces. Facts about the game -- an offset, a stride, a pointer
index, an enum order, an LZSS window size -- are citable freely, because they are measurements of a disc
image rather than anyone's writing. Expression -- code, comments, docstrings, tooltips, option text -- is
neither copied nor claimed. So:

  1. No source file may assert that it was "ported from" that project. "Cross-checked against", "cited from"
     and "documents the same layout" are all fine and all still present; the banned phrasing is the one that
     asserts derivation of expression.
  2. `NOTICE.md` must ship inside the package and must still say the two things that make the citations
     safe to read: that no code is incorporated, and that the offsets are independently verified before use.

This is a cheap test guarding an expensive mistake. The failure mode it prevents is not a crash; it is a
sentence written in a hurry, six months from now, that gives away a claim this project never needed to make.
"""

from __future__ import annotations

import os
import unittest


WORLD_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Phrasings that assert derivation of EXPRESSION rather than citation of FACT. Matched case-insensitively
#: against the concatenation of a file's text, only on lines that also name the reference project, so an
#: unrelated internal "ported from iso_bridge.py" note is not caught by it.
_DERIVATION_PHRASES = (
    "ported from",
    "port of",
    "transliterat",
    "copied from",
    "taken verbatim",
)

_REFERENCE_MARKERS = ("rotobash", "ngc-rando", "ngcrando")


def _source_files() -> list[str]:
    out = []
    for dirpath, dirnames, filenames in os.walk(WORLD_ROOT):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in sorted(filenames):
            if name.endswith((".py", ".md", ".yaml", ".yml", ".txt")):
                out.append(os.path.join(dirpath, name))
    return out


class TestProvenanceClaims(unittest.TestCase):
    def test_no_file_claims_to_be_a_port_of_the_reference_project(self) -> None:
        offenders: list[str] = []
        for path in _source_files():
            rel = os.path.relpath(path, WORLD_ROOT)
            if rel == os.path.join("test", os.path.basename(__file__)):
                continue  # this file quotes the banned phrasings on purpose, to explain them
            with open(path, encoding="utf-8", errors="replace") as fh:
                lines = fh.read().splitlines()
            # A derivation claim can straddle a line break, so look at each line joined with the next one.
            for i, line in enumerate(lines):
                window = (line + " " + (lines[i + 1] if i + 1 < len(lines) else "")).lower()
                if not any(marker in window for marker in _REFERENCE_MARKERS):
                    continue
                for phrase in _DERIVATION_PHRASES:
                    if phrase in window:
                        offenders.append(f"{rel}:{i + 1}: {line.strip()}")
        self.assertEqual(
            offenders,
            [],
            "These lines claim this project derives EXPRESSION from rotobash/pokemon-ngc-rando. Cite the "
            "fact instead (\"cross-checked against\", \"cited from\", \"documents the same layout\") -- "
            "offsets and pointer indices are measurements of the game and are free to cite; code and "
            "comments are not ours to claim or to take.\n  " + "\n  ".join(offenders),
        )

    def test_notice_ships_and_states_the_two_load_bearing_claims(self) -> None:
        notice_path = os.path.join(WORLD_ROOT, "NOTICE.md")
        self.assertTrue(os.path.isfile(notice_path), "NOTICE.md must ship inside the package")
        text = open(notice_path, encoding="utf-8").read().lower()
        self.assertIn("rotobash/pokemon-ngc-rando", text)
        self.assertIn("gplv2", text)
        self.assertIn("does not incorporate source code", text)
        # The verification promise is what lets the citations stand on their own: we do not trust a cited
        # offset, we re-measure it against the player's ISO before writing through it.
        self.assertTrue(
            "verify_" in text or "independent" in text,
            "NOTICE.md must still say the cited offsets are independently verified before use",
        )


if __name__ == "__main__":
    unittest.main()
