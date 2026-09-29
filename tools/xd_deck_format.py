"""
Pokemon XD: Gale of Darkness -- Deck (trainer-team) file format.

Byte-exact against real ISO bytes, 2026-09-06. On the real
DeckData_Story.bin the section sizes sum to the file's declared total and DPKM's 823 entries * 32 bytes + a
16-byte header equal DPKM's declared size. There is no party-size field -- count the non-zero team slots.
"""
import struct

# 'LZSS'(4) + decompressed_size u32BE(4) + compressed_size u32BE(4, includes these 16) + reserved(4)
LZSS_HEADER_SIZE = 0x10


def lzss_decode(raw: bytes) -> bytes:
    """Decode one FSYS entry's LZSS payload; `raw` starts at the entry's own 'LZSS' magic. Trims to the size
    the HEADER declares, not to bytes[4:8] of the decoded output -- DeckData_*.bin happens to carry a
    self-referential 'DECK' size there, but common_rel.rel does not and came out truncated to garbage."""
    HEADER_LEN = 0x10  # see LZSS_HEADER_SIZE
    decompressed_size = struct.unpack_from('>I', raw, 4)[0]
    stream = raw[HEADER_LEN:]

    N = 4096          # window size, 1 << 12
    UNCODED_F = 16     # 1 << 4 (4-bit length field)
    THRESHOLD = 2
    n_mask = N - 1
    f_mask = UNCODED_F - 1  # 0x0F
    r = (N - UNCODED_F) - THRESHOLD  # initial ring write position = 4078

    ring = bytearray(N)
    out = bytearray()
    sp = 0
    flags = 0
    flag_bits_left = 0
    while sp < len(stream):
        if flag_bits_left == 0:
            flags = stream[sp]; sp += 1
            flag_bits_left = 8
        is_literal = flags & 1
        flags >>= 1
        flag_bits_left -= 1
        if is_literal:
            if sp >= len(stream):
                break
            c = stream[sp]; sp += 1
            out.append(c)
            ring[r] = c; r = (r + 1) & n_mask
        else:
            if sp + 1 >= len(stream):
                break
            b1 = stream[sp]; b2 = stream[sp + 1]; sp += 2
            pos = b1 | ((b2 & 0xF0) << 4)
            j = (b2 & f_mask) + THRESHOLD
            for k in range(j + 1):  # inclusive loop in the original C/C# -- j+1 iterations
                src = (pos + k) & n_mask
                c = ring[src]
                out.append(c)
                ring[r] = c; r = (r + 1) & n_mask

    return bytes(out[:decompressed_size])


def lzss_encode(decompressed: bytes) -> bytes:
    """Encode into a raw LZSS token stream -- flags and tokens only, no 16-byte header; the caller prepends
    that. Mirrors lzss_decode's ring bookkeeping exactly (N=4096, initial write pointer 4078, zero-filled
    ring) so `lzss_decode(header + lzss_encode(data)) == data` always holds; a hash index of every 3-byte
    prefix keeps the match search fast enough for real ~50KB files in pure Python. One-step lazy matching:
    emit a literal when the match one byte later is strictly longer. This is the encoder confirmed on real
    hardware. Headroom is fine for a species-only edit but not for species+moveset combined (measured 16807
    against a 16615 budget), where `patch_entry_decompressed()` raises."""
    N = 4096
    THRESHOLD = 2
    MAX_LEN = 18   # (0x0F) + THRESHOLD + 1
    MIN_LEN = 3    # THRESHOLD + 1 -- shortest match actually worth encoding (2 tokens vs 1-3 literal bytes)
    n_mask = N - 1

    ring = bytearray(N)
    r = (N - 16) - THRESHOLD  # 4078, matches lzss_decode's initial write pointer exactly

    # hash of 3-byte prefix -> set of ring positions currently holding that prefix, kept in sync as we write
    prefix_index: dict[bytes, set] = {}

    def ring_bytes(pos: int, length: int) -> bytes:
        if pos + length <= N:
            return bytes(ring[pos:pos + length])
        return bytes(ring[pos:N]) + bytes(ring[0:pos + length - N])

    def index_add(pos: int) -> None:
        key = ring_bytes(pos, 3)
        prefix_index.setdefault(key, set()).add(pos)

    def index_remove(pos: int) -> None:
        key = ring_bytes(pos, 3)
        s = prefix_index.get(key)
        if s is not None:
            s.discard(pos)

    # seed the index for the all-zero initial ring so early matches into it are found like any other
    for p in range(N):
        index_add(p)

    def ring_put(c: int) -> None:
        nonlocal r
        # positions whose 3-byte window will change once this byte lands need re-indexing after the write
        stale = [(r - k) & n_mask for k in range(3)]
        for p in stale:
            index_remove(p)
        ring[r] = c
        for p in stale:
            index_add(p)
        r = (r + 1) & n_mask

    def match_length(pos: int, max_len: int, start: int) -> int:
        # d is the distance back to the candidate. A match longer than d is a valid self-overlapping LZ77
        # reference (d=1 is a one-byte run); comparing against the pre-match ring instead of
        # data[start + length - d] yields matches that decode to something else -- the first roundtrip failure.
        d = (r - pos) & n_mask
        if d == 0:
            return 0
        length = 0
        while length < max_len:
            c = ring[(pos + length) & n_mask] if length < d else data[start + length - d]
            if c != data[start + length]:
                break
            length += 1
        return length

    def find_best_match(start: int, max_len: int) -> tuple[int, int]:
        best_len = 0
        best_pos = 0
        if max_len < MIN_LEN:
            return best_len, best_pos
        candidates = prefix_index.get(bytes(data[start:start + 3]))
        if not candidates:
            return best_len, best_pos
        for pos in candidates:
            length = match_length(pos, max_len, start)
            if length > best_len:
                best_len = length
                best_pos = pos
                if length == max_len:
                    break
        return best_len, best_pos

    data = decompressed
    n = len(data)
    in_pos = 0
    out = bytearray()
    flag_byte = 0
    flag_count = 0
    tokens = bytearray()

    def flush_flag():
        nonlocal flag_byte, flag_count, tokens
        out.append(flag_byte)
        out.extend(tokens)
        flag_byte = 0
        flag_count = 0
        tokens = bytearray()

    while in_pos < n:
        max_len = min(MAX_LEN, n - in_pos)
        best_len, best_pos = find_best_match(in_pos, max_len)

        if best_len >= MIN_LEN and in_pos + 1 < n:
            # nothing is committed to the ring/index for `in_pos` yet, so no state has to be undone here
            next_max_len = min(MAX_LEN, n - (in_pos + 1))
            next_len, _next_pos = find_best_match(in_pos + 1, next_max_len)
            if next_len > best_len:
                best_len = 0  # defer -- emit a literal now, let the next iteration take the better match

        if best_len >= MIN_LEN:
            pos = best_pos
            length = best_len
            b1 = pos & 0xFF
            b2 = (((pos >> 8) & 0x0F) << 4) | ((length - THRESHOLD - 1) & 0x0F)
            tokens.append(b1)
            tokens.append(b2)
            bit = 0
            for _ in range(length):
                ring_put(data[in_pos])
                in_pos += 1
        else:
            tokens.append(data[in_pos])
            bit = 1
            ring_put(data[in_pos])
            in_pos += 1

        flag_byte |= (bit << flag_count)
        flag_count += 1
        if flag_count == 8:
            flush_flag()

    if flag_count > 0:
        flush_flag()

    return bytes(out)


def patch_entry_decompressed(
    entry_raw: bytes, new_decompressed: bytes, allow_grow: bool = False, allow_decomp_resize: bool = False
) -> tuple[bytes, int, bool]:
    """Rebuild one FSYS entry from edited decompressed content. `entry_raw` starts at the entry's own 16-byte
    LZSS header; only `16 + declared_compressed_size` of it is read.

    Returns `(entry_blob, real_comp_size, grew)`. `real_comp_size` is HEADER-INCLUSIVE (16 + the real stream,
    padding excluded) and the caller must ALSO write it into the FSYS record's own comp_size field
    (`FSYS_RECORD_COMP_SIZE_OFF`, outside this blob). Do not skip that: the decompressor is input-driven, a
    0x00 flag byte over our zero padding means eight back-references emitting 3+ bytes each rather than eight
    literal zeroes, and it overruns a buffer sized for the declared decompressed size -- the Aferd freeze. A
    local round-trip misses it, since `lzss_decode` truncates to that same size.

    `grew=False`: the blob is exactly `old_comp_size` bytes, zero-padded, safe to write over the entry's old
    range with no other FSYS bookkeeping. `grew=True` (needs `allow_grow=True`) means it no longer fits: the
    blob is an exact fit and the caller must rebuild and relocate the container via
    `iso_patcher.rebuild_fsys_container_grown()`; otherwise this raises `ValueError`. Encodes exactly once.
    `len(new_decompressed)` must match the declared decompressed size unless `allow_decomp_resize`, since
    resizing a section would shift every later section's offsets."""
    # Both size fields count the 16-byte header -- the entry's total on-disc size, not the stream's length.
    # Evidence: the reference randomizer writes `codesize + 0x10`; vanilla pocket_menu.fsys's 544-byte entry
    # declares comp=112 with its stream ending at 0x70 = 16 + 96; DeckData_DarkPokemon.bin's comp=1084 reaches
    # the next entry at +1088 only once the header counts.
    old_decomp_size, old_comp_size = struct.unpack_from('>II', entry_raw, 4)
    old_stream_alloc = old_comp_size - LZSS_HEADER_SIZE
    if old_stream_alloc < 0:
        raise ValueError(
            f"LZSS header declares a compressed size of {old_comp_size} bytes, smaller than its own 16-byte "
            "header -- not a valid LZSS entry"
        )
    if len(new_decompressed) != old_decomp_size:
        if not allow_decomp_resize:
            raise AssertionError(
                f"resizing the decompressed payload ({len(new_decompressed)} vs original {old_decomp_size}) is "
                "not supported by this simple in-place patcher -- it would require adding/removing DTNR/DPKM/"
                "DDPK entries, which this project's edits never do. Pass allow_decomp_resize=True (NEW, "
                "ADDENDUM 51) if the caller genuinely changed a section's own entry count (see "
                "iso_patcher.grow_dpkm_section()) rather than only rewriting already-allocated entries in "
                "place -- this is a bigger, less-tested change than allow_grow alone; see that function's "
                "docstring."
            )
        declared_decomp_size = len(new_decompressed)
    else:
        declared_decomp_size = old_decomp_size
    new_stream = lzss_encode(new_decompressed)
    real_comp_size = LZSS_HEADER_SIZE + len(new_stream)  # header-inclusive
    if len(new_stream) > old_stream_alloc:
        if not allow_grow:
            raise ValueError(
                f"re-encoded stream ({len(new_stream)} bytes) is larger than the original allocated compressed "
                f"stream size ({old_stream_alloc} bytes, i.e. declared {old_comp_size} minus the 16-byte header) "
                "-- this particular edit doesn't fit in place. Pass allow_grow=True to let the caller relocate "
                "the containing FSYS container instead (see iso_patcher.rebuild_fsys_container_grown()/"
                "apply_patch()), or, for a seed-driven edit, try disabling shuffle_trainer_movesets -- species-"
                "only edits have comfortable headroom under this budget without growth (confirmed, ADDENDUM 9/10)."
            )
        new_header = b'LZSS' + struct.pack('>II', declared_decomp_size, real_comp_size) + entry_raw[12:16]
        result = new_header + new_stream
        assert len(result) == real_comp_size
        return result, real_comp_size, True
    padded_stream = new_stream + b'\x00' * (old_stream_alloc - len(new_stream))
    new_header = b'LZSS' + struct.pack('>II', declared_decomp_size, real_comp_size) + entry_raw[12:16]
    result = new_header + padded_stream
    assert len(result) == old_comp_size
    return result, real_comp_size, False


class DeckFile:
    """Parses one decompressed DeckData_*.bin blob: the DTNR -> DPKM -> DTAI -> DSTR section chain."""

    def __init__(self, data: bytes):
        self.data = data
        self._u32 = lambda off: struct.unpack_from('>I', data, off)[0]
        self._u16 = lambda off: struct.unpack_from('>H', data, off)[0]
        self._u8 = lambda off: data[off]

        assert data[0:4] == b'DECK', f"expected DECK magic at 0, got {data[0:4]!r}"

        self.dtnr_hdr = 0x10
        self.dtnr_size = self._u32(self.dtnr_hdr + 0x04)
        self.dtnr_entries = self._u32(self.dtnr_hdr + 0x08)
        self.dtnr_data = self.dtnr_hdr + 0x10
        assert data[self.dtnr_hdr:self.dtnr_hdr + 4] == b'DTNR'

        self.dpkm_hdr = self.dtnr_hdr + self.dtnr_size
        self.dpkm_size = self._u32(self.dpkm_hdr + 0x04)
        self.dpkm_entries = self._u32(self.dpkm_hdr + 0x08)
        self.dpkm_data = self.dpkm_hdr + 0x10

        self.dtai_hdr = self.dpkm_hdr + self.dpkm_size
        self.dtai_size = self._u32(self.dtai_hdr + 0x04)
        self.dtai_entries = self._u32(self.dtai_hdr + 0x08)
        self.dtai_data = self.dtai_hdr + 0x10

        self.dstr_hdr = self.dtai_hdr + self.dtai_size
        self.dstr_size = self._u32(self.dstr_hdr + 0x04)
        self.dstr_data = self.dstr_hdr + 0x10

    def dpkm_species_level(self, dpkm_index: int):
        off = self.dpkm_data + dpkm_index * 0x20
        return self._u16(off), self._u8(off + 2)

    def dpkm_full(self, dpkm_index: int):
        off = self.dpkm_data + dpkm_index * 0x20
        d = self.data
        return {
            'species': self._u16(off + 0x00),
            'level': self._u8(off + 0x02),
            'happiness': self._u8(off + 0x03),
            'item': self._u16(off + 0x04),
            'ai_role': self._u8(off + 0x06),
            'is_key_strategic': self._u8(off + 0x07),
            'ivs': list(d[off + 0x08:off + 0x0E]),
            'evs': list(d[off + 0x0E:off + 0x14]),
            'moves': [self._u16(off + 0x14 + 2 * i) for i in range(4)],
            'shininess': self._u16(off + 0x1C),
            'nature_gender_ability': self._u8(off + 0x1E),
            'combo_bitfield': self._u8(off + 0x1F),
        }

    def trainer(self, index: int):
        # An index past dtnr_entries but still inside self.data would read DTAI/DSTR bytes as a trainer record
        # and return plausible garbage instead of None, defeating every `deck.trainer(t) is None` version guard.
        if index < 0 or index >= self.dtnr_entries:
            return None
        base = self.dtnr_data + index * 0x38
        trainer_class = self._u8(base + 0x05)
        if trainer_class == 0:
            return None  # unused slot
        shadow_mask = self._u8(base + 0x04)
        team = []
        for slot in range(6):
            val = self._u16(base + 0x1C + slot * 2)
            if val == 0:
                continue
            is_shadow = (shadow_mask >> slot) & 1
            if is_shadow:
                team.append({'slot': slot, 'kind': 'DDPK', 'ddpk_index': val})
            else:
                sp, lv = self.dpkm_species_level(val)
                team.append({'slot': slot, 'kind': 'DPKM', 'dpkm_index': val, 'species': sp, 'level': lv})
        return {
            'index': index,
            'trainer_class': trainer_class,
            'name_id': self._u16(base + 0x06),
            'string_ptr': self._u16(base + 0x00),
            'ai_index': self._u16(base + 0x28),
            'party_size': len(team),
            'team': team,
        }

    def all_trainers(self):
        out = []
        for i in range(self.dtnr_entries):
            t = self.trainer(i)
            if t is not None:
                out.append(t)
        return out


class DarkPokemonFile:
    """Decompressed DeckData_DarkPokemon.bin: one outer 16-byte 'DECK' wrapper, then a single DDPK section --
    no DTNR/DPKM/DTAI/DSTR chain. Confirmed against real bytes: 'DECK' at +0x00, 'DDPK' at +0x10, data at
    +0x20, 0x18 (24) bytes per entry, entry 0 the reserved all-zero sentinel like DPKM/DTNR index 0."""

    def __init__(self, data: bytes):
        self.data = data
        self._u16 = lambda off: struct.unpack_from('>H', data, off)[0]
        self._u32 = lambda off: struct.unpack_from('>I', data, off)[0]

        assert data[0:4] == b'DECK', f"expected DECK magic at 0, got {data[0:4]!r}"
        self.ddpk_hdr = 0x10
        assert data[self.ddpk_hdr:self.ddpk_hdr + 4] == b'DDPK', \
            f"expected DDPK magic at {hex(self.ddpk_hdr)}, got {data[self.ddpk_hdr:self.ddpk_hdr + 4]!r}"
        self.ddpk_size = self._u32(self.ddpk_hdr + 0x04)
        self.ddpk_entries = self._u32(self.ddpk_hdr + 0x08)
        self.ddpk_data = self.ddpk_hdr + 0x10

    def ddpk_full(self, index: int):
        off = self.ddpk_data + index * 0x18
        d = self.data
        return {
            'flee_weight': d[off + 0x00],
            'catch_rate_override': d[off + 0x01],
            'shadow_level': d[off + 0x02],
            'in_use': d[off + 0x03],
            'story_deck_index': self._u16(off + 0x06),  # index into DeckData_Story.bin's DPKM pool
            'heart_gauge': self._u16(off + 0x08),
            'bonus_exp': self._u16(off + 0x0A),
            'shadow_moves': [self._u16(off + 0x0C + 2 * i) for i in range(4)],
            'aggression': d[off + 0x14],
            'always_flee': d[off + 0x15],
        }

    def all_ddpk(self):
        out = []
        for i in range(self.ddpk_entries):
            rec = self.ddpk_full(i)
            if rec['in_use'] == 0 and i == 0:
                continue  # index-0 sentinel, matching the DPKM/DTNR convention
            out.append({'index': i, **rec})
        return out


if __name__ == '__main__':
    import sys, json
    raw = open(sys.argv[1] if len(sys.argv) > 1 else
               '/mnt/user-data/uploads/PokemonXD-working/bridge/dumps/deck_story_1.bin', 'rb').read()
    decoded = lzss_decode(raw)
    deck = DeckFile(decoded)
    print('DTNR entries:', deck.dtnr_entries, ' DPKM entries:', deck.dpkm_entries,
          ' DTAI entries:', deck.dtai_entries, ' DSTR size:', deck.dstr_size)
    trainers = deck.all_trainers()
    print('non-empty trainers:', len(trainers))
    with open('deckdata_story_trainers.json', 'w') as f:
        json.dump(trainers, f, indent=1)
    print('wrote deckdata_story_trainers.json')
