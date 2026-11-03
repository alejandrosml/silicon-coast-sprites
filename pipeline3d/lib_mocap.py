# lib_mocap.py - Silicon Coast : convertit en lot des animations FBX (Mixamo, Rokoko : squelette de type Mixamo) en
# fichiers .npz (rotations et positions du monde par os et par image, image 0 = pose de repos du squelette source),
# lisibles par retarget.py, et écrit un index (nom, pack, images, im/s, durée, déplacement du bassin).
#   blender -b -P lib_mocap.py -- <dossier des packs décompressés> <dossier de sortie> [--packs A,B,...]
import json
import os
import sys

import bpy
import numpy as np

a = sys.argv[sys.argv.index('--') + 1:]
SRC, OUT = os.path.abspath(a[0]), os.path.abspath(a[1])
PACKS = a[a.index('--packs') + 1].split(',') if '--packs' in a else None
os.makedirs(OUT, exist_ok=True)
idx_path = os.path.join(OUT, 'index.json')
index = json.load(open(idx_path)) if os.path.exists(idx_path) else {}


def convert(fbx, out):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=fbx, ignore_leaf_bones=False, automatic_bone_orientation=False)
    arm = next(o for o in bpy.data.objects if o.type == 'ARMATURE')
    ad = arm.animation_data
    act = ad.action if ad else None
    sc = bpy.context.scene
    f0, f1 = (int(round(x)) for x in act.frame_range) if act else (sc.frame_start, sc.frame_end)
    noms = [b.name.split(':')[-1] for b in arm.data.bones]
    AW = arm.matrix_world.copy()

    def releve(repos):
        R, P = [], []
        for b in arm.data.bones:
            M = AW @ (b.matrix_local if repos else arm.pose.bones[b.name].matrix)
            R.append(np.array(M.to_3x3().normalized()))
            P.append(np.array(M.translation))
        return np.array(R), np.array(P)

    Rs, Ps = [], []
    r, p = releve(True); Rs.append(r); Ps.append(p)
    for f in range(f0, f1 + 1):
        sc.frame_set(f)
        r, p = releve(False); Rs.append(r); Ps.append(p)
    GW = np.transpose(np.array(Rs), (1, 0, 2, 3)).astype(np.float32)
    PW = np.transpose(np.array(Ps), (1, 0, 2)).astype(np.float32)
    fps = sc.render.fps / sc.render.fps_base
    parents = [noms.index(b.parent.name.split(':')[-1]) if b.parent else -1 for b in arm.data.bones]
    np.savez_compressed(out, noms=np.array(noms), GW=GW, PW=PW, dt=1.0 / fps, parents=np.array(parents))
    ih = noms.index('Hips') if 'Hips' in noms else 0
    hips = PW[ih, 1:]
    feet = [noms.index(n) for n in ('LeftToeBase', 'RightToeBase', 'LeftFoot', 'RightFoot') if n in noms]
    h_rest = float(PW[ih, 0, 2] - min(PW[k, 0, 2] for k in feet)) if feet else 1.0
    return dict(images=int(GW.shape[1] - 1), fps=float(fps), duree=float((GW.shape[1] - 1) / fps),
                dep_xy=float(np.hypot(*(hips[-1, :2] - hips[0, :2]))), h_hanches=h_rest,
                z_min_hanches=float(hips[:, 2].min()), z_max_hanches=float(hips[:, 2].max()))


n = 0
for pack in sorted(os.listdir(SRC)):
    d = os.path.join(SRC, pack)
    if not os.path.isdir(d) or (PACKS and pack not in PACKS):
        continue
    os.makedirs(os.path.join(OUT, pack), exist_ok=True)
    for f in sorted(os.listdir(d)):
        if not f.lower().endswith('.fbx') or f.startswith('imoen_GA'):
            continue
        key = pack + '/' + f[:-4]
        out = os.path.join(OUT, pack, f[:-4].replace(' ', '_') + '.npz')
        if key in index and os.path.exists(out):
            continue
        try:
            info = convert(os.path.join(d, f), out)
            info.update(pack=pack, nom=f[:-4], fichier=os.path.relpath(out, OUT))
            index[key] = info
            n += 1
            print('OK', key, info['images'], 'im', round(info['duree'], 2), 's', flush=True)
        except Exception as e:  # noqa: BLE001
            print('ERREUR', key, repr(e)[:200], flush=True)
        if n % 20 == 0:
            json.dump(index, open(idx_path, 'w'), indent=0, ensure_ascii=False)
json.dump(index, open(idx_path, 'w'), indent=0, ensure_ascii=False)
print('FINI', n, 'nouveaux,', len(index), 'au total', flush=True)
