"""Reconstruire un RAID1 Nacre monté, avec un membre sain et un disque vierge.

Aucune mise en panne, suppression de membre, assemblage forcé ou initialisation
n’est exécutée ici. Le membre défaillant doit déjà avoir quitté l’ensemble.
"""
from contextlib import ExitStack
import fcntl
import json
import os
from pathlib import Path
import secrets
import time
from native_storage import NativeError,canonical,fingerprint


class MirrorRepair:
    def __init__(self,engine):
        self.e=engine
        self.p=engine.provisioning()

    def record(self,identifier):
        row=self.e.db.execute('SELECT * FROM deployments WHERE id=?',(identifier,)).fetchone()
        if not row or row['phase']!='ready':raise NativeError('Volume non disponible pour une nouvelle reconstruction.')
        record=json.loads(row['record'])
        if record['layout']!='mirror' or len(record['specs'])!=2:raise NativeError('Seuls les miroirs RAID1 à deux membres sont pris en charge.')
        self.p.authorize(record)
        return record

    def observe(self,record):
        self.p.check_mount(record)
        mount=json.loads(self.e.run(['findmnt','-J','-M',record['mountpoint'],'-o','SOURCE']))['filesystems'][0]
        device=str(Path(mount['source'].split('[')[0]).resolve())
        values=self.p.check_md(device,record)
        if values.get('MD_DEVICES')!='2' or values.get('MD_METADATA')!='1.2':raise NativeError('Géométrie ou métadonnées RAID non prises en charge.')
        md=Path('/sys/class/block')/Path(device).name/'md'
        members=[]
        for item in sorted(md.glob('dev-*')):
            members.append({'device':(item/'block/dev').read_text().strip(),'state':sorted((item/'state').read_text().strip().split(','))})
        meta=os.stat(device)
        return {'path':device,'device':f'{os.major(meta.st_rdev)}:{os.minor(meta.st_rdev)}','members':members,
                'degraded':int((md/'degraded').read_text()),'sync_action':(md/'sync_action').read_text().strip(),
                'array_state':(md/'array_state').read_text().strip()}

    def degraded(self,record,old,new):
        if old not in [s['id'] for s in record['specs']] or new in [s['id'] for s in record['specs']]:raise NativeError('Choisir le membre absent et un autre disque.')
        survivor=next(s for s in record['specs'] if s['id']!=old)
        identity=self.p.probe(survivor,blank=False)
        observed=self.observe(record)
        if observed['degraded']!=1 or observed['sync_action']!='idle' or observed['array_state'] not in ('clean','active','active-idle'):
            raise NativeError('Le miroir doit être monté, dégradé d’un seul membre et sans synchronisation en cours.')
        if observed['members']!=[{'device':identity['device'],'state':['in_sync']}]:
            raise NativeError('Le seul membre présent doit être le survivant sain attendu. Retirer le membre défaillant avant ce parcours.')
        spec=self.p.spec(new);replacement=self.p.probe(spec)
        missing=next(s for s in record['specs'] if s['id']==old)
        if replacement['device']==identity['device'] or replacement['bytes']<missing['bytes']:
            raise NativeError('Le remplacement doit être distinct et au moins aussi grand que le membre absent.')
        return observed,identity,spec,replacement

    def prepare(self,uid,actor,body):
        record=self.record(body.get('volume'))
        old,new=body.get('replace'),body.get('device')
        observed,survivor,spec,replacement=self.degraded(record,old,new)
        identifier=secrets.token_hex(16);expiry=time.time()+120
        confirmation='RECONSTRUIRE '+record['id']+' AVEC '+new
        plan={'action':'repair','volume':record['id'],'record':fingerprint(record),'old':old,'spec':spec,'replacement':replacement,
              'survivor':survivor,'md':{'path':observed['path'],'device':observed['device']},'confirmation':confirmation}
        with self.e.db:self.e.db.execute('INSERT INTO plans(id,uid,actor,expires,payload) VALUES(?,?,?,?,?)',(identifier,uid,actor,expiry,canonical(plan)))
        return {'id':identifier,'expires':expiry,'action':'repair','volume':record['name'],'confirmation':confirmation,
                'effect':'Copier le membre sain vers le nouveau disque et reconstruire le miroir RAID1.',
                'notes':['Le disque '+new+' sera écrit intégralement. Série : '+replacement['serial']+'.',
                         'Le membre absent '+old+' est conservé hors de ce parcours. Aucun effacement de sa signature.',
                         'L’acceptation de la commande ne signifie pas que la synchronisation est terminée.']}

    def commit(self,row,plan):
        record=self.record(plan['volume'])
        if fingerprint(record)!=plan['record']:raise NativeError('Catalogue modifié depuis la préparation.')
        observed,survivor,spec,replacement=self.degraded(record,plan['old'],plan['spec']['id'])
        if (survivor,spec,replacement,{'path':observed['path'],'device':observed['device']})!=(plan['survivor'],plan['spec'],plan['replacement'],plan['md']):
            raise NativeError('Identité modifiée depuis la préparation.')
        with self.p.pinned([spec],[replacement]) as new_fds, ExitStack() as pins:
            fds=[]
            for item in (survivor,plan['md']):
                fd=os.open(item['path'],os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC);pins.callback(os.close,fd)
                fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
                meta=os.fstat(fd)
                if f'{os.major(meta.st_rdev)}:{os.minor(meta.st_rdev)}'!=item['device']:raise NativeError('Périphérique remplacé pendant son ouverture.')
                fds.append(fd)
            latest,again,_,_=self.degraded(record,plan['old'],spec['id'])
            if latest['device']!=plan['md']['device'] or again!=survivor:raise NativeError('Miroir modifié pendant son ouverture.')
            previous=next(s for s in record['specs'] if s['id']==plan['old'])
            record['specs']=[spec if s['id']==plan['old'] else s for s in record['specs']]
            record['repair']={'plan':row['id'],'replaced':previous,'status':'rebuilding'}
            # Journal durable AVANT l’ajout : aucun rejeu automatique après incident.
            with self.e.db:
                self.e.db.execute('UPDATE plans SET consumed=1 WHERE id=?',(row['id'],))
                self.e.db.execute("UPDATE deployments SET record=?,phase='repairing',error='' WHERE id=?",(canonical(record),record['id']))
                self.e.db.execute('INSERT INTO actions(id,ts,actor,action,volume,object,status) VALUES(?,?,?,?,?,?,?)',(row['id'],time.time(),row['actor'],'repair',record['id'],spec['id'],'running'))
            try:
                self.e.run(['mdadm','--manage',plan['md']['path'],'--add',f'/proc/self/fd/{new_fds[0]}'],tuple(fds)+new_fds)
            except Exception:
                self.p.save_record(record['id'],record,'uncertain','Ajout non confirmé. Inspecter le miroir ; aucun rejeu automatique.')
                with self.e.db:self.e.db.execute("UPDATE actions SET status='uncertain' WHERE id=?",(row['id'],))
                raise
        return {'ok':True,'rebuilding':True,'object':record['id'],'location':record['mountpoint']}

    def verified_complete(self,record):
        self.p.authorize(record)
        observed=self.observe(record)
        expected=sorted(self.p.probe(s,blank=False)['device'] for s in record['specs'])
        actual=sorted(m['device'] for m in observed['members'] if m['state']==['in_sync'])
        if len(observed['members'])!=2 or expected!=actual or observed['degraded']!=0 or observed['sync_action']!='idle':
            raise NativeError('Les deux membres attendus ne sont pas encore synchronisés.')

    def complete(self,record):
        record['repair']['status']='done'
        with self.e.db:
            self.e.db.execute("UPDATE deployments SET record=?,phase='ready',error='' WHERE id=?",(canonical(record),record['id']))
            self.e.db.execute("UPDATE actions SET status='done',location=? WHERE id=?",(record['mountpoint'],record['repair']['plan']))

    def review(self,uid,actor,body):
        row=self.e.db.execute('SELECT * FROM deployments WHERE id=?',(body.get('volume'),)).fetchone()
        if not row or row['phase'] not in ('repairing','uncertain'):raise NativeError('Aucune reconstruction à vérifier.')
        record=json.loads(row['record'])
        if not record.get('repair'):raise NativeError('Aucune reconstruction à vérifier.')
        self.verified_complete(record)
        identifier=secrets.token_hex(16);expiry=time.time()+120
        plan={'action':'repair-review','volume':record['id'],'record':fingerprint(record),'confirmation':'VALIDER '+record['id']}
        with self.e.db:self.e.db.execute('INSERT INTO plans(id,uid,actor,expires,payload) VALUES(?,?,?,?,?)',(identifier,uid,actor,expiry,canonical(plan)))
        return {'id':identifier,'expires':expiry,'action':'repair-review','volume':record['name'],'confirmation':plan['confirmation'],
                'effect':'Valider le catalogue après contrôle des deux membres synchronisés.',
                'notes':['Aucune commande d’ajout, de formatage ou d’assemblage ne sera exécutée.']}

    def commit_review(self,row,plan):
        current=self.e.db.execute('SELECT * FROM deployments WHERE id=?',(plan['volume'],)).fetchone()
        if not current or current['phase'] not in ('repairing','uncertain'):raise NativeError('État de reconstruction modifié.')
        record=json.loads(current['record'])
        if fingerprint(record)!=plan['record']:raise NativeError('Catalogue modifié.')
        self.verified_complete(record)
        with self.e.db:self.e.db.execute('UPDATE plans SET consumed=1 WHERE id=?',(row['id'],))
        self.complete(record)
        return {'ok':True,'object':record['id'],'metadata_verified':True}

    def reconcile(self):
        for row,record in self.p.records():
            if row['phase']!='repairing' or not record.get('repair'):continue
            try:
                self.verified_complete(record)
                self.complete(record)
            except (NativeError,OSError,ValueError,KeyError):continue
