#!/usr/bin/env python3
# sc_verify.py - verification par le calcul des BAM convertis par sc_convert.py (Silicon Coast, MIT).
#
# Pour chaque fichier converti, et chaque image de chaque cycle :
#   1. memes cycles et memes nombres d'images que l'original ;
#   2. les images "bouche-trou" (au plus 1 texel) sont restees celles d'origine ;
#   3. reperes : spines (v2) ou blocs (disposition F) decodes comme le ferait le shader, aux coins du quad
#      (v2 : chemin FXBltFromClipped, marges 2 et 8) ou en tout point d'une ligne speciale (F) ;
#   4. geometrie : (w, h) du bloc-sonde = geometrie canonique attendue ; le centre du cadre tombe sur le point
#      d'ancrage d'origine (centre - bloc-sonde = (L, T)) ; dimensions <= 1000 ;
#   5. bloc-sonde opaque (corps) ; image HD = image d'origine agrandie (silhouette et indices de palette) ;
#   6. calques d'une meme surface FX : geometrie identique pour une meme cle (union du moteur = cadre du corps).
#   python3 sc_verify.py <BAM d'origine> <BAM convertis> <groupes.json> <tables.json> [-j N] [--files LISTE]
import sys, os, re, json, time, argparse
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bam import BamV1
import schd
from sc_convert import tight, is_placeholder, table_key, tile_siblings, sibling_frames


def v2_decode_corner(alpha, W, H):
    """decode les spines comme VPDRAW aux 4 coins (lignes 0..7 puis de 8 en 8) ; renvoie les parametres
    trouves a chaque coin ou None."""
    out = []
    for hx in (0, 1):
        for hy in (0, 1):
            x0 = 0 if hx == 0 else W - 1
            d = 1 if hx == 0 else -1
            found = None
            for j in range(136):
                dj = j if j < 8 else 8 + (j - 8) * 8
                y = dj if hy == 0 else H - 1 - dj
                if y < 0 or y >= H:
                    break
                r = schd.read_row(alpha[y], x0, d)
                if r is None:
                    continue
                rexp = dj if hy == 0 else r['H'] - 1 - dj
                if r['r'] != rexp:
                    break
                # controle croise : spine opposee sur la meme ligne
                r2 = schd.read_row(alpha[y], W - 1 if hx == 0 else 0, -d)
                if r2 is None or r2['r'] != r['r']:
                    continue
                found = r
                break
            out.append(found)
    return out


def check_file(args):
    name, src, conv, g, table = args[:5]
    if (args[5] if len(args) > 5 else 'auto') == 'f':
        g = dict(g, path='from')
    errs = []
    st = dict(frames=0, hd=0)
    try:
        b = BamV1.load(open(os.path.join(src, name + '.BAM'), 'rb').read())
        o = BamV1.load(open(os.path.join(conv, name + '.BAM'), 'rb').read())
    except Exception as e:
        return name, ['lecture : %s' % e], st, {}
    t = b.tidx
    if len(b.cycles) != len(o.cycles) or any(a[0] != c[0] for a, c in zip(b.cycles, o.cycles)):
        return name, ['cycles differents'], st, {}
    if o.tidx != t or not (o.palette == b.palette).all():
        errs.append('palette ou indice transparent modifies')
    geoms = {}
    seen = {}
    # tuiles (wyvernes, dragons, Demogorgon) : l'agrandissement voit quelques texels des tuiles voisines
    sibs = [sb for sb in tile_siblings(name, g.get('family'), src)
            if sb.tidx == t and np.array_equal(np.asarray(sb.palette), np.asarray(b.palette))]
    for c, (cnt, s0) in enumerate(b.cycles):
        for f in range(cnt):
            fi = b.lookup[s0 + f]
            if fi >= len(b.frames):
                continue
            st['frames'] += 1
            fr = b.frames[fi]
            of = o.frames[o.lookup[o.cycles[c][1] + f]]
            tb = tight(fr.pix, t)
            if is_placeholder(tb):
                if not (of.w == fr.w and of.h == fr.h and of.cx == fr.cx and of.cy == fr.cy and (of.pix == fr.pix).all()):
                    errs.append(f'{c}/{f}: bouche-trou modifie')
                continue
            key = table_key(g, c, f)
            ext = table.get(key) if key else (fr.cx - tb[0], fr.cy - tb[1], tb[2] - fr.cx, tb[3] - fr.cy)
            if ext is None:
                continue
            # image gardee d'origine (trop grande) ?
            if of.w == fr.w and of.h == fr.h and of.cx == fr.cx and of.cy == fr.cy and (of.pix == fr.pix).all():
                errs.append(f'{c}/{f}: image laissee d origine') if max(ext[0] + ext[2], ext[1] + ext[3]) < 400 else None
                continue
            sk = (id(of.pix), of.cx, of.cy)
            if sk in seen:
                geoms.setdefault(key, set()).add(seen[sk]) if key else None
                st['hd'] += 1
                continue
            alpha = (of.pix != t).astype(np.uint8)
            H, W = of.pix.shape
            if W > schd.MAXDIM or H > schd.MAXDIM:
                errs.append(f'{c}/{f}: cadre trop grand {W}x{H}')
            L, T, R, B = ext
            w, h = L + R, T + B
            if g['path'] == 'from' and g['role'] != 'body':
                # calque d'equipement en disposition F : image HD seule, geometrie de la table
                gg = None
                for kk in range(8, 1, -1):
                    for fl in sorted({0, 1} | {schd.subshade_flags(cc) for cc in (1, 2, 3, 4)} | {schd.subshade_flags(cc, True) for cc in (1, 2, 3, 4)}):
                        g2 = schd.GeometryF(L, T, R, B, kk, flags=fl)
                        if g2.layout is not None and (g2.W, g2.H) == (W, H):
                            gg = g2
                            break
                    if gg is not None:
                        break
                if gg is None:
                    errs.append(f'{c}/{f}: calque {W}x{H} sans geometrie F canonique correspondante')
                    continue
                k, fl, probe, hdo = gg.k, gg.flags, gg.probe, gg.hd
                rows = np.array([schd.f_row(j) for j in range(k * h * schd.planes_grid(fl)[1])])
                hd = of.pix[rows][:, hdo[0]:hdo[0] + k * w * schd.planes_grid(fl)[0]]
                spec_rows = of.pix[0::schd.F_PER]
                probe_ok = not (spec_rows != t).any()       # aucune ligne speciale (reperes) sur un calque
                if not probe_ok:
                    errs.append(f'{c}/{f}: calque d equipement avec des texels sur les lignes speciales')
                    probe_ok = True
            elif g['path'] == 'from':
                bad = 0
                for y in range(0, H, schd.F_PER):
                    for x0 in range(0, W, schd.F_BW):
                        d = schd.f_decode_at(alpha, x0, y)
                        if d is None or d['origin'] != (0, 0) or d['W'] != W or d['H'] != H:
                            bad += 1
                if bad:
                    errs.append(f'{c}/{f}: {bad} blocs F illisibles')
                d = schd.f_decode_at(alpha, 0, 0)
                if d is None:
                    continue
                k, fl, probe, hdo = d['k'], d['flags'], d['probe'], d['hd']
                if (d['w'], d['h']) != (w, h):
                    errs.append(f'{c}/{f}: geometrie {d["w"]}x{d["h"]} au lieu de {w}x{h}')
                rows = np.array([schd.f_row(j) for j in range(k * h * schd.planes_grid(fl)[1])])
                hd = of.pix[rows][:, hdo[0]:hdo[0] + k * w * schd.planes_grid(fl)[0]]
                probe_ok = True
                pr = of.pix[probe[1]:probe[1] + h, probe[0]:probe[0] + w]
                spec = (np.arange(probe[1], probe[1] + h) % schd.F_PER) == 0
                if (pr[~spec] == t).any():
                    probe_ok = False
            else:
                if g['role'] == 'body':
                    cs = v2_decode_corner(alpha, W, H)
                    if any(x is None for x in cs):
                        errs.append(f'{c}/{f}: spines illisibles a {sum(x is None for x in cs)} coin(s)')
                        continue
                    d = cs[0]
                    if d['W'] != W or d['H'] != H or (d['w'], d['h']) != (w, h):
                        errs.append(f'{c}/{f}: geometrie {d["w"]}x{d["h"]} au lieu de {w}x{h}')
                    k, fl, probe, hdo = d['k'], d['flags'], d['probe'], d['hd']
                    pr = of.pix[probe[1]:probe[1] + h, probe[0]:probe[0] + w]
                    probe_ok = not (pr == t).any()
                else:
                    # calque d'equipement : meme geometrie que le corps, deduite de la table
                    gg = None
                    for kk in range(8, 1, -1):
                        gg = schd.Geometry(L, T, R, B, kk)
                        if gg.layout is not None and (gg.W, gg.H) == (W, H):
                            break
                        gg = None
                    if gg is None:
                        # sous-teintes : chercher aussi avec les drapeaux
                        for kk in range(8, 1, -1):
                            for cols in (1, 2, 3, 4):
                                g2 = schd.Geometry(L, T, R, B, kk, flags=schd.subshade_flags(cols))
                                if g2.layout is not None and (g2.W, g2.H) == (W, H):
                                    gg = g2
                    if gg is None:
                        errs.append(f'{c}/{f}: calque {W}x{H} sans geometrie canonique correspondante')
                        continue
                    k, fl, probe, hdo = gg.k, gg.flags, gg.probe, gg.hd
                    probe_ok = True
                cols, nrows = schd.planes_grid(fl)
                hd = of.pix[hdo[1]:hdo[1] + nrows * k * h, hdo[0]:hdo[0] + cols * k * w]
            if not probe_ok:
                errs.append(f'{c}/{f}: bloc-sonde non opaque')
            # centre = ancrage
            if (of.cx - probe[0], of.cy - probe[1]) != (L, T):
                errs.append(f'{c}/{f}: centre {of.cx - probe[0]},{of.cy - probe[1]} au lieu de {L},{T}')
            # image HD : silhouette et indices (plan I si sous-teintes)
            I = hd[:k * h, :k * w]
            cv = schd.canvas_1x(fr.pix, fr.cx, fr.cy, schd.Geometry(L, T, R, B, 1, layout=1), t)
            m1 = cv != t
            mk = (I != t).reshape(h, k, w, k).any(axis=(1, 3))
            # l'image HD couvre l'original (rappel) et ne deborde pas de plus d'un pixel (precision)
            md = m1.copy()
            md[1:] |= m1[:-1]; md[:-1] |= m1[1:]; md[:, 1:] |= m1[:, :-1]; md[:, :-1] |= m1[:, 1:]
            rec = (m1 & mk).sum() / max(1, m1.sum())
            pre = (mk & md).sum() / max(1, mk.sum())
            if (rec < 0.9 or pre < 0.995) and m1.sum() > 20:
                errs.append(f'{c}/{f}: silhouette HD differente (couverture {rec:.2f}, debordement {1 - pre:.3f})')
            allowed = set(np.unique(cv[cv != t]).tolist())
            for sb, sfr in sibling_frames(sibs, c, f):
                allowed |= set(np.unique(sfr.pix[sfr.pix != sb.tidx]).tolist())
            extra = set(np.unique(I[I != t]).tolist()) - allowed
            if extra and fl & schd.FLAG_SUBSHADE == 0:
                errs.append(f'{c}/{f}: indices absents de l image d origine {sorted(extra)[:5]}')
            seen[sk] = (W, H, of.cx, of.cy)
            if key:
                geoms.setdefault(key, set()).add((W, H, of.cx, of.cy))
            st['hd'] += 1
    errs = [e for e in errs if e]
    return name, errs, st, {k: sorted(v) for k, v in geoms.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src'); ap.add_argument('conv'); ap.add_argument('groups'); ap.add_argument('tables')
    ap.add_argument('-j', type=int, default=os.cpu_count() or 1)
    ap.add_argument('--files', default=None)
    ap.add_argument('--report', default=None)
    ap.add_argument('--layout', choices=['auto', 'f'], default='auto')
    a = ap.parse_args()
    groups = json.load(open(a.groups)); table = json.load(open(a.tables))['table']
    names = sorted(os.path.splitext(n)[0].upper() for n in os.listdir(a.conv) if n.upper().endswith('.BAM'))
    if a.files:
        want = set(l.strip().upper() for l in open(a.files) if l.strip()); names = [n for n in names if n in want]
    names = [n for n in names if n in groups]
    work = [(n, a.src, a.conv, groups[n], table, a.layout) for n in names]
    t0 = time.time()
    if a.j > 1:
        from multiprocessing import Pool
        with Pool(a.j) as p:
            res = list(p.imap_unordered(check_file, work, chunksize=2))
    else:
        res = [check_file(w) for w in work]
    allg = {}
    nerr = 0; frames = 0; hdn = 0
    bad_files = []
    for name, errs, st, geoms in sorted(res):
        frames += st['frames']; hdn += st['hd']
        if errs:
            nerr += len(errs); bad_files.append((name, errs[:5], len(errs)))
        for k, v in geoms.items():
            allg.setdefault(k, set()).update(map(tuple, v))
    # 6. calques d'une meme surface : une seule geometrie par cle
    multi = {k: v for k, v in allg.items() if len(v) > 1}
    rep = dict(files=len(res), frames=frames, hd_frames=hdn, errors=nerr, bad_files=len(bad_files),
               keys=len(allg), keys_with_several_geometries=len(multi), seconds=round(time.time() - t0, 1),
               examples=bad_files[:20], multi_examples=[(k, sorted(v)) for k, v in list(multi.items())[:10]])
    if a.report:
        json.dump(rep, open(a.report, 'w'), indent=1)
    print(json.dumps({k: v for k, v in rep.items() if k not in ('examples', 'multi_examples')}))
    for name, errs, n in bad_files[:20]:
        print(' ', name, n, errs)
    for k, v in list(multi.items())[:10]:
        print('  plusieurs geometries', k, sorted(v))


if __name__ == '__main__':
    main()
