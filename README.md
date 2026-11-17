# Journey to the Laugh (*嘻遊記*) — English Localization

Volunteer / preservation English translation project for **Journey to the Laugh (Taiwan)** (`©1995 FUNTECH ALL RIGHTS RESERVED.`), originally released for the **Super A'Can**.

> Put your own `Journey to the Laugh (Taiwan).bin` in this folder; no script in this project modifies it.

---

## How to Play

Apply `build/Journey to the Laugh (EN).ips` to `Journey to the Laugh (Taiwan).bin` (2,097,152 bytes,
CRC32 `cee25eea`, SHA-1 `fc82fc3a7d55571494cd62d8807160e22cf437bc`, the MAME `jttlaugh` dump `16002.cu2`).
The ROM keeps its size.

- **Repo emulator:** open the patched file.
- **MAME:** put the patched file in `roms/jttlaugh/` as `16002.cu2` and run `mame supracan jttlaugh`
  (MAME warns about the checksum; that's expected).

---

## Deliverables & Verification Hashes

| File | Size | SHA-1 | SHA-256 |
|---|---:|---|---|
| Source ROM: `Journey to the Laugh (Taiwan).bin` | 2,097,152 B | `fc82fc3a7d55571494cd62d8807160e22cf437bc` | `a4964b702214f70e199bb07bbd2777eb08875206fa27396989f2a79cb48c5087` |
| Built ROM: `Journey to the Laugh (EN).bin` (built, not included) | 2,097,152 B | `bdac36924150aedfe38046eea891d7171f011727` | `bf26831e385ab6fb764a6b5d91ffc4b1e1c9cebec17e6fe311df30bb8997ee85` |
| IPS Patch: [Journey to the Laugh (EN).ips](build/Journey%20to%20the%20Laugh%20(EN).ips) | 81,157 B (42 records) | — | `2ab2154dc831b0cc98083fbe03000aa11ec80647c46c6f43c85aaae9731fc767` |

- **Build & Integrity Report**: [build/report.txt](build/report.txt)

---

## Repository Layout

```text
journey-to-the-laugh/
├── build/
│   ├── Journey to the Laugh (EN).bin
│   ├── Journey to the Laugh (EN).ips
│   └── report.txt
├── notes/
│   ├── text_inventory.md
│   ├── translations_en.json
│   ├── verify_live.png
│   ├── verify_scenes.png
│   └── verify_scripts.png
├── tools/
│   ├── build_rom.py       # Rebuilds EN .bin, .ips patch, and build/report.txt
│   ├── gfx_patchers.py    # Pre-rendered asset & palette patchers (14 graphic scenes)
│   ├── jttl_d222.py       # Funtech d222 LZ77+RLE decompressor and compressor
│   ├── jttl_font.py       # Bitmap font & English badge/title pixel renderers
│   ├── jttl_rom.py        # Byte-swap helpers, SpaceAllocator, and IPS encoder
│   ├── jttl_text.py       # M68K 8x16 ASCII engine & script bytecode compiler
│   └── verify_visuals.py  # Generates static visual & script-simulation sheets
└── README.md
```

---

## How the Localization Works

1. **ROM Byte Order**: Super A'Can cartridges store 68000 big-endian words byte-swapped (`odd/even` swapped). [tools/jttl_rom.py](tools/jttl_rom.py) converts between raw `.bin` and big-endian CPU address space and generates standard IPS records.
2. **8x16 ASCII Text Engine (`draw_8x16_ascii` + `text_interp_v2`)**:
   - The original 16x16 Big5 CJK renderer in `0x002902..0x002B54` was replaced in-place (`576 / 594` bytes used, trampoline `0x002B54..0x002B58` preserved intact) with a 1bpp 8x16 ASCII glyph drawer (`95` printable glyphs `0x20..0x7E`, `1,536` bytes at `0x0A6686..0x0A6C86`, preserving the Text0 palette at `0x0A6666..0x0A6686`).
   - All `7` intro/continue/Game Over scripts (`intro_0..6`, `258` used / `98` free bytes in `0x002BE4..0x002D48`) and all `28` `STAGE_PTR_TABLE` slots (`0..27` at `0x002F30..0x002FA0`, using `2,282` / `878` free bytes in `0x002FA0..0x003BF8`) are compiled from [notes/translations_en.json](notes/translations_en.json) by [tools/jttl_text.py](tools/jttl_text.py).
   - Runtime-verified layout tuning: Continue box (`intro_3..5`) sits cleanly inside columns `6..25` (`Revive Wukong?` / `YES` / `NO`), and `stage_shared_pw` renders on a single line (`"Your password, Great Sage:"`) on Row 0 cleanly above the four password sprite icons at `y=182..221`. Slots `9` and `24` (whose `0x069226` password icon entries are `0xFF`) omit the password prompt page.
3. **Compressed Pre-Rendered Graphics (`d222` Codec)**:
   - [tools/gfx_patchers.py](tools/gfx_patchers.py) and [tools/jttl_d222.py](tools/jttl_d222.py) localize and recompress `14` graphical screens: `title_menu` (`START GAME`, `PASSWORD`, `OPTIONS`), `title_logo` (`JOURNEY TO THE LAUGH`), `password_plaque` (`PASSWORD`), `gift_box` (`SALTED CRACKERS`), `game_over` (`GAME OVER`), and all `9` ending scroll scenes (`end1..end9`).
   - Reclaimed tail space and old CJK font pools allow `SpaceAllocator` to cleanly relocate `end5Tiles` (`0x0A6C86..0x0A83A0`), `end9Tiles` (`0x1FC020..0x1FD1C2`), and `end9Map` (`0x0A60F2..0x0A63B5`) with zero pointer conflicts.

---

## Rebuilding & Verification

```bash
python3 tools/build_rom.py
python3 tools/verify_visuals.py
```

All automated checks (`ips_roundtrip: PASS`, `text0_pal: INTACT`, `capstone_engine: PASS`, `d222_redecode_all: PASS (27 streams)`), static sheets ([notes/verify_scenes.png](notes/verify_scenes.png), [notes/verify_scripts.png](notes/verify_scripts.png)), and live Super A'Can emulator captures ([notes/verify_live.png](notes/verify_live.png)) covering Title, Menu, Password entry + `[9, 3, 2, 1]` Stage 26 warp, Intro, Gift Box, Gameplay, Shrine dialogue + Password prompt, Continue, Game Over, and Ending scenes passed after the final build.

## License

The tools, fonts and patch are MIT-licensed (see `LICENSE`). The game itself is not included;
you need your own dump.
