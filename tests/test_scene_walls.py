# test_scene_walls.py - murs reels d'AR0602 aux positions de la scene en jeu (wyverne en 4 quarts, Demogorgon, dragon),
# mode "atenuer" (Always Dither) : l'attenuation du HD doit suivre celle de l'original.
import os, sys, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_allscene as T
from engine_sim import Pages, render_fxfrom
from scene import Job, run_jobs, to_png, WORK
from test_suite import report, masks_iou
from wed import Wed
from wall_stats import U
wd = Wed(open(U + 'AR0602.WED', 'rb').read())
HDD = os.path.join(T.SP, 'all', 'scene_hd')
cases = [('wyverne 4 quarts', ['MWYVG11', 'MWYVG12', 'MWYVG13', 'MWYVG14'], (3900, 1680), 2, 3),
         ('Demogorgon', ['MDEMG111', 'MDEMG121', 'MDEMG131', 'MDEMG141'], (3720, 1700), 0, 2),
         ('dragon', ['MDR11%d04' % p for p in range(1, 10)], (4450, 1520), 4, 3)]
jobs = []; meta = []
for name, files, anchor, c, f in cases:
    for d, sh in ((T.SRC, 'orig'), (HDD, 'new')):
        ls = T.layers(d, files, c, f)
        pg = Pages()
        for cr in ls:
            h, w = cr.pix.shape
            left, top = anchor[0] - cr.cx, anchor[1] - cr.cy
            rect = (left, top, left + w, top + h)
            walls = [(wd.polys[j]['pts'], 'halve') for j in wd.applied(rect, anchor)]
            pg.draw(lambda at, cr=cr, walls=walls: render_fxfrom(at, cr, anchor, False, walls, None))
        cam = (anchor[0] - 300, anchor[1] - 420)
        jobs.append(Job(f'{name[:4]}_{sh}', pg.result(), None, 1.0, cam, 600, 600, shaders=sh))
    meta.append(name)
res = run_jobs(jobs, 'scenewalls')
for name in meta:
    a = res[f'{name[:4]}_orig']['alpha']; b = res[f'{name[:4]}_new']['alpha']
    m = (a > 0.02) | (b > 0.02)
    diff = np.abs(a - b)[m]
    report(f'murs reels AR0602 (attenuer) : {name}', masks_iou(a, b, 0.2) > 0.9 and float(np.mean(diff)) < 0.05,
           iou=round(masks_iou(a, b, 0.2), 3), ecart_alpha_moyen=round(float(np.mean(diff)), 4),
           part_attenuee_orig=round(float(((a > 0.02) & (a < 0.75)).sum() / max(1, (a > 0.02).sum())), 3),
           part_attenuee_hd=round(float(((b > 0.02) & (b < 0.75)).sum() / max(1, (b > 0.02).sum())), 3))
comp = lambda r: r['black'] * 0.5 + 0.5 * r['white']
to_png(os.path.join(WORK, 'scene_walls.png'), np.concatenate([np.concatenate([comp(res[f'{n[:4]}_orig']), comp(res[f'{n[:4]}_new'])], 1) for n in meta], 0))
