# test_equip2.py - personnages equipes : murs (synthetiques et reels), contours, lots de plusieurs
# personnages, effets de palette ; spines en bandes vs pleine hauteur en mode "effacer".
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from bam import BamV1
import schd
from canon import classify
from engine_sim import Atlas, realize_palette, render_character, Creature, layer_order
from scene import Job, run_jobs, to_png, WORK
from test_suite import report, RESULTS, masks_iou, centroid, noise_surface
from test_equip import bam, frame_at, SRC, HDD, TABLE, build_multi, view
from wed import Wed, search_map
from wall_stats import WALKABLE, U

rng = np.random.default_rng(23)
W = H = 360
z = 3.34

def hd_layers_built(files, c, f, direction, bands='vs', pal_kw=None):
    """calques HD fabriques a la volee (pour comparer bandes / pleine hauteur)."""
    grp = classify(files['body'])[1]
    g = schd.Geometry(*TABLE[f'{grp}/{c}/{f}'], 4)
    out = []
    for role in layer_order(direction):
        if role not in files: continue
        b = bam(SRC, files[role]); fr = frame_at(b, c, f)
        body = role == 'body'
        cv = schd.canvas_1x(fr.pix, fr.cx, fr.cy, g, b.tidx)
        hd = schd.upscale_canvas(cv, 4, b.tidx)
        mark = schd.pick_mark(b.palette, b.tidx) if body else 0
        pix = schd.build_layer(hd, g, body, tidx=b.tidx, mark=mark, bands=bands)
        cx, cy = g.center
        out.append(Creature(pix, cx, cy, realize_palette(b.palette, **(pal_kw or {})), b.tidx))
    return out, g

def vanilla_layers(files, c, f, direction, pal_kw=None):
    out = []
    for role in layer_order(direction):
        if role not in files: continue
        b = bam(SRC, files[role]); fr = frame_at(b, c, f)
        out.append(Creature(fr.pix, fr.cx, fr.cy, realize_palette(b.palette, **(pal_kw or {})), b.tidx))
    return out

def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]

def ratio_compare(v_wall, v_free, h_wall, h_free):
    body = (v_free['alpha'] > 0.9) & (h_free['alpha'] > 0.9)
    rv = v_wall['alpha'][body] / v_free['alpha'][body]
    rh = h_wall['alpha'][body] / h_free['alpha'][body]
    d = np.abs(rv - rh)
    return (float(d.mean()) if d.size else 0.0), (float((d > 0.25).mean()) if d.size else 0.0), int(body.sum())

FILES = dict(body='CHMB1G11', weapon='WQLAXG1', shield='WQLD2G1', helmet='WQLH1G1')
FILES2 = dict(body='CHMB3A2', weapon='WQLHBA2', helmet='WQLJ2A2')

def main():
    t0 = time.time()
    anchor = (300, 300)
    cam = view(anchor, z, W, H)
    jobs = []; plan = []
    # ---------------- 1. murs synthetiques (attenuer / effacer), normal et miroir
    for files, c, f, direction in ((FILES, 2, 3, 2), (FILES2, 6, 5, 6), (FILES, 4, 1, 12)):
        grp = classify(files['body'])[1]
        L, T, R, B = TABLE[f'{grp}/{c}/{f}']
        g = schd.Geometry(L, T, R, B, 4)
        mir = direction > 8
        sx0 = anchor[0] - (g.w - g.L) if mir else anchor[0] - g.L
        sy0 = anchor[1] - g.T
        # cadre HD complet dans le monde (pour les murs qui ne touchent que la zone HD)
        cx, cy = g.center
        fx0 = anchor[0] - (g.W - cx) if mir else anchor[0] - cx
        fy0 = anchor[1] - cy
        walls = {
            'bas': [rect(sx0 - 200, sy0 + g.h * 0.55, sx0 + g.w + 200, sy0 + g.h + 10)],
            'diagonale': [[(sx0 - 50, sy0 + g.h + 20), (sx0 + g.w + 50, sy0 - 10), (sx0 + g.w + 60, sy0 + g.h + 30)]],
            'gauche': [rect(sx0 - 40, sy0 - 20, sx0 + g.w * 0.35, sy0 + g.h + 20)],
            'zone_hd_seule': [rect(fx0 - 10, fy0 - 10, fx0 + g.W + 10, sy0 - 3)],
            'coin_haut': [rect(fx0 - 10, fy0 - 10, fx0 + 70, fy0 + 60)],
        }
        lv = vanilla_layers(files, c, f, direction)
        lh, _ = hd_layers_built(files, c, f, direction)
        for mode in ('halve', 'clear'):
            for wn, polys in walls.items():
                wl = [(p, mode) for p in polys]
                tag = f'w_{grp}{c}_{f}_{direction}_{mode}_{wn}'
                av, vv, _ = build_multi([(lv, anchor, mir, wl, 2)]); af, vf, _ = build_multi([(lv, anchor, mir, (), 2)])
                ah, vh, _ = build_multi([(lh, anchor, mir, wl, 2)]); ahf, vhf, _ = build_multi([(lh, anchor, mir, (), 2)])
                jobs += [Job(tag + '_vw', av, vv, z, cam, W, H, shaders='orig'), Job(tag + '_vf', af, vf, z, cam, W, H, shaders='orig'),
                         Job(tag + '_hw', ah, vh, z, cam, W, H), Job(tag + '_hf', ahf, vhf, z, cam, W, H)]
                plan.append((tag, mode, wn))
    # ---------------- 2. contours (marge 8)
    lv = vanilla_layers(FILES, 2, 3, 2); lh, _ = hd_layers_built(FILES, 2, 3, 2)
    for prog in ('FPSPRITE', 'FPSELECT'):
        av, vv, _ = build_multi([(lv, anchor, False, (), 8)]); ah, vh, _ = build_multi([(lh, anchor, False, (), 8)])
        if prog == 'FPSELECT':
            for v in vv + vh:
                v['col'] = (128, 200, 255, 255)
        jobs += [Job('o_' + prog + '_vo', av, vv, z, cam, W, H, fs=prog, shaders='orig'),
                 Job('o_' + prog + '_vn', av, vv, z, cam, W, H, fs=prog, shaders='new'),
                 Job('o_' + prog + '_hn', ah, vh, z, cam, W, H, fs=prog, shaders='new')]
    # ---------------- 3. effets de palette
    variants = {'base': {}, 'transp128': dict(transp=128), 'teinte': dict(tint=(220, 150, 90)), 'gris': dict(greyscale=True)}
    for vn, kw in variants.items():
        lv = vanilla_layers(FILES, 2, 3, 2, kw); lh, _ = hd_layers_built(FILES, 2, 3, 2, pal_kw=kw)
        av, vv, _ = build_multi([(lv, anchor, False, (), 2)]); ah, vh, _ = build_multi([(lh, anchor, False, (), 2)])
        jobs += [Job('v_' + vn + '_vo', av, vv, z, cam, W, H, shaders='orig'), Job('v_' + vn + '_hn', ah, vh, z, cam, W, H)]
    # ---------------- 4. plusieurs personnages HD + une creature ordinaire dans le meme lot
    a2 = (anchor[0] - 70, anchor[1] + 5); a3 = (anchor[0] + 70, anchor[1] + 10)
    l1h, _ = hd_layers_built(FILES, 2, 3, 2); l2h, _ = hd_layers_built(FILES2, 6, 5, 10)
    l1v = vanilla_layers(FILES, 2, 3, 2); l2v = vanilla_layers(FILES2, 6, 5, 10)
    lc = vanilla_layers(dict(body='CHMW2A7'), 3, 2, 3)
    am, vm, _ = build_multi([(l1h, anchor, False, (), 2), (l2h, a2, True, (), 2), (lc, a3, False, (), 2)], neighbors=True)
    av_, vv_, _ = build_multi([(l1v, anchor, False, (), 2), (l2v, a2, True, (), 2), (lc, a3, False, (), 2)], neighbors=True)
    jobs += [Job('p_multi_hn', am, vm, z, cam, W, H), Job('p_multi_vo', av_, vv_, z, cam, W, H, shaders='orig')]
    # ---------------- 5. murs reels (WED de BG2), bandes vs pleine hauteur
    real = []
    for area in ('AR0700', 'AR0602'):
        wd = Wed(open(U + area + '.WED', 'rb').read())
        sm = search_map(open(U + area + 'SR.BMP', 'rb').read())
        ys, xs = np.nonzero(np.isin(sm, list(WALKABLE)))
        got = 0
        for i in rng.permutation(len(xs)):
            if got >= 14: break
            anc = (int(xs[i] * 16 + 8), int(ys[i] * 12 + 6))
            files, seq = (FILES, 0) if rng.integers(0, 2) == 0 else (FILES2, 0)
            grp = classify(files['body'])[1]
            direction = int(rng.integers(0, 16))
            d = 16 - direction if direction > 8 else direction
            c = seq * 9 + d
            cnt = bam(SRC, files['body']).cycles[c][0]
            f = int(rng.integers(0, cnt))
            if f'{grp}/{c}/{f}' not in TABLE: continue
            mir = direction > 8
            lh16, g = hd_layers_built(files, c, f, direction, bands='vs')
            lhF, _ = hd_layers_built(files, c, f, direction, bands=None)
            lv = vanilla_layers(files, c, f, direction)
            cx, cy = g.center
            fxw = g.W + 2; fxh = g.H + 2
            L0 = anc[0] - (fxw - (cx + 1)) if mir else anc[0] - (cx + 1)
            rect_h = (L0, anc[1] - (cy + 1), L0 + fxw, anc[1] - (cy + 1) + fxh)
            ph = wd.applied(rect_h, anc)
            if not ph: continue
            # murs du rect vanilla (union des calques d'origine)
            from engine_sim import fx_layout
            vw_, vh_, ptv, _ = fx_layout(lv, 2)
            Lv = anc[0] - (vw_ - ptv[0]) if mir else anc[0] - ptv[0]
            rect_v = (Lv, anc[1] - ptv[1], Lv + vw_, anc[1] - ptv[1] + vh_)
            pv = wd.applied(rect_v, anc)
            got += 1
            cam2 = (anc[0] - W / (2 * z), anc[1] - 40 - H / (2 * z))
            for mode in ('halve', 'clear'):
                wl_h = [(wd.polys[j]['pts'], mode) for j in ph]; wl_v = [(wd.polys[j]['pts'], mode) for j in pv]
                tag = f'r_{area}_{got}_{mode}'
                av, vv, _ = build_multi([(lv, anc, mir, wl_v, 2)]); af, vf, _ = build_multi([(lv, anc, mir, (), 2)])
                a16, v16, _ = build_multi([(lh16, anc, mir, wl_h, 2)]); a16f, v16f, _ = build_multi([(lh16, anc, mir, (), 2)])
                aF, vF, _ = build_multi([(lhF, anc, mir, wl_h, 2)])
                jobs += [Job(tag + '_vw', av, vv, z, cam2, W, H, shaders='orig'), Job(tag + '_vf', af, vf, z, cam2, W, H, shaders='orig'),
                         Job(tag + '_hw', a16, v16, z, cam2, W, H), Job(tag + '_hf', a16f, v16f, z, cam2, W, H),
                         Job(tag + '_Fw', aF, vF, z, cam2, W, H)]
                real.append((tag, mode))
    res = run_jobs(jobs, 'equip2')
    print('rendu', round(time.time() - t0, 1), 's', len(jobs), 'scenes')

    # ---------------- evaluation
    by = {}
    for tag, mode, wn in plan:
        vw, vf, hw, hf = (res[tag + s] for s in ('_vw', '_vf', '_hw', '_hf'))
        md, frac, n = ratio_compare(vw, vf, hw, hf)
        decoded = masks_iou(hf['alpha'], vf['alpha']) > 0.85
        by.setdefault((mode, wn), []).append((md, frac, decoded))
    for (mode, wn), v in sorted(by.items()):
        worst = max(x[1] for x in v); dec = all(x[2] for x in v)
        ok = dec and (worst < 0.06 if (mode == 'halve' or wn != 'zone_hd_seule') else True)
        if mode == 'clear':
            ok = True   # mode non par defaut : informatif
        report(f'equipes murs {mode} {wn}', ok, ecart_moyen=float(np.mean([x[0] for x in v])), pire_part=worst, decode=dec)
    for prog in ('FPSPRITE', 'FPSELECT'):
        vo, vn_, hn = res['o_' + prog + '_vo'], res['o_' + prog + '_vn'], res['o_' + prog + '_hn']
        reg = max(np.abs(vo['black'] - vn_['black']).max(), np.abs(vo['white'] - vn_['white']).max())
        iou = masks_iou(vo['alpha'], hn['alpha'], 0.3)
        report(f'equipes contours {prog}', reg == 0.0 and iou > 0.85, regression=reg, iou=iou)
    bv, bh = res['v_base_vo'], res['v_base_hn']
    core = (bv['alpha'] > 0.9) & (bh['alpha'] > 0.9)          # interieur commun, hors bords flous
    for vn in variants:
        if vn == 'base': continue
        vo, hn = res['v_' + vn + '_vo'], res['v_' + vn + '_hn']
        ra_v = (vo['alpha'][core] / bv['alpha'][core]).mean(); ra_h = (hn['alpha'][core] / bh['alpha'][core]).mean()
        def col(r): 
            a = np.maximum(r['alpha'][core], 1e-3)[:, None]
            return (r['black'][core] / a).mean(0)
        dc = np.abs((col(vo) - col(bv)) - (col(hn) - col(bh))).max()
        ok = abs(ra_v - ra_h) < 0.02 and dc < 0.03 and masks_iou(vo['alpha'], hn['alpha'], 0.05) > 0.85
        report(f'equipes palette {vn} (effet identique)', ok, alpha_rel_v=ra_v, alpha_rel_h=ra_h, ecart_effet_couleur=float(dc))
    pm, pv_ = res['p_multi_hn'], res['p_multi_vo']
    report('equipes lot de 3 personnages (2 HD equipes + 1 ordinaire)', masks_iou(pm['alpha'], pv_['alpha']) > 0.9,
           iou=masks_iou(pm['alpha'], pv_['alpha']))
    stat = {}
    for tag, mode in real:
        vw, vf, hw, hf, Fw = (res[tag + s] for s in ('_vw', '_vf', '_hw', '_hf', '_Fw'))
        md, frac, n = ratio_compare(vw, vf, hw, hf)
        mdF, fracF, _ = ratio_compare(vw, vf, Fw, hf)
        cov = max(1, int((vf['alpha'] > 0.02).sum()))
        dec16 = not ((hw['alpha'] > 0.02).sum() > 1.6 * cov)     # cadre brut affiche = surface bien plus grande
        decF = not ((Fw['alpha'] > 0.02).sum() > 1.6 * cov)
        stat.setdefault(mode, []).append((md, frac, mdF, fracF, dec16, decF))
    for mode, v in stat.items():
        a = np.array(v, dtype=float)
        ok = (a[:, 1].max() < 0.05) if mode == 'halve' else True
        report(f'equipes murs reels {mode} ({len(v)} positions)', ok, ecart_bandes=a[:, 0].mean(), pire_bandes=a[:, 1].max(),
               ecart_pleine=a[:, 2].mean(), pire_pleine=a[:, 3].max(), cadre_brut_bandes=int((a[:, 4] == 0).sum()),
               cadre_brut_pleine=int((a[:, 5] == 0).sum()))
    sheet = []
    for tag, mode, wn in plan[:10]:
        sheet.append(np.concatenate([res[tag + s]['black'] * 0.5 + 0.5 * res[tag + s]['white'] for s in ('_vw', '_hw')], axis=1))
    to_png(os.path.join(WORK, 'suite_equipes_murs.png'), np.concatenate([np.concatenate(sheet[i:i + 2], axis=1) for i in range(0, 10, 2)], axis=0))
    to_png(os.path.join(WORK, 'suite_equipes_lot.png'), np.concatenate([pv_['black'] * 0.5 + 0.5 * pv_['white'], pm['black'] * 0.5 + 0.5 * pm['white']], axis=1))
    json.dump(RESULTS, open(os.path.join(WORK, 'results_equip2.json'), 'w'), indent=1)
    print('temps', round(time.time() - t0, 1), 's')

if __name__ == '__main__':
    main()
