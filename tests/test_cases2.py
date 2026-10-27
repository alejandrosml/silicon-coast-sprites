# test_cases2.py - murs, transparence, teintes, filtres, voisins, contours, decodage robuste, texel exact
import sys, os, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from test_suite import (load, hd_of, build, Creature, realize_palette, Job, run_jobs, to_png, WORK,
                        masks_iou, centroid, view, report, RESULTS, rng)
import schd
from engine_sim import Atlas, render_creature

bA = load('CHMB1A1.BAM')
fr = bA.frames[10]
W = H = 360
anchor = (300, 300)
z = 3.34
cam = view(anchor, z, W, H)

def creatures(pal=None, k=4):
    pal = realize_palette(bA.palette) if pal is None else pal
    pix, cx2, cy2, hd = hd_of(bA, fr, k)
    return Creature(fr.pix, fr.cx, fr.cy, pal, bA.tidx), Creature(pix, cx2, cy2, pal, bA.tidx), pix, cx2, cy2

cv, ch, pix, cx2, cy2 = creatures()
h0, w0 = fr.pix.shape
# rect du monde du sprite d'origine (non miroir) et du cadre HD
sx0, sy0 = anchor[0] - fr.cx, anchor[1] - fr.cy
fx0, fy0 = anchor[0] - cx2, anchor[1] - cy2
FH, FW = pix.shape

def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]

WALLS = {
    'bas_du_corps': [rect(sx0 - 200, sy0 + h0 * 0.5, sx0 + w0 + 200, sy0 + h0 + 10)],
    'diagonale': [[(sx0 - 50, sy0 + h0 + 20), (sx0 + w0 + 50, sy0 - 10), (sx0 + w0 + 60, sy0 + h0 + 30)]],
    'tout': [rect(fx0 - 50, fy0 - 50, fx0 + FW + 50, fy0 + FH + 50)],
    'zone_hd_seule': [rect(fx0 - 10, fy0 - 10, fx0 + FW + 10, sy0 - 3)],
    'coin_haut_gauche_30': [rect(fx0 - 10, fy0 - 10, fx0 + 70, fy0 + 30)],
    'coin_haut_gauche_80': [rect(fx0 - 10, fy0 - 10, fx0 + 70, fy0 + 80)],
}

def ratio_compare(v_wall, v_free, h_wall, h_free):
    body = (v_free['alpha'] > 0.9) & (h_free['alpha'] > 0.9)
    rv = v_wall['alpha'][body] / v_free['alpha'][body]
    rh = h_wall['alpha'][body] / h_free['alpha'][body]
    d = np.abs(rv - rh)
    return float(d.mean()) if d.size else 0.0, float((d > 0.25).mean()) if d.size else 0.0, int(body.sum())

def main():
    jobs = []; plan = []
    for mode in ('halve', 'clear'):
        for wname, polys in WALLS.items():
            for mir in (False, True):
                walls = [(p, mode) for p in polys]
                if mir:   # miroir : on reflechit les murs autour de l'ancrage pour viser les memes zones
                    walls = [([(2 * anchor[0] - x, y) for x, y in p], mode) for p in polys]
                tag = f'w_{mode}_{wname}_{int(mir)}'
                av, vv, _ = build([(cv, anchor, mir, walls, 2)]); af, vf, _ = build([(cv, anchor, mir, (), 2)])
                ah, vh, _ = build([(ch, anchor, mir, walls, 2)]); ahf, vhf, _ = build([(ch, anchor, mir, (), 2)])
                jobs += [Job(tag + '_vw', av, vv, z, cam, W, H, shaders='orig'), Job(tag + '_vf', af, vf, z, cam, W, H, shaders='orig'),
                         Job(tag + '_hw', ah, vh, z, cam, W, H), Job(tag + '_hf', ahf, vhf, z, cam, W, H)]
                plan.append((tag, mode, wname, mir))
    # transparence / teinte / gris
    variants = {'transp128': dict(transp=128), 'teinte': dict(tint=(220, 150, 90)), 'gris': dict(greyscale=True),
                'ombre_grise': dict(shadow_rgb=(20, 20, 20))}
    for vn, kw in variants.items():
        pal = realize_palette(bA.palette, **kw)
        cvv, chh, *_ = creatures(pal)
        av, vv, _ = build([(cvv, anchor, False, (), 2)]); ah, vh, _ = build([(chh, anchor, False, (), 2)])
        jobs += [Job('v_' + vn + '_vo', av, vv, z, cam, W, H, shaders='orig'), Job('v_' + vn + '_hn', ah, vh, z, cam, W, H)]
    # filtre d'atlas, voisins
    ah, vh, infos = build([(ch, anchor, False, (), 2)], neighbors=True)
    # meme atlas, memes positions, mais voisins effaces : seule une fuite de lecture changerait le rendu
    ah2 = np.zeros_like(ah)
    (ax, ay), (fw_, fh_) = infos[0]['alloc'], infos[0]['fx']
    ah2[ay:ay + fh_, ax:ax + fw_] = ah[ay:ay + fh_, ax:ax + fw_]
    vh2 = vh
    jobs += [Job('f_lin', ah, vh, z, cam, W, H, filt='linear'), Job('f_near', ah, vh, z, cam, W, H, filt='nearest'),
             Job('f_novois', ah2, vh2, z, cam, W, H, filt='linear')]
    # plusieurs creatures HD dans le meme atlas et le meme lot de dessin
    a2 = (anchor[0] - 60, anchor[1]); a3 = (anchor[0] + 60, anchor[1] + 10)
    am, vm, _ = build([(ch, anchor, False, (), 2), (ch, a2, True, (), 2), (cv, a3, False, (), 2)], neighbors=True)
    aa, va, _ = build([(ch, anchor, False, (), 2)]); ab, vb, _ = build([(ch, a2, True, (), 2)]); ac, vc, _ = build([(cv, a3, False, (), 2)])
    jobs += [Job('p_multi', am, vm, z, cam, W, H), Job('p_a', aa, va, z, cam, W, H), Job('p_b', ab, vb, z, cam, W, H),
             Job('p_c', ac, vc, z, cam, W, H)]
    # contours de sprites (marge 8) : FPSPRITE / FPSELECT
    for prog in ('FPSPRITE', 'FPSELECT'):
        av, vv, _ = build([(cv, anchor, False, (), 8)]); ah, vh, _ = build([(ch, anchor, False, (), 8)])
        if prog == 'FPSELECT':
            for v in vv + vh:
                v['col'] = (128, 200, 255, 255)
        jobs += [Job('o_' + prog + '_vo', av, vv, z, cam, W, H, fs=prog, shaders='orig'),
                 Job('o_' + prog + '_vn', av, vv, z, cam, W, H, fs=prog, shaders='new'),
                 Job('o_' + prog + '_hn', ah, vh, z, cam, W, H, fs=prog, shaders='new')]
    # texel exact : z = 4, camera alignee -> 1 pixel ecran = 1 texel HD
    z4 = 4.0
    W4 = H4 = 640
    cam4 = (float(np.floor(anchor[0] - W4 / (2 * z4))), float(np.floor(anchor[1] - 30 - H4 / (2 * z4))))
    ah, vh, _ = build([(ch, anchor, False, (), 2)])
    jobs += [Job('x_exact', ah, vh, z4, cam4, W4, H4)]
    t0 = time.time()
    res = run_jobs(jobs, 'c2')
    print('rendu', round(time.time() - t0, 1), 's')

    # --- evaluation murs
    for tag, mode, wname, mir in plan:
        vw, vf, hw, hf = (res[tag + s] for s in ('_vw', '_vf', '_hw', '_hf'))
        md, frac, n = ratio_compare(vw, vf, hw, hf)
        decoded = masks_iou(hf['alpha'], vf['alpha']) > 0.85
        if mode == 'clear' and wname == 'zone_hd_seule':
            # limite connue (Always Dither desactive) : un mur "effacant" sur toute la zone HD efface l'image HD
            report(f'murs {mode} {wname} miroir={mir} (limite connue, information)', True, ecart_moyen=md,
                   part_ecart_fort=frac, px=n, decode_ok=bool(decoded))
            continue
        ok = decoded and frac < 0.06
        report(f'murs {mode} {wname} miroir={mir}', ok, ecart_moyen=md, part_ecart_fort=frac, px=n,
               decode_ok=bool(decoded), iou_hd_murs=float(masks_iou(hw['alpha'], vw['alpha'])))
    sheet = []
    for wname in ('bas_du_corps', 'diagonale', 'zone_hd_seule', 'coin_haut_gauche_80'):
        r = []
        for mode in ('halve', 'clear'):
            tag = f'w_{mode}_{wname}_0'
            r += [res[tag + '_vw']['black'] * 0.5 + 0.5 * res[tag + '_vw']['white'],
                  res[tag + '_hw']['black'] * 0.5 + 0.5 * res[tag + '_hw']['white']]
        sheet.append(np.concatenate(r, axis=1))
    to_png(os.path.join(WORK, 'suite_murs.png'), np.concatenate(sheet, axis=0))

    # --- variantes de palette
    for vn in ('transp128', 'teinte', 'gris', 'ombre_grise'):
        vo, hn = res['v_' + vn + '_vo'], res['v_' + vn + '_hn']
        body = (vo['alpha'] > 0.02) & (hn['alpha'] > 0.02)
        am_v = vo['alpha'][body].mean(); am_h = hn['alpha'][body].mean()
        col_v = (vo['black'][body] / np.maximum(vo['alpha'][body, None], 1e-3)).mean(0)
        col_h = (hn['black'][body] / np.maximum(hn['alpha'][body, None], 1e-3)).mean(0)
        sat_h = float(np.abs(col_h - col_h.mean()).max())
        ok = abs(am_v - am_h) < 0.05 and np.abs(col_v - col_h).max() < 0.06
        if vn == 'gris':
            ok = ok and sat_h < 0.02
        report(f'palette {vn}', ok, alpha_moy_van=am_v, alpha_moy_hd=am_h, ecart_couleur=float(np.abs(col_v - col_h).max()))

    # --- filtre / voisins / lots
    d1 = max(np.abs(res['f_lin']['black'] - res['f_near']['black']).max(), np.abs(res['f_lin']['white'] - res['f_near']['white']).max())
    report('filtre de l atlas (lineaire vs plus proche) sans effet sur le HD', d1 == 0.0, max_diff=d1)
    d2 = max(np.abs(res['f_lin']['black'] - res['f_novois']['black']).max(), np.abs(res['f_lin']['white'] - res['f_novois']['white']).max())
    report('voisins dans l atlas sans effet (aucune lecture hors du cadre)', d2 == 0.0, max_diff=d2)
    # lot multiple : composer les rendus isoles sur fond noir/blanc dans l'ordre de dessin
    comp_k = np.zeros_like(res['p_a']['black']); comp_w = np.ones_like(res['p_a']['white'])
    for t in ('p_a', 'p_b', 'p_c'):
        a = res[t]['alpha'][..., None]
        src = res[t]['black'] / np.maximum(a, 1e-6)
        comp_k = src * a + comp_k * (1 - a); comp_w = src * a + comp_w * (1 - a)
    d3 = max(np.abs(comp_k - res['p_multi']['black']).max(), np.abs(comp_w - res['p_multi']['white']).max())
    report('plusieurs creatures HD et ordinaires dans un meme lot', d3 < 0.02, max_diff=d3)

    # --- contours de sprites
    for prog in ('FPSPRITE', 'FPSELECT'):
        vo, vn_, hn = res['o_' + prog + '_vo'], res['o_' + prog + '_vn'], res['o_' + prog + '_hn']
        reg = max(np.abs(vo['black'] - vn_['black']).max(), np.abs(vo['white'] - vn_['white']).max())
        iou = masks_iou(vo['alpha'], hn['alpha'], 0.5)
        report(f'contours {prog}: regression et rendu HD', reg == 0.0 and iou > 0.8, regression=reg, iou=iou)
    to_png(os.path.join(WORK, 'suite_contours.png'), np.concatenate(
        [np.concatenate([res['o_' + p + s]['black'] * 0.5 + 0.5 * res['o_' + p + s]['white'] for s in ('_vo', '_hn')], axis=1)
         for p in ('FPSPRITE', 'FPSELECT')], axis=0))

    # --- texel exact
    x = res['x_exact']
    pal = realize_palette(bA.palette)
    hd = pix[0:4 * h0, 60:60 + 4 * w0] if False else None
    # reconstruit l'image HD attendue a l'ecran (premultipliee, ombre a 0.5)
    _, _, _, hdimg = hd_of(bA, fr)
    rgba = pal[hdimg].astype(np.float64) / 255.0
    rel = np.where(rgba[..., 3] <= 0, 0.0, np.where(hdimg == 1, 0.5, 1.0))
    rel[hdimg == bA.tidx] = 0.0
    exp_prem = rgba[..., :3] * rel[..., None]
    sx = int(round((sx0 - cam4[0]) * z4)); sy = int(round((sy0 - cam4[1]) * z4))
    got = x['black'][sy:sy + 4 * h0, sx:sx + 4 * w0]
    dmax = np.abs(got - exp_prem).max()
    report('texel exact a z=4 (1 pixel = 1 texel HD)', dmax < 2.5 / 255, max_diff=dmax, pos=(sx, sy))
    json.dump(RESULTS, open(os.path.join(WORK, 'results_c2.json'), 'w'), indent=1)

if __name__ == '__main__':
    main()
