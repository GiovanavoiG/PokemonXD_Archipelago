"""Quick Purification Ceremony: the purification ceremony plays without its move-effect sequences.

`reliveCeremonyAll` (0x80232E14) is the ceremony for both the Relic Stone at Agate (`reliveMain`, from the shrine's
script) and the Purify Chamber (`reliveCeremonyFromHologram`). Its visuals are battle move-effect sequences: it loads
them from the disc (`Sequence_LoadWaza`), looks each up (`Sequence_GetWaza`), then starts it, waits a frame at a time
until it ends, and frees it. Those sequences are what make the ceremony slow on weaker PCs.

Every lookup and every load here becomes `li r3,0`, so no effect is loaded and every lookup finds none. The ceremony
already copes with a missing effect: five lookups skip their start, wait and free when nothing is found, and for the
other two `WazaSequence_Start`, `WazaSequence_IsActive` and `WazaSequence_Free` each return at once on a null
handle. The three loads' results are never used. The Pokemon's model, the fades, the messages, the purification
itself, the experience, the moves learned, evolution and the nickname prompt are untouched.

Import-free so the standalone patcher can load it by path.
"""
from __future__ import annotations

LI_R3_0 = 0x38600000

#: (address, vanilla word: the call, patched word).
SITES: "tuple[tuple[int, int, str], ...]" = (
    (0x80232ED0, 0x4BF9F489, "Sequence_GetWaza"),
    (0x80232FC4, 0x4BF9D2D5, "Sequence_LoadWaza"),
    (0x80233010, 0x4BF9D289, "Sequence_LoadWaza"),
    (0x80233094, 0x4BF9F2C5, "Sequence_GetWaza"),
    (0x802330A8, 0x4BF9F2B1, "Sequence_GetWaza"),
    (0x8023317C, 0x4BF9D11D, "Sequence_LoadWaza"),
    (0x802331B0, 0x4BF9F1A9, "Sequence_GetWaza"),
    (0x80233514, 0x4BF9EE45, "Sequence_GetWaza"),
    (0x80233644, 0x4BF9ED15, "Sequence_GetWaza"),
    (0x802337D4, 0x4BF9EB85, "Sequence_GetWaza"),
)

CEREMONY_START, CEREMONY_END = 0x80232E14, 0x80232E14 + 0xA84
SEQUENCE_GET_WAZA, SEQUENCE_LOAD_WAZA = 0x801D2358, 0x801D0298


def dol_patch_words() -> "tuple[tuple[int, int, int], ...]":
    """(address, vanilla, new)."""
    return tuple((address, vanilla, LI_R3_0) for address, vanilla, _name in SITES)
