"""Garde-fous RAID1 sur métadonnées simulées, jamais sur les disques hôtes."""
import copy,json,os,sqlite3,tempfile,unittest
from pathlib import Path
from contextlib import nullcontext
from unittest.mock import patch
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'console'))
import native_storage as native
from mirror_repair import MirrorRepair

class MirrorTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)
  self.specs=[{'id':x,'path':'/dev/disk/by-id/'+x,'serial':x,'bytes':1000,'initialize':True} for x in ('disk-a','disk-b','disk-c')]
  self.policy={'version':1,'allowed_uid':1000,'volumes':[],'provisioning':{'enabled':True,'root':'/srv/test','devices':self.specs}}
  self.patch=patch.object(native,'read_policy',side_effect=lambda _:copy.deepcopy(self.policy));self.patch.start()
  self.private=patch('provisioning.private_directory');self.private.start()
  self.native_private=patch.object(native,'private_directory');self.native_private.start()
  self.calls=[]
  def runner(args,pass_fds=()):self.calls.append(args);raise native.NativeError('interruption simulée')
  self.engine=native.Engine(self.path/'policy',self.path,runner)
  self.record={'id':'managed-test','name':'Miroir','layout':'mirror','filesystem':'ext4','root':'/srv/test','mountpoint':'/srv/test/managed-test','md_uuid':'uuid-md','fs_uuid':'uuid-fs','specs':copy.deepcopy(self.specs[:2]),'native_volume':None}
  with self.engine.db:self.engine.db.execute('INSERT INTO deployments VALUES(?,0,?,?,?,?)',('managed-test','admin','ready',json.dumps(self.record),''))
  self.manager=MirrorRepair(self.engine)
  self.identities={s['id']:{'id':s['id'],'path':'/dev/'+s['id'],'device':'8:'+str(i),'serial':s['serial'],'bytes':1000} for i,s in enumerate(self.specs)}
  self.probe=patch('provisioning.Provisioning.probe',side_effect=lambda s,blank=True:copy.deepcopy(self.identities[s['id']]));self.probe.start()
  self.observed={'path':'/dev/md0','device':'9:0','members':[{'device':'8:0','state':['in_sync']}],'degraded':1,'sync_action':'idle','array_state':'clean'}
  self.observe=patch.object(MirrorRepair,'observe',side_effect=lambda _:copy.deepcopy(self.observed));self.observe.start()
 def tearDown(self):
  self.observe.stop();self.probe.stop();self.native_private.stop();self.private.stop();self.patch.stop();self.engine.db.close();self.temp.cleanup()
 def prepare(self):return self.engine.prepare(1000,'admin',{'action':'repair','volume':'managed-test','replace':'disk-b','device':'disk-c'})
 def commit(self,plan):return self.engine.commit(1000,'admin',{'plan':plan['id'],'confirmation':plan['confirmation']})
 def test_healthy_busy_wrong_survivor_or_small_replacement_refused(self):
  for field,value in [('degraded',0),('sync_action','recover'),('array_state','readonly'),('members',[{'device':'8:1','state':['in_sync']}])]:
   before=copy.deepcopy(self.observed);self.observed[field]=value
   with self.assertRaises(native.NativeError):self.prepare()
   self.observed=before
  self.identities['disk-c']['bytes']=999
  with self.assertRaises(native.NativeError):self.prepare()
  self.assertEqual(self.calls,[])
 def test_policy_change_and_replaced_disk_invalidate_plan(self):
  plan=self.prepare();self.specs[2]['serial']='changed'
  with self.assertRaises(native.NativeError):self.commit(plan)
  self.specs[2]['serial']='disk-c';self.identities['disk-c']['device']='8:99'
  with self.assertRaises(native.NativeError):self.commit(plan)
  self.assertEqual(self.calls,[])
 def test_confirmation_expiry_and_actor_are_bound(self):
  plan=self.prepare()
  for actor,confirmation in [('autre',plan['confirmation']),('admin','oui')]:
   with self.assertRaises(native.NativeError):self.engine.commit(1000,actor,{'plan':plan['id'],'confirmation':confirmation})
  with self.engine.db:self.engine.db.execute('UPDATE plans SET expires=0')
  with self.assertRaises(native.NativeError):self.commit(plan)
 def test_partial_rebuild_never_reported_complete(self):
  self.record['repair']={'plan':'p','status':'rebuilding'}
  self.record['specs']=[self.specs[0],self.specs[2]]
  with self.engine.db:self.engine.db.execute("UPDATE deployments SET phase='repairing',record=?",(json.dumps(self.record),))
  self.manager.reconcile()
  self.assertEqual(self.engine.db.execute('SELECT phase FROM deployments').fetchone()[0],'repairing')
  self.observed.update(degraded=0,members=[{'device':'8:0','state':['in_sync']},{'device':'8:2','state':['in_sync']}],sync_action='recover')
  self.manager.reconcile()
  self.assertEqual(self.engine.db.execute('SELECT phase FROM deployments').fetchone()[0],'repairing')
  self.observed['sync_action']='idle';self.manager.reconcile()
  self.assertEqual(self.engine.db.execute('SELECT phase FROM deployments').fetchone()[0],'ready')
 def test_command_failure_consumes_plan_without_automatic_retry(self):
  dummy=self.path/'pinned';dummy.touch()
  self.identities['disk-a'].update(path=str(dummy),device='0:0')
  mdfile=self.path/'md';mdfile.touch()
  self.observed.update(path=str(mdfile),device='0:0',members=[{'device':'0:0','state':['in_sync']}])
  plan=self.prepare()
  with patch('provisioning.Provisioning.pinned',return_value=nullcontext((999,))),self.assertRaises(native.NativeError):self.commit(plan)
  self.assertEqual(len(self.calls),1)
  self.assertEqual(self.engine.db.execute('SELECT phase FROM deployments').fetchone()[0],'uncertain')
  with self.assertRaises(native.NativeError):self.commit(plan)
  self.assertEqual(len(self.calls),1)

 def test_uncertain_repair_review_only_validates_verified_metadata(self):
  self.record['repair']={'plan':'old','status':'rebuilding'}
  self.record['specs']=[self.specs[0],self.specs[2]]
  with self.engine.db:self.engine.db.execute("UPDATE deployments SET phase='uncertain',record=?",(json.dumps(self.record),))
  body={'action':'repair-review','volume':'managed-test'}
  with self.assertRaises(native.NativeError):self.engine.prepare(1000,'admin',body)
  self.observed.update(degraded=0,members=[{'device':'8:0','state':['in_sync']},{'device':'8:2','state':['in_sync']}])
  plan=self.engine.prepare(1000,'admin',body);self.commit(plan)
  self.assertEqual(self.engine.db.execute('SELECT phase FROM deployments').fetchone()[0],'ready')
  self.assertEqual(self.calls,[])
