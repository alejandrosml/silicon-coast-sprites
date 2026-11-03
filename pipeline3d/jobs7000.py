# jobs7000.py - Silicon Coast, chaîne des monstres 3D, étape 6 : configuration de rendu (bl_anim.py) pour toutes les
# images HD d'un monstre de type 7000.
#   python3 jobs7000.py <RESREF> <travail> [--dirs 0,4] [--seq SD,A1] [--sortie cfg.json] [--echantillon]
# Lit origine/sequences.json, mouvements/choix.json (animations, échelle), rendu/lumiere.json (s'il existe).
# Une image rendue par image HD : séquence S (fichier, cycles 9*s+d), direction d (pas de 22,5° : d/2 en unités de
# 45° pour bl_anim), n images (choix.json : nombre voulu par les règles de fidélité, celui de l'original pour la
# marche, les images uniques pour une frise à motif répété). Les séquences copiées d'une autre dans l'original
# (A4 = A1...) ne sont rendues qu'une fois.
# Rendus : <travail>/rendu/images/<FICHIER>_c<cycle>_f<i>.png (+ _mask.png, .json).
import os
import sys

from commun import ecrit_json, lit_json

ARGS = sys.argv[3:]
opt = lambda n, d, c=str: c(ARGS[ARGS.index(n) + 1]) if n in ARGS else d

LUMIERE_DEFAUT = {
    'engine': 'CYCLES', 'samples': 12, 'k': 4, 'phi_deg': 39, 'ambient': 0.2, 'shadow': False,
    'lights': {'key': {'az_deg': -108, 'el_deg': 60, 'energy': 4.5, 'angle_deg': 3},
               'fill': {'az_deg': 0, 'el_deg': 39, 'energy': 2.5, 'angle_deg': 10, 'shadow': False}},
}
MARGE = 10      # pixels du sprite ajoutés autour du cadre d'origine (le nouveau dessin peut déborder)


def main():
    res, trav = sys.argv[1].upper(), os.path.abspath(sys.argv[2])
    seqs = lit_json(os.path.join(trav, 'origine', 'sequences.json'))
    choix = lit_json(os.path.join(trav, 'mouvements', 'choix.json'))
    lum = lit_json(os.path.join(trav, 'rendu', 'lumiere.json'), {})
    dirs = [int(x) for x in opt('--dirs', os.environ.get('SC_DIRS', '0,1,2,3,4,5,6,7,8')).split(',')]
    seules = opt('--seq', '').split(',') if '--seq' in ARGS else None
    rdir = os.path.join(trav, 'rendu', 'images')
    os.makedirs(rdir, exist_ok=True)
    cfg = dict(LUMIERE_DEFAUT)
    cfg.update({k: v for k, v in lum.items() if k in ('lights', 'ambient', 'samples', 'shadow', 'ombre')})
    rig = os.path.join(trav, 'rig', 'rig.blend')
    anims = {}
    for s, c in choix.items():
        if s.startswith('_') or 'fichier' not in c:
            continue
        boucle = bool(c.get('boucle'))
        anims[s] = dict(fbx=rig, action_blend=c['fichier'], action=s, loop=boucle, lock=False,
                        t0=1, t1=c['n'] + (1 if boucle else 0))
    cfg['anims'] = anims
    # échelle : celle qui donne à la 1re image de l'attente la hauteur de l'original (mouvements.py)
    cfg['scale'] = float(choix['_global']['echelle_px'])
    cfg['hips_bone'] = 'mixamorig:Hips'
    # objet tenu (arme.py) : prise dans le repère de l'os de la main, roulis calé par mouvements.py ; bl_anim.py
    # attend la translation de la prise en pixels du sprite et l'échelle de l'objet (unités du modèle -> pixels)
    arme = lit_json(os.path.join(trav, 'rig', 'arme_modele.json'))
    if arme:
        import math
        import numpy as np
        r = math.radians(choix['_global'].get('arme_roulis', 0.0))
        Ry = np.array([[math.cos(r), 0, math.sin(r), 0], [0, 1, 0, 0], [-math.sin(r), 0, math.cos(r), 0], [0, 0, 0, 1]])
        G = Ry @ np.array(arme['prise'])
        G[:3, 3] *= cfg['scale']
        cfg['club'] = dict(blend=arme['blend'], bone=arme['os'], side=arme['cote'], grip=G.tolist(),
                           scale=cfg['scale'])
        for s, an in anims.items():          # à la mort, l'arme tombe et reste au sol (règles de fidélité, 3)
            n = choix[s]['n']
            if s == 'DE':
                an['club_drop'] = dict(t_drop=1 + 0.35 * (n - 1), t_land=1 + 0.6 * (n - 1))
            elif s == 'TW':
                an['club_drop'] = dict(t_drop=1, t_land=1)
    jobs = []
    for s, info in seqs.items():
        if seules and s not in seules:
            continue
        if info.get('copie_de'):
            continue                                   # rendu une seule fois (fichier de la séquence copiée)
        if s not in anims:
            continue
        n = choix[s]['n']
        for d in dirs:
            cy = info['cycles'][d]
            if not cy:
                continue
            cad = list(cy['cadres'].values())
            g = max(c[2] for c in cad); dr = max(c[0] - c[2] for c in cad)
            hh = max(c[3] for c in cad); bb = max(c[1] - c[3] for c in cad)
            w, h, cx, cyy = g + dr + 2 * MARGE, hh + bb + 2 * MARGE, g + MARGE, hh + MARGE
            for i in range(n):
                base = os.path.join(rdir, '%s_c%d_f%d' % (info['fichier'], cy['cycle'], i))
                jobs.append(dict(anim=s, n=n, i=i, d=d / 2.0, w=w, h=h, cx=cx, cy=cyy, out=base + '.png',
                                 mask=base + '_mask.png', key=s))
    if '--echantillon' in ARGS:          # contrôle : 1re image et image du milieu seulement
        jobs = [j for j in jobs if j['i'] in (0, j['n'] // 2)]
    cfg['jobs'] = jobs
    out = opt('--sortie', os.path.join(trav, 'rendu', 'cfg.json'))
    ecrit_json(out, cfg)
    par = {}
    for j in jobs:
        par[j['key']] = par.get(j['key'], 0) + 1
    print(res, len(jobs), 'rendus', par, '->', out)


if __name__ == '__main__':
    main()
