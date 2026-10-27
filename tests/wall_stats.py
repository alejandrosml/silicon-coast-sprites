# wall_stats.py - frequence, sur de vraies zones, des murs qui touchent la zone HD d'un cadre SC-HD
# sans toucher le sprite lui-meme (cas qui donnerait des defauts), selon les regles du moteur.
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from wed import Wed, search_map
from engine_sim import raster_poly
from bam import BamV1
import schd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# WED et carte de recherche (SR.BMP) des zones, extraits du jeu : ../all/areas/ ou la variable SC_AREAS
U = os.environ.get('SC_AREAS', os.path.join(ROOT, 'all', 'areas')) + os.sep
rng = np.random.default_rng(3)
b = BamV1.load(open(os.path.join(ROOT, 'all', 'src', 'CHMB1A1.BAM'), 'rb').read())
fr = b.frames[10]
h, w = fr.pix.shape
k = 4
WALKABLE = {1, 2, 3, 4, 5, 6, 7, 9, 14, 15}

def regions(anchor, layout, mirrored):
    W, H, (px, py), (hx, hy) = schd.layout_dims(w, h, k, layout)
    cx2, cy2 = px + fr.cx, py + fr.cy
    fxw, fxh = W + 2, H + 2
    refx, refy = cx2 + 1, cy2 + 1
    L = anchor[0] - (fxw - refx) if mirrored else anchor[0] - refx
    T = anchor[1] - refy
    def wr(x0, y0, ww, hh):   # rect local du cadre -> rect monde (miroir compris)
        if mirrored:
            return (L + fxw - 1 - (x0 + ww), T + 1 + y0, L + fxw - 1 - x0, T + 1 + y0 + hh)
        return (L + 1 + x0, T + 1 + y0, L + 1 + x0 + ww, T + 1 + y0 + hh)
    return (L, T, L + fxw, T + fxh), wr(px, py, w, h), wr(hx, hy, k * w, k * h)

def frac(polys, wd, r):
    L, T, R, B = r
    if R <= L or B <= T:
        return 0.0
    m = np.zeros((B - T, R - L), bool)
    for i in polys:
        m |= raster_poly(wd.polys[i]['pts'], L, T, R - L, B - T)
    return m.mean()

for area in ('AR0602', 'AR0700', 'AR0300'):
    wd = Wed(open(U + area + '.WED', 'rb').read())
    sm = search_map(open(U + area + 'SR.BMP', 'rb').read())
    ys, xs = np.nonzero(np.isin(sm, list(WALKABLE)))
    n = 300
    pick = rng.choice(len(xs), n, replace=False)
    cnt = dict(any_wall=0, probe=0, hd_only=0, hd_and_probe=0)
    for lay in (schd.LAYOUT_TOP, schd.LAYOUT_SIDE):
        c = dict(any_wall=0, probe=0, hd_only=0, both=0, n=0)
        for i in pick:
            anchor = (int(xs[i] * 16 + 8), int(ys[i] * 12 + 6))
            for mir in (False, True):
                fxr, pr, hr = regions(anchor, lay, mir)
                polys = wd.applied(fxr, anchor)
                c['n'] += 1
                if not polys:
                    continue
                c['any_wall'] += 1
                fp = frac(polys, wd, pr); fh = frac(polys, wd, hr)
                if fp > 0.01 and fh > 0.01:
                    c['both'] += 1
                elif fp > 0.01:
                    c['probe'] += 1
                elif fh > 0.01:
                    c['hd_only'] += 1
        print(area, 'disposition', 'haut' if lay else 'cote', {k2: f'{100 * v / c["n"]:.1f}%' for k2, v in c.items() if k2 != 'n'},
              'positions', c['n'], 'polygones', len(wd.polys))
