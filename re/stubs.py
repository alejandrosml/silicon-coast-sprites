import lief, pickle, struct
b=lief.MachO.parse('bg2_arm64').at(0)
secs={s.name:s for s in b.sections}
for n in ['__stubs','__auth_stubs','__got','__la_symbol_ptr','__auth_got']:
    if n in secs: s=secs[n]; print(n, hex(s.virtual_address), hex(s.size), s.reserved1, s.reserved2)
# table des symboles indirects
dys=b.dynamic_symbol_command
ind=dys.indirect_symbols
print('indirect', len(ind))
stubmap={}
s=secs.get('__stubs')
if s:
    size=s.reserved2 or 12
    for k in range(s.size//size):
        idx=s.reserved1+k
        sym=ind[idx] if idx<len(ind) else None
        stubmap[s.virtual_address+k*size]=sym.name if sym is not None else '?'
gl=sorted((a,n) for a,n in stubmap.items() if 'gl' in n.lower())
print(len(stubmap),'stubs'); print(gl[:80])
pickle.dump(stubmap,open('stubs.pkl','wb'))
