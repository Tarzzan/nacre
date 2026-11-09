import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(SOURCE/'console'))
sys.path.insert(0,str(SOURCE))
from smb_storage import Shares,manifest,render
spec=importlib.util.spec_from_file_location('smb_fixture_server',SOURCE/'console/server.py')
app=importlib.util.module_from_spec(spec);sys.modules[spec.name]=app;spec.loader.exec_module(app)


class SMBStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();app.ROOT=Path(self.temp.name);app.STATE=app.ROOT/'state/console';app.DB=app.STATE/'console.db'
        app.initialize();self.manager=Shares(app)
        self.config=app.smb_state()
        self.config['shares'].append({'name':'volume','area':'native_managed-fixture','path':'','users':['nas'],'readonly':False})
        self.resource={'id':'managed-fixture','kind':'volume','name':'Volume','path':'/srv/Volume $A/data','writable':True,'identity':{'dev':42,'ino':256}}
        self.resources=[self.resource];self.calls=[]
        self.resource_patch=patch.object(app,'native_resources',side_effect=lambda:self.resources)
        self.compose_patch=patch.object(app,'compose',side_effect=self.compose)
        self.command_patch=patch.object(app,'command',return_value='')
        self.resource_patch.start();self.compose_patch.start();self.command_patch.start()

    def tearDown(self):
        self.resource_patch.stop();self.compose_patch.stop();self.command_patch.stop();self.temp.cleanup()

    def compose(self,*args,**kwargs):
        self.calls.append(args)
        if 'stat' in args:return '42:256\n'
        if 'id' in args:return '1000\n'
        return ''

    def test_manifest_prevents_directory_creation_and_escapes_compose_dollars(self):
        m=manifest(self.config,{'native_managed-fixture':self.resource})
        bind=m['services']['fichiers']['volumes'][0]
        self.assertFalse(bind['bind']['create_host_path'])
        self.assertEqual(bind['source'],'/srv/Volume $$A/data')
        self.assertEqual(bind['target'],'/shares/native_managed-fixture')

    def test_mount_recreates_only_samba_then_validates_and_enables_share(self):
        self.manager.apply(self.config)
        self.assertIn('available = yes',self.manager.runtime.read_text())
        self.assertTrue(any(a[:2]==('up','-d') and a[-1]=='fichiers' for a in self.calls))
        self.assertFalse(any(a[0] in ('up','start','stop','restart') and a[-1]=='video' for a in self.calls))
        self.assertIn('veto files = /.nacre-*/',self.manager.runtime.read_text())

    def test_missing_volume_disabled_without_replacement_bind_and_manual_stop_respected(self):
        self.manager.apply(self.config);self.resources=[];self.calls.clear()
        self.manager.apply(self.config,reconcile=True)
        self.assertIn('[volume]\npath = /shares/native_managed-fixture\navailable = no',self.manager.runtime.read_text())
        self.assertEqual(json.loads(self.manager.override.read_text())['services']['fichiers']['volumes'],[])
        self.manager.set_intent(False);self.calls.clear();self.manager.apply(self.config,reconcile=True)
        self.assertEqual(self.calls,[])

    def test_control_failure_does_not_reenable_native_share(self):
        self.manager.apply(self.config)
        changed=copy.deepcopy(self.config);changed['shares'][-1]['readonly']=True
        with patch.object(app,'command',side_effect=app.Problem('Docker indisponible',503)):
            with self.assertRaises(app.Problem):self.manager.apply(changed)
        self.assertIn('[volume]\npath = /shares/native_managed-fixture\navailable = no',self.manager.runtime.read_text())
        self.assertFalse(app.smb_state()['shares'][-1]['readonly'])


if __name__=='__main__':unittest.main()
