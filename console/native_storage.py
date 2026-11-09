#!/usr/bin/env python3
"""Service natif optionnel. Aucune opération sur un volume non inscrit par root.

Le serveur web utilise uniquement NativeClient. Le daemon ne reçoit ni commande,
ni chemin de stockage : IDs de politique, IDs de points, action et confirmation.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import socketserver
import sqlite3
import stat
import struct
import subprocess
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parent))
if __name__ == '__main__':
    sys.modules['native_storage'] = sys.modules[__name__]

SOCKET = '/run/nacre-storage/control.sock'
POLICY = '/etc/nacre-storage/policy.json'
STATE = '/var/lib/nacre-storage'
ID = re.compile(r'[a-z][a-z0-9_-]{0,47}\Z')
DATASET = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:/-]*\Z')
LV = re.compile(r'[A-Za-z0-9_+][A-Za-z0-9_.+-]*/[A-Za-z0-9_+][A-Za-z0-9_.+-]*\Z')
MAX_MESSAGE = 65536


class NativeError(ValueError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def execute(argv, pass_fds=()):
    """Environnement fixe ; chemins des exécutables résolus hors de l'API web."""
    binary = shutil.which(argv[0], path='/usr/sbin:/usr/bin:/sbin:/bin')
    if not binary:
        raise NativeError('Outil système absent : ' + argv[0])
    try:
        result = subprocess.run([binary, *argv[1:]], capture_output=True, text=True,
                                timeout=45, pass_fds=pass_fds,
                                env={'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C'})
    except subprocess.TimeoutExpired:
        raise NativeError('Délai dépassé. Vérifier le stockage avant de réessayer.') from None
    if result.returncode:
        # Le journal root conserve le détail ; aucune sortie brute dans le navigateur.
        print(canonical({'command': argv[0], 'code': result.returncode,
                         'detail': result.stderr[-2000:]}), flush=True)
        raise NativeError('Le système a refusé l’opération ' + argv[0] + '.')
    return result.stdout


@contextmanager
def trusted_directory(path):
    """Pin par FD, sans symlink. Parents non modifiables par l'application.

    Le dernier dossier peut contenir des données utilisateur ; son parent doit
    rester root et non inscriptible par le groupe/autres, empêchant son renommage.
    """
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts or str(path) == '/':
        raise NativeError('Racine de stockage invalide.')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in path.parts[1:]:
            meta = os.fstat(fd)
            if meta.st_uid != 0 or meta.st_mode & 0o022:
                raise NativeError('Un parent du volume est modifiable hors du service système.')
            next_fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        yield fd
    finally:
        os.close(fd)


def private_directory(path):
    with trusted_directory(path) as fd:
        meta = os.fstat(fd)
        if meta.st_uid != 0 or meta.st_mode & 0o022:
            raise NativeError('Le dossier géré doit appartenir à root sans écriture groupe/autres.')


def read_policy(path=POLICY):
    # O_NOFOLLOW sur tout le chemin, et politique immutable par le serveur web.
    path = Path(path)
    with trusted_directory(path.parent) as directory:
        meta = os.fstat(directory)
        if meta.st_uid != 0 or meta.st_mode & 0o022:
            raise NativeError('Répertoire de politique non protégé.')
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
        with os.fdopen(fd) as file:
            meta = os.fstat(file.fileno())
            if not stat.S_ISREG(meta.st_mode) or meta.st_uid != 0 or meta.st_mode & 0o022:
                raise NativeError('Politique non protégée par root.')
            raw = file.read(MAX_MESSAGE + 1)
    if len(raw) > MAX_MESSAGE:
        raise NativeError('Politique trop volumineuse.')
    policy = json.loads(raw)
    if policy.get('version') != 1 or type(policy.get('allowed_uid')) is not int or policy['allowed_uid'] <= 0 or not isinstance(policy.get('volumes'), list):
        raise NativeError('Politique invalide.')
    seen = set()
    for volume in policy.get('volumes', []):
        if not ID.fullmatch(volume['id']) or volume['id'] in seen or volume['family'] not in ('btrfs', 'zfs', 'lvm'):
            raise NativeError('Volume de politique invalide.')
        seen.add(volume['id'])
    return policy


class Engine:
    def __init__(self, policy=POLICY, state=STATE, runner=execute, recover=True):
        self.policy_path, self.state, self.run = Path(policy), Path(state), runner
        private_directory(self.state)
        self.db = sqlite3.connect(self.state / 'catalog.db')
        self.db.row_factory = sqlite3.Row
        os.chmod(self.state / 'catalog.db', 0o600)
        self.db.executescript('''
CREATE TABLE IF NOT EXISTS plans (id TEXT PRIMARY KEY, uid INTEGER, actor TEXT, expires REAL, payload TEXT, consumed INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS points (id TEXT PRIMARY KEY, volume TEXT, family TEXT, created REAL, actor TEXT, status TEXT, object TEXT, identity TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS actions (id TEXT PRIMARY KEY, ts REAL, actor TEXT, action TEXT, volume TEXT, object TEXT, status TEXT);
''')
        if 'native_identity' not in {row['name'] for row in self.db.execute('PRAGMA table_info(points)')}:
            self.db.execute("ALTER TABLE points ADD COLUMN native_identity TEXT NOT NULL DEFAULT ''")
        if 'location' not in {row['name'] for row in self.db.execute('PRAGMA table_info(actions)')}:
            self.db.execute("ALTER TABLE actions ADD COLUMN location TEXT NOT NULL DEFAULT ''")
        if recover:
            self.restorations()
            self.provisioning()
            with self.db:
                self.db.execute("UPDATE points SET status='uncertain', detail='Service interrompu pendant la création ; vérifier le stockage.' WHERE status='creating'")
                self.db.execute("UPDATE actions SET status='uncertain' WHERE status='running' AND id NOT IN (SELECT id FROM native_jobs WHERE status IN ('queued','running'))")
                self.db.execute("UPDATE deployments SET phase='uncertain',error='Service interrompu pendant l’initialisation. Vérifier le stockage ; aucun formatage ne sera rejoué.' WHERE phase='creating'")

    def policy(self):
        return read_policy(self.policy_path)

    def volume(self, identifier):
        for volume in self.policy().get('volumes', []) + self.provisioning().native_volumes():
            if volume['id'] == identifier:
                return volume
        raise NativeError('Volume non autorisé par la politique système.')

    def provisioning(self):
        from provisioning import Provisioning
        return Provisioning(self)

    def restorations(self):
        from native_restore import Restorations
        return Restorations(self)

    def resources(self):
        """Racines publiées pour lecture par le compte non privilégié de console."""
        resources=[]
        def expose(identifier,name,path,kind,filesystem_uuid=None,writable=False):
            meta=os.stat(path,follow_symlinks=False)
            if not stat.S_ISDIR(meta.st_mode):return
            resources.append({'id':identifier,'name':name,'path':str(path),'kind':kind,
                'filesystem_uuid':filesystem_uuid,'writable':writable,
                'identity':{'dev':meta.st_dev,'ino':meta.st_ino}})
        for row,record in self.provisioning().records():
            if row['phase']!='ready':continue
            try:
                self.provisioning().authorize(record);mount=self.provisioning().check_mount(record)
                expose(record['id'],record['name'],Path(record['mountpoint'])/'data','volume',record['fs_uuid'],
                       'ro' not in (mount.get('options') or '').split(','))
            except (NativeError,OSError,ValueError,KeyError):pass
        for row in self.db.execute("SELECT * FROM native_jobs WHERE status='done'"):
            try:
                options=json.loads(row['options']);volume=self.volume(options['volume']['id'])
                if volume!=options['volume']:continue
                expected=str(Path(volume['restore_directory'])/('restore_'+row['id']))
                private_directory(volume['restore_directory'])
                if expected==row['location']:
                    expose('restore-'+row['id'],'Restauration LVM '+row['id'][:8],expected,'restore')
            except (NativeError,OSError,ValueError,KeyError):pass
        for row in self.db.execute("SELECT * FROM actions WHERE action='clone' AND status='done'"):
            try:
                volume=self.volume(row['volume'])
                if volume['family']!='btrfs':continue
                with self.paths(volume) as fds:self.inspect(volume,fds,require_capacity=False)
                expected=str(Path(volume['restores'])/row['object'])
                if row['location']==expected and re.fullmatch(r'restore_[a-f0-9]{32}',row['object']):
                    expose('clone-'+row['id'],'Restauration Btrfs '+row['id'][:8],expected,'restore',volume['filesystem_uuid'])
            except (NativeError,OSError,ValueError,KeyError):pass
        return resources

    @contextmanager
    def paths(self, volume):
        if volume['family'] != 'btrfs':
            yield {}
            return
        from contextlib import ExitStack
        with ExitStack() as stack:
            descriptors = {}
            for field in ('source', 'snapshots', 'restores'):
                descriptors[field] = stack.enter_context(trusted_directory(volume[field]))
                if field != 'source':
                    meta = os.fstat(descriptors[field])
                    if meta.st_uid != 0 or meta.st_mode & 0o022:
                        raise NativeError('Destination native modifiable hors du service système.')
            # Btrfs attribue un st_dev différent à chaque sous-volume : comparer
            # l'UUID du FS, pas le numéro de périphérique synthétique de stat().
            for fd in descriptors.values():
                mount = json.loads(self.run(['findmnt', '-J', '-T', f'/proc/self/fd/{fd}/.', '-o', 'FSTYPE,UUID'], tuple(descriptors.values())))['filesystems'][0]
                if mount.get('fstype') != 'btrfs' or mount.get('uuid') != volume['filesystem_uuid']:
                    raise NativeError('Source et destinations Btrfs doivent être sur le même système de fichiers autorisé.')
            if len({(os.fstat(fd).st_dev, os.fstat(fd).st_ino) for fd in descriptors.values()}) != 3:
                raise NativeError('Source et destinations doivent être distinctes.')
            yield descriptors

    def inspect(self, volume, fds=None, require_capacity=True):
        family = volume['family']
        if family == 'btrfs':
            source = f'/proc/self/fd/{fds["source"]}/.'
            mount = json.loads(self.run(['findmnt', '-J', '-T', source, '-o', 'FSTYPE,UUID'], tuple(fds.values())))['filesystems'][0]
            text = self.run(['btrfs', 'subvolume', 'show', source], tuple(fds.values()))
            match = re.search(r'^\s*UUID:\s+(\S+)', text, re.M)
            if mount.get('fstype') != 'btrfs' or not match or not re.fullmatch(r'[a-fA-F0-9-]{36}', match[1]):
                raise NativeError('La source n’est pas un sous-volume Btrfs.')
            observed = {'filesystem_uuid': mount['uuid'], 'subvolume_uuid': match[1]}
            system_mount=json.loads(self.run(['findmnt','-J','-T','/','-o','FSTYPE,UUID']))['filesystems'][0]
            if system_mount.get('fstype')=='btrfs' and system_mount.get('uuid')==mount['uuid']:
                system_text=self.run(['btrfs','subvolume','show','/'])
                system_uuid=re.search(r'^\s*UUID:\s+(\S+)',system_text,re.M)
                if not system_uuid or system_uuid[1]==match[1]:
                    raise NativeError('Le sous-volume système ne peut pas être inscrit comme volume de données.')
            required = {k: volume[k] for k in observed}
        elif family == 'zfs':
            dataset = volume['dataset']
            if not DATASET.fullmatch(dataset) or '/' not in dataset or '@' in dataset or dataset.startswith('-'):
                raise NativeError('Dataset ZFS invalide ; la racine du pool est exclue.')
            raw = self.run(['zfs', 'get', '-Hp', '-o', 'property,value', 'guid,type,mountpoint,readonly', dataset])
            props = dict(line.split('\t', 1) for line in raw.strip().splitlines())
            if props.get('type') != 'filesystem' or props.get('mountpoint') in ('/', '/boot', '/boot/efi', 'none', 'legacy') or props.get('readonly') != 'off':
                raise NativeError('Dataset système ou non inscriptible exclu.')
            observed, required = {'guid': props['guid']}, {'guid': str(volume['guid'])}
        else:
            if not LV.fullmatch(volume['lv']):
                raise NativeError('Identifiant LVM invalide.')
            topology=json.loads(self.run(['lsblk','-J','-o','MOUNTPOINTS','/dev/'+volume['lv']]))
            def has_system_mount(node):
                return any(p in ('/','/boot','/boot/efi','/usr','/var','/etc') for p in node.get('mountpoints') or []) or any(has_system_mount(child) for child in node.get('children',[]))
            if any(has_system_mount(node) for node in topology['blockdevices']):
                raise NativeError('Un volume système LVM ne peut pas être inscrit comme volume de données.')
            data = json.loads(self.run(['lvs', '--reportformat', 'json', '--units', 'b', '--nosuffix',
                '-o', 'vg_uuid,lv_uuid,lv_attr,segtype,pool_lv,data_percent,metadata_percent', volume['lv']]))
            rows = data['report'][0]['lv']
            if len(rows) != 1:
                raise NativeError('Volume logique ambigu.')
            props = {k: str(v).strip() for k, v in rows[0].items()}
            if props['segtype'] not in ('thin', 'linear') or not props['lv_attr'].startswith(('V', '-', 'o')):
                raise NativeError('Ce type de volume LVM n’est pas pris en charge.')
            observed = {key: props[key] for key in ('vg_uuid', 'lv_uuid')}
            required = {key: volume[key] for key in observed}
            if props['segtype'] == 'thin' and require_capacity:
                pool = volume['lv'].split('/')[0] + '/' + props['pool_lv']
                pooldata = json.loads(self.run(['lvs', '--reportformat', 'json', '-o', 'data_percent,metadata_percent,lv_attr', pool]))['report'][0]['lv'][0]
                if any(not str(pooldata.get(k, '')).strip() or float(pooldata[k]) >= 90 for k in ('data_percent', 'metadata_percent')):
                    raise NativeError('Thin pool saturé ou capacité inconnue ; intervention nécessaire.')
            elif props['segtype'] == 'linear' and require_capacity:
                cow = volume.get('cow_bytes')
                if type(cow) is not int or cow <= 0:
                    raise NativeError('Réserve COW explicite requise pour LVM classique.')
                vg = volume['lv'].split('/')[0]
                free = json.loads(self.run(['vgs', '--reportformat', 'json', '--units', 'b', '--nosuffix', '-o', 'vg_free', vg]))['report'][0]['vg'][0]['vg_free']
                if float(free.strip()) < cow:
                    raise NativeError('Espace libre du groupe LVM insuffisant pour la réserve COW.')
            observed['segtype'] = props['segtype']
            required['segtype'] = volume.get('segtype')
        if observed != required:
            raise NativeError('L’identité du volume a changé ou ne correspond pas à la politique.')
        return observed

    def status(self):
        volumes = []
        for volume in self.policy().get('volumes', []) + self.provisioning().native_volumes():
            item = {'id': volume['id'], 'name': volume.get('name', volume['id']), 'family': volume['family'],
                    'ready': False, 'clone': volume['family'] == 'btrfs' or (volume['family'] == 'zfs' and bool(volume.get('restore_parent'))) or (volume['family']=='lvm' and bool(volume.get('restore_directory')))}
            try:
                with self.paths(volume) as fds:
                    self.inspect(volume, fds)
                item['ready'] = True
            except (NativeError, OSError, ValueError, KeyError) as error:
                item['reason'] = str(error) if isinstance(error, NativeError) else 'Volume indisponible ou politique incomplète.'
            volumes.append(item)
        points = []
        for row in self.db.execute('SELECT * FROM points ORDER BY created DESC'):
            point = dict(row)
            if point['status'] == 'ready':
                try:
                    self.verify_point(self.volume(point['volume']), point)
                except (NativeError, OSError, ValueError, KeyError):
                    point['status'] = 'invalid'
                    point['detail'] = 'Point absent, identité modifiée ou réserve LVM saturée. Vérifier le stockage.'
            points.append({key: point[key] for key in ('id', 'volume', 'family', 'created', 'actor', 'status', 'detail')})
        actions = [dict(row) for row in self.db.execute('SELECT id,ts,actor,action,volume,object,status,location FROM actions ORDER BY ts DESC LIMIT 100')]
        provisioning=self.provisioning().status()
        return {'connected': True, 'execution_enabled': any(v['ready'] for v in volumes) or any(d['ready'] for d in provisioning['devices']), 'volumes': volumes, 'points': points, 'actions': actions,
                'provisioning':provisioning,'jobs':self.restorations().list(),'resources':self.resources()}

    def verify_point(self, volume, point, fds=None):
        family = volume['family']
        if not re.fullmatch(r'nacre_[a-f0-9]{32}', point['object']):
            raise NativeError('Nom de point non géré.')
        if family == 'btrfs':
            if fds is None:
                with self.paths(volume) as opened:
                    return self.verify_point(volume, point, opened)
            source = f'/proc/self/fd/{fds["snapshots"]}/{point["object"]}'
            text = self.run(['btrfs', 'subvolume', 'show', source], tuple(fds.values()))
            uuid = re.search(r'^\s*UUID:\s+(\S+)', text, re.M)
            ro = self.run(['btrfs', 'property', 'get', '-ts', source, 'ro'], tuple(fds.values())).strip()
            if not uuid or uuid[1] != point['native_identity'] or ro != 'ro=true':
                raise NativeError('Identité ou lecture seule du point Btrfs modifiée.')
        elif family == 'zfs':
            guid = self.run(['zfs', 'get', '-Hp', '-o', 'value', 'guid', volume['dataset'] + '@' + point['object']]).strip()
            if guid != point['native_identity']:
                raise NativeError('Identité du point ZFS modifiée.')
        else:
            target = volume['lv'].split('/')[0] + '/' + point['object']
            raw = json.loads(self.run(['lvs', '--reportformat', 'json', '-o', 'lv_uuid,lv_attr,origin,data_percent', target]))['report'][0]['lv'][0]
            attr = raw['lv_attr'].strip()
            if raw['lv_uuid'].strip() != point['native_identity'] or len(attr) < 5 or attr[1] != 'r' or attr[4] in ('I', 'S') or float(str(raw.get('data_percent', '')).strip() or 0) >= 100:
                raise NativeError('Snapshot LVM invalide ou réserve saturée.')

    def prepare(self, uid, actor, body):
        action = body.get('action')
        if action == 'provision':
            return self.provisioning().prepare(uid,actor,body)
        if action not in ('snapshot', 'clone'):
            raise NativeError('Opération native non autorisée.')
        volume = self.volume(body.get('volume'))
        point = None
        if action == 'clone':
            row = self.db.execute('SELECT * FROM points WHERE id=? AND volume=? AND status=?', (body.get('point'), volume['id'], 'ready')).fetchone()
            if not row:
                raise NativeError('Point de restauration inconnu ou incomplet.')
            point = dict(row)
            if volume['family'] == 'lvm':
                if not volume.get('restore_directory','').startswith('/srv/'):
                    raise NativeError('Une destination dédiée de restauration LVM doit être inscrite dans la politique.')
                private_directory(volume['restore_directory'])
            self.verify_point(volume, point)
        with self.paths(volume) as fds:
            identity = self.inspect(volume, fds, require_capacity=action=='snapshot')
        identifier = secrets.token_hex(16)
        object_name = ('nacre_' if action == 'snapshot' else 'restore_') + identifier
        confirmation = ('CAPTURER ' if action == 'snapshot' else 'RESTAURER ') + volume['id']
        payload = {'action': action, 'volume': volume['id'], 'identity': identity,
                   'policy': fingerprint(volume), 'object': object_name, 'point': point, 'confirmation': confirmation}
        expiry = time.time() + 120
        with self.db:
            self.db.execute('DELETE FROM plans WHERE expires < ?', (time.time(),))
            self.db.execute('INSERT INTO plans(id,uid,actor,expires,payload) VALUES(?,?,?,?,?)', (identifier, uid, actor, expiry, canonical(payload)))
        return {'id': identifier, 'expires': expiry, 'action': action, 'volume': volume['id'], 'confirmation': confirmation,
                'effect': 'Créer un point natif en lecture seule.' if action == 'snapshot' else 'Créer une nouvelle copie inscriptible ; le volume actuel est conservé.',
                'notes': ['Les sous-volumes ou datasets enfants ne sont pas inclus.', 'Les applications ne sont pas mises en pause.', 'Un snapshot sur le même support ne remplace pas une sauvegarde.']}

    def commit(self, uid, actor, body):
        row = self.db.execute('SELECT * FROM plans WHERE id=?', (body.get('plan'),)).fetchone()
        if not row or row['uid'] != uid or row['actor'] != actor or row['consumed'] or row['expires'] < time.time():
            raise NativeError('Plan expiré, déjà exécuté ou appartenant à un autre compte.')
        plan = json.loads(row['payload'])
        if body.get('confirmation') != plan['confirmation']:
            raise NativeError('Recopier exactement la confirmation du plan.')
        if plan['action']=='provision':
            return self.provisioning().commit(row,plan)
        volume = self.volume(plan['volume'])
        if fingerprint(volume) != plan['policy']:
            raise NativeError('Politique modifiée ; préparer un nouveau plan.')
        with self.paths(volume) as fds:
            if self.inspect(volume, fds, require_capacity=plan['action']=='snapshot') != plan['identity']:
                raise NativeError('Identité modifiée ; préparer un nouveau plan.')
            # Consommer et journaliser AVANT la commande : un timeout ne se rejoue pas.
            with self.db:
                self.db.execute('UPDATE plans SET consumed=1 WHERE id=?', (row['id'],))
                self.db.execute('INSERT INTO actions(id,ts,actor,action,volume,object,status) VALUES(?,?,?,?,?,?,?)', (row['id'], time.time(), actor, plan['action'], volume['id'], plan['object'], 'running'))
                if plan['action'] == 'snapshot':
                    self.db.execute('INSERT INTO points(id,volume,family,created,actor,status,object,identity,detail) VALUES(?,?,?,?,?,?,?,?,?)', (row['id'], volume['id'], volume['family'], time.time(), actor, 'creating', plan['object'], canonical(plan['identity']), ''))
            try:
                result = self.restorations().enqueue(row['id'],actor,volume,plan['point']) if plan['action']=='clone' and volume['family']=='lvm' else self.apply(volume, plan, fds)
            except Exception:
                with self.db:
                    self.db.execute("UPDATE actions SET status='uncertain' WHERE id=?", (row['id'],))
                    self.db.execute("UPDATE points SET status='uncertain',detail='Vérifier le stockage : la commande n’a pas été confirmée.' WHERE id=?", (row['id'],))
                raise
            with self.db:
                self.db.execute("UPDATE actions SET status=?,location=? WHERE id=?", ('queued' if result.get('queued') else 'done', result.get('location', ''), row['id']))
                self.db.execute("UPDATE points SET status='ready',native_identity=? WHERE id=?", (result.get('native_identity', ''), row['id']))
            return {'ok': True, 'object': plan['object'], **result}

    def apply(self, volume, plan, fds):
        family, action, name = volume['family'], plan['action'], plan['object']
        if family == 'btrfs':
            source = f'/proc/self/fd/{fds["source"]}/.'
            destination = f'/proc/self/fd/{fds["snapshots" if action == "snapshot" else "restores"]}/{name}'
            if action == 'clone':
                self.verify_point(volume, plan['point'], fds)
                source = f'/proc/self/fd/{fds["snapshots"]}/{plan["point"]["object"]}'
                text = self.run(['btrfs', 'property', 'get', '-ts', source, 'ro'], tuple(fds.values()))
                if text.strip() != 'ro=true':
                    raise NativeError('Le point source n’est plus en lecture seule.')
            argv = ['btrfs', 'subvolume', 'snapshot'] + (['-r'] if action == 'snapshot' else []) + [source, destination]
            self.run(argv, tuple(fds.values()))
            text = self.run(['btrfs', 'subvolume', 'show', destination], tuple(fds.values()))
            uuid = re.search(r'^\s*UUID:\s+(\S+)', text, re.M)
            if not uuid:
                raise NativeError('Identité du nouveau sous-volume non confirmée.')
            if action == 'snapshot' and self.run(['btrfs', 'property', 'get', '-ts', destination, 'ro'], tuple(fds.values())).strip() != 'ro=true':
                raise NativeError('Lecture seule du nouveau point non confirmée.')
            return {'location': str(Path(volume['snapshots' if action == 'snapshot' else 'restores']) / name), 'native_identity': uuid[1]}
        if family == 'zfs':
            if action == 'snapshot':
                target = volume['dataset'] + '@' + name
                self.run(['zfs', 'snapshot', target])
                guid = self.run(['zfs', 'get', '-Hp', '-o', 'value', 'guid', target]).strip()
                return {'location': target, 'native_identity': guid}
            parent = volume.get('restore_parent', '')
            if not DATASET.fullmatch(parent) or not parent.startswith(volume['dataset'].split('/')[0] + '/') or parent == volume['dataset'] or parent.startswith(volume['dataset'] + '/'):
                raise NativeError('Parent de restauration ZFS dédié requis dans le même pool.')
            guid = self.run(['zfs', 'get', '-Hp', '-o', 'value', 'guid', parent]).strip()
            if guid != str(volume.get('restore_parent_guid')):
                raise NativeError('Identité du parent de restauration ZFS modifiée.')
            # Clone non monté : aucune écriture sur un chemin hôte arbitraire.
            self.verify_point(volume, plan['point'])
            target = parent + '/' + name
            # canmount=noauto + mountpoint=none empêchent le montage, y compris
            # sur OpenZFS 2.2 qui ne possède pas encore l'option clone -u.
            self.run(['zfs', 'clone', '-o', 'canmount=noauto', '-o', 'mountpoint=none', '-o', 'readonly=off',
                      '-o', 'exec=off', '-o', 'setuid=off', '-o', 'devices=off', volume['dataset'] + '@' + plan['point']['object'], target])
            if self.run(['zfs', 'get', '-Hp', '-o', 'value', 'mounted', target]).strip() != 'no':
                raise NativeError('Le clone ZFS doit rester non monté.')
            return {'location': target, 'mounted': False}
        argv = ['lvcreate', '--snapshot', '--permission', 'r', '--name', name]
        if volume['segtype'] == 'linear':
            argv += ['--size', str(volume['cow_bytes']) + 'b']
        self.run(argv + [volume['lv']])
        target = volume['lv'].split('/')[0] + '/' + name
        raw = json.loads(self.run(['lvs', '--reportformat', 'json', '-o', 'lv_uuid,lv_attr,origin,data_percent', target]))['report'][0]['lv'][0]
        if str(raw.get('origin', '')).strip() != volume['lv'].split('/')[1] or len(raw.get('lv_attr', '')) < 2 or raw['lv_attr'][1] != 'r':
            raise NativeError('La lecture seule du snapshot LVM n’a pas été confirmée.')
        return {'location': target, 'mounted': False, 'native_identity': raw['lv_uuid'].strip()}

    def request(self, uid, message):
        if uid != self.policy()['allowed_uid']:
            raise NativeError('Identité du client système non autorisée.')
        action = message.get('method')
        actor = message.get('actor', '')
        if not isinstance(actor, str) or not re.fullmatch(r'[a-z][a-z0-9_-]{2,23}', actor):
            raise NativeError('Compte de console invalide.')
        if action == 'status':
            return self.status()
        if action == 'prepare':
            return self.prepare(uid, actor, message.get('body', {}))
        if action == 'commit':
            return self.commit(uid, actor, message.get('body', {}))
        if action == 'cancel':
            return self.restorations().cancel(message.get('body',{}).get('job'))
        if action == 'resources':
            return self.resources()
        raise NativeError('Méthode non autorisée.')


class NativeClient:
    def __init__(self, path=SOCKET):
        self.path = path

    def request(self, method, actor, body=None):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(100)
            client.connect(self.path)
            client.sendall((canonical({'method': method, 'actor': actor, 'body': body or {}}) + '\n').encode())
            with client.makefile('rb') as file:
                raw = file.readline(MAX_MESSAGE * 16 + 1)
            if len(raw) > MAX_MESSAGE * 16:
                raise NativeError('Réponse système trop volumineuse.')
            response = json.loads(raw)
            if 'error' in response:
                raise NativeError(response['error'])
            return response['result']

    def status(self, actor):
        try:
            return self.request('status', actor)
        except (OSError, ValueError):
            return {'connected': False, 'execution_enabled': False, 'volumes': [], 'points': [], 'actions': [],
                    'provisioning':{'enabled':False,'devices':[],'deployments':[]},'jobs':[],'resources':[],
                    'message': 'Service natif non activé. Inscrivez les volumes autorisés sur le matériel cible pour activer les opérations.'}


class RequestHandler(socketserver.StreamRequestHandler):
    def handle(self):
        self.connection.settimeout(5)
        uid = struct.unpack('3i', self.connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i')))[1]
        try:
            raw = self.rfile.readline(MAX_MESSAGE + 1)
            if len(raw) > MAX_MESSAGE or not raw.endswith(b'\n'):
                raise NativeError('Requête système invalide.')
            response = {'result': self.server.engine.request(uid, json.loads(raw))}
        except (NativeError, OSError, ValueError, KeyError, TypeError) as error:
            response = {'error': str(error) if isinstance(error, NativeError) else 'Opération système refusée ; vérifier la politique et le journal.'}
        self.wfile.write((canonical(response) + '\n').encode())


def serve():
    if os.geteuid() != 0:
        raise SystemExit('Ce daemon optionnel doit être exécuté par root avec sa politique dédiée.')
    os.umask(0o077)
    policy = read_policy()
    directory = Path(SOCKET).parent
    directory.mkdir(mode=0o755, exist_ok=True)
    private_directory(directory)
    lock_fd = os.open(directory / 'daemon.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit('Un daemon est déjà actif.') from None
    Path(STATE).mkdir(mode=0o700, exist_ok=True)
    engine = Engine()
    engine.provisioning().recover_mounts()
    if Path(SOCKET).exists():
        # Ne jamais supprimer le socket d'un daemon en activité.
        with socket.socket(socket.AF_UNIX) as probe:
            try:
                probe.connect(SOCKET)
            except ConnectionRefusedError:
                Path(SOCKET).unlink()
            else:
                raise SystemExit('Un daemon utilise déjà le socket.')
    with socketserver.UnixStreamServer(SOCKET, RequestHandler) as server:
        server.engine = engine
        os.chown(SOCKET, policy['allowed_uid'], -1)
        os.chmod(SOCKET, 0o600)
        server.serve_forever()


if __name__ == '__main__':
    serve()
