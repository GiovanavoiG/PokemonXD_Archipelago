"""Wonder trades for the Pokemon XD client: `/wondertrade send <box> <slot>` puts a PC Pokemon in the team's shared
pool (the one Pokemon Emerald and Pokemon Crystal use), and one from the pool arrives in the first free PC slot.

One trade at a time, as in the other games: send one, and the next one another player sent comes back for it. The
pool's lock and claim follow those games' clients exactly (see `game_data/wonder_trade.py`); what XD adds is its own
memory, since it has no ROM of its own to hold a trade in flight. The state below is saved with the rest of the
client's per-seed state, and every step is safe to repeat after a restart:

    posting  -- the Pokemon is read but still in its box; posted again unless the pool already holds it
    awaiting -- it is in the pool and gone from the box; waiting for one to take
    received -- one was claimed from the pool; written to the PC as soon as that is safe

A received Pokemon carries another trainer's id, and its personality value is kept here too, so it is never counted
as a catch, a purification or anything else this seed checks."""
from __future__ import annotations

import asyncio
import json
import logging
import random
import time
import uuid
from typing import Any, Optional

from . import ram_client
from .game_data import wonder_trade as wt

logger = logging.getLogger("Client")

IDLE, POSTING, AWAITING, RECEIVED = "idle", "posting", "awaiting", "received"
WRITE_CONFIRM_POLLS = 3


class WonderTrade:
    def __init__(self) -> None:
        self.state = IDLE
        self.blob: Optional[str] = None           # what we posted (posting / awaiting)
        self.box_slot: Optional[int] = None       # where it came from (posting)
        self.record_hex: Optional[str] = None     # its record as read, so a moved Pokemon is never zeroed
        self.incoming: Optional[str] = None       # what we claimed (received)
        self.written_slot: Optional[int] = None
        self.write_streak = 0
        self.received_pids: "set[int]" = set()
        self.sent = 0
        self.received = 0
        self.cooldown_ms = wt.BASE_COOLDOWN_MS
        self.next_try = 0.0
        self.busy = False
        self.pc_full_noted = False
        self._replies: "dict[str, asyncio.Future]" = {}
        self._curves: "dict[int, int] | None" = None
        self._base_pp: "dict[int, int] | None" = None
        self._is_safe = lambda: False
        self.rng = random.Random()                # the client's own: backoff jitter and which offer to take

    # ---- persistence -------------------------------------------------------------------------------------------
    def to_json(self) -> "dict[str, Any]":
        return {"state": self.state, "blob": self.blob, "box_slot": self.box_slot, "record_hex": self.record_hex,
                "incoming": self.incoming, "received_pids": sorted(self.received_pids), "sent": self.sent,
                "received": self.received}

    def load_json(self, data: Any) -> None:
        if not isinstance(data, dict):
            return
        state = data.get("state")
        self.state = state if state in (IDLE, POSTING, AWAITING, RECEIVED) else IDLE
        self.blob = data.get("blob") if isinstance(data.get("blob"), str) else None
        self.box_slot = data.get("box_slot") if isinstance(data.get("box_slot"), int) else None
        self.record_hex = data.get("record_hex") if isinstance(data.get("record_hex"), str) else None
        self.incoming = data.get("incoming") if isinstance(data.get("incoming"), str) else None
        self.received_pids = {int(p) for p in data.get("received_pids") or [] if isinstance(p, int)}
        self.sent = int(data.get("sent") or 0)
        self.received = int(data.get("received") or 0)
        if self.state in (POSTING, AWAITING) and self.blob is None:
            self.state = IDLE
        if self.state == RECEIVED and self.incoming is None:
            self.state = AWAITING if self.blob else IDLE

    # ---- server traffic ----------------------------------------------------------------------------------------
    def on_connected(self, ctx) -> "list[dict]":
        """The packets to send on Connected: watch the pool, and make sure it exists."""
        key = wt.pool_key(ctx.team)
        return [{"cmd": "SetNotify", "keys": [key]},
                {"cmd": "Set", "key": key, "default": {wt.LOCK_KEY: 0},
                 "operations": [{"operation": "default", "value": None}]}]

    def on_set_reply(self, args: "dict[str, Any]") -> None:
        future = self._replies.pop(str(args.get("uuid", "")), None)
        if future is not None and not future.done():
            future.set_result(args)

    async def _set(self, ctx, operations: list, want_reply: bool = True) -> "dict | None":
        message = {"cmd": "Set", "key": wt.pool_key(ctx.team), "default": {wt.LOCK_KEY: 0},
                   "operations": operations}
        if not want_reply:
            await ctx.send_msgs([message])
            return None
        tag = str(uuid.uuid4())
        future = asyncio.get_event_loop().create_future()
        self._replies[tag] = future
        message.update({"want_reply": True, "uuid": tag})
        await ctx.send_msgs([message])
        try:
            return await asyncio.wait_for(future, wt.REPLY_TIMEOUT_S)
        except asyncio.TimeoutError:
            self._replies.pop(tag, None)
            return None

    def _back_off(self) -> None:
        self.cooldown_ms = min(self.cooldown_ms * 2, wt.MAX_COOLDOWN_MS) + self.rng.randrange(0, 500)
        self.next_try = time.monotonic() + self.cooldown_ms / 1000

    async def _acquire(self, ctx, keep_trying: bool) -> "dict | None":
        while True:
            if getattr(ctx, "slot", None) is None:
                return None
            lock = int(time.time_ns() / 1_000_000)
            reply = await self._set(ctx, [{"operation": "update", "value": {wt.LOCK_KEY: lock}}])
            if reply is not None and wt.lock_was_free(lock, reply):
                self.cooldown_ms = wt.BASE_COOLDOWN_MS
                return reply
            self._back_off()
            if not keep_trying:
                return None
            await asyncio.sleep(self.cooldown_ms / 1000)

    async def _unlock(self, ctx) -> None:
        await self._set(ctx, [{"operation": "update", "value": {wt.LOCK_KEY: 0}}], want_reply=False)

    def _pool(self, ctx) -> dict:
        value = (getattr(ctx, "stored_data", None) or {}).get(wt.pool_key(ctx.team))
        return value if isinstance(value, dict) else {}

    def _ours_in(self, value: dict) -> "str | None":
        for key, entry in value.items():
            if key != wt.LOCK_KEY and isinstance(entry, (list, tuple)) and len(entry) >= 2 and entry[1] == self.blob:
                return key
        return None

    # ---- the game's tables -------------------------------------------------------------------------------------
    def _tables_ready(self) -> bool:
        if self._curves is None:
            self._curves = ram_client.live_species_curves()
        if self._base_pp is None:
            self._base_pp = ram_client.live_move_base_pp()
        return self._curves is not None and self._base_pp is not None

    def _max_pp(self, move: int, ups: int) -> "int | None":
        base = (self._base_pp or {}).get(move)
        return None if base is None else base * (5 + ups) // 5

    # ---- sending -----------------------------------------------------------------------------------------------
    def prepare_send(self, ctx, box: int, slot: int) -> str:
        """Checks and reads the Pokemon for `/wondertrade send`; the posting itself runs from `poll`. Returns what to
        tell the player."""
        if self.state != IDLE:
            return {POSTING: "A wonder trade is already being sent.",
                    AWAITING: "You already have a Pokemon in the wonder trade pool -- one comes back for it first.",
                    RECEIVED: "A traded Pokemon is waiting to go into your PC first."}[self.state]
        if getattr(ctx, "slot", None) is None:
            return "Connect to the server first."
        if ctx.block_base is None:
            return "The game's save data isn't readable yet -- load your save and try again."
        if not (1 <= box <= ram_client.WONDER_TRADE_BOXES and 1 <= slot <= ram_client.PC_BOX_SLOTS_PER_BOX):
            return f"Box is 1-{ram_client.WONDER_TRADE_BOXES} and slot 1-{ram_client.PC_BOX_SLOTS_PER_BOX}."
        if not self._tables_ready():
            return "The game's species tables aren't readable yet -- try again in a moment."
        slot_index = (box - 1) * ram_client.PC_BOX_SLOTS_PER_BOX + (slot - 1)
        record = ram_client.read_box_record(ctx.block_base, slot_index)
        if record is None:
            return "That box slot did not read."
        internal = int.from_bytes(record[:2], "big")
        if wt.is_shadow(record):
            shadow_id = int.from_bytes(record[wt.OFF_SHADOW_ID:wt.OFF_SHADOW_ID + 2], "big")
            purified = ram_client.read_shadow_monitor(ctx.block_base) or set()
            flag = int.from_bytes(record[wt.OFF_RIBBONS:wt.OFF_RIBBONS + 2], "big") == ram_client.PURIFIED_FLAG_VALUE
            if shadow_id not in purified and not flag:
                return "That's a Shadow Pokemon -- purify it before trading it away."
        try:
            payload = wt.record_to_payload(record, (self._curves or {}).get(internal))
        except wt.TradeError as exc:
            return f"Can't trade that one: {exc}."
        self.blob = wt.dump_payload(payload)
        self.box_slot = slot_index
        self.record_hex = record.hex()
        self.state = POSTING
        self.next_try = 0.0
        ctx._save_local_state()
        return f"Sending {wt.describe_payload(payload)} to the wonder trade pool..."

    async def _post(self, ctx) -> None:
        reply = await self._acquire(ctx, keep_trying=False)
        if reply is None:
            return
        value = reply.get("value") if isinstance(reply.get("value"), dict) else {}
        key = self._ours_in(value)
        if key is None:
            key = wt.free_key(value)
            done = await self._set(ctx, [{"operation": "update",
                                          "value": {wt.LOCK_KEY: 0, key: [ctx.slot, self.blob]}}])
            if done is None or self._ours_in(done.get("value") or {}) is None:
                return                                   # try again next poll; posting twice is never possible
            original = done.get("original_value") or {}
            if key in original and original[key] != [ctx.slot, self.blob]:
                await self._repost(ctx, original[key])
        else:
            await self._unlock(ctx)
        # In the pool: now take it out of the box, unless the player moved something there meanwhile.
        if self.box_slot is not None and self.record_hex is not None:
            now = ram_client.read_box_record(ctx.block_base, self.box_slot)
            if now is None:
                return                                   # cannot see the box this poll; try again
            if now.hex() == self.record_hex:
                if not self._is_safe() or not ram_client.write_box_record(ctx.block_base, self.box_slot,
                                                                          ram_client.EMPTY_BOX_RECORD):
                    return
            elif not await self._withdraw(ctx):
                return
            else:
                self._reset()
                ctx._save_local_state()
                logger.info("Wonder trade cancelled: that Pokemon moved before it could leave the PC. Nothing was "
                            "traded.")
                return
        self.state = AWAITING
        self.box_slot = None
        self.record_hex = None
        self.sent += 1
        ctx._save_local_state()
        logger.info("Wonder trade sent! The next Pokemon another player sends will arrive in your PC. Save your "
                    "game now so the trade sticks.")

    async def _repost(self, ctx, entry: Any) -> None:
        """Our post landed on a key someone else had just taken (their lock had run out): put theirs back."""
        reply = await self._acquire(ctx, keep_trying=True)
        if reply is None:
            return
        await self._set(ctx, [{"operation": "update",
                               "value": {wt.LOCK_KEY: 0, wt.free_key(reply.get("value") or {}): entry}}],
                        want_reply=False)

    async def _withdraw(self, ctx) -> bool:
        reply = await self._acquire(ctx, keep_trying=True)
        if reply is None:
            return False
        key = self._ours_in(reply.get("value") or {})
        operations = [{"operation": "update", "value": {wt.LOCK_KEY: 0}}]
        if key is not None:
            operations.append({"operation": "pop", "value": key})
        return await self._set(ctx, operations) is not None

    def _reset(self) -> None:
        self.state = IDLE
        self.blob = self.box_slot = self.record_hex = self.incoming = None
        self.written_slot = None
        self.write_streak = 0

    # ---- receiving ---------------------------------------------------------------------------------------------
    async def _claim(self, ctx) -> None:
        if not wt.candidate_keys(self._pool(ctx), ctx.slot, self.blob):
            return
        reply = await self._acquire(ctx, keep_trying=False)
        if reply is None:
            return
        value = reply.get("value") if isinstance(reply.get("value"), dict) else {}
        keys = wt.candidate_keys(value, ctx.slot, self.blob)
        if not keys:
            await self._unlock(ctx)
            return
        key = self.rng.choice(keys)
        entry = value[key]
        self.incoming = entry[1]
        self.state = RECEIVED
        ctx._save_local_state()
        done = await self._set(ctx, [{"operation": "update", "value": {wt.LOCK_KEY: 0}},
                                     {"operation": "pop", "value": key}])
        if done is not None:
            original = done.get("original_value") or {}
            if original.get(key) != entry:
                self.incoming = None                     # someone else took it first
                self.state = AWAITING
                ctx._save_local_state()
                self._back_off()
                return
        elif key in self._pool(ctx) and self._pool(ctx)[key] == entry:
            self.incoming = None                         # no answer, and it is still there: not ours
            self.state = AWAITING
            ctx._save_local_state()
            return
        _parsed = wt.parse_entry(entry)
        if _parsed is not None:
            logger.info(f"Wonder trade found: {wt.describe_payload(_parsed[1])}. It goes into your PC as soon as "
                        "you're out of battles and menus.")

    def _write_received(self, ctx) -> None:
        parsed = wt.parse_entry([None, self.incoming])
        if parsed is None:                               # should not happen: it was checked before the claim
            logger.warning("Wonder trade: the Pokemon that arrived could not be read, so it was dropped.")
            self._finish(ctx)
            return
        payload = parsed[1]
        pid = int(payload.get("personality") or 0) & 0xFFFFFFFF
        if self.written_slot is not None:
            record = ram_client.read_box_record(ctx.block_base, self.written_slot)
            if record is not None and int.from_bytes(record[wt.OFF_PID:wt.OFF_PID + 4], "big") == pid \
                    and record[:2] != b"\x00\x00":
                self.write_streak += 1
                if self.write_streak >= WRITE_CONFIRM_POLLS:
                    box, slot = divmod(self.written_slot, ram_client.PC_BOX_SLOTS_PER_BOX)
                    self.received += 1
                    logger.info(f"Wonder trade received: {wt.describe_payload(payload)} -- it's in Box {box + 1}, "
                                f"slot {slot + 1}. Save your game now so it sticks.")
                    self._finish(ctx)
                return
            self.written_slot = None                     # gone again (the PC menu wrote its copy back): redo it
            self.write_streak = 0
        internal = wt._DEX_TO_INTERNAL[payload["species"]]
        template = self._template(ctx)
        record = wt.payload_to_record(payload, template, (self._curves or {}).get(internal), self._max_pp)
        slot_index = ram_client.first_empty_box_slot(ctx.block_base)
        if slot_index is None:
            if not self.pc_full_noted:
                self.pc_full_noted = True
                logger.info("Wonder trade: your PC boxes are full. Free a slot and the traded Pokemon goes there.")
            return
        self.pc_full_noted = False
        self.received_pids.add(pid)
        ctx._save_local_state()
        if self._is_safe() and ram_client.write_box_record(ctx.block_base, slot_index, record):
            self.written_slot = slot_index
            self.write_streak = 0

    def _finish(self, ctx) -> None:
        self._reset()
        ctx._save_local_state()

    def _template(self, ctx) -> "bytes | None":
        """One of the player's own records, a non-Shadow one if there is one, for the bytes nobody has named."""
        own = ram_client.hero_trainer_id(ctx.block_base)
        fallback = None
        for slot_index in range(ram_client.WONDER_TRADE_BOXES * ram_client.PC_BOX_SLOTS_PER_BOX):
            record = ram_client.read_box_record(ctx.block_base, slot_index)
            if record is None or record[:2] == b"\x00\x00":
                continue
            if own is not None and int.from_bytes(record[wt.OFF_TRAINER_ID:wt.OFF_TRAINER_ID + 4], "big") != own:
                continue
            if not wt.is_shadow(record):
                return record
            fallback = fallback or record
        return fallback

    # ---- the poll ----------------------------------------------------------------------------------------------
    def wants_poll(self) -> bool:
        return not self.busy and self.state != IDLE and (self.state == RECEIVED or time.monotonic() >= self.next_try)

    async def poll(self, ctx, is_safe) -> None:
        """Advance whatever is in flight. `is_safe()`: the save block is settled and the player is not in a battle or
        a full-screen menu, so a PC record may be written; asked again right before every write, since a step that
        talks to the server takes seconds. Runs as its own task, so the poll loop never waits on the server. Never
        raises."""
        if self.busy or self.state == IDLE or getattr(ctx, "slot", None) is None or ctx.block_base is None:
            return
        self.busy = True
        self._is_safe = is_safe
        try:
            if self.state == RECEIVED:
                if is_safe() and self._tables_ready():
                    self._write_received(ctx)
                return
            if time.monotonic() < self.next_try:
                return
            if self.state == POSTING:
                if is_safe():
                    await self._post(ctx)
            elif self.state == AWAITING:
                await self._claim(ctx)
        except Exception:
            logger.debug("Pokemon XD: wonder trade step failed", exc_info=True)
        finally:
            self.busy = False

    def describe(self, ctx) -> "list[str]":
        lines = [f"Wonder trades: {self.sent} sent, {self.received} received."]
        if self.state == POSTING:
            lines.append("  Sending: " + self._describe_blob(self.blob))
        elif self.state == AWAITING:
            lines.append("  In the pool: " + self._describe_blob(self.blob) + " -- waiting for another player's.")
        elif self.state == RECEIVED:
            lines.append("  Arrived, going into your PC: " + self._describe_blob(self.incoming))
        else:
            lines.append("  Nothing in flight. `/wondertrade send <box> <slot>` sends a PC Pokemon.")
        pool = self._pool(ctx) if getattr(ctx, "slot", None) is not None else {}
        offers = [k for k in pool if k != wt.LOCK_KEY]
        lines.append(f"  The team's pool holds {len(offers)} Pokemon, "
                     f"{len(wt.candidate_keys(pool, getattr(ctx, 'slot', None), self.blob))} of them for you.")
        return lines

    @staticmethod
    def _describe_blob(blob: "str | None") -> str:
        try:
            return wt.describe_payload(json.loads(blob or "{}"))
        except Exception:
            return "?"
