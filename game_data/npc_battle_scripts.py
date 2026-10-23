"""Aferd, Laken and Hebon always battle when talked to.

All three are repeat-battle NPCs whose talk function picks a team by the story value (script var 964) and refuses -- a
line of dialogue and no fight -- outside its windows, or once that team is beaten. The client patches the loaded
map script in RAM, like the Snagem 2F script: every write is checked against the stock byte, and the whole blob
against its size, section tags and the battle-id loads that pin the function. A map load reads the script from disc
again, so the patch is re-applied after each one.

AFERD (HQ Lab script, TCOD size 0x8620, `talk_100_gyma_m0`). After the patch the team follows the story and the
beaten counter (GS var 974) no longer locks it: story >= 980 #5, 800-979 #4, 470-799 #3, 400-469 #2, below 400 #1.
His yes/no prompt stays; "no" still declines.

LAKEN (Gateon Port script, TCOD size 0x13080, `talk_100_thief_f`). The story gate below 200 is removed, so below
390 he fields #1, 390-969 #2, 970+ #3; the once-per-visit flag (965) no longer stops a rematch. The two lines tied
to the all-Shadows-snagged side quest are left as they are, since they set the flags that quest needs.

HEBON (Agate Village script, TCOD size 0x44D0, `talk_113_rider_m`). He asks first, then fields #1 below 390, #2 at
390-969 and #3 from 970; the beaten lock (GS var 1107) no longer stops him. Answering "no" still declines.

Offsets are into the script blob. Instruction w sits at the CODE section + 0x20 + 4w.
"""
from __future__ import annotations

# ---------------------------------------------------------------- AFERD: talk_100_gyma_m0 in the 0x8620 lab script
AFERD_SCRIPT_SIZE = 0x8620
_AF_CODE0 = 0x4F0                    # CODE section (0x4D0) + 0x20


def _af(w):
    return _AF_CODE0 + 4 * w


AFERD_TALK_W = 5734                  # f16 talk_100_gyma_m0

AFERD_SCRIPT_PATCHES = (
    # S >= 980 window: flag-1751 test `flag == 0` -> `flag < 0` (never true), so the JUMPIF always leaves the refusal ...
    (_af(5757) + 1, 0x30, 0x33),     # +0x5EE5  op == -> op <
    # ... and that JUMPIF now lands on the #5 yes/no prompt (w5778), skipping the `A < 4` beaten-lock as well
    (_af(5758) + 3, 0x88, 0x92),     # +0x5EEB  jumpiffalse 5768 -> 5778
    # 970..979 refusal ("Yo, <player>."): its threshold constant 970 -> 0x010003CA, so `S >= it` is never true
    (_af(5840) + 1, 0x00, 0x01),     # +0x6031  ldimm 970 high byte
    # S < 800: skip the 740..799 refusal test, go straight to the S >= 470 test
    (_af(5866) + 3, 0x31, 0x44),     # +0x609B  jumpiffalse 5937 -> 5956
    # beaten-locks `A < n` (A = GS var 974, Aferd's 3-bit progress counter): n -> 0x01000000 + n, never reached
    (_af(5874) + 1, 0x00, 0x01),     # +0x60B9  800..979 window, ldimm 4 -> #4 prompt always
    (_af(5973) + 1, 0x00, 0x01),     # +0x6245  470..799 window, ldimm 3 -> #3 prompt always
    (_af(6053) + 1, 0x00, 0x01),     # +0x6385  400..469 window, ldimm 2 -> #2 prompt always
    # S < 400: the S >= 400 test's JUMPIF, retargeted from the 360/200/100/90/30 refusal chain onto the #1 prompt (w6296)
    (_af(6045) + 2, 0x17, 0x18),     # +0x6366  jumpiffalse 6116 -> 6296 (target high byte)
    (_af(6045) + 3, 0xE4, 0x98),     # +0x6367  (target low byte)
)

AFERD_SCRIPT_ANCHORS = (
    (0x0000, b"TCOD"), (0x0004, b"\x00\x00\x86\x20"),
    (0x0010, b"FTBL"), (0x0400, b"HEAD"), (0x04D0, b"CODE"),
    (0x83A0, b"GVAR"), (0x8400, b"STRG"), (0x8450, b"VECT"), (0x84D0, b"GIRI"), (0x8580, b"ARRY"),
    # the five battle calls' battle-id loads -- never patched, they pin the function to Aferd #1..#5
    (_af(5795), bytes.fromhex("02010000000001af")),   # ldimm 431  Aferd #5
    (_af(5894), bytes.fromhex("020100000000015c")),   # ldimm 348  Aferd #4
    (_af(5993), bytes.fromhex("0201000000000115")),   # ldimm 277  Aferd #3
    (_af(6073), bytes.fromhex("0201000000000114")),   # ldimm 276  Aferd #2
    (_af(6313), bytes.fromhex("02010000000000d8")),   # ldimm 216  Aferd #1
    # unpatched bytes around every patch site
    (_af(5734), bytes.fromhex("0d010000")),           # reserve 1, the function's first instruction
    (_af(5750), bytes.fromhex("02010000000006d7")),   # ldimm 1751
    (_af(5757), b"\x01"), (_af(5757) + 2, b"\x00\x00"),
    (_af(5758), b"\x0b\x00\x16"),
    (_af(5778), bytes.fromhex("100007c5")),           # line 1989, the #5 prompt the retarget lands on
    (_af(5839), bytes.fromhex("02010000")), (_af(5840) + 2, b"\x03\xca"),
    (_af(5866), b"\x0b\x00\x17"),
    (_af(5873), bytes.fromhex("02010000")), (_af(5874) + 2, b"\x00\x04"), (_af(5876), bytes.fromhex("0b001728")),
    (_af(5956), bytes.fromhex("100007fb")),           # line 2043, the S >= 470 test the 800-JUMPIF now lands on
    (_af(5957), bytes.fromhex("02010000000001d6")),   # ldimm 470
    (_af(5972), bytes.fromhex("02010000")), (_af(5973) + 2, b"\x00\x03"), (_af(5975), bytes.fromhex("0b00178b")),
    (_af(6052), bytes.fromhex("02010000")), (_af(6053) + 2, b"\x00\x02"), (_af(6055), bytes.fromhex("0b0017db")),
    (_af(6037), bytes.fromhex("0201000000000190")),   # ldimm 400
    (_af(6045), b"\x0b\x00"),
    (_af(6296), bytes.fromhex("1000085a")),           # line 2138, the #1 prompt
)

# ---------------------------------------------------------------- LAKEN: talk_100_thief_f in the 0x13080 Gateon script
LAKEN_SCRIPT_SIZE = 0x13080
_LK_CODE0 = 0x510                    # CODE section (0x4F0) + 0x20


def _lk(w):
    return _LK_CODE0 + 4 * w


LAKEN_TALK_W = 6690                  # f12 talk_100_thief_f

# core: the story gate. S >= 200 -> S >= 0, so every S < 390 takes the Laken #1 branch (vanilla refused below 200)
LAKEN_SCRIPT_PATCHES = (
    (_lk(7099) + 3, 0xC8, 0x00),     # +0x73FF  ldimm 200 -> ldimm 0
)
# optional: the once-per-visit lock (flag 965, group 1). `flag965 == 0` -> `flag965 >= 0` (always true)
LAKEN_REMATCH_PATCHES = (
    (_lk(6708) + 1, 0x30, 0x32),     # +0x6DE1  flag-1672 path (set after the all-Shadows-snagged line), Laken #3
    (_lk(6889) + 1, 0x30, 0x32),     # +0x70B5  S >= 970, Laken #3
    (_lk(7002) + 1, 0x30, 0x32),     # +0x7279  S >= 390, Laken #2
    (_lk(7115) + 1, 0x30, 0x32),     # +0x743D  S <  390, Laken #1
)

LAKEN_SCRIPT_ANCHORS = (
    (0x0000, b"TCOD"), (0x0004, b"\x00\x01\x30\x80"),
    (0x0010, b"FTBL"), (0x0410, b"HEAD"), (0x04F0, b"CODE"),
    (0x12E10, b"GVAR"), (0x12E30, b"STRG"), (0x12EA0, b"VECT"), (0x12F10, b"GIRI"), (0x13020, b"ARRY"),
    (_lk(6739), bytes.fromhex("0201000000000193")),  # ldimm 403  Laken #3 (flag-1672 path)
    (_lk(6920), bytes.fromhex("0201000000000193")),  # ldimm 403  Laken #3
    (_lk(7033), bytes.fromhex("02010000000001aa")),  # ldimm 426  Laken #2
    (_lk(7146), bytes.fromhex("02010000000000df")),  # ldimm 223  Laken #1
    (_lk(6690), bytes.fromhex("100007d2")),          # line 2002, the function's first instruction
    (_lk(7098), bytes.fromhex("02010000000000")),    # ldimm int, 3 high bytes of the 200 (low byte is ours)
    (_lk(7100), bytes.fromhex("02010000000003c409000085")),  # ldimm 964 ; callstd 0.0x85
    (_lk(7105), bytes.fromhex("013400000b001c2a")),  # op <= ; jumpiffalse 7210
    (_lk(6708), b"\x01"), (_lk(6708) + 2, b"\x00\x00"), (_lk(6709), bytes.fromhex("0b001a8a")),
    (_lk(6889), b"\x01"), (_lk(6889) + 2, b"\x00\x00"), (_lk(6890), bytes.fromhex("0b001b3f")),
    (_lk(7002), b"\x01"), (_lk(7002) + 2, b"\x00\x00"), (_lk(7003), bytes.fromhex("0b001bb0")),
    (_lk(7115), b"\x01"), (_lk(7115) + 2, b"\x00\x00"), (_lk(7116), bytes.fromhex("0b001c21")),
)


# ---------------------------------------------------------------- HEBON: talk_113_rider_m in the 0x44D0 Agate script
HEBON_SCRIPT_SIZE = 0x44D0
_HB_CODE0 = 0x2B0                     # CODE section (0x290) + 0x20


def _hb(w):
    return _HB_CODE0 + 4 * w


HEBON_TALK_W = 3433                   # f19 talk_113_rider_m

HEBON_SCRIPT_PATCHES = (
    (_hb(3436) + 1, 0x00, 0x01),      # +0x3861  ldimm 970 -> 0x010003CA: `S >= it` never true
    (_hb(3443) + 2, 0x0D, 0x0F),      # +0x387E  jumpiffalse 3525 -> 4012 (target high byte)
    (_hb(3443) + 3, 0xC5, 0xAC),      # +0x387F  (target low byte)
)

HEBON_SCRIPT_ANCHORS = (
    (0x0000, b"TCOD"), (0x0004, b"\x00\x00\x44\xd0"),
    (0x0010, b"FTBL"), (0x0210, b"HEAD"), (0x0290, b"CODE"),
    (0x4340, b"GVAR"), (0x4370, b"STRG"), (0x43D0, b"VECT"), (0x43F0, b"GIRI"), (0x44A0, b"ARRY"),
    (_hb(3433), bytes.fromhex("0d01000010000441")),          # reserve 1 ; line 1089 (function entry)
    (_hb(3435), bytes.fromhex("02010000")), (_hb(3436) + 2, b"\x03\xca"),   # ldimm 970 (byte 1 is ours)
    (_hb(3437), bytes.fromhex("02010000000003c409000085")),   # ldimm 964 ; callstd 0.0x85 (getVar)
    (_hb(3442), bytes.fromhex("01340000")), (_hb(3443), b"\x0b\x00"),       # op <= ; jumpiffalse (target is ours)
    (_hb(3525), bytes.fromhex("10000454")),                   # line 1108, the stock target (S >= 630 test)
    (_hb(4012), bytes.fromhex("100004c5020100000000000002010000000094940201000000000008")),  # new target: prompt 38036
    (_hb(3922), bytes.fromhex("02010000000001b7")),           # selector 439 (#3)
    (_hb(3943), bytes.fromhex("02010000000001ae")),           # selector 430 (#2)
    (_hb(3954), bytes.fromhex("02010000000000e6")),           # selector 230 (#1)
    (_hb(4036), bytes.fromhex("02010000000001b7")),           # w4012-path selector 439
    (_hb(4057), bytes.fromhex("02010000000001ae")),           # w4012-path selector 430
    (_hb(4068), bytes.fromhex("02010000000000e6")),           # w4012-path selector 230
    (_hb(4116), bytes.fromhex("0e01000008000000")),           # release 1 ; return
)
