"""ADDENDUM 135 (2026-09-11). Two player reports, one shared cause -- the battle roster was being read too
bluntly.

  1. "I just defeated Lovrina in the cipher lab, but her check didn't send."
  2. "we're still sending items during battle sometimes - see if you can find a more robust solution,
     hopefully with the same info as the trainer defeats."

Every record below is REAL: addresses, species and HP values come from the player's own post-battle MEM1 dump
taken at story byte 0x2B (story-flags checkpoint 14)."""
from __future__ import annotations

import unittest

from .. import ram_client as rc

R = rc.BattleRosterRecord

# Lovrina's roster exactly as it sat in the player's dump: a stale full-HP copy, the real all-zero copy, and
# two strays thousands of bytes away -- one of them (LOMBRE) a species that is not even on her team.
_LOVRINA_STALE = [(0x804A87C0, "SCEPTILE", 72), (0x804A8884, "KINGDRA", 72), (0x804A8948, "XATU", 67),
                  (0x804A8A0C, "KOFFING", 55), (0x804A8AD0, "CUBONE", 60)]
_LOVRINA_ZEROED = [(0x804A9048, "KOFFING", 0), (0x804A9348, "CUBONE", 0), (0x804A9648, "SCEPTILE", 0),
                   (0x804A9C48, "XATU", 0), (0x804A9F48, "KINGDRA", 0)]
_LOVRINA_STRAYS = [(0x804AF5C8, "LOMBRE", 53), (0x80831E54, "KOFFING", 55)]


def _recs(rows, surname="LOVRINA"):
    return [R(a, surname, s, hp) for a, s, hp in rows]


def _battle_frames():
    """The real live sequence: her team at full HP, chipped down, then KO'd (the zeroed copy appears), with
    the strays present the whole time -- which is how they actually looked in the dump."""
    def frame(scale, include_zero):
        rows = [(a, s, max(0, int(hp * scale))) for a, s, hp in _LOVRINA_STALE]
        if include_zero:
            rows += _LOVRINA_ZEROED
        return _recs(rows + _LOVRINA_STRAYS)

    return [frame(1.0, False), frame(0.6, False), frame(0.2, False),
            frame(0.0, True), frame(0.0, True), frame(0.0, True)]


class TestDominantRosterCluster(unittest.TestCase):
    def test_the_two_real_strays_are_dropped_and_both_copies_kept(self) -> None:
        records = _recs(_LOVRINA_STALE + _LOVRINA_ZEROED + _LOVRINA_STRAYS)
        cluster = rc.dominant_roster_cluster(records)
        self.assertEqual(len(cluster), 10)
        kept = {(r.address, r.species_name) for r in cluster}
        self.assertNotIn((0x804AF5C8, "LOMBRE"), kept)
        self.assertNotIn((0x80831E54, "KOFFING"), kept)
        for addr, species, _ in _LOVRINA_STALE + _LOVRINA_ZEROED:
            self.assertIn((addr, species), kept)

    def test_empty_and_single_record_inputs(self) -> None:
        self.assertEqual(rc.dominant_roster_cluster([]), [])
        one = _recs([(0x80400000, "PIKACHU", 10)])
        self.assertEqual(rc.dominant_roster_cluster(one), one)

    def test_ties_break_toward_the_lowest_address_so_the_result_is_deterministic(self) -> None:
        low = _recs([(0x80400000, "A", 1), (0x80400100, "B", 1)])
        high = _recs([(0x80500000, "C", 1), (0x80500100, "D", 1)])
        self.assertEqual(rc.dominant_roster_cluster(high + low), low)
        self.assertEqual(rc.dominant_roster_cluster(low + high), low)


class TestTrainerDefeatDetection(unittest.TestCase):
    def _run(self, frames, **kwargs):
        tracker = rc.TrainerBattleDefeatTracker()
        queue = {"LOVRINA": ["Defeat - Cipher Admin Lovrina"]}
        out = [tracker.poll(queue, lambda n: f"Defeat {n} Trainers", records=f, **kwargs) for f in frames]
        return tracker, out

    def test_lovrina_is_now_detected_through_the_real_stray_records(self) -> None:
        tracker, out = self._run(_battle_frames())
        fired = [name for poll in out for name in poll]
        self.assertIn("Defeat - Cipher Admin Lovrina", fired)
        self.assertIn("Defeat 1 Trainers", fired)
        self.assertEqual(tracker.defeat_count, 1)
        self.assertEqual(tracker.last_strays_dropped, {"LOVRINA": 2})

    def test_the_old_surname_only_grouping_would_have_missed_it(self) -> None:
        """Pins the actual regression: with clustering disabled, the same sequence fires nothing at all --
        which is exactly what the player experienced."""
        original = rc.dominant_roster_cluster
        rc.dominant_roster_cluster = lambda records, max_gap=0: list(records)
        try:
            tracker, out = self._run(_battle_frames())
        finally:
            rc.dominant_roster_cluster = original
        self.assertEqual([name for poll in out for name in poll], [])
        self.assertEqual(tracker.defeat_count, 0)

    def test_the_players_own_surname_can_be_excluded(self) -> None:
        """Every record of the player's own party carries their in-game trainer name, so a party wipe (i.e.
        the player LOSING) otherwise reads as a trainer defeat -- and parks that surname where it can never
        re-arm, because the player's own records never vanish."""
        wipe = [_recs([(0x804793A0, "ZAPDOS", 30), (0x80479464, "NIDORINA", 25)], surname="Gioig"),
                _recs([(0x804793A0, "ZAPDOS", 0), (0x80479464, "NIDORINA", 0)], surname="Gioig"),
                _recs([(0x804793A0, "ZAPDOS", 0), (0x80479464, "NIDORINA", 0)], surname="Gioig")]
        tracker, out = self._run(wipe, exclude_surnames={"Gioig"})
        self.assertEqual([n for poll in out for n in poll], [])
        self.assertEqual(tracker.defeat_count, 0)

        tracker2, out2 = self._run(wipe)  # without the exclusion it counts the player's own wipe
        self.assertGreater(tracker2.defeat_count, 0)

    def test_an_ordinary_single_cluster_battle_is_unaffected(self) -> None:
        frames = [_recs([(0x804A8000, "ZUBAT", 20), (0x804A80C4, "GULPIN", 18)], surname="BARDO"),
                  _recs([(0x804A8000, "ZUBAT", 0), (0x804A80C4, "GULPIN", 4)], surname="BARDO"),
                  _recs([(0x804A8000, "ZUBAT", 0), (0x804A80C4, "GULPIN", 0)], surname="BARDO"),
                  _recs([(0x804A8000, "ZUBAT", 0), (0x804A80C4, "GULPIN", 0)], surname="BARDO")]
        tracker = rc.TrainerBattleDefeatTracker()
        out = [tracker.poll({}, lambda n: f"Defeat {n} Trainers", records=f) for f in frames]
        self.assertIn("Defeat 1 Trainers", [n for poll in out for n in poll])
        self.assertEqual(tracker.last_strays_dropped, {})


class TestBattleActivityHold(unittest.TestCase):
    """The property that matters is not "does it detect battles" but "can it ever fail to release"."""

    def test_it_holds_while_roster_hp_is_moving_and_releases_when_it_stops(self) -> None:
        hold = rc.BattleActivityHold(quiet_seconds=2.5, max_hold_seconds=30.0)
        t = 1000.0
        hold.observe(_recs([(0x804A8000, "ZUBAT", 20)]), 0, now=t)          # first sighting: no motion yet
        self.assertFalse(hold.should_hold(t))
        self.assertTrue(hold.observe(_recs([(0x804A8000, "ZUBAT", 14)]), 0, now=t + 1))   # HP moved
        self.assertTrue(hold.should_hold(t + 2))
        self.assertTrue(hold.should_hold(t + 3.4))
        self.assertFalse(hold.should_hold(t + 4.0))                          # 3.0s quiet -> released

    def test_a_frozen_roster_can_never_hold_delivery(self) -> None:
        """The exact failure shape of ADDENDUM 34/37/39/41: something stale sitting in memory forever. A
        level signal gets stuck on this; a motion signal cannot, because nothing is changing."""
        hold = rc.BattleActivityHold()
        frozen = _recs([(0x804A8000, "ZUBAT", 0), (0x804A80C4, "GULPIN", 0)], surname="BARDO")
        t = 5000.0
        for i in range(400):
            hold.observe(frozen, 0, now=t + i)
        self.assertFalse(hold.should_hold(t + 400))

    def test_the_ceiling_releases_even_if_activity_never_stops(self) -> None:
        """Second belt: even a roster churning forever cannot block delivery past the ceiling."""
        hold = rc.BattleActivityHold(quiet_seconds=2.5, max_hold_seconds=30.0)
        t = 9000.0
        for i in range(200):
            hp = 50 - (i % 40)
            hold.observe(_recs([(0x804A8000, "ZUBAT", hp)]), 0, now=t + i)
        self.assertFalse(hold.should_hold(t + 200))
        self.assertTrue(hold.ceiling_tripped)

    def test_records_appearing_or_vanishing_counts_as_motion(self) -> None:
        hold = rc.BattleActivityHold()
        t = 100.0
        hold.observe(_recs([(0x804A8000, "ZUBAT", 20)]), 0, now=t)
        self.assertTrue(hold.observe(_recs([(0x804A8000, "ZUBAT", 20), (0x804A80C4, "GULPIN", 18)]), 0, now=t + 1))

    def test_the_anchor_alone_can_arm_it(self) -> None:
        hold = rc.BattleActivityHold()
        t = 200.0
        self.assertTrue(hold.observe([], anchor_value=0x80500000, now=t))
        self.assertFalse(hold.should_hold(t + 5))

    def test_no_records_at_all_never_holds(self) -> None:
        hold = rc.BattleActivityHold()
        for i in range(50):
            self.assertFalse(hold.observe([], 0, now=300.0 + i))


if __name__ == "__main__":
    unittest.main()
