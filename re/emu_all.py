# emu_all.py - emule le constructeur de chaque type d'animation pour chaque ID et releve
# les ressources chargees dans les cellules (offset -> resref). Licence MIT.
import json, sys, collections
src = open('emu_char.py').read()
src = src[:src.index('# trouver les ID')]
exec(src)
CT = {
 'Effect': 0x10025aa60, 'Flying': 0x10025d068, 'TownStatic': 0x10025e354, 'AmbientStatic': 0x10025f2b4,
 'Ambient': 0x100260594, 'Monster': 0x100261c94, 'MonsterOld': 0x1002670a4, 'MonsterIcewind': 0x100269288,
 'MonsterLarge': 0x10026df80, 'MonsterLarge16': 0x10026ff80, 'MonsterMulti': 0x100271954,
 'MonsterQuadrant': 0x1002753d8, 'MonsterLayered': 0x1002778c8, 'MonsterLayeredSpell': 0x100279ad8,
 'MonsterAnkheg': 0x10027c324, 'Character': 0x10027db6c, 'CharacterOld': 0x1002857f8, 'MonsterMultiNew': 0x1002902ac,
}
import struct as _st
NULLFN = _st.pack('<II', 0xd2800000, 0xd65f03c0)   # mov x0,#0 ; ret
def run_ctor(ctor, anim):
    global log
    globals()['CTOR'] = ctor
    log.clear() if isinstance(log, list) else None
    globals()['log'] = []
    mu.mem_write(OBJ, b'\0' * 0x10000)
    mu.mem_write(STACK, b'\0' * 0x200000)
    mu.mem_write(HEAP, b'\0' * 0x400000)
    mu.mem_write(0, b'\0' * 0x200000)
    mu.mem_write(0, NULLFN)
    heap_ptr[0] = HEAP
    sp = STACK + 0x1f0000
    mu.reg_write(UC_ARM64_REG_SP, sp)
    for i in range(29): mu.reg_write(X[i], 0)
    mu.reg_write(UC_ARM64_REG_X0, OBJ); mu.reg_write(UC_ARM64_REG_X1, anim)
    mu.reg_write(UC_ARM64_REG_X2, HEAP + 0x3f0000); mu.reg_write(UC_ARM64_REG_X3, 0)
    END = 0x7ffff000
    mu.reg_write(UC_ARM64_REG_LR, END)
    try:
        mu.emu_start(ctor, END, timeout=10_000_000, count=400000)
    except UcError as e:
        return dict(err=f'{e} at {R(UC_ARM64_REG_PC):#x}', log=globals()['log'])
    return dict(log=globals()['log'])

# (le crochet est deja pose par emu_char.py)
rows = json.load(open('../anim/anim_table.json'))
out = {}
for r in rows:
    anim = int(r['id'], 16)
    res = run_ctor(CT[r['cls']], anim)
    loads = [(w, s) for op, w, s in res['log'] if op == 'load']
    rrs = [(w, s) for op, w, s in res['log'] if op.startswith('rr')]
    out[r['id']] = dict(cls=r['cls'], resref=r['resref'], err=res.get('err'), loads=loads, rr=rrs)
json.dump(out, open('all_anims.json', 'w'), indent=0)
by = collections.Counter((v['cls'], bool(v['err']), len(v['loads']) > 0) for v in out.values())
for k, n in sorted(by.items()): print(k, n)
