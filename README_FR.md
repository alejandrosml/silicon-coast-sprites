# Silicon Coast — sprites HD

**Des créatures HD dans Baldur's Gate II : EE sur Mac, affichées à leur taille et à leur place d'origine, sans DLL ni
EEex : uniquement des BAM et cinq shaders dans `override`.**

État au 27/10/2026 :

- **Toutes les familles d'animation de créatures** de BG2:EE sont prises en charge : personnages équipés, monstres à
  calques, grands monstres, wyvernes, dragons, Démogorgon, animaux…
- **Les 10 284 fichiers d'animation de créatures que le moteur charge** sont convertis et vérifiés par le calcul,
  image par image. La liste vient de l'émulation des constructeurs d'animation, fichiers INI compris.
- **Un seul test en jeu** a suffi : une sauvegarde de test réunit une créature de chaque famille sur un même écran.
  Tout s'affiche en HD, à sa place, sans aucun défaut visible.
- Les images HD actuelles viennent de Scale4x (démonstration). Le format est prêt pour de vraies images HD : upscale
  IA (bg2hd et ses sous-teintes), ou rendus 3D.

Spécification en anglais pour les autres développeurs : `FORMAT.md`. Présentation en anglais : `README.md`.

---

## Le test en jeu n° 3 : toutes les familles sur un écran (26/10/2026)

Sauvegarde de test « Silicon Coast scene » : une copie de « Chapter 1 Start » où 22 créatures, une par famille, sont
réunies dans la grande salle d'AR0602, autour du groupe (Abdel équipé).

| Vérification | Résultat |
|---|---|
| Les 5 shaders compilent sur l'OpenGL d'Apple : menus, interface, décor, films | ✅ |
| Dragon rouge (9 tuiles), Démogorgon (4 parties), wyverne (4 quarts) : la disposition « F » | ✅ HD, sans couture entre les tuiles ; le dragon est coupé proprement par le bord de la vue |
| Personnages équipés : humaine en plates (casque, bouclier, épée), elfe (arc), nain (marteau, bouclier, casque), halfelin (dague), humain en plates (épée à deux mains) | ✅ les quatre calques en HD, dans le bon ordre |
| Moine (ancien type de personnage, avec ombre), sahuagin (lance), hobgobelin (épée), sirène (arc), squelette (hache), goule, ogre, wyverne volante, vache, aigle | ✅ |
| Créatures derrière des murs (l'arbre, les rochers) | ✅ atténuées comme les originales |
| Directions en miroir, groupe qui marche, zoom avant et arrière | ✅ |
| Cadre brut, repères ou lignes visibles | ✅ aucun |
| Sauvegardes du joueur | ✅ aucune n'a été modifiée |

Captures : `docs/ingame-*.jpg`.

**Ce que ce test a coûté :** un seul lancement du jeu. Tout le reste a été vérifié avant, hors ligne.

Un détail du premier chargement : les créatures étaient couchées, mortes. Le modèle de créature venait d'un voleur
mort de la scène d'ouverture. Le script de la sauvegarde remet maintenant leur état et leurs points de vie ; ce n'était
pas un problème des sprites.

### Les tests précédents

- **Test 1 :** Abdel seul, converti en ×4 (créature seule, barreaux de cage, pause, miroir, zoom). ✅
- **Test 2 :** Abdel équipé (corps + hache + bouclier + casque). ✅

---

## Le problème

Le moteur ne sait pas afficher un sprite plus fin que 1 texel = 1 pixel du monde.

- **Un BAM ×4 tel quel** s'affiche 4 fois trop grand.
- **Les murs tomberaient au mauvais endroit.** Le moteur les applique sur le processeur, à l'échelle 1:1, dans la
  surface FX de la créature.
- **Un BAM V2 fait planter le moteur** dans ce chemin : sa palette est nulle.

## Le principe

Chaque image d'animation garde l'échelle du moteur et contient trois choses :

1. **Des repères**, que les shaders lisent pour reconnaître l'image et ses paramètres ;
2. **un bloc-sonde** : un rectangle opaque exactement là où était le sprite d'origine. Le moteur y applique les murs,
   la transparence et la sélection au bon endroit ;
3. **l'image HD** (k fois plus grande, mêmes indices de palette, donc mêmes couleurs de personnage, teintes, gris de
   la pause et ombres).

Le moteur compose cette image comme d'habitude. Les shaders font le reste :

- **`VPDRAW.GLSL`** reconnaît l'image et ramène le quad sur le bloc-sonde (taille et place d'origine) ;
- **`FPDRAW.GLSL`** (et `FPTONE`, `FPSPRITE`, `FPSELECT`) affiche l'image HD réduite k fois, multipliée par l'effet
  des murs lu dans le bloc-sonde ;
- **pour tout le reste,** ces shaders exécutent le code d'origine de Beamdog, inchangé.

### Deux dispositions, selon le chemin de dessin du moteur

Toutes deux ont été trouvées dans le binaire (BG2:EE 2.7.3, arm64), pas par essais en jeu.

- **Disposition « v2 » (spines)** pour les créatures dessinées par `FXBltFromClipped` : personnages, monstres,
  animaux… Deux colonnes-repères de 60 texels, à gauche et à droite. Le quad couvre toute l'image, ses coins tombent
  sur les spines.
- **Disposition « F » (lignes spéciales)** pour les créatures dessinées par `FXBltFrom` : wyvernes, dragons,
  Démogorgon. Ici le quad est découpé au bord de la vue, et deux images voisines dans l'atlas partagent leurs coins :
  aucun shader de sommets ne peut savoir à quelle image appartient un coin. Une ligne sur 8 porte donc des blocs de
  repères sur toute la largeur, et c'est le shader de fragments qui décode l'image, pixel par pixel.

### Les calques : une géométrie commune

Un personnage est dessiné en **une seule surface FX** : le corps, puis le casque, le bouclier et l'arme. Le moteur
prend pour rectangle l'union des calques. Tous les calques d'une même surface reçoivent donc **la même géométrie**,
calculée sur tous les fichiers concernés :

| Famille | Calques dans une surface | Géométrie commune |
|---|---|---|
| Personnages | corps + arme + bouclier + casque (classes de taille L, N, M, S) | par cycle et par image |
| Anciens personnages (moine…) | corps + ombre + armes | par cycle |
| Monstres, Icewind, monstres à calques | corps + armes (+ lueur) | par cycle |
| Autres familles | un seul calque | boîte serrée de chaque image |
| Wyvernes, dragons, Démogorgon | une tuile par surface | boîte serrée de chaque image |

Les wyvernes (2×2), les dragons (3×3) et le Démogorgon (2×2) sont des images **découpées en tuiles jointives**. Le
convertisseur agrandit chaque tuile avec une bordure prise dans ses voisines, sinon les jointures se verraient.

## Vérifié et corrigé le 27/10 : la liste exacte des fichiers

Chaque animation du jeu est définie par un fichier INI (`7F3B.INI`…) que le constructeur lit au démarrage
(`Unmarshal`) : c'est lui qui donne les noms des fichiers chargés. La première émulation des constructeurs sautait
cette lecture : 135 animations prenaient alors les valeurs de secours du code (le sanglier d'Icewind Dale chargeait
les fichiers du myconide, par exemple). Refaite avec les INI lus comme le moteur les lit :

- **24 fichiers de plus** à convertir (le sanglier, `MBOA`) ;
- **10 fichiers d'ombre** (`SSHD`, que le code de secours donnait à Sarevok) que plus aucune animation ne charge ;
- **une géométrie commune plus petite** pour les calques des anciens personnages (moine…) : 1 774 fichiers
  reconvertis, dont les 54 de la sauvegarde de test, réinstallés dans la copie du jeu et revérifiés. Leurs images
  perdent seulement une marge vide ;
- les fichiers `MSOL`, `MASL` et `MDJC`, qui manquaient, ne sont en fait chargés par aucune animation : les INI
  utilisent `MSOG`, `MASG` et `MDJL`.

Au total, 10 284 fichiers dans les 17 familles de créatures, tous vérifiés par le calcul, sans erreur. Détail par
famille, et liste des fichiers laissés de côté : `docs/COVERAGE.md` (en anglais).

## Ce qui a été trouvé et corrigé le 26/10 (hors ligne, avant le test en jeu)

- **Contours de sprites en miroir.** Avec les contours, le quad est découpé de façon asymétrique, et le miroir échange
  les deux écarts. Le shader de sommets ne retrouvait pas l'image : il dessinait le cadre brut. Corrigé.
- **Lignes fines au bord des wyvernes et des dragons.** Les dérivées du shader de fragments étaient calculées après
  des branchements, donc indéfinies au bord du bloc-sonde. Elles sont maintenant prises au début du shader. Corrigé.
- **Murs « effacer » sur une spine entière.** Les sommets de l'autre côté ne trouvaient plus l'image. Une deuxième
  passe accepte une ligne confirmée par une autre ligne de la même spine, et un sommet qui ne trouve rien garde sa
  place sans perturber les autres (valeurs pondérées). Corrigé.
- **Atlas plein.** Le simulateur vide maintenant l'atlas comme le moteur (`DrawLockSurface`), pour tester des scènes
  chargées.

## Vérifications hors ligne

Le banc de test simule le chemin des créatures comme le binaire le fait (palette, surface FX, union des calques, atlas,
murs, quad, `aRef`, découpe à la vue), puis rend les scènes dans WebGL avec les vrais shaders.

| Test | Résultat |
|---|---|
| Scène avec une créature de chaque famille : sans murs, murs « atténuer », transparence, teinte, gris, contours, zoom ×2 | ✅ silhouette HD ≈ originale pour chaque famille (IoU ≥ 0,87, moyenne ≥ 0,95), aucun texel parasite |
| Tout ce qui n'est pas SC-HD, avec les nouveaux shaders | ✅ pixels identiques aux shaders d'origine |
| Disposition F : découpe à la vue sur chaque bord et coin, images voisines dans l'atlas, miroir, murs, palettes, contours | ✅ IoU ≥ 0,94 ; rien hors de la vue ; texel pour texel au zoom ×4 |
| Sous-teintes de bg2hd (formule Q3M), deux dispositions, teinte et gris | ✅ pixel pour pixel |
| Murs réels de BG2 (AR0602, AR0700), « Always Dither » activé | ✅ atténuation identique à l'original |
| Personnages équipés : 48 images × 3 zooms, 8 directions, miroir, 6 équipements | ✅ |
| Vérification par le calcul de chaque image de chaque fichier (10 284 fichiers, 5 492 738 positions d'image) | ✅ 0 erreur |

## Limites connues

- **Garder « Always Dither » activé** (options de jeu ; c'est le réglage par défaut, et ton jeu l'a). Sinon les murs
  effacent au lieu d'atténuer : trous dans le sprite HD, et cadre brut possible pour une créature encadrée par deux
  pans de mur.
- **Coût :** processeur et mémoire croissent avec k². Disque : environ 6 fois les BAM d'origine en ×4. Le temps par
  image n'a pas encore été mesuré en jeu.
- **Barre de vie au-dessus de la tête :** elle apparaît plus haut (le moteur prend la hauteur de l'image).
- **Animations d'effets** (22 identifiants : cercles de feu, morceaux, sang, glyphes…) : non converties.
- **Les cinq shaders vont ensemble.** Ils remplacent les mêmes fichiers que les packs de shaders existants.
- **Scale4x n'ajoute aucun détail :** il prouve le pipeline. Le gain réel viendra d'images HD dessinées, générées par
  IA ou re-rendues en 3D, converties par la même commande.

## Utilisation

```sh
# 1. conversion (Scale4x de démonstration ; k choisi image par image, 4 au plus)
python3 tools/sc_convert.py build <BAM d'origine> tables/groups.json tables/canon_all.json <sortie> -j 8
#    avec de vraies images HD (mêmes noms et cycles, images k fois plus grandes, centre k·(cx, cy), mêmes indices)
python3 tools/sc_convert.py build <BAM d'origine> tables/groups.json tables/canon_all.json <sortie> --hd <BAM HD> [--sub <BAM F>]

# 2. vérification par le calcul
python3 tools/sc_verify.py <BAM d'origine> <sortie> tables/groups.json tables/canon_all.json -j 8

# 3. installation : les 5 shaders et les BAM convertis dans le dossier override du jeu
```

Les fichiers qui partagent une surface (un corps et tous les équipements de sa classe de taille, un monstre et ses
armes) se convertissent ensemble : un corps HD avec une arme d'origine, ou l'inverse, s'afficherait mal.

**La scène de test** se refait en deux commandes (dossier `scene/`) : `install_scene.sh convert` puis
`install_scene.sh install`, et `mkscene2.py scene_cast.json` crée la sauvegarde « Silicon Coast scene » (copie de
« Chapter 1 Start » ; aucune autre sauvegarde n'est touchée).
