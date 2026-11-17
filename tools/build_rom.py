"""Build localized Journey to the Laugh (EN).bin, .ips patch, and build/report.txt."""

from __future__ import annotations

import hashlib
import shutil
import struct
import sys
from pathlib import Path
from typing import Dict

from capstone import Cs, CS_ARCH_M68K, CS_MODE_M68K_000

TOOLS_DIR = Path(__file__).resolve().parent
PROJ_DIR = TOOLS_DIR.parent
sys.path.insert(0, str(TOOLS_DIR))

import gfx_patchers
import jttl_d222
import jttl_rom
import jttl_text

TRANSLATIONS_PATH = PROJ_DIR / "notes" / "translations_en.json"
BUILD_DIR = PROJ_DIR / "build"
OUT_ROM_PATH = BUILD_DIR / "Journey to the Laugh (EN).bin"
OUT_IPS_PATH = BUILD_DIR / "Journey to the Laugh (EN).ips"
REPORT_PATH = BUILD_DIR / "report.txt"


def _verify_built_rom(
    orig_cpu: bytearray,
    orig_swapped: bytes,
    mod_cpu: bytearray,
    mod_swapped: bytes,
    ips_bytes: bytes,
    gfx_res: Dict,
) -> Dict[str, str]:
    """Run integrity checks: IPS round-trip, preserved Text0 palette, d222 decodes, Capstone."""
    # 1. IPS round-trip
    rt = jttl_rom.apply_ips(orig_swapped, ips_bytes)
    if rt != mod_swapped:
        raise AssertionError("IPS round-trip verification failed")

    # 2. Protected Text0 palette (0x0A6666..0x0A6686) untouched
    if orig_cpu[0x0A6666:0x0A6686] != mod_cpu[0x0A6666:0x0A6686]:
        raise AssertionError("Protected Text0 palette at 0x0A6666..0x0A6686 was modified!")

    # 3. Protected code entry trampoline 0x002B54..0x002B58 untouched
    if orig_cpu[0x002B54:0x002B58] != mod_cpu[0x002B54:0x002B58]:
        raise AssertionError("Entry trampoline at 0x002B54 was modified!")

    # 4. Capstone disassembly check on patched engine 0x002902..0x002B54
    md = Cs(CS_ARCH_M68K, CS_MODE_M68K_000)
    insns = list(md.disasm(bytes(mod_cpu[0x002902:0x002B54]), 0x002902))
    if sum(i.size for i in insns) != (0x002B54 - 0x002902):
        raise AssertionError("Built M68K text engine failed full Capstone disassembly")

    # 5. Re-decompress every patched graphic asset from final ROM pointers
    ptr_checks = [
        ("TitleMenuTiles", 0x006F4A, False),
        ("TitleLogoTiles", 0x006590, False),
        ("TitleLogoMap", 0x00659C, False),
        ("PasswordPlaqueTiles", 0x00CE42, False),
        ("PasswordPlaqueMap", 0x00CE46, False),
        ("GiftBoxTiles", 0x00582C, False),
        ("GiftBoxMap", 0x005838, False),
        ("GameOverTiles", 0x0EE700, False),
        ("GameOverMap", 0x0EE70C, False),
    ]
    for name, _, _, t_ptrs, _, _, m_ptrs, _ in gfx_patchers._ENDING_SPECS:
        ptr_checks.append((f"{name}Tiles", t_ptrs[0], True))
        ptr_checks.append((f"{name}Map", m_ptrs[0], False))

    for label, ptr_site, has_wc in ptr_checks:
        addr = struct.unpack_from(">I", mod_cpu, ptr_site)[0]
        raw, _ = jttl_d222.decompress_d222(mod_cpu, addr)
        if label.endswith("Tiles"):
            tiles = jttl_rom.decode_4bpp_tiles(raw, has_word_count=has_wc)
            if has_wc:
                wc = struct.unpack_from(">H", raw, 0)[0]
                if wc != len(tiles) * 16:
                    raise AssertionError(f"{label}: word_count={wc} != {len(tiles)*16}")

    # TitleMenu DMA count word matches TitleMenuTiles
    tmenu_addr = struct.unpack_from(">I", mod_cpu, 0x006F4A)[0]
    tmenu_raw, _ = jttl_d222.decompress_d222(mod_cpu, tmenu_addr)
    dma_cnt = struct.unpack_from(">H", mod_cpu, 0x006F86)[0]
    expected_cnt = (len(tmenu_raw) // 2) - 1
    if dma_cnt != expected_cnt:
        raise AssertionError(f"TitleMenu DMA count {dma_cnt} != {expected_cnt}")

    return {
        "ips_roundtrip": "PASS",
        "text0_pal": "INTACT",
        "capstone_engine": "PASS",
        "d222_redecode_all": f"PASS ({len(ptr_checks)} streams)",
    }


def main() -> None:
    cpu_rom, orig_swapped = jttl_rom.load_rom(verify_hash=True)
    orig_cpu = bytearray(cpu_rom)
    alloc = jttl_rom.SpaceAllocator()

    text_stats = jttl_text.apply_text_patches(cpu_rom, TRANSLATIONS_PATH)
    gfx_stats = gfx_patchers.apply_all_gfx_patches(cpu_rom, alloc, TRANSLATIONS_PATH)

    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    mod_swapped = jttl_rom.save_rom(cpu_rom, OUT_ROM_PATH)
    ips_records = jttl_rom.write_ips(orig_swapped, mod_swapped, OUT_IPS_PATH)
    ips_bytes = OUT_IPS_PATH.read_bytes()

    checks = _verify_built_rom(orig_cpu, orig_swapped, cpu_rom, mod_swapped, ips_bytes, gfx_stats)

    orig_sha1 = hashlib.sha1(orig_swapped).hexdigest()
    orig_sha256 = hashlib.sha256(orig_swapped).hexdigest()
    mod_sha1 = hashlib.sha1(mod_swapped).hexdigest()
    mod_sha256 = hashlib.sha256(mod_swapped).hexdigest()

    lines = [
        "Journey to the Laugh (Super A'Can) — English Localization Build Report",
        "=" * 74,
        f"Source ROM : {jttl_rom.ORIG_ROM_PATH.name}",
        f"  Size     : {len(orig_swapped)} bytes",
        f"  SHA-1    : {orig_sha1}",
        f"  SHA-256  : {orig_sha256}",
        f"Built ROM  : {OUT_ROM_PATH.name}",
        f"  Size     : {len(mod_swapped)} bytes",
        f"  SHA-1    : {mod_sha1}",
        f"  SHA-256  : {mod_sha256}",
        f"IPS Patch  : {OUT_IPS_PATH.name} ({len(ips_bytes)} bytes, {ips_records} records)",
        "",
        "Verification Checks:",
    ]
    for k, v in checks.items():
        lines.append(f"  {k:20s}: {v}")

    lines.extend([
        "",
        "Text Engine & Script Pool:",
        f"  M68K Engine (0x002902..0x002B54): {text_stats['engine_bytes']} / {0x2B54 - 0x2902} bytes",
        f"  8x16 ASCII Font (0x0A6686..0x0A6C86): {text_stats['font_bytes']} bytes",
        f"  Intro Scripts (0x002BE4..0x002D48): used {text_stats['intro_script_bytes']} B, {text_stats['intro_free_rem']} B free",
        f"  Stage Scripts (0x002FA0..0x003BF8): used {text_stats['stage_script_bytes']} B, {text_stats['stage_free_rem']} B free",
        "",
        "Localized Graphics & Palettes:",
    ])

    for k in ("title_menu", "title_logo", "password_plaque", "gift_box", "game_over"):
        info = gfx_stats[k]
        if k == "title_menu":
            lines.append(
                f"  {k:16s}: {info['ntiles']:3d} tiles (DMA 0x{info['dma_cnt']:04X}) -> "
                f"tiles@0x{info['t_addr']:06X} ({info['t_bytes']}B)"
            )
        else:
            lines.append(
                f"  {k:16s}: {info['ntiles']:3d} tiles -> "
                f"tiles@0x{info['t_addr']:06X} ({info['t_bytes']}B), "
                f"map@0x{info['m_addr']:06X} ({info['m_bytes']}B)"
            )
    for name, info in gfx_stats["ending"].items():
        lines.append(
            f"  {name:16s}: {info['ntiles']:3d} tiles -> "
            f"tiles@0x{info['t_addr']:06X} ({info['t_bytes']}B), "
            f"map@0x{info['m_addr']:06X} ({info['m_bytes']}B)"
        )

    lines.extend(["", "SpaceAllocator Regions Summary:"])
    lines.extend(alloc.summary())
    if alloc.allocs:
        lines.append("  Relocations:")
        for lbl, s, e in alloc.allocs:
            lines.append(f"    {lbl:20s}: 0x{s:06X}..0x{e:06X} ({e - s} B)")

    report_text = "\n".join(lines) + "\n"
    REPORT_PATH.write_text(report_text, encoding="utf-8")
    print(report_text)


if __name__ == "__main__":
    main()
