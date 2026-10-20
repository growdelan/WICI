"""Explicit local CLI smoke check. Starts and stops its own loopback processes."""
import json
import os
import signal
import socket
import subprocess
import time
from pathlib import Path
from urllib.request import urlopen

ROOT=Path(__file__).resolve().parents[1]
COMMAND=['uv','run','--locked','python','-m','wici','--demo']
URL='http://127.0.0.1:8765'

def read(path):
    with urlopen(URL+path,timeout=1) as response:
        return json.load(response)

def start():
    process=subprocess.Popen(COMMAND,cwd=ROOT,start_new_session=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    try:
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            if process.poll() is not None:
                raise RuntimeError(process.communicate()[0])
            try:
                health=read('/api/health')
                return process,health
            except OSError:
                time.sleep(0.05)
        raise RuntimeError('UI did not become available within 10s')
    except BaseException:
        stop(process)
        raise

def stop(process):
    if process.poll() is None:
        os.killpg(process.pid,signal.SIGINT)
    output=process.communicate(timeout=10)[0]
    assert 'Traceback' not in output,output
    assert process.returncode in (0,130,-signal.SIGINT),process.returncode
    return {'exit_code':process.returncode,'no_traceback':True}

def main():
    report={'command':' '.join(COMMAND)}
    process,health=start()
    try:
        report['mode']=health['mode']
        before=read('/api/communications')
        conflict=subprocess.run(COMMAND,check=False,cwd=ROOT,capture_output=True,text=True,timeout=10)
        assert conflict.returncode!=0 and 'Nie można uruchomić' in conflict.stderr
        report['second_instance_port_error']=True
        assert (ROOT/'var/demo/app.sqlite3').exists()
        report['local_data_path']=True
    finally:
        report['first_shutdown']=stop(process)
    process,_=start()
    try:
        after=read('/api/communications')
        assert before==after
        report['restart_preserved_records']=True
    finally:
        report['restart_shutdown']=stop(process)
    with socket.socket() as blocker:
        blocker.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        blocker.bind(('127.0.0.1',8765));blocker.listen()
        occupied=subprocess.run(COMMAND,check=False,cwd=ROOT,capture_output=True,text=True,timeout=10)
        assert occupied.returncode!=0 and 'Nie można uruchomić' in occupied.stderr
        report['occupied_port_does_not_kill_owner']=True
    with socket.socket() as freed:
        freed.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        freed.bind(('127.0.0.1',8765))
    report['port_released']=True
    file=ROOT/'tmp/live-checks/system-check.json'
    file.parent.mkdir(parents=True,exist_ok=True)
    file.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':
    main()
