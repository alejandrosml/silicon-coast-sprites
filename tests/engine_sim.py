# engine_sim.py - simulation hors ligne du rendu des creatures de BG2:EE 2.7.3 (Mac, OpenGL)
# Chaque regle est tiree du desassemblage (adresses arm64 entre crochets) :
#  - palette : CVidPalette::RealizeResource3d [100370d90] : alpha 0xFF (ou 255-t si drapeau 2),
#    entree d'ombre (1) -> alpha 0x7F (ou 0x80*(255-t)/255), entrees a alpha de palette 1..254
#    gardent cet alpha ; FXRender3d [10036e55c] garde l'ombre car CVidCell+0x130 = 1.
#  - Blt8To32 [10036d0cc] : indice transparent et entrees nulles non ecrits, 0x00FF00 -> 0.
#  - CalculateFxRect (personnage) [10027edf4] : rect (0,0,w+m,h+m), ptRef = centre + m/2,
#    m = 2 sans contours de sprites (8 avec) ; cadre blitte en ptRef - centre = (1,1).
#  - FXLock -> DrawLockSurface [10037e5ac] : atlas 1024x1024 alloue en etageres, sans marge.
#  - murs : FXRenderClippingPolys [1001e6380] + DrawRazerizedPolygon [1001e683c] :
#    mode 'halve' (Always Dither / survol) : alpha >>= 1 ; mode 'clear' : texel = 0 ;
#    en miroir, la colonne i de la surface FX correspond au pixel du monde rect.right - i.
#  - FXBltFromClipped [1001e5fa4] -> FXBltToBack [100374e18] -> RenderTexture [10036dbe8]
#    -> DrawQuad [100378128] : quad de la taille de la surface FX, decoupe au rect interieur
#    (marge de 1), tc inverses en miroir ; DrawQuad [100377fb8] : 6 sommets
#    (L,T)(L,B)(R,T)(R,T)(L,B)(R,B) ; DrawVertex ajoute l'offset d'atlas a tc ;
#    DrawTexCoord [10037ed98] : aRef = tc brut du 1er sommet.
import numpy as np

ATLAS = 1024

class AtlasFull(RuntimeError):
    pass


class Atlas:
    def __init__(self):
        self.img = np.zeros((ATLAS, ATLAS, 4), np.uint8)
        self.x = 0; self.shelf_y = 0; self.shelf_h = 0
        self.flushes = 0
    def alloc(self, w, h):
        if self.x + w > ATLAS:
            self.x = 0; self.shelf_y += self.shelf_h; self.shelf_h = 0
        if self.shelf_y + h >= ATLAS:
            raise AtlasFull('atlas plein : le moteur vide la file de dessin ici')
        x, y = self.x, self.shelf_y
        self.shelf_h = max(self.shelf_h, h)
        self.x += w
        return x, y

def realize_palette(bam_pal, tint=(255, 255, 255), transp=0, greyscale=False, shadow_rgb=(0, 0, 0)):
    """bam_pal : (256,4) BGRA du BAM. Renvoie (256,4) RGBA tel que le moteur l'ecrit dans l'atlas."""
    pal = np.asarray(bam_pal).astype(np.int64)
    r, g, b, pa = pal[:, 2], pal[:, 1], pal[:, 0], pal[:, 3]
    if greyscale:                                   # drapeau 0x80000 (pause en gris)
        avg = (r + g + b) >> 2
        r = g = b = avg
    t = np.array(tint, np.int64)
    r = (r * t[0]) >> 8; g = (g * t[1]) >> 8; b = (b * t[2]) >> 8
    a_body = 255 - transp
    a = np.where((pa > 0) & (pa < 255), pa, a_body)
    out = np.stack([r, g, b, a], 1).clip(0, 255).astype(np.uint8)
    out[1, :3] = shadow_rgb
    out[1, 3] = 0x7F if transp == 0 else (0x80 * a_body) // 255
    return out

def blt_frame(fx, pix, x0, y0, pal_rgba, tidx):
    h, w = pix.shape
    rgba = pal_rgba[pix]
    write = (pix != tidx) & (rgba.view(np.uint32)[..., 0] != 0)
    sub = fx[y0:y0 + h, x0:x0 + w]
    sub[write] = rgba[write]

def raster_poly(poly, x0, y0, w, h):
    """masque (h,w) des pixels (x0+i, y0+j) du monde dont le centre est dans le polygone"""
    ys, xs = np.mgrid[0:h, 0:w]
    px = x0 + xs + 0.5; py = y0 + ys + 0.5
    inside = np.zeros((h, w), bool)
    n = len(poly)
    for i in range(n):
        xa, ya = poly[i]; xb, yb = poly[(i + 1) % n]
        cond = (ya > py) != (yb > py)
        xint = (xb - xa) * (py - ya) / ((yb - ya) if yb != ya else 1e-9) + xa
        inside ^= cond & (px < xint)
    return inside

def apply_walls(fx, rect_world, mirrored, walls):
    """murs appliques a la surface FX entiere (rect_world = rect du monde de la surface)"""
    L, T, R, Bm = rect_world
    H, W = fx.shape[:2]
    for poly, mode in walls:
        if mirrored:
            # colonne i <-> pixel du monde R - i  (decalage d'un pixel du moteur, reproduit)
            m = raster_poly(poly, R - W + 1, T, W, H)[:, ::-1]
        else:
            m = raster_poly(poly, L, T, W, H)
        if mode == 'halve':
            fx[..., 3][m] >>= 1
        elif mode == 'clear':
            fx[m] = 0
        else:
            raise ValueError(mode)

class Creature:
    def __init__(self, pix, cx, cy, pal_rgba, tidx=0):
        self.pix, self.cx, self.cy, self.pal, self.tidx = pix, cx, cy, pal_rgba, tidx

def fx_layout(layers, margin=2):
    """CGameAnimationTypeCharacter::CalculateFxRect [10027edf4] : ptRef = max des centres des calques,
    rect = (0, 0, max(w_i + ptRef.x - cx_i), max(h_i + ptRef.y - cy_i)) agrandi de m a droite et en bas,
    ptRef += m/2. Chaque calque est dessine en ptRef - centre_i (FXRender)."""
    prx = max(cr.cx for cr in layers); pry = max(cr.cy for cr in layers)
    rw = max(cr.pix.shape[1] + prx - cr.cx for cr in layers)
    rh = max(cr.pix.shape[0] + pry - cr.cy for cr in layers)
    fxw, fxh = rw + margin, rh + margin
    ptref = (prx + margin // 2, pry + margin // 2)
    offs = [(ptref[0] - cr.cx, ptref[1] - cr.cy) for cr in layers]
    return fxw, fxh, ptref, offs

def render_character(atlas, layers, anchor, mirrored=False, walls=(), margin=2, color=(255, 255, 255, 255)):
    """Personnage a calques (corps, casque, bouclier, arme) dans l'ordre de dessin du moteur
    (CGameAnimationTypeCharacter::Render [100284114]). Renvoie les 6 sommets et les infos."""
    fxw, fxh, ptref, offs = fx_layout(layers, margin)
    ax, ay = atlas.alloc(fxw, fxh)
    fx = atlas.img[ay:ay + fxh, ax:ax + fxw]
    fx[:] = 0
    for cr, (ox, oy) in zip(layers, offs):
        blt_frame(fx, cr.pix, ox, oy, cr.pal, cr.tidx)
    # CalculateGCBoundsRect [10027f0b0]
    left = anchor[0] - (fxw - ptref[0]) if mirrored else anchor[0] - ptref[0]
    top = anchor[1] - ptref[1]
    rect_world = (left, top, left + fxw, top + fxh)
    if walls:
        apply_walls(fx, rect_world, mirrored, walls)
    # quad : surface FX entiere decoupee au rect interieur [100284538..100284590] :
    # sans contours (m=2) : DeflateRect(0,0,2,2) puis +1 -> (1,1,fxw-1,fxh-1)
    # avec contours (m=8) : DeflateRect(0,0,5,5) puis +2 -> (2,2,fxw-3,fxh-3)
    if margin == 2:
        dL = dT = 1; dR = dB = 1
    else:
        dL = dT = 2; dR = dB = 3
    pos = [left + dL, top + dT, left + fxw - dR, top + fxh - dB]
    tcL, tcT, tcR, tcB = dL, dT, fxw - dR, fxh - dB
    if mirrored:
        tcL, tcR = fxw - tcL, fxw - tcR
    corners = {'LT': ((pos[0], pos[1]), (tcL, tcT)), 'LB': ((pos[0], pos[3]), (tcL, tcB)),
               'RT': ((pos[2], pos[1]), (tcR, tcT)), 'RB': ((pos[2], pos[3]), (tcR, tcB))}
    order = ['LT', 'LB', 'RT', 'RT', 'LB', 'RB']
    ref = (tcL, tcT)
    verts = []
    for c in order:
        (px, py), (u, v) = corners[c]
        verts.append(dict(pos=(px, py), tc=(u + ax, v + ay), col=color, ref=ref))
    return verts, dict(alloc=(ax, ay), fx=(fxw, fxh), rect_world=rect_world, quad=pos, ptref=ptref, offs=offs)

def render_creature(atlas, cr, anchor, mirrored=False, walls=(), margin=2, color=(255, 255, 255, 255)):
    """Renvoie la liste des 6 sommets (dicts) et les infos utiles aux tests."""
    return render_character(atlas, [cr], anchor, mirrored, walls, margin, color)

def layer_order(direction, maxdir=8, helmet_on_top=True):
    """ordre de dessin des calques selon la direction (0..15), CGameAnimationTypeCharacter::Render :
    d' = 16 - d si d > maxdir (miroir) ; d' in 3..7 : [casque], corps, arme, bouclier, [casque] ;
    d' < 3 : corps, arme, bouclier, casque ; d' = 8 : casque, corps, bouclier, arme."""
    d = 16 - direction if direction > maxdir else direction
    if 3 <= d <= 7:
        return (['body', 'weapon', 'shield', 'helmet'] if helmet_on_top
                else ['helmet', 'body', 'weapon', 'shield'])
    if d < 3:
        return ['body', 'weapon', 'shield', 'helmet']
    return ['helmet', 'body', 'shield', 'weapon']

def pack(verts):
    out = []
    for v in verts:
        out += [v['pos'][0], v['pos'][1], v['tc'][0], v['tc'][1]] + [c / 255.0 for c in v['col']] + [v['ref'][0], v['ref'][1]]
    return out

def render_fxfrom(atlas, cr, anchor, mirrored=False, walls=(), viewport=None, color=(255, 255, 255, 255)):
    """Familles FXBltFrom (MonsterMulti, MonsterQuadrant, MonsterMultiNew, Effect) : surface FX de la taille
    exacte du cadre (point de reference = centre), CInfinity::FXBltFrom [1001e609c] -> FXBltToBack [100374e18]
    avec le rect de la fenetre de jeu (CInfinity+0x78) comme decoupe -> [100378128] : quad decoupe a la
    fenetre, tc decoupes de meme (miroir : tc.x = w - tc.x) ; aRef = tc brut du 1er sommet (haut-gauche)."""
    h, w = cr.pix.shape
    fxw, fxh = w, h
    ax, ay = atlas.alloc(fxw, fxh)
    fx = atlas.img[ay:ay + fxh, ax:ax + fxw]
    fx[:] = 0
    blt_frame(fx, cr.pix, 0, 0, cr.pal, cr.tidx)
    left = anchor[0] - ((fxw - cr.cx) if mirrored else cr.cx)
    top = anchor[1] - cr.cy
    rect_world = (left, top, left + fxw, top + fxh)
    if walls:
        apply_walls(fx, rect_world, mirrored, walls)
    VL, VT, VR, VB = viewport if viewport is not None else (-10 ** 6, -10 ** 6, 10 ** 6, 10 ** 6)
    info = dict(alloc=(ax, ay), fx=(fxw, fxh), rect_world=rect_world)
    if VR < left or VB < top or left + fxw < VL or top + fxh < VT:
        return [], info
    cl = max(VL - left, 0); ct = max(VT - top, 0)
    qL = max(VL, left); qT = max(VT, top)
    right = left + fxw; bottom = top + fxh
    qR = min(right, VR); qB = min(bottom, VB)
    tcR = fxw + VR - right if right > VR else fxw
    tcB = fxh + VB - bottom if bottom > VB else fxh
    tcL, tcT = cl, ct
    if mirrored:
        tcL, tcR = fxw - tcL, fxw - tcR
    corners = {'LT': ((qL, qT), (tcL, tcT)), 'LB': ((qL, qB), (tcL, tcB)),
               'RT': ((qR, qT), (tcR, tcT)), 'RB': ((qR, qB), (tcR, tcB))}
    order = ['LT', 'LB', 'RT', 'RT', 'LB', 'RB']
    ref = (tcL, tcT)
    verts = []
    for c in order:
        (px, py), (u, v) = corners[c]
        verts.append(dict(pos=(px, py), tc=(u + ax, v + ay), col=color, ref=ref))
    info.update(quad=(qL, qT, qR, qB))
    return verts, info


class Pages:
    """file de dessin du moteur : quand l'atlas 1024x1024 est plein, le moteur dessine ce qui est en file puis
    repart d'un atlas vide. Chaque page = (image d'atlas, sommets), dessinees dans l'ordre sur la meme image."""
    def __init__(self):
        self.done = []; self.at = Atlas(); self.verts = []

    def draw(self, fn):
        """fn(atlas) -> (sommets, info) ; recommence sur un atlas vide si celui-ci est plein."""
        try:
            v, info = fn(self.at)
        except AtlasFull:
            self.flush()
            v, info = fn(self.at)
        self.verts += v
        return info

    def alloc(self, w, h):
        try:
            return self.at.alloc(w, h)
        except AtlasFull:
            self.flush()
            return self.at.alloc(w, h)

    def flush(self):
        if self.verts:
            self.done.append((self.at.img.copy(), self.verts))
        self.at = Atlas(); self.verts = []

    def result(self):
        self.flush()
        return self.done
