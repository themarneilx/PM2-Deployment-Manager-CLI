"""Explicit adoption, private settings, startup integration and redacted inspection."""
import getpass
import json
import os
from pathlib import Path
import pwd
import re
import shutil
import subprocess
import time
import uuid
import model
import process


def unit_quote(value,command=False):
    value=str(value)
    if any(ord(c)<32 or ord(c)==127 for c in value): raise ValueError('Systemd values cannot contain control characters')
    if command: value=value.replace('$','$$')
    return '"'+value.replace('\\','\\\\').replace('"','\\"').replace('%','%%')+'"'


class Maintenance:
    def adopt(self,raw):
        p=model.resolve_project(raw); name=p['name']; self.activate_runtime(p)
        app=self.app(name)
        if not app: raise ValueError('There is no existing process with this name to adopt')
        if (self.state/'apps'/f'{name}.json').exists(): raise ValueError('This application is already managed')
        env=app.get('pm2_env',{})
        if ' ' in os.path.relpath(env.get('pm_exec_path',''),env.get('pm_cwd','/')): raise ValueError('PM2 treats script paths containing spaces as shell commands; move the unmanaged entry before adoption')
        if env.get('exec_mode','fork_mode')!='fork_mode' or env.get('instances',1)!=1: raise ValueError('Adoption supports a single fork process only')
        print(json.dumps(dict(name=name,id=app['pm_id'],identity={k:v for k,v in process.identity(app).items() if k!='args'},port=p['port']),indent=2))
        print('Adoption records this exact definition without restarting it. Its existing environment/log files remain external. A later update creates a managed release.')
        if self.dry_run: return
        if not self.confirm('Adopt this exact process definition?'): raise ValueError('Adoption declined')
        with self.lock():
            current=self.app(name)
            if not current or process.signature(current)!=process.signature(app): raise ValueError('Process definition changed during adoption')
            if (self.state/'apps'/f'{name}.json').exists(): raise ValueError('Name was claimed during adoption')
            p.update(node_path=str(self.node),pm2_path=str(self.pm2_bin),package_path=str(self.manager_bin))
            attestation=self.state/'private'/f'{name}-{uuid.uuid4().hex}.json'
            model.json_write(attestation,dict(signature=process.signature(app)))
            meta=dict(version=1,name=name,profile=p,pm2_home=str(self.home),adopted=True,signature=process.signature(app),ecosystem=str(attestation),ecosystem_sha=model.sha(attestation),script=env['pm_exec_path'],cwd=env['pm_cwd'])
            model.json_write(self.state/'profiles'/f'{name}.json',p)
            model.json_write(self.state/'apps'/f'{name}.json',meta)
            print('Adopted. Run health to verify the selected host/port/endpoint before saving reboot state.')
            return meta

    def create_env(self,name):
        if not model.name_valid(name): raise ValueError('Invalid app name')
        target=self.state/'env'/f'{name}.env'
        if target.exists(): raise ValueError('Environment file already exists; select it or create another file explicitly. It will not be overwritten.')
        print(f'Create protected environment file: {target}. Values are entered without terminal echo.')
        if self.dry_run: return None
        if not self.confirm('Create a new private environment file?'): raise ValueError('Environment creation declined')
        values={}
        while True:
            key=input('Variable name (blank to finish): ').strip()
            if not key: break
            if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',key): raise ValueError('Invalid variable name')
            values[key]=getpass.getpass('Value (hidden): ')
        with self.lock():
            if target.exists(): raise ValueError('Environment file was created by another operation')
            # JSON strings are compatible with this manager’s literal dotenv reader.
            model.atomic(target,''.join(k+'='+json.dumps(v,ensure_ascii=False)+'\n' for k,v in values.items()))
            try: model.read_env([str(target)])
            except BaseException: target.unlink(); raise
        print(f'Created: {target}. Select this file during deployment; NEXT_PUBLIC_ changes require rebuilding.')
        return str(target)

    def env_keys(self,name):
        meta=self.metadata(name)
        current=model.read_env(meta['profile']['env_files'])
        print(json.dumps(dict(files=meta['profile']['env_files'],keys=sorted(current),public_build_keys=sorted(k for k in current if k.startswith('NEXT_PUBLIC_'))),indent=2))
        print('Values are suppressed. Update selected files with a local editor; env-apply stages a release using their current values.')

    def profiles(self):
        rows=[]
        for category in ['profiles','drafts']:
            for path in sorted((self.state/category).glob('*.json')):
                p=model.load_profile(path); rows.append(dict(name=p['name'],kind=category,file=str(path),framework=p['framework'],path=p['path'],host=p['host'],port=p['port']))
        print(json.dumps(rows,indent=2)); return rows

    def profile_save(self,path):
        p=model.load_profile(path); target=self.state/'drafts'/f'{p["name"]}.json'
        print(f'Save validated nonsecret draft: {target}. Active deployment changes only through deploy/update.')
        if self.dry_run: return
        if not self.confirm('Save or replace this draft profile?'): raise ValueError('Profile save declined')
        with self.lock(): model.json_write(target,p)

    def export(self,name):
        meta,app=self.owned(name); p=meta['profile']; host=p['host']
        if host=='0.0.0.0': host='127.0.0.1'
        if host=='::': host='::1'
        data=dict(name=name,framework=p['framework'],host=host,port=p['port'],upstream=f'http://{"["+host+"]" if ":" in host else host}:{p["port"]}',health_path=p['health_path'],status=(app or {}).get('pm2_env',{}).get('status','absent'))
        print(json.dumps(data,indent=2)); return data

    def releases(self,name):
        self.metadata(name)
        rows=[]
        for path in sorted((self.state/'releases'/name).glob('*/release.json')):
            data=json.loads(path.read_text()); rows.append(dict(release=data['release'],reference=str(path),source_digest=data['source_digest']))
        print(json.dumps(rows,indent=2)); return rows

    def logs(self,name,lines=50,follow=False,kind='both'):
        meta,app=self.owned(name); self.values=self.environment_values(meta)
        env=(app or {}).get('pm2_env',{}); paths=[]
        if not meta.get('adopted'):
            paths=[self.state/'logs'/name/f'{stream}.log' for stream in (['stdout','stderr'] if kind=='both' else [kind])]
        else:
            for key in (['pm_out_log_path','pm_err_log_path'] if kind=='both' else ['pm_out_log_path' if kind=='stdout' else 'pm_err_log_path']):
                if env.get(key): paths.append(Path(env[key]))
        streams=[]
        try:
            from collections import deque
            for path in paths:
                if not path.exists(): continue
                if path.is_symlink() or path.stat().st_uid!=os.geteuid() or not path.is_file(): raise ValueError('Refusing an unowned or symlink log file')
                stream=path.open(errors='replace'); streams.append((path,stream))
                for line in deque(stream,maxlen=lines): print(model.redact(line,self.values),end='')
            if not streams: print('No application logs yet.')
            while follow and streams:
                for path,stream in streams:
                    if path.exists() and (path.stat().st_ino!=os.fstat(stream.fileno()).st_ino or path.stat().st_size<stream.tell()):
                        print('Log rotated; run logs again to follow the new file.'); return
                    for line in stream: print(model.redact(line,self.values),end='',flush=True)
                time.sleep(0.3)
        finally:
            for _,stream in streams: stream.close()

    def save(self):
        self.default_runtime(); apps=self.processes()
        if not apps: raise ValueError('No live process list to save; no PM2 daemon was started')
        print('PM2 save persists this user’s ENTIRE current process list, including unmanaged applications:')
        self.list_apps()
        for path in (self.state/'apps').glob('*.json'):
            meta=self.metadata(path.stem)
            app=self.app(path.stem)
            if app and app.get('pm2_env',{}).get('status')=='online':
                outcome=self.check_health(meta['profile'],lambda:self.app(path.stem))
                if not outcome['healthy']: raise ValueError(f'Cannot save while managed app {path.stem} is unhealthy')
            elif app and app.get('pm2_env',{}).get('status')=='stopped': print(f'{path.stem} is deliberately stopped; its stopped state will be saved.')
            elif app: raise ValueError(f'Managed app {path.stem} is unstable or failed; resolve its status before saving')
        print(f'Private reboot dump: {self.home}/dump.pm2. PM2 dumps may contain unmanaged environment secrets.')
        if self.dry_run: return
        if not self.confirm('Save this complete reviewed user process list?'): raise ValueError('Save declined')
        with self.lock():
            if [(a['name'],a['pm_id'],process.signature(a)) for a in self.processes()]!=[(a['name'],a['pm_id'],process.signature(a)) for a in apps]: raise ValueError('Process list changed after review; run save again')
            self.pm2(['save'])
            for name in ['dump.pm2','dump.pm2.bak']:
                path=self.home/name
                if path.exists() and not path.is_symlink(): os.chmod(path,0o600)
            print('Saved this PM2_HOME only.')

    def startup(self,install=False,replace=False):
        if os.geteuid()==0: raise ValueError('Startup integration requires the normal application owner, not root')
        self.default_runtime(); owner=pwd.getpwuid(os.geteuid())
        if not re.fullmatch(r'[a-z_][a-z0-9_-]*[$]?',owner.pw_name): raise ValueError('Unsupported service owner name')
        path=str(self.node.parent)+':'+os.environ.get('PATH','/usr/bin:/bin')
        unit='\n'.join(['# Managed by PM2 Deployment Manager','[Unit]','Description=PM2 process manager for '+owner.pw_name,'After=network.target','[Service]','Type=forking','User='+owner.pw_name,'UMask=0077','Environment='+unit_quote('HOME='+owner.pw_dir),'Environment='+unit_quote('PM2_HOME='+str(self.home)),'Environment='+unit_quote('PATH='+path),'PIDFile='+unit_quote(str(self.home/'pm2.pid')),'ExecStart='+unit_quote(self.node,command=True)+' '+unit_quote(self.pm2_bin,command=True)+' resurrect','ExecStop='+unit_quote(self.node,command=True)+' '+unit_quote(self.pm2_bin,command=True)+' kill','Restart=on-failure','TimeoutStartSec=60','TimeoutStopSec=30','[Install]','WantedBy=multi-user.target',''])
        print(unit)
        name='pm2-'+owner.pw_name+'.service'; existing=[]
        for directory in ['/etc/systemd/system','/usr/lib/systemd/system','/lib/systemd/system']:
            for candidate in Path(directory).glob('pm2*.service'):
                try:
                    text=candidate.read_text()
                    if candidate.name==name or re.search(r'^User='+re.escape(owner.pw_name)+r'\s*$',text,re.M) or str(self.home) in text:
                        if candidate.name not in existing: existing.append(candidate.name)
                except OSError: pass
        if existing: print('Existing PM2 services for this owner/home: '+', '.join(existing))
        if shutil.which('systemctl'):
            status=subprocess.run(['systemctl','show',name,'--property=ActiveState,UnitFileState,User','--no-pager'],text=True,capture_output=True,timeout=10)
            print(model.redact(status.stdout))
        print('Paths are pinned. Rerun startup --install --replace after a Node/PM2 path upgrade. Save the reviewed process list before enabling reboot startup.')
        print('The service controls this user’s whole PM2 daemon at boot/shutdown. Installation does not start, stop, or restart it now.')
        if not install or self.dry_run: return unit
        if not Path('/run/systemd/system').is_dir(): raise ValueError('Systemd is not running; startup installation is unavailable on this init system')
        if existing:
            target=Path('/etc/systemd/system')/name
            if existing!=[name] or not replace or not target.is_file() or not target.read_text().startswith('# Managed by PM2 Deployment Manager\n'):
                raise ValueError('Existing PM2 startup service preserved. Review it manually; only this manager’s own unit can be replaced with --replace')
        model.check_private(self.home,directory=True)
        if not (self.home/'dump.pm2').is_file(): raise ValueError('Run save after successful application health checks before installing startup')
        if not self.confirm('Install and enable this reviewed system-wide unit with sudo (no immediate restart)?'): raise ValueError('Startup installation declined')
        with self.lock():
            draft=self.state/'private'/name; model.atomic(draft,unit)
            subprocess.run(['sudo','install','-o','root','-g','root','-m','0644','--',str(draft),'/etc/systemd/system/'+name],check=True)
            subprocess.run(['sudo','systemctl','daemon-reload'],check=True)
            subprocess.run(['sudo','systemctl','enable',name],check=True)
        print('Startup enabled. Existing running applications were not restarted.')
        return unit

    def dependencies(self):
        node=process.executable(self.node_option,'node'); npm=process.executable('','npm')
        target=self.state/'tools'
        if (target/'node_modules/pm2/bin/pm2').is_file(): print('User-local PM2 already installed; no change.'); return
        print(f'Install PM2 7.0.4 and semver 7.8.5 under {target}; no global package installation or sudo. Node: {node}')
        if self.dry_run: return
        if not self.confirm('Download and install these user-local dependencies from npm?'): raise ValueError('Dependency installation declined')
        with self.lock():
            env=process.safe_env({'PATH':str(node.parent)+':'+os.environ.get('PATH','/usr/bin:/bin')})
            self.run_step([npm,'install','--prefix',str(target),'--ignore-scripts','--no-audit','--no-fund','pm2@7.0.4','semver@7.8.5'],self.state,env,self.state/'logs/dependencies.log')

    def logrotate(self):
        self.default_runtime()
        if any(a.get('name')=='pm2-logrotate' for a in self.processes()): print('pm2-logrotate is already present; existing configuration preserved.'); return
        if not process.daemon_live(self.home): raise ValueError('Deploy/start an application before installing this optional PM2 module')
        print('Install optional pm2-logrotate in this PM2_HOME. This affects this user’s PM2 logs, including other apps. The module starts immediately with its upstream defaults.')
        if self.dry_run: return
        if not self.confirm('Download and install pm2-logrotate for this PM2 user?'): raise ValueError('Log rotation installation declined')
        with self.lock(): self.pm2(['install','pm2-logrotate'])
