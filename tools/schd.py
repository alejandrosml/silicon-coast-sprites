# schd.py - format "SC-HD sprites v2" (Silicon Coast, MIT)
#
# Un cadre BAM V1 "HD" garde l'echelle du moteur (1 texel = 1 px du monde) et contient :
#   - deux colonnes-reperes ("spines") de S colonnes, a gauche et a droite du cadre ;
#     chaque ligne de spine est autonome : motif, numero de ligne, disposition, k, w, h,
#     drapeaux et somme de controle ;
#   - un "bloc-sonde" opaque w x h (la taille du sprite d'origine), place pour que
#     l'ancrage (les pieds) tombe exactement la ou le moteur placerait le sprite d'origine ;
#   - l'image HD (k*w x k*h, memes indices de palette que l'original), a cote du bloc-sonde.
# Le moteur compose ce cadre dans sa surface FX comme d'habitude (palette, teintes, ombres,
# transparence, murs a l'echelle 1:1). Le shader de sommets lit les spines aux coins du quad,
# deplace le quad sur le bloc-sonde ; le shader de fragments affiche l'image HD reduite k fois,
# avec l'effet des murs lu dans le bloc-sonde (qui est, lui, au bon endroit du monde).
import numpy as np

S = 60            # largeur d'une spine (58 bits + texel de reference d'ombre + 1 vide)
G = 4             # marge entre bloc-sonde et image HD
PA = [1,0,1,1,0,0,1,1,1,0,1,0]
PB = [1,1,0,0,1,0,1,1,0,0,0,1]
LAYOUT_SIDE, LAYOUT_TOP = 0, 1
MAXDIM = 1000     # la surface FX (cadre + 2) doit tenir dans l'atlas 1024 x 1024 du moteur
J_ROW, J_LAY, J_K, J_W, J_H, J_FL, J_CS, J_SHREF = 12, 22, 23, 26, 36, 46, 50, 58
FLAG_PALALPHA = 1
FLAG_SUBSHADE = 2    # 5 plans : I, S = succ(I), F0, F1, F2 (sous-teintes bg2hd, F = 0..7)
N_PLANES_SUB = 5


def planes_grid(flags):
    """(colonnes, lignes) de la grille des plans de l'image HD : 1 x 1, ou 5 plans sur 'cols' colonnes
    (bits 2-3 des drapeaux = cols - 1)."""
    if not flags & FLAG_SUBSHADE:
        return 1, 1
    cols = ((flags >> 2) & 3) + 1
    return cols, -(-N_PLANES_SUB // cols)


def subshade_flags(cols, palalpha=False):
    return FLAG_SUBSHADE | ((cols - 1) << 2) | (FLAG_PALALPHA if palalpha else 0)

def bits(v, n):
    return [(int(v) >> i) & 1 for i in range(n)]

def checksum(r, layout, k, w, h, flags):
    # meme formule que le shader (flottants exacts < 2^24)
    return int((r + layout * 37 + (k - 1) * 53 + w * 7 + h * 11 + flags * 97 + 89) % 256)

def layout_dims(w, h, k, layout, flags=0):
    """renvoie (W, H, (px,py) bloc-sonde, (hx,hy) image HD) ; l'image HD est une grille de plans
    (un seul plan sans sous-teintes) de k*w x k*h chacun."""
    cols, rows = planes_grid(flags)
    if layout == LAYOUT_SIDE:
        W = 2 * S + w + G + cols * k * w
        H = rows * k * h
        return W, H, (S, H - h), (S + w + G, 0)
    W = 2 * S + cols * k * w
    H = rows * k * h + G + h
    return W, H, (S, rows * k * h + G), (S, 0)

def choose_layout(w, h, k, flags=0):
    """image HD au-dessus du sprite de preference : sur de vraies zones (AR0602, AR0700, AR0300),
    c'est la disposition la moins exposee aux murs du moteur (40-56 % des positions contre 59-69 %
    a cote et 87-96 % en dessous) ; a cote si le cadre serait trop haut."""
    for lay in (LAYOUT_TOP, LAYOUT_SIDE):
        W, H, _, _ = layout_dims(w, h, k, lay, flags)
        if W <= MAXDIM and H <= MAXDIM:
            return lay
    return None

def spine_row(r, layout, k, w, h, flags, pattern):
    seq = list(pattern) + bits(r, 10) + [layout] + bits(k - 1, 3) + bits(w, 10) + bits(h, 10) \
        + bits(flags, 4) + bits(checksum(r, layout, k, w, h, flags), 8)
    assert len(seq) == J_SHREF
    return seq

def build_frame(orig, hd, cx, cy, k, tidx=0, mark=2, shadow_idx=1, flags=0, layout=None):
    """orig : indices d'origine (h,w) ; hd : indices HD (k*h, k*w).
    Renvoie (pix, cx', cy', layout) ou None si le cadre HD serait trop grand."""
    h, w = orig.shape
    assert hd.shape == (k * h, k * w), (hd.shape, (k * h, k * w))
    if layout is None:
        layout = choose_layout(w, h, k)
        if layout is None:
            return None
    W, H, (px, py), (hx, hy) = layout_dims(w, h, k, layout)
    pix = np.full((H, W), tidx, np.uint8)
    pix[hy:hy + k * h, hx:hx + k * w] = hd
    pix[py:py + h, px:px + w] = mark
    for r in range(H):
        a = spine_row(r, layout, k, w, h, flags, PA)
        b = spine_row(r, layout, k, w, h, flags, PB)
        for j in range(J_SHREF):
            pix[r, j] = mark if a[j] else tidx
            pix[r, W - 1 - j] = mark if b[j] else tidx
        pix[r, J_SHREF] = shadow_idx
        pix[r, W - 1 - J_SHREF] = shadow_idx
    return pix, px + cx, py + cy, layout

def read_row(alpha_row, x0, direction):
    """lit une ligne de spine (alpha > 0 -> 1) a partir de x0 vers direction (+1/-1).
    Renvoie dict ou None (motif/somme incorrects)."""
    n = len(alpha_row)
    def bit(j):
        x = x0 + direction * j
        return 1 if 0 <= x < n and alpha_row[x] > 0 else 0
    pat = PA if direction > 0 else PB
    for j in range(12):
        if bit(j) != pat[j]:
            return None
    val = lambda j0, nb: sum(bit(j0 + i) << i for i in range(nb))
    r, lay, k = val(J_ROW, 10), bit(J_LAY), val(J_K, 3) + 1
    w, h, fl, cs = val(J_W, 10), val(J_H, 10), val(J_FL, 4), val(J_CS, 8)
    if cs != checksum(r, lay, k, w, h, fl) or w < 1 or h < 1:
        return None
    W, H, probe, hdo = layout_dims(w, h, k, lay, fl)
    if r >= H or W > 1023 or H > 1023:
        return None
    return dict(r=r, layout=lay, k=k, w=w, h=h, flags=fl, W=W, H=H, probe=probe, hd=hdo)

def is_valid_build(pix, tidx=0, rows=None):
    alpha = (pix != tidx).astype(np.uint8)
    H, W = pix.shape
    for r in ((0, H // 2, H - 1) if rows is None else rows):
        a = read_row(alpha[r], 0, +1); b = read_row(alpha[r], W - 1, -1)
        if a is None or b is None or a['r'] != r or b['r'] != r or a['W'] != W or a['H'] != H:
            return False
    return True

# ---------------------------------------------------------------- agrandissement (PoC)
def scale2x(a, tidx=None):
    """Scale2x (EPX) sur indices de palette : preserve exactement la palette."""
    h, w = a.shape
    p = np.pad(a, 1, mode='edge')
    B = p[0:h, 1:w + 1]; D = p[1:h + 1, 0:w]; E = p[1:h + 1, 1:w + 1]
    F = p[1:h + 1, 2:w + 2]; Hh = p[2:h + 2, 1:w + 1]
    c = (B != Hh) & (D != F)
    e0 = np.where(c & (D == B), D, E); e1 = np.where(c & (B == F), F, E)
    e2 = np.where(c & (D == Hh), D, E); e3 = np.where(c & (Hh == F), F, E)
    out = np.empty((2 * h, 2 * w), a.dtype)
    out[0::2, 0::2] = e0; out[0::2, 1::2] = e1; out[1::2, 0::2] = e2; out[1::2, 1::2] = e3
    return out

def scale4x(a):
    return scale2x(scale2x(a))

def pick_mark(palette, tidx=0):
    """indice opaque pour les spines et le bloc-sonde : ni transparent, ni ombre, ni vert pur
    (0x00FF00 est rendu transparent par le moteur), alpha de palette nul (opaque)."""
    pal = np.asarray(palette)
    best = None
    for i in range(2, 256):
        if i == tidx:
            continue
        b, g, r, a = [int(v) for v in pal[i]]
        if (r, g, b) == (0, 255, 0) or a not in (0, 255):
            continue
        lum = 0.299 * r + 0.587 * g + 0.114 * b
        if best is None or lum > best[0]:
            best = (lum, i)
    return best[1]

def palette_has_alpha(palette):
    a = np.asarray(palette)[:, 3]
    return bool(((a != 0) & (a != 255)).any())

# ---------------------------------------------------------------- multi-calques (personnages equipes)
# Le moteur reunit corps, casque, bouclier et arme dans une seule surface FX : rectangle = union des
# cadres, point de reference = max des centres (CGameAnimationTypeCharacter::CalculateFxRect). Si tous
# les calques d'une meme image (groupe, cycle, image) ont exactement la meme geometrie, l'union est ce
# cadre et chaque calque est copie a l'origine : les spines et le bloc-sonde du corps restent aux coins,
# et les images HD des calques se superposent dans la zone HD, dans l'ordre de dessin du moteur.
# Le corps porte spines + bloc-sonde + image HD ; un calque d'equipement ne porte que son image HD.

def spine_bits(rows, layout, k, w, h, flags, pattern):
    """bits (n, 58) des lignes 'rows' (meme contenu que spine_row, vectorise)."""
    rows = np.asarray(rows, dtype=np.int64)
    n = len(rows)
    out = np.zeros((n, J_SHREF), np.uint8)
    out[:, 0:12] = np.asarray(pattern, np.uint8)
    out[:, J_ROW:J_ROW + 10] = (rows[:, None] >> np.arange(10)) & 1
    out[:, J_LAY] = layout
    out[:, J_K:J_K + 3] = bits(k - 1, 3)
    out[:, J_W:J_W + 10] = bits(w, 10)
    out[:, J_H:J_H + 10] = bits(h, 10)
    out[:, J_FL:J_FL + 4] = bits(flags, 4)
    cs = (rows + layout * 37 + (k - 1) * 53 + w * 7 + h * 11 + flags * 97 + 89) % 256
    out[:, J_CS:J_CS + 8] = (cs[:, None] >> np.arange(8)) & 1
    return out

def vs_rows(H):
    """lignes que VPDRAW peut lire : 8 premieres et 8 dernieres, puis de 8 en 8 depuis chaque bord
    (balayage des coins), plus les lignes d'echantillonnage de l'alpha de reference (17) et du
    texel d'ombre (9). Des spines sur ces seules lignes se decodent exactement comme des spines
    pleine hauteur, murs "effacants" compris, pour bien moins de memoire."""
    r = set(range(min(8, H))) | set(range(max(0, H - 8), H))
    r |= set(range(8, H, 8)) | set(H - 1 - d for d in range(8, H, 8))
    r |= set(int(np.floor(i * 0.0625 * (H - 1))) for i in range(17))
    r |= set(int(np.floor(i * 0.125 * (H - 1))) for i in range(9))
    return np.array(sorted(x for x in r if 0 <= x < H))

def spine_rows_for(H, bands):
    """lignes portant les spines : toutes (bands=None), lignes lues par le shader (bands='vs')
    ou une bande de 'bands' lignes en haut et en bas."""
    if bands is None:
        return np.arange(H)
    if bands == 'vs':
        return vs_rows(H)
    if 2 * bands >= H:
        return np.arange(H)
    return np.concatenate([np.arange(bands), np.arange(H - bands, H)])

class Geometry:
    """geometrie canonique d'une image : etendues (L, T, R, B) autour du point d'ancrage."""
    __slots__ = ('L', 'T', 'R', 'B', 'k', 'w', 'h', 'layout', 'W', 'H', 'probe', 'hd', 'flags')
    def __init__(self, L, T, R, B, k, layout=None, flags=0):
        self.L, self.T, self.R, self.B, self.k = int(L), int(T), int(R), int(B), int(k)
        self.w, self.h = self.L + self.R, self.T + self.B
        self.flags = flags
        self.layout = choose_layout(self.w, self.h, k, flags) if layout is None else layout
        if self.layout is not None:
            self.W, self.H, self.probe, self.hd = layout_dims(self.w, self.h, k, self.layout, flags)
    @property
    def center(self):
        """(cx, cy) du cadre SC-HD : le point d'ancrage dans le bloc-sonde"""
        return self.probe[0] + self.L, self.probe[1] + self.T

def canvas_1x(pix, cx, cy, g, tidx):
    """place un cadre d'origine (ancre cx, cy) dans le rectangle canonique w x h."""
    c = np.full((g.h, g.w), tidx, np.uint8)
    ox, oy = g.L - cx, g.T - cy
    h, w = pix.shape
    x0, y0 = max(0, ox), max(0, oy)
    x1, y1 = min(g.w, ox + w), min(g.h, oy + h)
    if x1 > x0 and y1 > y0:
        c[y0:y1, x0:x1] = pix[y0 - oy:y1 - oy, x0 - ox:x1 - ox]
    return c

def upscale_canvas(c, k, tidx, how='scale4x'):
    """agrandit le rectangle canonique ; le dehors est transparent (bord transparent d'1 texel)."""
    p = np.pad(c, 1, constant_values=tidx)
    if how == 'scale4x' and k == 4:
        u = scale4x(p)
    elif how == 'scale4x' and k == 2:
        u = scale2x(p)
    else:
        u = np.kron(p, np.ones((k, k), np.uint8))
    return np.ascontiguousarray(u[k:-k, k:-k])

def plane_grid_image(planes, cols, tidx):
    """assemble les plans (liste de tableaux kh x kw) en grille de 'cols' colonnes."""
    kh, kw = planes[0].shape
    rows = -(-len(planes) // cols)
    out = np.full((rows * kh, cols * kw), tidx, np.uint8)
    for p, a in enumerate(planes):
        cx, cy = p % cols, p // cols
        out[cy * kh:(cy + 1) * kh, cx * kw:(cx + 1) * kw] = a
    return out


def build_layer(hd, g, body, tidx=0, mark=2, shadow_idx=1, flags=0, bands=None):
    """cadre SC-HD d'un calque selon la geometrie canonique g.
    body=True : spines (sur 'bands' lignes en haut et en bas, ou toutes), bloc-sonde et image HD ;
    body=False : image HD seule (calque d'equipement).
    hd : image HD (k*h, k*w), ou grille de plans deja assemblee (sous-teintes)."""
    k = g.k
    cols, rows = planes_grid(flags)
    assert hd.shape == (rows * k * g.h, cols * k * g.w), (hd.shape, rows, cols, k, g.w, g.h)
    pix = np.full((g.H, g.W), tidx, np.uint8)
    hx, hy = g.hd
    pix[hy:hy + hd.shape[0], hx:hx + hd.shape[1]] = hd
    if body:
        px, py = g.probe
        pix[py:py + g.h, px:px + g.w] = mark
        rows = spine_rows_for(g.H, bands)
        A = spine_bits(rows, g.layout, k, g.w, g.h, flags, PA)
        Bb = spine_bits(rows, g.layout, k, g.w, g.h, flags, PB)
        sub = pix[rows]
        sub[:, 0:J_SHREF] = np.where(A == 1, mark, tidx)
        sub[:, g.W - 1 - np.arange(J_SHREF)] = np.where(Bb == 1, mark, tidx)
        sub[:, J_SHREF] = shadow_idx
        sub[:, g.W - 1 - J_SHREF] = shadow_idx
        pix[rows] = sub
    return pix

# ---------------------------------------------------------------- disposition F (familles FXBltFrom)
# CInfinity::FXBltFrom (dragons, wyvernes, Demogorgon...) dessine une surface FX de la taille exacte du cadre,
# sans marge, et decoupe le quad a la fenetre de jeu. Deux consequences :
#  - un sommet decoupe n'est plus sur un coin du cadre ;
#  - deux surfaces voisines dans l'atlas partagent des coins : le sommet haut-droit de l'une et le sommet
#    haut-gauche de la suivante ont exactement les memes attributs ; aucun shader de sommets ne peut savoir
#    a quel cadre il appartient.
# La disposition F ne deplace donc pas les sommets, et c'est le shader de fragments qui decode le cadre :
#  - les dimensions du cadre sont des multiples de 128 (largeur) et de 8 (hauteur) : deux cadres F voisins dans
#    l'atlas ont la meme "phase" (origine modulo 128 et 8), que le shader de sommets trouve et transmet ;
#  - une ligne sur 8 (lignes "speciales", la premiere comprise) est faite de blocs de 128 colonnes, eux-memes
#    faits de 8 sous-blocs de 16 colonnes (bits en alpha : opaque = 1) :
#        bits 0-3 synchro 0,1,1,0 ; bits 4-6 indice du sous-bloc ; bits 7-15 : 9 bits de donnees ;
#    donnees du bloc (72 bits) : b (3, indice du bloc dans la ligne), m (7, indice de la ligne speciale),
#    k-1 (3), w (10), h (10), drapeaux (4), sous-disposition (1), somme de controle (12) ; le dernier texel
#    du bloc (colonne 127) est le texel de reference d'ombre (indice 1) ;
#  - le bloc-sonde (w x h, opaque, couleur "mark") est a la place du sprite d'origine ; une marge de 4 texels
#    l'entoure (halo des contours) ;
#  - l'image HD saute les lignes speciales : ligne HD j -> ligne du cadre j + j//7 + 1.
LAYOUT_F = 2
F_BW = 128         # largeur d'un bloc
F_SB = 16          # largeur d'un sous-bloc
F_PER = 8          # periode des lignes speciales
F_MARGIN = 4       # marge autour du bloc-sonde
F_SYNC = [0, 1, 1, 0]
FSUB_TOP, FSUB_SIDE = 0, 1
F_FIELDS = [('b', 3), ('m', 7), ('k1', 3), ('w', 10), ('h', 10), ('flags', 4), ('sub', 1), ('cs', 12)]


def f_row(j):
    """ligne du cadre de la ligne HD j"""
    return j + j // 7 + 1


def f_rows_needed(n):
    """lignes du cadre pour n lignes HD (lignes speciales comprises)"""
    return f_row(n - 1) + 1 if n > 0 else 1


def _up(x, m):
    return -(-x // m) * m


def layout_dims_f(w, h, k, sub, flags=0):
    """(W, H, (px, py) bloc-sonde, (hx, 0) image HD) ; W multiple de 128, H multiple de 8."""
    M = F_MARGIN
    cols, rows = planes_grid(flags)
    if sub == FSUB_TOP:
        px, py = M, f_rows_needed(rows * k * h) + M
        W = max(cols * k * w, w + 2 * M)
        H = py + h + M
        hx = 0
    else:
        px, py = M, M
        hx = w + 2 * M
        W = hx + cols * k * w
        H = max(f_rows_needed(rows * k * h), py + h + M)
    return _up(W, F_BW), _up(H, F_PER), (px, py), (hx, 0)


def choose_layout_f(w, h, k, flags=0):
    best = None
    for sub in (FSUB_TOP, FSUB_SIDE):
        W, H, _, _ = layout_dims_f(w, h, k, sub, flags)
        if W <= MAXDIM and H <= MAXDIM and (best is None or W * H < best[0]):
            best = (W * H, sub)
    return None if best is None else best[1]


def f_checksum(b, m, k, w, h, flags, sub):
    return (b * 7 + m * 13 + (k - 1) * 53 + w * 31 + h * 37 + flags * 97 + sub * 131 + 1543) % 4096


def f_block_data(b, m, k, w, h, flags, sub):
    vals = dict(b=b, m=m, k1=k - 1, w=w, h=h, flags=flags, sub=sub, cs=f_checksum(b, m, k, w, h, flags, sub))
    out = []
    for name, nb in F_FIELDS:
        out += bits(vals[name], nb)
    out += [0] * (72 - len(out))
    out[71] = 1                         # texel de reference d'ombre (lu comme 1 : alpha 0x7F)
    return out


def f_block_bits(b, m, k, w, h, flags, sub):
    """128 bits du bloc ; renvoie aussi la position du texel d'ombre."""
    data = f_block_data(b, m, k, w, h, flags, sub)
    out = []
    for s in range(8):
        out += F_SYNC + bits(s, 3) + data[9 * s:9 * s + 9]
    return out


class GeometryF:
    """geometrie canonique en disposition F."""
    def __init__(self, L, T, R, B, k, sub=None, flags=0):
        self.L, self.T, self.R, self.B, self.k = int(L), int(T), int(R), int(B), int(k)
        self.w, self.h = self.L + self.R, self.T + self.B
        self.flags = flags
        self.sub = choose_layout_f(self.w, self.h, k, flags) if sub is None else sub
        self.layout = None if self.sub is None else LAYOUT_F
        if self.sub is not None:
            self.W, self.H, self.probe, self.hd = layout_dims_f(self.w, self.h, k, self.sub, flags)
    @property
    def center(self):
        return self.probe[0] + self.L, self.probe[1] + self.T


def build_layer_f(hd, g, body, tidx=0, mark=2, shadow_idx=1, flags=0):
    """cadre en disposition F. body=False : image HD seule (calque d'equipement).
    hd : image HD (k*h, k*w), ou grille de plans deja assemblee (sous-teintes)."""
    k = g.k
    cols, nrows = planes_grid(flags)
    assert hd.shape == (nrows * k * g.h, cols * k * g.w)
    pix = np.full((g.H, g.W), tidx, np.uint8)
    hx, _ = g.hd
    rows = np.array([f_row(j) for j in range(hd.shape[0])])
    assert rows.max() < g.H and not (rows % F_PER == 0).any()
    pix[rows, hx:hx + hd.shape[1]] = hd
    if body:
        px, py = g.probe
        pix[py:py + g.h, px:px + g.w] = mark
        nb = g.W // F_BW
        for y in range(0, g.H, F_PER):
            m = y // F_PER
            for b in range(nb):
                bb = np.array(f_block_bits(b, m, k, g.w, g.h, flags, g.sub))
                x0 = b * F_BW
                pix[y, x0:x0 + F_BW] = np.where(bb == 1, mark, tidx)
                pix[y, x0 + F_BW - 1] = shadow_idx
    return pix


# ---- decodage de reference (meme logique que les shaders, en Python) pour les verifications par le calcul
def f_read_block(alpha, x0, y):
    """lit un bloc complet a (x0, y) dans une image d'alpha (H, W) ; renvoie dict ou None."""
    Hh, Ww = alpha.shape
    if y < 0 or y >= Hh or x0 < 0 or x0 + F_BW > Ww:
        return None
    row = (alpha[y, x0:x0 + F_BW] > 0).astype(int)
    data = []
    for s in range(8):
        sb = row[16 * s:16 * s + 16]
        if list(sb[:4]) != F_SYNC or (sb[4] | (sb[5] << 1) | (sb[6] << 2)) != s:
            return None
        data += list(sb[7:16])
    v = {}; p = 0
    for name, nb in F_FIELDS:
        v[name] = sum(int(data[p + i]) << i for i in range(nb)); p += nb
    k = v['k1'] + 1
    if v['cs'] != f_checksum(v['b'], v['m'], k, v['w'], v['h'], v['flags'], v['sub']):
        return None
    if v['w'] < 1 or v['h'] < 1:
        return None
    v['k'] = k
    return v


def f_decode_at(alpha, x0, y):
    """decode complet a partir d'un bloc en (x0, y) : origine et parametres, ou None."""
    v = f_read_block(alpha, x0, y)
    if v is None:
        return None
    ox, oy = x0 - v['b'] * F_BW, y - v['m'] * F_PER
    W, H, probe, hdo = layout_dims_f(v['w'], v['h'], v['k'], v['sub'], v['flags'])
    return dict(origin=(ox, oy), k=v['k'], w=v['w'], h=v['h'], flags=v['flags'], sub=v['sub'],
                W=W, H=H, probe=probe, hd=hdo)


def is_valid_build_f(pix, tidx=0):
    alpha = (pix != tidx).astype(np.uint8)
    H, W = pix.shape
    if W % F_BW or H % F_PER:
        return False
    for y in range(0, H, F_PER):
        for x0 in range(0, W, F_BW):
            d = f_decode_at(alpha, x0, y)
            if d is None or d['origin'] != (0, 0) or d['W'] != W or d['H'] != H:
                return False
    return True
