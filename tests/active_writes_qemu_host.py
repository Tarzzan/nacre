#!/usr/bin/env python3
"""Coupures SIGKILL d’une VM Nacre dédiée ; aucune commande sur des disques hôtes."""
import argparse,json,os,signal,socket,stat,subprocess,time,threading
from pathlib import Path

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--command',type=Path,required=True)
p.add_argument('--key',type=Path,required=True)
p.add_argument('--known-hosts',type=Path,required=True)
p.add_argument('--port',type=int,required=True)
p.add_argument('--result',type=Path,required=True)
p.add_argument('--resume',action='store_true',help='Reprendre après une coupure déjà vérifiée, invité en marche, sans producteurs démarrés pour la session suivante.')
a=p.parse_args()
if os.environ.get('NACRE_VM_LAB_HOST')!='1':raise SystemExit('Banc hôte explicitement réservé requis.')
work=a.command.resolve().parent;args=json.loads(a.command.read_text())
assert a.result.exists() if a.resume else not a.result.exists()
os.environ['LD_LIBRARY_PATH']=str(work/'runtime/root/usr/lib/aarch64-linux-gnu')
assert Path(args[0]).name in ('qemu-system-x86_64','qemu-system-aarch64')
assert args[args.index('-name')+1].startswith('nacre-v11-')
assert not set(args)&{'-virtfs','-fsdev','-blockdev','-incoming','-loadvm'}
for i,x in enumerate(args):
    if x=='-drive':
        opts=dict(v.split('=',1) for v in args[i+1].split(',') if '=' in v)
        path=Path(opts['file']).resolve()
        assert stat.S_ISREG(path.stat().st_mode)
        assert path.is_relative_to(work) or (opts.get('if')=='pflash' and opts.get('readonly')=='on')
    if x=='-netdev':assert args[i+1].startswith('user,') and 'hostfwd=tcp:127.0.0.1:' in args[i+1]
pidfile=Path(args[args.index('-pidfile')+1]);assert pidfile.resolve().parent==work
qmp=Path(args[args.index('-qmp')+1].split(',')[0].removeprefix('unix:'));assert qmp.resolve().parent==work
ssh=['ssh','-o','BatchMode=yes','-o','ConnectTimeout=3','-o','ServerAliveInterval=5','-o','ServerAliveCountMax=2','-o','UserKnownHostsFile='+str(a.known_hosts),'-i',str(a.key),'-p',str(a.port),'ubuntu@127.0.0.1']
script='NACRE_VM_LAB=1 python3 /home/ubuntu/nacre-code/tests/integration_powercut_vm.py '

def guest(phase):
    r=subprocess.run(ssh+[script+phase],capture_output=True,text=True,timeout=330)
    if r.returncode:raise RuntimeError('Phase invité '+phase+' refusée : '+r.stderr[-1000:])
    return json.loads(r.stdout)

def control(name,arguments=None):
    with socket.socket(socket.AF_UNIX) as s:
        s.settimeout(10);s.connect(str(qmp));f=s.makefile('rwb');json.loads(f.readline())
        def call(cmd,values=None):
            f.write((json.dumps({'execute':cmd,**({'arguments':values} if values is not None else {})})+'\n').encode());f.flush()
            while True:
                r=json.loads(f.readline())
                if 'error' in r:raise RuntimeError(r)
                if 'return' in r:return r['return']
        call('qmp_capabilities');return call(name,arguments)

def throttle(bps):
    control('block_set_io_throttle',{'device':'labC','bps':0,'bps_rd':0,'bps_wr':bps,'iops':0,'iops_rd':0,'iops_wr':0})

# Le plafond QEMU persiste dans la commande de redémarrage, même avant sysctl.
for i,x in enumerate(args):
    if x=='-drive' and 'id=labC' in args[i+1]:args[i+1]+=',bps_wr=8388608'
def restart():
    global args
    rebuilt=[];i=0
    while i<len(args):
        if args[i] in ('-drive','-device') and ('id=labB' in args[i+1] or 'drive=labB,' in args[i+1]):i+=2;continue
        rebuilt.append(args[i]);i+=1
    args=rebuilt
    # La fin du processus principal peut précéder la libération des verrous IO.
    for _ in range(40):
        r=subprocess.run(['nice','-n','10',*args],capture_output=True,text=True)
        if r.returncode==0:return
        if not (('Failed to get' in r.stderr and 'lock' in r.stderr) or 'Cannot lock pid file' in r.stderr):raise RuntimeError(r.stderr)
        time.sleep(.5)
    raise RuntimeError('Images encore verrouillées ; aucun second hyperviseur lancé.')

active='NACRE_VM_LAB=1 /home/ubuntu/nacre-fresh-test/venv/bin/python -u /home/ubuntu/nacre-code/tests/integration_active_writes_vm.py '
journal=work/'acknowledgements.jsonl';assert journal.exists() if a.resume else not journal.exists()
lock=threading.Lock();acknowledged=[];events=[];errors=[];cuts=[];interrupted=[];checks=[]

def collect(process):
    with journal.open('a') as log:
        for line in process.stdout:
            try:
                event=json.loads(line);event['received_monotonic']=time.monotonic()
                with lock:
                    events.append(event)
                    if event['kind']=='ack':acknowledged.append(event)
                    if event['kind']=='error':errors.append(event)
                    log.write(json.dumps(event)+'\n');log.flush();os.fsync(log.fileno())
            except (ValueError,KeyError):
                with lock:errors.append({'kind':'invalid-output'})

def references():
    with lock:return {'acknowledged':list(acknowledged),'interrupted_http':list(interrupted)}
def verify():
    r=subprocess.run(ssh+[active+'verify'],input=json.dumps(references()),capture_output=True,text=True,timeout=180)
    if r.returncode:raise RuntimeError('Vérification invité refusée : '+r.stderr[-1500:])
    return json.loads(r.stdout)
def save(complete=False,**extra):
    a.result.write_text(json.dumps({'complete':complete,'cuts':cuts,'checks_after_cuts':checks,
        'method':'QEMU paused then SIGKILL; data images cache=none; durable reference journal outside guest',
        'smb_confirmation':'explicit SMB2 FLUSH response, strict sync=yes',
        'physical_controller_cache_loss_tested':False,**extra},indent=2))

if a.resume:
    prior=json.loads(a.result.read_text());assert not prior['complete'] and 1<=len(prior['cuts'])<3
    cuts=prior['cuts'];checks=prior['checks_after_cuts'];assert len(checks)==len(cuts)
    events=[json.loads(line) for line in journal.read_text().splitlines()]
    assert all(e['epoch']<=len(cuts) for e in events), 'Des producteurs ont déjà commencé la session suivante'
    acknowledged=[e for e in events if e['kind']=='ack'];assert not any(e['kind']=='error' for e in events)
    interrupted=[f"active-{c['epoch']}-interrupted.bin" for c in cuts]
    assert guest('observe')['boot_id']!=cuts[-1]['boot_id']
else:
    throttle(8388608);guest('begin')
for epoch,fraction in list(enumerate((.12,.42,.72),1))[len(cuts):]:
    error_log=(work/f'writer-{epoch}.stderr').open('w')
    process=subprocess.Popen(ssh+[active+'write --epoch '+str(epoch)],stdout=subprocess.PIPE,stderr=error_log,text=True,bufsize=1)
    reader=threading.Thread(target=collect,args=(process,),daemon=True);reader.start()
    deadline=time.monotonic()+360
    while time.monotonic()<deadline:
        with lock:
            if errors:raise RuntimeError('Producteur en erreur : '+str(errors[-1]))
            counts={p:sum(e['epoch']==epoch and e['protocol']==p for e in acknowledged) for p in ('local','http','smb')}
        if process.poll() is not None:raise RuntimeError('Producteurs arrêtés avant la coupure')
        try:
            observed=guest('observe')
            if fraction<=observed['done']/observed['total']<.95 and min(counts.values())>=5:break
        except (RuntimeError,subprocess.TimeoutExpired):pass
        time.sleep(.5)
    else:raise RuntimeError('Écritures et reconstruction non observées ensemble')
    subprocess.run(ssh+['touch /home/ubuntu/nacre-fresh-test/trigger-'+str(epoch)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    for _ in range(200):
        with lock:
            if errors:raise RuntimeError('Producteur en erreur : '+str(errors[-1]))
            ready=next((e for e in events if e['epoch']==epoch and e['kind']=='cut_ready'),None)
        if ready:break
        time.sleep(.05)
    else:raise RuntimeError('Dépôt HTTP incomplet non confirmé')
    observed=guest('observe');assert fraction<=observed['done']/observed['total']<.95
    with lock:
        for p in ('local','http','smb'):
            assert time.monotonic()-max(e['received_monotonic'] for e in acknowledged if e['epoch']==epoch and e['protocol']==p)<5
    pid=int(pidfile.read_text());cmdline=Path(f'/proc/{pid}/cmdline').read_bytes().decode().split('\0')
    assert '-name' in cmdline and cmdline[cmdline.index('-name')+1]==args[args.index('-name')+1]
    assert str(pidfile) in cmdline and str(qmp) in '\0'.join(cmdline)
    control('stop');assert control('query-status')['status']=='paused'
    os.kill(pid,signal.SIGKILL)
    for _ in range(100):
        proc=Path(f'/proc/{pid}/stat')
        if not proc.exists() or proc.read_text().split(') ')[1].startswith('Z'):break
        time.sleep(.1)
    else:raise RuntimeError('Hyperviseur encore actif')
    process.wait(timeout=20);reader.join(timeout=20);assert not reader.is_alive();error_log.close()
    # Inclure aussi les réponses déjà reçues qui étaient dans le pipe SSH.
    interrupted.append(ready['name'])
    with lock:counts={p:sum(e['epoch']==epoch and e['protocol']==p for e in acknowledged) for p in ('local','http','smb')}
    cuts.append({**observed,'epoch':epoch,'threshold':fraction,'confirmed_before_cut':counts,
                 'http_body_incomplete':{k:ready[k] for k in ('declared_bytes','sent_bytes','server_temporary_bytes')},
                 'hypervisor_paused_then_sigkill':True})
    save();restart()
    for _ in range(100):
        if subprocess.run(ssh+['test -S /run/nacre-storage/control.sock'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0:break
        time.sleep(.5)
    else:raise RuntimeError('Invité non revenu')
    checks.append(verify());save()
    print(json.dumps({'cut':epoch,'verified':checks[-1]}),flush=True)
throttle(0);baseline=guest('finish');final=verify()
assert len({c['boot_id'] for c in cuts})==3
save(True,baseline=baseline,final=final)
print(json.dumps({'complete':True,'final':final,'baseline':baseline}),flush=True)
