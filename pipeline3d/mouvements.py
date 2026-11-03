# mouvements.py - Silicon Coast, chaîne des monstres 3D, étape 5 : choix des mouvements par comparaison avec
# l'original, puis animations prêtes pour le rendu.
#
#   blender -b -P mouvements.py -- <RESREF> <travail> [--seq SD,WK] [--max-cand 40] [--fins 3]
#
# Pour chaque séquence du jeu (attente SD, garde SC, marche WK, coup reçu GH, mort DE, au sol TW, attaques A1..A5,
# incantation SP, sort CA) :
#  1. la frise d'origine est lue : jouée d'un trait (images dans l'ordre, doublées ou en aller-retour : « déroulée »,
#     rendue avec le nombre d'images voulu par les règles de fidélité), à motif répété (boucle d'incantation, au sol :
#     « table », les images uniques sont refaites et la frise d'origine est gardée) ou à image unique (« fixe ») ;
#  2. des captures candidates (bibliothèque Mixamo convertie, filtrée par mots-clés et par l'archétype du monstre)
#     sont reciblées sur le squelette du monstre ; leurs silhouettes, rendues à la caméra du jeu et à l'échelle du
#     sprite (directions 0 et 4), sont comparées aux images d'origine (1 - IoU) : passe grossière sur toute la
#     capture (fenêtre de durée bornée : vitesse 0,7 à 1,4 fois la durée voulue), puis passe fine sur les meilleures
#     (alignement temporel monotone dans une bande autour de l'alignement linéaire) ;
#  3. port du corps (règles 2 et 7) : position de la tête par rapport aux hanches, vue de profil, ramenée à celle de
#     l'original (attente pour tout le corps, puis garde, marche et coup reçu séquence par séquence) ;
#  4. marche : un cycle exact (même pose au début et à la fin), foulée ajustée à la vitesse du pied de l'original
#     (sinon les pieds glissent) ; attente et garde : bouclées, mouvement ramené à l'amplitude de l'original ;
#  5. une animation par séquence (<travail>/mouvements/anims/<SEQ>.blend), et la planche de contrôle
#     (<travail>/mouvements/planche.png : original | 3D, silhouettes de face et de profil).
import contextlib
import json
import math
import os
import sys
import time

import bpy
import numpy as np
from mathutils import Matrix, Quaternion, Vector

ICI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ICI)
from commun import IMAGES_CIBLES, MOCAP, ecrit_json, lit_json  # noqa: E402
from retarget_lib import Reciblage, Source, applique, ecrit_action, interpole  # noqa: E402

a = sys.argv[sys.argv.index('--') + 1:]
RES, TRAV = a[0].upper(), os.path.abspath(a[1])
opt = lambda n, d, c=str: c(a[a.index(n) + 1]) if n in a else d
SEULES = opt('--seq', '', str).split(',') if '--seq' in a else None
MAXC = opt('--max-cand', 40, int)
FINS = opt('--fins', 3, int)
PHI = math.radians(39.0)
OUT = os.path.join(TRAV, 'mouvements')
os.makedirs(os.path.join(OUT, 'anims'), exist_ok=True)
FICHE = lit_json(os.path.join(ICI, 'fiches.json'))[RES]
ARCH = FICHE.get('archetype', 'griffes')
SEQS = lit_json(os.path.join(TRAV, 'origine', 'sequences.json'))
MES = lit_json(os.path.join(TRAV, 'origine', 'mesures.json'))
MASQ = np.load(os.path.join(TRAV, 'origine', 'masques.npz'))
INDEX = lit_json(os.path.join(MOCAP, 'index.json'))
T_DEBUT = time.time()


def log(*x):
    print('[mouvements %4.0f s]' % (time.time() - T_DEBUT), *x, flush=True)


@contextlib.contextmanager
def silence():
    """les rendus de Blender écrivent une ligne chacun : on les fait taire."""
    sys.stdout.flush()
    fd = os.dup(1); nul = os.open(os.devnull, os.O_WRONLY)
    os.dup2(nul, 1)
    try:
        yield
    finally:
        os.dup2(fd, 1); os.close(fd); os.close(nul)


# ------------------------------------------------------------------------------------------------ candidats
EXCLUS_ARME = ('sword', 'shield', 'axe', 'bow', 'arrow', 'great sword', 'rifle', 'pistol')
CAT = {
    'WK': lambda n: ('walk' in n and not any(x in n for x in ('back', 'left', 'right', 'strafe', 'turn', 'crouch',
                                                             'sneak', 'aim', 'drunk'))),
    'SD': lambda n: (('idle' in n or 'breathing' in n or 'weight shift' in n or 'look away' in n)
                     and not any(x in n for x in ('to crouch', 'to standing', 'falling', 'block', 'jump', 'aim',
                                                  'injured'))),
    'SC': lambda n: (('idle' in n or 'breathing' in n or 'block idle' in n or 'flexing' in n)
                     and not any(x in n for x in ('to crouch', 'to standing', 'falling', 'jump', 'aim', 'injured'))),
    'GH': lambda n: any(x in n for x in ('impact', 'react small', 'react large', 'reaction hit', 'hit')) and
                     'death' not in n,
    'DE': lambda n: any(x in n for x in ('death', 'dying')),
    'A': lambda n: any(x in n for x in ('attack', 'slash', 'punch', 'swiping', 'strike', 'kick', 'jab', 'stab',
                                         'combo', 'swing', 'headbutt', 'biting', 'scratch')) and
                    not any(x in n for x in ('block', 'run', 'jump', 'slide', 'idle', 'walk')),
    'SP': lambda n: any(x in n for x in ('cast', 'spell', 'power up', 'roaring', 'scream', 'flexing', 'magic area')),
    'CA': lambda n: any(x in n for x in ('magic attack', 'cast', 'spell', 'roaring', 'scream')),
}


PACKS_ARMES = ('great_sword', 'sword_and_shield', 'melee_axe', 'longbow')


def candidats(seq):
    """captures possibles pour une séquence : mots-clés de la séquence, et archétype du monstre : les captures
    faites avec une arme (packs épée, hache, arc) ne servent qu'aux monstres armés ; les attaques magiques ne
    servent pas aux monstres à griffes ou à poings."""
    typ = 'A' if seq.startswith('A') else ('SC' if seq in ('TW',) else seq)
    f = CAT.get(typ, CAT['SC'])
    out = []
    for k, v in INDEX.items():
        n = v['nom'].lower(); p = v['pack'].lower()
        if not f(n):
            continue
        arme = any(x in p for x in PACKS_ARMES) or any(x in n for x in EXCLUS_ARME)
        magie = any(x in n for x in ('magic', 'spell', 'cast'))
        if ARCH != 'epee' and arme:
            continue
        if ARCH == 'epee' and typ == 'A' and not arme:
            continue
        if typ == 'A' and ARCH in ('griffes', 'poings', 'vampire') and magie:
            continue
        out.append(k)

    def prio(k):                       # packs « créatures » d'abord pour les monstres à griffes...
        p = INDEX[k]['pack'].lower()
        if ARCH in ('griffes', 'poings', 'vampire') and ('creature' in p or 'zombie' in p):
            return 0
        if ARCH == 'mage' and 'magic' in p:
            return 0
        if ARCH == 'epee' and any(x in p for x in PACKS_ARMES):
            return 0
        return 1
    out.sort(key=lambda k: (prio(k), INDEX[k]['nom']))
    return out[:MAXC]


# ------------------------------------------------------------------------------------------------ scène
with silence():
    bpy.ops.wm.open_mainfile(filepath=os.path.join(TRAV, 'rig', 'rig.blend'))
sc = bpy.context.scene
arm = bpy.data.objects['Armature']
corps = bpy.data.objects['SC_corps']
sil = corps.copy(); sil.data = corps.data.copy(); sil.name = 'SC_sil'      # silhouette : maillage allégé, mêmes poids
sc.collection.objects.link(sil)
nf = len(sil.data.polygons)
if nf > 12000:
    dec = sil.modifiers.new('dec', 'DECIMATE'); dec.ratio = 12000 / nf
    sil.modifiers.move(len(sil.modifiers) - 1, 0)          # avant l'armature
    bpy.context.view_layer.objects.active = sil
    bpy.ops.object.modifier_apply(modifier='dec')
sil.data.materials.clear()
corps.hide_render = True
for o in bpy.data.objects:
    if o.type in ('LIGHT', 'CAMERA') or (o.type == 'MESH' and o not in (sil,)):
        o.hide_render = True
racine = bpy.data.objects.new('SC_racine', None)
sc.collection.objects.link(racine)
arm.parent = racine
sc.render.engine = 'BLENDER_WORKBENCH'
sc.display.shading.light = 'FLAT'
sc.display.shading.color_type = 'SINGLE'
sc.display.shading.single_color = (1, 1, 1)
sc.display.render_aa = 'OFF'
sc.render.film_transparent = True
sc.view_settings.view_transform = 'Standard'
sc.render.image_settings.file_format = 'PNG'
cd = bpy.data.cameras.new('SC_cam'); cd.type = 'ORTHO'
cam = bpy.data.objects.new('SC_cam', cd); sc.collection.objects.link(cam); sc.camera = cam
cam.rotation_euler = (math.pi / 2 - PHI, 0.0, 0.0)
cd.clip_start, cd.clip_end = 1.0, 5000.0
TMP = os.path.join(OUT, '_tmp.png')

# objet tenu (arme.py) : il compte dans les silhouettes, la main le tient par la prise calée au repos
ARME = lit_json(os.path.join(TRAV, 'rig', 'arme_modele.json'))
arme_obj = None
if ARME:
    with bpy.data.libraries.load(ARME['blend']) as (src_, dst_):
        dst_.objects = [n for n in src_.objects if n == 'SC_massue']
    arme_obj = dst_.objects[0]
    sc.collection.objects.link(arme_obj)
    arme_obj.hide_render = False
    PRISE0 = Matrix(ARME['prise'])
ROULIS = 0.0


def place_arme(ech):
    """l'objet suit l'os de la main (même formule que bl_anim.place_club), roulis ROULIS autour de l'axe de la main."""
    if arme_obj is None:
        return
    pb = arm.pose.bones[ARME['os']]
    loc, rot, _ = (arm.matrix_world @ pb.matrix).decompose()
    G = Matrix.Rotation(math.radians(ROULIS), 4, 'Y') @ PRISE0
    G = G.copy(); G.translation = G.translation * ech
    arme_obj.matrix_world = Matrix.Translation(loc) @ rot.to_matrix().to_4x4() @ G @ Matrix.Scale(ech, 4)


def cadre_camera(w, h, cx, cy):
    sc.render.resolution_x, sc.render.resolution_y = int(w), int(h)
    sc.render.resolution_percentage = 100
    cd.ortho_scale = float(max(w, h)); cd.sensor_fit = 'AUTO'
    sx_c = w / 2.0 - cx; sy_c = cy - h / 2.0
    xa = Vector((1.0, 0.0, 0.0)); ya = Vector((0.0, math.sin(PHI), math.cos(PHI)))
    v = Vector((0.0, math.cos(PHI), -math.sin(PHI)))
    cam.location = xa * sx_c + ya * sy_c - v * 1500.0


def masque_rendu():
    sc.render.filepath = TMP
    with silence():
        bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(TMP)
    w, h = img.size
    px = np.empty(w * h * 4, np.float32); img.pixels.foreach_get(px)
    bpy.data.images.remove(img)
    return px.reshape(h, w, 4)[::-1, :, 3] > 0.5


def place_racine(direction, ech):
    """direction du jeu (0 S ... 8 N, pas de 22,5°) : le modèle tourne de -direction x 22,5° autour de Z."""
    racine.matrix_world = Matrix.Rotation(-direction * math.pi / 8.0, 4, 'Z') @ Matrix.Scale(ech, 4)
    bpy.context.view_layer.update()


def sommets_sil():
    dg = bpy.context.evaluated_depsgraph_get()
    ev = sil.evaluated_get(dg)
    me = ev.to_mesh()
    co = np.empty(len(me.vertices) * 3); me.vertices.foreach_get('co', co)
    ev.to_mesh_clear()
    co = co.reshape(-1, 3)
    M = np.array(sil.matrix_world)
    return co @ M[:3, :3].T + M[:3, 3]


def hauteur_ecran(co):
    sy = co[:, 1] * math.sin(PHI) + co[:, 2] * math.cos(PHI)
    return float(sy.max() - sy.min())


def echelle_pour(pose):
    """pixels du sprite par unité du modèle pour que la pose donnée (direction 0) ait la hauteur de l'original."""
    place_racine(0, 1.0)
    applique(arm, pose) if pose is not None else [setattr(pb, 'matrix_basis', Matrix.Identity(4))
                                                  for pb in arm.pose.bones]
    bpy.context.view_layer.update()
    return MES['hauteur_px'] / hauteur_ecran(sommets_sil())


ECH = echelle_pour(None)
log('échelle au repos (px par unité)', round(ECH, 3))


# ------------------------------------------------------------------------------------------------ original
def analyse(seq):
    """frise d'origine -> mode de rendu, nombre d'images, clés (images d'origine à imiter) et leur place."""
    info = SEQS[seq]
    tabs = {d: c['table'] for d, c in enumerate(info['cycles']) if c}
    d0 = 0 if 0 in tabs else min(tabs)
    tab = tabs[d0]
    uniq = sorted(set(tab))
    rangs = [uniq.index(x) for x in tab]
    # motif répété : une boucle qui reprend plus haut (… 34 -> 25, 26 …) ou une frise bien plus longue que ses
    # images uniques (attente irrégulière) ; un aller-retour ou des images doublées se jouent d'un trait
    reprise = any(rangs[i + 1] < rangs[i] - 1 and i + 2 < len(rangs) and rangs[i + 2] == rangs[i + 1] + 1
                  for i in range(len(rangs) - 1))
    if len(uniq) == 1:
        mode = 'fixe'
    elif seq == 'TW' or reprise or len(tab) > 2.5 * len(uniq):
        mode = 'table'
    else:
        mode = 'deroule'
    boucle = seq in ('SD', 'SC', 'WK') and mode == 'deroule'
    L = len(tab)
    cles, frac = {}, {}
    for d, t in tabs.items():
        if mode == 'deroule':
            c = list(t); span = float(len(t) if boucle else max(1, len(t) - 1))
            fr = np.arange(len(c)) / span
        elif mode == 'table':
            c = sorted(set(t)); fr = np.arange(len(c)) / max(1.0, len(c) - 1.0)
        else:
            c = [t[0]]; fr = np.zeros(1)
        cles[d] = c; frac[d] = fr
    if mode == 'deroule':
        N = L if seq == 'WK' else max(IMAGES_CIBLES.get(seq, L), L)
        motif = None
        D_out = (N if boucle else N - 1) / 15.0
    elif mode == 'table':
        N = len(uniq)
        motif = [uniq.index(x) for x in tab]
        D_out = max(1, N - 1) / 15.0
    else:
        N, motif, D_out = 1, [0] * L, 0.0
    if seq == 'WK':
        vit = (0.75, 2.3)                  # les marches du jeu sont souvent plus rapides que les captures
    elif boucle:
        vit = (0.6, 1.3)
    elif mode == 'deroule':
        vit = (0.7, 1.4)
    else:
        vit = (0.6, 1.5)
    return dict(mode=mode, boucle=boucle, N=N, motif=motif, cles=cles, frac=frac, D_out=D_out, L=L, vit=vit)


def canevas(seq, d):
    cy = SEQS[seq]['cycles'][d]
    cad = list(cy['cadres'].values())
    gauche = max(c[2] for c in cad) + 6; droite = max(c[0] - c[2] for c in cad) + 6
    haut = max(c[3] for c in cad) + 6; bas = max(c[1] - c[3] for c in cad) + 6
    return gauche + droite, haut + bas, gauche, haut


_cache_m = {}


def masque_orig(seq, d, i, cadre):
    k = (seq, d, i, cadre)
    if k not in _cache_m:
        W, H, ax, ay = cadre
        m = MASQ['%s_d%d_f%d' % (seq, d, i)]
        cx, cyy = MASQ['%s_d%d_f%d_ancre' % (seq, d, i)]
        c = np.zeros((H, W), bool)
        ox, oy = ax - int(cx), ay - int(cyy)
        h, w = m.shape
        x0, y0 = max(0, ox), max(0, oy)
        x1, y1 = min(W, ox + w), min(H, oy + h)
        if x1 > x0 and y1 > y0:
            c[y0:y1, x0:x1] |= m[y0 - oy:y1 - oy, x0 - ox:x1 - ox]
        _cache_m[k] = c
    return _cache_m[k]


def masques_cles(seq, ana, dirs=(0, 4)):
    out = {}
    for d in dirs:
        if d not in ana['cles']:
            continue
        cadre = canevas(seq, d)
        out[d] = ([masque_orig(seq, d, i, cadre) for i in ana['cles'][d]], cadre)
    return out


def couts(cles, sils):
    A = np.array([k.ravel() for k in cles], np.float32)
    B = np.array([s.ravel() for s in sils], np.float32)
    inter = A @ B.T
    uni = A.sum(1)[:, None] + B.sum(1)[None, :] - inter
    return 1.0 - inter / np.maximum(uni, 1.0)


# ------------------------------------------------------------------------------------------------ silhouettes 3D
_cache_src = {}


def source(k):
    if k not in _cache_src:
        if len(_cache_src) > 60:
            _cache_src.clear()
        _cache_src[k] = Source(os.path.join(MOCAP, INDEX[k]['fichier']))
    return _cache_src[k]


def reciblage(src):
    """reciblage d'une capture sur le squelette : la racine est remise à l'identité (direction 0, échelle 1) avant,
    car le reciblage travaille dans le repère du monde (une racine tournée ferait tourner les mouvements)."""
    place_racine(0, 1.0)
    return Reciblage(arm, src, sur_place=True, cap='auto')


_periodes = {}


def periode_marche(src):
    """durée d'un cycle de marche complet (deux pas) de la capture, en images : décalage pour lequel la pose des
    jambes se répète le mieux. On prend le creux le plus bas de l'écart (pose, pose décalée) entre 0,55 et 2,5 s, un
    vrai creux (l'écart y redescend après être monté), sinon la capture n'est pas cyclique et ne sert pas."""
    if src.chemin in _periodes:
        return _periodes[src.chemin]
    ks = [src.idx[n] for n in OS_JAMBES if n in src.idx]
    G = src.GW[ks][:, 1:]
    V = G.reshape(len(ks), G.shape[1], 9).transpose(1, 0, 2).reshape(G.shape[1], -1)
    fps = 1.0 / src.dt
    n = V.shape[0]
    lags = np.arange(1, n)
    d = np.array([float(np.linalg.norm(V[l:] - V[:-l], axis=1).mean()) for l in lags])
    lo, hi = int(0.55 * fps), min(int(2.5 * fps), n - 1)
    best = None
    for i, l in enumerate(lags):
        if l < lo or l > hi:
            continue
        gauche = d[i - 1] if i > 0 else np.inf
        droite = d[i + 1] if i + 1 < len(d) else np.inf
        haut_avant = d[:i].max() if i > 0 else 0.0
        if d[i] <= gauche and d[i] <= droite and d[i] < 0.5 * haut_avant:
            if best is None or d[i] < best[1]:
                best = (float(l), float(d[i]))
    _periodes[src.chemin] = best[0] if best else None
    return _periodes[src.chemin]


POSTURE_OS = (('Spine1', 0.35), ('Spine2', 0.4), ('Neck', 0.25))


def ajoute_posture(P, deg):
    """penche (deg > 0 : vers l'avant) le haut du dos et le cou, réparti sur Spine1, Spine2 et Neck."""
    out = {k: v.copy() for k, v in P.items()}
    if not deg:
        return out
    for nom, part in POSTURE_OS:
        nb = 'mixamorig:' + nom
        if nb not in arm.data.bones:
            continue
        b = arm.data.bones[nb]
        # axe X de l'armature (la gauche du personnage) dans le repère de l'os : rotation positive = vers l'avant
        ax_local = (b.matrix_local.to_3x3().inverted() @ Vector((1, 0, 0))).normalized()
        R = Quaternion(ax_local, math.radians(deg * part)).to_matrix().to_4x4()
        out[nb] = out.get(nb, Matrix.Identity(4)) @ R
    return out


def silhouettes(poses, seq, ech, posture=0.0, dirs=(0, 4)):
    res = {}
    for d in dirs:
        if not SEQS[seq]['cycles'][d]:
            continue
        W, H, ax, ay = canevas(seq, d)
        cadre_camera(W, H, ax, ay)
        place_racine(d, ech)
        ms = []
        for P in poses:
            applique(arm, ajoute_posture(P, posture) if posture else P)
            bpy.context.view_layer.update()
            place_arme(ech)
            ms.append(masque_rendu())
        res[d] = ms
    return res


# ------------------------------------------------------------------------------------------------ alignement
def dtw_bande(C, jl, B, lam=0.04):
    """C (clés x échantillons), jl : position linéaire de chaque clé (en échantillons), B : demi-largeur de bande.
    Chemin monotone (j(r) >= j(r-1)) dans la bande. Renvoie (coût moyen sans pénalité, chemin)."""
    K, S = C.shape
    INF = 1e9
    js = np.arange(S)[None, :]
    ecart = np.abs(js - jl[:, None])
    cc = np.where(ecart <= B, C + lam * ecart / max(B, 1e-6), INF)
    D = np.full((K, S), INF); P = np.zeros((K, S), int)
    D[0] = cc[0]
    for r in range(1, K):
        prev = D[r - 1]
        m = np.minimum.accumulate(prev)
        arg = np.zeros(S, int); cur, ca = INF, 0
        for j in range(S):
            if prev[j] < cur:
                cur, ca = prev[j], j
            arg[j] = ca
        D[r] = cc[r] + m; P[r] = arg
    j = int(np.argmin(D[K - 1]))
    if D[K - 1, j] >= INF:
        return None, None
    ch = [j]
    for r in range(K - 1, 0, -1):
        j = int(P[r, j]); ch.append(j)
    ch.reverse()
    ch = np.array(ch)
    return float(C[np.arange(K), ch].mean()), ch


def cout_lineaire(C, frac, fr, step, starts, L):
    """coût moyen des clés pour chaque début de fenêtre (alignement linéaire, échantillon le plus proche)."""
    pos = starts[:, None] + frac[None, :] * L
    j = np.clip(np.rint((pos - fr[0]) / step).astype(int), 0, len(fr) - 1)
    return C[np.arange(len(frac))[None, :], j].mean(1)


def grossier(k, seq, ana, orig, posture):
    src = source(k)
    fps = 1.0 / src.dt
    n = src.n
    rc = reciblage(src)
    if ana['mode'] == 'fixe':
        step = max(1, int(round(fps / 8)))
        frames = list(range(1, n, step))
        while len(frames) > 90:
            step += 1; frames = list(range(1, n, step))
        sils = silhouettes(rc.poses(frames), seq, ECH, posture)
        tot = np.mean([couts(orig[d][0], sils[d])[0] for d in sils], axis=0)
        j = int(np.argmin(tot))
        return dict(clip=k, cout=float(tot[j]), debut=float(frames[j]), L=0.0, v=1.0, fps=fps)
    Lout = ana['D_out'] * fps
    step = max(1, int(round(Lout / 10)))
    frames = list(range(1, n, step))
    while len(frames) > 90:
        step += 1; frames = list(range(1, n, step))
    if len(frames) < 3:
        return None
    sils = silhouettes(rc.poses(frames), seq, ECH, posture)
    C = {d: couts(orig[d][0], sils[d]) for d in sils}
    fr = np.array(frames, float)
    duree = fr[-1] - fr[0]
    vmin, vmax = ana['vit']
    vs = np.linspace(vmin, vmax, 7)
    if seq == 'WK':                        # marche : un cycle complet (deux pas) de la capture, joué en n images
        P = periode_marche(src)
        if not P or not (vmin <= P / Lout <= vmax):
            return None
        vs = [P / Lout]
    best = None
    for v in vs:
        L = v * Lout
        if L > duree:
            continue
        starts = fr[fr + L <= fr[-1] + 1e-6]
        tot = np.mean([cout_lineaire(C[d], ana['frac'][d], fr, step, starts, L) for d in C], axis=0)
        i = int(np.argmin(tot))
        if best is None or tot[i] < best[0]:
            best = (float(tot[i]), float(starts[i]), float(L), float(v))
    if best is None:                       # capture plus courte que la fenêtre voulue : toute la capture
        v = duree / Lout
        if v < 0.5 * vmin:
            return None
        tot = np.mean([cout_lineaire(C[d], ana['frac'][d], fr, step, fr[:1], duree) for d in C])
        best = (float(tot) + 0.05 * (vmin - v) / vmin, float(fr[0]), float(duree), float(v))
    return dict(clip=k, cout=best[0], debut=best[1], L=best[2], v=best[3], fps=fps)


def fin(g, seq, ana, orig, posture):
    """passe fine : échantillons serrés autour de la fenêtre retenue ; alignement linéaire puis bande."""
    k = g['clip']; src = source(k); n = src.n; fps = g['fps']
    rc = reciblage(src)
    if ana['mode'] == 'fixe':
        lo = int(max(1, g['debut'] - 8)); hi = int(min(n - 1, g['debut'] + 8))
        frames = list(range(lo, hi + 1))
        sils = silhouettes(rc.poses(frames), seq, ECH, posture)
        tot = np.mean([couts(orig[d][0], sils[d])[0] for d in sils], axis=0)
        j = int(np.argmin(tot))
        return dict(g, cout=float(tot[j]), cles_tau=[float(frames[j])], lo=lo, hi=hi)
    Lout = ana['D_out'] * fps
    vmin, vmax = ana['vit']
    L0 = g['L']
    marge = 0.15 * L0 + 3
    lo = int(max(1, math.floor(g['debut'] - marge)))
    hi = int(min(n - 1, math.ceil(g['debut'] + L0 * 1.15 + marge)))
    step = 1 if hi - lo <= 90 else 2
    frames = list(range(lo, hi + 1, step))
    sils = silhouettes(rc.poses(frames), seq, ECH, posture)
    C = {d: couts(orig[d][0], sils[d]) for d in sils}
    fr = np.array(frames, float)
    best = None
    vs = [g['v']] if seq == 'WK' else np.linspace(max(vmin, g['v'] * 0.88), min(vmax, g['v'] * 1.12), 9)
    for v in vs:
        L = min(v * Lout, fr[-1] - fr[0])
        starts = fr[fr + L <= fr[-1] + 1e-6]
        if not len(starts):
            continue
        tot = np.mean([cout_lineaire(C[d], ana['frac'][d], fr, step, starts, L) for d in C], axis=0)
        i = int(np.argmin(tot))
        if best is None or tot[i] < best[0]:
            best = (float(tot[i]), float(starts[i]), float(L))
    debut, L = best[1], best[2]
    # bande : alignement commun aux deux directions (mêmes clés), sinon direction 0 seule
    ds = list(C)
    if len({len(ana['frac'][d]) for d in ds}) > 1:
        ds = [ds[0]]
    Cj = np.mean([C[d] for d in ds], axis=0)
    frac = ana['frac'][ds[0]]
    jl = (debut + frac * L - fr[0]) / step
    cj, ch = dtw_bande(Cj, jl, max(1.5, (0.05 if seq == 'WK' else 0.12) * L / step))
    if ch is None:
        ch = np.clip(np.rint(jl).astype(int), 0, len(fr) - 1); cj = float(Cj[np.arange(len(ch)), ch].mean())
    taus = [float(fr[j]) for j in ch]
    return dict(g, cout=cj, cout_lineaire=best[0], debut=debut, L=L, cles_tau=taus, lo=lo, hi=hi)


# ------------------------------------------------------------------------------------------------ port du corps
def est_tete(m):
    """position horizontale du haut de la silhouette (15 %) par rapport au haut des jambes (62-78 %), en pixels.
    Médianes : un objet tenu (épée pointée devant, à hauteur des mains) ne tire pas la mesure."""
    ys, xs = np.nonzero(m)
    if len(ys) < 30:
        return None
    y0, y1 = ys.min(), ys.max(); h = y1 - y0 + 1
    haut = ys <= y0 + 0.15 * h
    bas = (ys >= y0 + 0.62 * h) & (ys <= y0 + 0.78 * h)
    if not haut.any() or not bas.any():
        return None
    return float(np.median(xs[haut]) - np.median(xs[bas]))


def ecart_profil(seq, ana, poses_cles, deg):
    if 4 not in ana['cles'] or not SEQS[seq]['cycles'][4]:
        return None
    orig = masques_cles(seq, ana, dirs=(4,))[4][0]
    sel = np.linspace(0, len(orig) - 1, min(6, len(orig))).round().astype(int)
    eo = [est_tete(orig[i]) for i in sel]
    sils = silhouettes([poses_cles[i] for i in sel], seq, ECH, deg, dirs=(4,))[4]
    er = [est_tete(m) for m in sils]
    pares = [(x, y) for x, y in zip(er, eo) if x is not None and y is not None]
    if not pares:
        return None
    return float(np.mean([x - y for x, y in pares]))


def cherche_posture(seq, ana, poses_cles, base, ecart_max):
    """angle (degrés) qui ramène la tête à la place de l'original (vue de profil), autour de base."""
    vus = {}

    def f(deg):
        if deg not in vus:
            vus[deg] = ecart_profil(seq, ana, poses_cles, deg)
        return vus[deg]
    grille = [base + x for x in np.arange(-ecart_max, ecart_max + 0.1, 5.0)]
    ok = [(abs(f(g)), g) for g in grille if f(g) is not None]
    if not ok:
        return base, None
    _, g0 = min(ok)
    for g in (g0 - 2.5, g0 + 2.5):
        if f(g) is not None:
            ok.append((abs(f(g)), g))
    e, g = min(ok)
    return float(g), round(float(f(g)), 2)


def cale_roulis(seq, ana, poses_cles, posture, autour=None):
    """roulis de l'arme autour de l'axe de la main qui recouvre le mieux l'original (quatre directions)."""
    global ROULIS
    dirs = tuple(d for d in (0, 2, 4, 6) if d in ana['cles'])
    orig = masques_cles(seq, ana, dirs=dirs)
    sel = np.linspace(0, len(poses_cles) - 1, min(5, len(poses_cles))).round().astype(int)
    grille = list(range(0, 360, 45)) if autour is None else [autour + x for x in (-20, -10, 0, 10, 20)]
    best = None
    for r in grille:
        ROULIS = float(r)
        sils = silhouettes([poses_cles[i] for i in sel], seq, ECH, posture, dirs=dirs)
        c = np.mean([np.mean([couts([orig[d][0][i]], [sils[d][k]])[0, 0] for k, i in enumerate(sel)])
                     for d in sils if d in orig])
        log('  roulis %4d° coût %.3f' % (r, c))
        if best is None or c < best[1]:
            best = (float(r) % 360, c)
    ROULIS = best[0]
    return best[0]


# ------------------------------------------------------------------------------------------------ choix
def choisit(seq, ana, posture, interdits=()):
    orig = masques_cles(seq, ana)
    cands = [c for c in candidats(seq) if c not in interdits] or candidats(seq)
    log(seq, ana['mode'], 'N', ana['N'], len(cands), 'candidats')
    gros = []
    for k in cands:
        try:
            r = grossier(k, seq, ana, orig, posture)
        except Exception as e:  # noqa: BLE001
            log('  erreur', k, repr(e)[:160]); continue
        if r:
            gros.append(r)
            log('  %-58s %.3f  v %.2f' % (k[:58], r['cout'], r['v']))
    if not gros:
        return None
    gros.sort(key=lambda r: r['cout'])
    fins = []
    for g in gros[:FINS]:
        try:
            r = fin(g, seq, ana, orig, posture)
        except Exception as e:  # noqa: BLE001
            log('  erreur fine', g['clip'], repr(e)[:160]); continue
        r['penalite'] = penalite_marche(r, ana) if seq == 'WK' else 0.0
        fins.append(r)
        log('  fin %-54s %.3f (+%.3f)' % (g['clip'][:54], r['cout'], r['penalite']))
    fins.sort(key=lambda r: r['cout'] + r['penalite'])
    best = dict(fins[0])
    best['autres'] = [{'clip': r['clip'], 'cout': round(r['cout'], 4)} for r in (fins[1:] + gros[FINS:FINS + 4])]
    best.update(mode=ana['mode'], n=ana['N'], boucle=ana['boucle'], motif=ana['motif'])
    log('=>', seq, best['clip'], 'coût %.3f' % best['cout'], 'images %.1f - %.1f' % (best['cles_tau'][0],
                                                                                     best['cles_tau'][-1]))
    return best


# ------------------------------------------------------------------------------------------------ marche
def vitesse_pied_capture(c, P):
    """vitesse (pixels du sprite par image du jeu) à laquelle le pied d'appui recule pour un cycle de P images de la
    capture joué en n images du jeu : déplacement des hanches de la capture sur le cycle, à l'échelle du monstre."""
    src = source(c['clip'])
    rc = reciblage(src)
    i = src.idx['Hips']
    t0 = c['cles_tau'][0]
    t1 = min(src.n - 1, t0 + P)
    p0 = np.array([np.interp(t0, np.arange(src.n), src.PW[i, :, k]) for k in (0, 1)])
    p1 = np.array([np.interp(t1, np.arange(src.n), src.PW[i, :, k]) for k in (0, 1)])
    return float(np.hypot(*(p1 - p0)) * rc.ECH * ECH / max(1, c['n']))


def penalite_marche(r, ana):
    vo = MES.get('vitesse_pied_px')
    if not vo:
        return 0.0
    r2 = dict(r, n=ana['N'])
    P = r['L']
    vc = vitesse_pied_capture(r2, P)
    if vc <= 1e-6:
        return 0.3
    s = vo / vc
    sc_ = min(1.4, max(0.6, s))
    return 0.8 * abs(math.log(s / sc_)) + 0.08 * abs(math.log(sc_))


# ------------------------------------------------------------------------------------------------ poses finales
def pose_distance_source(src, ta, tb, noms):
    ks = [src.idx[n] for n in noms if n in src.idx]

    def g(t):
        i = int(math.floor(t)); w = t - i; i2 = min(i + 1, src.n - 1)
        return np.concatenate([((1 - w) * src.GW[k, i] + w * src.GW[k, i2]).ravel() for k in ks])
    return float(np.linalg.norm(g(ta) - g(tb)))


OS_JAMBES = ('LeftUpLeg', 'RightUpLeg', 'LeftLeg', 'RightLeg', 'LeftFoot', 'RightFoot')
OS_CORPS = ('Hips', 'Spine', 'Spine1', 'Spine2', 'Neck', 'Head', 'LeftArm', 'RightArm', 'LeftForeArm',
            'RightForeArm') + OS_JAMBES


def periode_boucle(c, seq, ana):
    """durée (images de la capture) du cycle : la pose revient à celle du début (marche : jambes ; attente : corps)."""
    src = source(c['clip'])
    t0 = c['cles_tau'][0]
    L = c['L']
    vmin, vmax = ana['vit']
    Lout = ana['D_out'] * c['fps']
    e = 0.05 if seq == 'WK' else 0.15
    bas, haut = max((1 - e) * L, vmin * Lout), min((1 + e) * L, vmax * Lout, src.n - 1 - t0)
    if haut <= bas:
        return min(L, src.n - 1 - t0)
    noms = OS_JAMBES if seq == 'WK' else OS_CORPS
    best = None
    for P in np.arange(bas, haut + 1e-6, 0.25):
        dd = pose_distance_source(src, t0, t0 + P, noms)
        if best is None or dd < best[1]:
            best = (float(P), dd)
    return best[0]


def temps_sortie(c, ana):
    """temps (images de la capture) de chaque image rendue."""
    tau = np.array(c['cles_tau'], float)
    if ana['mode'] == 'fixe':
        return [float(tau[0])]
    if ana['mode'] == 'table':
        return [float(x) for x in tau]
    N = ana['N']
    K = len(tau)
    if ana['boucle']:
        P = c['periode']
        x = np.append(np.arange(K, dtype=float), float(K))
        s = P / max(c['L'], 1e-6)
        tau = tau[0] + (tau - tau[0]) * s
        y = np.append(tau, tau[0] + P)
        T = np.arange(N) * K / float(N)
        return [float(v) for v in np.interp(T, x, y)]
    T = np.arange(N) * (K - 1) / float(max(1, N - 1))
    return [float(v) for v in np.interp(T, np.arange(K, dtype=float), tau)]


def poses_aux_temps(c, temps):
    src = source(c['clip'])
    lo = int(max(1, min(c['lo'], math.floor(min(temps)))))
    hi = int(min(src.n - 1, max(c['hi'], math.ceil(max(temps)) + 1)))
    rc = reciblage(src)
    P = rc.poses(list(range(lo, hi + 1)))
    return [interpole(P, t - lo) for t in temps], rc


def _q(L):
    return L.to_quaternion()


def ferme_boucle(poses, fin_):
    """répartit sur le cycle l'écart entre la pose qui suit la dernière image et la première (rotation de chaque
    os, translation des hanches) : la boucle se referme sans saut."""
    N = len(poses)
    out = []
    for k, P in enumerate(poses):
        w = k / float(N)
        Q = {}
        for nb, L in P.items():
            l0, q0, _ = poses[0][nb].decompose()
            le, qe, _ = fin_[nb].decompose()
            D = q0 @ qe.inverted()
            if D.w < 0:
                D.negate()
            lk, qk, _ = L.decompose()
            q = Quaternion((1, 0, 0, 0)).slerp(D, w) @ qk
            M = q.to_matrix().to_4x4(); M.translation = lk + (l0 - le) * w
            Q[nb] = M
        out.append(Q)
    return out


def ajuste_foulee(poses, s):
    """foulée multipliée par s (jambes : écart à la pose moyenne du cycle)."""
    if abs(s - 1.0) < 0.03:
        return poses
    noms = [nb for nb in poses[0] if any(x in nb for x in ('UpLeg', 'Leg', 'Foot', 'ToeBase'))]
    for nb in noms:
        qs = [P[nb].to_quaternion() for P in poses]
        ref = qs[0]
        acc = np.zeros(4)
        for q in qs:
            v = np.array(q); acc += v if np.dot(v, np.array(ref)) >= 0 else -v
        moy = Quaternion(acc / np.linalg.norm(acc))
        for P, q in zip(poses, qs):
            rel = moy.inverted() @ q
            ax, ang = rel.to_axis_angle()
            if ang > math.pi:
                ang -= 2 * math.pi
            q2 = moy @ Quaternion(ax, ang * s)
            loc = P[nb].translation.copy()
            M = q2.to_matrix().to_4x4(); M.translation = loc
            P[nb] = M
    return poses


def amplitude(masques):
    return float(np.mean([1 - np.logical_and(masques[0], m).sum() / max(1, np.logical_or(masques[0], m).sum())
                          for m in masques]))


def amortit(poses, seq, ana, posture):
    """attente et garde : mouvement ramené à l'amplitude de l'original (vue de face)."""
    orig = masques_cles(seq, ana, dirs=(0,))
    if 0 not in orig:
        return poses, 1.0
    o = orig[0][0]
    a_o = amplitude(o)
    sel = poses[::max(1, len(poses) // 8)]
    a_c = amplitude(silhouettes(sel, seq, ECH, posture, dirs=(0,))[0])
    f = 1.0 if a_c <= 1e-6 else min(1.0, max(0.15, a_o / a_c))
    if f < 0.98:
        moy = poses[0]
        for P in poses:
            for nb, L in P.items():
                if 'UpLeg' in nb or nb.endswith('Leg') or 'Foot' in nb or 'Toe' in nb:
                    continue
                q = moy[nb].to_quaternion().slerp(L.to_quaternion(), f)
                M = q.to_matrix().to_4x4(); M.translation = moy[nb].translation.lerp(L.translation, f)
                P[nb] = M
    return poses, round(f, 3)


def prepare_poses(seq, c, ana, posture_glob):
    """poses finales (liste de N poses, posture comprise) d'une séquence. Toutes les poses d'une séquence viennent
    d'un même reciblage (même retrait de la dérive des hanches), images supplémentaires comprises."""
    temps = temps_sortie(c, ana)
    if ana['boucle']:
        tout, _ = poses_aux_temps(c, temps + [temps[0] + c['periode']])
        if seq == 'WK' and MES.get('vitesse_pied_px'):
            vc = vitesse_pied_capture(c, c['periode'])
            s = min(1.4, max(0.6, MES['vitesse_pied_px'] / vc)) if vc > 1e-6 else 1.0
            c['foulee'] = round(s, 3); c['vitesse_pied_capture'] = round(vc, 3)
            tout = ajuste_foulee(tout, s)
        poses = ferme_boucle(tout[:-1], tout[-1])
    elif ana['mode'] == 'table':
        suiv = {}
        paires = list(zip(ana['motif'], ana['motif'][1:]))
        if seq in ('SD', 'SC'):              # attente à frise irrégulière : elle boucle aussi de la fin au début
            paires.append((ana['motif'][-1], ana['motif'][0]))
        for x, y in paires:
            if y < x - 1:
                pas = (c['cles_tau'][x] - c['cles_tau'][y]) / max(1, x - y)
                suiv[(y, x)] = min(source(c['clip']).n - 1, c['cles_tau'][x] + pas)
        cles_suiv = sorted(suiv)
        tout, _ = poses_aux_temps(c, temps + [suiv[k] for k in cles_suiv])
        poses = tout[:len(temps)]
        for k, (y, x) in enumerate(cles_suiv):     # chaque segment rejoué (… 34 -> 25 …) se referme sans saut
            if x > y:
                poses[y:x + 1] = ferme_boucle(poses[y:x + 1], tout[len(temps) + k])
    else:
        poses, _ = poses_aux_temps(c, temps)
    deg = c.get('posture', posture_glob)
    poses = [ajoute_posture(P, deg) for P in poses]
    if seq in ('SD', 'SC'):
        poses, c['amortissement'] = amortit(poses, seq, ana, 0.0)
    return poses


def poses_des_cles(c, ana):
    """poses (sans posture) aux temps des clés d'origine, pour mesurer le port du corps."""
    tau = c['cles_tau']
    if ana['boucle'] and 'periode' in c:
        s = c['periode'] / max(c['L'], 1e-6)
        tau = [tau[0] + (t - tau[0]) * s for t in tau]
    P, _ = poses_aux_temps(c, tau)
    return P


# ------------------------------------------------------------------------------------------------ programme
choix = lit_json(os.path.join(OUT, 'choix.json'), {})
glob = choix.setdefault('_global', {})
ANA = {s: analyse(s) for s in SEQS}
ordre = [s for s in ('SD', 'SC', 'WK', 'GH', 'DE', 'A1', 'A2', 'A3', 'A4', 'A5', 'SP', 'CA', 'TW') if s in SEQS]
a_faire = [s for s in ordre if not SEULES or s in SEULES]
base = 'SD' if 'SD' in SEQS and not SEQS['SD'].get('copie_de') else (SEQS['SD'].get('copie_de') if 'SD' in SEQS
                                                                       else 'SC')
POSTURE = glob.get('posture', 0.0)
ROULIS = glob.get('arme_roulis', 0.0)
if glob.get('echelle_px'):
    ECH = glob['echelle_px']


def enregistre():
    ecrit_json(os.path.join(OUT, 'choix.json'), choix)


def deja_fait(s):
    return s in choix and 'cles_tau' in choix[s] and not (SEULES and s in SEULES)


# 1) attente (séquence de base) : mouvement, port du corps, échelle définitive
if base in a_faire and not deja_fait(base):
    ana = ANA[base]
    c = choisit(base, ana, 0.0)
    if ana['boucle']:
        c['periode'] = periode_boucle(c, base, ana)
    if arme_obj is not None:           # objet tenu : son orientation dans la main d'abord (il pèse dans les silhouettes)
        ROULIS = cale_roulis(base, ana, poses_des_cles(c, ana), 0.0)
        log('arme : roulis', ROULIS, '°')
    Pk = poses_des_cles(c, ana)
    deg, e = cherche_posture(base, ana, Pk, 20.0, 40.0)
    if abs(deg) >= 10 or arme_obj is not None:
        # port très différent de la capture, ou objet tenu : le choix est refait avec ce port et cette prise
        log('port du corps provisoire', deg, '° : nouveau choix de l\'attente avec ce port')
        c = choisit(base, ana, deg)
        if ana['boucle']:
            c['periode'] = periode_boucle(c, base, ana)
        if arme_obj is not None:
            ROULIS = cale_roulis(base, ana, poses_des_cles(c, ana), deg, autour=ROULIS)
            log('arme : roulis retenu', ROULIS, '°')
        Pk = poses_des_cles(c, ana)
        deg, e = cherche_posture(base, ana, Pk, deg, 10.0)
    POSTURE = deg
    if arme_obj is not None:
        glob['arme_roulis'] = ROULIS
    c['posture'] = deg; c['ecart_profil_px'] = e
    poses0 = prepare_poses(base, c, ana, deg)
    ECH = echelle_pour(poses0[0])
    glob.update(posture=deg, echelle_px=ECH, base=base)
    choix[base] = c
    log('port du corps', deg, '° (écart de la tête de profil %s px), échelle %.3f px/unité' % (e, ECH))
    enregistre()

# 2) autres séquences
deja = {choix[s]['clip'] for s in choix if not s.startswith('_') and 'clip' in choix[s] and s[0] == 'A'}
for seq in ordre:
    if seq == base or seq not in a_faire or seq == 'TW':
        continue
    info = SEQS[seq]
    if info.get('copie_de'):
        choix[seq] = {'copie_de': info['copie_de']}
        continue
    if deja_fait(seq):
        continue
    ana = ANA[seq]
    if ana['mode'] == 'fixe':
        continue                                    # plus bas : image unique reprise d'une autre séquence
    interdits = deja if (seq.startswith('A') or seq in ('SP', 'CA')) else ()
    c = choisit(seq, ana, POSTURE, interdits)
    if c is None:
        log('aucun candidat pour', seq); continue
    if ana['boucle']:
        c['periode'] = periode_boucle(c, seq, ana)
    if seq in ('SC', 'WK'):           # séquences debout et calmes : la tête se mesure bien de profil
        Pk = poses_des_cles(c, ana)
        deg, e = cherche_posture(seq, ana, Pk, POSTURE, 10.0)
        c['posture'] = deg; c['ecart_profil_px'] = e
        log('  port du corps', seq, deg, '° (écart %s px)' % e)
    else:
        c['posture'] = POSTURE
    if seq.startswith('A') or seq in ('SP', 'CA'):
        deja.add(c['clip'])
    choix[seq] = c
    enregistre()


# 3) images uniques (au sol, attaques à une image...) : reprises de la séquence d'origine la plus ressemblante
def image_la_plus_proche(seq, ana, sources):
    """(ressemblance, séquence, indice de clé) de l'image d'origine la plus proche de l'image unique de seq, parmi
    les séquences déjà choisies (silhouettes de face et de profil, posées sur le même canevas par leur ancre)."""
    best = None
    for s2 in sources:
        if s2 not in choix or 'cles_tau' not in choix[s2] or choix[s2].get('mode') == 'fixe':
            continue
        a2 = ANA[s2]
        sims = []
        for d in (0, 4):
            if d not in ana['cles'] or d not in a2['cles'] or len(a2['cles'][d]) != len(a2['cles'][min(a2['cles'])]):
                continue
            cadre = canevas(seq, d)
            m = masque_orig(seq, d, ana['cles'][d][0], cadre)
            o2d = [masque_orig(s2, d, i, cadre) for i in a2['cles'][d]]
            sims.append(1.0 - couts([m], o2d)[0])
        if not sims:
            continue
        sim = np.mean(sims, axis=0)
        j = int(np.argmax(sim))
        if best is None or sim[j] > best[0]:
            best = (float(sim[j]), s2, j)
    return best


for seq in ordre:
    if seq not in a_faire or seq == base or SEQS[seq].get('copie_de') or deja_fait(seq):
        continue
    ana = ANA[seq]
    if seq == 'TW' and 'DE' in choix and 'cles_tau' in choix['DE']:
        # au sol : chaque image unique est la pose de la mort la plus ressemblante
        de = choix['DE']; ade = ANA['DE']
        taus = []
        d0 = 0 if (0 in ana['cles'] and 0 in ade['cles']) else min(set(ana['cles']) & set(ade['cles']))
        for d in (d0,):
            cadre = canevas(seq, d)
            for i in ana['cles'][d]:
                m = masque_orig(seq, d, i, cadre)
                o2 = [masque_orig('DE', d, j, cadre) for j in ade['cles'][d]]
                sim = 1.0 - couts([m], o2)[0]
                r = int(np.argmax(sim))
                taus.append(de['cles_tau'][r] if sim[r] > 0.45 else de['cles_tau'][-1])
        choix['TW'] = dict(clip=de['clip'], cles_tau=taus, lo=de['lo'], hi=de['hi'], fps=de['fps'], L=0.0,
                           mode=ana['mode'], n=ana['N'], boucle=False, motif=ana['motif'], posture=de['posture'],
                           cout=None, repris_de='DE')
        log('au sol (TW) :', len(taus), 'images reprises de la mort', [round(t, 1) for t in taus])
        enregistre()
        continue
    if ana['mode'] != 'fixe':
        continue
    b = image_la_plus_proche(seq, ana, [s for s in ordre if s != seq])
    if b and b[0] >= 0.6:
        s2 = b[1]; c2 = choix[s2]
        choix[seq] = dict(clip=c2['clip'], cles_tau=[c2['cles_tau'][b[2]]], lo=c2['lo'], hi=c2['hi'], fps=c2['fps'],
                          L=0.0, mode='fixe', n=1, boucle=False, motif=ana['motif'], posture=c2.get('posture', POSTURE),
                          cout=round(1 - b[0], 4), repris_de=s2)
        log('image unique', seq, 'reprise de', s2, 'clé', b[2], 'ressemblance %.2f' % b[0])
    else:
        c = choisit(seq, ana, POSTURE)
        if c is None:
            continue
        c['posture'] = POSTURE
        choix[seq] = c
    enregistre()

# 4) écriture des animations
choix_seqs = [s for s in ordre if s in choix and 'cles_tau' in choix[s]]
planche = []
for seq in choix_seqs:
    if SEULES and seq not in SEULES and os.path.exists(os.path.join(OUT, 'anims', seq + '.blend')):
        continue
    c = choix[seq]; ana = ANA[seq]
    poses = prepare_poses(seq, c, ana, POSTURE)
    for pb in arm.pose.bones:
        pb.matrix_basis = Matrix.Identity(4)
    act = ecrit_action(arm, poses, seq, fps=15)
    p = os.path.join(OUT, 'anims', seq + '.blend')
    if os.path.exists(p):
        os.remove(p)
    bpy.data.libraries.write(p, {act}, fake_user=True)     # l'action seule : le rendu charge rig/rig.blend
    arm.animation_data_clear()
    bpy.data.actions.remove(act)
    c.update(fichier=p, n=len(poses), boucle=ana['boucle'], mode=ana['mode'], motif=ana['motif'],
             temps=[round(t, 3) for t in temps_sortie(c, ana)])
    log('animation', seq, ana['mode'], len(poses), 'images ->', os.path.basename(p))
    # planche : 6 clés de l'original et les silhouettes 3D aux mêmes instants (face, profil)
    orig = masques_cles(seq, ana)
    K = len(ana['cles'][0]) if 0 in ana['cles'] else 1
    sel = sorted(set(np.linspace(0, K - 1, min(6, K)).round().astype(int).tolist()))
    if ana['mode'] in ('deroule',) and not ana['boucle']:
        img_de = [int(round(r * (len(poses) - 1) / max(1, K - 1))) for r in sel]
    elif ana['boucle']:
        img_de = [int(round(r * len(poses) / float(K))) % len(poses) for r in sel]
    else:
        img_de = sel
    sils = silhouettes([poses[i] for i in img_de], seq, ECH, 0.0)
    planche.append((seq, [(orig[d][0][r], sils[d][k]) for d in sorted(sils) for k, r in enumerate(sel)
                          if d in orig]))
    enregistre()


def sauve_planche(rows, chemin):
    """silhouettes de la planche de contrôle (original | 3D), dessinées ensuite par controle.py (hors de Blender)."""
    d = {}
    for seq, paires in rows:
        for k, (o, s_) in enumerate(paires):
            d['%s__%d__o' % (seq, k)] = o; d['%s__%d__s' % (seq, k)] = s_
    if d:
        np.savez_compressed(chemin, **d)


sauve_planche(planche, os.path.join(OUT, 'planche.npz'))
enregistre()
log('FINI')
