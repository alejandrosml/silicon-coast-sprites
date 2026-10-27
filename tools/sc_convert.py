#!/usr/bin/env python3
# sc_convert.py - Silicon Coast : conversion des animations de creatures au format SC-HD (sans DLL). Licence MIT.
#
# Chaque image d'origine devient un cadre BAM V1 a l'echelle du moteur qui contient des reperes, un bloc-sonde
# (le sprite d'origine, a sa place) et l'image HD ; les shaders Silicon Coast affichent l'image HD a la taille
# d'origine. Deux dispositions selon le chemin de rendu du moteur :
#   - 'clip' (CInfinity::FXBltFromClipped : personnages, monstres...) : SC-HD v2 (spines sur les cotes) ;
#   - 'from' (CInfinity::FXBltFrom : wyvernes, dragons, Demogorgon) : disposition F (lignes speciales).
# Les calques dessines dans une meme surface FX (corps, armes, casque...) recoivent une geometrie commune
# (tables canoniques).
#
#   python3 sc_convert.py build <BAM d'origine> <groupes.json> <tables.json> <sortie> [options]
# options :
#   --k 4                 facteur HD maximal ; image par image, le plus grand qui tient (cadre <= 1000 x 1000)
#   --up scale4x|kron     agrandisseur de demonstration (palette preservee)
#   --hd DIR              images HD fournies (BAM de memes noms et memes cycles, cadres k fois plus grands,
#                         centres k fois) ; k est alors celui des images fournies
#   --sub DIR             sous-teintes : BAM de memes noms que --hd, valeur F (0..7) par pixel HD
#   --subshade-demo       sous-teintes de demonstration fabriquees ici (x2 lisse, palette preservee)
#   --no-tile-context     tuiles (wyvernes, dragons, Demogorgon) agrandies seules, sans texels des voisines
#   --only REGEX  -j N  --level 6
import sys, os, re, json, glob, zlib, time, argparse
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bam import BamV1, Frame
import schd


def tight(pix, t):
    nz = pix != t
    if not nz.any():
        return None
    ys = np.flatnonzero(nz.any(1)); xs = np.flatnonzero(nz.any(0))
    return int(xs[0]), int(ys[0]), int(xs[-1]) + 1, int(ys[-1]) + 1


def is_placeholder(tb):
    return tb is None or (tb[2] - tb[0]) * (tb[3] - tb[1]) <= 1


def table_key(g, c, f):
    if not g['token']:
        return None
    return '%s/%d/%d' % (g['token'], c, f) if g['mode'] == 'frame' else '%s/%d/*' % (g['token'], c)


# ---------------------------------------------------------------- sous-teintes (bg2hd, Q3M)
def shade_ranges(n=256):
    """succ(I) : teinte suivante dans la meme gamme. Personnages : 4-87 par gammes de 12 ; 88-255 par 8."""
    succ = np.arange(n)
    for start, end, step in ((4, 88, 12), (88, 256, 8)):
        for a in range(start, end, step):
            for i in range(a, min(a + step, end) - 1):
                succ[i] = i + 1
    return succ


SUCC = shade_ranges()


def subshade_demo(cv, k, tidx, palette):
    """x k : indice I = plus proche voisin (palette et gammes preservees), F (0..7) = position du rendu lisse
    entre P[I] et P[succ(I)] (bilineaire des couleurs d'origine). Renvoie les plans I, S, F (k*h, k*w)."""
    h, w = cv.shape
    pal = np.asarray(palette)[:, [2, 1, 0]].astype(np.float64)          # BGRA -> RGB
    I = np.kron(cv, np.ones((k, k), np.uint8))
    opaque = (cv != tidx) & (cv != 1)
    col = pal[cv] * opaque[..., None]
    wsum = opaque.astype(np.float64)
    # bilineaire (centres des pixels) des couleurs opaques, normalise par le poids
    ys = (np.arange(k * h) + 0.5) / k - 0.5
    xs = (np.arange(k * w) + 0.5) / k - 0.5
    y0 = np.clip(np.floor(ys).astype(int), 0, h - 1); y1 = np.clip(y0 + 1, 0, h - 1)
    x0 = np.clip(np.floor(xs).astype(int), 0, w - 1); x1 = np.clip(x0 + 1, 0, w - 1)
    fy = np.clip(ys - np.floor(ys), 0, 1)[:, None]; fx = np.clip(xs - np.floor(xs), 0, 1)[None, :]

    def bil(a):
        A00 = a[y0][:, x0]; A01 = a[y0][:, x1]; A10 = a[y1][:, x0]; A11 = a[y1][:, x1]
        fxx, fyy = (fx[..., None], fy[..., None]) if a.ndim == 3 else (fx, fy)
        return (A00 * (1 - fxx) + A01 * fxx) * (1 - fyy) + (A10 * (1 - fxx) + A11 * fxx) * fyy
    smooth = bil(col) / np.maximum(bil(wsum), 1e-6)[..., None]
    S = SUCC[I].astype(np.uint8)
    pI = pal[I]; pS = pal[S]
    d = pS - pI
    den = (d * d).sum(-1)
    t = np.where(den > 0, ((smooth - pI) * d).sum(-1) / np.maximum(den, 1e-9), 0.0)
    F = np.clip(np.round(t * 8), 0, 7).astype(np.uint8)
    keep = (I == tidx) | (I == 1) | (S == I)
    F[keep] = 0
    S = np.where(keep, I, S).astype(np.uint8)
    return I, S, F


def subshade_planes(I, S, F, tidx):
    """5 plans : I, S, et pour chaque bit b de F un plan d'indices I (bit 0) ou S (bit 1)."""
    out = [I, S]
    for b in range(3):
        out.append(np.where(((F >> b) & 1) == 1, S, I).astype(np.uint8))
    return out


# ---------------------------------------------------------------- tuiles (familles dessinees en morceaux)
# Wyvernes (MonsterQuadrant, 4 quarts), dragons (MonsterMulti, 3x3) et Demogorgon (MonsterMultiNew, 2x2) : chaque
# image est coupee en tuiles jointives, une par fichier, chacune dessinee dans sa propre surface FX. Agrandir
# chaque tuile seule abime les jointures ; on agrandit donc chaque tuile avec, autour, quelques texels des
# tuiles voisines de la meme image (meme cycle, meme image), puis on recoupe.
TILE_RULES = {
    'MonsterMulti': (re.compile(r'^(.{4}\d)([1-9])(\d\d)$'), 9),     # MDR1 + groupe, tuile 1-9, 2 chiffres
    'MonsterQuadrant': (re.compile(r'^(.{4}G\d)([1-4])(E?)$'), 4),   # MWYVG1 + quart 1-4 (+ E)
    'MonsterMultiNew': (re.compile(r'^(.{4}G\d)([1-4])(\d?)$'), 4),  # MDEMG1 + partie 1-4 (+ chiffre)
}
CTX = 2                                    # texels de contexte (Scale2x/4x lisent 1 voisin par passe)
_sib_cache = {}


def tile_siblings(name, family, src_dir):
    rule = TILE_RULES.get(family)
    m = rule[0].match(name) if rule else None
    if not m:
        return []
    out = []
    for p in range(1, rule[1] + 1):
        if str(p) == m.group(2):
            continue
        path = os.path.join(src_dir, m.group(1) + str(p) + m.group(3) + '.BAM')
        if not os.path.exists(path):
            continue
        if path not in _sib_cache:
            if len(_sib_cache) > 64:
                _sib_cache.clear()
            _sib_cache[path] = BamV1.load(open(path, 'rb').read())
        out.append(_sib_cache[path])
    return out


def sibling_frames(sibs, c, f):
    out = []
    for sb in sibs:
        if c < len(sb.cycles) and f < sb.cycles[c][0]:
            fi = sb.lookup[sb.cycles[c][1] + f]
            if fi < len(sb.frames):
                out.append((sb, sb.frames[fi]))
    return out


def context_canvas(cv, g2, sfrs, t, M=CTX):
    """canevas 1x elargi de M texels, avec autour les pixels des tuiles voisines (memes palette et indice
    transparent) ; la tuile elle-meme est recopiee telle quelle au centre."""
    h, w = cv.shape
    e = np.full((h + 2 * M, w + 2 * M), t, np.uint8)
    for sb, sfr in sfrs:
        ox, oy = M + g2.L - sfr.cx, M + g2.T - sfr.cy
        sh, sw = sfr.pix.shape
        x0, y0 = max(0, ox), max(0, oy)
        x1, y1 = min(e.shape[1], ox + sw), min(e.shape[0], oy + sh)
        if x1 > x0 and y1 > y0:
            sub = sfr.pix[y0 - oy:y1 - oy, x0 - ox:x1 - ox]
            reg = e[y0:y1, x0:x1]
            m = sub != sb.tidx
            reg[m] = sub[m]
    e[M:M + h, M:M + w] = cv
    return e


# ---------------------------------------------------------------- conversion d'un fichier
def choose_geometry(path, ext, kmax, flags, kfixed=None):
    """plus grand k qui tient ; avec sous-teintes, grille des 5 plans essayee sur 3, 2, 4 puis 1 colonnes."""
    ks = [kfixed] if kfixed else list(range(kmax, 1, -1))
    variants = [flags]
    if flags & schd.FLAG_SUBSHADE:
        base = flags & ~(3 << 2)
        variants = [base | ((c - 1) << 2) for c in (3, 2, 4, 1)]
    for k in ks:
        for fl in variants:
            g = schd.GeometryF(*ext, k, flags=fl) if path == 'from' else schd.Geometry(*ext, k, flags=fl)
            if g.layout is not None:
                return g
    return None


def place_hd(hdfr, cx, cy, g, k, tidx):
    """place une image HD fournie (centre k*cx, k*cy en coordonnees HD) dans le canevas HD canonique."""
    c = np.full((k * g.h, k * g.w), tidx, np.uint8)
    ox, oy = k * g.L - hdfr.cx, k * g.T - hdfr.cy
    h, w = hdfr.pix.shape
    x0, y0 = max(0, ox), max(0, oy)
    x1, y1 = min(c.shape[1], ox + w), min(c.shape[0], oy + h)
    if x1 > x0 and y1 > y0:
        c[y0:y1, x0:x1] = hdfr.pix[y0 - oy:y1 - oy, x0 - ox:x1 - ox]
    return c


def convert_file(path_in, g, table, opts):
    name = os.path.splitext(os.path.basename(path_in))[0].upper()
    if opts.get('layout', 'auto') == 'f':
        g = dict(g, path='from')               # disposition F pour toutes les familles (essais)
    b = BamV1.load(open(path_in, 'rb').read())
    t = b.tidx
    body = g['role'] == 'body'
    mark = schd.pick_mark(b.palette, t)
    palalpha = schd.palette_has_alpha(b.palette)
    sub = opts.get('subshade_demo') or bool(opts.get('sub'))
    hdb = fb = None
    kfixed = None
    if opts.get('hd'):
        p = os.path.join(opts['hd'], name + '.BAM')
        if os.path.exists(p):
            hdb = BamV1.load(open(p, 'rb').read())
            kfixed = opts.get('hd_k')
            if opts.get('sub'):
                pf = os.path.join(opts['sub'], name + '.BAM')
                fb = BamV1.load(open(pf, 'rb').read()) if os.path.exists(pf) else None
    if sub:
        cols = opts.get('sub_cols', 3)
        flags = schd.subshade_flags(cols, palalpha)
        kfixed = kfixed or 2
    else:
        flags = schd.FLAG_PALALPHA if palalpha else 0
    sibs = []
    if hdb is None and opts.get('src_dir'):
        sibs = [sb for sb in tile_siblings(name, g.get('family'), opts['src_dir'])
                if sb.tidx == t and np.array_equal(np.asarray(sb.palette), np.asarray(b.palette))]
    out = BamV1(); out.palette = b.palette.copy(); out.tidx = t
    frames = []; memo = {}; tb = {}
    cycles = []; lookup = []
    st = dict(hd=0, kept=0, too_big=0, missing=0, positions=0, k={})
    for c, (cnt, start) in enumerate(b.cycles):
        cycles.append((cnt, len(lookup)))
        for f in range(cnt):
            fi = b.lookup[start + f]
            st['positions'] += 1
            if fi >= len(b.frames):
                lookup.append(0); continue
            fr = b.frames[fi]
            pk = id(fr.pix)
            if pk not in tb:
                tb[pk] = tight(fr.pix, t)
            ext = None
            if not is_placeholder(tb[pk]):
                key = table_key(g, c, f)
                if key is None:
                    x0, y0, x1, y1 = tb[pk]
                    ext = (fr.cx - x0, fr.cy - y0, x1 - fr.cx, y1 - fr.cy)
                else:
                    ext = table.get(key)
                    if ext is None:
                        st['missing'] += 1
            hdfr = None
            if ext is not None and hdb is not None:
                if c < len(hdb.cycles) and f < hdb.cycles[c][0]:
                    hdfr = hdb.frames[hdb.lookup[hdb.cycles[c][1] + f]]
            sfrs = sibling_frames(sibs, c, f) if (sibs and ext is not None) else []
            ckey = tuple(id(x[1].pix) for x in sfrs)
            mkey = ('v', fi) if ext is None else ('h', pk, fr.cx, fr.cy, tuple(ext), id(hdfr.pix) if hdfr is not None else 0, ckey)
            if mkey not in memo:
                g2 = None if ext is None else choose_geometry(g['path'], ext, opts['k'], flags, kfixed)
                if ext is not None and g2 is None:
                    st['too_big'] += 1
                if g2 is None:
                    frames.append(Frame(fr.w, fr.h, fr.cx, fr.cy, fr.pix, True)); st['kept'] += 1
                else:
                    k = g2.k
                    if hdfr is not None:
                        hd = place_hd(hdfr, fr.cx, fr.cy, g2, k, t)
                        if sub:
                            Fp = np.zeros_like(hd)
                            if fb is not None:
                                ffr = fb.frames[fb.lookup[fb.cycles[c][1] + f]]
                                Fp = np.clip(place_hd(ffr, fr.cx, fr.cy, g2, k, 0), 0, 7)
                            Sp = SUCC[hd].astype(np.uint8)
                            Sp[(hd == t) | (hd == 1)] = hd[(hd == t) | (hd == 1)]
                            hd = schd.plane_grid_image(subshade_planes(hd, Sp, Fp, t), schd.planes_grid(g2.flags)[0], t)
                    else:
                        cv = schd.canvas_1x(fr.pix, fr.cx, fr.cy, g2, t)
                        M = CTX if sfrs else 0
                        if M:
                            cv = context_canvas(cv, g2, sfrs, t, M)
                        crop = (slice(k * M, k * M + k * g2.h), slice(k * M, k * M + k * g2.w))
                        if sub:
                            I, S, F = subshade_demo(cv, k, t, b.palette)
                            I, S, F = I[crop], S[crop], F[crop]
                            hd = schd.plane_grid_image(subshade_planes(I, S, F, t), schd.planes_grid(g2.flags)[0], t)
                        else:
                            hd = np.ascontiguousarray(schd.upscale_canvas(cv, k, t, opts.get('up', 'scale4x'))[crop])
                    if g['path'] == 'from':
                        pix = schd.build_layer_f(hd, g2, body, tidx=t, mark=mark, shadow_idx=1, flags=g2.flags)
                    else:
                        pix = schd.build_layer(hd, g2, body, tidx=t, mark=mark, shadow_idx=1, flags=g2.flags, bands='vs')
                    cx, cy = g2.center
                    frames.append(Frame(g2.W, g2.H, cx, cy, pix, True)); st['hd'] += 1
                    st['k'][k] = st['k'].get(k, 0) + 1
                memo[mkey] = len(frames) - 1
            lookup.append(memo[mkey])
    if len(frames) > 65535:
        raise ValueError(f'{name}: trop de cadres ({len(frames)})')
    out.frames = frames; out.cycles = cycles; out.lookup = lookup
    return out, st


def _job(args):
    path, g, table, outdir, opts = args
    t0 = time.time()
    name = os.path.basename(path).upper()
    try:
        hb, st = convert_file(path, g, table, opts)
    except Exception as e:
        return name, None, str(e), 0, 0, 0, 0
    raw = hb.dump(compress=False)
    blob = b'BAMCV1  ' + len(raw).to_bytes(4, 'little') + zlib.compress(raw, opts.get('level', 6))
    open(os.path.join(outdir, name), 'wb').write(blob)
    return name, st, None, os.path.getsize(path), len(blob), len(raw), time.time() - t0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['build'])
    ap.add_argument('src'); ap.add_argument('groups'); ap.add_argument('tables'); ap.add_argument('out')
    ap.add_argument('--k', type=int, default=4)
    ap.add_argument('--up', default='scale4x')
    ap.add_argument('--hd', default=None); ap.add_argument('--hd-k', type=int, default=None)
    ap.add_argument('--sub', default=None)
    ap.add_argument('--subshade-demo', action='store_true')
    ap.add_argument('--sub-cols', type=int, default=3)
    ap.add_argument('--only', default=None)
    ap.add_argument('--files', default=None, help='liste de noms (un par ligne)')
    ap.add_argument('-j', type=int, default=os.cpu_count() or 1)
    ap.add_argument('--level', type=int, default=6)
    ap.add_argument('--log', default=None)
    ap.add_argument('--no-tile-context', action='store_true', help='agrandir chaque tuile seule (sans ses voisines)')
    ap.add_argument('--layout', choices=['auto', 'f'], default='auto',
                    help='auto (defaut) : spines v2 pour FXBltFromClipped, disposition F pour FXBltFrom ; f : F partout (essais)')
    a = ap.parse_args()
    groups = json.load(open(a.groups))
    table = json.load(open(a.tables))['table']
    os.makedirs(a.out, exist_ok=True)
    names = sorted(groups)
    if a.only:
        rx = re.compile(a.only, re.I); names = [n for n in names if rx.search(n)]
    if a.files:
        want = set(l.strip().upper() for l in open(a.files) if l.strip()); names = [n for n in names if n in want]
    opts = dict(k=a.k, up=a.up, hd=a.hd, hd_k=a.hd_k, sub=a.sub, subshade_demo=a.subshade_demo,
                sub_cols=a.sub_cols, level=a.level, src_dir=None if a.no_tile_context else a.src, layout=a.layout)
    work = [(os.path.join(a.src, n + '.BAM'), groups[n], table, a.out, opts) for n in names
            if os.path.exists(os.path.join(a.src, n + '.BAM'))]
    t0 = time.time()
    tot = np.zeros(3); errs = []; agg = dict(hd=0, kept=0, too_big=0, missing=0, k={})
    log = open(a.log, 'w') if a.log else sys.stdout
    if a.j > 1:
        from multiprocessing import Pool
        with Pool(a.j) as p:
            res = p.imap_unordered(_job, work, chunksize=2)
            res = list(res)
    else:
        res = [_job(w) for w in work]
    for name, st, err, si, so, raw, dt in sorted(res, key=lambda r: r[0]):
        if err:
            errs.append((name, err)); print(f'{name:14s} ERREUR {err}', file=log); continue
        tot += (si, so, raw)
        for kk in ('hd', 'kept', 'too_big', 'missing'):
            agg[kk] += st[kk]
        for kk, v in st['k'].items():
            agg['k'][kk] = agg['k'].get(kk, 0) + v
        print(f'{name:14s} HD {st["hd"]:5d} gardes {st["kept"]:4d} trop grands {st["too_big"]:3d} hors table {st["missing"]:3d} '
              f'k {st["k"]}  {si/1024:7.0f} Ko -> {so/1024:8.0f} Ko (memoire {raw/1048576:7.1f} Mo) {dt:5.1f} s', file=log)
    summary = (f'total {len(res)} fichiers ({len(errs)} erreurs) : {tot[0]/1048576:.1f} Mo -> {tot[1]/1048576:.1f} Mo sur disque, '
               f'{tot[2]/1048576:.1f} Mo en memoire ; cadres HD {agg["hd"]} (k {agg["k"]}), gardes {agg["kept"]}, '
               f'trop grands {agg["too_big"]}, hors table {agg["missing"]} ; {time.time() - t0:.0f} s')
    print(summary, file=log)
    if log is not sys.stdout:
        print(summary)


if __name__ == '__main__':
    main()
