# emu_char.py - emule CGameAnimationTypeCharacter::CGameAnimationTypeCharacter pour chaque ID
# d'animation et releve les chaines (corps, codes de taille des equipements...) et drapeaux.
exec(open('rx.py').read())
from unicorn import *
from unicorn.arm64_const import *
import struct, json, sys

CTOR = 0x10027db6c
mu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
PG = 0x4000
def amap(a, size):
    a0 = a & ~(PG - 1); e = (a + size + PG - 1) & ~(PG - 1)
    mu.mem_map(a0, e - a0)
for s in _b.segments:
    if s.name == '__PAGEZERO': continue
    amap(s.virtual_address, s.virtual_size)
    if s.file_size:
        mu.mem_write(s.virtual_address, DATA[s.file_offset:s.file_offset + min(s.file_size, s.virtual_size)])
import numpy as _np
for s in _b.segments:
    if s.name not in ('__DATA_CONST', '__DATA') or not s.file_size: continue
    raw = _np.frombuffer(DATA[s.file_offset:s.file_offset + s.file_size], dtype='<u8').copy()
    tgt = raw & _np.uint64(0xFFFFFFFFF)
    bind = (raw >> _np.uint64(63)) & _np.uint64(1)
    ok = (bind == 0) & (tgt >= _np.uint64(0x100000000)) & (tgt < _np.uint64(0x103700000)) & (raw != tgt)
    raw[ok] = tgt[ok]
    mu.mem_write(s.virtual_address, raw.tobytes())
mu.mem_map(0, 0x200000)                       # pointeurs nuls lus sans planter
STACK = 0x70000000; mu.mem_map(STACK, 0x200000)
OBJ = 0x60000000; mu.mem_map(OBJ, 0x10000)
HEAP = 0x61000000; mu.mem_map(HEAP, 0x400000)
heap_ptr = [HEAP]
def halloc(n):
    p = heap_ptr[0]; heap_ptr[0] += (n + 15) & ~15; return p
def put_str(s):
    b = s.encode('latin1') + b'\0'
    p = halloc(len(b)); mu.mem_write(p, b); return p
def rd64(a): return struct.unpack('<Q', mu.mem_read(a, 8))[0]
def wr64(a, v): mu.mem_write(a, struct.pack('<Q', v))
def rdstr(p, n=256):
    if p == 0: return ''
    b = bytes(mu.mem_read(p, n)); return b.split(b'\0')[0].decode('latin1')
def cs_get(obj): return rdstr(rd64(obj))
def cs_set(obj, s): wr64(obj, put_str(s))
def resref_get(obj):
    b = bytes(mu.mem_read(obj, 8)); return b.split(b'\0')[0].decode('latin1')
def resref_set(obj, s):
    b = s.upper().encode('latin1')[:8]; mu.mem_write(obj, b + b'\0' * (8 - len(b)))

R = lambda r: mu.reg_read(r)
X = [UC_ARM64_REG_X0 + i for i in range(29)]
log = []
def ret(v=0):
    mu.reg_write(UC_ARM64_REG_X0, v)
    mu.reg_write(UC_ARM64_REG_PC, R(UC_ARM64_REG_LR))

def where(a):
    return f'this+{a-OBJ:#x}' if OBJ <= a < OBJ + 0x10000 else (f'sp+{a-R(UC_ARM64_REG_SP):#x}' if STACK <= a < STACK + 0x200000 else hex(a))

SEM = {}
def sem(addr):
    def d(fn): SEM[addr] = fn; return fn
    return d
@sem(0x100385e18)
def _(x0, x1, x8): s = rdstr(x1); cs_set(x0, s); log.append(('cs=', where(x0), s)); ret(x0)
@sem(0x1003862e8)
def _(x0, x1, x8): s = cs_get(x1); cs_set(x0, s); log.append(('cs=cs', where(x0), s)); ret(x0)
@sem(0x1003861d8)
def _(x0, x1, x8): cs_set(x0, rdstr(x1)); ret(x0)
@sem(0x100385eec)
def _(x0, x1, x8): cs_set(x0, cs_get(x1)); ret(x0)
@sem(0x100386dc0)
def _(x0, x1, x8): cs_set(x0, chr(x1 & 0xff) if x1 & 0xff else ''); ret(x0)
@sem(0x100386548)
def _(x0, x1, x8): cs_set(x8, cs_get(x0) + cs_get(x1)); ret(x8)
@sem(0x1003865e8)
def _(x0, x1, x8): cs_set(x8, cs_get(x0) + rdstr(x1)); ret(x8)
@sem(0x100386df8)
def _(x0, x1, x8): c = x1 & 0xff; cs_set(x8, cs_get(x0) + (chr(c) if c else '')); ret(x8)
@sem(0x1003691c4)
def _(x0, x1, x8): resref_set(x0, cs_get(x1)); ret(x0)
@sem(0x100369378)
def _(x0, x1, x8): resref_set(x0, rdstr(x1)); ret(x0)
@sem(0x1003690fc)
def _(x0, x1, x8): resref_set(x0, cs_get(x1)); log.append(('rr=cs', where(x0), cs_get(x1))); ret(x0)
@sem(0x10036928c)
def _(x0, x1, x8): resref_set(x0, rdstr(x1)); log.append(('rr=', where(x0), rdstr(x1))); ret(x0)
@sem(0x100369860)
def _(x0, x1, x8): ret(1 if resref_get(x0).upper() == rdstr(x1).upper() else 0)
@sem(0x100369f78)
def _(x0, x1, x8):
    fmt = rdstr(x0); sp = R(UC_ARM64_REG_SP); arg = rd64(sp)
    s = fmt.replace('%04x', '%04x' % (arg & 0xffff)) if '%04x' in fmt else fmt
    ret(put_str(s))
@sem(0x100078c00)
def _(x0, x1, x8): log.append(('load', where(x0), resref_get(x1))); ret(0)
@sem(0x100386124)
def _(x0, x1, x8): ret(0)

FSET = set(FUNCS)
import re as _re
def _is_ctor(a):
    n = name(a)
    m = _re.match(r'^([\w:]+)::(\w+)\(', n)
    return bool(m and m.group(1).split('::')[-1] == m.group(2))
CTORS = set(a for a in FUNCS if _is_ctor(a))
def hook(uc, addr, size, ud):
    if addr == CTOR: return
    if addr in SEM:
        SEM[addr](R(X[0]), R(X[1]), R(X[8])); return
    if addr in FSET:
        ret(R(X[0]) if addr in CTORS else 0)
done = []
def run(anim):
    global log
    log = []
    mu.mem_write(OBJ, b'\0' * 0x10000)
    heap_ptr[0] = HEAP
    sp = STACK + 0x1f0000
    mu.reg_write(UC_ARM64_REG_SP, sp)
    for i in range(29): mu.reg_write(X[i], 0)
    mu.reg_write(UC_ARM64_REG_X0, OBJ); mu.reg_write(UC_ARM64_REG_X1, anim)
    mu.reg_write(UC_ARM64_REG_X2, HEAP + 0x3f0000); mu.reg_write(UC_ARM64_REG_X3, 0)
    END = 0x7ffff000
    mu.reg_write(UC_ARM64_REG_LR, END)
    try:
        mu.emu_start(CTOR, END, timeout=5_000_000, count=200000)
    except UcError as e:
        pc = R(UC_ARM64_REG_PC)
        return dict(err=f'{e} at {pc:#x}', log=log)
    obj = bytes(mu.mem_read(OBJ, 0x2438))
    return dict(log=log, body=cs_get(OBJ + 0xcd8), armor=chr(obj[0xcf8]) if obj[0xcf8] else '',
                armor_max=chr(obj[0xcf9]) if obj[0xcf9] else '', split=struct.unpack('<I', obj[0x2430:0x2434])[0],
                obj=obj)

mu.hook_add(UC_HOOK_CODE, hook, begin=0x100000000, end=0x10074c000)
# trouver les ID personnages : boucle sur 0x5000-0x6fff, garder ceux qui donnent un corps
out = {}
for anim in list(range(0x5000, 0x5400)) + list(range(0x6000, 0x6600)):
    r = run(anim)
    if 'err' in r:
        print(hex(anim), r['err']); continue
    if not r['body']:
        continue
    strs = {}
    for op, w, s in r['log']:
        if op.startswith('cs') and w.startswith('this+'): strs[w] = s
    loads = [(w, s) for op, w, s in r['log'] if op == 'load']
    out[anim] = dict(body=r['body'], armor_max=r['armor_max'], split=r['split'], strs=strs, loads=loads)
json.dump({hex(k): v for k, v in out.items()}, open('char_anims.json', 'w'), indent=1)
print(len(out), 'animations de personnage')
for k in sorted(out)[:6]: print(hex(k), out[k])
