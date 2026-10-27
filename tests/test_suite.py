# test_suite.py - batterie de tests hors ligne des shaders sprites HD (SC-HD v2)
import sys, os, time, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from bam import BamV1
import schd
from engine_sim import Atlas, realize_palette, render_creature, Creature
from scene import Job, run_jobs, to_png, WORK

HERE = os.path.dirname(os.path.abspath(__file__))
rng = np.random.default_rng(7)
RESULTS = []

def report(name, ok, **kw):
    RESULTS.append(dict(name=name, ok=bool(ok), **{k: (float(v) if isinstance(v, (np.floating, float)) else v) for k, v in kw.items()}))
    print(('PASS ' if ok else 'FAIL ') + name, {k: (round(float(v), 4) if isinstance(v, (float, np.floating)) else v) for k, v in kw.items()})

def load(name):
    return BamV1.load(open(os.path.join(HERE, name), 'rb').read())

def hd_of(b, fr, k=4):
    mark = schd.pick_mark(b.palette, b.tidx)
    flags = schd.FLAG_PALALPHA if schd.palette_has_alpha(b.palette) else 0
    hd = schd.scale4x(fr.pix) if k == 4 else np.kron(fr.pix, np.ones((k, k), np.uint8))
    pix, cx2, cy2, lay = schd.build_frame(fr.pix, hd, fr.cx, fr.cy, k, tidx=b.tidx, mark=mark, flags=flags)
    return pix, cx2, cy2, hd

def noise_surface(at, w, h):
    x, y = at.alloc(w, h)
    at.img[y:y + h, x:x + w] = rng.integers(0, 256, (h, w, 4), dtype=np.uint8)

def build(creatures, neighbors=True):
    """creatures : liste de (Creature, anchor, mirrored, walls, margin). Renvoie atlas, sommets, infos."""
    at = Atlas()
    verts = []; infos = []
    for i, (cr, anchor, mir, walls, margin) in enumerate(creatures):
        if neighbors:
            noise_surface(at, *rng.integers(10, 90, 2))
        v, info = render_creature(at, cr, anchor, mir, walls, margin)
        verts += v; infos.append(info)
    if neighbors:
        noise_surface(at, *rng.integers(10, 90, 2))
    return at.img.copy(), verts, infos

def masks_iou(a, b, t=0.5):
    ma, mb = a > t, b > t
    return (ma & mb).sum() / max(1, (ma | mb).sum())

def centroid(alpha):
    ys, xs = np.nonzero(alpha > 0.5)
    return np.array([xs.mean(), ys.mean()]) if len(xs) else np.array([np.nan, np.nan])

def view(anchor, z, W, H, dy=40):
    return (anchor[0] - W / (2 * z), anchor[1] - dy - H / (2 * z))

# ------------------------------------------------------------------ donnees
bA = load('CHMB1A1.BAM'); bG = load('CHMB1G1.BAM')
palA = realize_palette(bA.palette)
frames = [bA.frames[i] for i in (0, 10, 37, 64, 100)] + [f for f in bG.frames if f.w > 20][:2]
W = H = 360
anchor = (300, 300)

def run_case_set():
    jobs = []; meta = {}
    # 1. geometrie / regression sur plusieurs cadres, miroir, zooms
    for fi, fr in enumerate(frames):
        b = bA if fi < 5 else bG
        pal = realize_palette(b.palette)
        pix, cx2, cy2, _ = hd_of(b, fr)
        for mir in (False, True):
            for z in (1.0, 2.0, 3.34, 5.0):
                cam = view(anchor, z, W, H)
                cv = Creature(fr.pix, fr.cx, fr.cy, pal, b.tidx); ch = Creature(pix, cx2, cy2, pal, b.tidx)
                av, vv, _ = build([(cv, anchor, mir, (), 2)])
                ah, vh, _ = build([(ch, anchor, mir, (), 2)])
                tag = f'g{fi}_{int(mir)}_{z}'
                jobs += [Job(tag + '_vo', av, vv, z, cam, W, H, shaders='orig'),
                         Job(tag + '_vn', av, vv, z, cam, W, H, shaders='new'),
                         Job(tag + '_hn', ah, vh, z, cam, W, H, shaders='new')]
                meta[tag] = dict(fi=fi, mir=mir, z=z)
    return jobs, meta

def eval_geometry(res, meta):
    worst_reg = 0.0; ious = []; cds = []
    for tag, m in meta.items():
        vo, vn, hn = res[tag + '_vo'], res[tag + '_vn'], res[tag + '_hn']
        reg = max(np.abs(vo['black'] - vn['black']).max(), np.abs(vo['white'] - vn['white']).max())
        worst_reg = max(worst_reg, reg)
        iou = masks_iou(vo['alpha'], hn['alpha'])
        cd = np.abs(centroid(vo['alpha']) - centroid(hn['alpha'])) / m['z']   # en pixels du monde
        ious.append(iou); cds.append(cd.max())
        if iou < 0.85 or cd.max() > 1.0:
            print('  geometrie douteuse', tag, round(iou, 3), cd.round(2))
    report('regression: cadres ordinaires identiques (nouveaux vs anciens shaders)', worst_reg == 0.0, max_diff=worst_reg)
    report('geometrie: silhouette HD ~ silhouette d origine', min(ious) > 0.85, min_iou=min(ious), mean_iou=float(np.mean(ious)))
    report('geometrie: centre de masse HD ~ origine (px du monde)', max(cds) < 1.0, max_offset=max(cds))

if __name__ == '__main__':
    t0 = time.time()
    jobs, meta = run_case_set()
    res = run_jobs(jobs, 'geo')
    eval_geometry(res, meta)
    # planche de controle : premier cadre, normal/miroir, zoom 3.34
    rows = []
    for fi in range(len(frames)):
        rows.append(np.concatenate([res[f'g{fi}_0_3.34_vo']['black'] * 0.5 + 0.5 * res[f'g{fi}_0_3.34_vo']['white'],
                                    res[f'g{fi}_0_3.34_hn']['black'] * 0.5 + 0.5 * res[f'g{fi}_0_3.34_hn']['white'],
                                    res[f'g{fi}_1_3.34_hn']['black'] * 0.5 + 0.5 * res[f'g{fi}_1_3.34_hn']['white']], axis=1))
    to_png(os.path.join(WORK, 'suite_geometry.png'), np.concatenate(rows[:4], axis=0))
    json.dump(RESULTS, open(os.path.join(WORK, 'results_geo.json'), 'w'), indent=1)
    print('temps', round(time.time() - t0, 1), 's')
