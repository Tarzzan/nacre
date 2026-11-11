"""Rétention après capture réussie, autorisation versionnée par dépôt."""
import json
import time
import retention

PREFIX='retention-policy:'
KIND='retention_auto'


def read(db, repo):
    row=db.execute('SELECT value FROM settings WHERE key=?',(PREFIX+repo,)).fetchone()
    return json.loads(row[0]) if row else {'repo':repo,'version':0,'enabled':False,'keep_last':7,'reason':''}


def write(db, policy):
    db.execute('INSERT INTO settings VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
               (PREFIX+policy['repo'],json.dumps(policy)))


def listing(app):
    with app.database() as db:
        result=[]
        for repo,name in db.execute('SELECT id,name FROM repositories ORDER BY name').fetchall():
            p=read(db,repo)
            result.append({**{k:p[k] for k in ('repo','version','enabled','keep_last','reason')},'name':name})
        return result


def configure(app, body, actor):
    if type(body.get('enabled')) is not bool or type(body.get('version')) is not int or not isinstance(body.get('repo'),str):
        raise app.Problem('État et version de règle requis.')
    if not body['enabled']:
        with app.database() as db:
            db.execute('BEGIN IMMEDIATE');p=read(db,body.get('repo'))
            if p['version']!=body['version']:raise app.Problem('La règle a changé. Actualisez.',409)
            if not db.execute('SELECT 1 FROM repositories WHERE id=?',(body.get('repo'),)).fetchone():raise app.Problem('Dépôt inconnu.',404)
            p.update(enabled=False,version=p['version']+1,reason='');write(db,p)
            db.execute('INSERT INTO audit(ts,username,action,detail) VALUES(?,?,?,?)',(time.time(),actor,'Rétention automatique désactivée',p['repo']))
        return {'ok':True}
    if body.get('confirm') is not True or not isinstance(body.get('token'),str):
        raise app.Problem('Une simulation et la confirmation des prochaines suppressions sont requises.')
    with retention.idle(app):
        with app.database() as db:
            row=db.execute('SELECT value FROM settings WHERE key=?',(retention.PREFIX+body['token'],)).fetchone()
        if not row:raise app.Problem('Refaites une simulation avant activation.',409)
        plan=json.loads(row[0])
        if plan['actor']!=actor:raise app.Problem('Simulation réservée à son auteur.',403)
        if plan['expires']<time.time():raise app.Problem('Simulation expirée.',409)
        if plan['repo']!=body.get('repo') or plan.get('policy_version')!=body['version']:
            raise app.Problem('La règle ne correspond plus à la simulation.',409)
        manager=app.protection();repo=manager.repository(plan['repo'])
        if retention.identity(manager,repo)!=plan['identity'] or sorted(p['id'] for p in manager.points(repo['id']))!=plan['snapshot_ids']:
            raise app.Problem('Le dépôt a changé. Refaites la simulation.',409)
        with app.database() as db:
            db.execute('BEGIN IMMEDIATE');p=read(db,repo['id'])
            if p['version']!=body['version'] or not db.execute('SELECT 1 FROM settings WHERE key=?',(retention.PREFIX+body['token'],)).fetchone():
                raise app.Problem('Simulation ou règle déjà modifiée.',409)
            # Exclut également les captures déjà demandées avant activation.
            barrier=db.execute('SELECT COALESCE(MAX(rowid),0) FROM jobs').fetchone()[0]
            p.update(version=p['version']+1,enabled=True,keep_last=plan['keep_last'],identity=plan['identity'],
                     actor=actor,after_rowid=barrier,reason='')
            write(db,p);db.execute('DELETE FROM settings WHERE key=?',(retention.PREFIX+body['token'],))
            db.execute('INSERT INTO audit(ts,username,action,detail) VALUES(?,?,?,?)',
                       (time.time(),actor,'Rétention automatique activée',repo['name']+' · '+str(p['keep_last'])+' point(s) par groupe'))
    return {'ok':True}


def dispatch(app):
    """Retrouve aussi un succès validé juste avant l'arrêt de la console."""
    jobs=[]
    with app.database() as db:
        db.execute('BEGIN IMMEDIATE')
        policies=[json.loads(r[0]) for r in db.execute('SELECT value FROM settings WHERE key LIKE ?',(PREFIX+'%',))]
        active={json.loads(r[0]).get('repo') for r in db.execute("SELECT options FROM jobs WHERE kind=? AND status IN ('queued','running')",(KIND,))}
        interrupted=[json.loads(r[0]) for r in db.execute("SELECT options FROM jobs WHERE kind=? AND status IN ('failed','partial','cancelled')",(KIND,))]
        for p in policies:
            # Couvre un arrêt après publication de l'échec mais avant suspension.
            if p['enabled'] and any(o['repo']==p['repo'] and o['policy_version']==p['version'] for o in interrupted):
                suspend(db,p,'planificateur');continue
            if not p['enabled'] or p['repo'] in active:continue
            rows=db.execute("SELECT id,options,result FROM jobs WHERE rowid>? AND kind='snapshot' AND status='done' ORDER BY rowid",(p['after_rowid'],)).fetchall()
            for row in rows:
                options=json.loads(row['options']);result=json.loads(row['result'])
                if options.get('repo')!=p['repo'] or not result.get('snapshot'):continue
                identifier=app.digest('automatic-retention:'+p['repo']+':'+str(p['version'])+':'+row['id'])[:24]
                if db.execute('SELECT 1 FROM jobs WHERE id=?',(identifier,)).fetchone():continue
                config={'repo':p['repo'],'policy_version':p['version'],'trigger':row['id'],'snapshot':result['snapshot']}
                db.execute('INSERT INTO jobs(id,kind,status,result,ts,options,username) VALUES(?,?,?,?,?,?,?)',
                           (identifier,KIND,'queued','{}',time.time(),json.dumps(config),p['actor']))
                jobs.append(identifier);break
    for identifier in jobs:app.protection().spawn(identifier)
    return jobs


def suspend(db,p,actor):
    p.update(enabled=False,version=p['version']+1,reason='Nettoyage interrompu ou refusé. Vérifiez le dépôt puis simulez à nouveau avant réactivation.')
    write(db,p)
    db.execute('INSERT INTO audit(ts,username,action,detail) VALUES(?,?,?,?)',
               (time.time(),actor,'Rétention automatique suspendue',p['repo']))


def finish(app, row):
    """Un incident suspend la règle courante ; ne pas affecter une règle remplacée."""
    options=json.loads(row['options'])
    with app.database() as db:
        db.execute('BEGIN IMMEDIATE');status=db.execute('SELECT status FROM jobs WHERE id=?',(row['id'],)).fetchone()[0]
        p=read(db,options['repo'])
        if status not in ('failed','partial','cancelled') or not p['enabled'] or p['version']!=options['policy_version']:return
        suspend(db,p,row['username'])


def run(app, row):
    manager=app.protection();options=json.loads(row['options'])
    with app.database() as db:
        p=read(db,options['repo'])
        actor=db.execute("SELECT 1 FROM users WHERE name=? AND active=1 AND role='admin'",(p.get('actor'),)).fetchone()
        trigger=db.execute("SELECT rowid,status,result,options FROM jobs WHERE id=? AND kind='snapshot'",(options['trigger'],)).fetchone()
    if not p['enabled'] or p['version']!=options['policy_version']:
        manager.update(row['id'],status='cancelled',result={'message':'La règle a été désactivée ou remplacée avant exécution.'});return
    if not actor:raise app.Problem('Le compte ayant activé la règle n’est plus administrateur actif.')
    if not trigger or trigger['rowid']<=p['after_rowid'] or trigger['status']!='done' or json.loads(trigger['result']).get('snapshot')!=options['snapshot'] or json.loads(trigger['options']).get('repo')!=p['repo']:
        raise app.Problem('La capture déclenchante n’est plus une réussite vérifiable.')
    def guard():
        with app.database() as db:current=read(db,p['repo'])
        if not current['enabled'] or current['version']!=p['version']:
            raise app.Problem('La règle a été désactivée ou remplacée pendant le traitement.')
    repo=manager.repository(p['repo'])
    if retention.identity(manager,repo)!=p['identity']:raise app.Problem('Le dépôt a changé depuis l’activation de la règle.')
    plan=retention.proposal(app,p['repo'],p['keep_last'],p['actor'])
    guard()
    if plan['identity']!=p['identity'] or options['snapshot'] not in plan['snapshot_ids']:
        raise app.Problem('Le dépôt ou la capture déclenchante ne correspond plus à la règle.')
    if not plan['remove']:
        manager.update(row['id'],status='done',result={'message':'Règle vérifiée : aucun point à supprimer.','removed':0});return
    retention.run(app,{**row,'options':json.dumps(plan)},guard=guard)


def disable_after_recovery(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='settings'").fetchone():return
    for key,value in db.execute('SELECT key,value FROM settings WHERE key LIKE ?',(PREFIX+'%',)).fetchall():
        p=json.loads(value);p.update(enabled=False,version=p['version']+1,reason='Installation récupérée : revalidez le dépôt et la règle avant activation.');write(db,p)
    db.execute('DELETE FROM settings WHERE key LIKE ? OR key LIKE ?',(retention.PREFIX+'%','cleanup-preview:%'))
