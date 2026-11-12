"""Administration quotidienne : préférences locales et sessions de console."""
import platform
import time
import onboarding


def authorized(app, db, session):
    row = db.execute("SELECT u.role FROM sessions s JOIN users u ON u.name=s.name WHERE s.token=? AND s.expires>? AND u.active=1", (session['token'], time.time())).fetchone()
    if not row or row['role'] != 'admin':
        raise app.Problem('La session administrateur n’est plus valide.', 403)


def read(app, session):
    now = time.time()
    with app.database() as db:
        authorized(app, db, session)
        state = onboarding.read(app, db)
        rows = db.execute('SELECT u.name,u.role,u.active,count(s.token) AS valid_sessions FROM users u LEFT JOIN sessions s ON s.name=u.name AND s.expires>? AND u.active=1 GROUP BY u.name ORDER BY u.name', (now,)).fetchall()
    return {'name': state['name'], 'timezone': state['timezone'],
            'revision': state.get('preferences_revision', 0), 'setup_complete': state['phase']=='complete',
            'version': app.release_version(), 'system': platform.system(), 'architecture': platform.machine(),
            'accounts': [{**dict(row), 'current': row['name']==session['name']} for row in rows]}


def configure(app, body, session):
    name, timezone = onboarding.preferences(app, body)
    revision = body.get('revision')
    if type(revision) is not int or revision < 0:
        raise app.Problem('Rechargez les préférences avant de les enregistrer.', 409)
    with app.database() as db:
        db.execute('BEGIN IMMEDIATE')
        authorized(app, db, session)
        state = onboarding.read(app, db)
        if state['phase'] != 'complete':
            raise app.Problem('Terminez d’abord la première configuration.', 409)
        if state.get('preferences_revision', 0) != revision:
            raise app.Problem('Les préférences ont changé dans une autre session. Rechargez la page et vérifiez vos modifications.', 409)
        state.update(name=name, timezone=timezone, preferences_revision=revision+1)
        onboarding.write(db, state)
        db.execute('INSERT INTO audit(ts,username,action,detail) VALUES(?,?,?,?)', (time.time(),session['name'],'Préférences du NAS modifiées',name+' · '+timezone))
    return {'name': name, 'timezone': timezone, 'revision': revision+1}


def revoke(app, body, session):
    name = body.get('name')
    if not isinstance(name, str) or not name or len(name)>128 or body.get('confirm') is not True:
        raise app.Problem('Choisissez un compte et confirmez la déconnexion.')
    with app.database() as db:
        db.execute('BEGIN IMMEDIATE')
        authorized(app, db, session)
        if not db.execute('SELECT 1 FROM users WHERE name=?', (name,)).fetchone():
            raise app.Problem('Compte introuvable.', 404)
        # La session utilisée pour administrer reste ouverte, même pour soi-même.
        count = db.execute('DELETE FROM sessions WHERE name=? AND token<>? AND expires>?', (name,session['token'],time.time())).rowcount
        db.execute('INSERT INTO audit(ts,username,action,detail) VALUES(?,?,?,?)', (time.time(),session['name'],'Sessions de console révoquées',name+' · '+str(count)))
    return {'revoked': count, 'current_session_preserved': True}
