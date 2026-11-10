"""Tâches d’installation fermées ; aucun shell ni paquet choisi par le client."""
import json
import time

COMPONENTS = {'restic', 'video', 'fichiers'}
KINDS = ('component_install', 'camera_add')


def ensure_idle(app):
    with app.database() as db:
        busy = db.execute("SELECT 1 FROM jobs WHERE kind IN ('component_install','camera_add') AND status IN ('queued','running')").fetchone()
    if busy:
        raise app.Problem('Une installation ou configuration caméra est déjà en cours. Consultez Services.', 409)


def submit(app, body, actor):
    component = body.get('component')
    if component not in COMPONENTS:
        raise app.Problem('Composant non autorisé.')
    if body.get('confirm') is not True:
        raise app.Problem('Confirmez le téléchargement et le démarrage du composant.')
    ensure_idle(app)
    identifier = app.protection().submit('component_install', actor, {'component': component})
    app.audit(actor, 'Installation demandée', component)
    return {'job': identifier}


def catalog(app):
    from onboarding import status
    setup = status(app)
    docker = next(c for c in setup['capabilities'] if c['id']=='docker')['ready']
    restic = next(c for c in setup['capabilities'] if c['id']=='restic')['ready']
    with app.database() as db:
        rows = db.execute("SELECT id,kind,status,result,progress,ts,options FROM jobs WHERE kind IN ('component_install','camera_add') ORDER BY ts DESC LIMIT 12").fetchall()
    return {'docker_ready': docker, 'components': [
        {'id':'restic','name':'Sauvegardes · restic','available':restic,'installable':True,
         'description':'Télécharger le moteur officiel avec vérification SHA-256. Aucun dépôt ni plan créé.'},
        {'id':'fichiers','name':'Partages · Samba','available':False,'installable':docker,
         'description':'Construire le service de fichiers et publier les partages configurés sur le port local 1445.'},
        {'id':'video','name':'Surveillance · Frigate','available':False,'installable':docker,
         'description':'Télécharger l’image prévue pour cette architecture et démarrer la vidéo sur le port local 8971.'}],
        'jobs':[public_job(row) for row in rows]}


def public_job(row):
    value = {key: row[key] for key in ('id', 'kind', 'status', 'ts')}
    value.update(result=json.loads(row['result']), progress=json.loads(row['progress']))
    component = json.loads(row['options']).get('component')
    if row['kind'] == 'component_install' and component in COMPONENTS:
        value['component'] = component
    return value


def ready(app, component):
    lines = app.compose('ps','--all','--format','json',component,timeout=10).splitlines()
    if not lines:
        return False
    items = [json.loads(line) for line in lines]
    if not all(item.get('State') == 'running' for item in items):
        return False
    if component == 'video':
        return all(item.get('Health') == 'healthy' for item in items)
    # Le conteneur peut tourner alors que l'entrypoint prépare encore Samba.
    try:
        return 'PONG from pid ' in app.compose('exec','-T','fichiers','smbcontrol','smbd','ping',timeout=10)
    except app.Problem:
        return False


def install(app, row):
    component = json.loads(row['options'])['component']
    if component not in COMPONENTS:
        raise app.Problem('Composant non autorisé.')
    progress = lambda message: app.protection().update(row['id'], progress={'message': message})
    if component == 'restic':
        progress('Téléchargement et vérification du moteur officiel…')
        from install_restic import install as install_restic
        install_restic(app.ROOT)
        result = {'message':'Moteur de sauvegarde installé et vérifié.'}
    else:
        from onboarding import probe
        if not probe(['docker','info','--format','{{.ServerVersion}}']) or not probe(['docker','compose','version']):
            raise app.Problem('Docker Engine et Compose doivent être installés et accessibles au compte Nacre.')
        if component == 'video':
            progress('Téléchargement de Frigate…')
            app.compose('pull','video',timeout=1800)
        else:
            progress('Préparation du service Samba…')
            manager = app.shares()
            manager.prepare_start(app.smb_state())
            if not (app.ROOT/'state/samba/recovery.compose.json').exists():
                app.compose('build','fichiers',timeout=1200)
        progress('Démarrage et contrôle du service…')
        app.compose('up','-d','--no-deps','--no-build',component,timeout=180)
        # Un code de sortie Compose réussi ne suffit pas à annoncer un service prêt.
        confirmed = False
        for _ in range(30):
            if ready(app, component):
                confirmed = True
                break
            time.sleep(2)
        if not confirmed:
            raise app.Problem('Composant préparé, mais son démarrage n’est pas confirmé. Consultez Services avant de réessayer.')
        if component == 'fichiers':
            manager.set_intent(True)
            manager.apply(app.smb_state())
        result = {'message':'Service installé et démarrage confirmé.'}
    app.protection().update(row['id'], status='done', result=result, progress={'message':'Terminé','percent_done':1})
    app.audit(row['username'], 'Composant installé', component)
