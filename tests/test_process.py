import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from test_model import ROOT, profile, model

try:
    import process
except ImportError:
    process=None


class ProcessTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='pm2-process-'); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        (self.root/'package.json').write_text(json.dumps(dict(scripts={'start':'node server.js'})))

    def test_ownership_is_not_inferred_from_name_alone(self):
        app=dict(name='example-app',pid=os.getpid(),pm_id=3,pm2_env=dict(pm_exec_path='/other.js',pm_cwd=str(self.root),env={}))
        meta=dict(name='example-app',nonce='managed-nonce',script='/launcher.cjs',cwd=str(self.root),interpreter='/usr/bin/node',args=[])
        self.assertFalse(process.matches(app,meta))
        app['pm2_env'].update(pm_exec_path='/launcher.cjs',exec_interpreter='/usr/bin/node',args=[],env={'PM2_MANAGER_NONCE':'managed-nonce'})
        self.assertTrue(process.matches(app,meta))

    def test_ecosystem_is_commonjs_without_secret_values(self):
        p=model.validate(profile(self.root,framework='node',build=False,install='skip'))
        obj=process.ecosystem(p,self.root,Path('/usr/bin/node'),Path('/private/launcher.cjs'),Path('/private/launch.json'),'nonce',self.root)
        text='module.exports = '+json.dumps(obj)+';'
        self.assertIn('fork',text); self.assertIn('production',text)
        self.assertNotIn('API_TOKEN',text)
        self.assertEqual(obj['apps'][0]['args'],['/private/launch.json'])

    def test_health_does_not_accept_online_without_own_listener(self):
        p=model.validate(profile(self.root,framework='node',build=False,health_retries=1))
        app=dict(name=p['name'],pid=os.getpid(),pm2_env={'status':'online','restart_time':0})
        with patch.object(process,'listener_owned',return_value=False):
            result=process.health(p,lambda:app)
        self.assertFalse(result['healthy'])

    def test_custom_command_preserves_argv_without_shell_evaluation(self):
        p=model.validate(profile(self.root,framework='custom',build=False,command=['/usr/bin/node','server.js','literal;touch nope']))
        command,cwd=process.launch_command(p,self.root,Path('/usr/bin/node'),Path('/usr/bin/npm'))
        self.assertEqual(command[-1],'literal;touch nope')
        self.assertEqual(cwd,self.root)

    def test_standalone_has_separate_entry_and_copies_static_assets(self):
        release=self.root
        standalone=release/'.next/standalone'; standalone.mkdir(parents=True)
        (standalone/'server.js').write_text('// test server')
        static=release/'.next/static'; static.mkdir(); (static/'asset.txt').write_text('asset')
        public=release/'public'; public.mkdir(); (public/'public.txt').write_text('public')
        p=model.validate(profile(self.root,framework='nextjs',mode='standalone',build=False))
        command,cwd=process.launch_command(p,release,Path('/usr/bin/node'),Path('/usr/bin/npm'))
        self.assertEqual(command,["/usr/bin/node",str(standalone/'server.js')])
        self.assertTrue((standalone/'.next/static/asset.txt').exists())
        self.assertTrue((standalone/'public/public.txt').exists())


if __name__=='__main__': unittest.main()
