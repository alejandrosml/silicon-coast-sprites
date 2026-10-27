# groups.py - quels fichiers BAM le moteur dessine ensemble dans une meme surface FX (Silicon Coast, MIT)
#
# Regles tirees du desassemblage de BG2:EE 2.7.3 (Mac arm64) et de l'emulation des constructeurs
# (re/emu_ini.py) : chaque constructeur appelle Unmarshal(<ID>.INI) ; si l'INI existe (468 animations), ses
# cles (resref, glow_layer, shadow, split_bams...) decident des fichiers charges ; sinon (36 ID d'ANIMATE.IDS,
# effets et Icewind sans INI) le constructeur prend ses valeurs codees en dur. L'emulation execute les deux
# chemins comme le moteur ; re/emu_all.py (INI ignores) n'est plus utilise :
#  - Character (CGameAnimationTypeCharacter) : corps C???<armure><action> + casque/bouclier/arme WQ<taille>...
#    dans une surface ; les calques prennent l'image du corps (FrameSet) -> union par image.
#  - CharacterOld : corps <resref><armure><action>[E] + ombre CSHD/SSHD + equipements WP<taille>..., chaque
#    cellule avance seule (FrameAdvance) -> union par cycle.
#  - Monster : corps <resref>G1|G2[chiffre] + arme <resref>G1|G2<code> + calque lumineux <glow>G1|G2...
#  - MonsterIcewind : corps <resref><action>[E] + arme <resref><lettre><action>[E].
#  - MonsterLayered / LayeredSpell : corps <resref>G1|G2[E] + armes <resref><lettre>G1|G2[E].
#  - familles a un seul calque (MonsterOld, Large, Large16, Ambient, AmbientStatic, Flying, TownStatic,
#    Ankheg) : chaque image garde sa propre geometrie.
#  - MonsterQuadrant, MonsterMulti, MonsterMultiNew : un calque par partie, dessine par
#    CInfinity::FXBltFrom (quad decoupe a la fenetre de jeu) -> disposition F.
#  - Effect : non converti (deux calques dans une surface FXBltFrom, 3 animations seulement).
import re, json, collections

ACT_CHAR = r'(A[1-9]|CA|G1[1-9]?|SA|SS|SX)'
ACT_OLD = r'(A[1-9]|CA|G1|SA|SX|W[1-9])'
ICE_ACT = ['A1', 'A2', 'A3', 'A4', 'GU', 'SL', 'DE', 'GH', 'SD', 'SC', 'SP', 'CA', 'TW', 'WK']

PATH_CLIP, PATH_FROM = 'clip', 'from'


class UF:
    def __init__(self):
        self.p = {}
    def find(self, a):
        self.p.setdefault(a, a)
        while self.p[a] != a:
            self.p[a] = self.p[self.p[a]]
            a = self.p[a]
        return a
    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[max(ra, rb)] = min(ra, rb)


def build(rows, emu, names):
    """rows : anim_table.json ; emu : re/all_anims.json ; names : noms des BAM disponibles (majuscules).
    Renvoie {nom: dict(family, path, token, mode)} ; token None = calque seul ; mode 'frame' | 'cycle'."""
    names = set(n.upper() for n in names)
    out = {}
    conflicts = []

    tok_uf = UF()

    def claim(n, fam, path, token, mode, role='body'):
        if n not in names:
            return
        cur = out.get(n)
        new = dict(family=fam, path=path, token=token, mode=mode, role=role)
        if cur is None:
            out[n] = new
            return
        if cur['path'] != path:
            conflicts.append((n, cur, new))      # deux chemins de rendu : signale
            return
        if cur['token'] and token:
            if cur['token'] != token:
                tok_uf.union(cur['token'], token)  # nom ambigu : les deux jetons sont fusionnes
            if mode == 'cycle':
                cur['mode'] = 'cycle'
            if role == 'body':
                cur['role'] = 'body'           # un nom ambigu corps/arme porte les reperes
        elif token and not cur['token']:
            out[n] = new
    # ---------------------------------------------------------- Character
    uf = UF()
    body_class = {}
    for r in rows:
        if r['cls'] != 'Character':
            continue
        kv = r['kv']; res = r['resref']
        hc = (kv.get('height_code') or '')[-1:]
        uf.union('B' + res, 'C' + hc)
        for k in ('height_code_helmet', 'height_code_shield'):
            v = (kv.get(k) or '')
            if v:
                uf.union('B' + res, 'C' + v[-1])
        body_class[res] = hc
    # armure 4 des corps de base : C??C4 (pretre) et C??F4 (guerrier), choisis par le constructeur
    for res in list(body_class):
        if res[3] == 'B':
            for alt in (res[:3] + 'C', res[:3] + 'F'):
                uf.union('B' + alt, 'B' + res)
                body_class.setdefault(alt, body_class[res])
    rx_body = re.compile(r'(C[A-Z]{3})([1-4])' + ACT_CHAR)
    rx_ovl = re.compile(r'WQ([A-Z])([A-Z0-9]{2})(O?)' + ACT_CHAR)
    for n in names:
        m = rx_body.fullmatch(n)
        if m and m.group(1) in body_class:
            act = 'G1' if m.group(3).startswith('G1') else m.group(3)
            claim(n, 'Character', PATH_CLIP, 'CH:%s:%s' % (uf.find('B' + m.group(1)), act), 'frame')
            continue
        m = rx_ovl.fullmatch(n)
        if m:
            act = 'G1' if m.group(4).startswith('G1') else m.group(4)
            claim(n, 'Character', PATH_CLIP, 'CH:%s:%s' % (uf.find('C' + m.group(1)), act), 'frame', 'ovl')
    # ---------------------------------------------------------- CharacterOld
    uf2 = UF()
    old_res = {}
    for r in rows:
        if r['cls'] != 'CharacterOld':
            continue
        e = emu.get(r['id'], {})
        loads = [s for w, s in e.get('loads', []) if w != '0x0']
        if not loads:
            continue
        # resref effectif : prefixe des corps charges (celui de l'INI)
        body = loads[0]
        m = re.fullmatch(r'([A-Z]{4})([0-9])' + r'(G1|W2|CA|A[1-9])E?', body)
        res = m.group(1) if m else r['resref']
        hc = (r['kv'].get('height_code') or '')
        uf2.union('B' + res, 'H' + hc)
        hh = r['kv'].get('height_code_helmet') or ''
        if hh:
            uf2.union('B' + res, 'H' + hh)
        for s in loads:
            if s.startswith(('CSHD', 'SSHD')):
                uf2.union('B' + res, 'S' + s[:4])
        old_res[res] = hc
    rx_old = re.compile(r'([A-Z]{4})([1-4])' + ACT_OLD + r'(E?)')
    rx_shd = re.compile(r'([CS]SHD)' + ACT_OLD + r'(E?)')
    rx_wp = re.compile(r'(WP[A-Z])([A-Z0-9]{2})' + ACT_OLD + r'(E?)')
    for n in names:
        m = rx_old.fullmatch(n)
        if m and m.group(1) in old_res:
            claim(n, 'CharacterOld', PATH_CLIP, 'CO:%s:%s' % (uf2.find('B' + m.group(1)), m.group(3)), 'cycle')
            continue
        m = rx_shd.fullmatch(n)
        if m and ('S' + m.group(1)) in uf2.p:
            claim(n, 'CharacterOld', PATH_CLIP, 'CO:%s:%s' % (uf2.find('S' + m.group(1)), m.group(2)), 'cycle', 'ovl')
            continue
        m = rx_wp.fullmatch(n)
        if m and ('H' + m.group(1)) in uf2.p:
            claim(n, 'CharacterOld', PATH_CLIP, 'CO:%s:%s' % (uf2.find('H' + m.group(1)), m.group(3)), 'cycle', 'ovl')
    # ---------------------------------------------------------- Monster (G1/G2 + armes + calque lumineux)
    for r in rows:
        if r['cls'] != 'Monster':
            continue
        e = emu.get(r['id'], {})
        loads = [s for w, s in e.get('loads', []) if w != '0x0']
        bases = set()
        for s in loads:
            m = re.fullmatch(r'([A-Z0-9]+?)(G[12])', s)
            if m:
                bases.add(m.group(1))
        res = r['resref']
        glow = r['kv'].get('glow_layer')
        for b in bases | ({res} if res else set()):
            for n in names:
                if not n.startswith(b):
                    continue
                m = re.fullmatch(re.escape(b) + r'(G[12])([1-9]?|[A-Z][A-Z0-9])', n)
                if m:
                    role = 'body' if len(m.group(2)) <= 1 else 'ovl'
                    claim(n, 'Monster', PATH_CLIP, 'MO:%s:%s' % (b, m.group(1)), 'cycle', role)
            if glow:
                for n in names:
                    m = re.fullmatch(re.escape(glow) + r'(G[12])([1-9]?)', n)
                    if m:
                        claim(n, 'Monster', PATH_CLIP, 'MO:%s:%s' % (b, m.group(1)), 'cycle', 'ovl')
    # ---------------------------------------------------------- MonsterIcewind
    for r in rows:
        if r['cls'] != 'MonsterIcewind':
            continue
        e = emu.get(r['id'], {})
        loads = [s for w, s in e.get('loads', []) if w != '0x0']
        bases = set(s[:-2] for s in loads if s.endswith('A1'))
        for b in bases:
            for a in ICE_ACT:
                for n in (b + a, b + a + 'E'):
                    claim(n, 'MonsterIcewind', PATH_CLIP, 'IW:%s:%s' % (b, a), 'cycle')
                for n in names:
                    m = re.fullmatch(re.escape(b) + r'([A-Z])' + a + r'(E?)', n)
                    if m:
                        claim(n, 'MonsterIcewind', PATH_CLIP, 'IW:%s:%s' % (b, a), 'cycle', 'ovl')
    # ---------------------------------------------------------- MonsterLayered / LayeredSpell
    for r in rows:
        if r['cls'] not in ('MonsterLayered', 'MonsterLayeredSpell'):
            continue
        e = emu.get(r['id'], {})
        loads = [s for w, s in e.get('loads', []) if w != '0x0']
        bases = set(re.fullmatch(r'([A-Z0-9]+?)(G[12])E?', s).group(1) for s in loads
                    if re.fullmatch(r'([A-Z0-9]+?)(G[12])E?', s))
        for b in bases:
            for n in names:
                if not n.startswith(b):
                    continue
                m = (re.fullmatch(re.escape(b) + r'([A-Z]?)(G[12])(E?)', n) or
                     re.fullmatch(re.escape(b) + r'()(G[12])[A-Z]E', n))
                if m:
                    role = 'body' if (m.group(1) == '' and len(n) <= len(b) + 3) else 'ovl'
                    claim(n, r['cls'], PATH_CLIP, 'LY:%s:%s' % (b, m.group(2)), 'cycle', role)
    # ---------------------------------------------------------- familles a calque seul (chemin FXBltFromClipped)
    single = ('MonsterOld', 'MonsterLarge', 'MonsterLarge16', 'Ambient', 'AmbientStatic', 'Flying',
              'TownStatic', 'MonsterAnkheg')
    for r in rows:
        if r['cls'] not in single:
            continue
        e = emu.get(r['id'], {})
        loads = [s for w, s in e.get('loads', []) if w != '0x0']
        split = r['kv'].get('split_bams') == '1'
        for s in loads:
            claim(s, r['cls'], PATH_CLIP, None, None)
            if split:
                for dgt in '123456789':
                    claim(s + dgt, r['cls'], PATH_CLIP, None, None)
                    if s.endswith('E'):
                        claim(s[:-1] + dgt + 'E', r['cls'], PATH_CLIP, None, None)
    # ---------------------------------------------------------- familles FXBltFrom (disposition F)
    for r in rows:
        c = r['cls']; res = r['resref']
        if c == 'MonsterQuadrant' and res:
            for n in names:
                if re.fullmatch(re.escape(res) + r'G[1-3][1-4]E?', n):
                    claim(n, c, PATH_FROM, None, None)
        elif c == 'MonsterMulti' and res:
            for n in names:
                if re.fullmatch(re.escape(res) + r'[0-9]{4}', n):
                    claim(n, c, PATH_FROM, None, None)
        elif c == 'MonsterMultiNew' and res:
            for n in names:
                if re.fullmatch(re.escape(res) + r'G[12][1-4][1-9]?', n):
                    claim(n, c, PATH_FROM, None, None)
    for v in out.values():
        if v['token']:
            v['token'] = tok_uf.find(v['token'])
    has_body = set(v['token'] for v in out.values() if v['token'] and v['role'] == 'body')
    for v in out.values():
        if v['token'] and v['token'] not in has_body:
            v['role'] = 'body'
    return out, conflicts


if __name__ == '__main__':
    # python3 groups.py <anim_table.json> <all_anims_ini.json> <inv.pkl> <groups.json>
    #   anim_table.json : tools/anim_table.py ; all_anims_ini.json : re/emu_ini.py ; inv.pkl : tools/inventory.py
    import sys, pickle
    rows = json.load(open(sys.argv[1]))
    emu = json.load(open(sys.argv[2]))
    inv = pickle.load(open(sys.argv[3], 'rb'))
    have = set(r['id'] for r in rows)
    for i, v in emu.items():                  # ID sans INI : chemin code en dur, classe d'apres l'ID
        if i not in have:
            rows.append(dict(id=i, cls=v['cls'], sec=[], type=None, resref='', kv={}))
    g, conf = build(rows, emu, inv.keys())
    json.dump(g, open(sys.argv[4], 'w'), indent=0, sort_keys=True)
    c = collections.Counter((v['family'], v['path'], v['mode']) for v in g.values())
    for k, n in sorted(c.items(), key=lambda x: str(x)):
        print(k, n)
    print(len(g), 'fichiers ; non revendiques :', len(set(inv) - set(g)), sorted(set(inv) - set(g))[:60])
    print('conflits :', len(conf))
    for x in conf[:20]:
        print('  ', x)
    toks = collections.Counter(v['token'] for v in g.values() if v['token'])
    print('jetons multi-calques :', len(toks))
