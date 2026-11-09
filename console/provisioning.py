"""Création fermée de volumes sur disques entiers inscrits comme initialisables.

Aucun effacement forcé, repartitionnement ou commande arbitraire. L'absence de
signature n'est pas une preuve d'absence de données : l'autorisation root et
la confirmation explicite du plan sont toutes deux nécessaires.
"""
from contextlib import ExitStack, contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import stat
import time
import uuid

from native_storage import NativeError, ID, canonical, fingerprint, private_directory, trusted_directory


def reject_used(node):
    if node.get('type') != 'disk' or node.get('ro') or node.get('children'):
        raise NativeError('Disque en lecture seule, partitionné ou utilisé par une autre couche de stockage.')
    if any(node.get('mountpoints') or []) or node.get('fstype') or node.get('pttype'):
        raise NativeError('Disque monté ou contenant déjà un système de fichiers ou des partitions.')


class Provisioning:
    def __init__(self, engine):
        self.e = engine
        self.e.db.execute('CREATE TABLE IF NOT EXISTS deployments (id TEXT PRIMARY KEY, created REAL, actor TEXT, phase TEXT, record TEXT, error TEXT)')

    def settings(self):
        settings = self.e.policy().get('provisioning', {})
        if settings.get('enabled') is not True:
            raise NativeError('L’initialisation de disques n’est pas autorisée sur ce matériel.')
        root = settings.get('root', '')
        if not isinstance(root, str) or not root.startswith('/srv/'):
            raise NativeError('Racine de volumes dédiée sous /srv requise dans la politique.')
        private_directory(root)
        return settings

    def spec(self, identifier):
        for item in self.settings().get('devices', []):
            if item.get('id') == identifier and ID.fullmatch(identifier) and item.get('initialize') is True:
                path = Path(item['path'])
                if path.parent != Path('/dev/disk/by-id') or path.name in ('.','..') or not item.get('serial') or type(item.get('bytes')) is not int:
                    raise NativeError('Identité stable by-id, série et capacité exactes requises.')
                return item
        raise NativeError('Disque non autorisé à l’initialisation par la politique système.')

    def probe(self, spec, blank=True):
        # Le lien by-id est géré par udev, dans une arborescence protégée par root.
        with trusted_directory('/dev/disk/by-id') as fd:
            meta = os.fstat(fd)
            if meta.st_uid != 0 or meta.st_mode & 0o022:
                raise NativeError('Répertoire des identités de disques non protégé.')
        path = str(Path(spec['path']).resolve(strict=True))
        if not path.startswith('/dev/'):
            raise NativeError('Identité de disque hors de /dev.')
        meta = os.stat(path, follow_symlinks=False)
        if not stat.S_ISBLK(meta.st_mode):
            raise NativeError('Un périphérique bloc réel est requis.')
        rows = json.loads(self.e.run(['lsblk','-J','-b','-p','-o','NAME,PATH,TYPE,SIZE,SERIAL,WWN,RO,MOUNTPOINTS,FSTYPE,PTTYPE,MAJ:MIN',path]))['blockdevices']
        if len(rows) != 1:
            raise NativeError('Identité de disque ambiguë.')
        node = rows[0]
        identity = {'id':spec['id'],'path':path,'serial':str(node.get('serial') or '').strip(),
                    'bytes':int(node.get('size') or 0),'device':f'{os.major(meta.st_rdev)}:{os.minor(meta.st_rdev)}'}
        if identity['serial'] != spec['serial'] or identity['bytes'] != spec['bytes'] or node.get('maj:min') != identity['device']:
            raise NativeError('La série, la capacité ou l’identité noyau du disque ne correspond plus.')
        if spec.get('wwn') and (node.get('wwn') or '').strip() != spec['wwn']:
            raise NativeError('Identité WWN différente.')
        if blank:
            reject_used(node)
            sysdir = Path('/sys/dev/block') / identity['device']
            if any((sysdir/'holders').iterdir()) or any((sysdir/'slaves').iterdir()):
                raise NativeError('Disque utilisé par une pile RAID, LVM ou device-mapper.')
            signatures = json.loads(self.e.run(['wipefs','--json','--no-act','--output','TYPE,OFFSET',path]))
            if signatures.get('signatures'):
                raise NativeError('Une signature de stockage existe déjà sur le disque. Aucun effacement forcé n’est proposé.')
        return identity

    @contextmanager
    def pinned(self, specs, expected):
        with ExitStack() as stack:
            fds = []
            for spec, previous in zip(specs, expected):
                fresh = self.probe(spec)
                if fresh != previous:
                    raise NativeError('Disque remplacé depuis la préparation du plan.')
                fd = os.open(fresh['path'], os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
                stack.callback(os.close, fd)
                # Coordination avec les outils/udev respectant les verrous BSD.
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                meta = os.fstat(fd)
                if f'{os.major(meta.st_rdev)}:{os.minor(meta.st_rdev)}' != previous['device'] or self.probe(spec) != previous:
                    raise NativeError('Identité de disque modifiée pendant son ouverture.')
                fds.append(fd)
            yield tuple(fds)

    def prepare(self, uid, actor, body):
        settings = self.settings()
        profile = body.get('profile', {})
        layout, filesystem = profile.get('layout'), profile.get('filesystem')
        name = profile.get('name', '')
        identifiers = body.get('devices')
        if layout not in ('single','mirror') or filesystem not in ('btrfs','ext4') or not isinstance(name,str) or not name.strip() or len(name)>80:
            raise NativeError('Profil de volume invalide.')
        count = 1 if layout == 'single' else 2
        sizes = profile.get('disk_bytes')
        if not isinstance(identifiers,list) or len(identifiers)!=count or any(not isinstance(i,str) for i in identifiers) or len(set(identifiers))!=count:
            raise NativeError('Choisir des disques distincts pour ce profil.')
        if not isinstance(sizes,list) or len(sizes)!=count or any(type(x) is not int or x<=0 for x in sizes):
            raise NativeError('Capacités du profil invalides.')
        specs = [self.spec(i) for i in identifiers]
        devices = [self.probe(s) for s in specs]
        if len({d['device'] for d in devices}) != count:
            raise NativeError('Deux identités désignent le même disque physique.')
        if any(d['bytes'] < size for d,size in zip(devices,sizes)):
            raise NativeError('Un disque est plus petit que la capacité prévue dans le profil.')
        token = secrets.token_hex(16)
        identifier = 'managed-' + token[:20]
        confirm = 'INITIALISER ' + ' + '.join(identifiers)
        payload = {'action':'provision','volume':identifier,'profile':profile,'specs':specs,'devices':devices,
                   'root':settings['root'],'confirmation':confirm,'object':identifier}
        with self.e.db:
            self.e.db.execute('INSERT INTO plans(id,uid,actor,expires,payload) VALUES(?,?,?,?,?)',(token,uid,actor,time.time()+120,canonical(payload)))
        return {'id':token,'expires':time.time()+120,'action':'provision','volume':name,'confirmation':confirm,
                'devices':devices,'effect':'Initialiser les disques entiers et créer '+('un miroir RAID1' if count==2 else 'un volume')+' '+filesystem+'.',
                'notes':['Cette opération écrit sur les disques sélectionnés et peut détruire des données non reconnues.',
                         'Aucune signature connue n’a été détectée ; cela ne prouve pas que le disque ne contient aucune donnée.',
                         'Le volume sera monté dans sa destination dédiée. Aucun disque système ni disque déjà utilisé n’est accepté.']}

    def authorize(self, record):
        settings = self.settings()
        if settings['root'] != record['root'] or any(self.spec(s['id']) != s for s in record['specs']):
            raise NativeError('L’autorisation de ce volume a changé.')
        return settings

    def commit(self, row, plan):
        if self.settings()['root'] != plan['root'] or any(self.spec(s['id']) != s for s in plan['specs']):
            raise NativeError('Politique modifiée ; préparer un nouveau plan.')
        identifier = plan['volume']
        record = {'id':identifier,'name':plan['profile']['name'],'filesystem':plan['profile']['filesystem'],
                  'layout':plan['profile']['layout'],'root':plan['root'],'specs':plan['specs'],
                  'mountpoint':str(Path(plan['root'])/identifier),'fs_uuid':None,'md_uuid':None,'native_volume':None}
        target = Path(record['mountpoint'])
        if target.exists():
            raise NativeError('La destination de ce nouveau volume existe déjà.')
        with self.pinned(plan['specs'],plan['devices']) as fds:
            with self.e.db:
                self.e.db.execute('UPDATE plans SET consumed=1 WHERE id=?',(row['id'],))
                self.e.db.execute('INSERT INTO deployments VALUES(?,?,?,?,?,?)',(identifier,time.time(),row['actor'],'creating',canonical(record),''))
                self.e.db.execute('INSERT INTO actions(id,ts,actor,action,volume,object,status) VALUES(?,?,?,?,?,?,?)',(row['id'],time.time(),row['actor'],'provision',identifier,identifier,'running'))
            try:
                devices = [f'/proc/self/fd/{fd}' for fd in fds]
                if record['layout'] == 'mirror':
                    record['md_uuid'] = ':'.join(re.findall('.{8}',uuid.uuid4().hex))
                    self.save_record(identifier,record)
                    device = '/dev/md/nacre_' + identifier[8:]
                    if Path(device).exists():
                        raise NativeError('Un périphérique RAID porte déjà ce nom.')
                    self.e.run(['mdadm','--create',device,'--run','--metadata=1.2','--level=1','--raid-devices=2',
                                '--homehost=none','--name=nacre_'+identifier[8:],'--uuid='+record['md_uuid'],*devices],fds)
                    self.check_md(device,record)
                else:
                    device = devices[0]
                label = 'nacre_' + identifier[8:16]
                self.e.run(['mkfs.btrfs','-L',label,device] if record['filesystem']=='btrfs' else ['mkfs.ext4','-L',label,device],fds)
                record['fs_uuid'] = self.e.run(['blkid','-p','-s','UUID','-o','value',device],fds).strip()
                if not re.fullmatch(r'[a-fA-F0-9-]{36}',record['fs_uuid']):
                    raise NativeError('UUID du nouveau système de fichiers non confirmé.')
                self.save_record(identifier,record)
                target.mkdir(mode=0o755)
                self.e.run(['mount','-t',record['filesystem'],'-o','nodev,nosuid',device,str(target)],fds)
                self.check_mount(record)
                if record['filesystem']=='btrfs':
                    self.e.run(['btrfs','subvolume','create',str(target/'data')])
                    (target/'snapshots').mkdir(mode=0o700)
                    (target/'restores').mkdir(mode=0o755)
                    text=self.e.run(['btrfs','subvolume','show',str(target/'data')])
                    subvolume_uuid=re.search(r'^\s*UUID:\s+(\S+)',text,re.M)[1]
                    record['native_volume']={'id':identifier,'name':record['name'],'family':'btrfs','source':str(target/'data'),
                        'snapshots':str(target/'snapshots'),'restores':str(target/'restores'),
                        'filesystem_uuid':record['fs_uuid'],'subvolume_uuid':subvolume_uuid}
                else:
                    (target/'data').mkdir(mode=0o770)
                uid=self.e.policy()['allowed_uid']
                import pwd
                os.chown(target/'data',uid,pwd.getpwuid(uid).pw_gid)
                os.chmod(target/'data',0o2770)
                self.save_record(identifier,record,'ready')
                with self.e.db:
                    self.e.db.execute("UPDATE actions SET status='done',location=? WHERE id=?",(str(target/'data'),row['id']))
                return {'ok':True,'object':identifier,'location':str(target/'data')}
            except Exception:
                self.save_record(identifier,record,'uncertain','Initialisation interrompue. Vérifier le stockage ; aucune reprise de formatage automatique.')
                with self.e.db:
                    self.e.db.execute("UPDATE actions SET status='uncertain' WHERE id=?",(row['id'],))
                raise

    def save_record(self, identifier, record, phase=None, error=''):
        with self.e.db:
            self.e.db.execute('UPDATE deployments SET record=?,phase=COALESCE(?,phase),error=? WHERE id=?',(canonical(record),phase,error,identifier))

    def check_md(self, device, record):
        values=dict(line.split('=',1) for line in self.e.run(['mdadm','--detail','--export',device]).splitlines() if '=' in line)
        if values.get('MD_UUID') != record['md_uuid'] or values.get('MD_LEVEL') != 'raid1':
            raise NativeError('Identité ou niveau du miroir différent du catalogue.')
        return values

    def check_mount(self, record):
        rows=json.loads(self.e.run(['findmnt','-J','-M',record['mountpoint'],'-o','TARGET,FSTYPE,UUID,OPTIONS']))['filesystems']
        if len(rows)!=1 or rows[0].get('uuid')!=record['fs_uuid'] or rows[0].get('fstype')!=record['filesystem']:
            raise NativeError('Le volume monté ne correspond pas au catalogue.')
        private_directory(record['mountpoint'])
        return rows[0]

    def records(self):
        return [(dict(row),json.loads(row['record'])) for row in self.e.db.execute('SELECT * FROM deployments ORDER BY created DESC')]

    def status(self):
        try:
            settings=self.settings()
        except (NativeError,OSError):
            settings=None
        disks=[]
        if settings:
            for item in settings.get('devices',[]):
                view={'id':item.get('id'),'serial':item.get('serial'),'bytes':item.get('bytes'),'ready':False}
                try:
                    view.update(self.probe(self.spec(item['id'])))
                    view['ready']=True
                except (NativeError,OSError,ValueError,KeyError) as error:
                    view['reason']=str(error) if isinstance(error,NativeError) else 'Disque indisponible.'
                disks.append(view)
        deployments=[]
        for row,record in self.records():
            view={k:record[k] for k in ('id','name','filesystem','layout','mountpoint')}
            view.update(phase=row['phase'],mounted=False,error=row['error'],raid=None)
            if row['phase']=='ready':
                try:
                    self.authorize(record)
                    self.check_mount(record)
                    view['mounted']=True
                    if record['layout']=='mirror':
                        source=json.loads(self.e.run(['findmnt','-J','-M',record['mountpoint'],'-o','SOURCE']))['filesystems'][0]['source']
                        # Btrfs source peut porter un suffixe [/subvol].
                        device=str(Path(source.split('[')[0]).resolve())
                        self.check_md(device,record)
                        md=Path('/sys/class/block')/Path(device).name/'md'
                        view['raid']={'state':(md/'array_state').read_text().strip(),'degraded':int((md/'degraded').read_text()),
                                      'sync_action':(md/'sync_action').read_text().strip(),'sync_completed':(md/'sync_completed').read_text().strip()}
                except (NativeError,OSError,ValueError,KeyError):
                    view['error']='Volume non monté, autorisation retirée ou identité à vérifier.'
            deployments.append(view)
        return {'enabled':settings is not None,'devices':disks,'deployments':deployments}

    def native_volumes(self):
        result=[]
        for row,record in self.records():
            if row['phase']=='ready' and record.get('native_volume'):
                try:
                    self.authorize(record); self.check_mount(record)
                    result.append(record['native_volume'])
                except (NativeError,OSError,ValueError,KeyError):
                    pass
        return result

    def mount_existing(self, record):
        self.authorize(record)
        try:
            self.check_mount(record)
            return
        except NativeError:
            # Une destination occupée par un autre montage ne doit pas être masquée.
            mounts=json.loads(self.e.run(['findmnt','-J','-l','-o','TARGET']))['filesystems']
            if any(m['target']==record['mountpoint'] for m in mounts):
                raise
        except OSError:
            pass
        devices=[self.probe(spec,blank=False)['path'] for spec in record['specs']]
        device=devices[0]
        if record['layout']=='mirror':
            # Retrouver uniquement notre UUID ; aucun assemblage global ni --force.
            found=None
            for path in Path('/sys/class/block').glob('md*'):
                candidate='/dev/'+path.name
                try:self.check_md(candidate,record);found=candidate;break
                except NativeError:pass
            if not found:
                found='/dev/md/nacre_'+record['id'][8:]
                self.e.run(['mdadm','--assemble',found,'--uuid='+record['md_uuid'],*devices])
                self.check_md(found,record)
            device=found
        observed=self.e.run(['blkid','-p','-s','UUID','-o','value',device]).strip()
        if observed!=record['fs_uuid']:
            raise NativeError('Le système de fichiers a changé depuis sa création.')
        target=Path(record['mountpoint'])
        if not target.exists():target.mkdir(mode=0o755)
        private_directory(target)
        if any(target.iterdir()):
            raise NativeError('La destination de montage contient déjà des fichiers.')
        self.e.run(['mount','-t',record['filesystem'],'-o','nodev,nosuid',device,str(target)])
        self.check_mount(record)

    def recover_mounts(self):
        try:settings=self.settings()
        except (NativeError,OSError):return
        if settings.get('mount_on_start') is not True:return
        for row,record in self.records():
            if row['phase']!='ready':continue
            try:self.mount_existing(record)
            except (NativeError,OSError,ValueError,KeyError):
                self.save_record(record['id'],record,error='Remontage automatique non abouti ; vérifier identité et disponibilité.')
