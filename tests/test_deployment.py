import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from test_model import ROOT,model,profile
import process

try:
    from engine import Manager
except ImportError:
    class Manager: pass


class FakeManager(Manager):
    def __init__(self,root,**kw):
        super().__init__(root/'state',root/'pm2',yes=True,allow_root=True,**kw)
        self.apps=[]; self.calls=[]; self.next_id=0; self.bad_build=False; self.fail_health=False; self.interrupt=False
    def runtime(self,p): return process.executable('','node'),Path('/tmp/fake-pm2'),process.executable('','npm'),os.environ['PATH']
    def processes(self): return self.apps.copy()
    def pm2(self,args,allow_start=False,values=None):
        self.calls.append(list(args))
        if args[0]=='delete': self.apps=[x for x in self.apps if str(x['pm_id'])!=str(args[1])]
        elif args[0]=='start':
            text=Path(args[1]).read_text()
            data=json.loads(text.removeprefix('module.exports = ').rstrip().removesuffix(';'))
            for opts in data['apps']:
                env=dict(pm_exec_path=str((Path(opts['cwd'])/opts['script']).resolve()),pm_cwd=opts['cwd'],args=opts.get('args',[]),exec_interpreter=opts.get('interpreter','node'),env=opts.get('env',{}),status='stopped' if opts.get('autostart') is False else 'online',restart_time=0)
                self.apps.append(dict(name=opts['name'],pid=os.getpid(),pm_id=self.next_id,pm2_env=env,monit={'cpu':0,'memory':1000}))
                self.next_id+=1
        return ''
    def run_step(self,args,cwd,env,log):
        if self.bad_build: raise ValueError('simulated build failure')
        return 0
    def check_health(self,p,getter):
        if self.interrupt: self.interrupt=False; raise KeyboardInterrupt()
        if self.fail_health: self.fail_health=False; return {'healthy':False,'reason':'simulated unhealthy new release'}
        return {'healthy':True,'pid':os.getpid(),'port':p['port'],'http_status':200,'restarts':0}


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='pm2-deployment-'); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); self.source=self.root/'source'; self.source.mkdir()
        (self.source/'package.json').write_text(json.dumps(dict(scripts={'build':'node build.js','start':'node server.js'})))
        (self.source/'server.js').write_text('// fixture')
        self.p=model.validate(profile(self.source,framework='node',entry='server.js',install='skip',build=False,health_interval=0))
        self.manager=FakeManager(self.root)
        self.port=patch.object(process,'port_available',return_value=True); self.port.start(); self.addCleanup(self.port.stop)

    def test_fixture_uses_runtime_executables_from_path(self):
        toolchain=self.root/'selected toolchain'; toolchain.mkdir()
        for name in ['node','npm']:
            executable=toolchain/name; executable.write_text('fixture'); executable.chmod(0o700)
        with patch.object(process.shutil,'which',side_effect=lambda name:str(toolchain/name)):
            node,_,npm,_=self.manager.runtime(self.p)
        self.assertEqual(node,toolchain/'node')
        self.assertEqual(npm,toolchain/'npm')

    def test_dry_run_and_declined_confirmation_create_no_state(self):
        self.manager.dry_run=True; self.manager.deploy(self.p)
        self.assertFalse((self.root/'state').exists()); self.assertFalse(self.manager.calls)
        self.manager.dry_run=False; self.manager.yes=False
        with patch('builtins.input',return_value='n'),self.assertRaises(ValueError): self.manager.deploy(self.p)
        self.assertFalse((self.root/'state').exists())

    def test_successful_deploy_and_repeat_are_idempotent(self):
        self.manager.deploy(self.p)
        meta=json.loads((self.root/'state/apps/example-app.json').read_text())
        self.assertTrue(process.matches(self.manager.apps[0],meta))
        calls=len(self.manager.calls); self.manager.deploy(self.p)
        self.assertEqual(len(self.manager.calls),calls)
        self.assertEqual(len(self.manager.apps),1)

    def test_existing_unmanaged_process_is_not_overwritten(self):
        self.manager.apps=[dict(name='example-app',pm_id=8,pid=os.getpid(),pm2_env=dict(pm_exec_path='/unmanaged.js',pm_cwd='/tmp'))]
        with self.assertRaises(ValueError): self.manager.deploy(self.p)
        self.assertFalse(self.manager.calls); self.assertFalse((self.root/'state').exists())

    def test_failed_build_preserves_live_release_and_original_build(self):
        self.manager.deploy(self.p); previous=self.manager.apps[0].copy()
        old=(self.root/'state/apps/example-app.json').read_bytes()
        build=self.source/'.next'; build.mkdir(); (build/'BUILD_ID').write_text('active-original')
        self.manager.bad_build=True
        with self.assertRaises(ValueError): self.manager.deploy({**self.p,'build':True},update=True)
        self.assertEqual(self.manager.apps,[previous]); self.assertEqual((build/'BUILD_ID').read_text(),'active-original')
        self.assertEqual((self.root/'state/apps/example-app.json').read_bytes(),old)

    def test_failed_health_restores_previous_definition(self):
        self.manager.deploy(self.p); old=json.loads((self.root/'state/apps/example-app.json').read_text())
        (self.source/'server.js').write_text('// new version')
        self.manager.fail_health=True
        with self.assertRaises(ValueError): self.manager.deploy(self.p,update=True)
        self.assertEqual(len(self.manager.apps),1); self.assertTrue(process.matches(self.manager.apps[0],old))
        self.assertEqual(json.loads((self.root/'state/apps/example-app.json').read_text())['release'],old['release'])

    def test_interrupt_during_swap_restores_previous_process(self):
        self.manager.deploy(self.p); old=json.loads((self.root/'state/apps/example-app.json').read_text())
        (self.source/'server.js').write_text('// interrupted version'); self.manager.interrupt=True
        with self.assertRaises(KeyboardInterrupt): self.manager.deploy(self.p,update=True)
        self.assertTrue(process.matches(self.manager.apps[0],old))

    def test_manually_changed_definition_cannot_be_deleted(self):
        self.manager.deploy(self.p); self.manager.apps[0]['pm2_env']['pm_exec_path']='/manual.js'
        before=list(self.manager.calls)
        with self.assertRaises(ValueError): self.manager.action('remove','example-app')
        self.assertEqual(before,self.manager.calls)

    def test_backup_omits_environment_values(self):
        secret=self.source/'.env'; secret.write_text('TOKEN=NEVER_IN_BACKUP\n')
        self.manager.deploy({**self.p,'env_files':[str(secret)]})
        backup=self.manager.backup('example-app')
        self.assertNotIn('NEVER_IN_BACKUP',Path(backup).read_text())

    def test_reserved_ports_conflict_even_when_other_app_is_stopped(self):
        self.manager.deploy(self.p)
        with self.assertRaises(ValueError): self.manager.deploy({**self.p,'name':'other-app'})
        self.assertEqual(len(self.manager.apps),1)


if __name__=='__main__': unittest.main()
