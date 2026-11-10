#!/usr/bin/env python3
"""Démarrer les VM ARM64 du banc avec un runtime Ubuntu extrait, sans installation hôte.

Usage : NACRE_VM_LAB_HOST=1 python3 tests/start_arm_lab.py /banc/prive arm-source
"""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys
if os.environ.get('NACRE_VM_LAB_HOST')!='1' or os.uname().machine!='aarch64':
 raise SystemExit('Hôte ARM64 et banc explicitement réservé requis.')
w=Path(sys.argv[1]).resolve()
name=sys.argv[2];assert name in ('arm-source','arm-target')
assert w.is_dir() and w.stat().st_uid==os.getuid() and not w.stat().st_mode&0o077
assert hashlib.sha256((w/'base-arm64.img').read_bytes()).hexdigest()=='3dc8370d923978d4b610fa7964d1b36ba040eefb43198809ca5bc8ac51777b18'
assert not (w/(name+'.qcow2')).exists() and not (w/(name+'-vars.fd')).exists()
assert not (w/(name+'.pid')).exists()
if name=='arm-target':assert not (w/'arm-source.pid').exists()
r=w/'runtime/root';env=dict(os.environ,LD_LIBRARY_PATH=str(r/'usr/lib/aarch64-linux-gnu'))
subprocess.run([str(r/'usr/bin/qemu-img'),'create','-f','qcow2','-F','qcow2','-b',str(w/'base-arm64.img'),str(w/(name+'.qcow2')),'16G'],env=env,check=True)
shutil.copyfile(r/'usr/share/AAVMF/AAVMF_VARS.fd',w/(name+'-vars.fd'))
a=[str(r/'usr/bin/qemu-system-aarch64'),'-L',str(r/'usr/share/qemu'),'-name','nacre-v09-'+name,'-machine','virt,accel=kvm,gic-version=host','-cpu','host','-m','3072','-smp','2',
'-smbios','type=1,manufacturer=QEMU,product=Nacre-isolated-ARM64',
'-drive','if=pflash,format=raw,readonly=on,file='+str(r/'usr/share/AAVMF/AAVMF_CODE.fd'),'-drive','if=pflash,format=raw,file='+str(w/(name+'-vars.fd')),
'-drive','file='+str(w/(name+'.qcow2'))+',format=qcow2,if=none,id=os','-device','virtio-blk-pci,drive=os,bootindex=1']
if name=='arm-target':
 for x in 'ABC':
  image=w/('disk-'+x+'.raw')
  with image.open('xb') as f:f.truncate(2*1024**3)
  a+=['-drive','file='+str(image)+',format=raw,if=none,id=lab'+x+',cache=none','-device','virtio-blk-pci,drive=lab'+x+',serial=NACRE-V08-'+x]
port='2251' if name=='arm-source' else '2252'
a+=['-drive','file='+str(w/'seed.iso')+',format=raw,if=virtio,readonly=on','-netdev','user,id=net0,hostfwd=tcp:127.0.0.1:'+port+'-:22','-device','virtio-net-pci,netdev=net0,romfile=',
'-display','none','-serial','file:'+str(w/(name+'-serial.log')),'-daemonize','-pidfile',str(w/(name+'.pid')),'-qmp','unix:'+str(w/(name+'-qmp.sock'))+',server=on,wait=off']
(w/(name+'-command.json')).write_text(json.dumps(a));subprocess.run(['nice','-n','10',*a],env=env,check=True)
