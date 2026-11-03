# lumiere.py - Silicon Coast, chaîne des monstres 3D, étape 6 : lumière et ombre calées sur l'original.
#   python3 lumiere.py <RESREF> <travail>
# 1. Luminosité (règles de fidélité, 4) : rend la 1re image de l'attente, de face, avec la lumière par défaut (soleil
#    -108°/60°, appoint sans ombre depuis la caméra, ambiance), mesure la luminance moyenne de la créature et la
#    compare à celle du sprite d'origine (origine/mesures.json) ; les énergies sont ajustées (au plus 4 passes).
# 2. Ombre (règles 6 : ombre au sol comme les sprites d'origine) : passe d'ombre seule pour la même image, de face
#    et de profil, sous plusieurs directions de soleil ; on garde celle (et le seuil) dont l'ombre visible recouvre
#    le mieux l'ombre de l'original (pixels d'indice 1 du BAM).
# Écrit rendu/lumiere.json (lights, ambient, ombre, seuil_ombre, mesures) et rendu/lumiere/*.png (essais).
import json
import os
import subprocess
import sys

import numpy as np
from PIL import Image

from commun import BLENDER, ICI, K, SRC, ecrit_json, lit_json
from bam import BamV1


def load(p):
    a = np.array(Image.open(p))
    return a.astype(np.float64) / (65535.0 if a.dtype != np.uint8 else 255.0)


def alpha_de(a):
    return a[..., 3] if a.ndim == 3 and a.shape[2] == 4 else a[..., 0] if a.ndim == 3 else a


def luminance(png, mask):
    c = load(png); m = alpha_de(load(mask)) > 0.5
    px = c[..., :3][m]
    return float((0.2126 * px[:, 0] + 0.7152 * px[:, 1] + 0.0722 * px[:, 2]).mean()) if len(px) else 0.0


def blender(cfgp):
    r = subprocess.run([BLENDER, '-b', '-P', os.path.join(ICI, 'bl_anim.py'), '--', cfgp],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if r.returncode != 0:
        print(r.stdout[-3000:]); raise SystemExit('bl_anim a échoué')


def main():
    res, trav = sys.argv[1].upper(), os.path.abspath(sys.argv[2])
    mes = lit_json(os.path.join(trav, 'origine', 'mesures.json'))
    seqs = lit_json(os.path.join(trav, 'origine', 'sequences.json'))
    choix = lit_json(os.path.join(trav, 'mouvements', 'choix.json'))
    base = choix['_global'].get('base', 'SD')
    cible = mes['luminance']
    d = os.path.join(trav, 'rendu', 'lumiere')
    os.makedirs(d, exist_ok=True)
    chemin = os.path.join(trav, 'rendu', 'lumiere.json')
    lum = lit_json(chemin, None)
    if lum and lum.get('ok'):
        print('déjà calé', {k: lum[k] for k in ('ambient', 'seuil_ombre') if k in lum}); return
    lum = {'lights': {'key': {'az_deg': -108, 'el_deg': 60, 'energy': 4.5, 'angle_deg': 3},
                      'fill': {'az_deg': 0, 'el_deg': 39, 'energy': 2.5, 'angle_deg': 10, 'shadow': False}},
           'ambient': 0.2, 'shadow': False}
    cfgp = os.path.join(d, 'cfg.json')

    def cfg_ref(dirs):
        ecrit_json(chemin, lum)
        subprocess.run([sys.executable, os.path.join(ICI, 'jobs7000.py'), res, trav, '--dirs', dirs, '--seq', base,
                        '--sortie', cfgp], check=True, stdout=subprocess.DEVNULL)
        cfg = json.load(open(cfgp))
        cfg['jobs'] = [j for j in cfg['jobs'] if j['i'] == 0]
        for j in cfg['jobs']:
            dd = int(round(j['d'] * 2))
            j['out'] = os.path.join(d, 'ref_d%d.png' % dd); j['mask'] = os.path.join(d, 'ref_d%d_mask.png' % dd)
        cfg['skip_done'] = False
        return cfg

    # 1) luminosité
    histo = []
    for passe in range(4):
        cfg = cfg_ref('0')
        json.dump(cfg, open(cfgp, 'w'))
        blender(cfgp)
        j = cfg['jobs'][0]
        L = luminance(j['out'], j['mask'])
        histo.append(dict(passe=passe, luminance=round(L, 4), cible=round(cible, 4),
                          energie_soleil=lum['lights']['key']['energy']))
        print('passe', passe, 'luminance %.4f cible %.4f' % (L, cible), flush=True)
        if abs(L - cible) <= 0.06 * cible or L <= 0:
            break
        r = min(3.0, max(0.33, (cible / L) ** 2.2))
        lum['lights']['key']['energy'] = round(lum['lights']['key']['energy'] * r, 3)
        lum['lights']['fill']['energy'] = round(lum['lights']['fill']['energy'] * r, 3)
        lum['ambient'] = round(lum['ambient'] * r, 4)
    lum['historique'] = histo

    # 2) ombre : couleur et silhouette dans quatre directions, puis une passe d'ombre (calculée sans rendu, comme
    #    les ombres du jeu : pleine, à bord net) pour chaque direction de soleil essayée, en un seul passage
    cfg = cfg_ref('0,2,4,6')
    json.dump(cfg, open(cfgp, 'w'))
    blender(cfgp)
    info = seqs[base]
    b = BamV1.load(open(os.path.join(SRC, info['fichier'] + '.BAM'), 'rb').read())
    refs = {}
    for j in cfg['jobs']:
        dd = int(round(j['d'] * 2))
        fr = b.frames[info['cycles'][dd]['table'][0]]
        p = fr.pix.reshape(fr.h, fr.w)
        box = json.load(open(os.path.splitext(j['out'])[0] + '.json'))
        obj = alpha_de(load(j['mask'])) > 0.5
        refs[dd] = dict(job=j, ombre_o=(p == 1), cx=fr.cx, cy=fr.cy, box=box, obj=obj)
    variantes = [dict(az_deg=az, el_deg=el, rapide=True) for az in range(-180, 180, 15) for el in (50, 60, 70, 78, 85, 89)]
    c2 = dict(cfg, ombre_seule=True, ombre_variantes=variantes, skip_done=False)
    json.dump(c2, open(cfgp, 'w'))
    blender(cfgp)

    def reduit(a):
        h, w = a.shape[0] // K, a.shape[1] // K
        return a[:h * K, :w * K].reshape(h, K, w, K).mean(axis=(1, 3))

    def iou_variante(k):
        ious = []
        for dd, r in refs.items():
            om = alpha_de(load(os.path.splitext(r['job']['out'])[0] + '_ombre_v%d.png' % k))
            vis = reduit(((om > 0.5) & ~r['obj']).astype(float)) > 0.5
            # même repère : ancre de l'original (cx, cy) <-> ancre du rendu (box cx, cy)
            H, W = r['ombre_o'].shape
            ox = int(round(r['box']['cx'])) - r['cx']; oy = int(round(r['box']['cy'])) - r['cy']
            can = np.zeros((max(H, vis.shape[0]) + 2 * abs(oy) + 4, max(W, vis.shape[1]) + 2 * abs(ox) + 4), bool)
            cv = np.zeros_like(can)
            X0, Y0 = abs(ox) + 2, abs(oy) + 2
            can[Y0:Y0 + H, X0:X0 + W] = r['ombre_o']
            cv[Y0 - oy:Y0 - oy + vis.shape[0], X0 - ox:X0 - ox + vis.shape[1]] = vis
            u = (can | cv).sum()
            ious.append((can & cv).sum() / u if u else 0.0)
        return float(np.mean(ious))

    notes = [(iou_variante(k), k) for k in range(len(variantes))]
    notes.sort(reverse=True)
    for iou, k in notes[:5]:
        print('ombre az %4d el %2d : IoU %.3f' % (variantes[k]['az_deg'], variantes[k]['el_deg'], iou), flush=True)
    iou, k = notes[0]
    az, el = variantes[k]['az_deg'], variantes[k]['el_deg']
    for dd, r in refs.items():                  # garde l'ombre retenue pour le contrôle, efface les essais
        base_o = os.path.splitext(r['job']['out'])[0]
        os.replace(base_o + '_ombre_v%d.png' % k, base_o + '_ombre.png')
        for kk in range(len(variantes)):
            if os.path.exists(base_o + '_ombre_v%d.png' % kk):
                os.remove(base_o + '_ombre_v%d.png' % kk)
    seuil = 0.5
    lum['ombre'] = {'az_deg': az, 'el_deg': el, 'rapide': True}
    lum['seuil_ombre'] = seuil
    lum['iou_ombre'] = round(iou, 3)
    lum['ok'] = True
    ecrit_json(chemin, lum)
    print('lumière : soleil', lum['lights']['key']['energy'], 'appoint', lum['lights']['fill']['energy'], 'ambiance',
          lum['ambient'], '; ombre az', az, 'el', el, 'seuil', seuil, 'IoU %.3f' % iou)


if __name__ == '__main__':
    main()
