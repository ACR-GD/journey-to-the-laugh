"""Graphic asset localizers for Journey to the Laugh (Super A'Can).

Covers all 14 localized pre-rendered tilemaps/sprites:
1. Title Logo (d222 tiles + d222 40x30 map)
2. Title Menu Sprites (d222 tiles + fixed 232B tilemap + DMA word-count patch)
3. Password Screen Plaque (d222 tiles + d222 40x30 map w/ 0028001E header)
4. Intro Gift Box Label ("SALTED CRACKERS", d222 tiles + d222 20x15 map)
5. Game Over Plaque (d222 tiles + d222 40x30 map w/ 0028001E header)
6. Ending Scroll-box Screens 1..9 (d222 wc+tiles + d222 64x32 map)
"""

from __future__ import annotations

import json
import struct
from collections import Counter, deque
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Set, Tuple

import jttl_d222
import jttl_font
import jttl_rom


# Compact 4x7 crisp uppercase bitmap glyphs for small labels (e.g. Gift Box)
_MINI_4X7: Dict[str, Tuple[str, ...]] = {
    " ": ("....", "....", "....", "....", "....", "....", "...."),
    "A": (".##.", "#..#", "#..#", "####", "#..#", "#..#", "#..#"),
    "C": (".###", "#...", "#...", "#...", "#...", "#...", ".###"),
    "D": ("###.", "#..#", "#..#", "#..#", "#..#", "#..#", "###."),
    "E": ("####", "#...", "#...", "###.", "#...", "#...", "####"),
    "K": ("#..#", "#.#.", "##..", "#...", "##..", "#.#.", "#..#"),
    "L": ("#...", "#...", "#...", "#...", "#...", "#...", "####"),
    "R": ("###.", "#..#", "#..#", "###.", "#.#.", "#..#", "#..#"),
    "S": (".###", "#...", ".##.", "..#.", "...#", "#..#", ".##."),
    "T": ("####", ".#..", ".#..", ".#..", ".#..", ".#..", ".#.."),
}


def _render_tilemap_to_grid(
    tiles: Sequence[Sequence[int]],
    m_words: Sequence[int],
    w_tiles: int,
    h_tiles: int,
    fill_oob: int = 0,
) -> List[List[int]]:
    """Decode tilemap + 4bpp tiles into a (h_tiles*8) x (w_tiles*8) palette-index grid."""
    grid = [[fill_oob] * (w_tiles * 8) for _ in range(h_tiles * 8)]
    for ty in range(h_tiles):
        for tx in range(w_tiles):
            mw = m_words[ty * w_tiles + tx]
            ti = mw & 0x3FF
            vf = bool(mw & 0x400)  # ppu.cpp: bit 10 = flip_v
            hf = bool(mw & 0x800)  # ppu.cpp: bit 11 = flip_h
            tp = tiles[ti] if ti < len(tiles) else None
            if tp is None:
                continue
            for py in range(8):
                sy = (7 - py) if vf else py
                for px in range(8):
                    sx = (7 - px) if hf else px
                    grid[ty * 8 + py][tx * 8 + px] = tp[sy * 8 + sx]
    return grid


def _commit_modified_cells(
    tiles: List[List[int]],
    m_words: List[int],
    map_stride: int,
    visible_h: int,
    visible_w: int,
    grid: List[List[int]],
    modified_cells: Set[Tuple[int, int]],
    bank_for_cell: Dict[Tuple[int, int], int] | int,
) -> None:
    """Update tiles and m_words for modified_cells, safely preserving outside tiles."""
    used_outside: Set[int] = {0}
    max_outside_ti = 0
    for ty in range(len(m_words) // map_stride):
        for tx in range(map_stride):
            if (tx, ty) in modified_cells:
                continue
            ti = m_words[ty * map_stride + tx] & 0x3FF
            used_outside.add(ti)
            if ti > max_outside_ti:
                max_outside_ti = ti

    # Ensure tiles covers any outside sentinel tile index (e.g. end1 uses tile 0xE8=232)
    while len(tiles) <= max_outside_ti:
        tiles.append([0] * 64)

    reclaimable = deque(ti for ti in range(1, len(tiles)) if ti not in used_outside)

    hash_to_ti: Dict[Tuple[int, ...], int] = {}
    for ti in sorted(used_outside):
        if ti < len(tiles):
            key = tuple(tiles[ti])
            if key not in hash_to_ti:
                hash_to_ti[key] = ti

    for ty in range(visible_h):
        for tx in range(visible_w):
            if (tx, ty) not in modified_cells:
                continue
            tp = [
                grid[ty * 8 + py][tx * 8 + px]
                for py in range(8)
                for px in range(8)
            ]
            key = tuple(tp)
            ti = hash_to_ti.get(key)
            if ti is None:
                if reclaimable:
                    ti = reclaimable.popleft()
                    tiles[ti] = tp
                else:
                    ti = len(tiles)
                    tiles.append(tp)
                hash_to_ti[key] = ti

            if isinstance(bank_for_cell, int):
                bank = bank_for_cell
            else:
                bank = bank_for_cell[(tx, ty)]
            m_words[ty * map_stride + tx] = (bank << 12) | ti

    if len(tiles) > 0x400:
        raise ValueError(f"Tile count {len(tiles)} exceeds 10-bit Super A'Can limit 1024")


def _cells_from_pixel_rect(
    x0: int, y0: int, x1: int, y1: int, w_tiles: int, h_tiles: int
) -> Set[Tuple[int, int]]:
    tx0 = max(0, x0 // 8)
    tx1 = min(w_tiles - 1, (x1 - 1) // 8)
    ty0 = max(0, y0 // 8)
    ty1 = min(h_tiles - 1, (y1 - 1) // 8)
    return {(tx, ty) for ty in range(ty0, ty1 + 1) for tx in range(tx0, tx1 + 1)}


def _draw_scaled_proportional(
    grid: List[List[int]],
    text: str,
    x0: int,
    y0: int,
    scale_x: float,
    scale_y: float,
    row_colors: Sequence[int],
    outline_idx: int | None = None,
    outline_r: int = 1,
    spacing: int = 1,
    shadow_idx: int | None = None,
    shadow_dx: int = 0,
    shadow_dy: int = 0,
) -> Tuple[int, int, int, int]:
    """Draw scaled crisp bitmap text onto grid using trimmed 11px proportional glyphs."""
    h = len(grid)
    w = len(grid[0])

    # Build unscaled binary mask first
    bms = [jttl_font.glyph_trimmed_bitmap(ch) for ch in text]
    raw_w = sum(len(bm[0]) for bm in bms) + spacing * max(0, len(text) - 1)
    raw_h = 11
    raw = [[0] * raw_w for _ in range(raw_h)]
    cx = 0
    for bm in bms:
        gw = len(bm[0])
        for ry in range(raw_h):
            for rx in range(gw):
                if bm[ry][rx]:
                    raw[ry][cx + rx] = 1
        cx += gw + spacing

    out_w = max(1, round(raw_w * scale_x))
    out_h = max(1, round(raw_h * scale_y))
    fg_pts: List[Tuple[int, int, int]] = []
    for dy in range(out_h):
        sy = min(raw_h - 1, int(dy / scale_y))
        cidx = row_colors[min(len(row_colors) - 1, (dy * len(row_colors)) // out_h)]
        for dx in range(out_w):
            sx = min(raw_w - 1, int(dx / scale_x))
            if raw[sy][sx]:
                px, py = x0 + dx, y0 + dy
                if 0 <= px < w and 0 <= py < h:
                    fg_pts.append((px, py, cidx))

    if shadow_idx is not None and (shadow_dx or shadow_dy):
        for px, py, _ in fg_pts:
            sx, sy = px + shadow_dx, py + shadow_dy
            if 0 <= sx < w and 0 <= sy < h:
                grid[sy][sx] = shadow_idx

    if outline_idx is not None and outline_r > 0:
        r2 = outline_r * outline_r + 1
        for px, py, _ in fg_pts:
            for oy in range(-outline_r, outline_r + 1):
                for ox in range(-outline_r, outline_r + 1):
                    if ox * ox + oy * oy <= r2:
                        nx, ny = px + ox, py + oy
                        if 0 <= nx < w and 0 <= ny < h:
                            grid[ny][nx] = outline_idx

    for px, py, cidx in fg_pts:
        grid[py][px] = cidx

    pad = outline_r if outline_idx is not None else 0
    return (x0 - pad, y0 - pad, x0 + out_w + pad, y0 + out_h + pad)


def _heal_cloud_region(grid: List[List[int]], mask: List[List[bool]]) -> None:
    """Inpaint masked TitleLogo Chinese stroke pixels seamlessly from cloud/sky neighbors."""
    h = len(grid)
    w = len(grid[0])
    q: deque[Tuple[int, int]] = deque()
    filled = [[not mask[y][x] for x in range(w)] for y in range(h)]

    for y in range(h):
        for x in range(w):
            if not filled[y][x]:
                # Seed pixels adjacent to unmasked background
                for oy in (-1, 0, 1):
                    for ox in (-1, 0, 1):
                        nx, ny = x + ox, y + oy
                        if 0 <= nx < w and 0 <= ny < h and filled[ny][nx]:
                            q.append((x, y))
                            break
                    else:
                        continue
                    break

    seen = set(q)
    # Multi-pass wave propagation from cloud (prefer 15/7/8 inside cloud, 0 outside)
    while q:
        batch = list(q)
        q.clear()
        updates: List[Tuple[int, int, int]] = []
        for x, y in batch:
            nbrs = []
            for oy in (-1, 0, 1):
                for ox in (-1, 0, 1):
                    if ox == 0 and oy == 0:
                        continue
                    nx, ny = x + ox, y + oy
                    if 0 <= nx < w and 0 <= ny < h and filled[ny][nx]:
                        nbrs.append(grid[ny][nx])
            if not nbrs:
                continue
            # Prefer cloud pixels over stray 0 inside interior holes
            cloud_nbrs = [c for c in nbrs if c != 0]
            if len(cloud_nbrs) >= 2:
                val = Counter(cloud_nbrs).most_common(1)[0][0]
            else:
                val = Counter(nbrs).most_common(1)[0][0]
            updates.append((x, y, val))

        for x, y, val in updates:
            grid[y][x] = val
            filled[y][x] = True
            for oy in (-1, 0, 1):
                for ox in (-1, 0, 1):
                    nx, ny = x + ox, y + oy
                    if 0 <= nx < w and 0 <= ny < h and not filled[ny][nx] and (nx, ny) not in seen:
                        seen.add((nx, ny))
                        q.append((nx, ny))


def patch_title_logo(rom: bytearray, alloc: jttl_rom.SpaceAllocator, tr: Dict) -> Dict:
    """Replace '嘻遊記' in TitleLogo (0x0B54CC + 0x0B51A8) with 'JOURNEY / TO THE / LAUGH'."""
    t_off, t_end, t_ptrs = 0x0B54CC, 0x0B69BF, [0x006590]
    m_off, m_end, m_ptrs = 0x0B51A8, 0x0B54CB, [0x00659C]

    t_raw, _ = jttl_d222.decompress_d222(rom, t_off)
    m_raw, _ = jttl_d222.decompress_d222(rom, m_off)
    tiles = jttl_rom.decode_4bpp_tiles(t_raw)
    m_words = list(struct.unpack(f">{40*30}H", m_raw))
    banks = {(tx, ty): (m_words[ty * 40 + tx] >> 12) & 0xF for ty in range(30) for tx in range(40)}

    grid = _render_tilemap_to_grid(tiles, m_words, 40, 30)

    # Identify pixels of original Chinese title (preserving Peach sun orb at y<63, x>=180 and copyright rows 26..28)
    title_cols = {1, 2, 3, 4, 6, 9, 11, 12, 13, 14}
    erase_mask = [[False] * 320 for _ in range(240)]
    for y in range(26, 168):
        for x in range(24, 296):
            if y < 63 and x >= 180:
                continue
            if grid[y][x] in title_cols:
                erase_mask[y][x] = True

    _heal_cloud_region(grid, erase_mask)

    lines = tr["graphics"]["title_logo"]
    # Render red-gold "JOURNEY" left of Peach, gold "TO THE" middle, and royal-blue "LAUGH" on bright cloud center
    j_w = round(jttl_font.measure_proportional_11px(lines[0]) * 2.25)
    t_w = round(jttl_font.measure_proportional_11px(lines[1]) * 1.85)
    l_w = round(jttl_font.measure_proportional_11px(lines[2]) * 3.2)

    _draw_scaled_proportional(
        grid, lines[0], x0=max(30, 102 - j_w // 2), y0=38,
        scale_x=2.25, scale_y=2.6,
        row_colors=[14, 14, 3, 13, 12, 12, 6],
        outline_idx=2, outline_r=2, spacing=1,
    )
    _draw_scaled_proportional(
        grid, lines[1], x0=156 - t_w // 2, y0=70,
        scale_x=1.85, scale_y=1.95,
        row_colors=[14, 14, 3, 13, 12],
        outline_idx=2, outline_r=2, spacing=1,
    )
    _draw_scaled_proportional(
        grid, lines[2], x0=160 - l_w // 2, y0=95,
        scale_x=3.2, scale_y=3.4,
        row_colors=[11, 11, 1, 1, 4, 4],
        outline_idx=2, outline_r=2, spacing=1,
    )

    mod_cells = _cells_from_pixel_rect(24, 24, 296, 168, 40, 30)
    _commit_modified_cells(tiles, m_words, 40, 30, 40, grid, mod_cells, banks)

    new_t_raw = jttl_rom.encode_4bpp_tiles(tiles)
    new_m_raw = struct.pack(f">{40*30}H", *m_words)
    new_t_comp = jttl_d222.encode_d222_best(new_t_raw, rom)
    new_m_comp = jttl_d222.encode_d222_best(new_m_raw, rom)

    t_addr = jttl_rom.patch_block_and_relocate(rom, alloc, t_off, t_end, new_t_comp, t_ptrs, "TitleLogoTiles")
    m_addr = jttl_rom.patch_block_and_relocate(rom, alloc, m_off, m_end, new_m_comp, m_ptrs, "TitleLogoMap")
    return {
        "ntiles": len(tiles),
        "t_addr": t_addr, "t_bytes": len(new_t_comp),
        "m_addr": m_addr, "m_bytes": len(new_m_comp),
    }


def patch_title_menu(rom: bytearray, alloc: jttl_rom.SpaceAllocator, tr: Dict) -> Dict:
    """Replace Title Menu labels (0x00D1E8 d222 tiles + 0x00D100 fixed 232B tilemap)."""
    t_off, t_end, t_ptrs = 0x00D1E8, 0x00D6C4, [0x006F4A]
    map_off = 0x00D100
    dma_cnt_off = 0x006F86

    t_raw, _ = jttl_d222.decompress_d222(rom, t_off)
    tiles = jttl_rom.decode_4bpp_tiles(t_raw)
    tm_words = list(struct.unpack_from(">116H", rom, map_off))

    # Preserve spinner/decor words [0..19] and bullet-icon cols 0..1 of each 2x16 item
    used_outside: Set[int] = {0}
    for i in range(20):
        used_outside.add(tm_words[i] & 0x3FF)
    for item in range(3):
        base = 20 + item * 32
        for r in range(2):
            for c in (0, 1):
                used_outside.add(tm_words[base + r * 16 + c] & 0x3FF)

    reclaimable = deque(ti for ti in range(1, len(tiles)) if ti not in used_outside)
    hash_to_ti: Dict[Tuple[int, ...], int] = {
        tuple(tiles[ti]): ti for ti in sorted(used_outside)
    }

    # Gradient matches original palette 15 (11 red-orange -> 12 -> 13 gold -> 9 cream -> 13 -> 12 -> 11) + 10 black outline
    row_pal_13 = [11, 11, 11, 12, 13, 9, 9, 13, 12, 11, 11]
    labels = tr["graphics"]["title_menu"]
    for item, label in enumerate(labels):
        canvas = [[0] * 112 for _ in range(16)]  # 14 tile cols (2..15) x 2 rows
        _draw_scaled_proportional(
            canvas, label, x0=1, y0=2,
            scale_x=1.0, scale_y=1.0,
            row_colors=row_pal_13,
            outline_idx=10, outline_r=1, spacing=1,
        )
        base = 20 + item * 32
        for r in range(2):
            for c in range(2, 16):
                cx = c - 2
                tp = [canvas[r * 8 + py][cx * 8 + px] for py in range(8) for px in range(8)]
                if all(v == 0 for v in tp):
                    tm_words[base + r * 16 + c] = 0xF000
                    continue
                key = tuple(tp)
                ti = hash_to_ti.get(key)
                if ti is None:
                    if reclaimable:
                        ti = reclaimable.popleft()
                        tiles[ti] = tp
                    else:
                        ti = len(tiles)
                        tiles.append(tp)
                    hash_to_ti[key] = ti
                tm_words[base + r * 16 + c] = 0xF000 | ti

    # Re-pack unused reclaimable tail if contiguous from end to keep DMA minimal
    max_used = max(
        {0}
        | {w & 0x3FF for w in tm_words}
        | used_outside
    )
    tiles = tiles[: max_used + 1]
    if len(tiles) > 0x400:
        raise ValueError(f"TitleMenu tile count {len(tiles)} too large")

    new_t_raw = jttl_rom.encode_4bpp_tiles(tiles)
    new_t_comp = jttl_d222.encode_d222_best(new_t_raw, rom)

    rom[map_off : map_off + 232] = struct.pack(">116H", *tm_words)
    struct.pack_into(">H", rom, dma_cnt_off, len(tiles) * 16 - 1)
    t_addr = jttl_rom.patch_block_and_relocate(rom, alloc, t_off, t_end, new_t_comp, t_ptrs, "TitleMenuTiles")
    return {"ntiles": len(tiles), "dma_cnt": len(tiles) * 16 - 1, "t_addr": t_addr, "t_bytes": len(new_t_comp)}


def patch_password_plaque(rom: bytearray, alloc: jttl_rom.SpaceAllocator, tr: Dict) -> Dict:
    """Replace wooden signboard text '過關密碼' with 'PASSWORD'."""
    t_off, t_end, t_ptrs = 0x05560E, 0x055C51, [0x00CE42]
    m_off, m_end, m_ptrs = 0x02AAA2, 0x02AC48, [0x00CE46, 0x00CE4A, 0x00CE4E]

    t_raw, _ = jttl_d222.decompress_d222(rom, t_off)
    m_raw, _ = jttl_d222.decompress_d222(rom, m_off)
    hdr = m_raw[:4]  # 0028 001E
    tiles = jttl_rom.decode_4bpp_tiles(t_raw)
    m_words = list(struct.unpack(f">{40*30}H", m_raw[4:]))

    grid = _render_tilemap_to_grid(tiles, m_words, 40, 30)

    # Clear full interior wood face (x=74..231, y=29..58) to wood bg idx 5 (preserves rounded corners & rims)
    for y in range(29, 59):
        for x in range(74, 232):
            grid[y][x] = 5

    label = tr["graphics"]["password_plaque"]
    tw = round(jttl_font.measure_proportional_11px(label) * 1.85)
    x0 = 74 + (158 - tw) // 2
    _draw_scaled_proportional(
        grid, label, x0=x0, y0=34,
        scale_x=1.85, scale_y=1.85,
        row_colors=[13],
        outline_idx=1, outline_r=1, spacing=1,
        shadow_idx=6, shadow_dx=1, shadow_dy=1,
    )

    mod_cells = _cells_from_pixel_rect(74, 29, 232, 59, 40, 30)
    _commit_modified_cells(tiles, m_words, 40, 30, 40, grid, mod_cells, 4)

    new_t_comp = jttl_d222.encode_d222_best(jttl_rom.encode_4bpp_tiles(tiles), rom)
    new_m_comp = jttl_d222.encode_d222_best(hdr + struct.pack(f">{40*30}H", *m_words), rom)

    t_addr = jttl_rom.patch_block_and_relocate(rom, alloc, t_off, t_end, new_t_comp, t_ptrs, "PasswordPlaqueTiles")
    m_addr = jttl_rom.patch_block_and_relocate(rom, alloc, m_off, m_end, new_m_comp, m_ptrs, "PasswordPlaqueMap")
    return {"ntiles": len(tiles), "t_addr": t_addr, "t_bytes": len(new_t_comp), "m_addr": m_addr, "m_bytes": len(new_m_comp)}


def _draw_mini_4x7(grid: List[List[int]], text: str, x0: int, y0: int, fg_idx: int, spacing: int = 1) -> None:
    cx = x0
    for ch in text:
        bm = _MINI_4X7[ch]
        for dy, row in enumerate(bm):
            for dx, c in enumerate(row):
                if c != ".":
                    grid[y0 + dy][cx + dx] = fg_idx
        cx += len(bm[0]) + spacing


def patch_gift_box(rom: bytearray, alloc: jttl_rom.SpaceAllocator, tr: Dict) -> Dict:
    """Replace Gift Box wrapper label with 'SALTED / CRACKERS'."""
    t_off, t_end, t_ptrs = 0x0AD47E, 0x0AE107, [0x00582C]
    m_off, m_end, m_ptrs = 0x0AD31C, 0x0AD47D, [0x005838]

    t_raw, _ = jttl_d222.decompress_d222(rom, t_off)
    m_raw, _ = jttl_d222.decompress_d222(rom, m_off)
    tiles = jttl_rom.decode_4bpp_tiles(t_raw)
    m_words = list(struct.unpack(f">{20*15}H", m_raw))
    banks = {(tx, ty): (m_words[ty * 20 + tx] >> 12) & 0xF for ty in range(15) for tx in range(20)}

    grid = _render_tilemap_to_grid(tiles, m_words, 20, 15)

    # Clear Chinese ink (black idx 2) on top label (x=49..86, y=42..57), bridge row y=58 (x=51..94),
    # and bottom label (x=57..100, y=59..72) while preserving paper/ribbon shading
    for y in range(42, 58):
        for x in range(49, 87):
            if grid[y][x] == 2:
                grid[y][x] = 8
    for x in range(51, 95):
        if grid[58][x] == 2:
            grid[58][x] = 8
    for y in range(59, 73):
        for x in range(57, 101):
            if grid[y][x] == 2:
                grid[y][x] = 8

    line1, line2 = tr["graphics"]["gift_box"]
    w1 = len(line1) * 5 - 1
    w2 = len(line2) * 5 - 1
    _draw_mini_4x7(grid, line1, x0=49 + (38 - w1) // 2, y0=46, fg_idx=2, spacing=1)
    _draw_mini_4x7(grid, line2, x0=57 + (44 - w2) // 2, y0=62, fg_idx=2, spacing=1)

    mod_cells = _cells_from_pixel_rect(49, 42, 101, 73, 20, 15)
    _commit_modified_cells(tiles, m_words, 20, 15, 20, grid, mod_cells, banks)

    new_t_comp = jttl_d222.encode_d222_best(jttl_rom.encode_4bpp_tiles(tiles), rom)
    new_m_comp = jttl_d222.encode_d222_best(struct.pack(f">{20*15}H", *m_words), rom)

    t_addr = jttl_rom.patch_block_and_relocate(rom, alloc, t_off, t_end, new_t_comp, t_ptrs, "GiftBoxTiles")
    m_addr = jttl_rom.patch_block_and_relocate(rom, alloc, m_off, m_end, new_m_comp, m_ptrs, "GiftBoxMap")
    return {"ntiles": len(tiles), "t_addr": t_addr, "t_bytes": len(new_t_comp), "m_addr": m_addr, "m_bytes": len(new_m_comp)}


def patch_game_over(rom: bytearray, alloc: jttl_rom.SpaceAllocator, tr: Dict) -> Dict:
    """Replace '遊戲結束' between periwinkle '@' swirls with 'GAME OVER'."""
    t_off, t_end, t_ptrs = 0x0FBCFA, 0x0FBF00, [0x0EE700]
    m_off, m_end, m_ptrs = 0x0FBF00, 0x0FBFC3, [0x0EE70C]

    t_raw, _ = jttl_d222.decompress_d222(rom, t_off)
    m_raw, _ = jttl_d222.decompress_d222(rom, m_off)
    hdr = m_raw[:4]  # 0028 001E
    tiles = jttl_rom.decode_4bpp_tiles(t_raw)
    m_words = list(struct.unpack(f">{40*30}H", m_raw[4:]))

    grid = _render_tilemap_to_grid(tiles, m_words, 40, 30)

    # Clear ONLY gold pixels (x=110..205, y=197..219) leaving '@' swirls at x=94..109 and x=206..220 intact
    for y in range(197, 220):
        for x in range(110, 206):
            grid[y][x] = 0

    label = tr["graphics"]["game_over"]
    tw = round(jttl_font.measure_proportional_11px(label) * 1.45)
    _draw_scaled_proportional(
        grid, label, x0=110 + (96 - tw) // 2, y0=201,
        scale_x=1.45, scale_y=1.45,
        row_colors=[2],
        outline_idx=None, spacing=1,
    )

    mod_cells = _cells_from_pixel_rect(110, 197, 206, 220, 40, 30)
    _commit_modified_cells(tiles, m_words, 40, 30, 40, grid, mod_cells, 15)

    new_t_comp = jttl_d222.encode_d222_best(jttl_rom.encode_4bpp_tiles(tiles), rom)
    new_m_comp = jttl_d222.encode_d222_best(hdr + struct.pack(f">{40*30}H", *m_words), rom)

    t_addr = jttl_rom.patch_block_and_relocate(rom, alloc, t_off, t_end, new_t_comp, t_ptrs, "GameOverTiles")
    m_addr = jttl_rom.patch_block_and_relocate(rom, alloc, m_off, m_end, new_m_comp, m_ptrs, "GameOverMap")
    return {"ntiles": len(tiles), "t_addr": t_addr, "t_bytes": len(new_t_comp), "m_addr": m_addr, "m_bytes": len(new_m_comp)}


_ENDING_SPECS = [
    ("end1", 0x0EF7CE, 0x0F020F, [0x0EEFA8, 0x0EEFBE], 0x0F0210, 0x0F042C, [0x0EEFAE], 14),
    ("end2", 0x0F042C, 0x0F15CF, [0x0EEFF8, 0x0EF03E], 0x0F15D0, 0x0F186C, [0x0EEFFE, 0x0EF044], 9),
    ("end3", 0x0F85A8, 0x0F9EF2, [0x0EF064, 0x0EF09E], 0x0F9EF2, 0x0FA1B9, [0x0EF06A, 0x0EF0A4], 9),
    ("end4", 0x0FA1BA, 0x0FB9FA, [0x0EF0C4, 0x0EF0EC], 0x0FB9FA, 0x0FBCDA, [0x0EF0CA, 0x0EF0F2], 9),
    ("end5", 0x0F186C, 0x0F2F71, [0x0EF112], 0x0F2F72, 0x0F327A, [0x0EF118], 9),
    ("end6", 0x0F327A, 0x0F486E, [0x0EF14C], 0x0F486E, 0x0F4B5D, [0x0EF152], 9),
    ("end7", 0x0F4B5E, 0x0F61F3, [0x0EF17C], 0x0F61F4, 0x0F6521, [0x0EF182], 9),
    ("end8", 0x0F794A, 0x0F8398, [0x0EF1A4, 0x0EF1BA], 0x0F8398, 0x0F85A7, [0x0EF1AA], 14),
    ("end9", 0x0F6522, 0x0F768F, [0x0EF214], 0x0F7690, 0x0F794A, [0x0EF21A], 9),
]


def patch_ending_screens(rom: bytearray, alloc: jttl_rom.SpaceAllocator, tr: Dict) -> Dict[str, Dict]:
    """Localize all 9 Ending scroll-box screens (end1..end9)."""
    ending_tr = tr["graphics"]["ending"]
    results: Dict[str, Dict] = {}

    for name, t_off, t_end, t_ptrs, m_off, m_end, m_ptrs, fg_idx in _ENDING_SPECS:
        t_raw, _ = jttl_d222.decompress_d222(rom, t_off)
        m_raw, _ = jttl_d222.decompress_d222(rom, m_off)
        tiles = jttl_rom.decode_4bpp_tiles(t_raw, has_word_count=True)
        m_words = list(struct.unpack(f">{64*32}H", m_raw))

        grid = _render_tilemap_to_grid(tiles, m_words, 64, 32, fill_oob=6)

        # Clear entire parchment interior x=32..287, y=175..216 to parchment index 6
        # (leaves vertical wood scroll rollers at x<=30, x>=289 and horizontal edges y<=172, y>=217 intact)
        for y in range(175, 217):
            for x in range(32, 288):
                grid[y][x] = 6

        lines = ending_tr[name]
        y_starts = [191] if len(lines) == 1 else [182, 199]
        for ln, y0 in zip(lines, y_starts):
            w = jttl_font.measure_proportional_11px(ln, spacing=1)
            x0 = 32 + (256 - w) // 2
            jttl_font.render_proportional_11px(grid, ln, x0=x0, y0=y0, fg_idx=fg_idx, outline_idx=None, spacing=1)

        mod_cells = _cells_from_pixel_rect(32, 175, 288, 217, 40, 30)
        _commit_modified_cells(tiles, m_words, 64, 30, 40, grid, mod_cells, 10)

        new_t_raw = jttl_rom.encode_4bpp_tiles(tiles, word_count_hdr=len(tiles) * 16)
        new_m_raw = struct.pack(f">{64*32}H", *m_words)
        new_t_comp = jttl_d222.encode_d222_best(new_t_raw, rom)
        new_m_comp = jttl_d222.encode_d222_best(new_m_raw, rom)

        t_addr = jttl_rom.patch_block_and_relocate(rom, alloc, t_off, t_end, new_t_comp, t_ptrs, f"{name}Tiles")
        m_addr = jttl_rom.patch_block_and_relocate(rom, alloc, m_off, m_end, new_m_comp, m_ptrs, f"{name}Map")
        results[name] = {
            "ntiles": len(tiles),
            "t_addr": t_addr, "t_bytes": len(new_t_comp),
            "m_addr": m_addr, "m_bytes": len(new_m_comp),
        }
    return results


def apply_all_gfx_patches(rom: bytearray, alloc: jttl_rom.SpaceAllocator, translations_path: Path) -> Dict:
    """Apply all 14 graphic patches using a single SpaceAllocator."""
    tr = json.loads(translations_path.read_text(encoding="utf-8"))
    res: Dict[str, object] = {}
    res["title_menu"] = patch_title_menu(rom, alloc, tr)
    res["title_logo"] = patch_title_logo(rom, alloc, tr)
    res["password_plaque"] = patch_password_plaque(rom, alloc, tr)
    res["gift_box"] = patch_gift_box(rom, alloc, tr)
    res["game_over"] = patch_game_over(rom, alloc, tr)
    res["ending"] = patch_ending_screens(rom, alloc, tr)
    return res
