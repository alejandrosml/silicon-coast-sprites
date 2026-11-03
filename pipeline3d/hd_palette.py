# hd_palette.py - Silicon Coast : rendus 3D -> images a palette du jeu, avec sous-teintes (format SC-HD).
#
# Mode « fixe » : les couleurs 88-255 de la palette du BAM sont refaites a partir des rendus, en 21 degrades de 8
# teintes (le successeur d'une teinte est la suivante du degrade, comme dans le shader SC-HD). Chaque pixel recoit
# l'indice I de la teinte inferieure et F (0..7), la position vers la teinte suivante : le shader affiche
# P[I] + (P[I+1] - P[I]) * F / 8. Les gammes 4-87 (couleurs de la creature, changees par le moteur) ne servent pas
# en mode fixe : le rendu garde ses couleurs telles quelles.
import numpy as np

FIXED0, NFAM, NSH = 88, 21, 8


def srgb_to_lab(rgb):
    """rgb : (..., 3) en 0..1 (sRGB) -> Lab (D65)."""
    c = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    M = np.array([[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750],
                  [0.0193339, 0.1191920, 0.9503041]])
    xyz = c @ M.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 216 / 24389, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    L = 116 * f[..., 1] - 16
    a = 500 * (f[..., 0] - f[..., 1])
    b = 200 * (f[..., 1] - f[..., 2])
    return np.stack([L, a, b], -1)


def lab_to_srgb(lab):
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    fy = (L + 16) / 116
    fx = fy + a / 500
    fz = fy - b / 200
    e, k = 216 / 24389, 24389 / 27
    x = np.where(fx ** 3 > e, fx ** 3, (116 * fx - 16) / k)
    y = np.where(L > k * e, fy ** 3, L / k)
    z = np.where(fz ** 3 > e, fz ** 3, (116 * fz - 16) / k)
    xyz = np.stack([x, y, z], -1) * np.array([0.95047, 1.0, 1.08883])
    Minv = np.array([[3.2404542, -1.5371385, -0.4985314], [-0.9692660, 1.8760108, 0.0415560],
                     [0.0556434, -0.2040259, 1.0572252]])
    c = np.clip(xyz @ Minv.T, 0, 1)
    return np.where(c <= 0.0031308, 12.92 * c, 1.055 * c ** (1 / 2.4) - 0.055)


def kmeans(X, k, iters=30, seed=0):
    rng = np.random.default_rng(seed)
    C = X[rng.choice(len(X), k, replace=False)].copy()
    for _ in range(iters):
        d = ((X[:, None, :] - C[None]) ** 2).sum(-1)
        lab = d.argmin(1)
        for j in range(k):
            sel = X[lab == j]
            if len(sel):
                C[j] = sel.mean(0)
            else:
                C[j] = X[rng.integers(len(X))]
    return C, lab


def build_palette(samples_rgb, n_fam=NFAM, n_sh=NSH, chroma_weight=1.6):
    """samples_rgb : (N, 3) en 0..1. Renvoie (familles : centres (a, b) et teintes Lab (n_fam, n_sh, 3), palette 88-255 RGB 0..255)."""
    lab = srgb_to_lab(samples_rgb)
    X = lab[:, 1:] * chroma_weight
    C, lab_idx = kmeans(X, n_fam)
    shades = np.zeros((n_fam, n_sh, 3))
    for j in range(n_fam):
        sel = lab[lab_idx == j]
        if len(sel) < n_sh:
            sel = lab[np.argsort(((X - C[j]) ** 2).sum(1))[:max(n_sh * 4, 64)]]
        Ls = np.sort(sel[:, 0])
        qs = np.linspace(0.02, 0.98, n_sh)
        for s, q in enumerate(qs):
            Lq = Ls[int(q * (len(Ls) - 1))]
            near = sel[np.abs(sel[:, 0] - Lq) <= max(2.0, (Ls[-1] - Ls[0]) / (2 * n_sh))]
            shades[j, s] = near.mean(0) if len(near) else (Lq, C[j][0] / chroma_weight, C[j][1] / chroma_weight)
        shades[j] = shades[j][np.argsort(shades[j][:, 0])]          # du plus sombre au plus clair
    pal = np.round(lab_to_srgb(shades.reshape(-1, 3)) * 255).astype(np.uint8)
    return C / chroma_weight, shades, pal


def quantize(rgb, fam_ab, shades, chroma_weight=1.6):
    """rgb : (..., 3) 0..1 -> (I indice 88.., F 0..7)."""
    lab = srgb_to_lab(rgb.reshape(-1, 3))
    # famille : la plus proche en chroma (a, b), departagee par la distance au degrade
    best_d = np.full(len(lab), np.inf); best_j = np.zeros(len(lab), int); best_t = np.zeros(len(lab))
    best_s = np.zeros(len(lab), int)
    for j in range(len(shades)):
        sh = shades[j]
        for s in range(len(sh) - 1):
            p, q = sh[s], sh[s + 1]
            v = q - p
            vv = max((v * v).sum(), 1e-9)
            t = np.clip(((lab - p) @ v) / vv, 0, 1)
            proj = p + t[:, None] * v
            dd = lab - proj
            d = dd[:, 0] ** 2 + (chroma_weight ** 2) * (dd[:, 1] ** 2 + dd[:, 2] ** 2)
            better = d < best_d
            best_d[better] = d[better]; best_j[better] = j; best_s[better] = s; best_t[better] = t[better]
    F = np.round(best_t * 8).astype(int)
    up = F >= 8
    best_s[up] += 1; F[up] = 0
    I = FIXED0 + best_j * NSH + best_s
    return I.reshape(rgb.shape[:-1]).astype(np.uint8), F.reshape(rgb.shape[:-1]).astype(np.uint8)
