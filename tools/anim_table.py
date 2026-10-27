# anim_table.py - table des animations de creatures a partir des fichiers INI du jeu (Silicon Coast, MIT)
#
#   python3 anim_table.py <dossier des INI> <anim_table.json>
#
# Le dossier contient les ressources INI d'animation extraites du jeu (une par identifiant : 7F3B.INI, E265.INI...).
# Chaque ligne de la table : identifiant, classe d'animation (d'apres l'identifiant, comme le moteur), resref et cles
# des sections autres que [sounds]. La classe se lit dans le binaire (CGameAnimationType::SetAnimationType, BG2:EE
# 2.7.3 arm64) : bits 12-15 de l'identifiant, puis sous-cas de la famille 7xxx.
import os, re, sys, json, collections


def anim_class(i):
    t = i >> 12; cls_n = (i >> 8) & 0xf; lo = i & 0xf
    if t == 0: return 'Effect'
    if t == 1:
        if (i & 0xe00) == 0: return 'MonsterQuadrant'
        if (i & 0xf00) == 0x300: return 'MonsterMultiNew'
        return 'MonsterMulti'
    if t == 2: return 'MonsterLayeredSpell'
    if t == 3: return 'MonsterAnkheg'
    if t == 4: return 'TownStatic'
    if t in (5, 6): return 'Character' if cls_n in (0, 1, 2, 3, 5) else 'CharacterOld'
    if t == 7:
        sub = {0: 'a', 1: 'a', 2: 'c', 3: 'm', 4: 'b', 5: 'a', 6: 'o', 7: 'b', 8: 'o', 9: 'd', 0xa: 'd', 0xb: 'e',
               0xc: 'a', 0xd: 'o', 0xe: 'a'}.get(cls_n, 'm')
        if sub == 'm': return 'Monster'
        if sub == 'o': return 'MonsterOld'
        if sub == 'a': return 'Monster' if (0xe & i) else 'MonsterOld'
        if sub == 'b': return 'Monster' if lo >= 3 else 'MonsterOld'
        if sub == 'c': return 'MonsterOld' if not (0xc & i) else 'Monster'
        if sub == 'd': return 'Monster' if lo >= 5 else 'MonsterOld'
        if sub == 'e': return 'Monster' if lo >= 7 else 'MonsterOld'
    return {8: 'MonsterLayered', 9: 'MonsterLarge', 0xa: 'MonsterLarge16', 0xb: 'AmbientStatic', 0xc: 'Ambient',
            0xd: 'Flying', 0xe: 'MonsterIcewind'}.get(t, '?')


def parse_ini(path):
    secs, kv, sec = [], {}, None
    for line in open(path, encoding='latin1').read().splitlines():
        line = line.strip()
        m = re.match(r'^\[(.+)\]$', line)
        if m:
            sec = m.group(1).strip().lower(); secs.append(sec); continue
        if '=' in line and sec not in (None, 'sounds') and not line.startswith('//'):
            k, v = line.split('=', 1); kv[k.strip()] = v.strip()
    return secs, kv


def build(ini_dir):
    rows = []
    for f in sorted(os.listdir(ini_dir)):
        m = re.fullmatch(r'([0-9A-Fa-f]{4})\.ini', f, re.I)
        if not m:
            continue
        i = int(m.group(1), 16)
        secs, kv = parse_ini(os.path.join(ini_dir, f))
        rows.append(dict(id='%04X' % i, cls=anim_class(i), sec=[s for s in secs if s not in ('general', 'sounds')],
                         type=kv.get('animation_type'), resref=kv.get('resref', ''), kv=kv))
    return rows


if __name__ == '__main__':
    rows = build(sys.argv[1])
    json.dump(rows, open(sys.argv[2], 'w'), indent=0)
    for c, n in sorted(collections.Counter(r['cls'] for r in rows).items()):
        print(f'{c:20s} {n:4d}')
    print(len(rows), 'animations')
