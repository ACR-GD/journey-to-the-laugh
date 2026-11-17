"""Text engine M68K hook (8x16 ASCII), script byte compiler, and verifier."""

from __future__ import annotations

import json
import struct
from pathlib import Path
from typing import Dict, List, Tuple

from capstone import Cs, CS_ARCH_M68K, CS_MODE_M68K_000

import jttl_font

ASCII_FONT_ADDR = 0x000A6686  # 1,536 bytes ending at 0x000A6C86 (protects 0x0A6666..0x0A6686 Text0 pal)

TEXT_ENGINE_START = 0x002902
TEXT_INTERP_ADDR = 0x0029E2
TEXT_ENGINE_END = 0x002B54  # exclusive (max 594 bytes)

SCRIPT_POOL_START = 0x002BE4
SCRIPT_POOL_END = 0x003BF8
STAGE_PTR_TABLE = 0x002F30  # 28 longs (slots 0..27)

# Setup pointer immediate operand offsets in intro_setups (0x002D6C..0x002EC8):
# Each entry: (lea_imm32_off, d1_imm32_off_or_None)
INTRO_PATCH_SITES: Dict[str, Tuple[int, int]] = {
    "intro_0": (0x002D90, 0x002D96),
    "intro_1": (0x002DC0, 0x002DC6),
    "intro_2": (0x002DF2, 0x002DF8),
    "intro_3": (0x002E12, 0x002E18),
    "intro_4": (0x002E34, 0x002E3A),
    "intro_5": (0x002E56, 0x002E5C),
    "intro_6": (0x002EB6, 0x002EBC),
}

# Byte-stream opcodes interpreted by text_interp_v2:
OP_END = 0x00        # flush & rts
OP_WAIT_END = 0x01   # wait release+press, flush & rts
OP_PAGE_CLR = 0x02   # flush, wait release+press, clear $FC0000, Yscroll=$FF5C, reset (X,Y)=D1
OP_CLR_ONLY = 0x03   # flush, clear $FC0000, reset (X,Y)=D1
OP_PAUSE = 0x04      # wait 24 frames
OP_DELAY = 0x05      # next byte = delay frames/char
OP_BASE_X = 0x06     # next byte = new base_X (resets current X,Y = (base_X, base_Y))
OP_NL2 = 0x0A        # X = base_X, Y += 2
OP_NL3 = 0x0D        # X = base_X, Y += 3
OP_NL4 = 0x0E        # X = base_X, Y += 4


class _M68KAsm:
    """Minimal relocatable M68000 emitter with exact label fixups & Capstone verification."""

    def __init__(self, base_addr: int):
        self.base = base_addr
        self.buf = bytearray()
        self.labels: Dict[str, int] = {}
        self.fixups: List[Tuple[int, str, int, int]] = []  # (patch_pos, label, pc_off, width)

    @property
    def pc(self) -> int:
        return self.base + len(self.buf)

    def label(self, name: str) -> None:
        if name in self.labels:
            raise ValueError(f"Duplicate label {name}")
        self.labels[name] = self.pc

    def w(self, *words: int) -> None:
        for val in words:
            self.buf.extend(struct.pack(">H", val & 0xFFFF))

    def l(self, val: int) -> None:
        self.buf.extend(struct.pack(">I", val & 0xFFFFFFFF))

    def bcc_w(self, cond_opcode: int, target: str) -> None:
        # 16-bit displacement is relative to address of extension word (pc + 2)
        self.w(cond_opcode)
        self.fixups.append((len(self.buf), target, self.pc, 2))
        self.w(0)

    def bcc_s(self, cond_hi8: int, target: str) -> None:
        # 8-bit displacement in low byte of opcode word is relative to (pc_of_opcode + 2)
        self.fixups.append((len(self.buf) + 1, target, self.pc + 2, 1))
        self.w((cond_hi8 & 0xFF) << 8)

    def finalize(self) -> bytes:
        for pos, label, ref_pc, width in self.fixups:
            if label not in self.labels:
                raise KeyError(f"Undefined label {label}")
            disp = self.labels[label] - ref_pc
            if width == 2:
                if not (-0x8000 <= disp <= 0x7FFF):
                    raise ValueError(f"Branch {label} out of range: {disp}")
                struct.pack_into(">h", self.buf, pos, disp)
            elif width == 1:
                if not (-128 <= disp <= 127) or disp in (0, -1):
                    raise ValueError(f"Short branch {label} out of range or invalid disp: {disp}")
                struct.pack_into(">b", self.buf, pos, disp)
            else:
                raise ValueError(f"Unsupported width {width}")
        return bytes(self.buf)


def assemble_text_engine() -> Tuple[bytes, int, int]:
    """Assemble draw_8x16_ascii (at 0x002902) and text_interp_v2 (at 0x0029E2).

    Returns (blob_from_0x2902, draw_addr, interp_addr).
    """
    a = _M68KAsm(TEXT_ENGINE_START)

    # ---- draw_8x16_ascii(D0 = (X<<16)|Y, A0 = ptr to 16-byte 1bpp char) ----
    # Matches original entry register contract at 0x002902.
    a.label("draw_8x16_ascii")
    # movem.l d0-d3/d6/a0-a2, -(a7)  [mask d0-d3=000F, d6=0040, a0-a2=0700 -> reglist 0xF020? No: predecrement order A7..A0, D7..D0: D0..D3=0xF000, D6=0x0200, A0-A2=0x00E0 -> wait verify with capstone!]
    # Easier & explicit: individual pushes (same as original 0x2902..0x290A + d1/d3/d6) or explicit MOVEM!
    a.w(0x2F00)  # move.l d0, -(a7)
    a.w(0x2F01)  # move.l d1, -(a7)
    a.w(0x2F02)  # move.l d2, -(a7)
    a.w(0x2F03)  # move.l d3, -(a7)
    a.w(0x2F06)  # move.l d6, -(a7)
    a.w(0x2F08)  # move.l a0, -(a7)
    a.w(0x2F09)  # move.l a1, -(a7)
    a.w(0x2F0A)  # move.l a2, -(a7)

    # A1 = $FC0000 + (Y << 10) + (X << 5)
    a.w(0x247C); a.l(0x00FC0000)      # movea.l #$fc0000, a2
    a.w(0x4282)                       # clr.l d2
    a.w(0x3400)                       # move.w d0, d2       (Y)
    a.w(0xEB8A)                       # lsl.l #5, d2
    a.w(0xEB8A)                       # lsl.l #5, d2        (Y << 10)
    a.w(0x2242)                       # movea.l d2, a1
    a.w(0x4240)                       # clr.w d0
    a.w(0x4840)                       # swap d0             (X; hi word == 0)
    a.w(0xEB48)                       # lsl.w #5, d0        (X << 5)
    a.w(0xD3C0)                       # adda.l d0, a1
    a.w(0xD3CA)                       # adda.l a2, a1       (A1 = $FC0000 + (Y<<10) + (X<<5))

    # Draw top 8x8 tile (8 bytes from (a0)+ into (a1)+..32B)
    a.bcc_s(0x61, "draw_8x8")         # bsr.s draw_8x8
    # Note draw_8x8 left A1 pointing +32B past top tile; bottom tile is at A1_orig + 0x400 = A1_cur + 0x3E0
    a.w(0xD3FC); a.l(0x000003E0)      # adda.l #$3e0, a1
    a.bcc_s(0x61, "draw_8x8")         # bsr.s draw_8x8

    a.w(0x245F)  # movea.l (a7)+, a2
    a.w(0x225F)  # movea.l (a7)+, a1
    a.w(0x205F)  # movea.l (a7)+, a0
    a.w(0x2C1F)  # move.l (a7)+, d6
    a.w(0x261F)  # move.l (a7)+, d3
    a.w(0x241F)  # move.l (a7)+, d2
    a.w(0x221F)  # move.l (a7)+, d1
    a.w(0x201F)  # move.l (a7)+, d0
    a.w(0x4E75)  # rts

    # ---- Helper: draw_8x8(A0=8 bytes 1bpp, A1=dest 32 bytes 4bpp) -> advances A0+=8, A1+=32 ----
    a.label("draw_8x8")
    a.w(0x7407)                       # moveq #7, d2
    a.label("d8_row")
    a.w(0x7601)                       # moveq #1, d3        (2 words per 8px row)
    a.w(0x1018)                       # move.b (a0)+, d0
    a.label("d8_word")
    a.w(0x4246)                       # clr.w d6
    a.w(0x3239); a.l(0x00FCEC06)      # move.w $fcec06.l, d1
    a.w(0xED49)                       # lsl.w #6, d1
    a.w(0xED49)                       # lsl.w #6, d1        (nibble in bits 15..12)
    for _ in range(4):
        a.w(0xE308)                   # lsl.b #1, d0
        a.w(0x6402)                   # bcc.s +2
        a.w(0x8C41)                   # or.w d1, d6
        a.w(0xE849)                   # lsr.w #4, d1
    a.w(0x32C6)                       # move.w d6, (a1)+
    a.w(0x51CB); a.fixups.append((len(a.buf), "d8_word", a.pc, 2)); a.w(0)
    a.w(0x51CA); a.fixups.append((len(a.buf), "d8_row", a.pc, 2)); a.w(0)
    a.w(0x4E75)                       # rts

    # Verify draw_8x16_ascii + draw_8x8 ends <= 0x0029E2!
    if a.pc > TEXT_INTERP_ADDR:
        raise ValueError(
            f"draw_8x16_ascii spilled past 0x{TEXT_INTERP_ADDR:06X}: pc=0x{a.pc:06X}"
        )
    while a.pc < TEXT_INTERP_ADDR:
        a.w(0x4E71)  # nop pad to exact 0x0029E2 entry

    # ---- text_interp_v2 at EXACT 0x0029E2 ----
    # Inputs: A1 = byte script, D1 = (base_X << 16) | base_Y, A6 = VRAM tile base ($F40000/$F50000)
    a.label("text_interp_v2")
    assert a.pc == TEXT_INTERP_ADDR
    a.w(0x2F0E)                       # move.l a6, -(a7)    (match original entry/exit)
    a.w(0x247C); a.l(ASCII_FONT_ADDR) # movea.l #ASCII_FONT_ADDR, a2
    a.w(0x2001)                       # move.l d1, d0       (D0 = current (X<<16)|Y)
    a.w(0x7802)                       # moveq #2, d4        (default delay = 2 frames/char)

    a.label("loop")
    a.w(0x4242)                       # clr.w d2
    a.w(0x1419)                       # move.b (a1)+, d2
    a.w(0x0C42, 0x0020)               # cmpi.w #$20, d2
    a.bcc_w(0x6D00, "ctrl")           # blt.w ctrl

    # Printable ASCII >= 0x20: draw glyph & advance X += 1
    a.w(0x0442, 0x0020)               # subi.w #$20, d2
    a.w(0xE94A)                       # lsl.w #4, d2        (* 16 bytes)
    a.w(0x41F2, 0x2000)               # lea (a2, d2.w), a0
    a.w(0x6100); a.fixups.append((len(a.buf), "draw_8x16_ascii", a.pc, 2)); a.w(0)
    a.w(0x0680); a.l(0x00010000)      # addi.l #$10000, d0  (X += 1 -> 8 px!)

    # Per-char delay & flush (skip if d4 == 0)
    a.w(0x4A44)                       # tst.w d4
    a.bcc_s(0x67, "loop")             # beq.s loop

    a.w(0x4A39); a.l(0x00FCEC31)      # tst.b $fcec31.l
    a.bcc_s(0x67, "no_sfx")           # beq.s no_sfx
    a.w(0x5279); a.l(0x00FCEC04)      # addq.w #1, $fcec04.l
    a.w(0x0279, 0x0001); a.l(0x00FCEC04)  # andi.w #1, $fcec04.l
    a.w(0x3C39); a.l(0x00FCEC04)      # move.w $fcec04.l, d6
    a.w(0x33C6); a.l(0x00F00022)      # move.w d6, $f00022.l
    a.w(0x0079, 0x0008); a.l(0x00FCEC02)  # ori.w #8, $fcec02.l
    a.w(0x33F9); a.l(0x00FCEC02); a.l(0x00F00008)  # move.w $fcec02.l, $f00008.l

    a.label("no_sfx")
    a.w(0x3E04)                       # move.w d4, d7
    a.w(0x4A79); a.l(0x00E80200)      # tst.w $e80200.l
    a.w(0x6702)                       # beq.s +2
    a.w(0x7E01)                       # moveq #1, d7
    a.w(0x4EB8, 0x2412)               # jsr $2412.w
    a.w(0x4EB8, 0x27E6)               # jsr $27e6.w
    a.w(0x0279, 0xFFF7); a.l(0x00FCEC02)  # andi.w #$fff7, $fcec02.l
    a.w(0x33F9); a.l(0x00FCEC02); a.l(0x00F00008)  # move.w $fcec02.l, $f00008.l
    a.bcc_s(0x60, "loop")             # bra.s loop

    # Control dispatch (< 0x20)
    a.label("ctrl")
    a.w(0x4A42); a.bcc_s(0x67, "do_end")        # tst.w d2; beq.s do_end (OP_END == 0)
    a.w(0x0C02, OP_WAIT_END); a.bcc_s(0x67, "do_wait_end")
    a.w(0x0C02, OP_PAGE_CLR); a.bcc_s(0x67, "do_page_clr")
    a.w(0x0C02, OP_CLR_ONLY); a.bcc_w(0x6700, "do_clr_only")
    a.w(0x0C02, OP_PAUSE); a.bcc_s(0x67, "do_pause")
    a.w(0x0C02, OP_DELAY); a.bcc_s(0x67, "do_delay")
    a.w(0x0C02, OP_BASE_X); a.bcc_s(0x67, "do_base_x")
    a.w(0x0C02, OP_NL2); a.bcc_s(0x67, "do_nl2")
    a.w(0x0C02, OP_NL3); a.bcc_s(0x67, "do_nl3")
    a.w(0x0C02, OP_NL4); a.bcc_s(0x67, "do_nl4")
    a.bcc_w(0x6000, "loop")           # unknown <0x20 ignored safely

    a.label("do_wait_end")
    a.w(0x4EB8, 0x27E6)               # jsr $27e6.w
    a.bcc_s(0x61, "wait_btn")         # bsr.s wait_btn
    a.label("do_end")
    a.w(0x4EB8, 0x27E6)               # jsr $27e6.w
    a.w(0x2C5F)                       # movea.l (a7)+, a6
    a.w(0x4E75)                       # rts

    a.label("do_pause")
    a.w(0x7E18)                       # moveq #24, d7
    a.w(0x4EB8, 0x2412)               # jsr $2412.w
    a.bcc_w(0x6000, "loop")

    a.label("do_delay")
    a.w(0x4244)                       # clr.w d4
    a.w(0x1819)                       # move.b (a1)+, d4
    a.bcc_w(0x6000, "loop")

    a.label("do_base_x")
    a.w(0x4841)                       # swap d1
    a.w(0x4241)                       # clr.w d1
    a.w(0x1219)                       # move.b (a1)+, d1
    a.w(0x4841)                       # swap d1
    a.w(0x2001)                       # move.l d1, d0
    a.bcc_w(0x6000, "loop")

    a.label("do_nl4")
    a.w(0x5240)                       # addq.w #1, d0
    a.label("do_nl3")
    a.w(0x5240)                       # addq.w #1, d0
    a.label("do_nl2")
    a.w(0x5440)                       # addq.w #2, d0
    a.w(0x4841); a.w(0x4840); a.w(0x3001); a.w(0x4841); a.w(0x4840)
    a.bcc_w(0x6000, "loop")

    a.label("do_page_clr")
    a.w(0x4EB8, 0x27E6)               # jsr $27e6.w
    a.bcc_s(0x61, "wait_btn")         # bsr.s wait_btn
    a.w(0x33FC, 0xFF5C); a.l(0x00FCEC1A)
    a.w(0x33FC, 0xFF5C); a.l(0x00F00106)
    a.label("do_clr_only")
    a.w(0x2A7C); a.l(0x00FC0000)      # movea.l #$fc0000, a5
    a.w(0x3C3C, 0x1FFF)               # move.w #$1fff, d6 (save d0!)
    a.label("clr_lp")
    a.w(0x429D)                       # clr.l (a5)+
    a.w(0x51CE); a.fixups.append((len(a.buf), "clr_lp", a.pc, 2)); a.w(0)
    a.w(0x2001)                       # move.l d1, d0
    a.bcc_w(0x6000, "loop")

    # ---- Helper: wait_btn (wait for joypad release then fresh button press, preserving d0..d5) ----
    a.label("wait_btn")
    a.w(0x2F07)                       # move.l d7, -(a7)
    a.label("wb_rel")
    a.w(0x4A79); a.l(0x00E80200)      # tst.w $e80200.l
    a.bcc_s(0x67, "wb_pr")
    a.w(0x7E01)                       # moveq #1, d7
    a.w(0x4EB8, 0x2412)               # jsr $2412.w
    a.bcc_s(0x60, "wb_rel")
    a.label("wb_pr")
    a.w(0x4A79); a.l(0x00E80200)      # tst.w $e80200.l
    a.bcc_s(0x66, "wb_done")
    a.w(0x7E01)                       # moveq #1, d7
    a.w(0x4EB8, 0x2412)               # jsr $2412.w
    a.bcc_s(0x60, "wb_pr")
    a.label("wb_done")
    a.w(0x2E1F)                       # move.l (a7)+, d7
    a.w(0x4E75)                       # rts

    code = a.finalize()
    if TEXT_ENGINE_START + len(code) > TEXT_ENGINE_END:
        raise ValueError(
            f"Text engine code {len(code)}B exceeds slot 0x{TEXT_ENGINE_START:06X}..0x{TEXT_ENGINE_END:06X}"
        )

    # Sanity-disassemble with Capstone to confirm every word decoded cleanly without dc.w
    md = Cs(CS_ARCH_M68K, CS_MODE_M68K_000)
    insns = list(md.disasm(code, TEXT_ENGINE_START))
    covered = sum(i.size for i in insns)
    if covered != len(code):
        raise AssertionError(
            f"M68K disassembly stopped early: {covered} != {len(code)} bytes"
        )
    for insn in insns:
        if insn.mnemonic == "dc.w":
            raise AssertionError(f"Illegal opcode at 0x{insn.address:06X}")

    return code, TEXT_ENGINE_START, TEXT_INTERP_ADDR


def compile_script(
    lines: List[str],
    delay: int = 2,
    wait_end: bool = False,
    line_cmd: str = "NL2",
    base_x: int | None = None,
    pw_lines: List[str] | None = None,
    max_cols: int = 30,
) -> bytes:
    """Compile English dialogue lines into a null/wait terminated byte stream."""
    nl_map = {"NL2": OP_NL2, "NL3": OP_NL3, "NL4": OP_NL4}
    nl_byte = nl_map[line_cmd]

    out = bytearray()
    if base_x is not None:
        out.extend([OP_BASE_X, base_x & 0xFF])
    out.extend([OP_DELAY, delay & 0xFF])

    if lines:
        for i, ln in enumerate(lines):
            if len(ln) > max_cols:
                raise ValueError(f"Line too long ({len(ln)} > {max_cols}): {ln!r}")
            for ch in ln:
                c = ord(ch)
                if not (0x20 <= c <= 0x7E):
                    raise ValueError(f"Non-ASCII char {ch!r} in {ln!r}")
                out.append(c)
            if i + 1 < len(lines):
                out.append(nl_byte)

    if pw_lines:
        if lines:
            out.append(OP_PAGE_CLR)
        for i, ln in enumerate(pw_lines):
            if len(ln) > max_cols:
                raise ValueError(f"PW line too long ({len(ln)} > {max_cols}): {ln!r}")
            for ch in ln:
                out.append(ord(ch))
            if i + 1 < len(pw_lines):
                out.append(OP_NL2)
        out.append(OP_END)
    else:
        out.append(OP_WAIT_END if wait_end else OP_END)

    return bytes(out)


def apply_text_patches(rom: bytearray, translations_path: Path) -> Dict[str, int]:
    """Install 8x16 ASCII font, M68K text engine hook, and all 35 translated scripts."""
    tr = json.loads(translations_path.read_text(encoding="utf-8"))

    # 1. Install 8x16 ASCII font at 0x0A6686 (1,536B), preserving 0x0A6666..0x0A6686 Text0 palette
    font_blob = jttl_font.build_8x16_font_table()
    if ASCII_FONT_ADDR + len(font_blob) > 0x0A6C86:
        raise AssertionError("Font overlaps allocator region")
    rom[ASCII_FONT_ADDR : ASCII_FONT_ADDR + len(font_blob)] = font_blob

    # 2. Install M68K draw_8x16_ascii + text_interp_v2 at 0x002902..0x002B54
    code_blob, _, _ = assemble_text_engine()
    rom[TEXT_ENGINE_START : TEXT_ENGINE_START + len(code_blob)] = code_blob
    if TEXT_ENGINE_START + len(code_blob) < TEXT_ENGINE_END:
        pad = TEXT_ENGINE_END - (TEXT_ENGINE_START + len(code_blob))
        rom[TEXT_ENGINE_START + len(code_blob) : TEXT_ENGINE_END] = b"\x4e\x71" * (pad // 2)

    # 3. Compile all 35 scripts into 0x002BE4..0x003BF8
    pool_cur = SCRIPT_POOL_START
    # STAGE_PTR_TABLE sits at 0x002F30..0x002FA0 (28 longs: slots 0..27).
    # Stage script pool starts right after at 0x002FA0 (matching original slot 0 start).
    intro_cur = 0x002BE4
    intro_end = 0x002D48
    stage_cur = 0x002FA0
    stage_end = 0x003BF8

    for name, info in tr["intro"].items():
        lea_site, d1_site = INTRO_PATCH_SITES[name]
        blob = compile_script(
            info["lines"],
            delay=info["delay"],
            wait_end=info["wait_end"],
            line_cmd=info["line_cmd"],
            max_cols=28,
        )
        if intro_cur + len(blob) <= intro_end:
            addr = intro_cur
            intro_cur += (len(blob) + 1) & ~1
        elif stage_cur + len(blob) <= stage_end:
            addr = stage_cur
            stage_cur += (len(blob) + 1) & ~1
        else:
            raise MemoryError(f"Out of script pool space for {name}")
        rom[addr : addr + len(blob)] = blob
        struct.pack_into(">I", rom, lea_site, addr)
        struct.pack_into(">I", rom, d1_site, (info["x"] << 16) | info["y"])

    # Zero remaining intro_cur..intro_end cleanly
    rom[intro_cur:intro_end] = b"\x00" * (intro_end - intro_cur)

    shared_pw = tr["stage_shared_pw"]
    base_x_stage = int(tr["meta"]["base_x_stage"])
    slot_addrs: Dict[int, int] = {}

    for orig_addr_hex, info in tr["stage_scripts"].items():
        pages = info["pages"]
        has_pw = bool(info["has_pw"])
        blob = compile_script(
            pages[0] if pages else [],
            delay=2,
            wait_end=(not has_pw),
            line_cmd="NL2",
            base_x=base_x_stage,
            pw_lines=(shared_pw if has_pw else None),
            max_cols=28,
        )
        if stage_cur + len(blob) > stage_end:
            raise MemoryError(f"Out of stage script space at {orig_addr_hex}")
        addr = stage_cur
        rom[addr : addr + len(blob)] = blob
        stage_cur += (len(blob) + 1) & ~1
        for slot in info["slots"]:
            slot_addrs[int(slot)] = addr

    # Zero unused tail of stage script pool
    rom[stage_cur:stage_end] = b"\x00" * (stage_end - stage_cur)

    # Patch pointer table 0x002F30 slots 0..27 (28 entries)
    for slot in range(0, 28):
        if slot not in slot_addrs:
            raise KeyError(f"Missing translation for stage slot {slot}")
        struct.pack_into(">I", rom, STAGE_PTR_TABLE + slot * 4, slot_addrs[slot])

    return {
        "engine_bytes": len(code_blob),
        "font_bytes": len(font_blob),
        "intro_script_bytes": intro_cur - 0x002BE4,
        "stage_script_bytes": stage_cur - 0x002FA0,
        "intro_free_rem": intro_end - intro_cur,
        "stage_free_rem": stage_end - stage_cur,
    }
