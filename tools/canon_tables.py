# canon_tables.py - geometries canoniques de tous les calques dessines ensemble (Silicon Coast, MIT)
#
# Pour chaque jeton (ensemble de fichiers dessines dans une meme surface FX) :
#  - mode 'frame' (Character) : union des contenus par (cycle, image) ;
#  - mode 'cycle' (cellules qui avancent chacune de leur cote) : union par cycle, toutes images confondues.
# Les fichiers a calque seul gardent la boite serree de chaque image.
import json, pickle, collections


def is_placeholder(tb):
    return tb is None or (tb[2] - tb[0]) * (tb[3] - tb[1]) <= 1


def extents(fr):
    """(L, T, R, B) du contenu autour du centre, ou None (bouche-trou)."""
    w, h, cx, cy, tb = fr
    if is_placeholder(tb):
        return None
    return (cx - tb[0], cy - tb[1], tb[2] - cx, tb[3] - cy)


def build_tables(inv, groups):
    table = {}
    for n, g in groups.items():
        tok = g['token']
        if not tok:
            continue
        d = inv[n]
        for c, lst in enumerate(d['cycles']):
            for f, fi in enumerate(lst):
                if fi >= len(d['frames']):
                    continue
                e = extents(d['frames'][fi])
                if e is None:
                    continue
                key = '%s/%d/%d' % (tok, c, f) if g['mode'] == 'frame' else '%s/%d/*' % (tok, c)
                cur = table.get(key)
                table[key] = list(e) if cur is None else [max(a, b) for a, b in zip(cur, e)]
    return table


def key_for(groups, n, c, f):
    g = groups[n]
    if not g['token']:
        return None
    return '%s/%d/%d' % (g['token'], c, f) if g['mode'] == 'frame' else '%s/%d/*' % (g['token'], c)


if __name__ == '__main__':
    # python3 canon_tables.py <inv.pkl> <groups.json> <canon_all.json>
    import sys
    inv = pickle.load(open(sys.argv[1], 'rb'))
    groups = json.load(open(sys.argv[2]))
    tab = build_tables(inv, groups)
    json.dump(dict(version=2, table=tab), open(sys.argv[3], 'w'), sort_keys=True)
    print(len(tab), 'geometries canoniques')
