# wed.py - lecture des polygones de murs d'un WED V1.3 et regles de selection du moteur
# (CInfinity::FXRenderClippingPolys [1001e6380]).
import struct
import numpy as np

class Wed:
    def __init__(self, data):
        assert data[:8] == b'WED V1.3', data[:8]
        nov, ndoor, oov, osec, odoor, odcell = struct.unpack('<IIIIII', data[8:32])
        self.w_tiles, self.h_tiles = struct.unpack('<HH', data[oov:oov + 4])
        npoly, opoly, overt, ogroup, olook = struct.unpack('<IIIII', data[osec:osec + 20])
        # les groupes peuvent designer des polygones au-dela du compte des murs (portes, a la suite)
        self.gx = (self.w_tiles * 64 + 639) // 640
        self.gy = (self.h_tiles * 64 + 479) // 480
        ng0 = self.gx * self.gy
        g0 = np.frombuffer(data[ogroup:ogroup + 4 * ng0], '<u2').reshape(-1, 2)
        nlook0 = int(max((s + c for s, c in g0), default=0))
        look0 = np.frombuffer(data[olook:olook + 2 * nlook0], '<u2')
        npoly = max(npoly, int(look0.max()) + 1 if len(look0) else 0)
        self.polys = []
        for i in range(npoly):
            st, cnt, fl, hgt, x0, x1, y0, y1 = struct.unpack('<IIBbHHHH', data[opoly + 18 * i: opoly + 18 * i + 18])
            self.polys.append(dict(start=st, count=cnt, flags=fl, minx=x0, maxx=x1, miny=y0, maxy=y1))
        nv = max(p['start'] + p['count'] for p in self.polys) if self.polys else 0
        self.verts = np.frombuffer(data[overt:overt + 4 * nv], '<u2').reshape(-1, 2).astype(np.int64)
        for p in self.polys:
            p['pts'] = [tuple(v) for v in self.verts[p['start']:p['start'] + p['count']]]
        # groupes de murs : un par cellule de 640 x 480
        self.gx = (self.w_tiles * 64 + 639) // 640
        self.gy = (self.h_tiles * 64 + 479) // 480
        ng = self.gx * self.gy
        groups = np.frombuffer(data[ogroup:ogroup + 4 * ng], '<u2').reshape(-1, 2)
        nlook = int(max((s + c for s, c in groups), default=0))
        look = np.frombuffer(data[olook:olook + 2 * nlook], '<u2')
        self.groups = [[int(i) for i in look[s:s + c]] for s, c in groups]

    def polys_for_rect(self, rect):
        L, T, R, B = rect
        out = set()
        for cy in range(max(0, T // 480), min(self.gy - 1, B // 480) + 1):
            for cx in range(max(0, L // 640), min(self.gx - 1, R // 640) + 1):
                out.update(self.groups[cy * self.gx + cx])
        return sorted(out)

    def applied(self, rect, pos):
        """indices des polygones que le moteur applique a une surface FX de rect monde 'rect' pour
        une creature dont les pieds sont en pos (x, y)."""
        res = []
        L, T, R, B = rect
        for i in self.polys_for_rect(rect):
            p = self.polys[i]
            if p['flags'] & 2 or p['count'] < 3:
                continue
            if not (R > p['minx'] and L < p['maxx'] and B > p['miny'] and T < p['maxy']):
                continue
            if p['flags'] & 1:
                v0, v1 = p['pts'][0], p['pts'][1]
                left, right = (v1, v0) if v0[0] > v1[0] else (v0, v1)
                if left[1] == right[1]:
                    if pos[1] >= left[1]:
                        continue
                else:
                    if left[0] == right[0]:
                        continue
                    s = (left[0] - right[0]) * (pos[1] - left[1]) + (pos[0] - left[0]) * (right[1] - left[1])
                    if s < 0:
                        continue
            res.append(i)
        return res

def search_map(data):
    """BMP 4 bits du search map -> tableau (h, w) de valeurs 0..15 (haut en premier)"""
    off = struct.unpack('<I', data[10:14])[0]
    w, h = struct.unpack('<ii', data[18:26])
    bpp = struct.unpack('<H', data[28:30])[0]
    assert bpp == 4, bpp
    stride = ((w * 4 + 31) // 32) * 4
    rows = []
    for y in range(abs(h)):
        row = data[off + y * stride: off + y * stride + (w + 1) // 2]
        v = np.frombuffer(row, np.uint8)
        px = np.empty(len(v) * 2, np.uint8); px[0::2] = v >> 4; px[1::2] = v & 15
        rows.append(px[:w])
    a = np.array(rows)
    return a[::-1] if h > 0 else a
