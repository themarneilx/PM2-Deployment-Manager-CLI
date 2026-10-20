import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from test_model import model, profile
import process


class SafetyTests(unittest.TestCase):
    def test_managed_identity_includes_interpreter_and_arguments(self):
        app={'name':'example-app','pm2_env':{'pm_exec_path':'/launcher','pm_cwd':'/release','exec_interpreter':'/node','args':['/launch.json'],'PM2_MANAGER_NONCE':'nonce'}}
        meta=dict(name='example-app',script='/launcher',cwd='/release',interpreter='/node',args=['/launch.json'],nonce='nonce')
        self.assertTrue(process.matches(app,meta))
        app['pm2_env']['args']=['/changed.json']; self.assertFalse(process.matches(app,meta))
        app['pm2_env']['args']=['/launch.json']; app['pm2_env']['exec_interpreter']='/other-node'
        self.assertFalse(process.matches(app,meta))

    def test_multiline_and_urlencoded_secrets_are_redacted_in_lines(self):
        values={'SECRET':'top line\nsecond line'}
        self.assertNotIn('top line',model.redact('top line\n',values))
        self.assertNotIn('second line',model.redact('second line\n',values))
        self.assertNotIn('top%20line',model.redact('top%20line%0Asecond%20line',values))

    def test_loopback_health_rejects_wildcard_bind(self):
        with patch.object(process,'listeners',return_value=[('0.0.0.0','123')]):
            self.assertFalse(process.listener_owned('127.0.0.1',3000,os.getpid()))

    def test_source_env_files_are_not_implicitly_loaded_in_place(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'package.json').write_text('{}'); (root/'.env.local').write_text('PRIVATE=hidden')
            with self.assertRaises(ValueError): model.resolve_project(profile(root,strategy='in-place',build=False,install='skip'))

    def test_active_source_guard_checks_script_even_when_cwd_is_elsewhere(self):
        with tempfile.TemporaryDirectory() as tmp:
            app={'pid':0,'pm2_env':{'status':'online','pm_cwd':'/unrelated','pm_exec_path':tmp+'/server.js'}}
            self.assertTrue(process.uses_source(app,tmp))

    def test_existing_dependencies_preserve_bin_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/'source'; source.mkdir(); modules=source/'node_modules'; (modules/'.bin').mkdir(parents=True)
            (modules/'package').mkdir(); (modules/'package/cli.js').write_text('module.exports=1;')
            (modules/'.bin/cli').symlink_to('../package/cli.js')
            target=root/'release'; model.copy_release(source,target,include_dependencies=True)
            self.assertTrue((target/'node_modules/.bin/cli').is_symlink())
            self.assertEqual((target/'node_modules/.bin/cli').resolve(),target/'node_modules/package/cli.js')

    def test_daemon_detection_rejects_regular_socket_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            home=Path(tmp); (home/'pm2.pid').write_text(str(os.getpid())); (home/'rpc.sock').touch()
            self.assertFalse(process.daemon_live(home))

    def test_declared_package_manager_version_must_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'package.json').write_text(json.dumps({'packageManager':'pnpm@10.0.0'}))
            result=__import__('subprocess').CompletedProcess([],0,stdout='9.0.0\n',stderr='')
            p=profile(root,package_manager='pnpm')
            with patch.object(process.subprocess,'run',return_value=result),self.assertRaises(ValueError):
                process.check_manager(p,root,Path('/pnpm'),{})
