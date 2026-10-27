# Constructor emulation (research, optional)

`tables/groups.json` says which BAM files the engine draws together and by which path. It was built from what the
animation constructors of the game actually load, obtained by running them in an emulator. You only need this folder
to rebuild the tables for another build of the game.

**What is emulated.** For every animation ID, the constructor of its class (`CGameAnimationType<Class>::
CGameAnimationType<Class>`) runs on the real arm64 code with Unicorn. As in the engine, it first calls
`Unmarshal(<ID>.INI)`, which reads the animation's INI file (`resref`, `glow_layer`, `shadow`, `split_bams`…); the
INI is served from the files you extracted from the game. If the INI is missing, the constructor takes its hardcoded
values, also as in the engine (36 IDs of `ANIMATE.IDS`: effects and Icewind Dale IDs without data). Every resource
the constructor asks for (`CVidCell` loads) is recorded. Engine calls that do not matter here (palettes, rule
tables…) return 0.

`emu_all.py` is the first version, which skipped the INI reader: 135 animations then got the hardcoded fallbacks
(for example the Icewind boar `MBOA` loaded `MMYC`, the myconid). It is kept for reference only.

## Requirements

- the game executable of BG2:EE 2.7.3 for macOS, arm64 slice, saved here as `bg2_arm64`
  (`lipo -thin arm64 -output bg2_arm64 <game executable>`). The addresses in these scripts are those of this build:
  SHA-256 of the slice `6454b380b64161f58939ae9ee4d7ba03be46bb53eff4c45d0ffaa1bde2073439`;
- the animation INI files of the game (resources named after the ID: `7F3B.INI`, `E265.INI`…) and `ANIMATE.IDS`;
- Python 3 with `unicorn`, `capstone`, `lief` and `numpy`; `c++filt`.

## Steps

```sh
python3 stubs.py          # import stubs            -> stubs.pkl
python3 xref.py           # calls and references    -> xref.pkl
python3 trie_scan.py      # exported symbol names   -> trie_names.pkl
python3 demangle.py       # demangled names         -> names_dem.pkl
python3 emu_ini.py <INI folder> <ANIMATE.IDS> all_anims_ini.json

cd ../tools
python3 anim_table.py <INI folder> anim_table.json
python3 inventory.py <original BAMs> inv.pkl
python3 groups.py anim_table.json ../re/all_anims_ini.json inv.pkl groups.json
python3 canon_tables.py inv.pkl groups.json canon_all.json
```

With BG2:EE 2.7.3 this gives the two files in `tables/` (10,284 BAM files in 17 creature classes).

`rx.py` holds the disassembly helpers used by the other scripts (function starts, names, annotated listings).
