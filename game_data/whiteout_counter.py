"""ADDENDUM 475 -- Death Link sends off the game's own white-out, not off a read of the party.
ADDENDUM 484 -- counted at the TOP of the white-out, the moment the game decides it, not at the recovery call.

WHERE THE GAME WHITES YOU OUT. Two places, and only two, run the white-out: `fightEncountCheckZenmetu` ("zenmetu",
annihilation -- 0x801F0D9C, called from `fightMain` as a battle ends) and `fightEncount` (0x801F0E94, at the next
encounter). Each tests the encounter's annihilation flag and that the player did NOT win, and only then runs the
white-out: free the battle's file, clear the encounter, turn off GS flag 803, `fightEncountAnnihilationRecovery`
(heal, lose half the money), and the warp to the battle-resume floor. The third caller of the recovery routine,
`AppScript::cmpFight`, is a SCRIPT healing the party -- not a death -- and is left alone.

THE HOOK (484). The FIRST instruction of each white-out branch -- the one every check has to pass to reach -- becomes
a `bl` to a small stub that adds one to a counter word and then does the instruction it replaced:

    0x801F0E10  fightEncountCheckZenmetu+0x74   li r3, 0x842   (first instruction after "not a win")
    0x801F10B4  fightEncount+0x220              li r3, 0       (first instruction after "not a win")

    stub (dbgMenuDbgPokemonGet + 0x718 / + 0x730 -- the unreferenced debug function the other caves use, clear of
    the Candy Box/Ability Swap code below +0x3F0 and the catch/purification code at +0x800):
        lis  r12, ha(counter)
        lwz  r11, lo(counter)(r12)
        addi r11, r11, 1
        stw  r11, lo(counter)(r12)
        li   r3, <the replaced immediate>
        blr
    counter (0x80067444, + 0x714): u32, 0 at boot -- the SAME word as ADDENDUM 475's.

r11/r12 are scratch and dead there (the next instruction in both is a call); LR is already saved by both functions'
prologues and every following call overwrites it anyway. Before 484 the hook was the `bl fightEncountAnnihilationRecovery`
a few calls further down each branch: the same white-out, counted a few calls later. `LEGACY_HOOK_WORDS` is that
layout, so a client reading an ISO patched by 0.1.2/0.1.3 still finds the counter.

The client watches the counter: it only ever goes up, by exactly one per white-out, and it holds its value until the
next one -- so a once-a-second poll cannot miss it the way it could miss a party that is at 0 HP for a moment. It
is RAM: a reboot puts it back to 0, which the client treats as a new baseline, never as a death.
"""
from __future__ import annotations

_CAVE = 0x80066D30
COUNTER_ADDRESS = _CAVE + 0x714                          # 0x80067444 -- unchanged since 475
STUB_ADDRESSES = (_CAVE + 0x718, _CAVE + 0x730)          # one per hook site, 6 words each
RECOVERY_ADDRESS = 0x801F0D18

# (site, vanilla word there, the replaced `li r3, imm` immediate)
HOOK_SITES = (
    (0x801F0E10, 0x38600842, 0x0842),    # fightEncountCheckZenmetu: li r3, 2114 (the GSfsysFree id)
    (0x801F10B4, 0x38600000, 0x0000),    # fightEncount: li r3, 0 (fightSetFightEncountDataId)
)
HOOK_VANILLA_WORDS = {site: vanilla for site, vanilla, _imm in HOOK_SITES}

# The vanilla debug-function words the stubs and counter overwrite, from a retail main.dol.
COUNTER_VANILLA_WORD = 0x38A00001
STUB_VANILLA_WORDS = (
    (0x38C0FFFF, 0x480E569D, 0x7FE3FB78, 0x38800243, 0x38A00001, 0x38C0FFFF),   # +0x718
    (0x480E5689, 0x7FE3FB78, 0x38800244, 0x38A00001, 0x38C0FFFF, 0x480E5675),   # +0x730
)

# ADDENDUM 475's layout: `bl stub` at each white-out's `bl fightEncountAnnihilationRecovery`, the stub at + 0x700
# tail-branching into the recovery routine. Read-only here: the client accepts it so an older patched ISO still sends.
LEGACY_HOOK_WORDS = {0x801F0E38: 0x4BE765F9, 0x801F10C4: 0x4BE7636D}
LEGACY_HOOK_VANILLA_WORDS = {0x801F0E38: 0x4BFFFEE1, 0x801F10C4: 0x4BFFFC55}   # bl fightEncountAnnihilationRecovery

assert 0x3F0 <= STUB_ADDRESSES[0] - _CAVE and STUB_ADDRESSES[-1] + 0x18 - _CAVE <= 0x800, (
    "the white-out stubs must stay between the Ability Swap code (ends +0x3F0) and the conditional catch (+0x800)")


def _branch(at: int, target: int, link: bool = False) -> int:
    return 0x48000000 | ((target - at) & 0x03FFFFFC) | (1 if link else 0)


def _ha_lo(address: int) -> "tuple[int, int]":
    lo = address & 0xFFFF
    return ((address >> 16) + (1 if lo & 0x8000 else 0)) & 0xFFFF, lo


def stub_words(immediate: int) -> "tuple[int, ...]":
    ha, lo = _ha_lo(COUNTER_ADDRESS)
    return (
        0x3D800000 | ha,                       # lis  r12, ha
        0x816C0000 | lo,                       # lwz  r11, lo(r12)
        0x396B0001,                            # addi r11, r11, 1
        0x916C0000 | lo,                       # stw  r11, lo(r12)
        0x38600000 | (immediate & 0xFFFF),     # li   r3, imm   -- the instruction the hook replaced
        0x4E800020,                            # blr
    )


def hook_words() -> "dict[int, int]":
    return {site: _branch(site, stub, link=True) for (site, _vanilla, _imm), stub in zip(HOOK_SITES, STUB_ADDRESSES)}


def dol_patch_words() -> "tuple[tuple[int, int, int], ...]":
    """(address, vanilla word, new word) for `iso_patcher.write_dol_words_patch`."""
    words = [(COUNTER_ADDRESS, COUNTER_VANILLA_WORD, 0x00000000)]
    for stub, vanilla_words, (_site, _vanilla, immediate) in zip(STUB_ADDRESSES, STUB_VANILLA_WORDS, HOOK_SITES):
        words += [(stub + 4 * i, vanilla, new) for i, (vanilla, new) in enumerate(zip(vanilla_words,
                                                                                       stub_words(immediate)))]
    words += [(site, HOOK_VANILLA_WORDS[site], new) for site, new in hook_words().items()]
    # A 475-patched main.dol as input would keep its recovery-call hooks beside the new ones and count each white-out
    # twice, so those two words go back to vanilla. On a vanilla main.dol they already are, and nothing changes.
    words += [(site, LEGACY_HOOK_WORDS[site], LEGACY_HOOK_VANILLA_WORDS[site]) for site in LEGACY_HOOK_WORDS]
    return tuple(words)


def installed_layouts() -> "tuple[dict[int, int], ...]":
    """Every hook layout a client should accept, newest first: either one means the counter word is live."""
    return (hook_words(), LEGACY_HOOK_WORDS)


assert stub_words(0x842)[0] == 0x3D808006 and stub_words(0x842)[1] == 0x816C7444
assert hook_words() == {0x801F0E10: 0x4BE76639, 0x801F10B4: 0x4BE763AD}, hook_words()
