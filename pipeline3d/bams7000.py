# bams7000.py - Silicon Coast, chaîne des monstres 3D, étape 8 : rendus -> BAM HD (palette 88-255 refaite, tramage)
# pour un monstre de type 7000. Adapté de make_bams.py (ogre).
#   python3 bams7000.py <RESREF> <travail>
# Rendus : <travail>/rendu/images/<FICHIER>_c<cycle>_f<i>.png (+ _mask.png, .json : cadre et ancre de bl_anim,
# _ombre.png : passe d'ombre seule). Frise de chaque cycle : mouvements/choix.json (n images rendues ; « motif » :
# la frise d'origine gardée pour une séquence à motif répété ou à image unique). Les séquences copiées d'une autre
# dans l'original (A4 = A1...) reprennent les rendus de la séquence d'origine. Les cycles non rendus (séquences que
# le moteur ne lit pas dans ce fichier) gardent l'original agrandi x4.
# Couleur : gain par canal (rouge, vert, bleu) qui ramène la teinte médiane de la 1re image de l'attente, de face,
# à celle de l'original (règles de fidélité, 4) ; ombre : pixels de la passe d'ombre au-dessus du seuil calé par
# lumiere.py -> indice 1 (ombre du jeu).
# Sorties : <travail>/hd/<FICHIER>.BAM (indices) et <travail>/hdF/<FICHIER>.BAM (sous-teintes, nulles avec le
# tramage), <travail>/hd/fichiers.txt (liste pour sc_convert / sc_verify), <travail>/hd/couleur.json.
import hashlib
import json
import os
import sys

import numpy as np
from PIL import Image

from commun import K, SEQ_7000, SRC, ecrit_json, lit_json
from bam import BamV1, Frame
import hd_palette as hp

BAYER8 = (np.array([[0, 32, 8, 40, 2, 34, 10, 42], [48, 16, 56, 24, 50, 18, 58, 26],
                    [12, 44, 4, 36, 14, 46, 6, 38], [60, 28, 52, 20, 62, 30, 54, 22],
                    [3, 35, 11, 43, 1, 33, 9, 41], [51, 19, 59, 27, 49, 17, 57, 25],
                    [15, 47, 7, 39, 13, 45, 5, 37], [63, 31, 55, 23, 61, 29, 53, 21]]) + 0.5) / 64.0


def load_png(p):
    a = np.array(Image.open(p))
    return a.astype(np.float64) / (65535.0 if a.dtype != np.uint8 else 255.0)


def alpha_de(a):
    return a[..., 3] if a.ndim == 3 and a.shape[2] == 4 else a[..., 0] if a.ndim == 3 else a


def main():
    res, trav = sys.argv[1].upper(), os.path.abspath(sys.argv[2])
    seqs = lit_json(os.path.join(trav, 'origine', 'sequences.json'))
    mes = lit_json(os.path.join(trav, 'origine', 'mesures.json'))
    choix = lit_json(os.path.join(trav, 'mouvements', 'choix.json'))
    lum = lit_json(os.path.join(trav, 'rendu', 'lumiere.json'), {})
    seuil_ombre = float(lum.get('seuil_ombre', 0.3))
    rdir = os.path.join(trav, 'rendu', 'images')
    out_hd, out_f = os.path.join(trav, 'hd'), os.path.join(trav, 'hdF')
    os.makedirs(out_hd, exist_ok=True); os.makedirs(out_f, exist_ok=True)
    fichiers = sorted({res + suf for suf, _ in SEQ_7000.values() if os.path.exists(os.path.join(SRC, res + suf + '.BAM'))})
    # cycles rendus : (fichier, cycle) -> (fichier source des rendus, cycle source, n images rendues, frise)
    rendus, manque = {}, []
    for s, info in seqs.items():
        src_s = info.get('copie_de') or s
        c = choix.get(src_s, {})
        if 'n' not in c or 'fichier' not in c:
            continue
        n = int(c['n']); motif = c.get('motif') or list(range(n))
        src_info = seqs[src_s]
        for d in range(9):
            cy, cys = info['cycles'][d], src_info['cycles'][d]
            if not cy or not cys:
                continue
            ok = all(os.path.exists(os.path.join(rdir, '%s_c%d_f%d_mask.png' % (src_info['fichier'], cys['cycle'], f)))
                     for f in range(n))
            if ok:
                rendus[(info['fichier'], cy['cycle'])] = (src_info['fichier'], cys['cycle'], n, tuple(motif))
            else:
                manque.append((s, d))
    print('cycles rendus', len(rendus), 'incomplets', manque[:12], flush=True)

    def charge(fs, cs, f):
        base = os.path.join(rdir, '%s_c%d_f%d' % (fs, cs, f))
        col = load_png(base + '.png'); msk = load_png(base + '_mask.png')
        bx = json.load(open(base + '.json'))
        obj = alpha_de(msk) > 0.5
        om = None
        if os.path.exists(base + '_ombre.png'):
            om = alpha_de(load_png(base + '_ombre.png'))
        return col, obj, om, (int(round(bx['cx'] * K)), int(round(bx['cy'] * K)))

    # 0) correction de couleur : médiane RGB de la créature (1re image de l'attente, de face) contre l'original
    gains = np.ones(3)
    base_s = choix.get('_global', {}).get('base', 'SD')
    bi = seqs.get(base_s, {})
    if bi and bi['cycles'][0]:
        p = os.path.join(rdir, '%s_c%d_f0' % (bi['fichier'], bi['cycles'][0]['cycle']))
        if os.path.exists(p + '.png'):
            col, obj, _, _ = charge(bi['fichier'], bi['cycles'][0]['cycle'], 0)
            med_r = np.median(col[..., :3][obj], axis=0) * 255.0
            ref = np.median(np.array([v for v in mes['bandes_rgb'].values() if v]), axis=0)
            gains = np.clip(ref / np.maximum(med_r, 1.0), 0.7, 1.4)
            # la luminosité est déjà calée par la lumière (lumiere.py) : les gains gardent la luminance de la teinte
            Yw = np.array([0.2126, 0.7152, 0.0722])
            gains = gains * float(Yw @ med_r) / max(float(Yw @ (med_r * gains)), 1e-6)
    ecrit_json(os.path.join(out_hd, 'couleur.json'), dict(gains_rgb=[round(float(g), 4) for g in gains],
                                                         seuil_ombre=seuil_ombre))
    print('gains de couleur', np.round(gains, 3).tolist(), flush=True)

    # 1) palette : échantillons de toutes les images
    rng = np.random.default_rng(1)
    uniques = sorted({(fs, cs, n) for fs, cs, n, _ in rendus.values()})
    toutes = [(fs, cs, f) for fs, cs, n in uniques for f in range(n)]
    samples = []
    for fs, cs, f in toutes[::max(1, len(toutes) // 150)]:
        col, obj, _, _ = charge(fs, cs, f)
        px = np.clip(col[..., :3][obj] * gains, 0, 1)
        if len(px):
            samples.append(px[rng.choice(len(px), min(len(px), 1500), replace=False)])
    fam_ab, shades, pal88 = hp.build_palette(np.concatenate(samples))
    # 2) images I (indices) et F (sous-teintes)
    I_, F_, A_ = {}, {}, {}
    n_ombre = 0
    for k, (fs, cs, f) in enumerate(toutes):
        col, obj, om, anc = charge(fs, cs, f)
        I = np.zeros(obj.shape, np.uint8); F = np.zeros(obj.shape, np.uint8)
        if obj.any():
            qi, qf = hp.quantize(np.clip(col[..., :3][obj] * gains, 0, 1), fam_ab, shades)
            ys, xs = np.nonzero(obj)
            thr = BAYER8[ys % 8, xs % 8]
            step = (qf / 8.0 > thr) & (((qi.astype(int) - hp.FIXED0) % hp.NSH) < hp.NSH - 1)
            qi = (qi.astype(int) + step).astype(np.uint8)
            I[obj] = qi
        if om is not None and om.shape == obj.shape:
            ombre = (~obj) & (om > seuil_ombre)
        else:
            ombre = (~obj) & (col[..., 3] > 0.25)
        I[ombre] = 1
        n_ombre += int(ombre.sum())
        I_[(fs, cs, f)] = I; F_[(fs, cs, f)] = F; A_[(fs, cs, f)] = anc
        if k % 200 == 0:
            print('images', k, '/', len(toutes), flush=True)
    # 3) BAM : cycles de l'original ; cycles rendus avec leur frise ; palette 88-255 refaite
    for name in fichiers:
        b = BamV1.load(open(os.path.join(SRC, name + '.BAM'), 'rb').read())
        pal = b.palette.copy()
        pal[88:256, 0] = pal88[:, 2]; pal[88:256, 1] = pal88[:, 1]; pal[88:256, 2] = pal88[:, 0]; pal[88:256, 3] = 0
        for which, store, dest in (('I', I_, out_hd), ('F', F_, out_f)):
            out = BamV1(); out.palette = pal.copy(); out.tidx = b.tidx
            frames, cycles, lookup, dedup = [], [], [], {}
            for c, (cnt, start) in enumerate(b.cycles):
                r = rendus.get((name, c))
                if r:
                    fs, cs, n, motif = r
                    idx_rendu = []
                    for f in range(n):
                        key = (fs, cs, f)
                        pix = np.ascontiguousarray(store[key]); ax, ay = A_[key]
                        h = (hashlib.md5(pix.tobytes()).hexdigest(), pix.shape, ax, ay)
                        if h not in dedup:
                            frames.append(Frame(pix.shape[1], pix.shape[0], ax, ay, pix, True))
                            dedup[h] = len(frames) - 1
                        idx_rendu.append(dedup[h])
                    cycles.append((len(motif), len(lookup)))
                    lookup.extend(idx_rendu[m] for m in motif)
                    continue
                cycles.append((cnt, len(lookup)))
                for f in range(cnt):
                    fi = b.lookup[start + f]
                    fr = b.frames[fi]
                    hk = ('orig', fi, which)
                    if hk not in dedup:
                        pix = (np.kron(fr.pix.reshape(fr.h, fr.w), np.ones((K, K), np.uint8)) if which == 'I'
                               else np.zeros((fr.h * K, fr.w * K), np.uint8))
                        frames.append(Frame(fr.w * K, fr.h * K, fr.cx * K, fr.cy * K, np.ascontiguousarray(pix), True))
                        dedup[hk] = len(frames) - 1
                    lookup.append(dedup[hk])
            out.frames, out.cycles, out.lookup = frames, cycles, lookup
            open(os.path.join(dest, name + '.BAM'), 'wb').write(out.dump(compress=False))
        print('écrit', name, len(b.cycles), 'cycles', flush=True)
    np.save(os.path.join(out_hd, 'palette88.npy'), pal88)
    open(os.path.join(out_hd, 'fichiers.txt'), 'w').write('\n'.join(fichiers) + '\n')
    print('FINI', len(fichiers), 'BAM, pixels d\'ombre', n_ombre, flush=True)


if __name__ == '__main__':
    main()
