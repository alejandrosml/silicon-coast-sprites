# Coverage: which BG2:EE 2.7.3 files are converted

**How the list was made.** Every animation constructor of the game was run in an emulator on the real arm64 code
([re/README.md](../re/README.md)). As in the engine, the constructor reads the animation's INI file (`Unmarshal`)
and loads what it names; without an INI it takes its hardcoded values. The draw-time files (split bodies, weapons,
glow layers, shadows, tiles) follow each class's naming rules, read in the disassembly (`tools/groups.py`). Every
file on the list is converted and checked by calculation (`tools/sc_verify.py`).

`ANIMATE.IDS` lists 504 animation IDs: 468 are defined by an INI file, and 36 use the hardcoded values (19 effects and
17 Icewind Dale IDs without data, which fall back to the myconid or the `MWWE` files). 133 IDs load no file that
exists in BG2:EE: the INI files are shared with the other Enhanced Editions (Icewind Dale creatures, Siege of
Dragonspear NPCs…), but their BAMs are not in this game.

| Class | IDs (INI + hardcoded) | IDs with files in BG2:EE | BAM files converted | Draw path | Layers drawn together |
|---|---|---|---|---|---|
| Character | 78 | 78 | 4,627 | FXBltFromClipped (v2) | body + weapon + shield + helmet |
| CharacterOld | 8 | 8 | 1,774 | FXBltFromClipped (v2) | body + shadow + weapons |
| Monster | 102 | 77 | 791 | FXBltFromClipped (v2) | body + weapons + glow layer |
| MonsterIcewind | 132 + 17 | 57 | 1,056 | FXBltFromClipped (v2) | body + weapons |
| MonsterLayered | 3 | 3 | 36 | FXBltFromClipped (v2) | body + weapons |
| MonsterLayeredSpell | 4 | 4 | 29 | FXBltFromClipped (v2) | body + weapons |
| MonsterOld | 54 | 46 | 72 | FXBltFromClipped (v2) | one |
| MonsterLarge | 1 | 1 | 6 | FXBltFromClipped (v2) | one |
| MonsterLarge16 | 5 | 3 | 12 | FXBltFromClipped (v2) | one |
| MonsterAnkheg | 1 | 1 | 12 | FXBltFromClipped (v2) | one |
| Ambient | 21 | 18 | 32 | FXBltFromClipped (v2) | one |
| AmbientStatic | 13 | 13 | 26 | FXBltFromClipped (v2) | one |
| Flying | 5 | 5 | 4 | FXBltFromClipped (v2) | one |
| TownStatic | 19 | 18 | 18 | FXBltFromClipped (v2) | one |
| MonsterQuadrant (wyverns) | 9 | 7 | 36 | FXBltFrom (F) | one tile per surface, 2×2 |
| MonsterMulti (dragons) | 9 | 9 | 1,701 | FXBltFrom (F) | one tile per surface, 3×3 |
| MonsterMultiNew (Demogorgon) | 1 | 1 | 52 | FXBltFrom (F) | one part per surface, 2×2 |
| **17 creature classes** | **482** | **349** | **10,284** | | |
| Effect (not converted) | 3 + 19 | 22 | — | two FXRender | — |

Several IDs can share files (for example the colour variants of one monster), so the IDs and files columns do not
add up per animation.

## Checked by calculation

| | |
|---|---|
| Files | 10,284 |
| Frame positions (cycles × frames, every layer) | 5,492,738 |
| of which HD frames | 2,497,608 |
| Layer groups with one common geometry (keys) | 34,365, none with two geometries |
| Errors | 0 |

Full report: `full_verify.json`.

Factor per HD frame (k ≤ 4, the largest that fits the 1024² atlas): 1,182,142 frames at k = 4, 3,048 at k = 3 and 48
at k = 2 (the largest monsters and some dragon tiles).

## Left alone

**Named like creature animations, loaded by no animation of 2.7.3** (found while checking; there may be others):

- `SSHD*` (15 files): a CharacterOld shadow that the hardcoded values give to Sarevok (6404) and to 6621. Their INI
  files give them `CSHD` instead.
- `MSOL*`, `MASL*`, `MDJC*` (47 files): the hardcoded values of IDs 7F3B, 7F3C and 7F41. Their INI files use `MSOG`,
  `MASG` and `MDJL` instead.
- `CSHD*X` (11 files), Icewind-style `MFIG*` (10 files), `NELLEG1`, `NELLEG2`, `MMELSPIN`.

**Effect animations** (22 IDs: fire rings, chunks, blood, glyphs, puffs of smoke, grease, webs…): drawn by the
`Effect` class through two separate `FXRender` calls; not converted.

**Animation 6621** (`XHFF`, the BG1 human female fighter): its INI file exists but its body files are not in BG2:EE;
only the shared shadow `CSHD` is.
