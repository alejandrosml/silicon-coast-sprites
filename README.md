# Silicon Coast — HD creature sprites for the Enhanced Edition, without a DLL

**HD creatures in Baldur's Gate II: EE on macOS (Apple Silicon, native), drawn at their original size and place,
with no DLL, no EEex and no engine patch: only BAM files and five GLSL shaders in `override`.**

Status on 27 October 2026: every creature animation of BG2:EE 2.7.3 is converted and verified by calculation (17
classes, the 10,284 BAM files the engine loads for them), and one in-game test with a creature of every class on the
same screen passed (M1 Max, BG2:EE 2.7.3 from Steam, a separate copy of the game). The HD images used so far are a
Scale4x demo; the format is meant to carry real HD art (AI upscales such as bg2hd's ×2 with its sub-shades, or 3D
re-renders).

## How it works, in short

The engine composes each creature on the CPU, at 1 texel = 1 world pixel, in an "FX surface" where it also applies
palette effects and wall polygons, then draws one quad. SC-HD keeps that pipeline intact. Each animation frame stays at
engine scale and carries:

1. **markers** (spines on the frame edges, or blocks on every 8th row), which the shaders read to recognise the frame;
2. a **probe block**, an opaque rectangle exactly where the original sprite was. The engine applies walls,
   transparency and selection to it at 1:1, and the shader uses it as a mask;
3. the **HD image** (k× the original, same palette indices, so remaps, tints, greyscale and shadows still apply).

The vertex shader shrinks the quad back onto the probe block; the fragment shader samples the HD image and multiplies
by the probe. Anything that is not an SC-HD frame goes through Beamdog's original shader code, unchanged. The full
specification is in [FORMAT.md](FORMAT.md).

Every engine rule used here comes from the disassembly of the Mac binary (constructors of the 18 animation classes
emulated with their INI files, `Render`, `CalculateFxRect`, `ChangeDirection`, `IncrementFrame`, `FXBltFromClipped`,
`FXBltFrom`, `FXRenderClippingPolys`, `DrawLockSurface`…), then reproduced in an offline simulator that renders scenes
with the real shaders in WebGL.

## What is verified

### By calculation, on every file

`sc_verify.py` decodes every frame the way the shaders do and checks markers, geometry, anchor, probe, HD silhouette,
palette indices, and that all layers of one FX surface share one geometry.

| Set | Files | Frames (positions / HD) | Errors |
|---|---|---|---|
| All creature animations of BG2:EE 2.7.3 (17 classes) | 10,284 | 5,492,738 / 2,497,608 | 0 |
| In-game test set (installed in the test copy) | 1,780 | 1,121,450 / 412,816 | 0 |

**Which files.** Every animation constructor was run in an emulator on the real arm64 code, with the animation's
INI file read as the engine does (`Unmarshal`): 468 animation IDs are defined by an INI file, and 36 more IDs of
`ANIMATE.IDS` take the constructor's hardcoded values ([re/README.md](re/README.md)). The 10,284 files are everything
these constructors load for the 17 creature classes, together with the files the classes load while drawing (split
bodies, weapons, glow layers, shadows, tiles). BAMs that only look like creature animations and that nothing loads in
2.7.3 are left alone: the `SSHD` shadow, Icewind-style `MFIG` files, `MSOL`, `MASL` and `MDJC` (the INI files use
`MSOG`, `MASG` and `MDJL` instead)… Effect animations are not converted (see the limits). Details per class:
[docs/COVERAGE.md](docs/COVERAGE.md).

A first version of this emulation skipped the INI reader, so 135 animations got the constructors' fallback values.
Redone on 27 October: 24 more files to convert (the Icewind boar), 10 shadow files that no animation uses any more,
and a smaller common geometry for the CharacterOld layers (1,774 files converted again, including the 54 of the
in-game test set, which were reinstalled and re-verified).

### Offline, rendered with the real shaders (simulated engine, WebGL/SwiftShader)

| Test | Result |
|---|---|
| One creature of every class in one scene (Character ×5 size classes with 2–4 layers, CharacterOld, Monster, MonsterIcewind, MonsterLayered, MonsterLayeredSpell, MonsterOld, MonsterLarge, MonsterLarge16, MonsterAnkheg, Ambient, AmbientStatic, Flying, TownStatic, MonsterQuadrant, MonsterMulti 3×3 dragon, MonsterMultiNew) × no walls / halving walls / palette effects / outlines / zoom ×2 | ✅ HD silhouette ≈ original for every class (IoU ≥ 0.87, mean ≥ 0.95), no stray texel anywhere |
| Non-SC-HD frames and quads with the new shaders | ✅ pixel-identical to Beamdog's shaders |
| Layout F (wyverns, dragons, Demogorgon): viewport cuts on every side and corner, frames touching in the atlas, mirrored, halving walls, palette effects, outlines | ✅ IoU ≥ 0.94; nothing drawn outside the viewport; texel-exact at zoom ×4 |
| Sub-shade planes (bg2hd Q3M formula), both layouts, tint and greyscale | ✅ pixel-exact |
| Real BG2 walls (WED of AR0602, AR0700), "Always Dither" on | ✅ attenuation identical to the original |
| Equipped characters: 48 images × 3 zooms, 8 directions, mirror, 6 equipment sets | ✅ IoU ≥ 0.93, texel-exact at zoom ×4 |
| Mirrored creatures with sprite outlines | ✅ (bug found and fixed on 26/10) |

### In game (BG2:EE 2.7.3, M1 Max, separate copy of the game)

Test save with 22 creatures of every class around the party (Abdel equipped), in the big room of AR0602:

| Check | Result |
|---|---|
| The five shaders compile and link on Apple's OpenGL; menus, UI, area, movies | ✅ |
| Dragon (MonsterMulti, 9 tiles), Demogorgon (MonsterMultiNew), wyvern (MonsterQuadrant) | ✅ HD, seamless tiles, at their place; the dragon is cut cleanly by the viewport edge |
| Equipped characters (human ×2, elf, dwarf, halfling: body + weapon + shield + helmet), monk (CharacterOld), sahuagin, hobgoblin, siren, skeleton (layered weapons), ghoul, ogre, wyvern (Large16), cow, eagle | ✅ all layers HD, right order and place, no raw frame or marker anywhere |
| Creatures behind wall polygons (dither) | ✅ attenuated like the originals |
| Mirrored directions, walking party, zoom in and out | ✅ |
| Saves | ✅ none touched (the test save is a separate folder) |

Screenshots: `docs/ingame-*.jpg`.

## Contents

```
FORMAT.md                 the format, for implementers
shaders/                  VPDRAW, FPDRAW, FPTONE, FPSPRITE, FPSELECT (built) — copy to override/
shaders/src/              sources (VPDRAW.GLSL, hd_common.glsl) and build_shaders.py
tools/sc_convert.py       converter: any class, any k, demo upscale or external HD (+ sub-shade planes)
tools/sc_verify.py        verification by calculation
tools/schd.py, bam.py     format library, BAM V1/BAMC reader-writer (bam_rle.c: optional fast RLE decoder)
tools/groups.py, canon_tables.py, inventory.py
                          build the layer groups and canonical geometries from the engine data
tables/                   groups.json and canon_all.json for BG2:EE 2.7.3
re/                       constructor emulation (needs the game binary and Unicorn)
tests/                    offline engine simulator and test suites (WebGL via Playwright)
scene/                    the in-game test: converter run, installer, test-save builder
docs/                     screenshots and test sheets
```

## Usage

```sh
# 1. convert (Scale4x demo upscale; k chosen per frame, at most 4)
python3 tools/sc_convert.py build <original BAMs> tables/groups.json tables/canon_all.json <out> -j 8
#    with real HD art: same names and cycles, frames k× larger with centre k·(cx, cy), same palette indices
python3 tools/sc_convert.py build <original BAMs> tables/groups.json tables/canon_all.json <out> --hd <HD BAMs> [--sub <F BAMs>]

# 2. verify every frame by calculation
python3 tools/sc_verify.py <original BAMs> <out> tables/groups.json tables/canon_all.json -j 8

# 3. install: the five shaders and the converted BAMs in the game's override folder
```

Files that share an FX surface (a body and all the equipment of its size class, a monster and its weapon files)
must be converted together: an HD body with an original weapon, or the reverse, would not display correctly.

## Requirements and limits

- **Keep "Always Dither" on** (Game Options; it is the engine default). With it off, walls erase texels instead of
  halving them: HD areas covered by a wall leave holes, and a creature framed by two wall pieces can show its raw
  frame.
- **CPU and memory grow with k².** The engine copies every layer into the FX surface on the CPU each frame, and the
  temporary 1024² atlas is flushed more often. Frame times have not been measured yet.
- **Disk:** about 6× the original BAMs at k = 4.
- **"HP over head"** bars appear higher (the engine uses the frame height).
- **Effect animations** (22 IDs: fire rings, chunks, blood, glyphs…) are not converted.
- **Shaders:** the five files go together and replace the same slots as other shader packs. They contain Beamdog's
  original code paths, unchanged, for everything that is not SC-HD.

## Licence and credits

MIT for the tools, tests, format and the Silicon Coast parts of the shaders. Baldur's Gate II: Enhanced Edition and its
assets belong to their owners; nothing from the game is distributed here, the converter works on the player's own
files. Scale4x is the classic EPX/AdvMAME algorithm. The sub-shade formula is the one documented by the bg2hd project
(Gaurox).
