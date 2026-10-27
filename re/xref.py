# Index des references (ADRP+ADD/LDR, BL) dans la tranche arm64 - analyse hors ligne.
import capstone, struct, pickle, sys, collections
data=open('bg2_arm64','rb').read()
TEXT_OFF=0x1350; TEXT_SIZE=0x63271c; BASE=0x100000000
md=capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
md.detail=False
code=data[TEXT_OFF:TEXT_OFF+TEXT_SIZE]
refs=collections.defaultdict(list)   # target -> [insn addr]
calls=collections.defaultdict(list)  # callee -> [call site]
pages={}                             # reg -> (page, addr) tracking within a window
n=0
last_adrp={}
for i in md.disasm_lite(code, BASE+TEXT_OFF):
    addr,size,mn,ops=i; n+=1
    if mn=='adrp':
        r,imm=ops.split(', '); last_adrp[r]=(int(imm.replace('#',''),16),addr)
    elif mn=='add' and '#' in ops:
        p=ops.split(', ')
        if len(p)==3 and p[1] in last_adrp and addr-last_adrp[p[1]][1]<64:
            t=last_adrp[p[1]][0]+int(p[2].replace('#',''),16); refs[t].append(addr)
    elif mn in('ldr','ldrb','ldrh','ldrsw','str','ldp','stp') and '[' in ops:
        try:
            base=ops.split('[')[1].split(']')[0].split(', ')
            if base[0] in last_adrp and len(base)==2 and base[1].startswith('#') and addr-last_adrp[base[0]][1]<64:
                t=last_adrp[base[0]][0]+int(base[1].replace('#',''),16); refs[t].append(addr)
        except Exception: pass
    elif mn=='bl':
        try: calls[int(ops.replace('#',''),16)].append(addr)
        except: pass
    elif mn in ('ret','b'): pass
print('insns',n,'refs',len(refs),'callees',len(calls))
pickle.dump((dict(refs),dict(calls)),open('xref.pkl','wb'))
