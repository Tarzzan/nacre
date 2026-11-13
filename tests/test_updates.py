"""Real update/recovery processes on temporary roots. No Docker or real NAS data."""
from contextlib import closing
import hashlib
import gzip
import http.client
import io
import json
import os
import py_compile
from pathlib import Path
import secrets
import signal
import socket
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace

SOURCE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(SOURCE/'console'))
import update_engine as engine
import schema


def seed(root,base):
    root.mkdir(mode=0o700)
    for name in engine.inventory(SOURCE):engine.write(root/name,(SOURCE/name).read_bytes())
    # Disable background collectors only in this disposable copy of the real server.
    server=(root/'console/server.py').read_text()
    for call in ('protection().start_scheduler()','shares().start_watch()','start_alerts(sys.modules[__name__])','start_notifications(sys.modules[__name__])'):
        server=server.replace(call,'pass # isolated test background')
    engine.write(root/'console/server.py',server.encode())
    engine.write(root/'CHANGELOG.md',b'# Changelog\n\n## 1.0.0-alpha.1 \xe2\x80\x94 fixture\n')
    key=base/'signing.key'
    subprocess.run(['openssl','genpkey','-algorithm','ED25519','-out',str(key)],check=True,capture_output=True)
    key.chmod(0o600)
    subprocess.run(['openssl','pkey','-in',str(key),'-pubout','-out',str(root/'console/update-signing.pub')],check=True,capture_output=True)
    (root/'state/console').mkdir(parents=True,mode=0o700)
    schema.ensure(root/'state/console/console.db')
    token=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(24)
    with closing(sqlite3.connect(root/'state/console/console.db')) as db:
        db.execute("INSERT INTO users VALUES('admin','00','unchanged-fixture','admin',1)")
        db.execute('INSERT INTO sessions VALUES(?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),'admin',csrf,time.time()+3600))
        db.execute("INSERT INTO settings VALUES('onboarding',?)",(json.dumps({'phase':'complete','name':'Banc mises à jour','timezone':'America/Cayenne','existing':False}),))
        db.commit()
    engine.write(root/'state/console/smb.json',b'{"users":[],"shares":[]}')
    engine.write(root/'state/console/keys/fixture.key',secrets.token_bytes(32))
    engine.write(root/'data/fichiers/witness',b'user data preserved')
    engine.provision(root)
    return key,token,csrf


def package(root,key,dest,changes=None,extra=None,sign=True):
    files={n:(root/n).read_bytes() for n in engine.inventory(root)}
    files['CHANGELOG.md']=b'# Changelog\n\n## 1.0.0-alpha.2 \xe2\x80\x94 fixture\n'
    files.update(changes or {})
    manifest=json.dumps({'format':1,'schema':2,'version':'1.0.0-alpha.2','commit':'a'*40,'files':{n:hashlib.sha256(v).hexdigest() for n,v in files.items()}},sort_keys=True).encode()
    meta=dest.with_suffix('.json');meta.write_bytes(manifest);sig=dest.with_suffix('.sig')
    subprocess.run(['openssl','pkeyutl','-sign','-rawin','-inkey',str(key),'-in',str(meta),'-out',str(sig)],check=True,capture_output=True)
    with tarfile.open(dest,'w:gz') as archive:
        entries=[('manifest.json',manifest),('manifest.sig',sig.read_bytes() if sign else b'invalid'),*(('code/'+n,v) for n,v in files.items()),*(extra or [])]
        for name,value in entries:
            info=tarfile.TarInfo(name);info.size=len(value);info.mode=0o600;archive.addfile(info,io.BytesIO(value))
    return dest


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.base=Path(self.temp.name);self.root=self.base/'nas'
        self.key,self.token,self.csrf=seed(self.root,self.base)
        self.before=engine.inventory(self.root)
        self.key_before=(self.root/'state/console/keys/fixture.key').read_bytes()
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));self.port=sock.getsockname()[1]
        self.process=None;self.log=(self.base/'runtime.log').open('wb')
    def tearDown(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait()
        engine.terminate(self.root)
        self.log.close();self.temp.cleanup()
    def start(self):
        self.process=subprocess.Popen([sys.executable,str(engine.area(self.root)/'runtime.py'),str(self.root),str(self.port)],stdout=self.log,stderr=self.log)
        self.wait(lambda:self.get('/api/me')[0]==200)
    def wait(self,condition,timeout=20):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            try:
                if condition():return
            except (OSError,ValueError,http.client.HTTPException):pass
            time.sleep(.1)
        self.fail('Timed out; '+(self.base/'runtime.log').read_text()[-1600:])
    def get(self,path,token=True,method='GET',body=None,raw=None,csrf=True):
        connection=http.client.HTTPConnection('127.0.0.1',self.port,timeout=2)
        headers={'Cookie':'nas_session='+self.token} if token else {}
        if csrf:headers['X-CSRF-Token']=self.csrf
        if raw is not None:payload=raw;headers['Content-Type']='application/octet-stream'
        else:payload=json.dumps(body) if body is not None else None;headers['Content-Type']='application/json'
        connection.request(method,path,payload,headers);response=connection.getresponse();data=response.read();status=response.status;connection.close()
        return status,json.loads(data)
    def candidate(self,**kwargs):return package(self.root,self.key,self.base/'candidate.nacre-update',**kwargs)
    def unchanged(self):
        self.assertEqual((self.root/'data/fichiers/witness').read_bytes(),b'user data preserved')
        self.assertEqual((self.root/'state/console/keys/fixture.key').read_bytes(),self.key_before)
        with closing(sqlite3.connect(self.root/'state/console/console.db')) as db:self.assertEqual(db.execute("SELECT hash FROM users WHERE name='admin'").fetchone()[0],'unchanged-fixture')

    def test_signed_web_update_success_preserves_account_keys_data_and_session(self):
        self.start();candidate=self.candidate(changes={'console/new_feature.py':b'VALUE=42\n'})
        status,result=self.get('/api/updates/upload',method='POST',raw=candidate.read_bytes());self.assertEqual(status,200,result)
        self.assertEqual(result['phase'],'prepared');self.assertNotIn(self.token,json.dumps(result))
        status,result=self.get('/api/updates/apply',method='POST',body={'id':result['id'],'confirm':True});self.assertEqual(status,200,result)
        self.wait(lambda:engine.state(self.root)['phase']=='succeeded')
        self.assertEqual(self.get('/api/me')[1]['app_version'],'1.0.0-alpha.2');self.assertTrue((self.root/'console/new_feature.py').exists())
        self.unchanged();engine.installed(self.root)

    def test_old_copies_are_purged_around_a_real_update_and_an_admin_can_delete_one(self):
        area=engine.area(self.root);name=lambda index:f'{index:024x}'
        for index in range(1,5):
            folder=area/name(index)
            engine.write(folder/'manifest.json',json.dumps({'version':f'0.9.{index}'}).encode());engine.write(folder/'code/console/server.py',b'old candidate')
            engine.write(folder/'before/console/server.py',b'older code');engine.write(folder/'before.sqlite3',b'synthetic')
            engine.write(folder/'before.json',json.dumps({'version':f'0.9.{index-1}','files':{}}).encode())
            os.utime(folder/'before.json',(time.time()-5000+index*1000,)*2)
        folders=lambda:sorted(p.name for p in area.iterdir() if p.is_dir())
        # Démarrage : la règle automatique garde les trois copies les plus récentes.
        self.start();self.assertEqual(folders(),[name(2),name(3),name(4)])
        first=self.get('/api/updates/upload',method='POST',raw=self.candidate().read_bytes())[1]['id']
        status,result=self.get('/api/updates/upload',method='POST',raw=self.candidate(changes={'console/new_feature.py':b'VALUE=42\n'}).read_bytes());self.assertEqual(status,200,result)
        # Un paquet vérifié puis remplacé ne reste pas sur le disque.
        self.assertEqual(folders(),sorted([name(2),name(3),name(4),result['id']]));self.assertNotEqual(first,result['id'])
        current=result['id'];self.assertEqual(self.get('/api/updates/apply',method='POST',body={'id':current,'confirm':True})[0],200)
        self.wait(lambda:engine.state(self.root)['phase']=='succeeded');self.wait(lambda:self.get('/api/me')[0]==200 and not (area/name(2)).exists())
        self.assertEqual(folders(),sorted([name(3),name(4),current]))
        status,data=self.get('/api/updates');self.assertEqual(status,200,data)
        self.assertEqual([(i['id'],i['kind'],i['previous'],i['version'],i['current']) for i in data['copies']['items']],
                         [(current,'copy','1.0.0-alpha.1','1.0.0-alpha.2',True),(name(4),'copy','0.9.3','0.9.4',False),(name(3),'copy','0.9.2','0.9.3',False)])
        self.assertEqual((data['copies']['keep'],data['copies']['bytes']),(3,sum(i['bytes'] for i in data['copies']['items'])))
        delete=lambda body,**kwargs:self.get('/api/updates/copies/delete',method='POST',body=body,**kwargs)
        self.assertEqual(delete({'id':name(3),'confirm':True},csrf=False)[0],403)
        self.assertEqual(delete({'id':name(3)})[0],400)
        self.assertEqual((delete({'id':current,'confirm':True})[0],delete({'id':'../'+name(3),'confirm':True})[0],delete({'id':name(2),'confirm':True})[0]),(409,409,409))
        with closing(sqlite3.connect(self.root/'state/console/console.db')) as db:db.execute("UPDATE users SET role='viewer'");db.commit()
        self.assertEqual(delete({'id':name(3),'confirm':True})[0],403)
        with closing(sqlite3.connect(self.root/'state/console/console.db')) as db:db.execute("UPDATE users SET role='admin'");db.commit()
        self.assertEqual(folders(),sorted([name(3),name(4),current]))
        status,data=delete({'id':name(3),'confirm':True});self.assertEqual((status,[i['id'] for i in data['items']]),(200,[current,name(4)]))
        self.assertEqual(folders(),sorted([name(4),current]))
        with closing(sqlite3.connect(self.root/'state/console/console.db')) as db:
            trail=db.execute("SELECT username,action,detail FROM audit WHERE action LIKE '%opie%' ORDER BY rowid").fetchall()
        self.assertEqual(trail,[('console','Anciennes copies de mise à jour supprimées','Nacre 0.9.0, avant 0.9.1'),('console','Anciennes copies de mise à jour supprimées','Nacre 0.9.1, avant 0.9.2'),
                                ('admin','Copie de mise à jour supprimée','Nacre 0.9.2, avant 0.9.3')])
        self.assertEqual(self.get('/api/me')[1]['app_version'],'1.0.0-alpha.2');self.unchanged();engine.installed(self.root)

    def test_failed_start_restores_code_database_and_original_session(self):
        self.start();candidate=self.candidate(changes={'console/server.py':b"import sqlite3\nfrom pathlib import Path\np=Path(__file__).resolve().parents[1]/'state/console/console.db'\nwith sqlite3.connect(p) as db:db.execute(\"UPDATE users SET hash='candidate-damage'\")\nraise RuntimeError('synthetic startup failure')\n",'console/new_feature.py':b'NEW=True\n'})
        staged=engine.prepare(self.root,candidate);engine.request(self.root,staged['id'],'admin')
        self.wait(lambda:engine.state(self.root)['phase']=='rolled_back')
        self.wait(lambda:self.get('/api/me')[0]==200)
        self.assertEqual(engine.inventory(self.root),self.before);self.unchanged()
        self.assertFalse((self.root/'console/new_feature.py').exists())
        self.assertEqual(self.get('/api/me')[1]['app_version'],'1.0.0-alpha.1')

    def test_restart_recovers_interrupted_copy_before_any_console_start(self):
        staged=engine.prepare(self.root,self.candidate(changes={'console/new_feature.py':b'NEW=True\n'}))
        engine.request(self.root,staged['id'],'admin')
        with engine.exclusive(self.root):
            engine.set_state(self.root,'backing_up');engine.backup(self.root)
            engine.write(self.root/'console/server.py',b'broken partial deployment')
            engine.write(self.root/'console/new_feature.py',b'partial')
        self.start()
        self.assertEqual(engine.state(self.root)['phase'],'rolled_back');self.assertEqual(engine.inventory(self.root),self.before);self.unchanged()

    def test_killed_supervisor_during_verification_recovers_on_restart(self):
        self.start();staged=engine.prepare(self.root,self.candidate(changes={'console/server.py':b'import time\ntime.sleep(120)\n'}));engine.request(self.root,staged['id'],'admin')
        self.wait(lambda:engine.state(self.root)['phase']=='verifying')
        self.process.kill();self.process.wait();self.process=None
        self.start();self.assertEqual(engine.state(self.root)['phase'],'rolled_back');self.assertEqual(engine.inventory(self.root),self.before);self.unchanged()

    def test_signature_path_duplicate_and_critical_changes_are_rejected(self):
        for options in ({'sign':False},{'extra':[('../outside',b'bad')]},{'extra':[('manifest.json',b'{}')]},{'changes':{'state/smb_password':b'bad'}},{'changes':{'console/schema.py':b'VERSION=3\n'}}):
            with self.subTest(options=options),self.assertRaises(engine.UpdateError):engine.prepare(self.root,self.candidate(**options))
            self.assertEqual(engine.inventory(self.root),self.before)
        self.assertFalse((self.base/'outside').exists())

    def test_revalidation_rejects_changed_local_code_and_changed_prepared_bytes(self):
        staged=engine.prepare(self.root,self.candidate())
        engine.write(self.root/'console/release.py',b'LOCAL=True\n')
        with self.assertRaises(engine.UpdateError):engine.request(self.root,staged['id'],'admin')
        self.assertEqual(engine.state(self.root)['phase'],'prepared')
        engine.write(self.root/'console/release.py',(SOURCE/'console/release.py').read_bytes())
        self.start();engine.write(engine.area(self.root)/staged['id']/'code/console/server.py',b'changed')
        engine.request(self.root,staged['id'],'admin');self.wait(lambda:engine.state(self.root)['phase']=='rolled_back')
        self.wait(lambda:self.get('/api/me')[0]==200);self.assertEqual(engine.inventory(self.root),self.before)

    def test_active_jobs_confirmation_and_expired_preparation_are_refused(self):
        staged=engine.prepare(self.root,self.candidate())
        with closing(sqlite3.connect(self.root/'state/console/console.db')) as db:
            db.execute("INSERT INTO jobs(id,status) VALUES('fixture','running')");db.commit()
        with self.assertRaises(engine.UpdateError):engine.request(self.root,staged['id'],'admin')
        with closing(sqlite3.connect(self.root/'state/console/console.db')) as db:db.execute('DELETE FROM jobs');db.commit()
        engine.set_state(self.root,'prepared',prepared_at=0)
        with self.assertRaises(engine.UpdateError):engine.request(self.root,staged['id'],'admin')
        self.assertEqual(engine.inventory(self.root),self.before)

    def test_http_auth_csrf_viewer_and_maintenance_gates(self):
        self.start()
        self.assertEqual(self.get('/api/updates',token=False)[0],401)
        self.assertEqual(self.get('/api/update-health')[0],403)
        self.assertEqual(self.get('/api/updates/apply',method='POST',body={},csrf=False)[0],403)
        self.assertEqual(self.get('/api/updates/apply',method='POST',body={})[0],400)
        with closing(sqlite3.connect(self.root/'state/console/console.db')) as db:
            db.execute("UPDATE users SET role='viewer'");db.commit()
        self.assertEqual(self.get('/api/updates')[0],403)
        self.assertEqual(self.get('/api/updates/upload',method='POST',raw=b'bad')[0],403)
        with closing(sqlite3.connect(self.root/'state/console/console.db')) as db:db.execute("UPDATE users SET role='admin'");db.commit()
        engine.set_state(self.root,'verifying')
        self.assertEqual(self.get('/api/control-panel')[0],503)
        self.assertEqual(self.get('/api/logout',method='POST',body={})[0],503)
        self.assertEqual(self.get('/api/updates')[0],200)
        engine.set_state(self.root,'idle')

    def test_malformed_upload_and_unsigned_payload_are_refused_without_change(self):
        self.start()
        for payload in (b'not a gzip archive',self.candidate(sign=False).read_bytes()):
            status,result=self.get('/api/updates/upload',method='POST',raw=payload)
            self.assertIn(status,(400,409),result)
            self.assertEqual(engine.state(self.root)['phase'],'idle')
            self.assertEqual(engine.inventory(self.root),self.before)
        self.unchanged()

    def test_insufficient_backup_space_never_replaces_code(self):
        staged=engine.prepare(self.root,self.candidate());engine.request(self.root,staged['id'],'admin')
        engine.set_state(self.root,'backing_up')
        with patch.object(engine.shutil,'disk_usage',return_value=SimpleNamespace(free=0)),self.assertRaises(engine.UpdateError):engine.backup(self.root)
        self.assertEqual(engine.inventory(self.root),self.before)
        self.start();self.assertEqual(engine.state(self.root)['phase'],'failed');self.unchanged()

    def test_decompression_budget_counts_padding_before_tar_parsing(self):
        candidate=self.base/'padding.nacre-update'
        with gzip.open(candidate,'wb') as stream:stream.write(b'\0'*4096)
        with patch.object(engine,'MAX_EXPANDED',1024),self.assertRaisesRegex(engine.UpdateError,'hors limites'):
            engine.prepare(self.root,candidate)
        self.assertEqual(engine.inventory(self.root),self.before)

    def test_launch_ignores_stale_bytecode_with_equal_size_and_timestamp(self):
        module=self.root/'console/cached_fixture.py'
        module.write_text("VALUE='old'\n");before=module.stat()
        py_compile.compile(str(module),doraise=True)
        module.write_text("VALUE='new'\n");os.utime(module,ns=(before.st_atime_ns,before.st_mtime_ns))
        server=self.root/'console/server.py'
        server.write_text("from cached_fixture import VALUE\nassert VALUE=='new', 'stale cached code'\n"+server.read_text())
        self.start()
        self.assertEqual(self.get('/api/me')[0],200)
        self.assertEqual(engine.state(self.root)['phase'],'idle')
