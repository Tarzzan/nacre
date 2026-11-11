import http.client
import importlib.util
import json
import os
from pathlib import Path
import secrets
import sqlite3
import stat
import sys
import tarfile
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('nacre_server', ROOT / 'console/server.py')
server = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = server
spec.loader.exec_module(server)


class ConsoleSecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        server.ROOT = Path(cls.temp.name)
        server.STATE = server.ROOT / 'state/console'
        server.DB = server.STATE / 'console.db'
        server.initialize()
        cls.http = server.Server(('127.0.0.1', 0), server.Handler)
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()
        cls.token, cls.csrf = server.make_session('admin')
        with server.database() as db:
            db.execute('INSERT INTO users(name,salt,hash,role) VALUES (?,?,?,?)', ('reader', '00'*16, 'unused', 'viewer'))
        cls.reader, cls.reader_csrf = server.make_session('reader')

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.temp.cleanup()

    def request(self, method, path, body=None, token=None, csrf=None, origin=None, raw=None, host=None, cookie=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.http.server_port, timeout=4)
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Cookie'] = 'nas_session=' + token
        if cookie is not None:
            headers['Cookie']=cookie
        if csrf:
            headers['X-CSRF-Token'] = csrf
        if origin:
            headers['Origin'] = origin
        if host:
            headers['Host'] = host
        payload = raw if raw is not None else json.dumps(body) if body is not None else None
        conn.request(method, path, payload, headers)
        response = conn.getresponse()
        data = response.read()
        status = response.status
        conn.close()
        return status, data

    def admin_post(self, route, body):
        return self.request('POST', route, body, self.token, self.csrf)

    def test_retention_requires_administrator_and_csrf(self):
        for route in ('/api/protection/retention-preview','/api/protection/retention-apply','/api/protection/retention-policy','/api/protection/cleanup-preview','/api/protection/cleanup-apply'):
            self.assertEqual(self.request('POST',route,{},self.reader,self.reader_csrf)[0],403)
            self.assertEqual(self.request('POST',route,{},self.token)[0],403)
            self.assertEqual(self.request('POST',route,{},self.token,self.csrf,'https://other.example')[0],403)
        self.assertEqual(self.request('GET','/api/protection/retention-policies',token=self.reader)[0],403)
        self.assertEqual(self.request('GET','/api/protection/cleanup-preview?job=fixture',token=self.reader)[0],403)

    def test_session_cookie_survives_unrelated_local_cookies(self):
        # Des applications sur d’autres ports déposent des valeurs JSON libres.
        for header in (
            'other=ok; preferences={"mode": "dark"}; nas_session='+self.token,
            'nas_session='+self.token+'; preferences={"mode": "dark"}',
        ):
            with self.subTest(header_order=header.startswith('nas_session')):
                code,payload=self.request('GET','/api/me',cookie=header)
                self.assertEqual(code,200)
                self.assertEqual(json.loads(payload)['name'],'admin')

    def test_ambiguous_or_malformed_session_cookie_is_refused(self):
        for header in (
            'nas_session='+self.token+'; nas_session='+self.reader,
            'nas_session='+self.token+'; nas_session='+self.token,
            'nas_session=', 'nas_session=invalid',
            'other_nas_session='+self.token,
            'nas_session='+self.token+'=suffix',
        ):
            self.assertEqual(self.request('GET','/api/me',cookie=header)[0],401)

    def test_installation_recovery_status_is_admin_only_and_has_no_secrets(self):
        route='/api/protection/installation'
        self.assertEqual(self.request('GET',route,token=self.reader)[0],403)
        status,body=self.request('GET',route,token=self.token)
        self.assertEqual(status,200)
        result=json.loads(body)
        self.assertTrue(result['offline_only'])
        self.assertNotIn('password',body.decode())
        self.assertNotIn('key_file',body.decode())

    def test_unauthenticated_private_api_and_files_denied(self):
        for path in ('/api/me', '/api/files', '/api/smb', '/api/download?path=test'):
            self.assertEqual(self.request('GET', path)[0], 401)

    def test_migration_status_is_admin_only_and_excludes_credentials(self):
        route='/api/protection/migrations'
        self.assertEqual(self.request('GET',route)[0],401)
        self.assertEqual(self.request('GET',route,token=self.reader)[0],403)
        code,payload=self.request('GET',route,token=self.token)
        self.assertEqual(code,200)
        self.assertEqual(json.loads(payload)['schema_version'],2)
        self.assertNotIn(b'password',payload)
        self.assertNotIn(b'hash',payload)

    def test_dns_rebinding_host_is_rejected(self):
        self.assertEqual(self.request('GET', '/', host='attacker.example')[0], 403)

    def test_csrf_and_foreign_origin_are_rejected(self):
        body = {'name': 'csrf-test'}
        self.assertEqual(self.request('POST', '/api/folder', body, self.token)[0], 403)
        self.assertEqual(self.request('POST', '/api/folder', body, self.token, self.csrf, 'https://attacker.example')[0], 403)
        self.assertFalse((server.ROOT/'data/fichiers/csrf-test').exists())

    def test_viewer_can_read_but_cannot_mutate(self):
        self.assertEqual(self.request('GET', '/api/files', token=self.reader)[0], 200)
        self.assertEqual(self.request('POST', '/api/folder', {'name': 'viewer-write'}, self.reader, self.reader_csrf)[0], 403)
        self.assertEqual(self.request('GET', '/api/files?area=restaurations', token=self.reader)[0],403)
        self.assertEqual(self.request('GET', '/api/protection/recovery?repo=anything', token=self.reader)[0],403)
        for path in ('/api/files?area=native_managed-example','/api/download?area=native_managed-example&path=file'):
            self.assertEqual(self.request('GET',path,token=self.reader)[0],403)

    def test_special_file_download_does_not_block_request_thread(self):
        path=server.ROOT/'data/fichiers/fifo-test'
        os.mkfifo(path)
        try:
            self.assertEqual(self.request('GET','/api/download?path=fifo-test',token=self.token)[0],400)
        finally:path.unlink()

    def test_native_storage_profiles_are_admin_only_and_never_apply_disks(self):
        for path in ('/api/storage/native', '/api/storage/profiles'):
            self.assertEqual(self.request('GET', path, token=self.reader)[0], 403)
        body={'name':'NAS miroir portable','layout':'mirror','filesystem':'btrfs','disk_bytes':[4000*1024**3,6000*1024**3]}
        self.assertEqual(self.request('POST','/api/storage/profile',body,self.reader,self.reader_csrf)[0],403)
        status,data=self.admin_post('/api/storage/profile',body)
        self.assertEqual(status,200)
        identifier=json.loads(data)['id']
        status,data=self.request('GET','/api/storage/profiles',token=self.token)
        profile=next(p for p in json.loads(data) if p['id']==identifier)
        self.assertFalse(profile['execution_enabled'])
        self.assertEqual(profile['config']['usable_upper_bytes'],4000*1024**3)
        self.assertEqual(profile['config']['assigned_devices'],[])
        self.assertEqual(self.admin_post('/api/storage/native-prepare',{'action':'format','volume':'system'})[0],503)
        self.assertEqual(self.admin_post('/api/storage/profile-delete',{'id':identifier})[0],200)

    def test_native_volume_write_upload_trash_restore_and_readonly_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);volume=root/'data';volume.mkdir();restoration=root/'restore';restoration.mkdir()
            def resource(identifier,path,kind,writable):
                meta=path.stat()
                return {'id':identifier,'path':str(path),'name':identifier,'kind':kind,'writable':writable,
                        'filesystem_uuid':'fixture','identity':{'dev':meta.st_dev,'ino':meta.st_ino}}
            values=[resource('managed-fixture',volume,'volume',True),resource('restore-fixture',restoration,'restore',False)]
            with patch.object(server,'native_resources',return_value=values):
                area='native_managed-fixture'
                status,data=self.request('GET','/api/areas',token=self.token)
                self.assertTrue(next(a for a in json.loads(data) if a['id']==area)['writable'])
                self.assertEqual(self.admin_post('/api/folder',{'area':area,'name':'dossier'})[0],200)
                self.assertEqual(self.request('POST','/api/upload?area='+area+'&path=dossier&name=preuve',token=self.token,csrf=self.csrf,raw=b'volume exact')[0],200)
                self.assertEqual((volume/'dossier/preuve').read_bytes(),b'volume exact')
                self.assertEqual(self.admin_post('/api/rename',{'area':area,'path':'dossier/preuve','name':'renomme'})[0],200)
                self.assertEqual(self.admin_post('/api/trash',{'area':area,'path':'dossier/renomme'})[0],200)
                with server.database() as db:row=dict(db.execute('SELECT * FROM trash WHERE area=?',(area,)).fetchone())
                self.assertFalse((volume/'dossier/renomme').exists())
                self.assertEqual(self.admin_post('/api/restore',{'id':row['id']})[0],200)
                self.assertEqual((volume/'dossier/renomme').read_bytes(),b'volume exact')
                self.assertEqual(self.admin_post('/api/folder',{'area':'native_restore-fixture','name':'refus'})[0],403)
                self.assertEqual(self.admin_post('/api/smb/share',{'area':'native_restore-fixture','name':'refus','users':['nas']})[0],403)
                self.assertEqual(self.request('GET','/api/files?area='+area+'&path=.nacre-trash',token=self.token)[0],403)
                volume.rename(root/'unmounted');volume.mkdir()
                self.assertEqual(self.admin_post('/api/folder',{'area':area,'name':'jamais'})[0],503)
                self.assertFalse((volume/'jamais').exists())

    def test_native_trash_symlink_cannot_redirect_a_move(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);volume=root/'volume';outside=root/'outside';volume.mkdir();outside.mkdir()
            (volume/'original').write_text('conserve')
            (volume/'.nacre-trash').symlink_to(outside,target_is_directory=True)
            meta=volume.stat();resource={'id':'managed-fixture','name':'Volume','path':str(volume),'kind':'volume','writable':True,'identity':{'dev':meta.st_dev,'ino':meta.st_ino}}
            with patch.object(server,'native_resources',return_value=[resource]):
                self.assertNotEqual(self.admin_post('/api/trash',{'area':'native_managed-fixture','path':'original'})[0],200)
            self.assertEqual((volume/'original').read_text(),'conserve')
            self.assertEqual(list(outside.iterdir()),[])

    def test_invalid_storage_profile_does_not_create_configuration(self):
        for sizes in ([True,1],[-1,1],[1],['4T','4T']):
            self.assertEqual(self.admin_post('/api/storage/profile',{'name':'Invalide','layout':'mirror','filesystem':'btrfs','disk_bytes':sizes})[0],400)

    def test_stream_upload_larger_than_old_256_mib_limit(self):
        length=257*1024**2
        conn=http.client.HTTPConnection('127.0.0.1',self.http.server_port,timeout=30)
        conn.putrequest('POST','/api/upload?name=grand-depot.bin')
        conn.putheader('Cookie','nas_session='+self.token)
        conn.putheader('X-CSRF-Token',self.csrf)
        conn.putheader('Content-Length',str(length))
        conn.endheaders()
        chunk=b'\0'*1024**2
        for _ in range(257):conn.send(chunk)
        response=conn.getresponse();response.read()
        self.assertEqual(response.status,200)
        conn.close()
        self.assertEqual((server.ROOT/'data/fichiers/grand-depot.bin').stat().st_size,length)
        (server.ROOT/'data/fichiers/grand-depot.bin').unlink()

    def test_upload_syncs_content_before_publication_and_directory_before_success(self):
        target=server.ROOT/'data/fichiers/sync-order.bin';observed=[];real_fsync=os.fsync
        def sync(fd):
            directory=stat.S_ISDIR(os.fstat(fd).st_mode)
            observed.append(('directory' if directory else 'file',target.exists()))
            real_fsync(fd)
        with patch.object(server.os,'fsync',side_effect=sync):
            status,_=self.request('POST','/api/upload?name='+target.name,token=self.token,csrf=self.csrf,raw=b'confirmed')
        self.assertEqual(status,200);self.assertEqual(observed,[('file',False),('directory',True)])
        self.assertEqual(target.read_bytes(),b'confirmed')

    def test_upload_file_sync_failure_is_not_acknowledged_or_published(self):
        target=server.ROOT/'data/fichiers/sync-file-failure.bin'
        before=set(target.parent.glob('.nacre-upload-*'))
        with patch.object(server.os,'fsync',side_effect=OSError('test sync failure')):
            status,_=self.request('POST','/api/upload?name='+target.name,token=self.token,csrf=self.csrf,raw=b'unconfirmed')
        self.assertEqual(status,500);self.assertFalse(target.exists())
        self.assertEqual(set(target.parent.glob('.nacre-upload-*')),before)

    def test_upload_directory_sync_failure_preserves_complete_file_without_success(self):
        target=server.ROOT/'data/fichiers/sync-directory-failure.bin';real_fsync=os.fsync
        def sync(fd):
            if stat.S_ISDIR(os.fstat(fd).st_mode):raise OSError('test directory sync failure')
            real_fsync(fd)
        with patch.object(server.os,'fsync',side_effect=sync):
            status,_=self.request('POST','/api/upload?name='+target.name,token=self.token,csrf=self.csrf,raw=b'complete but unconfirmed')
        self.assertEqual(status,500);self.assertEqual(target.read_bytes(),b'complete but unconfirmed')
        self.assertEqual(self.request('POST','/api/upload?name='+target.name,token=self.token,csrf=self.csrf,raw=b'retry')[0],409)

    def test_physical_capacity_guard_rejects_without_receiving_body(self):
        conn=http.client.HTTPConnection('127.0.0.1',self.http.server_port,timeout=5)
        conn.putrequest('POST','/api/upload?name=impossible.bin')
        conn.putheader('Cookie','nas_session='+self.token)
        conn.putheader('X-CSRF-Token',self.csrf)
        conn.putheader('Content-Length',str(2**62))
        conn.endheaders()
        response=conn.getresponse();response.read()
        self.assertEqual(response.status,507)
        conn.close()

    def test_traversal_and_symlink_cannot_read_outside_volume(self):
        outside = server.ROOT / 'confidentiel'
        outside.write_text('secret-ne-doit-pas-sortir')
        (server.ROOT/'data/fichiers/lien-externe').symlink_to(outside)
        (server.ROOT/'data/fichiers/dossier-externe').symlink_to(server.ROOT, target_is_directory=True)
        for path in ('/api/files?path=..', '/api/download?path=lien-externe', '/api/files?path=dossier-externe'):
            status, data = self.request('GET', path, token=self.token)
            self.assertNotEqual(status, 200)
            self.assertNotIn(b'secret-ne-doit-pas-sortir', data)

    def test_upload_no_overwrite_and_trash_restore_round_trip(self):
        status, _ = self.admin_post('/api/folder', {'name': 'test-fichiers'})
        self.assertEqual(status, 200)
        endpoint = '/api/upload?path=test-fichiers&name=preuve.txt'
        status, _ = self.request('POST', endpoint, token=self.token, csrf=self.csrf, raw=b'contenu exact')
        self.assertEqual(status, 200)
        self.assertEqual(self.request('POST', endpoint, token=self.token, csrf=self.csrf, raw=b'ecrasement')[0], 409)
        path = server.ROOT/'data/fichiers/test-fichiers/preuve.txt'
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o660)
        status, data = self.request('GET', '/api/download?path=test-fichiers/preuve.txt', token=self.token)
        self.assertEqual((status, data), (200, b'contenu exact'))
        self.assertEqual(self.admin_post('/api/trash', {'path':'test-fichiers/preuve.txt'})[0], 200)
        self.assertFalse(path.exists())
        status, data = self.request('GET', '/api/trash', token=self.token)
        row = next(x for x in json.loads(data) if x['original']=='test-fichiers/preuve.txt')
        self.assertEqual(self.admin_post('/api/restore', {'id':row['id']})[0], 200)
        self.assertEqual(path.read_bytes(), b'contenu exact')

    def test_one_time_access_ticket_cannot_be_replayed(self):
        token = secrets.token_urlsafe(32)
        with server.database() as db:
            db.execute('INSERT INTO tickets VALUES (?,?)', (server.digest(token), time.time()+60))
        path = '/connexion-locale?ticket=' + token
        self.assertEqual(self.request('GET', path)[0], 303)
        self.assertEqual(self.request('GET', path)[0], 401)

    def test_cannot_disable_own_administrator_account(self):
        self.assertEqual(self.admin_post('/api/user/update', {'name':'admin','role':'viewer','active':True})[0], 400)
        self.assertEqual(self.admin_post('/api/user/update', {'name':'admin','role':'admin','active':False})[0], 400)

    def test_invalid_retention_cannot_change_camera_configuration(self):
        for days in (0,31,True,'2',-1):
            self.assertEqual(self.admin_post('/api/camera/settings', {'days':days,'enabled':True})[0], 400)

    def test_disable_console_account_revokes_existing_access(self):
        with server.database() as db:
            db.execute('INSERT INTO users(name,salt,hash,role) VALUES (?,?,?,?)', ('temporary', '00'*16, 'unused', 'viewer'))
        token,_=server.make_session('temporary')
        self.assertEqual(self.request('GET','/api/me',token=token)[0],200)
        self.assertEqual(self.admin_post('/api/user/update', {'name':'temporary','role':'viewer','active':False})[0],200)
        self.assertEqual(self.request('GET','/api/me',token=token)[0],401)

    def test_backup_does_not_follow_links_or_include_configuration(self):
        (server.ROOT/'data/fichiers/sauvegarder.txt').write_text('contenu sauvegardé')
        outside = server.ROOT/'identifiants-prives'
        outside.write_text('ne jamais exporter')
        (server.ROOT/'data/fichiers/lien-backup').symlink_to(outside)
        job = secrets.token_hex(8)
        with server.database() as db:
            db.execute('INSERT INTO jobs(id,kind,status,result,ts) VALUES (?,?,?,?,?)', (job,'backup','running','{}',time.time()))
        server.run_backup(job,'admin')
        with server.database() as db:
            row=db.execute('SELECT * FROM jobs WHERE id=?',(job,)).fetchone()
        self.assertEqual(row['status'],'done')
        with tarfile.open(server.ROOT/'data/sauvegardes'/json.loads(row['result'])['file']) as archive:
            names=archive.getnames()
            self.assertIn('sauvegarder.txt',names)
            self.assertFalse(any('lien' in name or 'identifiants' in name or 'console' in name for name in names))


if __name__ == '__main__':
    unittest.main()
