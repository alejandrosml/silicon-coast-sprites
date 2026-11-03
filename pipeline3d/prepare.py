# prepare.py - Silicon Coast, chaîne des monstres 3D, étape 1 : analyse du sprite d'origine (type d'animation 7000).
#   python3 prepare.py <RESREF> <dossier de travail>
# Écrit dans <travail>/origine/ :
#   sequences.json  pour chaque séquence du jeu (WK, SC, SD, GH, DE, TW, A1..A5, SP, CA) : fichier, cycles des
#                   9 directions, table d'images, images uniques, cadres (l, h, cx, cy), empreinte ; séquences
#                   identiques à une autre (« copie_de ») ; images vides (1 x 1) ignorées.
#   masques.npz     silhouettes (créature sans l'ombre) des images uniques, par séquence et direction, alignées sur
#                   l'ancre (cx, cy) dans un canevas commun.
#   vues/           image de repos (SD, 1re image) des directions 0, 2, 4, 6, 8, agrandie x8, sur fond gris clair,
#                   et planche des 5 vues (entrée du dessin de référence).
#   mesures.json    hauteur et largeur (px) au repos de face, luminance moyenne, couleurs dominantes par bande
#                   (tête, tronc, jambes), épaisseurs relatives, vitesse du pied d'appui dans la marche (px/image).
import hashlib
import os
import sys

import numpy as np
from PIL import Image

from commun import SEQ_7000, SRC, DIRS, ecrit_json
from bam import BamV1


def charge(nom):
    return BamV1.load(open(os.path.join(SRC, nom + '.BAM'), 'rb').read())


def rgba(b, fi):
    fr = b.frames[fi]
    p = fr.pix.reshape(fr.h, fr.w)
    pal = b.palette[:, [2, 1, 0]]
    im = np.zeros((fr.h, fr.w, 4), np.uint8)
    im[..., :3] = pal[p]
    crea = (p != b.tidx) & (p != 1)
    ombre = p == 1
    im[..., 3] = np.where(crea, 255, np.where(ombre, 110, 0))
    return im, crea, fr


def main():
    res, travail = sys.argv[1].upper(), os.path.abspath(sys.argv[2])
    out = os.path.join(travail, 'origine')
    os.makedirs(os.path.join(out, 'vues'), exist_ok=True)
    seqs, cache, empreintes = {}, {}, {}
    masques = {}
    for nom_seq, (suf, s) in SEQ_7000.items():
        fichier = res + suf
        if not os.path.exists(os.path.join(SRC, fichier + '.BAM')):
            continue
        b = cache.setdefault(fichier, charge(fichier))
        cyc = []
        h = hashlib.sha1()
        for d in range(DIRS):
            c = 9 * s + d
            if c >= len(b.cycles):
                cyc.append(None)
                continue
            cnt, st = b.cycles[c]
            lk = b.lookup[st:st + cnt]
            vrais = [i for i in lk if b.frames[i].w > 1 or b.frames[i].h > 1]
            if not vrais:
                cyc.append(None)
                continue
            uniq = list(dict.fromkeys(lk))
            cadres = {}
            for i in uniq:
                fr = b.frames[i]
                cadres[str(i)] = [fr.w, fr.h, fr.cx, fr.cy]
                h.update(fr.pix.tobytes()); h.update(bytes([fr.w % 256, fr.h % 256]))
                im, crea, _ = rgba(b, i)
                masques['%s_d%d_f%d' % (nom_seq, d, i)] = crea
                masques['%s_d%d_f%d_ancre' % (nom_seq, d, i)] = np.array([fr.cx, fr.cy])
            cyc.append(dict(cycle=c, table=lk, uniques=uniq, cadres=cadres))
        if all(x is None for x in cyc):
            continue
        emp = h.hexdigest()
        seqs[nom_seq] = dict(fichier=fichier, seq=s, cycles=cyc, empreinte=emp,
                             n_images=max(len(x['table']) for x in cyc if x),
                             n_uniques=max(len(x['uniques']) for x in cyc if x))
        if emp in empreintes:
            seqs[nom_seq]['copie_de'] = empreintes[emp]
        else:
            empreintes[emp] = nom_seq
    np.savez_compressed(os.path.join(out, 'masques.npz'), **masques)

    # ---- vues de repos (SD, 1re image ; sinon SC ou WK)
    base = next(k for k in ('SD', 'SC', 'WK') if k in seqs)
    b = cache[seqs[base]['fichier']]
    vues = []
    for d in (0, 2, 4, 6, 8):
        cy = seqs[base]['cycles'][d]
        im, crea, fr = rgba(b, cy['table'][0])
        Image.fromarray(im, 'RGBA').save(os.path.join(out, 'vues', 'brut_d%d.png' % d))
        z = 8
        big = Image.fromarray(im, 'RGBA').resize((fr.w * z, fr.h * z), Image.NEAREST)
        big = big.resize((fr.w * z, fr.h * z), Image.LANCZOS)
        fond = Image.new('RGBA', big.size, (205, 205, 205, 255))
        a = np.array(big)
        a[..., 3] = np.where(a[..., 3] > 200, 255, 0)      # sans l'ombre
        fond.alpha_composite(Image.fromarray(a, 'RGBA'))
        fond.convert('RGB').save(os.path.join(out, 'vues', 'vue_d%d.png' % d))
        vues.append(fond.convert('RGB'))
    H = max(v.height for v in vues)
    pl = Image.new('RGB', (sum(v.width for v in vues) + 40 * (len(vues) - 1), H), (205, 205, 205))
    x = 0
    for v in vues:
        pl.paste(v, (x, H - v.height)); x += v.width + 40
    pl.save(os.path.join(out, 'vues', 'planche_vues.png'))

    # ---- mesures au repos de face
    im, crea, fr = rgba(b, seqs[base]['cycles'][0]['table'][0])
    ys, xs = np.nonzero(crea)
    haut = int(ys.max() - ys.min() + 1)
    larg = int(xs.max() - xs.min() + 1)
    rgb = im[..., :3][crea].astype(np.float64) / 255.0
    lum = float((0.2126 * rgb[:, 0] + 0.7152 * rgb[:, 1] + 0.0722 * rgb[:, 2]).mean())
    bandes = {}
    y0 = ys.min()
    for nom_b, (a0, a1) in {'tete': (0.0, 0.18), 'tronc': (0.18, 0.55), 'jambes': (0.55, 1.0)}.items():
        sel = (ys >= y0 + a0 * haut) & (ys < y0 + a1 * haut)
        px = im[ys[sel], xs[sel], :3].astype(np.float64)
        bandes[nom_b] = [round(float(v), 1) for v in np.median(px, axis=0)] if len(px) else None
    largeurs = []
    for r in range(ys.min(), ys.max() + 1):
        row = crea[r]
        largeurs.append(int(row.sum()))
    # vitesse du pied d'appui dans la marche, vue de profil (direction 4) : déplacement du point le plus bas
    vit = None
    if 'WK' in seqs and seqs['WK']['cycles'][4]:
        bw = cache[seqs['WK']['fichier']]
        cyw = seqs['WK']['cycles'][4]
        xs_bas = []
        for i in cyw['table']:
            _, cr, f2 = rgba(bw, i)
            yy, xx = np.nonzero(cr)
            if len(yy) == 0:
                continue
            bas = yy >= yy.max() - 2
            xs_bas.append(float(np.median(xx[bas]) - f2.cx))
        if len(xs_bas) > 2:
            dx = np.diff(xs_bas)
            vit = float(np.median(np.abs(dx[np.abs(dx) < 8]))) if np.any(np.abs(dx) < 8) else None
    mes = dict(resref=res, base=base, hauteur_px=haut, largeur_px=larg, luminance=lum, bandes_rgb=bandes,
               largeurs_lignes=largeurs, vitesse_pied_px=vit, ancre_repos=[fr.cx, fr.cy],
               cadre_repos=[fr.w, fr.h])
    ecrit_json(os.path.join(out, 'mesures.json'), mes)
    ecrit_json(os.path.join(out, 'sequences.json'), seqs)
    resume = {k: (v['n_images'], v['n_uniques'], v.get('copie_de')) for k, v in seqs.items()}
    print(res, 'hauteur', haut, 'px, luminance %.3f' % lum, 'séquences', resume)


if __name__ == '__main__':
    main()
