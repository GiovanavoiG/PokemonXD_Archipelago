"""ADDENDUM 322 -- a check the seed does not contain is never offered to the server.

Player, with the server's own log:

    [11:11:52]: 'No location 3821605 for player 1'
    KeyError: 'No location 3821605 for player 1'
    Notice (all): Gioig (Team #1) has left the game.

3821605 is `Agate Village Shop AP Item 1`. The seed was generated with Agate Village Pit Stop on, which
removes Agate's shop checks -- so the location exists in the datapackage (identical in every seed) and not in
the seed. MultiServer raises on an unknown id and the raise closes the connection, which is why this looked
like a connection problem rather than a check problem."""
import asyncio
import unittest
from unittest import mock

from .. import Client

AGATE = Client.LOCATION_NAME_TO_ID["Agate Village Shop AP Item 1"]
GATEON = Client.LOCATION_NAME_TO_ID["Gateon Port Shop AP Item 1"]


class _Ctx:
    """Only the fields the funnel touches."""

    def __init__(self, missing=(), checked=()):
        self.missing_locations = set(missing)
        self.checked_locations = set(checked)
        self._locations_not_in_seed = set()
        self.sent: "list[set[int]]" = []

    async def check_locations(self, ids):
        self.sent.append(set(ids))
        return set(ids)


def _send(ctx, names):
    asyncio.get_event_loop().run_until_complete(Client._send_checks(ctx, names))


class TestTheFunnel(unittest.TestCase):
    def setUp(self):
        self.logged: "list[str]" = []
        patcher = mock.patch.object(Client.logger, "info", side_effect=self.logged.append)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_reported_case_is_not_sent(self):
        ctx = _Ctx(missing={GATEON})
        _send(ctx, ["Agate Village Shop AP Item 1"])
        self.assertEqual([], ctx.sent, "the id that disconnected the player must never reach the server")

    def test_a_real_location_still_goes(self):
        ctx = _Ctx(missing={GATEON})
        _send(ctx, ["Gateon Port Shop AP Item 1"])
        self.assertEqual([{GATEON}], ctx.sent)

    def test_a_mixed_batch_sends_the_real_half(self):
        ctx = _Ctx(missing={GATEON})
        _send(ctx, ["Gateon Port Shop AP Item 1", "Agate Village Shop AP Item 1"])
        self.assertEqual([{GATEON}], ctx.sent)

    def test_an_already_checked_location_still_counts_as_in_the_seed(self):
        """`checked_locations` is the other half of what the seed contains -- a re-offer must not be dropped
        as 'not in this seed', or a reconnect would report every earned check as missing."""
        ctx = _Ctx(missing=set(), checked={GATEON})
        _send(ctx, ["Gateon Port Shop AP Item 1"])
        self.assertEqual([{GATEON}], ctx.sent)

    def test_it_is_reported_once_and_then_held(self):
        ctx = _Ctx(missing={GATEON})
        for _ in range(5):
            _send(ctx, ["Agate Village Shop AP Item 1"])
        said = [line for line in self.logged if "no such location" in line]
        self.assertEqual(1, len(said), said)
        self.assertIn("Agate Village Shop AP Item 1", said[0])

    def test_before_connecting_nothing_is_filtered(self):
        """With no seed list yet there is nothing to filter against, and inventing one would drop real
        checks. `check_locations` is a no-op before the connection anyway."""
        ctx = _Ctx()
        _send(ctx, ["Gateon Port Shop AP Item 1"])
        self.assertEqual([{GATEON}], ctx.sent)

    def test_an_unknown_name_is_still_ignored(self):
        ctx = _Ctx(missing={GATEON})
        _send(ctx, ["Not A Real Location"])
        self.assertEqual([], ctx.sent)


class TestTheFunnelIsTheOnlyWayOut(unittest.TestCase):
    def test_every_detector_goes_through_it(self):
        """The guard is only worth anything if nothing calls `check_locations` around it."""
        from pathlib import Path
        source = Path(Client.__file__).read_text(encoding="utf-8")
        body = source.split("async def _send_checks", 1)[1]
        calls = source.count("ctx.check_locations(")
        self.assertEqual(1, calls, "a detector is calling check_locations directly, bypassing the filter")
        # ADDENDUM 323 moved the union behind `seed_location_ids`, which the scout uses too.
        self.assertIn("seed_location_ids(ctx)", body)
