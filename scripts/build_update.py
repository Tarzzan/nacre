#!/usr/bin/env python3
"""Build a signed Nacre update from an exact committed tree; private key stays external."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'console'))
from update_engine import code_path,REQUIRED

def build(repo,key,output,commit='HEAD'):
    def git(*args):return subprocess.check_output(['git',*args],cwd=repo)
    commit=git('rev-parse',commit+'^{commit}').decode().strip()
    files={name:git('show',commit+':'+name) for name in git('ls-tree','-r','--name-only',commit).decode().splitlines() if code_path(name)}
    if not REQUIRED.issubset(files):raise ValueError('Committed source is incomplete')
    version=re.search(r'^## (\S+) —',files['CHANGELOG.md'].decode(),re.M)[1]
    # Schema compatibility is also pinned byte-for-byte by the receiving supervisor.
    schema=int(re.search(r'^VERSION = (\d+)$',files['console/schema.py'].decode(),re.M)[1])
    manifest=json.dumps({'format':1,'version':version,'schema':schema,'commit':commit,'files':{n:hashlib.sha256(v).hexdigest() for n,v in files.items()}},sort_keys=True).encode()
    with tempfile.TemporaryDirectory() as directory:
        temp=Path(directory);(temp/'manifest.json').write_bytes(manifest)
        subprocess.run(['openssl','pkeyutl','-sign','-rawin','-inkey',str(Path(key).resolve()),'-in',str(temp/'manifest.json'),'-out',str(temp/'manifest.sig')],check=True,capture_output=True)
        # Refuse signing with a key different from the public authority in the release.
        (temp/'trust.pub').write_bytes(files['console/update-signing.pub'])
        subprocess.run(['openssl','pkeyutl','-verify','-pubin','-rawin','-inkey',str(temp/'trust.pub'),'-in',str(temp/'manifest.json'),'-sigfile',str(temp/'manifest.sig')],check=True,capture_output=True)
        with tarfile.open(output,'w:gz') as archive:
            for name,value in [('manifest.json',manifest),('manifest.sig',(temp/'manifest.sig').read_bytes()),*(('code/'+n,v) for n,v in files.items())]:
                info=tarfile.TarInfo(name);info.size=len(value);info.mode=0o600;archive.addfile(info,io.BytesIO(value))
    return {'version':version,'commit':commit,'sha256':hashlib.sha256(Path(output).read_bytes()).hexdigest(),'files':len(files)}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--key',required=True);parser.add_argument('--output',required=True);parser.add_argument('--commit',default='HEAD')
    args=parser.parse_args();print(json.dumps(build(Path(__file__).resolve().parents[1],args.key,args.output,args.commit)))
