#!/usr/bin/env python3
"""The menu and command line share these validated operations."""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys
import model
from engine import Manager


def parser():
    root=argparse.ArgumentParser(description='User-owned PM2 releases and process management. Run without arguments for the menu.',epilog='Shared flags (before or after command): --state-dir PATH, --pm2-home PATH, --node PATH, --pm2 PATH, --yes, --dry-run, --allow-root. Only startup --install uses sudo.')
    sub=root.add_subparsers(dest='action',required=True)
    for action in ['deploy','update','adopt','profile-template']:
        cmd=sub.add_parser(action)
        if action=='update': cmd.add_argument('app_name',nargs='?')
        cmd.add_argument('--profile'); cmd.add_argument('--name'); cmd.add_argument('--path')
        cmd.add_argument('--framework',choices=sorted(model.FRAMEWORKS)); cmd.add_argument('--mode',choices=['standard','standalone'])
        cmd.add_argument('--package-manager',choices=['auto','npm','pnpm','yarn','bun'])
        cmd.add_argument('--package-path'); cmd.add_argument('--install',choices=['lockfile','existing','skip'])
        build=cmd.add_mutually_exclusive_group(); build.add_argument('--build',dest='build',action='store_true',default=None); build.add_argument('--no-build',dest='build',action='store_false')
        cmd.add_argument('--build-script'); cmd.add_argument('--start-script'); cmd.add_argument('--entry')
        cmd.add_argument('--command-json',help='JSON argv array; never evaluated by a shell')
        cmd.add_argument('--host'); cmd.add_argument('--port',type=int); cmd.add_argument('--env-file',action='append')
        cmd.add_argument('--strategy',choices=['release','in-place']); cmd.add_argument('--health-path')
        cmd.add_argument('--accepted-status',help='Comma-separated HTTP codes'); cmd.add_argument('--health-retries',type=int)
        cmd.add_argument('--health-interval',type=int); cmd.add_argument('--health-timeout',type=int)
        cmd.add_argument('--memory'); cmd.add_argument('--kill-timeout',type=int)
        cmd.add_argument('--git-pull',action='store_true',default=None); cmd.add_argument('--git-branch'); cmd.add_argument('--git-remote')
        cmd.add_argument('--vite-ack',action='store_true',default=None)
        cmd.add_argument('--save',action='store_true'); cmd.add_argument('--startup',action='store_true',help='Print startup preview after success; installation is separate')
    for action in ['start','stop','restart','reload','remove','health','status','monitor','backup','env-keys','env-apply','export','releases']:
        cmd=sub.add_parser(action); cmd.add_argument('--name'); cmd.add_argument('app_name',nargs='?')
        if action=='env-apply': cmd.add_argument('--env-file',action='append'); cmd.add_argument('--no-build',action='store_true')
    cmd=sub.add_parser('logs'); cmd.add_argument('--name'); cmd.add_argument('app_name',nargs='?'); cmd.add_argument('--lines',type=int,default=50); cmd.add_argument('--follow',action='store_true'); cmd.add_argument('--kind',choices=['both','stdout','stderr'],default='both')
    cmd=sub.add_parser('env-create'); cmd.add_argument('--name',required=True)
    cmd=sub.add_parser('startup'); cmd.add_argument('--install',action='store_true'); cmd.add_argument('--replace',action='store_true')
    for action in ['restore','recover','profile-save']:
        cmd=sub.add_parser(action); cmd.add_argument('--file',required=True)
    cmd=sub.add_parser('inspect'); cmd.add_argument('--path',required=True)
    for action in ['list','profiles','save','dependencies','doctor','logrotate']: sub.add_parser(action)
    return root


def doctor(manager):
    release={}
    try:
        for line in Path('/etc/os-release').read_text().splitlines():
            if '=' in line:
                key,value=line.split('=',1)
                if key in {'ID','ID_LIKE','PRETTY_NAME'}: release[key]=value.strip('"\'')
    except OSError: pass
    binaries={name:shutil.which(name) for name in ['bash','python3','node','npm','pnpm','yarn','bun','pm2','git','systemctl','ss']}
    print(json.dumps(dict(os=release,kernel=platform.system(),uid=os.geteuid(),state=str(manager.state),pm2_home=str(manager.home),binaries=binaries,user_local_pm2=(manager.state/'tools/node_modules/pm2/bin/pm2').is_file(),startup_available=Path('/run/systemd/system').is_dir()),indent=2))
    print('No packages installed or services changed. Linux /proc and Python 3.9+ are required; startup installation additionally requires systemd.')


def profile_from(args,manager):
    if args.profile: p=model.load_profile(args.profile)
    elif args.action=='update' and args.name: p=manager.metadata(args.name)['profile'].copy()
    else: p={}
    for key in ['name','path',*model.DEFAULTS]:
        value=getattr(args,key,None)
        if value is not None: p[key]=value
    if args.env_file is not None: p['env_files']=args.env_file
    if args.command_json is not None: p['command']=json.loads(args.command_json)
    if args.accepted_status is not None: p['accepted_status']=[int(x) for x in args.accepted_status.split(',')]
    return model.validate(p)


def main(argv=None):
    common=argparse.ArgumentParser(add_help=False)
    common.add_argument('--state-dir',default=os.environ.get('PM2_MANAGER_STATE',str(Path.home()/'.local/state/pm2-deployment-manager')))
    common.add_argument('--pm2-home',default=os.environ.get('PM2_HOME',str(Path.home()/'.pm2')))
    common.add_argument('--node',default=''); common.add_argument('--pm2',default='')
    common.add_argument('--yes',action='store_true'); common.add_argument('--dry-run',action='store_true'); common.add_argument('--allow-root',action='store_true')
    options,remaining=common.parse_known_args(argv)
    args=parser().parse_args(remaining)
    manager=Manager(options.state_dir,options.pm2_home,options.yes,options.dry_run,options.allow_root,options.node,options.pm2)
    action=args.action
    if hasattr(args,'app_name'):
        if getattr(args,'name',None) and args.app_name and args.name!=args.app_name: raise ValueError('Conflicting application names')
        args.name=getattr(args,'name',None) or args.app_name
        if not args.name and not getattr(args,'profile',None): raise ValueError('Supply --name or an application name')
    if platform.system()!='Linux': raise ValueError('Linux is required for PID-owned listener checks')
    if action=='doctor': return doctor(manager)
    if action=='inspect': return print(json.dumps(model.inspect_project(args.path),indent=2))
    if action in {'deploy','update','adopt','profile-template'}:
        p=profile_from(args,manager)
        if action=='profile-template': return print(json.dumps(p,indent=2))
        if action=='adopt': return manager.adopt(p)
        result=manager.deploy(p,update=action=='update')
        if result and args.save: manager.save()
        if result and args.startup: manager.startup()
        return
    if action in {'start','stop','restart','reload','remove','health','status','monitor'}: return manager.action(action,args.name)
    if action=='list': return manager.list_apps()
    if action=='logs':
        if not 1<=args.lines<=10000: raise ValueError('Log line count must be 1–10000')
        return manager.logs(args.name,args.lines,args.follow,args.kind)
    if action=='env-create': return manager.create_env(args.name)
    if action=='env-keys': return manager.env_keys(args.name)
    if action=='env-apply':
        p=manager.metadata(args.name)['profile'].copy()
        if args.env_file: p['env_files']=args.env_file
        if args.no_build:
            if any(k.startswith('NEXT_PUBLIC_') for k in model.read_env(p['env_files'])): raise ValueError('Public browser variables require a rebuild; omit --no-build')
            p['build']=False
        return manager.deploy(p,update=True)
    if action=='profiles': return manager.profiles()
    if action=='profile-save': return manager.profile_save(args.file)
    if action=='backup': return manager.backup(args.name)
    if action=='restore': return manager.restore(args.file)
    if action=='recover': return manager.recover(args.file)
    if action=='startup': return manager.startup(args.install,args.replace)
    if action=='export': return manager.export(args.name)
    if action=='releases': return manager.releases(args.name)
    if action=='save': return manager.save()
    if action=='dependencies': return manager.dependencies()
    if action=='logrotate': return manager.logrotate()
    raise ValueError('Unsupported operation')


if __name__=='__main__':
    signal.signal(signal.SIGTERM,lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    try: main()
    except KeyboardInterrupt: print('\nInterrupted. Applications continue when leaving logs/monitoring; interrupted swaps attempt guarded recovery.',file=sys.stderr); sys.exit(130)
    except (ValueError,OSError,subprocess.SubprocessError,KeyError,TypeError) as error:
        print('Error: '+model.redact(str(error)),file=sys.stderr); sys.exit(1)
