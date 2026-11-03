# hub.py - Silicon Coast, chaîne des monstres 3D : échanges avec le dépôt privé Hugging Face (dataset), qui relie
# la session qui prépare (code, données du jeu, captures) et les sessions qui calculent (un monstre chacune).
#
#   python3 hub.py test                                   accès au dépôt (lecture)
#   python3 hub.py prendre <chemin distant> <dossier local>   un fichier ou un dossier (motif « dossier/ »)
#   python3 hub.py poser <fichier ou dossier local> <chemin distant> [message] [--sauf=motif,motif]
#
# Dépôt : SC_HUB (défaut aisml/silicon-coast-3d, type dataset). Authentification : secret réseau de l'environnement
# cloud (le proxy ajoute l'en-tête) ou variable HF_TOKEN ; la clé n'est jamais écrite dans un fichier.
import os
import sys

DEPOT = os.environ.get('SC_HUB', 'aisml/silicon-coast-3d')
TOKEN = os.environ.get('HF_TOKEN') or None


def api():
    from huggingface_hub import HfApi
    return HfApi(token=TOKEN)


def test():
    a = api()
    info = a.dataset_info(DEPOT)
    print('dépôt', DEPOT, 'accessible ; fichiers :', len(info.siblings or []))
    return 0


def prendre(distant, local):
    from huggingface_hub import hf_hub_download, snapshot_download
    os.makedirs(local, exist_ok=True)
    if distant.endswith('/'):
        p = snapshot_download(DEPOT, repo_type='dataset', allow_patterns=[distant + '**'], local_dir=local,
                              token=TOKEN)
    else:
        p = hf_hub_download(DEPOT, distant, repo_type='dataset', local_dir=local, token=TOKEN)
    print('reçu', distant, '->', p)
    return 0


def poser(local, distant, message=None, sauf=()):
    a = api()
    msg = message or ('chaîne monstres : ' + distant)
    if os.path.isdir(local):
        a.upload_folder(folder_path=local, path_in_repo=distant, repo_id=DEPOT, repo_type='dataset',
                        commit_message=msg, ignore_patterns=['*.tmp', '__pycache__/*', '*.blend1'] + list(sauf))
    else:
        a.upload_file(path_or_fileobj=local, path_in_repo=distant, repo_id=DEPOT, repo_type='dataset',
                      commit_message=msg)
    print('envoyé', local, '->', distant)
    return 0


if __name__ == '__main__':
    c = sys.argv[1]
    if c == 'test':
        sys.exit(test())
    if c == 'prendre':
        sys.exit(prendre(sys.argv[2], sys.argv[3]))
    if c == 'poser':
        r = [x for x in sys.argv[4:] if not x.startswith('--sauf=')]
        sauf = [m for x in sys.argv[4:] if x.startswith('--sauf=') for m in x[7:].split(',') if m]
        sys.exit(poser(sys.argv[2], sys.argv[3], r[0] if r else None, sauf))
    raise SystemExit(__doc__)
