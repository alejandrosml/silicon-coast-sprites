# ana_v2walls.py - murs "effacants" reels (WED de BG2) sur des cadres v2 : modele Python du shader de sommets
# (2 passes) -> combien de sommets trouvent le cadre, et dans quels cas aucun (image brute = dechets).
import sys, os, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wed import Wed, search_map
from wall_stats import U, WALKABLE
from engine_sim import fx_layout, raster_poly
import schd
import test_allscene as T

rng = np.random.default_rng(3)
HD = os.path.join(T.SP, 'all', 'scene_hd')
PAD = 1100


def model_vertex(A, tcx, tcy, eLx, eRx, eLT, eRB):
    """A : alpha (bool) de l'atlas simule ; renvoie (passe, hypothese) ou None"""
    Hh, Ww = A.shape
    for pas in (0, 1):
        for hyp in range(4):
            hx, hy = hyp % 2, hyp // 2
            xs = tcx + eLx if hx == 0 else tcx - 1 - eRx
            d = 1 if hx == 0 else -1
            y0 = tcy + eLT if hy == 0 else tcy - 1 - eRB
            sgn = 1 if hy == 0 else -1
            for j in range(136):
                dj = j if j < 8 else 8 + (j - 8) * 8
                yy = y0 + sgn * dj
                yc = min(max(yy, 0), Hh - 1)
                r = schd.read_row(A[yc], xs, d)
                if r is None:
                    continue
                rexp = dj if hy == 0 else r['H'] - 1 - dj
                if r['r'] != rexp:
                    break
                ox = xs if hx == 0 else xs - r['W'] + 1
                if pas == 0:
                    ok = (schd.read_row(A[yc], ox + r['W'] - 1, -1) is not None) if hx == 0 else (schd.read_row(A[yc], ox, 1) is not None)
                else:
                    ok = False
                    for q in (1, 2, 3):
                        e2 = 8 * (dj // 8 + q)
                        if e2 > r['H'] - 1:
                            break
                        y2 = min(max(y0 + sgn * e2, 0), Hh - 1)
                        r2 = schd.read_row(A[y2], xs, d)
                        if r2 and r2['r'] == (e2 if hy == 0 else r['H'] - 1 - e2) and all(r2[k] == r[k] for k in ('layout', 'k', 'w', 'h', 'flags')):
                            ok = True
                            break
                if ok:
                    return pas, hyp
    return None


def main():
    cases = [c for c in T.CAST if c[1] == 'clip']
    stats = dict(positions=0, with_walls=0, all4=0, partial=0, none_visible=0, none_hidden=0, probe_hidden=0)
    examples = []
    for area in ('AR0602', 'AR0700', 'AR0300'):
        wd = Wed(open(U + area + '.WED', 'rb').read())
        sm = search_map(open(U + area + 'SR.BMP', 'rb').read())
        ys, xs = np.nonzero(np.isin(sm, list(WALKABLE)))
        n_done = 0
        for i in rng.permutation(len(xs)):
            if n_done >= 400:
                break
            fam, path, names, c, f = cases[int(rng.integers(0, len(cases)))]
            ls = T.layers(HD, names, c, f)
            if not ls:
                continue
            anchor = (int(xs[i] * 16 + 8), int(ys[i] * 12 + 6))
            mir = bool(rng.integers(0, 2))
            fxw, fxh, ptref, offs = fx_layout(ls, 2)
            left = anchor[0] - (fxw - ptref[0]) if mir else anchor[0] - ptref[0]
            top = anchor[1] - ptref[1]
            rect = (left, top, left + fxw, top + fxh)
            polys = wd.applied(rect, anchor)
            stats['positions'] += 1
            if not polys:
                continue
            stats['with_walls'] += 1
            n_done += 1
            fx = np.zeros((fxh, fxw), bool)
            for cr, (ox, oy) in zip(ls, offs):
                h, w = cr.pix.shape
                fx[oy:oy + h, ox:ox + w] |= cr.pix != cr.tidx
            body = ls[0]
            for pi in polys:
                poly = wd.polys[pi]['pts']
                m = raster_poly(poly, left, top, fxw, fxh) if not mir else raster_poly(poly, rect[2] - fxw + 1, top, fxw, fxh)[:, ::-1]
                fx[m] = False
            # sonde (bloc du corps) : visible ?
            r0 = schd.read_row((body.pix[0] != body.tidx).astype(np.uint8), 0, 1)
            if r0 is None:
                continue
            po = (offs[0][0] + r0['probe'][0], offs[0][1] + r0['probe'][1])
            probe_vis = fx[po[1]:po[1] + r0['h'], po[0]:po[0] + r0['w']].mean()
            A = np.zeros((fxh + 2 * PAD, fxw + 2 * PAD), np.uint8)
            A[PAD:PAD + fxh, PAD:PAD + fxw] = fx
            tcs = [(1, 1), (1, fxh - 1), (fxw - 1, 1), (fxw - 1, fxh - 1)]
            found = 0
            for (u, v) in tcs:
                uu = fxw - u if mir else u
                if model_vertex(A, PAD + uu, PAD + v, 0, 0, 0, 0):
                    found += 1
            if found == 4:
                stats['all4'] += 1
            elif found > 0:
                stats['partial'] += 1
            else:
                if fx.any():
                    stats['none_visible'] += 1
                    if len(examples) < 10:
                        examples.append((area, anchor, fam[:20], mir, round(float(probe_vis), 3), int(fx.sum())))
                else:
                    stats['none_hidden'] += 1
            if probe_vis < 0.999:
                stats['probe_hidden'] += 1
    print(stats)
    for e in examples:
        print('  aucun sommet, cadre visible :', e)


if __name__ == '__main__':
    main()
