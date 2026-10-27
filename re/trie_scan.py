# Balayage brut de la region du trie d'export : reconstruit les noms (meme non atteignables).
import pickle, subprocess, string
D=open('bg2_arm64','rb').read()[8097344:8097344+478136]
N=len(D)
PR=set(bytes(string.ascii_letters+string.digits+'_$.',"ascii"))
def uleb(d,i):
    r=0; s=0
    while i<len(d):
        b=d[i]; i+=1; r|=(b&0x7f)<<s; s+=7
        if b<0x80: return r,i
        if s>35: return None,i
    return None,i
def try_node(i):
    t,j=uleb(D,i)
    if t is None or t>12: return None
    term=None
    if t:
        fl,k=uleb(D,j)
        if fl is None or fl>0x1f: return None
        ad,k=uleb(D,k)
        if ad is None: return None
        term=(fl,ad)
    j=j+t
    if j>=N: return None
    n=D[j]; j+=1
    if n>64: return None
    edges=[]
    for _ in range(n):
        e=D.find(b'\0',j)
        if e<0 or e==j or e-j>400: return None
        lab=D[j:e]
        if any(c not in PR for c in lab): return None
        c,j=uleb(D,e+1)
        if c is None or c>=N or c==0: return None
        edges.append((lab.decode(),c))
    if not edges and term is None: return None
    return term,edges
nodes={}
for i in range(N):
    r=try_node(i)
    if r: nodes[i]=r
# garder les aretes dont la cible est un noeud valide
parent={}
for i,(term,edges) in nodes.items():
    for lab,c in edges:
        if c in nodes and c not in parent: parent[c]=(i,lab)
names=[]
for i,(term,edges) in nodes.items():
    if term is None: continue
    # remonter
    parts=[]; k=i; depth=0
    while k in parent and depth<50:
        p,lab=parent[k]; parts.append(lab); k=p; depth+=1
    if not parts: continue
    nm=''.join(reversed(parts))
    names.append((0x100000000+term[1], nm, k))
print(len(nodes),'noeuds', len(names),'terminaux')
pickle.dump(names,open('trie_names.pkl','wb'))
