"""
Pokemon XD: Gale of Darkness -- Archipelago client.

Built on ram_client.py (Dolphin memory access: hooking, block-base resolution, Bag pocket read/write,
party/species detection, purification detection) and shadow_species.py.

Detected live with no ISO patch: "Catch - {species}" (386), "Purify N Shadow Pokemon" (32),
"Defeat - {trainer}" (66), "Defeat N Trainers" (232), and the seed's Goal. Catches read the save-resident
`Pokemon` records (BLOCK_BASE - 0x10 + i * 0xC4, what `heroBiosGetPokemonPtr` returns), valid as soon as the
save block resolves, by numeric species field so nicknames count; PARTY_BASE is only a second witness, being a
menu row that reads all-zero until the party screen has drawn. Trainer defeats key on SURNAME, since an
ordinary trainer's species are not globally unique, and are only confirmed live for teams of <=2.

The ~67 Overworld Item (chest/box/NPC-gift) locations have no known RAM or ISO-patch signal, so they are
manual: `/checked <name>`, with `/remaining` for what is left. See patch.py for why the ISO patch stalled.

This project does not patch the ISO, so there is no embedded slot name -- the player types it.
`CommonContext.server_auth()` only handles the PASSWORD prompt, so `get_username()` and `send_connect()` must
be called explicitly from the override below or the client connects and never asks for a slot name. That slot
name (`ctx.auth`) is only a tie-break for `resolve_block_base()` now: ADDENDUM 444 finds the save block without a
name, so the in-game trainer name can be anything and the slot name can be as long as Archipelago allows. The
trainer name is read back out of the block (`ctx.trainer_name`) wherever the client needs it.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import sys
import os
import re
import time
import traceback
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    import kvui

import Utils
from CommonClient import ClientCommandProcessor, CommonContext, get_base_parser, gui_enabled, logger, server_loop
from NetUtils import ClientStatus

from . import fst_guard, items, ram_client, shop_scout, species, trainer_defeat, travel_locations
from . import wonder_trade_client
from .game_data import story_bytes, trainer_roster
from .game_data.mtbattle_trainer_data import (
    MT_BATTLE_FINAL_TRAINER_SURNAME,
    MT_BATTLE_FINAL_TRAINER_SURNAMES,
    MT_BATTLE_ONLY_SURNAMES,
    MT_BATTLE_SURNAME_TO_LOCATION_QUEUE,
    MT_BATTLE_FIRST_TRAINER_SURNAME,
    MT_BATTLE_TOTAL_TRAINER_COUNT,
)
from .items import ITEM_TABLE, get_item_name_to_id
from .locations import (
    PERR_MACHINE_PART_LOCATION_NAME,
    EEVEELUTION_LOCATION_NAME,
    LOCATION_NAME_GROUPS,
    SHOP_ITEM_LOCATIONS,
    TRAINER_DEFEAT_COUNT_LOCATION_COUNT,
    TRAINER_DEFEAT_COUNT_LOCATION_NAME_SET,
    get_location_name_to_id,
    trainer_defeat_count_location_name,
)

# Mirrors __init__.py's PokemonXDWorld.base_id. Duplicated rather than imported so this file does not drag in
# the World/Options/AutoWorld stack; items.py/locations.py work standalone from a base id. Keep in sync.
BASE_ID = 3_820_000
ITEM_NAME_TO_ID = get_item_name_to_id(BASE_ID, include_retired=True)   # ADDENDUM 443: old ids still resolve
ITEM_ID_TO_NAME = {v: k for k, v in ITEM_NAME_TO_ID.items()}
LOCATION_NAME_TO_ID = get_location_name_to_id(BASE_ID)
# This build's location-table fingerprint, compared at connect with the one the seed carries.
from .locations import LOCATION_TABLE_FINGERPRINT  # noqa: E402
# {UPPER-CASE surname -> "Defeat X (Any)" location}. Imported, not rebuilt: locations.py and this file must
# spell a location identically or every check against it is silently rejected.
from .game_data.repeatable_trainers import SURNAME_TO_LOCATION as REPEATABLE_SURNAME_TO_LOCATION  # noqa: E402
from .game_data.trainer_beaten_flags import TRAINER_BEATEN_FLAGS  # noqa: E402
# Reverse map, so the "Sent N check(s)" line in _send_checks can name them.
ID_TO_LOCATION_NAME = {v: k for k, v in LOCATION_NAME_TO_ID.items()}

DOLPHIN_NOT_STARTED = "Not connected to Dolphin yet."
DOLPHIN_LOST = "Lost Dolphin. Start Dolphin with Pokemon XD running and the client will reconnect."
DOLPHIN_WRONG_GAME = (
    "Dolphin is running something other than Pokemon XD: Gale of Darkness (USA). Checking again every 5 seconds..."
)
DOLPHIN_NO_SAVE = (
    "Dolphin is connected, but there is no save loaded yet. Load your save and get in-game (past the title screen "
    "and menus). Checking again every 5 seconds..."
)
DOLPHIN_READY = "Connected to Dolphin."

# Verbose logging. Unconditional output is the connection lifecycle, items received, checks sent, errors,
# warnings needing player action, and one-shot guidance. Narration of normal progress is gated behind `/verbose`.

def _note(ctx: "PokemonXDContext", message: str) -> None:
    """Progress narration: only printed when `/verbose` is on. Never use this for a failure the player has to
    do something about -- those stay on `logger.warning`/`logger.error` unconditionally."""
    if getattr(ctx, "verbose_logging", False):
        logger.info(message)


def _warn_write_window_full(ctx: "PokemonXDContext", idx: int, item_name: str,
                            pocket_base: int, max_slots: int) -> None:
    """Says once per item, unconditionally, that a write never reached memory. Unconditional because the pocket
    stays full until the player makes room, so no number of polls will deliver it. The item is deliberately not
    marked delivered, so it lands on its own once a slot frees up."""
    if idx in ctx._delivery_write_full_warned:
        return
    ctx._delivery_write_full_warned.add(idx)
    logger.warning(f"{item_name} is waiting: that Bag pocket is full (and the PC can't take it). Free a slot and it "
                   f"arrives on its own.")
    _note(ctx, f"  (pocket 0x{pocket_base:08X}, {max_slots} writable slots)")


def _held_quantity(ctx: "PokemonXDContext", idx: int, read_base: int, read_slots: int, game_item_id: int) -> int:
    """How many of `game_item_id` the player holds for this delivery's purposes: the Bag window, plus the PC's item
    storage when this delivery may overflow there (ADDENDUM 446). Fixed per delivery at its baseline, so the
    baseline and every later read count the same places -- and moving an item between Bag and PC changes neither."""
    held = ram_client.find_item_quantity(read_base, read_slots, game_item_id)
    if ctx._delivery_counts_pc.get(idx):
        held += ram_client.pc_item_quantity(ctx.block_base, game_item_id)
    return held


def _give_item_or_pc_overflow(ctx: "PokemonXDContext", idx: int, item_name: str, pocket_base: int,
                           game_item_id: int, quantity: int, max_slots: int, allow_pc: bool) -> bool:
    """`give_item` into the Bag; when the Items pocket is full, into the PC's item storage instead (ADDENDUM 446).
    False only when neither took the item, having written nothing."""
    if ram_client.give_item(pocket_base, game_item_id, quantity, max_slots):
        return True
    if not (allow_pc and ram_client.may_overflow_to_pc(ctx.block_base, game_item_id)):
        return False
    if not ram_client.give_pc_item(ctx.block_base, game_item_id, quantity):
        return False
    if idx not in ctx._delivery_pc_announced:
        ctx._delivery_pc_announced.add(idx)
        logger.info(f"Your Items pocket is full -- {item_name} went to your PC's item storage.")
    return True


def _note_warn(ctx: "PokemonXDContext", message: str) -> None:
    """A transient, self-healing hiccup (a read that failed this tick, a bit that will be re-applied next
    poll). Only printed when `/verbose` is on."""
    if getattr(ctx, "verbose_logging", False):
        logger.warning(message)


def _announce_first(ctx: "PokemonXDContext", is_first: bool, message: str) -> None:
    """First occurrence of a repeating event goes to the log unconditionally; the rest are verbose-only. The
    reconciler needs this third axis -- clearing the Machine Part matters once and is noise on every later
    poll. Same message either way, so the two paths cannot drift."""
    if is_first:
        logger.info(message)
    else:
        _note(ctx, message)


# From this project's own ISO extraction (iso_filelist.json: game_code == "GXXE").
XD_GAME_CODE = b"GXXE"

POLL_INTERVAL_INGAME = 1.0  # seconds between memory polls while hooked, resolved, and in-game
#: Consecutive failed hooks before the memory-size-override hint is shown, once. About half a minute at the
#: 5s retry cadence: late enough that "emulator not open yet" is unlikely, early enough to still be watched.
HOOK_FAILURES_BEFORE_OVERRIDE_HINT = 6

# The PC-box name-text scan is ~360 reads (12 boxes x 30 slots): the one poll-loop cost that scales badly with
# poll rate, and one whose latency does not matter. Just under POLL_INTERVAL_INGAME, so the ordinary cadence never
# skips a scan and the faster map-screen loop cannot run it at its own rate.
BOX_SCAN_MIN_INTERVAL = 0.9

# On the map screen (room 910) poll rate is correctness: the area-memory write is a PRE-LOAD hook that must land
# while the cursor still hovers the destination, because the room is built from the byte as it stands at load.
# At 1.0s a fast cursor-then-A beats the poll and the player arrives at an area built from the wrong byte.
# Affordable because a map-screen tick has no battle roster, trainer scan or Bag writes, and the box scan keeps
# its own cadence; `map_cursor_tracker.resolve()` rescans MEM1 once per map open, not per tick.
POLL_INTERVAL_MAP_SCREEN = 0.05
POLL_INTERVAL_RETRY = 5.0   # seconds before retrying a failed hook / block-base resolution
CATCH_GUARD_INTERVAL = 10.0      # seconds between Guaranteed Catches guard passes
ANIMATION_GUARD_INTERVAL = 5.0   # ADDENDUM 454: seconds between Disable Move Animations guard passes

# Sub-tick interval for `fast_poll_window()`, which re-runs only the shop and chest paths in the between-tick
# wait. Not a rescale: the outer tick still comes round once a second, so every other check keeps its cadence and
# confirm windows. Speeding up the whole loop would drag in the 24MB MEM1 roster scan and shorten every
# poll-counted confirm streak in real time.
#
# It buys granularity, not a shorter debounce -- the shop and chest windows are wall-clock floors. Measured
# against the real chest tables at 0.02 / 0.05 / 0.1 / 1.0s, flagged and unflagged, including with the room
# unreadable throughout: every pickup was credited at every rate. The real edge is latency, since an unflagged
# chest waits out `_CONFIRM_SECONDS` (2.0s) for lack of a second witness.
POLL_INTERVAL_FAST = 0.05

# The chest half has no room to gate on -- a chest can be opened anywhere -- so it runs everywhere in-game, at one
# `read_room_id` plus one bulk Bag read. `ChestBerryTracker._MAX_PENDING_SECONDS` is a real duration, not a poll
# count: unlike every other window in ram_client, shrinking that one drops a check the player already earned.

# A write is trusted only after this many CONSECUTIVE polls. One check ~1s after the write is a single data
# point: if the in-battle logic that reverts it runs per turn or per animation, that check can land before the
# revert. The streak resets to 0 on any poll that reads back under baseline.
ITEM_DELIVERY_CONFIRM_STREAK = 5  # consecutive confirmed polls required (~5 seconds at POLL_INTERVAL_INGAME)

# Hard ceiling on how long an item may wait for battle to end before give_items() delivers anyway. Its only job
# is to guarantee a misbehaving battle-state signal can DELAY a delivery, never block one -- such a gate has got
# permanently stuck several times here, from a different cause each time -- so it may never be None or infinity.
# 10 minutes, not the 45s it was: 45s is shorter than a real battle, and when it tripped the item landed INTO
# the battle. Still well past the tracker's own ~30s self-healing window.
ITEM_DELIVERY_MAX_BATTLE_WAIT_SECONDS = 600  # 10 minutes -- a defense-in-depth backstop, not the primary fix


def _normalize_for_match(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


# Where the player's patched ISO is, for the FST guard's baseline. First hit wins: `/fstiso` (which persists the
# path), POKEMON_XD_ISO, a previously stored path. Optional -- without it the guard works from a validated RAM
# snapshot, and the ISO only adds repair of damage present before the client connected.

FST_ISO_ENV_VAR = "POKEMON_XD_ISO"


def _fst_iso_settings_path():
    from pathlib import Path
    try:
        base = Path(Utils.user_path("data"))
    except Exception:
        base = Path(Utils.local_path("data")) if hasattr(Utils, "local_path") else Path(".")
    return base / "pokemon_xd_fst_iso.txt"


def remember_fst_iso(path: str) -> None:
    try:
        target = _fst_iso_settings_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(path), encoding="utf-8")
    except Exception:
        pass  # purely a convenience; never let this break the client


def resolve_fst_iso() -> "Optional[str]":
    from pathlib import Path
    candidates = [os.environ.get(FST_ISO_ENV_VAR)]
    try:
        stored = _fst_iso_settings_path()
        if stored.is_file():
            candidates.append(stored.read_text(encoding="utf-8").strip())
    except Exception:
        pass
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    return None


class PokemonXDCommandProcessor(ClientCommandProcessor):
    """Command processor for Pokemon XD client commands."""

    def _cmd_dolphin(self) -> None:
        """Display the current Dolphin emulator connection status."""
        if isinstance(self.ctx, PokemonXDContext):
            logger.info(f"Dolphin status: {self.ctx.dolphin_status}")

    def _cmd_verbose(self, state: str = "") -> None:
        """DEBUG: Narrates almost every debug message. /verbose ON/OFF"""
        if not isinstance(self.ctx, PokemonXDContext):
            return
        word = state.strip().lower()
        if word in ("on", "true", "1", "yes"):
            self.ctx.verbose_logging = True
        elif word in ("off", "false", "0", "no"):
            self.ctx.verbose_logging = False
        elif word == "":
            self.ctx.verbose_logging = not self.ctx.verbose_logging
        else:
            logger.info(f"/verbose: don't understand {state!r}. Usage: /verbose [on|off]")
            return
        if self.ctx.verbose_logging:
            logger.info("Verbose logging ON -- progress narration (room changes, story bytes, travel bits, "
                        "key-item reconciliation, save-block pauses) will be printed until you run "
                        "`/verbose off`.")
        else:
            logger.info("Verbose logging OFF -- only connection status, received items, sent checks and real "
                        "failures will be printed.")

    def _cmd_fstiso(self, *path_words: str) -> None:
        """DEBUG: Check RAM repair count."""
        if not isinstance(self.ctx, PokemonXDContext):
            return
        path = " ".join(path_words).strip().strip('"')
        if not path:
            current = self.ctx.fst_guard.disc_source or resolve_fst_iso() or "(none set)"
            logger.info(f"FST repair reference ISO: {current}. Set one with: /fstiso <path to your .iso/.ciso>")
            return
        self.ctx.apply_fst_iso(path, remember=True)

    def _cmd_story(self) -> None:
        """DEBUG: Show the current story byte."""
        if isinstance(self.ctx, PokemonXDContext):
            logger.info(self.ctx.story_tracker.describe())

    def _cmd_mirorforce(self, place: str = "") -> None:
        """Make Miror B. appear where you say, on your next step.

        Usage: /mirorforce pyrite | realgam | rock | oasis | cave | kaminko     (/mirorforce alone lists them)
        """
        if not isinstance(self.ctx, PokemonXDContext):
            return
        ctx = self.ctx
        key = place.strip().lower()
        if key == "kaminko":
            # Nothing to arm: his copy stands outside Kaminko's House in every seed.
            queue = ram_client.read_miror_queue(ctx.block_base) if ctx.block_base is not None else None
            logger.info("/mirorforce kaminko: Miror B. always stands outside Kaminko's House, by the entrance. "
                        + ("He has nothing queued right now, so he won't fight." if queue == [] else
                           f"He fights for the {len(queue)} Shadow(s) in his queue (/mirorqueue lists them)."
                           if queue else "His queue isn't readable right now."))
            return
        if not key:
            state = ram_client.miror_state()
            logger.info("/mirorforce <place>: " + " | ".join(sorted(ram_client.MIROR_PLACE_IDS) + ["kaminko"]))
            if state is None:
                logger.info("  The engine is not readable right now (no save loaded?).")
                return
            v, ids, c = state["values"], state["ids"], state["consts"]
            logger.info("  signal %d/%d, place %d, start flag %d %s, suppress %d",
                        v["signal"], c[ram_client.MIROR_SIGNAL_MAX_OFF] - 1, v["place"], ids["start"],
                        "SET" if v["start"] else "CLEAR -- nothing can happen until you beat him once",
                        v["suppress"])
            logger.info("  %s", ctx.miror_force.describe())
            return
        if key not in ram_client.MIROR_PLACE_IDS:
            logger.info("/mirorforce: don't know %r. One of: %s",
                        place, ", ".join(sorted(ram_client.MIROR_PLACE_IDS)))
            return
        try:
            ok, message = ctx.miror_force.arm(key)
        except Exception:
            logger.debug("Pokemon XD: /mirorforce failed", exc_info=True)
            logger.info("/mirorforce failed -- see the log with `/verbose on`.")
            return
        logger.info("%s", message)

    def _cmd_unlocks(self) -> None:
        """DEBUG: Shows which `Unlock -` checks are sent, and which destinations the game has revealed on the map."""
        if not isinstance(self.ctx, PokemonXDContext):
            return
        ctx = self.ctx
        if not ctx.randomize_travel_locations:
            logger.info("/unlocks: travel shuffle is off in this seed, so there are no `Unlock -` checks.")
            return
        # ADDENDUM 434: an `Unlock -` check goes out when the GAME sets one of the destination's map bits -- any bit
        # while the destination is locked, its partial bit once it is granted -- not off the story byte.
        received = set(ctx.received_travel_locations or ())
        record_base = (None if ctx.block_base is None
                       else ctx.block_base + travel_locations.TRAVEL_RECORD_OFFSET_FROM_BLOCK_BASE)
        width = max(len(name) for name in travel_locations.TRAVEL_LOCATION_NAMES)
        logger.info("Unlock checks -- each is sent when the game reveals that destination on the map (sets one "
                    "of its travel bits), whether or not you hold its Travel Unlock:")
        waiting = 0
        for name in travel_locations.TRAVEL_LOCATION_NAMES:
            if name in _TRAVEL_CLEAR_EXEMPT:
                continue
            location_id = LOCATION_NAME_TO_ID.get(travel_locations.travel_unlock_location_name(name))
            if location_id is not None and location_id in ctx.checked_locations:
                verdict = "SENT"
            elif name in ctx.travel_revealed:
                verdict = "revealed -- sending"
            else:
                verdict = "waiting for the game to reveal it"
                waiting += 1
            bits = ""
            if record_base is not None:
                try:
                    values = []
                    for destination in travel_locations.travel_unlock_members(name):
                        bit = travel_locations.TRAVEL_LOCATION_BITS[destination]
                        byte = ram_client.read_bytes(record_base + bit.byte_offset, 1)[0]
                        values.append(f"+0x{bit.byte_offset:02X}=0x{byte & bit.all_bits:02X}")
                    bits = " ".join(values)
                except Exception:
                    bits = "(unreadable)"
            held_text = "held" if name in received else "locked"
            logger.info(f"  {name.ljust(width)}  {held_text.ljust(6)}  {bits.ljust(12)}  {verdict}")
        if waiting:
            logger.info(f"  {waiting} waiting. A reveal is recorded the poll it happens and survives a restart.")

    def _cmd_storybyte(self, value: str = "") -> None:
        """DEBUG: Read or set the global story byte, in hex. `/storybyte` reads it; `/storybyte 27` sets it."""
        if not isinstance(self.ctx, PokemonXDContext):
            return
        ctx = self.ctx
        if ctx.block_base is None:
            logger.info("Not hooked to a running game yet -- nothing to read or write.")
            return
        current = ram_client.read_story_byte(ctx.block_base)
        # The whole variable, not just the eight bits this command is named after.
        live = ram_client.read_story_value(ctx.block_base)
        shown = "unreadable" if current is None else f"0x{current:02X}"
        if current is not None and live is not None:
            shown += f" (story variable {live})"
        text = value.strip().lower()
        if not text:
            logger.info(f"Story byte is {shown}. Set it with `/storybyte 27` (hex).")
            return
        try:
            parsed = int(text[1:], 10) if text.startswith("d") else int(text, 16)
        except ValueError:
            logger.info(f"`{value}` is not a number. Use hex (`/storybyte 6e`) or decimal (`/storybyte d110`).")
            return
        if not 0 <= parsed <= 0xFF:
            logger.info(f"0x{parsed:X} is outside a byte (0x00-0xFF).")
            return
        written, previous = ram_client.write_story_byte(
            ctx.block_base, parsed, write_log=ctx.story_write_log, why="/storybyte (manual)",
        )
        if not written:
            logger.info("The write failed -- the game may not be running, or the save block moved.")
            return
        # Ownership channel, so the witness cannot bank this as progress the game made.
        ctx.area_story_memory.last_written_target = parsed
        readback = ram_client.read_story_byte(ctx.block_base)
        readback_value = ram_client.read_story_value(ctx.block_base)
        was = "unreadable" if previous is None else f"0x{previous:02X}"
        now = "unreadable" if readback is None else f"0x{readback:02X}"
        if readback is not None and readback_value is not None:
            now += f" ({readback_value})"
        logger.info(f"Story byte: {was} -> {now} (wrote 0x{parsed:02X}). No checks were credited for it. "
                    f"The client's own story rules may write over this on the next poll.")
        # A byte with no story value behind it is not a state the game can be in. Still written, never silently.
        from .game_data import story_bytes as _sb
        if _sb.story_value_for_byte(parsed) is None:
            logger.info(f"  Note: 0x{parsed:02X} covers story values {parsed * 8}..{parsed * 8 + 7}, and the "
                        f"game only ever holds multiples of {ram_client.STORY_VALUE_STEP} -- so there is no "
                        f"state behind this byte and no script will match it. The nearest real rungs are "
                        f"0x{_sb.story_byte_for_value((parsed * 8 // 10) * 10):02X} and "
                        f"0x{_sb.story_byte_for_value(((parsed * 8 + 9) // 10 + 1) * 10):02X}.")
        _save_story_write_log(ctx)

    def _cmd_trainers(self, *words: str) -> None:
        """DEBUG: Lists all trainers and their team."""
        if not isinstance(self.ctx, PokemonXDContext):
            return
        from .game_data import trainer_roster

        query = " ".join(words).strip()
        if not query:
            total = len(trainer_roster.TRAINERS)
            logger.info(f"{total} trainers in the roster, {len(trainer_roster.UNIQUELY_NAMED)} of them with a "
                        f"name no other trainer shares. Try `/trainers miror` or `/trainers 32`.")
            return
        if query.isdigit():
            found = [t for t in trainer_roster.TRAINERS if t["index"] == int(query)]
        else:
            needle = query.upper()
            found = [t for t in trainer_roster.TRAINERS if needle in t["name"].upper()]
        if not found:
            logger.info(f"No trainer matches {query!r}.")
            return
        logger.info(f"{len(found)} match(es) for {query!r}:")
        for t in found[:25]:
            shared = "" if t["total_with_name"] == 1 else f" (#{t['occurrence']} of {t['total_with_name']})"
            logger.info(f"  index {t['index']:<4} {t['name']}{shared}  class {t['trainer_class']}  "
                        f"party {t['party_size']}")
        if len(found) > 25:
            logger.info(f"  ... and {len(found) - 25} more")

    def _cmd_missables(self, *args: str) -> None:
        """Missable trainer checks: which ones this seed sends for you, and at what point in the story."""
        if not isinstance(self.ctx, PokemonXDContext):
            return
        # ADDENDUM 402: the schedule is invisible otherwise -- a check that arrives on its own with no way to see
        # why reads as a bug, and one that has not arrived yet reads as a missed fight.
        seed_ids = seed_location_ids(self.ctx)
        in_seed = ({ID_TO_LOCATION_NAME[i] for i in seed_ids if i in ID_TO_LOCATION_NAME}
                   if seed_ids else None)
        kaminko = getattr(self.ctx, "kaminko_trainers", False)
        if in_seed is not None and kaminko:
            in_seed -= kaminko_autosend_labels()
        checked = {ID_TO_LOCATION_NAME[i] for i in self.ctx.checked_locations if i in ID_TO_LOCATION_NAME}
        for line in self.ctx.missable_autosender.describe(in_seed, checked, _missable_area_progress(self.ctx)):
            logger.info(line)
        if kaminko:
            logger.info("Kaminko Missable Trainers is on: a missed trainer is not sent for you -- it waits outside "
                        "Kaminko's House once its area's story is past it, and beating it there sends its check.")

    def _cmd_toggledeathlink(self, *args: str) -> None:
        """Turn Death Link on or off for this slot (ADDENDUM 477). `/toggledeathlink on|off`, or no argument to flip it.
        Remembered for this seed and slot across reconnects; it overrides the YAML's `death_link`."""
        if not isinstance(self.ctx, PokemonXDContext):
            return
        ctx = self.ctx
        choice = (args[0].strip().lower() if args else "")
        if choice in ("on", "true", "1", "yes"):
            enabled = True
        elif choice in ("off", "false", "0", "no"):
            enabled = False
        elif choice:
            logger.info("Usage: /toggledeathlink [on|off] -- no argument flips it.")
            return
        else:
            enabled = not ctx.death_link_bridge.enabled
        ctx.death_link_bridge.enabled = enabled
        # A fence or a half-seen white-out from before the switch must not fire the moment it comes back on.
        ctx.death_link_bridge._ours = False
        ctx.death_link_bridge._was_wiped = False
        ctx.death_link_bridge._was_annihilated = False
        ctx.death_link_override = enabled
        Utils.async_start(ctx.update_death_link(enabled))
        try:
            if ctx.slot is not None:
                ctx._save_local_state()
        except Exception:
            pass
        logger.info(f"Death Link is now {'ON' if enabled else 'OFF'} for this slot"
                    + (" -- deaths are sent and received." if enabled else " -- nothing is sent or received.")
                    + ("" if ctx.slot is not None else " (Not connected yet: it applies when you connect.)"))

    def _cmd_missableshadows(self) -> None:
        """Which Shadows sit on missable trainers this seed, and which have gone to Miror B."""
        if not isinstance(self.ctx, PokemonXDContext):
            return
        for line in self.ctx.missable_shadow_pusher.describe():
            logger.info(line)

    def _cmd_wondertrade(self, *args: str) -> None:
        """Wonder trade with the team's other Pokemon games. `/wondertrade send <box> <slot>` sends that PC Pokemon;
        the next one another player sends arrives in your PC. `/wondertrade box <n>` lists a box. No argument: status."""
        if not isinstance(self.ctx, PokemonXDContext):
            return
        ctx = self.ctx
        words = [a.lower() for a in args]
        if words[:1] == ["send"] and len(words) == 3 and words[1].isdigit() and words[2].isdigit():
            logger.info(ctx.wonder_trade.prepare_send(ctx, int(words[1]), int(words[2])))
            return
        if words[:1] == ["box"] and len(words) == 2 and words[1].isdigit():
            for line in describe_wonder_trade_box(ctx, int(words[1])):
                logger.info(line)
            return
        if words and words != ["status"]:
            logger.info("Usage: /wondertrade send <box> <slot>, /wondertrade box <n>, or /wondertrade for the status.")
            return
        for line in ctx.wonder_trade.describe(ctx):
            logger.info(line)

    def _cmd_mirorqueue(self) -> None:
        """Lists the Shadows Miror B. is holding -- the ones that ran from you, plus any the client handed him."""
        if not isinstance(self.ctx, PokemonXDContext):
            return
        ctx = self.ctx
        if ctx.block_base is None:
            logger.info("Not hooked to the game yet.")
            return
        for line in describe_miror_queue(ctx):
            logger.info(line)

    def _cmd_kaminko(self) -> None:
        """Who stands in the trainer spots outside Kaminko's House (Kaminko Missable Trainers)."""
        if not isinstance(self.ctx, PokemonXDContext):
            return
        slots = self.ctx.kaminko_slots
        state = {None: "not seen yet", True: "fights (his queue holds a Shadow)", False: "waits (his queue is empty)"}
        logger.info(f"Miror B. outside the manor: {state[slots.miror_queued]}.")
        if not getattr(self.ctx, "kaminko_trainers", False):
            logger.info("Kaminko Missable Trainers is off in this seed.")
            return
        logger.info(slots.describe())
        logger.info(f"Beaten there so far: {len(self.ctx.kaminko_won)}.")
        for line in describe_kaminko_trainers(self.ctx):
            logger.info(line)

    def _cmd_pokespots(self) -> None:
        """Show each Poke Spot's snacks, the Pokemon waiting there, its 'player is here' flag, and Miror B.'s place."""
        if not isinstance(self.ctx, PokemonXDContext):
            return
        if self.ctx.block_base is None:
            logger.info("Not hooked to the game yet.")
            return
        for line in ram_client.describe_pokespots():
            logger.info(line)

    def _cmd_pokespotforce(self, *args: str) -> None:
        """Put a Pokemon at a Poke Spot, snacks or not: /pokespotforce rock|oasis|cave [number or name]. With no
        number or name it picks one of that spot's five at random; on its own, lists each spot's five."""
        if not isinstance(self.ctx, PokemonXDContext):
            return
        if self.ctx.block_base is None:
            logger.info("Not hooked to the game yet.")
            return
        for line in force_pokespot_encounter(self.ctx, args):
            logger.info(line)

    def _cmd_animations(self, *args: str) -> None:
        """Turn move animations on or off: `/animations on|off`, or no argument to flip. Works on any patched ISO,
        whatever the YAML said, and is remembered for this seed and slot."""
        if not isinstance(self.ctx, PokemonXDContext):
            return
        ctx = self.ctx
        choice = (args[0].strip().lower() if args else "")
        if choice in ("on", "true", "1", "yes"):
            playing = True
        elif choice in ("off", "false", "0", "no"):
            playing = False
        elif choice:
            logger.info("Usage: /animations [on|off] -- no argument flips it.")
            return
        else:
            playing = animations_disabled(ctx)
        ctx.animations_override = playing
        ctx._animation_guard_due = 0.0
        try:
            if ctx.slot is not None:
                ctx._save_local_state()
        except Exception:
            pass
        logger.info(f"Move animations are now {'ON' if playing else 'OFF'} for this slot"
                    + ("" if ctx.slot is not None else " (Not connected yet: it applies when you connect).")
                    + " It takes effect within a few seconds.")

    def _cmd_deathlink(self, *args: str) -> None:
        """DEBUG: Death Link status -- what has been sent, received, and which signal is doing the work."""
        if not isinstance(self.ctx, PokemonXDContext):
            return
        # ADDENDUM 390: `describe()` shipped with ADDENDUM 351 and nothing ever called it, so a player whose
        # Death Link was silently sending nothing had no way to say so with a number. This is that way.
        logger.info(self.ctx.death_link_bridge.describe())
        logger.info(self.ctx.whiteout_latch.describe())   # ADDENDUM 400
        logger.info(self.ctx.whiteout_counter.describe())  # ADDENDUM 475
        watch = self.ctx.battle_party_watch                # ADDENDUM 472
        logger.info(f"Battle watch: {watch.locates} locate(s), {watch.full_locates} full-memory locate(s), "
                    f"{watch.stale_resets} stale record set(s) dropped, "
                    + (f"watching {len(watch.addresses)} record(s) now." if watch.addresses else "not in a battle."))
        if not self.ctx.death_link_bridge.enabled:
            logger.info("  Turn it on with /toggledeathlink (this slot, remembered), or `death_link: true` in your YAML "
                        "for a new seed.")
            return
        flag = ram_client.read_annihilation_flag()
        logger.info(
            "  The game's annihilation flag reads "
            + ("unavailable -- its tables have not initialised yet, or this build puts them elsewhere. "
               "Death Link falls back to watching your party's HP." if flag is None
               else ("SET (a white-out is in progress)" if flag else "clear"))
        )
        if self.ctx.block_base is None:
            logger.info("  Save data not resolved yet, so the party cannot be read this moment.")
            return
        try:
            members = ram_client.read_party(self.ctx.block_base)
        except Exception as exc:
            logger.info(f"  Party could not be read ({exc}).")
            return
        if not members:
            logger.info("  No readable party right now -- that reads as 'no answer', never as a death.")
            return
        logger.info("  Party: " + ", ".join(f"{m.hp}/{m.max_hp}" for m in members))

    def _cmd_chests(self, *args: str) -> None:
        """DEBUG: Lists chests in the room, with their coordinates."""
        if not isinstance(self.ctx, PokemonXDContext):
            return
        from .game_data import chest_table

        if args and args[0].isdigit():
            room_id: "Optional[int]" = int(args[0])
        else:
            room_id = self.ctx.room_tracker.current
            if room_id is None:
                logger.info("Don't know which room you're in yet -- walk through a doorway and try again, "
                            "or use `/chests <room id>`.")
                return
        found = chest_table.chests_in_room(room_id)
        header = f"{ram_client.room_name(room_id)} [room {room_id}]"
        if not found:
            logger.info(f"{header}: no chests in this room.")
            return
        fenced = sum(1 for c in found if c["item"] >= 500)
        note = ""
        if fenced:
            note = (f"  ({fenced} of these hold a key item and are NOT randomized -- see ADDENDUM 134; they "
                    f"keep their real contents and are not AP locations)")
        logger.info(f"{header}: {len(found)} chest(s).{note}")
        # Print each chest's berry: that is its identity -- see it in your Bag and you know which chest opened.
        from .game_data import chest_berries

        for chest in found:
            line = "  " + chest_table.describe_chest(chest)
            assigned = chest_berries.berry_for_chest(chest["chest"])
            if assigned is not None and chest["chest"] in ram_client.CHEST_ID_TO_LOCATION:
                berry_id, quantity = assigned
                name = chest_berries.CHEST_BERRY_ID_TO_NAME.get(berry_id, str(berry_id))
                line += f"   -> {name} x{quantity}"
            logger.info(line)
        held = self.ctx.chest_berry_tracker.pending
        if held:
            logger.info("  a pickup is currently held waiting for a readable room -- it has not been lost, "
                        "and will be credited as soon as the room resolves.")
        # A non-zero count means some chest's measured open-flag belongs to a different chest, and names which.
        tracker = self.ctx.chest_berry_tracker
        if tracker.flag_disagreed_with_room:
            logger.info(f"  [!] {tracker.flag_disagreed_with_room} pickup(s) this session had a chest FLAG "
                        f"naming a different chest than the room did. The room won, so nothing was "
                        f"mis-credited -- but a chest's measured open-flag is wrong. `/chestflags` in the room "
                        f"where it happened will show which bit really moved.")
        if tracker.flag_corroborated or tracker.flag_transitions_expired:
            logger.info(f"  flag fast path: {tracker.flag_corroborated} pickup(s) credited on the flag+berry "
                        f"pair, {tracker.flag_transitions_seen} transition(s) seen, "
                        f"{tracker.flag_transitions_expired} expired unused "
                        f"(a number well above zero means the corroboration window is too short).")

    def _cmd_chestflags(self, *args: str) -> None:
        """DEBUG: Shows chest open/closed status through their bitfield."""
        if not isinstance(self.ctx, PokemonXDContext):
            return
        if self.ctx.block_base is None:
            logger.info("No player-state block yet -- load a save and try again.")
            return
        from .game_data import chest_flags

        # Deliberately wider than chest_flag_span(): the original dumps show flag traffic well below the
        # modelled region, so the unvalidated clusters' real bits are somewhere the model does not look.
        first, length = 0x10700, 0x120
        try:
            block = ram_client.read_bytes(self.ctx.block_base + first, length)
        except Exception as exc:  # noqa: BLE001 -- a diagnostic must report its own failure, not raise
            logger.info(f"Could not read the flag region: {exc}")
            return
        logger.info(f"chest-flag region, BLOCK_BASE+0x{first:05X} .. +0x{first + length - 1:05X} "
                    f"(BLOCK_BASE = 0x{self.ctx.block_base:08X})")
        for row in range(0, length, 16):
            chunk = block[row:row + 16]
            if not any(chunk):
                continue   # the region is mostly empty; printing the zeros buries the signal
            logger.info(f"  +0x{first + row:05X}: " + " ".join(f"{b:02X}" for b in chunk))
        set_bits = [chest_flags.flag_at_byte_bit(first + i, bit)
                    for i, byte in enumerate(block) for bit in range(8) if byte & (1 << bit)]
        decoded = sorted(f for f in set_bits if f is not None)
        logger.info(f"  {len(set_bits)} bit(s) set: {len(decoded)} chest flag(s) {decoded}, "
                    f"{len(set_bits) - len(decoded)} other game flag(s)")
        open_now = sorted(c for c in chest_flags.flagged_chest_ids()
                          if (loc := chest_flags.chest_byte_offset_and_mask(c))
                          and first <= loc[0] < first + length
                          and block[loc[0] - first] & loc[1])
        logger.info(f"  chests open: {open_now}")

    def _cmd_battle(self) -> None:
        """DEBUG: Shows whether you are detected as in-battle."""
        if not isinstance(self.ctx, PokemonXDContext):
            return
        # The step counter gates new deliveries; the battle readings only take over when it is unreadable.
        steps = ram_client.read_step_counter(self.ctx.block_base)
        logger.info(f"delivery gate: {self.ctx._delivery_gate_name} -- "
                    f"step counter = {steps if steps is not None else 'unreadable'}. "
                    f"Walk a step and run this again: the number should rise.")
        logger.info(f"  {self.ctx.step_gate.describe()}")
        try:
            flag = ram_client.read_battle_ui_flag()
            mode = ram_client.read_battle_mode_enum()
            anchor = ram_client.read_battle_struct_anchor()
        except Exception as exc:  # noqa: BLE001 -- a diagnostic reports its own failure
            logger.info(f"Couldn't read battle state: {exc}")
            return
        state = "IN BATTLE or a full-screen menu -- items are being held" if flag else "free -- items can deliver"
        logger.info(f"battle gate  0x{ram_client.BATTLE_UI_FLAG_ADDRESS:08X} = {flag}   ({state})")
        mode_name = {0: "normal", 1: "just after a battle", 2: "cutscene/dialogue"}.get(mode, "unknown")
        logger.info(f"  mode enum  0x{ram_client.BATTLE_MODE_ENUM_ADDRESS:08X} = {mode} ({mode_name}) "
                    f"-- observation only, nothing gates on it")
        logger.info(f"  retired anchor 0x{ram_client.BATTLE_STRUCT_ANCHOR_ADDRESS:08X} = 0x{anchor:08X} "
                    f"(ADDENDUM 202 -- expected 0 always on this build)")
        logger.info(f"  debounce: {self.ctx.battle_state_tracker._consecutive_zero}"
                    f"/{ram_client.BattleStateTracker.CONFIRM_POLLS} consecutive clear polls")
        # This overrides the flag and debounce above: `BattleStateTracker.poll` returns False outright when the
        # defeat tracker says a battle is unresolved, so "free" can print while every delivery is held.
        if self.ctx.shuffle_trainer_defeats:
            for line in self.ctx.trainer_defeat_tracker.describe_blocking():
                logger.info(line)
        else:
            logger.info("  unresolved battle: not consulted (this seed does not shuffle trainer defeats)")

    def _cmd_room(self) -> None:
        """DEBUG: Shows which room you're in by ID."""
        if isinstance(self.ctx, PokemonXDContext):
            logger.info(self.ctx.room_tracker.describe())

    def _cmd_shops(self) -> None:
        """DEBUG: Shows shop info."""
        ctx = self.ctx
        if not isinstance(ctx, PokemonXDContext):
            return
        if not ctx.randomize_shops:
            logger.info("Shop randomization is off for this seed -- shops sell their real stock and there "
                        "are no shop checks.")
            return
        logger.info("1. Scout      : %d shop line(s) known%s",
                    len(ctx.scouted_shop_items),
                    "" if ctx.scouted_shop_items else " -- shelves will say \"Not scouted yet.\"")
        if ctx.shop_line_classifications:
            counts: "dict[str, int]" = {}
            for value in ctx.shop_line_classifications.values():
                counts[value] = counts.get(value, 0) + 1
            logger.info("     by class : %s",
                        ", ".join(f"{name} {count}" for name, count in sorted(counts.items())))
        for problem in ctx.shop_scout_problems[:5]:
            logger.info("     problem  : %s", problem)
        if len(ctx.shop_scout_problems) > 5:
            logger.info("     ... and %d more", len(ctx.shop_scout_problems) - 5)
        renamer = ctx.item_name_renamer
        logger.info("2. Shelf names: %s", "on" if (renamer.enabled and renamer.verified) else
                    ("off -- " + (renamer.verify_failures[0] if renamer.verify_failures else "not verified")))
        writer = ctx.item_description_writer
        if not writer.enabled:
            located = "off -- %s" % (writer.last_error or "disabled")
        elif writer.table_base is None:
            # Say which rate the sweep is at: "not in RAM" and "not in RAM, and we have stopped looking hard"
            # look identical to a player and are not the same state.
            located = ("table not currently in RAM (normal with the shop menu closed -- it loads with the "
                       "menu); %d scan(s), %d found nothing, next scan in up to %.2fs, %d known address(es)"
                       % (writer.scans, writer.failed_scans, writer._scan_interval, len(writer._hot_bases)))
        else:
            located = "table at 0x%08X, %d write(s), %d reload(s) seen, %d found by remembered address" % (
                writer.table_base, writer.writes, writer.reloads_detected, writer.hot_hits)
            # ADDENDUM 427: a second copy is the Realgam shape -- the one being written may not be the one shown.
            if writer.extra_bases:
                located += "; also writing %d other cop%s at %s" % (
                    len(writer.extra_bases), "y" if len(writer.extra_bases) == 1 else "ies",
                    ", ".join("0x%08X" % b for b in writer.extra_bases))
        logger.info("3. Descriptions: %s", located)
        prices = ctx.item_price_writer
        if not prices.enabled:
            price_state = "off -- %s" % (prices.verify_failures[0] if prices.verify_failures else "disabled")
        elif prices.table_base is None:
            price_state = "Items table not resolved yet"
        else:
            price_state = "Items table at 0x%08X, %d write(s)" % (prices.table_base, prices.writes)
        logger.info("4. Prices     : %s", price_state)
        logger.info("5. Purchases  : %s",
                    ", ".join(f"room {room}: {count} line(s)"
                              for room, count in sorted(ctx.shop_tracker.slots_credited.items()))
                    or "none credited yet")
        if ctx.shop_tracker.purchases_outside_a_shop:
            logger.info("     %d berry increase(s) seen outside any shop -- credited nothing",
                        ctx.shop_tracker.purchases_outside_a_shop)
        # ADDENDUM 394: WHERE, not just how many. "Credited nothing, by design" is only true when the room
        # really is not a shop; when it is a shop whose id this project has wrong, that line was reporting a
        # silent loss of every check in that shop as intended behaviour. The Outskirt Stand was 164, and is 163.
        # ADDENDUM 395: if the shelf keeps reverting, this is the line that says so.
        if ctx.item_name_renamer.reverts_detected or ctx.item_price_writer.reverts_detected:
            logger.info("     shelf put back by the game %d time(s) (names) / %d (prices) -- rewritten each "
                        "time", ctx.item_name_renamer.reverts_detected,
                        ctx.item_price_writer.reverts_detected)
        if ctx.shop_tracker.unknown_shop_rooms:
            logger.info("     rooms involved: %s", ", ".join(
                f"room {room} ({count})"
                for room, count in sorted(ctx.shop_tracker.unknown_shop_rooms.items())))
            logger.info("     If you bought those at a shop counter, that room is a SHOP THIS CLIENT DOES NOT "
                        "KNOW and its checks are not being credited -- please report the room number.")

    def _cmd_saveclock(self) -> None:
        """Shows the play time the client last read, the saves it has seen, and the last reload it caught."""
        if isinstance(self.ctx, PokemonXDContext):
            for line in self.ctx.save_timeline.describe():
                logger.info(line)
            held = self.ctx.save_distrust
            logger.info(f"  Checks held back: {held['saving']} poll(s) while saving or loading, "
                        f"{held['clock jump']} play-time jump(s) (another save's data came in).")

    def _cmd_progress(self) -> None:
        """DEBUG: Shows chest information."""
        if isinstance(self.ctx, PokemonXDContext):
            for line in self.ctx.story_progress.describe():
                logger.info(line)
            # Candidate crash-redelivery witness, unconfirmed. To confirm: walk ~20 steps and re-run (should rise
            # by about that much), then save, reset Dolphin, load and re-run (must read its value at the save).
            if self.ctx.block_base is not None:
                value = ram_client.read_progress_counter(self.ctx.block_base)
                if value is None:
                    logger.info("Save progress counter: unreadable right now.")
                else:
                    logger.info(
                        f"Save progress counter (ADDENDUM 286, UNCONFIRMED): {value}. This is a candidate "
                        f"witness for crash re-delivery -- it should rise as you walk and fall back to its "
                        f"saved value after a reload. Nothing depends on it yet."
                    )

    def _cmd_seedcheck(self) -> None:
        """DEBUG: Checks ap world version against seed."""
        if isinstance(self.ctx, PokemonXDContext):
            self.ctx.print_seed_location_check()

    def _cmd_keyitems(self, *args: str) -> None:
        """Shows which key items you own."""
        ctx = self.ctx
        managed = managed_key_item_ids(ctx)
        # block_base is passed so the readout can name the pocket each id was last seen in.
        for line in ctx.key_item_reconciler.describe(should_have_key_item_ids(ctx), managed,
                                                     block_base=ctx.block_base or 0):
            logger.info(line)
        for line in key_item_sources(ctx):            # ADDENDUM 420
            logger.info(line)
        logger.info(ctx.music_disc_hold.describe())   # ADDENDUM 419
        logger.info(ctx.machine_part_hold.describe())  # ADDENDUM 421
        logger.info(ctx.lab_memo_hold.describe())      # ADDENDUM 452
        try:   # ADDENDUM 458: why the hold is (or is not) armed, in one line
            logger.info("  HQ Lab hold inputs: Machine Part "
                        + ("seen" if machine_part_obtained(ctx) else "NOT seen")
                        + ", Krane Memos 3-5 " + ("handed over" if lab_memos_received(ctx) else "not handed over")
                        + ", server items " + ("synced" if _lab_hold_inputs_ready(ctx) else "NOT synced yet")
                        + (", latched" if ctx.lab_memo_hold.latched else "")
                        + ", lab reached 0x0F " + ("yes" if ctx.lab_memo_hold.lab_reached else "NOT yet")   # ADDENDUM 464
                        + ", Krane Memos 1-2 " + ("received" if lab_memos_received(ctx, ram_client.LAB_MEMO_ARM_MEMOS)
                                                  else "NOT received")
                        + f", room {ctx.room_tracker.current}"
                        + (" (an HQ Lab room)" if ctx.lab_memo_hold.in_place(ctx.room_tracker.current) else "") + ".")
        except Exception:
            pass
        if ctx.ability_patch:   # ADDENDUM 454: a USE item now -- the game does the work
            logger.info("Ability Swap: on Gateon Port's last shelf (2000). Bag -> USE on a party Pokemon.")

    def _cmd_areas(self, *args: str) -> None:
        """DEBUG: Shows visited areas."""
        ctx = self.ctx
        if not ctx.randomize_travel_locations:
            logger.info("Per-area story-byte memory is off for this seed -- it comes on with Randomize "
                        "Travel Locations, which this seed does not have.")
            return
        for line in ctx.area_story_memory.describe():
            logger.info(line)
        for line in ctx.live_story_bumper.describe():
            logger.info(line)
        # The ceiling each area is held to, and whether the guard has acted -- the other side of "what does this
        # area remember", so it shares this command.
        memory = ctx.area_story_memory
        logger.info(f"  poison guard: {memory.poison_clamps} clamp(s); "
                    f"{memory.declined_above_ceiling} mark(s) refused for being above a ceiling; "
                    f"{memory.declined_poison_no_mark} declined with nothing to restore to; "
                    f"{memory.declined_poison_busy} declined while another writer held the byte")
        if memory.last_poison_clamp is not None:
            region, found, restored = memory.last_poison_clamp
            logger.info(f"    last: {region} was holding 0x{found:02X}, put back to 0x{restored:02X}")
        for region, ceiling in sorted(story_bytes.AREA_GUARD_CEILINGS.items()):
            mark = memory.highest_by_region.get(region)
            logger.info(f"    {region}: ceiling 0x{ceiling:02X}"
                        + (f", highest seen 0x{mark:02X}" if mark is not None else ", never visited"))
        if ctx.area_story_memory_path:
            logger.info(f"  file: {ctx.area_story_memory_path}")

    def _cmd_forgetareas(self) -> None:
        """DEBUG: Clears poisoned area marks."""
        ctx = self.ctx
        if not isinstance(ctx, PokemonXDContext):
            return
        had = len(ctx.area_story_memory.highest_by_region)
        ctx.area_story_memory.highest_by_region = {}
        ctx.area_story_memory.visited = set()
        ctx.area_story_memory.dirty = True
        _save_area_memory(ctx)
        logger.info(f"/forgetareas: cleared {had} remembered area mark(s). Every area will now enter at its "
                    f"floor and re-earn its mark as you play. Use /areas to confirm.")

    def _cmd_bag(self) -> None:
        """DEBUG: Every Bag tab's raw item ids and quantities, with anything in the wrong tab flagged."""
        if not isinstance(self.ctx, PokemonXDContext) or self.ctx.block_base is None:
            logger.info("Not connected to the game yet.")
            return
        base = self.ctx.block_base
        tabs = [("Items", base + ram_client.ITEMS_POCKET_OFFSET, ram_client.ITEMS_POCKET_MAX_SLOTS),
                ("Key Items", base + ram_client.KEY_ITEMS_OFFSET, ram_client.KEY_ITEMS_MAX_SLOTS),
                ("Balls/TMs/Berries (shared array)", base + ram_client.POKEBALL_POCKET_OFFSET,
                 ram_client.POKEBALL_POCKET_ARRAY_SLOT_COUNT)]
        for label, address, slots in tabs:
            held = [s for s in ram_client.read_pocket(address, slots) if not s.empty]
            logger.info(f"{label}: " + (", ".join(f"[{s.index}] {s.item_id} x{s.quantity}" for s in held)
                                        or "empty"))
        # ADDENDUM 446: the PC's item storage, where a full Items pocket overflows to.
        pc_held = [s for s in ram_client.read_pocket(ram_client.pc_items_base(base), ram_client.PC_ITEMS_MAX_SLOTS)
                   if not s.empty]
        logger.info(f"PC item storage ({len(pc_held)}/{ram_client.PC_ITEMS_MAX_SLOTS}"
                    f"{'' if ram_client.pc_storage_looks_valid(base) else ', NOT recognised -- no overflow'}): "
                    + (", ".join(f"[{s.index}] {s.item_id} x{s.quantity}" for s in pc_held) or "empty"))
        misfiled = ram_client.find_misfiled_items(base)
        logger.info("Wrong tab: " + (", ".join(f"{tab} slot {slot}: {_game_item_label(item_id)} x{qty}"
                                                for tab, slot, item_id, qty in misfiled) or "none"))

    def _cmd_purifications(self) -> None:
        """DEBUG: Shows purification scans/rejections."""
        if not isinstance(self.ctx, PokemonXDContext):
            return
        for line in self.ctx.purification_tracker.describe():
            logger.info(line)

    def _cmd_storywatch(self, state: str = "") -> None:
        """DEBUG: Prints story bytes as you progress."""
        if not isinstance(self.ctx, PokemonXDContext):
            return
        word = state.strip().lower()
        if word in ("on", "true", "1", "yes"):
            self.ctx.story_byte_watch = True
        elif word in ("off", "false", "0", "no"):
            self.ctx.story_byte_watch = False
        elif word == "":
            self.ctx.story_byte_watch = not self.ctx.story_byte_watch
        else:
            logger.info(f"/storywatch: don't understand {state!r}. Usage: /storywatch [on|off]")
            return
        if self.ctx.story_byte_watch:
            current = self.ctx.story_tracker.current
            where = "not read yet" if current is None else f"currently 0x{current:02X}"
            logger.info(f"Story-byte watch ON -- every change will be printed ({where}). "
                        f"`/storylog` shows the changes the CLIENT made; this shows all of them.")
        else:
            logger.info("Story-byte watch OFF.")

    def _cmd_storylog(self, *args: str) -> None:
        """DEBUG: Shows story byte changes."""
        ctx = self.ctx
        limit: "int | None" = None
        if args:
            try:
                limit = max(1, int(args[0]))
            except ValueError:
                logger.info(f"`{args[0]}` is not a number -- `/storylog 20` shows the last 20 entries, "
                            f"`/storylog` shows all of them.")
                return
        for line in ctx.story_write_log.describe(limit):
            logger.info(line)
        if ctx.story_write_log_path:
            logger.info(f"  file: {ctx.story_write_log_path}")
        if not ctx.randomize_travel_locations:
            logger.info("  note: this seed has Randomize Travel Locations OFF, so the client never writes the "
                        "story byte -- nothing new will be added to this list.")

    def _cmd_map(self) -> None:
        """DEBUG: Shows location's ID on the map screen when hovering."""
        if not isinstance(self.ctx, PokemonXDContext):
            return
        for line in self.ctx.map_cursor_tracker.describe(self.ctx.room_tracker.current):
            logger.info(line)

    def _cmd_catchscan(self) -> None:
        """DEBUG: Detect catch scans/rejections. (ADDENDUM 483, issue #8: was a second `/catches`, which the
        where-to-catch command below silently replaced.)"""
        if isinstance(self.ctx, PokemonXDContext):
            logger.info(self.ctx.species_catch_tracker.describe())

    def _cmd_teams(self, *name_words: str) -> None:
        """DEBUG: Shows trainer's team."""
        if not isinstance(self.ctx, PokemonXDContext):
            return
        fingerprints = self.ctx.trainer_team_fingerprints
        if not fingerprints:
            logger.info(
                "No team fingerprints in this seed's slot data -- it was generated before ADDENDUM 155, so "
                "repeated trainer names are still told apart by how many you have beaten."
            )
            return
        needle = " ".join(name_words).strip().lower()
        rows = []
        for name, entry in sorted(fingerprints.items()):
            if needle and needle not in name.lower():
                continue
            if isinstance(entry, dict):
                species_names = ", ".join(entry.get("species") or ()) or "?"
                levels = entry.get("levels") or ()
                enhanced = entry.get("levels_enhanced") or ()
                detail = f"  {name}: {species_names}"
                if levels:
                    detail += (
                        f" | levels {'/'.join(str(v) for v in levels)}"
                        f" (enhanced {'/'.join(str(v) for v in enhanced)})"
                    )
                bands = entry.get("hp_bands") or {}
                if bands:
                    # What the client matches on: max HP at THIS encounter's level, not base HP.
                    detail += " | max HP " + ", ".join(
                        f"{name} {band[0]}-{band[1]}" for name, band in sorted(bands.items())
                    )
                shadow_slots = entry.get("shadow_slots") or 0
                if shadow_slots:
                    detail += f" | +{shadow_slots} Shadow slot(s), not fingerprinted"
                rows.append(detail)
            else:  # older bare-list shape
                rows.append(f"  {name}: {', '.join(entry)}")
        if not rows:
            logger.info(f"No repeated-name trainer matches '{needle}'.")
            return
        logger.info(f"Team fingerprints ({len(rows)} shown):")
        for row in rows:
            logger.info(row)
        # The state half, not seed data: whether the client thinks it has seen that team. Visible nowhere else.
        beaten = self.ctx.trainer_defeat_tracker.beaten_team_counts()
        if needle:
            beaten = {k: v for k, v in beaten.items() if needle in k.lower()}
        if beaten:
            logger.info(
                "Distinct teams beaten so far: "
                + ", ".join(f"{name} {count}" for name, count in sorted(beaten.items()))
            )
        ignored = self.ctx.trainer_defeat_tracker.rematches_ignored
        if ignored:
            logger.info(
                f"{ignored} win(s) this session were rematches against a team already beaten, so they "
                "checked off nothing. That is the unique-team rule working, not a missed check."
            )

    def _cmd_roster(self) -> None:
        """DEBUG: Shows trainer team in battle."""
        if not isinstance(self.ctx, PokemonXDContext):
            return
        for line in ram_client.describe_battle_roster_bytes():
            logger.info(line)

    def _cmd_parts(self) -> None:
        """Robo Kyogre Part progress, and the state of the story-byte override it drives."""
        if not isinstance(self.ctx, PokemonXDContext):
            return
        ctx = self.ctx
        if not ctx.robo_kyogre_parts_unlock_citadark:
            logger.info("Robo Kyogre Parts are not enabled for this seed, so none are in the pool.")
            return
        held, required = robo_kyogre_parts_held(ctx), ctx.robo_kyogre_parts_required
        logger.info(f"Robo Kyogre Parts: {held}/{required} -- "
                    + ("Citadark Isle is unlocked." if held >= required > 0
                       else f"{required - held} more to unlock Citadark Isle."))
        logger.info(ctx.story_byte_override.describe())
        # Say WHICH gate is closed: `maintain_story_byte_override` has three silent early returns before the
        # override is consulted and `describe()` sees none of them, so "not armed" was all it could report.
        room = ctx.room_tracker.current
        checks = [
            (f"option `robo_kyogre_parts_unlock_citadark` is on", bool(ctx.robo_kyogre_parts_unlock_citadark)),
            (f"all {required} Part(s) received (you have {held})", required > 0 and held >= required),
            (f"connected to a running game (save block resolved)", ctx.block_base is not None),
            (f"hovering Gateon Port on the map, or standing in a Gateon room -- you are in "
             f"{ram_client.room_name(room)}",
             ctx.story_byte_override.active
             or (room is not None and (room in ram_client.GATEON_ROOM_IDS
                                       or room == ram_client.MAP_SCREEN_ROOM_ID))),
        ]
        logger.info("For the Gateon story byte to be written, ALL of these must be true:")
        for label, ok in checks:
            logger.info(f"  [{'x' if ok else ' '}] {label}")
        blocked = [label for label, ok in checks if not ok]
        if blocked:
            logger.info(f"Not written because: {blocked[0]}")
        logger.info("Gateon Port rooms: "
                    + ", ".join(f"{r} ({ram_client.room_name(r)})"
                                for r in sorted(ram_client.GATEON_ROOM_IDS)))

    def _cmd_openkaminko(self) -> None:
        """DEBUG: Reveals Kaminko's House on the world map."""
        if isinstance(self.ctx, PokemonXDContext):
            logger.info("Kaminko's House is open on the map." if open_kaminko_on_map(self.ctx)
                        else "Couldn't write the map yet -- is the game running with a save loaded?")

    def _cmd_memos(self) -> None:
        """DEBUG: Shows whether krane memos have been counted."""
        if isinstance(self.ctx, PokemonXDContext):
            logger.info(self.ctx.krane_memo_tracker.describe())

    def _cmd_block(self) -> None:
        """DEBUG: Show whether the save menu is writing."""
        if isinstance(self.ctx, PokemonXDContext):
            logger.info(self.ctx.block_stability.describe())

    def _cmd_party(self) -> None:
        """DEBUG: Shows party -- both species sources, plus each live record's level, experience and HP."""
        if not isinstance(self.ctx, PokemonXDContext):
            return
        logger.info(self.ctx.describe_party_sources())
        # ADDENDUM 393: level and experience, because the level-0 wild Pokemon report cannot be checked without
        # them. See `describe_live_party` for what each combination of the two means.
        if self.ctx.block_base is None:
            return
        try:
            for line in ram_client.describe_live_party(self.ctx.block_base):
                logger.info(line)
        except Exception:
            logger.debug("Pokemon XD: live party read failed", exc_info=True)

    def _cmd_area(self) -> None:
        """DEBUG: Shows area/location by NAME not ID."""
        if isinstance(self.ctx, PokemonXDContext):
            logger.info(self.ctx.area_tracker.describe())

    def _cmd_fst(self) -> None:
        """DEBUG: Checks RAM guard."""
        if isinstance(self.ctx, PokemonXDContext):
            logger.info(self.ctx.fst_guard.describe())

    def _cmd_checked(self, *name_words: str) -> None:
        """DEBUG: Manually mark a chest as opened."""
        if not isinstance(self.ctx, PokemonXDContext):
            return
        self.ctx.queue_manual_check(" ".join(name_words))

    def _cmd_getitem(self, *name_words: str) -> None:
        """Notable items not in pool: 99 Master Balls, 99 Rare Candies, 99 Candy Boxes"""
        if not isinstance(self.ctx, PokemonXDContext):
            return
        force_deliver_pending_items(self.ctx, " ".join(name_words))

    def _cmd_remaining(self) -> None:
        """DEBUG: List this seed's Overworld Item (chest/box/NPC-gift) locations that haven't been checked yet -
        the ones '/checked' can mark.
        """
        if not isinstance(self.ctx, PokemonXDContext):
            return
        self.ctx.print_remaining_manual_checks()

    def _cmd_shadowdex(self, *name_words: str) -> None:
        """Print this seed's Shadow Pokemon species map: which species each Shadow Pokemon encounter was
        randomized into (and where to find it), so you always know where a given species ended up or what a
        given Cipher trainer's Shadow Pokemon actually is now. With no arguments, prints the full map; with
        words, fuzzy-matches them against location, original species, or new species names, e.g.
        '/shadowdex miror b' or '/shadowdex charizard'. Only meaningful if Randomize Shadow Species is on."""
        if not isinstance(self.ctx, PokemonXDContext):
            return
        self.ctx.print_shadow_species_map(" ".join(name_words))

    def _cmd_catches(self, *name_words: str) -> None:
        """Where each "Catch - {species}" check is caught this seed -- which trainer holds that Shadow and
        where, or which Poke Spot has it wild. Unchecked ones only; add words to filter, e.g. '/catches luvdisc'
        or '/catches phenac'."""
        if not isinstance(self.ctx, PokemonXDContext):
            return
        self.ctx.print_catch_sources(" ".join(name_words))

    def _cmd_goal(self) -> None:
        """DEBUG: Trigger goal. Use ONLY if you've defeated greevil/mt battle and the goal did not send."""
        if not isinstance(self.ctx, PokemonXDContext):
            return
        Utils.async_start(self.ctx.declare_goal_complete())


class PokemonXDContext(CommonContext):
    """The context for the Pokemon XD: Gale of Darkness client."""

    command_processor = PokemonXDCommandProcessor
    game = "Pokemon XD Gale of Darkness"
    items_handling = 0b111  # receive items from everywhere, like every other simple GameCube client

    def __init__(self, server_address: Optional[str], password: Optional[str]) -> None:
        super().__init__(server_address, password)
        self.dolphin_sync_task: Optional["asyncio.Task[None]"] = None
        self.dolphin_status: str = DOLPHIN_NOT_STARTED

        # Resolved once per Dolphin boot and cached. None means "not resolved yet", not "known not to exist".
        self.block_base: Optional[int] = None
        self.trainer_name: Optional[str] = None   # ADDENDUM 444: read from the save once the block resolves

        self.area_tracker = ram_client.AreaTracker()   # retracted, research only
        # The validated room id -- this is the one that is trusted and logged.
        self.room_tracker = ram_client.RoomTracker()
        self.story_tracker = ram_client.StoryByteTracker()
        # Its own flag, not `verbose_logging`: watching the story byte should not also mean the room-change,
        # travel-bit and key-item firehose.
        self.story_byte_watch: bool = False
        # Map screen's highlighted destination. Read-only; `/map` is its only caller.
        self.map_cursor_tracker = ram_client.MapCursorTracker()
        self.chest_berry_tracker = ram_client.ChestBerryTracker()
        # The room the map was opened FROM. Returning to it is the only thing that tells a back-out from a trip.
        self._room_before_map: "int | None" = None
        self._last_box_scan = 0.0        # see BOX_SCAN_MIN_INTERVAL
        self._last_box_species: "set[int]" = set()
        # Did the last box scan read every slot? An incomplete scan may add a species but must never be read as
        # one having left -- see SpeciesCatchTracker.poll.
        self._last_box_complete: bool = True
        # ONE log shared by every story-byte writer, so `/storylog` is one chronological list. Constructed
        # before its consumers, which take it by reference.
        self.story_write_log = ram_client.StoryByteWriteLog()
        self.area_story_memory = ram_client.AreaStoryByteMemory(write_log=self.story_write_log)
        # The highest story byte the GAME put there. `Unlock -` checks credit from this, not the live byte,
        # which this client writes on every map hover.
        self.story_progress = ram_client.StoryProgressWitness(confirm_polls=2)
        self.live_story_bumper = ram_client.LiveStoryByteBumper(write_log=self.story_write_log)
        # The Snagem hideout loads at 0x63 and fights at 0x62.
        self.snagem_battle_hold = ram_client.SnagemBattleStoryHold(write_log=self.story_write_log)
        # Keeps the Snagem 2F script patched so the Wakin/Gonzap fight can start at all. The script reloads
        # from disc on every map entry, so this re-applies rather than firing once.
        self.snagem_script_patcher = ram_client.SnagemScriptPatcher()
        self.npc_battle_patcher = ram_client.NpcBattleScriptPatcher()
        self.map_level_text = ram_client.MapLevelTextWriter()
        self.pokespot_guard = ram_client.PokeSpotGuard()
        self.key_item_reconciler = ram_client.KeyItemReconciler()
        self.area_story_memory_path: "str | None" = None
        self.story_write_log_path: "str | None" = None
        self.battle_hold = ram_client.BattleActivityHold()
        self._battle_hold_ceiling_logged = False

        # Default-off narration: everything through _note/_note_warn is silent until `/verbose`. Set BEFORE
        # the FstGuard below, whose arming message is gated on it.
        self.verbose_logging: bool = False

        # `log` prints unconditionally -- it only ever carries an actual repair. `log_verbose` carries the two
        # "armed, snapshot taken" startup lines.
        self.fst_guard = fst_guard.FstGuard(
            read=ram_client.read_bytes, write=ram_client.write_bytes, log=logger.info,
            log_verbose=lambda message: _note(self, message),
        )
        # If the ISO path is already known (env var, or a previous /fstiso), load its file table now so the
        # guard is authoritative from the first poll.
        startup_iso = resolve_fst_iso()
        if startup_iso:
            self.apply_fst_iso(startup_iso, remember=False)
        self._fst_iso_hint_logged = False
        self._dolphin_missing_logged = False
        # New item deliveries start on a step. See ram_client.StepCounterGate.
        self.step_gate = ram_client.StepCounterGate()
        self._delivery_gate_name = "step"
        # Counted so the memory-override hint waits until "Dolphin is not open yet" has stopped being
        # plausible. Reset on every successful hook.
        self._hook_failures = 0
        self._override_hint_logged = False

        # Snapshots go through a tracker that discards an implausible PC-box poll and holds a box-only species for
        # several polls: opening the save menu used to send checks for the previous save's Pokemon.
        # `seen_dex_numbers` aliases the tracker's own set.
        self.species_catch_tracker = ram_client.SpeciesCatchTracker()
        # Watches a quiet window of the save block and reports a wholesale rewrite, so block-derived trackers
        # can be SKIPPED for those polls rather than shown a value to argue about. Never gates item delivery.
        self.block_stability = ram_client.BlockStabilityGate()
        self.block_trust = ram_client.BlockTrust()
        # The save clock's own signals feed the trust: a save under way, or a play time that does not follow on.
        self.clock_continuity = ram_client.SaveClockContinuity()
        self.save_distrust = {"saving": 0, "clock jump": 0}
        self._travel_reveal_candidates: "set[str]" = set()
        self.victory_story_streak = 0
        # Awards the five "Story - Krane Memo N" locations off the story byte, and clears the game's own copies.
        self.krane_memo_tracker = ram_client.KraneMemoTracker()
        self._block_churn_logged = False
        # Species newly seen this session (party + optionally PC box) -- feeds "Catch - X" only.
        self.seen_dex_numbers: set[int] = self.species_catch_tracker.seen
        self.purification_tracker = ram_client.PurificationCountTracker()
        self.chest_tracker = ram_client.ChestFlagTracker()
        # Same role as chest_tracker, over a separate set of dummy berry ids (26, since Enigma Berry came out).
        self.shop_tracker = ram_client.ShopPurchaseTracker()
        # ADDENDUM 394: one warning per unknown shop room, not one per purchase.
        self._warned_unknown_shop_rooms: "set[int]" = set()
        # Renames the dummy shop berries IN RAM so the shelf names the check the next purchase sends. Cosmetic:
        # verified once, disables itself on any doubt, can never block a check.
        self.item_name_renamer = ram_client.ItemNameRenamer()
        # The description half of the same idea. Reads `scouted_shop_items`.
        self.item_description_writer = ram_client.ItemDescriptionWriter()
        # Holds nothing until `/mirorforce` arms it, and puts back what it changed.
        self.miror_force = ram_client.MirorForce()
        # Live roster-HP tracking for the defeat checks: surname-keyed, per-surname rematch queue, and a count.
        self.trainer_defeat_tracker = ram_client.TrainerBattleDefeatTracker()
        self.beaten_flag_watcher = ram_client.TrainerBeatenFlagWatcher()
        self.kaminko_slots = ram_client.KaminkoTrainerSlots()
        self.wonder_trade = wonder_trade_client.WonderTrade()
        self.kaminko_trainers = False
        self.kaminko_won: "set[int]" = set()
        self._snag_machine_check_due = True     # the first save this client sees may come from a crash or reload
        # Debounced in/out-of-battle detection for give_items(), behind a hard timeout: a scripted battle loss in
        # Gateon once got this gate stuck for a whole run, and write-revert detection alone let items through.
        self.battle_state_tracker = ram_client.BattleStateTracker()
        # Counters for the "party struct not populated yet this boot" state, reported by `/dolphin`.
        self._not_ingame_consecutive_polls: int = 0
        self._not_ingame_hint_logged: bool = False

        # From slot_data: which location categories exist for this player, so nothing ever names an id the
        # server does not have for this slot.
        self.shuffle_overworld_items: bool = True
        self.randomize_shadow_species: bool = False
        self.randomize_chests: bool = True    # ADDENDUM 404: always on from 0.1.2; slot data still says so
        self.randomize_shops: bool = False
        # ADDENDUM 415. True until slot data says otherwise: a seed generated before the option existed had them.
        self.purification_checks: bool = True
        # {shop location name: (AP item name, receiving player name or None for ours)}, from the LocationScouts
        # reply. Read ONLY by the cosmetic description writer -- see on_package's LocationInfo branch for why.
        self.scouted_shop_items: "dict[str, tuple[str, str | None]]" = {}
        # Why the dict above is empty, when it is. Read by `/shops`, so a silently-failed scout is visible.
        self.shop_scout_problems: "list[str]" = []
        # {shop location name: "progression"/"useful"/"trap"/"filler"}, from each scout record's `flags` -- the
        # only place a client can learn the class of an item on someone else's location. Drives shop pricing.
        self.shop_line_classifications: "dict[str, str]" = {}
        # Prices each shelf line by what it sends. Off unless the seed randomizes shops, and off for the session
        # the moment its own verification disagrees about where the Items table is.
        self.item_price_writer = ram_client.ItemPriceWriter()
        self.shuffle_trainer_defeats: bool = True
        # Per-seed cap on the cumulative "Defeat N Trainers" checks, defaulting to the in-game max.
        self.trainer_defeat_check_count: int = TRAINER_DEFEAT_COUNT_LOCATION_COUNT
        # 0 = cumulative "Defeat N Trainers" (historical), 1 = one check per real trainer.
        self.unique_trainer_defeats: bool = False

        # See sync_travel_locations(). `received_travel_locations` persists every travel-unlock item received this
        # seed/slot; `_travel_bits_applied_for_block_base` is the block_base those bits were last applied against,
        # so a fresh boot or reconnect re-flips every bit. This flag also arms the per-area story-byte memory.
        self.randomize_travel_locations: bool = False
        # Death Link. The bridge is inert while `enabled` is False, so a seed without it never reads the party.
        self.death_link_bridge = ram_client.DeathLinkBridge()
        self.death_link_from_seed: bool = False            # ADDENDUM 477 -- the seed's `death_link`
        self.death_link_override: "bool | None" = None     # ADDENDUM 477 -- `/toggledeathlink`, persisted per slot
        # ADDENDUM 400. Wired into the area memory so one object answers "did we just white out" for
        # both the Death Link send and the HQ Lab floor hold.
        self.whiteout_latch = ram_client.WhiteoutLatch()
        self.missable_autosender = ram_client.MissableAutoSender()   # ADDENDUM 402
        self.missable_shadow_pusher = ram_client.MissableShadowPusher()
        self.escape_rope_keeper = ram_client.EscapeRopeKeeper()
        self.start_with_poke_spots = False
        self._shadow_monitor_last: "set[int]" = set()
        self._shadow_monitor_sent: "set[int]" = set()
        self._missable_tick_progress: "int | None" = None
        self.death_link_bridge.whiteout_latch = self.whiteout_latch
        self.battle_party_watch = ram_client.BattlePartyWatch()   # ADDENDUM 417
        self.whiteout_counter = ram_client.WhiteoutCounterWatch()   # ADDENDUM 475
        self.area_story_memory.whiteout_latch = self.whiteout_latch
        # Key-item reconciliation owns the gating key items outright; give_items() does not write them. Needs
        # key_item_shuffle: with it off the player is supposed to hold whatever the story hands them.
        self.key_item_shuffle: bool = False
        self.received_travel_locations: set[str] = set()
        # ADDENDUM 434: destinations the GAME has revealed on the map (`travel_locations.revealed_by_game`). Each
        # one's `Unlock -` check is re-offered every stable poll until the server has it, and the set is persisted,
        # because the evidence is erased the same tick it is read -- the lock and the grant both rewrite the bits.
        self.travel_revealed: set[str] = set()
        self._travel_bits_applied_for_block_base: Optional[int] = None
        # ADDENDUM 382: the move-status census is checked once per block base, not per poll -- block_base
        # changes on a boot and on a save load, which is exactly when a save state could have replaced
        # common_rel with another build's.
        self._move_status_checked_for_block_base: Optional[int] = None
        # ADDENDUM 454: Disable Move Animations' live guard.
        self.disable_move_animations = False
        self._animation_guard_due = 0.0
        self.catch_guard = ram_client.GuaranteedCatchGuard()
        self.catch_guaranteed = False
        self.catch_exclusions = False
        self._catch_guard_due = 0.0
        # Citadark Admins Only: the other Citadark trainers are marked beaten in the save.
        self.citadark_admins_only = False
        self._citadark_admins_due = 0.0

        # 0 = Defeat Greevil, 1 = Win Mt. Battle (its 100th trainer). `/goal` is the manual fallback.
        self.goal: int = 0
        # Once armed, the defeat-count target meaning "Mt. Battle's 100th trainer is defeated". None until "MIRU"
        # (trainer_index 1) is confirmed defeated THIS session: there is no live "inside Mt. Battle" signal.
        self.mt_battle_target_defeat_count: Optional[int] = None

        # Per-seed Shadow Pokemon species map from slot_data; only `/shadowdex` reads it.
        self.shadow_species_map: list[dict[str, Any]] = []
        # The dex numbers this seed makes Shadow Pokemon, for the purification scan's second rule ("a Shadow
        # species owned as an ordinary Pokemon has been purified"). Vanilla ones come from `shadow_species_map`
        # when species were shuffled, and the static table when they were not.
        self.generated_shadow_dex: "set[int]" = set()
        # This seed's Poke Spot species. Empty for an older seed -- the seed that needs the Eevee guard below.
        self.pokespot_dex: "set[int]" = set()
        self.starter_line_dex: "set[int]" = set()   # ADDENDUM 443
        self._last_purification_scan: float = 0.0
        # Ids a detector named that this seed does not contain. Reported once each, then held.
        self._locations_not_in_seed: "set[int]" = set()
        # Checks detected but not yet confirmed by the server. Re-sent on reconnect and every
        # PENDING_CHECK_RESEND_SECONDS until the server lists them, so a dropped or half-dead connection loses none.
        self.pending_check_ids: "set[int]" = set()
        self._pending_resend_at: float = 0.0
        # `/animations on|off` for this slot, outranking the seed's Disable Move Animations (persisted).
        self.animations_override: "bool | None" = None
        # "Catch - {species}" -> this seed's source text, for `/catches`. See catch_sources.py.
        self.catch_sources: "dict[str, str]" = {}
        # {location name -> the species that trainer has this seed}, for surnames more than one trainer shares:
        # attributes a defeat by who was on the field, not by how many of that name have been beaten. Empty for
        # an older seed, which falls back to story-order counting.
        self.trainer_team_fingerprints: dict[str, list[str]] = {}
        # When on, a Mt. Battle win does not advance the cumulative "Defeat N Trainers" counter.
        self.exclude_mt_battle_trainers: bool = False
        self.reduce_citadark_grind: bool = False   # ADDENDUM 428: whether id 50 is a Candy Box in this seed
        self.candy_box_in_seed: bool = False
        # The Robo Kyogre Part MacGuffin goal, and the story-byte override it can drive.
        self.robo_kyogre_parts_required: int = 0
        self.robo_kyogre_parts_unlock_citadark: bool = False
        self.story_byte_override = ram_client.StoryByteOverride(write_log=self.story_write_log)
        # The story-side half of the SS Libra gate. Watches the BYTE, not a room: the leak it closes is a story
        # warp into the ship, and by the time the ship's rooms are visible the room is already built.
        self.scooter_hold = ram_client.ScooterStoryHold(write_log=self.story_write_log)
        # ADDENDUM 419: the Music Disc is a story byte; this keeps Phenac below the pickup until the item arrives.
        self.music_disc_hold = ram_client.MusicDiscStoryHold(write_log=self.story_write_log)
        # ADDENDUM 421: the Machine Part's in-game effect is the 0x16 byte, so the early areas wait for the item.
        self.machine_part_hold = ram_client.MachinePartStoryHold(write_log=self.story_write_log)
        # ADDENDUM 452: the HQ Lab waits at 0x16 for the Krane Memo 3-5 handover once the Machine Part is held.
        self.lab_memo_hold = ram_client.LabMemoStoryHold(write_log=self.story_write_log)
        self._items_synced = False   # ADDENDUM 458: set by the first full ReceivedItems after Connected
        self._items_sync_deadline: "float | None" = None
        # ADDENDUM 453/454: the Ability Swap is a Bag USE item handled by the game; only its shop text is ours.
        self.ability_patch = False
        # ADDENDUM 421: notices the game's save data moving (a reset, or a save state from another boot).
        self.block_base_watch = ram_client.BlockBaseWatch()
        self.shuffle_scooter_upgrade: bool = False
        # The SS Libra gate for travel-randomization-OFF seeds. Reuses StoryByteOverride, already the "hold a
        # byte while you are here, put it back when you leave" machine; with `armed` permanently False it is
        # pure ceiling, which is all this gate is.
        self.ss_libra_gate = ram_client.StoryByteOverride(
            write_log=self.story_write_log,
            trigger_rooms=ram_client.SS_LIBRA_ROOM_IDS,
            trigger_region="SS Libra",
            value=ram_client.SS_LIBRA_SCOOTER_FLOOR,
            ceiling=ram_client.SS_LIBRA_STRANDED_FLOOR,
        )
        # Set when the local state file says a previous session was holding the Gateon ceiling. Cleared by the
        # first recovery attempt that resolves, written or not.
        self._gateon_ceiling_recovery_pending: bool = False
        # So the "Agate and Gateon are open" line is said once, not every poll.
        self._always_open_gate_announced: bool = False
        # Once the pair is earned it stays earned -- see `_always_open_gate_is_open`.
        self._always_open_gate_latched: bool = False
        self._gateon_ceiling_last_persisted: "int | None" = None

        self._manual_check_queue: list[str] = []
        self._overworld_location_names: list[str] = []

        # No ISO/save field stores which received items have been given, so it is tracked client-side, persisted
        # by seed+slot. A SET, not a high-water index: with a "from index N onward, stop at the first failure"
        # threshold, one item stuck on a full pocket blocked every item behind it, including ones bound for a
        # different pocket (they are separate physical arrays).
        self.given_item_indices: set[int] = set()
        self._local_state_loaded_for: Optional[str] = None
        # The save clock: which deliveries a reloaded save still holds. See ram_client.SaveTimeline.
        self.save_timeline = ram_client.SaveTimeline()

        # Indices already warned about being undelivered/unconfirmed, so a stuck item warns once rather than
        # every poll. Covers a full pocket and a write a Bag re-read could not verify.
        self._delivery_warned_indices: set[int] = set()

        # Indices already told, once, that there is no slot to write them into. Its own set: the one above means
        # "cannot confirm yet, sit tight", this means "nothing was written until you make room".
        self._delivery_write_full_warned: set[int] = set()

        # ADDENDUM 446: deliveries that count (and may write into) the PC's item storage, decided once at the
        # baseline; and those already told they went there.
        self._delivery_counts_pc: dict[int, bool] = {}
        self._delivery_pc_announced: set[int] = set()

        # Filled on Connected by `_warn_about_a_seed_from_another_build`. None means "not connected yet", which
        # `/seedcheck` reports differently from "connected and nothing is wrong".
        self._seed_only_location_ids: "list[int] | None" = None
        self._build_only_location_count: int = 0
        self._seed_fingerprint: "str | None" = None

        # For an unconfirmed item: the Bag quantity of its pocket slot as of the FIRST poll that attempted the
        # give, fixed until it confirms. It has to outlive one poll, or a write that looked like it stuck and was
        # reverted before the next poll is never caught.
        self._delivery_pending_baseline: dict[int, int] = {}

        # Consecutive polls a pending item has read back at or above baseline+1. Reset to 0, not decremented, on
        # any poll under it: one bad poll means whatever reverted it may still be active.
        self._delivery_confirm_streak: dict[int, int] = {}
        # Highest quantity seen for a pending delivery since its baseline was fixed -- this is what makes a
        # consumed item confirm instead of looping.
        self._delivery_peak: dict[int, int] = {}

        # time.monotonic() (immune to system-clock changes) of the first poll that noticed an item waiting,
        # fixed while it stays undelivered. Bounds how long give_items() holds an item back for battle.
        self._delivery_first_seen: dict[int, float] = {}
        # {received-item index: {companion game item id: baseline quantity}} for the extra ids one AP item
        # delivers. Separate from the primary id's state so a companion cannot hold up the delivery decision.
        self._delivery_companion_pending: "dict[int, dict[int, int]]" = {}

    def describe_party_sources(self) -> str:
        """Reads both party sources and reports them side by side, so "did this catch reach the save block, or
        only the party menu?" is answerable in one line. Diagnostic only."""
        if self.block_base is None:
            return "Party: the save block hasn't been located yet, so neither source can be read."
        if not ram_client.dolphin_available() or not ram_client.is_hooked():
            return "Party: not hooked to Dolphin right now."
        try:
            menu = sorted(ram_client.get_owned_species_snapshot(self.block_base, ram_client.PARTY_BASE))
        except Exception as error:
            menu, menu_error = [], error
        else:
            menu_error = None
        try:
            block = sorted(ram_client.get_party_recap_species_snapshot(self.block_base))
        except Exception as error:
            block, block_error = [], error
        else:
            block_error = None

        def _render(dex_numbers: list[int], error: "Exception | None") -> str:
            if error is not None:
                return f"unreadable ({error})"
            if not dex_numbers:
                return "empty"
            return ", ".join(
                f"#{dex} {species.NATIONAL_DEX.get(dex, '?')}" for dex in dex_numbers
            )

        lines = [
            f"PARTY_BASE (menu-facing struct, {ram_client.PARTY_BASE:#010x}): {_render(menu, menu_error)}",
            f"Save block party records (BLOCK_BASE+{ram_client.PARTY_RECAP_OFFSET:#x}): "
            f"{_render(block, block_error)}",
        ]
        only_in_block = set(block) - set(menu)
        only_in_menu = set(menu) - set(block)
        if only_in_block:
            lines.append(
                "In the save block but not the menu struct: "
                + ", ".join(f"#{dex}" for dex in sorted(only_in_block))
                + " -- exactly the case ADDENDUM 147 added the save-block read for."
            )
        if only_in_menu:
            lines.append(
                "In the menu struct but not the save block: "
                + ", ".join(f"#{dex}" for dex in sorted(only_in_menu))
                + " -- please report this; it means the save-block records lag in some situation."
            )
        if not only_in_block and not only_in_menu:
            lines.append("Both sources agree.")
        return "\n".join(lines)

    def apply_fst_iso(self, path: str, remember: bool) -> bool:
        """Load the FST out of `path` and install it as the guard's repair reference. Read-only; the ISO is
        never modified. Returns True on success and logs either way."""
        try:
            blob = fst_guard.read_disc_fst(path)
            # `/fstiso` is a command and must answer; the startup auto-load is narration. A genuine failure
            # prints either way -- a silently ignored ISO path is a trap.
            line = self.fst_guard.set_disc_baseline(blob, path)
            if remember:
                logger.info(line)
            else:
                _note(self, line)
        except Exception as exc:  # noqa: BLE001 -- a bad path must never take the client down
            logger.warning(f"Could not read a file table from {path!r}: {exc}")
            return False
        if remember:
            remember_fst_iso(path)
        return True

    async def disconnect(self, allow_autoreconnect: bool = False) -> None:
        self.block_base = None
        # A changed block_base already triggers a re-apply; resetting it here also covers a reconnect that
        # resolves the SAME numeric block_base (a Dolphin hiccup, not a reboot).
        self._travel_bits_applied_for_block_base = None
        self._move_status_checked_for_block_base = None
        await super().disconnect(allow_autoreconnect)

    async def server_auth(self, password_requested: bool = False) -> None:
        # The base CommonContext.server_auth() only prompts for a PASSWORD; without this override the client
        # never asks for a slot name and never finishes connecting.
        if password_requested and not self.password:
            await super().server_auth(password_requested)
        await self.get_username()
        await self.send_connect()

    def on_deathlink(self, data: dict[str, Any]) -> None:
        """A death arrived from the pool: wipe the party and let the game resolve it.

        CommonContext's `on_deathlink` runs first on purpose -- it stamps `last_death_link`, which is what
        stops the bounce of our own `send_death` from being read as a new death and looping."""
        super().on_deathlink(data)
        # ADDENDUM 417: in a battle the game fights from its own copy of the party, so the save-side wipe alone
        # waits for the battle to end. The battle flag (1 in battles and full-screen menus) gates the in-battle
        # write; outside a battle those records are the last fight's leftovers and are never touched.
        try:
            in_battle = ram_client.read_battle_ui_flag() == 1
        except Exception:
            in_battle = False
        try:
            note = self.death_link_bridge.receive(self.block_base, str(data.get("cause", "") or ""),
                                                  in_battle=in_battle)
        except Exception:
            return
        if note:
            logger.info(f"Death Link: {note}")

    def on_package(self, cmd: str, args: dict[str, Any]) -> None:
        if cmd == "RoomInfo":
            # `seed_name` is on RoomInfo (handshake, before auth), NOT on Connected -- reading it there is an
            # uncaught KeyError the moment the slot name is entered. It must be set at all, too: `_state_key()`
            # is f"{self.seed_name}:{self.slot}", so a None seed_name collides every multiworld on the same slot
            # number onto one key and a fresh seed inherits another playthrough's `given_item_indices`.
            self.seed_name = args["seed_name"]
        elif cmd == "LocationInfo":
            # The reply to the shop scout sent at the end of the Connected branch below, so a shelf can name the
            # AP item it will send. Purely cosmetic and structured so it cannot be anything else: nothing in the
            # delivery or check paths reads `scouted_shop_items`, and a missing scout just leaves the shelf saying
            # "Not scouted yet.". Wrapped, because a malformed packet must not take the client down.
            #
            # Entries are NAMEDTUPLES, not dicts -- `NetUtils.allowlist` includes `NetworkItem`, so the decoder's
            # object hook converts them before any client sees them, and subscripting by string raises TypeError.
            # Parsing lives in `shop_scout.py`, which has no Archipelago imports, so tests can feed it a real
            # `NetworkItem`; Client.py cannot be imported in this project's test environment.
            try:
                scouted, problems = shop_scout.scouted_shop_items(
                    args.get("locations") or [],
                    ID_TO_LOCATION_NAME.get,
                    self.item_names.lookup_in_slot,
                    self.player_names.get,
                    self.slot,
                    self.shop_line_classifications,
                )
                self.scouted_shop_items.update(scouted)
                self.shop_scout_problems = problems
                if scouted:
                    _note(self, f"Scouted {len(self.scouted_shop_items)} shop line(s) -- shop descriptions "
                                "will name the item each line sends.")
                elif problems:
                    # Louder than `_note_warn`: nothing is broken for the run, but a feature is off. `/shops`
                    # has the detail.
                    logger.warning("Shop scouting failed -- shelves will say \"Not scouted yet.\" (`/shops` for detail).")
                    _note(self, f"  {len(problems)} problem(s); first: {problems[0]}")
            except Exception as exc:  # noqa: BLE001 -- cosmetic data; never worth a disconnect
                self.shop_scout_problems = [str(exc)]
                _note_warn(self, f"Shop scout reply could not be read ({exc}); shop descriptions stay generic.")
        elif cmd == "SetReply":
            try:
                self.wonder_trade.on_set_reply(args)
            except Exception:
                pass
        elif cmd == "ReceivedItems":
            # ADDENDUM 458: index 0 is the full list the server sends after Connected -- from here on
            # `items_received` is the slot's real inventory (the HQ Lab hold waits for it).
            if int(args.get("index", -1) or 0) == 0:
                self._items_synced = True
        elif cmd == "Connected":
            self._items_synced = False   # ADDENDUM 458: until the full item list follows
            self._items_sync_deadline = time.monotonic() + 5.0
            slot_data = args.get("slot_data") or {}
            self.trainer_team_fingerprints = dict(slot_data.get("trainer_team_fingerprints") or {})
            self.catch_sources = {str(k): str(v) for k, v in dict(slot_data.get("catch_sources") or {}).items()}
            # With Agate Village Pit Stop on, Agate's shelf sells real items and has no checks.
            from .game_data import shops as _shops
            _shops.set_disabled_shop_rooms(
                {_shops.AGATE_PIT_STOP_ROOM_ID} if slot_data.get("agate_village_pit_stop") else set()
            )
            # ADDENDUM 427: the Candy Box's own description, on the shelf that sells it.
            from .game_data import candy_box as _candy
            from .game_data import ability_patch as _patch
            _gateon_lines: "dict[int, list[str]]" = {}
            if slot_data.get("reduce_citadark_grind"):
                # ADDENDUM 456: equal_to_citadark_entry (2) levels to Citadark's lowest level, not 100.
                _gateon_lines[_candy.CANDY_BOX_ITEM_ID] = list(
                    _candy.CANDY_BOX_CITADARK_DESCRIPTION_LINES
                    if slot_data.get("reduce_citadark_grind") == _candy.GRIND_CITADARK_ENTRY
                    else _candy.CANDY_BOX_DESCRIPTION_LINES)
            if slot_data.get("ability_patch"):   # ADDENDUM 453/454
                _gateon_lines[_patch.ABILITY_PATCH_ITEM_ID] = list(_patch.DESCRIPTION_LINES)
            self.item_description_writer.fixed_lines_by_room = (
                {_shops.SHOPS_BY_ROOM[156].room_id: _gateon_lines} if _gateon_lines else {})
            # ADDENDUM 428; ADDENDUM 437 dropped the Randomize Shops requirement.
            self.reduce_citadark_grind = bool(slot_data.get("reduce_citadark_grind"))
            self.catch_guaranteed = int(slot_data.get("catch_rate_scaling") or 0) == 2
            self.catch_exclusions = bool(slot_data.get("catch_rate_exclude_citadark")
                                         or slot_data.get("catch_rate_exclude_greevil"))
            self.ability_patch = bool(slot_data.get("ability_patch"))   # ADDENDUM 453/454
            self.candy_box_in_seed = bool(slot_data.get("candy_box")) or self.reduce_citadark_grind
            self.disable_move_animations = bool(slot_data.get("disable_move_animations"))   # ADDENDUM 454
            self.map_level_text.levels = {str(k): int(v) for k, v in dict(slot_data.get("map_place_levels") or {}).items()}
            self.exclude_mt_battle_trainers = bool(slot_data.get("exclude_mt_battle_trainers", False))
            self.purification_checks = bool(slot_data.get("purification_checks", True))   # ADDENDUM 415
            self.kaminko_trainers = bool(slot_data.get("kaminko_missable_trainers", False))
            self.citadark_admins_only = bool(slot_data.get("citadark_admins_only", False))
            self.robo_kyogre_parts_required = int(slot_data.get("robo_kyogre_parts_required", 0) or 0)
            self.robo_kyogre_parts_unlock_citadark = bool(
                slot_data.get("robo_kyogre_parts_unlock_citadark", False)
            )
            self.shuffle_overworld_items = bool(slot_data.get("shuffle_overworld_items", True))
            self.randomize_shadow_species = bool(slot_data.get("randomize_shadow_species", False))
            self.randomize_chests = bool(slot_data.get("randomize_chests", True))
            # Re-derive every debounce from its real duration at the live poll rate, and log it: a window that
            # changed length unnoticed is the failure this prevents. Keyed to the ORDINARY in-game cadence, not
            # the map screen's -- these windows guard events that happen during play.
            _resolved = ram_client.set_poll_interval(POLL_INTERVAL_INGAME)
            if _resolved:
                _note(self, f"Poll interval {POLL_INTERVAL_INGAME}s; confirm windows "
                            + ", ".join(f"{name}={polls}p" for name, polls in sorted(_resolved.items())))
            self.randomize_shops = bool(slot_data.get("randomize_shops", False))
            self.shuffle_trainer_defeats = bool(slot_data.get("shuffle_trainer_defeats", True))
            self.unique_trainer_defeats = int(slot_data.get("trainer_defeat_mode", 0)) == 1
            self.trainer_defeat_check_count = int(
                slot_data.get("trainer_defeat_check_count", TRAINER_DEFEAT_COUNT_LOCATION_COUNT)
            )
            self.goal = int(slot_data.get("goal", 0))
            self.randomize_travel_locations = bool(slot_data.get("randomize_travel_locations", False))
            self.start_with_poke_spots = bool(slot_data.get("start_with_poke_spots", False))
            # Defaults FALSE: an older seed had no Death Link, and turning it on would start wiping a party.
            self.death_link_from_seed = bool(slot_data.get("death_link", False))
            self.death_link_bridge.enabled = self.death_link_from_seed
            Utils.async_start(self.update_death_link(self.death_link_bridge.enabled))
            # Defaults TRUE to match options.KeyItemShuffle: a seed from before this slot_data key had the option
            # on, so assuming False would silently stop reconciling for it.
            self.key_item_shuffle = bool(slot_data.get("key_item_shuffle", True))
            self.shuffle_scooter_upgrade = bool(slot_data.get("shuffle_scooter_upgrade", False))
            self.scooter_hold.enabled = self.shuffle_scooter_upgrade
            self.music_disc_hold.enabled = self.key_item_shuffle   # ADDENDUM 419
            # ADDENDUM 421: vanilla travel only -- with location shuffle on, Krane Memos 3-5 (0x17) are free.
            self.machine_part_hold.enabled = self.key_item_shuffle and not self.randomize_travel_locations
            # ADDENDUM 435: one story byte for the whole game -- an early Robo Kyogre ride gives it back on return.
            self.story_byte_override.return_story_after_citadark = not self.randomize_travel_locations
            if self.randomize_travel_locations:
                # Loaded at connect, not construction: the file is per seed AND per slot, and neither is known
                # before slot_data arrives. A restart mid-run must come back with the same high-water marks or
                # the next map selection sends the player to an area's FLOOR and undoes their progress there.
                _load_area_memory(self)
            # Loaded unconditionally, unlike the area memory above: nothing is recorded with travel
            # randomization off, but `/storylog` should still be able to read and name the file.
            _load_story_write_log(self)
            self._overworld_location_names = sorted(
                LOCATION_NAME_GROUPS["Overworld Items"] if self.shuffle_overworld_items else []
            )

            # Used only by the `/shadowdex` spoiler command.
            self.shadow_species_map = list(slot_data.get("shadow_species_map") or [])
            self.generated_shadow_dex = {int(d) for d in (slot_data.get("generated_shadow_dex") or [])}
            self.pokespot_dex = {
                int(entry["new_dex"]) for entry in (slot_data.get("pokespot_species_map") or [])
                if entry.get("new_dex") is not None
            }
            self.starter_line_dex = {int(d) for d in (slot_data.get("starter_line_dex") or [])}   # ADDENDUM 443
            # Missable Trainer Shadows: the Shadows on missable fights, handed to Miror B. at each fight's area cap.
            self.missable_shadow_pusher = ram_client.MissableShadowPusher(
                (kaminko_shadow_hosts(list(slot_data.get("missable_shadow_hosts") or []), self.kaminko_trainers)
                 if slot_data.get("missable_trainer_shadows") else []) + list(slot_data.get("shadow_rescues") or []))

            # Before anything else this branch does with the seed: say whether the seed and the installed
            # apworld agree about what locations exist. Early, so it lands near the connection banner.
            self._warn_about_a_seed_from_another_build(slot_data)

            self._load_local_state()
            # The team's wonder trade pool, shared with the other Pokemon games: watched from the start.
            Utils.async_start(self.send_msgs(self.wonder_trade.on_connected(self)))
            # Anything detected while the connection was down goes out now; trackers get the room again.
            self._published_room = None
            self._pending_resend_at = 0.0
            asyncio.create_task(flush_pending_checks(self, force=True), name="FlushPendingChecks")
            # ADDENDUM 477: `/toggledeathlink`'s choice outranks the seed's, and survives a reconnect.
            if self.death_link_override is not None and self.death_link_override != self.death_link_bridge.enabled:
                self.death_link_bridge.enabled = self.death_link_override
                Utils.async_start(self.update_death_link(self.death_link_bridge.enabled))
                logger.info(f"Death Link: {'ON' if self.death_link_override else 'OFF'} for this slot "
                            "(set with /toggledeathlink; the seed says "
                            f"{'on' if self.death_link_from_seed else 'off'}).")

            # A scout is the only way to learn what a location holds without checking it, and create_as_hint 0
            # creates no hint, so this is invisible to the rest of the multiworld. Shop locations only, and only
            # when the seed has shop checks. `create_task` because `on_package` is synchronous and on the
            # critical path for every packet, deliveries included.
            if self.randomize_shops:
                # Scout only the shop lines THIS SEED HAS. Built from SHOP_ITEM_LOCATIONS -- the world's whole
                # shop table -- this named nine locations a Pit-Stop-on seed does not contain, and MultiServer's
                # LOCATIONSCOUTS handler indexes them without a membership test, so the KeyError closed the
                # connection. `_send_checks`' filter does not cover a scout: it is a different packet, sent here.
                _seed_ids = seed_location_ids(self)
                shop_ids = sorted(
                    LOCATION_NAME_TO_ID[name] for name in SHOP_ITEM_LOCATIONS
                    if name in LOCATION_NAME_TO_ID and LOCATION_NAME_TO_ID[name] in _seed_ids
                )
                if shop_ids:
                    asyncio.create_task(_scout_shop_locations(self, shop_ids), name="ScoutShopLocations")

    def make_gui(self) -> type["kvui.GameManager"]:
        ui = super().make_gui()
        ui.base_title = "Archipelago Pokemon XD Client"
        return ui

    async def declare_goal_complete(self) -> None:
        if self.finished_game:
            logger.info("Already declared the game complete.")
            return
        self.finished_game = True
        await self.send_msgs([{"cmd": "StatusUpdate", "status": ClientStatus.CLIENT_GOAL}])
        goal_description = (
            "defeating Mt. Battle's 100th and final trainer" if self.goal == 1
            else "defeating the Cipher Boss Greevil at Citadark Isle"
        )
        logger.info(f"Declared the game complete ({goal_description}) -- goal sent to the server.")

    # Manual "/checked" handling for Overworld Item locations -- see module docstring.

    def queue_manual_check(self, text: str) -> None:
        if not text.strip():
            logger.info("Usage: /checked <part of the chest/item location's name> (see /remaining for the list)")
            return
        if not self.shuffle_overworld_items and not self._undetectable_chest_location_names():
            logger.info("This seed doesn't have Overworld Items shuffled -- nothing to manually check.")
            return
        match = self._fuzzy_match_overworld_location(text)
        if match is None:
            logger.info(f"No unchecked Overworld Item location matches {text!r} -- try /remaining for the list.")
            return
        self._manual_check_queue.append(match)
        logger.info(f"Queued check: {match}")

    def _fuzzy_match_overworld_location(self, text: str) -> Optional[str]:
        needle = _normalize_for_match(text)
        if not needle:
            return None
        remaining = self._remaining_overworld_locations()
        # Exact normalized match first, then substring -- but only with exactly one candidate: an ambiguous
        # partial match is refused rather than guessing which chest the player means.
        for name in remaining:
            if _normalize_for_match(name) == needle:
                return name
        candidates = [name for name in remaining if needle in _normalize_for_match(name)]
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            logger.info(f"{text!r} matches more than one location, be more specific: {', '.join(candidates[:8])}")
        return None

    # Detects a seed rolled against a different build. On Connected the server hands over this slot's whole
    # location id set (`missing_locations | checked_locations`), which IS the seed's location list, so this needs
    # no slot data and works on seeds older than the fingerprint below.
    #
    # Only one direction is dangerous: ids in the SEED this build lacks can never fire (one unwinnable
    # seed had 63 of 685 rows naming retired locations, five of them progression). Ids this BUILD has that the
    # seed lacks are harmless, so they go to `/seedcheck` and stay silent. It warns, it does not refuse.
    def _warn_about_a_seed_from_another_build(self, slot_data: dict) -> None:
        seed_ids = set(self.missing_locations) | set(self.checked_locations)
        if not seed_ids:
            return   # nothing to compare against; say nothing rather than guess
        mine = set(LOCATION_NAME_TO_ID.values())
        unknown = seed_ids - mine
        self._seed_only_location_ids = sorted(unknown)
        self._build_only_location_count = len(mine - seed_ids)

        seed_print = slot_data.get("location_table_fingerprint")
        mine_print = LOCATION_TABLE_FINGERPRINT
        self._seed_fingerprint = seed_print

        if not unknown:
            if seed_print and seed_print != mine_print:
                # Same ids, different table: a rename carried its id across. The id set cannot see it, and the
                # client would send a string the server does not recognise. This is what the fingerprint is for.
                logger.warning(f"This seed came from a different apworld build ({seed_print} vs installed "
                               f"{mine_print}) -- use the build it was generated with if a check fails to register.")
            return

        logger.warning(f"Version mismatch: {len(unknown)} of this seed's {len(seed_ids)} locations don't exist in the "
                       f"installed apworld and can never be sent. Install the build the seed was generated with "
                       f"(`/seedcheck` for detail).")

    def print_seed_location_check(self) -> None:
        """`/seedcheck` -- the seed/build location comparison, on demand."""
        if self._seed_only_location_ids is None:
            logger.info("Not connected yet, so there is no seed to compare against.")
            return
        logger.info(f"Installed location table: {len(LOCATION_NAME_TO_ID)} locations, "
                    f"fingerprint {LOCATION_TABLE_FINGERPRINT}.")
        logger.info(f"Seed's table fingerprint: {self._seed_fingerprint or 'not recorded (pre-ADDENDUM 251 seed)'}.")
        if self._seed_only_location_ids:
            shown = ", ".join(str(i) for i in self._seed_only_location_ids[:20])
            more = f" (+{len(self._seed_only_location_ids) - 20} more)" if len(self._seed_only_location_ids) > 20 else ""
            logger.info(f"{len(self._seed_only_location_ids)} location id(s) in the seed that this build does "
                        f"NOT have -- these can never be checked: {shown}{more}")
            logger.info("  They cannot be named: the id is not in this build's table, which is the point.")
        else:
            logger.info("Every location in this seed exists in the installed apworld.")
        if self._build_only_location_count:
            logger.info(f"{self._build_only_location_count} location(s) this build has that the seed does not. "
                        f"Harmless -- options differ, or the build gained locations since.")

    def _undetectable_chest_location_names(self) -> list[str]:
        """Always empty. This used to offer `/checked` the chests whose flag position was never measured; chest
        identity is now the berry plus the room, so there is no such category. Kept because
        `_remaining_overworld_locations` calls it, and because offering chests the client will send itself is
        worse than useless -- a fuzzy match on a nearby name marks the WRONG location, and that cannot be taken
        back. A chest that genuinely did not register can still be named directly."""
        return []

    def _remaining_overworld_locations(self) -> list[str]:
        checked_ids = self.checked_locations | set(self.locations_checked) | set(self._manual_check_queue_ids())
        return [
            name for name in self._overworld_location_names + self._undetectable_chest_location_names()
            if LOCATION_NAME_TO_ID[name] not in checked_ids
        ]

    def _manual_check_queue_ids(self) -> set[int]:
        return {LOCATION_NAME_TO_ID[name] for name in self._manual_check_queue if name in LOCATION_NAME_TO_ID}

    def print_remaining_manual_checks(self) -> None:
        remaining = self._remaining_overworld_locations()
        if not remaining:
            logger.info("No remaining Overworld Item locations (or shuffle_overworld_items is off for this seed).")
            return
        logger.info(f"{len(remaining)} Overworld Item location(s) not yet checked:")
        for name in remaining:
            logger.info(f"  {name}")

    # `/shadowdex` -- this seed's Shadow Pokemon species map, so "where do I find X now" is answerable without
    # the spoiler log.

    def print_catch_sources(self, filter_text: str = "") -> None:
        if not self.catch_sources:
            logger.info("No catch-location sources for this seed (generated before ADDENDUM 310, or no catch "
                        "locations this seed).")
            return
        checked = {self.location_names.lookup_in_game(i) for i in self.checked_locations}
        needle = filter_text.strip().lower()
        rows = [(name, text) for name, text in sorted(self.catch_sources.items())
                if name not in checked and (not needle or needle in f"{name} {text}".lower())]
        if not rows:
            logger.info("No unchecked catch locations match." if needle else "Every catch location is checked.")
            return
        for name, text in rows:
            logger.info(f"{name}: {text}")

    def seed_shadow_dex(self) -> "set[int]":
        """Every species that is a Shadow Pokemon in THIS seed. The per-seed map wins when present, because
        `randomize_shadow_species` has moved the species since the static table was written; the static table
        answers for a seed with that option off. Generated Shadows are additive either way."""
        from . import shadow_species

        out: "set[int]" = set(self.generated_shadow_dex)
        if self.shadow_species_map:
            out |= {int(entry["new_dex"]) for entry in self.shadow_species_map
                    if entry.get("new_dex") is not None}
        else:
            out |= set(shadow_species.SHADOW_CAPTURE_LOCATION_TO_DEX.values())
        return out

    def obtainable_without_purifying(self) -> "set[int]":
        """Species this seed gives WITHOUT a purification, so rule 2 of the purification scan does not read
        owning one as evidence: the guaranteed Eevee (dex 133) and its five evolutions, since nothing stops the
        expansion making one a generated Shadow and then the story gift alone satisfies rule 2; and this seed's
        Poke Spot species, which generation now forbids overlapping but an older seed can still contain."""
        from . import species as species_module

        return ({133} | set(species_module.EEVEELUTION_DEX_NUMBERS) | set(self.pokespot_dex)
                | set(self.starter_line_dex))   # ADDENDUM 443: a randomized starter's line too

    def print_shadow_species_map(self, filter_text: str = "") -> None:
        if not self.shadow_species_map:
            logger.info(
                "No Shadow Pokemon species map for this seed -- either Randomize Shadow Species is off, or "
                "this seed was generated before that option existed."
            )
            return
        needle = _normalize_for_match(filter_text) if filter_text.strip() else None
        shown = 0
        if needle is None:
            logger.info("This seed's Shadow Pokemon species map (original -> now found there):")
        for entry in self.shadow_species_map:
            location = entry.get("location", "?")
            original_name = entry.get("original_name") or "?"
            new_name = entry.get("new_name") or "?"
            if needle is not None:
                haystack = _normalize_for_match(f"{location} {original_name} {new_name}")
                if needle not in haystack:
                    continue
            logger.info(f"  {location}: {original_name} -> {new_name}")
            shown += 1
        if shown == 0:
            logger.info(f"No Shadow Pokemon species map entries match {filter_text!r}.")
        elif needle is not None:
            logger.info(f"({shown} matching entr{'y' if shown == 1 else 'ies'} shown above.)")

    # Local state persistence -- see __init__'s comment on why this is client-side rather than in-save.

    def _state_file_path(self) -> str:
        return Utils.cache_path("pokemon_xd_client_state.json")

    def _state_key(self) -> str:
        return f"{self.seed_name}:{self.slot}"

    def _load_local_state(self) -> None:
        key = self._state_key()
        if self._local_state_loaded_for == key:
            return
        self._local_state_loaded_for = key
        # Everything below is per seed and slot. A client that was connected to another seed or slot in this same
        # run still holds that one's ledgers, and Shadow ids, species and trainer teams are the same numbers in
        # every seed: kept, they read this seed's purifications, catches and defeats as already counted and send
        # nothing -- and the next save writes them into this seed's state too. Start clean, then load.
        self.purification_tracker = ram_client.PurificationCountTracker()
        self.trainer_defeat_tracker = ram_client.TrainerBattleDefeatTracker()
        self.beaten_flag_watcher = ram_client.TrainerBeatenFlagWatcher()
        self.kaminko_slots = ram_client.KaminkoTrainerSlots()
        self.wonder_trade = wonder_trade_client.WonderTrade()
        self.kaminko_won = set()
        self.save_timeline = ram_client.SaveTimeline()
        self.species_catch_tracker = ram_client.SpeciesCatchTracker()
        self.krane_memo_tracker = ram_client.KraneMemoTracker()
        self._shadow_monitor_last = set()
        for hold in (self.music_disc_hold, self.machine_part_hold, self.lab_memo_hold):
            hold.declined_value = None
        self.music_disc_hold.lowered = False
        self.lab_memo_hold.latched = False
        self.lab_memo_hold.lab_reached = False
        self._always_open_gate_latched = False
        self.story_byte_override.pre_ride_byte = None
        self.story_byte_override.citadark_mark = None
        self.given_item_indices = set()
        self.received_travel_locations = set()
        self.travel_revealed = set()
        self.scooter_upgrade_seen = False   # ADDENDUM 474
        self.death_link_override = None     # ADDENDUM 477
        self.pending_check_ids = set()
        self.animations_override = None
        path = self._state_file_path()
        try:
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as f:
                    all_state = json.load(f)
                slot_state = all_state.get(key, {})
                if "given_item_indices" in slot_state:
                    self.given_item_indices = {int(i) for i in slot_state["given_item_indices"]}
                elif "expected_item_index" in slot_state:
                    # Migration: an older state file recorded only a linear high-water mark, and everything
                    # below it was by definition already given.
                    self.given_item_indices = set(range(int(slot_state["expected_item_index"])))
                # Its own list, not given_item_indices: the travel-control record lives in volatile RAM with no
                # confirmed save-file backing, so "was this ever given" and "are its bits set in THIS boot's
                # RAM" are different questions.
                self.received_travel_locations = {
                    str(name) for name in slot_state.get("received_travel_locations", [])
                }
                self.travel_revealed = {str(name) for name in slot_state.get("travel_revealed", [])}   # ADDENDUM 434
                self.scooter_upgrade_seen = bool(slot_state.get("scooter_upgrade_seen", False))   # ADDENDUM 474
                _override = slot_state.get("death_link_override")   # ADDENDUM 477
                self.death_link_override = None if _override is None else bool(_override)
                self.pending_check_ids = {int(i) for i in slot_state.get("pending_checks", [])}
                self.kaminko_won = {int(i) for i in slot_state.get("kaminko_won", [])}
                self.wonder_trade.load_json(slot_state.get("wonder_trade"))
                self.save_timeline.load_json(slot_state.get("save_timeline"))
                _anim = slot_state.get("animations_override")
                self.animations_override = None if _anim is None else bool(_anim)
                # The purified-species ledger records what the game cannot be re-read for: a species purified in
                # an earlier session leaves a flag that looks brand new to a fresh client.
                if "purification" in slot_state:
                    self.purification_tracker.load_json(slot_state["purification"])
                # Same shape, same failure if missing: a defeat check fires on the Nth DISTINCT team and the game
                # records none of them, so a client that restarts without this reads every rematch as a first win.
                if "trainer_teams" in slot_state:
                    self.trainer_defeat_tracker.load_json(slot_state["trainer_teams"])
                # A byte a previous session was holding down, loaded into `saved_byte` so the recovery pass can
                # put it back once a block base resolves. NOT "we are still active" -- nothing is written yet.
                self._always_open_gate_latched = bool(slot_state.get("always_open_gate_latched", False))
                held_steps = slot_state.get("story_item_holds", {})   # ADDENDUM 421
                if isinstance(held_steps, dict):
                    for hold in (self.music_disc_hold, self.machine_part_hold):
                        value = held_steps.get(hold.ITEM)
                        if isinstance(value, int):
                            hold.declined_value = value
                self.music_disc_hold.lowered = bool(slot_state.get("music_disc_room_lowered", False))   # ADDENDUM 441
                lab_held = slot_state.get("lab_memo_hold_declined")   # ADDENDUM 452
                if isinstance(lab_held, int):
                    self.lab_memo_hold.declined_value = lab_held
                self.lab_memo_hold.latched = bool(slot_state.get("lab_memo_hold_latched", False))   # ADDENDUM 458
                self.lab_memo_hold.lab_reached = bool(slot_state.get("lab_memo_lab_reached", False))   # ADDENDUM 464
                # ADDENDUM 435: an early Citadark ride's story to give back, and the island's own progress.
                for key, attr in (("citadark_pre_ride_byte", "pre_ride_byte"), ("citadark_mark", "citadark_mark")):
                    value = slot_state.get(key)
                    if isinstance(value, int):
                        setattr(self.story_byte_override, attr, value)
                held = slot_state.get("gateon_ceiling_holding")
                if isinstance(held, int):
                    self.story_byte_override.saved_byte = held
                    self._gateon_ceiling_recovery_pending = True
        except (OSError, ValueError, TypeError):
            _note_warn(self, f"Couldn't read local client state from {path} -- starting fresh for this "
                              "seed/slot.")

    def _save_local_state(self) -> None:
        path = self._state_file_path()
        key = self._state_key()
        all_state: dict[str, Any] = {}
        try:
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as f:
                    all_state = json.load(f)
        except (OSError, ValueError, TypeError):
            all_state = {}
        all_state[key] = {
            "given_item_indices": sorted(self.given_item_indices),
            "received_travel_locations": sorted(self.received_travel_locations),
            "travel_revealed": sorted(self.travel_revealed),   # ADDENDUM 434
            "scooter_upgrade_seen": bool(getattr(self, "scooter_upgrade_seen", False)),   # ADDENDUM 474
            "death_link_override": getattr(self, "death_link_override", None),   # ADDENDUM 477
            "pending_checks": sorted(getattr(self, "pending_check_ids", ()) or ()),
            "kaminko_won": sorted(getattr(self, "kaminko_won", ()) or ()),
            "wonder_trade": self.wonder_trade.to_json(),
            "save_timeline": self.save_timeline.to_json(),
            "animations_override": getattr(self, "animations_override", None),
            "purification": self.purification_tracker.to_json(),
            "trainer_teams": self.trainer_defeat_tracker.to_json(),
            # The value the Gateon ceiling is holding back, or None -- the only write this client makes that can
            # lose progress. Restore-on-leave does not cover the client being killed inside Gateon; this does.
            "gateon_ceiling_holding": self.story_byte_override.saved_byte,
            "citadark_pre_ride_byte": self.story_byte_override.pre_ride_byte,   # ADDENDUM 435
            "citadark_mark": self.story_byte_override.citadark_mark,            # ADDENDUM 435
            # A grant, so it survives a reconnect: otherwise reconnecting outside the lab re-locks Agate and
            # Gateon after the player has opened them.
            "always_open_gate_latched": self._always_open_gate_latched,
            # ADDENDUM 421: what each item story hold is waiting to give back.
            "story_item_holds": {hold.ITEM: hold.declined_value
                                 for hold in (self.music_disc_hold, self.machine_part_hold)
                                 if hold.declined_value is not None},
            # ADDENDUM 441: a 0x3F in Phenac that is ours to put back to 0x41.
            "music_disc_room_lowered": self.music_disc_hold.lowered,
            # ADDENDUM 452: what the HQ Lab memo hold is waiting to give back.
            "lab_memo_hold_declined": self.lab_memo_hold.declined_value,
            "lab_memo_hold_latched": self.lab_memo_hold.latched,   # ADDENDUM 458
            "lab_memo_lab_reached": self.lab_memo_hold.lab_reached,   # ADDENDUM 464
        }
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(all_state, f)
        except OSError:
            logger.warning(f"Couldn't persist local client state to {path} -- progress on receiving items "
                            "may replay from an earlier point next time the client starts.")


# Trap handling. An AP-only item with no real Bag id (route_and_give_item returns None for it); it uses the
# already-validated money read/write rather than any new memory location.

TRAP_ITEM_NAMES = {"Itemfinder Malfunction Trap"}

# Neither effect item is a Bag item; both are a currency write into the save block, four bytes apart.
# Everything else in `ITEM_TABLE` routes to a pocket and confirms a quantity, and these cannot.
EFFECT_ITEM_NAMES = TRAP_ITEM_NAMES | {items.POKECOUPON_ITEM_NAME}


def _apply_pokecoupon_item(ctx: PokemonXDContext, item_name: str) -> None:
    """Add this item's coupons to BOTH fields, the way `heroAddPokecoupon` does. The lifetime total is what Mt.
    Battle's prize tiers read and it never falls when you spend, so raising only the balance would hand over
    coupons that buy nothing. `add_pokecoupons` clamps to the same 9999999 the game's own setters do."""
    if ctx.block_base is None:
        return
    try:
        balance, total = ram_client.add_pokecoupons(ctx.block_base, items.POKECOUPON_ITEM_AMOUNT)
        logger.info("%s: %d Poke Coupons added -- balance %d, lifetime %d.",
                    item_name, items.POKECOUPON_ITEM_AMOUNT, balance, total)
    except Exception:
        logger.warning(f"Couldn't apply {item_name}'s effect (Poke Coupon read/write failed) -- skipping "
                       f"this time.")


def _apply_effect_item(ctx: PokemonXDContext, item_name: str) -> None:
    """Dispatch for the AP-only items that have an effect instead of a Bag id."""
    if item_name in TRAP_ITEM_NAMES:
        _apply_trap_effect(ctx, item_name)
    elif item_name == items.POKECOUPON_ITEM_NAME:
        _apply_pokecoupon_item(ctx, item_name)


def _apply_trap_effect(ctx: PokemonXDContext, item_name: str) -> None:
    if ctx.block_base is None:
        return
    try:
        money = ram_client.read_money(ctx.block_base)
        deduction = min(money, max(50, money // 10))  # 10%, floor 50, never below 0
        ram_client.write_money(ctx.block_base, money - deduction)
        logger.info(f"{item_name}: your Itemfinder glitches and drops {deduction} Pokedollars out of your bag!")
    except Exception:
        logger.warning(f"Couldn't apply {item_name}'s effect (money read/write failed) -- skipping this time.")


# Receiving items

def _deliver_companion_items(ctx: PokemonXDContext) -> None:
    """Write the extra game item ids a packaged AP item carries (items.ItemData.companion_game_item_ids).

    Deliberately outside the confirmation gate: a companion write that does not land must not stop the AP item
    being marked delivered, stall the queue, or retry forever and stack duplicates. So each pending companion id
    is checked before it is written -- that is what makes retrying safe rather than duplicating -- and once its
    quantity rises past baseline it is dropped and never written again. The cost is that a companion could in
    principle never land, which for the Data ROM & ID Card is the half-delivered state the packaging exists to
    prevent; hence the loud miss.
    """
    if ctx.block_base is None or not ctx._delivery_companion_pending:
        return
    for idx, pending in list(ctx._delivery_companion_pending.items()):
        for companion_id, baseline in list(pending.items()):
            pocket = ram_client.resolve_item_pocket(ctx.block_base, companion_id)
            if pocket is None:
                pending.pop(companion_id, None)   # no known pocket -- nothing this client can do, so stop trying
                continue
            pocket_base, max_slots = pocket
            try:
                current = ram_client.find_item_quantity(pocket_base, max_slots, companion_id)
                if current > baseline:
                    pending.pop(companion_id, None)
                    continue
                ram_client.give_item(pocket_base, companion_id, 1, max_slots)
            except Exception:
                continue   # transient read/write trouble: leave it pending and try again next poll
        if not pending:
            ctx._delivery_companion_pending.pop(idx, None)


def _note_candy_box_seed(ctx: PokemonXDContext, idx: int, item_name: str) -> None:
    """ADDENDUM 428: `99 Candy Boxes` is item 50, which only the Reduce Citadark Grind patch turns into a Candy
    Box. Still delivered either way -- an item is never held back -- but a seed without the option is told it
    is getting Yellow Shards, once per received item."""
    if item_name != "99 Candy Boxes" or getattr(ctx, "reduce_citadark_grind", False) \
            or getattr(ctx, "candy_box_in_seed", False):
        return
    warned = ctx.__dict__.setdefault("_candy_box_warned", set())
    if idx in warned:
        return
    warned.add(idx)
    logger.warning("99 Candy Boxes: this seed does not have Reduce Citadark Grind, so the "
                   "ISO has no Candy Box code -- they arrive as 99 Yellow Shards, which do nothing.")


async def give_items(ctx: PokemonXDContext) -> None:
    """Delivers every received item not yet marked given. One poll, every item, no early exit.

    Every item gets its own try/except: a failure on one must not block another, and must not escape into
    `dolphin_sync_task`, whose handler tears the poll down and reports the connection lost even though Dolphin is
    fine. `given_item_indices` is likewise a SET, not a high-water index, so one item stuck on a full pocket
    blocks only itself. That set IS the buffer, and nothing upstream may refuse to try -- a battle-state gate
    that wedged shut once blocked deliveries for a whole run.

    The write and its confirmation live on SEPARATE polls, because a same-call read-back cannot tell "landed"
    from "looked landed for the instant I checked": if the game's battle-time Bag logic reverts a foreign write,
    an immediate read still sees our own fresh bytes. The first poll fixes a baseline quantity
    (`_delivery_pending_baseline`, never re-sampled) and issues a write it does not trust yet. One later poll is
    not enough either, since in-battle logic may revert per turn or per animation, so an item is delivered only
    after ITEM_DELIVERY_CONFIRM_STREAK consecutive polls at or above baseline + quantity.

    The comparison is against the PEAK since the baseline, not the current value: drink a Potion before the
    streak finishes and a current-value test never confirms, so the item is rewritten every poll.

    A FIRST write is gated on the step counter (or the battle tracker, when the counter is unreadable), bounded
    by ITEM_DELIVERY_MAX_BATTLE_WAIT_SECONDS. Deliveries already in flight are never gated, and the tracker is
    polled once per call, never per item -- advancing its debounce several times in one tick corrupts it.
    """
    if ctx.block_base is None:
        return
    received = ctx.items_received
    # Polled EVERY tick, above the "nothing pending" return: the gate answers "did the counter rise since the
    # previous poll", so a baseline left untouched while nothing was queued would compare against steps walked
    # minutes ago.
    walked = ctx.step_gate.poll(ctx.block_base)
    if len(ctx.given_item_indices) >= len(received):
        return  # nothing new this poll -- skip the battle-state read entirely

    # A DELAY, not a gate. `battle_hold` is armed only by roster HP actually CHANGING poll-over-poll, so it decays
    # by itself once the game stops updating those values, and one continuous hold has a hard ceiling -- which is
    # what makes it incapable of the "stuck True forever" failure that took out every earlier battle gate.
    if ctx.battle_hold.should_hold():
        if ctx.battle_hold.ceiling_tripped and not ctx._battle_hold_ceiling_logged:
            ctx._battle_hold_ceiling_logged = True
            _note(ctx, "Battle activity has looked continuous for an unusually long time -- delivering "
                       "queued items anyway rather than holding them any longer.")
        return
    ctx._battle_hold_ceiling_logged = False

    changed = False
    now = time.monotonic()
    # Once per poll, never once per item: repeated calls in the same tick corrupt BattleStateTracker's debounce.
    corroborating = ctx.trainer_defeat_tracker.has_unresolved_battle() if ctx.shuffle_trainer_defeats else False
    battle_says_safe = ctx.battle_state_tracker.poll(corroborating_in_battle=corroborating)
    # A NEW delivery starts on a step, not on the absence of a detected battle. The battle tracker is still
    # polled every tick -- its debounce needs the calls, and it takes over when the counter reads None, so a bad
    # read degrades to the old behaviour instead of holding items. Deliveries already in flight are untouched.
    if walked is None:
        safe_to_start_new_items = battle_says_safe
        ctx._delivery_gate_name = "battle"
    else:
        safe_to_start_new_items = walked
        ctx._delivery_gate_name = "step"
    # A save under way: no NEW write starts until it is done, so every delivery is plainly before or after it. A
    # delay with a ceiling (SaveTimeline.holding), never a gate.
    saving = ctx.save_timeline.holding()
    for idx, network_item in enumerate(received):
        if idx in ctx.given_item_indices:
            continue
        if idx not in ctx._delivery_first_seen:
            ctx._delivery_first_seen[idx] = now
        if saving and idx not in ctx._delivery_pending_baseline:
            continue
        item_name = ITEM_ID_TO_NAME.get(network_item.item, f"Unknown Item {network_item.item}")
        _note_candy_box_seed(ctx, idx, item_name)
        try:
            if item_name in EFFECT_ITEM_NAMES:
                _apply_effect_item(ctx, item_name)
                if item_name not in TRAP_ITEM_NAMES:
                    ctx.save_timeline.stamp(idx)
                delivered = True
            else:
                data = ITEM_TABLE.get(item_name)
                game_item_id = data.game_item_id if data is not None else None
                # The gating key items belong to reconcile_key_items(). Doing both would race: this
                # function's confirm streak would read a quantity the reconciler had just written and both
                # would think they did it. Marked delivered, not skipped -- a pending index parks forever.
                managed_ids = managed_key_item_ids(ctx)
                if managed_ids and game_item_id in managed_ids:
                    if idx not in ctx._delivery_warned_indices:
                        logger.info(f"Received {item_name} -- the key-item reconciler keeps this one in your "
                                    f"Bag from now on (see /keyitems).")
                        ctx._delivery_warned_indices.add(idx)
                    ctx.given_item_indices.add(idx)
                    continue
                # Most items deliver quantity 1; a bundle filler like "10 Poke Balls" delivers several units of
                # one game_item_id in the SAME write. See items.py's ItemData.quantity.
                quantity = data.quantity if data is not None else 1
                pocket = ram_client.resolve_item_pocket(ctx.block_base, game_item_id)
                if pocket is None:
                    logger.info(f"Received {item_name} -- no real in-game item id is known for this one yet "
                                "(see items.py); nothing was written, but it's marked received.")
                    delivered = True
                else:
                    pocket_base, max_slots = pocket
                    if idx not in ctx._delivery_pending_baseline:
                        waited = now - ctx._delivery_first_seen[idx]
                        if not safe_to_start_new_items and waited < ITEM_DELIVERY_MAX_BATTLE_WAIT_SECONDS:
                            # Battle plausibly still active and we have not given up waiting yet -- do not even
                            # issue a first write. It stays in the retry queue and is tried next poll.
                            delivered = False
                        else:
                            # The ceiling firing is itself a bug report, hence `logger.warning`: a battle gate
                            # claiming a battle for ten straight minutes means the gate is wrong. At most once
                            # per item -- the baseline below means this branch is not reached again.
                            if not safe_to_start_new_items:
                                if ctx._delivery_gate_name == "step":
                                    # Under the step gate this means "no steps in ten minutes", usually a
                                    # player idling in a menu rather than a fault.
                                    _note(ctx, f"{item_name}: no step taken in "
                                               f"{ITEM_DELIVERY_MAX_BATTLE_WAIT_SECONDS:.0f}s -- written anyway.")
                                else:
                                    logger.warning(f"{item_name} waited out the full battle hold -- written anyway "
                                                   f"(`/battle` shows what held it).")
                            # First poll for this item: fix the baseline once, then write, confirming later. The
                            # baseline is READ across the full pocket array, not the narrow window this client
                            # WRITES into -- the game's own item-add code puts a berry wherever the Bag fills
                            # from, usually well below the slot-82 write window, and a baseline that cannot see
                            # an existing stack reads 0. Base AND count come from one call, since pairing the
                            # narrow write base with a widened count read slot 82 for 190 slots, past the end of
                            # the array. A read is never corrupting; only the write window is.
                            read_base, read_slots = (
                                ram_client.resolve_item_read_window(ctx.block_base, game_item_id)
                                or (pocket_base, max_slots)
                            )
                            # ADDENDUM 446: decided once, here -- does this delivery also count the PC?
                            ctx._delivery_counts_pc[idx] = ram_client.may_overflow_to_pc(ctx.block_base,
                                                                                         game_item_id)
                            ctx._delivery_pending_baseline[idx] = _held_quantity(
                                ctx, idx, read_base, read_slots, game_item_id,
                            )
                            # The return value must be checked: `give_item` answers False when the id is absent
                            # and every slot in the write window is taken, having touched no memory. Discarding
                            # it gave a baseline, no write, a `peak` that could never rise and a silent retry.
                            if not _give_item_or_pc_overflow(ctx, idx, item_name, pocket_base, game_item_id, quantity,
                                                          max_slots, ctx._delivery_counts_pc[idx]):
                                _warn_write_window_full(ctx, idx, item_name, pocket_base, max_slots)
                            ctx.save_timeline.stamp(idx)
                            # A packaged item's extra ids get their baselines fixed in the SAME poll as the
                            # primary's, so both halves describe the same instant. They are written by
                            # _deliver_companion_items(), never here.
                            companions = data.companion_game_item_ids if data is not None else ()
                            if companions:
                                baselines: "dict[int, int]" = {}
                                for companion_id in companions:
                                    companion_pocket = ram_client.resolve_item_pocket(
                                        ctx.block_base, companion_id
                                    )
                                    if companion_pocket is None:
                                        continue
                                    c_base, c_slots = companion_pocket
                                    baselines[companion_id] = ram_client.find_item_quantity(
                                        c_base, c_slots, companion_id
                                    )
                                if baselines:
                                    ctx._delivery_companion_pending[idx] = baselines
                            delivered = False
                    else:
                        baseline = ctx._delivery_pending_baseline[idx]
                        read_base, read_slots = (
                            ram_client.resolve_item_read_window(ctx.block_base, game_item_id)
                            or (pocket_base, max_slots)
                        )
                        current = _held_quantity(ctx, idx, read_base, read_slots, game_item_id)
                        # Confirm on the PEAK, not the current value: "did our write land?" and "does the player
                        # still have it?" diverge the moment the item is used. Drink a Potion before the streak
                        # finishes and a current-value test rewrites the item every poll.
                        peak = max(ctx._delivery_peak.get(idx, 0), current)
                        ctx._delivery_peak[idx] = peak
                        if peak >= baseline + quantity:
                            # One good poll is not enough: ITEM_DELIVERY_CONFIRM_STREAK consecutive confirmed
                            # polls, so a revert more than one poll interval after our write is still caught.
                            streak = ctx._delivery_confirm_streak.get(idx, 0) + 1
                            if streak >= ITEM_DELIVERY_CONFIRM_STREAK:
                                ctx._delivery_peak.pop(idx, None)
                                logger.info(f"Received {item_name}.")
                                # The packaged item is confirmed, but its second id may not have landed. Said
                                # out loud: for the Data ROM & ID Card this is the half-delivered state the
                                # packaging exists to prevent.
                                still_missing = ctx._delivery_companion_pending.get(idx)
                                if still_missing:
                                    ids = ", ".join(str(i) for i in sorted(still_missing))
                                    logger.warning(f"{item_name}: part of it (id {ids}) has not landed yet -- "
                                                   f"retrying; `/getitem {item_name}` forces it.")
                                delivered = True
                            else:
                                ctx._delivery_confirm_streak[idx] = streak
                                delivered = False
                        else:
                            # Reverted, or never took: the streak starts over, since one bad reading means
                            # whatever reverted the write may still be active. Same fixed baseline throughout.
                            ctx._delivery_confirm_streak[idx] = 0
                            # A retry that cannot change anything is a bug. Re-writing every poll while the item
                            # stayed unconfirmed made it climb by `quantity` per second until the slot's u16
                            # overflowed and the pack raised, eighteen hours in. Retrying is right while the
                            # write might still land, and wrong once the slot physically cannot hold more. So it
                            # stops, the item is marked delivered -- it IS in the Bag, at the largest quantity
                            # the slot can express -- and the player is told once, loudly, because a saturated
                            # slot means something upstream never confirmed.
                            if ram_client.bag_slot_is_saturated(read_base, read_slots, game_item_id):
                                logger.warning(f"{item_name}: that Bag slot is at the game's maximum "
                                               f"({ram_client.BAG_SLOT_QUANTITY_MAX}) -- marked delivered.")
                                # `delivered = True` alone: the `if delivered:` tail below already clears every
                                # piece of per-item pending state, and duplicating it is how copies drift.
                                ctx._delivery_peak.pop(idx, None)
                                delivered = True
                            elif not _give_item_or_pc_overflow(ctx, idx, item_name, pocket_base, game_item_id,
                                                            quantity, max_slots,
                                                            bool(ctx._delivery_counts_pc.get(idx))):
                                # Same as the saturated slot above: a retry into a full write window cannot
                                # change anything, and never reaches memory, so nothing climbs to reveal it.
                                _warn_write_window_full(ctx, idx, item_name, pocket_base, max_slots)
                                delivered = False
                            else:
                                ctx.save_timeline.stamp(idx)
                                if idx not in ctx._delivery_warned_indices:
                                    _note_warn(ctx, f"Received {item_name} but couldn't yet confirm it landed "
                                                    "in your Bag -- will keep retrying silently every poll "
                                                    "until confirmed (this won't be logged again for this "
                                                    "item). Other received items are still being delivered "
                                                    "normally.")
                                    ctx._delivery_warned_indices.add(idx)
                                delivered = False
        except Exception:
            # Never let one bad item take down the rest of the queue, or the rest of this poll's checks: log
            # once, leave it un-given so a transient failure is retried next poll, and keep going.
            if idx not in ctx._delivery_warned_indices:
                # ADDENDUM 445: one line by default; the traceback is `/verbose` only.
                logger.warning(f"Couldn't deliver {item_name} yet ({sys.exc_info()[0].__name__}) -- retrying.")
                _note(ctx, traceback.format_exc())
                ctx._delivery_warned_indices.add(idx)
            delivered = False
        if delivered:
            ctx.given_item_indices.add(idx)
            ctx._delivery_warned_indices.discard(idx)
            ctx._delivery_write_full_warned.discard(idx)
            ctx._delivery_counts_pc.pop(idx, None)
            ctx._delivery_pc_announced.discard(idx)
            ctx._delivery_pending_baseline.pop(idx, None)
            ctx._delivery_confirm_streak.pop(idx, None)
            ctx._delivery_first_seen.pop(idx, None)
            changed = True
    if changed:
        ctx._save_local_state()


def describe_wonder_trade_box(ctx: PokemonXDContext, box: int) -> "list[str]":
    """One PC box's occupants with their slot numbers, for picking one to send."""
    from .game_data import wonder_trade as wt

    if ctx.block_base is None:
        return ["Not hooked to the game yet."]
    if not 1 <= box <= ram_client.WONDER_TRADE_BOXES:
        return [f"Box is 1-{ram_client.WONDER_TRADE_BOXES}."]
    lines = [f"Box {box}:"]
    for slot in range(ram_client.PC_BOX_SLOTS_PER_BOX):
        record = ram_client.read_box_record(ctx.block_base, (box - 1) * ram_client.PC_BOX_SLOTS_PER_BOX + slot)
        if record is None or record[:2] == b"\x00\x00":
            continue
        nickname = wt.decode_name(record[wt.OFF_NICKNAME:wt.OFF_NICKNAME + wt.NAME_BYTES]) or "?"
        dex = wt.tables.SPECIES.get(int.from_bytes(record[:2], "big"), (None,))[0]
        kind = wt.species_name(dex).title() if dex else "?"
        head = kind if nickname.upper() == kind.upper() else f"{nickname} ({kind})"
        note = " -- Shadow" if wt.is_shadow(record) else ""
        lines.append(f"  slot {slot + 1}: {head}, Lv {record[wt.OFF_LEVEL]}{note}")
    if len(lines) == 1:
        lines.append("  (empty)")
    return lines


def poll_wonder_trade(ctx: PokemonXDContext) -> None:
    """Start the next wonder trade step as its own task when one is due. Never raises, never waits."""
    trade = getattr(ctx, "wonder_trade", None)
    if trade is None or not trade.wants_poll():
        return
    running = getattr(ctx, "_wonder_trade_task", None)
    if running is not None and not running.done():
        return

    def is_safe() -> bool:
        try:
            return (ctx.block_base is not None and not ctx.save_timeline.holding()
                    and ram_client.read_battle_ui_flag() != 1)
        except Exception:
            return False
    ctx._wonder_trade_task = asyncio.create_task(trade.poll(ctx, is_safe), name="WonderTrade")


def force_pokespot_encounter(ctx: PokemonXDContext, args) -> "list[str]":
    """`/pokespotforce`: list each spot's Pokemon, or put one of them at a spot."""
    import random as _random

    from .tools.xd_species_index import name_for

    def label(species: int) -> str:
        return (name_for(species) or f"species {species}").title()

    words = [str(a).strip().lower() for a in args if str(a).strip()]
    spots = {name.lower(): name for name in ram_client.POKESPOT_ROW_INDEX}
    if not words:
        lines = ["/pokespotforce rock|oasis|cave [number or name] -- puts one of that spot's Pokemon there, waiting:"]
        for spot in ram_client.POKESPOT_ROW_INDEX:
            pool = ram_client.pokespot_candidates(spot)
            lines.append(f"  {spot}: " + (", ".join(f"{i} {label(sp)}" for i, sp in enumerate(pool, 1))
                                         if pool else "not readable right now"))
        return lines
    spot = spots.get(words[0].replace("spot", "").strip())
    if spot is None:
        return ["Which spot? rock, oasis or cave."]
    pool = ram_client.pokespot_candidates(spot)
    if not pool:
        return [f"The {spot} Poke Spot's table isn't readable right now."]
    pick = " ".join(words[1:])
    if not pick:
        species = _random.choice(pool)
    elif pick.isdigit() and 1 <= int(pick) <= len(pool):
        species = pool[int(pick) - 1]
    else:
        matches = [sp for sp in pool if label(sp).lower() == pick] or \
                  [sp for sp in pool if label(sp).lower().startswith(pick)]
        if not matches:
            return [f"{pick.title()} can't appear at the {spot} Poke Spot. It has: "
                    + ", ".join(f"{i} {label(sp)}" for i, sp in enumerate(pool, 1)) + "."]
        species = matches[0]
    if not ram_client.force_pokespot(spot, species):
        return [f"Couldn't write the {spot} Poke Spot right now."]
    lines = [f"{label(species)} is waiting at the {spot} Poke Spot."]
    room = ram_client.POKESPOT_ROOM_BY_SPOT[spot]
    if ctx.room_tracker.current == room:
        lines.append("You're standing there now: it appears the next time you arrive.")
    else:
        lines.append("Go there to meet it.")
    if ram_client.gs_flag_get(ram_client.MIROR_B_PLACE_VAR) == room:
        lines.append("Miror B. is at that spot right now, so you'll meet him first.")
    return lines


def describe_miror_queue(ctx: PokemonXDContext) -> "list[str]":
    """`/mirorqueue`: the save's Miror B. queue, where he is, and which of them the client sent him."""
    from .tools.xd_species_index import name_for

    queue = ram_client.read_miror_queue(ctx.block_base)
    if queue is None:
        return ["The save's Shadow list isn't readable right now (no save loaded, or it's being rewritten). "
                "Try again in a moment."]
    place = ram_client.gs_flag_get(ram_client.MIROR_B_PLACE_VAR)
    places = {pid: name for pid, name in ram_client.MIROR_PLACE_IDS.values()}
    where = ("He isn't out right now." if not place
             else f"He's out at the {places[place]}." if place in places else f"He's out (place id {place}).")
    if not queue:
        return ["Miror B. has no Shadows queued. He only appears while he's holding at least one. " + where,
                "His copy outside Kaminko's House fights whenever he is holding one."]
    sent = {name.strip().upper() for name in getattr(ctx.missable_shadow_pusher, "sent", ())}
    lines = [f"Miror B. is holding {len(queue)} Shadow(s). {where} His copy outside Kaminko's House fights for them "
             "too."]
    for shadow_id, species, escaped in sorted(queue, key=lambda q: (q[2], q[0])):
        name = (name_for(species) or f"species {species}").title()
        note = " -- sent by the client from a missable trainer" if name.upper() in sent else ""
        lines.append(f"  {name} (Shadow #{shadow_id}, escaped at step {escaped}){note}")
    return lines


def read_save_clock_safely(ctx: PokemonXDContext) -> "ram_client.SaveClockReading | None":
    if ctx.block_base is None:
        return None
    try:
        return ram_client.read_save_clock()
    except Exception:
        return None


def save_clock_allows_trust(ctx: PokemonXDContext, reading: "ram_client.SaveClockReading | None") -> bool:
    """False while a save or load is under way (the save dialog is open or the memory card is working -- the dialog
    copies the card's file over the live data while it asks about overwriting), and on a tick whose play time does
    not follow on from the last one (another save's data has just come in). Either one restarts the block's settle
    count, so nothing reads the story, travel or flags until the data has held still again. An unreadable clock
    leaves the decision to the block-stability gate."""
    if reading is None:
        return True
    if reading.busy:
        ctx.save_distrust["saving"] += 1
        return False
    try:
        jumped = ctx.clock_continuity.poll(reading)
    except Exception:
        return True
    if jumped:
        ctx.save_distrust["clock jump"] += 1
        return False
    return True


def check_save_clock(ctx: PokemonXDContext, block_is_stable: bool,
                     reading: "ram_client.SaveClockReading | None" = None) -> None:
    """Reads the save clock and, when the play time has gone back, hands every delivery the loaded save no longer
    holds back to give_items(). Items still waiting start over too: their baselines describe the old timeline."""
    if ctx.block_base is None:
        return
    saves_before = ctx.save_timeline.saves_seen
    try:
        point = ctx.save_timeline.poll(reading if reading is not None else ram_client.read_save_clock(),
                                       block_is_stable)
    except Exception:
        return
    if point is None:
        if ctx.save_timeline.saves_seen != saves_before:
            ctx._save_local_state()     # the save's time has to outlive the client to be any use after a reboot
        return
    ctx._snag_machine_check_due = True
    lost = [idx for idx in ctx.save_timeline.taken_back(point) if idx < len(ctx.items_received)]
    for idx in lost:
        ctx.given_item_indices.discard(idx)
    for idx in range(len(ctx.items_received)):
        if idx in ctx.given_item_indices:
            continue
        for pending in (ctx._delivery_pending_baseline, ctx._delivery_confirm_streak, ctx._delivery_peak,
                        ctx._delivery_counts_pc, ctx._delivery_companion_pending):
            pending.pop(idx, None)
        ctx._delivery_pc_announced.discard(idx)
        ctx._delivery_warned_indices.discard(idx)
        ctx._delivery_write_full_warned.discard(idx)
    loaded, seen, _point = ctx.save_timeline.last_rewind or (0.0, 0.0, point)
    if lost:
        names = [ITEM_ID_TO_NAME.get(ctx.items_received[i].item, "an item") for i in lost]
        shown = ", ".join(names[:8]) + (f" and {len(names) - 8} more" if len(names) > 8 else "")
        logger.info(f"Your game went back to play time {ram_client.format_playtime(loaded)} (it was at "
                    f"{ram_client.format_playtime(seen)}). Sending {len(lost)} item(s) again that the loaded "
                    f"save doesn't have: {shown}.")
    else:
        _note(ctx, f"Play time went back to {ram_client.format_playtime(loaded)} from "
                   f"{ram_client.format_playtime(seen)}; nothing delivered after that point needed sending again.")
    ctx._save_local_state()


SNAG_MACHINE_LAB_ABOVE = 0x03


def _hq_lab_progress(ctx: PokemonXDContext) -> "int | None":
    """The HQ Lab's story value: its own area's with travel shuffled, the one story byte without."""
    area_progress = _missable_area_progress(ctx)
    if area_progress is not None:
        return area_progress("Pokemon HQ Lab")
    return ram_client.read_story_byte(ctx.block_base)


def open_kaminko_on_map(ctx: PokemonXDContext) -> bool:
    """Kaminko's House selectable on the world map. True once the bit is written."""
    if ctx.block_base is None:
        return False
    try:
        travel_locations.write_kaminko_bit(ctx.block_base + travel_locations.TRAVEL_RECORD_OFFSET_FROM_BLOCK_BASE)
    except Exception:
        return False
    return True


def check_snag_machine_after_reload(ctx: PokemonXDContext, block_is_stable: bool) -> None:
    """After a crash or a reload (the save found again, or its play time gone back), a game whose HQ Lab is past
    0x03 without the Snag Machine is given it. Checked once per load, as soon as both can be read."""
    if not getattr(ctx, "_snag_machine_check_due", False) or ctx.block_base is None or not block_is_stable:
        return
    try:
        owned = ram_client.read_snag_machine(ctx.block_base)
        lab = _hq_lab_progress(ctx)
        if owned is None or lab is None:
            return
        ctx._snag_machine_check_due = False
        if owned or lab <= SNAG_MACHINE_LAB_ABOVE:
            return
        if not (ram_client.write_snag_machine(ctx.block_base, True) and open_kaminko_on_map(ctx)):
            ctx._snag_machine_check_due = True
            return
        naps = ram_client.hand_shadow_to_miror(ctx.block_base, ram_client.NAPS_SHADOW_RECORD,
                                               getattr(getattr(ctx, "missable_shadow_pusher", None), "rng", None))
        logger.info(f"The loaded game had no Snag Machine with the HQ Lab at 0x{lab:02X}; it's back in your "
                    "hands, and Kaminko's House is open on the map."
                    + (" Naps's Shadow is with Miror B. now." if naps else ""))
    except Exception:
        pass


def force_deliver_pending_items(ctx: PokemonXDContext, name_filter: str = "") -> None:
    """Backs `/getitem`: a manual escape hatch that skips both of give_items()' safety holds on purpose. It
    never consults the battle/step gate, and it issues exactly ONE write per item and marks it delivered with no
    baseline, re-read or confirm streak. Same kind of opt-in override as `/checked` and `/goal`.

    Targets every pending item, or only those whose name fuzzy-matches `name_filter`. Each is attempted in its
    own try/except, and once written its give_items()-side pending state is cleared so a later poll does not pick
    up a half-finished baseline. With no confirmation re-read, a write reverted afterwards (most likely because
    the player really is mid-battle) is never noticed or retried -- run `/getitem` again."""
    if ctx.block_base is None:
        logger.info("Not connected to a running game yet -- nothing to force-deliver.")
        return
    received = ctx.items_received
    pending_indices = [idx for idx in range(len(received)) if idx not in ctx.given_item_indices]
    if not pending_indices:
        logger.info("Nothing pending -- every received item has already been delivered.")
        return
    needle = _normalize_for_match(name_filter) if name_filter.strip() else None
    if needle is not None:
        pending_indices = [
            idx for idx in pending_indices
            if needle in _normalize_for_match(ITEM_ID_TO_NAME.get(received[idx].item, ""))
        ]
        if not pending_indices:
            logger.info(f"No pending received item matches {name_filter!r}.")
            return
    changed = False
    for idx in pending_indices:
        network_item = received[idx]
        item_name = ITEM_ID_TO_NAME.get(network_item.item, f"Unknown Item {network_item.item}")
        try:
            if item_name in EFFECT_ITEM_NAMES:
                _apply_effect_item(ctx, item_name)
                if item_name not in TRAP_ITEM_NAMES:
                    ctx.save_timeline.stamp(idx)
            else:
                data = ITEM_TABLE.get(item_name)
                game_item_id = data.game_item_id if data is not None else None
                # The gating key items belong to reconcile_key_items(). Doing both would race: this
                # function's confirm streak would read a quantity the reconciler had just written and both
                # would think they did it. Marked delivered, not skipped -- a pending index parks forever.
                managed_ids = managed_key_item_ids(ctx)
                if managed_ids and game_item_id in managed_ids:
                    if idx not in ctx._delivery_warned_indices:
                        logger.info(f"Received {item_name} -- the key-item reconciler keeps this one in your "
                                    f"Bag from now on (see /keyitems).")
                        ctx._delivery_warned_indices.add(idx)
                    ctx.given_item_indices.add(idx)
                    continue
                quantity = data.quantity if data is not None else 1
                pocket = ram_client.resolve_item_pocket(ctx.block_base, game_item_id)
                if pocket is not None:
                    pocket_base, max_slots = pocket
                    # Single write, no verify/confirm-streak -- see this function's docstring. "No verify" is
                    # still not "no answer": `give_item` returns False when every slot in the write window is
                    # taken, having touched no memory, and a silent `/getitem` reads as success.
                    if not _give_item_or_pc_overflow(ctx, idx, item_name, pocket_base, game_item_id, quantity,
                                                  max_slots, True):
                        logger.warning(
                            f"/getitem: {item_name} could not be written to your Bag -- every slot this "
                            f"client may write to in that pocket is already in use by a different item. "
                            f"Make room and run /getitem again."
                        )
                    # A packaged item's extra ids go through the same hatch, written once each with no re-read.
                    # Without this, `/getitem` on the Data ROM & ID Card hands over half of it.
                    for companion_id in (data.companion_game_item_ids if data is not None else ()):
                        companion_pocket = ram_client.resolve_item_pocket(ctx.block_base, companion_id)
                        if companion_pocket is None:
                            continue
                        c_base, c_slots = companion_pocket
                        ram_client.give_item(c_base, companion_id, 1, c_slots)
                    ctx.save_timeline.stamp(idx)
                # pocket is None (Ein File S / the unresolved key items / the trap already handled above) --
                # nothing to write, same as give_items()'s own handling; still counts as delivered below.
        except Exception:
            logger.warning(f"/getitem: couldn't force {item_name} ({sys.exc_info()[0].__name__}) -- still pending.")
            _note(ctx, traceback.format_exc())   # ADDENDUM 445: the traceback is `/verbose` only
            continue
        ctx.given_item_indices.add(idx)
        ctx._delivery_warned_indices.discard(idx)
        ctx._delivery_pending_baseline.pop(idx, None)
        ctx._delivery_counts_pc.pop(idx, None)
        ctx._delivery_confirm_streak.pop(idx, None)
        ctx._delivery_first_seen.pop(idx, None)
        ctx._delivery_companion_pending.pop(idx, None)   # written above, so stop retrying it
        logger.info(f"/getitem: force-delivered {item_name} immediately (bypassed the battle-safety wait and "
                    "the normal confirm-streak check).")
        changed = True
    if changed:
        ctx._save_local_state()


# Travel-location unlocks (options.RandomizeTravelLocations)

def _always_open_gate_is_open(ctx: PokemonXDContext) -> bool:
    """True once the story has reached 0x0F in the Pokemon HQ Lab.

    Reads the LIVE byte, not the lab's mark, deliberately: the mark cannot reach 0x0F, because the live bump's own
    `0x0D -> 0x0F` write goes through `last_written_*` so `observe` refuses it -- and refuses a game-set 0x0F too,
    since nothing in RAM distinguishes them. Measured: the lab's mark goes straight from absent to 0x10. The
    mark's strict reading is still wanted elsewhere, or the bump's 0x0F satisfies the lab's 0x17 rule and buying
    the Machine Part fast-forwards the Krane Memos.

    The region test keeps the live byte honest: a hover write lands on the map screen, where `region_for_room` is
    None rather than the lab, and the Parts override and scooter hold write in Gateon and the SS Libra, so none
    can satisfy "standing in the lab, byte at or past 0x0F". Latched once open, and persisted, because this is a
    grant -- otherwise the gate shuts when the player leaves the lab, or a reconnect re-locks two earned
    destinations."""
    if ctx._always_open_gate_latched:
        return True
    from .game_data import chest_regions, story_bytes

    reached = story_bytes.highest_in_area(travel_locations.ALWAYS_OPEN_GATE_AREA,
                                          ctx.area_story_memory.highest_by_region)
    if reached is not None and reached >= travel_locations.ALWAYS_OPEN_GATE_BYTE:
        ctx._always_open_gate_latched = True
        ctx._save_local_state()
        return True
    region = chest_regions.region_for_room(ctx.room_tracker.current)
    if region != travel_locations.ALWAYS_OPEN_GATE_AREA:
        return False
    live = ram_client.read_story_byte(ctx.block_base)
    if live is None or live < travel_locations.ALWAYS_OPEN_GATE_BYTE:
        return False
    ctx._always_open_gate_latched = True
    ctx._save_local_state()
    return True


#: ADDENDUM 474. SS Libra must never be usable as a way back into Phenac without Phenac itself. Logic requires Phenac
#: (`travel_locations.TRAVEL_LOCATION_REQUIRED_REGIONS`); this is the hard half. The stranded ship's own cutscene ends
#: by putting the player in Phenac, so an SS Libra icon usable without Phenac was a way INTO Phenac.
#: ADDENDUM 481: the Phenac clear is not needed at all -- the icon now waits for the Phenac UNLOCK, not the Sixes.
SS_LIBRA_TRAVEL_NAME = "SS Libra"
PHENAC_TRAVEL_NAME = "Phenac City"
PHENAC_CLEARED_REGION = "Phenac City (Post-Sixes)"     # ADDENDUM 474's condition, kept for `_phenac_cleared`


def _phenac_unlocked(ctx: PokemonXDContext) -> bool:
    """ADDENDUM 481: the multiworld has sent Travel Unlock - Phenac City. The delivered set is persisted, so a reconnect
    that has not been resent `items_received` yet still answers yes; `items_received` is read too, for the poll that
    delivers it."""
    if PHENAC_TRAVEL_NAME in (getattr(ctx, "received_travel_locations", None) or ()):
        return True
    wanted = travel_locations.travel_unlock_item_name(PHENAC_TRAVEL_NAME)
    return any(ITEM_ID_TO_NAME.get(network_item.item) == wanted
               for network_item in (getattr(ctx, "items_received", None) or ()))


def _phenac_cleared(ctx: PokemonXDContext) -> bool:
    """The Sixes are behind the player in Phenac: its own area progress reached the Post-Sixes floor."""
    from .game_data import story_bytes as _story_bytes

    floor = _story_bytes.region_floor(PHENAC_CLEARED_REGION)
    progress = _story_bytes.area_progress(PHENAC_CLEARED_REGION, ctx.area_story_memory.highest_by_region)
    return floor is not None and progress is not None and progress >= floor


def _travel_held_closed(ctx: PokemonXDContext, name: str) -> bool:
    """ADDENDUM 474: a destination whose item has arrived but whose map bit stays clear for now. ADDENDUM 481: the SS
    Libra waits for the Phenac unlock (was: Phenac cleared -- REVERT `not _phenac_cleared(ctx)`)."""
    return name == SS_LIBRA_TRAVEL_NAME and not _phenac_unlocked(ctx)


async def sync_travel_locations(ctx: PokemonXDContext) -> None:
    """Delivers "Travel Unlock - {name}" items. Not routed through give_items(): these occupy no Bag slot, and
    the live memory record they write has never been confirmed to survive a Dolphin reboot or save-state reload
    (travel_locations.py's save-safety caveat). So given_item_indices is not enough -- an index already in it is
    never attempted again, but the RAM bits it set may be gone after a reboot. This tracks
    `ctx.received_travel_locations` separately and re-applies every received location's bits on a fresh
    `block_base`, retrying until it succeeds, along with every equally volatile
    `travel_locations.ALWAYS_OPEN_TRAVEL_BITS` entry. No-ops with randomize_travel_locations off."""
    if not ctx.randomize_travel_locations or ctx.block_base is None:
        return
    record_base = ctx.block_base + travel_locations.TRAVEL_RECORD_OFFSET_FROM_BLOCK_BASE

    # Agate and Gateon wait for the lab to reach 0x0F, checked EVERY poll rather than once per block base: the
    # condition changes during play, so a once-per-boot write would open the pair too early or never.
    #
    # It CLEARS while the gate is shut rather than declining to write: these are always-open in vanilla, so the
    # game sets the bits itself and declining would gate nothing.
    try:
        gate_open = _always_open_gate_is_open(ctx)
        if gate_open:
            travel_locations.write_always_open_bits(record_base)
            if not ctx._always_open_gate_announced:
                ctx._always_open_gate_announced = True
                _note(ctx, f"Pokemon HQ Lab reached 0x{travel_locations.ALWAYS_OPEN_GATE_BYTE:02X} -- Agate "
                           "Village and Gateon Port are now selectable on the map.")
        elif travel_locations.clear_always_open_bits(record_base):
            # Only on a real CHANGE, so this is one line when the game grants them, not one per poll.
            _note(ctx, "Travel: held Agate Village and Gateon Port closed -- the HQ Lab has not reached "
                       f"0x{travel_locations.ALWAYS_OPEN_GATE_BYTE:02X} yet.")
    except Exception:
        pass  # transient, like every other write here -- retried next poll

    # Received destinations are re-asserted EVERY POLL, not once per block base. The game keeps writing the same
    # byte: when the story reaches the point that would have unlocked the area in the unmodified game it sets
    # that area's PARTIAL bit, so a once-per-boot write leaves the icon in the full|partial state that
    # `_or_write_bit` masks off. Costs one byte read per received destination, and they share bytes (0x08 holds
    # three), so at most eleven; `_or_write_bit` writes only on a real change.
    try:
        for name in ctx.received_travel_locations:
            if _travel_held_closed(ctx, name):
                continue        # ADDENDUM 474 -- `enforce_travel_locks` keeps it clear until Phenac is cleared
            travel_locations.write_travel_location_bit(record_base, name)
    except Exception:
        _note_warn(ctx, "Couldn't apply the always-open/previously-received travel unlocks yet (still "
                        "looking for the travel-control record) -- will keep retrying every poll.")
        return
    # The notice stays one-shot per block base even though the write is per-poll -- it is a reconnect message.
    if ctx._travel_bits_applied_for_block_base != ctx.block_base:
        ctx._travel_bits_applied_for_block_base = ctx.block_base
        if ctx.received_travel_locations:
            _note(ctx, f"Re-applied {len(ctx.received_travel_locations)} previously-received travel "
                       "unlock(s) after reconnecting.")

    # New-item delivery: any received "Travel Unlock - X" item not yet in received_travel_locations.
    changed = False
    for network_item in ctx.items_received:
        item_name = ITEM_ID_TO_NAME.get(network_item.item)
        if item_name is None:
            continue
        location_name = travel_locations.travel_location_name_from_item(item_name)
        if location_name is None or location_name in ctx.received_travel_locations:
            continue
        if _travel_held_closed(ctx, location_name):
            ctx.received_travel_locations.add(location_name)
            logger.info(f"Received {item_name} -- {location_name} opens on the map once Phenac City is "
                        "unlocked too.")
            changed = True
            continue
        try:
            travel_locations.write_travel_location_bit(record_base, location_name)
        except Exception:
            continue  # transient -- retried again next poll, same as every other write in this file
        ctx.received_travel_locations.add(location_name)
        logger.info(f"Received {item_name} -- {location_name} is now selectable on the map.")
        changed = True
    if changed:
        ctx._save_local_state()


# Detecting checks

async def check_species_catches(ctx: PokemonXDContext) -> None:
    """Species-catch detection for "Catch - {species}". There is no in-battle "catch confirmed" RAM signal the way
    there is an HP-reaches-zero signal for a defeat, so ownership is the signal.

    Three sources, unioned: PARTY_BASE (a 0x30-byte menu row -- fast, but it does not populate a slot until the
    party screen has drawn), the save block's own party records (BLOCK_BASE + PARTY_RECAP_OFFSET, the 0xC4 format
    the boxes use), and a full PC-box scan so a catch routed straight into the PC registers on its own. `/party`
    prints the first two side by side.

    The box half goes through `ram_client.SpeciesCatchTracker`, which discards a box poll whose snapshot gains and
    loses species at once (or gains more than one) and holds anything left for several trusted polls. Without
    that, a save-menu open that made the box region read as an earlier snapshot of itself sent real,
    never-before-checked locations -- a wrong location checked outright, which the server's dedup cannot cover.

    A newly-seen Eeveelution also queues EEVEELUTION_LOCATION_NAME, and `ctx.check_locations` is idempotent, so
    no one-shot guard is needed."""
    if ctx.block_base is None:
        return
    # The live save-resident `Pokemon` records, not PARTY_BASE: no menu has to have been opened, and species come
    # from the numeric field, so a nicknamed Pokemon counts. PARTY_BASE is unioned in below as a second witness.
    party_species = ram_client.get_live_party_species_snapshot(ctx.block_base)
    try:
        party_species |= ram_client.get_owned_species_snapshot(ctx.block_base, ram_client.PARTY_BASE)
    except Exception:
        pass
    # Boxes and the save-block party are passed SEPARATELY, not unioned: unioning put party-shaped data through a
    # guard that assumes one-slot-at-a-time box movement, so every withdrawal looked like the save-menu glitch.
    #
    # The box scan keeps its own ~1s cadence however fast the loop runs, reusing the previous snapshot between
    # scans -- an unchanged snapshot is a trusted poll that advances nothing, so reuse neither fires early nor
    # resets a streak. The recap (party) half is cheap and runs every poll.
    now = time.monotonic()
    # The scan reports whether it read every slot. A snapshot with a failed slot read is INCOMPLETE and must
    # never be read as "those Pokemon are gone" -- that is what stopped catches sending after two or three.
    if now - ctx._last_box_scan >= BOX_SCAN_MIN_INTERVAL:
        ctx._last_box_scan = now
        ctx._last_box_species, _box_failures = ram_client.get_box_species_snapshot_detailed(ctx.block_base)
        ctx._last_box_complete = _box_failures == 0
    box_species = ctx._last_box_species
    recap_species = ram_client.get_party_recap_species_snapshot(ctx.block_base)
    # A wonder-traded Pokemon was not caught: a species only it holds is left out of all three.
    traded_pids = getattr(getattr(ctx, "wonder_trade", None), "received_pids", None)
    if traded_pids:
        traded_only = ram_client.traded_only_species(ctx.block_base, traded_pids)
        if traded_only:
            party_species = set(party_species) - traded_only
            box_species = set(box_species) - traded_only
            recap_species = set(recap_species) - traded_only
    newly_seen = set(ctx.species_catch_tracker.poll(
        party_species, box_species, recap_species,
        box_complete=getattr(ctx, "_last_box_complete", True),
    ))
    if not newly_seen:
        return
    location_names = [species.location_name_for_species(dex_number) for dex_number in sorted(newly_seen)]
    if newly_seen & species.EEVEELUTION_DEX_NUMBERS:
        location_names.append(EEVEELUTION_LOCATION_NAME)
    await _send_checks(ctx, location_names)


async def check_shadow_monitor_catches(ctx: PokemonXDContext) -> None:
    """`Catch - {species}` for every Shadow the in-game Shadow Monitor marks snagged or purified -- the game's own
    record, so a snag counts wherever the Pokemon went afterwards. A species has to read snagged on two polls in a row.
    Adds to the party/PC detection; never replaces it."""
    if ctx.block_base is None:
        return
    current = ram_client.read_snagged_shadow_species(ctx.block_base)
    if current is None:
        return
    confirmed = current & ctx._shadow_monitor_last
    ctx._shadow_monitor_last = current
    fresh = confirmed - ctx._shadow_monitor_sent
    if not fresh:
        return
    from .tools.xd_species_index import national_dex_for

    seed_ids = seed_location_ids(ctx)
    names = []
    for internal in sorted(fresh):
        ctx._shadow_monitor_sent.add(internal)
        dex = national_dex_for(internal)
        if dex is None:
            continue
        try:
            name = species.location_name_for_species(dex)
        except KeyError:
            continue
        location_id = LOCATION_NAME_TO_ID.get(name)
        if location_id is None or location_id in ctx.checked_locations or (seed_ids and location_id not in seed_ids):
            continue
        names.append(name)
    if names:
        await _send_checks(ctx, names)


def purification_counts_not_sent(ctx: PokemonXDContext) -> "list[str]":
    """`Purify N` for every N up to the ledger's total that the server has not checked and nothing is re-sending."""
    total = min(int(getattr(ctx.purification_tracker, "total_purified", 0) or 0), ram_client.PURIFICATION_LOCATION_COUNT)
    pending = getattr(ctx, "pending_check_ids", None) or set()
    out: "list[str]" = []
    for count in range(1, total + 1):
        name = ram_client.purification_location_name(count)
        location_id = LOCATION_NAME_TO_ID.get(name)
        if location_id is None or location_id in ctx.checked_locations or location_id in pending:
            continue
        out.append(name)
    return out


async def check_purifications(ctx: PokemonXDContext) -> None:
    if ctx.block_base is None:
        return
    # A Pokemon does not become purified mid-fight, and a battle is when PARTY_BASE and the recap records are least
    # trustworthy. The tracker holds its baselines while skipping, so this delays a check, never drops one.
    in_battle = False
    try:
        in_battle = ctx.trainer_defeat_tracker.has_unresolved_battle()
    except Exception:
        in_battle = False
    # The `_looks_ingame()` gate wraps this ONE call, not the function: `PurificationTracker.poll` correlates the
    # recap array against PARTY_BASE, and that has never been confirmed safe against an all-zero PARTY_BASE.
    # Everything else here reads save data. The state scan below covers what this watcher cannot see anyway.
    newly_crossed: "list[str]" = []
    if _looks_ingame():
        newly_crossed = ctx.purification_tracker.poll(
            ctx.block_base, ram_client.PARTY_BASE, in_battle=in_battle
        )
    # The party/PC state scan, alongside the flip-watcher above. That watcher has to SEE the flag flip in a party
    # slot; the Purify Chamber hands the Pokemon back to the PC, and a purification from before this client
    # connected never flips at all. This reads the STATE of every party and PC record instead, on the box cadence
    # rather than every poll: 360 record reads.
    if not in_battle and time.monotonic() - ctx._last_purification_scan >= BOX_SCAN_MIN_INTERVAL:
        ctx._last_purification_scan = time.monotonic()
        try:
            records = ram_client.scan_shadow_records(
                ctx.block_base,
                box_slots=list(range(ram_client.PC_BOX_SCAN_COUNT * ram_client.PC_BOX_SLOTS_PER_BOX)),
            )
            _traded = getattr(getattr(ctx, "wonder_trade", None), "received_pids", None)
            if _traded:
                records = [r for r in records if r.pid not in _traded]   # wonder trades purified nothing here
            _shadow_dex = ctx.seed_shadow_dex()
            newly_crossed = list(newly_crossed) + ctx.purification_tracker.observe_records(
                records,
                seed_shadow_dex=_shadow_dex,
                # Species this seed hands out WITHOUT a purification -- the guaranteed Eevee and its
                # evolutions, and this seed's Poke Spot species. Rule 2 must not fire on one.
                obtainable_elsewhere_dex=ctx.obtainable_without_purifying(),
                # The species the CATCH scan has seen the player own. Rule 2 infers ownership, so it leans on the
                # one scan already hardened against a bad box poll rather than trusting a single record.
                trusted_owned_dex=set(getattr(ctx.species_catch_tracker, "seen", None) or ()),
                # One Shadow can be purified once, so the seed's Shadow count is a real ceiling. `None` when the
                # seed did not say, leaving the PURIFICATION_LOCATION_COUNT cap as the only one.
                shadow_count_cap=len(_shadow_dex) or None,
            )
            # The save's own Shadow status table: it also sees a Shadow purified in the chamber and moved on, or
            # before this client connected. Same id ledger, so nothing is counted twice.
            monitor_ids = ram_client.read_shadow_monitor(ctx.block_base)
            if monitor_ids:
                newly_crossed = list(newly_crossed) + ctx.purification_tracker.observe_monitor(
                    monitor_ids, shadow_count_cap=len(_shadow_dex) or None)
            # Say WHICH record caused each count -- a count printed only as a location name cannot be traced
            # when two checks arrive for one purification.
            for line in ctx.purification_tracker.last_counts:
                _note(ctx, f"Purification counted from {line}")
            # ADDENDUM 407: a PID the game changed at purification (the Unown letter case). Loud, because it is
            # the evidence that case needs and it happens once per Shadow at most.
            for line in ctx.purification_tracker.new_pid_changes:
                _note_warn(ctx, f"Purification changed this Pokemon's PID -- {line}. Please report it with "
                                "`/purifications`.")
        except Exception:
            logger.debug("Pokemon XD: purification scan failed this poll", exc_info=True)
    # ADDENDUM 415: with "Purification Checks" off the count is still kept (it is the ledger that stops a
    # double-count if the setting were ever read differently), but nothing is sent.
    if newly_crossed and ctx.purification_checks:
        await _send_checks(ctx, newly_crossed)
    # Every count up to the ledger's total has a `Purify N` on the server. A count whose send never reached it (a
    # ledger that already held this seed's Shadows when the client connected, say) goes out here, once the server
    # has said what it has.
    if ctx.purification_checks and _lab_hold_inputs_ready(ctx):
        missing = purification_counts_not_sent(ctx)
        if missing:
            await _send_checks(ctx, missing)
    # Persist the species ledger the moment it changes, not on a timer: it records which species have already
    # been counted, and losing the last few seconds of that is the duplicate it exists to stop.
    if ctx.purification_tracker.dirty:
        ctx.purification_tracker.dirty = False
        ctx._save_local_state()


def robo_kyogre_parts_held(ctx: PokemonXDContext) -> int:
    """How many Robo Kyogre Parts the multiworld has sent this slot. Counted straight off `items_received`:
    the Parts have no in-game Bag item, so the received list is the only place they exist. They gate Citadark
    Isle; they are not a goal of their own."""
    return sum(1 for network_item in ctx.items_received
               if ITEM_ID_TO_NAME.get(network_item.item) == items.MACGUFFIN_ITEM_NAME)


def scooter_upgrade_held(ctx: PokemonXDContext) -> bool:
    """True when the SS Libra gate is satisfied -- the multiworld sent the Scooter Upgrade, or this seed never
    gated it. The second half keeps an opted-out seed playable: with `shuffle_scooter_upgrade` off the item is
    never created and `regions.py` drops it from the SS Libra edge, so a client that did not match would hold SS
    Libra at its stranded floor forever waiting for an item that does not exist. Keyed on
    `shuffle_scooter_upgrade`, not `key_item_shuffle` -- the Scooter has no Bag entry and its upgrade is a
    cutscene, so it has its own toggle covering both travel modes."""
    if not ctx.shuffle_scooter_upgrade:
        return True
    # ADDENDUM 474: LATCHED and persisted. SS Libra sometimes refused entry even with the scooter upgrade held, so the
    # story byte floor is guarded hard. `items_received` is empty for the first ticks after a
    # (re)connect, and in that window this said False: the SS Libra icon wrote the STRANDED tier (0x4E) and the story
    # hold pulled a byte on the real ship (0x58-0x5B) back to 0x57. Once the item has been seen, it is held for good.
    if getattr(ctx, "scooter_upgrade_seen", False):
        return True
    held = any(ITEM_ID_TO_NAME.get(network_item.item) == items.SCOOTER_ITEM_NAME
               for network_item in ctx.items_received)
    if held:
        ctx.scooter_upgrade_seen = True
        try:
            ctx._save_local_state()
        except Exception:
            pass
    return held


# Per-area story-byte memory: the file and the wiring. The rule itself lives in
# ram_client.AreaStoryByteMemory, including why the hook is the map screen and why there is no restore-on-exit.


def _area_memory_path(ctx: PokemonXDContext) -> "str | None":
    """One file per (seed, slot). Keyed by both because a player can run two slots of the same seed, and an
    area's high-water mark belongs to a save file rather than to a multiworld."""
    seed = getattr(ctx, "seed_name", None)
    slot = getattr(ctx, "slot", None)
    if not seed or slot is None:
        return None
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", str(seed))[:64]
    try:
        folder = Utils.user_path("pokemon_xd")
    except Exception:
        folder = os.path.join(os.path.expanduser("~"), ".pokemon_xd")
    return os.path.join(folder, f"area_story_bytes_{safe}_{slot}.json")


def _story_write_log_path(ctx: PokemonXDContext) -> "str | None":
    """Keyed by (seed, slot) like the area-memory file, and for the same reason: this is the log of a RUN, and
    a run is a save file rather than a client session."""
    path = _area_memory_path(ctx)
    if path is None:
        return None
    folder, name = os.path.split(path)
    return os.path.join(folder, name.replace("area_story_bytes_", "story_byte_writes_", 1))


def _load_story_write_log(ctx: PokemonXDContext) -> None:
    ctx.story_write_log_path = _story_write_log_path(ctx)
    path = ctx.story_write_log_path
    if not path or not os.path.exists(path):
        return
    try:
        with open(path, encoding="utf-8") as handle:
            ctx.story_write_log.load_json(json.load(handle))
    except Exception:
        # Quieter than the area-memory failure below: nothing reads this log back to decide anything, so an
        # unreadable one costs a diagnostic rather than the player's per-area progress.
        return
    if ctx.story_write_log.total:
        _note(ctx, f"Story-byte overwrite log: restored {ctx.story_write_log.total} entr"
                   f"{'y' if ctx.story_write_log.total == 1 else 'ies'} from a previous session.")


def _save_story_write_log(ctx: PokemonXDContext) -> None:
    path = ctx.story_write_log_path
    if not path or not ctx.story_write_log.dirty:
        return
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(ctx.story_write_log.to_json(), handle, indent=1)
        ctx.story_write_log.dirty = False
    except Exception:
        pass  # same contract as _save_area_memory: persistence never disturbs the poll loop


def _load_area_memory(ctx: PokemonXDContext) -> None:
    ctx.area_story_memory_path = _area_memory_path(ctx)
    path = ctx.area_story_memory_path
    if not path or not os.path.exists(path):
        return
    try:
        with open(path, encoding="utf-8") as handle:
            ctx.area_story_memory.load_json(json.load(handle))
    except Exception:
        # A corrupt or hand-edited file degrades to "no memory yet" rather than taking the client down. The
        # cost is that first visits are re-detected; the cost of raising here would be no client at all.
        logger.warning("Could not read the area story-byte memory file; starting with an empty memory.")
        return
    seen = len(ctx.area_story_memory.visited)
    if seen:
        _note(ctx, f"Area story-byte memory: restored {seen} area(s) from a previous session.")


def _save_area_memory(ctx: PokemonXDContext) -> None:
    """Written whenever the memory changed, not on a timer -- the value that matters is the high-water mark,
    and losing the last few seconds of it would send the player back to an area's floor."""
    path = ctx.area_story_memory_path
    if not path or not ctx.area_story_memory.dirty:
        return
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(ctx.area_story_memory.to_json(), handle, indent=1)
        ctx.area_story_memory.dirty = False
    except Exception:
        pass  # never let persistence disturb the poll loop -- the in-memory copy is still correct


def _hold_ss_libra_without_the_scooter(ctx: PokemonXDContext) -> None:
    """The travel-randomization-OFF path, SS Libra only. Same shape as the Gateon ceiling: the hover is the
    PRE-LOAD hook, so the byte has to be right while the cursor is still on the icon. Hover SS Libra without the
    Scooter and the byte is held at the stranded floor; hover elsewhere, or leave the map, and it goes back.

    It restores rather than clamping permanently, because in this mode the byte is the player's GLOBAL story
    progress and nothing else rewrites it. `0x57 -> 0x5A` is "scooter upgraded in Gateon" and the only way into
    0x5A or beyond, so a byte at or past 0x5A means the upgrade already happened in story, and a permanent clamp
    would rewind a player at 0x6E to 0x4E with nothing on disk to recover from. Restoring does not weaken the
    gate -- the room is BUILT from the byte at load time. `SS_LIBRA_HOLD_IS_PERMANENT` below is the one line to
    flip if that reasoning is rejected."""
    if ctx.area_story_memory.scooter_held:
        ctx.ss_libra_gate.poll_hover(ctx.block_base, None)   # release anything we were holding
        return
    room_id = ctx.room_tracker.current
    if room_id != ram_client.MAP_SCREEN_ROOM_ID:
        note = ctx.ss_libra_gate.poll(ctx.block_base, room_id)
        _claim_story_write(ctx, ctx.ss_libra_gate)
        if note:
            _note(ctx, note)
        return
    try:
        hovered = ram_client.map_destination_region(ctx.map_cursor_tracker.resolve())
    except Exception:
        hovered = None
    note = ctx.ss_libra_gate.poll_hover(ctx.block_base, hovered)
    _claim_story_write(ctx, ctx.ss_libra_gate)
    if note:
        _note(ctx, note)
    _save_story_write_log(ctx)


async def _bump_in_vanilla_travel(ctx: PokemonXDContext) -> None:
    """One tick of the live in-area bump for a seed with travel randomization OFF.

    Its own function rather than a branch in `check_area_story_memory`, because almost nothing that function does
    around the bump applies: there is no area memory in this mode, so no `_write_outstanding` to respect and no
    mark our write could poison. Ownership still applies, since `StoryProgressWitness` asks whether the byte it
    sees is one this client wrote, and a silent bump would credit the player for a rung we put them on.

    Never raises and never guesses: an unknown room resolves to no region and the bumper declines."""
    if ctx.block_base is None:
        return
    from .game_data import chest_regions

    current_region = chest_regions.region_for_room(ctx.room_tracker.current)
    story_byte = ram_client.read_story_byte(ctx.block_base)
    bumped = ctx.live_story_bumper.poll(ctx.block_base, current_region, story_byte,
                                        travel_shuffle=False,
                                        scooter_shuffle=ctx.shuffle_scooter_upgrade)
    if bumped is None:
        return
    _claim_story_write(ctx, ctx.live_story_bumper)
    _note(ctx, bumped[1])
    await _send_bump_awards(ctx)
    _save_story_write_log(ctx)


async def check_area_story_memory(ctx: PokemonXDContext) -> None:
    """The per-area story-byte memory poll. Needs travel randomization on: it writes save data, and with the
    option off the player reaches every area by playing, so the byte is already right everywhere.

    Runs inside the block-stability gate with every other block writer."""
    if ctx.block_base is None:
        return
    # Kept current before any early return below: `target_for` caps on this flag, and a stale one is a wrong
    # byte rather than a missing feature.
    ctx.area_story_memory.scooter_held = scooter_upgrade_held(ctx)
    if not ctx.randomize_travel_locations:
        # Two narrow exceptions to "with travel randomization off, leave the bytes to vanilla gameplay", both for
        # SS Libra: the Scooter is an Archipelago item the multiworld times, and the game has no concept of that,
        # so the option off would just leave the player holding an item with nothing to show for it. A bump whose
        # `story_bytes.OptionGate` is TRAVEL_SHUFFLE_ONLY (the HQ Lab's) still never fires here. THE HOLD RUNS
        # FIRST: it can write the byte, and the bump must decide from the value actually in the save.
        _hold_ss_libra_without_the_scooter(ctx)
        await _bump_in_vanilla_travel(ctx)
        return
    # While the Parts override holds the byte there is nothing here worth doing. Two writers, one byte:
    # `check_story_byte_override` runs immediately before this, so when it is active the live byte is 0x6E because
    # WE put it there -- the hover write would write Gateon's floor over it, undoing the unlock eight Parts
    # bought, and `observe()` would bank 0x6E as Gateon's high-water mark in a file built to outlive the client.
    #
    # Stepping aside must not freeze the MAP BOOKKEEPING, cleared below this line: an override that armed
    # mid-map-visit used to pin it for the whole trip, so `left_map_screen` never ran and the next back-out was
    # measured against a room the player left two areas ago. Only that record is released.
    if ctx.story_byte_override.active:
        if ctx.room_tracker.current != ram_client.MAP_SCREEN_ROOM_ID:
            ctx._room_before_map = None
            ctx.area_story_memory.saved_byte = None
            ctx.area_story_memory._write_outstanding = False
        return

    room_id = ctx.room_tracker.current
    story_byte = ram_client.read_story_byte(ctx.block_base)

    # Where the player is standing, for raising that area's high-water mark. A room with no known region raises
    # nothing -- inventing a region would poison the memory with values earned somewhere else.
    from .game_data import chest_regions

    current_region = chest_regions.region_for_room(room_id)

    # Leaving the map screen, before anything records anything. A back-out is detected by the room returning to
    # the one the map was opened from -- travelling lands the player in the DESTINATION's room, and nothing else
    # tells the two apart. This runs ahead of the bump and of the memory's own `observe`, because one poll of a
    # foreign byte reaching `observe` writes another area's floor into this area's PERSISTED high-water mark.
    on_map = room_id == ram_client.MAP_SCREEN_ROOM_ID
    if on_map:
        if ctx._room_before_map is None and ctx.room_tracker.previous is not None:
            ctx._room_before_map = ctx.room_tracker.previous
    elif room_id is not None:
        # Off the map with a readable room. An unreadable one decides nothing -- asking again next poll is free,
        # where a wrong "backed out" rolls back a byte the destination is about to be built from.
        backed_out = ctx._room_before_map is not None and room_id == ctx._room_before_map
        restore_note = ctx.area_story_memory.left_map_screen(ctx.block_base, backed_out=backed_out)
        if restore_note:
            _note(ctx, restore_note)
            story_byte = ram_client.read_story_byte(ctx.block_base)   # re-read: the restore just changed it
        ctx._room_before_map = None

    # The in-area bump and the Snagem battle drop both land BEFORE the area memory observes anything: observing
    # first would bank the bump's pass-through value, or the drop's 0x62, as the area's high-water mark, and the
    # mark cannot be recovered by looking at the game -- a banked 0x62 makes the drop permanent. Each writer
    # hands back the byte it wrote, so the rest of this function works from the new value.
    #
    # The roster is read only inside the hideout with the battle flag up: the scan covers the whole of MEM1, and
    # the signal is relevant in three rooms. A failed read yields no surnames and the hold declines.
    snagem_room = room_id is not None and room_id in ram_client.SNAGEM_ROOM_IDS
    snagem_fighting = False
    snagem_surnames: "set[str] | None" = None
    if snagem_room:
        try:
            snagem_fighting = bool(ram_client.read_battle_ui_flag())
        except Exception:
            snagem_fighting = False
        if snagem_fighting:
            try:
                snagem_surnames = {record.trainer_name.strip().upper()
                                   for record in ram_client.scan_battle_roster()
                                   if record.species_dex is not None and record.trainer_name.strip()}
                for own in own_trainer_names(ctx):   # ADDENDUM 444
                    snagem_surnames.discard(own.upper())
            except Exception:
                snagem_surnames = None
    # The script patch, independent of the byte hold above: that one makes the hideout's GRUNTS fight, this one
    # makes Wakin and Gonzap possible at all. Polled before the hold so a freshly loaded room is patched on the
    # tick it is recognised. Confirmed surnames are handed over so the patch can take itself back out once
    # Gonzap is beaten -- `hero_main` is a loop, and a patched story gate re-runs the encounter forever. These
    # are the PREVIOUS tick's confirmations, since the tracker is polled further down; the patcher latches the
    # surname, so one tick late costs nothing.
    try:
        confirmed_surnames = set(ctx.trainer_defeat_tracker.last_confirmed_surnames)
    except Exception:
        confirmed_surnames = set()
    script_note = ctx.snagem_script_patcher.poll(ctx.block_base, room_id, confirmed_surnames)
    if script_note:
        _note(ctx, script_note)

    snagem_note = ctx.snagem_battle_hold.poll(ctx.block_base, room_id, snagem_fighting, snagem_surnames)
    if snagem_note:
        _claim_story_write(ctx, ctx.snagem_battle_hold)
        _note(ctx, snagem_note)
        story_byte = ram_client.read_story_byte(ctx.block_base)   # re-read: the hold just changed it
        _save_story_write_log(ctx)

    bumped = ctx.live_story_bumper.poll(ctx.block_base, current_region, story_byte,
                                        travel_shuffle=True, scooter_shuffle=ctx.shuffle_scooter_upgrade)
    if bumped is not None:
        # ADDENDUM 476: a bump that says so banks the byte that triggered it -- the GAME's, earned here -- as this
        # area's mark before the bump replaces it, so its paired floor rule binds on later visits.
        _bump = ctx.live_story_bumper.last_bump
        if getattr(_bump, "banks_trigger", False) and ctx.live_story_bumper.last_trigger_byte is not None:
            _mark = ctx.area_story_memory.highest_by_region.get(current_region, -1)
            if ctx.live_story_bumper.last_trigger_byte > _mark:
                ctx.area_story_memory.highest_by_region[current_region] = ctx.live_story_bumper.last_trigger_byte
                ctx.area_story_memory.visited.add(current_region)
                ctx.area_story_memory.dirty = True
        story_byte, bump_note = bumped
        # The bump is a CLIENT WRITE and must not become the area's mark: 0x0D -> 0x0F fires on arrival, so
        # without this the lab "reached" the Snag Machine tier because WE put it there, and
        # `AreaFloorRule("Pokemon HQ Lab", 0x17, ...)` opened on a value the player had not earned.
        _claim_story_write(ctx, ctx.live_story_bumper)
        ctx.area_story_memory.last_written_region = current_region
        _note(ctx, bump_note)
        await _send_bump_awards(ctx)

    # What they are hovering on the map -- the pre-load hook: the write has to land while they are still
    # choosing, because once the room loads it was built from the old byte.
    hovered_region = None
    if room_id == ram_client.MAP_SCREEN_ROOM_ID:
        try:
            # `resolve()` is cached and only rescans MEM1 when its address stops answering, and it is called
            # ONLY on the map screen, so the expensive path costs one scan per map open, not one per tick.
            hovered_region = ram_client.map_destination_region(ctx.map_cursor_tracker.resolve())
        except Exception:
            hovered_region = None

    # The poisoned-byte guard runs BEFORE anything records or writes: `area_story_memory.poll` opens with
    # `observe()`, so a foreign byte reaching that call can be banked into the persisted per-area file and
    # re-applied on every later entry. Clamping first means `observe()` next sees the value this area earned.
    #
    # `busy` is the ownership channel, not a guess: every other story-byte writer announces itself through
    # `story_byte_override.active` or the map-visit lock, and this guard stands down for both. The Gateon ceiling
    # deliberately parks the byte where no area's window contains it, and clamping that would fight it every tick.
    clamp_note = ctx.area_story_memory.clamp_poisoned_byte(
        ctx.block_base, current_region, story_byte,
        busy=ctx.story_byte_override.active,
    )
    if clamp_note:
        # Loud rather than throttled: it only fires when something put a byte somewhere it cannot belong.
        _note_warn(ctx, clamp_note)
        story_byte = ram_client.read_story_byte(ctx.block_base)   # re-read: the clamp just changed it
        _save_story_write_log(ctx)

    # ADDENDUM 400: disarm BEFORE the poll, so the first tick in a new area already has its floor back.
    # `current_region` is where the player actually is, which is exactly what the latch asks about.
    left = ctx.whiteout_latch.note_region(current_region)
    if left:
        _note(ctx, left)

    note = ctx.area_story_memory.poll(ctx.block_base, hovered_region, current_region, story_byte)
    if note:
        _note(ctx, note)
    _save_area_memory(ctx)
    _save_story_write_log(ctx)


def _claim_story_write(ctx: PokemonXDContext, writer) -> None:
    """Copy a writer's own `last_written_value` into the ONE ownership channel both readers consult.

    `AreaStoryByteMemory.last_written_target` is what `observe()` and `StoryProgressWitness` both test against.
    Every story-byte writer reports through this one field rather than each reader knowing a list of writers:
    two readers with independent notions of "did we write this" is how they come to disagree. Never raises -- an
    ownership record is a defence, and a defence that can break the poll loop is worse than the hole it closes."""
    try:
        value = getattr(writer, "last_written_value", None)
        if value is None:
            return
        ctx.area_story_memory.last_written_target = value
        writer.last_written_value = None
    except Exception:
        pass


async def check_scooter_hold(ctx: PokemonXDContext) -> None:
    """See `ram_client.ScooterStoryHold` for the design and for why 0x57 is a hold rather than a rollback. Runs
    in both travel modes and everywhere in the game, which nothing else that writes this byte does -- the leak
    it closes is a story warp, so watching any single room would be watching the wrong one."""
    if ctx.block_base is None or not ctx.shuffle_scooter_upgrade:
        return
    ctx.scooter_hold.scooter_held = scooter_upgrade_held(ctx)
    note = ctx.scooter_hold.poll(ctx.block_base, ram_client.read_story_byte(ctx.block_base))
    _claim_story_write(ctx, ctx.scooter_hold)   # the hold AND the grant
    if note:
        _note(ctx, note)
        _save_story_write_log(ctx)


MUSIC_DISC_ITEM_NAME = "Music Disc"


def music_disc_held(ctx: PokemonXDContext) -> bool:
    """True when the multiworld has sent the Music Disc. Only consulted with key items shuffled."""
    return any(ITEM_ID_TO_NAME.get(network_item.item) == MUSIC_DISC_ITEM_NAME
               for network_item in ctx.items_received)


def music_disc_chest_checked(ctx: PokemonXDContext) -> bool:
    """True when chest 80 -- the game's Music Disc pickup -- has already been checked on the server."""
    name = ram_client.CHEST_ID_TO_LOCATION.get(ram_client.MUSIC_DISC_CHEST_ID)
    location_id = LOCATION_NAME_TO_ID.get(name) if name else None
    if location_id is None:
        return False
    return location_id in ctx.checked_locations   # the server's set; nothing here writes `locations_checked`


def own_trainer_names(ctx) -> "set[str]":
    """ADDENDUM 444. The name the player's own party records carry on the battle roster: the in-game trainer name
    read from the save, or -- only until that is known -- the slot name, which older setups made the same."""
    name = getattr(ctx, "trainer_name", None) or ctx.auth
    return {name.strip()} if isinstance(name, str) and name.strip() else set()


def item_received(ctx: PokemonXDContext, item_name: str) -> bool:
    """True when the multiworld has sent `item_name` to this slot."""
    return any(ITEM_ID_TO_NAME.get(network_item.item) == item_name for network_item in ctx.items_received)


def _poll_item_story_hold(ctx: PokemonXDContext, hold, item_name: str, already_happened: bool = False) -> None:
    """ADDENDA 419/421, shared by every `ram_client.ItemStoryHold`. The held value is persisted the moment it
    changes, so a client restart between the hold and the item cannot strand the step that was pulled back."""
    if ctx.block_base is None or not hold.enabled:
        return
    hold.item_held = item_received(ctx, item_name)
    before = (hold.declined_value, getattr(hold, "lowered", None))   # ADDENDUM 441: the room flag persists too
    note = hold.poll(ctx.block_base, ram_client.read_story_byte(ctx.block_base),
                     ctx.room_tracker.current, already_happened)
    _claim_story_write(ctx, hold)
    if (hold.declined_value, getattr(hold, "lowered", None)) != before:
        ctx._save_local_state()
    if note:
        _note(ctx, note)
        _save_story_write_log(ctx)


async def check_music_disc_hold(ctx: PokemonXDContext) -> None:
    """ADDENDUM 419. See `ram_client.MusicDiscStoryHold`: in Phenac, without the Music Disc, the story byte is
    capped at 0x41 (before the pickup), and the held step is given back when the disc arrives."""
    _poll_item_story_hold(ctx, ctx.music_disc_hold, MUSIC_DISC_ITEM_NAME,
                          music_disc_chest_checked(ctx) if ctx.music_disc_hold.enabled else False)


async def check_machine_part_hold(ctx: PokemonXDContext) -> None:
    """ADDENDUM 421. See `ram_client.MachinePartStoryHold`: with location shuffle off, the early areas are capped
    at 0x15 (before the Gateon parts shop) until the Machine Part arrives."""
    _poll_item_story_hold(ctx, ctx.machine_part_hold, "Machine Part")


PERR_MACHINE_PART_STORY_BYTE = 0x16


async def check_perr_machine_part(ctx: PokemonXDContext) -> None:
    """Perr's Machine Part: Gateon's story reaching 0x16, the byte the parts-shop scene sets. With vanilla travel the
    story byte is Gateon's, so a story already past it counts too. With location shuffle only Gateon's own value does."""
    if ctx.block_base is None:
        return
    location_id = LOCATION_NAME_TO_ID.get(PERR_MACHINE_PART_LOCATION_NAME)
    if location_id is None or location_id in ctx.checked_locations:
        return
    try:
        story = ram_client.read_story_byte(ctx.block_base)
    except Exception:
        return
    high = getattr(ctx.story_progress, "high_water", None)
    # Two more witnesses of the scene having played: the Machine Part hold pulled the story back from it (its
    # remembered value is persisted), or Gateon's own remembered mark reached it.
    declined = getattr(getattr(ctx, "machine_part_hold", None), "declined_value", None)
    gateon = None
    try:
        from .game_data import story_bytes as _sb
        gateon = _sb.highest_in_area("Gateon Port", ctx.area_story_memory.highest_by_region)
    except Exception:
        pass
    # With location shuffle the live byte is not Gateon's: hovering a destination on the map writes that area's value
    # there. Only Gateon's own remembered value counts then -- recorded while the player is in Gateon, or raised when
    # the client sets Gateon's floor -- never the live byte or its high-water mark.
    witnesses = (gateon,) if ctx.randomize_travel_locations else (story, high, declined, gateon)
    seen = [v for v in witnesses if v is not None]
    if seen and max(seen) >= PERR_MACHINE_PART_STORY_BYTE:
        await _send_checks(ctx, [PERR_MACHINE_PART_LOCATION_NAME])


def machine_part_obtained(ctx: PokemonXDContext) -> bool:
    """ADDENDUM 452. With key items shuffled, the Machine Part item received; otherwise the game's own parts-shop
    event, 0x16, reached in Gateon (per-area memory) or by the story itself (the witness's high-water mark)."""
    if ctx.key_item_shuffle:
        return item_received(ctx, "Machine Part")
    from .game_data import story_bytes
    gateon = story_bytes.highest_in_area("Gateon Port", ctx.area_story_memory.highest_by_region)
    high = getattr(ctx.story_progress, "high_water", -1)
    return max(gateon if gateon is not None else -1, high if high is not None else -1) >= ram_client.LAB_MEMO_HOLD_BYTE


def lab_memos_received(ctx: PokemonXDContext, numbers: "tuple[int, ...] | None" = None) -> bool:
    """ADDENDUM 452. Krane Memos 3, 4 and 5 (or `numbers`) handed over: each one's check sent (the server's record) or
    taken out of the Bag this session (`KraneMemoTracker.awarded`)."""
    awarded = ctx.krane_memo_tracker.awarded or set()
    for number in (ram_client.LAB_MEMO_HOLD_MEMOS if numbers is None else numbers):
        if number in awarded:
            continue
        location_id = LOCATION_NAME_TO_ID.get(ram_client.krane_memo_location_name(number))
        if location_id is None or location_id not in ctx.checked_locations:
            return False
    return True


def animations_disabled(ctx: PokemonXDContext) -> bool:
    """Move animations off: `/animations`' choice for this slot, else the seed's Disable Move Animations."""
    override = getattr(ctx, "animations_override", None)
    if override is not None:
        return not override
    return bool(getattr(ctx, "disable_move_animations", False))


def cipher_lab_cleared(ctx: PokemonXDContext) -> bool:
    """The Cipher Lab has reached 0x2B: its own remembered mark with travel shuffle on, the story's high-water mark
    with it off."""
    from .game_data import story_bytes as _sb

    mark = _sb.highest_in_area("Cipher Lab", ctx.area_story_memory.highest_by_region)
    if not ctx.randomize_travel_locations:
        high = getattr(ctx.story_progress, "high_water", None)
        if high is not None:
            mark = max(mark if mark is not None else -1, high)
    return mark is not None and mark >= ram_client.LAB_MEMO_RELEASE_CIPHER_LAB


def _lab_hold_inputs_ready(ctx: PokemonXDContext) -> bool:
    """ADDENDUM 458: connected, and the server's full item list (ReceivedItems from index 0) has arrived since, so
    `items_received` and `checked_locations` are the server's and not a not-yet-synced empty set."""
    if getattr(ctx, "slot", None) is None:
        return False
    if getattr(ctx, "_items_synced", False):
        return True
    # The server sends no ReceivedItems at all for a slot with nothing received yet, so a few seconds after
    # Connected an empty list IS the real one.
    due = getattr(ctx, "_items_sync_deadline", None)
    return due is not None and time.monotonic() >= due


async def check_lab_memo_hold(ctx: PokemonXDContext) -> None:
    """ADDENDUM 452. Once the Machine Part is obtained, the HQ Lab is held at or below 0x16 until
    Krane Memos 3, 4 and 5 have been received. Runs LAST of the story-byte writers, so in an HQ Lab room nothing
    else's write can stand; the lab's map-hover target is capped at 0x16 as well. Neither ever raises the lab. See `ram_client.LabMemoStoryHold`."""
    hold = ctx.lab_memo_hold
    # ADDENDUM 458: the hold was found broken -- the lab read 0x19 with Memos 3-5 never handed over. The arming used to
    # be recomputed from scratch every tick, so any tick where `machine_part_obtained` read False (right after a
    # (re)connect, before the server has re-sent the received items) RELEASED the hold, and the release gave back the
    # byte it had pulled back from -- 0x19, persisted from an earlier session. Now: (1) nothing happens before the
    # server has synced this slot; (2) once the hold has pulled the lab back (a persisted `declined_value`) it stays
    # armed until the memos really come; (3) the give-back only ever runs on that handover.
    if not _lab_hold_inputs_ready(ctx):
        return
    memos = lab_memos_received(ctx)
    if not memos and cipher_lab_cleared(ctx):
        # Past the Cipher Lab the handover has had its chance: the three memos are sent, and the hold lets go.
        names = [ram_client.krane_memo_location_name(n) for n in ram_client.LAB_MEMO_HOLD_MEMOS]
        await _send_checks(ctx, names)
        ctx.krane_memo_tracker.awarded = set(ctx.krane_memo_tracker.awarded or ()) | set(ram_client.LAB_MEMO_HOLD_MEMOS)
        memos = True
    # ADDENDUM 464: clamp to 0x16 ONLY when the HQ Lab story byte has reached 0x0F at all and Memos 1 and 2 have both
    # been received. The lab's 0x0F is latched;
    # memos 1-2 are the server's record. Without both nothing below arms, whatever the Machine Part says.
    if ctx.block_base is not None and not hold.lab_reached:
        try:
            from .game_data import story_bytes as _sb

            lab_mark = _sb.highest_in_area(ram_client.LAB_MEMO_HOLD_AREA, ctx.area_story_memory.highest_by_region)
            if not ctx.randomize_travel_locations:
                # One story byte for the whole game: its high-water mark is the lab's.
                high = getattr(ctx.story_progress, "high_water", None)
                if high is not None:
                    lab_mark = max(lab_mark if lab_mark is not None else -1, high)
            if hold.note_lab_progress(ctx.room_tracker.current, ram_client.read_story_byte(ctx.block_base), lab_mark):
                ctx._save_local_state()
        except Exception:
            pass
    first_memos = lab_memos_received(ctx, ram_client.LAB_MEMO_ARM_MEMOS)
    armed = ctx.block_base is not None and not memos and hold.lab_reached and first_memos and (
        machine_part_obtained(ctx) or hold.declined_value is not None or hold.latched)
    was_latched = hold.latched
    if armed:
        hold.latched = True
    elif memos:
        hold.latched = False
    if hold.latched != was_latched:
        ctx._save_local_state()
    hold.armed = armed
    forced = ctx.area_story_memory.held_ceiling_by_region
    if armed:
        forced[ram_client.LAB_MEMO_HOLD_AREA] = ram_client.LAB_MEMO_HOLD_BYTE
    else:
        forced.pop(ram_client.LAB_MEMO_HOLD_AREA, None)
    if ctx.block_base is None:
        return
    before = hold.declined_value
    note = hold.poll(ctx.block_base, ram_client.read_story_byte(ctx.block_base), ctx.room_tracker.current,
                     memos_received=memos)
    _claim_story_write(ctx, hold)
    if hold.declined_value != before:
        ctx._save_local_state()
    if note:
        _note(ctx, note)   # ADDENDUM 445: quiet by default; `/keyitems` shows the hold's state
        _save_story_write_log(ctx)


async def check_story_byte_override(ctx: PokemonXDContext) -> None:
    """Writes Gateon's story byte once enough Robo Kyogre Parts are held, and restores it on leaving.

    That write IS the Citadark unlock, so there is no second toggle: one option gates the Parts in logic and arms
    this, which keeps logic and the game agreeing. Off unless that option is on, since it writes save data; runs
    inside the block-stability gate, and reuses the room RoomTracker already resolved this tick.

    See `ram_client.StoryByteOverride` for the save/restore rule, including why a restore declines when real
    progress has moved the byte past the remembered value."""
    if ctx.block_base is None or not ctx.robo_kyogre_parts_unlock_citadark:
        return
    # The Parts override writes in BOTH travel modes -- the narrow exception to "with travel randomization off,
    # leave the bytes to vanilla gameplay", because the Parts are Archipelago items in either mode and the game
    # has no way to know the player holds eight of them. Everything else stays gated as before.
    #
    # Undoing a ceiling a previous session died holding runs FIRST, for the same reason `left_map_screen` runs
    # before `poll`: the recovery is about the value in the save right now, and every line below is entitled to
    # change it. Recovering late would mean recovering from our own fresh write.
    if ctx._gateon_ceiling_recovery_pending:
        ctx._gateon_ceiling_recovery_pending = False
        try:
            recovery_note = ctx.story_byte_override.recover(ctx.block_base)
            _claim_story_write(ctx, ctx.story_byte_override)
        except Exception:
            recovery_note = None
        if recovery_note:
            _note(ctx, recovery_note)
        ctx._save_local_state()

    required = ctx.robo_kyogre_parts_required
    armed = required > 0 and robo_kyogre_parts_held(ctx) >= required
    ctx.story_byte_override.armed = armed

    # The HOVER is the real hook -- see StoryByteOverride.poll_hover for why arrival is one visit too late.
    # Resolved here rather than reused from check_area_story_memory, which is travel-randomization-only while
    # this is not; the cursor read is cached and only runs on the map screen.
    room_id = ctx.room_tracker.current
    # Not gated on `armed` or `active`. The hover also RESTORES when the cursor moves off Gateon while we hold
    # the byte, which has to keep working after the Parts condition stops being true; and without the Parts
    # there is a CEILING to apply, which has to land on the hover because Gateon is built from the byte as it
    # stands when the room loads. `poll_hover` and `_apply` decide whether anything is needed, so asking on
    # every map-screen tick costs one cached cursor read.
    if room_id == ram_client.MAP_SCREEN_ROOM_ID:
        try:
            hovered = ram_client.map_destination_region(ctx.map_cursor_tracker.resolve())
        except Exception:
            hovered = None
        hover_note = ctx.story_byte_override.poll_hover(ctx.block_base, hovered)
        _claim_story_write(ctx, ctx.story_byte_override)
        if hover_note:
            _note(ctx, hover_note)

    note = ctx.story_byte_override.poll(ctx.block_base, room_id)
    _claim_story_write(ctx, ctx.story_byte_override)
    if note:
        _note(ctx, note)
    _save_story_write_log(ctx)
    # The held value has to reach disk on the tick the clamp lands, not at a later checkpoint -- the case this
    # covers is the client dying without warning. Written only when it CHANGED, so an idle Gateon visit is not
    # a file write per tick.
    persisted = (ctx.story_byte_override.saved_byte, ctx.story_byte_override.pre_ride_byte,
                 ctx.story_byte_override.citadark_mark)
    if persisted != ctx._gateon_ceiling_last_persisted:
        ctx._gateon_ceiling_last_persisted = persisted
        ctx._save_local_state()


def managed_key_item_ids(ctx: PokemonXDContext) -> "frozenset[int]":
    """The game item ids the reconciler owns. Empty unless key-item shuffle is on, which is what keeps this whole
    feature inert for a seed where the player is supposed to hold whatever the story gives them.

    game_data/key_items.POLLED_GAME_ITEM_IDS is already exactly this set -- shuffled AND in the pool -- so the
    Elevator Key and Gonzap's Key are excluded by the data rather than by a condition here."""
    if not ctx.key_item_shuffle:
        return frozenset()
    from .game_data import key_items

    return key_items.POLLED_GAME_ITEM_IDS


def should_have_key_item_ids(ctx: PokemonXDContext) -> "frozenset[int]":
    """The managed ids Archipelago says this player owns, derived from the received-items list every poll.

    Derived rather than accumulated: an incrementally-maintained set is a second copy of the truth that can
    drift, while the received list is already authoritative, replayed in full on reconnect, and cheap to walk.
    Recomputing it each tick is what makes the reconciler stateless. A PACKAGED item contributes every id it
    delivers, and the two retired singles are still honoured so an older seed reconciles correctly."""
    managed = managed_key_item_ids(ctx)
    if not managed:
        return frozenset()
    owned: "set[int]" = set()
    for network_item in ctx.items_received:
        item_name = ITEM_ID_TO_NAME.get(network_item.item)
        if item_name is None:
            continue
        data = ITEM_TABLE.get(item_name)
        if data is None:
            continue
        for candidate in (data.game_item_id, *data.companion_game_item_ids):
            if candidate in managed:
                owned.add(candidate)
    return frozenset(owned)


def key_item_sources(ctx: PokemonXDContext) -> "list[str]":
    """ADDENDUM 420: for every managed key item Archipelago says you own, where it came from.

    "Not removed" has two answers that look identical in the Bag -- the clear did not happen, or the item really
    arrived (the Machine Part is an early item, so it usually has). This says which. Never raises."""
    lines: "list[str]" = []
    managed = managed_key_item_ids(ctx)
    if not managed:
        return lines
    for network_item in ctx.items_received:
        try:
            item_name = ITEM_ID_TO_NAME.get(network_item.item)
            data = ITEM_TABLE.get(item_name) if item_name else None
            if data is None or not any(i in managed for i in (data.game_item_id, *data.companion_game_item_ids)):
                continue
            sender = network_item.player
            who = "your own world" if sender == ctx.slot else f"{ctx.player_names.get(sender, f'player {sender}')}'s world"
            try:
                where = ctx.location_names.lookup_in_slot(network_item.location, sender)
            except Exception:
                where = f"location {network_item.location}"
            lines.append(f"  {item_name}: received from {who} ({where}).")
        except Exception:
            continue
    return lines


async def reconcile_key_items(ctx: PokemonXDContext) -> None:
    """Makes the Bag's gating key items match what Archipelago says the player owns, every poll, instead of
    relying on the item-delivery path.

    Runs INSIDE the block-stability gate, unlike give_items(), and that is not a contradiction of "never block
    sending items": this function has no queue and no state, so a tick it sits out costs nothing -- the next does
    the same work. Reading a half-rewritten block is actively harmful here, since a stale zero writes a duplicate
    and a stale non-zero clears an item the player legitimately owns.

    See ram_client.KeyItemReconciler for the one visible consequence -- a key item the player USES is written
    back within a poll."""
    if ctx.block_base is None:
        return
    managed = managed_key_item_ids(ctx)
    if not managed:
        return
    written, cleared = ctx.key_item_reconciler.poll(
        ctx.block_base, should_have_key_item_ids(ctx), managed
    )
    from .game_data import key_items

    def label(item_id: int) -> str:
        key_item = key_items.KEY_ITEM_BY_GAME_ID.get(item_id)
        return key_item.name if key_item is not None else f"item {item_id}"

    # The FIRST time an id is written or cleared is news; every one after is narration. The reconciler's own
    # counters make "first" cheap to know: a 1 means this is the event.
    for item_id in written:
        _announce_first(
            ctx, ctx.key_item_reconciler.writes.get(item_id, 0) == 1,
            f"Key item restored to your Bag: {label(item_id)} (Archipelago says you own it).",
        )
    for item_id in cleared:
        _announce_first(
            ctx, ctx.key_item_reconciler.clears.get(item_id, 0) == 1,
            f"Key item removed from your Bag: {label(item_id)} -- this seed shuffles it, and Archipelago "
            f"has not sent it to you.",
        )


def apply_start_with_poke_spots(ctx: PokemonXDContext) -> None:
    """Start With Miror Radar and Poke Spots: keep a Miror Radar in the Key Items pocket, and with Location Shuffle
    off hold the three Poke Spots open on the map (with it on, the unlock is starting inventory and arrives like any
    other). Idempotent; runs inside the block-stability gate. Never raises."""
    if not ctx.start_with_poke_spots or ctx.block_base is None:
        return
    try:
        if ram_client.keep_key_item(ctx.block_base, ram_client.MIROR_RADAR_ITEM_ID):
            _note(ctx, "Miror Radar put in your Key Items (Start With Miror Radar and Poke Spots).")
    except Exception:
        pass
    if ctx.randomize_travel_locations:
        return
    try:
        record_base = ctx.block_base + travel_locations.TRAVEL_RECORD_OFFSET_FROM_BLOCK_BASE
        travel_locations.write_travel_location_bit(record_base, "Poke Spots")
    except Exception:
        pass


async def check_krane_memos(ctx: PokemonXDContext) -> None:
    """ADDENDUM 434: each "Story - Krane Memo N" check is sent when the game puts that memo in the Bag and this
    client takes it back out -- not off the story byte. Both travel modes; the memos are out
    of the item pool, so every copy in the Bag is the story's. See `ram_client.KraneMemoTracker`."""
    if ctx.block_base is None:
        return
    newly_awarded = ctx.krane_memo_tracker.poll(ctx.block_base)
    if newly_awarded:
        await _send_checks(ctx, newly_awarded)
        _note(ctx, "Took " + ", ".join(name.replace("Story - ", "") for name in newly_awarded)
                   + " out of your Bag -- sent the check(s).")


async def _send_bump_awards(ctx: PokemonXDContext) -> None:
    """Send the checks a live bump declares it skipped past (`LiveStoryByteBump.awards_locations`). ADDENDUM 434
    took the two Krane Memos off the HQ Lab bump -- they are sent when the memo is taken out of the Bag now -- so
    no bump in the table awards anything today; the plumbing stays for one that does."""
    names = ctx.live_story_bumper.last_awarded_locations
    if not names:
        return
    newly = [name for name in names
             if name in LOCATION_NAME_TO_ID and LOCATION_NAME_TO_ID[name] not in ctx.checked_locations]
    if newly:
        await _send_checks(ctx, newly)
        _note(ctx, "Sent " + ", ".join(newly) + " -- the bump skipped the tier they are earned at.")


async def check_chests(ctx: PokemonXDContext) -> None:
    """The berry IS the chest. Each chest holds its own berry, assigned so no two chests in a room share one
    (game_data/chest_berries.py asserts that at import): the berry says a chest opened, the berry plus the room
    says which one, and no flag bit is read. Every earlier attempt read identity out of the chest-flag bitfield,
    a global array carrying story flags on chest positions with non-monotonic cluster offsets, so a model fitted
    in one cluster never survived the other four.

    The room is never a veto: if it cannot be read the pickup is HELD and resolved a poll or two later, since the
    player is standing in the room when they open a chest. Deferred, never dropped. No-ops when randomize_chests
    is off -- an unpatched chest is not an AP location and holds no reserved berry."""
    if ctx.block_base is None or not ctx.randomize_chests:
        return
    try:
        room_id = ram_client.read_room_id()
    except Exception:  # noqa: BLE001 -- a failed read must not take the poll loop down
        room_id = None
    if room_id is None:
        room_id = ctx.room_tracker.current

    already = frozenset(
        name for name in ram_client.CHEST_LOCATION_NAMES
        if name in LOCATION_NAME_TO_ID and LOCATION_NAME_TO_ID[name] in ctx.checked_locations
    )
    names = ctx.chest_berry_tracker.poll(ctx.block_base, room_id=room_id, already_checked=already)
    if names:
        await _send_checks(ctx, names)

    # A pickup no room the player was in can explain is HELD and reported, never dropped silently. Printed here
    # because this is the only place with a logger that runs every chest poll.
    if ctx.chest_berry_tracker.unplaceable_notices:
        for line in ctx.chest_berry_tracker.unplaceable_notices:
            logger.warning(line)
        ctx.chest_berry_tracker.unplaceable_notices.clear()

    # The guard and its counter stay; only the per-occurrence warning is gone. Drained rather than left to grow,
    # since an unread list appended to on every disagreement leaks. `/chests` still reports the count.
    if ctx.chest_berry_tracker.flag_room_disagreements:
        ctx.chest_berry_tracker.flag_room_disagreements.clear()

    tracker = ctx.chest_berry_tracker
    if tracker.baseline_carried and not tracker.backfill_announced:
        tracker.backfill_announced = True
        # Credit the DEDUCIBLE ones before announcing the rest: a carried berry with exactly one unchecked
        # candidate chest needs no guessing. This path loses a check outright rather than merely late -- a chest
        # opened before the client connected was swallowed as a baseline and could never fire.
        deduced = tracker.unambiguous_backfill(already)
        if deduced:
            logger.info(f"Sending {len(deduced)} chest check(s) opened before the client connected.")
            await _send_checks(ctx, deduced)
            already = already | frozenset(deduced)
        for line in tracker.backfill_notice(already):
            logger.warning(line)


def _game_item_label(item_id: int) -> str:
    """`id 19 (Full Restore)` when this world knows the id, else `id 19`."""
    for name, data in ITEM_TABLE.items():
        if data.game_item_id == item_id:
            return f"id {item_id} ({name})"
    return f"id {item_id}"


def check_misfiled_items(ctx: PokemonXDContext) -> None:
    """ADDENDUM 408: say, once per slot, when a Bag tab holds an item that is not that tab's kind -- with the raw
    id, so a report can be traced. Read-only: it names the item and moves nothing."""
    if ctx.block_base is None:
        return
    now = time.monotonic()
    if now - getattr(ctx, "_last_misfile_scan", 0.0) < 10.0:
        return
    ctx._last_misfile_scan = now
    try:
        found = ram_client.find_misfiled_items(ctx.block_base)
    except Exception:
        return
    seen = getattr(ctx, "_misfiles_reported", set())
    for tab, slot, item_id, quantity in found:
        key = (tab, slot, item_id)
        if key in seen:
            continue
        seen.add(key)
        _note_warn(ctx, f"Bag: {_game_item_label(item_id)} x{quantity} is in the {tab} tab (slot {slot}), which "
                        f"is the wrong tab for it. Please report this line and the output of `/bag`.")
    ctx._misfiles_reported = seen


async def check_shops(ctx: PokemonXDContext) -> None:
    """Shop purchases, credited per SHOP by room id. The dummy berry is the signal -- it is what the ISO patch
    writes into every mart slot -- but not the identity: when its quantity goes up, the room says WHICH shop, so
    the check is "Gateon Port Shop AP Item 3" rather than "Buy Shop Item - Wepear Berry #3".

    A berry that goes up in a room that is NOT a shop credits nothing: a dummy berry can arrive from a gift or a
    field pickup, and crediting a guess sends a check for a purchase that never happened. The tracker counts
    those separately so `/shops` can say so. No-ops when randomize_shops is off -- except for the Candy Box's
    description at Gateon when Reduce Citadark Grind is on (ADDENDUM 437)."""
    if ctx.block_base is None:
        return
    if not ctx.randomize_shops:
        # ADDENDUM 437: vanilla shops, but the Gorigan-tier shelf still sells the Candy Box. Its description is the
        # only thing written -- no berry lines (`berry_ids=[]`), so every vanilla description stays as it is.
        if ctx.reduce_citadark_grind or ctx.ability_patch:   # ADDENDUM 453: the Ability Swap's text too
            try:
                room_id = ram_client.read_room_id()
            except Exception:
                room_id = None
            if room_id is None:
                room_id = ctx.room_tracker.current
            try:
                ctx.item_description_writer.poll(room_id, {}, set(), berry_ids=[])
            except Exception:
                logger.debug("Pokemon XD: Candy Box description pass failed", exc_info=True)
        return
    # READ FRESH rather than reusing ctx.room_tracker.current: the tracker's value is maintained later in the
    # same poll loop inside a `try/except pass`, so a persistent exception there would leave `.current` at None
    # forever and silently stop every shop check. The tracker's value is the fallback, not the source.
    try:
        room_id = ram_client.read_room_id()
    except Exception:
        room_id = None
    if room_id is None:
        room_id = ctx.room_tracker.current
    newly_crossed = ctx.shop_tracker.poll(ctx.block_base, room_id)
    if newly_crossed:
        await _send_checks(ctx, newly_crossed)

    # ADDENDUM 394: a shop berry bought in a room this client does not list as a shop credits NOTHING, and used
    # to do so in silence. One warning per room, because the room number is the whole report.
    try:
        for _unknown_room, _unknown_count in sorted(ctx.shop_tracker.unknown_shop_rooms.items()):
            if _unknown_room in ctx._warned_unknown_shop_rooms:
                continue
            ctx._warned_unknown_shop_rooms.add(_unknown_room)
            _note_warn(ctx, (
                f"an AP shop item was bought in room {_unknown_room}, which this client does not list as a "
                f"shop, so that purchase credited NO check ({_unknown_count} so far). If that room is a shop "
                "counter, please report the number -- eight checks were lost this way at the Outskirt Stand."
            ))
    except Exception:
        logger.debug("Pokemon XD: unknown-shop-room notice failed", exc_info=True)

    # AFTER the credit above, so a purchase made this poll is reflected and the shelf advances from "GATEON #3"
    # to "GATEON #4" while the player is still at it. Wrapped: a cosmetic rename must not come between a
    # purchase and its check.
    try:
        renamer = ctx.item_name_renamer
        renamer.slots_credited_by_room = ctx.shop_tracker.slots_credited
        # Which shelf lines have already been bought here, so they can grey out to NO CHECK.
        # ADDENDUM 389: the derived set, so NO CHECK survives a reboot here as well as in the descriptions.
        renamer.purchased_by_room = dict(ctx.shop_tracker.purchased_by_room)
        if room_id is not None:
            renamer.purchased_by_room[room_id] = bought_berries_in_room(ctx, room_id)
        if not renamer.verified and renamer.enabled:
            if renamer.verify(ram_client.USELESS_BERRY_IDS):
                logger.debug("Pokemon XD: live item renaming is on")
            else:
                # Not a connection log, a check or a real failure, so `/verbose` decides whether the player
                # sees it. Nothing is broken when this fires -- one cosmetic feature is off.
                _note_warn(ctx, (
                    "live item renaming is off for this session (%s) -- the shop berries keep their vanilla "
                    "names. Nothing else is affected."
                ) % (renamer.verify_failures[0] if renamer.verify_failures else "verification failed"))
        if newly_crossed:
            renamer.refresh(room_id)
        else:
            renamer.poll(room_id)
    except Exception:
        logger.debug("Pokemon XD: live item rename pass failed", exc_info=True)

    # A purchase makes a line NO CHECK, so its price must stop advertising the item it no longer sends. Only the
    # credit case is here; the ordinary pass is `check_shop_prices()`, far earlier in the tick.
    if newly_crossed:
        try:
            ctx.item_price_writer.refresh(room_id, ctx.shop_line_classifications)
        except Exception:
            logger.debug("Pokemon XD: live shop price refresh failed", exc_info=True)

    # The description half, after the rename for the same reason the rename follows the credit: a line bought
    # this poll should already read "Already bought." Wrapped separately so a description failure cannot take the
    # cheaper, always-resident rename down with it. Unlike the rename, this writes WHILE THE MENU IS OPEN -- the
    # description table is not resident before it and reloads from disc each time it opens.
    try:
        writer = ctx.item_description_writer
        writer.poll(
            room_id,
            ctx.scouted_shop_items,
            bought_berries_in_room(ctx, room_id),
        )
    except Exception:
        logger.debug("Pokemon XD: live item description pass failed", exc_info=True)


def bought_berries_in_room(ctx: PokemonXDContext, room_id: "int | None") -> "set[int]":
    """Which of this shop's berries name a line that has ALREADY BEEN CHECKED, so the shelf can read NO CHECK.

    ADDENDUM 389: DERIVED from the server's checked locations, not accumulated locally. `shop_tracker.
    purchased_by_room` is documented as "berry ids already bought there this session" and is not persisted, so
    a reboot lost every NO CHECK marker and the shelf went back to advertising items it could no longer send.
    The checked-location set is already authoritative, already replayed in full on reconnect, and survives a
    reboot for free -- the same argument `should_have_key_item_ids` makes for the key-item reconciler.

    Unioned with the session tracker rather than replacing it: a purchase credited THIS tick has not reached
    `checked_locations` yet, and the shelf is supposed to advance while the player is still standing at it."""
    from .game_data import shops

    live = ctx.shop_tracker.purchased_by_room.get(room_id, set()) if room_id is not None else set()
    if room_id is None:
        return set(live)
    shop = shops.shop_for_room(room_id)
    if shop is None:
        return set(live)
    out = set(live)
    for slot in range(1, shop.slot_count + 1):
        if slot > len(ram_client.USELESS_BERRY_IDS):
            break
        location_id = LOCATION_NAME_TO_ID.get(shops.shop_location_name(shop.name, slot))
        if location_id is not None and location_id in ctx.checked_locations:
            out.add(ram_client.USELESS_BERRY_IDS[slot - 1])
    return out


async def check_shop_prices(ctx: PokemonXDContext) -> None:
    """Keep every shop berry priced by what its line currently sends. Cosmetic, so wrapped, so it can never cost
    a check.

    Separate from `check_shops` so it can run as early in the tick as possible: the Items table lives in
    `common_rel`, resident at a fixed base from boot, so it needs no `block_base`, no block-stability gate and no
    `_looks_ingame()`. Early is not sufficient on its own, since a price derives from the scout reply, which
    arrives asynchronously after `Connected`, so `ItemPriceWriter.poll` also re-prices when the SCOUT changes.

    It has to stay per-room: price is keyed by item id, and a berry id is a shop line NUMBER shared by every
    shop, so in a real seed 13 of 18 line numbers hold different item classes in different shops. Writing on room
    ENTRY keeps a price from changing under a player already at a counter."""
    if not ctx.randomize_shops:
        return
    # Fall back on a None RETURN, not only on an exception: `read_room_id` answers None rather than guessing when
    # its four replicated copies disagree, and does not raise, so an exception-only fallback lets the None reach
    # a writer that reads it as "not in a shop, restore vanilla prices".
    try:
        room_id = ram_client.read_room_id()
    except Exception:
        room_id = None
    if room_id is None:
        room_id = ctx.room_tracker.current
    try:
        ctx.item_price_writer.poll(room_id, ctx.shop_line_classifications)
    except Exception:
        logger.debug("Pokemon XD: live shop price pass failed", exc_info=True)


async def fast_poll_window(ctx: PokemonXDContext, budget_seconds: float) -> float:
    """Spend `budget_seconds` of the ordinary between-tick wait re-running only the two CHEAP Bag-watching
    checks, at `POLL_INTERVAL_FAST`. Returns the unspent budget, for the caller to sleep.

    One window for both, not two: they read the Bag pocket and nothing else, and two overlapping sub-loops would
    each think they owned the sleep. The halves are gated differently -- a shop check can only happen in a shop
    room, while a chest can be opened anywhere, so `check_chests` runs every sub-tick at one `read_room_id` plus
    one bulk Bag read. The rest of the tick is not affordable: `check_trainer_defeats` reads all 24MB of MEM1.

    It re-reads the room every sub-tick (walking out of a shop must end that half at once), re-polls block
    stability (both checks sit behind that gate in the main loop), and waits on the same `watcher_event` the
    outer loop does. Every failure mode is "do less": any exception, an unreadable room, an unstable block or a
    lost hook ends the window."""
    if budget_seconds <= 0.0 or ctx.block_base is None:
        return budget_seconds
    # ADDENDUM 400: the white-out signal is sampled in here too, so the window has to open for a seed with
    # chests AND shops off. The latch is not a Death Link feature -- it also keeps a white-out from walking the
    # story byte backwards -- so it is not gated on the option either.
    if not ctx.randomize_shops and not ctx.randomize_chests:
        return budget_seconds
    remaining = budget_seconds
    while remaining > 0.0 and not ctx.exit_event.is_set():
        tick = min(POLL_INTERVAL_FAST, remaining)
        try:
            await asyncio.wait_for(ctx.watcher_event.wait(), tick)
        except asyncio.TimeoutError:
            pass
        else:
            # Something was queued for us. Hand the rest of the wait back so the outer loop's full body --
            # give_items above all -- runs now. The event is cleared by the outer loop, not here.
            #
            # But poll the chests ONCE on the way out: returning immediately meant that in a multiworld
            # delivering an item most ticks, the chest half was cut off at the first sub-tick and ran at the
            # outer 1.0s rate for exactly the players receiving the most items.
            if ctx.randomize_chests:
                try:
                    if (ram_client.is_hooked() and ctx.block_base is not None
                            and ctx.block_stability.poll(ctx.block_base)):
                        await check_chests(ctx)
                except Exception:
                    logger.debug("Pokemon XD: chest poll on wake failed", exc_info=True)
            return 0.0
        remaining -= tick
        try:
            if not ram_client.is_hooked() or ctx.block_base is None:
                return remaining
            if not ctx.block_stability.poll(ctx.block_base):
                return remaining
            # Read once here, purely for the shop gate. Both checks still read it again themselves, per
            # `check_shops`' self-contained rule; four two-byte reads is not worth weakening it for.
            room_id = ram_client.read_room_id()
            # ADDENDUM 400: the one thing in this window that is NOT a Bag check. A white-out's window is the
            # end-of-battle sequence -- flag set, party healed -- and the outer loop's 1.0s cadence can sit
            # across the whole of it, which is why no Death Link was being SENT at all. Sampled at 0.05s
            # here it is twenty looks instead of one, for one bulk read of the encounter records.
            #
            # It only ARMS here. The send and the region bookkeeping stay in the outer loop, so the ordering
            # against `send_death` and the area memory is unchanged and this cannot race them.
            try:
                ctx.whiteout_latch.sample()
            except Exception:
                pass            # a latch may never be the thing that ends the fast window
            if ctx.randomize_chests:
                await check_chests(ctx)
            if ctx.randomize_shops and ram_client.is_shop_room(room_id):
                await check_shops(ctx)
        except Exception:
            logger.debug("Pokemon XD: fast poll window ended early", exc_info=True)
            return remaining
    return max(0.0, remaining)


def beaten_flag_location_names(ctx: PokemonXDContext, indices) -> "list[str]":
    """The checks a trainer's beaten flag stands for: its own "Defeat -" check and its surname's "(Any)" check."""
    names: "list[str]" = []
    for index in indices:
        trainer = trainer_roster.TRAINERS_BY_INDEX.get(int(index))
        if trainer is None:
            continue
        for name in (trainer_roster.trainer_label(trainer),
                     REPEATABLE_SURNAME_TO_LOCATION.get(trainer["name"].strip().upper())):
            if name and name in LOCATION_NAME_TO_ID and LOCATION_NAME_TO_ID[name] not in ctx.checked_locations:
                names.append(name)
    return sorted(set(names))


def kaminko_autosend_labels() -> "set[str]":
    """The missable auto-send checks that belong to a Kaminko trainer: with Kaminko Missable Trainers on, a missed
    one is won outside the manor rather than sent at its area's cap."""
    from .game_data import kaminko_trainers as kt
    from .game_data.missable_autosend import AUTO_SEND_ONE_SHOT_INDICES

    return {AUTO_SEND_ONE_SHOT_INDICES[t] for t, _b, _s in kt.KAMINKO_TRAINERS if t in AUTO_SEND_ONE_SHOT_INDICES}


def kaminko_shadow_hosts(hosts: "list[dict]", kaminko_trainers: bool) -> "list[dict]":
    """With Kaminko Missable Trainers on, a Kaminko trainer keeps its Shadow for the rematch outside the manor; one
    left unsnagged there flees to Miror B. the ordinary way."""
    if not kaminko_trainers:
        return list(hosts)
    from .game_data import kaminko_trainers as kt

    fought_there = {t for t, _b, _s in kt.KAMINKO_TRAINERS}
    return [h for h in hosts if int(h.get("trainer_index", -1)) not in fought_there]


def _kaminko_progress_known(ctx: PokemonXDContext) -> bool:
    """Something has been read about story progress, so a missed trainer can be told from one still ahead."""
    if _missable_area_progress(ctx) is not None:
        return bool(ctx.area_story_memory.highest_by_region)
    high = getattr(ctx.story_progress, "high_water", None)
    return max(ctx.missable_autosender.last_progress, -1 if high is None else int(high)) >= 0


def _kaminko_trainer_missed(ctx: PokemonXDContext, trainer: int) -> bool:
    """Its area's story is past it: the cap the missable auto-send waits for, or -- for a trainer with no auto-send
    label of its own (a Six's second fight, Equin's first) -- its region's story ceiling."""
    from .game_data import story_bytes, trainer_placements
    from .game_data.missable_autosend import AUTO_SEND_ONE_SHOT_INDICES

    from .game_data import missable_autosend

    sender = ctx.missable_autosender
    label = AUTO_SEND_ONE_SHOT_INDICES.get(int(trainer))
    if label is not None and label in sender.schedule:
        cap, caps = sender.schedule[label], sender.area_caps.get(label, ())
    else:
        # No label of its own (a Six's second fight, Equin): the cap its area's missable fights share.
        record = trainer_roster.TRAINERS_BY_INDEX.get(int(trainer))
        region = missable_autosend.region_for(int(trainer)) or trainer_placements.region_for(int(trainer))
        cap = missable_autosend.cap_for(trainer_roster.trainer_label(record), int(trainer)) if record else None
        if cap is None or region is None:
            window = story_bytes.REGION_STORY_WINDOW.get(region) if region else None
            if window is None:
                return False
            cap = window.ceiling
        caps = ((region, cap),)
    area_progress = _missable_area_progress(ctx)
    if area_progress is not None:
        if not caps:
            return False
        for region, area_cap in caps:
            reached = area_progress(region)
            if reached is None or reached < area_cap:
                return False
        return True
    progress = max(sender.last_progress, int(getattr(ctx.story_progress, "high_water", -1)))
    return progress >= 0 and cap <= progress


def describe_kaminko_trainers(ctx: PokemonXDContext) -> "list[str]":
    """Every trainer who can stand outside the manor, and why they do or don't: beaten, missed (waiting there, twelve
    at a time, in this order) or still ahead in their own area."""
    from .game_data import kaminko_trainers as kt

    if not _kaminko_progress_known(ctx):
        return ["Story progress hasn't been read yet, so no one is placed."]
    beaten, waiting, ahead = [], [], []
    for trainer, _battle, _source in kt.KAMINKO_TRAINERS:
        record = trainer_roster.TRAINERS_BY_INDEX.get(trainer)
        name = trainer_roster.trainer_label(record).replace("Defeat - ", "") if record else str(trainer)
        try:
            if _kaminko_trainer_beaten(ctx, trainer):
                beaten.append(name)
            elif _kaminko_trainer_missed(ctx, trainer):
                waiting.append(name)
            else:
                ahead.append(name)
        except Exception:
            ahead.append(f"{name} (?)")
    lines = [f"Missed, waiting outside the manor ({len(waiting)}; twelve show at a time, in this order): "
             + (", ".join(waiting) or "none")]
    lines.append("Not missed yet (their area's story isn't past them): " + (", ".join(ahead) or "none"))
    lines.append("Beaten: " + (", ".join(beaten) or "none"))
    return lines


def _kaminko_trainer_beaten(ctx: PokemonXDContext, trainer: int) -> bool:
    if trainer in ctx.kaminko_won:
        return True
    record = trainer_roster.TRAINERS_BY_INDEX.get(int(trainer))
    label = trainer_roster.trainer_label(record) if record is not None else None
    if label in LOCATION_NAME_TO_ID and LOCATION_NAME_TO_ID[label] in ctx.checked_locations:
        return True                                 # beaten where it stood
    if record is not None and _beaten_in_defeat_ledger(ctx, record):
        return True                                 # the same, read off the win itself (cumulative mode has no label)
    flag = TRAINER_BEATEN_FLAGS.get(trainer)
    return bool(flag is not None and ram_client.gs_flag_get(flag))


def _beaten_in_defeat_ledger(ctx: PokemonXDContext, record: dict) -> bool:
    """The battle watcher's own record of wins, in either trainer-defeat mode. A surname only one trainer carries is
    that trainer; a shared one counts only when the beaten team resolves to this trainer's, never on a guess."""
    tracker = getattr(ctx, "trainer_defeat_tracker", None)
    if tracker is None:
        return False
    surname = str(record.get("name", "")).strip().upper()
    if int(record.get("total_with_name", 1) or 1) <= 1:
        return tracker.wins_by_surname.get(surname, 0) > 0
    label = trainer_roster.trainer_label(record)
    beaten = tracker._beaten_team_ids.get(surname, [])
    if f"occ:{label}" in beaten:
        return True
    fingerprints = ctx.trainer_team_fingerprints or {}
    labels = trainer_roster.UNIQUE_SURNAME_TO_LOCATION_QUEUE.get(surname, [])
    if not fingerprints or label not in fingerprints:
        return False
    for identity in beaten:
        if not identity.startswith("obs:"):
            continue
        species = {part.split("@", 1)[0] for part in identity[4:].split(",") if part}
        if species and tracker._resolve_occurrence(labels, species, fingerprints, None) == label:
            return True
    return False


async def check_kaminko_trainers(ctx: PokemonXDContext) -> None:
    """Kaminko Missable Trainers: fill the twelve spots outside the manor each time it loads, and record wins. A win
    also sets the trainer's own beaten flag where it has one, and sends their defeat checks."""
    if not getattr(ctx, "kaminko_trainers", False) or ctx.block_base is None:
        return
    from .game_data import kaminko_trainers as kt

    in_area = ctx.room_tracker.current == kt.FLOOR_ROOM_ID
    won = ctx.kaminko_slots.poll(in_area, lambda trainer: _kaminko_trainer_beaten(ctx, trainer)
                                 or not _kaminko_trainer_missed(ctx, trainer),
                                 ready=_kaminko_progress_known(ctx))
    if not won:
        return
    ctx.kaminko_won.update(won)
    ctx._save_local_state()
    for trainer in won:
        flag = TRAINER_BEATEN_FLAGS.get(trainer)
        if flag is not None:
            ram_client.gs_flag_set(flag, 1)
    seed_ids = seed_location_ids(ctx)
    names = [name for name in beaten_flag_location_names(ctx, won)
             if not seed_ids or LOCATION_NAME_TO_ID[name] in seed_ids]
    if names:
        await _send_checks(ctx, names)


def check_kaminko_miror(ctx: PokemonXDContext) -> None:
    """Miror B. outside Kaminko's House fights only while his queue holds a Shadow; the client tells him which."""
    if ctx.block_base is None:
        return
    from .game_data import kaminko_trainers as kt

    in_area = ctx.room_tracker.current == kt.FLOOR_ROOM_ID
    if not in_area:
        return
    queue = ram_client.read_miror_queue(ctx.block_base)
    if queue is None:
        return
    ctx.kaminko_slots.set_miror(True, bool(queue))


CITADARK_ADMINS_INTERVAL = 15.0


def check_citadark_admins_only(ctx: PokemonXDContext) -> None:
    """Citadark Admins Only: every Citadark trainer who is not an admin reads as beaten, so their floors never start
    the fight and hide them. Only writes a variable that is not already set; never raises."""
    if not getattr(ctx, "citadark_admins_only", False) or ctx.block_base is None:
        return
    now = time.monotonic()
    if now < ctx._citadark_admins_due:
        return
    ctx._citadark_admins_due = now + CITADARK_ADMINS_INTERVAL
    from .game_data.citadark_admins import beaten_variables

    written = 0
    for variable in beaten_variables():
        try:
            if ram_client.gs_flag_get(variable) == 0 and ram_client.gs_flag_set(variable, 1):
                written += 1
        except Exception:
            continue
    if written:
        _note(ctx, f"Citadark Admins Only: {written} Citadark trainer marker(s) set to beaten.")


async def check_trainer_beaten_flags(ctx: PokemonXDContext) -> None:
    """A second witness for trainer defeats: each trainer's own beaten flag, set by its map script after the win.
    Unique trainer-defeat mode only (cumulative mode is a tally). Runs inside the save-block gate, and a flag must
    read set on two polls in a row."""
    if not (ctx.shuffle_trainer_defeats and ctx.unique_trainer_defeats) or ctx.block_base is None:
        return
    try:
        fresh = ctx.beaten_flag_watcher.poll()
    except Exception:
        return
    if fresh and getattr(ctx, "citadark_admins_only", False):
        from .game_data.citadark_admins import REMOVED_TRAINER_INDICES
        fresh = [index for index in fresh if index not in REMOVED_TRAINER_INDICES]   # marked beaten by the client
    if not fresh:
        return
    seed_ids = seed_location_ids(ctx)
    names = [name for name in beaten_flag_location_names(ctx, fresh)
             if not seed_ids or LOCATION_NAME_TO_ID[name] in seed_ids]
    if names:
        await _send_checks(ctx, names)


async def check_trainer_defeats(ctx: PokemonXDContext) -> None:
    """Live battle-roster HP tracking for "Defeat - {trainer}" and cumulative "Defeat N Trainers". Design lives
    in ram_client.TrainerBattleDefeatTracker; no scan at all with shuffle_trainer_defeats off.

    The scan covers the whole 24MB of MEM1 every tick, because roster records sit at boot-dependent addresses
    (0x80831e54 on one boot, elsewhere on the next) and every bounded window tried missed a real battle on some
    boot and found nothing, silently, for that whole run.

    A RuntimeError from that read is caught locally as "no records this tick": part of MEM1 is sometimes
    transiently unreadable (a full-range dump failed at ~0x805b0000 and succeeded minutes later mid-battle), and
    an escaping exception reaches `dolphin_sync_task`'s handler, which reads any exception as "connection lost" --
    turning "occasionally misses a defeat" into "the connection drops during battles". The tracker tolerates
    missed ticks: it needs an HP-drop transition across several polls, not one snapshot.

    This poll also drives the seed's Goal off the tracker's confirmed-kill signal rather than a second scan. Goal
    0 watches for Greevil's already-named location. Goal 1 fires on ONE thing: a confirmed win over Battlus, Mt.
    Battle's 100th and final trainer (Bulbapedia: "Battlus ... is the final trainer at Mt. Battle"; index 100
    decodes out of the ISO as BATTLUS). ADDENDUM 406 removed the running-count backstop -- MIRU plus 99 more
    defeats -- because MIRU is also story trainer 30, so it armed in the story and fired on the 100th defeat of
    anything; and Battlus is watched through the Mt. Battle exclusion, which used to hide him from this check
    entirely. `/goal` stays the manual fallback."""
    if ctx.block_base is None:
        return
    # ADDENDUM 406: the Mt. Battle goal needs this scan even in a seed with no trainer-defeat checks. Such a seed
    # only WATCHES (nothing is sent, nothing feeds the battle hold), exactly as it behaved before for everything
    # but the goal.
    goal_watch_only = not ctx.shuffle_trainer_defeats
    if goal_watch_only and (ctx.goal != 1 or ctx.finished_game):
        return
    try:
        records = ram_client.scan_battle_roster()
    except RuntimeError as e:
        _note_warn(ctx, f"Battle-roster scan failed this tick (transient memory-read error, skipping): {e}")
        records = []
    # Feed the same scan to the battle-activity hold before anything else consumes it: no extra memory read.
    if not goal_watch_only:
        try:
            ctx.battle_hold.observe(records, ram_client.read_battle_struct_anchor())
        except Exception:
            ctx.battle_hold.observe(records)  # anchor read is optional; motion alone is the load-bearing signal

    # The player's own trainer name is on every one of their party's roster records, so without this the tracker
    # reads their own party wiping (losing) as a defeat and parks that surname in _awaiting_clear, where it can
    # never re-arm because the player's records never vanish.
    exclude = set(own_trainer_names(ctx))   # ADDENDUM 444: the in-game name, from the save
    # The Mt. Battle option reuses the same exclude_surnames mechanism rather than a second one.
    # MIRU/CRIDEL/BARDO are deliberately absent from MT_BATTLE_ONLY_SURNAMES: they are story trainers 30/31/32
    # too, so excluding them would stop their STORY encounter counting.
    if ctx.exclude_mt_battle_trainers:
        exclude |= MT_BATTLE_ONLY_SURNAMES
    # Unique mode dispatches against the full 232-trainer ISO roster and suppresses the cumulative bucket
    # entirely -- count_location_max=0 means no "Defeat N Trainers" name is ever produced.
    if ctx.unique_trainer_defeats:
        queue = trainer_roster.UNIQUE_SURNAME_TO_LOCATION_QUEUE
        if not ctx.exclude_mt_battle_trainers:
            # Each Mt. Battle trainer 4-100 is a check of its own.
            queue = {**queue, **MT_BATTLE_SURNAME_TO_LOCATION_QUEUE}
        count_cap = 0
    else:
        queue = trainer_defeat.SURNAME_TO_LOCATION_QUEUE
        count_cap = ctx.trainer_defeat_check_count
    # ADDENDUM 406: with the Mt. Battle goal, the final trainer is watched through the exclusion -- confirmed for
    # the goal, never counted or sent. Only the names actually excluded need it; otherwise he counts as usual.
    confirm_only = (frozenset(MT_BATTLE_FINAL_TRAINER_SURNAMES) & exclude) if ctx.goal == 1 else frozenset()
    newly_completed = ctx.trainer_defeat_tracker.poll(
        queue,
        trainer_defeat_count_location_name,
        records,
        count_location_max=count_cap,
        exclude_surnames=exclude,
        team_fingerprints=ctx.trainer_team_fingerprints or None,
        confirm_only_surnames=confirm_only,
        non_player_fights=trainer_roster.NON_PLAYER_FIGHTS,   # ADDENDUM 436
        # ADDENDUM 439: the room the fight is in. A battle keeps the field's room id (the Snagem hold relies on the
        # same), so the room the player is standing in is the fight's.
        watched_here=ram_client.watched_fight_surnames(
            ctx.room_tracker.current if ctx.room_tracker.current is not None else ctx.room_tracker.previous),
    )
    _bank_key_lair_zook(ctx)   # ADDENDUM 487
    if goal_watch_only:
        newly_completed = []   # no defeat checks exist in this seed; the scan ran for the goal only
    elif ctx.unique_trainer_defeats and newly_completed:
        # ADDENDUM 411: Ardos #1 and Zook #1 send each other; see `trainer_roster.apply_defeat_links`.
        checked_ids = set(ctx.checked_locations) | set(getattr(ctx, "locations_checked", ()) or ())
        already = {
            name for name in trainer_roster.DEFEAT_LINKS
            if name in LOCATION_NAME_TO_ID and LOCATION_NAME_TO_ID[name] in checked_ids
        }
        newly_completed = trainer_roster.apply_defeat_links(list(newly_completed), already)
    # ADDENDUM 414: cumulative mode is a tally and nothing else. The named queue is still dispatched -- the Greevil
    # goal reads it -- but only "Defeat N Trainers" names are sent; the named checks are not locations any more.
    goal_names = list(newly_completed)
    if not ctx.unique_trainer_defeats:
        newly_completed = [name for name in newly_completed if name in TRAINER_DEFEAT_COUNT_LOCATION_NAME_SET]
    # The "Defeat X (Any)" checks, dispatched off the SURNAME rather than the queue.
    # `last_confirmed_surnames` says nothing about which occurrence was fought -- exactly the question "any
    # defeat" does not ask -- so no queue position, team fingerprint or story order is needed. CASE-INSENSITIVE,
    # because the live roster reports NPC names upper-case ("LOVRINA") and a mismatch un-fires all 35. Greevil's
    # decoy counts: only the NAMED queue suppresses it, and the location is always filler.
    if ctx.shuffle_trainer_defeats and ctx.unique_trainer_defeats:   # ADDENDUM 414: unique mode's checks only
        confirmed = {s.strip().upper() for s in ctx.trainer_defeat_tracker.last_confirmed_surnames}
        any_defeat = [
            name for surname, name in REPEATABLE_SURNAME_TO_LOCATION.items()
            if surname in confirmed
            and name in LOCATION_NAME_TO_ID
            and LOCATION_NAME_TO_ID[name] not in ctx.checked_locations
        ]
        if any_defeat:
            newly_completed = list(newly_completed) + sorted(any_defeat)

    if newly_completed:
        await _send_checks(ctx, newly_completed)

    if not ctx.finished_game:
        if ctx.goal == 0 and _greevil_rematch_defeated(goal_names + list(newly_completed),
                                                       ctx.trainer_defeat_tracker.wins_by_surname):
            logger.info("Greevil's rematch confirmed defeated -- completing this seed's goal.")
            await ctx.declare_goal_complete()
        elif ctx.goal == 1:
            confirmed_upper = {s.strip().upper() for s in ctx.trainer_defeat_tracker.last_confirmed_surnames}
            final_hit = sorted(confirmed_upper & {s.upper() for s in MT_BATTLE_FINAL_TRAINER_SURNAMES})
            if final_hit:
                logger.info(
                    f"Mt. Battle's 100th and final trainer ({final_hit[0].title()}) confirmed defeated -- "
                    f"completing this seed's goal."
                )
                await ctx.declare_goal_complete()


#: ADDENDUM 487. Zook kept rematching: beating him moved the byte from 0x64 to 0x65, but returning wrote 0x64 again.
#: The Key Lair's floor was not being banked -- only the byte was written, and only sometimes:
#: ADDENDUM 476's bump (0x65 -> 0x66, banking 0x65 as the Lair's mark so its floor rule enters later visits at 0x66)
#: fires while the player stands in a room `region_for_room` calls "Cipher Key Lair" -- the 1F-4F and roof rooms.
#: Zook is fought in the courtyard outside them, which resolves to no region, so leaving from there banked nothing and
#: the next arrival wrote the 0x64 entry floor: Zook again. The floor is now banked off the DEFEAT itself, wherever it
#: is fought -- his win is the one thing that is certain -- and the live bump still lifts the byte on entering 1F.
KEY_LAIR_REGION = "Cipher Key Lair"
KEY_LAIR_ZOOK_SURNAME = "ZOOK"
KEY_LAIR_ZOOK_WINDOW = (0x64, 0x66)     # staged at 0x64, his win writes 0x65; 0x66 if our bump already ran
KEY_LAIR_ZOOK_MARK = 0x65               # the trigger byte `AreaFloorRule("Cipher Key Lair", 0x66, ...)` keys on


def _bank_key_lair_zook(ctx: PokemonXDContext) -> None:
    """ADDENDUM 487: Zook beaten at the Key Lair -> the Lair's mark is at least 0x65, so every later visit enters at
    0x66, past his fight. Zook's only other fight is the watched Gateon one (Ardos vs Zook, story ~0x10s), far outside
    the window. Location shuffle only, like the bump it backs up; never lowers a mark."""
    if not getattr(ctx, "randomize_travel_locations", False) or ctx.block_base is None:
        return
    confirmed = {s.strip().upper() for s in (ctx.trainer_defeat_tracker.last_confirmed_surnames or ())}
    if KEY_LAIR_ZOOK_SURNAME not in confirmed:
        return
    live = ram_client.read_story_byte(ctx.block_base)
    low, high = KEY_LAIR_ZOOK_WINDOW
    if live is None or not low <= live <= high:
        return
    memory = ctx.area_story_memory
    if memory.highest_by_region.get(KEY_LAIR_REGION, -1) >= KEY_LAIR_ZOOK_MARK:
        return
    memory.highest_by_region[KEY_LAIR_REGION] = KEY_LAIR_ZOOK_MARK
    memory.visited.add(KEY_LAIR_REGION)
    memory.dirty = True
    _save_area_memory(ctx)
    _note(ctx, "Zook beaten at the Cipher Key Lair -- your next visits enter past his fight (0x66).")


# The roster holds THREE Greevil encounters (indices 199, 200, 201) and the win is the second of the two
# back-to-back fights, so occurrence 1 is not a win and anything after it is. Matching on occurrence >= 2 rather
# than one exact index survives a roster regeneration that renumbers the encounters.
#
# ADDENDUM 415: unique mode too. This set used to hold the cumulative queue's name only, so a unique-mode seed
# dispatched "Defeat - Greevil #2" and never matched it -- those seeds finished on the story-byte backstop alone.
# Matching the #2 label is right, and having ever defeated Greevil twice also sends the victory. Both are here: the unique labels past #1, and a plain count of Greevil wins (`GREEVIL_WINS_FOR_GOAL`).
_GREEVIL_REMATCH_LOCATION_NAMES: "frozenset[str]" = frozenset(
    name for name in (list(trainer_defeat.SURNAME_TO_LOCATION_QUEUE.get("Greevil", ()))
                      + list(trainer_roster.UNIQUE_SURNAME_TO_LOCATION_QUEUE.get("GREEVIL", ())))
    if name and not name.endswith("#1")
)
GREEVIL_WINS_FOR_GOAL = 2


def _greevil_rematch_defeated(newly_completed, wins_by_surname=None) -> bool:
    """True when a Greevil encounter past the first has just been confirmed, or Greevil has been beaten twice."""
    if _GREEVIL_REMATCH_LOCATION_NAMES & set(newly_completed):
        return True
    return (wins_by_surname or {}).get("GREEVIL", 0) >= GREEVIL_WINS_FOR_GOAL


VICTORY_STORY_CONFIRM_POLLS = 3


async def check_victory_story_byte(ctx: PokemonXDContext) -> None:
    """The second, independent win detection. The trainer-defeat path can miss -- a roster read landing
    mid-update, a battle ending in a way the tracker does not recognise -- and a missed win is the one failure a
    player cannot work around from inside the game, while the story byte advances on its own as the ending runs.

    Cheap and last: one 20-byte read, never writes, never blocks delivery, and can only ADD a win (an unreadable
    or implausible byte is simply False, per `story_byte_says_won`'s contract)."""
    if ctx.finished_game or ctx.block_base is None:
        return
    # ADDENDUM 406: the story's ending is the Greevil goal's win, not the Mt. Battle goal's. A Mt. Battle seed
    # that finishes the story first must keep going.
    if ctx.goal != 0:
        return
    try:
        if not ram_client.story_byte_says_won(ctx.block_base):
            ctx.victory_story_streak = 0
            return
        # The ending has to hold for several settled polls in a row; a value seen once, mid-save, does not count.
        ctx.victory_story_streak += 1
        if ctx.victory_story_streak >= VICTORY_STORY_CONFIRM_POLLS:
            logger.info(
                f"Story byte reached 0x{ram_client.VICTORY_STORY_BYTE:02X} -- completing this seed's goal "
                f"(the independent win check; the Greevil defeat may simply not have been seen)."
            )
            await ctx.declare_goal_complete()
    except Exception:
        return  # never let a win-detection read break the poll loop


# Hold the vanilla travel bits clear, and turn the vanilla unlock into a check. Only ADDING bits when an item
# arrives is not enough: the game keeps unlocking destinations as the story advances.
#
# Four areas are exempt: Gateon Port and Agate Village are in ALWAYS_OPEN_TRAVEL_BITS rather than
# TRAVEL_LOCATION_BITS, Pokemon HQ Lab was never a travel destination, and Kaminko's House is skipped by name.
# The set lives in travel_locations so regions.py reads the SAME one -- the graph decides which regions are
# gateway-only from it, and a disagreement would promise access to an icon this loop is re-locking.
_TRAVEL_CLEAR_EXEMPT: "frozenset[str]" = travel_locations.TRAVEL_CLEAR_EXEMPT


def _any_override_holding(ctx: PokemonXDContext) -> bool:
    """True while EITHER `StoryByteOverride` is sitting on the story byte: the Gateon Robo Kyogre override and
    `ss_libra_gate`, the travel-OFF scooter clamp. Asking about both is redundant today -- `ss_libra_gate` only
    runs with travel randomization off, where `enforce_travel_locks` returns immediately -- but otherwise the
    fence would hold only by coincidence between two `if` statements in different files. Never raises."""
    for name in ("story_byte_override", "ss_libra_gate"):
        try:
            if getattr(getattr(ctx, name, None), "active", False):
                return True
        except Exception:
            continue
    return False


def _unlock_mark_for(ctx: PokemonXDContext, destination: str) -> "int | None":
    """The highest byte the GAME has put in the story while the player stood in the area ONE RUNG BELOW
    `destination` -- where its icon is actually earned. `travel_locations.unlock_witness_regions` names that
    area's group; the mark is `AreaStoryByteMemory.highest_by_region`, which banks nothing this client wrote.
    None when there is no mark, the ordinary state for somewhere the player has not played."""
    try:
        from . import travel_locations

        marks = ctx.area_story_memory.highest_by_region
        seen = [marks[region] for region in travel_locations.unlock_witness_regions(destination)
                if region in marks]
        return max(seen) if seen else None
    except Exception:
        return None


def _unlock_is_earned(ctx: PokemonXDContext, destination: str, threshold: int) -> bool:
    """Has the player earned `Unlock - {destination}`?

    The rule: the game moved the story byte to this destination's threshold WHILE the player stood in the area
    one rung below it -- where, in the unmodified game, that icon appears. Nobody unlocks a destination by
    standing in it. Asking for the mark in the destination itself is wrong both ways: it let an early region
    credit every later unlock (nine at once at Gateon Port, whose 0x0F floor is at or before every threshold in
    the game), and it made every `Unlock - D` wait on `Travel Unlock - D`, which is deferred self-credit. The
    predecessor rule cannot self-credit, because the witness is never D. The retired `_story_byte_was_earned_here`
    asked the global byte's provenance instead; `Unlock -` checks no longer consult it at all.

    Never raises; anything unexpected answers False, which defers rather than sends. `/unlocks` prints the held
    table, because a check waiting on a mark that never arrives would otherwise be silent."""
    mark = _unlock_mark_for(ctx, destination)
    return mark is not None and mark >= threshold


def _witness_story_progress(ctx: PokemonXDContext) -> "int | None":
    """One tick of `StoryProgressWitness`: the highest story byte the GAME wrote, or None before one is seen.

    ADDENDUM 402: a helper rather than an inline call because there are two readers now -- `Unlock -` credit in
    `enforce_travel_locks`, and the missable auto-send, which runs in BOTH travel modes while the former returns
    early with travel randomization off. One call shape, so the two cannot drift on what counts as credible.

    BOTH overrides are passed: `ss_libra_gate` is a second `StoryByteOverride`. With travel randomization off it
    is the one that can be holding the byte, which is exactly the mode the second reader added."""
    value = ctx.story_progress.poll(
        ram_client.read_story_byte(ctx.block_base),
        ctx.room_tracker.current,
        ctx.area_story_memory._write_outstanding,
        _any_override_holding(ctx),
        ctx.area_story_memory.last_written_target,
    )
    return None if value < 0 else value


def _missable_area_progress(ctx: PokemonXDContext):
    """ADDENDUM 405: region -> that area's own story progress, or None in vanilla travel (one byte for all).

    Read from `AreaStoryByteMemory.highest_by_region` -- the marks it banks only for bytes the GAME put there while
    the player stood in that area -- plus the floors its satisfied rules now impose. See
    `story_bytes.area_progress`."""
    if not ctx.randomize_travel_locations:
        return None
    from .game_data import story_bytes as _story_bytes

    marks = ctx.area_story_memory.highest_by_region
    return lambda region: _story_bytes.area_progress(region, marks)


async def check_missable_autosend(ctx: PokemonXDContext) -> None:
    """ADDENDUM 402/405: send each missable trainer check once its area's story reaches that area's cap.

    The schedule and the reasoning live in `game_data/missable_autosend.py`; the WHEN lives in
    `ram_client.MissableAutoSender`. This only gathers the three inputs. Never raises -- a detector that can stop
    the poll loop is worse than a check that arrives a tick late."""
    if ctx.block_base is None or not ctx.shuffle_trainer_defeats:
        return
    try:
        # With travel randomization ON, `enforce_travel_locks` already polled the witness this tick; polling it
        # again would only double its counters. With it OFF nothing else polls it, so this does.
        if ctx.randomize_travel_locations:
            progress = ctx.story_progress.high_water
        else:
            progress = _witness_story_progress(ctx)
        ctx._missable_tick_progress = progress
        seed_ids = seed_location_ids(ctx)
        in_seed = {ID_TO_LOCATION_NAME[i] for i in seed_ids if i in ID_TO_LOCATION_NAME} if seed_ids else None
        if in_seed is not None and getattr(ctx, "kaminko_trainers", False):
            in_seed -= kaminko_autosend_labels()        # fought at Kaminko's House instead
        checked = {ID_TO_LOCATION_NAME[i] for i in ctx.checked_locations if i in ID_TO_LOCATION_NAME}
        # ADDENDUM 405: with travel randomization ON each check waits on ITS OWN area's progress, never on the
        # global high-water mark -- every area keeps its own story, so another area's progress closes nothing here.
        due = ctx.missable_autosender.due(progress, in_seed, checked, _missable_area_progress(ctx))
    except Exception:
        logger.debug("Pokemon XD: missable auto-send skipped this tick", exc_info=True)
        return
    if due:
        _note(ctx, f"{len(due)} missable trainer fight(s) reached their area's story cap -- sending them for you: "
                   f"{', '.join(due)}")
        await _send_checks(ctx, due)


def _species_catch_sent(ctx: PokemonXDContext, dex: int) -> bool:
    """The server has this species' `Catch -` check."""
    from .species import location_name_for_species

    location_id = LOCATION_NAME_TO_ID.get(location_name_for_species(int(dex)))
    return location_id is not None and location_id in ctx.checked_locations


async def check_missable_shadows(ctx: PokemonXDContext) -> None:
    """Missable Trainer Shadows: hand each missed missable fight's Shadow to Miror B. once its area's story cap has
    passed, and say so. Runs right after `check_missable_autosend`, reusing the progress it read this tick (the witness
    must not be polled twice); with trainer defeats off that function returns early, so this reads it itself."""
    pusher = ctx.missable_shadow_pusher
    if not pusher or ctx.block_base is None:
        return
    try:
        if ctx.randomize_travel_locations:
            progress = ctx.story_progress.high_water
        elif ctx.shuffle_trainer_defeats:
            progress = ctx._missable_tick_progress
        else:
            progress = _witness_story_progress(ctx)
        moved = pusher.poll(ctx.block_base, progress, _missable_area_progress(ctx),
                            already_caught=lambda dex: _species_catch_sent(ctx, dex))
    except Exception:
        logger.debug("Pokemon XD: missable Shadow hand-off skipped this tick", exc_info=True)
        return
    for miror_b_handoff_line in moved:
        logger.info(miror_b_handoff_line)


async def enforce_travel_locks(ctx: PokemonXDContext) -> None:
    """Holds every not-yet-received destination's map bit CLEAR. Runs only with randomize_travel_locations on --
    with it off the player unlocks destinations by playing, and nothing here should touch save data. Never raises,
    and never blocks item delivery.

    ADDENDUM 434: this no longer sends the `Unlock - {name}` checks off the story byte. They go out when the game
    sets one of the destination's bits (`observe_travel_reveals`, read before this clears them)."""
    if not ctx.randomize_travel_locations or ctx.block_base is None:
        return
    record_base = ctx.block_base + travel_locations.TRAVEL_RECORD_OFFSET_FROM_BLOCK_BASE
    received = set(ctx.received_travel_locations or ())

    # Still polled here every tick, though nothing below reads it any more: with travel randomization ON this is
    # the witness's one poll per tick, and `check_missable_autosend` reads its high-water mark rather than polling
    # it a second time.
    _witness_story_progress(ctx)

    for name in travel_locations.TRAVEL_LOCATION_NAMES:
        if name in _TRAVEL_CLEAR_EXEMPT:
            continue
        # Access. The item is the ONLY way in; the game's own unlock is taken back every tick until it arrives.
        # Re-clearing an already-clear bit is a no-op, so this is cheap and idempotent.
        # ADDENDUM 474: SS Libra also stays shut, item or not, until Phenac City is unlocked (ADDENDUM 481: was cleared).
        if name in received and _travel_held_closed(ctx, name):
            try:
                if travel_locations.clear_travel_location_bit(record_base, name):
                    _note(ctx, "Travel: SS Libra stays closed until Travel Unlock - Phenac City arrives -- its "
                               "stranded visit would otherwise drop you into Phenac.")
            except Exception:
                pass
            continue
        if name not in received:
            try:
                if travel_locations.clear_travel_location_bit(record_base, name):
                    _note(
                        ctx,
                        f"Travel: re-locked {name} -- the story unlocked it, but its Archipelago item has not "
                        f"arrived yet.",
                    )
            except Exception:
                pass  # a failed bit write is never worth breaking the poll loop over


def observe_travel_reveals(ctx: PokemonXDContext) -> None:
    """ADDENDUM 434. Location unlock checks are sent when a partial travel-visibility bit of any kind is detected,
    not off the story byte.

    Read-only, and it must run FIRST in the tick -- before `sync_travel_locations` re-asserts granted destinations
    (clearing their partial bit) and before `enforce_travel_locks` clears the rest, since either write erases the
    evidence. What it sees is recorded in `ctx.travel_revealed` and sent from inside the block-stability gate by
    `send_travel_reveal_checks`, so nothing read mid save-menu rewrite is sent the same tick. Never raises."""
    if not ctx.randomize_travel_locations or ctx.block_base is None:
        return
    record_base = ctx.block_base + travel_locations.TRAVEL_RECORD_OFFSET_FROM_BLOCK_BASE
    received = set(ctx.received_travel_locations or ())
    seen_now: "set[str]" = set()
    for name in travel_locations.TRAVEL_LOCATION_NAMES:
        if name in _TRAVEL_CLEAR_EXEMPT or name in ctx.travel_revealed:
            continue
        try:
            revealed = travel_locations.revealed_by_game(record_base, name, name in received)
        except Exception:
            continue    # an unreadable byte reveals nothing; the next poll reads it again
        if revealed:
            seen_now.add(name)
            if name not in ctx._travel_reveal_candidates:
                continue   # a reveal counts once it has been read twice in a row
            ctx.travel_revealed.add(name)
            try:
                ctx._save_local_state()
            except Exception:
                pass
    ctx._travel_reveal_candidates = seen_now
    # The beat that reveals Realgam Tower sits below Phenac's entry floor, so it never plays in Location Shuffle:
    # standing in Phenac City counts as the reveal.
    if REALGAM_REVEAL_NAME not in ctx.travel_revealed and REALGAM_REVEAL_NAME in travel_locations.TRAVEL_LOCATION_NAMES:
        try:
            in_phenac = ram_client._room_in_areas(ctx.room_tracker.current, frozenset({"Phenac City"}))
        except Exception:
            in_phenac = False
        if in_phenac:
            ctx.travel_revealed.add(REALGAM_REVEAL_NAME)
            try:
                ctx._save_local_state()
            except Exception:
                pass


REALGAM_REVEAL_NAME = "Realgam Tower"


async def send_travel_reveal_checks(ctx: PokemonXDContext) -> None:
    """Send `Unlock - {name}` for every destination the game has revealed, until the server has each one. Re-offered
    every poll like the other detectors -- `_send_checks` is idempotent and announces only what is new."""
    if not ctx.randomize_travel_locations or not ctx.travel_revealed:
        return
    due: "list[str]" = []
    for name in sorted(ctx.travel_revealed):
        location_name = travel_locations.travel_unlock_location_name(name)
        location_id = LOCATION_NAME_TO_ID.get(location_name)
        if location_id is None or location_id in ctx.checked_locations:
            continue
        due.append(location_name)
    if due:
        await _send_checks(ctx, due)


async def check_manual_queue(ctx: PokemonXDContext) -> None:
    if not ctx._manual_check_queue:
        return
    pending, ctx._manual_check_queue = ctx._manual_check_queue, []
    await _send_checks(ctx, pending)


def seed_location_ids(ctx: PokemonXDContext) -> "set[int]":
    """Every location id THIS SEED contains, as the server reported it on Connected. `LOCATION_NAME_TO_ID` is the
    world's whole name table, identical in every seed; this is what a seed actually has. Every id this client puts
    in a packet goes through here first, because the failure mode is not a missed check, it is the server raising
    a KeyError and dropping the connection. Empty before Connected -- "not known yet", not "the seed has none"."""
    server_locations = getattr(ctx, "server_locations", None)
    if server_locations:
        return set(server_locations)
    return set(ctx.missing_locations) | set(ctx.checked_locations)


async def _scout_shop_locations(ctx: PokemonXDContext, location_ids: "list[int]") -> None:
    """Ask the server what every shop line holds, so the shelf can say it. `create_as_hint: 0` is the important
    argument -- a silent read, not a hint, so this costs the player nothing and shows up in nobody else's
    tracker. Fired from `on_package`'s Connected branch through `create_task`, and fully wrapped, because a
    server that never answers must leave the shelf generic rather than take down a client delivering items."""
    # Filtered again here, not only at the call site: this function is what puts ids on the wire, and a second
    # caller added later must not be able to reintroduce the disconnect.
    seed_ids = seed_location_ids(ctx)
    if seed_ids:
        location_ids = [location_id for location_id in location_ids if location_id in seed_ids]
    if not location_ids:
        return
    try:
        await ctx.send_msgs([{"cmd": "LocationScouts", "locations": location_ids, "create_as_hint": 0}])
    except Exception as exc:  # noqa: BLE001
        _note_warn(ctx, f"Shop scout could not be sent ({exc}); shop descriptions stay generic.")


async def _send_checks(ctx: PokemonXDContext, location_names: list[str]) -> None:
    """The single funnel every check in this client goes through. The one unconditional "sent" line lives here
    rather than in each of the ~10 callers, so no detector can be added that fires silently. Only names not
    already known to the server are announced: `ctx.check_locations` is deliberately idempotent, since several
    detectors legitimately re-offer the same location every poll until the server acknowledges it."""
    ids = {LOCATION_NAME_TO_ID[name] for name in location_names if name in LOCATION_NAME_TO_ID}
    if not ids:
        return
    # Never offer the server a location this seed does not have. MultiServer looks a LocationChecks id up in this
    # slot's own table and raises if it is absent, and the raise drops the connection -- so a stale detector does
    # not mis-credit a check, it disconnects the player in a loop. Every detector resolves names against
    # `LOCATION_NAME_TO_ID`, the world's whole name table, while what a seed CONTAINS arrives on Connected, so
    # any option that trims a category leaves them able to name a location that is not there. DROPPED, NOT
    # DEFERRED, and logged once per name.
    seed_ids = seed_location_ids(ctx)
    if seed_ids:
        outside = ids - seed_ids
        if outside:
            ids -= outside
            unreported = [i for i in outside if i not in ctx._locations_not_in_seed]
            ctx._locations_not_in_seed |= outside
            if unreported:
                names = ", ".join(ID_TO_LOCATION_NAME.get(i, f"location {i}") for i in sorted(unreported))
                _note(ctx, f"Not sent -- not in this seed: {names}.")
        if not ids:
            return
    # Announced once: a check another detector (a backup) already sent is still waiting on the server, so it is in
    # `pending_check_ids`, not yet in `checked_locations`. It goes on the wire again, but says nothing.
    pending = getattr(ctx, "pending_check_ids", None)
    fresh = sorted(ids - ctx.checked_locations - (pending or set()))
    if fresh:
        shown = ", ".join(ID_TO_LOCATION_NAME.get(i, f"location {i}") for i in fresh[:6])
        more = f" (+{len(fresh) - 6} more)" if len(fresh) > 6 else ""
        logger.info(f"Sent {len(fresh)} check(s): {shown}{more}")
        # Kept until the server confirms them: a send on a dropped connection goes nowhere.
        if pending is not None and not set(fresh) <= pending:
            pending |= set(fresh)
            try:
                ctx._save_local_state()
            except Exception:
                pass
    await _put_on_wire(ctx, ids)


async def _put_on_wire(ctx: PokemonXDContext, ids: "set[int]") -> None:
    """The one `check_locations` call. Callers have already filtered `ids` against the seed."""
    try:
        await ctx.check_locations(ids)
    except Exception as exc:  # noqa: BLE001 -- a send failure is the connection's, never Dolphin's
        _note_warn(ctx, f"Couldn't send checks right now ({exc}); they are kept and re-sent when the server is back.")


PENDING_CHECK_RESEND_SECONDS = 30.0

# Data Storage keys trackers read the player's current room from (the same templates the world puts in slot_data as
# room_id_key / room_area_key).
ROOM_ID_KEY_TEMPLATE = "pokemon_xd_room_{team}_{slot}"
ROOM_AREA_KEY_TEMPLATE = "pokemon_xd_area_{team}_{slot}"


async def publish_room(ctx: PokemonXDContext) -> None:
    """Write the current room id (and its area) to Data Storage whenever it changes, for trackers. Never raises."""
    try:
        room = ctx.room_tracker.current
        if room is None or getattr(ctx, "slot", None) is None or room == getattr(ctx, "_published_room", None):
            return
        ctx._published_room = room
        from .game_data import chest_regions

        area = chest_regions.region_for_room(room) or ""
        team, slot = getattr(ctx, "team", 0) or 0, ctx.slot
        await ctx.send_msgs([
            {"cmd": "Set", "key": ROOM_ID_KEY_TEMPLATE.format(team=team, slot=slot), "default": 0,
             "want_reply": False, "operations": [{"operation": "replace", "value": int(room)}]},
            {"cmd": "Set", "key": ROOM_AREA_KEY_TEMPLATE.format(team=team, slot=slot), "default": "",
             "want_reply": False, "operations": [{"operation": "replace", "value": str(area)}]},
        ])
    except Exception:
        pass


async def flush_pending_checks(ctx: PokemonXDContext, force: bool = False) -> None:
    """Re-send every detected check the server has not confirmed yet. Confirmed ones leave the list. Runs on
    Connected and every PENDING_CHECK_RESEND_SECONDS while connected. Never raises."""
    try:
        pending = getattr(ctx, "pending_check_ids", None)
        if not pending or getattr(ctx, "slot", None) is None:
            return
        now = time.monotonic()
        if not force and now < ctx._pending_resend_at:
            return
        ctx._pending_resend_at = now + PENDING_CHECK_RESEND_SECONDS
        confirmed = pending & set(ctx.checked_locations)
        seed_ids = seed_location_ids(ctx)
        stale = (pending - seed_ids) if seed_ids else set()
        if confirmed or stale:
            pending -= confirmed | stale
            ctx._save_local_state()
        if not pending:
            return
        ids = set(pending)
        if seed_ids:
            ids &= seed_ids
        if ids:
            await _put_on_wire(ctx, ids)
    except Exception as exc:  # noqa: BLE001
        _note(ctx, f"Pending checks not re-sent this time ({exc}).")


# The Dolphin loop: hook, confirm the game, then poll every tick.

def _looks_ingame() -> bool:
    """Cheap in-game check: is party slot 0's species field non-zero yet? PARTY_BASE initializes lazily, so an
    all-zero read means either "not in-game yet" or "in-game but has not opened Party/Status yet".

    Consulted ONLY to gate check_species_catches() and check_purifications(), the two that genuinely read
    PARTY_BASE. Everything else is BLOCK_BASE-relative or needs no live memory, and gating those here -- an
    accident of sharing one loop body -- once held item delivery for a whole session because the player had not
    opened the party screen."""
    try:
        addr = ram_client.PARTY_BASE + ram_client.PARTY_SPECIES_OFFSET
        return ram_client.read_bytes(addr, 2) != b"\x00\x00"
    except Exception:
        return False


async def _pause(ctx: PokemonXDContext, seconds: float) -> None:
    """Wait up to `seconds`, waking early when the context signals (a received item, shutdown)."""
    if seconds <= 0.0:
        return
    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(ctx.watcher_event.wait(), seconds)


async def dolphin_sync_task(ctx: PokemonXDContext) -> None:
    logger.info("Watching for Dolphin. /dolphin shows the connection status.")
    sleep_time = 0.0
    while not ctx.exit_event.is_set():
        await _pause(ctx, sleep_time)
        sleep_time = 0.0
        ctx.watcher_event.clear()

        try:
            if ram_client.is_hooked() and ctx.dolphin_status == DOLPHIN_READY:
                if ram_client.read_bytes(ram_client.MEM1_START, 4) != XD_GAME_CODE:
                    logger.info(DOLPHIN_WRONG_GAME)
                    ctx.dolphin_status = DOLPHIN_WRONG_GAME
                    ctx.block_base = None
                    ctx.fst_guard.reset()
                    sleep_time = POLL_INTERVAL_RETRY
                    continue

                # Automatic area logging is DISABLED. 0x80447EF0 was believed to hold the current-area id; a
                # post-reboot test disproved it -- standing at the HQ Lab exterior it read 6 ("Gateon Port"), and
                # no record in MEM1 held the correct id behind a live pointer. It is a cache of recently-loaded
                # areas, which only looked like position because the player walked through them in order. Still
                # polled so `/area` can report a best-effort value with its caveat.
                try:
                    ctx.area_tracker.poll(ctx.block_base)
                except Exception:
                    pass  # never let area reporting disturb the poll loop

                # The room id IS logged: unlike the retracted area value it survives a reboot and a save load,
                # distinguishes rooms within one town, and agrees with the ISO's own treasure table.
                try:
                    moved = ctx.room_tracker.poll()
                    if moved is not None:
                        was, now = moved
                        _note(ctx, f"Room change: {ram_client.room_name(was)} [id {was}] -> "
                                   f"{ram_client.room_name(now)} [id {now}]")
                except Exception:
                    pass

                # Keeps the in-RAM GameCube FST intact. Deliberately ABOVE the block_base gate: the corruption
                # happens at boot and on save load, exactly when the save block is not resolved. Writes only to
                # Dolphin's emulated RAM, never the ISO.
                fst_result = ctx.fst_guard.poll()
                # If the file table in RAM has never looked intact there is nothing to repair towards, so the
                # guard cannot arm. Said once, with the one action that fixes it.
                if fst_result.get("needs_disc_baseline", 0) == 15 and not ctx._fst_iso_hint_logged:
                    ctx._fst_iso_hint_logged = True
                    logger.info("Tip: run `/fstiso <path to your patched .iso>` once so the client can repair "
                                "'DVDOpen ... not found' freezes.")

                # ADDENDUM 421: the game picks its save buffer's address at boot (OSGetTime-seeded), so a reset
                # or a save state from another boot moves it while Dolphin stays hooked. Every read and write
                # below -- the key-item reconciler's clears included -- would go to the old address. Re-resolve.
                if ctx.block_base is not None:
                    moved_to = ctx.block_base_watch.poll(ctx.block_base)
                    if moved_to is not None:
                        _note(ctx, f"The game's save data moved ({hex(ctx.block_base)} -> {hex(moved_to)}) -- "
                                   f"re-reading it.")
                        ctx.block_base = None
                        ctx.block_stability.reset()
                        ctx.block_trust.reset()

                if ctx.block_base is None:
                    landmark = ctx.auth or ctx.username
                    if not landmark:
                        # Not authenticated to the server yet -- nothing to search for. Let server_auth() (the
                        # default CommonContext one, see module docstring) run its course.
                        sleep_time = POLL_INTERVAL_RETRY
                        continue
                    ctx.block_base = ram_client.resolve_block_base(landmark)
                    if ctx.block_base is None:
                        logger.info(DOLPHIN_NO_SAVE)
                        sleep_time = POLL_INTERVAL_RETRY
                        continue
                    ctx._snag_machine_check_due = True
                    # ADDENDUM 444: the in-game name, read from the save rather than assumed to be the slot name.
                    ctx.trainer_name = ram_client.read_trainer_name(ctx.block_base) or None
                    _note(ctx, f"Resolved Pokemon XD save data (block base {hex(ctx.block_base)}"
                               + (f", trainer {ctx.trainer_name}" if ctx.trainer_name else "") + ").")

                # ADDENDUM 382: one 20KB read, once per block base. Warns and never blocks -- see
                # `ram_client.live_move_status_report`.
                if ctx._move_status_checked_for_block_base != ctx.block_base:
                    ctx._move_status_checked_for_block_base = ctx.block_base
                    try:
                        from .game_data.move_status import MOVE_STATUS
                        for line in ram_client.describe_live_move_status(
                                ram_client.live_move_status_report(MOVE_STATUS)):
                            _note_warn(ctx, line)   # ADDENDUM 445: verbose only -- moves confirmed fine
                    except Exception:
                        pass            # a diagnostic may never be the thing that stops a poll loop

                # ADDENDUM 454: the Disable Move Animations guard -- a save state from an older build brings its
                # animation pointers back; this puts the Null ones back. ~9KB (+20KB) every few seconds, data only.
                # `/animations off` turns them off on any ISO; `/animations on` puts the game's own back.
                if ctx.animations_override is True and time.monotonic() >= ctx._animation_guard_due:
                    ctx._animation_guard_due = time.monotonic() + ANIMATION_GUARD_INTERVAL
                    try:
                        restored = ram_client.restore_move_animations()
                        if restored:
                            _note(ctx, f"Move animations: {restored} animation pointer(s) put back (/animations on).")
                    except Exception:
                        pass
                elif animations_disabled(ctx) and time.monotonic() >= ctx._animation_guard_due:
                    ctx._animation_guard_due = time.monotonic() + ANIMATION_GUARD_INTERVAL
                    try:
                        fixed = ram_client.guard_move_animations()
                        if fixed and (fixed["pointers"] or fixed["func_ids"]):
                            _note(ctx, f"Move animations: re-applied {fixed['pointers']} animation pointer(s) and "
                                       f"{fixed['func_ids']} move function id(s) -- memory came from another build "
                                       "(a save state?).")
                    except Exception:
                        pass            # a guard may never be the thing that stops a poll loop

                # Guaranteed Catches: the always-catch code and the 255 catch rates, put back if the game lacks them.
                if ctx.catch_guaranteed and time.monotonic() >= ctx._catch_guard_due:
                    ctx._catch_guard_due = time.monotonic() + CATCH_GUARD_INTERVAL
                    try:
                        for line in ctx.catch_guard.poll(ctx.catch_exclusions):
                            logger.info(line)
                    except Exception:
                        pass            # a guard may never be the thing that stops a poll loop

                # One 20-byte read per tick; needs block_base, so it sits after resolution rather than beside
                # the area id. Never allowed to disturb the poll loop.
                try:
                    advance = ctx.story_tracker.poll(ctx.block_base)
                    if advance is not None:
                        was, now = advance
                        note = ram_client.STORY_BYTE_LANDMARKS.get(now)
                        # The tracker reports ANY change, and this client writes lower values too (the area
                        # memory's first-visit floor, the parts-override restore), so "advanced" is not a given.
                        direction = "advanced" if now > was else "moved back"
                        # The byte is `value >> 3` of the story variable scripts read, and several test it by
                        # equality, so 0x26 alone cannot tell 308 from 310. Every line carries the real value and
                        # flags a non-multiple of ten, the shape of a rung the game never holds.
                        value = ctx.story_tracker.story_value
                        shown = f"0x{now:02X}" if value is None else f"0x{now:02X} ({value})"
                        line = (f"Story byte {direction}: 0x{was:02X} -> {shown}"
                                + (f" ({note})" if note else ""))
                        if value is not None and value % ram_client.STORY_VALUE_STEP:
                            line += (f" -- {value} is not a multiple of "
                                     f"{ram_client.STORY_VALUE_STEP}, so no script tests for it")
                        if ctx.story_byte_watch:
                            logger.info(line)      # /storywatch is on -- always visible, never silenced
                        else:
                            _note(ctx, line)
                except Exception:
                    pass

                # Death Link sits beside the story tracker for the same reason: it needs `block_base` and must
                # never disturb the poll loop. Inert when the option is off, without reading memory.
                try:
                    # ADDENDUM 400: one outer-loop sample too, so the latch still arms on a seed where the
                    # fast window never opens (hook lost, block unstable, or the window returning early).
                    # Cheap, and the fast window is an optimisation rather than the only path.
                    ctx.whiteout_latch.sample()
                    # ADDENDUM 417: the battle's own records, read only while a battle is running.
                    # ADDENDUM 435: polled whether or not Death Link is on -- a loss is also what arms the white-out
                    # latch that keeps the HQ Lab's story byte (ADDENDUM 400), and the annihilation flag that was
                    # meant to arm it never reads (ADDENDUM 417).
                    battle_wiped = None
                    try:
                        in_battle = ram_client.read_battle_ui_flag() == 1
                    except Exception:
                        in_battle = False
                    battle_wiped = ctx.battle_party_watch.poll(ctx.block_base, in_battle)
                    if battle_wiped is True and ctx.whiteout_latch.arm_from_battle():
                        _note(ctx, "Your team fainted -- the HQ Lab's story byte is held until you walk out of it.")
                    # ADDENDUM 475: the game's own white-out count, when the ISO has the hook. It is the send signal
                    # whenever it reads; the party watch above is only the fallback for an older ISO.
                    whiteouts = ctx.whiteout_counter.poll()
                    if whiteouts and ctx.whiteout_latch.arm_from_battle():
                        _note(ctx, "You whited out -- the HQ Lab's story byte is held until you walk out of it.")
                    should_send, death_note = ctx.death_link_bridge.poll(ctx.block_base, battle_wiped,
                                                                         whiteouts=whiteouts)
                    if death_note:
                        logger.info(f"Death Link: {death_note}")
                    if should_send:
                        Utils.async_start(ctx.send_death("whited out in Orre"))
                except Exception:
                    pass

                # Nothing below is gated on `_looks_ingame()` any more. The whole poll body used to sit behind it,
                # and PARTY_BASE initializes lazily -- all-zero until the Party/Status screen is opened once that
                # boot -- so item delivery did not start until the player's first real battle. The counters below
                # survive only because `/dolphin` reports them.
                if not _looks_ingame():
                    ctx._not_ingame_consecutive_polls += 1
                else:
                    ctx._not_ingame_consecutive_polls = 0
                    ctx._not_ingame_hint_logged = False

                if ctx.slot is not None:
                    # The save block is trusted only once it has read settled for several polls in a row. The save
                    # menu rewrites it (saving over an older file puts that file's story and travel records there
                    # for a while), so everything that reads a story byte or a travel bit -- or writes the block --
                    # waits for this, not just the checks further down.
                    save_clock = read_save_clock_safely(ctx)
                    block_is_stable = ctx.block_trust.poll(
                        (ctx.block_base is None or ctx.block_stability.poll(ctx.block_base))
                        & save_clock_allows_trust(ctx, save_clock))
                    await flush_pending_checks(ctx)
                    await publish_room(ctx)
                    try:
                        ctx.map_level_text.poll(ctx.room_tracker.current)
                    except Exception:
                        pass
                    # check_trainer_defeats() runs before give_items() and stays that way; it has to run every
                    # tick for its own job regardless.
                    await check_trainer_defeats(ctx)
                    check_save_clock(ctx, block_is_stable, save_clock)
                    await give_items(ctx)
                    # Immediately after give_items and OUTSIDE the block-stability gate, like give_items itself:
                    # a packaged item's second half is part of delivering that item.
                    _deliver_companion_items(ctx)
                    check_snag_machine_after_reload(ctx, block_is_stable)
                    # ADDENDUM 434: FIRST of the travel-record readers -- the two writers below erase what it reads.
                    if block_is_stable:
                        observe_travel_reveals(ctx)
                        await sync_travel_locations(ctx)
                    await check_manual_queue(ctx)
                    if block_is_stable:
                        await enforce_travel_locks(ctx)
                    # Inert unless `/mirorforce` armed it. Read-only until the moment it resolves, wrapped like
                    # every other cosmetic, and it can never cost a check.
                    try:
                        _miror = ctx.miror_force.poll()
                        if _miror:
                            # Unconditional, not `/verbose`: this is the second half of a command the player
                            # typed -- /mirorforce arms and returns, and the outcome lands here seconds later.
                            logger.info("/mirorforce: %s", _miror)
                    except Exception:
                        logger.debug("Pokemon XD: miror force poll failed", exc_info=True)
                    # Outside the block-stability gate and before anything needing `block_base`: the Items table
                    # is in `common_rel`, not the save block, so those preconditions only made prices late.
                    await check_shop_prices(ctx)
                    # Everything below reads the save block, and the save menu rewrites it. During that rewrite
                    # the trackers are not polled at all -- not fed a value and debounced, simply not polled --
                    # so their baselines still hold the true pre-menu state. give_items() is OUTSIDE this gate.
                    if block_is_stable:
                        # FIRST of the story-byte writers, in both travel modes: it decides whether the upgrade
                        # the game just granted may stand, and everything below reads that byte -- `observe()`
                        # above all, which would otherwise bank an unearned tier into the per-area file.
                        await check_scooter_hold(ctx)
                        await check_music_disc_hold(ctx)   # ADDENDUM 419 -- before observe() can bank 0x42
                        await check_perr_machine_part(ctx)   # before the Machine Part hold can pull 0x16 back
                        try:
                            _spot_note = ctx.pokespot_guard.poll(ctx.room_tracker.current)
                            if _spot_note:
                                _note(ctx, _spot_note)
                        except Exception:
                            pass
                        try:
                            _npc_note = ctx.npc_battle_patcher.poll(ctx.room_tracker.current)
                            if _npc_note:
                                _note(ctx, _npc_note)
                        except Exception:
                            pass
                        await check_machine_part_hold(ctx)  # ADDENDUM 421
                        await check_story_byte_override(ctx)
                        await check_area_story_memory(ctx)
                        await reconcile_key_items(ctx)
                        apply_start_with_poke_spots(ctx)
                        try:
                            if ctx.escape_rope_keeper.poll(ctx.block_base) and ctx.escape_rope_keeper.writes == 1:
                                _note(ctx, "Escape Rope put in your Key Items -- use it to go straight to the world map.")
                        except Exception:
                            pass
                        await check_krane_memos(ctx)
                        # ADDENDUM 452: after every other story-byte writer, and after the memo tracker, so a memo
                        # taken out of the Bag this tick releases the hold this tick.
                        await check_lab_memo_hold(ctx)
                        await send_travel_reveal_checks(ctx)   # ADDENDUM 434
                        await check_missable_autosend(ctx)   # ADDENDUM 402
                        await check_missable_shadows(ctx)
                        await check_chests(ctx)
                        await check_shops(ctx)
                        # Un-gated: both read the save-resident `Pokemon` records (BLOCK_BASE - 0x10 + i * 0xC4),
                        # valid from the moment the block resolves. The one call that still needs the
                        # Party/Status screen keeps its own gate inside check_purifications.
                        await check_species_catches(ctx)
                        await check_shadow_monitor_catches(ctx)
                        poll_wonder_trade(ctx)
                        check_citadark_admins_only(ctx)
                        await check_trainer_beaten_flags(ctx)
                        await check_kaminko_trainers(ctx)
                        try:
                            check_kaminko_miror(ctx)
                        except Exception:
                            pass
                        await check_purifications(ctx)
                        check_misfiled_items(ctx)   # ADDENDUM 408 -- read-only
                        # Behind the gate like every other save-block check: saving over an older file that has
                        # finished the game shows its story byte for a moment, which must not complete the goal.
                        await check_victory_story_byte(ctx)
                    elif not ctx._block_churn_logged:
                        _note(
                            ctx,
                            "Save block is being rewritten (save menu?) -- chest/shop/catch/purification "
                            "checks are paused until it settles. Nothing is lost; they resume automatically.",
                        )
                        ctx._block_churn_logged = True
                    if not block_is_stable:
                        ctx.victory_story_streak = 0
                    if block_is_stable:
                        ctx._block_churn_logged = False
                # On the map screen, poll fast: the cursor hook is a race against the player pressing A, not a
                # routine check. `room_tracker.current` is already maintained this tick.
                sleep_time = (POLL_INTERVAL_MAP_SCREEN
                              if ctx.room_tracker.current == ram_client.MAP_SCREEN_ROOM_ID
                              else POLL_INTERVAL_INGAME)
                # Spend that wait re-polling the two cheap Bag checks instead of idling. At the sleep rather than
                # in the poll body, so it only consumes time the loop was going to spend waiting -- the outer
                # cadence, and every confirm window sized against it, is untouched. Entered on the map screen
                # too: the budget there is one sub-tick, but opening the map is how a player leaves a room
                # FASTEST, which is when a chest pickup sitting in the Bag is most vulnerable.
                sleep_time = await fast_poll_window(ctx, sleep_time)
            else:
                if ctx.dolphin_status == DOLPHIN_READY:
                    logger.info("Lost Dolphin -- reconnecting...")
                ctx.dolphin_status = DOLPHIN_LOST
                ctx.block_base = None
                ctx.fst_guard.reset()
                ctx.block_stability.reset()
                ctx.block_trust.reset()
                # ADDENDUM 450: the attempt and the failure are said once per run of failures, then the retry is
                # silent (`/verbose` still shows each one) instead of spamming the log.
                if ctx._hook_failures == 0 and not ctx._dolphin_missing_logged:
                    logger.info("Attempting to connect to Dolphin...")
                else:
                    _note(ctx, "Attempting to connect to Dolphin...")
                if not ram_client.dolphin_available():
                    # A missing or broken native dolphin-memory-engine raised a raw traceback out of the import
                    # and made the whole apworld look broken. One message instead, at the retry cadence.
                    if not ctx._dolphin_missing_logged:
                        ctx._dolphin_missing_logged = True
                        logger.error(ram_client.DOLPHIN_MISSING_MESSAGE)
                    sleep_time = POLL_INTERVAL_RETRY
                    continue
                if ram_client.hook():
                    logger.info(DOLPHIN_READY)
                    ctx.dolphin_status = DOLPHIN_READY
                    ctx._hook_failures = 0
                else:
                    if ctx._hook_failures == 0:
                        logger.info("Connection to Dolphin failed -- is Dolphin running with Pokemon XD loaded? "
                                    "Retrying quietly every 5 seconds until it is.")
                    else:
                        _note(ctx, "Connection to Dolphin failed -- retrying in 5 seconds.")
                    # Said ONCE, after enough failures that "Dolphin isn't open yet" has stopped being likely: a
                    # hint on the first attempt fires every time the client starts before the emulator.
                    ctx._hook_failures += 1
                    if (ctx._hook_failures >= HOOK_FAILURES_BEFORE_OVERRIDE_HINT
                            and not ctx._override_hint_logged):
                        ctx._override_hint_logged = True
                        logger.warning(ram_client.DOLPHIN_MEMORY_OVERRIDE_HINT)
                    sleep_time = POLL_INTERVAL_RETRY
        except Exception as exc:
            # ADDENDUM 445: one line by default; the traceback is `/verbose` only.
            logger.warning(f"Lost the game for a moment ({type(exc).__name__}: {exc}) -- reconnecting.")
            _note(ctx, traceback.format_exc())
            ctx.dolphin_status = DOLPHIN_LOST
            ctx.block_base = None
            sleep_time = POLL_INTERVAL_RETRY
            continue


async def _run_client(connect: Optional[str], password: Optional[str], name: Optional[str]) -> None:
    ctx = PokemonXDContext(connect, password)
    # Not ctx.auth: self.auth is reset to None on every disconnect while self.username is not, so setting
    # username here lets a reconnect re-derive auth instead of getting stuck unauthenticated.
    ctx.username = name
    ctx.server_task = asyncio.create_task(server_loop(ctx), name="ServerLoop")
    if gui_enabled:
        ctx.run_gui()
    ctx.run_cli()
    await asyncio.sleep(1)
    ctx.dolphin_sync_task = asyncio.create_task(dolphin_sync_task(ctx), name="DolphinSync")
    await ctx.exit_event.wait()
    ctx.watcher_event.set()                 # wake the Dolphin loop so it sees the exit
    ctx.server_address = None
    await ctx.shutdown()
    if ctx.dolphin_sync_task:
        await ctx.dolphin_sync_task


def main(*args: str) -> None:
    Utils.init_logging("Pokemon XD Client")
    parser = get_base_parser()
    parser.add_argument("--name", default=None, help="Slot name to connect as (also your in-game trainer name).")
    options = parser.parse_args(args)

    import colorama

    colorama.init()
    try:
        asyncio.run(_run_client(options.connect, options.password, options.name))
    finally:
        colorama.deinit()
