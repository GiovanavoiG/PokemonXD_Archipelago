"""A check two detectors send (the main one and a backup) is announced once, and still goes on the wire both times."""
from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest import mock

from .. import Client


class TestAnnouncedOnce(unittest.TestCase):
    def test_a_backup_send_says_nothing(self) -> None:
        name = next(iter(Client.LOCATION_NAME_TO_ID))
        wire = []

        async def put(ctx, ids):
            wire.append(set(ids))
        ctx = SimpleNamespace(checked_locations=set(), pending_check_ids=set(), _locations_not_in_seed=set(),
                              _save_local_state=lambda: None)
        with mock.patch.object(Client, "seed_location_ids", lambda ctx: set()), \
                mock.patch.object(Client, "_put_on_wire", put), \
                self.assertLogs(Client.logger, "INFO") as logs:
            asyncio.run(Client._send_checks(ctx, [name]))
            asyncio.run(Client._send_checks(ctx, [name]))      # the backup, before the server confirmed it
            Client.logger.info("end")
        self.assertEqual(1, sum("Sent 1 check(s)" in line for line in logs.output))
        self.assertEqual(2, len(wire))


if __name__ == "__main__":
    unittest.main()
