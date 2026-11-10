"""Schéma versionné, migration transactionnelle et copie préalable durable."""
from contextlib import closing
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import secrets
import sqlite3
import stat

VERSION = 2


class SchemaError(RuntimeError):
    pass


TABLES = {
    'users': 'name TEXT PRIMARY KEY, salt TEXT NOT NULL, hash TEXT NOT NULL, role TEXT NOT NULL',
    'sessions': 'token TEXT PRIMARY KEY, name TEXT NOT NULL, csrf TEXT NOT NULL, expires REAL NOT NULL',
    'tickets': 'token TEXT PRIMARY KEY, expires REAL NOT NULL',
    'audit': 'id INTEGER PRIMARY KEY, ts REAL, username TEXT, action TEXT, detail TEXT',
    'trash': 'id TEXT PRIMARY KEY, original TEXT, ts REAL',
    'jobs': 'id TEXT PRIMARY KEY, kind TEXT, status TEXT, result TEXT, ts REAL',
    'repositories': 'id TEXT PRIMARY KEY,name TEXT,path TEXT,key_file TEXT,created REAL,target TEXT',
    'plans': 'id TEXT PRIMARY KEY,name TEXT,repo TEXT,enabled INTEGER,config TEXT,next_run REAL,last_job TEXT,last_run REAL',
    'storage_profiles': 'id TEXT PRIMARY KEY, name TEXT, config TEXT, created REAL',
}
V2_TABLES = {'settings': 'key TEXT PRIMARY KEY, value TEXT NOT NULL'}

ADDITIONS = {
    'users': {'active': 'INTEGER NOT NULL DEFAULT 1'},
    'trash': {'area': "TEXT NOT NULL DEFAULT 'fichiers'"},
    'repositories': {'storage_uuid': "TEXT NOT NULL DEFAULT ''"},
    'jobs': {'options': "TEXT NOT NULL DEFAULT '{}'", 'progress': "TEXT NOT NULL DEFAULT '{}'",
             'cancel': 'INTEGER NOT NULL DEFAULT 0', 'pid': 'INTEGER', 'username': "TEXT NOT NULL DEFAULT 'admin'"},
}


def columns(db, table):
    return {r[1] for r in db.execute('PRAGMA table_info('+table+')')}


def migrate_v1(db):
    # execute(), jamais executescript() : ce dernier pourrait committer implicitement.
    for table, declaration in TABLES.items():
        db.execute('CREATE TABLE IF NOT EXISTS '+table+' ('+declaration+')')
    for table, additions in ADDITIONS.items():
        existing = columns(db, table)
        for column, declaration in additions.items():
            if column not in existing:
                db.execute('ALTER TABLE '+table+' ADD COLUMN '+column+' '+declaration)


def private_directory(path):
    path = Path(path)
    path.mkdir(mode=0o700, exist_ok=True)
    meta = path.lstat()
    if not stat.S_ISDIR(meta.st_mode) or meta.st_uid != os.getuid() or meta.st_mode & 0o077:
        raise SchemaError('Le répertoire de reprise doit être privé et appartenir au compte de console.')
    return path


def private_file(path):
    meta = Path(path).lstat()
    if not stat.S_ISREG(meta.st_mode) or meta.st_nlink != 1 or meta.st_uid != os.getuid() or meta.st_mode & 0o077:
        raise SchemaError('Le fichier de reprise doit être privé, ordinaire et sans lien.')


def readonly(path):
    return sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True, timeout=30)


def checksum(path):
    with open(path, 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try: os.fsync(fd)
    finally: os.close(fd)


def check(db):
    if db.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
        raise SchemaError('La vérification SQLite a échoué.')


def checkpoint(path, old_version):
    directory = private_directory(path.parent/'migration-backups')
    name = 'schema-v'+str(old_version)+'-'+secrets.token_hex(12)
    target = directory/(name+'.sqlite3')
    fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    # Une autre connexion lit l'état validé, WAL inclus, pendant que le verrou
    # BEGIN IMMEDIATE interdit les écritures concurrentes de la migration.
    with closing(readonly(path)) as source, closing(sqlite3.connect(target)) as destination:
        source.backup(destination)
        check(destination)
    with open(target, 'rb') as stream: os.fsync(stream.fileno())
    record = {'format': 1, 'name': name, 'source_version': old_version,
              'target_version': VERSION, 'created': datetime.now(timezone.utc).isoformat(),
              'sha256': checksum(target), 'bytes': target.stat().st_size}
    record_path = directory/(name+'.json')
    fd = os.open(record_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(record, stream); stream.flush(); os.fsync(stream.fileno())
    sync_directory(directory)
    sync_directory(path.parent)
    return record


def ensure(path):
    path = Path(path)
    private_directory(path.parent)
    lock_fd = os.open(path.parent/'schema.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        if path.exists() or path.is_symlink(): private_file(path)
        else:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600); os.close(fd)
        with closing(sqlite3.connect(path, timeout=30, isolation_level=None)) as db:
            db.execute('PRAGMA trusted_schema=OFF')
            version = db.execute('PRAGMA user_version').fetchone()[0]
            if version > VERSION:
                raise SchemaError('Base créée par une version plus récente : démarrage refusé, sans rétrogradation.')
            if version == VERSION:
                return
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            try:
                check(db)
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' LIMIT 1").fetchone():
                    checkpoint(path, version)
                if version < 1:
                    migrate_v1(db)
                for table, declaration in V2_TABLES.items():
                    db.execute('CREATE TABLE IF NOT EXISTS '+table+' ('+declaration+')')
                for table, declaration in (TABLES | V2_TABLES).items():
                    required = {part.strip().split()[0] for part in declaration.split(',')} | set(ADDITIONS.get(table, {}))
                    if not required.issubset(columns(db, table)):
                        raise SchemaError('Structure de base non reconnue : migration annulée.')
                check(db)
                db.execute('PRAGMA user_version='+str(VERSION))
                db.execute('COMMIT')
            except BaseException:
                db.execute('ROLLBACK')
                raise
        sync_directory(path.parent)
    finally:
        os.close(lock_fd)


def status(path):
    path = Path(path)
    with closing(readonly(path)) as db:
        version = db.execute('PRAGMA user_version').fetchone()[0]
    records = []
    directory = path.parent/'migration-backups'
    if directory.exists():
        private_directory(directory)
        for item in sorted(directory.glob('schema-v*.json')):
            try:
                private_file(item)
                record = json.loads(item.read_text())
                if record.get('format') != 1 or record.get('name') != item.stem: continue
                backup = item.with_suffix('.sqlite3'); private_file(backup)
                records.append({k: record[k] for k in ('name', 'source_version', 'target_version', 'created', 'bytes')})
            except (OSError, ValueError, KeyError, SchemaError):
                continue
    return {'schema_version': version, 'supported_version': VERSION, 'checkpoints': records,
            'scope': 'console-database', 'automatic_restore': False}
