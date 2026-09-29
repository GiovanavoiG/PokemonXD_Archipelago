"""ADDENDUM 323 -- the shop SCOUT is what disconnected the player, and it is filtered now.

Server log the player sent:

    'No location 3821605 for player 1'
    File "MultiServer.py", line 2105, in process_client_cmd
      target_item, target_player, flags = ctx.locations[client.slot][location]
    KeyError: 'No location 3821605 for player 1'
    Notice (all): Gioig (Team #1) has left the game.

Line 2105 is the LocationScouts handler. 3821605 is `Agate Village Shop AP Item 1`, which Agate Village Pit
Stop removes from the seed -- so the cosmetic shelf-description scout named nine locations the seed does not
have, and MultiServer's KeyError closed the connection.

ADDENDUM 322 guarded `_send_checks` and did not cover this: a scout is a different packet sent from a
different place. (Checks were never the exposure at all -- `CommonContext.check_locations` intersects with
`missing_locations` itself.)"""
import asyncio
import unittest

from .. import Client

AGATE = [Client.LOCATION_NAME_TO_ID[f"Agate Village Shop AP Item {n}"] for n in range(1, 10)]
GATEON = Client.LOCATION_NAME_TO_ID["Gateon Port Shop AP Item 1"]


class _Ctx:
    def __init__(self, server_locations=()):
        self.server_locations = set(server_locations)
        self.missing_locations = set(server_locations)
        self.checked_locations = set()
        self.sent: "list[dict]" = []

    async def send_msgs(self, msgs):
        self.sent.extend(msgs)


def _scout(ctx, ids):
    asyncio.get_event_loop().run_until_complete(Client._scout_shop_locations(ctx, list(ids)))


class TestTheScout(unittest.TestCase):
    def test_the_reported_id_is_never_scouted(self):
        ctx = _Ctx({GATEON})
        _scout(ctx, [GATEON] + AGATE)
        self.assertEqual(1, len(ctx.sent))
        self.assertEqual([GATEON], ctx.sent[0]["locations"])

    def test_nothing_is_sent_when_every_id_is_outside_the_seed(self):
        ctx = _Ctx({GATEON})
        _scout(ctx, AGATE)
        self.assertEqual([], ctx.sent)

    def test_a_normal_seed_still_scouts_its_shops(self):
        ctx = _Ctx(set(AGATE) | {GATEON})
        _scout(ctx, AGATE + [GATEON])
        self.assertEqual(sorted(AGATE + [GATEON]), sorted(ctx.sent[0]["locations"]))

    def test_it_stays_a_silent_read(self):
        ctx = _Ctx({GATEON})
        _scout(ctx, [GATEON])
        self.assertEqual(0, ctx.sent[0]["create_as_hint"], "a scout must never create a hint")


class TestTheSeedLocationHelper(unittest.TestCase):
    def test_it_prefers_the_servers_own_union(self):
        ctx = _Ctx({GATEON})
        self.assertEqual({GATEON}, Client.seed_location_ids(ctx))

    def test_it_falls_back_to_missing_plus_checked(self):
        ctx = _Ctx()
        ctx.server_locations = set()
        ctx.missing_locations = {GATEON}
        ctx.checked_locations = {AGATE[0]}
        self.assertEqual({GATEON, AGATE[0]}, Client.seed_location_ids(ctx))

    def test_empty_means_not_known_yet(self):
        self.assertEqual(set(), Client.seed_location_ids(_Ctx()))


class TestNoOtherPacketCarriesRawIds(unittest.TestCase):
    def test_every_id_bearing_packet_is_filtered(self):
        """The guard is only worth something if nothing else puts location ids on the wire unfiltered."""
        from pathlib import Path
        source = Path(Client.__file__).read_text(encoding="utf-8")
        for command in ("LocationScouts", "LocationChecks"):
            for line_number, line in enumerate(source.splitlines(), 1):
                if f'"{command}"' in line and "cmd" in line:
                    window = "\n".join(source.splitlines()[max(0, line_number - 15):line_number])
                    self.assertIn("seed_location_ids", window,
                                  f"{command} at line {line_number} is sent without the seed filter")
