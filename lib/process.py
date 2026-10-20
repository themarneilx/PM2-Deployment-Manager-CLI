#!/usr/bin/env python3
"""Pinned runtime paths, exact PM2 identities, launch definitions and listener health."""
import errno
import hashlib
import ipaddress
import json
import os
import re
from pathlib import Path
import shutil
import signal
import socket
import stat
import subprocess
import time
import urllib.error
import urllib.request
from model import atomic, json_write, redact, path_value

LIB=Path(__file__).resolve().parent


def safe_env(extra=None):
    env={k:os.environ[k] for k in ['HOME','USER','LOGNAME','SHELL','LANG','LC_ALL','TZ','PATH'] if k in os.environ}
    env['NODE_ENV']='production'
    if extra: env.update({k:str(v) for k,v in extra.items()})
    return env


def executable(value,label):
    candidate=value or shutil.which(label)
    if not candidate: raise ValueError(f'{label} is not installed or not on PATH')
    p=Path(candidate).resolve()
    if not path_value(str(p)): raise ValueError(f'{label} path cannot contain control characters')
    if not p.is_file() or not os.access(p,os.X_OK): raise ValueError(f'{label} is not an executable file')
    return p


def runtimes(p,state):
    node=executable(p['node_path'],'node')
    pm2=p['pm2_path'] or shutil.which('pm2') or str(Path(state)/'tools/node_modules/pm2/bin/pm2')
    if not Path(pm2).is_file(): raise ValueError('PM2 is missing; use the dependencies command for an explicitly confirmed user-local installation')
    pm2=Path(pm2).resolve()
    if not path_value(str(pm2)): raise ValueError('Invalid PM2 executable path')
    manager=executable(p['package_path'],p['package_manager'])
    path=os.pathsep.join(dict.fromkeys([str(node.parent),str(manager.parent),*os.environ.get('PATH','/usr/bin:/bin').split(os.pathsep)]))
    return node,pm2,manager,path


def check_engines(p,root,node,pm2,manager,path):
    package=json.loads((Path(root)/'package.json').read_text())
    requirements=[('project',package.get('engines',{}).get('node',''))]
    if p['framework']=='nextjs':
        f=Path(root)/'node_modules/next/package.json'
        if f.is_file(): requirements.append(('installed Next.js',json.loads(f.read_text()).get('engines',{}).get('node','')))
    roots=[str(Path(root)),str(manager.parent),str(pm2.parent),str(manager.parent.parent),str(pm2.parent.parent)]
    for label,requirement in requirements:
        if not requirement: continue
        result=subprocess.run([str(node),str(LIB/'semver.cjs')],input=json.dumps(dict(range=requirement,roots=roots)),text=True,capture_output=True,env=safe_env({'PATH':path}),timeout=15)
        if result.returncode: raise ValueError('Cannot validate declared Node requirement; install npm/PM2 with its semver dependency')
        data=json.loads(result.stdout)
        if not data['satisfied']: raise ValueError(f'Node {data["version"]} does not satisfy {label} engines.node {requirement}; select the correct Node executable')


def daemon_live(home):
    home=Path(home)
    if not (home/'pm2.pid').is_file(): return False
    try:
        pid=int((home/'pm2.pid').read_text().strip())
        if pid<=1 or Path(f'/proc/{pid}').stat().st_uid!=os.geteuid(): return False
        os.kill(pid,0)
        socket_path=home/'rpc.sock'
        return not socket_path.is_symlink() and stat.S_ISSOCK(socket_path.stat().st_mode) and socket_path.stat().st_uid==os.geteuid()
    except (OSError,ValueError): return False


def pm2_cli(node,pm2,home,args,raw=False,values=None,allow_start=False):
    if not daemon_live(home) and not allow_start:
        if args==['jlist']: return []
        raise ValueError('No live PM2 daemon for this PM2_HOME; nothing was started')
    if args==['jlist']:
        result=subprocess.run([str(node),str(LIB/'readonly.cjs'),str(pm2),str(Path(home)/'rpc.sock')],env=safe_env(),text=True,capture_output=True,timeout=5)
        if result.returncode: raise ValueError('PM2 RPC is unavailable; read-only query did not start a daemon')
        data=json.loads(result.stdout)
        if not isinstance(data,list): raise ValueError('Invalid PM2 RPC process list')
        return data
    env=safe_env({'PATH':str(Path(node).parent)+os.pathsep+os.environ.get('PATH','/usr/bin:/bin'),'PM2_HOME':str(home),'NO_COLOR':'1','PM2_SILENT':'true'})
    result=subprocess.run([str(node),str(pm2),*map(str,args)],env=env,text=True,capture_output=True,timeout=45)
    if result.returncode:
        raise ValueError('PM2 command failed: '+redact((result.stderr or result.stdout)[-1500:],values))
    if raw: return result.stdout
    if args==['jlist']:
        lines=result.stdout.splitlines()
        for i,line in enumerate(lines):
            if line.lstrip().startswith('['):
                try:
                    data=json.loads('\n'.join(lines[i:]))
                    if isinstance(data,list): return data
                except ValueError: pass
        raise ValueError('PM2 did not return a valid process list; raw output suppressed')
    return redact(result.stdout,values)


def identity(app):
    env=app.get('pm2_env',{})
    return dict(script=env.get('pm_exec_path',''),cwd=env.get('pm_cwd',''),
                interpreter=env.get('exec_interpreter',''),args=env.get('args',[]))


def signature(app):
    return hashlib.sha256(json.dumps(identity(app),sort_keys=True).encode()).hexdigest()


def matches(app,meta):
    if not app or app.get('name')!=meta.get('name'): return False
    if meta.get('adopted'): return signature(app)==meta.get('signature')
    env=app.get('pm2_env',{}); nested=env.get('env',{})
    nonce=env.get('PM2_MANAGER_NONCE',nested.get('PM2_MANAGER_NONCE',''))
    return nonce==meta.get('nonce') and env.get('pm_exec_path')==meta.get('script') and env.get('pm_cwd')==meta.get('cwd') and env.get('exec_interpreter')==meta.get('interpreter') and env.get('args',[])==meta.get('args',[])


def ecosystem(p,cwd,node,launcher,launch,nonce,log_dir):
    return {'apps':[dict(name=p['name'],cwd=str(cwd),script=os.path.relpath(launcher,cwd),args=[str(launch)],
                        interpreter=str(node),exec_mode='fork',instances=1,watch=False,vizion=False,
                        autorestart=True,min_uptime=3000,max_restarts=p['max_restarts'],restart_delay=p['restart_delay'],
                        kill_timeout=p['kill_timeout'],max_memory_restart=p['memory'],merge_logs=True,
                        out_file=str(Path(log_dir)/'stdout.log'),error_file=str(Path(log_dir)/'stderr.log'),
                        env=dict(NODE_ENV='production',PORT=str(p['port']),HOSTNAME=p['host'],PM2_MANAGER_NONCE=nonce))]}


def launch_command(p,release,node,manager):
    root=Path(release)
    if p['framework']=='nextjs':
        if p['mode']=='standalone':
            if p['entry']:
                server=(root/p['entry']).resolve()
            else:
                servers=list((root/'.next/standalone').glob('**/server.js'))
                servers=[x for x in servers if 'node_modules' not in x.relative_to(root/'.next/standalone').parts]
                if len(servers)!=1: raise ValueError('Standalone entry is missing or ambiguous; select its relative server.js path')
                server=servers[0]
            if not server.is_file() or not server.resolve().is_relative_to(root.resolve()): raise ValueError('Standalone server entry must exist inside the release')
            for src,dest in [(root/'public',server.parent/'public'),(root/'.next/static',server.parent/'.next/static')]:
                if src.is_dir() and src.resolve()!=dest.resolve(): shutil.copytree(src,dest,dirs_exist_ok=True)
            return [str(node),str(server)],server.parent
        executable_path=root/'node_modules/next/dist/bin/next'
        if not executable_path.is_file() or not (root/'.next/BUILD_ID').is_file(): raise ValueError('Standard Next.js requires its installed executable and .next/BUILD_ID')
        return [str(node),str(executable_path),'start','-H',p['host'],'-p',str(p['port'])],root
    if p['command']:
        command=list(p['command'])
        if command[0]=='node': command[0]=str(node)
        elif not Path(command[0]).is_absolute():
            local=root/command[0]
            command[0]=str(local) if local.is_file() else str(executable(command[0],command[0]))
        return command,root
    if p['entry']:
        entry=(root/p['entry']).resolve()
        if not entry.is_relative_to(root.resolve()) or not entry.is_file(): raise ValueError('Application entry must exist inside the release')
        return [str(node),str(entry)],root
    package=json.loads((root/'package.json').read_text())
    if p['start_script'] not in package.get('scripts',{}): raise ValueError('No start script; select a relative Node entry or custom argv command')
    if p['framework']=='vite':
        return [str(manager),'run',p['start_script'],'--','--host',p['host'],'--port',str(p['port']),'--strictPort'],root
    return [str(manager),'run',p['start_script']],root


def descendants(pid):
    parent_map={}
    for p in Path('/proc').iterdir():
        if not p.name.isdigit(): continue
        try:
            if p.stat().st_uid!=os.geteuid(): continue
            text=(p/'status').read_text()
            parent_map[int(p.name)]=int(next(x.split()[1] for x in text.splitlines() if x.startswith('PPid:')))
        except (OSError,ValueError,StopIteration): pass
    result={int(pid)}
    while True:
        new={p for p,parent in parent_map.items() if parent in result}
        if new<=result: return result
        result|=new


def listeners(port):
    result=[]
    for version,path in [(4,'/proc/net/tcp'),(6,'/proc/net/tcp6')]:
        try: lines=Path(path).read_text().splitlines()[1:]
        except OSError: continue
        for line in lines:
            parts=line.split()
            if len(parts)<10 or parts[3]!='0A': continue
            raw,number=parts[1].split(':')
            if int(number,16)!=port: continue
            data=bytes.fromhex(raw)
            if version==4: data=data[::-1]
            else: data=b''.join(data[i:i+4][::-1] for i in range(0,16,4))
            result.append((str(ipaddress.ip_address(data)),parts[9]))
    return result


def listener_owned(host,port,pid):
    records=listeners(port)
    target=ipaddress.ip_address(host)
    for address,_ in records:
        actual=ipaddress.ip_address(address)
        if not target.is_unspecified and actual.is_unspecified: return False
    relevant={inode for address,inode in records if ipaddress.ip_address(address).is_unspecified or target.is_unspecified or ipaddress.ip_address(address)==target}
    if not relevant: return False
    owned=set()
    for process_id in descendants(pid):
        try:
            for fd in Path(f'/proc/{process_id}/fd').iterdir():
                try:
                    target=os.readlink(fd)
                    if target.startswith('socket:['): owned.add(target[8:-1])
                except OSError: pass
        except OSError: pass
    return bool(relevant) and relevant<=owned


def port_available(host,port,allowed_pid=None):
    if allowed_pid and listener_owned(host,port,allowed_pid): return True
    family=socket.AF_INET6 if ':' in host else socket.AF_INET
    try:
        with socket.socket(family,socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            probe.bind((host,port))
        return True
    except OSError: return False


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None


def health(p,get_app):
    last='No online process'; first_restart=None; success_at=None
    target='127.0.0.1' if p['host']=='0.0.0.0' else '::1' if p['host']=='::' else p['host']
    url=f'http://{"["+target+"]" if ":" in target else target}:{p["port"]}{p["health_path"]}'
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    for _ in range(p['health_retries']):
        app=get_app()
        if not app or app.get('pm2_env',{}).get('status')!='online' or not app.get('pid'):
            last='PM2 is not online with a PID'
        else:
            pid=int(app['pid']); restarts=int(app['pm2_env'].get('restart_time',0))
            if first_restart is None: first_restart=restarts
            if restarts!=first_restart: last='Process restart count changed during health checks'
            elif not listener_owned(p['host'],p['port'],pid): last='Expected port is not owned by the PM2 process tree'
            else:
                try:
                    with socket.create_connection((target,p['port']),timeout=p['health_timeout']): pass
                    try:
                        with opener.open(url,timeout=p['health_timeout']) as response: status=response.status
                    except urllib.error.HTTPError as response: status=response.code
                    if status in p['accepted_status']:
                        if success_at is not None and time.monotonic()-success_at>=0.15:
                            return dict(healthy=True,pid=pid,port=p['port'],http_status=status,restarts=restarts)
                        success_at=time.monotonic()
                        last='Waiting for a stable second health sample'
                    else: last=f'HTTP status {status} is not in configured acceptable statuses'
                except (OSError,urllib.error.URLError): last='TCP/HTTP probe failed'
        time.sleep(max(p['health_interval'],0.2))
    return dict(healthy=False,reason=last,port=p['port'])


def uses_source(app,root):
    env=app.get('pm2_env',{})
    if env.get('status') in {'stopped','errored'}: return False
    root=Path(root).resolve()
    candidates=[env.get('pm_cwd'),env.get('pm_exec_path')]
    args=env.get('args',[])
    if isinstance(args,list): candidates.extend(a for a in args if isinstance(a,str) and a.startswith('/'))
    if app.get('pid'):
        for pid in descendants(app['pid']):
            try: candidates.append(os.readlink(f'/proc/{pid}/cwd'))
            except OSError: pass
    return any(Path(p).resolve().is_relative_to(root) for p in candidates if p)


def tree_usage(pid):
    def snapshot():
        ticks=0; memory=0
        for child in descendants(pid):
            try:
                raw=Path(f'/proc/{child}/stat').read_text().rsplit(')',1)[1].split()
                ticks+=int(raw[11])+int(raw[12])
                memory+=int(raw[21])*os.sysconf('SC_PAGE_SIZE')
            except (OSError,ValueError,IndexError): pass
        return ticks,memory
    start,_=snapshot(); before=time.monotonic(); time.sleep(0.1); end,memory=snapshot()
    return dict(cpu_percent=round(max(0,end-start)/os.sysconf('SC_CLK_TCK')/(time.monotonic()-before)*100,1),rss_bytes=memory,scope='launcher and live descendants; summed RSS includes shared pages')


def check_manager(p,root,manager,env):
    package=json.loads((Path(root)/'package.json').read_text())
    declared=package.get('packageManager','')
    match=re.fullmatch(r'(npm|pnpm|yarn|bun)@([0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?)(?:\+.*)?',declared) if isinstance(declared,str) else None
    if not match: return
    if match[1]!=p['package_manager']: raise ValueError('Selected package manager conflicts with package.json packageManager')
    result=subprocess.run([str(manager),'--version'],env=env,text=True,capture_output=True,timeout=30)
    if result.returncode or result.stdout.strip()!=match[2]: raise ValueError(f'Select the package-manager executable matching packageManager {declared}; no version was installed automatically')
