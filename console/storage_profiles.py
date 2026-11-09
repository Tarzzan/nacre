"""Profils matériels de déploiement. Ils n'affectent aucun disque réel."""
import json
import secrets
import time


class Profiles:
    def __init__(self, app):
        self.app = app

    def list(self):
        with self.app.database() as db:
            return [{**dict(row), 'config': json.loads(row['config']), 'execution_enabled': False} for row in db.execute('SELECT * FROM storage_profiles ORDER BY created DESC')]

    def create(self, body, actor):
        name = body.get('name', '').strip()
        layout, filesystem = body.get('layout'), body.get('filesystem')
        sizes = body.get('disk_bytes')
        if not name or len(name) > 80 or layout not in ('single', 'mirror') or filesystem not in ('btrfs', 'ext4'):
            raise self.app.Problem('Profil de stockage invalide.')
        if not isinstance(sizes, list) or len(sizes) != (1 if layout == 'single' else 2) or any(type(x) is not int or x <= 0 or x > 2**63-1 for x in sizes):
            raise self.app.Problem('Capacités physiques invalides pour ce profil.')
        config = {'layout': layout, 'filesystem': filesystem, 'disk_bytes': sizes,
                  'raw_bytes': sum(sizes), 'usable_upper_bytes': min(sizes),
                  'fault_tolerance': 1 if layout == 'mirror' else 0,
                  'raid_engine': 'mdadm RAID1' if layout == 'mirror' else None,
                  'native_snapshot_family': 'btrfs' if filesystem == 'btrfs' else None,
                  'state': 'design', 'assigned_devices': []}
        identifier = secrets.token_hex(12)
        with self.app.database() as db:
            db.execute('INSERT INTO storage_profiles VALUES(?,?,?,?)', (identifier, name, json.dumps(config), time.time()))
        self.app.audit(actor, 'Profil matériel préparé', name)
        return {'id': identifier, 'execution_enabled': False}

    def prepare(self, body, actor):
        with self.app.database() as db:
            row=db.execute('SELECT * FROM storage_profiles WHERE id=?',(body.get('id'),)).fetchone()
        if not row:
            raise self.app.Problem('Profil inconnu.',404)
        profile=json.loads(row['config'])
        return self.app.native_storage('prepare',actor,{'action':'provision','profile':{**profile,'name':row['name']},'devices':body.get('devices')})

    def delete(self, body, actor):
        with self.app.database() as db:
            row = db.execute('SELECT name FROM storage_profiles WHERE id=?', (body.get('id'),)).fetchone()
            if not row:
                raise self.app.Problem('Profil inconnu.', 404)
            db.execute('DELETE FROM storage_profiles WHERE id=?', (body['id'],))
        self.app.audit(actor, 'Profil matériel supprimé', row['name'])
        return {'ok': True}
