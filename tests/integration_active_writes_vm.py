#!/usr/bin/env python3
"""Producteurs et contrôles invités du banc coupures + écritures. QEMU seulement.

Les confirmations sont envoyées au contrôleur externe, jamais prises comme preuve
à partir d’un journal stocké dans la VM qui va être coupée. SMB utilise FLUSH.
"""
import argparse,hashlib,http.client,json,os,re,subprocess,sys,threading,time
from pathlib import Path
assert os.environ.get('NACRE_VM_LAB')=='1'
assert Path('/sys/class/dmi/id/sys_vendor').read_text().strip() in ('QEMU','Bochs')
p=argparse.ArgumentParser(description=__doc__);p.add_argument('phase',choices=('write','verify'));p.add_argument('--epoch',type=int,default=0);a=p.parse_args()
SOURCE=Path(__file__).resolve().parents[1];BASE=Path('/home/ubuntu/nacre-fresh-test');ROOT=BASE/'restored'
sys.path.insert(0,str(SOURCE/'console'));sys.path.insert(0,str(SOURCE))
from native_storage import NativeClient
from compose_support import arguments
client=NativeClient();pool=json.loads((BASE/'result.json').read_text())['pool']
def status():return client.request('status','admin')
for _ in range(120):
 try:
  s=status();resource=next(r for r in s['resources'] if r['id']==pool)
  assert resource['writable'];break
 except (OSError,ValueError,StopIteration,AssertionError):time.sleep(.5)
else:raise AssertionError('Volume vérifié indisponible')
target=Path(resource['path']);assert target.is_relative_to('/srv/nacre-volumes')
password=re.search(r'Mot de passe : (.+)',(BASE/'bundle/source-lost/state/console/acces.txt').read_text())[1]
for _ in range(120):
 try:
  c=http.client.HTTPConnection('127.0.0.1',8766,timeout=15)
  c.request('POST','/api/login',json.dumps({'username':'admin','password':password}),{'Content-Type':'application/json'})
  r=c.getresponse();body=json.loads(r.read());assert r.status==200
  headers={'Cookie':r.getheader('Set-Cookie').split(';')[0],'X-CSRF-Token':body['csrf'],'Content-Type':'application/octet-stream'};c.close();break
 except (OSError,ValueError):time.sleep(.5)
else:raise AssertionError('Console indisponible')
def web_request(method,path,data=None):
 c=http.client.HTTPConnection('127.0.0.1',8766,timeout=30);c.request(method,path,data,headers);r=c.getresponse();out=r.read();code=r.status;c.close();return code,out

def payload(name,size=65536):return (hashlib.sha256(name.encode()).digest()*((size+31)//32))[:size]
def digest(path):
 with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

if a.phase=='verify':
 references=json.load(sys.stdin);ack=references['acknowledged'];interruptions=references['interrupted_http']
 assert ack and len({r['name'] for r in ack})==len(ack)
 for row in ack:
  assert re.fullmatch(r'active-[1-3]-(local|http|smb)-[0-9]+\.bin',row['name'])
  path=target/row['name'];assert path.stat().st_size==row['size'] and digest(path)==row['sha256'],row['name']
 for name in interruptions:
  assert re.fullmatch(r'active-[1-3]-interrupted\.bin',name)
  assert not (target/name).exists(),'Dépôt HTTP incomplet publié'
 code,raw=web_request('GET','/api/files?area=native_'+pool);assert code==200
 listing=json.loads(raw);assert '.nacre-upload-' not in raw.decode()
 partials=list(target.glob('.nacre-upload-*'))
 for path in partials:
  code,_=web_request('GET','/api/download?area=native_'+pool+'&path='+path.name);assert code==403
 counts={p:sum(r['protocol']==p for r in ack) for p in ('local','http','smb')}
 out={'architecture':os.uname().machine,'confirmed_files_verified':counts,'confirmed_bytes':sum(r['size'] for r in ack),
      'missing_or_corrupt_confirmed_files':0,'incomplete_http_names_absent':len(interruptions),
      'internal_upload_fragments_not_exposed':len(partials),'http_login_after_cut':True}
 print(json.dumps(out));sys.exit()

import smbclient
from smbprotocol.exceptions import SMBException
secret='Banc-reprise-samba-seulement-42' # gitleaks:allow — fixture synthétique
for _ in range(100):
 try:
  smbclient.register_session('127.0.0.1',username='alice',password=secret,port=1445,connection_timeout=10)
  assert 'temoin.txt' in smbclient.listdir(r'\\127.0.0.1\fichiers',port=1445);break
 except (OSError,ValueError,SMBException):
  smbclient.reset_connection_cache();time.sleep(.5)
else:raise AssertionError('SMB indisponible')
# Exiger que le serveur honore les requêtes FLUSH, sans modifier sa configuration.
strict=subprocess.check_output(arguments(ROOT,'exec','-T','fichiers','testparm','-s','--parameter-name=strict sync'),stderr=subprocess.DEVNULL,text=True).strip()
assert strict.lower()=='yes'
lock=threading.Lock();stop=threading.Event()
def emit(kind,**values):
 with lock:print(json.dumps({'kind':kind,'epoch':a.epoch,**values}),flush=True)
def writer(protocol):
 try:
  for index in range(2000):
   if stop.is_set():return
   name=f'active-{a.epoch}-{protocol}-{index}.bin';data=payload(name)
   row={'protocol':protocol,'name':name,'size':len(data),'sha256':hashlib.sha256(data).hexdigest()}
   emit('intent',**row)
   if protocol=='local':
    temporary=target/('.local-'+name)
    with temporary.open('xb') as f:f.write(data);f.flush();os.fsync(f.fileno())
    temporary.rename(target/name);fd=os.open(target,os.O_DIRECTORY);os.fsync(fd);os.close(fd)
   elif protocol=='http':
    code,_=web_request('POST','/api/upload?area=native_'+pool+'&name='+name,data);assert code==200,code
   else:
    with smbclient.open_file(r'\\127.0.0.1\fichiers'+'\\'+name,mode='xb',buffering=0,port=1445) as f:
     view=memoryview(data)
     while view:view=view[f.write(view):]
     f.flush() # Réponse SMB2 FLUSH reçue avant la confirmation externe.
   emit('ack',**row);time.sleep(.15)
  raise AssertionError('Budget du banc épuisé sans coupure')
 except BaseException as error:
  emit('error',protocol=protocol,error=type(error).__name__);stop.set()
def incomplete_http():
 try:
  trigger=BASE/f'trigger-{a.epoch}'
  while not trigger.exists():
   if stop.wait(.05):return
  name=f'active-{a.epoch}-interrupted.bin';size=2*1024**2
  before=set(target.glob('.nacre-upload-*'))
  c=http.client.HTTPConnection('127.0.0.1',8766,timeout=30)
  c.putrequest('POST','/api/upload?area=native_'+pool+'&name='+name)
  for k,v in headers.items():c.putheader(k,v)
  c.putheader('Content-Length',str(size));c.endheaders();c.send(payload(name,size//2))
  for _ in range(100):
   fragments=[p for p in set(target.glob('.nacre-upload-*'))-before if p.stat().st_size==size//2]
   if fragments:break
   time.sleep(.05)
  else:raise AssertionError('Écriture partielle serveur non observée')
  # L’autre moitié n’est jamais envoyée : le contrôleur coupe cette VM.
  emit('cut_ready',name=name,declared_bytes=size,sent_bytes=size//2,server_temporary_bytes=size//2)
  while not stop.wait(.5):pass
  c.close()
 except BaseException as error:emit('error',protocol='incomplete-http',error=type(error).__name__);stop.set()
assert 1<=a.epoch<=3 and not (BASE/f'trigger-{a.epoch}').exists()
emit('ready',smb_strict_sync=True,smb_explicit_flush=True)
threads=[threading.Thread(target=writer,args=(p,)) for p in ('local','http','smb')]+[threading.Thread(target=incomplete_http)]
for t in threads:t.start()
for t in threads:t.join()
raise SystemExit(1)
