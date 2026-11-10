"""Dépôts chiffrés, snapshots de fichiers et plans portables, sans destination implicite."""
from datetime import datetime, time as day_time, timedelta, timezone
from contextlib import closing
import fcntl
import base64
import json
import os
from pathlib import Path
import re
import secrets
import selectors
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def next_occurrence(config, now=None):
    zone = ZoneInfo(config.get('timezone', 'UTC'))
    moment = datetime.fromtimestamp(time.time() if now is None else now, timezone.utc)
    local = moment.astimezone(zone)
    hour, minute = map(int, config['time'].split(':'))
    days = config.get('weekdays', list(range(7)))
    for offset in range(15):
        date = local.date() + timedelta(days=offset)
        if date.weekday() not in days:
            continue
        candidate = datetime.combine(date, day_time(hour, minute), tzinfo=zone)
        back = candidate.astimezone(timezone.utc).astimezone(zone)
        if (back.hour, back.minute, back.date()) != (hour, minute, date):
            continue  # Heure locale inexistante lors du changement d’heure.
        if candidate.astimezone(timezone.utc) > moment:
            return candidate.timestamp()
    raise ValueError('Aucune prochaine exécution calculable.')


class Protection:
    def __init__(self, app):
        self.app = app
        self.schedule_lock = threading.Lock()

    def initialize(self):
        for name in ('keys', 'tasks', 'restic-cache'):
            (self.app.STATE / name).mkdir(mode=0o700, exist_ok=True)
        (self.app.ROOT / 'data/restaurations').mkdir(mode=0o700, exist_ok=True)
    def binary(self):
        candidate = os.environ.get('NAS_RESTIC_BIN') or str(self.app.ROOT / '.tools/restic')
        if Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
        return shutil.which('restic')

    def capabilities(self):
        binary = self.binary()
        version = None
        if binary:
            try:
                version = ' '.join(subprocess.run([binary, 'version'], capture_output=True, text=True, timeout=5).stdout.splitlines()[0].split()[:2])
            except (OSError, IndexError, subprocess.TimeoutExpired):
                binary = None
        return {'available': bool(binary), 'version': version, 'snapshots': 'file-level',
                'native_volume_snapshot': False, 'automatic_plans_default': 'disabled',
                'upload_size_limit': None, 'backup_size_limit': None, 'file_count_limit': None,
                'note': 'Snapshots chiffrés et dédupliqués de fichiers. Ils ne figent pas atomiquement tout un volume.'}

    def sources(self):
        return [a for a in self.app.file_areas(True) if a['id']=='fichiers' or a['kind']=='volume']

    def validate_sources(self,values=None,allow_unavailable=False):
        values=['fichiers'] if values is None else values
        if not isinstance(values,list) or not values or any(not isinstance(v,str) for v in values):
            raise self.app.Problem('Choisir au moins un espace de fichiers à sauvegarder.')
        available={a['id'] for a in self.sources()}
        for value in values:
            if value not in available and not (allow_unavailable and re.fullmatch(r'native_managed-[a-f0-9]{20}',value)):
                raise self.app.Problem('Un volume source est absent ou non autorisé.',503)
        return list(dict.fromkeys(values))

    def targets(self):
        targets = [{'id': 'local', 'label': 'Volume de l’application', 'path': str(self.app.ROOT / 'data/sauvegardes'), 'external': False}]
        try:
            result = subprocess.run(['findmnt', '-J', '-l', '-o', 'TARGET,SOURCE,FSTYPE'], capture_output=True, text=True, timeout=5)
            mounts = json.loads(result.stdout).get('filesystems', [])
        except (OSError, ValueError, subprocess.TimeoutExpired):
            mounts = []
        for mount in mounts:
            path = mount.get('target', '')
            if path.startswith(('/mnt/', '/media/', '/run/media/')) and os.path.isdir(path) and os.access(path, os.W_OK):
                targets.append({'id': self.app.digest(path)[:16], 'label': path, 'path': str(Path(path).resolve()), 'external': True})
        for r in self.app.native_resources():
            if r.get('kind')=='volume' and r.get('writable') and os.access(r['path'],os.W_OK):
                targets.append({'id':'native_'+r['id'],'label':r['name'],'path':r['path'],'external':True,'storage_uuid':r['filesystem_uuid'],'identity':r['identity']})
        return targets

    def repository(self, identifier):
        with self.app.database() as db:
            row = db.execute('SELECT * FROM repositories WHERE id=?', (identifier,)).fetchone()
        if not row:
            raise self.app.Problem('Dépôt inconnu.', 404)
        value=dict(row)
        if value['target']=='recovery-detached':
            raise self.app.Problem('Raccorder ce dépôt avec la procédure de reprise avant de l’utiliser.',503)
        if value['target'].startswith('native_'):
            resource=self.app.resolve_area(value['target'])
            if resource.get('kind')!='volume' or resource.get('filesystem_uuid')!=value['storage_uuid'] or str(Path(resource['path'])/'.nacre-repos'/value['id'])!=value['path']:
                raise self.app.Problem('La destination ne correspond plus au volume du dépôt.',503)
        if value['target']=='recovered':
            expected=json.loads((self.app.STATE/'recovery-repositories.json').read_text())[identifier]
            if json.loads(self.checked(value,'cat','config'))['id']!=expected:
                raise self.app.Problem('Le dépôt raccordé a changé d’identité.',503)
        return value

    def repositories(self):
        with self.app.database() as db:
            return [dict(r) for r in db.execute('SELECT id,name,path,target,created FROM repositories ORDER BY created')]

    def args(self, repository, *operation):
        binary = self.binary()
        if not binary:
            raise self.app.Problem('Le runtime restic doit être installé sur le serveur cible.', 503)
        return [binary, '--repo', repository['path'], '--password-file', repository['key_file'],
                '--cache-dir', str(self.app.STATE / 'restic-cache'), *operation]

    def checked(self, repository, *operation, timeout=30):
        result = subprocess.run(self.args(repository, *operation), capture_output=True, text=True, timeout=timeout)
        if result.returncode:
            raise self.app.Problem({10: 'Dépôt absent.', 11: 'Le dépôt est utilisé par une autre opération.', 12: 'Clé de dépôt refusée.'}.get(result.returncode, 'Le dépôt n’a pas accepté cette opération.'), 503)
        return result.stdout

    def create_repository(self, body, username):
        name = self.app.safe_name(body['name'])
        password = body.get('password', '')
        if not 12 <= len(password) <= 1024 or '\n' in password or '\x00' in password:
            raise self.app.Problem('Choisir une clé de dépôt de 12 caractères minimum, sur une seule ligne.')
        target = next((x for x in self.targets() if x['id'] == body.get('target')), None)
        if not target:
            raise self.app.Problem('Destination indisponible.')
        identifier = secrets.token_hex(12)
        base = Path(target['path'])
        base_fd = os.open(base, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            meta=os.fstat(base_fd)
            if target.get('identity') and target['identity']!={'dev':meta.st_dev,'ino':meta.st_ino}:
                raise self.app.Problem('Le volume de destination a changé.',503)
            try:
                os.mkdir('.nacre-repos', 0o700, dir_fd=base_fd)
            except FileExistsError:
                pass
            fd = os.open('.nacre-repos', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=base_fd)
            try:
                os.mkdir(identifier, 0o700, dir_fd=fd)
            finally:
                os.close(fd)
        finally:
            os.close(base_fd)
        path = base / '.nacre-repos' / identifier
        key = self.app.STATE / 'keys' / (identifier + '.key')
        self.app.private_write(key, password + '\n')
        repository = {'id': identifier, 'name': name, 'path': str(path), 'key_file': str(key), 'target': target['id']}
        try:
            self.checked(repository, 'init', '--json')
            with self.app.database() as db:
                db.execute('INSERT INTO repositories(id,name,path,key_file,created,target,storage_uuid) VALUES (?,?,?,?,?,?,?)', (identifier,name,str(path),str(key),time.time(),target['id'],target.get('storage_uuid','')))
        except Exception:
            shutil.rmtree(path)
            key.unlink(missing_ok=True)
            raise
        self.app.audit(username, 'Dépôt chiffré créé', name)
        return {'id': identifier}

    def points(self, identifier):
        repository = self.repository(identifier)
        values = json.loads(self.checked(repository, 'snapshots', '--json') or '[]') or []
        return [{key: snapshot.get(key) for key in ('id', 'short_id', 'time', 'hostname', 'paths', 'tags', 'summary')} for snapshot in values]

    def point(self, repository, identifier):
        if not isinstance(identifier, str) or not re.fullmatch(r'[a-f0-9]{8,64}', identifier):
            raise self.app.Problem('Identifiant de snapshot invalide.')
        found = next((x for x in self.points(repository['id']) if x['id'] == identifier), None)
        if not found:
            raise self.app.Problem('Snapshot introuvable.', 404)
        return found

    def submit(self, kind, username, options=None):
        identifier = secrets.token_hex(12)
        with self.app.database() as db:
            db.execute('INSERT INTO jobs(id,kind,status,result,ts,options,username) VALUES (?,?,?,?,?,?,?)',
                       (identifier, kind, 'queued', '{}', time.time(), json.dumps(options or {}), username))
        self.spawn(identifier)
        return identifier

    def spawn(self, identifier):
        env = dict(os.environ, NAS_ROOT=str(self.app.ROOT))
        if os.environ.get('NACRE_SYSTEMD_TASKS') == '1':
            args = ['systemd-run', '--user', '--collect', '--quiet', '--unit=nacre-task-' + identifier,
                    '--property=UMask=0077', '--property=Nice=10', '--property=WorkingDirectory=' + str(self.app.ROOT),
                    '--setenv=NAS_ROOT=' + str(self.app.ROOT)]
            if os.environ.get('NAS_RESTIC_BIN'):
                args.append('--setenv=NAS_RESTIC_BIN=' + os.environ['NAS_RESTIC_BIN'])
            args += [sys.executable, str(Path(__file__).with_name('task_worker.py')), identifier]
            result = subprocess.run(args, capture_output=True, text=True, timeout=10)
            if result.returncode:
                self.update(identifier, status='failed', result={'error': 'Le gestionnaire de tâches système n’a pas démarré le traitement.'})
            return
        process = subprocess.Popen([sys.executable, str(Path(__file__).with_name('task_worker.py')), identifier], cwd=self.app.ROOT,
                                   env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        with self.app.database() as db:
            db.execute('UPDATE jobs SET pid=? WHERE id=?', (process.pid, identifier))
        threading.Thread(target=process.wait, daemon=True).start()

    def cancel(self, identifier):
        with self.app.database() as db:
            row = db.execute('SELECT status FROM jobs WHERE id=?', (identifier,)).fetchone()
            if not row:
                raise self.app.Problem('Tâche inconnue.', 404)
            if row['status'] in ('running', 'queued'):
                db.execute('UPDATE jobs SET cancel=1 WHERE id=?', (identifier,))

    def cancelled(self, identifier):
        with self.app.database() as db:
            row = db.execute('SELECT cancel FROM jobs WHERE id=?', (identifier,)).fetchone()
        return bool(row and row['cancel'])

    def update(self, identifier, **values):
        allowed = {'status', 'result', 'progress'}
        if not values or not set(values) <= allowed:
            return
        with self.app.database() as db:
            db.execute('UPDATE jobs SET ' + ','.join(k + '=?' for k in values) + ' WHERE id=?',
                       [json.dumps(v) if isinstance(v, dict) else v for v in values.values()] + [identifier])

    def stream(self, repository, identifier, *operation):
        process = subprocess.Popen(self.args(repository, *operation), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        selector.register(process.stderr, selectors.EVENT_READ)
        summary, last = {}, 0
        try:
            while selector.get_map():
                if self.cancelled(identifier) and process.poll() is None:
                    process.terminate()
                for selected, _ in selector.select(0.25):
                    line = selected.fileobj.readline()
                    if not line:
                        selector.unregister(selected.fileobj)
                        continue
                    try:
                        message = json.loads(line)
                    except ValueError:
                        continue
                    if message.get('message_type') == 'summary':
                        summary = message
                    if message.get('message_type') == 'status' and time.monotonic() - last > .5:
                        self.update(identifier, progress={k: message[k] for k in ('percent_done', 'bytes_done', 'total_bytes', 'files_done', 'total_files') if k in message})
                        last = time.monotonic()
            code = process.wait()
        finally:
            selector.close()
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            process.stdout.close()
            process.stderr.close()
        if self.cancelled(identifier):
            raise InterruptedError('Tâche annulée.')
        if code not in (0, 3):
            raise self.app.Problem({10: 'Dépôt absent.', 11: 'Dépôt verrouillé.', 12: 'Clé de dépôt refusée.'}.get(code, 'Opération du dépôt non aboutie. Vérifier l’espace et les accès.'))
        return summary, code

    def stage_configuration(self, identifier):
        stage = self.app.STATE / 'tasks' / identifier / 'configuration'
        stage.mkdir(parents=True, mode=0o700)
        for relative in ('compose.yaml', 'state/frigate/config.yml', 'state/samba/smb.conf', 'state/samba/users.tsv', 'state/console/smb.json', 'state/smb_password'):
            source = self.app.ROOT / relative
            if source.is_file() and not source.is_symlink():
                destination = stage / relative
                destination.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
                with source.open('rb') as incoming, destination.open('xb') as outgoing:
                    os.fchmod(outgoing.fileno(), 0o600)
                    shutil.copyfileobj(incoming, outgoing, 1024**2)
        # Copie transactionnelle de SQLite, y compris les transactions WAL validées.
        with closing(sqlite3.connect(self.app.DB)) as source, closing(sqlite3.connect(stage / 'console.db')) as target:
            source.backup(target)
        (stage / 'console.db').chmod(0o600)
        recording_db = self.app.ROOT / 'state/frigate/frigate.db'
        if recording_db.is_file() and not recording_db.is_symlink():
            target_path = stage / 'state/frigate/frigate.db'
            target_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            with closing(sqlite3.connect('file:' + str(recording_db) + '?mode=ro', uri=True)) as source, closing(sqlite3.connect(target_path)) as target:
                source.backup(target)
            target_path.chmod(0o600)
        return stage

    def run_job(self, identifier):
        if not re.fullmatch(r'[a-f0-9]{24}', identifier):
            return
        with self.app.database() as db:
            row = db.execute('SELECT * FROM jobs WHERE id=?', (identifier,)).fetchone()
        if not row or row['status'] not in ('queued', 'running'):
            return
        row, options = dict(row), json.loads(row['options'])
        with self.app.database() as db:
            db.execute('UPDATE jobs SET pid=? WHERE id=?', (os.getpid(), identifier))
        guards=[]
        lock = (self.app.STATE / 'task.lock').open('a')
        try:
            while True:
                if self.cancelled(identifier):
                    raise InterruptedError()
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    time.sleep(.25)
            self.update(identifier, status='running')
            if row['kind'] == 'backup':
                self.app.run_backup(identifier, row['username'])
                return
            repository = self.repository(options['repo'])
            if row['kind'] == 'snapshot':
                sources=[]
                source_map={}
                selected=self.validate_sources(options.get('sources'))
                for area in selected:
                    resource=self.app.resolve_area(area)
                    path=resource['path']
                    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
                    meta=os.fstat(fd);identity={'dev':meta.st_dev,'ino':meta.st_ino}
                    if resource.get('identity') and identity!=resource['identity']:
                        os.close(fd);raise self.app.Problem('Un volume source a changé pendant son ouverture.',503)
                    guards.append((fd,path,identity));sources.append(path)
                    if area=='fichiers':label='fichiers'
                    else:
                        label='volume-'+re.sub(r'[^A-Za-z0-9_-]','-',resource['name'])[:40]+'-'+area[-8:]
                    source_map[path]=label
                repo_fd=os.open(repository['path'],os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
                repo_meta=os.fstat(repo_fd)
                guards.append((repo_fd,repository['path'],{'dev':repo_meta.st_dev,'ino':repo_meta.st_ino}))
                if options.get('configuration', True):
                    sources.append(str(self.stage_configuration(identifier)))
                if options.get('video', False):
                    sources.append(str(self.app.ROOT / 'data/video/recordings'))
                tag = 'nacre:plan:' + options['plan'] if options.get('plan') else 'nacre:manual'
                summary, code = self.stream(repository, identifier, 'backup', '--json', '--exclude-caches', '--exclude','**/.nacre-*','--tag','nacre','--tag',tag,'--tag','nacre-source-map-v1='+base64.urlsafe_b64encode(json.dumps(source_map).encode()).decode(),*sources)
                changed=False
                for fd,path,expected in guards:
                    try:
                        meta=os.stat(path,follow_symlinks=False)
                        changed|={'dev':meta.st_dev,'ino':meta.st_ino}!=expected
                    except OSError:changed=True
                if changed:code=3
                result = {'snapshot': summary.get('snapshot_id'), 'bytes': summary.get('total_bytes_processed'), 'files': summary.get('total_files_processed'), 'label': options.get('label', '')}
                if code == 3:
                    result['warning'] = 'Un volume a changé pendant la capture. Ce point est partiel.' if changed else 'Certains fichiers étaient illisibles ou ont changé pendant la capture. Ce point est partiel.'
                status = 'partial' if code == 3 else 'done'
                self.update(identifier, status=status, result=result, progress={'percent_done': 1})
            elif row['kind'] == 'snapshot_restore':
                point = self.point(repository, options['snapshot'])
                destination = self.app.ROOT / 'data/restaurations' / identifier
                destination.mkdir(mode=0o700)
                summary, code = self.stream(repository, identifier, 'restore', point['id'], '--target', str(destination), '--overwrite', 'never', '--sparse', '--json')
                if code:
                    raise self.app.Problem('Restauration incomplète.')
                # Regrouper les sources sous des noms stables, quel que soit l’hôte d’origine.
                source_map={}
                for tag in point.get('tags',[]):
                    if tag.startswith('nacre-source-map-v1='):
                        try:source_map=json.loads(base64.urlsafe_b64decode(tag.split('=',1)[1]))
                        except (ValueError,TypeError):pass
                for index, source in enumerate(point.get('paths') or []):
                    components = Path(source).parts[1:]
                    if '..' in components:
                        continue
                    nested = destination.joinpath(*components)
                    confined = not any(destination.joinpath(*components[:i]).is_symlink() for i in range(1, len(components) + 1))
                    if confined and nested.exists() and nested.resolve().is_relative_to(destination.resolve()):
                        label=source_map.get(source,Path(source).name) if isinstance(source_map,dict) else Path(source).name
                        if not isinstance(label,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,100}',label):label='source-'+str(index+1)
                        target=destination/label
                        if target.exists():target=destination/(label+'-'+str(index+1))
                        if nested != target and not target.exists():
                            nested.rename(target)
                for path, dirs, files in os.walk(destination, topdown=False, followlinks=False):
                    if Path(path) != destination:
                        try:
                            Path(path).rmdir()
                        except OSError:
                            pass
                self.update(identifier, status='done', result={'directory': identifier, 'snapshot': point['id']}, progress={'percent_done': 1})
            else:
                raise self.app.Problem('Type de tâche inconnu.')
            self.app.audit(row['username'], 'Tâche de protection terminée', row['kind'])
        except InterruptedError:
            self.update(identifier, status='cancelled', result={'error': 'Tâche annulée.'})
        except Exception as error:
            message = error.message if isinstance(error, self.app.Problem) else 'Tâche interrompue. Vérifier la destination, l’espace disponible et les accès.'
            self.update(identifier, status='failed', result={'error': message})
        finally:
            for fd,_,_ in guards:os.close(fd)
            fcntl.flock(lock, fcntl.LOCK_UN)
            lock.close()
            shutil.rmtree(self.app.STATE / 'tasks' / identifier, ignore_errors=True)

    def plans(self):
        with self.app.database() as db:
            return [{**dict(r), 'config': json.loads(r['config'])} for r in db.execute('SELECT * FROM plans ORDER BY name')]

    def save_plan(self, body, username):
        name = self.app.safe_name(body['name'])
        enabled = body.get('enabled', False)
        if not isinstance(enabled, bool):
            raise self.app.Problem('État de plan invalide.')
        repository = self.repository(body['repo']) if body.get('repo') else None
        if enabled and repository is None:
            raise self.app.Problem('Choisir une destination avant d’activer ce plan.')
        hour = body.get('time', '02:00')
        if not isinstance(hour, str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', hour):
            raise self.app.Problem('Heure invalide.')
        days = body.get('weekdays', list(range(7)))
        if not isinstance(days, list) or not days or any(type(x) is not int or x not in range(7) for x in days):
            raise self.app.Problem('Choisir au moins un jour valide.')
        zone = body.get('timezone', 'UTC')
        try:
            ZoneInfo(zone)
        except (ValueError, ZoneInfoNotFoundError):
            raise self.app.Problem('Fuseau horaire inconnu.')
        config = {'time': hour, 'timezone': zone, 'weekdays': sorted(set(days)), 'configuration': bool(body.get('configuration', True)), 'video': bool(body.get('video', False)), 'sources':self.validate_sources(body.get('sources'),allow_unavailable=not enabled)}
        identifier = body.get('id') or secrets.token_hex(12)
        if not re.fullmatch(r'[a-f0-9]{24}', identifier):
            raise self.app.Problem('Identifiant de plan invalide.')
        with self.app.database() as db:
            db.execute('INSERT INTO plans(id,name,repo,enabled,config,next_run) VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,repo=excluded.repo,enabled=excluded.enabled,config=excluded.config,next_run=excluded.next_run',
                       (identifier, name, repository['id'] if repository else None, int(enabled), json.dumps(config), next_occurrence(config) if enabled else None))
        self.app.audit(username, 'Plan de sauvegarde enregistré', name + (' (actif)' if enabled else ' (désactivé)'))
        return {'id': identifier}

    def scheduler_tick(self, now=None):
        now = time.time() if now is None else now
        identifiers = []
        with self.schedule_lock, self.app.database() as db:
            db.execute('BEGIN IMMEDIATE')
            due = db.execute('SELECT * FROM plans WHERE enabled=1 AND next_run<=?', (now,)).fetchall()
            for row in due:
                config = json.loads(row['config'])
                identifier = secrets.token_hex(12)
                options = {**config, 'repo': row['repo'], 'plan': row['id'], 'label': row['name']}
                # Un plan ne s’empile pas si son exécution précédente est encore en cours.
                previous = db.execute('SELECT status FROM jobs WHERE id=?', (row['last_job'],)).fetchone()
                if not previous or previous['status'] not in ('running', 'queued'):
                    db.execute('INSERT INTO jobs(id,kind,status,result,ts,options,username) VALUES (?,?,?,?,?,?,?)', (identifier, 'snapshot', 'queued', '{}', now, json.dumps(options), 'planificateur'))
                    db.execute('UPDATE plans SET last_job=?,last_run=? WHERE id=?', (identifier, now, row['id']))
                    identifiers.append(identifier)
                db.execute('UPDATE plans SET next_run=? WHERE id=?', (next_occurrence(config, now), row['id']))
        for identifier in identifiers:
            self.spawn(identifier)
        return identifiers

    def recover(self):
        with self.app.database() as db:
            rows = db.execute("SELECT id,pid,status,ts FROM jobs WHERE status IN ('running','queued')").fetchall()
        for row in rows:
            if not row['pid'] and time.time() - row['ts'] < 30:
                continue
            try:
                command = Path(f'/proc/{row["pid"]}/cmdline').read_bytes()
                live = b'task_worker.py' in command and row['id'].encode() in command
            except (OSError, TypeError):
                live = False
            if not live:
                self.update(row['id'], status='failed', result={'error': 'Processus interrompu avant la fin de la tâche.'})

    def start_scheduler(self):
        def loop():
            last_recovery = 0
            while True:
                try:
                    if time.monotonic() - last_recovery > 30:
                        self.recover()
                        last_recovery = time.monotonic()
                    self.scheduler_tick()
                except Exception:
                    pass
                time.sleep(5)
        threading.Thread(target=loop, daemon=True, name='nacre-scheduler').start()
