# Outils d'analyse hors ligne : debuts de fonctions (LC_FUNCTION_STARTS), desassemblage, xrefs.
import lief, pickle, bisect, capstone
B=0x100000000
_b=lief.MachO.parse('bg2_arm64').at(0)
FUNCS=sorted(B+f for f in _b.function_starts.functions)
DATA=open('bg2_arm64','rb').read()
REFS,CALLS=pickle.load(open('xref.pkl','rb'))
STUBS=pickle.load(open('stubs.pkl','rb'))
NAME={v:k for k,v in STUBS.items()}
md=capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
def func_of(a):
    i=bisect.bisect_right(FUNCS,a)-1
    return FUNCS[i] if i>=0 else None
def func_end(f):
    i=bisect.bisect_right(FUNCS,f)
    return FUNCS[i] if i<len(FUNCS) else f+0x1000
def cstr(a):
    o=a-B; e=DATA.index(b'\0',o); return DATA[o:e].decode('latin1')
def stub_addr(name): return NAME[name]
def callers(name):
    return sorted(set(CALLS.get(stub_addr(name),[])))
def dis(f, hi=None, annotate=True, maxn=4000):
    e=func_end(f) if hi is None else hi
    out=[]
    for i in md.disasm(DATA[f-B:e-B], f):
        s=f'{i.address:x}: {i.mnemonic} {i.op_str}'
        if annotate and i.mnemonic=='bl':
            try:
                t=int(i.op_str.replace('#',''),16)
                if t in STUBS: s+='   ; '+STUBS[t]
                else: s+=f'   ; fn_{t:x}'
            except: pass
        out.append(s)
        if len(out)>=maxn: break
    return out
def refs_to(a): return sorted(set(REFS.get(a,[])))

def dis2(f, hi=None, maxn=6000):
    """desassemblage annote : chaines (adrp+add), appels de stubs."""
    e=func_end(f) if hi is None else hi
    out=[]; adrp={}
    for i in md.disasm(DATA[f-B:e-B], f):
        s=f'{i.address:x}: {i.mnemonic} {i.op_str}'
        ops=[o.strip() for o in i.op_str.split(',')]
        if i.mnemonic=='adrp': adrp[ops[0]]=int(ops[1].replace('#',''),16)
        elif i.mnemonic=='add' and len(ops)==3 and ops[1] in adrp and ops[2].startswith('#'):
            t=adrp[ops[1]]+int(ops[2].replace('#',''),16)
            if 0x10063cf50<=t<0x10063cf50+0x443ca:
                try: s+=f'   ; "{cstr(t)}"'
                except: pass
            else: s+=f'   ; ={t:x}'
        if i.mnemonic=='bl':
            try:
                t=int(i.op_str.replace('#',''),16)
                s+='   ; '+(STUBS[t] if t in STUBS else f'fn_{t:x}')
            except: pass
        out.append(s)
        if len(out)>=maxn: break
    return out

import pickle as _pk
try:
    _M=_pk.load(open('names_dem.pkl','rb'))
    SYM={a:d for a,n,d in _M}
except Exception: SYM={}
def name(a):
    if a in STUBS: return STUBS[a]
    if a in SYM: return SYM[a]
    return f'fn_{a:x}'
def find(pat):
    import re
    return sorted((a,d) for a,d in SYM.items() if re.search(pat,d))
def dis3(f, hi=None, maxn=8000):
    """desassemblage annote avec noms de symboles."""
    e=func_end(f) if hi is None else hi
    out=[]; adrp={}
    for i in md.disasm(DATA[f-B:e-B], f):
        s=f'{i.address:x}: {i.mnemonic} {i.op_str}'
        ops=[o.strip() for o in i.op_str.split(',')]
        if i.mnemonic=='adrp': adrp[ops[0]]=int(ops[1].replace('#',''),16)
        elif i.mnemonic=='add' and len(ops)==3 and ops[1] in adrp and ops[2].startswith('#'):
            t=adrp[ops[1]]+int(ops[2].replace('#',''),16)
            if 0x10063cf50<=t<0x10063cf50+0x443ca:
                try: s+=f'   ; "{cstr(t)}"'
                except: pass
            elif t in SYM: s+='   ; &'+SYM[t]
            else: s+=f'   ; ={t:x}'
        if i.mnemonic in ('bl','b'):
            try:
                t=int(i.op_str.replace('#',''),16)
                if i.mnemonic=='bl' or t in SYM or t in STUBS:
                    if not (f<=t<e): s+='   ; '+name(t)
            except: pass
        out.append(s)
        if len(out)>=maxn: break
    return out
