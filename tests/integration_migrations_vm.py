#!/usr/bin/env python3
"""Reprise de la base de console dans une installation neuve, VM QEMU uniquement."""
from contextlib import closing
import http.client
import json
import os
from pathlib import Path
import re
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time

SOURCE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(SOURCE/'console'))
import schema
from recover_database import prepare


def main():
    assert os.environ.get('NACRE_VM_LAB')=='1'
    assert Path('/sys/class/dmi/id/sys_vendor').read_text().strip() in ('QEMU','Bochs')
    with tempfile.TemporaryDirectory(prefix='nacre-reprise-') as temporary:
        root=Path(temporary);old=root/'old';fresh=root/'fresh'
        env=dict(os.environ,NAS_ROOT=str(old),NACRE_SYSTEMD_TASKS='0')
        subprocess.run([sys.executable,str(SOURCE/'console/server.py'),'init'],env=env,check=True,capture_output=True)
        dbpath=old/'state/console/console.db'
        password=re.search(r'Mot de passe : (.+)',(old/'state/console/acces.txt').read_text())[1]
        with closing(sqlite3.connect(dbpath)) as db:
            db.execute('PRAGMA user_version=0')
            db.execute("INSERT INTO audit(ts,username,action,detail) VALUES(1,'admin','Témoin de reprise','donnée synthétique')")
            db.commit()
        schema.ensure(dbpath)
        checkpoint=next((dbpath.parent/'migration-backups').glob('*.sqlite3'))
        (fresh/'state/console').mkdir(parents=True,mode=0o700)
        prepare(checkpoint,fresh/'state/console/console.db')
        env['NAS_ROOT']=str(fresh)
        with socket.socket() as probe:
            probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
        env['NAS_PORT']=str(port)
        process=subprocess.Popen([sys.executable,str(SOURCE/'console/server.py')],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            for _ in range(100):
                if process.poll() is not None:raise RuntimeError('La nouvelle console a quitté prématurément.')
                try:
                    with socket.create_connection(('127.0.0.1',port),timeout=.2):break
                except OSError:time.sleep(.1)
            client=http.client.HTTPConnection('127.0.0.1',port,timeout=5)
            client.request('POST','/api/login',body=json.dumps({'username':'admin','password':password}),headers={'Content-Type':'application/json'})
            response=client.getresponse();body=json.loads(response.read())
            assert response.status==200 and body['role']=='admin'
            cookie=response.getheader('Set-Cookie').split(';')[0];client.close()
            client=http.client.HTTPConnection('127.0.0.1',port,timeout=5)
            client.request('GET','/api/events',headers={'Cookie':cookie})
            response=client.getresponse();events=json.loads(response.read());client.close()
            assert response.status==200 and any(e['action']=='Témoin de reprise' for e in events)
            assert not (fresh/'state/console/acces.txt').exists(), 'Aucun nouvel identifiant ne doit remplacer celui conservé.'
            with closing(sqlite3.connect(dbpath)) as db:
                assert db.execute("SELECT count(*) FROM audit WHERE action='Témoin de reprise'").fetchone()[0]==1
        finally:
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait()
    result={'fresh_console_from_checkpoint':True,'original_admin_password_http_login':True,
            'recovered_audit_read_via_http':True,'original_database_preserved':True,
            'no_new_password_generated':True,'scope':'console database only','host_block_devices_used':False}
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
