#!/usr/bin/env python3
"""Validated deployment data and private filesystem/environment helpers."""
import base64
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import urllib.parse

DEFAULTS=dict(framework='auto',mode='standard',package_manager='auto',install='lockfile',build=True,
              build_script='build',start_script='start',entry='',command=[],host='127.0.0.1',port=3000,
              env_files=[],strategy='release',health_path='/',accepted_status=[200,301,302,307,308],
              health_retries=15,health_interval=1,health_timeout=3,memory='512M',kill_timeout=8000,
              restart_delay=1500,max_restarts=10,instances=1,exec_mode='fork',node_path='',pm2_path='',
              package_path='',git_pull=False,git_branch='',git_remote='origin',vite_ack=False)
FRAMEWORKS={'auto','nextjs','express','nestjs','vite','node','custom'}
RESERVED={'all','pm2','pm2-logrotate','none','null','undefined'}


def name_valid(value):
    return isinstance(value,str) and bool(re.fullmatch(r'[a-z][a-z0-9_-]{0,63}',value)) and value not in RESERVED


def path_value(value,empty=False):
    return isinstance(value,str) and ((empty and not value) or (value.startswith('/') and '..' not in Path(value).parts and not any(ord(c)<32 or c=='\x7f' for c in value)))


def validate(raw):
    if not isinstance(raw,dict) or set(raw)-({'name','path'}|set(DEFAULTS)):
        raise ValueError('Profiles contain only known nonsecret settings; credentials belong in environment files')
    p={**DEFAULTS,**raw}
    if not name_valid(p.get('name')): raise ValueError('Use a lowercase app name; reserved PM2 names and metacharacters are forbidden')
    if not path_value(p.get('path')) or not Path(p['path']).is_dir(): raise ValueError('Application path must be an existing absolute directory')
    source=Path(p['path']).resolve()
    if source.stat().st_uid != os.geteuid(): raise ValueError('Application directory must belong to the deployment user')
    if source.stat().st_mode & 0o022: raise ValueError('Application directory cannot be group/world writable')
    if not (source/'package.json').is_file(): raise ValueError('Application directory must contain package.json')
    p['path']=str(source)
    for key,default in DEFAULTS.items():
        if type(default) is bool and type(p[key]) is not bool: raise ValueError(f'{key} must be a boolean')
        if type(default) is str and not isinstance(p[key],str): raise ValueError(f'{key} must be a string')
    if p['framework'] not in FRAMEWORKS or p['mode'] not in {'standard','standalone'}: raise ValueError('Invalid framework/mode')
    if p['package_manager'] not in {'auto','npm','pnpm','yarn','bun'}: raise ValueError('Invalid package manager')
    if p['install'] not in {'lockfile','existing','skip'} or p['strategy'] not in {'release','in-place'}: raise ValueError('Invalid install/deployment strategy')
    for key,low,high in [('port',1,65535),('health_retries',1,120),('health_interval',0,60),('health_timeout',1,120),('kill_timeout',1000,120000),('restart_delay',0,60000),('max_restarts',1,100)]:
        if type(p[key]) is not int or not low<=p[key]<=high: raise ValueError(f'Invalid {key}')
    if p['port']<1024: raise ValueError('Use an unprivileged application port (1024–65535) behind Nginx')
    try: p['host']=str(ipaddress.ip_address(p['host']))
    except ValueError as exc: raise ValueError('Bind host must be an IPv4/IPv6 address') from exc
    if p['instances']!=1 or type(p['instances']) is not int or p['exec_mode']!='fork': raise ValueError('This manager supports one fork instance; clustering requires separate application testing')
    if not re.fullmatch(r'[1-9][0-9]{0,5}[MKGT]',p['memory']): raise ValueError('Memory threshold must be bounded, e.g. 512M or 1G')
    for key in ['build_script','start_script']:
        if not re.fullmatch(r'[A-Za-z0-9:_-]+',p[key]): raise ValueError(f'Invalid {key}')
    if not isinstance(p['command'],list) or any(not isinstance(x,str) or not x or '\x00' in x or '\n' in x for x in p['command']): raise ValueError('Custom command must be an argv array, never a shell string')
    if p['command'] and Path(p['command'][0]).name in {'sh','bash','zsh','dash'} and '-c' in p['command']: raise ValueError('Shell -c commands are unsupported; use an executable script file')
    for arg in p['command']:
        if re.search(r'(?:--(?:password|token|secret)|sb_secret_|Bearer\s|eyJ[A-Za-z0-9_-]+\.)',arg,re.I): raise ValueError('Do not put secrets in command arguments; select an environment file')
    if p['framework']=='custom' and not p['command']: raise ValueError('Custom framework requires an argv command')
    for key in ['node_path','pm2_path','package_path']:
        if not path_value(p[key],True): raise ValueError(f'{key} must be an absolute executable path')
    if p['entry'] and (Path(p['entry']).is_absolute() or '..' in Path(p['entry']).parts or any(ord(c)<32 for c in p['entry'])): raise ValueError('Entry must be a relative path inside the release')
    if not isinstance(p['env_files'],list) or any(not path_value(v) for v in p['env_files']): raise ValueError('Environment file references must be absolute paths')
    if not re.fullmatch(r'/[A-Za-z0-9_./~%-]*',p['health_path']) or '..' in p['health_path'].split('/'): raise ValueError('Health path must be a path without credentials, fragments or query strings')
    if not isinstance(p['accepted_status'],list) or not p['accepted_status'] or any(type(v)is not int or not 100<=v<=599 for v in p['accepted_status']): raise ValueError('Acceptable HTTP statuses must be numeric codes')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+',p['git_remote']) or p['git_remote'].startswith('-'): raise ValueError('Invalid Git remote name')
    if p['git_branch'] and (p['git_branch'].startswith('-') or not re.fullmatch(r'[A-Za-z0-9_./-]+',p['git_branch']) or '..' in p['git_branch']): raise ValueError('Invalid Git branch')
    return p


def load_profile(path):
    try: return validate(json.loads(Path(path).read_text()))
    except (json.JSONDecodeError,UnicodeError) as exc: raise ValueError('Profile must be non-executable JSON') from exc


def inspect_project(path):
    root=Path(path)
    try: package=json.loads((root/'package.json').read_text())
    except (OSError,ValueError) as exc: raise ValueError('package.json is missing or invalid') from exc
    if not isinstance(package,dict): raise ValueError('package.json must be an object')
    deps={**package.get('dependencies',{}),**package.get('devDependencies',{})}
    framework='nextjs' if 'next' in deps else 'nestjs' if '@nestjs/core' in deps else 'express' if 'express' in deps else 'vite' if 'vite' in deps else 'node'
    routers=[key for key in ['app','pages'] if (root/key).is_dir() or (root/'src'/key).is_dir()]
    locks=[manager for manager,files in [('npm',['package-lock.json','npm-shrinkwrap.json']),('pnpm',['pnpm-lock.yaml']),('yarn',['yarn.lock']),('bun',['bun.lock','bun.lockb'])] if any((root/x).is_file() for x in files)]
    declared=package.get('packageManager','')
    match=re.fullmatch(r'(npm|pnpm|yarn|bun)@([^\s]+)',declared) if isinstance(declared,str) else None
    manager=match[1] if match else locks[0] if len(locks)==1 else 'ambiguous' if locks else 'npm'
    text=''
    for f in root.glob('next.config.*'):
        if f.is_file(): text+=f.read_text(errors='replace')
    static=bool(re.search(r'output\s*:\s*[\'\"]export[\'\"]',text))
    standalone=(root/'.next/standalone').is_dir() or bool(re.search(r'output\s*:\s*[\'\"]standalone[\'\"]',text))
    return dict(framework=framework,router='+'.join(routers) or 'none',package_manager=manager,
                declared_manager=declared,locks=locks,standalone=standalone,static=static,
                node_engine=package.get('engines',{}).get('node',''),scripts=sorted(package.get('scripts',{})))


def resolve_project(profile):
    p=validate(profile); detected=inspect_project(p['path'])
    if p['strategy']=='in-place' and any(Path(p['path']).glob('.env*')): raise ValueError('In-place sources with .env files can load unselected values implicitly; use release strategy with explicit env-file references')
    if p['framework']=='auto': p['framework']=detected['framework']
    if p['package_manager']=='auto': p['package_manager']=detected['package_manager']
    if p['package_manager']=='ambiguous': raise ValueError('Multiple lockfiles found; explicitly select a package manager')
    if p['framework']=='nextjs' and detected['static']: raise ValueError('Next.js output: export is static; use the Nginx static-site manager')
    if p['framework']=='vite' and not p['vite_ack']: raise ValueError('Vite preview is not a normal production server; acknowledge preview explicitly or use static Nginx hosting')
    if p['framework']=='nextjs' and detected['standalone']: p['mode']='standalone'
    if p['build'] and p['build_script'] not in detected['scripts']: raise ValueError('Configured production build script is missing')
    return p


def _dotenv(path):
    p=Path(path)
    if not p.is_file() or p.is_symlink() or p.stat().st_uid!=os.geteuid() or p.stat().st_mode & 0o022:
        raise ValueError('Environment file must be a regular, owner-controlled file (no group/world writes)')
    data=p.read_text(); lines=data.splitlines(); result={}; i=0
    while i<len(lines):
        line=lines[i].strip(); i+=1
        if not line or line.startswith('#'): continue
        if line.startswith('export '): line=line[7:].lstrip()
        match=re.match(r'([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)',line)
        if not match: raise ValueError('Invalid environment assignment (values suppressed)')
        key,value=match.groups()
        if value.startswith(('\"',"'")):
            quote=value[0]; value=value[1:]
            while not re.search(r'(?<!\\)'+re.escape(quote)+r'\s*(?:#.*)?$',value):
                if i>=len(lines): raise ValueError('Unterminated environment quote')
                value+='\n'+lines[i]; i+=1
            value=re.sub(re.escape(quote)+r'\s*(?:#.*)?$','',value)
            if quote=='"': value=re.sub(r'\\([nrt"\\$])',lambda m:{'n':'\n','r':'\r','t':'\t'}.get(m[1],m[1]),value)
        else: value=re.split(r'\s+#',value,maxsplit=1)[0].strip()
        if '\x00' in value: raise ValueError('Environment values cannot contain NUL')
        result[key]=value
    return result


def read_env(paths):
    result={}
    for path in paths: result.update(_dotenv(path))
    for key,value in result.items():
        if not key.startswith('NEXT_PUBLIC_'): continue
        forbidden=bool(re.search(r'(SERVICE_ROLE|SECRET|PRIVATE)',key,re.I)) or value.startswith('sb_secret_')
        parts=value.split('.')
        if len(parts)==3:
            try: forbidden=forbidden or json.loads(base64.urlsafe_b64decode(parts[1]+'='*(-len(parts[1])%4))).get('role')=='service_role'
            except (ValueError,UnicodeError): pass
        if forbidden: raise ValueError(f'{key} would publish a privileged secret to browser clients; use a server-only variable')
    return result


def redact(text,values=None):
    variants=set()
    for value in (values or {}).values():
        variants.update([value,urllib.parse.quote(value,safe=''),*value.splitlines()])
    text=re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]','',text)
    for value in sorted(variants,key=len,reverse=True):
        if value: text=text.replace(value,'[REDACTED]')
    text=re.sub(r'(?i)(Bearer\s+)\S+',r'\1[REDACTED]',text)
    text=re.sub(r'(?i)((?:access_token|refresh_token|token|password|secret|api[_-]?key|authorization|cookie|set-cookie)\s*[:=]\s*)[^\s,;]+',r'\1[REDACTED]',text)
    text=re.sub(r'\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b','[REDACTED]',text)
    text=re.sub(r'\bsb_secret_[A-Za-z0-9_-]+','[REDACTED]',text)
    return text


def check_private(path,directory=False):
    p=Path(path)
    if p.is_symlink() or not p.is_absolute() or '..' in p.parts: raise ValueError('Private state paths must be absolute and cannot be symlinks')
    for parent in p.parents:
        if parent.is_symlink(): raise ValueError('Private state cannot traverse symlinks')
    if p.exists():
        mode=p.stat().st_mode
        if p.stat().st_uid!=os.geteuid() or mode&0o077: raise ValueError('Private state must belong to this user with mode 700 (directories) or 600 (files)')
        if directory and not p.is_dir(): raise ValueError('Expected a private directory')
    return p


def atomic(path,data,mode=0o600):
    p=Path(path)
    if p.is_symlink(): raise ValueError('Refusing to replace a symlink')
    p.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd,tmp=tempfile.mkstemp(prefix='.pending-',dir=p.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            os.fchmod(stream.fileno(),mode)
            stream.write(data.encode() if isinstance(data,str) else data); stream.flush(); os.fsync(stream.fileno())
        os.replace(tmp,p)
        directory=os.open(p.parent,os.O_DIRECTORY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def json_write(path,data): atomic(path,json.dumps(data,indent=2)+'\n')

def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_files(path,include_dependencies=False,include_artifacts=False):
    root=Path(path).resolve()
    def ignored(name):
        return name in {'.git','.pm2','.pm2-manager','coverage'} or name.startswith('.env') or (name=='node_modules' and not include_dependencies) or (name in {'.next','dist','out','.nuxt'} and not include_artifacts)
    for current,dirs,files in os.walk(root,followlinks=False):
        dirs[:]=sorted(x for x in dirs if not ignored(x))
        for name in [*dirs,*sorted(files)]:
            if ignored(name): continue
            p=Path(current)/name
            if p.is_symlink():
                target=p.resolve()
                if not target.is_relative_to(root): raise ValueError('Project symlink escapes its source directory')
                if p.is_dir():
                    parts=p.relative_to(root).parts
                    if (include_dependencies and 'node_modules' in parts) or (include_artifacts and '.next' in parts): yield p; continue
                    raise ValueError('Directory symlinks require a self-contained source tree; choose the workspace root')
            if p.is_file(): yield p


def source_digest(path):
    root=Path(path).resolve(); digest=hashlib.sha256()
    for p in source_files(root):
        digest.update(str(p.relative_to(root)).encode()); digest.update(p.read_bytes())
    return digest.hexdigest()


def copy_release(source,destination,include_dependencies=False,include_artifacts=False):
    source=Path(source).resolve(); destination=Path(destination)
    if destination.exists(): raise ValueError('Release destination already exists')
    if destination.resolve().is_relative_to(source): raise ValueError('Release directory must be outside the source tree')
    files=list(source_files(source,include_dependencies,include_artifacts))
    destination.mkdir(parents=True,mode=0o700)
    for path in files:
        dest=destination/path.relative_to(source); dest.parent.mkdir(parents=True,exist_ok=True)
        if path.is_symlink():
            target=destination/path.resolve().relative_to(source)
            dest.symlink_to(os.path.relpath(target,dest.parent),target_is_directory=path.is_dir())
        else: shutil.copy2(path,dest,follow_symlinks=True)
