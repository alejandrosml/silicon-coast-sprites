# inventory.py - releve de tous les BAM d'animation : cycles, cadres, contenus (boites serrees). Licence MIT.
#   python3 inventory.py <dossier des BAM d'origine> <inv.pkl>
import sys, os, glob, pickle, time
import numpy as np
from bam import BamV1

def tight(pix, t):
    nz = pix != t
    if not nz.any():
        return None
    ys = np.flatnonzero(nz.any(1)); xs = np.flatnonzero(nz.any(0))
    return (int(xs[0]), int(ys[0]), int(xs[-1]) + 1, int(ys[-1]) + 1)

def scan(path):
    name = os.path.splitext(os.path.basename(path))[0].upper()
    raw = open(path, 'rb').read()
    b = BamV1.load(raw)
    t = b.tidx
    frames = []
    tb = {}
    for fr in b.frames:
        k = id(fr.pix)
        if k not in tb:
            tb[k] = tight(fr.pix, t)
        frames.append((fr.w, fr.h, fr.cx, fr.cy, tb[k]))
    cycles = [[b.lookup[s + i] for i in range(c)] for c, s in b.cycles]
    pal = b.palette
    palalpha = bool(((pal[:, 3] != 0) & (pal[:, 3] != 255)).any())
    return name, dict(tidx=t, frames=frames, cycles=cycles, palalpha=palalpha, size=len(raw),
                      uniq=len(tb), area=sum(f[0] * f[1] for f in frames))

if __name__ == '__main__':
    src = sys.argv[1]; out = sys.argv[2]
    files = sorted(glob.glob(os.path.join(src, '*.BAM')))
    t0 = time.time()
    from multiprocessing import Pool
    with Pool(os.cpu_count() or 1) as p:
        res = dict(p.imap_unordered(scan, files, chunksize=16))
    pickle.dump(res, open(out, 'wb'))
    print(len(res), 'fichiers', time.time() - t0, 's')
