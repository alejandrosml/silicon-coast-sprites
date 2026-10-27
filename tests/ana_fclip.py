# ana_fclip.py - murs reels (WED de BG2) sur des creatures FXBltFromClipped converties en disposition F :
# sommets qui trouvent le cadre (recherche exacte par coin), pixels du sprite visibles mais perdus (zone HD
# effacee), risque de dechets (aucun sommet ne trouve le cadre alors que des texels restent).
import sys, os, collections, numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wed import Wed, search_map
from wall_stats import U, WALKABLE
from engine_sim import fx_layout, raster_poly
import shader_model as sm
import schd
import test_allscene as T

mode = sys.argv[1] if len(sys.argv) > 1 else 'clear'
depth_m = int(sys.argv[2]) if len(sys.argv) > 2 else 64
HD = os.path.join(T.SP, 'all', 'scene_f')
rng = np.random.default_rng(3)
PAD = 1100


def main():
    cases = [c for c in T.CAST if c[1] == 'clip']
    st = collections.Counter(); ex = []
    reads = []
    for area in ('AR0602', 'AR0700', 'AR0300'):
        wd = Wed(open(U + area + '.WED', 'rb').read())
        smap = search_map(open(U + area + 'SR.BMP', 'rb').read())
        ys, xs = np.nonzero(np.isin(smap, list(WALKABLE)))
        n_done = 0
        for i in rng.permutation(len(xs)):
            if n_done >= 300:
                break
            fam, path, names, c, f = cases[int(rng.integers(0, len(cases)))]
            ls = T.layers(HD, names, c, f)
            if not ls:
                continue
            anchor = (int(xs[i] * 16 + 8), int(ys[i] * 12 + 6))
            mir = bool(rng.integers(0, 2))
            margin = 8 if rng.random() < 0.25 else 2
            fxw, fxh, ptref, offs = fx_layout(ls, margin)
            left = anchor[0] - (fxw - ptref[0]) if mir else anchor[0] - ptref[0]
            top = anchor[1] - ptref[1]
            rect = (left, top, left + fxw, top + fxh)
            polys = wd.applied(rect, anchor)
            st['positions'] += 1
            if not polys:
                continue
            st['avec_murs'] += 1
            n_done += 1
            fx = np.zeros((fxh, fxw), np.uint8)
            for cr, (ox, oy) in zip(ls, offs):
                h, w = cr.pix.shape
                sub = fx[oy:oy + h, ox:ox + w]
                sub[cr.pix != cr.tidx] = 255
            for pi in polys:
                poly = wd.polys[pi]['pts']
                mk = raster_poly(poly, left, top, fxw, fxh) if not mir else raster_poly(poly, rect[2] - fxw + 1, top, fxw, fxh)[:, ::-1]
                if mode == 'clear':
                    fx[mk] = 0
                else:
                    fx[mk] >>= 1
            img = np.zeros((fxh + 2 * PAD, fxw + 2 * PAD, 4), np.uint8)
            img[PAD:PAD + fxh, PAD:PAD + fxw, 3] = fx
            t = sm.Tex(img)
            # sommets (quad au rect interieur de la surface FX)
            dL, dT, dR, dB = (1, 1, 1, 1) if margin == 2 else (2, 2, 3, 3)
            tcs = [(dL, dT), (dL, fxh - dB), (fxw - dR, dT), (fxw - dR, fxh - dB)]
            eo = sm.clip_offsets(margin, mir)
            found = 0; d0 = None
            for (u, v) in tcs:
                uu = fxw - u if mir else u
                d, hyp, nr = sm.vs_clip_find(t, (PAD + uu, PAD + v), eo, depth_m)
                reads.append(nr)
                if d is not None:
                    found += 1; d0 = d
            # sprite visible (bloc-sonde du corps, hors lignes speciales) et zone HD correspondante
            body = ls[0]
            bd = schd.f_decode_at((body.pix != body.tidx).astype(np.uint8), 0, 0)
            if bd is None:
                continue
            bx, by = offs[0]
            px, py = bx + bd['probe'][0], by + bd['probe'][1]
            k, w, h = bd['k'], bd['w'], bd['h']
            pr = fx[py:py + h, px:px + w]
            spec = ((np.arange(py, py + h) - by) % 8 == 0)
            vis = (pr > 0) & ~spec[:, None]
            # texels HD de chaque pixel du sprite (couverture : au moins un texel HD non efface si l'original l'a)
            rows = np.array([schd.f_row(j) for j in range(k * h)])
            hdz = fx[by + rows][:, bx + bd['hd'][0]:bx + bd['hd'][0] + k * w]
            hdz_orig = np.zeros_like(hdz)
            for cr, (ox, oy) in zip(ls, offs):
                pass
            # pixels du sprite dont tous les texels HD sont effaces alors que la sonde est visible
            blk = hdz.reshape(h, k, w, k).max(axis=(1, 3)) > 0
            # l'original avait-il de la matiere HD ici ? (couche sans murs)
            fx0 = np.zeros((fxh, fxw), np.uint8)
            for cr, (ox, oy) in zip(ls, offs):
                hh, ww = cr.pix.shape
                fx0[oy:oy + hh, ox:ox + ww][cr.pix != cr.tidx] = 255
            hd0 = fx0[by + rows][:, bx + bd['hd'][0]:bx + bd['hd'][0] + k * w].reshape(h, k, w, k).max(axis=(1, 3)) > 0
            st['sprite_visible'] += int((vis & hd0).sum())
            st['trous_zone_hd'] += int((vis & hd0 & ~blk).sum())
            if found == 4:
                st['4_sommets'] += 1
            elif found > 0:
                st['partiel'] += 1
            else:
                if fx.any():
                    st['aucun_mais_visible'] += 1
                    if len(ex) < 8:
                        ex.append((area, anchor, fam[:18], mir, margin, int(vis.sum()), int((fx > 0).sum())))
                else:
                    st['aucun_tout_cache'] += 1
    print(mode, 'profondeur', depth_m, dict(st))
    print('lectures de candidats par sommet : moyenne %.0f, max %d' % (np.mean(reads), max(reads)))
    for e in ex:
        print('   aucun sommet :', e)


if __name__ == '__main__':
    main()
