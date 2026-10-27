# SC-HD sprite format (Silicon Coast) — specification

Version 3 (26 October 2026): layout v2 for creatures drawn by `FXBltFromClipped`, layout F for creatures drawn
by `FXBltFrom`, optional sub-shade planes. MIT licence.

SC-HD lets the Enhanced Edition engine display creature sprites at k× resolution **without any DLL, EEex or engine
patch**. The HD data travels inside ordinary BAM V1 frames; the engine composes them exactly as usual (palette,
colour remaps, tints, greyscale, transparency, shadows, wall clipping, multi-layer equipment), and the stock shader
slots (`VPDRAW`, `FPDRAW`, `FPTONE`, `FPSPRITE`, `FPSELECT`, loaded from `override`) turn the result back into an HD
sprite drawn at its original size and place.

It was built and verified against BG2:EE 2.7.3 (macOS, universal arm64 + x86_64 binary, OpenGL). Every engine rule
it relies on was read in the disassembly, not guessed. Nothing in it is Mac-specific: the same files should work
wherever the engine loads GLSL from `override` (Linux has not been tried).

## 1. Why a special frame format

The engine composes every creature in a CPU "FX surface" at 1 texel = 1 world pixel (`CInfinity::FXRender`), applies
wall polygons there (`FXRenderClippingPolys`), uploads it to a 1024×1024 atlas (`DrawLockSurface`, shelf allocator,
flushed when full) and draws one textured quad. A plain k× BAM is therefore drawn k× too big, and walls land in the
wrong place. A BAM V2 crashes the FX path (null palette). So an SC-HD frame keeps the engine scale and carries:

- **markers** that let the shaders recognise the frame and read its parameters;
- a **probe block**: an opaque w×h rectangle exactly where the original sprite would be. The engine applies walls,
  transparency and selection effects to it at 1:1, and the fragment shader reads the result as a mask;
- the **HD image** (k·w × k·h, same palette indices as the original, so every palette effect still applies).

## 2. Common parameters

| Field | Bits | Meaning |
|---|---|---|
| k | 3 (k−1) | HD factor, 1–8 (per frame) |
| w, h | 10 + 10 | size of the original sprite (= probe block) |
| flags | 4 | bit 0: palette with alpha entries; bit 1: sub-shade planes; bits 2–3: plane-grid columns − 1 |
| layout | 1 (v2) / 1 (F sub-layout) | TOP or SIDE |

A frame is at most 1000×1000 texels (FX surface plus margins must fit the 1024² atlas). The converter picks, per
geometry, the largest k ≤ k_max that fits. With BG2:EE 2.7.3 and k_max = 4: 1,182,142 HD frames at k = 4, 3,048 at
k = 3 and 48 at k = 2 (the largest monsters and dragon tiles).

Which layout a file gets depends on the engine draw path of its animation class (§6), never on the file name alone.

## 3. Layout v2 — creatures drawn by `FXBltFromClipped`

Used by Character, CharacterOld, Monster, MonsterIcewind, MonsterLayered(Spell), MonsterOld, MonsterLarge(16),
MonsterAnkheg, Ambient(Static), Flying and TownStatic. Their quad is the FX surface cut to its inner rectangle:
(1, 1, w−1, h−1), or (2, 2, w−3, h−3) with sprite outlines; mirrored quads use tc.x = w − tc.x.

```
TOP:   W = 2·60 + cols·k·w           H = rows·k·h + 4 + h    HD at (60, 0)          probe at (60, rows·k·h + 4)
SIDE:  W = 2·60 + w + 4 + cols·k·w   H = rows·k·h            HD at (60 + w + 4, 0)  probe at (60, H − h)
```

**Spines.** Columns 0–59 (read left→right) and W−1…W−60 (read right→left) carry, on the rows the vertex shader reads
(rows 0–7 and H−8…H−1, every 8th row from each edge, and the a0/shadow sampling rows), 58 alpha bits (opaque = 1): a
12-bit pattern (PA left, PB right), row index (10), layout (1), k−1 (3), w (10), h (10), flags (4), checksum (8) =
(r + 37·layout + 53·(k−1) + 7·w + 11·h + 97·flags + 89) mod 256; column 58 is a texel of palette index 1 (shadow
reference).

**Vertex shader.** Creature blits have `aRef.y` = 1 (2 with sprite outlines); every other quad is left untouched.
Each vertex tries the four corner hypotheses (horizontal offsets 0/0, or 2/1 with outlines, swapped when mirrored),
reads spine rows from its corner (rows 0–7, then every 8th row up to 1024), and accepts a row when:

1. the opposite spine shows the same row (first pass), or
2. another row of the same spine, 8–24 rows further, decodes to the same parameters (second pass, used when an
   "erasing" wall wiped the opposite spine).

It then moves itself onto the matching corner of the probe block (±2 texels for outline halos) and passes the frame
parameters to the fragment shader **with weight 1**. A vertex that finds nothing keeps its place and passes weight 0.
The fragment shader divides the interpolated values by the interpolated weight: the quad stays correct (moved and
unmoved vertices lie on the same tc↔position mapping) as long as one vertex of each triangle found the frame, and
fragments outside the probe are discarded.

## 4. Layout F — creatures drawn by `FXBltFrom`

Used by MonsterQuadrant (wyverns, 2×2 tiles), MonsterMulti (dragons, 3×3 tiles) and MonsterMultiNew (Demogorgon,
2×2 tiles). Their FX surface is exactly the frame size, without margin, and the quad is clipped to the game viewport
(`CInfinity+0x78`). Two consequences, both found in the disassembly: a clipped vertex is not on a frame corner, and two
frames allocated side by side in the atlas share corner vertices **with identical attributes** — no vertex shader can
tell which frame such a vertex belongs to. Layout F therefore never moves vertices and lets the fragment shader decode
the frame:

- W is a multiple of 128 and H a multiple of 8, so frames that touch in the atlas share the same *phase*
  (origin mod 128, mod 8);
- every 8th row ("special row", row 0 included) is made of 128-column blocks of eight 16-column sub-blocks: sync
  `0110`, sub-block index (3 bits), 9 data bits; block data = block index b (3), special-row index m (7), k−1 (3),
  w (10), h (10), flags (4), sub-layout (1), checksum (12) = (7b + 13m + 53(k−1) + 31w + 37h + 97·flags + 131·sub
  + 1543) mod 4096; the last texel of each block is the shadow reference (index 1);
- the HD image skips special rows: HD row j is frame row j + ⌊j/7⌋ + 1;
- the probe block sits where the original sprite was, with a 4-texel margin (for outline halos); TOP-F puts the HD
  image above the probe, SIDE-F beside it.

**Vertex shader:** finds any F block near the vertex (exact origin `aTc − aRef` first, then frame edges, then a local
search) and outputs the frame phase as two unit circles (θx = 2π·origin.x/128, θy = 2π·origin.y/8), plus hints
(w, h, k, flags) and the a0/shadow references. A vertex that finds nothing outputs zeros: the interpolated direction
stays exact, only its length drops.

**Fragment shader:** recovers the phase, locates the block above/left of the fragment, rejects in two texel reads
every fragment that is not probe-coloured, decodes origin and parameters (hints verified by the checksum, full read
otherwise; 13 neighbouring candidates if its own block is damaged), and renders the HD sample masked by the probe — or
discards. Texture derivatives are taken at the top of `main`, before any branch (neighbouring fragments decode
different things, so derivatives inside the branch would be undefined).

## 5. Sub-shade planes (bg2hd "Q3M")

With flag bit 1, the HD area is a grid of five planes (cols × rows, cols from flag bits 2–3): **I** (palette index),
**S** = succ(I) (next shade of the same gradient), and **F0, F1, F2**, where each texel is I (bit 0) or S (bit 1). The
fragment shader compares each F-plane texel's colour with the I and S plane colours — so the bits survive palette
remapping, tints and the pause greyscale — rebuilds F ∈ 0..7 and outputs

```
rgb = (P[I]·(8 − F) + P[S]·F + 4) >> 3          (bg2hd's formula, on the realised palette)
```

then filters, masks and tones as usual. Verified pixel-exact at z = k, on both layouts, with tint and greyscale.

## 6. Which files share a surface, and their geometry

Constructors of every animation class were emulated with the animation's INI file read as the engine does
(`Unmarshal`; 468 IDs have an INI file, 36 IDs take the hardcoded values), which gives 10,284 BAM files for the 17
creature classes of BG2:EE 2.7.3, and `Render`, `CalculateFxRect`, `ChangeDirection` and `IncrementFrame` were
disassembled:

| Class | Draw path | Layers in one FX surface | Frame sync | Canonical geometry |
|---|---|---|---|---|
| Character | FXBltFromClipped | body + weapon + shield + helmet (size class WQL/WQN/WQM/WQS) | overlays `FrameSet` to the body | per cycle **and** frame |
| CharacterOld | FXBltFromClipped | body + shadow (INI `shadow`, CSHD by default) + WP? overlays | each cell `FrameAdvance`s alone | per cycle |
| Monster | FXBltFromClipped | body (G1/G2 + split digit) + weapon (G1xx) + glow layer (INI `glow_layer`) | idem | per cycle |
| MonsterIcewind | FXBltFromClipped | body (action[E]) + weapon (letter + action[E]) | idem | per cycle |
| MonsterLayered(Spell) | FXBltFromClipped | body (G1/G2[E]) + weapons (letter + G1/G2[E]) | idem | per cycle |
| other FXBltFromClipped classes | FXBltFromClipped | one layer | — | tight box per frame |
| MonsterQuadrant / Multi / MultiNew | FXBltFrom | one tile per surface (2×2, 3×3, 2×2 tiles of one image) | — | tight box per frame |
| Effect (22 IDs) | two FXRender | — | — | not converted |

All layers drawn into one FX surface must have **identical frame geometry** for a given cycle/frame, so that the
engine's union rectangle equals the body frame. The union is the max of the content extents (L, T, R, B) around the
anchor over every member file. Per-cycle unions keep the geometry valid when cells drift out of sync.

**Tiles.** Wyverns, dragons and the Demogorgon are images cut into abutting tiles (MDR1 + group + tile 1–9 +
direction; MWYVG + group + quarter 1–4; MDEMG + group + part 1–4), each drawn in its own surface. They must be upscaled
**as one image** and cut back, or the seams show: the converter upscales each tile with a ring of texels from its
neighbours (same cycle and frame) and crops. External HD tiles should come from an upscale of the assembled image.

## 7. External HD input

`sc_convert.py --hd DIR` takes HD BAMs with the same names and cycle/frame structure as the originals, each frame k×
the original size with its centre at k·(cx, cy), using the same palette indices; `--sub DIR` adds the F values (0..7,
one BAM per HD BAM). The converter places them into the canonical geometry, builds the markers, and `sc_verify.py`
checks every frame by calculation (markers decoded the way the shaders do, geometry, anchor, probe, HD silhouette and
palette indices, one geometry per key across files).

## 8. Requirements, costs and limits

- **"Always Dither" must stay on** (`Game Options / Always Dither = 1`, the engine default, read in
  `CInfGame::LoadOptions`). With it, wall polygons halve the alpha of whatever they cover and SC-HD is exact. With it
  off, walls *erase* texels of non-hovered creatures: HD texels erased in the HD area leave holes, and if both spines
  of a v2 frame are erased (a creature framed by two wall pieces) the raw frame is drawn.
- **CPU and memory grow with k².** The engine blits every layer into the FX surface on the CPU each frame, and the
  atlas is flushed more often. k = 2 is about 4× cheaper than k = 4.
- **Disk:** about 6× the original BAMs at k = 4 (zlib BAMC).
- **"HP over head"** bars are placed from the frame height, so they appear higher.
- **Effect animations** (22 IDs) are not converted.
- **The five shaders go together** and replace the same slots as existing shader packs.
