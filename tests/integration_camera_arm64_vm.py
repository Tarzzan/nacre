#!/usr/bin/env python3
"""Qualifier le vrai runtime vidéo ARM64 sans publier d’image ou de secret.

VM QEMU uniquement. Configurer une caméra de banc nommée tapo, puis appeler
synthetic, source, target ou reboot. Les attentes source restent privées hors Git.
"""
import argparse,hashlib,http.client,json,os,re,sqlite3,subprocess,sys,time
from pathlib import Path
from urllib.request import urlopen
assert os.environ.get('NACRE_VM_LAB')=='1' and os.uname().machine=='aarch64'
assert Path('/sys/class/dmi/id/sys_vendor').read_text().strip() in ('QEMU','Bochs')
parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('phase',choices=('synthetic','source','target','reboot'));phase=parser.parse_args().phase
BASE=Path('/home/ubuntu/nacre-fresh-test');ROOT=BASE/'restored';SOURCE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));from compose_support import arguments

def run(args,**kwargs):return subprocess.check_output(args,stderr=subprocess.PIPE,**kwargs)
def sha(path):
 with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
container=run(arguments(ROOT,'ps','-q','video'),text=True).strip();assert container
info=json.loads(run(['docker','inspect',container]))[0]
assert json.loads(run(['docker','image','inspect',info['Image']]))[0]['Architecture']=='arm64'
ip=next(iter(info['NetworkSettings']['Networks'].values()))['IPAddress']
def video(path):return urlopen('http://'+ip+':5000'+path,timeout=20)
def rows():
 with sqlite3.connect('file:'+str(ROOT/'state/frigate/frigate.db')+'?mode=ro',uri=True) as db:
  db.row_factory=sqlite3.Row;return [dict(r) for r in db.execute("SELECT id,path,start_time,end_time FROM recordings WHERE camera='tapo' ORDER BY start_time")]
def local(row):
 path=Path(row['path']);assert path.is_relative_to('/media/frigate/recordings');return ROOT/'data/video'/path.relative_to('/media/frigate')
def decode(container_path):
 run(['docker','exec',container,'/usr/lib/ffmpeg/7.0/bin/ffmpeg','-v','error','-i',container_path,'-map','0:v:0','-frames:v','10','-f','null','-'])
start=time.time()
for _ in range(120):
 try:
  with video('/api/stats') as response:stats=json.load(response)['cameras']['tapo']
  recorded=rows()
  if stats['camera_fps']>0 and len(recorded)>=2 and (phase in ('synthetic','source') or any(r['start_time']>start for r in recorded)):break
 except (OSError,ValueError,KeyError,sqlite3.Error):pass
 time.sleep(2)
else:raise AssertionError('Flux actif et nouveaux enregistrements non confirmés')
password=re.search(r'Mot de passe : (.+)',(BASE/'bundle/source-lost/state/console/acces.txt').read_text())[1]
c=http.client.HTTPConnection('127.0.0.1',8766,timeout=30)
c.request('POST','/api/login',json.dumps({'username':'admin','password':password}),{'Content-Type':'application/json'})
r=c.getresponse();body=json.loads(r.read());assert r.status==200;headers={'Cookie':r.getheader('Set-Cookie').split(';')[0]};c.close()
def web(path,limit=None):
 c=http.client.HTTPConnection('127.0.0.1',8766,timeout=30);c.request('GET',path,headers=headers);r=c.getresponse();data=r.read(limit);status=r.status;c.close();assert status==200,status;return data
assert web('/api/camera/snapshot').startswith(b'\xff\xd8')
assert b'\xff\xd8' in web('/api/camera/live',16384)
listing=json.loads(web('/api/camera/recordings'));assert len(listing)>=2
expected_path=BASE/'camera-expectations.json'
if phase in ('target','reboot'):
 expected=json.loads(expected_path.read_text());old=expected['recordings']
 by_id={r['id']:r for r in recorded}
 for r in old:
  assert r['id'] in by_id
  assert sha(local(by_id[r['id']]))==r['sha256']
  assert all(by_id[r['id']][key]==r[key] for key in ('start_time','end_time','path'))
 selected=by_id[old[0]['id']]
else:
 selected=recorded[0]
 if phase=='source':
  old=[{**r,'sha256':sha(local(r))} for r in recorded[:2]]
  expected_path.write_text(json.dumps({'recordings':old,'source_architecture':os.uname().machine},indent=2));expected_path.chmod(0o600)
decode(selected['path'])
clip=web('/api/camera/clip?start='+str(selected['start_time']+.1)+'&end='+str(selected['end_time']-.1))
assert b'ftyp' in clip[:40];clip_path=BASE/'private-playback.mp4';clip_path.write_bytes(clip);clip_path.chmod(0o600)
run(['docker','cp',str(clip_path),container+':/tmp/recovery-playback.mp4']);decode('/tmp/recovery-playback.mp4')
run(['docker','exec',container,'rm','/tmp/recovery-playback.mp4']);clip_path.unlink()
proof={'phase':phase,'architecture':os.uname().machine,'frigate_image_arm64':True,'camera_fps':stats['camera_fps'],
 'recordings_observed':len(recorded),'nacre_authenticated_snapshot_jpeg':True,'nacre_authenticated_live_mjpeg':True,
 'nacre_authenticated_recording_list':True,'nacre_authenticated_clip_decoded':True,'recording_decoded':True,
 'source_recordings_restored_with_identical_hashes':len(old) if phase in ('target','reboot') else 0,
 'new_recordings_after_start':phase in ('target','reboot'),'frames_or_credentials_published':False}
(BASE/('camera-'+phase+'-proof.json')).write_text(json.dumps(proof,indent=2));print(json.dumps(proof))
