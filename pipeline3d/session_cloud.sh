#!/bin/bash
# session_cloud.sh <RESREF> - Silicon Coast, chaîne des monstres 3D : un monstre dans une session cloud (Claude Code
# sur le web), par tranches de moins de 10 minutes : chaque appel avance la chaîne là où elle s'était arrêtée et
# finit par une ligne d'état. À relancer jusqu'à « TERMINÉ ».
#   bash pipeline3d/session_cloud.sh MGIT          (depuis la racine du dépôt silicon-coast-sprites)
# Données (BAM d'origine, captures de mouvement, dessin et modèle 3D) : dépôt Hugging Face privé SC_HUB, lu grâce au
# secret réseau de l'environnement. Blender 5.2.3 : téléchargé une fois. La conversion SC-HD et la vérification
# finale se font ensuite dans la session principale (outils du dépôt pas encore publiés).
set -u
RES=$(echo "$1" | tr a-z A-Z)
R=$(cd "$(dirname "$0")/.." && pwd)
W=${SC_RACINE:-$HOME/sc3d}
DEPOT=${SC_HUB:-aisml/silicon-coast-3d}
BUDGET=${SC_TRANCHE_S:-520}
T0=$(date +%s)
mkdir -p "$W"
reste() { echo $(( BUDGET - ( $(date +%s) - T0 ) )); }

python3 -c "import huggingface_hub, numpy, PIL" 2>/dev/null || pip install -q --break-system-packages huggingface_hub numpy pillow > /dev/null 2>&1
if [ ! -f "$W/.donnees_$RES" ]; then
  python3 - "$RES" "$W" "$DEPOT" <<'PY' || { echo "ÉCHEC : dépôt Hugging Face injoignable"; exit 2; }
import sys
from huggingface_hub import snapshot_download
res, w, depot = sys.argv[1:4]
snapshot_download(depot, repo_type='dataset', local_dir=w,
                  allow_patterns=['mocap/lib/**', 'jeu/src/%s*' % res, 'monstres/%s/**' % res])
PY
  touch "$W/.donnees_$RES"
  echo "données reçues"
fi
if [ ! -x "$W/blender/blender" ]; then
  curl -sL https://download.blender.org/release/Blender5.2/blender-5.2.3-linux-x64.tar.xz | tar -xJ -C "$W" \
    && mv "$W/blender-5.2.3-linux-x64" "$W/blender" || { echo "ÉCHEC : Blender introuvable"; exit 3; }
  echo "Blender installé"
fi
export SC_SRC=$W/jeu/src SC_BLENDER=$W/blender/blender SC_MOCAP=$W/mocap/lib SC_SPRITES=$R
TRAV=$W/monstres/$RES
code=124
t=$(reste)
if [ "$t" -gt 60 ]; then
  timeout "$t" python3 "$R/pipeline3d/chaine.py" "$RES" --travail "$TRAV" --sans-gpu --sans-schd >> "$W/chaine_$RES.txt" 2>&1
  code=$?
fi
if [ "$code" -eq 124 ] && [ -d "$TRAV/rendu/images" ]; then
  # coupé en plein rendu : la dernière image écrite peut être incomplète, elle sera refaite
  d=$(ls -t "$TRAV"/rendu/images/*.png 2>/dev/null | head -1)
  if [ -n "$d" ]; then b=${d%_mask.png}; b=${b%_ombre.png}; b=${b%.png}; rm -f "$b.png" "$b.json" "$b"_mask.png "$b"_ombre.png; fi
fi
python3 - "$TRAV" "$RES" <<'PY'
import glob, json, os, sys
trav, res = sys.argv[1:3]
e = json.load(open(os.path.join(trav, 'etat.json'))) if os.path.exists(os.path.join(trav, 'etat.json')) else {}
ordre = ['origine', 'dessin', 'modele', 'rig', 'arme', 'mouvements', 'lumiere', 'rendu', 'ombre', 'bams', 'schd', 'controle']
faites = [k for k in ordre if e.get(k, {}).get('ok')]
cours = next((k for k in ordre if not e.get(k, {}).get('ok')), None)
n = len(glob.glob(os.path.join(trav, 'rendu', 'images', '*_mask.png')))
total = 0
cfg = os.path.join(trav, 'rendu', 'cfg.json')
if os.path.exists(cfg):
    total = len(json.load(open(cfg)).get('jobs', []))
print('%s : étapes faites %d/12, en cours : %s, images rendues %d%s' % (
    res, len(faites), cours or 'aucune', n, ('/%d' % total) if total else ''))
PY
if [ "$code" -eq 0 ]; then
  cd "$R/pipeline3d" && python3 hub.py poser "$TRAV" "monstres/$RES" "session cloud $RES" --sauf=rendu/lumiere/* > /dev/null 2>&1 \
    && echo "TERMINÉ : résultats envoyés sur le dépôt (monstres/$RES)" || echo "ÉCHEC : envoi des résultats impossible"
elif [ "$code" -ne 124 ]; then
  echo "ÉCHEC : la chaîne s'est arrêtée (code $code). Fin du journal :"
  tail -5 "$W/chaine_$RES.txt"
else
  echo "EN COURS : relancer la même commande"
fi
