# chaine.py - Silicon Coast, chaîne des monstres 3D : un monstre de BG2:EE (type d'animation 7000), du sprite
# d'origine aux BAM HD (SC-HD x4) vérifiés, sans retouche à la main. Chaque étape reprend là où elle s'était arrêtée.
#
#   python3 chaine.py <RESREF> [--travail DOSSIER] [--jusqua ETAPE] [--refaire ETAPE[,ETAPE]] [--sans-gpu]
#                     [--sans-schd]
#
# Étapes (dans l'ordre) et fichiers produits dans <travail> :
#   origine     prepare.py      origine/ (frises, silhouettes, vues agrandies, mesures)
#   dessin      reference.py    dessin/reference.png (Qwen-Image-Edit, plusieurs variantes notées)        [GPU]
#   modele      reference.py    modele/modele.glb (TRELLIS.2)                                            [GPU]
#   rig         auto_rig.py     rig/rig.blend (squelette Mixamo, poids), rig/rig_rig.json (contrôle)
#   arme        arme.py         rig/arme.blend, rig/arme_modele.json (objet tenu, si la fiche en a un)
#   mouvements  mouvements.py   mouvements/choix.json, anims/<SEQ>.blend, planche.npz
#   lumiere     lumiere.py      rendu/lumiere.json (luminosité de l'original, ombre au sol)
#   rendu       bl_anim.py      rendu/images/ (couleur, silhouette, cadre) : une séquence par processus
#   ombre       bl_anim.py      rendu/images/*_ombre.png (passe d'ombre seule)
#   bams        bams7000.py     hd/*.BAM (+ hdF), palette 88-255 refaite
#   schd        sc_convert.py   schd/*.BAM (format SC-HD), verif.json (sc_verify.py)
#   controle    controle.py     controle/rapport.json, rapport.md, planche.png, GIF original | nouveau
# Variables d'environnement : SC_SRC (BAM d'origine), SC_BLENDER, SC_MOCAP, SC_SPRITES (voir commun.py).
import json
import os
import subprocess
import sys
import time

from commun import BLENDER, ICI, SPRITES, SRC, ecrit_json, lit_json

ETAPES = ['origine', 'dessin', 'modele', 'rig', 'arme', 'mouvements', 'lumiere', 'rendu', 'ombre', 'bams', 'schd',
          'controle']
A = sys.argv[1:]
RES = A[0].upper()
opt = lambda n, d=None: A[A.index(n) + 1] if n in A else d
TRAV = os.path.abspath(opt('--travail', os.path.join(os.environ.get('SC_MONSTRES', os.path.join(ICI, 'monstres')), RES)))
JUSQUA = opt('--jusqua', ETAPES[-1])
REFAIRE = set((opt('--refaire', '') or '').split(',')) - {''}
SANS_GPU = '--sans-gpu' in A
SANS_SCHD = '--sans-schd' in A          # sessions cloud : la conversion SC-HD se fait ensuite dans la session principale
os.makedirs(os.path.join(TRAV, 'journal'), exist_ok=True)
ETAT_P = os.path.join(TRAV, 'etat.json')
etat = lit_json(ETAT_P, {})
PY = sys.executable


def note(etape, **kw):
    etat.setdefault(etape, {}).update(kw)
    ecrit_json(ETAT_P, etat)


def lance(etape, cmd, cwd=None, essais=1):
    """commande d'une étape : sortie dans journal/<etape>.txt ; True si code 0."""
    j = os.path.join(TRAV, 'journal', etape + '.txt')
    for k in range(essais):
        with open(j, 'a') as f:
            f.write('\n### %s essai %d : %s\n' % (time.strftime('%Y-%m-%d %H:%M:%S'), k + 1, ' '.join(cmd)))
            f.flush()
            r = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, cwd=cwd)
        if r.returncode == 0:
            return True
    return False


def blender(etape, script, *args, essais=1):
    return lance(etape, [BLENDER, '-b', '--factory-startup', '--python-exit-code', '1', '-P', os.path.join(ICI, script),
                         '--'] + list(args), essais=essais)


def existe(*p):
    return all(os.path.exists(os.path.join(TRAV, x)) for x in p)


# ------------------------------------------------------------------------------------------------ étapes
def e_origine():
    if existe('origine/sequences.json', 'origine/mesures.json', 'origine/masques.npz'):
        return True
    return lance('origine', [PY, os.path.join(ICI, 'prepare.py'), RES, TRAV])


def e_dessin():
    if existe('dessin/reference.png'):
        return True
    if SANS_GPU:
        print('dessin : pas de GPU dans cette session (--sans-gpu)'); return False
    return lance('dessin', [PY, os.path.join(ICI, 'reference.py'), 'dessin', RES, TRAV])


def e_modele():
    if existe('modele/modele.glb'):
        return True
    if SANS_GPU:
        print('modèle : pas de GPU dans cette session (--sans-gpu)'); return False
    return lance('modele', [PY, os.path.join(ICI, 'reference.py'), 'modele', RES, TRAV])


def e_rig():
    if existe('rig/rig.blend', 'rig/rig_rig.json'):
        return lit_json(os.path.join(TRAV, 'rig', 'rig_rig.json'), {}).get('ok', True) or True
    os.makedirs(os.path.join(TRAV, 'rig'), exist_ok=True)
    ok = blender('rig', 'auto_rig.py', os.path.join(TRAV, 'modele', 'modele.glb'), os.path.join(TRAV, 'rig', 'rig.blend'))
    r = lit_json(os.path.join(TRAV, 'rig', 'rig_rig.json'), {})
    if not r.get('ok', False):
        # contrôle douteux : nouvel essai avec un remaillage plus grossier ; on garde le meilleur des deux
        print('rig : contrôle douteux, nouvel essai (voxel 0.025)', flush=True)
        import shutil
        d = os.path.join(TRAV, 'rig')
        if os.path.exists(os.path.join(d, 'rig_rig.json')):
            os.replace(os.path.join(d, 'rig_rig.json'), os.path.join(d, 'rig_rig_essai1.json'))
        if os.path.exists(os.path.join(d, 'rig.blend')):
            shutil.copy(os.path.join(d, 'rig.blend'), os.path.join(d, 'rig_essai1.blend'))
        ok2 = blender('rig', 'auto_rig.py', os.path.join(TRAV, 'modele', 'modele.glb'), os.path.join(d, 'rig.blend'),
                      '--voxel', '0.025')
        r2 = lit_json(os.path.join(d, 'rig_rig.json'), {})
        mesure = lambda x: (x.get('sommets_sans_poids', 1e9), x.get('aretes_etirees_x2_pct', 1e9))
        if r and os.path.exists(os.path.join(d, 'rig_essai1.blend')) and (not ok2 or mesure(r) < mesure(r2)):
            shutil.copy(os.path.join(d, 'rig_essai1.blend'), os.path.join(d, 'rig.blend'))
            shutil.copy(os.path.join(d, 'rig_rig_essai1.json'), os.path.join(d, 'rig_rig.json'))
            print('rig : premier essai gardé', mesure(r), 'contre', mesure(r2), flush=True)
            ok2 = ok
        note('rig', controle=lit_json(os.path.join(d, 'rig_rig.json'), {}).get('ok'), essais=2)
        return ok2 and os.path.exists(os.path.join(d, 'rig.blend'))
    return ok


def e_arme():
    fiche = lit_json(os.path.join(ICI, 'fiches.json'))[RES]
    if not fiche.get('objet'):
        return True
    if existe('rig/arme.blend', 'rig/arme_modele.json'):
        return True
    return blender('arme', 'arme.py', RES, TRAV)


def e_mouvements():
    c = lit_json(os.path.join(TRAV, 'mouvements', 'choix.json'), {})
    seqs = lit_json(os.path.join(TRAV, 'origine', 'sequences.json'))
    voulues = [s for s in seqs if not seqs[s].get('copie_de')]
    if c and all(s in c and 'fichier' in c[s] for s in voulues) and existe('mouvements/planche.npz'):
        return True
    return blender('mouvements', 'mouvements.py', RES, TRAV, essais=2)


def e_lumiere():
    if lit_json(os.path.join(TRAV, 'rendu', 'lumiere.json'), {}).get('ok'):
        return True
    return lance('lumiere', [PY, os.path.join(ICI, 'lumiere.py'), RES, TRAV])


def configs_par_sequence(ombre=False):
    cfgp = os.path.join(TRAV, 'rendu', 'cfg.json')
    if not lance('rendu', [PY, os.path.join(ICI, 'jobs7000.py'), RES, TRAV, '--sortie', cfgp]):
        return None
    cfg = json.load(open(cfgp))
    out = []
    for s in sorted(cfg['anims']):
        jobs = [j for j in cfg['jobs'] if j['anim'] == s]
        if not jobs:
            continue
        c = dict(cfg, jobs=jobs)
        if ombre:
            c['ombre_seule'] = True
            c['samples_ombre'] = 8
            c['ombre'] = lit_json(os.path.join(TRAV, 'rendu', 'lumiere.json'), {}).get('ombre', {'az_deg': -108,
                                                                                               'el_deg': 80})
        p = os.path.join(TRAV, 'rendu', 'cfg_%s%s.json' % (s, '_ombre' if ombre else ''))
        json.dump(c, open(p, 'w'))
        out.append((s, p, jobs))
    return out


def manquants(jobs, ombre=False):
    if ombre:
        return [j for j in jobs if not os.path.exists(os.path.splitext(j['out'])[0] + '_ombre.png')]
    return [j for j in jobs if not all(os.path.exists(x) for x in (j['out'], j['mask'],
                                                                     os.path.splitext(j['out'])[0] + '.json'))]


def e_rendu(ombre=False):
    etape = 'ombre' if ombre else 'rendu'
    cfgs = configs_par_sequence(ombre)
    if cfgs is None:
        return False
    total = sum(len(j) for _, _, j in cfgs)
    for s, p, jobs in cfgs:
        for essai in range(3):
            m = manquants(jobs, ombre)
            if not m:
                break
            t0 = time.time()
            print('%s %s : %d images à faire (essai %d)' % (etape, s, len(m), essai + 1), flush=True)
            blender(etape, 'bl_anim.py', p)
            note(etape, **{'duree_' + s: round(time.time() - t0)})
        if manquants(jobs, ombre):
            print('%s %s : images manquantes après 3 essais' % (etape, s), flush=True)
            return False
    note(etape, images=total)
    return True


def e_ombre():
    return e_rendu(ombre=True)


def e_bams():
    if existe('hd/fichiers.txt') and 'bams' not in REFAIRE:
        return True
    return lance('bams', [PY, os.path.join(ICI, 'bams7000.py'), RES, TRAV])


def e_schd():
    if SANS_SCHD:
        print('schd : laissé à la session principale (--sans-schd)')
        return True
    v = lit_json(os.path.join(TRAV, 'verif.json'))
    if v is not None and v.get('errors') == 0 and 'schd' not in REFAIRE:
        return True
    outils = os.path.join(SPRITES, 'tools')
    tables = os.path.join(SPRITES, 'tables')
    hd = os.path.join(TRAV, 'hd'); fich = os.path.join(hd, 'fichiers.txt'); schd = os.path.join(TRAV, 'schd')
    ok = lance('schd', [PY, 'sc_convert.py', 'build', SRC, os.path.join(tables, 'groups.json'),
                        os.path.join(tables, 'canon_all.json'), schd, '--hd', hd, '--hd-k', '4', '--hd-palette',
                        '--ext-hd', '--hd-cycles', '--files', fich, '-j', '2',
                        '--log', os.path.join(TRAV, 'journal', 'sc_convert_detail.txt')], cwd=outils)
    if not ok:
        return False
    ok = lance('schd', [PY, 'sc_verify.py', SRC, schd, os.path.join(tables, 'groups.json'),
                        os.path.join(tables, 'canon_all.json'), '--files', fich, '--new-art', '--ext-hd', hd, '4',
                        '--hd-cycles', '-j', '2', '--report', os.path.join(TRAV, 'verif.json')], cwd=outils)
    v = lit_json(os.path.join(TRAV, 'verif.json'), {})
    note('schd', erreurs=v.get('errors'), images_hd=v.get('hd_frames'))
    return ok and v.get('errors') == 0


def e_controle():
    return lance('controle', [PY, os.path.join(ICI, 'controle.py'), RES, TRAV])


FONCTIONS = {e: globals()['e_' + e] for e in ETAPES}


def main():
    t_debut = time.time()
    print('chaîne', RES, '->', TRAV, flush=True)
    for e in ETAPES:
        if e in REFAIRE:
            etat.pop(e, None)
        if etat.get(e, {}).get('ok') and e not in REFAIRE:
            print('%-10s déjà fait' % e, flush=True)
        else:
            t0 = time.time()
            print('%-10s ...' % e, flush=True)
            ok = bool(FONCTIONS[e]())
            note(e, ok=ok, fini=time.strftime('%Y-%m-%d %H:%M:%S'), duree=round(time.time() - t0))
            print('%-10s %s en %.0f s' % (e, 'fait' if ok else 'ÉCHEC', time.time() - t0), flush=True)
            if not ok:
                note('_chaine', arret=e, duree=round(time.time() - t_debut))
                print('arrêt à l\'étape', e, '- journal :', os.path.join(TRAV, 'journal', e + '.txt'))
                return 1
        if e == JUSQUA:
            break
    note('_chaine', arret=None, fin=time.strftime('%Y-%m-%d %H:%M:%S'), duree=round(time.time() - t_debut))
    print('chaîne finie pour', RES, 'en %.0f s' % (time.time() - t_debut))
    return 0


if __name__ == '__main__':
    sys.exit(main())
