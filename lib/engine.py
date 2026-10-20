#!/usr/bin/env python3
"""Release transactions and narrowly scoped PM2 operations for one deployment user."""
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pwd
import shutil
import signal
import subprocess
import time
import uuid
import model
import process
from maintenance import Maintenance


class Manager(Maintenance):
    def __init__(self,state,pm2_home,yes=False,dry_run=False,allow_root=False,node='',pm2=''):
        self.state=Path(state).expanduser().absolute(); self.home=Path(pm2_home).expanduser().absolute()
        if not model.path_value(str(self.state)) or not model.path_value(str(self.home)): raise ValueError('State and PM2_HOME must be absolute paths')
        self.yes=yes; self.dry_run=dry_run; self.allow_root=allow_root
        self.node_option=node; self.pm2_option=pm2
        self.node=None; self.pm2_bin=None; self.manager_bin=None; self.runtime_path=None
        self.values={}

    def confirm(self,message):
        if self.dry_run: return False
        if self.yes: return True
        try: answer=input(message+' [y/N]: ')
        except EOFError: return False
        return answer.lower() in {'y','yes'}

    def ensure_state(self):
        if os.geteuid()==0 and not self.allow_root: raise ValueError('Run as the application owner, not root. Root requires an explicit --allow-root opt-in; startup always requires a non-root owner.')
        model.check_private(self.state,directory=True)
        self.state.mkdir(parents=True,exist_ok=True,mode=0o700)
        for directory in ['apps','profiles','drafts','releases','logs','backups','journals','env','private']:
            path=self.state/directory; model.check_private(path,directory=True); path.mkdir(mode=0o700,exist_ok=True)

    @contextlib.contextmanager
    def lock(self):
        self.ensure_state()
        path=self.state/'lock'
        if path.is_symlink(): raise ValueError('Refusing symlink lock')
        with path.open('a') as lock:
            os.chmod(path,0o600)
            try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError as exc: raise ValueError('Another deployment manager is changing this state') from exc
            yield

    def runtime(self,p):
        p={**p,'node_path':self.node_option or p['node_path'],'pm2_path':self.pm2_option or p['pm2_path']}
        return process.runtimes(p,self.state)

    def activate_runtime(self,p):
        self.node,self.pm2_bin,self.manager_bin,self.runtime_path=self.runtime(p)

    def default_runtime(self):
        if self.node and self.pm2_bin: return
        self.node=process.executable(self.node_option,'node')
        candidate=self.pm2_option or shutil.which('pm2') or str(self.state/'tools/node_modules/pm2/bin/pm2')
        if not Path(candidate).is_file(): raise ValueError('PM2 is not installed; use dependencies to install a user-local PM2')
        self.pm2_bin=Path(candidate).resolve()

    def processes(self):
        if not process.daemon_live(self.home): return []
        self.default_runtime()
        return process.pm2_cli(self.node,self.pm2_bin,self.home,['jlist'])

    def pm2(self,args,allow_start=False,values=None):
        self.default_runtime()
        if allow_start:
            if self.home.is_symlink(): raise ValueError('PM2_HOME cannot be a symlink')
            self.home.mkdir(parents=True,exist_ok=True,mode=0o700)
            if self.home.stat().st_uid!=os.geteuid(): raise ValueError('PM2_HOME belongs to another user')
            if self.home.stat().st_mode & 0o077:
                raise ValueError('Protect the existing PM2_HOME with chmod 700 before mutation; the manager will not change its permissions silently')
        model.check_private(self.home,directory=True)
        return process.pm2_cli(self.node,self.pm2_bin,self.home,args,values=values or self.values,allow_start=allow_start)

    def app(self,name):
        found=[a for a in self.processes() if a.get('name')==name]
        if len(found)>1: raise ValueError('Duplicate PM2 process names require manual resolution')
        return found[0] if found else None

    def metadata(self,name,verify=True):
        if not model.name_valid(name): raise ValueError('Invalid managed app name')
        path=self.state/'apps'/f'{name}.json'
        if not path.is_file(): raise ValueError('Application is not manager-owned; use the explicit adoption workflow')
        model.check_private(path)
        data=json.loads(path.read_text())
        if data.get('name')!=name or data.get('pm2_home')!=str(self.home): raise ValueError('Application state belongs to another name or PM2_HOME')
        if verify:
            config=Path(data['ecosystem'])
            if not config.resolve().is_relative_to(self.state.resolve()) or model.sha(config)!=data['ecosystem_sha']: raise ValueError('Managed ecosystem was edited or is outside this state directory')
            app=self.app(name)
            if app and not process.matches(app,data): raise ValueError('PM2 definition was changed outside this manager; refusing to modify it')
        return data

    def owned(self,name):
        meta=self.metadata(name)
        app=self.app(name)
        if app and not process.matches(app,meta): raise ValueError('Unowned process collision')
        return meta,app

    def check_health(self,p,getter): return process.health(p,getter)

    def _port_guard(self,p,old_app=None):
        target=p['host']; address=__import__('ipaddress').ip_address
        for path in (self.state/'apps').glob('*.json'):
            other=json.loads(path.read_text())
            if other.get('name')==p['name']: continue
            op=other['profile']
            if op['port']==p['port'] and (op['host']==target or address(op['host']).is_unspecified or address(target).is_unspecified):
                raise ValueError(f'Port {p["port"]} is reserved by another managed app: {other["name"]}')
        allowed=old_app.get('pid') if old_app else None
        if not process.port_available(target,p['port'],allowed): raise ValueError(f'Port {p["port"]} cannot be bound or belongs to another process; inspect ss -ltnp. No process was killed.')

    def preview(self,p,old,digest):
        print('\n========== PM2 DEPLOYMENT SUMMARY ==========')
        for key,value in [('Name',p['name']),('Owner',pwd.getpwuid(os.geteuid()).pw_name),('Source',p['path']),('Framework',p['framework']),('Mode',p['mode']),('Bind',f'{p["host"]}:{p["port"]}'),('Strategy',p['strategy']),('Package manager',p['package_manager']),('Dependencies',p['install']),('Build',p['build']),('Execution','fork / one instance'),('Node',str(self.node)),('PM2 executable',str(self.pm2_bin)),('PM2 home',str(self.home)),('Health path',p['health_path']),('Accepted HTTP statuses',p['accepted_status']),('Environment keys',', '.join(sorted(self.values)) or '(none)'),('Previous release',old.get('release','unmanaged adoption') if old else '(none)'),('Source digest',digest[:12])]: print(f'{key}: {value}')
        if p['host'] in {'0.0.0.0','::'}: print('Public bind: requests can reach the application directly if firewall rules permit. Prefer loopback behind Nginx.')
        print('Release changes: private staged source/build, environment snapshot, ecosystem, profile and ownership metadata.')
        print('Only this named process is replaced. Fork deployment has a restart gap. Existing releases are retained.')

    def run_step(self,args,cwd,env,log):
        log=Path(log); log.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        fd=os.open(log,os.O_WRONLY|os.O_CREAT|os.O_APPEND|os.O_NOFOLLOW,0o600)
        child=None
        try:
            with os.fdopen(fd,'a') as output:
                child=subprocess.Popen([str(a) for a in args],cwd=cwd,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,errors='replace',start_new_session=True)
                for line in child.stdout:
                    clean=model.redact(line,self.values)
                    output.write(clean); output.flush(); print(clean,end='',flush=True)
                code=child.wait()
                if code: raise ValueError(f'Command failed (exit {code}); redacted log: {log}')
        except BaseException:
            if child and child.poll() is None:
                os.killpg(child.pid,signal.SIGTERM)
                try: child.wait(timeout=5)
                except subprocess.TimeoutExpired: os.killpg(child.pid,signal.SIGKILL); child.wait()
            raise
        return 0

    def _git(self,p):
        root=Path(p['path'])
        if not p['git_pull']: return
        for app in self.processes():
            if process.uses_source(app,root):
                raise ValueError('Git updates would modify source used by a running PM2 app; use a separate checkout/release source')
        def git(*args):
            result=subprocess.run(['git','-C',str(root),*args],env=process.safe_env(),text=True,capture_output=True,timeout=90)
            if result.returncode: raise ValueError('Git operation failed; raw remote output suppressed to protect credentials')
            return result.stdout.strip()
        if git('status','--porcelain'): raise ValueError('Git source has uncommitted changes; no stash/reset/discard will run')
        branch=git('branch','--show-current')
        if not branch: raise ValueError('Detached Git HEAD requires a separately selected source checkout')
        if p['git_branch'] and p['git_branch']!=branch: raise ValueError('Requested Git branch differs from the current branch; switch it explicitly after reviewing your working tree')
        print(f'Git: branch {branch}, current revision {git("rev-parse","--short","HEAD")}')
        git('fetch',p['git_remote'],branch)
        git('pull','--ff-only',p['git_remote'],branch)

    def _stage(self,p,release):
        root=Path(p['path']); release=Path(release)
        if p['strategy']=='in-place':
            for app in self.processes():
                if process.uses_source(app,root) and (p['build'] or p['install']=='lockfile' or p['git_pull']):
                    raise ValueError('In-place install/build/Git update would overwrite a running app; use release strategy')
            work=root
        else:
            work=release/'source'
            model.copy_release(root,work,include_dependencies=p['install']=='existing',include_artifacts=not p['build'])
        build_env=process.safe_env({**self.values,'PATH':self.runtime_path,'NODE_ENV':'production','PORT':p['port'],'HOSTNAME':p['host'],'HOST':p['host']})
        log=release/'build.log'
        process.check_engines(p,work,self.node,self.pm2_bin,self.manager_bin,self.runtime_path)
        if p['install']=='existing' and not (work/'node_modules').is_dir(): raise ValueError('Existing dependency mode requires node_modules')
        if p['install']=='lockfile':
            process.check_manager(p,work,self.manager_bin,build_env)
            manager=p['package_manager']
            required={'npm':['package-lock.json','npm-shrinkwrap.json'],'pnpm':['pnpm-lock.yaml'],'yarn':['yarn.lock'],'bun':['bun.lock','bun.lockb']}[manager]
            if not any((work/x).is_file() for x in required): raise ValueError('Reproducible dependency installation requires the selected package manager lockfile')
            if manager=='npm': args=[self.manager_bin,'ci']
            elif manager=='pnpm': args=[self.manager_bin,'install','--frozen-lockfile']
            elif manager=='bun': args=[self.manager_bin,'install','--frozen-lockfile']
            else:
                version=subprocess.run([str(self.manager_bin),'--version'],env=build_env,text=True,capture_output=True,timeout=30)
                if version.returncode: raise ValueError('Cannot determine Yarn version')
                args=[self.manager_bin,'install','--immutable' if int(version.stdout.strip().split('.')[0])>=2 else '--frozen-lockfile']
            print('Installing dependencies from lockfile...')
            self.run_step(args,work,{**build_env,'NODE_ENV':'development'},log)
        process.check_engines(p,work,self.node,self.pm2_bin,self.manager_bin,self.runtime_path)
        if p['build']:
            print('Building staged production release...')
            self.run_step([self.manager_bin,'run',p['build_script']],work,build_env,log)
        command,cwd=process.launch_command(p,work,self.node,self.manager_bin)
        if p['framework']=='nestjs' and not p['entry'] and not (work/'dist').is_dir(): raise ValueError('NestJS build is missing dist; select the correct build/entry')
        return work,command,cwd

    def _restore_options(self,app):
        env=app.get('pm2_env',{})
        keys={'exec_mode','instances','max_memory_restart','kill_timeout','restart_delay','autorestart','min_uptime','max_restarts','watch','env','node_args','interpreter_args','out_file','error_file','merge_logs','wait_ready','listen_timeout'}
        result={k:env[k] for k in keys if k in env}
        result.update(name=app['name'],script=env['pm_exec_path'],cwd=env['pm_cwd'],args=env.get('args',[]),interpreter=env.get('exec_interpreter',str(self.node)))
        relative=os.path.relpath(result['script'],result['cwd'])
        if ' ' in relative: raise ValueError('PM2 interprets script paths containing spaces as shell commands; move this unmanaged entry before adoption/update')
        result['script']=relative
        result['exec_mode']='cluster' if env.get('exec_mode')=='cluster_mode' else 'fork'
        result['instances']=1
        result['autostart']=env.get('status') not in {'stopped','errored'}
        return result

    def _state_snapshot(self,name):
        result={}
        for category in ['apps','profiles']:
            path=self.state/category/f'{name}.json'
            if path.is_file(): result[str(path)]=path.read_text()
            else: result[str(path)]=None
        return result

    def _publish(self,new,prior_snapshot):
        name=new['name']
        for path,old in prior_snapshot.items():
            current=Path(path).read_text() if Path(path).is_file() else None
            if current!=old: raise ValueError('Managed state changed during deployment; refusing to overwrite it')
        model.json_write(self.state/'profiles'/f'{name}.json',new['profile'])
        model.json_write(self.state/'apps'/f'{name}.json',new)

    def _rollback(self,journal,path):
        name=journal['name']; new=journal.get('new'); previous=journal.get('previous')
        current=self.app(name)
        if current and new and process.matches(current,new):
            self.pm2(['delete',str(current['pm_id'])]); current=None
        elif current and previous and process.matches(current,previous):
            pass
        elif current:
            raise ValueError('Concurrent PM2 change: recovery refuses to replace an unowned process')
        if previous and not current and journal.get('previous_options'):
            restore=Path(path).with_suffix('.restore.json')
            model.json_write(restore,{'apps':[journal['previous_options']]})
            self.pm2(['start',str(restore),'--only',name],allow_start=True)
            current=self.app(name)
            if not process.matches(current,previous): raise ValueError('Prior process definition could not be restored; use the private journal for recovery')
        for file,old in journal['state_before'].items():
            target=Path(file)
            if target.is_file():
                content=target.read_text()
                allowed={old, json.dumps(new['profile'],indent=2)+'\n' if file.endswith('/profiles/'+name+'.json') and new else json.dumps(new,indent=2)+'\n' if new else None}
                if content not in allowed: raise ValueError('Concurrent state-file edit; recovery refuses to overwrite it')
            if old is None: target.unlink(missing_ok=True)
            else: model.atomic(target,old)
        journal['phase']='rolled-back'; model.json_write(path,journal)
        if previous and journal.get('previous_options') and journal['previous_options'].get('autostart',True):
            outcome=self.check_health(previous['profile'],lambda:self.app(name))
            if not outcome['healthy']: print('Prior definition restored, but its health needs operator attention.')

    def _swap(self,new,old,old_app,prepared_journal=None):
        name=new['name']; path=prepared_journal or self.state/'journals'/f'{name}-{uuid.uuid4().hex}.json'
        journal=dict(version=1,name=name,pm2_home=str(self.home),phase='prepared',previous=old,new=new,
                     previous_options=self._restore_options(old_app) if old_app else None,state_before=self._state_snapshot(name))
        model.json_write(path,journal)
        try:
            current=self.app(name)
            if old_app and (not current or not process.matches(current,old)): raise ValueError('Previous process changed during staging')
            if current and not old_app: raise ValueError('Another process claimed this name during staging')
            self._port_guard(new['profile'],current)
            journal['phase']='swapping'; model.json_write(path,journal)
            if current:
                self.pm2(['delete',str(current['pm_id'])])
            self.pm2(['start',new['ecosystem'],'--only',name],allow_start=True)
            journal['phase']='started'; model.json_write(path,journal)
            current=self.app(name)
            if not process.matches(current,new): raise ValueError('Started process does not match the generated managed definition')
            result=self.check_health(new['profile'],lambda:self.app(name))
            if not result['healthy']: raise ValueError('New release failed health: '+result.get('reason','unknown reason'))
            self._publish(new,journal['state_before'])
            journal['phase']='committed'; model.json_write(path,journal)
            print(f'Healthy deployment: {name}, PID {result["pid"]}, HTTP {result["http_status"]}, port {result["port"]}')
            target='127.0.0.1' if new['profile']['host']=='0.0.0.0' else new['profile']['host']
            print(f'Nginx proxy target: http://{"["+target+"]" if ":" in target else target}:{new["profile"]["port"]}')
            print('Reboot persistence is separate: run save/startup after reviewing this user’s complete process list.')
            return new
        except BaseException:
            try: self._rollback(journal,path)
            except BaseException as error:
                journal['phase']='recovery-required'; model.json_write(path,journal)
                print(f'Automatic recovery incomplete: {model.redact(str(error),self.values)}. Private journal: {path}')
            raise

    def deploy(self,raw,update=False):
        p=model.resolve_project(raw); name=p['name']; self.values=model.read_env(p['env_files'])
        self.activate_runtime(p)
        p.update(node_path=str(self.node),pm2_path=str(self.pm2_bin),package_path=str(self.manager_bin))
        old=self.metadata(name) if (self.state/'apps'/f'{name}.json').exists() else None
        app=self.app(name)
        if app and not old: raise ValueError('A PM2 process already uses this name; inspect or explicitly adopt it')
        if old and p['framework']=='nextjs' and not p['build']:
            previous_values=self.environment_values(old)
            public=lambda values:{k:v for k,v in values.items() if k.startswith('NEXT_PUBLIC_')}
            if public(previous_values)!=public(self.values): raise ValueError('NEXT_PUBLIC_ changes require a production rebuild; enable build before updating')
        if old and not update:
            digest=model.source_digest(p['path'])
            fingerprint=hashlib.sha256(json.dumps(p,sort_keys=True).encode()+digest.encode()+json.dumps(self.values,sort_keys=True).encode()).hexdigest()
            if old.get('fingerprint')==fingerprint and app and app.get('pm2_env',{}).get('status')=='online':
                outcome=self.check_health(p,lambda:self.app(name))
                if outcome['healthy']: print('Already deployed and healthy; no changes.'); return old
            raise ValueError('This name is already managed; use update to change its deployment')
        if update and not old: raise ValueError('Cannot update an unmanaged application; deploy or adopt first')
        self._port_guard(p,app)
        digest=model.source_digest(p['path'])
        self.preview(p,old,digest)
        if self.dry_run: print('Dry-run: no files, package commands, PM2 daemon or processes changed.'); return None
        if not self.confirm('Deploy this reviewed application?'): raise ValueError('Deployment declined')
        with self.lock():
            if old:
                current=self.metadata(name)
                if current!=old: raise ValueError('Managed metadata changed after the preview')
            elif (self.state/'apps'/f'{name}.json').exists(): raise ValueError('Another manager claimed this name')
            self._git(p)
            digest=model.source_digest(p['path'])
            fingerprint=hashlib.sha256(json.dumps(p,sort_keys=True).encode()+digest.encode()+json.dumps(self.values,sort_keys=True).encode()).hexdigest()
            release=self.state/'releases'/name/(time.strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:10])
            release.mkdir(parents=True,mode=0o700)
            model.json_write(release/'environment.json',self.values)
            work,command,cwd=self._stage(p,release)
            nonce=uuid.uuid4().hex
            launcher=release/'launcher.cjs'; model.atomic(launcher,(process.LIB/'launcher.cjs').read_bytes())
            launch=release/'launch.json'
            model.json_write(launch,dict(command=command,cwd=str(cwd),env_file=str(release/'environment.json'),path=self.runtime_path,port=p['port'],host=p['host'],kill_timeout=p['kill_timeout'],memory_bytes=int(p['memory'][:-1])*1024**('MKGT'.index(p['memory'][-1])+1)))
            logs=self.state/'logs'/name; logs.mkdir(mode=0o700,parents=True,exist_ok=True)
            eco=release/'ecosystem.config.cjs'
            model.atomic(eco,'module.exports = '+json.dumps(process.ecosystem(p,release,self.node,launcher,launch,nonce,logs),indent=2)+';\n')
            subprocess.run([str(self.node),'--check',str(eco)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            new=dict(version=1,name=name,profile=p,pm2_home=str(self.home),release=str(release),cwd=str(release),script=str(launcher),nonce=nonce,
                     ecosystem=str(eco),ecosystem_sha=model.sha(eco),interpreter=str(self.node),args=[str(launch)],fingerprint=fingerprint,source_digest=digest,adopted=False)
            model.json_write(release/'release.json',new)
            return self._swap(new,old,app)

    def action(self,action,name):
        meta,app=self.owned(name); self.activate_runtime(meta['profile']); self.values=self.environment_values(meta)
        if action=='health':
            result=self.check_health(meta['profile'],lambda:self.app(name)); print(json.dumps(result,indent=2))
            if not result['healthy']: raise ValueError(result.get('reason','Application unhealthy'))
            return result
        if action in {'status','monitor'}:
            env=(app or {}).get('pm2_env',{}); monit=(app or {}).get('monit',{})
            data=dict(name=name,status=env.get('status','absent'),pid=(app or {}).get('pid',0),port=meta['profile']['port'],cpu=monit.get('cpu'),memory_bytes=monit.get('memory'),restarts=env.get('restart_time',0),uptime_ms=max(0,int(time.time()*1000)-env.get('pm_uptime',int(time.time()*1000))))
            if app and app.get('pid'): data['application_tree']=process.tree_usage(app['pid'])
            print(json.dumps(data,indent=2)); return data
        if action=='reload':
            print('Fork-mode application: using a controlled restart; this is not a zero-downtime cluster reload.')
            action='restart'
        if action not in {'start','stop','restart','remove'}: raise ValueError('Unknown process action')
        print(f'{action}: only managed application {name}; PM2 ID {app.get("pm_id") if app else "absent"}. Logs, releases, environment files and certificates are retained.')
        if self.dry_run: return
        if not self.confirm(f'Confirm {action} for {name}?'): raise ValueError('Operation declined')
        with self.lock():
            meta,app=self.owned(name)
            if action=='remove':
                if app: self.pm2(['delete',str(app['pm_id'])])
                (self.state/'apps'/f'{name}.json').unlink(missing_ok=True)
                (self.state/'profiles'/f'{name}.json').unlink(missing_ok=True)
                print('Managed process/profile removed. Retained release/log/private recovery files can be reviewed separately. PM2 save is required to update reboot state.')
            elif action=='stop':
                if app: self.pm2(['stop',str(app['pm_id'])])
                else: print('Already absent; no process changed.')
            else:
                if app: self.pm2(['restart',str(app['pm_id']),'--update-env'])
                elif meta.get('adopted'): raise ValueError('An absent adopted app must be redeployed; the manager does not reconstruct its external secret environment')
                else: self.pm2(['start',meta['ecosystem'],'--only',name],allow_start=True)
                result=self.check_health(meta['profile'],lambda:self.app(name))
                if not result['healthy']: raise ValueError('Process operation completed but health failed; inspect redacted logs')

    def environment_values(self,meta):
        if meta.get('adopted'):
            app=self.app(meta['name']) or {}
            env=app.get('pm2_env',{}).get('env',{})
            known={k:v for k,v in env.items() if isinstance(v,str)}
            return {**known,**model.read_env(meta['profile']['env_files'])}
        path=Path(meta['release'])/'environment.json'; model.check_private(path)
        return json.loads(path.read_text())

    def list_apps(self):
        apps=self.processes(); owned={p.stem for p in (self.state/'apps').glob('*.json')}
        rows=[]
        for app in apps:
            row=dict(name=app.get('name'),id=app.get('pm_id'),pid=app.get('pid'),status=app.get('pm2_env',{}).get('status'),managed=app.get('name') in owned)
            rows.append(row)
        for name in sorted(owned-{r['name'] for r in rows}): rows.append(dict(name=name,status='absent',managed=True))
        print(json.dumps(rows,indent=2)); return rows

    def backup(self,name):
        meta,_=self.owned(name)
        print(f'Backup nonsecret profile, process metadata and active release reference for {name}; environment snapshots, logs and PM2 dumps are excluded.')
        if self.dry_run: return None
        if not self.confirm('Create this private metadata backup?'): raise ValueError('Backup declined')
        with self.lock():
            path=self.state/'backups'/f'{name}-{uuid.uuid4().hex}.json'
            model.json_write(path,dict(version=1,name=name,pm2_home=str(self.home),metadata=meta))
            print(f'Backup: {path}'); return str(path)

    def restore(self,path):
        data=json.loads(Path(path).read_text()); new=data.get('metadata',{})
        if data.get('version')!=1 or not model.name_valid(data.get('name')) or data.get('pm2_home')!=str(self.home): raise ValueError('Backup does not match this user/PM2_HOME')
        name=data['name']; old,app=self.owned(name)
        if new.get('adopted'): raise ValueError('Adopted external definitions are not retained releases; create a managed update before release restore')
        release=Path(new.get('release','/'))
        if new.get('name')!=name or not release.resolve().is_relative_to((self.state/'releases'/name).resolve()): raise ValueError('Restore release is outside managed application releases')
        if Path(new['ecosystem']).resolve()!=release.resolve()/'ecosystem.config.cjs': raise ValueError('Restored ecosystem must belong to the selected release')
        if json.loads((release/'release.json').read_text())!=new: raise ValueError('Backup differs from the retained release metadata')
        if model.sha(new['ecosystem'])!=new['ecosystem_sha']: raise ValueError('Restored ecosystem is missing or modified')
        self.activate_runtime(new['profile']); self.values=self.environment_values(new)
        print(f'Restore {name} to retained release {release}; source, databases, uploads and external changes are not rolled back.')
        if self.dry_run: return
        if not self.confirm('Activate this release and verify health?'): raise ValueError('Restore declined')
        with self.lock(): return self._swap(new,old,app)

    def recover(self,path):
        path=Path(path)
        if not path.resolve().is_relative_to((self.state/'journals').resolve()) or path.is_symlink(): raise ValueError('Select a private journal from this state directory')
        model.check_private(path); journal=json.loads(path.read_text())
        if journal.get('version')!=1 or journal.get('pm2_home')!=str(self.home) or not model.name_valid(journal.get('name')): raise ValueError('Invalid recovery journal')
        if journal.get('phase') in {'committed','rolled-back'}: print('Journal is already finalized; use a backup to select a different release.'); return
        expected={str(self.state/k/f'{journal["name"]}.json') for k in ['apps','profiles']}
        if set(journal.get('state_before',{}))!=expected: raise ValueError('Recovery journal contains unexpected state paths')
        for candidate in [journal.get('new'),journal.get('previous')]:
            if candidate and (candidate.get('name')!=journal['name'] or candidate.get('pm2_home')!=str(self.home)): raise ValueError('Recovery identity mismatch')
        p=(journal.get('new') or journal.get('previous'))['profile']; self.activate_runtime(p)
        print(f'Recover only {journal["name"]}, phase {journal.get("phase")}.')
        if self.dry_run: return
        if not self.confirm('Recover this interrupted process swap?'): raise ValueError('Recovery declined')
        with self.lock(): self._rollback(journal,path)
