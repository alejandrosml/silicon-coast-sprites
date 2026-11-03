# revue.py - Silicon Coast, chaîne des monstres 3D : page de revue des monstres refaits (artefact), à partir des
# dossiers de travail (controle/rapport.json, BAM HD, dessin de référence).
#   python3 revue.py <dossier de sortie> <dossier des monstres> RES [RES ...]
# Écrit <sortie>/index.html et <sortie>/a/ (aperçus réduits : GIF original | nouveau, 2 directions ; dessins).
import html
import json
import os
import sys

from PIL import Image

from commun import NOMS_SEQ, lit_json
import controle

ICI = os.path.dirname(os.path.abspath(__file__))
FICHES = lit_json(os.path.join(ICI, 'fiches.json'))
INI = {'MTRO': '7F00', 'MUMB': '7F11', 'MVAM': '7F12', 'MMIN': '7F01', 'MIGO': '7F04', 'MGLC': '7F07',
       'MLIC': '7F0D', 'MGIT': '7F14', 'MSLY': '7F32', 'MSHD': '7703'}
ARCH = {'griffes': 'griffes', 'poings': 'poings', 'vampire': 'griffes et morsure', 'mage': 'lanceur de sorts',
        'epee': 'épée'}
APERCUS = ('SD', 'WK', 'A1')


def e(x):
    return html.escape(str(x))


def apercus(res, trav, adir):
    out = []
    seqs = lit_json(os.path.join(trav, 'origine', 'sequences.json'))
    choix = lit_json(os.path.join(trav, 'mouvements', 'choix.json'), {})
    for s in APERCUS:
        src = s if s in seqs and not seqs[s].get('copie_de') else (seqs.get(s, {}).get('copie_de'))
        if not src or src not in seqs or 'n' not in choix.get(src, {}):
            continue
        p = os.path.join(adir, '%s_%s.gif' % (res, src))
        if not os.path.exists(p):
            controle.gif_sequence(src, seqs[src], choix[src], res, trav, p, dirs=(0, 4))
            im = Image.open(p)
            if im.width > 560:            # réduit pour la page
                fr = []
                try:
                    while True:
                        f = im.convert('RGB'); f = f.resize((560, int(f.height * 560 / f.width)), Image.LANCZOS)
                        fr.append(f); im.seek(im.tell() + 1)
                except EOFError:
                    pass
                fr[0].save(p, save_all=True, append_images=fr[1:], duration=67, loop=0, optimize=True)
        out.append((src, os.path.basename(p)))
    d = os.path.join(trav, 'dessin', 'reference.png')
    dessin = None
    if os.path.exists(d):
        dessin = '%s_dessin.jpg' % res
        im = Image.open(d).convert('RGB'); im.thumbnail((360, 480)); im.save(os.path.join(adir, dessin), quality=85)
    return out, dessin


def main():
    sortie, racine = os.path.abspath(sys.argv[1]), os.path.abspath(sys.argv[2])
    resrefs = [r.upper() for r in sys.argv[3:]]
    adir = os.path.join(sortie, 'a')
    os.makedirs(adir, exist_ok=True)
    lignes, cartes = [], []
    for res in resrefs:
        trav = os.path.join(racine, res)
        rap = lit_json(os.path.join(trav, 'controle', 'rapport.json'))
        f = FICHES.get(res, {})
        nom = f.get('fr', res)
        if not rap:
            lignes.append('<tr><th scope="row">%s</th><td class="m">%s</td><td colspan="6" class="att">pas encore '
                          'fini</td></tr>' % (e(nom.capitalize()), e(res)))
            continue
        m = rap['mesures']
        al = rap.get('alertes', [])
        etat = '<span class="pill ok">sans alerte</span>' if not al else \
            '<span class="pill warn">%d alerte%s</span>' % (len(al), 's' if len(al) > 1 else '')
        lignes.append(
            '<tr><th scope="row"><a href="#%s">%s</a></th><td class="m">%s</td><td class="n">%+.1f %%</td>'
            '<td class="n">%.3f / %.3f</td><td class="n">%s°</td><td class="n">%s</td><td class="n">%s</td>'
            '<td>%s</td></tr>' % (
                res.lower(), e(nom.capitalize()), e(res), m.get('ecart_taille_pct', 0.0),
                m.get('luminance_nouveau', 0), m.get('luminance_original', 0), e(m.get('posture_globale_deg')),
                e(m.get('recouvrement_ombre')), e(m.get('sc_verify_erreurs')), etat))
        gifs, dessin = apercus(res, trav, adir)
        seq_l = []
        for s, x in rap['sequences'].items():
            if x.get('copie_de'):
                quoi = 'mêmes images que %s' % x['copie_de']
            elif x.get('repris_de'):
                quoi = 'pose reprise de %s' % x['repris_de']
            else:
                quoi = (x.get('clip') or '').replace('_', ' ')
            cout = x.get('cout_silhouette')
            seq_l.append('<tr><td class="m">%s</td><td>%s</td><td>%s</td><td class="n">%s</td><td class="n">%s</td></tr>' % (
                e(s), e(NOMS_SEQ.get(s, '')), e(quoi), e(x.get('images', '')),
                '%.2f' % cout if isinstance(cout, (int, float)) else ''))
        figs = ''.join('<figure><img src="a/%s" alt="%s, %s : original et nouveau" loading="lazy" width="560">'
                       '<figcaption>%s</figcaption></figure>' % (e(g), e(nom), e(NOMS_SEQ.get(s, s)),
                                                                 e(NOMS_SEQ.get(s, s).capitalize()))
                       for s, g in gifs)
        des = ('<figure class="dessin"><img src="a/%s" alt="Dessin de référence : %s" loading="lazy">'
               '<figcaption>Dessin de référence</figcaption></figure>' % (e(dessin), e(nom))) if dessin else ''
        alertes = ''.join('<li>%s</li>' % e(a) for a in al) or '<li>Aucune.</li>'
        teinte = ', '.join('%s %s' % (k, v) for k, v in (m.get('ecart_teinte_lab') or {}).items())
        cartes.append('''
<section class="entree" id="%(id)s">
  <header class="tete">
    <h2>%(nom)s</h2>
    <p class="meta"><span class="m">%(res)s</span> · animation <span class="m">0x%(ini)s</span> · %(en)s ·
       mouvements de type %(arch)s</p>
  </header>
  <div class="vues">%(figs)s%(des)s</div>
  <div class="details">
    <dl class="mesures">
      <div><dt>Hauteur</dt><dd>%(h)s px pour %(ho)s px</dd></div>
      <div><dt>Luminance</dt><dd>%(l)s pour %(lo)s</dd></div>
      <div><dt>Teinte (écart Lab)</dt><dd>%(teinte)s</dd></div>
      <div><dt>Ombre au sol</dt><dd>soleil %(az)s°, %(el)s° de haut</dd></div>
      <div><dt>Images HD vérifiées</dt><dd>%(hd)s, %(err)s erreur</dd></div>
    </dl>
    <div class="seqs"><table><caption>Mouvements choisis (coût : 1 - recouvrement des silhouettes)</caption>
      <thead><tr><th scope="col">Séq.</th><th scope="col">Action</th><th scope="col">Capture</th>
      <th scope="col">Images</th><th scope="col">Coût</th></tr></thead><tbody>%(seq)s</tbody></table></div>
    <div class="alertes"><h3>Alertes</h3><ul>%(alertes)s</ul></div>
  </div>
</section>''' % dict(id=res.lower(), nom=e(nom.capitalize()), res=e(res), ini=INI.get(res, '?'),
                     en=e(f.get('en', '')), arch=e(ARCH.get(f.get('archetype'), f.get('archetype', ''))),
                     figs=figs, des=des, h=e(m.get('hauteur_px_nouveau')), ho=e(m.get('hauteur_px_original')),
                     l=e(m.get('luminance_nouveau')), lo=e(m.get('luminance_original')), teinte=e(teinte),
                     az=e((m.get('ombre') or {}).get('az_deg')), el=e((m.get('ombre') or {}).get('el_deg')),
                     hd=e(m.get('sc_verify_images_hd')), err=e(m.get('sc_verify_erreurs')),
                     seq=''.join(seq_l), alertes=alertes))
    gabarit = open(os.path.join(ICI, 'revue_gabarit.html')).read()
    page = gabarit.replace('{{LIGNES}}', '\n'.join(lignes)).replace('{{CARTES}}', '\n'.join(cartes)) \
        .replace('{{N}}', str(len(resrefs)))
    open(os.path.join(sortie, 'index.html'), 'w').write(page)
    print('revue :', os.path.join(sortie, 'index.html'), len(os.listdir(adir)), 'fichiers')


if __name__ == '__main__':
    main()
