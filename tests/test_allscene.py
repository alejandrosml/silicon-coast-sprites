# test_allscene.py - une scene simulee avec une creature de chaque famille d'animation de BG2:EE (calques et
# chemins de rendu du moteur), murs, miroir, effets de palette, contours, surfaces voisines dans l'atlas.
# Les BAM HD viennent de sc_convert.py (tous les cadres verifies par sc_verify.py).
import sys, os, json, time, argparse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from bam import BamV1
from engine_sim import Atlas, Pages, realize_palette, Creature, render_character, render_fxfrom
from scene import Job, run_jobs, to_png, WORK
from test_suite import report, RESULTS, masks_iou, centroid

SP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(SP, 'all', 'src')
rng = np.random.default_rng(5)

# (famille, chemin, calques dans l'ordre de dessin, cycle, image)
CAST = [
    ('Character L (plates, arme, bouclier, casque)', 'clip', ['CHMF4A1', 'WQLAXA1', 'WQLD2A1', 'WQLH1A1'], 2, 5),
    ('Character N', 'clip', ['CHFB1A1', 'WQNAXA1'], 1, 4),
    ('Character M (elfe)', 'clip', ['CEMB1A1', 'WQMAXA1'], 3, 3),
    ('Character S (nain)', 'clip', ['CDMB1A1', 'WQSAXA1'], 0, 6),
    ('Character S (halfelin)', 'clip', ['CIMB1A1', 'WQSAXA1'], 4, 2),
    ('CharacterOld (ombre, corps, arme)', 'clip', ['CSHDA1', 'CMNK1A1', 'WPMAXA1'], 2, 3),
    ('Monster (corps fractionne + arme)', 'clip', ['MSAHG11', 'MSAHG1CB'], 3, 4),
    ('MonsterIcewind (corps + arme)', 'clip', ['MSKTA1', 'MSKTAA1'], 2, 7),
    ('MonsterLayered (corps + arme)', 'clip', ['MHOBG1', 'MHOBSG1'], 9, 3),
    ('MonsterLayeredSpell', 'clip', ['MSIRG1', 'MSIRBG1'], 1, 2),
    ('MonsterOld', 'clip', ['MOGHG1'], 2, 4),
    ('MonsterLarge', 'clip', ['MOGRG1'], 1, 3),
    ('MonsterLarge16', 'clip', ['MWYVG1'], 2, 3),
    ('MonsterAnkheg', 'clip', ['MAKHG1'], 8, 5),
    ('Ambient', 'clip', ['ABATG1'], 1, 2),
    ('AmbientStatic', 'clip', ['ACOWG1'], 0, 5),
    ('Flying', 'clip', ['AEAGG1'], 9, 3),
    ('TownStatic', 'clip', ['SNOMC'], 2, 10),
    ('MonsterQuadrant (wyverne, 4 quarts)', 'from', ['MWYVG11', 'MWYVG12', 'MWYVG13', 'MWYVG14'], 2, 3),
    # dragon : 9 tuiles 3x3 (MDR1 + groupe + tuile 1-9 + 0 + direction), chacune sa surface FX, cycle = direction
    ('MonsterMulti (dragon, 9 tuiles)', 'from', ['MDR11%d04' % p for p in range(1, 10)], 4, 3),
    ('MonsterMultiNew (Demogorgon)', 'from', ['MDEMG111', 'MDEMG121', 'MDEMG131', 'MDEMG141'], 0, 2),
]
_c = {}


def bam(d, n):
    k = (d, n)
    if k not in _c:
        _c[k] = BamV1.load(open(os.path.join(d, n + '.BAM'), 'rb').read())
    return _c[k]


def layers(d, names, c, f, pal_kw=None):
    out = []
    for n in names:
        b = bam(d, n)
        if c >= len(b.cycles) or f >= b.cycles[c][0]:
            continue
        fr = b.frames[b.lookup[b.cycles[c][1] + f]]
        out.append(Creature(fr.pix, fr.cx, fr.cy, realize_palette(b.palette, **(pal_kw or {})), b.tidx))
    return out


def build_scene(d, positions, walls, mirror, pal_kw=None, outline=False, noise=True):
    """renvoie (pages, sommets) : pages = [(atlas, sommets)] dans l'ordre de dessin (vidages du moteur)"""
    pg = Pages()
    for (fam, path, names, c, f), anchor in zip(CAST, positions):
        ls = layers(d, names, c, f, pal_kw)
        mir = mirror.get(fam, False)
        if noise:
            pg.alloc(*rng.integers(6, 40, 2))
        if path == 'clip':
            pg.draw(lambda at: render_character(at, ls, anchor, mir, walls, 8 if outline else 2))
        else:
            for cr in ls:                      # une surface par partie, collees dans l'atlas
                pg.draw(lambda at, cr=cr: render_fxfrom(at, cr, anchor, mir, walls, None))
    pages = pg.result()
    return pages, [v for p in pages for v in p[1]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('hd_dir')
    ap.add_argument('--tag', default='all')
    a = ap.parse_args()
    t0 = time.time()
    # positions sur une grille (monde), les grands (dragon, Demogorgon) a part
    pos = []
    for i, (fam, path, names, c, f) in enumerate(CAST):
        if 'dragon' in fam:
            pos.append((1150, 760))
        elif 'Demogorgon' in fam:
            pos.append((1500, 780))
        else:
            pos.append((140 + 150 * (i % 6), 230 + 230 * (i // 6)))
    walls_sets = {'sans_murs': [],
                  'murs_attenuants': [([(100, 260), (1000, 300), (1000, 360), (100, 330)], 'halve'),
                                      ([(1050, 500), (1300, 520), (1250, 800), (1040, 780)], 'halve')],
                  'murs_effacants': [([(100, 260), (1000, 300), (1000, 360), (100, 330)], 'clear'),
                                     ([(1050, 500), (1300, 520), (1250, 800), (1040, 780)], 'clear')]}
    mirror = {fam: (i % 2 == 1) for i, (fam, *_r) in enumerate(CAST)}
    W, H = 1700, 1000
    jobs = []
    z = 1.0; cam = (0, 0)
    for wname, walls in walls_sets.items():
        av, vv = build_scene(SRC, pos, walls, mirror)
        ah, vh = build_scene(a.hd_dir, pos, walls, mirror)
        jobs += [Job(f'{wname}_vo', av, vv, z, cam, W, H, shaders='orig'),
                 Job(f'{wname}_vn', av, vv, z, cam, W, H, shaders='new'),
                 Job(f'{wname}_hn', ah, vh, z, cam, W, H, shaders='new')]
    # effets de palette
    for pname, kw in [('transp', dict(transp=128)), ('teinte', dict(tint=(255, 120, 80))), ('gris', dict(greyscale=True))]:
        av, vv = build_scene(SRC, pos, [], mirror, kw)
        ah, vh = build_scene(a.hd_dir, pos, [], mirror, kw)
        jobs += [Job(f'pal_{pname}_vo', av, vv, z, cam, W, H, shaders='orig'),
                 Job(f'pal_{pname}_hn', ah, vh, z, cam, W, H, shaders='new')]
    # contours (marge 8)
    for fs in ('FPSPRITE', 'FPSELECT'):
        av, vv = build_scene(SRC, pos, [], mirror, outline=True)
        ah, vh = build_scene(a.hd_dir, pos, [], mirror, outline=True)
        for v in vv + vh:
            v['col'] = (60, 255, 60, 255)
        jobs += [Job(f'out_{fs}_vo', av, vv, z, cam, W, H, fs=fs, shaders='orig'),
                 Job(f'out_{fs}_vn', av, vv, z, cam, W, H, fs=fs, shaders='new'),
                 Job(f'out_{fs}_hn', ah, vh, z, cam, W, H, fs=fs, shaders='new')]
    # zoom x2 sur deux zones
    for zi, (cx, cy) in enumerate([(450, 420), (1250, 650)]):
        z2 = 2.0; cam2 = (cx - W / 4, cy - H / 4)
        av, vv = build_scene(SRC, pos, walls_sets['murs_attenuants'], mirror)
        ah, vh = build_scene(a.hd_dir, pos, walls_sets['murs_attenuants'], mirror)
        jobs += [Job(f'zoom{zi}_vo', av, vv, z2, cam2, W, H, shaders='orig'),
                 Job(f'zoom{zi}_hn', ah, vh, z2, cam2, W, H, shaders='new')]
    res = run_jobs(jobs, 'allscene_' + a.tag)
    print('rendu', round(time.time() - t0, 1), 's', len(jobs), 'scenes')

    # ---------------------------------------------------------------- evaluation par creature
    def crop(img, p, z, cam, r=(110, 230, 110, 60)):
        x0 = int((p[0] - r[0] - cam[0]) * z); x1 = int((p[0] + r[2] - cam[0]) * z)
        y0 = int((p[1] - r[1] - cam[1]) * z); y1 = int((p[1] + r[3] - cam[1]) * z)
        x0, y0 = max(0, x0), max(0, y0)
        return img[y0:y1, x0:x1]
    worst_reg = 0.0
    per = {}; per_clear = {}
    for tag in [t[:-3] for t in res if t.endswith('_hn')]:
        vo = res[tag + '_vo']; hn = res[tag + '_hn']
        if tag + '_vn' in res:
            vn = res[tag + '_vn']
            worst_reg = max(worst_reg, np.abs(vo['black'] - vn['black']).max(), np.abs(vo['white'] - vn['white']).max())
        thr_a = 0.2 if tag == 'pal_transp' else 0.5        # transparence 128 : alpha ~ 0.5
        if tag.startswith('zoom'):
            per.setdefault('zoom x2 (scene entiere)', []).append((tag, masks_iou(vo['alpha'], hn['alpha'], thr_a)))
            continue
        for (fam, path, names, c, f), p in zip(CAST, pos):
            r = (110, 230, 110, 60) if 'dragon' not in fam and 'Demogorgon' not in fam else (330, 520, 330, 200)
            a1 = crop(vo['alpha'], p, 1.0, (0, 0), r); a2 = crop(hn['alpha'], p, 1.0, (0, 0), r)
            if (a1 > thr_a).sum() < 30 and (a2 > thr_a).sum() < 30:
                continue                       # creature entierement cachee (mur effacant)
            dest = per_clear if tag == 'murs_effacants' else per
            dest.setdefault(fam, []).append((tag, masks_iou(a1, a2, thr_a)))
    report('scene: regression (calques d origine, nouveaux vs anciens shaders, toutes familles)', worst_reg == 0.0, max_diff=worst_reg)
    for fam, lst in per.items():
        vals = [x[1] for x in lst]
        ok = min(vals) > 0.85
        report(f'scene: {fam}', ok, min_iou=min(vals), mean_iou=float(np.mean(vals)), n=len(vals),
               pire=[x[0] for x in lst if x[1] == min(vals)][:1])
    # murs effacants (Always Dither desactive, hors reglage par defaut) : trous possibles dans la zone HD
    cl = [x[1] for lst in per_clear.values() for x in lst]
    if cl:
        report('scene: murs effacants (information, limite connue : trous)', True, min_iou=min(cl), mean_iou=float(np.mean(cl)))
    # aucun dechet : rien de dessine (alpha > 0.1) hors des silhouettes d'origine dilatees de 6 px
    from scipy.ndimage import binary_dilation
    junk = {}
    for tag in [t[:-3] for t in res if t.endswith('_hn') and not t.startswith('zoom')]:
        vo = res[tag + '_vo']['alpha'] > 0.02; hn = res[tag + '_hn']['alpha'] > 0.1
        dil = binary_dilation(vo, iterations=6)
        junk[tag] = float((hn & ~dil).sum())
    report('scene: aucun texel parasite hors des silhouettes (reperes, blocs, images HD brutes)', max(junk.values()) < 50,
           pixels=max(junk.values()), pire=max(junk, key=junk.get))
    comp = lambda r: r['black'] * 0.5 + 0.5 * r['white']
    to_png(os.path.join(WORK, f'scene_{a.tag}_vo.png'), comp(res['murs_attenuants_vo']))
    to_png(os.path.join(WORK, f'scene_{a.tag}_hn.png'), comp(res['murs_attenuants_hn']))
    to_png(os.path.join(WORK, f'scene_{a.tag}_zoom.png'), np.concatenate([comp(res['zoom0_vo']), comp(res['zoom0_hn'])], axis=1))
    json.dump(RESULTS, open(os.path.join(WORK, f'results_allscene_{a.tag}.json'), 'w'), indent=1)
    print('temps', round(time.time() - t0, 1), 's')


if __name__ == '__main__':
    main()
