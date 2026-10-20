import json
import os
from pathlib import Path
from unittest.mock import patch
import unittest
import test_deployment as deployment


class MaintenanceTests(unittest.TestCase):
    setUp=deployment.DeploymentTests.setUp
    def test_adoption_does_not_restart_or_capture_secret_in_metadata(self):
        self.manager.apps=[dict(name='example-app',pm_id=8,pid=os.getpid(),pm2_env=dict(pm_exec_path='/unmanaged.js',pm_cwd=str(self.source),exec_mode='fork_mode',instances=1,env={'TOKEN':'adoption-secret'},exec_interpreter='/usr/bin/node'))]
        self.manager.adopt(self.p)
        self.assertFalse(self.manager.calls)
        meta=self.manager.metadata('example-app')
        self.assertTrue(meta['adopted'])
        self.assertNotIn('adoption-secret',json.dumps(meta))
        self.manager.apps[0]['pm2_env']['args']=['changed']
        with self.assertRaises(ValueError): self.manager.action('stop','example-app')

    def test_env_creation_is_private_and_refuses_overwrite(self):
        with patch('builtins.input',side_effect=['TOKEN','']),patch('getpass.getpass',return_value='env-secret'):
            path=self.manager.create_env('example-app')
        self.assertEqual(Path(path).stat().st_mode & 0o777,0o600)
        with self.assertRaises(ValueError): self.manager.create_env('example-app')

    def test_startup_preview_pins_paths_and_is_nonmutating(self):
        self.manager.node=Path('/opt/node version/bin/node'); self.manager.pm2_bin=Path('/opt/pm2/bin/pm2')
        with patch('os.geteuid',return_value=1000),patch('pwd.getpwuid') as user:
            user.return_value.pw_name='exampleuser'; user.return_value.pw_dir='/home/exampleuser'
            unit=self.manager.startup()
        self.assertIn('User=exampleuser',unit)
        self.assertIn('"/opt/node version/bin/node"',unit)
        self.assertIn('UMask=0077',unit)
        self.assertNotIn('reload all',unit)
        self.assertFalse(self.manager.state.exists())

    def test_forged_backup_cannot_point_at_external_ecosystem(self):
        self.manager.deploy(self.p)
        backup=Path(self.manager.backup('example-app')); data=json.loads(backup.read_text())
        outside=self.root/'outside.config.cjs'; outside.write_text('module.exports = {};')
        data['metadata'].update(ecosystem=str(outside),ecosystem_sha=__import__('model').sha(outside))
        backup.write_text(json.dumps(data))
        with self.assertRaises(ValueError): self.manager.restore(backup)

    def test_rollback_does_not_start_previously_absent_process(self):
        self.manager.deploy(self.p); self.manager.apps=[]
        self.manager.fail_health=True
        with self.assertRaises(ValueError): self.manager.deploy(self.p,update=True)
        self.assertFalse(self.manager.apps)
        phases=[json.loads(path.read_text())['phase'] for path in (self.manager.state/'journals').glob('*.json')]
        self.assertIn('rolled-back',phases)
        self.assertNotIn('recovery-required',phases)

    def test_adopted_log_redaction_uses_existing_process_environment(self):
        import contextlib
        import io
        log=self.root/'external.log'; log.write_text('value=unmanaged-opaque-secret\n')
        self.manager.apps=[dict(name='example-app',pm_id=8,pid=os.getpid(),pm2_env=dict(pm_exec_path='/unmanaged.js',pm_cwd=str(self.source),exec_mode='fork_mode',instances=1,env={'TOKEN':'unmanaged-opaque-secret'},exec_interpreter='/usr/bin/node',pm_out_log_path=str(log)))]
        self.manager.adopt(self.p)
        output=io.StringIO()
        with contextlib.redirect_stdout(output): self.manager.logs('example-app')
        self.assertNotIn('unmanaged-opaque-secret',output.getvalue())

    def test_save_refuses_failed_managed_process(self):
        self.manager.deploy(self.p); self.manager.apps[0]['pm2_env']['status']='errored'
        with self.assertRaises(ValueError): self.manager.save()
        self.assertFalse(any(call[0]=='save' for call in self.manager.calls))

    def test_rollback_restores_deliberately_stopped_state(self):
        self.manager.deploy(self.p); self.manager.apps[0]['pm2_env']['status']='stopped'
        self.manager.fail_health=True
        with self.assertRaises(ValueError): self.manager.deploy(self.p,update=True)
        self.assertEqual(self.manager.apps[0]['pm2_env']['status'],'stopped')
