# auto_rig.py - Silicon Coast, chaîne des monstres 3D : squelette et peau automatiques (sans Mixamo).
#
#   blender -b -P auto_rig.py -- <modele.glb> <sortie.blend> [--hauteur 2.0] [--rapport rig.json]
#                                [--images dossier] [--voxel 0.012]
#
# 1. Importe le modèle (GLB de TRELLIS), réunit les morceaux, retire les poussières, le pose debout au sol,
#    face à -Y (le sens est vérifié : les pieds dépassent vers l'avant), hauteur fixe.
# 2. Silhouettes de face et de profil (rendus Workbench orthographiques) ; repères comme ceux qu'on place à la main
#    dans Mixamo : entrejambe, hanches, genoux, chevilles, pointes des pieds, aisselles, épaules, coudes, poignets,
#    bouts des mains, cou, tête. Personnage en pose en A ou en T (bras écartés du corps).
# 3. Squelette aux noms et à la hiérarchie de Mixamo (mixamorig:Hips ... sans doigts), lisible par les outils de
#    reciblage et de rendu de la chaîne.
# 4. Poids par diffusion de chaleur sur une copie remaillée (étanche) puis transférés au maillage d'origine ;
#    4 os au plus par sommet, normalisés.
# 5. Contrôle : pose d'essai (bras baissés, coudes et genoux pliés, torsion du buste, tête tournée) ; étirement des
#    arêtes, sommets sans poids, sommets portés par un os éloigné -> rapport JSON et images (repos | essai).
import json
import math
import os
import sys

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

a = sys.argv[sys.argv.index('--') + 1:]
SRC, OUT = os.path.abspath(a[0]), os.path.abspath(a[1])
opt = lambda n, d, c=float: c(a[a.index(n) + 1]) if n in a else d
HAUT = opt('--hauteur', 2.0)
RAPPORT = opt('--rapport', os.path.splitext(OUT)[0] + '_rig.json', str)
IMAGES = opt('--images', os.path.splitext(OUT)[0] + '_rig', str)
VOXEL = opt('--voxel', 0.0, float)
os.makedirs(IMAGES, exist_ok=True)
P = 'mixamorig:'
rapport = {'source': SRC}


def log(*x):
    print('[auto_rig]', *x, flush=True)


# ------------------------------------------------------------------------------------------------ 1. import
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
avant = set(bpy.data.objects)
if SRC.lower().endswith(('.glb', '.gltf')):
    bpy.ops.import_scene.gltf(filepath=SRC, merge_vertices=True)
elif SRC.lower().endswith('.fbx'):
    bpy.ops.import_scene.fbx(filepath=SRC)
else:
    bpy.ops.wm.obj_import(filepath=SRC)
nouv = [o for o in bpy.data.objects if o not in avant]
mailles = [o for o in nouv if o.type == 'MESH']
bpy.ops.object.select_all(action='DESELECT')
for o in mailles:
    o.select_set(True)
bpy.context.view_layer.objects.active = mailles[0]
bpy.ops.object.parent_clear(type='CLEAR_KEEP_TRANSFORM')
if len(mailles) > 1:
    bpy.ops.object.join()
corps = bpy.context.view_layer.objects.active
for o in nouv:
    if o != corps and o.name in bpy.data.objects:
        bpy.data.objects.remove(o, do_unlink=True)
corps.name = 'SC_corps'
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)


def sommets(ob):
    n = len(ob.data.vertices)
    co = np.empty(n * 3)
    ob.data.vertices.foreach_get('co', co)
    return co.reshape(n, 3)


def retire_poussieres(ob, frac=0.006):
    bm = bmesh.new(); bm.from_mesh(ob.data)
    bm.verts.ensure_lookup_table()
    vu = set(); comps = []
    for v in bm.verts:
        if v.index in vu:
            continue
        pile = [v]; comp = []; vu.add(v.index)
        while pile:
            u = pile.pop(); comp.append(u)
            for e in u.link_edges:
                w = e.other_vert(u)
                if w.index not in vu:
                    vu.add(w.index); pile.append(w)
        comps.append(comp)
    co = sommets(ob)
    H = co[:, 2].max() - co[:, 2].min()
    petits = []
    for c in comps:
        pts = np.array([v.co for v in c])
        if (pts.max(0) - pts.min(0)).max() < frac * H:
            petits.append(c)
    bmesh.ops.delete(bm, geom=[v for c in petits for v in c], context='VERTS')
    bm.to_mesh(ob.data); bm.free()
    return len(comps), len(petits)


nc, np_ = retire_poussieres(corps)
log('morceaux', nc, 'poussières retirées', np_)


def pose_debout(ob, rotz=0.0):
    co = sommets(ob)
    lo, hi = co.min(0), co.max(0)
    s = HAUT / (hi[2] - lo[2])
    c = Vector(((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]))
    M = Matrix.Rotation(math.radians(rotz), 4, 'Z') @ Matrix.Scale(s, 4) @ Matrix.Translation(-c)
    ob.data.transform(M); ob.data.update()


pose_debout(corps)
# sens : les pieds dépassent vers l'avant (-Y) par rapport aux tibias
co = sommets(corps)
bas = co[co[:, 2] < 0.04 * HAUT]
tib = co[(co[:, 2] > 0.12 * HAUT) & (co[:, 2] < 0.2 * HAUT)]
avant_pieds = np.median(bas[:, 1]) - np.median(tib[:, 1]) if len(bas) and len(tib) else -1
if avant_pieds > 0.01 * HAUT:
    pose_debout(corps, 180.0)
    log('modèle retourné (face à -Y)')
rapport['retourne'] = bool(avant_pieds > 0.01 * HAUT)
co = sommets(corps)
log('sommets', len(co), 'faces', len(corps.data.polygons))


def applique(ob, mod):
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.modifier_apply(modifier=mod.name)


def garde_plus_grande(ob):
    """ne garde que la plus grande composante (enveloppe extérieure) : les coques intérieures du remaillage
    (cavités entre le corps et les vêtements) empêchent la diffusion de chaleur de voir les os."""
    bm = bmesh.new(); bm.from_mesh(ob.data); bm.verts.ensure_lookup_table()
    vu = set(); comps = []
    for v in bm.verts:
        if v.index in vu:
            continue
        pile = [v]; comp = []; vu.add(v.index)
        while pile:
            u = pile.pop(); comp.append(u)
            for e in u.link_edges:
                w = e.other_vert(u)
                if w.index not in vu:
                    vu.add(w.index); pile.append(w)
        comps.append(comp)
    comps.sort(key=len, reverse=True)
    garde = set(v.index for v in comps[0])
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if v.index not in garde], context='VERTS')
    bm.to_mesh(ob.data); bm.free()
    return len(comps)


# maillage de calcul : coque épaissie (les modèles de TRELLIS ont des bords ouverts et des surfaces simples, que le
# remaillage en voxels morcelle), remaillée en voxels, plus grande composante seulement. Si elle ne couvre pas toute
# la hauteur du modèle, le remaillage est refait plus grossier.
vox = VOXEL or HAUT / 120
for essai in range(4):
    proxy = corps.copy(); proxy.data = corps.data.copy(); proxy.name = 'SC_proxy'
    sc.collection.objects.link(proxy)
    so = proxy.modifiers.new('so', 'SOLIDIFY'); so.thickness = 1.5 * vox; so.offset = 0.0
    applique(proxy, so)
    rm = proxy.modifiers.new('rm', 'REMESH'); rm.mode = 'VOXEL'; rm.voxel_size = vox; rm.adaptivity = 0
    applique(proxy, rm)
    ncomp = garde_plus_grande(proxy)
    cz = sommets(proxy)[:, 2]
    haut_proxy = float(cz.max() - cz.min()) if len(cz) else 0.0
    log('maillage de calcul (voxel %.4f)' % vox, len(proxy.data.vertices), 'sommets ;', ncomp - 1,
        'coques intérieures retirées ; hauteur %.2f H' % (haut_proxy / HAUT))
    if haut_proxy >= 0.95 * HAUT and len(proxy.data.vertices) > 2000:
        break
    bpy.data.objects.remove(proxy, do_unlink=True)
    vox *= 1.5
rapport['voxel'] = vox
from mathutils.bvhtree import BVHTree  # noqa: E402
BVH = BVHTree.FromObject(proxy, bpy.context.evaluated_depsgraph_get())


# ------------------------------------------------------------------------------------------------ 2. silhouettes
def rendu_masque(ob, vue, res=512):
    """silhouette orthographique (Workbench) : vue 'face' (caméra en -Y) ou 'profil' (caméra en +X).
    Renvoie le masque (res x res, ligne 0 en haut) et la fonction pixel -> monde."""
    lo, hi = sommets(ob).min(0), sommets(ob).max(0)
    taille = 1.08 * max(hi - lo)
    cx, cy, cz = (lo + hi) / 2
    cam_d = bpy.data.cameras.new('cm'); cam_d.type = 'ORTHO'; cam_d.ortho_scale = taille
    cam = bpy.data.objects.new('cm', cam_d); sc.collection.objects.link(cam)
    if vue == 'face':
        cam.location = (cx, cy - 10, cz); cam.rotation_euler = (math.radians(90), 0, 0)
    else:
        cam.location = (cx + 10, cy, cz); cam.rotation_euler = (math.radians(90), 0, math.radians(90))
    sc.camera = cam
    sc.render.engine = 'BLENDER_WORKBENCH'
    sc.display.shading.light = 'FLAT'
    sc.display.shading.color_type = 'SINGLE'
    sc.display.shading.single_color = (1, 1, 1)
    sc.display.shading.show_shadows = False
    sc.display.shading.show_cavity = False
    sc.display.render_aa = 'OFF'
    sc.render.film_transparent = False
    w = sc.world or bpy.data.worlds.new('w'); sc.world = w
    w.color = (0, 0, 0)
    sc.view_settings.view_transform = 'Standard'
    sc.render.resolution_x = sc.render.resolution_y = res
    sc.render.resolution_percentage = 100
    p = os.path.join(IMAGES, 'masque_%s.png' % vue)
    sc.render.filepath = p
    bpy.ops.render.render(write_still=True)
    img = bpy.data.images.load(p)
    px = np.empty(res * res * 4, np.float32); img.pixels.foreach_get(px)
    m = px.reshape(res, res, 4)[::-1, :, 0] > 0.5            # ligne 0 en haut
    bpy.data.images.remove(img)
    bpy.data.objects.remove(cam, do_unlink=True)

    def vers_monde(u, v):     # u : colonne (gauche -> droite), v : ligne (haut -> bas) -> (h, z) monde
        hh = (u + 0.5) / res - 0.5
        zz = 0.5 - (v + 0.5) / res
        if vue == 'face':
            return cx + hh * taille, cz + zz * taille       # h = X (droite de l'image = +X)
        return cy + hh * taille, cz + zz * taille           # profil : droite de l'image = +Y (dos)

    def ligne_de(z):
        return int(round((0.5 - (z - cz) / taille) * res - 0.5))

    def col_de(h):
        c0 = cx if vue == 'face' else cy
        return int(round(((h - c0) / taille + 0.5) * res - 0.5))
    return m, vers_monde, ligne_de, col_de


corps.hide_render = True
MF, f_monde, f_ligne, f_col = rendu_masque(proxy, 'face')
MP, p_monde, p_ligne, p_col = rendu_masque(proxy, 'profil')
corps.hide_render = False
proxy.hide_render = True


def runs(row):
    """segments pleins d'une ligne de masque : [(début, fin)] (fin incluse)."""
    r = np.concatenate([[0], row.astype(np.int8), [0]])
    d = np.diff(r)
    return list(zip(np.nonzero(d == 1)[0], np.nonzero(d == -1)[0] - 1))


H = HAUT
c0 = f_col(0.0)                                   # colonne du milieu (x = 0)


def z_de_ligne(v):
    return f_monde(0, v)[1]


# ---- entrejambe : en montant depuis les pieds, première ligne où le milieu est plein (au-dessus de 0,25 H)
lig_bas = f_ligne(0.03 * H); lig_haut = f_ligne(0.75 * H)
entre = None
for v in range(lig_bas, lig_haut, -1):
    rs = runs(MF[v])
    plein = any(s <= c0 <= e for s, e in rs)
    if plein and z_de_ligne(v) > 0.25 * H:
        entre = z_de_ligne(v); break
    if plein and z_de_ligne(v) <= 0.25 * H:
        entre = None                              # robe : le milieu est plein dès le bas
        break
robe = entre is None
if robe:
    entre = 0.46 * H
rapport['robe'] = robe
log('entrejambe %.3f H' % (entre / H), '(robe : jambes cachées)' if robe else '')


def centre_jambes(z):
    """centres (x) des deux jambes juste sous z (segments de part et d'autre du milieu)."""
    v = f_ligne(z)
    rs = runs(MF[v])
    g = [r for r in rs if r[1] < c0]; d = [r for r in rs if r[0] > c0]
    if robe or not g or not d:
        lo, hi = sommets(corps).min(0), sommets(corps).max(0)
        return -0.09 * H, 0.09 * H
    rg = max(g, key=lambda r: r[1]); rd = min(d, key=lambda r: r[0])   # les plus proches du milieu
    xg = f_monde((rg[0] + rg[1]) / 2, v)[0]; xd = f_monde((rd[0] + rd[1]) / 2, v)[0]
    return xg, xd


# ---- aisselles : en descendant depuis 0,88 H, première ligne à partir de laquelle les bras sont séparés du tronc
#      (trois segments : bras, tronc, bras) sur au moins 6 % de la hauteur (les pointes d'épaulières ne comptent pas)
def separe(z):
    v = f_ligne(z)
    rs = runs(MF[v])
    tronc = [r for r in rs if r[0] <= c0 <= r[1]]
    if not tronc:
        return False
    t = tronc[0]
    g = [r for r in rs if r[1] < t[0] - 1]
    d = [r for r in rs if r[0] > t[1] + 1]
    return bool(g and d)


pas = 0.004 * H
zs = np.arange(0.88 * H, 0.40 * H, -pas)
sep = [separe(z) for z in zs]
n_suite = int(0.06 * H / pas)
aisselle = None
for i in range(len(zs) - n_suite):
    if all(sep[i:i + n_suite]):
        aisselle = zs[i]
        break
if aisselle is None:
    aisselle = 0.72 * H
log('aisselles %.3f H' % (aisselle / H))

# ---- largeur du tronc à hauteur des aisselles
v_ais = f_ligne(aisselle)
t_ais = [r for r in runs(MF[v_ais]) if r[0] <= c0 <= r[1]][0]
x_tronc_g, x_tronc_d = f_monde(t_ais[0], v_ais)[0], f_monde(t_ais[1], v_ais)[0]


def bras(cote):
    """chaîne du bras (côté 'L' : +X, gauche du personnage ; 'R' : -X) : épaule, coude, poignet, bout de la main."""
    s = 1 if cote == 'L' else -1
    pts = []
    for z in np.arange(aisselle, 0.02 * H, -0.004 * H):
        v = f_ligne(z)
        rs = runs(MF[v])
        tronc = [r for r in rs if r[0] <= c0 <= r[1]]
        if s > 0:
            cand = [r for r in rs if (not tronc or r[0] > tronc[0][1] + 1) and f_monde(r[0], v)[0] > 0]
            cand = [r for r in cand if r not in tronc]
        else:
            cand = [r for r in rs if (not tronc or r[1] < tronc[0][0] - 1) and f_monde(r[1], v)[0] < 0]
            cand = [r for r in cand if r not in tronc]
        if not cand:
            if pts:
                break
            continue
        r = max(cand, key=lambda r: abs(f_monde((r[0] + r[1]) / 2, v)[0]))     # le plus extérieur
        xm = f_monde((r[0] + r[1]) / 2, v)[0]
        ep = (r[1] - r[0] + 1) * (f_monde(1, v)[0] - f_monde(0, v)[0])
        if pts and abs(xm - pts[-1][0]) > 0.08 * H:                           # saut : ce n'est plus le bras
            break
        pts.append((xm, z, ep))
    pts = np.array(pts) if pts else np.zeros((0, 3))
    epaule_x = (x_tronc_d if s > 0 else x_tronc_g) - s * 0.03 * H
    epaule = np.array([epaule_x, 0, aisselle + 0.05 * H])
    if len(pts) < 5:            # bras collés au corps : proportions humaines
        bout = np.array([epaule_x + s * 0.12 * H, 0, 0.38 * H])
    else:
        bout = np.array([pts[-1][0], 0, pts[-1][1]])
        # le vrai bout : le pixel du bras le plus loin de l'épaule
    L = np.linalg.norm(bout - epaule)
    u = (bout - epaule) / max(L, 1e-9)
    coude = epaule + u * 0.42 * L
    poignet = epaule + u * 0.78 * L
    # creux du poignet : épaisseur minimale entre 65 % et 88 % de la longueur
    if len(pts) >= 8:
        d = np.array([np.dot(np.array([p[0], 0, p[1]]) - epaule, u) / L for p in pts])
        sel = (d > 0.65) & (d < 0.88)
        if sel.sum() >= 3:
            k = np.argmin(pts[sel][:, 2])
            p = pts[sel][k]
            poignet = np.array([p[0], 0, p[1]])
        sel = (d > 0.35) & (d < 0.55)
        if sel.sum() >= 3:
            p = pts[sel][np.argmin(pts[sel][:, 2])]
            coude = np.array([p[0], 0, p[1]])
    return dict(epaule=epaule, coude=coude, poignet=poignet, bout=bout, longueur=float(L))


BG, BD = bras('L'), bras('R')
xg_j, xd_j = centre_jambes(entre - 0.04 * H)
# ---- cou : ligne la plus étroite entre les aisselles + 5 % et le haut - 8 %
best = None
for z in np.arange(aisselle + 0.04 * H, 0.94 * H, 0.003 * H):
    v = f_ligne(z)
    rs = [r for r in runs(MF[v]) if r[0] <= c0 + 3 and r[1] >= c0 - 3]
    if not rs:
        continue
    w = rs[0][1] - rs[0][0]
    if best is None or w < best[0]:
        best = (w, z)
cou = best[1] if best else 0.86 * H
cou = min(max(cou, aisselle + 0.04 * H), 0.93 * H)
log('cou %.3f H' % (cou / H))


def centre_y(z, x=0.0, y_pref=None):
    """profondeur (y) du centre du corps en (x, z) : milieu du plus long intervalle intérieur le long de Y
    (rayons dans le maillage étanche) ; à défaut, centre de la silhouette de profil."""
    o = Vector((x, -10.0, z)); d = Vector((0, 1, 0))
    pts = []
    for _ in range(64):
        loc, nor, idx, dist = BVH.ray_cast(o, d)
        if loc is None:
            break
        pts.append(loc.y); o = loc + d * 1e-4
    ints = [(pts[k], pts[k + 1]) for k in range(0, len(pts) - 1, 2)]
    if ints:
        if y_pref is not None:
            dedans = [iv for iv in ints if iv[0] <= y_pref <= iv[1]]
            if dedans:
                return (dedans[0][0] + dedans[0][1]) / 2
        a_, b_ = max(ints, key=lambda iv: iv[1] - iv[0])
        return (a_ + b_) / 2
    v = p_ligne(z)
    rs = runs(MP[v])
    if not rs:
        return 0.0
    r = max(rs, key=lambda r: r[1] - r[0])
    return p_monde((r[0] + r[1]) / 2, v)[0]


def avant_y(z):
    v = p_ligne(z)
    rs = runs(MP[v])
    if not rs:
        return 0.0
    return min(p_monde(r[0], v)[0] for r in rs)


co = sommets(corps)


def pied(s):
    """cheville, base des orteils et bout du pied d'un côté (sommets du maillage)."""
    xj = xd_j if s > 0 else xg_j
    sel = (co[:, 2] < 0.07 * H) & (np.sign(co[:, 0]) == s)
    pts = co[sel]
    if len(pts) < 10:
        pts = co[co[:, 2] < 0.07 * H]
    yb = pts[:, 1].min()                    # bout (avant, -Y)
    yt = pts[:, 1].max()                    # talon
    cheville = np.array([xj, yt - 0.35 * (yt - yb), 0.055 * H])
    base = np.array([xj, yb + 0.30 * (yt - yb), 0.02 * H])
    bout = np.array([xj, yb, 0.015 * H])
    return cheville, base, bout


ChG, BaG, BoG = pied(1)
ChD, BaD, BoD = pied(-1)
z_hanche = entre + 0.035 * H
y_bassin = centre_y(z_hanche)
J = {}
J['Hips'] = np.array([0, y_bassin, z_hanche])
z_sp = [z_hanche + (aisselle + 0.02 * H - z_hanche) * f for f in (0.25, 0.55, 0.85)]
J['Spine'] = np.array([0, centre_y(z_sp[0]), z_sp[0]])
J['Spine1'] = np.array([0, centre_y(z_sp[1]), z_sp[1]])
J['Spine2'] = np.array([0, centre_y(z_sp[2]), z_sp[2]])
J['Neck'] = np.array([0, centre_y(cou), cou])
z_tete = cou + 0.35 * (H - cou)
J['Head'] = np.array([0, centre_y(z_tete), z_tete])
J['HeadTop_End'] = np.array([0, centre_y(z_tete), H])
for nom, B, s in (('Left', BG, 1), ('Right', BD, -1)):
    yb = centre_y(B['epaule'][2])
    J[nom + 'Shoulder'] = np.array([s * 0.035 * H, centre_y(B['epaule'][2] - 0.01 * H, s * 0.035 * H),
                                    B['epaule'][2] - 0.01 * H])
    for k_, cle in (('Arm', 'epaule'), ('ForeArm', 'coude'), ('Hand', 'poignet'), ('HandEnd', 'bout')):
        p_ = B[cle]
        J[nom + k_] = np.array([p_[0], centre_y(p_[2], p_[0], yb), p_[2]])
for nom, s, ch, ba, bo, xj in (('Left', 1, ChG, BaG, BoG, xd_j), ('Right', -1, ChD, BaD, BoD, xg_j)):
    J[nom + 'UpLeg'] = np.array([xj, centre_y(z_hanche - 0.02 * H, xj), z_hanche - 0.02 * H])
    zg = (z_hanche + ch[2]) / 2 + 0.01 * H
    J[nom + 'Leg'] = np.array([xj, centre_y(zg, xj) - 0.008 * H, zg])             # genou un peu en avant
    J[nom + 'Foot'] = ch
    J[nom + 'ToeBase'] = ba
    J[nom + 'Toe_End'] = bo
rapport['reperes'] = {k: [round(float(x), 4) for x in v] for k, v in J.items()}

# ------------------------------------------------------------------------------------------------ 3. squelette
arm_d = bpy.data.armatures.new('Armature')
arm = bpy.data.objects.new('Armature', arm_d)
sc.collection.objects.link(arm)
bpy.context.view_layer.objects.active = arm
bpy.ops.object.select_all(action='DESELECT')
arm.select_set(True)
bpy.ops.object.mode_set(mode='EDIT')
eb = arm_d.edit_bones
CHAINE = [('Hips', None, 'Spine'), ('Spine', 'Hips', 'Spine1'), ('Spine1', 'Spine', 'Spine2'),
          ('Spine2', 'Spine1', 'Neck'), ('Neck', 'Spine2', 'Head'), ('Head', 'Neck', 'HeadTop_End')]
for c in ('Left', 'Right'):
    CHAINE += [(c + 'Shoulder', 'Spine2', c + 'Arm'), (c + 'Arm', c + 'Shoulder', c + 'ForeArm'),
               (c + 'ForeArm', c + 'Arm', c + 'Hand'), (c + 'Hand', c + 'ForeArm', c + 'HandEnd'),
               (c + 'UpLeg', 'Hips', c + 'Leg'), (c + 'Leg', c + 'UpLeg', c + 'Foot'),
               (c + 'Foot', c + 'Leg', c + 'ToeBase'), (c + 'ToeBase', c + 'Foot', c + 'Toe_End')]
for nom, parent, suiv in CHAINE:
    b = eb.new(P + nom)
    b.head = Vector(J[nom].tolist())
    b.tail = Vector(J[suiv].tolist())
    if (b.tail - b.head).length < 0.01 * H:
        b.tail = b.head + Vector((0, 0, 0.03 * H))
    if parent:
        b.parent = eb[P + parent]
        b.use_connect = False
# bouts (comme Mixamo : HeadTop_End) ; rôle de chaque os : axe Z vers l'avant (-Y) pour le tronc et les jambes,
# vers le haut pour les bras
for nom in ('HeadTop_End',):
    b = eb.new(P + nom); b.head = Vector(J[nom].tolist()); b.tail = b.head + Vector((0, 0, 0.05 * H))
    b.parent = eb[P + 'Head']
for b in eb:
    if 'Arm' in b.name or 'Hand' in b.name or 'Shoulder' in b.name:
        b.align_roll(Vector((0, 0, 1)))
    else:
        b.align_roll(Vector((0, -1, 0)))
bpy.ops.object.mode_set(mode='OBJECT')
arm_d.bones[P + 'HeadTop_End'].use_deform = False
log('os', len(arm_d.bones))


# ------------------------------------------------------------------------------------------------ 4. poids
bpy.ops.object.select_all(action='DESELECT')
proxy.select_set(True); arm.select_set(True)
bpy.context.view_layer.objects.active = arm
bpy.ops.object.parent_set(type='ARMATURE_AUTO')
# sommets du proxy sans poids -> os le plus proche
vg_noms = [g.name for g in proxy.vertex_groups]
sans = 0
segs = {}
for b in arm_d.bones:
    segs[b.name] = (np.array(arm.matrix_world @ b.head_local), np.array(arm.matrix_world @ b.tail_local))


def os_proche(p):
    best = None
    for n, (h, t) in segs.items():
        if n.endswith('_End') or 'HandEnd' in n:
            continue
        d = t - h
        u = np.clip(np.dot(p - h, d) / max(np.dot(d, d), 1e-12), 0, 1)
        dist = np.linalg.norm(p - (h + u * d))
        if best is None or dist < best[0]:
            best = (dist, n)
    return best[1]


for v in proxy.data.vertices:
    if not v.groups or sum(g.weight for g in v.groups) < 1e-6:
        sans += 1
        n = os_proche(np.array(proxy.matrix_world @ v.co))
        g = proxy.vertex_groups.get(n) or proxy.vertex_groups.new(name=n)
        g.add([v.index], 1.0, 'REPLACE')
rapport['proxy_sans_poids'] = sans
log('sommets du proxy sans poids (corrigés)', sans)
# transfert vers le vrai maillage
for b in arm_d.bones:
    if not corps.vertex_groups.get(b.name):
        corps.vertex_groups.new(name=b.name)
dt = corps.modifiers.new('dt', 'DATA_TRANSFER')
dt.object = proxy
dt.use_vert_data = True
dt.data_types_verts = {'VGROUP_WEIGHTS'}
dt.vert_mapping = 'POLYINTERP_NEAREST'
dt.layers_vgroup_select_src = 'ALL'
dt.layers_vgroup_select_dst = 'NAME'
bpy.context.view_layer.objects.active = corps
bpy.ops.object.datalayout_transfer(modifier=dt.name)
applique(corps, dt)
bpy.ops.object.select_all(action='DESELECT')
corps.select_set(True)
bpy.context.view_layer.objects.active = corps
bpy.ops.object.vertex_group_limit_total(group_select_mode='ALL', limit=4)
bpy.ops.object.vertex_group_normalize_all(group_select_mode='ALL', lock_active=False)
corps.parent = arm
mod = corps.modifiers.new('Armature', 'ARMATURE'); mod.object = arm
bpy.data.objects.remove(proxy, do_unlink=True)

# ------------------------------------------------------------------------------------------------ 5. contrôle
dg = bpy.context.evaluated_depsgraph_get()
nv = len(corps.data.vertices)
W = np.zeros(nv)
dom = np.full(nv, -1)
noms = [g.name for g in corps.vertex_groups]
for v in corps.data.vertices:
    if v.groups:
        g = max(v.groups, key=lambda g: g.weight)
        W[v.index] = sum(x.weight for x in v.groups)
        dom[v.index] = g.group
sans_poids = int((W < 1e-6).sum())
co = sommets(corps)
loin = 0
for i in np.random.default_rng(0).choice(nv, min(nv, 4000), replace=False):
    if dom[i] < 0:
        continue
    h, t = segs[noms[dom[i]]]
    d = t - h
    u = np.clip(np.dot(co[i] - h, d) / max(np.dot(d, d), 1e-12), 0, 1)
    if np.linalg.norm(co[i] - (h + u * d)) > 0.25 * H:
        loin += 1
rapport['sommets_sans_poids'] = sans_poids
rapport['sommets_os_loin_pct'] = round(100.0 * loin / min(nv, 4000), 2)
# pose d'essai
EDGES = np.empty(len(corps.data.edges) * 2, np.int64)
corps.data.edges.foreach_get('vertices', EDGES)
EDGES = EDGES.reshape(-1, 2)


def longueurs(C):
    return np.linalg.norm(C[EDGES[:, 0]] - C[EDGES[:, 1]], axis=1)


L0 = longueurs(co)
essai = {'LeftArm': ('Z', -45), 'RightArm': ('Z', 45), 'LeftForeArm': ('X', 50), 'RightForeArm': ('X', 50),
         'LeftUpLeg': ('X', -40), 'RightUpLeg': ('X', 20), 'LeftLeg': ('X', 60), 'RightLeg': ('X', 30),
         'Spine1': ('Z', 20), 'Head': ('Z', 30), 'Neck': ('X', 10)}
for pb in arm.pose.bones:
    pb.rotation_mode = 'XYZ'
for n, (ax, deg) in essai.items():
    pb = arm.pose.bones.get(P + n)
    if pb:
        r = [0, 0, 0]; r['XYZ'.index(ax)] = math.radians(deg); pb.rotation_euler = r
bpy.context.view_layer.update()
dg = bpy.context.evaluated_depsgraph_get()
ev = corps.evaluated_get(dg)
me = ev.to_mesh()
C1 = np.empty(len(me.vertices) * 3); me.vertices.foreach_get('co', C1); C1 = C1.reshape(-1, 3)
ev.to_mesh_clear()
C1 = np.array([list(corps.matrix_world @ Vector(c)) for c in C1]) if False else C1
r = longueurs(C1) / np.maximum(L0, 1e-9)
rapport['aretes_etirees_x2_pct'] = round(100.0 * float((r > 2.0).mean()), 3)
rapport['aretes_ecrasees_pct'] = round(100.0 * float((r < 0.3).mean()), 3)
log('contrôle : sans poids', sans_poids, '| os éloigné %.2f %%' % rapport['sommets_os_loin_pct'],
    '| arêtes étirées x2 %.3f %%' % rapport['aretes_etirees_x2_pct'])


def vue(nom, cam_loc, cam_rot):
    sc.render.engine = 'BLENDER_WORKBENCH'
    sc.display.shading.light = 'STUDIO'
    sc.display.shading.color_type = 'TEXTURE'
    sc.display.render_aa = '8'
    sc.world.color = (0.25, 0.25, 0.27)
    cd = bpy.data.cameras.new('cv'); cd.type = 'ORTHO'; cd.ortho_scale = 1.25 * H
    cam = bpy.data.objects.new('cv', cd); sc.collection.objects.link(cam)
    cam.location = cam_loc; cam.rotation_euler = cam_rot
    sc.camera = cam
    sc.render.resolution_x, sc.render.resolution_y = 420, 560
    sc.render.filepath = os.path.join(IMAGES, nom + '.png')
    bpy.ops.render.render(write_still=True)
    bpy.data.objects.remove(cam, do_unlink=True)


arm.show_in_front = True
vue('essai_face', (0, -10, 0.55 * H), (math.radians(90), 0, 0))
vue('essai_profil', (10, 0, 0.55 * H), (math.radians(90), 0, math.radians(90)))
for pb in arm.pose.bones:
    pb.rotation_euler = (0, 0, 0)
bpy.context.view_layer.update()
vue('repos_face', (0, -10, 0.55 * H), (math.radians(90), 0, 0))
vue('repos_profil', (10, 0, 0.55 * H), (math.radians(90), 0, math.radians(90)))
rapport['ok'] = bool(sans_poids < 0.001 * nv and rapport['sommets_os_loin_pct'] < 2.0
                     and rapport['aretes_etirees_x2_pct'] < 0.5)
for img in bpy.data.images:
    if img.source in ('FILE', 'GENERATED') and img.users:
        try:
            img.pack()
        except Exception:  # noqa: BLE001
            pass
for pb in arm.pose.bones:                     # rotations en quaternions (les actions de la chaîne en portent)
    pb.rotation_mode = 'QUATERNION'
bpy.ops.wm.save_as_mainfile(filepath=OUT)
json.dump(rapport, open(RAPPORT, 'w'), indent=1, ensure_ascii=False)
log('ECRIT', OUT, 'ok' if rapport['ok'] else 'À VÉRIFIER')
