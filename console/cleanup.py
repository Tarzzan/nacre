"""Nettoyage seul : simulation persistante, aucun oubli de snapshot."""
import json
import re
import secrets
import time
import retention

PREFIX='cleanup-preview:'


def preview(app, body, actor):
    repo=app.protection().repository(body.get('repo'))
    return {'job':app.protection().submit('cleanup_preview',actor,{'repo':repo['id']})}


def load(app, db, job, actor):
    if not isinstance(job,str):raise app.Problem('Simulation requise.')
    row=db.execute('SELECT value FROM settings WHERE key=?',(PREFIX+job,)).fetchone()
    if not row:raise app.Problem('Simulation absente ou déjà utilisée. Recommencez.',409)
    plan=json.loads(row[0])
    if plan['actor']!=actor:raise app.Problem('Simulation réservée à son auteur.',403)
    if plan['expires']<time.time():raise app.Problem('Simulation expirée. Recommencez.',409)
    return plan


def review(app, job, actor):
    with app.database() as db:plan=load(app,db,job,actor)
    return {key:plan[key] for key in ('token','repo','name','expires','points')}


def submit(app, body, actor):
    if body.get('confirm') is not True or not isinstance(body.get('token'),str) or not re.fullmatch(r'[a-f0-9]{48}',body['token']):
        raise app.Problem('Confirmez le nettoyage des blocs non référencés.')
    with app.database() as db:
        db.execute('BEGIN IMMEDIATE')
        plan=load(app,db,body.get('job'),actor)
        if not secrets.compare_digest(plan['token'],body['token']):raise app.Problem('Confirmation incorrecte.',403)
        job=secrets.token_hex(12)
        db.execute('INSERT INTO jobs(id,kind,status,result,ts,options,username) VALUES(?,?,?,?,?,?,?)',
                   (job,'cleanup','queued','{}',time.time(),json.dumps(plan),actor))
        db.execute('DELETE FROM settings WHERE key=?',(PREFIX+body['job'],))
        db.execute('UPDATE jobs SET result=? WHERE id=?',
                   (json.dumps({'message':'Simulation confirmée ; voir la tâche de nettoyage.'}),body['job']))
        db.execute('INSERT INTO audit(ts,username,action,detail) VALUES(?,?,?,?)',
                   (time.time(),actor,'Nettoyage seul confirmé',plan['name']))
    app.protection().spawn(job)
    return {'job':job}


def run(app, row):
    manager=app.protection();job=row['id'];plan=json.loads(row['options'])
    simulation=row['kind']=='cleanup_preview'
    repo=manager.repository(plan['repo'])
    if simulation:
        fingerprint=retention.identity(manager,repo)
        points=[{'id':p['id'],'time':p['time']} for p in manager.points(repo['id'])]
        plan={'actor':row['username'],'repo':repo['id'],'name':repo['name'],
              'identity':fingerprint,'snapshot_ids':sorted(p['id'] for p in points),'points':points}
    elif plan['expires']<time.time():
        raise app.Problem('Simulation expirée avant exécution. Recommencez.')

    def unchanged():
        if retention.identity(manager,repo)!=plan['identity']:
            raise app.Problem('Le dépôt a changé d’identité. Refaire la simulation.',409)
        if sorted(p['id'] for p in manager.points(repo['id']))!=plan['snapshot_ids']:
            raise app.Problem('Les points du dépôt ont changé. Refaire la simulation.',409)

    unchanged();started=False
    try:
        if manager.cancelled(job):raise InterruptedError()
        manager.update(job,progress={'message':'Simulation du nettoyage…' if simulation else 'Nettoyage des blocs non référencés…'})
        started=True
        _,code=manager.stream(repo,job,'prune',*(['--dry-run'] if simulation else []),'--json')
        if code:raise app.Problem('Nettoyage non abouti.')
        unchanged()
        if manager.cancelled(job):raise InterruptedError()
        if not simulation:
            manager.update(job,progress={'message':'Vérification de la structure du dépôt…'})
            _,code=manager.stream(repo,job,'check','--json')
            if code:raise app.Problem('La vérification du dépôt a échoué.')
            unchanged()
    except Exception:
        if simulation or not started:raise
        manager.update(job,status='partial',result={'warning':'Nettoyage interrompu : le contrôle final reste à faire. Aucun oubli de point demandé. Refaire une simulation avant de reprendre ; aucun rejeu automatique.'})
        app.audit(row['username'],'Nettoyage seul interrompu',plan['name'])
        return
    if simulation:
        plan.update(token=secrets.token_hex(24),expires=time.time()+retention.TTL)
        result={'cleanup_ready':True,'expires':plan['expires'],'message':f"Simulation terminée · {len(plan['points'])} point(s) à conserver. Examinez la confirmation."}
        with app.database() as db:
            db.execute('BEGIN IMMEDIATE')
            for old in db.execute('SELECT key,value FROM settings WHERE key LIKE ?',(PREFIX+'%',)).fetchall():
                value=json.loads(old['value'])
                if value['expires']<time.time() or (value['actor']==plan['actor'] and value['repo']==plan['repo']):
                    db.execute('DELETE FROM settings WHERE key=?',(old['key'],))
            db.execute('INSERT INTO settings VALUES(?,?)',(PREFIX+job,json.dumps(plan)))
            db.execute("UPDATE jobs SET status='done',result=?,progress=? WHERE id=?",
                       (json.dumps(result),json.dumps({'percent_done':1}),job))
    else:
        manager.update(job,status='done',progress={'percent_done':1},result={
            'message':f"Nettoyage et contrôle de structure terminés · {len(plan['points'])} point(s) conservé(s).",
            'remaining':len(plan['points']),'removed':0,'repository':plan['name']})
        app.audit(row['username'],'Nettoyage seul terminé',plan['name'])
