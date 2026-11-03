# bl_anim.py - Silicon Coast : rendu des animations d'une creature riggee (FBX Mixamo) a la camera de BG2:EE.
#
#   blender -b -P bl_anim.py -- <config.json>
#
# config :
#   "anims": {"marche": {"fbx": ".../walk.fbx", "loop": true, "lock": "hips_xy"|"drift"|false,
#                        "hold_last": false, "t0": null, "t1": null}, ...}
#        lock "hips_xy" : les hanches restent sur place (horizontalement) ; "drift" : seule la derive lineaire
#        entre le debut et la fin est retiree (le cycle se referme) ; t0/t1 : sous-partie de l'animation (images).
#   "height": 95.0 + "height_anim": "repos"   hauteur de la creature dans la 1re image de cette animation
#        (unites = pixels du sprite d'origine) ; ou "scale": s pour une echelle fixe.
#   "material": {"blend": ".../ogre_mat.blend", "name": "SC_ogre_mat"}   materiau HD a remettre sur le maillage
#   "club": {"blend": ".../club.blend", "bone": "mixamorig:RightHand", "grip": [[4x4]], "scale": 1.0}
#   "fist": {"side": "Right", "axis": "X", "deg": 70, "thumb_deg": 35}   main fermee sur la massue
#   "jobs": [{"anim": "marche", "n": 14, "i": 3, "d": 1, "w": .., "h": .., "cx": .., "cy": .., "out": "...png",
#             "mask": "..._mask.png"}, ...]      image i sur n de l'animation, direction d, cadre d'origine
#   + les reglages de rendu de bl_game.py (engine, samples, lights, ambient, shadow, k, phi_deg)
#   "proc" (par animation) : pose procedurale ajoutee apres l'animation, selon l'image i du travail (cles [[i, valeur]],
#        interpolation douce) : "rots": [{"bone": "mixamorig:Neck", "axis": "X"|"Y"|"Z", "keys": [[0, 0], [10, 35]]}]
#        rotations en degres autour des axes du personnage (X a sa gauche : + penche vers l'avant un os dresse ;
#        Y vers son dos ; Z en haut : + tourne vers sa gauche) ; "accroupi": {"drop": m, "cuisse": {"Left": deg,
#        "Right": deg}, "ecart": {...}} : hanches abaissees, cuisses en avant (deg < 0), tibias et pieds recalcules pour
#        que les chevilles restent a leur hauteur et les pieds a plat.
#   "ombre_seule": true + "ombre": {"az_deg": -108, "el_deg": 80, "angle_deg": 5}  passe d'ombre seule : meme pose
#        et meme cadre que le rendu deja fait (<image>.json relu), personnage invisible a la camera mais qui porte
#        ombre, une seule lumiere (soleil presque vertical : ombre courte sous les pieds, comme les sprites
#        d'origine) -> <image>_ombre.png (alpha = ombre)
#   "classes": {"SC_imoen_GA_1": ".../plages_couleurs.png", ...}  carte des plages de couleurs par maillage (prefixe du
#        nom) : chaque rendu ecrit aussi <image>_classes.png (texels sans filtrage, sans anticrenelage)
# Chaque animation est importee a part (Mixamo livre un FBX par animation, avec la peau). L'echelle est la meme
# pour toutes ; le personnage est pose au sol (pose de repos) et centre sur ses hanches ; il regarde vers -Y
# (la camera) ; la massue suit l'os de la main.
import json
import math
import os
import sys

import bpy
from mathutils import Matrix, Quaternion, Vector

argv = sys.argv[sys.argv.index('--') + 1:]
cfg = json.load(open(argv[0]))
sys.argv = [sys.argv[0], '--', argv[0]]
HERE = os.path.dirname(os.path.abspath(__file__))
exec(open(os.path.join(HERE, 'bl_game.py')).read().split('\ndef main():')[0])   # camera, lumieres, rendu, masque

HIPS = cfg.get('hips_bone', 'mixamorig:Hips')
KEEP = ('SC_cam', 'SC_ground', 'SC_massue')


def import_char(path):
    before = set(bpy.data.objects)
    if path.lower().endswith(('.glb', '.gltf')):
        bpy.ops.import_scene.gltf(filepath=path)                # essais
    elif path.lower().endswith('.blend'):                       # armature + maillage + action (marche transferee)
        with bpy.data.libraries.load(path) as (src, dst):
            dst.objects = list(src.objects)
        for o in dst.objects:
            if o is not None:
                bpy.context.scene.collection.objects.link(o)
    else:
        bpy.ops.import_scene.fbx(filepath=path, ignore_leaf_bones=True, automatic_bone_orientation=False)
    new = [o for o in bpy.data.objects if o not in before]
    arm = next(o for o in new if o.type == 'ARMATURE')
    shapes = {pb.custom_shape for pb in arm.pose.bones if pb.custom_shape}
    for o in new:
        if o in shapes:
            o.hide_render = True                                # formes d'os (import glTF), pas du personnage
    meshes = [o for o in new if o.type == 'MESH' and o not in shapes and not o.hide_render]
    return arm, meshes, new


def curves_of(new):
    """courbes de cheveux du personnage (objets CURVES rendus)."""
    return [o for o in new if o.type == 'CURVES' and not o.hide_render]


def points_world(o, dg, step=1):
    """positions monde (numpy N x 3) des sommets d'un maillage ou des points d'un objet de courbes de cheveux."""
    import numpy as np
    ev = o.evaluated_get(dg)
    M = np.array(ev.matrix_world)
    if o.type == 'CURVES':
        pd = ev.data.position_data
        co = np.empty(len(pd) * 3); pd.foreach_get('vector', co)
        P = co.reshape(-1, 3)[::step]
    else:
        me = ev.to_mesh(); n = len(me.vertices)
        co = np.empty(n * 3); me.vertices.foreach_get('co', co)
        ev.to_mesh_clear()
        P = co.reshape(-1, 3)
    return P @ M[:3, :3].T + M[:3, 3]


def frame_range(arm):
    act = arm.animation_data.action if arm.animation_data else None
    if act is None:
        return 1, 1
    a, b = act.frame_range
    return int(round(a)), int(round(b))


def action_fcurves(act):
    """courbes d'une action (Blender 4.4+ : actions en couches ; avant : action.fcurves)."""
    if act is None:
        return []
    if hasattr(act, 'layers') and len(act.layers):
        out = []
        for layer in act.layers:
            for strip in layer.strips:
                for bag in getattr(strip, 'channelbags', []):
                    out.extend(bag.fcurves)
        if out:
            return out
    return list(getattr(act, 'fcurves', []))


def remove_fcurves(act, pred):
    if act is None:
        return
    if hasattr(act, 'layers') and len(act.layers):
        for layer in act.layers:
            for strip in layer.strips:
                for bag in getattr(strip, 'channelbags', []):
                    for cu in [c for c in bag.fcurves if pred(c.data_path)]:
                        bag.fcurves.remove(cu)
    elif hasattr(act, 'fcurves'):
        for cu in [c for c in act.fcurves if pred(c.data_path)]:
            act.fcurves.remove(cu)


def world_bbox(meshes):
    dg = bpy.context.evaluated_depsgraph_get()
    lo = Vector((1e9, 1e9, 1e9)); hi = Vector((-1e9, -1e9, -1e9))
    for m in meshes:
        ev = m.evaluated_get(dg)
        me = ev.to_mesh()
        mw = ev.matrix_world
        for v in me.vertices:
            p = mw @ v.co
            lo = Vector(map(min, lo, p)); hi = Vector(map(max, hi, p))
        ev.to_mesh_clear()
    return lo, hi


def set_frame(scene, t):
    scene.frame_set(int(math.floor(t)), subframe=t - math.floor(t))


def hips_local(root, arm):
    """position des hanches dans le repere de SC_root (avant echelle) ; None sans os de hanches."""
    pb = arm.pose.bones.get(HIPS)
    if pb is None:
        return None
    return root.matrix_world.inverted() @ (arm.matrix_world @ pb.head)


def apply_material(meshes):
    m = cfg.get('material')
    if not m:
        return
    mat = bpy.data.materials.get(m['name'])
    if mat is None:
        with bpy.data.libraries.load(m['blend']) as (src, dst):
            dst.materials = [n for n in src.materials if n == m['name']]
        mat = dst.materials[0]
    for o in meshes:
        o.data.materials.clear()
        o.data.materials.append(mat)


def curl_axis(bone, toward):
    """axe local de l'os (X ou Z, avec son signe) dont la rotation positive deplace le bout du doigt vers
    'toward' (direction dans le repere de l'armature, pose de repos) : independant de l'orientation des os."""
    M = bone.matrix_local.to_3x3()
    kids = [c for c in bone.children if (c.head_local - bone.head_local).length > 1e-6]
    # direction du segment : vers l'articulation suivante (la queue de l'os n'y mene pas toujours, import glTF)
    d = ((kids[0].head_local if kids else bone.tail_local) - bone.head_local).normalized()
    best = None
    for a in (Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1))):
        s = (M @ a).normalized().cross(d).dot(toward)
        if best is None or abs(s) > abs(best[1]):
            best = (a, s)
    return best[0] * (1.0 if best[1] > 0 else -1.0)


DAMP_BONES = ['Hips', 'Spine', 'Spine1', 'Spine2', 'Neck', 'Head', 'LeftShoulder', 'RightShoulder', 'LeftArm',
              'RightArm', 'LeftForeArm', 'RightForeArm']


def apply_damp(arm, d):
    """mouvement adouci : la rotation de chaque os choisi (torse, tete, bras, hanches) est ramenee vers sa pose
    moyenne de l'animation (facteur 1 = inchange, 0 = immobile), de meme pour le balancement des hanches ; les jambes
    gardent leur pas. Sert a calmer une demarche trop marquee."""
    act = arm.animation_data.action if arm.animation_data else None
    if act is None or not d:
        return
    alpha = d.get('factor', 0.5)
    aloc = d.get('hips_loc', alpha)
    bones = ['mixamorig:' + b for b in d.get('bones', DAMP_BONES)]
    curves = {}
    for cu in action_fcurves(act):
        for b in bones:
            if cu.data_path.startswith('pose.bones["%s"].' % b):
                curves.setdefault((b, cu.data_path.rsplit('.', 1)[1]), {})[cu.array_index] = cu
    n_q = n_l = 0
    for (b, prop), chans in curves.items():
        if prop == 'rotation_quaternion' and len(chans) == 4:
            kps = [chans[i].keyframe_points for i in range(4)]
            n = min(len(k) for k in kps)
            qs = [Quaternion([kps[i][j].co[1] for i in range(4)]) for j in range(n)]
            # moyenne : somme des quaternions alignes sur le premier, normalisee
            m = Quaternion((0, 0, 0, 0))
            for q in qs:
                m = m + (q if q.dot(qs[0]) >= 0 else -q)
            m.normalize()
            for j, q in enumerate(qs):
                r = m.slerp(q if q.dot(m) >= 0 else -q, alpha)
                for i in range(4):
                    kp = kps[i][j]
                    dv = r[i] - kp.co[1]
                    kp.co[1] = r[i]; kp.handle_left[1] += dv; kp.handle_right[1] += dv
            n_q += 1
        elif prop == 'location' and b.endswith(':Hips'):
            for cu in chans.values():
                vals = [kp.co[1] for kp in cu.keyframe_points]
                mean = sum(vals) / max(1, len(vals))
                for kp in cu.keyframe_points:
                    nv = mean + aloc * (kp.co[1] - mean)
                    dv = nv - kp.co[1]
                    kp.co[1] = nv; kp.handle_left[1] += dv; kp.handle_right[1] += dv
            n_l += 1
    for cu in action_fcurves(act):
        cu.update()
    print('adoucissement', alpha, 'os', n_q, 'hanches', n_l, flush=True)


def apply_fist(arm):
    """main fermee : les phalanges de la main qui tient la massue sont figees en position de prise. Les doigts se
    replient vers la paume (cote du pouce par rapport au plan des jointures), le pouce vers le milieu de l'index."""
    f = cfg.get('fist')
    if not f:
        return
    side = f.get('side', 'Right')
    pref = 'mixamorig:%sHand' % side
    B = arm.data.bones
    if pref + 'Middle1' not in B:
        return
    act = arm.animation_data.action if arm.animation_data else None
    names = [pb.name for pb in arm.pose.bones if pb.name.startswith(pref) and pb.name != pref]
    remove_fcurves(act, lambda p: any('"%s"' % n in p for n in names))
    H = lambda n: B[pref + n].head_local
    hand = B[pref].head_local
    u = (H('Middle1') - hand).normalized()
    w = (H('Index1') - H('Pinky1')).normalized()
    npalm = u.cross(w).normalized()
    if pref + 'Thumb2' in B and (H('Thumb2') - hand).dot(npalm) < 0:
        npalm = -npalm                                    # le pouce est du cote de la paume
    degs = f.get('deg', [65, 95, 50])
    tdegs = f.get('thumb_deg', [20, 35, 30])
    degs = [degs] * 3 if isinstance(degs, (int, float)) else degs
    tdegs = [tdegs] * 3 if isinstance(tdegs, (int, float)) else tdegs
    for n in names:
        suffix = n[len(pref):]
        if not suffix[-1].isdigit() or int(suffix[-1]) > 3:
            continue                                      # bouts de doigts (_End, 4)
        j = int(suffix[-1]) - 1
        bone = B[n]
        if suffix.startswith('Thumb'):
            kids = [c for c in bone.children]
            tip = kids[0].head_local if kids else bone.tail_local
            target = (H('Index2') - tip).normalized() if pref + 'Index2' in B else npalm
            ax, deg = curl_axis(bone, target), tdegs[j]
        else:
            ax, deg = curl_axis(bone, npalm), degs[j]
        pb = arm.pose.bones[n]
        pb.rotation_mode = 'QUATERNION'
        pb.rotation_quaternion = Quaternion(ax, math.radians(deg))


POSTURE_BONES = (('spine', 'Spine1', 'Spine2'), ('chest', 'Spine2', 'Neck'), ('neck', 'Neck', 'Head'),
                 ('head', 'Head', None))                    # os, articulation suivante
POSTURE_KEEP = {'spine': ('LeftShoulder', 'RightShoulder'), 'chest': ('LeftShoulder', 'RightShoulder')}
# (os qui gardent leur orientation : les bras ne bougent pas quand le dos se redresse)


def rotate_bone_keys(arm, bone, q):
    """ajoute la rotation q (repere local de l'os) a toutes les cles de rotation de l'os, ou a sa pose fixe."""
    pb = arm.pose.bones[bone]
    chans = {}
    if arm.animation_data and arm.animation_data.action:
        for cu in action_fcurves(arm.animation_data.action):
            if cu.data_path == 'pose.bones["%s"].rotation_quaternion' % bone:
                chans[cu.array_index] = cu
    if len(chans) == 4:
        kps = [chans[i].keyframe_points for i in range(4)]
        for j in range(min(len(k) for k in kps)):
            r = Quaternion([kps[i][j].co[1] for i in range(4)]) @ q
            for i in range(4):
                kp = kps[i][j]
                dv = r[i] - kp.co[1]
                kp.co[1] = r[i]; kp.handle_left[1] += dv; kp.handle_right[1] += dv
        for cu in chans.values():
            cu.update()
    else:
        pb.rotation_mode = 'QUATERNION'
        pb.rotation_quaternion = pb.rotation_quaternion @ q


def apply_posture(arm, a, scene, f0, f1):
    """port de tete : le haut du dos, le cou et la tete sont redresses vers une inclinaison voulue (degres vers
    l'avant, mesures par rapport a l'axe du bassin, donc valables aussi couche par terre). La correction est une
    rotation fixe par os, calculee sur la moyenne de l'animation : les mouvements de tete restent, seul l'axe change.
    a['posture'] (ou cfg['posture']) : {"chest": 15, "neck": 15, "head": 5}, une cle absente laisse l'os tel quel."""
    post = a.get('posture', cfg.get('posture'))
    if not post or arm.animation_data is None:
        return
    pbs = arm.pose.bones
    hips = pbs.get(HIPS)
    if hips is None:
        return
    n = 16
    frames = [f0 + (f1 - f0) * k / (n - 1) for k in range(n)]
    for key, short, nxt in POSTURE_BONES:
        target = post.get(key)
        bone = 'mixamorig:' + short
        if target is None or bone not in pbs:
            continue
        pb = pbs[bone]
        keep = [pbs['mixamorig:' + k] for k in POSTURE_KEEP.get(key, ()) if ('mixamorig:' + k) in pbs]
        kaxes = [Vector() for _ in keep]
        phis, axes = [], Vector()
        for t in frames:
            set_frame(scene, t)
            bpy.context.view_layer.update()
            H = (arm.matrix_world @ hips.matrix).to_3x3().normalized()
            up, fwd = H @ Vector((0, 1, 0)), H @ Vector((0, 0, 1))     # Mixamo : Y le long du dos, Z vers l'avant
            lat = up.cross(fwd).normalized()                           # axe de bascule : + = vers l'avant
            Wb = (arm.matrix_world @ pb.matrix).to_3x3().normalized()
            end = pbs['mixamorig:' + nxt].head if nxt and ('mixamorig:' + nxt) in pbs else pb.tail
            d = (arm.matrix_world @ end - arm.matrix_world @ pb.head).normalized()   # segment jusqu'a l'articulation suivante
            phis.append(math.degrees(math.atan2(d.dot(fwd), d.dot(up))))
            axes += Wb.inverted() @ lat
            for j, kb in enumerate(keep):
                kaxes[j] += (arm.matrix_world @ kb.matrix).to_3x3().normalized().inverted() @ lat
        phi = sum(phis) / len(phis)
        lim = post.get(key + '_max', post.get('max', 75))
        delta = max(-lim, min(lim, target - phi))
        if key in ('spine', 'chest') and not post.get('forward_ok'):
            delta = min(0.0, delta)                        # le dos est seulement redresse, jamais plus courbe
            # (sauf si "forward_ok" : une marche trop cambree peut aussi etre penchee un peu vers l'avant)
        q = Quaternion(axes.normalized(), math.radians(delta))
        rotate_bone_keys(arm, bone, q)
        for kb, ka in zip(keep, kaxes):                    # rotation inverse : les epaules et les bras restent en place
            rotate_bone_keys(arm, kb.name, Quaternion(ka.normalized(), math.radians(-delta)))
        print('posture %-6s moyenne %.0f -> %.0f degres (correction %.0f)' % (key, phi, phi + delta, delta), flush=True)


def apply_club_dir(arm, a, scene, f0, f1):
    """massue orientee en moyenne vers a['club_dir'] (direction dans la scene, personnage face a -Y) : la main qui
    la tient recoit une rotation fixe, la plus petite possible, ajoutee a toutes ses cles. Sert aux marches d'une
    autre source (MotionBricks) ou la main pend paume vers l'arriere : la massue partait en travers du corps.
    a['club_dir_weight'] (0 a 1) n'applique qu'une partie de la correction."""
    target = a.get('club_dir')
    club = cfg.get('club')
    if not target or not club or arm.animation_data is None:
        return
    hand = 'mixamorig:%sHand' % club.get('side', 'Right')
    if hand + 'Index1' not in arm.pose.bones:
        return
    pb = arm.pose.bones[hand]
    c = Vector(target).normalized()
    z0, v, n = Vector(), Vector(), 24
    for k in range(n):
        set_frame(scene, f0 + (f1 - f0) * k / n)
        bpy.context.view_layer.update()
        Wi = (arm.matrix_world @ pb.matrix).to_3x3().normalized().inverted()
        P = lambda s: arm.matrix_world @ arm.pose.bones[hand + s].head
        z0 += Wi @ (P('Index1') - P('Pinky1')).normalized()       # axe de la massue dans le repere de la main
        v += Wi @ c                                               # direction voulue, vue de la main
    z0.normalize(); v.normalize()
    q = Quaternion().slerp(z0.rotation_difference(v), a.get('club_dir_weight', 1.0))
    chans = {}
    for cu in action_fcurves(arm.animation_data.action):
        if cu.data_path == 'pose.bones["%s"].rotation_quaternion' % hand:
            chans[cu.array_index] = cu
    if len(chans) == 4:
        kps = [chans[i].keyframe_points for i in range(4)]
        for j in range(min(len(k) for k in kps)):
            r = Quaternion([kps[i][j].co[1] for i in range(4)]) @ q
            for i in range(4):
                kp = kps[i][j]
                dv = r[i] - kp.co[1]
                kp.co[1] = r[i]; kp.handle_left[1] += dv; kp.handle_right[1] += dv
        for cu in chans.values():
            cu.update()
    else:
        pb.rotation_mode = 'QUATERNION'
        pb.rotation_quaternion = pb.rotation_quaternion @ q
    print('massue reorientee de %.1f degres (main %s)' % (math.degrees(q.angle), hand), flush=True)


def load_club(scene):
    club = cfg.get('club')
    if not club:
        return None
    cl = bpy.data.objects.get('SC_massue')
    if cl is None:
        with bpy.data.libraries.load(club['blend']) as (src, dst):
            dst.objects = [n for n in src.objects if n == 'SC_massue']
        cl = dst.objects[0]
        scene.collection.objects.link(cl)
    return cl


def place_club(cl, arm):
    """la massue suit la main. Prise "auto" : le manche passe dans le poing ferme (entre les jointures et le bout
    des doigts replies), de l'auriculaire vers l'index, la tete du cote du pouce ; sinon matrice "grip" donnee
    dans le repere de l'os de la main (position et orientation de l'os, sans son echelle). Unites du jeu."""
    club = cfg['club']
    sc = Matrix.Scale(club.get('scale', 1.0), 4)
    side = club.get('side', 'Right')
    hand = 'mixamorig:%sHand' % side
    if club.get('grip', 'auto') == 'auto' and ('%sIndex1' % hand) in arm.pose.bones:
        P = lambda n: arm.matrix_world @ arm.pose.bones[hand + n].head
        fingers = ('Index', 'Middle', 'Ring', 'Pinky')
        center = sum((P(f + '1') + P(f + '3') for f in fingers), Vector()) / 8.0
        z = (P('Index1') - P('Pinky1')).normalized()
        y = center - (arm.matrix_world @ arm.pose.bones[hand].head)
        y = (y - z * y.dot(z)).normalized()
        x = y.cross(z)
        R = Matrix((x, y, z)).transposed().to_4x4()
        off = Matrix.Translation(Vector(club.get('offset', (0.0, 0.0, 0.0))))
        cl.matrix_world = Matrix.Translation(center) @ R @ off @ sc
        return
    pb = arm.pose.bones[club.get('bone', hand)]
    loc, rot, _ = (arm.matrix_world @ pb.matrix).decompose()
    grip = Matrix(club['grip']) if isinstance(club.get('grip'), list) else Matrix.Identity(4)
    cl.matrix_world = Matrix.Translation(loc) @ rot.to_matrix().to_4x4() @ grip @ sc


def club_drop_setup(cl, st, a, scene):
    """massue lachee pendant la chute (a['club_drop'] = {"t_drop": T, "t_land": T2}, temps de l'action) : elle
    quitte la main a t_drop et finit couchee au sol a t_land, le manche pres de la main de la pose finale, dans la
    direction ou elle pointait. Matrices rendues dans le repere de la racine (avant la rotation de direction)."""
    cd = a.get('club_drop')
    if not cd or cl is None:
        return None
    arm, root, base = st['arm'], st['root'], st['base']
    root.matrix_world = base
    binv = base.inverted()
    set_frame(scene, cd['t_drop'])
    bpy.context.view_layer.update()
    place_club(cl, arm)
    m_drop = binv @ cl.matrix_world
    set_frame(scene, st['f1'])
    bpy.context.view_layer.update()
    place_club(cl, arm)
    side = cfg['club'].get('side', 'Right')
    hand = arm.matrix_world @ arm.pose.bones['mixamorig:%sHand' % side].head
    hips = arm.matrix_world @ arm.pose.bones[HIPS].head
    ax = cl.matrix_world.to_3x3().normalized() @ Vector((0, 0, 1))
    d = Vector((ax.x, ax.y, 0.0))
    if d.length < 0.3:
        d = Vector((hand.x - hips.x, hand.y - hips.y, 0.0))
    d.normalize()
    # couchee : boule (centre a 5,6 px, pointes dans le sol) et pommeau (1,6 px) posent tous les deux par terre
    tilt = math.asin((5.6 - 1.6) / 42.3)
    z = (d * math.cos(tilt) + Vector((0, 0, math.sin(tilt)))).normalized()
    x = z.cross(Vector((0, 0, 1))).normalized()
    y = z.cross(x)
    R = Matrix((x, y, z)).transposed().to_4x4()
    grip = Vector((hand.x, hand.y, 1.6 + 5.5 * math.sin(tilt)))
    m_ground = binv @ (Matrix.Translation(grip) @ R @ Matrix.Scale(cfg['club'].get('scale', 1.0), 4))
    print('massue lachee a %s, au sol a %s' % (cd['t_drop'], cd['t_land']), flush=True)
    return dict(t_drop=cd['t_drop'], t_land=cd['t_land'], m_drop=m_drop, m_ground=m_ground)


def club_drop_apply(cl, drop, root, t):
    """massue en chute ou au sol pour le temps t (rien avant t_drop)."""
    if not drop or t < drop['t_drop']:
        return
    s = min(1.0, (t - drop['t_drop']) / max(1e-6, drop['t_land'] - drop['t_drop']))
    l0, r0, s0 = drop['m_drop'].decompose()
    l1, r1, s1 = drop['m_ground'].decompose()
    loc = l0.lerp(l1, s * s)                          # chute : de plus en plus vite
    rot = r0.slerp(r1, s)
    m = Matrix.Translation(loc) @ rot.to_matrix().to_4x4() @ Matrix.Diagonal(s0.lerp(s1, s)).to_4x4()
    cl.matrix_world = root.matrix_world @ m


def light_dir():
    lc = cfg.get('lights', {'key': {'az_deg': -108, 'el_deg': 60}})
    l = next(iter(lc.values()))
    az, el = math.radians(l.get('az_deg', 0)), math.radians(l.get('el_deg', 45))
    return Vector((math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el)))


def screen_box(objs, pad):
    """emprise a l'ecran (pixels du sprite, par rapport a l'ancre ; y vers le bas) de la creature, de la massue et
    de leur ombre au sol (projection le long de la lumiere) : le cadre de rendu est ajuste a chaque image."""
    import numpy as np
    ld = light_dir()
    dg = bpy.context.evaluated_depsgraph_get()
    sp, cp = math.sin(PHI), math.cos(PHI)
    lo = [1e9, 1e9]; hi = [-1e9, -1e9]
    for o in objs:
        P = points_world(o, dg, 3)
        n = len(P)
        if n:
            t = np.clip(P[:, 2], 0, None) / max(ld.z, 1e-3)
            G = P - np.outer(t, np.array(ld))
            for Q in (P, G):
                X = Q[:, 0]; Y = -(Q[:, 1] * sp + Q[:, 2] * cp)
                lo = [min(lo[0], X.min()), min(lo[1], Y.min())]
                hi = [max(hi[0], X.max()), max(hi[1], Y.max())]
    x0, y0 = int(math.floor(lo[0] - pad)), int(math.floor(lo[1] - pad))
    x1, y1 = int(math.ceil(hi[0] + pad)), int(math.ceil(hi[1] + pad))
    return dict(w=x1 - x0, h=y1 - y0, cx=-x0, cy=-y0)


AXES = {'X': Vector((1, 0, 0)), 'Y': Vector((0, 1, 0)), 'Z': Vector((0, 0, 1))}


def interp_keys(keys, u):
    """valeur a l'image u : cles [[u, v], ...] (fondu doux entre deux cles, constante au-dela) ou nombre."""
    if not isinstance(keys, list):
        return float(keys)
    if u <= keys[0][0]:
        return float(keys[0][1])
    for (u0, v0), (u1, v1) in zip(keys, keys[1:]):
        if u <= u1:
            s = (u - u0) / max(1e-9, u1 - u0)
            s = s * s * (3 - 2 * s)
            return v0 + (v1 - v0) * s
    return float(keys[-1][1])


def rotate_bone(arm, name, axis_arm, deg):
    """tourne l'os (et ses enfants) autour de sa tete, d'un angle en degres, axe dans le repere de l'armature."""
    pb = arm.pose.bones[name]
    M = pb.matrix.copy()
    head = M.to_translation()
    pb.matrix = Matrix.Translation(head) @ Matrix.Rotation(math.radians(deg), 4, axis_arm) @ Matrix.Translation(-head) @ M
    bpy.context.view_layer.update()


def crouch(st, cr, u, A, Mrel, ax):
    """hanches abaissees, cuisses tournees ; chaque tibia tourne autour du genou pour ramener la cheville a sa hauteur
    d'origine, puis le pied reprend son orientation d'origine (a plat)."""
    arm = st['arm']; pbs = arm.pose.bones
    feet = {}
    for side in ('Left', 'Right'):
        pf = pbs['mixamorig:%sFoot' % side]
        feet[side] = (pf.matrix.copy(), (Mrel @ pf.head).z)
    drop = interp_keys(cr.get('drop', 0.0), u)
    if drop:
        hips = pbs[HIPS]
        hips.matrix = Matrix.Translation(A @ Vector((0, 0, -drop))) @ hips.matrix.copy()
        bpy.context.view_layer.update()
    for side in ('Left', 'Right'):
        pitch = interp_keys(cr.get('cuisse', {}).get(side, 0.0), u)
        spread = interp_keys(cr.get('ecart', {}).get(side, 0.0), u)
        up = 'mixamorig:%sUpLeg' % side
        if pitch:
            rotate_bone(arm, up, ax['X'], pitch)
        if spread:
            rotate_bone(arm, up, ax['Y'], (-1 if side == 'Left' else 1) * spread)
        leg, foot = pbs['mixamorig:%sLeg' % side], pbs['mixamorig:%sFoot' % side]
        K = Mrel @ leg.head; Aa = Mrel @ foot.head
        dy, dz = (Aa - K).y, (Aa - K).z
        Rr = math.hypot(dy, dz)
        if Rr > 1e-9:
            psi = math.atan2(dy, dz)
            ca = max(-1.0, min(1.0, (feet[side][1] - K.z) / Rr))
            wrap = lambda t: (t + math.pi) % (2 * math.pi) - math.pi
            # des deux solutions, celle ou la cheville passe derriere le genou (genou plie dans le bon sens)
            back = lambda t: dy * math.cos(t) - dz * math.sin(t)
            phi = max((wrap(psi + math.acos(ca)), wrap(psi - math.acos(ca))), key=back)
            rotate_bone(arm, leg.name, ax['X'], math.degrees(phi))
        M0 = feet[side][0].copy()
        M0.translation = foot.matrix.to_translation()
        foot.matrix = M0
        bpy.context.view_layer.update()


def freeze_pose(st):
    """fige la pose evaluee (l'action est retiree le temps du rendu) : sinon le graphe de dependances la reevalue et
    efface les rotations ajoutees a la main."""
    arm = st['arm']
    ad = arm.animation_data
    vals = {pb.name: (pb.location.copy(), pb.rotation_quaternion.copy(), pb.rotation_euler.copy(), pb.scale.copy())
            for pb in arm.pose.bones}
    st['frozen'] = (ad.action, getattr(ad, 'action_slot', None))
    ad.action = None
    for pb in arm.pose.bones:
        pb.location, pb.rotation_quaternion, pb.rotation_euler, pb.scale = vals[pb.name]
    bpy.context.view_layer.update()


def unfreeze_pose(st):
    fr = st.pop('frozen', None)
    if fr is None:
        return
    ad = st['arm'].animation_data
    ad.action = fr[0]
    if fr[1] is not None and hasattr(ad, 'action_slot'):
        ad.action_slot = fr[1]


def apply_proc(st, a, u):
    """pose procedurale de l'animation a (cle "proc") pour l'image u, ajoutee a la pose de l'animation."""
    pr = a.get('proc')
    if not pr:
        return
    arm = st['arm']
    Mrel = st['root'].matrix_world.inverted() @ arm.matrix_world     # armature -> repere du personnage (racine)
    A = Mrel.to_3x3().inverted()
    ax = {k: (A @ v).normalized() for k, v in AXES.items()}
    if pr.get('accroupi'):
        crouch(st, pr['accroupi'], u, A, Mrel, ax)
    depth = lambda n: len(arm.pose.bones[n].parent_recursive)
    for rot in sorted(pr.get('rots', []), key=lambda r: depth(r['bone'])):
        deg = interp_keys(rot['keys'], u) * rot.get('k', 1.0)
        if abs(deg) > 1e-6:
            rotate_bone(arm, rot['bone'], ax[rot['axis']], deg)


_CLASS_MATS = {}


def render_classes(scene, st, out):
    """carte des plages de couleurs a l'ecran : chaque maillage avec sa texture de plages (texels sans filtrage),
    Workbench a plat, sans anticrenelage ni sol."""
    cl = cfg.get('classes')
    if not cl:
        return
    saved = {}
    objs = st['meshes'] + st.get('curves', [])
    for o in objs:
        path = next((p for k, p in sorted(cl.items(), key=lambda kv: -len(kv[0])) if o.name.startswith(k)), None)
        if path is None:
            raise SystemExit('pas de carte des plages pour %s' % o.name)
        if path not in _CLASS_MATS:
            if path.startswith('@'):
                # plage unie : couleur du matériau (Workbench « texture » la prend quand il n'y a pas d'image ;
                # seule possibilité pour les courbes de cheveux, qui n'ont pas d'UV)
                FCOL = {'metal': (230, 190, 40), 'mineur': (120, 200, 60), 'majeur': (170, 90, 230),
                        'peau': (250, 200, 170), 'cuir': (140, 80, 30), 'armure': (150, 160, 190),
                        'cheveux': (255, 60, 120)}[path[1:]]
                lin = [((c / 255.0 + 0.055) / 1.055) ** 2.4 if c / 255.0 > 0.04045 else c / 255.0 / 12.92 for c in FCOL]
                m = bpy.data.materials.new('SC_plage_' + path[1:]); m.use_nodes = True
                m.diffuse_color = (lin[0], lin[1], lin[2], 1.0)
                m.node_tree.nodes.get('Principled BSDF').inputs['Base Color'].default_value = (lin[0], lin[1], lin[2], 1.0)
            else:
                img = bpy.data.images.load(path)
                m = bpy.data.materials.new('SC_plages'); m.use_nodes = True
                nt = m.node_tree; bs = nt.nodes.get('Principled BSDF')
                tx = nt.nodes.new('ShaderNodeTexImage'); tx.image = img; tx.interpolation = 'Closest'
                nt.links.new(tx.outputs['Color'], bs.inputs['Base Color']); nt.nodes.active = tx
            _CLASS_MATS[path] = m
        if o.type == 'CURVES':
            saved[o.name] = list(o.data.materials)
            o.data.materials.clear(); o.data.materials.append(_CLASS_MATS[path])
            continue
        saved[o.name] = [sl.material for sl in o.material_slots]
        for sl in o.material_slots:
            sl.material = _CLASS_MATS[path]
    eng, ft = scene.render.engine, scene.render.film_transparent
    ground = bpy.data.objects.get('SC_ground')
    if ground:
        ground.hide_render = True
    scene.render.engine = 'BLENDER_WORKBENCH'
    scene.display.shading.light = 'FLAT'
    scene.display.shading.color_type = 'TEXTURE'
    scene.display.render_aa = 'OFF'
    scene.render.film_transparent = True
    cd = scene.render.image_settings.color_depth
    scene.render.image_settings.color_depth = '8'
    vt = scene.view_settings.view_transform
    scene.view_settings.view_transform = 'Standard'
    scene.render.filepath = out
    bpy.ops.render.render(write_still=True)
    scene.view_settings.view_transform = vt
    scene.render.image_settings.color_depth = cd
    scene.render.engine = eng
    scene.render.film_transparent = ft
    if ground:
        ground.hide_render = False
    for o in objs:
        if o.type == 'CURVES':
            o.data.materials.clear()
            for m in saved[o.name]:
                o.data.materials.append(m)
            continue
        for sl, m in zip(o.material_slots, saved[o.name]):
            sl.material = m


def points_aretes(ob, dg, pas):
    """points le long des aretes d'un maillage (monde), espaces d'au plus 'pas' : objets fins (lame d'une epee)
    dont les sommets seuls laisseraient des trous dans l'ombre."""
    import numpy as np
    ev = ob.evaluated_get(dg)
    me = ev.to_mesh()
    n = len(me.vertices)
    co = np.empty(n * 3); me.vertices.foreach_get('co', co)
    ed = np.empty(len(me.edges) * 2, np.int64); me.edges.foreach_get('vertices', ed)
    ev.to_mesh_clear()
    M = np.array(ev.matrix_world)
    P = co.reshape(-1, 3) @ M[:3, :3].T + M[:3, 3]
    a, b = P[ed[0::2]], P[ed[1::2]]
    out = [P]
    L = np.linalg.norm(b - a, axis=1)
    for k in range(1, int(np.ceil(L.max() / max(pas, 1e-6))) if len(L) else 1):
        t = k * pas / np.maximum(L, 1e-9)
        sel = t < 1.0
        out.append(a[sel] + (b[sel] - a[sel]) * t[sel, None])
    return np.concatenate(out)


def shadow_mask(st, box, out, o=None):
    """ombre calculee sans rendu : sommets projetes au sol le long de la lumiere d'ombre, puis a l'ecran
    (camera du jeu), poses en disques et fermes ; PNG RGBA (alpha = ombre), meme cadre que le rendu couleur.
    L'objet tenu (SC_massue) porte aussi son ombre."""
    import numpy as np
    o = o if o is not None else cfg.get('ombre', {})
    az, el = math.radians(o.get('az_deg', -108)), math.radians(o.get('el_deg', 85))
    l = np.array([math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el)])
    sp, cp = math.sin(PHI), math.cos(PHI)
    Wd, Hd = int(box['w'] * K), int(box['h'] * K)
    grid = np.zeros((Hd, Wd), bool)
    dg = bpy.context.evaluated_depsgraph_get()
    objs = [(ob, None) for ob in st['meshes'] + st.get('curves', [])]
    cl = bpy.data.objects.get('SC_massue')
    if cl is not None and not cl.hide_render:
        objs.append((cl, 0.5 / K))
    for ob, pas in objs:
        P = points_world(ob, dg, 2) if pas is None else points_aretes(ob, dg, pas)
        G = P - np.outer(np.clip(P[:, 2], 0, None) / l[2], l)
        X = (G[:, 0] + box['cx']) * K
        Y = (-(G[:, 1] * sp + G[:, 2] * cp) + box['cy']) * K
        xi, yi = np.round(X).astype(int), np.round(Y).astype(int)
        ok = (xi >= 0) & (xi < Wd) & (yi >= 0) & (yi < Hd)
        grid[yi[ok], xi[ok]] = True
    R = int(o.get('rayon', 3))
    yy, xx = np.mgrid[-R:R + 1, -R:R + 1]
    disk = (xx * xx + yy * yy) <= R * R
    dil = np.zeros_like(grid)
    for dy, dx in zip(*np.nonzero(disk)):
        dy -= R; dx -= R
        dil[max(0, dy):Hd + min(0, dy), max(0, dx):Wd + min(0, dx)] |= grid[max(0, -dy):Hd - max(0, dy), max(0, -dx):Wd - max(0, dx)]
    ero = np.ones_like(dil)
    for dy, dx in zip(*np.nonzero(disk)):
        dy -= R; dx -= R
        sh = np.ones_like(dil)
        sh[max(0, dy):Hd + min(0, dy), max(0, dx):Wd + min(0, dx)] = dil[max(0, -dy):Hd - max(0, dy), max(0, -dx):Wd - max(0, dx)]
        ero &= sh
    mask = ero | grid
    img = bpy.data.images.new('SC_ombre', Wd, Hd, alpha=True)
    px = np.zeros((Hd, Wd, 4), np.float32)
    px[..., 3] = mask
    img.pixels.foreach_set(px[::-1].reshape(-1))
    img.filepath_raw = out; img.file_format = 'PNG'; img.save()
    bpy.data.images.remove(img)


def setup_anim(name, a, scene, scale):
    for o in list(bpy.data.objects):
        if o.name in KEEP or o.type in ('LIGHT', 'CAMERA'):
            continue
        bpy.data.objects.remove(o, do_unlink=True)
    try:                                                        # donnees des animations precedentes : liberees
        bpy.data.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
    except Exception:  # noqa: BLE001
        pass
    arm, meshes, new = import_char(a['fbx'])
    if a.get('action_blend'):                                   # action seule dans un fichier a part (monstres)
        with bpy.data.libraries.load(a['action_blend']) as (src, dst):
            dst.actions = [n for n in src.actions if n == a.get('action', n)][:1]
        act = dst.actions[0]
        for pb in arm.pose.bones:                               # l'action porte des quaternions : les os doivent
            pb.rotation_mode = 'QUATERNION'                     # tourner en quaternions, sinon elle est ignoree
        if arm.animation_data is None:
            arm.animation_data_create()
        arm.animation_data.action = act
        if getattr(act, 'slots', None) and hasattr(arm.animation_data, 'action_slot') and len(act.slots):
            arm.animation_data.action_slot = act.slots[0]
    elif a.get('action'):                                       # fichier a plusieurs animations (essais glTF)
        act = bpy.data.actions[a['action']]
        if arm.animation_data is None:
            arm.animation_data_create()
        arm.animation_data.action = act
        if getattr(act, 'slots', None) and hasattr(arm.animation_data, 'action_slot'):
            arm.animation_data.action_slot = act.slots[0]
    apply_material(meshes)
    apply_damp(arm, a.get('damp'))
    apply_fist(arm)
    root = bpy.data.objects.new('SC_root', None)
    scene.collection.objects.link(root)
    for o in new:
        if o.parent is None:
            o.parent = root
    f0, f1 = frame_range(arm)
    if a.get('t0') is not None:
        f0 = a['t0']
    if a.get('t1') is not None:
        f1 = a['t1']
    bpy.context.view_layer.update()
    apply_posture(arm, a, scene, f0, f1)
    apply_club_dir(arm, a, scene, f0, f1)
    # sol et centre : pose de repos (la meme pour toutes les animations du personnage)
    arm.data.pose_position = 'REST'
    bpy.context.view_layer.update()
    lo, hi = world_bbox(meshes)
    hp = hips_local(root, arm)
    c = Vector((hp.x, hp.y, lo.z)) if hp is not None else Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
    arm.data.pose_position = 'POSE'
    set_frame(scene, f0)
    if scale is None:
        lo2, hi2 = world_bbox(meshes)
        scale = cfg.get('height', 95.0) / max(hi2.z - c.z, 1e-6)
        print('echelle', round(scale, 5), 'hauteur 3D', round(hi2.z - c.z, 3), 'repos', round(hi.z - lo.z, 3), flush=True)
    base = Matrix.Scale(scale, 4) @ Matrix.Translation(-c)
    root.matrix_world = base
    bpy.context.view_layer.update()
    h0 = hips_local(root, arm)
    set_frame(scene, f1)
    h1 = hips_local(root, arm)
    if h0 is not None:
        print('anim', name, 'images', f0, f1, 'derive des hanches (px)',
              tuple(round(scale * x, 1) for x in (h1 - h0)), flush=True)
    return dict(root=root, arm=arm, meshes=meshes, curves=curves_of(new), f0=f0, f1=f1, base=base, scale=scale, h0=h0, h1=h1)


def time_of(a, st, n, i):
    f0, f1 = st['f0'], st['f1']
    if a.get('hold_last'):
        return f1
    if a.get('loop', True):
        return f0 + (f1 - f0) * i / n
    return f0 + (f1 - f0) * (i / max(1, n - 1))


def lock_offset(a, st, t):
    """translation horizontale (unites du jeu) a retirer pour garder la creature sur place."""
    mode = a.get('lock', 'hips_xy' if a.get('lock_root') else False)
    if not mode or st['h0'] is None:
        return Vector((0, 0, 0))
    root, arm, s = st['root'], st['arm'], st['scale']
    if mode == 'drift':
        u = (t - st['f0']) / max(1e-6, st['f1'] - st['f0'])
        d = (st['h1'] - st['h0']) * u
    else:
        root.matrix_world = st['base']
        bpy.context.view_layer.update()
        d = hips_local(root, arm) - st['h0']
    return Vector((d.x * s, d.y * s, 0.0))


def main():
    reset()
    scene = bpy.context.scene
    cam = setup_camera(scene)
    setup_render(scene)
    scene.render.use_persistent_data = True
    OMBRE = cfg.get('ombre_seule')
    if OMBRE:
        o = dict(cfg.get('ombre', {}), energy=3.0)
        cfg['ambient'] = 0.0
        setup_lights(scene, {'ombre': o})
        setup_shadow_catcher(scene)
        scene.cycles.samples = cfg.get('samples_ombre', 8)
    elif cfg.get('engine', 'CYCLES') != 'WORKBENCH':
        setup_lights(scene, cfg.get('lights', {'key': {'az_deg': -108, 'el_deg': 60, 'energy': 1.6}}))
        if cfg.get('shadow', True):
            setup_shadow_catcher(scene)
    cl = load_club(scene)
    scale = cfg.get('scale')
    if scale is None and cfg.get('height_anim'):
        ref = cfg['height_anim']
        scale = setup_anim(ref, cfg['anims'][ref], scene, None)['scale']
    cur = None
    st = None
    jobs = sorted(cfg['jobs'], key=lambda j: (j['anim'], j['i'], j['d']))
    if cfg.get('skip_done', True):
        # reprise : les images deja rendues (couleur, silhouette et cadre presents) ne sont pas refaites
        done = lambda j: all(os.path.exists(p) for p in (j['out'], j.get('mask', j['out']),
                                                         os.path.splitext(j['out'])[0] + '.json'))
        if OMBRE:
            done = lambda j: os.path.exists(os.path.splitext(j['out'])[0] + '_ombre.png')
        n0 = len(jobs)
        jobs = [j for j in jobs if not done(j)]
        if n0 != len(jobs):
            print('reprise :', n0 - len(jobs), 'images deja faites', flush=True)
    for job in jobs:
        if job['anim'] != cur:
            cur = job['anim']
            a = cfg['anims'][cur]
            st = setup_anim(cur, a, scene, scale)
            if scale is None:
                scale = st['scale']
            st['drop'] = club_drop_setup(cl, st, a, scene)
        t = time_of(a, st, job['n'], job['i'])
        unfreeze_pose(st)
        set_frame(scene, t)
        if a.get('proc'):
            freeze_pose(st)
            apply_proc(st, a, job['i'])
        off = lock_offset(a, st, t)
        st['root'].matrix_world = Matrix.Rotation(-job['d'] * math.pi / 4.0, 4, 'Z') @ Matrix.Translation(-off) @ st['base']
        bpy.context.view_layer.update()
        if cl is not None:
            place_club(cl, st['arm'])
            club_drop_apply(cl, st.get('drop'), st['root'], t)
            bpy.context.view_layer.update()
        box = dict(w=job['w'], h=job['h'], cx=job['cx'], cy=job['cy'])
        if OMBRE and cfg.get('ombre_variantes'):
            # calage de l'ombre (lumiere.py) : toutes les directions de soleil essayees en une seule passe
            box = json.load(open(os.path.splitext(job['out'])[0] + '.json'))
            for k, o in enumerate(cfg['ombre_variantes']):
                shadow_mask(st, box, os.path.splitext(job['out'])[0] + '_ombre_v%d.png' % k, o)
            print('ombres', job['out'], len(cfg['ombre_variantes']), flush=True)
            continue
        if OMBRE and cfg.get('ombre', {}).get('rapide'):
            box = json.load(open(os.path.splitext(job['out'])[0] + '.json'))
            shadow_mask(st, box, os.path.splitext(job['out'])[0] + '_ombre.png')
            print('ombre', job['out'], flush=True)
            continue
        if OMBRE:
            box = json.load(open(os.path.splitext(job['out'])[0] + '.json'))
            for o in st['meshes']:
                o.visible_camera = False
            frame_camera(scene, cam, box['w'], box['h'], box['cx'], box['cy'])
            scene.render.filepath = os.path.splitext(job['out'])[0] + '_ombre.png'
            bpy.ops.render.render(write_still=True)
            print('ombre', job['out'], flush=True)
            continue
        if cfg.get('auto_box', True):
            box = screen_box(st['meshes'] + st.get('curves', []) + ([cl] if cl is not None else []), cfg.get('box_pad', 4))
            json.dump(box, open(os.path.splitext(job['out'])[0] + '.json', 'w'))
        frame_camera(scene, cam, box['w'], box['h'], box['cx'], box['cy'])
        scene.render.filepath = job['out']
        bpy.ops.render.render(write_still=True)
        if job.get('mask'):
            render_mask(scene, job['mask'])
        if cfg.get('classes'):
            render_classes(scene, st, os.path.splitext(job['out'])[0] + '_classes.png')
        print('rendu', job['out'], flush=True)


if not os.environ.get('SC_NO_MAIN'):
    main()
