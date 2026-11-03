# arme.py - Silicon Coast, chaîne des monstres 3D, étape 5 : objet tenu (règles de fidélité, 3), fait à part du
# corps (le dessin de référence demande une main vide), puis tenu par l'os de la main.
#   blender -b --factory-startup -P arme.py -- <RESREF> <travail>
# Fiche (fiches.json) : "objet": {"type": "epee_longue", "main": "droite", "couleur": [r, g, b],
#                                 "longueur_rel": 0.62, "prise": "bas"}
# Épée longue : lame droite à arête centrale, pointe effilée, garde courte, fusée gainée de cuir, pommeau ; longueur
# totale = longueur_rel x hauteur du monstre. Prise « bas » : la main serre la fusée près du pommeau.
# La prise est donnée dans le repère de l'os de la main (pose de repos) : la lame sort du côté du pouce (vers
# l'avant quand le bras pend, paume vers le corps). L'orientation autour de l'axe de la main (roulis) est ensuite
# calée par mouvements.py sur les silhouettes d'origine.
# Sorties : <travail>/rig/arme.blend (objet « SC_massue », nom attendu par bl_anim.py), rig/arme_modele.json
# (os, prise 4x4 en unités du modèle, longueur), rig/arme_apercu.png.
import json
import math
import os
import sys

import bmesh
import bpy
from mathutils import Matrix, Vector

a = sys.argv[sys.argv.index('--') + 1:]
RES, TRAV = a[0].upper(), os.path.abspath(a[1])
ICI = os.path.dirname(os.path.abspath(__file__))
FICHE = json.load(open(os.path.join(ICI, 'fiches.json')))[RES]
OBJ = FICHE['objet']
COTE = 'Right' if OBJ.get('main', 'droite').startswith('d') else 'Left'
HAUTEUR = 2.0                                # hauteur du modèle (auto_rig.py)


def materiau(nom, couleur, metal, rugosite):
    m = bpy.data.materials.new(nom)
    m.use_nodes = True
    b = m.node_tree.nodes.get('Principled BSDF')
    b.inputs['Base Color'].default_value = (*couleur, 1.0)
    b.inputs['Metallic'].default_value = metal
    b.inputs['Roughness'].default_value = rugosite
    return m


def epee(longueur):
    """maillage de l'épée, axe Z le long de la lame, origine au point de prise (centre de la main)."""
    bm = bmesh.new()
    L = longueur
    fusee = 0.17 * L; pommeau = 0.035 * L; garde_l = 0.16 * L; lame = L - fusee - pommeau - 0.02 * L
    z_bas = -0.3 * fusee                     # prise basse : la main est au tiers inférieur de la fusée
    z_garde = z_bas + fusee
    mats = {}
    # lame : section en losange (arête centrale), largeur décroissante, pointe
    larg0, larg1, ep = 0.06 * L, 0.045 * L, 0.014 * L
    n = 8
    anneaux = []
    for k in range(n + 1):
        t = k / n
        z = z_garde + 0.01 * L + t * lame
        if t < 0.85:
            w = larg0 + (larg1 - larg0) * (t / 0.85)
        else:
            w = larg1 * max(0.0, (1.0 - t) / 0.15)
        e = ep * (1.0 - 0.5 * t)
        if k == n:
            anneaux.append([bm.verts.new((0, 0, z))])
        else:
            anneaux.append([bm.verts.new((w / 2, 0, z)), bm.verts.new((0, e / 2, z)), bm.verts.new((-w / 2, 0, z)),
                            bm.verts.new((0, -e / 2, z))])
    for k in range(n):
        A, B = anneaux[k], anneaux[k + 1]
        for i in range(4):
            if len(B) == 1:
                f = bm.faces.new((A[i], A[(i + 1) % 4], B[0]))
            else:
                f = bm.faces.new((A[i], A[(i + 1) % 4], B[(i + 1) % 4], B[i]))
            f.material_index = 0
    f = bm.faces.new(list(reversed(anneaux[0]))); f.material_index = 0

    def boite(cx, cy, cz, sx, sy, sz, mi):
        r = bmesh.ops.create_cube(bm, size=1.0)
        for v in r['verts']:
            v.co = Vector((cx + v.co.x * sx, cy + v.co.y * sy, cz + v.co.z * sz))
        for f_ in {f for v in r['verts'] for f in v.link_faces}:
            f_.material_index = mi

    def cylindre(cz, h, r_, mi, seg=10):
        res = bmesh.ops.create_cone(bm, cap_ends=True, segments=seg, radius1=r_, radius2=r_, depth=h)
        for v in res['verts']:
            v.co.z += cz
        for f_ in {f for v in res['verts'] for f in v.link_faces}:
            f_.material_index = mi

    boite(0, 0, z_garde, garde_l, 0.022 * L, 0.018 * L, 1)                      # garde
    cylindre(z_bas + fusee / 2, fusee, 0.016 * L, 2)                             # fusée
    s = bmesh.ops.create_uvsphere(bm, u_segments=10, v_segments=6, radius=pommeau / 1.6)   # pommeau
    for v in s['verts']:
        v.co.z += z_bas - pommeau / 2
    for f_ in {f for v in s['verts'] for f in v.link_faces}:
        f_.material_index = 1
    me = bpy.data.meshes.new('SC_massue')
    bm.to_mesh(me); bm.free()
    for p in me.polygons:
        p.use_smooth = False
    o = bpy.data.objects.new('SC_massue', me)
    lame_c = tuple(OBJ.get('couleur', (0.78, 0.8, 0.84)))
    me.materials.append(materiau('SC_arme_lame', lame_c, 1.0, 0.28))
    me.materials.append(materiau('SC_arme_garde', (0.32, 0.3, 0.27), 1.0, 0.4))
    me.materials.append(materiau('SC_arme_fusee', (0.16, 0.1, 0.07), 0.0, 0.75))
    return o, dict(longueur=L, lame=lame, fusee=fusee, z_bas=z_bas, z_garde=z_garde)


def main():
    bpy.ops.wm.open_mainfile(filepath=os.path.join(TRAV, 'rig', 'rig.blend'))
    arm = bpy.data.objects['Armature']
    nb = 'mixamorig:%sHand' % COTE
    b = arm.data.bones[nb]
    Mb = arm.matrix_world @ b.matrix_local                     # repère de l'os au repos (monde)
    tete, queue = arm.matrix_world @ b.head_local, arm.matrix_world @ b.tail_local
    axe = (queue - tete).normalized()
    centre = tete + (queue - tete) * 0.45                     # paume
    avant = Vector((0, -1, 0))                                # le personnage regarde vers -Y
    z = (avant - axe * avant.dot(axe)).normalized()           # lame : côté du pouce, perpendiculaire à la main
    x = axe.cross(z).normalized()
    y = z.cross(x)
    Mw = Matrix.Translation(centre) @ Matrix((x, y, z)).transposed().to_4x4()
    L = OBJ.get('longueur_rel', 0.6) * HAUTEUR
    if OBJ.get('type', '').startswith('epee'):
        o, geo = epee(L)
    else:
        raise SystemExit('objet inconnu : %s' % OBJ.get('type'))
    loc, rot, _ = Mb.decompose()
    G = (Matrix.Translation(loc) @ rot.to_matrix().to_4x4()).inverted() @ Mw
    # fichier de l'arme seule
    sc = bpy.context.scene
    sc.collection.objects.link(o)
    o.matrix_world = Mw
    p = os.path.join(TRAV, 'rig', 'arme.blend')
    o.matrix_world = Matrix.Identity(4)
    bpy.data.libraries.write(p, {o}, fake_user=True)
    o.matrix_world = Mw
    info = dict(objet=OBJ, os=nb, cote=COTE, prise=[list(r) for r in G], geometrie=geo, blend=p)
    json.dump(info, open(os.path.join(TRAV, 'rig', 'arme_modele.json'), 'w'), indent=1)
    # aperçu : modèle au repos avec l'arme, de face et de profil
    for ob in bpy.data.objects:
        if ob.type == 'LIGHT':
            ob.hide_render = True
    sc.render.engine = 'BLENDER_WORKBENCH'
    sc.display.shading.light = 'STUDIO'; sc.display.shading.color_type = 'MATERIAL'
    sc.render.resolution_x, sc.render.resolution_y = 600, 600
    cd = bpy.data.cameras.new('apercu'); cd.type = 'ORTHO'; cd.ortho_scale = 2.6
    cam = bpy.data.objects.new('apercu', cd); sc.collection.objects.link(cam); sc.camera = cam
    for nom, rotz in (('face', 0.0), ('profil', math.pi / 2)):
        cam.location = Vector((math.sin(rotz) * -6, -math.cos(rotz) * 6, 1.1))
        cam.rotation_euler = (math.pi / 2, 0, rotz + (0 if nom == 'face' else -math.pi))
        if nom == 'profil':
            cam.location = Vector((-6, 0, 1.1)); cam.rotation_euler = (math.pi / 2, 0, -math.pi / 2)
        sc.render.filepath = os.path.join(TRAV, 'rig', 'arme_apercu_%s.png' % nom)
        bpy.ops.render.render(write_still=True)
    print('arme', OBJ.get('type'), 'longueur %.3f' % L, 'os', nb, '->', p)


main()
