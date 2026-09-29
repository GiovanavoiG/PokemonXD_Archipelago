"""
Launcher integration for the ISO-patch step.

generate_output() only produces a small `.appxd` seed file, never a full ISO or a diff against one (patch.py
says why). This wires tools/iso_patcher.py into the Launcher's "open a patch file" flow, so opening a `.appxd`
-- double-click, drag-and-drop, "Open Patch", or the "Pokemon XD Client" component __init__.py registers via
launch_client_or_patch -- walks the player through picking their own ISO and produces a patched COPY. The
source ISO is never opened write-capable; apply_patch() enforces that. All byte-level work stays in
tools/iso_patcher.py.

`Utils.open_filename`/`save_filename` each create and tear down their own `tkinter.Tk()` root per call where
kdialog/zenity is unavailable, and back-to-back calls -- what `prompt_and_patch` does -- hang on Windows when
the first dialog was dismissed by double-click: the new root's message pump waits on dispatch state the
destroyed root left behind. `_run_dialog_chain` uses one persistent hidden root and pumps it (`root.update()`)
between dialogs. Linux keeps using Utils where a native dialog tool exists; those are subprocesses.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

_TOOLS_DIR = str(Path(__file__).resolve().parent / "tools")
_ISO_PATCHER_SCRIPT = str(Path(__file__).resolve().parent / "tools" / "iso_patcher.py")

# Set by `_ensure_visible_console()`, consumed and cleared by `_release_console()`. Holds the process's real
# stdout/stderr/stdin from BEFORE the redirection so they can be put back exactly.
_console_state: dict = {}


def _ensure_visible_console() -> bool:
    """Attach a visible Windows console to this process via `AllocConsole()` and point `sys.stdout`/`stderr`
    at it, so apply_patch()'s print() progress becomes visible. No subprocess, so no external Python has to
    resolve for the window to appear.

    Returns True only when it ALLOCATED the console here. One the process already had (a dev terminal) is
    somebody else's: not redirected, not prompted at, not freed, and `_release_console()` must only run
    against one this allocated. `_has_console()` answers "is there a console at all"."""
    import ctypes
    from ctypes import wintypes

    # ctypes assumes a 32-bit c_int return for any function it has not been told about, which truncates a
    # 64-bit HWND from GetConsoleWindow. Declare the real WinAPI types.
    kernel32 = ctypes.windll.kernel32
    kernel32.GetConsoleWindow.restype = wintypes.HWND
    kernel32.AllocConsole.restype = wintypes.BOOL
    kernel32.SetConsoleTitleW.argtypes = [wintypes.LPCWSTR]
    kernel32.SetConsoleTitleW.restype = wintypes.BOOL

    if kernel32.GetConsoleWindow():
        return False  # already has one (e.g. a dev terminal) -- not ours to redirect, prompt at, or free

    if not kernel32.AllocConsole():
        return False

    kernel32.SetConsoleTitleW("Pokemon XD Patch - Progress")
    # Saved before anything is replaced. Either may legitimately be None in a frozen, GUI-launched Launcher;
    # None is what gets restored then, and print() against a None sys.stdout is a documented no-op.
    _console_state["stdout"] = sys.stdout
    _console_state["stderr"] = sys.stderr
    _console_state["stdin"] = sys.stdin
    sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)  # noqa: SIM115
    sys.stderr = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)  # noqa: SIM115
    # CONIN$ too: the console ends on a "press Enter" prompt and `input()` reads sys.stdin, which in a
    # GUI-launched Launcher is None or unusable -- without this the window would close instantly or hang.
    try:
        sys.stdin = open("CONIN$", "r", encoding="utf-8", errors="replace")  # noqa: SIM115
    except OSError:
        sys.stdin = _console_state["stdin"]  # no console input available -- the prompt degrades, see below
    _console_state["allocated"] = True
    return True


def _has_console() -> bool:
    """Whether this process has a console attached at all, whoever created it."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        kernel32.GetConsoleWindow.restype = wintypes.HWND
        return bool(kernel32.GetConsoleWindow())
    except Exception:
        return False


def _release_console(message: str) -> None:
    """Hold the console open on `message` until Enter, restore the saved streams, close the CONOUT$/CONIN$
    handles this module opened, and FreeConsole().

    The redirection is process-wide and the process is the Launcher, so without this it outlived the patch and
    the window went on to catch the CLIENT's output once the player started the client in the same session.
    Only acts on a console `_ensure_visible_console()` allocated. Safe to call twice or with nothing
    allocated, and never raises: failing to tidy up must not fail a patch that already succeeded."""
    if not _console_state.get("allocated"):
        return
    try:
        print(message)
    except Exception:
        pass
    try:
        input()
    except Exception:
        # No usable console input (CONIN$ refused above, or stdin closed underneath us). Better to fall
        # through and tidy up than to hang a window the player cannot answer.
        pass
    for stream_name in ("stdout", "stderr", "stdin"):
        replacement = getattr(sys, stream_name, None)
        setattr(sys, stream_name, _console_state.get(stream_name))
        # Only close what this module opened -- never the stream that was there before.
        if replacement is not None and replacement is not _console_state.get(stream_name):
            try:
                replacement.close()
            except Exception:
                pass
    try:
        import ctypes

        ctypes.windll.kernel32.FreeConsole()
    except Exception:
        pass
    _console_state.clear()


def _import_iso_patcher():
    """Return the `tools/iso_patcher` module, imported THROUGH the package so it gets a real `__package__`
    and its relative imports resolve, zip or loose checkout, with nothing read as a file.

    A rootless `sys.path.insert(tools_dir); import iso_patcher` leaves `__package__` empty, so every
    `from ..game_data import ...` raises and the patcher's ImportError fallbacks look for those modules as
    files -- inside an installed `.apworld`, a zip no file read can see into ("No such file or directory:
    ...game_data/shadow_move_slots.py"). The sys.path branch is kept only for this file run with no parent
    package; it inserts once."""
    if __package__:
        from .tools import iso_patcher

        return iso_patcher

    # pragma: no cover - standalone execution with no parent package
    if _TOOLS_DIR not in sys.path:
        sys.path.insert(0, _TOOLS_DIR)
    import iso_patcher  # type: ignore[import-not-found]

    return iso_patcher


def _has_native_linux_dialog() -> bool:
    """True only when Utils.open_filename/save_filename would use a native, subprocess-based dialog
    (kdialog/zenity) rather than the Tkinter fallback that needs the shared-root workaround."""
    from shutil import which

    from Utils import is_linux

    return is_linux and (which("kdialog") is not None or which("zenity") is not None)


def _run_dialog_chain(need_seed: bool) -> tuple[str | None, str | None, str | None]:
    """Run the seed/source/output dialog sequence and return `(seed_path, source, output)`. Anything the
    player was never asked for comes back None, and cancelling anywhere returns `(None, None, None)`. On Linux
    with a native dialog tool this delegates to Utils; everywhere else it drives `tkinter.filedialog` against
    one shared hidden root -- see the module docstring."""
    if _has_native_linux_dialog():
        from Utils import open_filename, save_filename

        seed_path = None
        if need_seed:
            seed_path = open_filename(
                "Select your Pokemon XD Archipelago patch (.appxd)",
                (("Pokemon XD patch", (".appxd",)),),
            )
            if not seed_path:
                return None, None, None

        source = open_filename(
            "Select your Pokemon XD: Gale of Darkness ISO",
            (("GameCube disc image", (".iso", ".gcm", ".ciso")),),
        )
        if not source:
            return None, None, None

        source_path = Path(source)
        suggested_name = f"{source_path.stem} (AP){source_path.suffix}"
        output = save_filename(
            "Save patched ISO copy as",
            (("GameCube disc image", (".iso", ".gcm", ".ciso")),),
            suggest=suggested_name,
        )
        if not output:
            return None, None, None
        return seed_path, source, output

    import tkinter
    import tkinter.filedialog

    try:
        root = tkinter.Tk()
    except tkinter.TclError:
        return None, None, None  # no GUI available at all -- same as the player cancelling
    root.withdraw()
    try:
        seed_path = None
        if need_seed:
            seed_path = tkinter.filedialog.askopenfilename(
                title="Select your Pokemon XD Archipelago patch (.appxd)",
                filetypes=[("Pokemon XD patch", ".appxd")],
                parent=root,
            )
            if not seed_path:
                return None, None, None
            root.update()  # let the dialog's own close/dispatch fully settle before opening the next one

        source = tkinter.filedialog.askopenfilename(
            title="Select your Pokemon XD: Gale of Darkness ISO",
            filetypes=[("GameCube disc image", ".iso .gcm .ciso")],
            parent=root,
        )
        if not source:
            return None, None, None
        root.update()

        source_path = Path(source)
        suggested_name = f"{source_path.stem} (AP){source_path.suffix}"
        output = tkinter.filedialog.asksaveasfilename(
            title="Save patched ISO copy as",
            filetypes=[("GameCube disc image", ".iso .gcm .ciso")],
            initialfile=suggested_name,
            parent=root,
        )
        if not output:
            return None, None, None
        return seed_path, source, output
    finally:
        root.destroy()


def _apply_with_visible_progress(iso_patcher, source: str, output: str, seed_path: str, overwrite: bool) -> dict:
    """Call `iso_patcher.apply_patch()` with a visible progress console on Windows. Its printouts go to the
    Launcher's own stdout, invisible when the Launcher is not itself running from a console -- the normal case
    for a double-clicked `.appxd` -- so patching a ~1GB ISO looked like a frozen window for the whole copy and
    LZSS re-encode. With no console available, or off Windows, this proceeds without one."""
    console_available = False
    if sys.platform == "win32":
        try:
            _ensure_visible_console()
        except Exception:
            pass  # the progress window is a nice-to-have -- patching still proceeds fully in-process below
        console_available = _has_console()

    if console_available:
        print("Patching Pokemon XD ISO -- this can take a few minutes for a real disc image. Do not close "
              "this window.\n")

    # The console is handed back on both paths. Through an exception the window stays up long enough to read
    # the traceback -- the only place the error is legible in full, since prompt_and_patch's message box shows
    # the exception text alone -- and the exception is re-raised unchanged.
    try:
        result = iso_patcher.apply_patch(Path(source), Path(output), Path(seed_path), overwrite=overwrite)
    except BaseException:
        if console_available:
            traceback.print_exc()
        _release_console("\nPatch FAILED. Press Enter to close.")
        raise

    _release_console("\nPatch Complete. Press Enter to close.")
    return result


def prompt_and_patch(seed_path: str | None = None) -> str | None:
    """Walk the player through selecting their source ISO and an output path, then apply `seed_path`'s
    trainer-species data via iso_patcher.apply_patch(). Prompts for the seed too if it is not given.

    Returns the new ISO's path, or None if the player cancelled or patching failed -- a failure is reported by
    message box, and this never raises out to the Launcher.
    """
    from Utils import messagebox

    try:
        iso_patcher = _import_iso_patcher()
    except Exception as e:  # noqa: BLE001 - surfaced to the player, not a silent failure
        traceback.print_exc()
        messagebox("Pokemon XD Patch - Error", f"Could not load the ISO patcher tool:\n{e}", error=True)
        return None

    resolved_seed_path, source, output = _run_dialog_chain(need_seed=not seed_path)
    if seed_path is None:
        seed_path = resolved_seed_path
    if not source or not output:
        return None  # player cancelled somewhere in the chain -- not an error

    try:
        # overwrite=True: the save dialog already had the player confirm this destination, including the OS's
        # own "file exists, overwrite?" prompt, so apply_patch() has nothing useful to add on top.
        summary = _apply_with_visible_progress(iso_patcher, source, output, seed_path, overwrite=True)
    except Exception as e:  # noqa: BLE001 - surfaced to the player via messagebox, not swallowed
        traceback.print_exc()
        messagebox("Pokemon XD Patch - Error", f"Could not patch the ISO:\n{e}", error=True)
        return None

    slots_patched = summary.get("trainer_slots_patched", 0)
    messagebox(
        "Pokemon XD Patch",
        f"Patched copy created:\n{summary['output']}\n\n"
        f"{slots_patched} trainer Pokemon species assignments applied.\n\n"
        'Load this copy in Dolphin, then use "Pokemon XD Client" to connect.',
    )
    return str(summary["output"])
