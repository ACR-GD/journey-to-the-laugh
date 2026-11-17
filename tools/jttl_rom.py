"""Journey to the Laugh (Taiwan) Super A'Can ROM helpers, allocator, and IPS utilities."""

from __future__ import annotations

import hashlib
import struct
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

ORIG_ROM_PATH = Path(__file__).resolve().parent.parent / "Journey to the Laugh (Taiwan).bin"   # your own dump
ORIG_ROM_SIZE = 0x200000  # Full 2 MiB ROM (unmirrored)
ORIG_SHA1 = "fc82fc3a7d55571494cd62d8807160e22cf437bc"
ORIG_SHA256 = "a4964b702214f70e199bb07bbd2777eb08875206fa27396989f2a79cb48c5087"

# Verified free/reclaimed regions in 68000 big-endian address space:
# NOTE: 0x0A6666..0x0A6686 (32B) holds Text Palette `Text0` (referenced by 0x069036 / 0x0EE52E)
#       and MUST remain untouched! ASCII 8x16 font goes at 0x0A6686..0x0A6C86 (1,536B).
DEFAULT_FREE_REGIONS: List[Tuple[int, int]] = [
    (0x0A60F2, 0x0A6666),  # 1,396 bytes (reclaimed old 16x16 font pointer table)
    (0x0A6C86, 0x0A9226),  # 9,632 bytes (reclaimed after ASCII 8x16 font at 0x0A6686..0x0A6C86)
    (0x1FC020, 0x200000),  # 16,352 bytes (trailing empty zero-filled ROM space)
]


def swap16(data: bytes) -> bytes:
    """16-bit byte-swap between .bin file order and 68000 big-endian CPU space."""
    if len(data) & 1:
        raise ValueError(f"Odd ROM length {len(data)}")
    out = bytearray(len(data))
    out[0::2] = data[1::2]
    out[1::2] = data[0::2]
    return bytes(out)


def load_rom(path: Path = ORIG_ROM_PATH, verify_hash: bool = True) -> Tuple[bytearray, bytes]:
    """Return (cpu_be_rom, orig_swapped_bytes)."""
    swapped = path.read_bytes()
    if verify_hash:
        sha1 = hashlib.sha1(swapped).hexdigest()
        sha256 = hashlib.sha256(swapped).hexdigest()
        if sha1 != ORIG_SHA1 or sha256 != ORIG_SHA256:
            raise ValueError(
                f"ROM hash mismatch for {path}: sha1={sha1} sha256={sha256}"
            )
    if len(swapped) != ORIG_ROM_SIZE:
        raise ValueError(f"Unexpected ROM size {len(swapped)} (expected {ORIG_ROM_SIZE})")
    be = bytearray(swap16(swapped))
    return be, swapped


def save_rom(cpu_rom: bytearray, out_path: Path) -> bytes:
    """Byte-swap full 2 MiB CPU ROM to little-endian .bin and write out_path."""
    if len(cpu_rom) != ORIG_ROM_SIZE:
        raise ValueError(f"Unexpected CPU ROM length {len(cpu_rom)}")
    swapped = swap16(bytes(cpu_rom))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(swapped)
    return swapped


def write_ips(orig_swapped: bytes, mod_swapped: bytes, ips_path: Path) -> int:
    """Write standard IPS patch transforming orig_swapped -> mod_swapped. Returns record count."""
    orig_len = len(orig_swapped)
    mod_len = len(mod_swapped)
    if mod_len > 0xFFFFFF:
        raise ValueError(f"ROM size {mod_len:#x} exceeds 24-bit IPS limit")

    out = bytearray(b"PATCH")
    records = 0
    i = 0
    while i < mod_len:
        b_mod = mod_swapped[i]
        b_orig = orig_swapped[i] if i < orig_len else None
        if b_orig == b_mod:
            i += 1
            continue
        start = i
        chunk = bytearray()
        same_run = 0
        while i < mod_len and len(chunk) < 0xFFFF:
            bm = mod_swapped[i]
            bo = orig_swapped[i] if i < orig_len else None
            if bm == bo:
                same_run += 1
                if same_run >= 6:
                    break
            else:
                same_run = 0
            chunk.append(bm)
            i += 1
        while same_run > 0 and chunk and len(chunk) > 1:
            idx = start + len(chunk) - 1
            if idx < orig_len and chunk[-1] == orig_swapped[idx]:
                chunk.pop()
                same_run -= 1
                i -= 1
            else:
                break
        if start == 0x454F46:  # avoid 'EOF' sentinel collision
            start -= 1
            chunk.insert(0, mod_swapped[start])
        out.extend(start.to_bytes(3, "big"))
        out.extend(len(chunk).to_bytes(2, "big"))
        out.extend(chunk)
        records += 1

    out.extend(b"EOF")
    ips_path.parent.mkdir(parents=True, exist_ok=True)
    ips_path.write_bytes(out)
    return records


def apply_ips(orig_bytes: bytes, ips_bytes: bytes) -> bytes:
    """Apply an IPS patch in memory (for strict round-trip verification)."""
    if not ips_bytes.startswith(b"PATCH"):
        raise ValueError("Invalid IPS header")
    out = bytearray(orig_bytes)
    p = 5
    while p < len(ips_bytes):
        if ips_bytes[p : p + 3] == b"EOF":
            break
        off = int.from_bytes(ips_bytes[p : p + 3], "big")
        p += 3
        sz = int.from_bytes(ips_bytes[p : p + 2], "big")
        p += 2
        if sz == 0:
            rle_cnt = int.from_bytes(ips_bytes[p : p + 2], "big")
            val = ips_bytes[p + 2]
            p += 3
            if off + rle_cnt > len(out):
                out.extend(b"\x00" * (off + rle_cnt - len(out)))
            out[off : off + rle_cnt] = bytes([val]) * rle_cnt
        else:
            data = ips_bytes[p : p + sz]
            p += sz
            if off + sz > len(out):
                out.extend(b"\x00" * (off + sz - len(out)))
            out[off : off + sz] = data
    return bytes(out)


class SpaceAllocator:
    """Tracks allocations in free/reclaimed ROM spans to guarantee zero overlaps."""

    def __init__(self, regions: Sequence[Tuple[int, int]] = DEFAULT_FREE_REGIONS):
        self.regions: List[List[int]] = [[s, e] for s, e in regions]  # [cursor, end]
        self.starts: List[int] = [s for s, _ in regions]
        self.allocs: List[Tuple[str, int, int]] = []

    def alloc(self, size: int, label: str, align: int = 2) -> int:
        for i, (cur, end) in enumerate(self.regions):
            aligned = (cur + align - 1) & ~(align - 1)
            if aligned + size <= end:
                self.regions[i][0] = aligned + size
                self.allocs.append((label, aligned, aligned + size))
                return aligned
        rem = sum(e - c for c, e in self.regions)
        raise MemoryError(f"Out of ROM free space allocating {size}B for {label} ({rem}B left)")

    def add_region(self, start: int, end: int) -> None:
        if end > start:
            self.regions.append([start, end])
            self.starts.append(start)

    def summary(self) -> List[str]:
        lines = []
        for (s0, (cur, end)) in zip(self.starts, self.regions):
            lines.append(
                f"  0x{s0:06X}..0x{end:06X}: used {cur - s0} / {end - s0} B ({end - cur} B free)"
            )
        return lines


def patch_block_and_relocate(
    rom: bytearray,
    alloc: SpaceAllocator,
    orig_start: int,
    orig_end: int,
    new_blob: bytes,
    ptr_sites: Sequence[int],
    label: str,
    pad_byte: int = 0x00,
) -> int:
    """Write new_blob in-place if <= orig span, else allocate in free space and update ptr_sites.

    Every ptr_site must currently hold the exact 32-bit BE value `orig_start`.
    Returns the final address of new_blob.
    """
    for site in ptr_sites:
        cur = struct.unpack_from(">I", rom, site)[0]
        if cur != orig_start:
            raise ValueError(
                f"{label}: ptr site 0x{site:06X} has 0x{cur:06X}, expected 0x{orig_start:06X}"
            )

    orig_span = orig_end - orig_start
    if len(new_blob) <= orig_span:
        rom[orig_start : orig_start + len(new_blob)] = new_blob
        if len(new_blob) < orig_span:
            rom[orig_start + len(new_blob) : orig_end] = bytes([pad_byte]) * (
                orig_span - len(new_blob)
            )
        return orig_start

    # Relocate to free space and reclaim original block
    new_addr = alloc.alloc(len(new_blob), label=label, align=2)
    rom[new_addr : new_addr + len(new_blob)] = new_blob
    rom[orig_start:orig_end] = bytes([pad_byte]) * orig_span
    alloc.add_region(orig_start, orig_end)
    for site in ptr_sites:
        struct.pack_into(">I", rom, site, new_addr)
    return new_addr


def bgr555_to_rgb(word: int) -> Tuple[int, int, int]:
    """Convert Super A'Can 15-bit xBBBBBGGGGGRRRRR CGRAM word to 24-bit RGB."""
    r = ((word >> 0) & 0x1F) * 255 // 31
    g = ((word >> 5) & 0x1F) * 255 // 31
    b = ((word >> 10) & 0x1F) * 255 // 31
    return (r, g, b)


def decode_4bpp_tiles(data: bytes, has_word_count: bool = False) -> List[List[int]]:
    """Decode packed 4bpp 8x8 tiles (2 pixels/byte, high nibble left) into 64-entry index lists."""
    tdata = data[2:] if has_word_count else data
    if len(tdata) % 32 != 0:
        raise ValueError(f"Tile data length {len(tdata)} not multiple of 32")
    tiles: List[List[int]] = []
    for t in range(len(tdata) // 32):
        base = t * 32
        pix: List[int] = []
        for b in tdata[base : base + 32]:
            pix.append((b >> 4) & 0xF)
            pix.append(b & 0xF)
        tiles.append(pix)
    return tiles


def encode_4bpp_tiles(tiles: Sequence[Sequence[int]], word_count_hdr: Optional[int] = None) -> bytes:
    """Encode 64-entry 4bpp tiles back into packed bytes (optional leading word-count header)."""
    out = bytearray()
    if word_count_hdr is not None:
        out.extend(struct.pack(">H", word_count_hdr))
    for tp in tiles:
        if len(tp) != 64:
            raise ValueError(f"Tile pixel count {len(tp)} != 64")
        for i in range(0, 64, 2):
            out.append(((tp[i] & 0xF) << 4) | (tp[i + 1] & 0xF))
    return bytes(out)
