#!/usr/bin/env python3
"""Banc des espaces en SMB : les faits dont le modèle dépend, prouvés sur le vrai Samba de l'image du dépôt.

Ne fait pas partie de la découverte unittest : il lui faut Docker. Tout est isolé : un dossier temporaire, un réseau
Docker sans port publié, des conteneurs et un volume au nom du banc, retirés à la fin. Aucun service réel n'est touché.

    python3 tests/integration_spaces_smb.py

Le dossier temporaire est créé sous le dossier personnel : un démon Docker ne voit pas toujours /tmp.
"""
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
NAME = 'nacre-banc-espaces-smb'
SERVER, NETWORK, VOLUME, IMAGE = NAME + '-srv', NAME + '-net', NAME + '-etat', NAME
PEOPLE = {'camille': 2001, 'bruno': 2002, 'dora': 2003}   # comptes fictifs
TEAM, MINE = 'chantier-ecole', 'perso-camille'

GLOBAL = '''[global]
server role = standalone server
workgroup = WORKGROUP
security = user
map to guest = never
server min protocol = SMB2
smb ports = 445
disable netbios = yes
load printers = no
printing = bsd
printcap name = /dev/null
log file = /dev/stdout
max log size = 0
follow symlinks = no
wide links = no
invalid users = root
veto files = /.nacre-*/
delete veto files = no
access based share enum = yes
restrict anonymous = 2
'''


def share(name, folder, readers, writers):
    """Un espace : vu et ouvert par ses seuls ayants droit, en lecture sauf pour ceux qui y écrivent, tout sous le compte de la console."""
    return (f'\n[{name}]\npath = /shares/espaces/{folder}\nvalid users = {" ".join(readers)}\nread only = yes\nwrite list = {" ".join(writers)}\n'
            'force user = nas\nforce group = nas\ncreate mask = 0660\ndirectory mask = 2770\n')


def docker(*args, data=None, check=True):
    done = subprocess.run(('docker',) + args, input=data, capture_output=True, text=True, timeout=300)
    if check and done.returncode:
        raise RuntimeError('docker ' + ' '.join(args[:3]) + ' : ' + done.stderr.strip()[-300:])
    return done.stdout + done.stderr


def client(command):
    return docker('run', '--rm', '--network', NETWORK, '--entrypoint', 'sh', IMAGE, '-c', command, check=False)


def smb(name, who, commands):
    return client(f"cd /tmp; echo essai > a.txt; smbclient '//{SERVER}/{name}' -U {who}%{password(who)} -m SMB3 -c '{commands}' 2>&1")


def password(who):
    return 'essai-de-banc-' + who   # visiblement factice


def session(name, who, first='ls', second='ls'):
    """Session gardée ouverte : une commande tout de suite, une autre sept secondes plus tard. Rend le nom du conteneur."""
    box = NAME + '-cli-' + who
    docker('rm', '-f', box, check=False)
    docker('run', '-d', '--name', box, '--network', NETWORK, '--entrypoint', 'sh', IMAGE, '-c',
           f"cd /tmp; echo essai > a.txt; (echo '{first}'; sleep 7; echo '{second}'; sleep 2) | smbclient '//{SERVER}/{name}' -U {who}%{password(who)} -m SMB3 2>&1")
    time.sleep(2)
    return box


def outcome(box):
    time.sleep(9)
    text = docker('logs', box, check=False)
    docker('rm', '-f', box, check=False)
    return text.count('blocks of size'), 'NT_STATUS_NETWORK_NAME_DELETED' in text, text


def start(root):
    docker('rm', '-f', SERVER, check=False)
    docker('run', '-d', '--name', SERVER, '--network', NETWORK, '-v', f'{root}/data/espaces:/shares/espaces', '-v', f'{root}/data/fichiers:/shares/fichiers',
           '-v', f'{root}/state/samba:/etc/nas-autonome:ro', '-v', f'{root}/state/smb_password:/run/secrets/smb_password:ro', '-v', f'{VOLUME}:/var/lib/samba', IMAGE)
    for _ in range(40):
        if 'PONG' in docker('exec', SERVER, 'smbcontrol', 'smbd', 'ping', check=False):
            return
        time.sleep(.25)
    raise RuntimeError('Samba ne répond pas : ' + docker('logs', SERVER, check=False)[-300:])


def apply(root, text, close=()):
    """Comme la console : écrire, recharger, puis fermer les partages changés (un rechargement seul ne révoque rien)."""
    (root / 'state/samba/smb.conf').write_text(text)
    docker('exec', SERVER, 'smbcontrol', 'all', 'reload-config')
    for name in close:
        docker('exec', SERVER, 'smbcontrol', 'all', 'close-share', name)


def main():
    results, failed = {}, []

    def check(key, value, expected=True):
        results[key] = value
        if value != expected:
            failed.append(key)

    root = Path(tempfile.mkdtemp(prefix='nacre-banc-smb-', dir=Path.home()))
    try:
        for path in ('data/fichiers', 'data/espaces/aaaaaaaaaaaa/.nacre-trash', 'data/espaces/aaaaaaaaaaaa/.nacre-versions', 'data/espaces/bbbbbbbbbbbb', 'state/samba'):
            (root / path).mkdir(parents=True)
        (root / 'data/espaces/aaaaaaaaaaaa/perso.txt').write_text('perso')
        (root / 'data/espaces/aaaaaaaaaaaa/.nacre-trash/jete').write_text('en corbeille')
        (root / 'data/espaces/bbbbbbbbbbbb/equipe.txt').write_text('equipe')
        for space in ('aaaaaaaaaaaa', 'bbbbbbbbbbbb'):
            (root / 'data/espaces' / space).chmod(0o2770)
        (root / 'data/espaces').chmod(0o700)   # comme dans le produit : seul le compte de la console traverse
        (root / 'state/smb_password').write_text('essai-de-banc-nas\n')
        (root / 'state/samba/users.tsv').write_text(''.join(f'{name}\t{uid}\n' for name, uid in PEOPLE.items()))
        full = GLOBAL + share(MINE, 'aaaaaaaaaaaa', ['camille'], ['camille']) + share(TEAM, 'bbbbbbbbbbbb', ['camille', 'bruno'], ['camille'])
        (root / 'state/samba/smb.conf').write_text(full)
        import os
        docker('build', '-q', '--build-arg', f'NAS_UID={os.getuid()}', '--build-arg', f'NAS_GID={os.getgid()}', '-t', IMAGE, str(REPO / 'samba'))
        docker('network', 'create', NETWORK, check=False)
        docker('volume', 'rm', '-f', VOLUME, check=False)
        start(root)
        results['samba'] = docker('exec', SERVER, 'smbd', '--version').strip()
        for name in PEOPLE:
            docker('exec', '-i', SERVER, 'smbpasswd', '-s', '-a', name, data=password(name) + '\n' + password(name) + '\n')

        # 1. Chacun ne voit et n'ouvre que ses espaces ; un lecteur lit sans écrire.
        seen = lambda who: sorted(line.split()[0] for line in client(f"smbclient -L //{SERVER} -U {who}%{password(who)} -m SMB3 2>&1").splitlines() if ' Disk ' in line)
        check('partages_vus', {who: seen(who) for who in PEOPLE}, {'camille': [TEAM, MINE], 'bruno': [TEAM], 'dora': []})
        check('anonyme_refuse', 'NT_STATUS_ACCESS_DENIED' in client(f"smbclient '//{SERVER}/{TEAM}' -N -m SMB3 -c ls 2>&1"))
        check('ecrivain_ecrit', 'NT_STATUS' not in smb(TEAM, 'camille', 'put a.txt de-camille.txt'))
        check('lecteur_lit', 'getting file' in smb(TEAM, 'bruno', 'get equipe.txt lu.txt'))
        check('lecteur_n_ecrit_pas', 'NT_STATUS_ACCESS_DENIED' in smb(TEAM, 'bruno', 'put a.txt de-bruno.txt'))
        check('espace_personnel_ferme_aux_autres', 'NT_STATUS_ACCESS_DENIED' in smb(MINE, 'bruno', 'ls'))
        check('espace_ferme_a_qui_n_y_est_pas', 'NT_STATUS_ACCESS_DENIED' in smb(TEAM, 'dora', 'ls'))
        # 2. Les dossiers internes ne se voient pas, ne se lisent pas, ne se créent pas.
        check('internes_invisibles', '.nacre' not in smb(MINE, 'camille', 'ls'))
        check('corbeille_illisible', 'NT_STATUS_OBJECT' in smb(MINE, 'camille', 'get .nacre-trash/jete lu.txt'))
        check('nom_interne_refuse', 'NT_STATUS_OBJECT' in smb(MINE, 'camille', 'put a.txt .nacre-upload-x') and not (root / 'data/espaces/aaaaaaaaaaaa/.nacre-upload-x').exists())
        # 3. Ce que SMB écrit appartient au compte de la console, qui peut donc tout en faire ensuite.
        made = (root / 'data/espaces/bbbbbbbbbbbb/de-camille.txt').stat()
        check('proprietaire_console', (made.st_uid, made.st_gid, oct(made.st_mode & 0o777)), (os.getuid(), os.getgid(), '0o660'))
        # 4. Un accès retiré : le rechargement seul laisse la connexion ouverte ; fermer le partage la coupe, et elle ne revient pas.
        box = session(TEAM, 'bruno')
        without = GLOBAL + share(MINE, 'aaaaaaaaaaaa', ['camille'], ['camille']) + share(TEAM, 'bbbbbbbbbbbb', ['camille'], ['camille'])
        apply(root, without)
        lists, cut, _ = outcome(box)
        check('rechargement_seul_ne_revoque_pas', (lists, cut), (2, False))
        apply(root, full)
        box = session(TEAM, 'bruno')
        apply(root, without, close=[TEAM])
        lists, cut, _ = outcome(box)
        check('fermeture_du_partage_revoque', (lists, cut), (1, True))
        check('pas_de_retour', 'NT_STATUS_ACCESS_DENIED' in smb(TEAM, 'bruno', 'ls'))
        # 5. Écriture retirée pendant une session : le dépôt suivant ne passe pas.
        apply(root, full)
        box = session(TEAM, 'camille', 'put a.txt avant.txt', 'put a.txt apres.txt')
        apply(root, GLOBAL + share(MINE, 'aaaaaaaaaaaa', ['camille'], ['camille']) + share(TEAM, 'bbbbbbbbbbbb', ['camille', 'bruno'], []), close=[TEAM])
        outcome(box)
        check('ecriture_retiree', sorted(p.name for p in (root / 'data/espaces/bbbbbbbbbbbb').iterdir() if p.name in ('avant.txt', 'apres.txt')), ['avant.txt'])
        # 6. Désactiver un compte ne coupe PAS sa session ouverte : il faut aussi fermer ses partages. Une nouvelle connexion, elle, est refusée.
        apply(root, full)
        box = session(TEAM, 'bruno')
        docker('exec', SERVER, 'smbpasswd', '-d', 'bruno')
        lists, cut, _ = outcome(box)
        check('desactivation_seule_ne_coupe_pas', (lists, cut), (2, False))
        check('compte_desactive_refuse', 'NT_STATUS_ACCOUNT_DISABLED' in smb(TEAM, 'bruno', 'ls'))
        docker('exec', SERVER, 'smbpasswd', '-e', 'bruno')
        # 7. Fermer « ce qui est refusé » coupe tout le monde quand le partage force un compte : pas plus fin que fermer le partage.
        box, other = session(TEAM, 'bruno'), session(TEAM, 'camille')
        (root / 'state/samba/smb.conf').write_text(without)
        docker('exec', SERVER, 'smbcontrol', 'all', 'reload-config')
        docker('exec', SERVER, 'smbcontrol', 'all', 'close-denied-share', '*')
        _, cut, _ = outcome(box)
        _, kept_cut, _ = outcome(other)
        results['close_denied_share'] = {'retire_coupe': cut, 'ayant_droit_coupe_aussi': kept_cut}   # constat, pas une exigence
        # 8. Les mots de passe survivent à une recréation du conteneur, par le volume de /var/lib/samba.
        apply(root, full)
        start(root)
        check('mot_de_passe_apres_recreation', 'getting file' in smb(TEAM, 'camille', 'get equipe.txt lu.txt'))
    finally:
        for box in [SERVER] + [NAME + '-cli-' + who for who in PEOPLE]:
            docker('rm', '-f', box, check=False)
        docker('volume', 'rm', '-f', VOLUME, check=False)
        docker('network', 'rm', NETWORK, check=False)
        docker('rmi', '-f', IMAGE, check=False)
        shutil.rmtree(root, ignore_errors=True)
    print(json.dumps({'ok': not failed, 'echecs': failed, **results}, ensure_ascii=False, indent=1))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
