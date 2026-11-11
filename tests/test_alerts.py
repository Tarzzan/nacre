"""Incidents et collecte simulée, aucune caméra ni service réel."""
import json
import time
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import test_console
server=test_console.server
import alerts


class AlertTests(unittest.TestCase):
    request=test_console.ConsoleSecurityTests.request

    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.previous=server.ROOT,server.STATE,server.DB
        server.ROOT=Path(self.temp.name);server.STATE=server.ROOT/'state/console';server.DB=server.STATE/'console.db'
        server.initialize();self.token,self.csrf=server.make_session('admin')
        self.http=server.Server(('127.0.0.1',0),server.Handler)
        threading.Thread(target=self.http.serve_forever,daemon=True).start()
        self.item=alerts.condition('camera:atelier','Caméra atelier : flux absent','Vérifier la connexion.','camera')

    def tearDown(self):
        self.http.shutdown();self.http.server_close();server.ROOT,server.STATE,server.DB=self.previous;self.temp.cleanup()

    def sample(self,items=(),scope='cameras',now=100):
        scopes={key:[] for key in alerts.SCOPES};scopes[scope]=list(items) if items is not None else None
        alerts.record(server,scopes,now=now)

    def open(self,scope='cameras',item=None):
        self.sample([item or self.item],scope,100);self.sample([item or self.item],scope,130)
        return next(iter(alerts.read(server)['active'].values()))

    def job(self,identifier,status,repo='repo-a',plan='',ts=100):
        with server.database() as db:
            db.execute('INSERT INTO jobs(id,kind,status,result,ts,options) VALUES(?,?,?,?,?,?)',(identifier,'snapshot',status,json.dumps({'error':'private-secret-error'}),ts,json.dumps({'repo':repo,'plan':plan,'password':'private-secret-password'})))

    def collect(self,services='',config=None,stats=None):
        with patch.object(server,'compose',return_value=services),patch('cameras.config',return_value=config or {'cameras':{}}),patch.object(server,'video_json',return_value={'service':{'last_updated':time.time()},**(stats or {'cameras':{}})}),patch('alerts.shutil.disk_usage',return_value=SimpleNamespace(total=100,used=10)):
            return alerts.collect(server)

    def test_debounce_deduplication_and_normal_recovery(self):
        self.sample([self.item],now=100);self.assertFalse(alerts.read(server)['active'])
        self.sample([],now=120);self.sample([self.item],now=130);self.assertFalse(alerts.read(server)['active'])
        self.sample([self.item],now=160);incident=next(iter(alerts.read(server)['active'].values()))
        self.sample([self.item],now=190);self.assertEqual(len(alerts.read(server)['active']),1)
        self.sample([],now=200);self.assertTrue(alerts.read(server)['active'])
        self.sample([],now=230);state=alerts.read(server);self.assertFalse(state['active'])
        self.assertEqual(state['history'][0]['id'],incident['id']);self.assertEqual(state['history'][0]['resolved'],230)

    def test_acknowledgement_persists_and_recurrence_needs_new_attention(self):
        incident=self.open();alerts.acknowledge(server,{'id':incident['id'],'version':incident['version']},'admin')
        server.initialize();self.assertEqual(alerts.listing(server)['attention'],0)
        self.assertEqual(len(alerts.listing(server)['active']),1)
        self.sample([],now=160);self.sample([],now=190)
        self.sample([self.item],now=220);self.sample([self.item],now=250)
        reopened=alerts.listing(server);self.assertEqual(reopened['attention'],1)
        self.assertNotEqual(reopened['active'][0]['id'],incident['id'])
        self.assertEqual(reopened['history'][0]['ackby'],'admin')

    def test_unknown_and_stale_samples_never_resolve_or_accumulate_pending(self):
        incident=self.open();self.sample([],now=160);self.sample(None,now=190)
        self.assertIn('cameras',alerts.listing(server)['unavailable'])
        self.sample([],now=220);self.assertTrue(alerts.read(server)['active'])
        self.sample([],now=400);self.assertTrue(alerts.read(server)['active'])
        self.sample([],now=430);self.assertFalse(alerts.read(server)['active'])
        with patch('alerts.time.time',return_value=600):self.assertTrue(alerts.listing(server)['stale'])

    def test_authorization_csrf_and_no_probe_on_get(self):
        incident=self.open()
        self.assertEqual(self.request('GET','/api/alerts')[0],401)
        with server.database() as db:db.execute("INSERT INTO users(name,salt,hash,role) VALUES('reader','00','unused','viewer')")
        token,csrf=server.make_session('reader')
        self.assertEqual(self.request('GET','/api/alerts',token=token)[0],403)
        self.assertEqual(self.request('POST','/api/alerts/acknowledge',{'id':incident['id'],'version':incident['version']},token,csrf)[0],403)
        self.assertEqual(self.request('POST','/api/alerts/acknowledge',{'id':incident['id'],'version':incident['version']},self.token)[0],403)
        with patch.object(server,'compose',side_effect=AssertionError('No probe')):
            self.assertEqual(self.request('GET','/api/alerts',token=self.token)[0],200)
        self.assertEqual(self.request('POST','/api/alerts/acknowledge',{'id':incident['id'],'version':incident['version']},self.token,self.csrf)[0],200)
        self.assertEqual(self.request('POST','/api/alerts/acknowledge',{'id':'missing'},self.token,self.csrf)[0],409)

    def test_initial_missing_services_are_not_incidents_but_known_services_are(self):
        with patch.object(server,'compose',side_effect=server.Problem('private-daemon-error')):
            scopes,seen=alerts.collect(server)
        self.assertFalse(scopes['docker']);self.assertEqual(scopes['services'],[])
        services='{"Service":"video","State":"running","Health":"healthy"}'
        scopes,seen=self.collect(services);alerts.record(server,scopes,seen,100)
        scopes,seen=self.collect();self.assertEqual(scopes['services'][0]['key'],'service:video')
        with patch.object(server,'compose',side_effect=server.Problem('private-daemon-error')):scopes,seen=alerts.collect(server)
        self.assertIsNone(scopes['services']);self.assertEqual(scopes['docker'][0]['key'],'monitor:docker')
        self.assertNotIn('private-daemon-error',json.dumps(scopes))

    def test_enabled_cameras_only_and_unknown_stats_preserve_state(self):
        services='{"Service":"video","State":"running","Health":"healthy"}'
        config={'cameras':{'atelier':{'enabled':True},'pause':{'enabled':False},'entree':{'enabled':True}}}
        scopes,_=self.collect(services,config,{'cameras':{'atelier':{'camera_fps':0},'entree':{'camera_fps':5}}})
        self.assertEqual([c['key'] for c in scopes['cameras']],['camera:atelier'])
        with patch.object(server,'compose',return_value=services),patch('cameras.config',return_value=config),patch.object(server,'video_json',side_effect=server.Problem('private-url')):
            scopes,_=alerts.collect(server)
        self.assertIsNone(scopes['cameras']);self.assertNotIn('private-url',json.dumps(scopes))

    def test_stale_positive_stats_do_not_resolve_camera_incident(self):
        services='{"Service":"video","State":"running","Health":"healthy"}'
        config={'cameras':{'atelier':{'enabled':True}}}
        incident=self.open('cameras',alerts.condition('camera:atelier','Flux absent','Vérifier.','camera'))
        scopes,seen=self.collect(services,config,{'service':{'last_updated':time.time()-3600},'cameras':{'atelier':{'camera_fps':5}}})
        self.assertIsNone(scopes['cameras']);self.assertEqual(scopes['video_api'][0]['key'],'monitor:camera')
        alerts.record(server,scopes,seen,160);alerts.record(server,scopes,seen,190)
        active=alerts.listing(server)['active']
        self.assertTrue(any(a['id']==incident['id'] for a in active))
        self.assertEqual(len(active),2)

    def test_deployment_suspends_service_and_camera_checks(self):
        with server.database() as db:db.execute("INSERT INTO jobs(id,kind,status,result,ts) VALUES('deploy','component_install','running','{}',1)")
        with patch.object(server,'compose',side_effect=AssertionError('probe during deployment')):scopes,_=alerts.collect(server)
        self.assertIsNone(scopes['services']);self.assertIsNone(scopes['cameras'])
        self.assertIsNone(scopes['docker']);self.assertIsNone(scopes['video_api'])
        incident=self.open('docker',alerts.condition('monitor:docker','Contrôle indisponible','Vérifier.','services'))
        alerts.record(server,scopes,now=160);alerts.record(server,scopes,now=190)
        self.assertEqual(alerts.listing(server)['active'][0]['id'],incident['id'])

    def test_failed_and_partial_backups_group_by_plan_and_success_resolves(self):
        self.job('one','failed',plan='plan-a');self.job('two','partial',plan='plan-b',ts=101)
        scopes,seen=self.collect();alerts.record(server,scopes,seen,100)
        self.assertEqual(len(alerts.listing(server)['active']),2)
        data=json.dumps(alerts.listing(server));self.assertNotIn('private-secret',data);self.assertNotIn('repo-a',data)
        self.job('three','done',plan='plan-a',ts=102)
        scopes,seen=self.collect();alerts.record(server,scopes,seen,130)
        self.assertEqual(len(alerts.listing(server)['active']),1);self.assertEqual(len(alerts.listing(server)['history']),1)

    def test_new_backup_failure_and_escalation_revoke_ack_but_downgrade_does_not(self):
        item=alerts.condition('storage:application','Espace','Consultez Stockage.','storage')
        incident=self.open('storage',item);alerts.acknowledge(server,{'id':incident['id'],'version':incident['version']},'admin')
        self.sample([{**item,'severity':'critical'}],'storage',160);self.assertEqual(alerts.listing(server)['attention'],1)
        with self.assertRaises(server.Problem):alerts.acknowledge(server,{'id':incident['id'],'version':incident['version']},'admin')
        incident=next(iter(alerts.read(server)['active'].values()))
        alerts.acknowledge(server,{'id':incident['id'],'version':incident['version']},'admin')
        self.sample([item],'storage',190);self.assertEqual(alerts.listing(server)['attention'],0)
        self.job('one','failed');scopes,seen=self.collect();alerts.record(server,scopes,seen,220)
        incident=next(i for i in alerts.listing(server)['active'] if i['scope']=='backups');alerts.acknowledge(server,{'id':incident['id'],'version':incident['version']},'admin')
        self.job('two','failed',ts=200);scopes,seen=self.collect();alerts.record(server,scopes,seen,250)
        self.assertIsNone(next(i for i in alerts.listing(server)['active'] if i['scope']=='backups')['acknowledged'])

    def test_disk_thresholds_and_bounded_resolved_history(self):
        for used,expected in ((89,None),(90,'warning'),(97,'critical')):
            with patch('alerts.shutil.disk_usage',return_value=SimpleNamespace(total=100,used=used)),patch.object(server,'compose',return_value=''):
                scopes,_=alerts.collect(server)
            self.assertEqual(scopes['storage'][0]['severity'] if scopes['storage'] else None,expected)
        item=alerts.condition('backup:one','Sauvegarde','Vérifier.','backups')
        for index in range(105):
            self.sample([item],'backups',100+index*2);self.sample([],'backups',101+index*2)
        self.assertEqual(len(alerts.listing(server)['history']),100)
