# ana_fwalls.py - par le calcul : pixels visibles perdus par les creatures FXBltFrom (disposition F) sous de
# vrais murs (WED de BG2) en mode "effacant", avec le modele Python des shaders.
import sys, os, json, collections
import numpy as np
from wed import Wed, search_map
from wall_stats import WALKABLE, U
import shader_model as sm
from engine_sim import Atlas, realize_palette, Creature, render_fxfrom
import test_layoutF as TL

rng = np.random.default_rng(int(sys.argv[2]) if len(sys.argv) > 2 else 1)
mode = sys.argv[1] if len(sys.argv) > 1 else 'clear'
sets = [('wyverne', TL.WYV, 2, 3), ('dragon', TL.dragon_parts(), 1, 4)]
out = collections.Counter(); per = []
for area in ('AR0602', 'AR0700', 'AR0300'):
    p = U + area + '.WED'
    if not os.path.exists(p):
        continue
    wd = Wed(open(p, 'rb').read())
    smap = search_map(open(U + area + 'SR.BMP', 'rb').read())
    ys, xs = np.nonzero(np.isin(smap, list(WALKABLE)))
    n = 0
    for i in rng.permutation(len(xs)):
        if n >= 25:
            break
        anchor = (int(xs[i] * 16 + 8), int(ys[i] * 12 + 6))
        kind, parts, c, f = sets[n % 2]
        mir = bool(rng.integers(0, 2))
        # murs appliques : ceux qui touchent le rect de chaque partie (regle du moteur simplifiee : wd.applied)
        lost = vis = 0
        at = Atlas(); quads = []
        for name in parts:
            pix, cx, cy, g, _ = TL.make_f(name, c, f)
            b = TL.bam(name)
            cr = Creature(pix, cx, cy, realize_palette(b.palette), b.tidx)
            left = anchor[0] - ((pix.shape[1] - cx) if mir else cx); top = anchor[1] - cy
            rect = (left, top, left + pix.shape[1], top + pix.shape[0])
            polys = [(wd.polys[j]['pts'], mode) for j in wd.applied(rect, anchor)]
            v, info = render_fxfrom(at, cr, anchor, mir, polys, None)
            quads.append((v, info, g))
        t = sm.Tex(at.img)
        for v, info, g in quads:
            ax, ay = info['alloc']
            founds = []
            for vv in v:
                d, step = sm.vs_find(t, vv['tc'], vv['ref'])
                founds.append(None if d is None else d['org'])
            unamb = len(set(founds)) == 1 and founds[0] is not None
            ph = (ax % 128, ay % 8)
            px0, py0 = g.probe
            for yy in range(ay + py0, ay + py0 + g.h):
                if (yy - ay) % 8 == 0:
                    continue
                for xx in range(ax + px0, ax + px0 + g.w):
                    col, a = t.col(xx, yy)
                    if a < 0.002:
                        continue                  # efface par un mur : invisible aussi a l'origine
                    vis += 1
                    code, info2 = sm.fs_decode(t, (xx, yy), ph)
                    if code != 'hd' and not (unamb and info2 == 'aucun bloc lisible'):
                        lost += 1
        n += 1
        per.append((area, kind, anchor, mir, vis, lost))
        out['positions'] += 1; out['visible'] += vis; out['perdus'] += lost
        if vis and lost / vis > 0.01:
            out['positions_avec_perte>1%'] += 1
print(mode, dict(out))
worst = sorted(per, key=lambda r: -(r[5] / max(r[4], 1)))[:5]
for r in worst:
    print('  ', r[0], r[1], r[2], 'miroir' if r[3] else '', 'visibles', r[4], 'perdus', r[5])
