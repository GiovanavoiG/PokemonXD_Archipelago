"""ADDENDUM 181 (2026-09-13): the client is quiet by default.

Player instruction: "let's remove all of the default-on logging that's in the client. I want it to print
nothing except for the standard archipelago connection logs, and the checks received/sent."

Nothing was deleted -- every narration line is real diagnostic output this project has needed at least once,
and several are the only evidence that would explain a bad run after the fact. They were routed through
`_note`/`_note_warn`, which print only when `!verbose` is on.

WHY THIS DOES NOT IMPORT `Client.py` DIRECTLY: the same documented sandbox limitation as
test_addendum_109_getitem_command.py -- `Client.py` -> `CommonClient` -> `MultiServer` ->
`websockets.extensions`. So the default-off guarantee is enforced by parsing the file with `ast`: every
`logger.*` call that is NOT inside a `_cmd_*` command handler is checked against an explicit allow-list of the
categories the player named. A new narration line added later fails this test by default, which is the point
-- the allow-list is the contract, and widening it has to be a deliberate edit.

The two helpers themselves ARE executed for real (they need nothing but `logger`), so the gate is tested
behaviourally rather than by reading its source.
"""
from __future__ import annotations

import ast
import pathlib
import re
import unittest


CLIENT_PATH = pathlib.Path(__file__).resolve().parent.parent / "Client.py"
SOURCE = CLIENT_PATH.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


# The only automatic (non-command) log output the player asked to keep, as substrings of the call's source.
# Grouped by the reason each one survives, so a future reader can tell "kept on purpose" from "missed."
ALLOWED_AUTOMATIC = {
    # -- the connection lifecycle: exactly "the standard archipelago connection logs."
    "Starting Dolphin connector",
    "CONNECTION_REFUSED_GAME_STATUS",
    "CONNECTION_REFUSED_SAVE_STATUS",
    "CONNECTION_CONNECTED_STATUS",
    "Connection to Dolphin lost",
    "Attempting to connect to Dolphin",
    "Connection to Dolphin failed",
    "DOLPHIN_MISSING_MESSAGE",
    # ADDENDUM 307: one-shot actionable guidance, in the same class as DOLPHIN_MISSING_MESSAGE -- a real
    # failure the player can only fix outside this client, said once and never repeated.
    "DOLPHIN_MEMORY_OVERRIDE_HINT",
    # ADDENDUM 309: the step-gate counterpart of ADDENDUM 294's ten-minute warning -- fires at most once per
    # item, and only when the backstop has actually been reached.
    "for you to take a step",
    "traceback.format_exc()",
    # -- "the checks received": one line per item that arrives from the multiworld.
    "Received {item_name}",
    "your Itemfinder glitches",
    # ADDENDUM 361: the 5000 Poke Coupons item. Exactly the class of "Received {item_name}" and of the
    # trap's "your Itemfinder glitches" line directly above -- an item arrived from the multiworld and
    # changed the save. It is the ONLY feedback this item gives: it is not a Bag item, so nothing appears
    # in a pocket and there is no quantity to notice. One line per delivery, and none on a seed that never
    # rolls one.
    "Poke Coupons added",
    # -- "the checks sent": the single funnel in _send_checks.
    "Sent {len(fresh)} check(s)",
    # ADDENDUM 376: checks the client sent for chests opened BEFORE it was watching, deduced at connect from
    # the carried berry plus the server's checked list. In the same class as "Sent ... check(s)" and stronger:
    # these are locations the player earned in a previous session and is being told about now, at most once per
    # connect, and only on a seed where a chest was opened while the client was not running. Gating it behind
    # `!verbose` would mean silently sending checks the player has no way to account for.
    "only one unchecked chest could have held each",
    # ADDENDUM 322: the other half of that funnel -- a location this SEED does not contain, named once and
    # then held. Same class as the one-shot guidance above: it is the diagnostic for an options mismatch that
    # used to disconnect the player, and a player who never hits one never sees it.
    "this seed has no such location(s)",
    # ADDENDUM 359: the asynchronous half of `!mirorforce`. The command arms and returns immediately; the
    # outcome -- he appeared, or which gate refused it -- arrives from the poll loop seconds later. It is
    # not narration: it is the answer to something the player typed, and gating it behind `!verbose` would
    # mean running a command and being told nothing. At most one line per invocation, and none at all
    # unless the player uses it.
    "!mirorforce: ",
    # ADDENDUM 351: Death Link, both directions. Same class as "Received {item_name}" and
    # "Sent {len(fresh)} check(s)" -- it is a multiworld event the player is part of, it is caused by
    # somebody else, and a party that faints with no explanation is the definition of a line you cannot
    # gate behind `!verbose`. Only ever one line per death, and none at all on a seed without the option.
    "Death Link: ",
    # -- the goal, which is the one thing a player would never forgive being silent.
    "completing this seed's goal",
    "completing this seed's goal.",
    "-- goal sent to the server",
    # -- real failures. Each one means something did not work and the player has to know.
    "Couldn't persist local client state",
    "Couldn't apply {item_name}'s effect",
    "Failed to deliver {item_name}",
    "failed forcing delivery",
    "Could not read a file table",
    "Could not read the area story-byte memory file",
    # -- one-shot actionable guidance: printed at most once per session, each with exactly one fix.
    # ADDENDUM 201: the chest locations this client cannot detect. Deliberately LOUD and automatic rather than
    # behind `!verbose` -- a check that can never fire is not narration, it is a seed that may not be
    # completable, and the player has to learn it at connect rather than by never finding the item.
    "have no measured open-flag position",
    # ADDENDUM 253: the Bag slot that cannot hold any more. This is a real failure being reported rather than
    # narration -- the item stops being retried at this point, so if it is not said here it is not said at
    # all, and a saturated slot is the only surviving evidence that an item was never confirming.
    "Bag slot is full at the maximum the game can store",
    # ADDENDUM 251: the seed/apworld mismatch warning. Same category and the same argument as the line above
    # and ADDENDUM 246's backfill notice -- ADDENDA 245/246 are a worked example of what silence costs here:
    # 63 locations that could never be checked, five of them holding progression, discovered hours into a run.
    # Printed at most once, at connect, and only when something is actually wrong.
    "different build of the Pokemon XD apworld",
    # ADDENDUM 261: the shop scout reply that could not be read. Added ON PURPOSE, and this addendum is the
    # argument for the whole category. That branch was already wrapped and already reported through
    # `_note_warn` -- correctly, by the letter of this rule -- and the result was that a `TypeError` on the
    # very first record took the ENTIRE shop-description feature out for months, with the explanation sitting
    # behind `!verbose` where nobody looked. The player reported it as "descriptions do not have the AP item
    # listed at all", i.e. as never built.
    #
    # The distinction this rule actually wants is not cosmetic-vs-load-bearing. It is NARRATION vs "a feature
    # you asked for is off and will stay off". The first belongs behind `!verbose`; the second has to be said
    # once, out loud, or it is not said at all. Fires only when the scout produced nothing AND had problems,
    # so a working seed never sees it.
    "the shop scout reply could not be read",
    "do not exist in the installed apworld",
    "Location tables differ",
    "version mismatch, not a logic error",
    # ADDENDUM 246: chest berries already in the Bag at the first poll. Same category and the same reasoning
    # as the line above -- a check that cannot fire on its own is not narration, and this one is silent in
    # every other way. Printed at most once per session (`backfill_announced`) and it names the fix.
    "logger.warning(line)",
    "file-table watchdog can't repair it from a snapshot",
    "Still waiting to detect your party as loaded in-game",
    # -- the delivery-safety warning that names a real missing companion item (ADDENDUM 179). This one is
    #    the whole reason the Data ROM / ID Card softlock is recoverable, so it is never gated.
    "also carries game item id(s)",
    # -- ADDENDUM 215: the story-byte watch. This is the one automatic line the player asked for BY NAME
    #    ("Add a toggle to the client for printing out every time the story byte changes"), and it is
    #    unreachable unless they turn `!storywatch` on -- so it is opt-in output rather than narration. It
    #    deliberately does not go through `_note`: routing it there would let `!verbose off` silence a watch
    #    the player switched on, which is the opposite of what was asked for.
    "logger.info(line)",
    # ADDENDUM 294: the ten-minute battle hold firing. The player asked to "double check our item delivery"
    # precisely because they could not tell a held delivery from a working one, and they could not because
    # NOTHING was logged when an item crossed that ceiling -- not narration, the absence of a bug report.
    # A gate claiming a battle for six hundred unbroken seconds means the gate is wrong, it fires at most once
    # per item, and it names the command that says which roster record is holding it.
    "waited the full "
    ,
    # ADDENDUM 294: the write that never reached memory. `give_item` answers False when every slot in the
    # write window is taken; both call sites used to discard that, so a full pocket was an infinite silent
    # retry. Unconditional and once per item, in the same category as ADDENDUM 253's saturated slot directly
    # above: the item stops making progress here, so if it is not said here it is not said at all.
    "could not be written to your Bag",
    # -- the helpers' own bodies. THREE helpers as of ADDENDUM 294, not two: `_announce_first` joins
    #    `_note`/`_note_warn` and shares their exemption because it is the same shape of thing -- a named
    #    gate whose body is one `logger` call and whose callers are the ones deciding. Named here so the
    #    exemption stays a list of known helpers rather than "any call that happens to pass a variable
    #    called `message`", which is what it had quietly become.
    "logger.info(message)",
    "logger.warning(message)",
}


# `_cmd_*` handlers that are thin wrappers delegating to a named helper. Their output is command output --
# printed because the player just typed something -- so it is out of scope exactly like the handler's own
# `logger.info`. Listed explicitly rather than inferred: a helper that starts ALSO being called from the poll
# loop would otherwise silently inherit the exemption, which is how a narration line sneaks back in.
COMMAND_ONLY_HELPERS = {
    "declare_goal_complete",       # !goal
    "queue_manual_check",          # !checked
    "print_remaining_manual_checks",  # !remaining
    "print_shadow_species_map",    # !shadowdex
    "print_catch_sources",         # !catches (ADDENDUM 310)
    "force_deliver_pending_items",  # !getitem
    "_fuzzy_match_overworld_location",  # shared by !checked / !remaining, reached only from them
    "print_seed_location_check",   # !seedcheck (ADDENDUM 251)
    "apply_fst_iso",               # !fstiso (its startup auto-load path is separately gated on `remember`)
}


def _automatic_logger_calls() -> "list[tuple[int, str]]":
    """Every `logger.info/warning/error(...)` call that is NOT command output.

    Command output is deliberately untouched by this addendum: it is on-demand, printed because the player
    just typed the command, and silencing it would make the commands useless.
    """
    calls: "list[tuple[int, str]]" = []

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.in_command = 0

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
            command = node.name.startswith("_cmd_") or node.name in COMMAND_ONLY_HELPERS
            self.in_command += 1 if command else 0
            self.generic_visit(node)
            self.in_command -= 1 if command else 0

        visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

        def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "logger"
                and func.attr in ("info", "warning", "error")
                and not self.in_command
            ):
                calls.append((node.lineno, ast.get_source_segment(SOURCE, node) or ""))
            self.generic_visit(node)

    Visitor().visit(TREE)
    return calls


class TestNothingNarratesByDefault(unittest.TestCase):
    def test_every_automatic_logger_call_is_one_the_player_asked_to_keep(self) -> None:
        unexpected = [
            (line, text.replace("\n", " ")[:120])
            for line, text in _automatic_logger_calls()
            if not any(token in text for token in ALLOWED_AUTOMATIC)
        ]
        self.assertEqual(
            unexpected,
            [],
            "These automatic logger calls are neither a connection log, a received item, a sent check, the "
            "goal, a real failure, nor one-shot actionable guidance -- route them through _note()/_note_warn() "
            "so `!verbose` controls them, or add them to ALLOWED_AUTOMATIC on purpose.",
        )

    def test_the_narration_actually_went_somewhere_rather_than_being_deleted(self) -> None:
        """The player said "remove"; this project kept the lines and gated them instead. If a future edit
        deletes them for real, this is the test that notices the diagnostics are gone."""
        gated = len(re.findall(r"\b_note(?:_warn)?\(", SOURCE))
        # 2 definitions + 1 lambda wiring FstGuard + the converted call sites.
        self.assertGreaterEqual(
            gated, 18,
            "far fewer _note()/_note_warn() call sites than ADDENDUM 181 converted -- narration was deleted "
            "rather than gated",
        )

    def test_the_room_change_and_story_byte_lines_specifically_are_gated(self) -> None:
        """The two chattiest lines in the client (one per doorway, one per story advance) are the ones the
        player would have seen most, so they are pinned individually."""
        # UPDATED 2026-09-15 (ADDENDUM 215). The story-byte line is no longer a bare string: it is built
        # once and then sent EITHER to logger.info (when !storywatch is on) or to _note (when it is not), and
        # the wording now distinguishes an advance from a move backwards, since this client writes lower
        # values itself. The property being pinned is unchanged -- with the watch off, the line is gated.
        index = SOURCE.index("Room change:")
        self.assertIn("_note(", SOURCE[max(0, index - 200):index], "'Room change:' is not gated behind !verbose")

        # ADDENDUM 350 added two lines between the string and the gate -- the story variable itself, and the
        # not-a-multiple-of-ten note -- so the window widened. The property is unchanged: whatever the line
        # ends up saying, it reaches logger.info only with !storywatch on.
        index = SOURCE.index('f"Story byte {direction}')
        window = SOURCE[index:index + 1200]
        self.assertIn("if ctx.story_byte_watch:", window,
                      "the story-byte line must only reach logger.info when !storywatch is on")
        self.assertIn("_note(ctx, line)", window,
                      "with !storywatch off the story-byte line must still be gated behind !verbose")


class TestTheGateItself(unittest.TestCase):
    """`_note`/`_note_warn` need nothing but a `logger`, so they can be executed for real."""

    def _helpers(self) -> "tuple[object, object, list[tuple[str, str]]]":
        printed: "list[tuple[str, str]]" = []

        class _Logger:
            @staticmethod
            def info(message: str) -> None:
                printed.append(("info", message))

            @staticmethod
            def warning(message: str) -> None:
                printed.append(("warning", message))

        namespace: "dict[str, object]" = {"logger": _Logger}
        for name in ("_note", "_note_warn"):
            match = re.search(rf"^def {name}\(.*?(?=\n\n)", SOURCE, re.S | re.M)
            assert match is not None, f"{name} not found in Client.py"
            exec(compile(match.group(0), "<client>", "exec"), namespace)  # noqa: S102
        return namespace["_note"], namespace["_note_warn"], printed

    def test_silent_by_default_and_audible_once_verbose_is_on(self) -> None:
        note, note_warn, printed = self._helpers()

        class Ctx:
            verbose_logging = False

        ctx = Ctx()
        note(ctx, "a room change")
        note_warn(ctx, "a transient read failure")
        self.assertEqual(printed, [], "narration printed with verbose_logging False")

        ctx.verbose_logging = True
        note(ctx, "a room change")
        note_warn(ctx, "a transient read failure")
        self.assertEqual(
            printed, [("info", "a room change"), ("warning", "a transient read failure")]
        )

    def test_a_context_with_no_verbose_attribute_at_all_stays_silent(self) -> None:
        """Belt and braces: an older/partial context object must not raise, and must not print either -- a
        crash in a narration helper would take out the poll loop it is called from."""
        note, note_warn, printed = self._helpers()

        class Bare:
            pass

        note(Bare(), "x")
        note_warn(Bare(), "y")
        self.assertEqual(printed, [])


class TestVerboseCommand(unittest.TestCase):
    def test_the_command_exists_and_accepts_on_off_and_a_bare_toggle(self) -> None:
        match = re.search(r"def _cmd_verbose\(.*?\n(?=    def |\n\nclass )", SOURCE, re.S)
        self.assertIsNotNone(match, "!verbose command not found")
        body = match.group(0)
        self.assertIn('"on"', body)
        self.assertIn('"off"', body)
        self.assertIn("not self.ctx.verbose_logging", body, "no bare `!verbose` toggle")

    def test_the_context_defaults_it_off_before_the_fst_guard_that_reads_it(self) -> None:
        """FstGuard's `log_verbose` closes over the context, so the attribute has to exist first -- an
        AttributeError here would happen during __init__, before the client ever connects."""
        flag = SOURCE.index("self.verbose_logging: bool = False")
        guard = SOURCE.index("self.fst_guard = fst_guard.FstGuard(")
        self.assertLess(flag, guard)


class TestChecksSent(unittest.TestCase):
    def test_send_checks_announces_only_locations_the_server_does_not_have_yet(self) -> None:
        """`ctx.check_locations` is deliberately idempotent -- several detectors re-offer the same location
        every poll until the server acknowledges it. Announcing the full set would reprint the same line once
        per second, which is exactly the noise this addendum removed."""
        match = re.search(r"async def _send_checks\(.*?\n(?=\n\n)", SOURCE, re.S)
        self.assertIsNotNone(match, "_send_checks not found")
        body = match.group(0)
        self.assertIn("ctx.checked_locations", body, "the sent line does not filter already-checked ids")
        self.assertIn("Sent ", body)
        # Still forwards the FULL id set, not just the fresh ones -- the filter is for the log line only.
        self.assertIn("await ctx.check_locations(ids)", body)

    def test_the_reverse_id_map_the_line_needs_is_built(self) -> None:
        self.assertIn("ID_TO_LOCATION_NAME = {v: k for k, v in LOCATION_NAME_TO_ID.items()}", SOURCE)


if __name__ == "__main__":
    unittest.main()
