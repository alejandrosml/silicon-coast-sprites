#!/bin/bash
# install_scene.sh - Silicon Coast (VM Cowork du Mac) : convertit les sprites de la scene de test, les verifie, et
# les installe avec les shaders dans la copie BG-Lab de BG2:EE (jamais dans l'installation Steam).
#   bash install_scene.sh convert   : extraction des BAM d'origine, conversion SC-HD, verification par le calcul
#   bash install_scene.sh install   : anciens sprites et shaders mis de cote, nouveaux installes, manifeste a jour
set -e
# chemins utilises pour le test ; chacun se change par une variable d'environnement
T="${SC_TOOLS:-$HOME/mnt/BG-Lab/lab-build/silicon-coast/tools}"      # tools/, tables/, shaders/ et ingame_files.txt
W="${SC_WORK:-$HOME/work/sc}"                                        # dossier de travail
GAME_LAB="$HOME/mnt/BG-Lab/Baldur's Gate II Enhanced Edition"
GAME="${SC_GAME:-$GAME_LAB}"                                          # copie du jeu (pas l'installation Steam)
SRC_TARS="${SC_SRC_TARS:-$HOME/mnt/BG-Lab/lab-build/sprites-hd/src_all}"  # BAM d'origine (archives tar)
BKROOT="${SC_BACKUP:-$HOME/mnt/BG-Lab/_debug_off}"                  # ce qui est remplace est mis de cote ici
OV="$GAME/override"
case "$1" in
convert)
  mkdir -p "$W/src" "$W/out"
  cp "$T"/*.py "$T"/bam_rle.c "$W/"
  gcc -O2 -shared -fPIC -o "$W/libbamrle.so" "$W/bam_rle.c"
  cd "$W"
  python3 - "$T/ingame_files.txt" "$SRC_TARS" <<'PY'
import tarfile, os, sys
want = set(l.strip().upper() + '.BAM' for l in open(sys.argv[1]) if l.strip())
n = 0
src = sys.argv[2] + '/'
for t in ['anim.01.tar', 'anim.02.tar', 'extra.01.tar']:
    with tarfile.open(src + t) as tf:
        for m in tf.getmembers():
            nm = os.path.basename(m.name).upper()
            if nm in want and not os.path.exists('src/' + nm):
                open('src/' + nm, 'wb').write(tf.extractfile(m).read()); n += 1
print('extraits', n, 'presents', len(os.listdir('src')), 'voulus', len(want))
PY
  python3 sc_convert.py build src "$T/groups.json" "$T/canon_all.json" out --files "$T/ingame_files.txt" -j 4 --log convert.log
  python3 sc_verify.py src out "$T/groups.json" "$T/canon_all.json" --files "$T/ingame_files.txt" -j 4 --report verify.json | tail -3
  ;;
install)
  test -d "$OV" || { echo "override introuvable"; exit 1; }
  BK="$BKROOT/avant-scene-$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$BK"
  n=0
  if [ -f "$OV/.sc-sprites-manifest" ]; then
    while read -r f; do
      [ -n "$f" ] && [ -f "$OV/$f" ] && mv "$OV/$f" "$BK/" && n=$((n+1))
    done < "$OV/.sc-sprites-manifest"
    mv "$OV/.sc-sprites-manifest" "$BK/"
  fi
  for s in VPDRAW FPDRAW FPTONE FPSPRITE FPSELECT; do
    [ -f "$OV/$s.GLSL" ] && mv "$OV/$s.GLSL" "$BK/"
  done
  echo "mis de cote : $n sprites + shaders -> $BK"
  cp "$W"/out/*.BAM "$OV/"
  (cd "$W/out" && ls *.BAM) > "$OV/.sc-sprites-manifest"
  cp "$T"/shaders/*.GLSL "$OV/"
  echo "installes : $(wc -l < "$OV/.sc-sprites-manifest") sprites + $(ls "$T"/shaders/*.GLSL | wc -l) shaders"
  # SC-HD demande l'option « Always Dither » (murs qui attenuent au lieu d'effacer), reglage par defaut du moteur
  LUA="$HOME/mnt/Baldur's Gate II - Enhanced Edition/Baldur.lua"
  if [ -f "$LUA" ] && grep -q "'Always Dither','0'" "$LUA"; then
    echo "ATTENTION : « Always Dither » est desactive dans Baldur.lua ; reactive-le (Options > Jeu) pour SC-HD"
  else
    echo "« Always Dither » : actif (ou par defaut)"
  fi
  ;;
*)
  echo "usage : bash install_scene.sh convert|install"; exit 2;;
esac
