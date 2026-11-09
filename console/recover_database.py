#!/usr/bin/env python3
"""Préparer une base de console récupérée, sans remplacer la base active."""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile

from schema import VERSION, SchemaError, check, checksum, columns, private_directory, private_file, readonly, status, sync_directory


def prepare(source, output):
    source, output = Path(source), Path(output)
    private_file(source)
    record_path = source.with_suffix('.json')
    private_file(record_path)
    record = json.loads(record_path.read_text())
    if not isinstance(record, dict) or record.get('format') != 1 or record.get('name') != source.stem or source.suffix != '.sqlite3':
        raise SchemaError('Manifest de récupération invalide.')
    if type(record.get('source_version')) is not int or not 0 <= record['source_version'] <= VERSION:
        raise SchemaError('Version de sauvegarde non prise en charge.')
    private_directory(output.parent)
    if output.exists() or output.is_symlink():
        raise SchemaError('La destination existe déjà. Choisir un nouveau nom.')
    fd, name = tempfile.mkstemp(prefix='.nacre-recovery-', dir=output.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'wb') as destination, source.open('rb') as incoming:
            shutil.copyfileobj(incoming, destination, 1024**2)
            destination.flush(); os.fsync(destination.fileno())
        if checksum(temporary) != record.get('sha256'):
            raise SchemaError('Empreinte de la copie incorrecte : récupération refusée.')
        with closing(sqlite3.connect(temporary)) as db:
            db.execute('PRAGMA trusted_schema=OFF')
            check(db)
            if db.execute('PRAGMA user_version').fetchone()[0] != record['source_version']:
                raise SchemaError('Version SQLite différente du manifest.')
            if db.execute("SELECT 1 FROM sqlite_master WHERE type IN ('trigger','view')").fetchone():
                raise SchemaError('Objets SQLite non pris en charge dans cette copie.')
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if 'users' not in tables:
                raise SchemaError('Aucun catalogue de comptes dans cette copie.')
            active = ' AND active=1' if 'active' in columns(db, 'users') else ''
            if not db.execute("SELECT 1 FROM users WHERE role='admin'"+active).fetchone():
                raise SchemaError('La copie ne contient aucun administrateur actif.')
            db.execute('BEGIN IMMEDIATE')
            for table in ('sessions', 'tickets'):
                if table in tables: db.execute('DELETE FROM '+table)
            if 'plans' in tables: db.execute('UPDATE plans SET enabled=0,next_run=NULL')
            if 'jobs' in tables:
                extra = ',pid=NULL' if 'pid' in columns(db, 'jobs') else ''
                if 'cancel' in columns(db, 'jobs'): extra += ',cancel=1'
                db.execute("UPDATE jobs SET status='failed',result=?"+extra+" WHERE status IN ('queued','running')",
                           (json.dumps({'error': 'Tâche interrompue par la reprise de la base. Vérifier les données avant de relancer.'}),))
            db.commit()
            check(db)
        with open(temporary, 'rb') as stream: os.fsync(stream.fileno())
        # Publication sans écrasement, même si un fichier apparaît entre-temps.
        os.link(temporary, output, follow_symlinks=False)
        temporary.unlink()
        sync_directory(output.parent)
        return {'output': str(output), 'source_version': record['source_version'],
                'sha256': checksum(output), 'sessions_revoked': True,
                'plans_disabled': True, 'active_database_replaced': False}
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    listing = sub.add_parser('list', help='Lister les points de reprise sans afficher leur contenu')
    listing.add_argument('--database', type=Path, required=True)
    recovery = sub.add_parser('prepare', help='Préparer une copie assainie dans un nouveau fichier privé')
    recovery.add_argument('--source', type=Path, required=True)
    recovery.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = status(args.database) if args.action == 'list' else prepare(args.source, args.output)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (SchemaError, OSError, sqlite3.Error, ValueError) as error:
        # Ne pas exposer le contenu de la base ni des traces contenant des données.
        parser.exit(1, 'Récupération refusée : '+(str(error) if isinstance(error, SchemaError) else 'fichier indisponible ou invalide.')+'\n')


if __name__ == '__main__':
    main()
