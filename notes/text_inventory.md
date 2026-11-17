# Journey to the Laugh (Taiwan) — Complete ROM Text & Graphic Audit Inventory

- **Source ROM**: `Journey to the Laugh (Taiwan).bin` (2,097,152 bytes, Super A'Can, ©1995 Funtech)
- **SHA-1**: `fc82fc3a7d55571494cd62d8807160e22cf437bc`
- **SHA-256**: `a4964b702214f70e199bb07bbd2777eb08875206fa27396989f2a79cb48c5087`

---

## 1. Engine & Font Regions (68000 Big-Endian Addresses)

| Region | Span | Size | Purpose |
|---|---:|---:|---|
| `draw_8x16_ascii` | `0x002902..0x0029E2` | 224 B | 1bpp 8x16 glyph renderer (reads palette nibble from `$FCEC06`) |
| `text_interp_v2` | `0x0029E2..0x002B54` | 370 B | Byte-stream script interpreter (`0x20..0x7E`, `0x00..0x06`, `0x0A`, `0x0D`, `0x0E`) |
| Entry trampoline | `0x002B54..0x002B58` | 4 B | `bra.w $2d48` (all 7 ROM callers target `0x002B54`) |
| Intro script pool | `0x002BE4..0x002D48` | 356 B | Patched via `INTRO_PATCH_SITES` immediates (`0x002D90..0x002EBC`) |
| `stage_run` + pointer table | `0x002D48..0x002FA0` | 600 B | `STAGE_PTR_TABLE` at `0x002F30` (28 longword slots `0..27`) |
| Stage script pool | `0x002FA0..0x003BF8` | 3,160 B | All 22 unique stage dialogue scripts |
| Text0 palette | `0x0A6666..0x0A6686` | 32 B | **Protected** (referenced at `0x069036` / `0x0EE52E`) |
| ASCII 8x16 font table | `0x0A6686..0x0A6C86` | 1,536 B | 95 glyphs `0x20..0x7E` (16B each) + 16B pad |
| Reclaimed free pools | `0x0A60F2..0x0A6666`, `0x0A6C86..0x0A9226`, `0x1FC020..0x200000` | 27,380 B | Zero-filled tail + old 16x16 font data |

---

## 2. All 35 Script Entries

### Intro / Continue / Game Over Scripts (7 entries, `intro_0..6`)

| ID | Setup Sites (`lea`, `d1`) | Pos `(x, y)` | English Text |
|---|---|---|---|
| `intro_0` | `0x002D90`, `0x002D96` | `(4, 10)` | So Wukong and company / procured the scriptures / and returned to court... |
| `intro_1` | `0x002DC0`, `0x002DC6` | `(4, 16)` | Your Majesty, please / inspect the scriptures... |
| `intro_2` | `0x002DF2`, `0x002DF8` | `(3, 16)` | Wukong! Leap 108,000 miles / back West and bring me the / real scriptures! Or else.. |
| `intro_3` | `0x002E12`, `0x002E18` | `(6, 25)` | Revive Wukong? |
| `intro_4` | `0x002E34`, `0x002E3A` | `(20, 25)` | YES |
| `intro_5` | `0x002E56`, `0x002E5C` | `(24, 25)` | NO |
| `intro_6` | `0x002EB6`, `0x002EBC` | `(8, 25)` | G A M E   O V E R |

### Stage & Shrine Scripts (28 slots `0..27`, 24 unique localized scripts)

All password-bearing scripts (`has_pw = true`) append page 2 (`OP_PAGE_CLR`): `"Your password, Great Sage:"` on Row 0 cleanly above the password icon sprites at `y=182..221` (or display it immediately on page 1 for slot 3). Slots `9` and `24` (whose `0x069226` icon table entries are `0xFF`) are compiled without the password page.

| Orig Addr | Slots | PW | English Page 1 |
|---|---|---:|---|
| `0x002FA0` | `0` | No | Great Sage, this is the / Spider Demon's turf. Watch / out for minions on webs! |
| `0x003004` | `1` | Yes | Silk Cave lies ahead. Some / spiders are controlled by / those floating totems... |
| `0x00309C` | `2` | Yes | You'll soon meet the Boss's / guard, the Spider Demon! / Hit its face--nowhere else! |
| `0x00317C` | `3` | Yes | *(Password page only)* |
| `0x0031B0` | `4` | No | The Giant Spider is right / ahead! Inside its web, / never stand in one spot! |
| `0x00326C` | `5` | Yes | Great Sage, these scorching / Flaming Mountains never see / rain! Step on cooled rocks! |
| `0x003338` | `6` | Yes | When walking on the sand, / don't stand still for long. / Keep moving and jumping! |
| `0x0033D4` | `7, 8` | Yes | Next is the volcano zone! / There's a huge monster / lurking in the magma! |
| `0x0033D4_no_pw` | `9` | No | Next is the volcano zone! / There's a huge monster / lurking in the magma! |
| `0x00345C` | `10` | No | Only the little bull in / back is Bull King's spirit! / Don't hit Rakshasi, or... |
| `0x0034DC` | `11, 12` | Yes | Brrr! It's freezing cold / out here in the snow & ice. / Careful, don't slip!! |
| `0x003564` | `13` | Yes | Great Sage, take it slow, / one step at a time. Never / charge blindly in a maze! |
| `0x003608` | `14` | Yes | Great Sage, there's a / twin-headed snow sled! / Put it to good use! |
| `0x003684` | `15` | Yes | Shrink down small and sneak / in through the kitchen! / Try smashing rice jars... |
| `0x00372C` | `16` | No | Gold & Silver Horn wield / that magic gourd. Whatever / you do, don't answer them! |
| `0x003798` | `17, 18` | Yes | This is Tongtian River-- / deep beyond measure! Look / for a secret shore path... |
| `0x003834` | `19, 20` | Yes | A giant octopus lurks by / the waterfall. Watch out / for what's in its head! |
| `0x0038B8` | `21` | Yes | Next lies the river depths! / Where currents reverse sits / the Grave of Ten Thousand! |
| `0x003954` | `22` | No | The rapids throw off your / spirit shots, Great Sage. / Switch weapons often! |
| `0x0039B0` | `23` | Yes | Demons forged this fake / paradise! Don't be fooled / by their illusions! |
| `0x0039B0_no_pw` | `24` | No | Demons forged this fake / paradise! Don't be fooled / by their illusions! |
| `0x003A50` | `25` | Yes | Ride the three incense / sticks ahead! Move up and / down to dodge obstacles! |
| `0x003AE0` | `26` | Yes | The final Buddha's Palms / cannot be destroyed. You'll / have to dodge them deftly! |
| `0x003B78` | `27` | No | As for the final Demon / King, I know nothing at / all! Please be careful!! |

---

## 3. All 14 Pre-Rendered Graphic Assets

| Asset | Tiles Span | Tile Ptrs | Map Span | Map Ptrs | Palette | English Text |
|---|---|---|---|---|---|---|
| `TitleMenu` | `0x00D1E8..0x00D6C4` (d222) | `0x006F4A` (+DMA `0x006F86`) | `0x00D100..0x00D1E8` (fixed 232B) | Inline DMA | `0x00CEF2` (bank 15) | `START GAME` / `PASSWORD` / `OPTIONS` |
| `TitleLogo` | `0x0B54CC..0x0B69BF` (d222) | `0x006590` | `0x0B51A8..0x0B54CB` (d222, 40x30) | `0x00659C` | `0x0B5188` (bank 14) | `JOURNEY / TO THE / LAUGH` |
| `PasswordPlaque` | `0x05560E..0x055C51` (d222) | `0x00CE42` | `0x02AAA2..0x02AC48` (d222, `0028001E` + 40x30) | `0x00CE46, 0x00CE4A, 0x00CE4E` | `0x0AE108` (bank 4) | `PASSWORD` |
| `GiftBox` | `0x0AD47E..0x0AE107` (d222) | `0x00582C` | `0x0AD31C..0x0AD47D` (d222, 20x15) | `0x005838` | `0x0AD2FC` (bank 3) | `SALTED / CRACKERS` |
| `GameOver` | `0x0FBCFA..0x0FBF00` (d222) | `0x0EE700` | `0x0FBF00..0x0FBFC3` (d222, `0028001E` + 40x30) | `0x0EE70C` | `0x0FBCDA` (bank 15) | `GAME OVER` |
| `end1` | `0x0EF7CE..0x0F020F` (`wc`+d222) | `0x0EEFA8, 0x0EEFBE` | `0x0F0210..0x0F042C` (d222, 64x32) | `0x0EEFAE` | `0x0EF42E` (bank 10, fg 14) | Wukong, your attitude on your / first trip West was arrogant! |
| `end2` | `0x0F042C..0x0F15CF` (`wc`+d222) | `0x0EEFF8, 0x0EF03E` | `0x0F15D0..0x0F186C` (d222, 64x32) | `0x0EEFFE, 0x0EF044` | `0x0EF42E` (bank 10, fg 9) | You hurled insults at us! |
| `end3` | `0x0F85A8..0x0F9EF2` (`wc`+d222) | `0x0EF064, 0x0EF09E` | `0x0F9EF2..0x0FA1B9` (d222, 64x32) | `0x0EF06A, 0x0EF0A4` | `0x0EF42E` (bank 10, fg 9) | And to us... to us... it was... |
| `end4` | `0x0FA1BA..0x0FB9FA` (`wc`+d222) | `0x0EF0C4, 0x0EF0EC` | `0x0FB9FA..0x0FBCDA` (d222, 64x32) | `0x0EF0CA, 0x0EF0F2` | `0x0EF42E` (bank 10, fg 9) | W A Y   T O O   G O O D !! |
| `end5` | `0x0F186C..0x0F2F71` (`wc`+d222) | `0x0EF112` | `0x0F2F72..0x0F327A` (d222, 64x32) | `0x0EF118` | `0x0EF42E` (bank 10, fg 9) | Ahem! So I decided to make / you endure more trials! |
| `end6` | `0x0F327A..0x0F486E` (`wc`+d222) | `0x0EF14C` | `0x0F486E..0x0F4B5D` (d222, 64x32) | `0x0EF152` | `0x0EF42E` (bank 10, fg 9) | To soothe my own... |
| `end7` | `0x0F4B5E..0x0F61F3` (`wc`+d222) | `0x0EF17C` | `0x0F61F4..0x0F6521` (d222, 64x32) | `0x0EF182` | `0x0EF42E` (bank 10, fg 9) | Cough! Cough! To cure / your unruly nature! |
| `end8` | `0x0F794A..0x0F8398` (`wc`+d222) | `0x0EF1A4, 0x0EF1BA` | `0x0F8398..0x0F85A7` (d222, 64x32) | `0x0EF1AA` | `0x0EF42E` (bank 10, fg 14) | Your merit is now complete! / I dub you Fighting Buddha!! |
| `end9` | `0x0F6522..0x0F768F` (`wc`+d222) | `0x0EF214` | `0x0F7690..0x0F794A` (d222, 64x32) | `0x0EF21A` | `0x0EF42E` (bank 10, fg 9) | Follow me to Spirit Mountain / for your title! Amitabha! |

---

## 4. Audited Exclusions (Confirmed Non-Text / Already English)

- **Gameplay HUD & Pause screen**: Icons + numeric counters only; pause desaturates palette only.
- **Title Logo bottom copyright** (`rows 26..28` of `0x0B51A8`): Already English `"©1995 FUNTECH ALL RIGHTS RESERVED."`.
- **Password icons**: 10 non-text character head portraits.
- **`0x0A9170`**: False positive inside raw 16x16 Taiwanese glyph bitmap region (`0x0A6686..0x0A9226`).
- **`0x1F9CC6` & `0x1FA956`**: Compressed level/map tables copied to `$FF0000` only for game states `$C12E == $28/$29` (`0x1EF6D8`).
