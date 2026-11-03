# controle.py - Silicon Coast, chaîne des monstres 3D, étape 12 : contrôles chiffrés (règles de fidélité, 7) et
# aperçus. Ne modifie rien : il mesure et montre.
#   python3 controle.py <RESREF> <travail>
# Mesures : taille (hauteur de la 1re image de l'attente, de face : ±3 %), luminance (même image), teinte par bande
# (tête, tronc, jambes : écart dans l'espace Lab), position de la tête par rapport aux hanches de profil (2 pixels),
# recouvrement de l'ombre, vérification SC-HD (sc_verify : 0 erreur), images rendues et frises.
# Sorties : <travail>/controle/rapport.json, rapport.md, planche_mouvements.png (silhouettes original | 3D),
# <SEQ>.gif (original x4 | nouveau HD, directions 0, 2, 4 et 6, au rythme du jeu), comparaison.png.
import json
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from commun import K, NOMS_SEQ, SRC, ecrit_json, lit_json
from bam import BamV1

try:
    FONT = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 14)
    FONT_P = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 11)
    FONT_G = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 30)
except Exception:  # noqa: BLE001
    FONT = FONT_P = FONT_G = ImageFont.load_default()
FOND = np.array([58, 54, 46], np.float32)


def rgb_palette(b):
    return np.array(b.palette)[:, [2, 1, 0]].astype(np.float32)


def rgba_image(b, fr):
    pix = fr.pix.reshape(fr.h, fr.w)
    rgb = rgb_palette(b)
    out = np.zeros(pix.shape + (4,), np.float32)
    out[..., :3] = rgb[pix]; out[..., 3] = 255
    out[pix == b.tidx, 3] = 0
    sh = pix == 1
    out[sh, :3] = 0; out[sh, 3] = 110
    return out, pix


def sur_canevas(img, cx, cy, W, H, CX, CY):
    c = np.zeros((H, W, 4), np.float32)
    x0, y0 = CX - cx, CY - cy
    ys, xs = max(0, y0), max(0, x0)
    ye, xe = min(H, y0 + img.shape[0]), min(W, x0 + img.shape[1])
    if ye > ys and xe > xs:
        c[ys:ye, xs:xe] = img[ys - y0:ye - y0, xs - x0:xe - x0]
    a = c[..., 3:4] / 255.0
    return (FOND * (1 - a) + c[..., :3] * a).clip(0, 255).astype(np.uint8)


def lab(rgb):
    c = np.asarray(rgb, np.float64) / 255.0
    c = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
    M = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = c @ M.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def bandes(img_rgba, pix):
    crea = pix > 1
    ys, xs = np.nonzero(crea)
    if not len(ys):
        return {}
    y0, h = ys.min(), ys.max() - ys.min() + 1
    out = {}
    for nom, (a0, a1) in {'tete': (0.0, 0.18), 'tronc': (0.18, 0.55), 'jambes': (0.55, 1.0)}.items():
        sel = (ys >= y0 + a0 * h) & (ys < y0 + a1 * h)
        if sel.any():
            out[nom] = np.median(img_rgba[ys[sel], xs[sel], :3], axis=0)
    return out


def planche(trav, out):
    p = os.path.join(trav, 'mouvements', 'planche.npz')
    if not os.path.exists(p):
        return None
    z = np.load(p)
    rows = {}
    for k in z.files:
        s, i, t = k.split('__')
        rows.setdefault(s, {}).setdefault(int(i), {})[t] = z[k]
    ordre = [s for s in ('SD', 'SC', 'WK', 'GH', 'DE', 'TW', 'A1', 'A2', 'A3', 'A4', 'A5', 'SP', 'CA') if s in rows]
    zz = 2
    blocs = []
    for s in ordre:
        paires = [rows[s][i] for i in sorted(rows[s])]
        h = max(max(p_['o'].shape[0], p_['s'].shape[0]) for p_ in paires)
        w = sum(max(p_['o'].shape[1], p_['s'].shape[1]) for p_ in paires)
        blocs.append((s, paires, h, w))
    W = max(b[3] * zz + 6 * len(b[1]) for b in blocs) + 140
    H = sum(2 * b[2] * zz + 30 for b in blocs) + 50
    im = Image.new('RGB', (W, H), (36, 36, 42)); dr = ImageDraw.Draw(im)
    dr.text((10, 4), 'Silhouettes : original (jaune) | 3D (bleu), mêmes instants, de face puis de profil',
            fill=(235, 235, 235), font=FONT_G)
    y = 46
    for s, paires, h, w in blocs:
        dr.text((10, y + h * zz - 34), s, fill=(235, 235, 235), font=FONT_G)
        dr.text((10, y + h * zz + 4), NOMS_SEQ.get(s, ''), fill=(200, 200, 200), font=FONT)
        x = 120
        for p_ in paires:
            ww = max(p_['o'].shape[1], p_['s'].shape[1])
            for k, m in enumerate((p_['o'], p_['s'])):
                rgb = np.zeros(m.shape + (3,), np.uint8); rgb[:] = (52, 52, 60)
                rgb[m] = (232, 208, 110) if k == 0 else (110, 190, 240)
                im.paste(Image.fromarray(rgb).resize((m.shape[1] * zz, m.shape[0] * zz), Image.NEAREST),
                         (x, y + k * (h * zz + 4)))
            x += ww * zz + 6
        y += 2 * h * zz + 30
    im.save(out)
    return out


def gif_sequence(seq, info, choix_s, res, trav, out, dirs=(0, 2, 4, 6)):
    o = BamV1.load(open(os.path.join(SRC, info['fichier'] + '.BAM'), 'rb').read())
    h = BamV1.load(open(os.path.join(trav, 'hd', info['fichier'] + '.BAM'), 'rb').read())
    cols = []
    for d in dirs:
        cy = info['cycles'][d]
        if not cy:
            continue
        c = cy['cycle']
        co, so = o.cycles[c]; ch, sh = h.cycles[c]
        fo = [o.frames[o.lookup[so + i]] for i in range(co)]
        fh = [h.frames[h.lookup[sh + i]] for i in range(ch)]
        cols.append((d, fo, fh))
    if not cols:
        return None
    # canevas commun (repère de l'ancre, pixels HD)
    L = max(len(fh) for _, _, fh in cols)
    gx = max(max(max(f.cx * K for f in fo), max(f.cx for f in fh)) for _, fo, fh in cols) + 8
    dx = max(max(max((f.w - f.cx) * K for f in fo), max(f.w - f.cx for f in fh)) for _, fo, fh in cols) + 8
    gy = max(max(max(f.cy * K for f in fo), max(f.cy for f in fh)) for _, fo, fh in cols) + 8
    dy = max(max(max((f.h - f.cy) * K for f in fo), max(f.h - f.cy for f in fh)) for _, fo, fh in cols) + 8
    W, H = gx + dx, gy + dy
    S = min(1.0, 300.0 / max(W, H))
    tw, th = int(W * S), int(H * S)
    ims = []
    for k in range(L):
        im = Image.new('RGB', (len(cols) * (tw + 8) + 110, 2 * (th + 6) + 30), (30, 30, 34))
        dr = ImageDraw.Draw(im)
        dr.text((6, 6), '%s %s - %s' % (res, seq, NOMS_SEQ.get(seq, '')), fill=(230, 230, 230), font=FONT_P)
        dr.text((6, 30 + th // 2), 'original x4', fill=(230, 230, 230), font=FONT_P)
        dr.text((6, 36 + th + th // 2), 'nouveau HD', fill=(230, 230, 230), font=FONT_P)
        for j, (d, fo, fh) in enumerate(cols):
            a = fh[k % len(fh)]
            b_ = fo[min(len(fo) - 1, (k % len(fh)) * len(fo) // len(fh))]
            io, _ = rgba_image(o, b_)
            io = np.kron(io, np.ones((K, K, 1), np.float32))
            ih, _ = rgba_image(h, a)
            p1 = sur_canevas(io, b_.cx * K, b_.cy * K, W, H, gx, gy)
            p2 = sur_canevas(ih, a.cx, a.cy, W, H, gx, gy)
            x = 110 + j * (tw + 8)
            im.paste(Image.fromarray(p1).resize((tw, th), Image.LANCZOS), (x, 24))
            im.paste(Image.fromarray(p2).resize((tw, th), Image.LANCZOS), (x, 30 + th))
        ims.append(im)
    ims[0].save(out, save_all=True, append_images=ims[1:], duration=67, loop=0, optimize=True)
    return out


def main():
    res, trav = sys.argv[1].upper(), os.path.abspath(sys.argv[2])
    cdir = os.path.join(trav, 'controle')
    os.makedirs(cdir, exist_ok=True)
    seqs = lit_json(os.path.join(trav, 'origine', 'sequences.json'))
    mes = lit_json(os.path.join(trav, 'origine', 'mesures.json'))
    choix = lit_json(os.path.join(trav, 'mouvements', 'choix.json'), {})
    lum = lit_json(os.path.join(trav, 'rendu', 'lumiere.json'), {})
    verif = lit_json(os.path.join(trav, 'verif.json'), {})
    rig = lit_json(os.path.join(trav, 'rig', 'rig_rig.json'), {})
    coul = lit_json(os.path.join(trav, 'hd', 'couleur.json'), {})
    rapport = dict(resref=res, mesures={}, sequences={}, alertes=[])
    base = choix.get('_global', {}).get('base', 'SD')
    # --- taille, luminance, couleurs : 1re image de l'attente, de face, dans le BAM HD final
    bi = seqs[base]
    if os.path.exists(os.path.join(trav, 'hd', bi['fichier'] + '.BAM')):
        o = BamV1.load(open(os.path.join(SRC, bi['fichier'] + '.BAM'), 'rb').read())
        h = BamV1.load(open(os.path.join(trav, 'hd', bi['fichier'] + '.BAM'), 'rb').read())
        c = bi['cycles'][0]['cycle']
        fo = o.frames[o.lookup[o.cycles[c][1]]]; fh = h.frames[h.lookup[h.cycles[c][1]]]
        io, po = rgba_image(o, fo); ih, ph = rgba_image(h, fh)
        yo = np.nonzero(po > 1)[0]; yh = np.nonzero(ph > 1)[0]
        haut_o = yo.max() - yo.min() + 1; haut_h = (yh.max() - yh.min() + 1) / float(K)
        ecart_taille = 100.0 * (haut_h / haut_o - 1)
        rgb_o = io[..., :3][po > 1]; rgb_h = ih[..., :3][ph > 1]
        Y = lambda x: float((0.2126 * x[:, 0] + 0.7152 * x[:, 1] + 0.0722 * x[:, 2]).mean() / 255.0)
        lo_, lh_ = Y(rgb_o), Y(rgb_h)
        bo, bh = bandes(io, po), bandes(ih, ph)
        de = {k: round(float(np.linalg.norm(lab(bo[k]) - lab(bh[k]))), 1) for k in bo if k in bh}
        rapport['mesures'].update(hauteur_px_original=int(haut_o), hauteur_px_nouveau=round(float(haut_h), 1),
                                  ecart_taille_pct=round(float(ecart_taille), 2), luminance_original=round(lo_, 4),
                                  luminance_nouveau=round(lh_, 4), ecart_teinte_lab=de)
        if abs(ecart_taille) > 3:
            rapport['alertes'].append('taille : écart de %.1f %% (règle : 3 %%)' % ecart_taille)
        if abs(lh_ / max(lo_, 1e-6) - 1) > 0.12:
            rapport['alertes'].append('luminance : %.3f contre %.3f pour l\'original' % (lh_, lo_))
        for k, v in de.items():
            if v > 18:
                rapport['alertes'].append('teinte (%s) : écart Lab %.0f' % (k, v))
    # --- port du corps, mouvements
    for s, c in choix.items():
        if s.startswith('_'):
            continue
        e = dict(clip=c.get('clip'), mode=c.get('mode'), images=c.get('n'), cout_silhouette=c.get('cout'),
                 copie_de=c.get('copie_de'), repris_de=c.get('repris_de'), posture_deg=c.get('posture'),
                 ecart_tete_profil_px=c.get('ecart_profil_px'), foulee=c.get('foulee'),
                 amortissement=c.get('amortissement'))
        rapport['sequences'][s] = {k: v for k, v in e.items() if v is not None}
        ep = c.get('ecart_profil_px')
        if ep is not None and abs(ep) > 2.0:
            rapport['alertes'].append('%s : tête à %.1f px de sa place de profil (règle : 2 px)' % (s, ep))
    rapport['mesures'].update(posture_globale_deg=choix.get('_global', {}).get('posture'),
                              echelle_px_par_unite=choix.get('_global', {}).get('echelle_px'),
                              ombre=lum.get('ombre'), recouvrement_ombre=lum.get('iou_ombre'),
                              lumiere_soleil=lum.get('lights', {}).get('key', {}).get('energy'),
                              gains_couleur=coul.get('gains_rgb'),
                              rig_ok=rig.get('ok'), rig_aretes_etirees_pct=rig.get('aretes_etirees_x2_pct'),
                              sc_verify_erreurs=verif.get('errors'), sc_verify_images_hd=verif.get('hd_frames'))
    if verif and verif.get('errors'):
        rapport['alertes'].append('sc_verify : %d erreurs' % verif['errors'])
    if rig and not rig.get('ok', True):
        rapport['alertes'].append('squelette : contrôle douteux (voir rig/rig_rig.json)')
    # --- images
    pl = planche(trav, os.path.join(cdir, 'planche_mouvements.png'))
    gifs = []
    for s, info in seqs.items():
        c = choix.get(s, {})
        if info.get('copie_de') or 'n' not in c:
            continue
        if not os.path.exists(os.path.join(trav, 'hd', info['fichier'] + '.BAM')):
            continue
        try:
            g = gif_sequence(s, info, c, res, trav, os.path.join(cdir, '%s_%s.gif' % (res, s)))
            if g:
                gifs.append(os.path.basename(g))
        except Exception as e:  # noqa: BLE001
            rapport['alertes'].append('aperçu %s impossible : %r' % (s, e))
    rapport['images'] = dict(planche=os.path.basename(pl) if pl else None, gifs=gifs)
    rapport['ok'] = not rapport['alertes']
    ecrit_json(os.path.join(cdir, 'rapport.json'), rapport)
    # --- rapport lisible
    m = rapport['mesures']
    L = ['# Contrôle %s' % res, '']
    if 'ecart_taille_pct' in m:
        L.append('- Taille : %s px (original %s px), écart %+.1f %% (règle : 3 %%)' % (
            m['hauteur_px_nouveau'], m['hauteur_px_original'], m['ecart_taille_pct']))
        L.append('- Luminance : %.3f (original %.3f)' % (m['luminance_nouveau'], m['luminance_original']))
        L.append('- Teinte, écart Lab par bande : %s' % ', '.join('%s %s' % kv for kv in m['ecart_teinte_lab'].items()))
    L.append('- Ombre : soleil %s, recouvrement %s' % (m.get('ombre'), m.get('recouvrement_ombre')))
    L.append('- Port du corps : %s° ; échelle %.2f px/unité' % (m.get('posture_globale_deg'),
                                                              m.get('echelle_px_par_unite') or 0))
    L.append('- SC-HD : %s erreur(s), %s images HD' % (m.get('sc_verify_erreurs'), m.get('sc_verify_images_hd')))
    L += ['', '| Séquence | Mouvement | Mode | Images | Coût | Tête (px) |', '|---|---|---|---|---|---|']
    for s, e in rapport['sequences'].items():
        L.append('| %s %s | %s | %s | %s | %s | %s |' % (
            s, NOMS_SEQ.get(s, ''), e.get('clip') or ('copie de ' + str(e.get('copie_de'))), e.get('mode', ''),
            e.get('images', ''), ('%.3f' % e['cout_silhouette']) if e.get('cout_silhouette') is not None else '',
            e.get('ecart_tete_profil_px', '')))
    L += ['', 'Alertes : ' + ('aucune' if not rapport['alertes'] else '')]
    L += ['- ' + a for a in rapport['alertes']]
    open(os.path.join(cdir, 'rapport.md'), 'w').write('\n'.join(L) + '\n')
    print('\n'.join(L))


if __name__ == '__main__':
    main()
