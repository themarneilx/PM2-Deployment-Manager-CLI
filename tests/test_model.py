import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'lib'))
spec=importlib.util.spec_from_file_location('model',ROOT/'lib/model.py')
model=importlib.util.module_from_spec(spec)
if (ROOT/'lib/model.py').exists(): spec.loader.exec_module(model)


def profile(path,**kw):
    return dict(name='example-app',path=str(path),**kw)


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='pm2-model-'); self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        (self.root/'package.json').write_text(json.dumps(dict(scripts={'start':'node server.js','build':'node build.js'},dependencies={'next':'^16.0.0'})))
        (self.root/'package-lock.json').write_text('{}')

    def test_valid_profile_has_private_bind_and_fork_defaults(self):
        p=model.validate(profile(self.root))
        self.assertEqual(p['host'],'127.0.0.1'); self.assertEqual(p['strategy'],'release')
        self.assertEqual(p['instances'],1); self.assertEqual(p['exec_mode'],'fork')

    def test_names_ports_types_and_shell_strings_are_rejected(self):
        for change in [dict(name='all'),dict(name='../bad'),dict(name='a;touch x'),dict(port=0),dict(port=65536),dict(port=True),dict(build='false'),dict(command='node app.js; echo bad'),dict(health_path='/?token=secret'),dict(env={'TOKEN':'secret'}),dict(path='/does/not/exist')]:
            with self.subTest(change=change),self.assertRaises(ValueError): model.validate({**profile(self.root),**change})

    def test_detects_framework_router_and_conflicting_lockfiles(self):
        (self.root/'app').mkdir()
        detected=model.inspect_project(self.root)
        self.assertEqual(detected['framework'],'nextjs'); self.assertEqual(detected['router'],'app')
        self.assertEqual(detected['package_manager'],'npm')
        (self.root/'yarn.lock').touch()
        self.assertEqual(model.inspect_project(self.root)['package_manager'],'ambiguous')
        p=model.validate(profile(self.root,package_manager='npm'))
        self.assertEqual(model.resolve_project(p)['package_manager'],'npm')

    def test_environment_files_are_data_and_public_secret_keys_are_rejected(self):
        env=self.root/'.env.production'
        marker=self.root/'owned'
        env.write_text(f'API_TOKEN="top secret"\nVALUE=$(touch {marker})\nNEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=sb_publishable_example\n')
        values=model.read_env([str(env)])
        self.assertEqual(values['API_TOKEN'],'top secret'); self.assertFalse(marker.exists())
        env.write_text('NEXT_PUBLIC_SUPABASE_KEY=sb_secret_do_not_publish\n')
        with self.assertRaises(ValueError): model.read_env([str(env)])

    def test_redaction_removes_known_values_and_common_token_patterns(self):
        out=model.redact('token=abc123 cookie: JWTSECRET Bearer eyJabc.def.ghi value=MY_PRIVATE_VALUE',{'API_KEY':'MY_PRIVATE_VALUE','OTHER':'JWTSECRET'})
        for secret in ['MY_PRIVATE_VALUE','JWTSECRET','eyJabc.def.ghi','abc123']:
            self.assertNotIn(secret,out)

    def test_profile_json_is_nonexecutable_and_unknown_fields_fail(self):
        path=self.root/'profile.conf'; path.write_text('NAME=$(touch nope)')
        with self.assertRaises(ValueError): model.load_profile(path)
        path.write_text(json.dumps(profile(self.root,password='never-store')))
        with self.assertRaises(ValueError): model.load_profile(path)

    def test_release_copy_does_not_mutate_active_source_or_copy_env_files(self):
        (self.root/'server.js').write_text('original')
        (self.root/'.env').write_text('TOKEN=secret')
        (self.root/'.next').mkdir(); (self.root/'.next/BUILD_ID').write_text('active-build')
        destination=self.root.parent/(self.root.name+'-release')
        self.addCleanup(lambda: __import__('shutil').rmtree(destination,ignore_errors=True))
        model.copy_release(self.root,destination,include_dependencies=False,include_artifacts=False)
        self.assertEqual((self.root/'.next/BUILD_ID').read_text(),'active-build')
        self.assertFalse((destination/'.env').exists()); self.assertFalse((destination/'.next').exists())
        self.assertEqual((destination/'server.js').read_text(),'original')

    def test_release_copy_refuses_external_symlinks(self):
        (self.root/'outside').symlink_to('/etc/passwd')
        with self.assertRaises(ValueError): model.source_digest(self.root)


if __name__=='__main__': unittest.main()
