"""Parcours SMTP chiffrés réels sur loopback ; aucune boîte externe."""
import json
from pathlib import Path
import ssl
import tempfile
import threading
from email import policy
from email.parser import BytesParser
import unittest
from unittest.mock import patch
import test_console
from smtp_fixture import Server,certificate
server=test_console.server
import notifications as n
import smtp_notifications as smtp

class SMTPTests(unittest.TestCase):
    request=test_console.ConsoleSecurityTests.request
    @classmethod
    def setUpClass(cls):
        cls.certs=tempfile.TemporaryDirectory();cls.cert,cls.context=certificate(cls.certs.name)
    @classmethod
    def tearDownClass(cls):cls.certs.cleanup()
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.previous=server.ROOT,server.STATE,server.DB
        server.ROOT=Path(self.temp.name);server.STATE=server.ROOT/'state/console';server.DB=server.STATE/'console.db';server.initialize()
        self.sink=Server(self.context).start();self.token,self.csrf=server.make_session('admin')
        self.http=server.Server(('127.0.0.1',0),server.Handler);threading.Thread(target=self.http.serve_forever,daemon=True).start()
    def tearDown(self):
        self.http.shutdown();self.http.server_close();self.sink.stop()
        server.ROOT,server.STATE,server.DB=self.previous;self.temp.cleanup()
    def body(self,**changes):
        value={'host':'127.0.0.1','port':self.sink.server_address[1],'security':'starttls','username':'fixture-user','password':'fixture-pass','sender':'nacre@example.test','recipient':'alerts@example.test'};value.update(changes)
        return {'version':n.status(server)['config']['version'],'enabled':False,'kind':'smtp','minimum':'warning','recovery':True,'smtp':value}
    def configure(self,**changes):n.configure(server,self.body(**changes),'admin')
    def enqueue(self):n.test(server,{'version':n.status(server)['config']['version']},'admin')
    def state(self):
        with server.database() as db:return n.read(db)
    def dispatch(self,now=None):
        context=ssl.create_default_context(cafile=str(self.cert))
        with patch.object(smtp.ssl,'create_default_context',return_value=context):return n.dispatch(server,now)
    def message(self,index=0):return BytesParser(policy=policy.default).parsebytes(self.sink.received[index]['data'])

    def test_starttls_authentication_precedes_email_and_secret_is_private(self):
        self.configure();self.enqueue();self.dispatch()
        self.assertIn(('STARTTLS',False),self.sink.commands);self.assertIn(('AUTH',True),self.sink.commands)
        self.assertNotIn(('AUTH',False),self.sink.commands);self.assertTrue(self.sink.received[0]['secure'])
        m=self.message();self.assertEqual(m['To'],'alerts@example.test');self.assertEqual(m['From'],'nacre@example.test')
        self.assertIn('Test de notification Nacre',m['Subject']);self.assertIn('Aucun incident réel',m.get_content())
        self.assertEqual(m['Message-ID'],'<'+self.state()['items'][0]['id']+'@nacre.local>')
        public=json.dumps(n.status(server));self.assertNotIn('fixture-pass',public);self.assertTrue(n.status(server)['config']['smtp']['has_password'])
        self.assertNotIn('fixture-pass',str(m));self.assertNotIn('fixture-user',str(m));self.assertEqual(self.state()['items'][0]['status'],'sent')
        with server.database() as db:log=json.dumps([tuple(x) for x in db.execute('SELECT * FROM audit')])
        self.assertNotIn('fixture-pass',log);self.assertNotIn('fixture-data-private',log)

    def test_direct_tls_without_authentication_and_quit_disconnect(self):
        self.sink.stop();self.sink=Server(self.context,direct=True).start();self.sink.drop_after_data=True
        self.configure(security='tls',username='',password='');self.enqueue();self.dispatch()
        self.assertTrue(self.sink.received[0]['secure']);self.assertNotIn(('STARTTLS',False),self.sink.commands)
        self.assertFalse(any(c[0]=='AUTH' for c in self.sink.commands));self.assertEqual(self.state()['items'][0]['status'],'sent')

    def test_untrusted_certificate_and_missing_starttls_never_send_credentials(self):
        self.configure();self.enqueue();n.dispatch(server)
        self.assertFalse(self.sink.received);self.assertFalse(any(c[0] in ('AUTH','MAIL') for c in self.sink.commands))
        item=self.state()['items'][0];self.assertEqual(item['status'],'queued')
        self.sink.allow_starttls=False;self.dispatch(item['next'])
        self.assertEqual(self.state()['items'][0]['status'],'failed');self.assertFalse(self.sink.received)
        self.assertFalse(any(c[0] in ('AUTH','MAIL') for c in self.sink.commands))

    def test_temporary_data_failure_persists_and_keeps_message_id(self):
        self.sink.data_codes=[451,250];self.configure();self.enqueue();self.dispatch()
        item=self.state()['items'][0];self.assertEqual(item['status'],'queued');server.initialize();self.dispatch(item['next'])
        self.assertEqual(self.message(0)['Message-ID'],self.message(1)['Message-ID'])
        self.assertEqual(self.state()['items'][0]['attempts'],2);self.assertEqual(self.state()['items'][0]['status'],'sent')

    def test_authentication_refusal_is_permanent_without_raw_error(self):
        self.sink.auth_code=535;self.configure();self.enqueue();self.dispatch()
        item=self.state()['items'][0];self.assertEqual(item['status'],'failed');self.assertIn('535',item['result'])
        self.assertNotIn('fixture-auth-private',item['result']);self.assertFalse(self.sink.received)

    def test_recipient_refusal_550_and_manual_retry(self):
        self.sink.rcpt_code=550;self.configure();self.enqueue();self.dispatch();item=self.state()['items'][0]
        self.assertEqual(item['status'],'failed');self.assertIn('550',item['result']);self.assertNotIn('fixture-recipient-private',item['result'])
        self.sink.rcpt_code=250;n.retry(server,{'version':1,'id':item['id']},'admin');self.dispatch()
        self.assertEqual(self.state()['items'][0]['status'],'sent')

    def test_validation_and_no_old_password_forwarded_to_changed_endpoint(self):
        for change in ({'security':'none'},{'port':True},{'host':'mail.example:587'},{'host':'bad\r\nhost'},{'sender':'x@example.test\r\nBcc:evil@example.test'},{'recipient':'a@example.test,b@example.test'},{'recipient':'Nom <a@example.test>'},{'username':'é'},{'password':''},{'password':'x','clear_password':True}):
            with self.subTest(change=change),self.assertRaises(server.Problem):self.configure(**change)
        self.configure()
        with self.assertRaises(server.Problem):self.configure(host='other.example',password='')
        self.configure(password='');self.assertEqual(self.state()['config']['smtp']['password'],'fixture-pass')
        self.configure(host='other.example',username='',password='',clear_password=True)
        self.assertEqual(self.state()['config']['smtp']['password'],'')

    def test_lazy_upgrade_and_transport_switch_clear_unused_secrets(self):
        old={'config':{'version':3,'enabled':False,'kind':'webhook','url':'https://example.test/private','token':'fixture-http-token','minimum':'warning','recovery':True},'items':[],'dropped':0,'last_test':0}
        with server.database() as db:n.write(db,old)
        self.assertEqual(n.status(server)['config']['smtp']['port'],587);self.assertEqual(self.state()['config']['token'],'fixture-http-token')
        self.configure();self.assertEqual(self.state()['config']['token'],'');self.assertEqual(self.state()['config']['url'],'')
        n.configure(server,{'version':4,'enabled':False,'kind':'ntfy','url':'https://example.test/topic','minimum':'warning','recovery':True},'admin')
        self.assertEqual(self.state()['config']['smtp'],smtp.defaults())

    def test_smtp_configuration_through_http_has_no_network_side_effect(self):
        with patch.object(smtp,'deliver',side_effect=AssertionError('no sending in request')):
            self.assertEqual(self.request('POST','/api/notifications/configure',self.body(),self.token)[0],403)
            self.assertEqual(self.request('POST','/api/notifications/configure',self.body(),self.token,self.csrf)[0],200)
            response=self.request('GET','/api/notifications',token=self.token)
            self.assertEqual(response[0],200);self.assertNotIn('fixture-pass',str(response))
            self.assertEqual(self.request('POST','/api/notifications/test',{'version':1},self.token,self.csrf)[0],200)
        self.assertFalse(self.sink.received)
