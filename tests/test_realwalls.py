# test_realwalls.py - murs reels (WED de BG2) : le sprite HD doit etre attenue exactement comme
# le sprite d'origine, y compris quand des murs tombent sur la zone HD du cadre.
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from wed import Wed, search_map
from test_suite import load, hd_of, build, Creature, realize_palette, Job, run_jobs, to_png, WORK, masks_iou, report, RESULTS
from wall_stats import regions, frac, WALKABLE, U
import schd

rng = np.random.default_rng(5)
b = load('CHMB1A1.BAM')
pal = realize_palette(b.palette)
W = H = 300
z = 3.34

def fx_rect_vanilla(fr, anchor, mir):
    fxw, fxh = fr.w + 2, fr.h + 2
    refx, refy = fr.cx + 1, fr.cy + 1
    L = anchor[0] - (fxw - refx) if mir else anchor[0] - refx
    return (L, anchor[1] - refy, L + fxw, anchor[1] - refy + fxh)

def fx_rect_hd(pix, cx2, cy2, anchor, mir):
    fxw, fxh = pix.shape[1] + 2, pix.shape[0] + 2
    refx, refy = cx2 + 1, cy2 + 1
    L = anchor[0] - (fxw - refx) if mir else anchor[0] - refx
    return (L, anchor[1] - refy, L + fxw, anchor[1] - refy + fxh)

cases = []
for area in ('AR0700', 'AR0602'):
    wd = Wed(open(U + area + '.WED', 'rb').read())
    sm = search_map(open(U + area + 'SR.BMP', 'rb').read())
    ys, xs = np.nonzero(np.isin(sm, list(WALKABLE)))
    got = dict(hd_only=0, both=0, probe=0)
    for i in rng.permutation(len(xs)):
        if all(v >= 8 for v in got.values()):
            break
        anchor = (int(xs[i] * 16 + 8), int(ys[i] * 12 + 6))
        fr = b.frames[int(rng.integers(0, len(b.frames)))]
        if fr.w < 8 or fr.h < 8:
            continue
        mir = bool(rng.integers(0, 2))
        pix, cx2, cy2, _ = hd_of(b, fr)
        rh = fx_rect_hd(pix, cx2, cy2, anchor, mir); rv = fx_rect_vanilla(fr, anchor, mir)
        ph = wd.applied(rh, anchor); pv = wd.applied(rv, anchor)
        if not ph:
            continue
        # zones du monde : sprite (bloc-sonde) et reste du cadre
        sx0 = anchor[0] - (fr.w - fr.cx) if mir else anchor[0] - fr.cx
        probe = (sx0, anchor[1] - fr.cy, sx0 + fr.w, anchor[1] - fr.cy + fr.h)
        fp = frac(ph, wd, probe); fh = frac(ph, wd, rh)
        cat = 'both' if (fp > 0.01 and fh > fp + 0.01) else 'probe' if fp > 0.01 else 'hd_only' if fh > 0.01 else None
        if cat is None or got[cat] >= 8:
            continue
        got[cat] += 1
        cases.append(dict(area=area, anchor=anchor, fr=fr, mir=mir, pix=pix, cx2=cx2, cy2=cy2,
                          walls_h=[wd.polys[j]['pts'] for j in ph], walls_v=[wd.polys[j]['pts'] for j in pv], cat=cat))
print('cas', len(cases), {c: sum(1 for x in cases if x['cat'] == c) for c in ('hd_only', 'both', 'probe')})

jobs = []
for n, c in enumerate(cases):
    cam = (c['anchor'][0] - W / (2 * z), c['anchor'][1] - 30 - H / (2 * z))
    cv = Creature(c['fr'].pix, c['fr'].cx, c['fr'].cy, pal, b.tidx)
    chd = Creature(c['pix'], c['cx2'], c['cy2'], pal, b.tidx)
    for mode in ('halve', 'clear'):
        av, vv, _ = build([(cv, c['anchor'], c['mir'], [(p, mode) for p in c['walls_v']], 2)], neighbors=False)
        ah, vh, _ = build([(chd, c['anchor'], c['mir'], [(p, mode) for p in c['walls_h']], 2)], neighbors=False)
        jobs += [Job(f'r{n}_{mode}_v', av, vv, z, cam, W, H, shaders='orig'), Job(f'r{n}_{mode}_h', ah, vh, z, cam, W, H)]
    av, vv, _ = build([(cv, c['anchor'], c['mir'], (), 2)], neighbors=False)
    ah, vh, _ = build([(chd, c['anchor'], c['mir'], (), 2)], neighbors=False)
    jobs += [Job(f'r{n}_free_v', av, vv, z, cam, W, H, shaders='orig'), Job(f'r{n}_free_h', ah, vh, z, cam, W, H)]
res = run_jobs(jobs, 'real')

summary = {}
sheet = []
for n, c in enumerate(cases):
    fv, fh = res[f'r{n}_free_v'], res[f'r{n}_free_h']
    body = (fv['alpha'] > 0.9) & (fh['alpha'] > 0.9)
    for mode in ('halve', 'clear'):
        wv, wh = res[f'r{n}_{mode}_v'], res[f'r{n}_{mode}_h']
        rv = wv['alpha'][body] / fv['alpha'][body]; rh = wh['alpha'][body] / fh['alpha'][body]
        d = np.abs(rv - rh)
        key = (c['cat'], mode)
        summary.setdefault(key, []).append((float(d.mean()), float((d > 0.25).mean())))
    if len(sheet) < 6 and c['cat'] in ('hd_only', 'both'):
        sheet.append(np.concatenate([res[f'r{n}_{m}_{s}']['black'] * 0.5 + 0.5 * res[f'r{n}_{m}_{s}']['white']
                                     for m in ('halve', 'clear') for s in ('v', 'h')], axis=1))
for (cat, mode), v in sorted(summary.items()):
    md = np.mean([x[0] for x in v]); worst = max(x[1] for x in v)
    ok = worst < 0.05 if mode == 'halve' else True
    report(f'murs reels {mode} cas={cat} ({len(v)} positions)', ok, ecart_moyen=md, pire_part_ecart_fort=worst)
if sheet:
    to_png(os.path.join(WORK, 'suite_murs_reels.png'), np.concatenate(sheet, axis=0))
json.dump(RESULTS, open(os.path.join(WORK, 'results_real.json'), 'w'), indent=1)
