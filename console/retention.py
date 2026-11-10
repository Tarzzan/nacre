"""Rétention explicite : prévisualisation liée au dépôt, tâche à usage unique."""
from contextlib import contextmanager
from datetime import datetime
import fcntl
import json
from pathlib import Path
import re
import secrets
import time

PREFIX = 'retention-preview:'
TTL = 900


@contextmanager
def idle(app):
    with (app.STATE/'task.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:raise app.Problem('Une tâche est en cours. Réessayez la simulation après sa fin.',409) from None
        try:yield
        finally:fcntl.flock(lock,fcntl.LOCK_UN)


def identity(manager, repository):
    path=Path(repository['path'])
    if path.is_symlink():raise manager.app.Problem('Le chemin du dépôt est un lien symbolique.',409)
    meta=path.stat()
    config=json.loads(manager.checked(repository,'cat','config'))
    return {'id':config['id'],'dev':meta.st_dev,'ino':meta.st_ino,'path':str(path.resolve())}


def selection(app, repository, snapshots, keep_last):
    # Seules les captures dont Nacre possède une preuve locale de succès sont
    # candidates. Les captures importées, partielles ou étrangères sont protégées.
    with app.database() as db:
        jobs=db.execute("SELECT options,result,status FROM jobs WHERE kind='snapshot'").fetchall()
    known={}; unsafe=set()
    for row in jobs:
        options=json.loads(row['options']); result=json.loads(row['result'])
        identifier=result.get('snapshot')
        if not identifier or options.get('repo')!=repository['id']:continue
        if row['status']!='done':unsafe.add(identifier);continue
        group=json.dumps([options.get('plan','manual'),sorted(options.get('sources',['fichiers'])),
                          options.get('configuration',True),options.get('video',False)],sort_keys=True)
        known[identifier]=group
    groups={}; protected=[]
    for point in snapshots:
        identifier=point['id']
        if not re.fullmatch(r'[a-f0-9]{64}',identifier):raise app.Problem('Identifiant de point non reconnu.',409)
        try:
            stamp=datetime.fromisoformat(point['time'].replace('Z','+00:00')).timestamp()
        except (ValueError,KeyError,TypeError):raise app.Problem('Date de point non reconnue.',409) from None
        public={'id':identifier,'time':point['time']}
        if identifier not in known or identifier in unsafe or 'nacre' not in (point.get('tags') or []) or stamp>time.time():
            protected.append({**public,'reason':'Capture importée, partielle, future ou sans preuve locale de succès.'})
            continue
        # Ne pas mélanger plans, hôtes, sources ou options de capture. Le chemin
        # temporaire de la copie de configuration ne crée pas un groupe par tâche.
        group=(point.get('hostname',''),known[identifier])
        groups.setdefault(group,[]).append((stamp,identifier,public))
    keep=[]; remove=[]
    for values in groups.values():
        values.sort(reverse=True)
        keep.extend(item[2] for item in values[:keep_last])
        remove.extend(item[2] for item in values[keep_last:])
    return {'keep':sorted(keep,key=lambda p:(p['time'],p['id']),reverse=True),
            'remove':sorted(remove,key=lambda p:(p['time'],p['id'])),
            'protected':protected,'groups':len(groups)}


def preview(app, body, actor):
    count=body.get('keep_last')
    if type(count) is not int or not 1<=count<=1000000:
        raise app.Problem('Conserver au moins un point par groupe (entier de 1 à 1 000 000).')
    manager=app.protection()
    with idle(app):
        repository=manager.repository(body.get('repo'))
        before=identity(manager,repository)
        points=manager.points(repository['id'])
        chosen=selection(app,repository,points,count)
        ids=[p['id'] for p in chosen['remove']]
        for offset in range(0,len(ids),128):
            manager.checked(repository,'forget','--dry-run','--json',*ids[offset:offset+128])
        snapshot_ids=sorted(p['id'] for p in points)
        if identity(manager,repository)!=before or sorted(p['id'] for p in manager.points(repository['id']))!=snapshot_ids:
            raise app.Problem('Le dépôt a changé pendant la simulation. Recommencez.',409)
        plan={'token':secrets.token_hex(24),'actor':actor,'repo':repository['id'],'name':repository['name'],
              'keep_last':count,'expires':time.time()+TTL,'identity':before,'snapshot_ids':snapshot_ids,**chosen}
        with app.database() as db:
            db.execute('BEGIN IMMEDIATE')
            # Une seule proposition par administrateur et dépôt ; nettoyer les expirées.
            for row in db.execute('SELECT key,value FROM settings WHERE key LIKE ?', (PREFIX+'%',)).fetchall():
                old=json.loads(row['value'])
                if old['expires']<time.time() or (old['actor']==actor and old['repo']==repository['id']):
                    db.execute('DELETE FROM settings WHERE key=?',(row['key'],))
            db.execute('INSERT INTO settings VALUES(?,?)',(PREFIX+plan['token'],json.dumps(plan)))
    return {key:value for key,value in plan.items() if key not in ('actor','identity','snapshot_ids')}


def submit(app, body, actor):
    if body.get('confirm') is not True or not isinstance(body.get('token'),str):
        raise app.Problem('Confirmez la suppression des points affichés et le nettoyage du dépôt.')
    with app.database() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT value FROM settings WHERE key=?',(PREFIX+body['token'],)).fetchone()
        if not row:raise app.Problem('Simulation absente ou déjà utilisée. Recommencez.',409)
        plan=json.loads(row[0])
        if plan['actor']!=actor:raise app.Problem('Simulation réservée à son auteur.',403)
        if plan['expires']<time.time():raise app.Problem('Simulation expirée. Recommencez.',409)
        if not plan['remove']:raise app.Problem('Aucun point à supprimer.')
        job=secrets.token_hex(12)
        db.execute('INSERT INTO jobs(id,kind,status,result,ts,options,username) VALUES(?,?,?,?,?,?,?)',
                   (job,'retention','queued','{}',time.time(),json.dumps(plan),actor))
        db.execute('DELETE FROM settings WHERE key=?',(PREFIX+body['token'],))
        db.execute('INSERT INTO audit(ts,username,action,detail) VALUES(?,?,?,?)',
                   (time.time(),actor,'Rétention confirmée',repository_detail(plan)))
    app.protection().spawn(job)
    return {'job':job}


def repository_detail(plan):
    return plan['name']+' · '+str(len(plan['remove']))+' point(s)'


def run(app, row):
    manager=app.protection(); plan=json.loads(row['options']); job=row['id']
    if plan['expires']<time.time():raise app.Problem('Simulation expirée avant exécution. Aucune suppression lancée.')
    repository=manager.repository(plan['repo'])
    expected=set(plan['snapshot_ids']); removed=[]
    def unchanged():
        if identity(manager,repository)!=plan['identity']:
            raise app.Problem('Le dépôt a changé d’identité. Refaire la simulation.',409)
        if {p['id'] for p in manager.points(plan['repo'])}!=expected:
            raise app.Problem('Les points du dépôt ont changé. Refaire la simulation.',409)
    unchanged()
    # Revalider également la provenance locale, qui peut avoir changé depuis le plan.
    fresh=selection(app,repository,manager.points(plan['repo']),plan['keep_last'])
    if {p['id'] for p in fresh['remove']}!={p['id'] for p in plan['remove']}:
        raise app.Problem('La sélection a changé. Refaire la simulation.',409)
    ids=[p['id'] for p in plan['remove']]
    started=False
    try:
        for offset in range(0,len(ids),128):
            if manager.cancelled(job):raise InterruptedError()
            unchanged()
            manager.update(job,progress={'message':'Suppression des points confirmés…'})
            started=True
            batch=ids[offset:offset+128]
            _,code=manager.stream(repository,job,'forget','--json',*batch)
            if code:raise app.Problem('Suppression non aboutie.')
            removed.extend(batch);expected.difference_update(batch)
            unchanged()
        manager.update(job,progress={'message':'Récupération des blocs non référencés…'})
        _,code=manager.stream(repository,job,'prune','--json')
        if code:raise app.Problem('Nettoyage non abouti.')
        unchanged()
        manager.update(job,progress={'message':'Vérification de la structure du dépôt…'})
        _,code=manager.stream(repository,job,'check','--json')
        if code:raise app.Problem('La vérification du dépôt a échoué.')
        unchanged()
    except Exception:
        if not started:raise
        # Une interruption ne rétablit pas les points déjà oubliés. Ne jamais
        # présenter cette opération comme annulée sans effet ni la rejouer seule.
        manager.update(job,status='partial',result={'warning':'Opération interrompue : des points peuvent avoir été supprimés. Actualisez le dépôt et refaites une simulation avant toute nouvelle action.',
                       'removed_confirmed':len(removed),'repository':plan['name']})
        app.audit(row['username'],'Rétention interrompue',repository_detail(plan))
        return
    manager.update(job,status='done',progress={'percent_done':1},result={
        'message':str(len(removed))+' point(s) supprimé(s) ; nettoyage et contrôle de structure terminés.',
        'removed':len(removed),'remaining':len(expected),'repository':plan['name']})
    app.audit(row['username'],'Rétention terminée',repository_detail(plan))
