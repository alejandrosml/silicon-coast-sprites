# reference.py - Silicon Coast, chaîne des monstres 3D, étapes 2 et 3 : dessin de référence puis modèle 3D.
#
#   python3 reference.py dessin <RESREF> <travail> [--variantes 4] [--pas 40]
#   python3 reference.py modele <RESREF> <travail> [--essais 2]
#
# dessin : Qwen-Image-Edit-2511 (Space Hugging Face) part des vues agrandies du sprite (face, profil, dos) et de la
#          fiche du monstre (fiches.json) ; plusieurs graines ; chaque variante est notée contre le sprite :
#          cadrage (personnage entier, seul), couleurs par bande (tête, tronc, jambes, écart en Lab), ressemblance
#          d'ensemble (DINOv2 si disponible). La meilleure est retenue : <travail>/dessin/reference.png.
# modele : TRELLIS.2 (Space Hugging Face) -> <travail>/modele/modele.glb (300 000 faces, texture 2048), contrôle de la
#          silhouette de face du modèle contre le dessin ; nouvel essai (autre graine) si elle s'en écarte.
# Authentification Hugging Face : secret réseau de l'environnement cloud (ajouté par le proxy) ou HF_TOKEN.
# Quota ZeroGPU dépassé : attente puis nouvel essai (jusqu'à 3 h).
import glob
import json
import os
import re
import shutil
import sys
import time

import numpy as np
from PIL import Image

from commun import ICI, lit_json, ecrit_json

FICHES = lit_json(os.path.join(ICI, 'fiches.json'))
TOKEN = os.environ.get('HF_TOKEN') or None


def opt(args, n, d, c=str):
    return c(args[args.index(n) + 1]) if n in args else d


def client(space):
    from gradio_client import Client
    for k in range(20):
        try:
            return Client(space, token=TOKEN, verbose=False)
        except Exception as e:  # noqa: BLE001
            print('connexion', space, 'échec', repr(e)[:160], flush=True)
            time.sleep(30 * (k + 1))
    raise RuntimeError('Space injoignable : ' + space)


# Budget GPU : le compte PRO a 40 min de ZeroGPU incluses par 24 h ; au-delà, Hugging Face prélève des crédits
# payants si le compte a un moyen de paiement. Avant chaque appel, la chaîne lit le quota restant
# (api/spaces/zero-gpu/quota : « current » = secondes restantes, réservées au début d'un appel et rendues en partie
# à la fin) et n'appelle que s'il reste de quoi couvrir l'appel au pire ; sinon elle attend la remise à zéro
# (« resetsAt »). SC_GPU_PAYANT=1 lève cette garde (dépassement accepté par l'utilisateur). Journal des appels :
# SC_GPU_JOURNAL.
JOURNAL = os.environ.get('SC_GPU_JOURNAL', os.path.join(ICI, 'gpu_journal.json'))


def quota_gpu():
    import urllib.request
    h = {'Authorization': 'Bearer ' + TOKEN} if TOKEN else {}
    r = urllib.request.urlopen(urllib.request.Request('https://huggingface.co/api/spaces/zero-gpu/quota', headers=h),
                               timeout=30)
    return json.load(r)


PLAFOND_S = 60.0 * float(os.environ.get('SC_GPU_PLAFOND_MIN', '250'))     # dépassement payant maximal (min)


def payant():
    """dépassement payant accepté par l'utilisateur : variable SC_GPU_PAYANT=1 ou fichier <journal>.payant."""
    return os.environ.get('SC_GPU_PAYANT') == '1' or os.path.exists(JOURNAL + '.payant')


def budget_gpu(quoi, besoin=400.0):
    """attend que le quota ZeroGPU restant couvre « besoin » secondes (l'appel au pire), sans dépassement payant ;
    si l'utilisateur a accepté le dépassement, vérifie seulement qu'il reste sous le plafond (SC_GPU_PLAFOND_MIN)."""
    if payant():
        try:
            q = quota_gpu()
        except Exception:  # noqa: BLE001
            return
        if float(q.get('overquotaUsed') or 0) + besoin > PLAFOND_S:
            raise RuntimeError('plafond du dépassement payant atteint (%.0f s utilisées, plafond %.0f s)' % (
                float(q.get('overquotaUsed') or 0), PLAFOND_S))
        return
    while True:
        try:
            q = quota_gpu()
        except Exception as e:  # noqa: BLE001
            print(quoi, ': quota illisible', repr(e)[:120], '-> attente 5 min', flush=True)
            time.sleep(300); continue
        if q.get('current', 0) >= besoin and not q.get('overquotaUsed'):
            return
        import datetime as _dt
        try:
            fin = _dt.datetime.fromisoformat(q['resetsAt'].replace('Z', '+00:00')).timestamp()
        except Exception:  # noqa: BLE001
            fin = time.time() + 3600
        attente = max(120.0, fin - time.time() + 60)
        print('%s : quota GPU restant %.0f s (il faut %.0f s) -> attente de la remise à zéro (%s), %.0f min' % (
            quoi, q.get('current', 0), besoin, q.get('resetsAt'), attente / 60), flush=True)
        time.sleep(min(attente, 1800))


def note_gpu(quoi, secondes):
    j = lit_json(JOURNAL, [])
    try:
        q = quota_gpu().get('current')
    except Exception:  # noqa: BLE001
        q = None
    j.append(dict(t=time.time(), s=round(secondes, 1), quoi=quoi, quota_restant=q))
    ecrit_json(JOURNAL, j)


def appel_gpu(fn, quoi, reserve=0.0):
    """appelle fn() ; si le quota ZeroGPU est épuisé, attend et recommence (jusqu'à 3 h). Chaque appel est noté dans
    le journal du budget GPU pour la plus grande de sa durée réelle et de la durée que le Space réserve (« reserve »,
    décorateur @spaces.GPU : Hugging Face peut décompter la durée réservée plutôt que la durée réelle)."""
    t0 = time.time()
    while True:
        budget_gpu(quoi, besoin=2.0 * max(reserve, 60.0) + 30.0)
        ta = time.time()
        try:
            r = fn()
            note_gpu(quoi, time.time() - ta)
            return r
        except Exception as e:  # noqa: BLE001
            note_gpu(quoi + ' (échec)', time.time() - ta)
            m = repr(e)
            if 'maximum allowed' in m or 'Invalid username' in m or '401' in m:
                raise RuntimeError('Hugging Face sans authentification (secret réseau ou HF_TOKEN absent) : ' + m[:200])
            attente = 120
            mm = re.search(r'(\d+):(\d+):(\d+)', m)
            if 'quota' in m.lower() or 'GPU' in m:
                if mm:
                    attente = min(3600, int(mm.group(1)) * 3600 + int(mm.group(2)) * 60 + int(mm.group(3)) + 30)
                else:
                    attente = 600
            print(quoi, ': échec', m[:200], '-> nouvel essai dans', attente, 's', flush=True)
            if time.time() - t0 > 3 * 3600:
                raise
            time.sleep(attente)


# ------------------------------------------------------------------------------------------------ dessin
GABARIT = (
    "Pictures 1, 2 and 3 show the front, the side and the back of a low-resolution sprite of {en} from an old "
    "video game. Recreate this exact creature as a realistic, highly detailed character render for a modern AAA "
    "fantasy video game. {description} Keep exactly the body proportions, the silhouette and the colors of the "
    "sprite: every visible part of the creature keeps the same place, shape, size and color. {objet}Full body "
    "visible from the top of the head to the feet, standing upright on both feet, facing the viewer, both arms held "
    "straight out to the sides about 40 degrees below horizontal, well away from the body, {mains}, legs slightly "
    "apart, front view at eye level, plain light grey background, soft even studio lighting without strong "
    "shadows, no ground, no text, nothing else in the picture.")


def masque_dessin(im):
    """sépare le personnage du fond gris clair uni (couleur estimée sur les bords)."""
    a = np.asarray(im.convert('RGB')).astype(np.float64)
    bord = np.concatenate([a[:4].reshape(-1, 3), a[-4:].reshape(-1, 3), a[:, :4].reshape(-1, 3),
                           a[:, -4:].reshape(-1, 3)])
    fond = np.median(bord, axis=0)
    d = np.linalg.norm(a - fond, axis=2)
    m = d > 28
    # remplissage depuis les bords : le fond est la partie claire reliée au bord
    from collections import deque
    h, w = m.shape
    vu = np.zeros_like(m)
    q = deque()
    for y in range(h):
        for x in (0, w - 1):
            if not m[y, x] and not vu[y, x]:
                vu[y, x] = True; q.append((y, x))
    for x in range(w):
        for y in (0, h - 1):
            if not m[y, x] and not vu[y, x]:
                vu[y, x] = True; q.append((y, x))
    while q:
        y, x = q.popleft()
        for yy, xx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
            if 0 <= yy < h and 0 <= xx < w and not vu[yy, xx] and not m[yy, xx]:
                vu[yy, xx] = True; q.append((yy, xx))
    return ~vu, fond


def composantes(m, mini=0.002):
    """nombre de morceaux (en pixels > mini x surface) du masque (étiquetage simple, 4-connexe, sous-échantillonné)."""
    s = m[::4, ::4]
    h, w = s.shape
    lab = np.zeros(s.shape, np.int32)
    n = 0
    tailles = []
    for y in range(h):
        for x in range(w):
            if s[y, x] and not lab[y, x]:
                n += 1
                pile = [(y, x)]; lab[y, x] = n; t = 0
                while pile:
                    yy, xx = pile.pop(); t += 1
                    for y2, x2 in ((yy + 1, xx), (yy - 1, xx), (yy, xx + 1), (yy, xx - 1)):
                        if 0 <= y2 < h and 0 <= x2 < w and s[y2, x2] and not lab[y2, x2]:
                            lab[y2, x2] = n; pile.append((y2, x2))
                tailles.append(t)
    return sum(1 for t in tailles if t > mini * h * w)


def rgb_vers_lab(c):
    c = np.asarray(c, np.float64) / 255.0
    c = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
    M = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = c @ M.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


_dino = None


def dino_sim(a, b):
    """similarité cosinus DINOv2-small entre deux images (None si indisponible)."""
    global _dino
    try:
        import torch
        from transformers import AutoImageProcessor, AutoModel
        if _dino is None:
            _dino = (AutoImageProcessor.from_pretrained('facebook/dinov2-small'),
                     AutoModel.from_pretrained('facebook/dinov2-small').eval())
        proc, mod = _dino
        with torch.no_grad():
            f = [mod(**proc(images=x.convert('RGB'), return_tensors='pt')).pooler_output[0] for x in (a, b)]
        return float(torch.nn.functional.cosine_similarity(f[0], f[1], dim=0))
    except Exception as e:  # noqa: BLE001
        print('DINOv2 indisponible :', repr(e)[:120], flush=True)
        _dino = False if _dino is None else _dino
        return None


def iou_proportions(m, brut):
    """silhouette du dessin ramenée à la hauteur du sprite de face (alignées en bas, au centre) : recouvrement avec la
    silhouette du sprite. Mesure les proportions (corpulence, longueur des membres), pas seulement la couleur."""
    if brut is None:
        return None
    a = np.asarray(brut)
    s = a[..., 3] > 200 if a.ndim == 3 and a.shape[2] == 4 else None
    if s is None or not s.any():
        return None
    ys, xs = np.nonzero(s); H = ys.max() - ys.min() + 1
    s = s[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    yd, xd = np.nonzero(m)
    if not len(yd):
        return None
    md = m[yd.min():yd.max() + 1, xd.min():xd.max() + 1]
    f = H / float(md.shape[0])
    md = np.asarray(Image.fromarray(md.astype(np.uint8) * 255).resize((max(1, int(round(md.shape[1] * f))), H),
                                                                     Image.BILINEAR)) > 127
    W = max(md.shape[1], s.shape[1]) + 4
    c1 = np.zeros((H, W), bool); c2 = np.zeros((H, W), bool)
    o1 = (W - s.shape[1]) // 2; o2 = (W - md.shape[1]) // 2
    c1[:, o1:o1 + s.shape[1]] = s; c2[:, o2:o2 + md.shape[1]] = md
    return float((c1 & c2).sum() / max(1, (c1 | c2).sum()))


def note(im, mes, vue_face, brut=None):
    m, fond = masque_dessin(im)
    h, w = m.shape
    ys, xs = np.nonzero(m)
    if len(ys) < 100:
        return dict(score=99.0, raison='vide')
    touche = bool(ys.min() <= 2 or ys.max() >= h - 3 or xs.min() <= 2 or xs.max() >= w - 3)
    haut = (ys.max() - ys.min() + 1) / h
    n_morceaux = composantes(m)
    a = np.asarray(im.convert('RGB')).astype(np.float64)
    y0, H = ys.min(), ys.max() - ys.min() + 1
    dE = []
    for nom_b, (a0, a1) in {'tete': (0.0, 0.18), 'tronc': (0.18, 0.55), 'jambes': (0.55, 1.0)}.items():
        ref = mes['bandes_rgb'].get(nom_b)
        sel = (ys >= y0 + a0 * H) & (ys < y0 + a1 * H)
        if ref is None or sel.sum() < 50:
            continue
        med = np.median(a[ys[sel], xs[sel]], axis=0)
        L1, L2 = rgb_vers_lab(med), rgb_vers_lab(ref)
        # teinte et saturation comptent plus que la clarté (lumière de studio contre lumière du jeu)
        dE.append(float(np.sqrt(0.25 * (L1[0] - L2[0]) ** 2 + (L1[1] - L2[1]) ** 2 + (L1[2] - L2[2]) ** 2)))
    dE = float(np.mean(dE)) if dE else 50.0
    # ressemblance d'ensemble : personnage détouré sur fond gris contre la vue de face du sprite
    det = np.full_like(a, 205.0); det[m] = a[m]
    sim = dino_sim(Image.fromarray(det.astype(np.uint8)), vue_face)
    iou = iou_proportions(m, brut)
    score = dE / 10.0 + (0 if sim is None else (1.0 - sim) * 6.0) + (0 if iou is None else (1.0 - iou) * 4.0)
    score += 3.0 if touche else 0.0
    score += 2.0 * max(0, n_morceaux - 1)
    score += 2.0 if haut < 0.7 else 0.0
    return dict(score=round(score, 3), ecart_couleur=round(dE, 2), dino=None if sim is None else round(sim, 3),
                proportions=None if iou is None else round(iou, 3),
                touche_bord=touche, morceaux=n_morceaux, hauteur=round(haut, 3))


def dessin(res, travail, args):
    fiche = FICHES[res]
    nvar = opt(args, '--variantes', 3, int)
    pas = opt(args, '--pas', 40, int)
    o = os.path.join(travail, 'origine')
    out = os.path.join(travail, 'dessin')
    os.makedirs(out, exist_ok=True)
    mes = lit_json(os.path.join(o, 'mesures.json'))
    vues = [os.path.join(o, 'vues', 'vue_d%d.png' % d) for d in (0, 4, 8)]
    if fiche.get('objet'):
        objet = 'The weapon of the sprite is NOT drawn: no weapon, nothing held. '
        mains = 'the right hand closed into an empty fist as if gripping a handle, the left hand open and empty'
    else:
        objet = ''
        mains = 'hands open and empty'
    prompt = GABARIT.format(en=fiche['en'], description=fiche['description'], objet=objet, mains=mains)
    open(os.path.join(out, 'consigne.txt'), 'w').write(prompt)
    etat = lit_json(os.path.join(out, 'variantes.json'), {})
    c = None
    for k in range(nvar):
        p = os.path.join(out, 'variante_%d.png' % k)
        if not os.path.exists(p):
            if c is None:
                c = client('Qwen/Qwen-Image-Edit-2511')
            from gradio_client import handle_file

            def go():
                r = c.predict(images=[{'image': handle_file(v), 'caption': None} for v in vues], prompt=prompt,
                              seed=1000 + 17 * k, randomize_seed=False, true_guidance_scale=4.0,
                              num_inference_steps=pas, height=1408, width=1056, rewrite_prompt=False,
                              api_name='/infer')
                r = r[0] if isinstance(r, (list, tuple)) else r
                if isinstance(r, (list, tuple)):
                    r = r[0]
                return r['image'] if isinstance(r, dict) and 'image' in r else (r.get('path') if isinstance(r, dict) else r)
            t = time.time()
            src = appel_gpu(go, 'dessin %s %d' % (res, k), reserve=180)
            Image.open(src).convert('RGB').save(p)
            print('variante', k, round(time.time() - t, 1), 's', flush=True)
        if str(k) not in etat:
            etat[str(k)] = note(Image.open(p), mes, Image.open(vues[0]),
                                Image.open(os.path.join(o, 'vues', 'brut_d0.png')).convert('RGBA'))
            ecrit_json(os.path.join(out, 'variantes.json'), etat)
        print('variante', k, etat[str(k)], flush=True)
    best = min(etat, key=lambda k: etat[k]['score'])
    shutil.copy(os.path.join(out, 'variante_%s.png' % best), os.path.join(out, 'reference.png'))
    ecrit_json(os.path.join(out, 'choix.json'), dict(choisie=int(best), notes=etat, consigne=prompt))
    # planche des variantes (notes en légende)
    ims = [Image.open(os.path.join(out, 'variante_%d.png' % k)).convert('RGB').resize((264, 352)) for k in range(nvar)]
    pl = Image.new('RGB', (264 * nvar + 10 * (nvar - 1), 352), (40, 40, 40))
    for k, im in enumerate(ims):
        pl.paste(im, (k * 274, 0))
    pl.save(os.path.join(out, 'planche_variantes.png'))
    print('choisie', best, etat[best], flush=True)


# ------------------------------------------------------------------------------------------------ modèle
def modele(res, travail, args):
    essais = opt(args, '--essais', 2, int)
    ref = os.path.join(travail, 'dessin', 'reference.png')
    out = os.path.join(travail, 'modele')
    os.makedirs(out, exist_ok=True)
    glb = os.path.join(out, 'modele.glb')
    if os.path.exists(glb):
        print('déjà fait', glb)
        return
    from gradio_client import handle_file
    for k in range(essais):
        c = client('microsoft/TRELLIS.2')
        try:
            c.predict(api_name='/start_session')
        except Exception as e:  # noqa: BLE001
            print('start_session :', repr(e)[:160])
        t = time.time()
        pre = appel_gpu(lambda: c.predict(input=handle_file(ref), api_name='/preprocess_image'), 'pré-traitement')
        pre_path = pre['path'] if isinstance(pre, dict) else pre
        shutil.copy(pre_path, os.path.join(out, 'entree_%d.png' % k))
        appel_gpu(lambda: c.predict(image=handle_file(pre_path), seed=k, resolution='1024',
                                    api_name='/image_to_3d'), 'modèle 3D', reserve=120)
        g = appel_gpu(lambda: c.predict(decimation_target=300000, texture_size=2048, api_name='/extract_glb'),
                      'extraction GLB', reserve=120)
        glb_t, dl = g if isinstance(g, (list, tuple)) else (g, g)
        path = dl if isinstance(dl, str) else (dl.get('path') if isinstance(dl, dict) else glb_t)
        p = os.path.join(out, 'modele_%d.glb' % k)
        shutil.copy(path, p)
        print('modèle', k, os.path.getsize(p), 'octets', round(time.time() - t, 1), 's', flush=True)
        # contrôle : le modèle est-il complet ? (taille raisonnable)
        if os.path.getsize(p) > 2e6:
            shutil.copy(p, glb)
            ecrit_json(os.path.join(out, 'modele.json'), dict(graine=k, octets=os.path.getsize(p)))
            return
    raise RuntimeError('TRELLIS : pas de modèle exploitable')


if __name__ == '__main__':
    cmd, res, travail = sys.argv[1], sys.argv[2].upper(), os.path.abspath(sys.argv[3])
    {'dessin': dessin, 'modele': modele}[cmd](res, travail, sys.argv[4:])
