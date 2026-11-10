#!/usr/bin/env python3
"""Coupures SIGKILL d’une VM Nacre dédiée ; aucune commande sur des disques hôtes."""
import argparse,json,os,signal,socket,stat,subprocess,time
from pathlib import Path

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--command',type=Path,required=True)
p.add_argument('--key',type=Path,required=True)
p.add_argument('--known-hosts',type=Path,required=True)
p.add_argument('--port',type=int,required=True)
p.add_argument('--result',type=Path,required=True)
p.add_argument('--resume',action='store_true',help='Reprendre un banc interrompu après une coupure déjà consignée.')
a=p.parse_args()
if os.environ.get('NACRE_VM_LAB_HOST')!='1':raise SystemExit('Banc hôte explicitement réservé requis.')
work=a.command.resolve().parent;args=json.loads(a.command.read_text())
assert Path(args[0]).name in ('qemu-system-x86_64','qemu-system-aarch64')
assert args[args.index('-name')+1].startswith('nacre-v09-')
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
    if x=='-drive' and 'id=labC' in args[i+1]:args[i+1]+=',bps_wr=16777216'
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

cuts=[]
if a.resume:
    prior=json.loads(a.result.read_text());assert prior['complete'] is False and 1<=len(prior['cuts'])<=3
    cuts=prior['cuts'];restart()
else:
    assert not a.result.exists()
    throttle(16777216);guest('begin')
for fraction in (.10,.40,.70)[len(cuts):]:
    deadline=time.monotonic()+300
    while time.monotonic()<deadline:
        try:
            observed=guest('observe')
            if fraction<=observed['done']/observed['total']<.95:break
        except (RuntimeError,subprocess.TimeoutExpired):pass
        time.sleep(.3)
    else:raise RuntimeError('Reconstruction active incomplète non observée ; aucune coupure exécutée.')
    pid=int(pidfile.read_text());cmdline=Path(f'/proc/{pid}/cmdline').read_bytes().decode().split('\0')
    assert '-name' in cmdline and cmdline[cmdline.index('-name')+1]==args[args.index('-name')+1]
    assert str(pidfile) in cmdline and str(qmp) in '\0'.join(cmdline)
    control('stop');assert control('query-status')['status']=='paused'
    os.kill(pid,signal.SIGKILL)
    for _ in range(100):
        proc=Path(f'/proc/{pid}/stat')
        if not proc.exists() or proc.read_text().split(') ')[1].startswith('Z'):break
        time.sleep(.1)
    else:raise RuntimeError('Ancien hyperviseur toujours actif')
    cuts.append({**observed,'threshold':fraction,'hypervisor_paused_then_sigkill':True})
    a.result.write_text(json.dumps({'cuts':cuts,'complete':False},indent=2))
    # Le membre défaillant reste conservé hors de la VM.
    restart()
    if len(cuts)==3:throttle(0)
    print(json.dumps({'cut':len(cuts),'completed_sectors':observed['done'],'total_sectors':observed['total']}),flush=True)
if len(cuts)==3:throttle(0)
# Disponibilité du guest après la dernière coupure, sans déclencher finish deux fois.
for _ in range(100):
    if subprocess.run(ssh+['test -S /run/nacre-storage/control.sock'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0:break
    time.sleep(.5)
else:raise RuntimeError('Invité non revenu')
final=guest('finish')
assert len({c['boot_id'] for c in cuts})==3
out={'complete':True,'cuts':cuts,'result':final,'method':'QEMU vCPU stop then SIGKILL; no guest shutdown; data drives cache=none','scope':'virtual abrupt loss; not physical controller cache or power electronics'}
a.result.write_text(json.dumps(out,indent=2));print(json.dumps(out),flush=True)
