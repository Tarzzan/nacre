#!/usr/bin/env python3
"""Capture chiffrée et reprise hors ligne de l’installation Nacre."""
import argparse
from contextlib import closing, ExitStack
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from compose_support import arguments
from installation_lock import held
from schema import check, checksum, private_file, private_directory, readonly, sync_directory, VERSION

TAG='nacre-installation-v1'
PENDING='nacre-installation-pending-v1'
SOURCE=Path(__file__).resolve().parents[1]


class RecoveryError(RuntimeError):pass


def run(args, stdin=None, stdout=None, env=None):
    result=subprocess.run([str(x) for x in args],stdin=stdin,stdout=stdout or subprocess.PIPE,stderr=subprocess.PIPE,env=env)
    if result.returncode:
        raise RecoveryError('Commande de reprise refusée ('+str(args[0])+', code '+str(result.returncode)+'). Aucun succès supposé.')
    return result.stdout


def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2);stream.flush();os.fsync(stream.fileno())


def restic(repository,key,*args,stdout=None):
    private_file(key)
    binary=os.environ.get('NAS_RESTIC_BIN') or shutil.which('restic') or str(SOURCE/'.tools/restic')
    return run([binary,'--repo',repository,'--password-file',key,'--no-cache',*args],stdout=stdout)


def offline(root):
    ids=run(arguments(root,'ps','--all','--quiet')).decode().split()
    if not ids:raise RecoveryError('Aucun conteneur existant : l’état Samba doit être identifiable.')
    states=json.loads(run(['docker','inspect',*ids]))
    if any(c['State']['Running'] or c['State'].get('Restarting') for c in states):
        raise RecoveryError('Arrêter les services vidéo et fichiers avant la capture.')
    samba=next((c for c in states if c['Config']['Labels'].get('com.docker.compose.service')=='fichiers'),None)
    if not samba:raise RecoveryError('Conteneur Samba absent.')
    return states,samba


def tar_safe(path,required='passdb.tdb'):
    with tarfile.open(path,'r:') as archive:
        names=set();files=set()
        for member in archive:
            parts=PurePosixPath(member.name).parts
            if member.name.startswith('/') or '..' in parts or not (member.isfile() or member.isdir()):
                raise RecoveryError('Archive contenant un chemin ou un type non autorisé.')
            name=str(PurePosixPath(member.name))
            if name in names:raise RecoveryError('Archive ambiguë.')
            names.add(name)
            if member.isfile():files.add(name)
        if not any(n.endswith('/'+required) or n==required for n in files):
            raise RecoveryError('Fichier requis absent de la capture : '+required)


def video_config_container(root,states):
    videos=[c for c in states if c['Config']['Labels'].get('com.docker.compose.service')=='video']
    if not videos:return None
    if len(videos)!=1:raise RecoveryError('Conteneur vidéo ambigu.')
    video=videos[0]
    for destination,relative in (('/config','state/frigate'),('/media/frigate','data/video')):
        mounts=[m for m in video.get('Mounts',[]) if m['Destination']==destination]
        if len(mounts)!=1 or mounts[0]['Type']!='bind' or Path(mounts[0]['Source']).resolve()!=(root/relative).resolve():
            raise RecoveryError('Le conteneur vidéo ne correspond pas aux données de cette installation.')
    return video


def restore_video_config(root,image,manifest):
    if manifest['format']==1:return
    archive=root/'state/recovery-kit/frigate.tar'
    if checksum(archive)!=manifest['sha256'].get('frigate.tar'):raise RecoveryError('Empreinte de la configuration vidéo incorrecte.')
    tar_safe(archive,required='frigate.db')
    target=root/'state/frigate'
    if target.exists() or target.is_symlink():raise RecoveryError('Destination vidéo déjà présente dans le point de reprise.')
    target.mkdir(mode=0o700)
    container='nacre-recovery-video-'+secrets.token_hex(12);created=False
    try:
        # Copie des fichiers root privés avec leurs UID et modes, sans démarrer
        # de processus ni exposer un autre chemin en écriture.
        run(['docker','create','--name',container,'--network','none','--read-only','--cap-drop','ALL',
             '--security-opt','no-new-privileges','--mount','type=bind,source='+str(target)+',target=/restore',
             '--entrypoint','/bin/true',image]);created=True
        with archive.open('rb') as stream:run(['docker','cp','-a','-',container+':/restore/'],stdin=stream)
    finally:
        if created:run(['docker','rm',container])


def native_sources(root):
    # Les montages externes explicitement définis font partie du plan de reprise.
    path=root/'state/console/recovery-volumes.json'
    values=json.loads(path.read_text()) if path.exists() else {}
    if not isinstance(values,dict):raise RecoveryError('Carte des volumes invalide.')
    for name,value in values.items():
        if not re.fullmatch(r'native_[a-z][a-z0-9_-]{0,80}',name):raise RecoveryError('Identifiant de volume invalide.')
        p=Path(value)
        if not p.is_absolute() or p.is_symlink() or not p.is_dir() or p.resolve()==Path('/'):
            raise RecoveryError('Source de volume indisponible.')
        if p.resolve().is_relative_to(root) or root.is_relative_to(p.resolve()):raise RecoveryError('Sources de reprise imbriquées.')
    paths=[Path(v).resolve() for v in values.values()]
    if any(a.is_relative_to(b) or b.is_relative_to(a) for i,a in enumerate(paths) for b in paths[i+1:]):
        raise RecoveryError('Sources de reprise imbriquées.')
    needed=set()
    config=json.loads((root/'state/console/smb.json').read_text())
    needed.update(s['area'] for s in config['shares'] if s['area'].startswith('native_'))
    with closing(readonly(root/'state/console/console.db')) as db:
        for row in db.execute('SELECT config FROM plans'):
            needed.update(s for s in json.loads(row[0]).get('sources',[]) if s.startswith('native_'))
        needed.update(r[0] for r in db.execute("SELECT target FROM repositories WHERE target LIKE 'native_%'"))
        needed.update(r[0] for r in db.execute("SELECT area FROM trash WHERE area LIKE 'native_%'"))
    if not needed.issubset(values):raise RecoveryError('Un volume référencé manque dans recovery-volumes.json.')
    # Même les volumes gérés sans partage doivent être inscrits ; pas d’omission silencieuse.
    socket=Path('/run/nacre-storage/control.sock')
    if Path('/etc/nacre-storage/policy.json').exists() and not socket.exists():
        raise RecoveryError('Service natif installé mais indisponible : inventaire complet impossible.')
    if socket.exists():
        from native_storage import NativeClient
        if not (root/'state/native-recovery.tar').is_file():raise RecoveryError('Exporter la politique et le catalogue natifs avant la capture.')
        info=NativeClient().request('status','admin')
        if not info.get('connected'):raise RecoveryError('Inventaire natif indisponible.')
        for volume in info.get('volumes',[]):
            if not volume.get('ready') or 'native_'+volume['id'] not in values:
                raise RecoveryError('Un volume natif manque ou son identité ne peut pas être validée.')
        if any(j.get('status') in ('queued','running') for j in info.get('jobs',[])):
            raise RecoveryError('Attendre la fin des copies natives avant la capture.')
        managed=info.get('provisioning',{}).get('deployments',[])
        resources={ 'native_'+r['id']:r for r in info.get('resources',[]) if r.get('kind')=='volume'}
        if not set(resources).issubset(values):raise RecoveryError('Inscrire tous les volumes gérés dans la carte de reprise.')
        for area,r in resources.items():
            if Path(values[area]).resolve()!=Path(r['path']).resolve():raise RecoveryError('La carte diffère du volume autorisé.')
        for v in managed:
            if 'native_'+v['id'] not in resources:raise RecoveryError('Un volume géré est indisponible.')
    return {name:str(Path(value).resolve()) for name,value in values.items()}


def capture(root,repository,key):
    root=Path(root).resolve();repository=Path(repository).resolve();key=Path(key).resolve()
    if root.stat().st_uid!=os.getuid():raise RecoveryError('La racine doit appartenir au compte de capture.')
    if key.is_relative_to(root):raise RecoveryError('Conserver la clé de reprise hors de l’installation.')
    if repository.is_relative_to(root):raise RecoveryError('Le dépôt de reprise doit être hors de l’installation.')
    with held(root,True), ExitStack() as pins:
        states,samba=offline(root)
        video=video_config_container(root,states)
        volumes=native_sources(root)
        for source in [str(root),*volumes.values()]:
            if key.is_relative_to(source):raise RecoveryError('Clé de reprise présente dans une source de données.')
            if repository.is_relative_to(source):raise RecoveryError('Le dépôt de reprise ne peut être sa propre source.')
        identifiers={}
        with closing(readonly(root/'state/console/console.db')) as db:
            for identifier,path,key_file in db.execute('SELECT id,path,key_file FROM repositories'):
                expected=root/'state/console/keys'/(identifier+'.key')
                if Path(key_file)!=expected:raise RecoveryError('Clé de dépôt hors du répertoire privé attendu.')
                private_file(expected)
                identifiers[identifier]=json.loads(restic(path,expected,'cat','config'))['id']
        guards=[]
        for source in [str(root),*volumes.values()]:
            fd=os.open(source,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW);pins.callback(os.close,fd)
            st=os.fstat(fd);guards.append((Path(source),st.st_dev,st.st_ino))
        kit=root/'state/recovery-kit'
        kit.mkdir(mode=0o700) # Refus d’un ancien kit : ne jamais le supprimer implicitement.
        try:
            for name,cmd in [('samba.tar',['docker','cp',samba['Id']+':/var/lib/samba/.','-']),
                             ('samba-image.tar',['docker','image','save',samba['Image']])]:
                fd=os.open(kit/name,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
                with os.fdopen(fd,'wb') as output:run(cmd,stdout=output)
            tar_safe(kit/'samba.tar')
            captured=['samba.tar','samba-image.tar'];exclusions=[]
            if video:
                # Frigate crée .jwt_secret en root:0600. Ne pas changer ses
                # droits ni omettre ce fichier dans la sauvegarde chiffrée.
                fd=os.open(kit/'frigate.tar',os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
                with os.fdopen(fd,'wb') as output:run(['docker','cp',video['Id']+':/config/.','-'],stdout=output)
                tar_safe(kit/'frigate.tar',required='frigate.db')
                captured.append('frigate.tar');exclusions=['--exclude',str(root/'state/frigate')]
            token='nacre-installation-id:'+secrets.token_hex(16)
            manifest={'format':2 if video else 1,'token':token,'root':str(root),'volumes':volumes,'uid':os.getuid(),'gid':os.getgid(),
                      'architecture':platform.machine(),'samba_image':samba['Image'],'samba_hostname':samba['Config']['Hostname'],'repositories':identifiers,
                      'created':datetime.now(timezone.utc).isoformat(),
                      'sha256':{n:checksum(kit/n) for n in captured}}
            write(kit/'manifest.json',manifest)
            # Le journal peut être très volumineux : stockage temporaire hors source,
            # puis lecture ligne par ligne, sans plafond arbitraire ni accumulation RAM.
            with tempfile.TemporaryFile() as output:
                restic(repository,key,'backup','--json','--tag',PENDING,'--tag',token,
                       '--exclude','**/.nacre-repos','--exclude','**/.git','--exclude','**/.tools',
                       '--exclude',str(root/'state/console/updates'),'--exclude',str(root/'state/console/tasks'),'--exclude',str(root/'state/console/restic-cache'),
                       *exclusions,str(root),*volumes.values(),stdout=output)
                output.seek(0);summary=None
                for line in output:
                    item=json.loads(line)
                    if item.get('message_type')=='summary':summary=item
                if not summary or not summary.get('snapshot_id'):raise RecoveryError('Capture sans résumé vérifiable.')
            after,_=offline(root)
            identity=lambda rows:sorted((r['Id'],r['State']['StartedAt']) for r in rows)
            if identity(states)!=identity(after):raise RecoveryError('Les services ont changé pendant la capture : point à écarter.')
            for path,dev,ino in guards:
                st=path.stat(follow_symlinks=False)
                if (st.st_dev,st.st_ino)!=(dev,ino):raise RecoveryError('Un volume source a changé pendant la capture.')
            restic(repository,key,'tag','--add',TAG,summary['snapshot_id'])
            finished=json.loads(restic(repository,key,'snapshots','--json','--tag',token))
            if len(finished)!=1 or TAG not in finished[0]['tags']:raise RecoveryError('Validation finale du point impossible.')
            receipt={'snapshot':finished[0]['id'],'created':manifest['created'],'complete':True,
                     'scope':'installation-files-keys-samba','native_volumes':len(volumes)}
            target=root/'state/console/last-system-recovery.json'
            # Écriture atomique du reçu, sans clé ni chemin du dépôt.
            temporary=target.with_name('.recovery-receipt-'+secrets.token_hex(6))
            write(temporary,receipt);os.replace(temporary,target)
            return receipt
        finally:shutil.rmtree(kit)


def neutralize(root,old_root,manifest):
    dbpath=root/'state/console/console.db'
    with closing(sqlite3.connect(dbpath)) as db:
        db.execute('PRAGMA trusted_schema=OFF')
        check(db)
        if db.execute('PRAGMA user_version').fetchone()[0]!=VERSION:raise RecoveryError('Schéma non qualifié pour cette reprise.')
        if not db.execute("SELECT 1 FROM users WHERE role='admin' AND active=1").fetchone():raise RecoveryError('Administrateur actif absent.')
        db.execute('DELETE FROM sessions');db.execute('DELETE FROM tickets')
        db.execute('UPDATE plans SET enabled=0,next_run=NULL')
        from automatic_retention import disable_after_recovery
        disable_after_recovery(db)
        db.execute("UPDATE repositories SET target='recovery-detached'")
        for identifier,raw in db.execute('SELECT id,config FROM plans').fetchall():
            config=json.loads(raw)
            config['sources']=list(dict.fromkeys('fichiers' if s.startswith('native_') else s for s in config.get('sources',['fichiers'])))
            db.execute('UPDATE plans SET config=? WHERE id=?',(json.dumps(config),identifier))
        db.execute("UPDATE jobs SET status='failed',cancel=1,pid=NULL WHERE status IN ('queued','running')")
        for (identifier,) in db.execute('SELECT id FROM repositories').fetchall():
            db.execute('UPDATE repositories SET key_file=? WHERE id=?',(str(root/'state/console/keys'/(identifier+'.key')),identifier))
        for identifier,original,area in db.execute("SELECT id,original,area FROM trash WHERE area LIKE 'native_%'").fetchall():
            if area not in manifest['volumes'] or not re.fullmatch(r'[a-f0-9]{32}',identifier):raise RecoveryError('Corbeille native non rattachable.')
            source=root/'data/fichiers/reprise-volumes'/area/'.nacre-trash'/identifier
            if source.parent.is_symlink():raise RecoveryError('Corbeille native symlinkée.')
            target=root/'data/.corbeille'/identifier
            if target.exists() or target.is_symlink():raise RecoveryError('Collision de corbeille.')
            if not source.exists() and not source.is_symlink():raise RecoveryError('Contenu de corbeille native absent.')
            source.rename(target)
            db.execute("UPDATE trash SET area='fichiers',original=? WHERE id=?",('reprise-volumes/'+area+'/'+original,identifier))
        db.commit()
    # L’ancien fichier d’accès initial peut être périmé ; les hashes sont conservés.
    shutil.rmtree(root/'state/console/updates',ignore_errors=True)
    (root/'state/console/acces.txt').unlink(missing_ok=True)
    (root/'state/console/recovery-volumes.json').unlink(missing_ok=True)
    (root/'state/samba/volumes.compose.json').unlink(missing_ok=True)
    (root/'state/samba/recovery.compose.json').unlink(missing_ok=True)
    config=json.loads((root/'state/console/smb.json').read_text())
    for share in config['shares']:
        if share['area'].startswith('native_'):
            area=share['area']
            if area not in manifest['volumes']:raise RecoveryError('Partage natif sans données récupérées.')
            share['area']='fichiers'
            share['path']='reprise-volumes/'+area+('/'+share['path'] if share['path'] else '')
    (root/'state/console/smb.json').write_text(json.dumps(config,indent=2))
    from smb_storage import render
    (root/'state/samba/smb.conf').write_text(render(config,{}))
    # Docker ne doit jamais réutiliser le nom de projet ni les volumes de la source.
    (root/'state/console/recovery-project.json').unlink(missing_ok=True)
    write(root/'state/console/recovery-project.json',{'project':'nacre-recovered-'+secrets.token_hex(12)})
    (root/'state/console/smb-intent.json').write_text(json.dumps({'enabled':False}))


def validate_tree(root):
    # Aucun chemin de contrôle symlinké n’est exécuté/interprété à la reprise.
    for relative in ('state','data','data/fichiers','data/video','data/.corbeille','data/sauvegardes','.env'):
        if (root/relative).is_symlink():raise RecoveryError('Racine de configuration ou de données symlinkée.')
    for directory,dirs,files in os.walk(root/'state',followlinks=False):
        for name in [*dirs,*files]:
            path=Path(directory)/name
            if path.is_symlink() or not (path.is_file() or path.is_dir()):
                raise RecoveryError('Objet non ordinaire dans la configuration restaurée.')


def source_directory_metadata(repository,key,snapshot,source):
    # Le restore snapshot:sous-dossier ne réapplique pas les métadonnées du
    # dossier racine à une destination déjà créée. Lire son entrée originale.
    found=None
    with tempfile.TemporaryFile() as output:
        restic(repository,key,'ls','--json',snapshot,source,stdout=output)
        output.seek(0)
        for line in output:
            row=json.loads(line)
            if row.get('path')!=source:continue
            if found is not None or row.get('type')!='dir':raise RecoveryError('Racine de restitution ambiguë.')
            if any(type(row.get(k)) is not int or not 0<=row[k]<2**32-1 for k in ('uid','gid','mode')):
                raise RecoveryError('Propriétaires ou mode de la racine invalides.')
            # restic expose un FileMode Go : bits spéciaux distincts de chmod.
            mode=row['mode'];permissions=mode&0o777
            for flag,unix in ((1<<23,0o4000),(1<<22,0o2000),(1<<20,0o1000)):
                if mode&flag:permissions|=unix
            found=(row['uid'],row['gid'],format(permissions,'04o'))
    if found is None:raise RecoveryError('Métadonnées de la racine absentes du point.')
    return found


def prepare(repository,key,snapshot,destination):
    repository=Path(repository).resolve();key=Path(key).resolve()
    destination=Path(destination).absolute()
    if any(',' in str(p) for p in (repository,key,destination)):raise RecoveryError('Les chemins de reprise ne doivent pas contenir de virgule.')
    private_directory(destination.parent)
    if destination.exists() or destination.is_symlink():raise RecoveryError('La destination doit être nouvelle.')
    if not re.fullmatch(r'[a-f0-9]{64}',snapshot):raise RecoveryError('Choisir l’identifiant complet et exact du point.')
    points=json.loads(restic(repository,key,'snapshots','--json',snapshot))
    if len(points)!=1 or TAG not in points[0].get('tags',[]):raise RecoveryError('Ce point n’est pas une reprise d’installation.')
    paths=points[0]['paths']
    if not paths or any(not p.startswith('/') or '..' in PurePosixPath(p).parts for p in paths):raise RecoveryError('Sources du point invalides.')
    manifest=None
    for candidate in paths:
        try:value=json.loads(restic(repository,key,'dump',snapshot,candidate+'/state/recovery-kit/manifest.json'))
        except (RecoveryError,ValueError):continue
        if manifest is not None:raise RecoveryError('Plusieurs installations dans le même point.')
        manifest=value
    if not isinstance(manifest,dict) or manifest.get('format') not in (1,2):raise RecoveryError('Manifest de reprise absent ou invalide.')
    if manifest.get('token') not in points[0].get('tags',[]):raise RecoveryError('Identité du kit incohérente.')
    if manifest.get('architecture')!=platform.machine():raise RecoveryError('Architecture de l’image Samba non qualifiée pour cette cible.')
    if (manifest['uid'],manifest['gid'])!=(os.getuid(),os.getgid()):raise RecoveryError('Utiliser un compte cible de mêmes UID/GID ; remappage non qualifié.')
    if set(paths)!={manifest['root'],*manifest['volumes'].values()}:raise RecoveryError('Périmètre de capture incohérent.')
    image=manifest['samba_image']
    if not re.fullmatch(r'sha256:[a-f0-9]{64}',image):raise RecoveryError('Image de récupération invalide.')
    binary=Path(os.environ.get('NAS_RESTIC_BIN') or shutil.which('restic') or SOURCE/'.tools/restic').resolve()
    with tempfile.TemporaryDirectory(prefix='.nacre-restore-',dir=destination.parent) as temporary:
        scratch=Path(temporary)
        package=scratch/'image.tar'
        with package.open('wb') as stream:
            run([binary,'--repo',repository,'--password-file',key,'--no-cache','dump',snapshot,manifest['root']+'/state/recovery-kit/samba-image.tar'],stdout=stream)
        if checksum(package)!=manifest['sha256']['samba-image.tar']:raise RecoveryError('Empreinte de l’image de reprise incorrecte.')
        with package.open('rb') as stream:run(['docker','image','load'],stdin=stream)
        run(['docker','image','inspect',image])
        def restore_tree(source,target):
            uid,gid,mode=source_directory_metadata(repository,key,snapshot,source)
            target.mkdir(mode=0o700,parents=True)
            # Root seulement dans un conteneur sans réseau, avec écriture limitée
            # à une nouvelle destination. Les UID/GID des données sont préservés.
            args=['docker','run','--rm','--network','none','--read-only','--cap-drop','ALL',
                  '--cap-add','CHOWN','--cap-add','FOWNER','--cap-add','DAC_OVERRIDE',
                  '--security-opt','no-new-privileges',
                  '--mount','type=bind,source='+str(Path(repository).resolve())+',target=/repository,readonly',
                  '--mount','type=bind,source='+str(Path(key).resolve())+',target=/recovery-key,readonly',
                  '--mount','type=bind,source='+str(binary)+',target=/recovery-restic,readonly',
                  '--mount','type=bind,source='+str(target)+',target=/restore',
                  '--entrypoint','/recovery-restic',image,'--repo','/repository','--password-file','/recovery-key','--no-cache','--no-lock',
                  'restore',snapshot+':'+source,'--target','/restore','--overwrite','never','--sparse','--verify']
            run(args)
            # Seule la nouvelle racine est modifiée, après copie vérifiée. Les
            # descendants ont leurs métadonnées restaurées par restic.
            run(['docker','run','--rm','--network','none','--read-only','--cap-drop','ALL',
                 '--cap-add','CHOWN','--cap-add','FOWNER','--security-opt','no-new-privileges',
                 '--mount','type=bind,source='+str(target)+',target=/restore',
                 '--entrypoint','/bin/sh',image,'-c','chown "$1:$2" /restore && chmod "$3" /restore',
                 'sh',str(uid),str(gid),mode])
        root=scratch/'installation';restore_tree(manifest['root'],root);validate_tree(root)
        for name in ('samba.tar','samba-image.tar'):
            if checksum(root/'state/recovery-kit'/name)!=manifest['sha256'][name]:raise RecoveryError('Empreinte du kit invalide.')
        tar_safe(root/'state/recovery-kit/samba.tar')
        restore_video_config(root,image,manifest)
        validate_tree(root)
        for area,source in manifest['volumes'].items():
            if not re.fullmatch(r'native_[a-z][a-z0-9_-]{0,80}',area):raise RecoveryError('Volume invalide.')
            folder=scratch/'volumes'/area
            restore_tree(source,folder)
            target=root/'data/fichiers/reprise-volumes'/area
            if target.parent.is_symlink():raise RecoveryError('Destination des volumes symlinkée.')
            target.parent.mkdir(mode=0o770,parents=True,exist_ok=True)
            target.parent.chmod(0o770)
            if target.exists():raise RecoveryError('Destination de volume déjà occupée.')
            folder.rename(target)
        neutralize(root,manifest['root'],manifest)
        # Les références finales doivent utiliser le nouveau chemin, pas le staging.
        with closing(sqlite3.connect(root/'state/console/console.db')) as db:
            for (identifier,) in db.execute('SELECT id FROM repositories').fetchall():
                db.execute('UPDATE repositories SET key_file=? WHERE id=?',(str(destination/'state/console/keys'/(identifier+'.key')),identifier))
            db.commit()
        (root/'state/console/recovery-repositories.json').unlink(missing_ok=True)
        write(root/'state/console/recovery-repositories.json',manifest['repositories'])
        (root/'state/console/system-recovery-status.json').unlink(missing_ok=True)
        write(root/'state/console/system-recovery-status.json',{'restored_from':snapshot,'prepared_at':datetime.now(timezone.utc).isoformat(),'samba_ready':False,'plans_enabled':False})
        # Copier du code approuvé depuis cette version, jamais exécuter le code sauvegardé.
        for name in ('console','samba','frigate'):
            shutil.rmtree(root/name,ignore_errors=True)
            shutil.copytree(SOURCE/name,root/name,ignore=shutil.ignore_patterns('__pycache__'))
        for name in ('compose.yaml','compose_support.py','platform_config.py','lab.py','verifier.py'):
            (root/name).unlink(missing_ok=True);shutil.copyfile(SOURCE/name,root/name)
        root.chmod(0o700)
        # renameat2 NOREPLACE empêche toute substitution apparue pendant la préparation.
        from server import rename_noreplace
        parent=os.open(destination.parent,os.O_RDONLY|os.O_DIRECTORY)
        source_parent=os.open(root.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:rename_noreplace(source_parent,root.name,parent,destination.name)
        finally:os.close(parent);os.close(source_parent)
        sync_directory(destination.parent)
    return {'prepared':str(destination),'services_started':False,'plans_enabled':False,'repositories_to_reconnect':len(manifest['repositories'])}


def samba_restore(root):
    root=Path(root).resolve()
    with held(root,True):
        status=root/'state/console/system-recovery-status.json'
        private_file(status)
        manifest=json.loads((root/'state/recovery-kit/manifest.json').read_text())
        marker=root/'state/samba/recovery.compose.json'
        if marker.exists():raise RecoveryError('État Samba déjà préparé ; aucun volume existant ne sera remplacé.')
        for name in ('samba.tar','samba-image.tar'):
            if checksum(root/'state/recovery-kit'/name)!=manifest['sha256'][name]:raise RecoveryError('Empreinte Samba incorrecte.')
        tar_safe(root/'state/recovery-kit/samba.tar')
        image=manifest['samba_image']
        if not re.fullmatch(r'sha256:[a-f0-9]{64}',image):raise RecoveryError('Image Samba invalide.')
        with (root/'state/recovery-kit/samba-image.tar').open('rb') as stream:run(['docker','image','load'],stdin=stream)
        run(['docker','image','inspect',image])
        volume='nacre-recovered-samba-'+secrets.token_hex(12)
        container='nacre-recovery-'+secrets.token_hex(12)
        run(['docker','volume','create','--label','nacre.recovery=true',volume])
        created=False
        try:
            run(['docker','create','--name',container,'--network','none','--mount','type=volume,source='+volume+',target=/var/lib/samba','--entrypoint','/bin/true',image]);created=True
            with (root/'state/recovery-kit/samba.tar').open('rb') as stream:run(['docker','cp','-a','-',container+':/var/lib/samba/'],stdin=stream)
            write(marker,{'services':{'fichiers':{'image':image,'hostname':manifest['samba_hostname']}},'volumes':{'samba-state':{'external':True,'name':volume}}})
        finally:
            # Seul le conteneur auxiliaire créé ici est supprimé ; le volume reste récupérable.
            if created:run(['docker','rm',container])
        status=root/'state/console/system-recovery-status.json'
        receipt=json.loads(status.read_text());receipt['samba_ready']=True
        temporary=status.with_name('.recovery-status-'+secrets.token_hex(6));write(temporary,receipt);os.replace(temporary,status)
        shutil.rmtree(root/'state/recovery-kit')
        return {'samba_volume_prepared':True,'services_started':False,'volume':volume}


def attach(root,identifier,path):
    root=Path(root).resolve();path=Path(path).resolve()
    with held(root,True):
        expected=json.loads((root/'state/console/recovery-repositories.json').read_text())
        if identifier not in expected:raise RecoveryError('Dépôt absent de l’inventaire de reprise.')
        key=root/'state/console/keys'/(identifier+'.key')
        observed=json.loads(restic(path,key,'cat','config'))['id']
        if observed!=expected[identifier]:raise RecoveryError('L’identité du dépôt ne correspond pas à la sauvegarde.')
        with closing(sqlite3.connect(root/'state/console/console.db')) as db:
            db.execute("UPDATE repositories SET path=?,key_file=?,target='recovered',storage_uuid='' WHERE id=?",(str(path),str(key),identifier));db.commit()
        return {'repository_attached':identifier,'plans_enabled':False}


def export_native():
    if os.geteuid()!=0:raise RecoveryError('L’export natif doit être effectué par l’administrateur système.')
    from native_storage import read_policy, POLICY, STATE
    policy=read_policy(POLICY)
    with tempfile.TemporaryDirectory(prefix='nacre-native-export-') as name:
        root=Path(name)
        write(root/'policy.json',policy)
        with closing(readonly(Path(STATE)/'catalog.db')) as source, closing(sqlite3.connect(root/'catalog.db')) as target:
            tables={r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'native_jobs' in tables and source.execute("SELECT 1 FROM native_jobs WHERE status IN ('queued','running')").fetchone():
                raise RecoveryError('Attendre ou arrêter les copies natives avant export.')
            source.backup(target);check(target)
        with tarfile.open(fileobj=sys.stdout.buffer,mode='w|') as archive:
            for filename in ('policy.json','catalog.db'):archive.add(root/filename,arcname=filename,recursive=False)


def status(root):
    """État administratif sans mot de passe, chemin privé ni opération Docker."""
    root=Path(root);directory=root/'state/console'
    with closing(readonly(directory/'console.db')) as db:
        rows=db.execute('SELECT id,target FROM repositories').fetchall()
        plans=db.execute('SELECT count(*) FROM plans WHERE enabled=1').fetchone()[0]
    missing=0
    for identifier,_ in rows:
        try:private_file(directory/'keys'/(identifier+'.key'))
        except (OSError,RuntimeError):missing+=1
    def record(name,fields):
        path=directory/name
        if not path.exists():return None
        private_file(path)
        value=json.loads(path.read_text())
        return {k:value[k] for k in fields if k in value}
    return {'scope':'installation-files-keys-samba','offline_only':True,
            'repositories':len(rows),'missing_keys':missing,'enabled_plans':plans,
            'detached_repositories':sum(target=='recovery-detached' for _,target in rows),
            'last_capture':record('last-system-recovery.json',('snapshot','created','complete','native_volumes')),
            'restoration':record('system-recovery-status.json',('prepared_at','samba_ready'))}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    for name in ('capture','prepare'):
        p=sub.add_parser(name);p.add_argument('--repository',required=True);p.add_argument('--key-file',required=True)
        if name=='capture':p.add_argument('--root',type=Path,required=True)
        else:p.add_argument('--snapshot',required=True);p.add_argument('--destination',type=Path,required=True)
    p=sub.add_parser('samba');p.add_argument('--root',type=Path,required=True)
    p=sub.add_parser('attach');p.add_argument('--root',type=Path,required=True);p.add_argument('--id',required=True);p.add_argument('--path',required=True)
    sub.add_parser('native-export',help='Exporter sur stdout la politique et le catalogue natifs, en administrateur')
    a=parser.parse_args();os.umask(0o077)
    try:
        if a.command=='native-export':
            export_native();return
        if a.command=='capture':result=capture(a.root,a.repository,a.key_file)
        elif a.command=='prepare':result=prepare(a.repository,a.key_file,a.snapshot,a.destination)
        elif a.command=='samba':result=samba_restore(a.root)
        else:result=attach(a.root,a.id,a.path)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except (RecoveryError,RuntimeError,OSError,ValueError,KeyError,sqlite3.Error) as error:
        parser.exit(1, 'Reprise non aboutie : '+(str(error) if isinstance(error,RuntimeError) else 'état ou fichier invalide ; aucun succès supposé.')+'\n')


if __name__=='__main__':main()
