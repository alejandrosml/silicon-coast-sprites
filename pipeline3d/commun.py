# commun.py - Silicon Coast, chaîne des monstres 3D : chemins, constantes et petits outils partagés.
import json
import os
import sys

ICI = os.path.dirname(os.path.abspath(__file__))
# dépôt silicon-coast-sprites (tools/bam.py, sc_convert.py, sc_verify.py, tables/)
SPRITES = os.environ.get('SC_SPRITES', '/home/claude/silicon-coast-sprites')
sys.path.insert(0, os.path.join(SPRITES, 'tools'))
# BAM d'origine du jeu (BG2:EE) : un dossier avec les fichiers <RESREF><suffixe>.BAM
SRC = os.environ.get('SC_SRC', '/tmp/claude-0/-home-claude/d60ccd02-a06d-5f16-8e4c-eec21888b8b3/scratchpad/all/src')
BLENDER = os.environ.get('SC_BLENDER', '/tmp/claude-0/-home-claude/d60ccd02-a06d-5f16-8e4c-eec21888b8b3/scratchpad/'
                                       'blender/blender-5.2.3-linux-x64/blender')
MOCAP = os.environ.get("SC_MOCAP", "/tmp/claude-0/-home-claude/d60ccd02-a06d-5f16-8e4c-eec21888b8b3/scratchpad/mocap/lib")

# Type d'animation 7000 (« monster »), split_bams=1 : un fichier par séquence (IESDP, ini_anim)
#   séquence -> (suffixe du fichier, indice de la séquence dans le fichier : cycles 9*s à 9*s+8)
SEQ_7000 = {'WK': ('G11', 0), 'SC': ('G1', 1), 'SD': ('G12', 2), 'GH': ('G13', 3), 'DE': ('G14', 4), 'TW': ('G15', 5),
            'A1': ('G2', 0), 'A2': ('G21', 1), 'A3': ('G22', 2), 'A4': ('G23', 3), 'A5': ('G24', 4), 'SP': ('G25', 5),
            'CA': ('G26', 6)}
NOMS_SEQ = {'WK': 'marche', 'SC': 'garde', 'SD': 'attente', 'GH': 'coup reçu', 'DE': 'mort', 'TW': 'au sol',
            'A1': 'attaque 1', 'A2': 'attaque 2', 'A3': 'attaque 3', 'A4': 'attaque 4', 'A5': 'attaque 5',
            'SP': 'incantation', 'CA': 'sort lancé'}
DIRS = 9                    # directions enregistrées : 0 S, 1 SSO, 2 SO, 3 OSO, 4 O, 5 ONO, 6 NO, 7 NNO, 8 N
# nombre d'images voulu par séquence (règles de fidélité, 5 : plus fluide que l'original ; la marche garde le compte
# d'origine, sinon les pieds glissent ; au sol : les images uniques de l'original)
IMAGES_CIBLES = {'SD': 32, 'SC': 32, 'GH': 16, 'DE': 24, 'A1': 24, 'A2': 24, 'A3': 24, 'A4': 24, 'A5': 24,
                 'SP': 24, 'CA': 24}
K = 4                       # facteur HD (SC-HD x4)


def lit_json(p, defaut=None):
    return json.load(open(p)) if os.path.exists(p) else defaut


def ecrit_json(p, d):
    os.makedirs(os.path.dirname(os.path.abspath(p)), exist_ok=True)
    tmp = p + '.tmp'
    json.dump(d, open(tmp, 'w'), indent=1, ensure_ascii=False)
    os.replace(tmp, p)
