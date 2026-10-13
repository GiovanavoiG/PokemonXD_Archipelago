"""ADDENDUM 471 (2026-10-12) -- InfernoXD: "some purifications not being found".

The purification ledger deduplicated by the record's CURRENT species. A purified Shadow evolves (often at the ceremony,
from its stored EXP), and when it lands on the species of ANOTHER Shadow in the seed, that second Shadow's purification
was taken for a re-observation: its id went into the id ledger and nothing was ever counted. InfernoXD's seed has 13
such pairs (Quilava -> the generated Typhlosion, Bellsprout -> Weepinbell -> Victreebel, Haunter -> Gengar ...).

The fix counts up to the id ledger, which is a lower bound on the truth: every id in it is a distinct Pokemon seen
purified. So a check can arrive late, never early -- and a saved state that already swallowed one is repaired.
"""
from __future__ import annotations

import unittest

from .. import ram_client as rc

TID = 0x12345678
QUILAVA, TYPHLOSION = 156, 157


def _rec(slot: int, dex: int, shadow_id: int, purified: bool = True, pid: int = 0) -> "rc.ShadowRecord":
    return rc.ShadowRecord("box", slot, dex, shadow_id, rc.PURIFIED_FLAG_VALUE if purified else 0,
                           level=40, trainer_id=TID, pid=pid or (0x1000 + shadow_id), cur_hp=50, max_hp=50)


def _scan(tracker, records, times=rc.PURIFICATION_SCAN_CONFIRM_SCANS, **kw):
    out = []
    for _ in range(times):
        out += tracker.observe_records(list(records), seed_shadow_dex={QUILAVA, TYPHLOSION}, **kw)
    return out


class TestTheEvolvedSpeciesNoLongerSwallowsAShadow(unittest.TestCase):
    def test_quilava_evolves_then_the_real_typhlosion_is_purified(self) -> None:
        t = rc.PurificationCountTracker()
        # Shadow 10 (a Quilava) is first seen purified ALREADY evolved -- the ceremony's EXP did it.
        self.assertEqual([rc.purification_location_name(1)], _scan(t, [_rec(0, TYPHLOSION, 10)]))
        # Shadow 44, the seed's own Typhlosion, purified later.
        crossed = _scan(t, [_rec(0, TYPHLOSION, 10), _rec(1, TYPHLOSION, 44)])
        self.assertEqual([rc.purification_location_name(2)], crossed)
        self.assertEqual(2, t.total_purified)
        self.assertEqual({10, 44}, t.purified_shadow_ids)

    def test_a_saved_state_that_already_swallowed_one_is_repaired(self) -> None:
        """What the old client left behind: both ids in the ledger, one count."""
        t = rc.PurificationCountTracker()
        t.load_json({"total_purified": 1, "purified_species": [TYPHLOSION], "purified_shadow_ids": [10, 44]})
        crossed = _scan(t, [_rec(0, TYPHLOSION, 10), _rec(1, TYPHLOSION, 44)], times=1)
        self.assertEqual([rc.purification_location_name(2)], crossed)
        self.assertEqual(1, t.caught_up)
        self.assertTrue(any("ADDENDUM 471" in line for line in t.describe()))

    def test_never_early(self) -> None:
        """A species-only count (no id yet) and then that same Pokemon's id: still one purification."""
        t = rc.PurificationCountTracker()
        t.load_json({"total_purified": 1, "purified_species": [QUILAVA], "purified_shadow_ids": []})
        self.assertEqual([], _scan(t, [_rec(0, QUILAVA, 10)]))
        self.assertEqual(1, t.total_purified)
        self.assertEqual({10}, t.purified_shadow_ids)

    def test_the_seed_cap_still_holds(self) -> None:
        t = rc.PurificationCountTracker()
        t.load_json({"total_purified": 1, "purified_species": [TYPHLOSION], "purified_shadow_ids": [10, 44, 45]})
        self.assertEqual([rc.purification_location_name(2)],
                         _scan(t, [_rec(0, TYPHLOSION, 10)], times=1, shadow_count_cap=2))

    def test_the_flip_watcher_path_catches_up_too(self) -> None:
        t = rc.PurificationCountTracker()
        t.purified_shadow_ids = {10, 44}
        t.total_purified = 1
        t.tracker.poll = lambda *a, **k: []          # no new flips this poll
        self.assertEqual([rc.purification_location_name(2)], t.poll(0x80000000))


if __name__ == "__main__":
    unittest.main()
