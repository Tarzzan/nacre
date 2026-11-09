#!/usr/bin/env python3
"""Cycle de vie des copies, uniquement après le banc QEMU 0.4 + XFS."""
import hashlib
import json
import os
from pathlib import Path
import signal
import sqlite3
import sys
import time
from integration_provision_vm import run,rpc


def pause_worker(job):
    with sqlite3.connect('/var/lib/nacre-storage/catalog.db') as db:
        for _ in range(300):
            status,pid=db.execute('SELECT status,pid FROM native_jobs WHERE id=?',(job,)).fetchone()
            if pid:
                command=Path(f'/proc/{pid}/cmdline').read_bytes()
                assert b'native_restore.py' in command and job.encode() in command
                os.kill(pid,signal.SIGSTOP)
                return pid
            if status not in ('queued','running'):raise RuntimeError('Tâche terminée avant observation')
            time.sleep(.005)
    raise RuntimeError('Worker non observé')


def wait_job(job):
    for _ in range(300):
        row=next(j for j in rpc('status')['jobs'] if j['id']==job)
        if row['status'] not in ('queued','running'):return row
        time.sleep(.1)
    raise RuntimeError('Copie non terminée')


def main():
    assert os.geteuid()==0 and os.environ.get('NACRE_VM_LAB')=='1'
    assert Path('/sys/class/dmi/id/sys_vendor').read_text().strip() in ('QEMU','Bochs')
    assert run('lsblk','-dn','-o','SERIAL','/dev/vdc')=='NACRE-LAB-B'
    source=Path('/srv/nacre-xfs')
    if str(source) not in run('findmnt','-rn','-o','TARGET').splitlines():
        run('mount','/dev/nacre_test/thin',str(source))
    large=source/'copie-volumineuse.bin'
    expected=hashlib.sha256()
    block=b'Nacre - copie native - donnees virtuelles\n'*(1024*1024//40)
    with large.open('wb') as file:
        for _ in range(300):file.write(block);expected.update(block)
        file.flush();os.fsync(file.fileno())
    plan=rpc('prepare',{'action':'snapshot','volume':'thin'})
    rpc('commit',{'plan':plan['id'],'confirmation':plan['confirmation']})
    point=plan['id']
    plan=rpc('prepare',{'action':'clone','volume':'thin','point':point})
    job=rpc('commit',{'plan':plan['id'],'confirmation':plan['confirmation']})['job']
    pid=pause_worker(job)
    try:
        run('systemctl','daemon-reload')
        run('systemctl','restart','nacre-storage')
        for _ in range(100):
            try:status=rpc('status');break
            except RuntimeError:time.sleep(.1)
        os.kill(pid,0)
        assert next(j for j in status['jobs'] if j['id']==job)['status']=='running'
    finally:os.kill(pid,signal.SIGCONT)
    completed=wait_job(job)
    assert completed['status']=='done',completed
    restored=Path(completed['location'])/large.name
    digest=hashlib.sha256()
    with restored.open('rb') as file:
        while chunk:=file.read(1024*1024):digest.update(chunk)
    assert digest.hexdigest()==expected.hexdigest()
    plan=rpc('prepare',{'action':'clone','volume':'thin','point':point})
    cancelled_job=rpc('commit',{'plan':plan['id'],'confirmation':plan['confirmation']})['job']
    pid=pause_worker(cancelled_job)
    try:rpc('cancel',{'job':cancelled_job})
    finally:os.kill(pid,signal.SIGCONT)
    cancelled=wait_job(cancelled_job)
    assert cancelled['status']=='cancelled',cancelled
    assert not cancelled['location']
    assert large.stat().st_size==restored.stat().st_size
    result={'survives_daemon_restart':True,'large_copy_bytes':large.stat().st_size,'sha256_verified':True,'cancellation_verified':True,'original_preserved':True}
    Path('/home/ubuntu/native-jobs-results.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result))


if __name__=='__main__':main()
