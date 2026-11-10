"""Configurations et tâches sur répertoires temporaires, Docker simulé."""
import copy
import json
import secrets
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import test_console
server=test_console.server
import cameras
import deployment
from protection import Protection
from lab import initial_config


class ComponentsCameraTests(unittest.TestCase):
    request=test_console.ConsoleSecurityTests.request

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.previous=server.ROOT,server.STATE,server.DB
        server.ROOT=Path(self.temp.name);server.STATE=server.ROOT/'state/console';server.DB=server.STATE/'console.db'
        server.initialize()
        self.config=server.ROOT/'state/frigate/config.yml'
        self.config.parent.mkdir(parents=True)
        server.private_write(self.config,json.dumps(initial_config()))
        self.token,self.csrf=server.make_session('admin')
        self.http=server.Server(('127.0.0.1',0),server.Handler)
        threading.Thread(target=self.http.serve_forever,daemon=True).start()
        self.body={'id':'atelier','name':'Atelier','host':'192.168.50.10','profile':'tapo',
                   'username':'fixture','password':secrets.token_urlsafe(24),'onvif':True,'confirm':True}
        self.spawn=patch.object(Protection,'spawn');self.spawn.start()

    def tearDown(self):
        self.spawn.stop();self.http.shutdown();self.http.server_close()
        server.ROOT,server.STATE,server.DB=self.previous;self.temp.cleanup()

    def post(self,path,body):return self.request('POST',path,body,self.token,self.csrf)
    def row(self,identifier):
        with server.database() as db:return dict(db.execute('SELECT * FROM jobs WHERE id=?',(identifier,)).fetchone())
    def add(self,body=None):
        code,raw=self.post('/api/cameras/add',body or self.body)
        self.assertEqual(code,200,raw);return json.loads(raw)['job']

    def test_authorization_csrf_and_closed_component_catalog(self):
        self.assertEqual(self.request('GET','/api/components')[0],401)
        self.assertEqual(self.request('POST','/api/cameras/add',self.body,self.token)[0],403)
        with server.database() as db:db.execute("INSERT INTO users(name,salt,hash,role) VALUES('reader','00','unused','viewer')")
        token,csrf=server.make_session('reader')
        for route,body in [('/api/components/install',{'component':'restic','confirm':True}),('/api/cameras/add',self.body)]:
            self.assertEqual(self.request('POST',route,body,token,csrf)[0],403)
        for body in ({'component':'docker','confirm':True},{'component':'restic'},{'component':'restic;id','confirm':True}):
            self.assertEqual(self.post('/api/components/install',body)[0],400)
        self.assertEqual(self.post('/api/components/install',{'component':'restic','confirm':True})[0],200)
        self.assertEqual(self.post('/api/components/install',{'component':'video','confirm':True})[0],409)
        self.assertEqual(self.post('/api/service',{'name':'video','action':'stop'})[0],409)

    def test_camera_validation_rejects_unsafe_targets_and_duplicate_streams(self):
        for change in ({'id':'../evil'},{'id':'UPPER'},{'host':'127.0.0.1'},{'host':'8.8.8.8'},{'host':'169.254.169.254'},
                       {'host':'camera.local'},{'port':True},{'profile':'shell'},{'password':''},{'confirm':False},
                       {'profile':'rtsp','path':'file:///etc/passwd'},{'profile':'rtsp','path':'/stream#exec=bad'}):
            self.assertEqual(self.post('/api/cameras/add',{**self.body,**change})[0],400,change)
        config=initial_config();config['go2rtc']={'streams':{'atelier_sub':['existing']}}
        server.private_write(self.config,json.dumps(config))
        self.assertEqual(self.post('/api/cameras/add',self.body)[0],409)
        self.assertEqual(list((server.STATE/'camera-pending').glob('*.json')),[])

    def test_secrets_are_private_not_in_jobs_audit_or_listing(self):
        job=self.add();row=self.row(job)
        private=server.STATE/'camera-pending'/(json.loads(row['options'])['candidate']+'.json')
        self.assertEqual(private.stat().st_mode&0o777,0o600)
        self.assertIn(self.body['password'],private.read_text())
        for route in ('/api/jobs','/api/events','/api/cameras'):
            code,raw=self.request('GET',route,token=self.token);self.assertEqual(code,200)
            self.assertNotIn(self.body['password'],raw.decode())
            self.assertNotIn('rtsp://',raw.decode())

    def test_runtime_validation_failure_preserves_config_and_erases_pending_secret(self):
        original=self.config.read_bytes();job=self.add()
        with patch.object(server,'compose',side_effect=server.Problem('secret runtime details')):
            server.protection().run_job(job)
        row=self.row(job);self.assertEqual(row['status'],'failed')
        self.assertNotIn('secret runtime details',row['result'])
        self.assertEqual(self.config.read_bytes(),original)
        self.assertEqual(list((server.STATE/'camera-pending').glob('*.json')),[])

    def test_add_preserves_existing_camera_and_routes_selected_camera(self):
        old=initial_config();old['cameras']['tapo']={'enabled':True,'custom':'preserved'}
        old['go2rtc']={'streams':{'tapo':['private-old-stream']}}
        server.private_write(self.config,json.dumps(old));job=self.add()
        stats={'cameras':{'atelier':{'camera_fps':5},'tapo':{'camera_fps':0}}}
        with patch.object(server,'compose') as compose,patch.object(server,'video_json',return_value=stats):
            server.protection().run_job(job)
        self.assertEqual(self.row(job)['status'],'done')
        saved=json.loads(self.config.read_text());self.assertEqual(saved['cameras']['tapo'],old['cameras']['tapo'])
        self.assertEqual(saved['go2rtc']['streams']['tapo'],['private-old-stream'])
        self.assertFalse(saved['cameras']['atelier']['onvif']['autotracking']['enabled'])
        self.assertEqual((server.STATE/('camera-before-'+job+'.yml')).stat().st_mode&0o777,0o600)
        with patch.object(server,'video_json',return_value={'features':['pt']}) as video:
            code,_=self.request('GET','/api/camera/info?camera=atelier',token=self.token)
            self.assertEqual(code,200);video.assert_called_once_with('/api/atelier/ptz/info')
        with patch.object(server,'ptz_move') as ptz:
            self.assertEqual(self.post('/api/camera/ptz',{'camera':'atelier','action':'left'})[0],200)
            ptz.assert_called_once_with('left',None,'atelier')
        self.assertEqual(self.request('GET','/api/camera/info?camera=missing',token=self.token)[0],404)
        with patch.object(server,'video_json',return_value=stats):
            code,raw=self.request('GET','/api/cameras',token=self.token)
        self.assertEqual(code,200);self.assertEqual(len(json.loads(raw)),2)
        self.assertNotIn(self.body['password'],raw.decode());self.assertNotIn('rtsp://',raw.decode())

    def test_restart_failure_reports_saved_configuration_and_keeps_private_backup(self):
        job=self.add()
        def compose(*args,**kwargs):
            if args[0]=='restart':raise server.Problem('secret error')
        with patch.object(server,'compose',side_effect=compose):server.protection().run_job(job)
        self.assertEqual(self.row(job)['status'],'failed')
        self.assertIn('Configuration enregistrée',json.loads(self.row(job)['result'])['error'])
        self.assertIn('atelier',json.loads(self.config.read_text())['cameras'])
        self.assertTrue((server.STATE/('camera-before-'+job+'.yml')).exists())

    def test_external_config_edit_during_validation_is_not_overwritten(self):
        job=self.add()
        def compose(*args,**kwargs):server.private_write(self.config,json.dumps({'cameras':{},'external':True}))
        with patch.object(server,'compose',side_effect=compose):server.protection().run_job(job)
        self.assertEqual(self.row(job)['status'],'failed');self.assertTrue(json.loads(self.config.read_text())['external'])

    def test_restic_install_uses_fixed_installer_without_backup_creation(self):
        code,raw=self.post('/api/components/install',{'component':'restic','confirm':True});job=json.loads(raw)['job']
        with patch('install_restic.install') as install:server.protection().run_job(job)
        install.assert_called_once_with(server.ROOT);self.assertEqual(self.row(job)['status'],'done')
        with server.database() as db:self.assertEqual(db.execute('SELECT count(*) FROM plans').fetchone()[0],0)

    def test_video_install_checks_health_and_docker_absence_is_actionable(self):
        _,raw=self.post('/api/components/install',{'component':'video','confirm':True});job=json.loads(raw)['job']
        with patch('onboarding.probe',return_value=False),patch.object(server,'compose') as compose:server.protection().run_job(job)
        compose.assert_not_called();self.assertEqual(self.row(job)['status'],'failed')
        _,raw=self.post('/api/components/install',{'component':'video','confirm':True});job=json.loads(raw)['job']
        with patch('onboarding.probe',return_value=True),patch.object(server,'compose',return_value='{"State":"running","Health":"healthy"}') as compose:
            server.protection().run_job(job)
        self.assertEqual(self.row(job)['status'],'done')
        self.assertEqual(compose.call_args_list[0].args,('pull','video'))
        self.assertEqual(compose.call_args_list[1].args,('up','-d','--no-deps','--no-build','video'))

    def test_interrupted_camera_task_is_not_replayed_and_pending_secret_removed(self):
        job=self.add()
        with server.database() as db:db.execute('UPDATE jobs SET pid=-1,ts=0 WHERE id=?',(job,))
        server.protection().recover()
        self.assertEqual(self.row(job)['status'],'failed')
        self.assertEqual(list((server.STATE/'camera-pending').glob('*.json')),[])
        self.assertEqual(json.loads(self.config.read_text()),initial_config())

    def test_rtsp_credentials_encoded_and_optional_secondary_stream(self):
        key,camera,streams=cameras.build(server,{**self.body,'password':'private@:/%value','profile':'rtsp','path':'/main','subpath':''})
        self.assertIn('private%40%3A%2F%25value',streams[key][0])
        self.assertEqual(len(streams),1);self.assertEqual(camera['ffmpeg']['inputs'][0]['roles'],['record','detect'])

    def test_connection_edit_preserves_recording_settings_and_other_camera(self):
        key,camera,streams=cameras.build(server,self.body)
        camera['record']['continuous']['days']=7;camera['enabled']=False
        value=initial_config();value['cameras']={key:camera,'other':{'enabled':True}}
        value['go2rtc']={'streams':streams};server.private_write(self.config,json.dumps(value))
        job=self.add({**self.body,'replace':True,'host':'192.168.50.20','profile':'rtsp','path':'/main','subpath':''})
        with patch.object(server,'compose'),patch.object(server,'video_json',return_value={'cameras':{'atelier':{'camera_fps':0}}}):
            server.protection().run_job(job)
        updated=json.loads(self.config.read_text())
        self.assertEqual(updated['cameras']['atelier']['record']['continuous']['days'],7)
        self.assertFalse(updated['cameras']['atelier']['enabled'])
        self.assertEqual(updated['cameras']['other'],value['cameras']['other'])
        self.assertIn('192.168.50.20',updated['go2rtc']['streams']['atelier'][0])
        self.assertNotIn('atelier_sub',updated['go2rtc']['streams'])
        self.assertFalse(json.loads(self.row(job)['result'])['online'])

    def test_samba_recovery_image_is_preserved_and_unhealthy_video_not_success(self):
        _,raw=self.post('/api/components/install',{'component':'fichiers','confirm':True});job=json.loads(raw)['job']
        (server.ROOT/'state/samba/recovery.compose.json').write_text('{}')
        manager=MagicMock()
        with patch('onboarding.probe',return_value=True),patch.object(server,'shares',return_value=manager),patch.object(server,'compose',return_value='{"State":"running"}') as compose:
            server.protection().run_job(job)
        self.assertEqual(self.row(job)['status'],'done')
        self.assertNotIn('build',[call.args[0] for call in compose.call_args_list])
        manager.prepare_start.assert_called_once();manager.apply.assert_called_once()
        _,raw=self.post('/api/components/install',{'component':'video','confirm':True});job=json.loads(raw)['job']
        with patch('onboarding.probe',return_value=True),patch('deployment.time.sleep'),patch.object(server,'compose',return_value='{"State":"running","Health":"unhealthy"}'):
            server.protection().run_job(job)
        self.assertEqual(self.row(job)['status'],'failed')
