# test_regress.py - les nouveaux shaders doivent rendre a l'identique tout ce qui n'est pas SC-HD,
# y compris des quads qui ressemblent a des blits de creatures (aRef.y = 1 ou 2) et des "presque" cadres HD.
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import schd
from scene import Job, run_jobs, to_png, WORK
from test_suite import report, RESULTS

rng = np.random.default_rng(11)
A = 1024
atlas = rng.integers(0, 256, (A, A, 4), dtype=np.uint8)
# zones transparentes et opaques franches, comme dans un atlas reel
atlas[rng.random((A, A)) < 0.35, 3] = 0
atlas[200:400, 0:300, 3] = 0
atlas[400:600, 0:300, 3] = 255

def plant_near_miss(x0, y0, kind):
    """ecrit une ligne de spine plausible mais fausse (somme, motif oppose absent...)"""
    seq = schd.spine_row(0, 0, 4, 40, 50, 0, schd.PA)
    if kind == 'checksum':
        seq[schd.J_CS] ^= 1
    for j, bit in enumerate(seq):
        atlas[y0, x0 + j, 3] = 255 if bit else 0
    if kind == 'no_cross':
        pass   # spine gauche correcte, pas de spine droite
    return x0, y0

near = [plant_near_miss(10, 210, 'checksum'), plant_near_miss(10, 260, 'no_cross'), plant_near_miss(500, 700, 'checksum')]

def quad(x, y, w, h, tx, ty, tw, th, ref, mirror=False, col=(255, 255, 255, 255)):
    tl, tr = (tx + tw, tx) if mirror else (tx, tx + tw)
    c = {'LT': ((x, y), (tl, ty)), 'LB': ((x, y + h), (tl, ty + th)), 'RT': ((x + w, y), (tr, ty)), 'RB': ((x + w, y + h), (tr, ty + th))}
    return [dict(pos=c[k][0], tc=c[k][1], col=col, ref=ref) for k in ('LT', 'LB', 'RT', 'RT', 'LB', 'RB')]

verts = []
for i in range(400):
    w, h = rng.integers(4, 120, 2)
    tw, th = (w, h) if rng.random() < 0.7 else tuple(rng.integers(2, 200, 2))
    tx, ty = rng.integers(0, A - tw), rng.integers(0, A - th)
    x, y = rng.integers(-40, 360, 2)
    r = rng.random()
    if r < 0.4:
        ref = (float(rng.choice([1, 2])), float(rng.choice([1, 2])))
    elif r < 0.6:
        ref = (float(tw + 1), 1.0)
    else:
        ref = (float(rng.integers(0, 900)), float(rng.integers(0, 900)))
    col = tuple(int(c) for c in rng.integers(0, 256, 4)) if rng.random() < 0.5 else (255, 255, 255, 255)
    verts += quad(x, y, w, h, tx, ty, tw, th, ref, rng.random() < 0.5, col)
# quads poses exactement sur les "presque" cadres HD : aTc au coin de la spine plantee
for (x0, y0) in near:
    verts += quad(50, 50, 60, 40, x0, y0, 60, 40, (1.0, 1.0))
    verts += quad(150, 120, 60, 40, x0 - 1, y0 - 1, 60, 40, (2.0, 2.0))

W = H = 400
jobs = []
for prog in ('FPDRAW', 'FPTONE', 'FPSPRITE', 'FPSELECT'):
    for filt in ('linear', 'nearest'):
        for z in (1.0, 2.5):
            t = f'{prog}_{filt}_{z}'
            tone = (0.3, 0.4, 0.5, 0.6) if prog in ('FPDRAW', 'FPTONE') else (0, 0, 0, 0)
            jobs += [Job(t + '_o', atlas, verts, z, (0, 0), W, H, filt=filt, fs=prog, shaders='orig', tone=tone),
                     Job(t + '_n', atlas, verts, z, (0, 0), W, H, filt=filt, fs=prog, shaders='new', tone=tone)]
res = run_jobs(jobs, 'reg')
worst = {}
for j in jobs[::2]:
    t = j.name[:-2]
    d = max(np.abs(res[t + '_o']['black'] - res[t + '_n']['black']).max(), np.abs(res[t + '_o']['white'] - res[t + '_n']['white']).max())
    worst[t] = float(d)
for t, d in worst.items():
    report('regression contenu quelconque ' + t, d == 0.0, max_diff=d)
to_png(os.path.join(WORK, 'regress_fpdraw.png'), res['FPDRAW_linear_1.0_n']['black'])
json.dump(RESULTS, open(os.path.join(WORK, 'results_reg.json'), 'w'), indent=1)
