# emu_ini.py - emule le constructeur de chaque type d'animation AVEC la lecture de son fichier INI
# (CGameAnimationType*::Unmarshal(CResRef) execute pour de vrai ; CMemINI::Load/GetSection fournis
# a partir des INI du jeu). C'est le chemin que le moteur suit pour les 468 animations definies par
# un INI ; l'ancienne emulation (emu_all.py) prenait le chemin code en dur (INI absent). Licence MIT.
import json, sys, collections, os, re
src = open('emu_char.py').read()
src = src[:src.index('# trouver les ID')]
exec(src)
exec(open('emu_all.py').read().split('# (le crochet est deja pose par emu_char.py)')[0].split('exec(src)', 1)[1]
     .replace('timeout=10_000_000, count=400000', 'timeout=60_000_000, count=3_000_000'))

# python3 emu_ini.py <dossier des INI d'animation> <ANIMATE.IDS> <all_anims_ini.json>
# (dans ce dossier : bg2_arm64 et les index faits par stubs.py, xref.py, trie_scan.py, demangle.py ; voir README.md)
INI_DIR = sys.argv[1]
INI = {}
for f in os.listdir(INI_DIR):
    secs = {}; cur = None
    for line in open(os.path.join(INI_DIR, f), encoding='latin1').read().splitlines():
        s = line.strip()
        if not s or s.startswith('//') or s.startswith(';'):
            continue
        m = re.match(r'^\[(.+)\]$', s)
        if m:
            cur = m.group(1).strip().lower(); secs.setdefault(cur, []); continue
        if cur is not None and '=' in s:
            k, v = s.split('=', 1)
            secs[cur].append((k.strip(), v.strip()))
    INI[f[:-4].upper()] = secs

# CString a la MFC : en-tete (nRefs, nDataLength, nAllocLength) avant les donnees
def put_str(s):
    b = s.encode('latin1')
    p = halloc(16 + len(b) + 1)
    mu.mem_write(p + 4, struct.pack('<iii', 1, len(b), len(b)))
    mu.mem_write(p + 16, b + b'\0')
    return p + 16
globals()['put_str'] = put_str

INIOBJ = {}
STUBBED = collections.Counter()
UNKNOWN_IMPORT = collections.Counter()

@sem(0x1000365cc)          # CMemINI::Load(CString const&)
def _(x0, x1, x8):
    name = cs_get(x1).upper()
    INIOBJ[x0] = INI.get(name)
    log.append(('ini', name, bool(INIOBJ[x0])))
    ret(1 if INIOBJ[x0] else 0)
@sem(0x1000364ec)          # CMemINI::GetSection(CString const&) -> CMemINISection* (liste de cles)
def _(x0, x1, x8):
    secs = INIOBJ.get(x0)
    name = cs_get(x1).lower()
    if not secs or name not in secs:
        ret(0); return
    sec = halloc(0x40)
    prev = 0; head = 0
    nodes = []
    for k, v in secs[name]:
        ent = halloc(0x20); cs_set(ent + 8, k); cs_set(ent + 0x10, v)
        node = halloc(0x18); wr64(node + 0x10, ent)
        nodes.append(node)
    for i, nd in enumerate(nodes):
        wr64(nd, nodes[i + 1] if i + 1 < len(nodes) else 0)
        wr64(nd + 8, nodes[i - 1] if i else 0)
    wr64(sec + 8, nodes[0] if nodes else 0)
    wr64(sec + 0x10, nodes[-1] if nodes else 0)
    mu.mem_write(sec + 0x18, struct.pack('<i', len(nodes)))
    log.append(('sec', name, len(nodes)))
    ret(sec)
@sem(0x10003649c)          # CMemINI::ClearINI()
def _(x0, x1, x8): ret(0)
@sem(0x100036560)          # CMemINISection::Get(CString const&) -> CString* ou 0
def _(x0, x1, x8):
    key = cs_get(x1).lower()
    n = rd64(x0 + 8)
    while n:
        ent = rd64(n + 0x10)
        if cs_get(ent + 8).lower() == key:
            ret(ent + 0x10); return
        n = rd64(n)
    ret(0)
@sem(0x1003695bc)          # CResRef::GetResRefStr() const -> CString (sret x8)
def _(x0, x1, x8): cs_set(x8, resref_get(x0)); ret(x8)
@sem(0x100385ca4)          # CString::MakeLower()
def _(x0, x1, x8): cs_set(x0, cs_get(x0).lower()); ret(0)
@sem(0x100385bb0)          # CString::MakeUpper()
def _(x0, x1, x8): cs_set(x0, cs_get(x0).upper()); ret(0)
@sem(0x1003885f0)          # CString::TrimRight()
def _(x0, x1, x8): cs_set(x0, cs_get(x0).rstrip()); ret(0)
@sem(0x100386768)          # CString::operator+=(char const*)
def _(x0, x1, x8): cs_set(x0, cs_get(x0) + rdstr(x1)); ret(x0)
@sem(0x10049abf8)          # WITCHSTRING : 4 premiers caracteres, majuscules
def _(x0, x1, x8):
    if x0 == 0: ret(0); return
    b = bytes(mu.mem_read(x0, 4))
    v = 0
    for i in range(4):
        if b[i] == 0: break
        v |= b[i] << (8 * i)
    ret(v & 0xdfdfdfdf)
@sem(0x100634438)          # operator new[]
def _(x0, x1, x8): ret(halloc(max(x0, 16)))
@sem(0x100634444)          # operator new
def _(x0, x1, x8): ret(halloc(max(x0, 16)))
@sem(0x100634d5c)          # malloc
def _(x0, x1, x8): ret(halloc(max(x0, 16)))
for _a in (0x100634420, 0x10063442c, 0x100634864):   # delete[], delete, free
    SEM[_a] = lambda x0, x1, x8: ret(0)
@sem(0x100634d80)          # memcpy
def _(x0, x1, x8):
    n = R(X[2])
    if n: mu.mem_write(x0, bytes(mu.mem_read(x1, n)))
    ret(x0)
@sem(0x100634d98)          # memset
def _(x0, x1, x8):
    n = R(X[2])
    if n: mu.mem_write(x0, bytes([x1 & 0xff]) * n)
    ret(x0)
@sem(0x10063508c)          # rand
def _(x0, x1, x8): ret(0)
@sem(0x10063535c)          # strstr
def _(x0, x1, x8):
    a, b = rdstr(x0, 4096), rdstr(x1, 4096)
    i = a.find(b); ret(0 if i < 0 else x0 + i)
@sem(0x100635290)          # strchr
def _(x0, x1, x8):
    a = rdstr(x0, 4096); c = chr(x1 & 0xff)
    i = a.find(c) if c != '\0' else len(a); ret(0 if i < 0 else x0 + i)
@sem(0x100635344)          # strrchr
def _(x0, x1, x8):
    a = rdstr(x0, 4096); c = chr(x1 & 0xff)
    i = a.rfind(c) if c != '\0' else len(a); ret(0 if i < 0 else x0 + i)
@sem(0x1006352b4)          # strcpy
def _(x0, x1, x8): mu.mem_write(x0, rdstr(x1, 4096).encode('latin1') + b'\0'); ret(x0)
@sem(0x10063532c)          # strncpy
def _(x0, x1, x8):
    n = R(X[2]); b = rdstr(x1, 4096).encode('latin1')[:n]
    mu.mem_write(x0, b + b'\0' * (n - len(b))); ret(x0)
def _atoi(s):
    m = re.match(r'\s*([+-]?\d+)', s)
    return int(m.group(1)) if m else 0
@sem(0x100634648)
def _(x0, x1, x8): ret(_atoi(rdstr(x0)) & 0xffffffff)
@sem(0x10063538c)          # strtol
def _(x0, x1, x8):
    s = rdstr(x0); base = x8  # non utilise
    ret(_atoi(s) & 0xffffffffffffffff)
@sem(0x10063529c)
def _(x0, x1, x8):
    a, b = rdstr(x0), rdstr(x1); ret(0 if a == b else (0xffffffff if a < b else 1))
@sem(0x100635278)
def _(x0, x1, x8):
    a, b = rdstr(x0).lower(), rdstr(x1).lower(); ret(0 if a == b else (0xffffffff if a < b else 1))
@sem(0x1006352fc)
def _(x0, x1, x8): ret(len(rdstr(x0, 4096)))

# fonctions executees pour de vrai (au lieu d'etre court-circuitees)
RUN = set(a for a, d in find(r'Unmarshal\((CResRef|CMemINISection\*)\)'))
FSET -= RUN
IMPORTS = set(a for a in STUBS if 0x100634000 <= a < 0x100636000)
def hook2(uc, addr, size, ud):
    if addr in IMPORTS and addr not in SEM:
        UNKNOWN_IMPORT[STUBS.get(addr)] += 1
        ret(0)
    elif addr in FSET and addr not in SEM and addr != CTOR:
        STUBBED[name(addr)] += 1
mu.hook_add(UC_HOOK_CODE, hook2, begin=0x100000000, end=0x10074c000)

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'tools'))
import anim_table
rows = anim_table.build(INI_DIR)
ids_txt = open(sys.argv[2], encoding='latin1').read().splitlines()[1:]
ids = sorted(set('%04X' % int(l.split()[0], 16) for l in ids_txt if l.strip().startswith('0x')))
cls_of = {r['id']: r['cls'] for r in rows}
out = {}
for i in sorted(set(ids) | set(cls_of)):
    c = cls_of.get(i) or anim_table.anim_class(int(i, 16))
    if c not in CT:
        continue
    res = run_ctor(CT[c], int(i, 16))
    done_ok = (R(UC_ARM64_REG_PC) == 0x7ffff000)
    lg = res['log']
    loads = [(w, s) for op, w, s in [x for x in lg if len(x) == 3] if op == 'load']
    rrs = [(w, s) for op, w, s in [x for x in lg if len(x) == 3] if op.startswith('rr')]
    ini = [x for x in lg if x[0] == 'ini']
    secs = [x for x in lg if x[0] == 'sec']
    out[i] = dict(cls=c, ini=bool(ini and ini[0][2]), secs=[s[1] for s in secs], err=res.get('err'), done=done_ok, loads=loads, rr=rrs)
json.dump(out, open(sys.argv[3], 'w'), indent=0, sort_keys=True)
by = collections.Counter((v['cls'], v['ini'], bool(v['err']), v['done'], len(v['loads']) > 0) for v in out.values())
for k, n in sorted(by.items()): print(k, n)
print('fonctions court-circuitees :', STUBBED.most_common(60))
print('imports inconnus :', UNKNOWN_IMPORT)
