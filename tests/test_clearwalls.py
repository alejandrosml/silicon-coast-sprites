# test_clearwalls.py - murs "effacants" (option Always Dither desactivee) sur les cadres v2 (FXBltFromClipped) :
# jamais de dechets (reperes ou image HD brute dessines), pertes limitees aux texels HD effaces.
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from scipy.ndimage import binary_dilation
import test_allscene as T
from engine_sim import Pages, render_character
from scene import Job, run_jobs, to_png, WORK
from test_suite import report, RESULTS, masks_iou

HD = sys.argv[1] if len(sys.argv) > 1 else os.path.join(T.SP, 'all', 'scene_hd')
rng = np.random.default_rng(11)
CLIP = [c for c in T.CAST if c[1] == 'clip']


def world_rect(ls, anchor, mir, margin=2):
    from engine_sim import fx_layout
    fxw, fxh, ptref, _ = fx_layout(ls, margin)
    left = anchor[0] - (fxw - ptref[0]) if mir else anchor[0] - ptref[0]
    top = anchor[1] - ptref[1]
    return left, top, left + fxw, top + fxh


def main():
    t0 = time.time()
    W = H = 400
    junk_max = 0.0; per = {}
    sheet = []
    for ci, (fam, path, names, c, f) in enumerate(CLIP):
        jobs = []
        lv = T.layers(T.SRC, names, c, f); lh = T.layers(HD, names, c, f)
        for case in range(8):
            mir = bool(case % 2)
            anchor = (200, 300)
            L, Tp, R, B = world_rect(lh, anchor, mir)
            # polygones : bande verticale sur un bord du cadre HD (spine), coin, bande oblique, bande haute
            kind = case // 2
            if kind == 0:      # bord droit du cadre HD (toute la hauteur)
                x = R - rng.integers(4, 40)
                poly = [(x, Tp - 50), (R + 60, Tp - 50), (R + 60, B + 50), (x - 8, B + 50)]
            elif kind == 1:    # bord gauche
                x = L + rng.integers(4, 40)
                poly = [(L - 60, Tp - 50), (x, Tp - 50), (x + 8, B + 50), (L - 60, B + 50)]
            elif kind == 2:    # coin haut-droit + haut
                poly = [(L + (R - L) // 3, Tp - 40), (R + 40, Tp - 40), (R + 40, Tp + (B - Tp) // 2), (L + (R - L) // 2, Tp + (B - Tp) // 3)]
            else:              # les deux bords (deux piliers)
                x1 = L + rng.integers(4, 30); x2 = R - rng.integers(4, 30)
                poly = [(L - 40, Tp - 40), (x1, Tp - 40), (x1, B + 40), (L - 40, B + 40)]
                poly2 = [(x2, Tp - 40), (R + 40, Tp - 40), (R + 40, B + 40), (x2, B + 40)]
            walls = [(poly, 'clear')] + ([(poly2, 'clear')] if kind == 3 else [])
            for d, ls, sh in ((T.SRC, lv, 'orig'), (HD, lh, 'new')):
                pg = Pages()
                pg.draw(lambda at: render_character(at, ls, anchor, mir, walls, 2))
                jobs.append(Job(f'c{ci}_{case}_{sh}', pg.result(), None, 1.0, (0, 0), W, H, shaders=sh))
        res = run_jobs(jobs, 'clearwalls')
        for case in range(8):
            a = res[f'c{ci}_{case}_orig']['alpha']; b = res[f'c{ci}_{case}_new']['alpha']
            dil = binary_dilation(a > 0.02, iterations=4)
            junk = float(((b > 0.1) & ~dil).sum())
            junk_max = max(junk_max, junk)
            vis = (a > 0.5).sum()
            lost = float(((a > 0.5) & (b < 0.1)).sum()) / max(1, vis)
            per.setdefault(case // 2, []).append((junk, lost, fam))
            if junk > 20 and len(sheet) < 6:
                sheet.append(np.concatenate([res[f'c{ci}_{case}_orig']['black'], res[f'c{ci}_{case}_new']['black']], axis=1))
    names = ['bord droit', 'bord gauche', 'coin haut', 'deux bords']
    for kd, lst in per.items():
        print(names[kd], 'dechets max', max(x[0] for x in lst), 'pertes moy %.3f max %.3f' % (np.mean([x[1] for x in lst]), max(x[1] for x in lst)),
              'pire', max(lst, key=lambda x: x[0])[2][:30])
    one_side = max(x[0] for kd, lst in per.items() if kd != 3 for x in lst)
    report('murs effacants (v2), un cote ou le haut du cadre : aucun dechet (reperes, image HD brute)', one_side < 20,
           max_px=one_side)
    # deux pieces de mur sur les deux spines a la fois : cadre brut possible (limite connue, Always Dither requis)
    report('murs effacants (v2), les deux spines effacees (limite connue, information)', True,
           max_px=max(x[0] for x in per.get(3, [(0, 0, '')])))
    if sheet:
        to_png(os.path.join(WORK, 'clearwalls_bad.png'), np.concatenate(sheet, axis=0))
    print('temps', round(time.time() - t0, 1))


if __name__ == '__main__':
    main()
