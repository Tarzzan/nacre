#!/usr/bin/env python3
"""Point d'entrée du service natif : le moteur de native_storage, étendu de la suppression explicite de points.

native_storage.py reste tel quel ; ce module y ajoute une seule action, « delete », sur le même modèle préparation
puis validation. Le service ne supprime rien tant que root n'a pas écrit "deletion": true dans sa politique.
La commande n'est jamais récursive ni forcée, et chaque effet est relu sur le stockage avant d'être inscrit au catalogue.
Voir docs/NATIVE-SNAPSHOT-POLICY.md.
"""
import json
import os
from pathlib import Path
import re
import secrets
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import native_storage
from native_storage import NativeError, canonical, fingerprint

MAX_DELETE = 50     # points par plan de suppression
DELETE_BUDGET = 45  # secondes : au-delà, les points restants ne sont pas touchés


class Engine(native_storage.Engine):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if kwargs.get('recover', args[3] if len(args) > 3 else True):
            with self.db:
                self.db.execute("UPDATE points SET status='uncertain', detail='Service interrompu pendant la suppression ; vérifier le stockage.' WHERE status='deleting'")

    def policy(self):
        policy = super().policy()
        if type(policy.get('deletion', False)) is not bool:
            raise NativeError('Politique invalide : « deletion » vaut true ou false.')
        return policy

    def status(self):
        # Suppression non confirmée : relire l'état réel du stockage, sans rien rejouer.
        for row in self.db.execute("SELECT * FROM points WHERE status='uncertain' AND native_identity!=''").fetchall():
            self.settle(dict(row))
        return {**super().status(), 'deletion': self.policy().get('deletion') is True}

    def prepare(self, uid, actor, body):
        if body.get('action') == 'delete':
            return self.prepare_delete(uid, actor, body)
        return super().prepare(uid, actor, body)

    def commit(self, uid, actor, body):
        row = self.db.execute('SELECT * FROM plans WHERE id=?', (body.get('plan'),)).fetchone()
        if not row or json.loads(row['payload']).get('action') != 'delete':
            return super().commit(uid, actor, body)
        if row['uid'] != uid or row['actor'] != actor or row['consumed'] or row['expires'] < time.time():
            raise NativeError('Plan expiré, déjà exécuté ou appartenant à un autre compte.')
        plan = json.loads(row['payload'])
        if body.get('confirmation') != plan['confirmation']:
            raise NativeError('Recopier exactement la confirmation du plan.')
        return self.commit_delete(row, plan, actor)

    # --- Suppression explicite de points : jamais implicite, jamais récursive, jamais forcée. ---

    def may_delete(self):
        if self.policy().get('deletion') is not True:
            raise NativeError('La suppression de points n’est pas autorisée par la politique système.')

    def unread(self, volume):
        if self.db.execute("SELECT 1 FROM actions WHERE action='clone' AND volume=? AND status IN ('queued','running','uncertain')", (volume['id'],)).fetchone():
            raise NativeError('Une restauration est en cours ou à vérifier sur ce volume : aucun point ne peut être supprimé.')

    def deletable(self, volume, point, fds):
        """Identité inchangée, et rien ne lit ni ne dépend du point."""
        self.verify_point(volume, point, fds)
        if volume['family'] == 'zfs':
            raw = self.run(['zfs', 'get', '-Hp', '-o', 'property,value', 'clones,userrefs', volume['dataset'] + '@' + point['object']])
            props = {line.partition('\t')[0]: line.partition('\t')[2].strip() for line in raw.splitlines()}
            if props.get('clones') not in ('', '-') or props.get('userrefs') != '0':
                raise NativeError('Une copie ZFS dépend de ce point, ou il est retenu : il ne peut pas être supprimé.')
        elif volume['family'] == 'lvm':
            group, origin = volume['lv'].split('/')
            raw = json.loads(self.run(['lvs', '--reportformat', 'json', '-o', 'lv_attr,origin', group + '/' + point['object']]))['report'][0]['lv'][0]
            attr = raw['lv_attr'].strip()
            if str(raw.get('origin', '')).strip() != origin or len(attr) < 6 or attr[5] == 'o':
                raise NativeError('Ce point LVM est ouvert, ou n’est pas un point de ce volume : il ne peut pas être supprimé.')

    def current(self, volume, item, fds):
        row = self.db.execute("SELECT * FROM points WHERE id=? AND volume=? AND status='ready'", (item['id'], volume['id'])).fetchone()
        if not row or row['object'] != item['object'] or row['native_identity'] != item['native_identity']:
            raise NativeError('Un point du plan n’est plus prêt : préparer un nouveau plan.')
        point = dict(row)
        self.deletable(volume, point, fds)
        return point

    def prepare_delete(self, uid, actor, body):
        self.may_delete()
        volume = self.volume(body.get('volume'))
        wanted = body.get('points')
        if (not isinstance(wanted, list) or not 1 <= len(wanted) <= MAX_DELETE
                or not all(isinstance(value, str) and re.fullmatch(r'[a-f0-9]{32}', value) for value in wanted) or len(set(wanted)) != len(wanted)):
            raise NativeError(f'Liste de points invalide : de 1 à {MAX_DELETE} points distincts.')
        self.unread(volume)
        points = []
        with self.paths(volume) as fds:
            identity = self.inspect(volume, fds, require_capacity=False)
            for identifier in wanted:
                row = self.db.execute("SELECT * FROM points WHERE id=? AND volume=? AND status='ready'", (identifier, volume['id'])).fetchone()
                if not row:
                    raise NativeError('Point inconnu, d’un autre volume ou non prêt : aucun point ne sera supprimé.')
                point = dict(row)
                self.deletable(volume, point, fds)
                points.append({key: point[key] for key in ('id', 'object', 'native_identity', 'created')})
        identifier = secrets.token_hex(16)
        count = len(points)
        confirmation = f'SUPPRIMER {count} POINT{"S" if count > 1 else ""} DE {volume["id"]}'
        payload = {'action': 'delete', 'volume': volume['id'], 'identity': identity, 'policy': fingerprint(volume),
                   'points': points, 'confirmation': confirmation}
        expiry = time.time() + 120
        with self.db:
            self.db.execute('DELETE FROM plans WHERE expires < ?', (time.time(),))
            self.db.execute('INSERT INTO plans(id,uid,actor,expires,payload) VALUES(?,?,?,?,?)', (identifier, uid, actor, expiry, canonical(payload)))
        return {'id': identifier, 'expires': expiry, 'action': 'delete', 'volume': volume['id'], 'confirmation': confirmation,
                'points': [{'id': point['id'], 'created': point['created']} for point in points],
                'effect': 'Supprimer définitivement ' + ('ces %d points natifs.' % count if count > 1 else 'ce point natif.'),
                'notes': ['Un point supprimé ne peut pas être récupéré.', 'Le volume, ses fichiers actuels et les points non listés ne sont pas modifiés.',
                          'Au premier point qui ne peut pas être supprimé, l’opération s’arrête et les suivants restent intacts.']}

    def commit_delete(self, row, plan, actor):
        started = time.monotonic()
        self.may_delete()
        volume = self.volume(plan['volume'])
        if fingerprint(volume) != plan['policy']:
            raise NativeError('Politique modifiée ; préparer un nouveau plan.')
        with self.paths(volume) as fds:
            if self.inspect(volume, fds, require_capacity=False) != plan['identity']:
                raise NativeError('Identité modifiée ; préparer un nouveau plan.')
            self.unread(volume)
            # Tout le plan est revérifié avant le premier effet : un seul refus, et rien n'est supprimé.
            for item in plan['points']:
                self.current(volume, item, fds)
            with self.db:
                self.db.execute('UPDATE plans SET consumed=1 WHERE id=?', (row['id'],))
            deleted, uncertain, reason = [], [], ''
            for item in plan['points']:
                if time.monotonic() - started > DELETE_BUDGET:
                    reason = 'Durée maximale atteinte : les points restants n’ont pas été touchés.'
                    break
                try:
                    point = self.current(volume, item, fds)
                except NativeError as error:
                    reason = str(error)
                    break
                # Marquer et journaliser AVANT la commande : une coupure laisse une trace, jamais un rejeu.
                with self.db:
                    self.db.execute("UPDATE points SET status='deleting',detail='Suppression en cours.' WHERE id=?", (point['id'],))
                    self.db.execute('INSERT INTO actions(id,ts,actor,action,volume,object,status) VALUES(?,?,?,?,?,?,?)',
                                    (secrets.token_hex(16), time.time(), actor, 'delete', volume['id'], point['object'], 'running'))
                try:
                    self.remove(volume, point, fds)
                except Exception:
                    pass  # l'état réel du stockage décide, pas le code de retour
                state = self.settle(point, volume, fds)
                if state == 'absent':
                    deleted.append(point['id'])
                    continue
                if state == 'unknown':
                    uncertain.append(point['id'])
                    reason = 'La suppression d’un point n’est pas confirmée : vérifier le stockage.'
                else:
                    reason = 'Le système a refusé la suppression d’un point, qui reste intact.'
                break
            done = set(deleted) | set(uncertain)
            return {'ok': not reason, 'deleted': deleted, 'uncertain': uncertain,
                    'kept': [item['id'] for item in plan['points'] if item['id'] not in done], 'reason': reason}

    def remove(self, volume, point, fds):
        name = point['object']
        if not re.fullmatch(r'nacre_[a-f0-9]{32}', name):
            raise NativeError('Nom de point non géré.')
        if volume['family'] == 'btrfs':
            self.run(['btrfs', 'subvolume', 'delete', '--commit-after', f'/proc/self/fd/{fds["snapshots"]}/{name}'], tuple(fds.values()))
        elif volume['family'] == 'zfs':
            # Sans -r, -R ni -f : un clone ou une retenue font échouer la commande.
            self.run(['zfs', 'destroy', volume['dataset'] + '@' + name])
        else:
            self.run(['lvremove', '--yes', volume['lv'].split('/')[0] + '/' + name])

    def presence(self, volume, point, fds):
        """Lecture seule. « absent » demande une preuve : le bon conteneur a été lu et le nom n'y est plus."""
        try:
            name = point['object']
            if volume['family'] == 'btrfs':
                try:
                    os.stat(name, dir_fd=fds['snapshots'], follow_symlinks=False)
                except FileNotFoundError:
                    return 'absent'
            elif volume['family'] == 'zfs':
                listed = self.run(['zfs', 'list', '-H', '-t', 'snapshot', '-d', '1', '-o', 'name', volume['dataset']]).splitlines()
                if volume['dataset'] + '@' + name not in [line.strip() for line in listed]:
                    return 'absent'
            else:
                rows = json.loads(self.run(['lvs', '--reportformat', 'json', '-a', '-o', 'lv_name', volume['lv'].split('/')[0]]))['report'][0]['lv']
                if not any(str(item['lv_name']).strip() == name for item in rows):
                    return 'absent'
            self.verify_point(volume, point, fds)
            return 'present'
        except (NativeError, OSError, ValueError, KeyError):
            return 'unknown'  # nom encore là mais identité non confirmée, ou stockage illisible

    def settle(self, point, volume=None, fds=None):
        """Accorder le catalogue à l'état réel d'un point marqué pour suppression. Ne supprime jamais rien du stockage."""
        try:
            if volume is None:
                volume = self.volume(point['volume'])
                with self.paths(volume) as opened:
                    self.inspect(volume, opened, require_capacity=False)
                    state = self.presence(volume, point, opened)
            else:
                state = self.presence(volume, point, fds)
        except (NativeError, OSError, ValueError, KeyError):
            state = 'unknown'
        if state == 'unknown' and point['status'] == 'uncertain':
            return state  # déjà « à vérifier » : rien de nouveau à écrire
        outcome = {'absent': 'done', 'present': 'failed', 'unknown': 'uncertain'}[state]
        with self.db:
            if state == 'absent':
                self.db.execute('DELETE FROM points WHERE id=?', (point['id'],))
            elif state == 'present':
                self.db.execute("UPDATE points SET status='ready',detail='' WHERE id=?", (point['id'],))
            else:
                self.db.execute("UPDATE points SET status='uncertain',detail='Suppression non confirmée ; vérifier le stockage.' WHERE id=?", (point['id'],))
            self.db.execute("UPDATE actions SET status=? WHERE action='delete' AND object=? AND status IN ('running','uncertain')", (outcome, point['object']))
        print(canonical({'event': 'delete', 'volume': point['volume'], 'object': point['object'], 'state': state}), flush=True)
        return state


def serve():
    # Le service démarre le moteur étendu ; tout le reste du démarrage est celui de native_storage.
    native_storage.Engine = Engine
    native_storage.serve()


if __name__ == '__main__':
    serve()
