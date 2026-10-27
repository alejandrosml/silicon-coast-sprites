# test_subshade.py - sous-teintes facon bg2hd (x2, Q3M : couleur = (P[I] (8 - F) + P[S] F + 4) >> 3) affichees
# par les shaders Silicon Coast, sur les deux chemins de rendu (FXBltFromClipped et FXBltFrom).
# Verifie : pixel exact a z = 2 (1 pixel = 1 texel HD) contre la formule de bg2hd appliquee a la palette telle
# que le moteur la realise (teinte comprise), silhouette, murs, et calques multiples.
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from bam import BamV1
import schd
import sc_convert as sc
from engine_sim import Atlas, realize_palette, Creature, render_character, render_fxfrom
from scene import Job, run_jobs, to_png, WORK
from test_suite import report, RESULTS, masks_iou, centroid

SP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(SP, 'all', 'src')
SUB = os.path.join(SP, 'all', 'scene_sub')
_c = {}


def bam(d, n):
    if (d, n) not in _c:
        _c[(d, n)] = BamV1.load(open(os.path.join(d, n + '.BAM'), 'rb').read())
    return _c[(d, n)]


def frame(b, c, f):
    return b.frames[b.lookup[b.cycles[c][1] + f]]


def expected(n, c, f, pal_kw=None, mirror=False):
    """image attendue a z = 2 : plans I/S/F du cadre converti -> formule bg2hd sur la palette realisee."""
    b = bam(SUB, n)
    fr = frame(b, c, f)
    t = b.tidx
    alpha = (fr.pix != t).astype(np.uint8)
    path = 'from' if n.startswith(('MWYVG1', 'MDR', 'MDEM')) and len(n) > 6 else 'clip'
    if path == 'from':
        d = schd.f_decode_at(alpha, 0, 0)
        k, w, h, fl = d['k'], d['w'], d['h'], d['flags']
        cols, nr = schd.planes_grid(fl)
        rows = np.array([schd.f_row(j) for j in range(nr * k * h)])
        grid = fr.pix[rows][:, d['hd'][0]:d['hd'][0] + cols * k * w]
        probe = d['probe']
    else:
        r = schd.read_row(alpha[0], 0, 1)
        k, w, h, fl = r['k'], r['w'], r['h'], r['flags']
        cols, nr = schd.planes_grid(fl)
        grid = fr.pix[r['hd'][1]:r['hd'][1] + nr * k * h, r['hd'][0]:r['hd'][0] + cols * k * w]
        probe = r['probe']
    P = [grid[(p // cols) * k * h:(p // cols + 1) * k * h, (p % cols) * k * w:(p % cols + 1) * k * w] for p in range(5)]
    I, S = P[0], P[1]
    F = sum(((P[2 + bb] == S) & (S != I)).astype(int) << bb for bb in range(3))
    pal = realize_palette(b.palette, **(pal_kw or {})).astype(np.int64)
    rgb = (pal[I][..., :3] * (8 - F[..., None]) + pal[S][..., :3] * F[..., None] + 4) >> 3
    # memes couleurs que P[I] et P[S] confondus -> P[I]
    same = (pal[I][..., :3] == pal[S][..., :3]).all(-1)
    rgb[same] = pal[I][same][:, :3]
    m = I != t
    rel = np.where(I == 1, 0.5, 1.0)
    acc = np.zeros(I.shape + (3,)); acc[m] = rgb[m] / 255.0 * rel[m][:, None]
    if mirror:
        acc = acc[:, ::-1]
    L, T = fr.cx - probe[0], fr.cy - probe[1]
    return acc, (w, h, L, T, k), path


def main():
    t0 = time.time()
    cases = [('CHMB1A1', 2, 5, False, None), ('CHMB1A1', 6, 3, True, None), ('MSKTA1', 2, 7, False, None),
             ('MOGRG1', 1, 3, True, None), ('MWYVG11', 2, 3, False, None), ('MDR11104', 1, 4, True, None),
             ('CHMB1A1', 2, 5, False, dict(tint=(255, 150, 90))), ('MSKTA1', 2, 7, False, dict(greyscale=True))]
    jobs = []; meta = []
    z = 2.0; W = H = 640
    for i, (n, c, f, mir, kw) in enumerate(cases):
        b = bam(SUB, n); bv = bam(SRC, n)
        # cadre reel (pas un cadre vide 1x1 conserve tel quel) : premier cadre non vide a partir de (c, f)
        order = [(c, f)] + [(cc, ff) for cc in range(len(bv.cycles)) for ff in range(bv.cycles[cc][0])]
        for cc, ff in order:
            if cc < len(bv.cycles) and ff < bv.cycles[cc][0] and frame(bv, cc, ff).pix.size > 64:
                c, f = cc, ff
                break
        fr = frame(b, c, f); fv = frame(bv, c, f)
        anchor = (300, 300)
        cr = Creature(fr.pix, fr.cx, fr.cy, realize_palette(b.palette, **(kw or {})), b.tidx)
        cv = Creature(fv.pix, fv.cx, fv.cy, realize_palette(bv.palette, **(kw or {})), bv.tidx)
        acc, geo, path = expected(n, c, f, kw, mir)
        # camera centree sur le sprite (les parties de dragon ont leur centre loin hors du cadre)
        w_, h_, L_, T_, k_ = geo
        bx0 = anchor[0] - ((w_ - L_) if mir else L_); by0 = anchor[1] - T_
        cam = (float(np.floor(bx0 + w_ / 2 - W / (2 * z))), float(np.floor(by0 + h_ / 2 - H / (2 * z))))
        rend = render_fxfrom if path == 'from' else (lambda at, x, a, m, w_, vp: render_character(at, [x], a, m, w_, 2))
        at = Atlas(); vh, _ = (render_fxfrom(at, cr, anchor, mir, (), None) if path == 'from' else render_character(at, [cr], anchor, mir, (), 2))
        ah = at.img.copy()
        at2 = Atlas(); vv, _ = (render_fxfrom(at2, cv, anchor, mir, (), None) if path == 'from' else render_character(at2, [cv], anchor, mir, (), 2))
        av = at2.img.copy()
        jobs += [Job(f's{i}_h', ah, vh, z, cam, W, H), Job(f's{i}_v', av, vv, z, cam, W, H, shaders='orig')]
        meta.append((f's{i}', n, acc, geo, anchor, cam, mir))
        # avec un mur attenuant sur la moitie basse
        ym = by0 + h_ // 2
        walls = [([(bx0 - 20, ym), (bx0 + w_ + 20, ym - 6), (bx0 + w_ + 20, by0 + h_ + 20), (bx0 - 20, by0 + h_ + 20)], 'halve')]
        at = Atlas(); vh, _ = (render_fxfrom(at, cr, anchor, mir, walls, None) if path == 'from' else render_character(at, [cr], anchor, mir, walls, 2))
        ah = at.img.copy()
        at2 = Atlas(); vv, _ = (render_fxfrom(at2, cv, anchor, mir, walls, None) if path == 'from' else render_character(at2, [cv], anchor, mir, walls, 2))
        av = at2.img.copy()
        jobs += [Job(f'w{i}_h', ah, vh, z, cam, W, H), Job(f'w{i}_v', av, vv, z, cam, W, H, shaders='orig')]
    res = run_jobs(jobs, 'sub')
    worst = 0.0; ious = []; wious = []
    sheet = []
    for tag, n, acc, (w, h, L, T, k), anchor, cam, mir in meta:
        got = res[tag + '_h']['black']
        sx0 = anchor[0] - ((w - L) if mir else L); sy0 = anchor[1] - T
        sx = int(round((sx0 - cam[0]) * z)); sy = int(round((sy0 - cam[1]) * z))
        g = got[sy:sy + k * h, sx:sx + k * w]
        d = np.abs(g - acc[:g.shape[0], :g.shape[1]]).max()
        worst = max(worst, d)
        if d > 1.5 / 255:
            print('  ecart', tag, n, round(d * 255, 2))
        ious.append(masks_iou(res[tag + '_v']['alpha'], res[tag + '_h']['alpha']))
        wt = 'w' + tag[1:]
        wious.append(masks_iou(res[wt + '_v']['alpha'], res[wt + '_h']['alpha']))
        if len(sheet) < 8:
            sheet.append(np.concatenate([res[tag + '_v']['black'], got], axis=1))
    report('sous-teintes: pixel exact a z=2 (formule bg2hd sur la palette realisee, teinte et gris compris)', worst <= 1.5 / 255,
           max_ecart_sur_255=round(worst * 255, 2), n=len(meta))
    report('sous-teintes: silhouette ~ origine', min(ious) > 0.85, min_iou=min(ious), mean_iou=float(np.mean(ious)))
    report('sous-teintes: murs attenuants', min(wious) > 0.85, min_iou=min(wious))
    to_png(os.path.join(WORK, 'suite_subshade.png'), np.concatenate([np.concatenate(sheet[i:i + 2], axis=1) for i in range(0, len(sheet) - 1, 2)], axis=0))
    json.dump(RESULTS, open(os.path.join(WORK, 'results_subshade.json'), 'w'), indent=1)
    print('temps', round(time.time() - t0, 1), 's')


if __name__ == '__main__':
    main()
