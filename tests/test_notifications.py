"""Récepteur HTTP loopback jetable ; aucun service tiers ni NAS réel."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import ssl
import subprocess
import threading
import unittest
from unittest.mock import patch
import test_console
server=test_console.server
import alerts
import notifications as n

class Receiver(BaseHTTPRequestHandler):
    def do_POST(self):
        self.server.received.append((self.path,dict(self.headers),self.rfile.read(int(self.headers['Content-Length']))))
        code=self.server.responses.pop(0) if self.server.responses else 200
        self.send_response(code)
        if code==302:self.send_header('Location','http://127.0.0.1:'+str(self.server.server_port)+'/redirected')
        self.end_headers();self.wfile.write(b'private-response')
    def log_message(self,*args):pass

class NotificationTests(unittest.TestCase):
    request=test_console.ConsoleSecurityTests.request
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.previous=server.ROOT,server.STATE,server.DB
        server.ROOT=Path(self.temp.name);server.STATE=server.ROOT/'state/console';server.DB=server.STATE/'console.db'
        server.initialize();self.token,self.csrf=server.make_session('admin')
        self.http=server.Server(('127.0.0.1',0),server.Handler);self.sink=ThreadingHTTPServer(('127.0.0.1',0),Receiver)
        self.sink.received=[];self.sink.responses=[]
        for http in (self.http,self.sink):threading.Thread(target=http.serve_forever,daemon=True).start()
        self.url='http://127.0.0.1:'+str(self.sink.server_port)+'/private-hook?key=fixture-private'
        self.item=alerts.condition('camera:atelier','Caméra atelier : flux absent','Vérifier la connexion.','camera')
    def tearDown(self):
        for http in (self.http,self.sink):http.shutdown();http.server_close()
        server.ROOT,server.STATE,server.DB=self.previous;self.temp.cleanup()
    def configure(self,**values):
        body={'version':n.status(server)['config']['version'],'enabled':True,'kind':'webhook','url':self.url,'token':'fixture-token','minimum':'warning','recovery':True}
        body.update(values);n.configure(server,body,'admin');return n.status(server)['config']['version']
    def sample(self,items=(),now=100):
        scopes={key:[] for key in alerts.SCOPES};scopes['cameras']=list(items) if items is not None else None
        alerts.record(server,scopes,now=now)
    def open(self):self.sample([self.item]);self.sample([self.item],130)
    def state(self):
        with server.database() as db:return n.read(db)

    def test_default_disabled_and_no_replay_after_activation(self):
        self.open();self.assertFalse(n.status(server)['deliveries']);self.configure()
        self.sample([self.item],160);self.sample([],190);self.sample([],220)
        self.assertFalse(n.status(server)['deliveries']);self.assertFalse(n.dispatch(server,230));self.assertFalse(self.sink.received)

    def test_events_dedup_ack_unknown_and_atomic_commit(self):
        self.configure();self.sample([self.item])
        with patch('alerts.enqueue',side_effect=RuntimeError('fixture failure')):
            with self.assertRaises(RuntimeError):self.sample([self.item],130)
        self.assertFalse(alerts.listing(server)['active']);self.assertFalse(self.state()['items'])
        self.sample([self.item],130);self.sample([self.item],160);self.sample(None,190)
        incident=alerts.listing(server)['active'][0];alerts.acknowledge(server,{'id':incident['id'],'version':1},'admin')
        self.assertEqual(len(self.state()['items']),1)
        self.sample([{**self.item,'severity':'critical'}],220);self.sample([],250);self.sample([],280)
        self.assertEqual([i['event'] for i in self.state()['items']],['opened','updated','resolved'])

    def test_critical_filter_recovery_after_downgrade_and_exclusion(self):
        self.configure(minimum='critical');self.open();self.assertFalse(self.state()['items'])
        self.sample([{**self.item,'severity':'critical'}],160);self.sample([self.item],190);self.sample([],220);self.sample([],250)
        self.assertEqual([i['event'] for i in self.state()['items']],['updated','resolved'])
        self.configure(recovery=False);self.open();self.sample([],160);self.sample([],190)
        self.assertEqual(self.state()['items'][-1]['event'],'opened')

    def test_webhook_real_http_payload_redaction_success(self):
        self.configure();self.open();self.assertTrue(n.dispatch(server,130));self.assertFalse(n.dispatch(server,131))
        path,headers,data=self.sink.received[0];payload=json.loads(data)
        self.assertEqual(path,'/private-hook?key=fixture-private');self.assertEqual(headers['Authorization'],'Bearer fixture-token')
        self.assertEqual(payload['schema'],'nacre.alert.v1');self.assertEqual(payload['event'],'opened')
        self.assertEqual(headers['X-Nacre-Event-Id'],payload['id']);self.assertNotIn('ackby',payload);self.assertNotIn('url',payload)
        public=json.dumps(n.status(server))
        with server.database() as db:log=json.dumps([tuple(row) for row in db.execute('SELECT * FROM audit')])
        for secret in ('fixture-token','private-hook','private-response','fixture-private'):
            self.assertNotIn(secret,public);self.assertNotIn(secret,log)
        self.assertEqual(n.status(server)['deliveries'][0]['status'],'sent')

    def test_ntfy_real_http_and_test_while_disabled_rate_limit(self):
        revision=self.configure(kind='ntfy',enabled=False);n.test(server,{'version':revision},'admin');n.dispatch(server)
        _,headers,data=self.sink.received[0]
        self.assertEqual(headers['Content-Type'],'text/plain; charset=utf-8');self.assertEqual(headers['Title'],'Nacre')
        self.assertEqual(headers['Priority'],'3');self.assertIn('message de test',data.decode('utf8'))
        with self.assertRaises(server.Problem) as error:n.test(server,{'version':revision},'admin')
        self.assertEqual(error.exception.status,429)

    def test_transient_failure_persists_identity_and_fifo(self):
        self.configure();self.open();self.sample([],160);self.sample([],190);self.sink.responses=[503,200,200]
        n.dispatch(server,200);self.assertEqual(self.state()['items'][0]['next'],230)
        server.initialize();self.assertFalse(n.dispatch(server,229));self.assertEqual(len(self.sink.received),1)
        n.dispatch(server,230);n.dispatch(server,231)
        values=[json.loads(data) for _,_,data in self.sink.received]
        self.assertEqual([v['event'] for v in values],['opened','opened','resolved']);self.assertEqual(values[0]['id'],values[1]['id'])
        self.assertTrue(all(i['status']=='sent' for i in self.state()['items']))

    def test_permanent_failure_manual_retry_and_stale_version(self):
        revision=self.configure();self.open();self.sink.responses=[401,200];n.dispatch(server,130)
        item=self.state()['items'][0];self.assertEqual(item['status'],'failed')
        with self.assertRaises(server.Problem):n.retry(server,{'version':revision-1,'id':item['id']},'admin')
        n.retry(server,{'version':revision,'id':item['id']},'admin');n.dispatch(server)
        self.assertEqual(self.state()['items'][0]['status'],'sent')

    def test_exhaustion_and_network_error_redaction(self):
        self.configure();self.open()
        with patch.object(n,'deliver',return_value=(False,True,'Connexion impossible.')):
            for now in (130,160,280,880,2680):self.assertTrue(n.dispatch(server,now))
        item=self.state()['items'][0];self.assertEqual(item['attempts'],5);self.assertEqual(item['status'],'failed')
        with patch.object(n,'build_opener',side_effect=RuntimeError('private-url-and-token')):ok,transient,message=n.deliver(self.state()['config'],item)
        self.assertFalse(ok);self.assertTrue(transient);self.assertNotIn('private-url',message)

    def test_parallel_dispatch_and_reclaimed_lease(self):
        self.configure();self.open();entered=threading.Event();release=threading.Event()
        def blocked(config,item):entered.set();release.wait(3);return True,False,'Accepté.'
        with patch.object(n,'deliver',side_effect=blocked):
            thread=threading.Thread(target=lambda:n.dispatch(server,130));thread.start();self.assertTrue(entered.wait(2))
            self.assertFalse(n.dispatch(server,131));release.set();thread.join(3);self.assertFalse(thread.is_alive())
        with server.database() as db:
            state=n.read(db);state['items'][0].update(status='sending',next=200,attempts=1,lease='old');n.write(db,state)
        server.initialize();self.assertFalse(n.dispatch(server,199));self.assertTrue(n.dispatch(server,200));self.assertEqual(self.state()['items'][0]['attempts'],2)

    def test_config_change_cancels_inflight_result(self):
        self.configure();self.open()
        def change(config,item):self.configure(enabled=False);return True,False,'Accepté.'
        with patch.object(n,'deliver',side_effect=change):n.dispatch(server,130)
        self.assertEqual(self.state()['items'][0]['status'],'cancelled');self.assertFalse(n.dispatch(server))
        with self.assertRaises(server.Problem):n.retry(server,{'version':2,'id':self.state()['items'][0]['id']},'admin')

    def test_validation_secret_destination_change_and_optimistic_save(self):
        for value in ('http://example.com/topic','file:///tmp/secret','https://u:p@example.com/path','https://example.com/#frag','https://example.com:99999/x','https://example.com/\r\nInjected:header'):
            with self.subTest(value=value),self.assertRaises(server.Problem):self.configure(url=value)
        revision=self.configure()
        with self.assertRaises(server.Problem):self.configure(version=revision-1)
        with self.assertRaises(server.Problem):self.configure(url='https://new.example/topic',token='')
        self.configure(url='',token='');self.assertEqual(self.state()['config']['token'],'fixture-token')
        self.configure(url='https://new.example/topic',token='',clear_token=True);self.assertEqual(self.state()['config']['token'],'')

    def test_redirect_not_followed_and_proxy_ignored(self):
        self.configure();self.open();self.sink.responses=[302]
        with patch.dict('os.environ',{'http_proxy':'http://127.0.0.1:1','HTTP_PROXY':'http://127.0.0.1:1','no_proxy':'','NO_PROXY':''}):n.dispatch(server,130)
        self.assertEqual(len(self.sink.received),1);self.assertEqual(self.state()['items'][0]['status'],'failed');self.assertIn('302',self.state()['items'][0]['result'])

    def test_admin_csrf_no_network_during_api(self):
        self.assertEqual(self.request('GET','/api/notifications')[0],401)
        with server.database() as db:db.execute("INSERT INTO users(name,salt,hash,role) VALUES('reader','00','unused','viewer')")
        token,csrf=server.make_session('reader');self.assertEqual(self.request('GET','/api/notifications',token=token)[0],403)
        for route in ('configure','test','retry'):
            self.assertEqual(self.request('POST','/api/notifications/'+route,{},token,csrf)[0],403)
            self.assertEqual(self.request('POST','/api/notifications/'+route,{},self.token)[0],403)
        body={'version':0,'enabled':True,'kind':'webhook','minimum':'warning','recovery':True,'url':self.url}
        with patch.object(n,'deliver',side_effect=AssertionError('no network in request')):
            self.assertEqual(self.request('POST','/api/notifications/configure',body,self.token,self.csrf)[0],200)
            self.assertEqual(self.request('GET','/api/notifications',token=self.token)[0],200)
            self.assertEqual(self.request('POST','/api/notifications/test',{'version':1},self.token,self.csrf)[0],200)
        self.assertFalse(self.sink.received)

    def test_overflow_visible_history_bounded(self):
        self.configure()
        with server.database() as db:
            state=n.read(db)
            with patch.object(n,'MAX_QUEUE',2):
                for i in range(3):n.append(state,'test',dict(self.item,id=str(i)),100+i)
            self.assertEqual(state['dropped'],1)
            for item in state['items']:item['status']='sent'
            for i in range(105):n.append(state,'test',dict(self.item,id=str(i)),200+i);state['items'][-1]['status']='sent'
            n.write(db,state)
        self.assertEqual(len(self.state()['items']),100);self.assertEqual(n.status(server)['dropped'],1)

    def test_tls_rejects_untrusted_certificate_and_accepts_explicit_test_ca(self):
        cert=Path(self.temp.name)/'test-cert.pem';key=Path(self.temp.name)/'test-key.pem'
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(key),'-out',str(cert),'-days','1','-subj','/CN=localhost','-addext','subjectAltName=IP:127.0.0.1'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        tls=ThreadingHTTPServer(('127.0.0.1',0),Receiver);tls.received=[];tls.responses=[]
        context=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);context.load_cert_chain(cert,key)
        tls.socket=context.wrap_socket(tls.socket,server_side=True)
        thread=threading.Thread(target=tls.serve_forever,daemon=True);thread.start()
        try:
            self.configure(url='https://127.0.0.1:'+str(tls.server_port)+'/test');self.open()
            n.dispatch(server,130);self.assertFalse(tls.received);self.assertEqual(self.state()['items'][0]['status'],'queued')
            trusted=ssl.create_default_context(cafile=str(cert))
            with patch.object(n.ssl,'create_default_context',return_value=trusted):n.dispatch(server,160)
            self.assertEqual(len(tls.received),1);self.assertEqual(self.state()['items'][0]['status'],'sent')
        finally:tls.shutdown();tls.server_close();thread.join(2)
