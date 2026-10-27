# Measuring frame times on macOS (optional)

`scfps.c` is a small library that the game loads at launch through `DYLD_INSERT_LIBRARIES`. The signature of the
Mac builds of BG:EE and BG2:EE allows it (entitlements `com.apple.security.cs.allow-dyld-environment-variables` and
`com.apple.security.cs.disable-library-validation`). It changes no game file.

- It wraps `-[NSOpenGLContext flushBuffer]` to time every frame, and counts texture uploads (`glTexImage2D`,
  `glTexSubImage2D`, `glCompressedTexImage2D`) and draw calls (`glDrawArrays`) by dyld interposition.
- Once per second it appends a line to the CSV file named by `SCFPS_LOG` (default `/tmp/scfps.csv`).
- It keeps macOS App Nap off while the game runs, so a hidden game is not slowed down.
- It can also drive the game, so that runs can be repeated without touching the mouse: lines written to `cmd.txt`,
  next to the library, are run in order (`move X Y`, `click X Y`, `dclick X Y`, `rclick X Y` in points from the
  top-left corner of the window content; `key CODE` with a Mac key code; `sleep MS`; `mark TEXT`; `info`; `exit`).
  Mouse events go straight to SDL on the main thread, so the game does not need to be in front. A report is
  written to `etat.txt`.

## Build and run

```sh
# on a Mac with the Command Line Tools
clang -shared -O2 -undefined dynamic_lookup -o scfps.dylib scfps.c
codesign -s - -f scfps.dylib
# or from Linux: python3 -m ziglang cc -target aarch64-macos -shared -O2 -Wl,-undefined,dynamic_lookup -o scfps.dylib scfps.c

./run.sh "/path/to/Baldur's Gate II Enhanced Edition/BaldursGateIIEnhancedEdition.app" orig.csv
python3 summary.py orig.csv
```

Work on a copy of the game if you can: the library changes nothing, but a test run is still a game session.

## Log columns

The header is written in French. In order: `t_s` time since launch (s); `images` frames in that second;
`intervalle_moy_ms`, `intervalle_max_ms` mean and longest frame interval; `cpu_rendu_moy_ms`, `cpu_rendu_max_ms`
CPU time of the rendering thread per frame (the main thread in BG2:EE 2.7.3); `attente_flush_moy_ms` time spent
inside `flushBuffer`; `cpu_processus_pct` CPU of the whole process, in % of one core; `memoire_mo` resident memory
(MB); `textures_envois`, `textures_mo` texture uploads and MB uploaded in that second; `dessins_par_image` draw calls
per frame; `visible`, `actif` whether the window was visible and the game in front. `# mark` lines come from the
`mark` command; `summary.py` uses the `scene-debut` and `scene-fin` marks when present.
