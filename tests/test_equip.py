# test_equip.py - personnages equipes (corps + arme + bouclier + casque) au format SC-HD multi-calques.
# Compare, pour des images reelles de BG2:EE (classe de taille L), le rendu moteur simule des calques
# d'origine (shaders d'origine) et des calques HD canoniques (shaders Silicon Coast).
import sys, os, json, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
from bam import BamV1
import schd
from engine_sim import Atlas, realize_palette, render_character, Creature, layer_order
from scene import Job, run_jobs, to_png, WORK
from test_suite import report, RESULTS, masks_iou, centroid, noise_surface

SP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(SP, 'equip', 'src_L')
HDD = os.path.join(SP, 'equip', 'hd_L')
TABLE = json.load(open(os.path.join(SP, 'equip', 'canon_L.json')))['table']
rng = np.random.default_rng(11)
_cache = {}

def bam(dirn, name):
    key = (dirn, name)
    if key not in _cache:
        _cache[key] = BamV1.load(open(os.path.join(dirn, name + '.BAM'), 'rb').read())
    return _cache[key]

def frame_at(b, c, f):
    cnt, start = b.cycles[c]
    return b.frames[b.lookup[start + f]]

def layers_for(files, c, f, direction, hd, helmet_on_top=True):
    """files : dict role -> resref ; renvoie les calques (Creature) dans l'ordre de dessin du moteur."""
    out = []
    for role in layer_order(direction, helmet_on_top=helmet_on_top):
        if role not in files:
            continue
        b = bam(HDD if hd else SRC, files[role])
        fr = frame_at(b, c, f)
        out.append(Creature(fr.pix, fr.cx, fr.cy, realize_palette(b.palette), b.tidx))
    return out

def build_multi(chars, neighbors=True):
    """chars : liste de (calques, ancre, miroir, murs, marge)."""
    at = Atlas()
    verts = []; infos = []
    for layers, anchor, mir, walls, margin in chars:
        if neighbors:
            noise_surface(at, *rng.integers(10, 90, 2))
        v, info = render_character(at, layers, anchor, mir, walls, margin)
        verts += v; infos.append(info)
    if neighbors:
        noise_surface(at, *rng.integers(10, 90, 2))
    return at.img.copy(), verts, infos

def view(anchor, z, W, H, dy=40):
    return (anchor[0] - W / (2 * z), anchor[1] - dy - H / (2 * z))

# ensembles d'equipement : (groupe, fichier du corps pour la sequence, equipements)
SETS = [
    ('G1', 0, dict(body='CHMB1G11', weapon='WQLAXG1', shield='WQLD2G1', helmet='WQLH1G1')),   # sequence 0
    ('G1', 7, dict(body='CHMB1G17', weapon='WQLS1G1', shield='WQLD3G1', helmet='WQLH3G1')),   # sequence 7
    ('A1', 0, dict(body='CHMB1A1', weapon='WQLAXA1', shield='WQLD2A1', helmet='WQLH1A1')),
    ('A2', 0, dict(body='CHMB3A2', weapon='WQLHBA2', helmet='WQLJ2A2')),                       # arme a deux mains
    ('SA', 0, dict(body='CHMF4SA', weapon='WQLBWSA', helmet='WQLH4SA')),                       # arc
    ('A7', 0, dict(body='CHMW2A7', weapon='WQLS1A7', shield='WQLS2OA7')),                      # deux armes
]

def cases():
    out = []
    for grp, seq, files in SETS:
        files = {r: n for r, n in files.items() if os.path.exists(os.path.join(SRC, n + '.BAM'))}
        bb = bam(SRC, files['body'])
        for direction in (0, 2, 4, 6, 8, 10, 12, 14):
            d = 16 - direction if direction > 8 else direction
            c = seq * 9 + d
            cnt = bb.cycles[c][0]
            f = int(rng.integers(0, cnt))
            if f'{grp}/{c}/{f}' not in TABLE:
                continue
            out.append(dict(grp=grp, c=c, f=f, direction=direction, mir=direction > 8, files=files))
    return out

def expected_hd(files, c, f, direction, z4):
    """image attendue a z=4 : composite des images HD des calques (premultiplie, ombre a 0,5)."""
    grp = None
    layers = []
    for role in layer_order(direction):
        if role not in files: continue
        b = bam(SRC, files[role]); fr = frame_at(b, c, f)
        layers.append((b, fr))
    from canon import classify
    grp = classify(files['body'])[1]
    g = schd.Geometry(*TABLE[f'{grp}/{c}/{f}'], 4)
    acc = np.zeros((4 * g.h, 4 * g.w, 3)); cov = np.zeros((4 * g.h, 4 * g.w))
    for b, fr in layers:
        cv = schd.canvas_1x(fr.pix, fr.cx, fr.cy, g, b.tidx)
        hd = schd.upscale_canvas(cv, 4, b.tidx)
        pal = realize_palette(b.palette).astype(np.float64) / 255.0
        m = hd != b.tidx
        rel = np.where(hd == 1, 0.5, 1.0)
        acc[m] = pal[hd][m][:, :3] * rel[m][:, None]
        cov[m] = rel[m]
    return acc, cov, g

def main():
    t0 = time.time()
    W = H = 360
    anchor = (300, 300)
    jobs = []; meta = []
    for i, cs in enumerate(cases()):
        lv = layers_for(cs['files'], cs['c'], cs['f'], cs['direction'], hd=False)
        lh = layers_for(cs['files'], cs['c'], cs['f'], cs['direction'], hd=True)
        for z in (1.0, 2.0, 3.34):
            cam = view(anchor, z, W, H)
            av, vv, _ = build_multi([(lv, anchor, cs['mir'], (), 2)])
            ah, vh, ih = build_multi([(lh, anchor, cs['mir'], (), 2)])
            tag = f'e{i}_{z}'
            jobs += [Job(tag + '_vo', av, vv, z, cam, W, H, shaders='orig'),
                     Job(tag + '_vn', av, vv, z, cam, W, H, shaders='new'),
                     Job(tag + '_hn', ah, vh, z, cam, W, H, shaders='new')]
            meta.append((tag, cs, z, ih[0]))
    # texel exact a z = 4 (camera alignee) sur 4 cas, miroir compris
    z4 = 4.0; W4 = H4 = 720
    exact = []
    for i, cs in enumerate(cases()[:: max(1, len(cases()) // 6)][:6]):
        lh = layers_for(cs['files'], cs['c'], cs['f'], cs['direction'], hd=True)
        cam4 = (float(np.floor(anchor[0] - W4 / (2 * z4))), float(np.floor(anchor[1] - 40 - H4 / (2 * z4))))
        ah, vh, ih = build_multi([(lh, anchor, cs['mir'], (), 2)], neighbors=True)
        jobs.append(Job(f'x{i}', ah, vh, z4, cam4, W4, H4))
        exact.append((f'x{i}', cs, cam4))
    res = run_jobs(jobs, 'equip')
    print('rendu', round(time.time() - t0, 1), 's', len(jobs), 'scenes')

    worst_reg = 0.0; ious = []; cds = []; sheet = []
    for tag, cs, z, info in meta:
        vo, vn, hn = res[tag + '_vo'], res[tag + '_vn'], res[tag + '_hn']
        reg = max(np.abs(vo['black'] - vn['black']).max(), np.abs(vo['white'] - vn['white']).max())
        worst_reg = max(worst_reg, reg)
        iou = masks_iou(vo['alpha'], hn['alpha'])
        cd = np.abs(centroid(vo['alpha']) - centroid(hn['alpha'])) / z
        ious.append(iou); cds.append(cd.max())
        if iou < 0.9 or cd.max() > 1.0:
            print('  douteux', tag, cs['grp'], cs['c'], cs['f'], 'dir', cs['direction'], round(iou, 3), cd.round(2))
        if z == 3.34 and len(sheet) < 12:
            sheet.append(np.concatenate([vo['black'] * 0.5 + 0.5 * vo['white'], hn['black'] * 0.5 + 0.5 * hn['white']], axis=1))
    report('equipes: regression (calques ordinaires, nouveaux vs anciens shaders)', worst_reg == 0.0, max_diff=worst_reg)
    report('equipes: silhouette HD composee ~ silhouette d origine', min(ious) > 0.9, min_iou=min(ious), mean_iou=float(np.mean(ious)), n=len(ious))
    report('equipes: centre de masse (px du monde)', max(cds) < 1.0, max_offset=max(cds))
    worst = 0.0
    for tag, cs, cam4 in exact:
        acc, cov, g = expected_hd(cs['files'], cs['c'], cs['f'], cs['direction'], z4)
        if cs['mir']:
            acc = acc[:, ::-1]; cov = cov[:, ::-1]
            sx0 = anchor[0] - (g.w - g.L)
        else:
            sx0 = anchor[0] - g.L
        sy0 = anchor[1] - g.T
        sx = int(round((sx0 - cam4[0]) * z4)); sy = int(round((sy0 - cam4[1]) * z4))
        got = res[tag]['black'][sy:sy + 4 * g.h, sx:sx + 4 * g.w]
        d = np.abs(got - acc).max()
        worst = max(worst, d)
        if d > 2.5 / 255:
            print('  ecart texel', tag, cs['grp'], cs['c'], cs['f'], cs['direction'], round(d, 4))
    report('equipes: texel exact a z=4 (composite HD des calques, miroir compris)', worst < 2.5 / 255, max_diff=worst, n=len(exact))
    if sheet:
        rows = [np.concatenate(sheet[i:i + 3], axis=1) for i in range(0, len(sheet) - len(sheet) % 3, 3)]
        to_png(os.path.join(WORK, 'suite_equipes.png'), np.concatenate(rows, axis=0))
    json.dump(RESULTS, open(os.path.join(WORK, 'results_equip.json'), 'w'), indent=1)
    print('temps', round(time.time() - t0, 1), 's')

if __name__ == '__main__':
    main()
