"""
Pokemon XD: Gale of Darkness -- Archipelago client (2026-09-03).

Real, connectable CommonClient implementation -- closes the gap this project's docs have flagged since the
skeleton's inception as "no AP server/CommonClient integration." Built on top of `ram_client.py` (the
already live-validated Dolphin-memory-access layer: hooking, block-base resolution, Bag pocket read/write,
party/species detection, purification detection -- see that file's own module docstring for what's confirmed
live vs. best-effort) and `shadow_species.py` (the real, sourced Shadow Pokemon capture-location roster).
Mirrors `worlds/tww/TWWClient.py`'s overall shape (also a GameCube CommonClient), with one deliberate
structural difference explained below.

============================================================================================================
WHAT THIS CLIENT DOES AUTOMATICALLY, WITH NO ISO PATCH REQUIRED
============================================================================================================
  - "Catch - {species}" locations (386 of them): fires the moment a species is newly seen in the live party
    struct (the confirmed-live PARTY_BASE data source -- see ram_client.py). Per the player's own instruction
    (and per ram_client.py's PARTY_BASE docstring), this assumes the player opens the in-game Party/Status
    screen at least once after booting Dolphin -- PARTY_BASE reads all-zero until then (lazy
    initialization); this client cannot press that button for the player (see docs/setup_en.md).
  - "Purify N Shadow Pokemon" locations (32): fires on each newly-observed purification event
    (ram_client.PurificationCountTracker, built on the confirmed PARTY_RECAP_PURIFIED_FLAG_OFFSET signal).
  - "Shadow Capture - {trainer} ({species})" locations (83): ALSO fires off the very same species-detection
    signal as species-catch locations above -- see shadow_species.py's module docstring for why this is a
    safe, honest proxy for "the player just snagged/defeated this specific Shadow Pokemon" (every one of the
    83 shadow species is numerically distinct across the whole roster, and a snagged Shadow Pokemon lands in
    the party exactly like any other catch).

============================================================================================================
WHAT THIS CLIENT DOES NOT DO AUTOMATICALLY, AND WHY (the one deliberate, disclosed gap)
============================================================================================================
The ~67 "Overworld Items" (chest/box/NPC-gift) locations have NO known live-RAM or ISO-patch detection signal
in this project -- unlike species/purification, picking up a chest item doesn't touch any address this
project has confirmed. The verifiably-safe way to do this would be to patch each location's vanilla
item-table entry in the ISO to grant one watchable placeholder id (see `patch.py`'s module docstring for why
that ISO-side patch was investigated and NOT completed: the reference randomizer's own `ISO.cs.Encode()` is
an unimplemented stub, and guessing at GameCube FST/FSYS byte offsets against a real ISO without being able
to verify the result risks corrupting the player's disc image). Rather than ship nothing for this whole
category, or silently guess, this client exposes a manual `!checked <name>` command (see
PokemonXDCommandProcessor._cmd_checked) -- the player types (part of) the chest's location name right after
picking it up in-game, fuzzy-matched against the seed's real Overworld Item location list (`!remaining` shows
what's left). This is the single biggest documented "issue to solve" left in this build.

============================================================================================================
STRUCTURAL DIFFERENCE FROM TWWClient.py
============================================================================================================
TWW's ISO is patched by generation, and that patch embeds the connecting slot name at a fixed address
(SLOT_NAME_ADDR) so its client can auto-authenticate without the ISO itself ever changing hands unpatched.
This project deliberately does NOT patch the ISO at all (see patch.py) -- there is no such address to read.
This client instead relies on CommonContext's own default `server_auth()` behavior (username from `--name` /
an `archipelago://` connect URL / an interactive prompt), which is standard for the large majority of
non-ROM-patched AP clients and needs no override here. Once connected, the AP slot name (`ctx.auth`) is
reused as the `resolve_block_base()` search landmark under this project's established convention: setup
instructions tell the player to enter that same string as their in-game trainer name, and to open the
Party/Status screen once after booting (see docs/setup_en.md).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import traceback
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    import kvui

import Utils
from CommonClient import ClientCommandProcessor, CommonContext, get_base_parser, gui_enabled, logger, server_loop
from NetUtils import ClientStatus

from . import ram_client, shadow_species, species
from .items import ITEM_TABLE, get_item_name_to_id
from .locations import LOCATION_NAME_GROUPS, get_location_name_to_id

# Mirrors __init__.py's PokemonXDWorld.base_id. Duplicated here rather than importing PokemonXDWorld directly
# (which would need the full World/Options/AutoWorld stack) -- items.py/locations.py are already designed to
# be usable standalone with just a base id, exactly for this kind of caller. Keep in sync with __init__.py if
# that ever changes (it's an arbitrary constant with no reason to, per __init__.py's own comment on it).
BASE_ID = 3_820_000
ITEM_NAME_TO_ID = get_item_name_to_id(BASE_ID)
ITEM_ID_TO_NAME = {v: k for k, v in ITEM_NAME_TO_ID.items()}
LOCATION_NAME_TO_ID = get_location_name_to_id(BASE_ID)

CONNECTION_INITIAL_STATUS = "Dolphin connection has not been initiated."
CONNECTION_LOST_STATUS = "Dolphin connection was lost. Please restart Dolphin with Pokemon XD loaded."
CONNECTION_REFUSED_GAME_STATUS = (
    "Dolphin is not running Pokemon XD: Gale of Darkness (USA). Please load it. Retrying in 5 seconds..."
)
CONNECTION_REFUSED_SAVE_STATUS = (
    "Connected to Dolphin, but couldn't find your save data yet. Make sure you're in-game (not on a menu), "
    "your in-game trainer name matches your Archipelago slot name exactly, and you've opened the "
    "Party/Status screen at least once this boot. Retrying in 5 seconds..."
)
CONNECTION_CONNECTED_STATUS = "Dolphin connected successfully."

# Confirmed via this project's own ISO extraction (iso_filelist.json: game_code == "GXXE") -- see
# ram_client.py's module docstring / pokemon-xd-ram-map.md.
XD_GAME_CODE = b"GXXE"

POLL_INTERVAL_INGAME = 1.0  # seconds between memory polls while hooked, resolved, and in-game
POLL_INTERVAL_RETRY = 5.0   # seconds before retrying a failed hook / block-base resolution


def _normalize_for_match(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


class PokemonXDCommandProcessor(ClientCommandProcessor):
    """Command processor for Pokemon XD client commands."""

    def _cmd_dolphin(self) -> None:
        """Display the current Dolphin emulator connection status."""
        if isinstance(self.ctx, PokemonXDContext):
            logger.info(f"Dolphin status: {self.ctx.dolphin_status}")

    def _cmd_checked(self, *name_words: str) -> None:
        """Manually mark an Overworld Item (chest/box/NPC-gift) location as checked -- use this right after
        picking up the item in-game, since this category has no automatic detection yet (see Client.py's
        module docstring for why). Fuzzy-matches your words against this seed's real Overworld Item location
        names, e.g. '!checked phenac shop ledge'. Species catches, Shadow captures, and purification
        thresholds are all detected automatically and never need this command."""
        if not isinstance(self.ctx, PokemonXDContext):
            return
        self.ctx.queue_manual_check(" ".join(name_words))

    def _cmd_remaining(self) -> None:
        """List this seed's Overworld Item (chest/box/NPC-gift) locations that haven't been checked yet --
        the ones '!checked' can mark."""
        if not isinstance(self.ctx, PokemonXDContext):
            return
        self.ctx.print_remaining_manual_checks()

    def _cmd_goal(self) -> None:
        """Declare the game complete (you've defeated the Cipher Boss at Citadark Isle) -- there's no known
        live-RAM signal for this event, so like the Overworld Item chests, it's reported manually rather than
        guessed at. Only use this after actually beating him."""
        if not isinstance(self.ctx, PokemonXDContext):
            return
        Utils.async_start(self.ctx.declare_goal_complete())


class PokemonXDContext(CommonContext):
    """The context for the Pokemon XD: Gale of Darkness client."""

    command_processor = PokemonXDCommandProcessor
    game = "Pokemon XD Gale of Darkness"
    items_handling = 0b111  # receive items from everywhere, matching every other simple GameCube client

    def __init__(self, server_address: Optional[str], password: Optional[str]) -> None:
        super().__init__(server_address, password)
        self.dolphin_sync_task: Optional["asyncio.Task[None]"] = None
        self.dolphin_status: str = CONNECTION_INITIAL_STATUS

        # Resolved once per Dolphin boot (see ram_client.resolve_block_base) and cached -- None means "not
        # yet resolved this connection," not "known to not exist."
        self.block_base: Optional[int] = None

        # Species newly seen this session (party + optionally PC box, see ram_client.get_owned_species_snapshot)
        # -- tracked directly here (rather than via ram_client.SpeciesTracker) so both the "Catch - X" AND the
        # matching "Shadow Capture - ..." location (if any) can be derived from the same raw dex number in one
        # place. See the module docstring's automatic-detection section.
        self.seen_dex_numbers: set[int] = set()
        self.purification_tracker = ram_client.PurificationCountTracker()

        # From this seed's slot_data (see __init__.py's fill_slot_data) -- which location categories actually
        # exist for this player, so manual checks / automatic sends never reference a location id the server
        # doesn't have for this slot.
        self.shuffle_overworld_items: bool = True
        self.shuffle_shadow_captures: bool = True
        self.include_traps: bool = False

        self._manual_check_queue: list[str] = []
        self._overworld_location_names: list[str] = []

        # See give_items() below -- no ISO/save field exists to store "how many received items has the
        # player already been given," so this is tracked client-side, persisted locally keyed by seed+slot
        # (same category of design as every other non-ROM-patched AP client's local state).
        self.expected_item_index: int = 0
        self._local_state_loaded_for: Optional[str] = None

    async def server_auth(self, password_requested: bool = False):
        await super().server_auth(password_requested)
        await self.get_username()
        await self.send_connect()

    async def disconnect(self, allow_autoreconnect: bool = False) -> None:
        self.block_base = None
        await super().disconnect(allow_autoreconnect)

    def on_package(self, cmd: str, args: dict[str, Any]) -> None:
        if cmd == "Connected":
            slot_data = args.get("slot_data") or {}
            self.shuffle_overworld_items = bool(slot_data.get("shuffle_overworld_items", True))
            self.shuffle_shadow_captures = bool(slot_data.get("shuffle_shadow_captures", True))
            self.include_traps = bool(slot_data.get("include_traps", False))
            self._overworld_location_names = sorted(
                LOCATION_NAME_GROUPS["Overworld Items"] if self.shuffle_overworld_items else []
            )
            self._load_local_state()

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
        logger.info("Declared the game complete -- goal sent to the server.")

    # --------------------------------------------------------------------------------------------------
    # Manual "!checked" handling for Overworld Item locations -- see module docstring.
    # --------------------------------------------------------------------------------------------------

    def queue_manual_check(self, text: str) -> None:
        if not text.strip():
            logger.info("Usage: !checked <part of the chest/item location's name> (see !remaining for the list)")
            return
        if not self.shuffle_overworld_items:
            logger.info("This seed doesn't have Overworld Items shuffled -- nothing to manually check.")
            return
        match = self._fuzzy_match_overworld_location(text)
        if match is None:
            logger.info(f"No unchecked Overworld Item location matches {text!r} -- try !remaining for the list.")
            return
        self._manual_check_queue.append(match)
        logger.info(f"Queued check: {match}")

    def _fuzzy_match_overworld_location(self, text: str) -> Optional[str]:
        needle = _normalize_for_match(text)
        if not needle:
            return None
        remaining = self._remaining_overworld_locations()
        # Prefer an exact normalized match, then fall back to substring matches (only if exactly one candidate
        # -- an ambiguous partial match is refused rather than guessing which chest the player means).
        for name in remaining:
            if _normalize_for_match(name) == needle:
                return name
        candidates = [name for name in remaining if needle in _normalize_for_match(name)]
        if len(candidates) == 1:
            return candidates[0]
        if len(candidates) > 1:
            logger.info(f"{text!r} matches more than one location, be more specific: {', '.join(candidates[:8])}")
        return None

    def _remaining_overworld_locations(self) -> list[str]:
        checked_ids = self.checked_locations | set(self.locations_checked) | set(self._manual_check_queue_ids())
        return [
            name for name in self._overworld_location_names
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

    # --------------------------------------------------------------------------------------------------
    # Local state persistence (expected received-item index) -- see __init__'s comment on why this is
    # client-side rather than in-save.
    # --------------------------------------------------------------------------------------------------

    def _state_file_path(self) -> str:
        return Utils.cache_path("pokemon_xd_client_state.json")

    def _state_key(self) -> str:
        return f"{self.seed_name}:{self.slot}"

    def _load_local_state(self) -> None:
        key = self._state_key()
        if self._local_state_loaded_for == key:
            return
        self._local_state_loaded_for = key
        self.expected_item_index = 0
        path = self._state_file_path()
        try:
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as f:
                    all_state = json.load(f)
                self.expected_item_index = int(all_state.get(key, {}).get("expected_item_index", 0))
        except (OSError, ValueError, TypeError):
            logger.warning(f"Couldn't read local client state from {path} -- starting fresh for this seed/slot.")

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
        all_state[key] = {"expected_item_index": self.expected_item_index}
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(all_state, f)
        except OSError:
            logger.warning(f"Couldn't persist local client state to {path} -- progress on receiving items "
                            "may replay from an earlier point next time the client starts.")


# ----------------------------------------------------------------------------------------------------------
# Trap handling -- the one AP-only item with no real Bag id (see items.py's TRAP_ITEMS / ram_client.py's
# route_and_give_item, which returns None for it). Uses only the already-confirmed-safe money read/write
# (ram_client.read_money/write_money) rather than guessing at any new memory location.
# ----------------------------------------------------------------------------------------------------------

TRAP_ITEM_NAMES = {"Itemfinder Malfunction Trap"}


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


# ----------------------------------------------------------------------------------------------------------
# Receiving items
# ----------------------------------------------------------------------------------------------------------

async def give_items(ctx: PokemonXDContext) -> None:
    if ctx.block_base is None:
        return
    received = ctx.items_received
    if len(received) <= ctx.expected_item_index:
        return
    for idx in range(ctx.expected_item_index, len(received)):
        network_item = received[idx]
        item_name = ITEM_ID_TO_NAME.get(network_item.item, f"Unknown Item {network_item.item}")
        if item_name in TRAP_ITEM_NAMES:
            _apply_trap_effect(ctx, item_name)
        else:
            data = ITEM_TABLE.get(item_name)
            game_item_id = data.game_item_id if data is not None else None
            result = ram_client.route_and_give_item(ctx.block_base, game_item_id, 1)
            if result is None:
                logger.info(f"Received {item_name} -- no real in-game item id is known for this one yet "
                            "(see items.py); nothing was written, but it's marked received.")
            elif result is False:
                logger.warning(f"Received {item_name} but its Bag pocket is full -- will retry next poll.")
                return  # stop here, don't advance expected_item_index past this item
            else:
                logger.info(f"Received {item_name}.")
        ctx.expected_item_index = idx + 1
        ctx._save_local_state()


# ----------------------------------------------------------------------------------------------------------
# Detecting checks
# ----------------------------------------------------------------------------------------------------------

async def check_species_and_shadow_captures(ctx: PokemonXDContext) -> None:
    if ctx.block_base is None:
        return
    current = ram_client.get_owned_species_snapshot(ctx.block_base, ram_client.PARTY_BASE)
    newly_seen = current - ctx.seen_dex_numbers
    if not newly_seen:
        return
    ctx.seen_dex_numbers |= newly_seen
    location_names: list[str] = []
    for dex_number in sorted(newly_seen):
        location_names.append(species.location_name_for_species(dex_number))
        if ctx.shuffle_shadow_captures:
            shadow_name = shadow_species.shadow_capture_location_for_dex(dex_number)
            if shadow_name is not None:
                location_names.append(shadow_name)
    await _send_checks(ctx, location_names)


async def check_purifications(ctx: PokemonXDContext) -> None:
    if ctx.block_base is None:
        return
    newly_crossed = ctx.purification_tracker.poll(ctx.block_base, ram_client.PARTY_BASE)
    if newly_crossed:
        await _send_checks(ctx, newly_crossed)


async def check_manual_queue(ctx: PokemonXDContext) -> None:
    if not ctx._manual_check_queue:
        return
    pending, ctx._manual_check_queue = ctx._manual_check_queue, []
    await _send_checks(ctx, pending)


async def _send_checks(ctx: PokemonXDContext, location_names: list[str]) -> None:
    ids = {LOCATION_NAME_TO_ID[name] for name in location_names if name in LOCATION_NAME_TO_ID}
    if ids:
        await ctx.check_locations(ids)


# ----------------------------------------------------------------------------------------------------------
# Main Dolphin sync loop -- mirrors worlds/tww/TWWClient.py's dolphin_sync_task structure.
# ----------------------------------------------------------------------------------------------------------

def _looks_ingame() -> bool:
    """Cheap in-game check: is party slot 0's species field non-zero yet? See ram_client.py's PARTY_BASE
    docstring on lazy initialization -- an all-zero read there means either "not in-game yet" or "in-game but
    hasn't opened Party/Status yet," and either way there's nothing useful to poll until it populates."""
    try:
        addr = ram_client.PARTY_BASE + ram_client.PARTY_SPECIES_OFFSET
        return ram_client.read_bytes(addr, 2) != b"\x00\x00"
    except Exception:
        return False


async def dolphin_sync_task(ctx: PokemonXDContext) -> None:
    logger.info("Starting Dolphin connector. Use !dolphin for status information.")
    sleep_time = 0.0
    while not ctx.exit_event.is_set():
        if sleep_time > 0.0:
            try:
                await asyncio.wait_for(ctx.watcher_event.wait(), sleep_time)
            except asyncio.TimeoutError:
                pass
            sleep_time = 0.0
        ctx.watcher_event.clear()

        try:
            if ram_client.is_hooked() and ctx.dolphin_status == CONNECTION_CONNECTED_STATUS:
                if ram_client.read_bytes(ram_client.MEM1_START, 4) != XD_GAME_CODE:
                    logger.info(CONNECTION_REFUSED_GAME_STATUS)
                    ctx.dolphin_status = CONNECTION_REFUSED_GAME_STATUS
                    ctx.block_base = None
                    sleep_time = POLL_INTERVAL_RETRY
                    continue

                if ctx.block_base is None:
                    landmark = ctx.auth or ctx.username
                    if not landmark:
                        # Not authenticated to the server yet -- nothing to search for. Let server_auth() (the
                        # default CommonContext one, see module docstring) run its course.
                        sleep_time = POLL_INTERVAL_RETRY
                        continue
                    ctx.block_base = ram_client.resolve_block_base(landmark)
                    if ctx.block_base is None:
                        logger.info(CONNECTION_REFUSED_SAVE_STATUS)
                        sleep_time = POLL_INTERVAL_RETRY
                        continue
                    logger.info(f"Resolved Pokemon XD save data (block base {hex(ctx.block_base)}).")

                if not _looks_ingame():
                    sleep_time = POLL_INTERVAL_INGAME
                    continue

                if ctx.slot is not None:
                    await give_items(ctx)
                    await check_species_and_shadow_captures(ctx)
                    await check_purifications(ctx)
                    await check_manual_queue(ctx)
                sleep_time = POLL_INTERVAL_INGAME
            else:
                if ctx.dolphin_status == CONNECTION_CONNECTED_STATUS:
                    logger.info("Connection to Dolphin lost, reconnecting...")
                ctx.dolphin_status = CONNECTION_LOST_STATUS
                ctx.block_base = None
                logger.info("Attempting to connect to Dolphin...")
                if ram_client.hook():
                    logger.info(CONNECTION_CONNECTED_STATUS)
                    ctx.dolphin_status = CONNECTION_CONNECTED_STATUS
                else:
                    logger.info("Connection to Dolphin failed -- is Dolphin running with Pokemon XD loaded? "
                                 "Retrying in 5 seconds...")
                    sleep_time = POLL_INTERVAL_RETRY
        except Exception:
            logger.error(traceback.format_exc())
            ctx.dolphin_status = CONNECTION_LOST_STATUS
            ctx.block_base = None
            sleep_time = POLL_INTERVAL_RETRY
            continue


def main(*args: str) -> None:
    Utils.init_logging("Pokemon XD Client")

    async def _main(connect: Optional[str], password: Optional[str], name: Optional[str]) -> None:
        ctx = PokemonXDContext(connect, password)
        # Not ctx.auth directly -- CommonContext's default server_auth() falls back to self.username, and
        # self.auth (unlike self.username) gets reset to None on every disconnect, so setting username here
        # means a reconnect re-derives auth from it automatically instead of getting stuck unauthenticated.
        ctx.username = name
        ctx.server_task = asyncio.create_task(server_loop(ctx), name="ServerLoop")
        if gui_enabled:
            ctx.run_gui()
        ctx.run_cli()
        await asyncio.sleep(1)

        ctx.dolphin_sync_task = asyncio.create_task(dolphin_sync_task(ctx), name="DolphinSync")

        await ctx.exit_event.wait()
        ctx.watcher_event.set()
        ctx.server_address = None

        await ctx.shutdown()

        if ctx.dolphin_sync_task:
            await ctx.dolphin_sync_task

    parser = get_base_parser()
    parser.add_argument("--name", default=None, help="Slot name to connect as (also your in-game trainer name).")
    parsed_args = parser.parse_args(args)

    import colorama

    colorama.init()
    asyncio.run(_main(parsed_args.connect, parsed_args.password, parsed_args.name))
    colorama.deinit()
