# mkscene2.py - Silicon Coast : sauvegarde de test "une creature de chaque famille d'animation sur un ecran".
# Copie de "000000007-Chapter 1 Start" vers une nouvelle sauvegarde (aucune autre sauvegarde n'est touchee) :
#  - zone AR0602 : retire les acteurs proches de la scene (gobelins, dryades : ni combat ni dialogue), ajoute les
#    creatures de la scene (CRE incorporees, neutres, sans script ni dialogue, equipement et orientation donnes) ;
#  - groupe : Abdel equipe (casque, cotte de mailles, bouclier, hache), groupe et vue deplaces dans la salle.
#   python3 mkscene2.py scene_cast.json ["000000099-Silicon Coast scene"]
import struct, os, shutil, sys, json, zlib

# dossier des sauvegardes (macOS par defaut) ; SC_SAVE_DIR pour un autre emplacement
SAVE = os.environ.get('SC_SAVE_DIR', os.path.expanduser("~/Documents/Baldur's Gate II - Enhanced Edition/save"))
SRC = os.path.join(SAVE, "000000007-Chapter 1 Start")
DST = os.path.join(SAVE, sys.argv[2] if len(sys.argv) > 2 else "000000099-Silicon Coast scene")
# n'ecrit que dans une sauvegarde de test : aucune sauvegarde du joueur ne peut etre remplacee
assert 'Silicon Coast' in os.path.basename(DST) and os.path.abspath(DST) != os.path.abspath(SRC), DST
scene = json.load(open(sys.argv[1]))
cast = scene['cast']


def read_sav(d):
    assert d[:8] == b'SAV V1.0'
    o = 8; ents = []
    while o < len(d):
        n = struct.unpack('<I', d[o:o + 4])[0]; name = d[o + 4:o + 4 + n]; o += 4 + n
        ul, cl = struct.unpack('<II', d[o:o + 8]); o += 8
        ents.append([name, zlib.decompress(d[o:o + cl])]); o += cl
    return ents


def write_sav(ents):
    out = bytearray(b'SAV V1.0')
    for name, data in ents:
        z = zlib.compress(data, 9)
        out += struct.pack('<I', len(name)) + name + struct.pack('<II', len(data), len(z)) + z
    return bytes(out)


def cre_rebuild(c, items=None, slots=None):
    """reconstruit une CRE V1.0 avec une nouvelle liste d'objets / emplacements."""
    def sec(off_at, cnt_at, size):
        off, cnt = struct.unpack('<II', c[off_at:off_at + 4] + c[cnt_at:cnt_at + 4])
        return c[off:off + cnt * size], cnt
    eff_size = 0x108 if c[0x33] == 1 else 0x30
    known, nk = sec(0x2a0, 0x2a4, 12)
    meminfo, nmi = sec(0x2a8, 0x2ac, 16)
    mem, nm = sec(0x2b0, 0x2b4, 12)
    effs, ne = sec(0x2c4, 0x2c8, eff_size)
    items_old, ni = sec(0x2bc, 0x2c0, 20)
    so = struct.unpack('<I', c[0x2b8:0x2bc])[0]
    sl = list(struct.unpack('<40H', c[so:so + 80]))
    if items is not None:
        items_old = items; ni = len(items) // 20
    if slots is not None:
        sl = slots
    hdr = bytearray(c[:0x2d4]); body = bytearray()

    def place(off_at, cnt_at, blob, cnt):
        struct.pack_into('<I', hdr, off_at, 0x2d4 + len(body))
        if cnt_at is not None:
            struct.pack_into('<I', hdr, cnt_at, cnt)
        body.extend(blob)
    place(0x2a0, 0x2a4, known, nk); place(0x2a8, 0x2ac, meminfo, nmi); place(0x2b0, 0x2b4, mem, nm)
    place(0x2c4, 0x2c8, effs, ne); place(0x2bc, 0x2c0, bytes(items_old), ni)
    place(0x2b8, None, struct.pack('<40H', *sl), 0)
    return bytes(hdr) + bytes(body)


SLOT = dict(helmet=0, armor=1, shield=2, weapon=9)


def make_cre(tpl, a):
    c = bytearray(tpl)
    struct.pack_into('<I', c, 0x28, int(a['anim'], 16))
    if 'colors' in a:
        c[0x2c:0x33] = bytes(a['colors'])
    c[0x270] = 128                                   # NEUTRAL
    struct.pack_into('<I', c, 0x10, 0)               # drapeaux de CRE (le modele garde son cadavre)
    struct.pack_into('<I', c, 0x20, 0)               # etat : le modele (voleur de la scene d'ouverture) est mort
    struct.pack_into('<hh', c, 0x24, 60, 60)         # points de vie
    for off in (0x248, 0x250, 0x258, 0x260, 0x268, 0x2cc):
        c[off:off + 8] = b'\0' * 8                   # scripts et dialogue retires
    items = bytearray(); slots = [0xFFFF] * 40
    for role, res in a.get('items', {}).items():
        items += res.encode().ljust(8, b'\0') + struct.pack('<HHHHI', 0, 1, 0, 0, 1)
        slots[SLOT[role]] = len(items) // 20 - 1
    slots[38] = 0; slots[39] = 0
    return cre_rebuild(bytes(c), bytes(items), slots)


g = bytearray(open(os.path.join(SRC, 'BALDUR.gam'), 'rb').read())
ents = read_sav(open(os.path.join(SRC, 'BALDUR.SAV'), 'rb').read())
ai = [i for i, (n, _) in enumerate(ents) if n.rstrip(b'\0').upper() == b'AR0602.ARE'][0]
a = bytearray(ents[ai][1])
ao, ac = struct.unpack('<IH', a[0x54:0x5a])
actors = [bytes(a[ao + 0x110 * i: ao + 0x110 * (i + 1)]) for i in range(ac)]
# modele : CRE incorporee d'un voleur neutre de la scene d'ouverture (STHIEF)
tpl = None
for e in actors:
    if e[0x80:0x88].rstrip(b'\0') == b'*STHIEF':
        off, sz = struct.unpack('<II', e[0x88:0x90]); tpl = bytes(a[off:off + sz]); break
assert tpl and tpl[:8] == b'CRE V1.0'
# acteurs proches de la scene retires (copie de test seulement)
cx, cy, r = scene.get('remove_near', (0, 0, 0))
kept = []
for e in actors:
    x, y = struct.unpack('<HH', e[0x20:0x24])
    if r and (x - cx) ** 2 + (y - cy) ** 2 < r * r:
        print('retire', e[0x80:0x88].rstrip(b'\0').decode(errors='replace'), (x, y))
        continue
    kept.append(e)
actors = kept
new = []
blobs = []
for x in cast:
    e = bytearray(0x110)
    e[0:32] = x['name'].encode()[:31].ljust(32, b'\0')
    struct.pack_into('<HHHH', e, 0x20, x['x'], x['y'], x['x'], x['y'])
    struct.pack_into('<I', e, 0x28, 0)               # CRE incorporee
    struct.pack_into('<I', e, 0x30, int(x['anim'], 16))
    struct.pack_into('<H', e, 0x34, x['orient'])
    struct.pack_into('<i', e, 0x38, -1)
    struct.pack_into('<I', e, 0x40, 0xFFFFFF)        # present a toute heure
    e[0x80:0x88] = b'*SCTEST\0'
    blobs.append(make_cre(tpl, x))
    new.append(e)
# nouvelle table des acteurs (gardes + nouveaux) et CRE ajoutees en fin de fichier
base = len(a)
table = b''.join(actors) + b''.join(bytes(e) for e in new)
cre_at = base + len(table)
for e, bl in zip(new, blobs):
    struct.pack_into('<II', e, 0x88, cre_at, len(bl)); cre_at += len(bl)
table = b''.join(actors) + b''.join(bytes(e) for e in new)
a += table + b''.join(blobs)
struct.pack_into('<I', a, 0x54, base)
struct.pack_into('<H', a, 0x58, len(actors) + len(new))
ents[ai][1] = bytes(a)
os.makedirs(DST, exist_ok=True)
for f in os.listdir(SRC):
    if f.upper() not in ('BALDUR.GAM', 'BALDUR.SAV'):
        shutil.copy2(os.path.join(SRC, f), os.path.join(DST, f))
# groupe : positions, orientation et vue dans la salle de la scene
po, pc = struct.unpack('<II', g[0x20:0x28])
vx, vy = scene.get('viewport', (None, None))
for i, (px, py, por) in enumerate(scene.get('party', [])[:pc]):
    s = po + i * 0x160
    struct.pack_into('<HH', g, s + 0x20, px, py)
    if vx is not None:
        struct.pack_into('<HH', g, s + 0x24, vx, vy)
    struct.pack_into('<H', g, s + 0x14, por)
# Abdel equipe (casque, cotte de mailles, bouclier, hache)
cre_off, cre_size = struct.unpack('<II', g[po + 4:po + 12])
c = bytes(g[cre_off:cre_off + cre_size])
slots = list(struct.unpack('<40H', c[struct.unpack('<I', c[0x2b8:0x2bc])[0]:][:80]))


def sec(off_at, cnt_at, size):
    off, cnt = struct.unpack('<II', c[off_at:off_at + 4] + c[cnt_at:cnt_at + 4]); return c[off:off + cnt * size], cnt


old, ni = sec(0x2bc, 0x2c0, 20); items = bytearray(old)
for res, slot in (('HELM01', 0), ('CHAN01', 1), ('SHLD03', 2), ('AX1H01', 9)):
    items += res.encode().ljust(8, b'\0') + struct.pack('<HHHHI', 0, 1, 0, 0, 1); slots[slot] = len(items) // 20 - 1
slots[38] = 0; slots[39] = 0
newc = cre_rebuild(c, bytes(items), slots)
newoff = len(g); g += newc
struct.pack_into('<II', g, po + 4, newoff, len(newc))
open(os.path.join(DST, 'BALDUR.gam'), 'wb').write(bytes(g))
open(os.path.join(DST, 'BALDUR.SAV'), 'wb').write(write_sav(ents))
print('ecrit', DST, len(new), 'creatures ajoutees,', len(actors), 'acteurs gardes ; ARE', base, '->', len(a))
