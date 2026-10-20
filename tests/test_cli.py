import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from test_model import ROOT


class CLITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name); self.source=self.root/'app with spaces'; self.source.mkdir()
        (self.source/'package.json').write_text('{"scripts":{"start":"node server.js"}}')
    def run_cli(self,*args):
        return subprocess.run(['bash',str(ROOT/'pm2-manager.sh'),'--state-dir',str(self.root/'state'),'--pm2-home',str(self.root/'pm2'),*args],text=True,capture_output=True)
    def test_help_and_doctor_do_not_create_state(self):
        for args in [('--help',),('doctor',),('list',)]:
            result=self.run_cli(*args); self.assertEqual(result.returncode,0,result.stderr)
        self.assertFalse((self.root/'state').exists()); self.assertFalse((self.root/'pm2').exists())
    def test_invalid_names_and_shell_strings_fail_without_state(self):
        result=self.run_cli('deploy','--name','all','--path',str(self.source),'--no-build','--install','skip')
        self.assertNotEqual(result.returncode,0)
        self.assertFalse((self.root/'state').exists())
    def test_profile_template_is_json_and_inspection_is_readonly(self):
        result=self.run_cli('profile-template','--name','example-app','--path',str(self.source))
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['name'],'example-app')
        result=self.run_cli('inspect','--path',str(self.source))
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout)['framework'],'node')
