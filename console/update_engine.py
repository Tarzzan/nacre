"""Stable update supervisor. Installed outside replaceable code; stdlib + OpenSSL.

Web packages cannot change this engine, the trust anchor, schema or native helper.
No package hook is executed. See docs/BROWSER-UPDATES.md for the recovery contract.
"""
import ast
from contextlib import contextmanager, closing
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import shutil
import signal
import sqlite3
import subprocess
import sys
import tarfile
import time
from urllib.request import Request, urlopen

FORMAT=1
MAX_PACKAGE=32*1024**2
MAX_EXPANDED=128*1024**2
ACTIVE={'queued','backing_up','installing','verifying','rolling_back'}
PINNED={'console/update_engine.py','console/update-signing.pub','console/schema.py','console/installation_lock.py','console/install_service.py','console/native_storage.py','console/provisioning.py','console/native_restore.py','console/mirror_repair.py'}
REQUIRED=PINNED|{'console/server.py','console/updates.py','console/release.py','console/static/index.html','console/static/app.js','CHANGELOG.md','lab.py'}

class UpdateError(RuntimeError):pass

def area(root):return Path(root)/'state/console/updates'
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def sync(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)
def write(path,content):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if path.is_symlink():raise UpdateError('Lien symbolique refusé.')
    temp=path.with_name(path.name+'.'+secrets.token_hex(8))
    fd=os.open(temp,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(content);stream.flush();os.fsync(stream.fileno())
        os.replace(temp,path);sync(path.parent)
    finally:temp.unlink(missing_ok=True)
def save(path,value):write(path,(json.dumps(value,ensure_ascii=False,sort_keys=True)+'\n').encode())
def read(path,default=None):
    try:return json.loads(Path(path).read_text())
    except FileNotFoundError:return default

def code_path(name):
    if not isinstance(name,str):return False
    p=PurePosixPath(name)
    return isinstance(name,str) and not p.is_absolute() and '..' not in p.parts and str(p)==name and (
        name=='CHANGELOG.md' or (len(p.parts)==1 and p.suffix=='.py') or
        (len(p.parts)==2 and p.parts[0]=='console' and (p.suffix=='.py' or p.name=='update-signing.pub')) or
        (len(p.parts)==3 and p.parts[:2]==('console','static') and p.suffix in ('.js','.css','.html','.svg')))
def safe(root,name):
    if not code_path(name):raise UpdateError('Chemin de code non autorisé.')
    target=Path(root)/name
    for p in (target,*target.parents):
        if p==Path(root):break
        if p.is_symlink():raise UpdateError('Lien symbolique dans le code installé.')
    if target.exists() and not target.is_file():raise UpdateError('Chemin de code non ordinaire.')
    return target
def inventory(root):
    paths=[*Path(root).glob('*.py'),Path(root)/'CHANGELOG.md',*Path(root).glob('console/*.py'),Path(root)/'console/update-signing.pub',*Path(root).glob('console/static/*')]
    return {str(p.relative_to(root)):sha(safe(root,str(p.relative_to(root)))) for p in paths if code_path(str(p.relative_to(root))) and p.is_file()}
def version(root):
    match=re.search(r'^## (\d+\.\d+\.\d+(?:-[A-Za-z0-9.]+)?)\s+—',(Path(root)/'CHANGELOG.md').read_text(),re.M)
    if not match:raise UpdateError('Version du code non identifiée.')
    return match[1]
def db_version(root):
    with closing(sqlite3.connect(Path(root)/'state/console/console.db')) as db:return db.execute('PRAGMA user_version').fetchone()[0]

def state(root):return read(area(root)/'status.json',{'phase':'idle'})
def set_state(root,phase,**values):
    result={**state(root),**values,'phase':phase,'updated_at':time.time()};save(area(root)/'status.json',result);return result

@contextmanager
def guard(root):
    folder=area(root);folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd=os.open(folder/'request.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise UpdateError('Une préparation de mise à jour est déjà en cours.') from None
        yield
    finally:os.close(fd)

@contextmanager
def exclusive(root):
    fd=os.open(Path(root)/'state/console/installation.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise UpdateError('Une tâche utilise encore l’installation.') from None
        yield
    finally:os.close(fd)

def idle(root):
    with closing(sqlite3.connect(Path(root)/'state/console/console.db')) as db:
        if db.execute("SELECT 1 FROM jobs WHERE status IN ('queued','running') LIMIT 1").fetchone():
            raise UpdateError('Attendez la fin des tâches avant la mise à jour.')

def installed(root):
    baseline=read(area(root)/'baseline.json')
    if not baseline or inventory(root)!=baseline['files']:raise UpdateError('Le code local a changé. Une préparation administrateur est nécessaire.')
    if sha(area(root)/'runtime.py')!=baseline['files']['console/update_engine.py']:raise UpdateError('Superviseur incompatible.')
    if sha(area(root)/'trust.pub')!=baseline['files']['console/update-signing.pub']:raise UpdateError('Clé de vérification incompatible.')
    return baseline

def verify(root,package,destination):
    if Path(package).stat().st_size>MAX_PACKAGE:raise UpdateError('Paquet de mise à jour trop volumineux (32 Mio).')
    destination=Path(destination);destination.mkdir(mode=0o700)
    with tarfile.open(package,'r:gz') as archive:
        members=[];total=0
        for member in archive:
            members.append(member);total+=member.size
            if len(members)>1024 or total>MAX_EXPANDED:raise UpdateError('Paquet de mise à jour hors limites.')
        names=[m.name for m in members]
        if len(set(names))!=len(names) or any(not m.isfile() or m.size<0 for m in members):raise UpdateError('Archive ambiguë ou non ordinaire.')
        if not {'manifest.json','manifest.sig'}.issubset(names):raise UpdateError('Signature du paquet absente.')
        for special,limit in [('manifest.json',256*1024),('manifest.sig',1024)]:
            m=archive.getmember(special)
            if m.size>limit:raise UpdateError('Manifest trop volumineux.')
            write(destination/special,archive.extractfile(m).read())
        try:
            subprocess.run(['openssl','pkeyutl','-verify','-pubin','-inkey',str(area(root)/'trust.pub'),'-rawin','-in',str(destination/'manifest.json'),'-sigfile',str(destination/'manifest.sig')],check=True,capture_output=True,timeout=10)
        except (OSError,subprocess.SubprocessError):raise UpdateError('Signature du paquet refusée.') from None
        manifest=read(destination/'manifest.json')
        if not isinstance(manifest,dict):raise UpdateError('Manifeste invalide.')
        files=manifest.get('files')
        if manifest.get('format')!=FORMAT or manifest.get('schema')!=db_version(root) or not isinstance(files,dict) or not REQUIRED.issubset(files):raise UpdateError('Format ou schéma non compatible avec le retour arrière automatique.')
        if set(names)!={'manifest.json','manifest.sig',*('code/'+n for n in files)}:raise UpdateError('Contenu différent du manifeste signé.')
        for name,digest in files.items():
            if not code_path(name) or not isinstance(digest,str) or not re.fullmatch('[a-f0-9]{64}',digest):raise UpdateError('Entrée de code invalide.')
            content=archive.extractfile('code/'+name).read()
            if hashlib.sha256(content).hexdigest()!=digest:raise UpdateError('Empreinte du code incorrecte.')
            if name.endswith('.py'):
                try:ast.parse(content,filename=name)
                except (SyntaxError,ValueError):raise UpdateError('Code Python invalide.') from None
            write(destination/'code'/name,content)
    baseline=installed(root)
    if any(files.get(n)!=baseline['files'].get(n) for n in PINNED):raise UpdateError('Cette version modifie le schéma, le superviseur ou le service natif : installation accompagnée requise.')
    if version(destination/'code')!=manifest.get('version') or not re.fullmatch('[a-f0-9]{40}',str(manifest.get('commit',''))):raise UpdateError('Version ou provenance incohérente.')
    return manifest

def prepare(root,package):
    with guard(root):
        if state(root)['phase'] in ACTIVE:raise UpdateError('Une mise à jour est déjà engagée.')
        installed(root)
        identifier=secrets.token_hex(12);folder=area(root)/identifier
        try:manifest=verify(root,package,folder)
        except BaseException:
            shutil.rmtree(folder,ignore_errors=True);raise
        current=version(root)
        # No implicit downgrades: normal releases advance numeric versions/alpha counters.
        def order(v):
            m=re.fullmatch(r'(\d+)\.(\d+)\.(\d+)(?:-alpha\.(\d+))?',v)
            if not m:raise UpdateError('Canal de version non pris en charge.')
            return tuple(map(int,m.groups()[:3]))+(int(m[4]) if m[4] else 10**12,)
        try:
            if order(manifest['version'])<order(current):raise UpdateError('Une ancienne version ne peut pas être installée par ce parcours.')
        except UpdateError:
            shutil.rmtree(folder,ignore_errors=True);raise
        set_state(root,'prepared',id=identifier,version=manifest['version'],previous_version=current,commit=manifest['commit'],prepared_at=time.time(),error=None,actor=None)
        return state(root)

def request(root,identifier,actor):
    with guard(root):
        s=state(root)
        if s['phase']!='prepared' or s.get('id')!=identifier or time.time()-s['prepared_at']>3600:raise UpdateError('Préparation expirée ou remplacée. Importez à nouveau le paquet.')
        installed(root);idle(root)
        set_state(root,'queued',actor=actor)

def backup(root):
    s=state(root);folder=area(root)/s['id'];baseline=installed(root);idle(root)
    need=sum((Path(root)/n).stat().st_size for n in baseline['files'])+sum(p.stat().st_size for p in (Path(root)/'state/console').glob('console.db*'))
    if shutil.disk_usage(root).free<need*3+16*1024**2:raise UpdateError('Espace insuffisant pour la copie préalable et le retour arrière.')
    for name in baseline['files']:write(folder/'before'/name,safe(root,name).read_bytes())
    save(folder/'before.json',baseline)
    with closing(sqlite3.connect(Path(root)/'state/console/console.db')) as source,closing(sqlite3.connect(folder/'before.sqlite3')) as target:
        source.backup(target)
        if target.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise UpdateError('Copie de base non valide.')
    with (folder/'before.sqlite3').open('rb') as stream:os.fsync(stream.fileno())
    save(folder/'before.json',{**baseline,'database_sha256':sha(folder/'before.sqlite3')})
    sync(folder);set_state(root,'installing')

def replace(root):
    s=state(root);folder=area(root)/s['id'];manifest=read(folder/'manifest.json');before=read(folder/'before.json')
    # Recheck signature and bytes at the point of use, before replacing anything.
    try:
        subprocess.run(['openssl','pkeyutl','-verify','-pubin','-inkey',str(area(root)/'trust.pub'),'-rawin','-in',str(folder/'manifest.json'),'-sigfile',str(folder/'manifest.sig')],check=True,capture_output=True,timeout=10)
    except (OSError,subprocess.SubprocessError):raise UpdateError('Signature préparée modifiée.') from None
    if manifest['version']!=s['version'] or manifest['commit']!=s['commit']:raise UpdateError('Préparation remplacée.')
    if any(sha(folder/'code'/n)!=h for n,h in manifest['files'].items()):raise UpdateError('Code préparé modifié.')
    for name in manifest['files']:write(safe(root,name),(folder/'code'/name).read_bytes())
    for name in before['files'].keys()-manifest['files'].keys():
        target=safe(root,name);target.unlink();sync(target.parent)
    set_state(root,'verifying')

def rollback(root):
    s=state(root);folder=area(root)/s['id'];before=read(folder/'before.json');manifest=read(folder/'manifest.json')
    if not before or any(sha(folder/'before'/n)!=h for n,h in before['files'].items()):raise UpdateError('Copie de code précédente non valide : reprise manuelle nécessaire.')
    if sha(folder/'before.sqlite3')!=before.get('database_sha256'):raise UpdateError('Copie de base modifiée : reprise manuelle nécessaire.')
    set_state(root,'rolling_back')
    for name in before['files']:write(safe(root,name),(folder/'before'/name).read_bytes())
    for name in manifest['files'].keys()-before['files'].keys():
        target=safe(root,name);target.unlink(missing_ok=True);sync(target.parent)
    with closing(sqlite3.connect(folder/'before.sqlite3')) as source,closing(sqlite3.connect(Path(root)/'state/console/console.db')) as target:
        if source.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise UpdateError('Copie de base non valide.')
        source.backup(target);target.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    save(area(root)/'baseline.json',before)
    set_state(root,'rolled_back',error='La nouvelle version n’a pas été confirmée. Code et base précédents restaurés.')

def provision(root):
    root=Path(root).resolve();folder=area(root)
    if not shutil.which('openssl'):raise UpdateError('Installer OpenSSL avant d’activer les mises à jour signées.')
    folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    if folder.is_symlink() or folder.stat().st_mode&0o077:raise UpdateError('Le répertoire de mise à jour doit être privé.')
    if state(root)['phase'] in ACTIVE:raise UpdateError('Mise à jour engagée : ne pas remplacer le superviseur.')
    files=inventory(root)
    if not REQUIRED.issubset(files):raise UpdateError('Installation du code incomplète.')
    if (folder/'runtime.py').exists():
        installed(root);return
    write(folder/'runtime.py',(root/'console/update_engine.py').read_bytes())
    write(folder/'trust.pub',(root/'console/update-signing.pub').read_bytes())
    save(folder/'baseline.json',{'files':files,'version':version(root)})

def identity(pid):
    try:return Path('/proc',str(pid),'stat').read_text().split(') ',1)[1].split()[19]
    except FileNotFoundError:return None

def terminate(root,process=None):
    saved=read(area(root)/'child.json',{})
    pid=saved.get('pid')
    if pid and identity(pid)==saved.get('start'):
        # Only our still-identical process group, never an unrelated reused PID.
        if os.getpgid(pid)!=pid:raise UpdateError('Processus console inattendu.')
        os.killpg(pid,signal.SIGTERM)
        for _ in range(50):
            if process:process.poll()
            if identity(pid)!=saved['start']:break
            time.sleep(.1)
        else:os.killpg(pid,signal.SIGKILL)
    if process:
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:raise UpdateError('La console ne s’arrête pas.') from None

def launch(root,port,probe=None):
    env={**os.environ,'NAS_ROOT':str(root),'NAS_PORT':str(port),'NACRE_SUPERVISED':'1'}
    if probe:env['NACRE_UPDATE_PROBE']=probe
    else:env.pop('NACRE_UPDATE_PROBE',None)
    process=subprocess.Popen([sys.executable,str(Path(root)/'console/server.py')],cwd=root,env=env,start_new_session=True)
    save(area(root)/'child.json',{'pid':process.pid,'start':identity(process.pid)})
    return process

def healthy(root,port,process,nonce,expected,timeout=45):
    deadline=time.monotonic()+timeout;success=0
    while time.monotonic()<deadline:
        if process.poll() is not None:return False
        try:
            req=Request(f'http://127.0.0.1:{port}/api/update-health',headers={'X-Nacre-Update-Probe':nonce})
            with urlopen(req,timeout=1) as response:data=json.load(response)
            if data!={'version':expected,'schema':db_version(root),'ready':True}:return False
            success+=1
            if success>=3:return True
        except (OSError,ValueError):success=0
        time.sleep(.5)
    return False

def perform(root,port,process):
    with guard(root):
        try:
            installed(root);idle(root)
            terminate(root,process);process=None
            with exclusive(root):
                set_state(root,'backing_up');backup(root);replace(root)
            nonce=secrets.token_urlsafe(32);s=state(root)
            process=launch(root,port,nonce)
            if not healthy(root,port,process,nonce,s['version']):raise UpdateError('Nouvelle console non disponible.')
            manifest=read(area(root)/s['id']/'manifest.json')
            save(area(root)/'baseline.json',{'files':manifest['files'],'version':s['version']})
            set_state(root,'succeeded',error=None)
            return process
        except Exception:
            if state(root)['phase'] in {'installing','verifying','rolling_back'}:
                terminate(root,process);process=None
                with exclusive(root):rollback(root)
            else:set_state(root,'failed',error='Préparation interrompue ou installation occupée. Le code précédent est conservé.')
            return process if process is not None and process.poll() is None else launch(root,port)

def supervise(root,port):
    root=Path(root).resolve();os.umask(0o077)
    fd=os.open(area(root)/'supervisor.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    # A killed supervisor may have left its child alive (non-systemd tests too).
    terminate(root)
    with exclusive(root):
        s=state(root)
        if s['phase'] in {'installing','verifying','rolling_back'}:rollback(root)
        elif s['phase'] in ACTIVE:set_state(root,'failed',error='Redémarrage avant installation : code précédent conservé.')
    process=launch(root,port)
    stopping=False;last_heartbeat=0
    def stop(*_):
        nonlocal stopping
        stopping=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    try:
        while not stopping:
            if time.monotonic()-last_heartbeat>=10:
                save(area(root)/'heartbeat.json',{'pid':os.getpid(),'updated_at':time.time()});last_heartbeat=time.monotonic()
            if state(root)['phase']=='queued':process=perform(root,port,process)
            if process.poll() is not None:
                time.sleep(2);process=launch(root,port)
            time.sleep(.5)
    finally:terminate(root,process);os.close(fd)

if __name__=='__main__':
    supervise(Path(sys.argv[1]),int(sys.argv[2]))
