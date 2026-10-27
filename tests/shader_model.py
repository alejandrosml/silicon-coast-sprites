# shader_model.py - modele Python de la logique de decodage des shaders (disposition F), pour verifier par
# le calcul (et deboguer) ce que font VPDRAW (recherche de phase) et le bloc commun des shaders de fragments.
import numpy as np

F_BW, F_SB, F_PER = 128, 16, 8


class Tex:
    def __init__(self, img):
        self.a = img[..., 3]
        self.rgb = img[..., :3]
        self.H, self.W = self.a.shape

    def alpha(self, x, y):
        x, y = int(x), int(y)
        if x < 0 or y < 0 or x >= self.W or y >= self.H:
            x = min(max(x, 0), self.W - 1); y = min(max(y, 0), self.H - 1)
        return self.a[y, x] / 255.0

    def bit(self, x, y):
        return 1 if self.alpha(x, y) > 0.002 else 0

    def col(self, x, y):
        x = min(max(int(x), 0), self.W - 1); y = min(max(int(y), 0), self.H - 1)
        return self.rgb[y, x] / 255.0, self.a[y, x] / 255.0


def field(t, x0, y, j0, n):
    return sum(t.bit(x0 + j0 + i, y) << i for i in range(n))


def fsync(t, x0, y):
    return t.bit(x0, y) == 0 and t.bit(x0 + 1, y) == 1 and t.bit(x0 + 2, y) == 1 and t.bit(x0 + 3, y) == 0


def fdata(t, x0, y, d):
    s = d // 9
    return t.bit(x0 + F_SB * s + 7 + (d - 9 * s), y)


def ffield(t, x0, y, d0, n):
    return sum(fdata(t, x0, y, d0 + i) << i for i in range(n))


def fchk(b, m, k, w, h, fl, sub):
    return (b * 7 + m * 13 + (k - 1) * 53 + w * 31 + h * 37 + fl * 97 + sub * 131 + 1543) % 4096


def fblock(t, x0, y, full_sync=True):
    if full_sync:
        for s in range(8):
            xs = x0 + F_SB * s
            if not fsync(t, xs, y) or field(t, xs, y, 4, 3) != s:
                return None
    b = ffield(t, x0, y, 0, 3); m = ffield(t, x0, y, 3, 7); k = ffield(t, x0, y, 10, 3) + 1
    w = ffield(t, x0, y, 13, 10); h = ffield(t, x0, y, 23, 10); fl = ffield(t, x0, y, 33, 4)
    sub = ffield(t, x0, y, 37, 1); cs = ffield(t, x0, y, 38, 12)
    if cs != fchk(b, m, k, w, h, fl, sub) or w < 1 or h < 1:
        return None
    return dict(org=(x0 - b * F_BW, y - m * F_PER), w=w, h=h, k=k, fl=fl, sub=sub)


def rows_needed(n):
    return n - 1 + (n - 1) // 7 + 2


def grid(fl):
    if not (fl >> 1) & 1:
        return 1, 1
    cols = ((fl >> 2) & 3) + 1
    return cols, -(-5 // cols)


def fdims(d):
    M = 4
    gc, gr = grid(d['fl'])
    k, w, h = d['k'], d['w'], d['h']
    if d['sub'] == 0:
        probe = (M, rows_needed(gr * k * h) + M)
        W = max(gc * k * w, w + 2 * M); H = probe[1] + h + M
    else:
        probe = (M, M); W = w + 2 * M + gc * k * w; H = max(rows_needed(gr * k * h), probe[1] + h + M)
    return (-(-W // F_BW) * F_BW, -(-H // F_PER) * F_PER), probe


def ftry(t, tc, x0, y):
    if x0 < 0 or y < 0 or x0 + F_BW > t.W + 0.5 or y > t.H - 0.5:
        return None
    if not fsync(t, x0, y):
        return None
    d = fblock(t, x0, y)
    if d is None:
        return None
    (W, H), _ = fdims(d)
    ox, oy = d['org']
    if tc[0] >= ox - 0.01 and tc[1] >= oy - 0.01 and tc[0] <= ox + W + 0.01 and tc[1] <= oy + H + 0.01:
        return d
    return None


def vs_find(t, tc, ref):
    """meme ordre de recherche que fFind (VPDRAW). Renvoie (d, etape) ou (None, None)."""
    u, v = tc
    d = ftry(t, tc, u - ref[0], v - ref[1])
    if d:
        return d, 'exact'
    for j in range(32):
        dy = 8 * j
        for x0, y in ((u, v + dy), (u - F_BW, v + dy), (u, v - 8 - dy), (u - F_BW, v - 8 - dy)):
            d = ftry(t, tc, x0, y)
            if d:
                return d, 'bord %d' % j
    for j in range(16):
        y = v - 1 - j if j < 8 else v + (j - 8)
        d = ftry(t, tc, u - ref[0], y)
        if d:
            return d, 'local-gauche %d' % j
        for i in range(0, 17):
            xs = u - i
            if xs < 0:
                break
            if not fsync(t, xs, y):
                continue
            s = field(t, xs, y, 4, 3)
            d = ftry(t, tc, xs - F_SB * s, y)
            if d:
                return d, 'local %d,%d' % (j, i)
    return None, None


def fhead(t, b):
    return (fsync(t, *b) and fsync(t, b[0] + 16, b[1]) and field(t, b[0], b[1], 4, 3) == 0
            and field(t, b[0] + 16, b[1], 4, 3) == 1)


OFFS = [(0, 0), (0, -8), (0, 8), (-128, 0), (128, 0), (0, -16), (0, 16), (0, -24), (0, 24), (0, -32), (0, 32),
        (-128, -8), (128, 8)]


def fs_decode(t, T, phase, g=1.0):
    """decode par fragment (scSetup, disposition F) ; codes : 'hd', 'ecarte', 'origine'."""
    px, py = phase
    b0 = (T[0] - ((T[0] - px) % F_BW), T[1] - ((T[1] - py) % F_PER))
    fail = 'ecarte' if g > 0.999 else 'origine'
    if b0[0] >= 0 and b0[1] >= 0 and fhead(t, b0):
        mark, ma = t.col(b0[0] + 1, b0[1])
        cand = False
        offs2 = [(0, 0)] + ([(0, -1), (0, 1)] if T[1] == b0[1] else [])
        for ox, oy in offs2:
            c, a = t.col(T[0] + ox, T[1] + oy)
            if a > 0.002 and abs(c - mark).max() < 0.004:
                cand = True
        if not cand:
            return 'ecarte', 'tri rapide'
    for ox, oy in OFFS:
        c = (b0[0] + ox, b0[1] + oy)
        if c[0] < 0 or c[1] < 0 or not fsync(t, *c):
            continue
        d = fblock(t, c[0], c[1], full_sync=False)
        if d is None:
            continue
        (W, H), probe = fdims(d)
        oxx, oyy = d['org']
        if not (oxx <= T[0] < oxx + W and oyy <= T[1] < oyy + H):
            continue
        po = (oxx + probe[0], oyy + probe[1])
        dd = (T[0] + 0.5 - po[0], T[1] + 0.5 - po[1])
        if dd[0] < 0 or dd[1] < 0 or dd[0] > d['w'] or dd[1] > d['h']:
            return 'ecarte', 'hors sonde'
        return 'hd', d
    return fail, 'aucun bloc lisible'


# ---------------------------------------------------------------- quads FXBltFromClipped (disposition F)
def clip_offsets(margin, mirrored):
    """ecarts entre le texel du sommet et le bord du cadre : (eLx, eRx, eLT, eRB) ; contours (marge 8) :
    quad (2,2,w-3,h-3), en miroir tc.x = w - tc.x"""
    if margin == 2:
        return 0, 0, 0, 0
    return (1, 2, 2, 1) if mirrored else (2, 1, 2, 1)


def vs_clip_find(t, tc, offs, depth_m=64, depth_n=8):
    """recherche du cadre F depuis un sommet de quad FXBltFromClipped : pour chaque coin suppose du cadre, les
    blocs aux positions exactes (lignes speciales de 8 en 8, blocs de 128 en 128), le sommet devant tomber
    exactement sur ce coin du cadre decode. Renvoie (bloc, (hx, hy), candidats lus) ou (None, None, n)."""
    eLx, eRx, eLT, eRB = offs
    u, v = tc
    n_read = 0
    for m in range(depth_m):
        for n in range(depth_n):
            for hyp in range(4):
                hx, hy = hyp % 2, hyp // 2
                x0 = u + eLx + F_BW * n if hx == 0 else u - eRx - F_BW * (n + 1)
                y = v + eLT + F_PER * m if hy == 0 else v - eRB - F_PER * (m + 1)
                if x0 < 0 or y < 0 or x0 + F_BW > t.W or y >= t.H:
                    continue
                n_read += 1
                if not fsync(t, x0, y):
                    continue
                d = fblock(t, x0, y)
                if d is None:
                    continue
                (W, H), probe = fdims(d)
                ox, oy = d['org']
                cx = ox - eLx if hx == 0 else ox + W + eRx
                cy = oy - eLT if hy == 0 else oy + H + eRB
                if (cx, cy) == (u, v):
                    return d, (hx, hy), n_read
    return None, None, n_read
