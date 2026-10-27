# Offline tests

Research test bench, not needed to use the format. It simulates the engine's creature path (palette realisation, FX
surface, layer union, 1024² shelf atlas with flushes, wall polygons in "halve" and "clear" modes, quads with `aRef`,
viewport clipping for `FXBltFrom`) and renders scenes with the real shaders in WebGL (SwiftShader, through Playwright:
`harness.js`).

Expected layout: the original BAMs of the game in `../all/src/` (relative to the folder holding these scripts), the
area files used by the wall tests (`AR0602.WED`, `AR0602SR.BMP`, `AR0700.WED`, `AR0700SR.BMP`) in `../all/areas/` or
in the folder named by `SC_AREAS`, the tables in `../all/`, converted sets made with `tools/sc_convert.py`.
`run_all_tests.sh` runs every suite and writes one log per suite plus `summary.txt`. `validate.sh` compiles the
shaders as desktop GLSL 1.10 with glslang.

| Suite | What it checks |
|---|---|
| test_allscene.py | one creature of every animation class in one scene: walls, palette effects, outlines, zoom, stray texels |
| test_layoutF.py | layout F: viewport cuts, frames touching in the atlas, noise neighbours, walls, outlines, texel exactness |
| test_subshade.py | sub-shade planes (bg2hd Q3M formula), pixel-exact, both layouts |
| test_clearwalls.py | "erasing" walls on v2 frames (Always Dither off): no raw frame when one side is erased |
| test_suite.py, test_cases2.py, test_regress.py | v2 single creature: regression vs Beamdog's shaders, geometry, walls, palettes, atlas, outlines |
| test_equip.py, test_equip2.py | equipped characters: layer union, order per direction, mirror, zooms |
| test_realwalls.py, ana_*.py | real BG2 wall polygons (WED) |
