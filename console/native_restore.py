"""Restauration LVM en tâche système indépendante, vers un nouveau dossier."""
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parent))
from native_storage import Engine, NativeError, canonical, private_directory


class Restorations:
    def __init__(self, engine):
        self.e=engine
        self.e.db.execute('CREATE TABLE IF NOT EXISTS native_jobs (id TEXT PRIMARY KEY, actor TEXT, ts REAL, status TEXT, options TEXT, pid INTEGER, files INTEGER DEFAULT 0, bytes INTEGER DEFAULT 0, cancel INTEGER DEFAULT 0, error TEXT DEFAULT \'\', location TEXT DEFAULT \'\')')

    def list(self):
        result=[]
        for row in self.e.db.execute('SELECT id,actor,ts,status,pid,files,bytes,cancel,error,location FROM native_jobs ORDER BY ts DESC'):
            view=dict(row)
            if view['status'] in ('queued','running') and time.time()-view['ts']>30:
                try:
                    cmd=Path(f'/proc/{view["pid"]}/cmdline').read_bytes()
                    alive=b'native_restore.py' in cmd and view['id'].encode() in cmd
                except OSError:alive=False
                if not alive:
                    self.update(view['id'],status='uncertain',error='Processus interrompu ; restauration partielle conservée à titre privé.')
                    view.update(status='uncertain',error='Processus interrompu ; restauration partielle conservée à titre privé.')
            result.append(view)
        return result

    def update(self, identifier, **values):
        if not set(values)<= {'status','pid','files','bytes','cancel','error','location'}:
            raise ValueError('Champ de tâche invalide')
        with self.e.db:
            self.e.db.execute('UPDATE native_jobs SET '+','.join(k+'=?' for k in values)+' WHERE id=?',(*values.values(),identifier))
            if 'status' in values:
                self.e.db.execute('UPDATE actions SET status=?,location=CASE WHEN ?!=\'\' THEN ? ELSE location END WHERE id=?',
                                  (values['status'],values.get('location',''),values.get('location',''),identifier))

    def enqueue(self, identifier, actor, volume, point):
        directory=volume.get('restore_directory','')
        if not directory.startswith('/srv/'):
            raise NativeError('Destination privée de restauration sous /srv requise dans la politique LVM.')
        private_directory(directory)
        self.e.verify_point(volume,point)
        options={'volume':volume,'point':point,'root':directory}
        with self.e.db:
            self.e.db.execute('INSERT INTO native_jobs(id,actor,ts,status,options) VALUES(?,?,?,?,?)',(identifier,actor,time.time(),'queued',canonical(options)))
        command=['systemd-run','--quiet','--collect','--unit=nacre-restore-'+identifier,
                 '--property=UMask=0077','--property=Nice=10','--property=PrivateMounts=yes',
                 '--property=PrivateNetwork=yes','--property=NoNewPrivileges=yes',
                 sys.executable,'-I',str(Path(__file__).resolve()),'--job',identifier]
        result=subprocess.run(command,capture_output=True,text=True,timeout=15)
        if result.returncode:
            self.update(identifier,status='failed',error='Le gestionnaire de tâches système n’a pas lancé la restauration.')
            raise NativeError('La tâche système de restauration n’a pas pu démarrer.')
        return {'job':identifier,'location':'Restauration LVM en arrière-plan','queued':True}

    def cancel(self, identifier):
        if not self.e.db.execute('SELECT 1 FROM native_jobs WHERE id=?',(identifier,)).fetchone():
            raise NativeError('Tâche de restauration inconnue.')
        self.update(identifier,cancel=1)
        return {'ok':True}

    def worker(self, identifier):
        row=self.e.db.execute('SELECT * FROM native_jobs WHERE id=?',(identifier,)).fetchone()
        if not row or row['status']!='queued':
            raise NativeError('Tâche absente ou déjà démarrée.')
        options=json.loads(row['options'])
        volume=self.e.volume(options['volume']['id'])
        if volume!=options['volume']:
            raise NativeError('Politique de restauration modifiée.')
        private_directory(options['root'])
        self.e.verify_point(volume,options['point'])
        self.update(identifier,status='running',pid=os.getpid())
        target=Path(options['root'])/('restore_'+identifier)
        view=Path('/run/nacre-restore-'+identifier)
        mounted=False
        try:
            self.check_cancel(identifier)
            target.mkdir(mode=0o700)
            view.mkdir(mode=0o700)
            device='/dev/'+volume['lv'].split('/')[0]+'/'+options['point']['object']
            if not Path(device).exists():
                self.e.run(['lvchange','-ay','--ignoreactivationskip','--yes',volume['lv'].split('/')[0]+'/'+options['point']['object']])
            self.e.verify_point(volume,options['point'])
            filesystem=self.e.run(['blkid','-p','-s','TYPE','-o','value',device]).strip()
            if filesystem not in ('ext4','xfs'):
                raise NativeError('La copie LVM prend en charge ext4 et XFS uniquement.')
            mount_options='ro,noload,nodev,nosuid,noexec' if filesystem=='ext4' else 'ro,nouuid,norecovery,nodev,nosuid,noexec'
            self.e.run(['mount','-t',filesystem,'-o',mount_options,device,str(view)])
            mounted=True
            self.copy(identifier,view,target)
            self.e.verify_point(volume,options['point'])
            self.check_cancel(identifier)
            uid=self.e.policy()['allowed_uid']
            os.chown(target,uid,-1)
            self.update(identifier,status='done',location=str(target))
        except InterruptedError:
            self.update(identifier,status='cancelled',error='Restauration annulée ; dossier partiel conservé privé.')
        except Exception as error:
            self.update(identifier,status='failed',error=str(error) if isinstance(error,NativeError) else 'Copie interrompue ; vérifier espace, fichiers et état du snapshot.')
        finally:
            if mounted:
                try:self.e.run(['umount',str(view)])
                except NativeError:pass
            try:view.rmdir()
            except OSError:pass

    def check_cancel(self, identifier):
        if self.e.db.execute('SELECT cancel FROM native_jobs WHERE id=?',(identifier,)).fetchone()['cancel']:
            raise InterruptedError()

    def copy(self, identifier, source, target):
        uid=self.e.policy()['allowed_uid']
        files=total=0
        tick=time.monotonic()
        def progress(force=False):
            nonlocal tick
            if force or time.monotonic()-tick>.25:
                self.check_cancel(identifier)
                self.update(identifier,files=files,bytes=total)
                tick=time.monotonic()
        # La source est montée readonly dans le namespace privé du worker.
        # fwalk + O_NOFOLLOW ne lit jamais la cible d'un lien utilisateur.
        for directory,dirs,names,source_fd in os.fwalk(source,follow_symlinks=False):
            relative=Path(directory).relative_to(source)
            destination=target/relative
            for name in list(dirs)+names:
                meta=os.stat(name,dir_fd=source_fd,follow_symlinks=False)
                output=destination/name
                if stat.S_ISLNK(meta.st_mode):
                    os.symlink(os.readlink(name,dir_fd=source_fd),output)
                    os.chown(output,uid,-1,follow_symlinks=False)
                    files+=1
                    if name in dirs:dirs.remove(name)
                elif stat.S_ISDIR(meta.st_mode):
                    output.mkdir(mode=0o700)
                    os.chown(output,uid,-1)
                elif stat.S_ISREG(meta.st_mode):
                    src=os.open(name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=source_fd)
                    try:
                        with os.fdopen(src,'rb') as reader, output.open('xb') as writer:
                            while chunk:=reader.read(1024*1024):
                                if chunk.count(0)==len(chunk):writer.seek(len(chunk),os.SEEK_CUR)
                                else:
                                    if len(chunk)>shutil.disk_usage(target).free:
                                        raise NativeError('Espace physique disponible insuffisant pour la restauration.')
                                    writer.write(chunk)
                                total+=len(chunk)
                                progress()
                            writer.truncate(reader.tell())
                            writer.flush();os.fsync(writer.fileno())
                        os.chown(output,uid,-1)
                        os.utime(output,ns=(meta.st_atime_ns,meta.st_mtime_ns),follow_symlinks=False)
                        files+=1
                    except Exception:
                        # fdopen ferme le FD ; aucun suivi de liens en reprise.
                        raise
                else:
                    raise NativeError('Un fichier spécial ne peut pas être restauré par cette copie de fichiers.')
                progress()
        progress(True)


if __name__=='__main__':
    if os.geteuid()!=0 or len(sys.argv)!=3 or sys.argv[1]!='--job' or not re.fullmatch(r'[a-f0-9]{32}',sys.argv[2]):
        raise SystemExit('Worker système réservé à une tâche de restauration connue.')
    os.umask(0o077)
    engine=Engine(recover=False)
    manager=Restorations(engine)
    try:manager.worker(sys.argv[2])
    except Exception as error:
        manager.update(sys.argv[2],status='failed',error=str(error) if isinstance(error,NativeError) else 'Préparation de la copie non aboutie.')
        raise SystemExit(1)
