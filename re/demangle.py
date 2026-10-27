# demangle.py - noms du trie d'export (trie_names.pkl, fait par trie_scan.py) -> names_dem.pkl pour rx.py
# (adresse, nom brut, nom demele par c++filt). Licence MIT.
import pickle, subprocess
T = pickle.load(open('trie_names.pkl', 'rb'))
raw = [n for a, n, k in T]
out = subprocess.run(['c++filt'], input='\n'.join(raw), capture_output=True, text=True).stdout.split('\n')
M = [(a, n, out[i] if n.startswith('_Z') else n) for i, (a, n, k) in enumerate(T)]
pickle.dump(M, open('names_dem.pkl', 'wb'))
print(len(M), 'noms')
