"""Static visual & bytecode verification sheet generator for Journey to the Laugh (EN).

Reads directly from build/Journey to the Laugh (EN).bin (and compares against original ROM):
- notes/verify_scenes.png: localized UI plaques, Title Logo + Menu, Gift Box, Game Over, End 1..9
- notes/verify_scripts.png: M68K script bytecode & 8x16 bitmap simulator output for all 35 scripts
"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from PIL import Image, ImageDraw

TOOLS_DIR = Path(__file__).resolve().parent
PROJ_DIR = TOOLS_DIR.parent
sys.path.insert(0, str(TOOLS_DIR))

import gfx_patchers
import jttl_d222
import jttl_rom
import jttl_text

BUILD_ROM_PATH = PROJ_DIR / "build" / "Journey to the Laugh (EN).bin"
TR_PATH = PROJ_DIR / "notes" / "translations_en.json"
SCENES_OUT = PROJ_DIR / "notes" / "verify_scenes.png"
SCRIPTS_OUT = PROJ_DIR / "notes" / "verify_scripts.png"


def _read_pal(cpu_rom: bytearray, off: int) -> List[Tuple[int, int, int]]:
    return [jttl_rom.bgr555_to_rgb(struct.unpack_from(">H", cpu_rom, off + 2 * i)[0]) for i in range(16)]


def _render_rgb_from_tilemap(
    tiles: Sequence[Sequence[int]],
    m_words: Sequence[int],
    w_tiles: int,
    h_tiles: int,
    pals_by_bank: Dict[int, List[Tuple[int, int, int]]],
    bg_rgb: Tuple[int, int, int] = (20, 24, 38),
    map_stride: int | None = None,
) -> Image.Image:
    stride = map_stride or w_tiles
    img = Image.new("RGB", (w_tiles * 8, h_tiles * 8), bg_rgb)
    px = img.load()
    for ty in range(h_tiles):
        for tx in range(w_tiles):
            mw = m_words[ty * stride + tx]
            ti = mw & 0x3FF
            bank = (mw >> 12) & 0xF
            vf = bool(mw & 0x400)
            hf = bool(mw & 0x800)
            pal = pals_by_bank.get(bank, pals_by_bank[next(iter(pals_by_bank))])
            tp = tiles[ti] if ti < len(tiles) else None
            if tp is None:
                continue
            for py in range(8):
                sy = (7 - py) if vf else py
                for pxx in range(8):
                    sx = (7 - pxx) if hf else pxx
                    cidx = tp[sy * 8 + sx]
                    if cidx != 0:
                        px[tx * 8 + pxx, ty * 8 + py] = pal[cidx]
    return img


def render_scenes_sheet(orig_cpu: bytearray, mod_cpu: bytearray) -> None:
    """Build notes/verify_scenes.png inspecting all 14 localized graphic assets."""
    tiles_pals: Dict[str, Image.Image] = {}

    # 1. Title Logo + Menu composited mockup (2x crisp zoom)
    t_addr = struct.unpack_from(">I", mod_cpu, 0x006590)[0]
    m_addr = struct.unpack_from(">I", mod_cpu, 0x00659C)[0]
    tl_tiles = jttl_rom.decode_4bpp_tiles(jttl_d222.decompress_d222(mod_cpu, t_addr)[0])
    tl_mw = list(struct.unpack(">1200H", jttl_d222.decompress_d222(mod_cpu, m_addr)[0]))
    tl_pal = _read_pal(mod_cpu, 0x0B5188)
    tl_img = _render_rgb_from_tilemap(
        tl_tiles, tl_mw, 40, 30,
        {14: tl_pal, 0: tl_pal}, bg_rgb=(28, 86, 176),
    ).crop((0, 0, 320, 240))

    # Overlay Title Menu items below logo preview
    tm_addr = struct.unpack_from(">I", mod_cpu, 0x006F4A)[0]
    tm_tiles = jttl_rom.decode_4bpp_tiles(jttl_d222.decompress_d222(mod_cpu, tm_addr)[0])
    tm_mw = list(struct.unpack_from(">116H", mod_cpu, 0x00D100))
    tm_pal = _read_pal(mod_cpu, 0x00CEF2)
    tm_imgs = []
    for item in range(3):
        sub_mw = tm_mw[20 + item * 32 : 20 + (item + 1) * 32]
        im = _render_rgb_from_tilemap(tm_tiles, sub_mw, 16, 2, {15: tm_pal}, bg_rgb=(18, 22, 42))
        tm_imgs.append(im)

    # Original Title Logo for side-by-side sanity compare
    otl_tiles = jttl_rom.decode_4bpp_tiles(jttl_d222.decompress_d222(orig_cpu, 0x0B54CC)[0])
    otl_mw = list(struct.unpack(">1200H", jttl_d222.decompress_d222(orig_cpu, 0x0B51A8)[0]))
    otl_img = _render_rgb_from_tilemap(otl_tiles, otl_mw, 40, 30, {14: tl_pal, 0: tl_pal}, bg_rgb=(28, 86, 176))

    # 2. Password Plaque crop + full
    pw_t_addr = struct.unpack_from(">I", mod_cpu, 0x00CE42)[0]
    pw_m_addr = struct.unpack_from(">I", mod_cpu, 0x00CE46)[0]
    pw_tiles = jttl_rom.decode_4bpp_tiles(jttl_d222.decompress_d222(mod_cpu, pw_t_addr)[0])
    pw_mraw = jttl_d222.decompress_d222(mod_cpu, pw_m_addr)[0]
    pw_mw = list(struct.unpack(">1200H", pw_mraw[4:]))
    pw_pal = _read_pal(mod_cpu, 0x0AE108)
    pw_img = _render_rgb_from_tilemap(pw_tiles, pw_mw, 40, 30, {4: pw_pal}, bg_rgb=(16, 20, 32))
    pw_crop = pw_img.crop((56, 16, 264, 72))

    # 3. Gift Box (160x120)
    gb_t_addr = struct.unpack_from(">I", mod_cpu, 0x00582C)[0]
    gb_m_addr = struct.unpack_from(">I", mod_cpu, 0x005838)[0]
    gb_tiles = jttl_rom.decode_4bpp_tiles(jttl_d222.decompress_d222(mod_cpu, gb_t_addr)[0])
    gb_mw = list(struct.unpack(">300H", jttl_d222.decompress_d222(mod_cpu, gb_m_addr)[0]))
    gb_pal = _read_pal(mod_cpu, 0x0AD2FC)
    gb_img = _render_rgb_from_tilemap(gb_tiles, gb_mw, 20, 15, {3: gb_pal}, bg_rgb=(255, 255, 255))

    # 4. Game Over crop + swirls
    go_t_addr = struct.unpack_from(">I", mod_cpu, 0x0EE700)[0]
    go_m_addr = struct.unpack_from(">I", mod_cpu, 0x0EE70C)[0]
    go_tiles = jttl_rom.decode_4bpp_tiles(jttl_d222.decompress_d222(mod_cpu, go_t_addr)[0])
    go_mw = list(struct.unpack(">1200H", jttl_d222.decompress_d222(mod_cpu, go_m_addr)[0][4:]))
    go_pal = _read_pal(mod_cpu, 0x0FBCDA)
    go_img = _render_rgb_from_tilemap(go_tiles, go_mw, 40, 30, {15: go_pal}, bg_rgb=(0, 0, 0))
    go_crop = go_img.crop((80, 184, 240, 232))

    # 5. Endings 1..9 full palette from 0x0EF42E (banks 0..15) & scroll-box crops
    end_pals = {b: _read_pal(mod_cpu, 0x0EF42E + b * 32) for b in range(16)}
    end_crops: List[Tuple[str, Image.Image]] = []
    end_full_1 = None
    for name, _, _, t_ptrs, _, _, m_ptrs, _ in gfx_patchers._ENDING_SPECS:
        ta = struct.unpack_from(">I", mod_cpu, t_ptrs[0])[0]
        ma = struct.unpack_from(">I", mod_cpu, m_ptrs[0])[0]
        etiles = jttl_rom.decode_4bpp_tiles(jttl_d222.decompress_d222(mod_cpu, ta)[0], has_word_count=True)
        emw = list(struct.unpack(">2048H", jttl_d222.decompress_d222(mod_cpu, ma)[0]))
        eimg = _render_rgb_from_tilemap(etiles, emw, 40, 30, end_pals, bg_rgb=(16, 16, 24), map_stride=64)
        if end_full_1 is None:
            end_full_1 = eimg
        end_crops.append((name, eimg.crop((16, 168, 304, 224))))

    # Compose contact sheet (clean 1480px wide canvas)
    sheet_w = 1480
    sheet_h = 1280
    sheet = Image.new("RGB", (sheet_w, sheet_h), (18, 20, 28))
    draw = ImageDraw.Draw(sheet)

    def _put(im: Image.Image, x: int, y: int, label: str, zoom: int = 1) -> int:
        draw.text((x, y), label, fill=(240, 220, 120))
        bim = im.resize((im.width * zoom, im.height * zoom), Image.NEAREST) if zoom > 1 else im
        sheet.paste(bim, (x, y + 14))
        return y + 14 + bim.height + 14

    # Top row: Orig TitleLogo | Localized TitleLogo | Title Menu x3 + PW + GiftBox + GameOver
    _put(otl_img, 20, 14, "ORIG TitleLogo (320x240)")
    _put(tl_img, 360, 14, "EN TitleLogo (320x240)")

    # Right panel top: Title Menu 3 items @ 3x
    my = 14
    draw.text((700, my), "EN Title Menu Sprites (3x zoom)", fill=(240, 220, 120))
    my += 18
    for idx, tim in enumerate(tm_imgs):
        z = tim.resize((tim.width * 3, tim.height * 3), Image.NEAREST)
        sheet.paste(z, (700, my))
        my += z.height + 6

    # GiftBox 2x right next to Password & GameOver
    _put(gb_img, 1100, 14, "EN Gift Box (2x zoom, 160x120)", zoom=2)
    _put(pw_crop, 700, 194, "EN Password Plaque (2x zoom)", zoom=2)
    _put(go_crop, 700, 340, "EN Game Over (2x zoom)", zoom=2)

    # Ending 1..9 scroll crops in 2 columns (2x zoom -> 576x112 each) + End1 full
    assert end_full_1 is not None
    _put(end_full_1, 20, 282, "EN end1 Full Scene (320x240)")
    _put(pw_img, 360, 282, "EN Password Plaque Context (320x240)")

    ey_start = 560
    for idx, (ename, eim) in enumerate(end_crops):
        col = idx % 2
        row = idx // 2
        ex = 20 + col * 640
        ey = ey_start + row * 140
        _put(eim, ex, ey, f"EN {ename} scroll box (2x zoom)", zoom=2)

    SCENES_OUT.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(SCENES_OUT)


def _sim_script_bytes(mod_cpu: bytearray, addr: int, init_x: int, init_y: int) -> List[List[Tuple[int, int, int]]]:
    """Execute compiled text_interp_v2 script bytes directly from built ROM.

    Returns list of pages; each page is a list of (tile_x, tile_y, ascii_code).
    Raises AssertionError on unknown opcode or screen spill.
    """
    pages: List[List[Tuple[int, int, int]]] = [[]]
    bx, by = init_x, init_y
    cx, cy = init_x, init_y
    p = addr
    steps = 0
    while True:
        steps += 1
        assert steps < 2000, f"Infinite script loop at 0x{addr:06X}"
        b = mod_cpu[p]
        p += 1
        if b >= 0x20:
            assert b <= 0x7E, f"Invalid char byte 0x{b:02X} in script 0x{addr:06X}"
            assert 0 <= cx < 32, f"Column overflow X={cx} (char={chr(b)!r}) at 0x{addr:06X}"
            assert 0 <= cy <= 28, f"Row overflow Y={cy} (char={chr(b)!r}) at 0x{addr:06X}"
            pages[-1].append((cx, cy, b))
            cx += 1
        elif b in (jttl_text.OP_END, jttl_text.OP_WAIT_END):
            break
        elif b == jttl_text.OP_PAGE_CLR:
            pages.append([])
            cx, cy = bx, by
        elif b == jttl_text.OP_CLR_ONLY:
            pages[-1] = []
            cx, cy = bx, by
        elif b == jttl_text.OP_PAUSE:
            pass
        elif b == jttl_text.OP_DELAY:
            p += 1
        elif b == jttl_text.OP_BASE_X:
            bx = mod_cpu[p]
            p += 1
            cx, cy = bx, by
        elif b == jttl_text.OP_NL2:
            cx, cy = bx, cy + 2
        elif b == jttl_text.OP_NL3:
            cx, cy = bx, cy + 3
        elif b == jttl_text.OP_NL4:
            cx, cy = bx, cy + 4
        else:
            raise AssertionError(f"Unknown opcode 0x{b:02X} in script 0x{addr:06X}")
    return pages


def render_scripts_sheet(mod_cpu: bytearray) -> None:
    """Build notes/verify_scripts.png by simulating all 35 built scripts from mod_cpu."""
    tr = json.loads(TR_PATH.read_text(encoding="utf-8"))
    font_tbl = mod_cpu[jttl_text.ASCII_FONT_ADDR : jttl_text.ASCII_FONT_ADDR + 1536]

    panels: List[Tuple[str, List[Tuple[int, int, int]], bool]] = []

    # 7 intro scripts directly via patched lea / d1 sites in mod_cpu
    for name, (lea_site, d1_site) in jttl_text.INTRO_PATCH_SITES.items():
        s_addr = struct.unpack_from(">I", mod_cpu, lea_site)[0]
        d1_val = struct.unpack_from(">I", mod_cpu, d1_site)[0]
        ix, iy = (d1_val >> 16) & 0xFFFF, d1_val & 0xFFFF
        pgs = _sim_script_bytes(mod_cpu, s_addr, ix, iy)
        for pi, pg in enumerate(pgs):
            panels.append((f"{name} (p{pi+1} @{s_addr:06X})", pg, True))

    # Unique stage scripts + check ALL 28 slots 0..27
    seen_addrs: set[int] = set()
    for slot in range(0, 28):
        s_addr = struct.unpack_from(">I", mod_cpu, jttl_text.STAGE_PTR_TABLE + slot * 4)[0]
        pgs = _sim_script_bytes(mod_cpu, s_addr, 0, 0)
        if s_addr in seen_addrs:
            continue
        seen_addrs.add(s_addr)
        for pi, pg in enumerate(pgs):
            panels.append((f"slot {slot:02d} (p{pi+1} @{s_addr:06X})", pg, False))

    # Render each panel onto 256x80 canvas (trim vertically around used rows so grid fits compactly)
    cols = 4
    pw, ph = 272, 112
    rows = (len(panels) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * pw + 24, rows * ph + 24), (16, 18, 26))
    draw = ImageDraw.Draw(sheet)

    for idx, (label, glyphs, is_intro) in enumerate(panels):
        gx = 12 + (idx % cols) * pw
        gy = 12 + (idx // cols) * ph
        bg = (28, 36, 56) if is_intro else (22, 46, 36)
        draw.rectangle((gx, gy, gx + pw - 8, gy + ph - 8), fill=bg, outline=(90, 100, 130))
        draw.text((gx + 4, gy + 2), label, fill=(255, 220, 110))

        # Normalize Y to start cleanly near panel top while keeping exact X column alignment
        min_y = min((g[1] for g in glyphs), default=0)
        px_buf = sheet.load()
        for cx, cy, ch in glyphs:
            off = (ch - 0x20) * 16
            x_px = gx + 4 + cx * 8
            y_px = gy + 16 + (cy - min_y) * 8
            for ry in range(16):
                byte = font_tbl[off + ry]
                for rx in range(8):
                    if byte & (0x80 >> rx):
                        sx, sy = x_px + rx, y_px + ry
                        if gx <= sx < gx + pw - 8 and gy <= sy < gy + ph - 8:
                            px_buf[sx, sy] = (248, 248, 248)

    SCRIPTS_OUT.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(SCRIPTS_OUT)
    print(f"Verified & rendered {len(panels)} script pages across all 35 entries -> {SCRIPTS_OUT}")


def main() -> None:
    orig_cpu, _ = jttl_rom.load_rom(verify_hash=True)
    mod_cpu, _ = jttl_rom.load_rom(BUILD_ROM_PATH, verify_hash=False)
    render_scenes_sheet(orig_cpu, mod_cpu)
    render_scripts_sheet(mod_cpu)
    print(f"Saved scene sheet -> {SCENES_OUT}")


if __name__ == "__main__":
    main()
