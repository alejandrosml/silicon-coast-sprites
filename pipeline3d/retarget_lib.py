# retarget_lib.py - Silicon Coast, chaîne des monstres 3D : reciblage de captures de mouvement (dans Blender).
# Même méthode que reciblage_bvh.py (rotations du monde par rapport à une pose de référence ; seuls les membres
# sont alignés sur la pose en T de la capture, le tronc, le cou, la tête et les clavicules gardent la posture du
# personnage), écrite en fonctions pour comparer des centaines de captures dans une même session Blender.
#   src = Source('clip.npz' | 'clip.bvh')
#   rc = Reciblage(arm, src, sur_place=True, cap='auto')
#   poses = rc.poses(images)        # liste de {os: Matrix 4x4 (matrix_basis)}
#   applique(arm, poses[k])         # pose une image ;  ecrit_action(arm, poses, 'nom')
import math

import numpy as np
from mathutils import Matrix, Quaternion, Vector

C_BVH = np.array([[1.0, 0, 0], [0, 0, -1.0], [0, 1.0, 0]])     # BVH (Y en haut, regard +Z) -> Blender


def _rot_axe(axe, deg):
    t = np.radians(deg); c, s = np.cos(t), np.sin(t); n = len(t)
    R = np.zeros((n, 3, 3)); R[:, 0, 0] = R[:, 1, 1] = R[:, 2, 2] = 1
    p, q = {'X': (1, 2), 'Y': (2, 0), 'Z': (0, 1)}[axe]
    R[:, p, p] = c; R[:, q, q] = c; R[:, p, q] = -s; R[:, q, p] = s
    return R


class Source:
    """capture : rotations GW (os x images x 3 x 3) et positions PW (os x images x 3) dans le repère de Blender ;
    image 0 = pose de référence (pose en T)."""

    def __init__(self, chemin):
        self.chemin = chemin
        if chemin.endswith('.npz'):
            z = np.load(chemin, allow_pickle=True)
            self.noms = [str(n) for n in z['noms']]
            self.parents = [int(p) for p in z['parents']]
            self.GW, self.PW, self.dt = z['GW'].astype(np.float64), z['PW'].astype(np.float64), float(z['dt'])
            self.bout = {n: np.array([0, 1.0, 0]) for n in self.noms}
            self.type = 'mixamo'
        else:
            self._lit_bvh(chemin)
            self.type = 'cmu'
        self.idx = {n: k for k, n in enumerate(self.noms)}
        self.n = self.GW.shape[1]

    def _lit_bvh(self, chemin):
        tok = open(chemin).read().split()
        J = []

        def lit(i, parent):
            nom = tok[i + 1]; i += 2; i += 1
            j = dict(nom=nom, parent=parent, off=np.zeros(3), can=[], bout=None)
            k = len(J); J.append(j)
            while tok[i] != '}':
                t = tok[i]
                if t == 'OFFSET':
                    j['off'] = np.array([float(x) for x in tok[i + 1:i + 4]]); i += 4
                elif t == 'CHANNELS':
                    n = int(tok[i + 1]); j['can'] = tok[i + 2:i + 2 + n]; i += 2 + n
                elif t == 'JOINT':
                    i = lit(i, k)
                elif t == 'End':
                    j['bout'] = np.array([float(x) for x in tok[i + 4:i + 7]]); i += 8
                else:
                    raise ValueError('BVH : ' + t)
            return i + 1
        i = lit(1, -1)
        NF, DT = int(tok[i + 2]), float(tok[i + 5])
        DATA = np.array(tok[i + 6:], float).reshape(NF, -1)
        G = np.zeros((len(J), NF, 3, 3)); P = np.zeros((len(J), NF, 3))
        col = 0
        for k, j in enumerate(J):
            R = np.tile(np.eye(3), (NF, 1, 1)); pos = np.zeros((NF, 3))
            for c in j['can']:
                v = DATA[:, col]; col += 1
                if c.endswith('position'):
                    pos[:, 'XYZ'.index(c[0])] = v
                else:
                    R = R @ _rot_axe(c[0], v)
            if j['parent'] < 0:
                G[k] = R; P[k] = j['off'] + pos
            else:
                pk = j['parent']
                G[k] = G[pk] @ R; P[k] = P[pk] + np.einsum('fij,j->fi', G[pk], j['off'])
        C = C_BVH
        self.GW = np.einsum('ij,kfjl,lm->kfim', C, G, C.T)
        self.PW = np.einsum('ij,kfj->kfi', C, P)
        self.noms = [j['nom'] for j in J]
        self.parents = [j['parent'] for j in J]
        self.dt = DT
        self.bout = {j['nom']: (C @ j['bout'] if j['bout'] is not None else np.array([0, 1.0, 0])) for j in J}
        self._cmu = True


def correspondances(src):
    if src.type == 'mixamo':
        CORR = {n: n for n in ('Hips', 'Spine', 'Spine1', 'Spine2', 'Neck', 'Head')}
        SUIV = {'Spine': 'Spine1', 'Spine1': 'Spine2', 'Spine2': 'Neck', 'Neck': 'Head', 'Head': None}
        for c in ('Left', 'Right'):
            for b in ('Shoulder', 'Arm', 'ForeArm', 'Hand', 'UpLeg', 'Leg', 'Foot', 'ToeBase'):
                CORR[c + b] = c + b
            SUIV.update({c + 'Shoulder': c + 'Arm', c + 'Arm': c + 'ForeArm', c + 'ForeArm': c + 'Hand',
                         c + 'Hand': c + 'HandMiddle1' if (c + 'HandMiddle1') in src.idx else None,
                         c + 'UpLeg': c + 'Leg', c + 'Leg': c + 'Foot', c + 'Foot': c + 'ToeBase', c + 'ToeBase': None})
    else:
        CORR = {'Hips': 'Hips', 'LowerBack': 'Spine', 'Spine': 'Spine1', 'Spine1': 'Spine2', 'Neck': 'Neck',
                'Head': 'Head'}
        SUIV = {'LowerBack': 'Spine', 'Spine': 'Spine1', 'Spine1': 'Neck', 'Neck': 'Head', 'Head': None}
        for c in ('Left', 'Right'):
            for b in ('Shoulder', 'Arm', 'ForeArm', 'Hand', 'UpLeg', 'Leg', 'Foot', 'ToeBase'):
                CORR[c + b] = c + b
            SUIV.update({c + 'Shoulder': c + 'Arm', c + 'Arm': c + 'ForeArm', c + 'ForeArm': c + 'Hand',
                         c + 'Hand': c + 'FingerBase' if (c + 'FingerBase') in src.idx else None,
                         c + 'UpLeg': c + 'Leg', c + 'Leg': c + 'Foot', c + 'Foot': c + 'ToeBase', c + 'ToeBase': None})
        if 'Neck1' in src.idx:
            SUIV['Neck'] = 'Head'
    return CORR, SUIV


MEMBRES = ('Arm', 'ForeArm', 'Hand', 'UpLeg', 'Leg', 'Foot', 'ToeBase')


class Reciblage:
    def __init__(self, arm, src, sur_place=False, cap='auto', cap_sur='bassin', f0=0):
        self.arm, self.src = arm, src
        CORR, SUIV = correspondances(src)
        self.SUIV = SUIV
        pref = 'mixamorig:' if any(b.name.startswith('mixamorig:') for b in arm.data.bones) else ''
        self.pref = pref
        self.AW = arm.matrix_world.copy(); self.AWr = self.AW.to_quaternion(); self.AWri = self.AWr.inverted()
        self.cibles = {s: pref + t for s, t in CORR.items() if s in src.idx and (pref + t) in arm.data.bones}
        self.src_de = {t: s for s, t in self.cibles.items()}
        self.ordre = [b.name for b in arm.data.bones]
        self.rest = {b.name: b.matrix_local.copy() for b in arm.data.bones}
        self.relp = {b.name: (self.rest[b.parent.name].inverted() @ self.rest[b.name]) if b.parent else None
                     for b in arm.data.bones}
        self.parent = {b.name: (b.parent.name if b.parent else None) for b in arm.data.bones}
        self.sur_place = sur_place
        self.f0 = f0
        # pose de référence : membres alignés sur la capture en T
        basis, M, RT = {}, {}, {}
        for nb in self.ordre:
            M[nb] = self._m(nb, M, basis.get(nb))
            if nb not in self.src_de:
                continue
            W = self.AWr @ M[nb].to_quaternion()
            s = self.src_de[nb]
            if s != 'Hips' and any(s.endswith(m) and 'Shoulder' not in s for m in MEMBRES):
                d_t = (self.AWr @ (M[nb].to_3x3() @ Vector((0, 1, 0)))).normalized()
                q = d_t.rotation_difference(self._dir_source(s, f0))
                W = q @ W
                basis[nb] = self._basis(nb, M, self.AWri @ W)
                M[nb] = self._m(nb, M, basis[nb])
            RT[nb] = W
        self.RT = RT
        self.M_T = M
        GW, PW, idx = src.GW, src.PW, src.idx
        pieds = [idx[n] for n in ('LeftToeBase', 'RightToeBase', 'LeftFoot', 'RightFoot') if n in idx]
        self.h_src = PW[idx['Hips'], f0, 2] - min(PW[k, f0, 2] for k in pieds)
        hips = self.cibles['Hips']; self.hips = hips
        self.h_cib_w = self.AW @ M[hips].translation
        pc = [self.AW @ M[pref + n].translation for n in ('LeftToeBase', 'RightToeBase', 'LeftFoot', 'RightFoot')
              if pref + n in arm.data.bones]
        self.h_cib = self.h_cib_w.z - min(p.z for p in pc)
        self.ECH = self.h_cib / max(self.h_src, 1e-9)
        self.RS0 = {s: Matrix(GW[idx[s], f0].tolist()).to_quaternion() for s in self.cibles}
        self.cap = cap; self.cap_sur = cap_sur

    # -- outils
    def _m(self, nb, M, L):
        L = L if L is not None else Matrix.Identity(4)
        p = self.parent[nb]
        return (self.rest[nb] if p is None else M[p] @ self.relp[nb]) @ L

    def _basis(self, nb, M, rot_arm, loc_arm=None):
        p = self.parent[nb]
        Pm = self.rest[nb] if p is None else M[p] @ self.relp[nb]
        q = Pm.to_quaternion().inverted() @ rot_arm
        L = q.to_matrix().to_4x4()
        if loc_arm is not None:
            L.translation = Pm.to_3x3().inverted() @ (loc_arm - Pm.translation)
        return L

    def _dir_source(self, nom, f):
        src = self.src
        k = src.idx[nom]; s = self.SUIV.get(nom)
        if s is not None and s in src.idx:
            v = src.PW[src.idx[s], f] - src.PW[k, f]
        else:
            v = src.GW[k, f] @ src.bout.get(nom, np.array([0, 1.0, 0]))
        return Vector((v / max(np.linalg.norm(v), 1e-9)).tolist())

    def angle_cap(self, images):
        src = self.src
        if self.cap != 'auto':
            return math.radians(float(self.cap))
        idx = src.idx
        k_ = idx[{'bassin': 'Hips', 'tete': 'Head', 'poitrine': 'Spine2' if 'Spine2' in idx else 'Spine1'}[self.cap_sur]]
        dep = src.PW[idx['Hips'], images[-1]] - src.PW[idx['Hips'], images[0]]
        if self.sur_place and np.hypot(dep[0], dep[1]) > 0.2 * self.h_src:
            return math.atan2(dep[0], -dep[1])
        angs = []
        for f in images:
            v = (src.GW[k_, f] @ src.GW[k_, self.f0].T) @ np.array([0, -1.0, 0])
            angs.append(math.atan2(v[0], -v[1]))
        return math.atan2(np.mean(np.sin(angs)), np.mean(np.cos(angs)))

    def poses(self, images):
        """poses (matrix_basis par os) pour les images données de la capture (indices dans GW, 0 = pose en T)."""
        src = self.src
        idx = src.idx
        ang = self.angle_cap(images)
        Ycorr = Quaternion((0, 0, 1), -ang)
        self.ang = ang
        p0 = Vector(src.PW[idx['Hips'], images[0]].tolist())
        out = []
        for f in images:
            basis, M = {}, {}
            for nb in self.ordre:
                if nb in self.src_de:
                    s = self.src_de[nb]
                    RSf = Matrix(src.GW[idx[s], f].tolist()).to_quaternion()
                    W = Ycorr @ RSf @ self.RS0[s].inverted() @ self.RT[nb]
                    loc = None
                    if s == 'Hips':
                        dp = Ycorr @ (Vector(src.PW[idx['Hips'], f].tolist()) - p0)
                        loc = self.AW.inverted() @ (self.h_cib_w + dp * self.ECH)
                    basis[nb] = self._basis(nb, M, self.AWri @ W, loc)
                M[nb] = self._m(nb, M, basis.get(nb))
            out.append(basis)
        if self.sur_place and len(out) > 2:
            hb = self.hips
            Wl = np.array([list(self.AW @ (self.rest[hb] @ p[hb]).translation) for p in out])
            t = np.arange(len(out))
            ref = (self.AW @ self.M_T[hb].translation)
            for ax in (0, 1):
                k_, b_ = np.polyfit(t, Wl[:, ax], 1)
                Wl[:, ax] -= k_ * t + b_ - ref[ax]
            for n, p in enumerate(out):
                want = self.AW.inverted() @ Vector(Wl[n].tolist())
                L = p[hb].copy()
                L.translation = self.rest[hb].to_3x3().inverted() @ (want - self.rest[hb].translation)
                p[hb] = L
        return out


def applique(arm, basis, defaut=True):
    for pb in arm.pose.bones:
        L = basis.get(pb.name)
        if L is None:
            if defaut:
                pb.matrix_basis = Matrix.Identity(4)
            continue
        pb.matrix_basis = L


def interpole(poses, t):
    """pose au temps fractionnaire t (indice dans poses), interpolation sphérique."""
    t = min(max(t, 0.0), len(poses) - 1.0)
    i = int(math.floor(t)); w = t - i
    if w < 1e-6 or i + 1 >= len(poses):
        return {k: v.copy() for k, v in poses[i].items()}
    a, b = poses[i], poses[i + 1]
    out = {}
    for k in a:
        la, qa, _ = a[k].decompose(); lb, qb, _ = b[k].decompose()
        q = qa.slerp(qb, w)
        M = q.to_matrix().to_4x4(); M.translation = la.lerp(lb, w)
        out[k] = M
    return out


def ecrit_action(arm, poses, nom, fps=30):
    import bpy
    arm.animation_data_clear()
    for pb in arm.pose.bones:
        pb.rotation_mode = 'QUATERNION'
        pb.location = (0, 0, 0); pb.rotation_quaternion = (1, 0, 0, 0); pb.scale = (1, 1, 1)
    hb = next((b.name for b in arm.data.bones if b.name.endswith('Hips')), None)
    for n, basis in enumerate(poses):
        fr = n + 1
        for nb, L in basis.items():
            pb = arm.pose.bones[nb]
            loc, q, _ = L.decompose()
            pb.rotation_quaternion = q
            pb.keyframe_insert('rotation_quaternion', frame=fr, group=nb)
            if nb == hb:
                pb.location = loc
                pb.keyframe_insert('location', frame=fr, group=nb)
    act = arm.animation_data.action
    act.name = nom
    sc = bpy.context.scene
    sc.frame_start, sc.frame_end = 1, len(poses)
    sc.render.fps = fps
    return act
