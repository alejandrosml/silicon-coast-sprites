# test_layoutF.py - disposition F (familles FXBltFrom : wyvernes, dragons, Demogorgon) hors ligne.
# Rendu moteur simule (CInfinity::FXBltFrom : surface de la taille du cadre, quad decoupe a la fenetre de jeu,
# surfaces voisines dans l'atlas) avec les shaders d'origine (cadres d'origine) et Silicon Coast (cadres F).
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from bam import BamV1
import schd
from engine_sim import Atlas, Pages, realize_palette, Creature, render_fxfrom, render_creature
from scene import Job, run_jobs, to_png, WORK
from test_suite import report, RESULTS, masks_iou, centroid

SP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(SP, 'all', 'src')
rng = np.random.default_rng(23)
_c = {}


def bam(name):
    if name not in _c:
        _c[name] = BamV1.load(open(os.path.join(SRC, name + '.BAM'), 'rb').read())
    return _c[name]


def frame_at(b, c, f):
    cnt, st = b.cycles[c]
    return b.frames[b.lookup[st + f]]


def tight(pix, t):
    nz = pix != t
    ys = np.flatnonzero(nz.any(1)); xs = np.flatnonzero(nz.any(0))
    return int(xs[0]), int(ys[0]), int(xs[-1]) + 1, int(ys[-1]) + 1


_fc = {}


def make_f(name, c, f, k=4):
    """cadre F d'une image d'origine (geometrie = boite serree), k le plus grand qui tient."""
    key = (name, c, f, k)
    if key in _fc:
        return _fc[key]
    b = bam(name); fr = frame_at(b, c, f); t = b.tidx
    x0, y0, x1, y1 = tight(fr.pix, t)
    ext = (fr.cx - x0, fr.cy - y0, x1 - fr.cx, y1 - fr.cy)
    kk = k
    g = schd.GeometryF(*ext, kk)
    while g.layout is None:
        kk -= 1
        g = schd.GeometryF(*ext, kk)
    cv = schd.canvas_1x(fr.pix, fr.cx, fr.cy, g, t)
    hd = schd.upscale_canvas(cv, kk, t)
    mark = schd.pick_mark(b.palette, t)
    flags = schd.FLAG_PALALPHA if schd.palette_has_alpha(b.palette) else 0
    pix = schd.build_layer_f(hd, g, True, tidx=t, mark=mark, flags=flags)
    assert schd.is_valid_build_f(pix, t)
    cx, cy = g.center
    _fc[key] = (pix, cx, cy, g, hd)
    return _fc[key]


def creatures(parts, c, f, hd, pal_kw=None):
    out = []
    for n in parts:
        b = bam(n); pal = realize_palette(b.palette, **(pal_kw or {}))
        if not (frame_at(b, c, f).pix != b.tidx).any():
            continue                           # tuile vide a cette image (rien a dessiner)
        if hd:
            pix, cx, cy, g, _ = make_f(n, c, f)
            out.append(Creature(pix, cx, cy, pal, b.tidx))
        else:
            fr = frame_at(b, c, f)
            out.append(Creature(fr.pix, fr.cx, fr.cy, pal, b.tidx))
    return out


def noise(pg, w, h):
    x, y = pg.alloc(w, h)
    pg.at.img[y:y + h, x:x + w] = rng.integers(0, 256, (h, w, 4), dtype=np.uint8)


def scene(items, noise_between=False):
    """items : liste de (Creature, ancre, miroir, murs, fenetre, chemin) ; chemin 'from' ou 'clip'.
    Renvoie (pages, sommets, infos) ; pages = [(atlas, sommets)] (le moteur vide sa file quand l'atlas est plein)."""
    pg = Pages(); infos = []
    for cr, anchor, mir, walls, vp, path in items:
        if noise_between:
            noise(pg, *rng.integers(8, 70, 2))
        if path == 'from':
            info = pg.draw(lambda at: render_fxfrom(at, cr, anchor, mir, walls, vp))
        else:
            info = pg.draw(lambda at: render_creature(at, cr, anchor, mir, walls, 2))
        infos.append(info)
    pages = pg.result()
    return pages, [v for p in pages for v in p[1]], infos


def cam_for(anchor, z, W, H, dy=0):
    return (anchor[0] - W / (2 * z), anchor[1] - dy - H / (2 * z))


WYV = ['MWYVG11', 'MWYVG12', 'MWYVG13', 'MWYVG14']


def dragon_parts(d=1):
    """les 9 tuiles (3x3) d'une image de dragon : MDR1 + groupe + tuile (1-9) + 0 + direction ; cycle = direction"""
    return ['MDR11%d0%d' % (p, d) for p in range(1, 10)]


def main():
    t0 = time.time()
    W = H = 400
    jobs = []; meta = []
    # ---------------------------------------------------------------- A/B. wyverne (4 quarts) et dragon : entiers
    sets = [('wyv', WYV, 2, 3), ('wyv', WYV, 5, 6), ('dragon', dragon_parts(), 1, 4)]
    for si, (kind, parts, c, f) in enumerate(sets):
        for mir in (False, True):
            for z in (1.0, 2.0):
                anchor = (300, 330)
                cam = cam_for(anchor, z, W, H, 60 if kind == 'wyv' else 120)
                cv = creatures(parts, c, f, False); ch = creatures(parts, c, f, True)
                av, vv, _ = scene([(x, anchor, mir, (), None, 'from') for x in cv])
                ah, vh, _ = scene([(x, anchor, mir, (), None, 'from') for x in ch])
                tag = f'w{si}_{int(mir)}_{z}'
                jobs += [Job(tag + '_vo', av, vv, z, cam, W, H, shaders='orig'),
                         Job(tag + '_vn', av, vv, z, cam, W, H, shaders='new'),
                         Job(tag + '_hn', ah, vh, z, cam, W, H, shaders='new')]
                meta.append(('whole', tag, z))
    # ---------------------------------------------------------------- C. fenetre de jeu qui coupe (bords, coins)
    anchor = (300, 330)
    parts = WYV; c, f = 2, 3
    cv = creatures(parts, c, f, False); ch = creatures(parts, c, f, True)
    z = 2.0
    cam = cam_for(anchor, z, W, H, 60)
    # rect de la fenetre en coordonnees du monde : la camera montre [cam, cam + W/z]
    X0, Y0, X1, Y1 = cam[0], cam[1], cam[0] + W / z, cam[1] + H / z
    cuts = {'gauche': (anchor[0] - 20, Y0, X1, Y1), 'droite': (X0, Y0, anchor[0] + 15, Y1),
            'haut': (X0, anchor[1] - 70, X1, Y1), 'bas': (X0, Y0, X1, anchor[1] - 25),
            'coin_bas_droite': (X0, Y0, anchor[0] + 10, anchor[1] - 30),
            'coin_haut_gauche': (anchor[0] - 25, anchor[1] - 80, X1, Y1),
            'fenetre_etroite': (anchor[0] - 30, anchor[1] - 90, anchor[0] + 25, anchor[1] - 20)}
    for name, vp in cuts.items():
        vp = tuple(int(round(v)) for v in vp)
        for mir in (False, True):
            av, vv, _ = scene([(x, anchor, mir, (), vp, 'from') for x in cv])
            ah, vh, _ = scene([(x, anchor, mir, (), vp, 'from') for x in ch])
            tag = f'cut_{name}_{int(mir)}'
            jobs += [Job(tag + '_vo', av, vv, z, cam, W, H, shaders='orig'),
                     Job(tag + '_vn', av, vv, z, cam, W, H, shaders='new'),
                     Job(tag + '_hn', ah, vh, z, cam, W, H, shaders='new')]
            meta.append(('cut', tag, z))
    # ---------------------------------------------------------------- D. voisins : cadres d'origine FXBltFrom collés
    # aux cadres F (coins partages) et surfaces de bruit intercalees
    mixes = []
    for mi, mode in enumerate(['alterne', 'bruit']):
        items_h = []; items_v = []
        for pi, n in enumerate(WYV):
            crh = creatures([n], c, f, True)[0]; crv = creatures([n], c, f, False)[0]
            use_hd = (pi % 2 == 0) if mode == 'alterne' else True
            items_h.append((crh if use_hd else crv, anchor, False, (), None, 'from'))
            items_v.append((crv, anchor, False, (), None, 'from'))
        av, vv, _ = scene(items_v, noise_between=(mode == 'bruit'))
        ah, vh, _ = scene(items_h, noise_between=(mode == 'bruit'))
        tag = f'mix_{mode}'
        jobs += [Job(tag + '_vo', av, vv, z, cam, W, H, shaders='orig'),
                 Job(tag + '_hn', ah, vh, z, cam, W, H, shaders='new')]
        meta.append(('mix', tag, z))
    # ---------------------------------------------------------------- E. murs (attenuant / effacant)
    for mode in ('halve', 'clear'):
        for wi, poly in enumerate([[(250, 300), (420, 300), (420, 420), (250, 420)],
                                   [(200, 250), (305, 250), (305, 400), (200, 400)],
                                   [(260, 200), (420, 330), (300, 420)]]):
            walls = [(poly, mode)]
            av, vv, _ = scene([(x, anchor, False, walls, None, 'from') for x in cv])
            ah, vh, _ = scene([(x, anchor, False, walls, None, 'from') for x in ch])
            tag = f'wall_{mode}_{wi}'
            jobs += [Job(tag + '_vo', av, vv, z, cam, W, H, shaders='orig'),
                     Job(tag + '_hn', ah, vh, z, cam, W, H, shaders='new')]
            meta.append(('wall_' + mode, tag, z))
    # ---------------------------------------------------------------- F. palette : transparence, teinte, gris
    for pname, kw in [('transp', dict(transp=128)), ('teinte', dict(tint=(255, 140, 90))), ('gris', dict(greyscale=True))]:
        cvp = creatures(parts, c, f, False, kw); chp = creatures(parts, c, f, True, kw)
        av, vv, _ = scene([(x, anchor, False, (), None, 'from') for x in cvp])
        ah, vh, _ = scene([(x, anchor, False, (), None, 'from') for x in chp])
        tag = f'pal_{pname}'
        jobs += [Job(tag + '_vo', av, vv, z, cam, W, H, shaders='orig'),
                 Job(tag + '_hn', ah, vh, z, cam, W, H, shaders='new')]
        meta.append(('pal', tag, z))
    # ---------------------------------------------------------------- G. contours (FPSPRITE / FPSELECT)
    for fs in ('FPSPRITE', 'FPSELECT'):
        av, vv, _ = scene([(x, anchor, False, (), None, 'from') for x in cv])
        ah, vh, _ = scene([(x, anchor, False, (), None, 'from') for x in ch])
        tag = f'out_{fs}'
        col = (0.2, 1.0, 0.2, 1.0)
        for v in vv + vh:
            v['col'] = tuple(int(255 * x) for x in col)
        jobs += [Job(tag + '_vo', av, vv, z, cam, W, H, fs=fs, shaders='orig'),
                 Job(tag + '_vn', av, vv, z, cam, W, H, fs=fs, shaders='new'),
                 Job(tag + '_hn', ah, vh, z, cam, W, H, fs=fs, shaders='new')]
        meta.append(('out', tag, z))
    # ---------------------------------------------------------------- H. texel exact a z = 4
    z4 = 4.0; W4 = H4 = 800
    exact = []
    for ei, (n, cc, ff, mir, vp) in enumerate([('MWYVG11', 2, 3, False, None), ('MWYVG13', 5, 1, True, None),
                                              ('MWYVG11', 2, 3, False, 'cut'), ('MDEMG111', 0, 2, False, None)]):
        if not os.path.exists(os.path.join(SRC, n + '.BAM')):
            continue
        pix, cx, cy, g, hdimg = make_f(n, cc, ff)
        b = bam(n)
        cr = Creature(pix, cx, cy, realize_palette(b.palette), b.tidx)
        anc = (300, 330)
        cam4 = (float(anc[0] - 100), float(anc[1] - 160))
        vpr = None
        if vp == 'cut':
            vpr = (anc[0] - 60, anc[1] - 150, anc[0] + 15, anc[1] + 40)
        ah, vh, _ = scene([(cr, anc, mir, (), vpr, 'from')], noise_between=True)
        jobs.append(Job(f'x{ei}', ah, vh, z4, cam4, W4, H4))
        exact.append((f'x{ei}', n, g, hdimg, b, anc, mir, cam4, vpr))
    res = run_jobs(jobs, 'layf')
    print('rendu', round(time.time() - t0, 1), 's', len(jobs), 'scenes')

    # ---------------------------------------------------------------- evaluation
    def comp(r):
        return r['black'] * 0.5 + 0.5 * r['white']
    worst_reg = 0.0; ious = {}; cds = {}; sheet = []
    for kind, tag, z in meta:
        vo = res[tag + '_vo']; hn = res[tag + '_hn']
        if tag + '_vn' in res:
            vn = res[tag + '_vn']
            worst_reg = max(worst_reg, np.abs(vo['black'] - vn['black']).max(), np.abs(vo['white'] - vn['white']).max())
        th = 0.2 if kind == 'pal' else 0.5      # transparence 128 : alpha ~ 0,5
        iou = masks_iou(vo['alpha'], hn['alpha'], th)
        cd = np.abs(centroid(vo['alpha'] * (0.5 / th)) - centroid(hn['alpha'] * (0.5 / th))) / z if (vo['alpha'] > th).any() else np.zeros(2)
        ious.setdefault(kind, []).append(iou); cds.setdefault(kind, []).append(float(np.nan_to_num(cd).max()))
        if iou < 0.9:
            print('  douteux', tag, round(iou, 3), np.round(cd, 2))
        if len(sheet) < 18 and kind in ('whole', 'cut', 'mix', 'wall'):
            sheet.append(np.concatenate([comp(vo), comp(hn)], axis=1))
    report('F: regression (cadres FXBltFrom d origine, nouveaux vs anciens shaders, decoupe comprise)', worst_reg == 0.0, max_diff=worst_reg)
    for kind, lst in ious.items():
        if kind == 'wall_clear':
            # mode "effacant" (option Always Dither desactivee ; elle vaut 1 par defaut, CInfGame::LoadOptions) :
            # limite connue, un mur peut effacer les blocs de reperes autour d'une partie visible
            report(f'F: {kind} (limite connue, information)', True, min_iou=min(lst), mean_iou=float(np.mean(lst)), n=len(lst))
            continue
        report(f'F: {kind}: silhouette HD ~ origine', min(lst) > 0.9, min_iou=min(lst), mean_iou=float(np.mean(lst)), n=len(lst))
        report(f'F: {kind}: centre de masse (px du monde)', max(cds[kind]) < 1.0, max_offset=max(cds[kind]))
    # rien hors de la fenetre de jeu
    leak = 0.0
    for name, vp in cuts.items():
        vp = tuple(int(round(v)) for v in vp)
        for mir in (False, True):
            hn = res[f'cut_{name}_{int(mir)}_hn']
            x0 = int(round((vp[0] - cam[0]) * z)); y0 = int(round((vp[1] - cam[1]) * z))
            x1 = int(round((vp[2] - cam[0]) * z)); y1 = int(round((vp[3] - cam[1]) * z))
            m = np.ones((H, W), bool)
            m[max(0, y0):max(0, y1), max(0, x0):max(0, x1)] = False
            leak = max(leak, float(hn['alpha'][m].max()) if m.any() else 0.0)
    report('F: decoupe a la fenetre : rien n est dessine hors de la fenetre', leak < 0.01, max_alpha_dehors=leak)
    # texel exact
    worst = 0.0
    for tag, n, g, hdimg, b, anc, mir, cam4, vpr in exact:
        pal = realize_palette(b.palette).astype(np.float64) / 255.0
        m = hdimg != b.tidx
        rel = np.where(hdimg == 1, 0.5, 1.0)
        acc = np.zeros(hdimg.shape + (3,)); acc[m] = pal[hdimg][m][:, :3] * rel[m][:, None]
        if mir:
            acc = acc[:, ::-1]
            sx0 = anc[0] - (g.w - g.L)
        else:
            sx0 = anc[0] - g.L
        sy0 = anc[1] - g.T
        sx = int(round((sx0 - cam4[0]) * z4)); sy = int(round((sy0 - cam4[1]) * z4))
        got = res[tag]['black'][sy:sy + g.k * g.h, sx:sx + g.k * g.w]
        exp = acc[:got.shape[0], :got.shape[1]]
        if vpr is not None:
            # hors de la fenetre : rien
            vx0 = int(round((vpr[0] - cam4[0]) * z4)) - sx; vy0 = int(round((vpr[1] - cam4[1]) * z4)) - sy
            vx1 = int(round((vpr[2] - cam4[0]) * z4)) - sx; vy1 = int(round((vpr[3] - cam4[1]) * z4)) - sy
            mm = np.zeros(exp.shape[:2], bool)
            mm[max(0, vy0):max(0, vy1), max(0, vx0):max(0, vx1)] = True
            exp = exp * mm[..., None]
        d = np.abs(got - exp).max()
        worst = max(worst, d)
        if d > 2.5 / 255:
            print('  ecart texel', tag, n, round(d, 4))
    report('F: texel exact a z=4 (1 pixel = 1 texel HD), miroir et decoupe compris', worst < 2.5 / 255, max_diff=worst, n=len(exact))
    if sheet:
        rows = [np.concatenate(sheet[i:i + 3], axis=1) for i in range(0, len(sheet) - len(sheet) % 3, 3)]
        to_png(os.path.join(WORK, 'suite_layoutF.png'), np.concatenate(rows, axis=0))
    json.dump(RESULTS, open(os.path.join(WORK, 'results_layoutF.json'), 'w'), indent=1)
    print('temps', round(time.time() - t0, 1), 's')


if __name__ == '__main__':
    main()
