"""Opt-in real PM2 tests; every process and daemon belongs to a disposable PM2_HOME."""
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import unittest
from test_model import ROOT, model
from engine import Manager
import process


@unittest.skipUnless(os.environ.get('PM2_TEST_BIN'),'Set PM2_TEST_BIN for isolated real PM2 tests')
class RealPM2Tests(unittest.TestCase):
    def test_release_lifecycle_failure_rollback_and_scoped_removal(self):
        with tempfile.TemporaryDirectory(prefix='pm2-manager-real-') as tmp:
            root=Path(tmp); source=root/'app with spaces'; source.mkdir()
            node=Path(shutil.which('node')).resolve(); pm2=Path(os.environ['PM2_TEST_BIN']).resolve()
            home=root/'pm2-home'; state=root/'private state'
            manager=Manager(state,home,yes=True,allow_root=True,node=str(node),pm2=str(pm2))
            with socket.socket() as probe:
                probe.bind(('127.0.0.1',0)); port=probe.getsockname()[1]
            (source/'package.json').write_text(json.dumps({'engines':{'node':'>=18'},'scripts':{'start':'node server.js'}}))
            server="const http=require('node:http'); console.log('token='+process.env.TEST_TOKEN); http.createServer((q,s)=>{s.statusCode=STATUS;s.end('fixture');}).listen(Number(process.env.PORT),process.env.HOST);"
            (source/'server.js').write_text(server.replace('STATUS','200'))
            secret=source/'.env.production'; secret.write_text('TEST_TOKEN=integration-secret-never-print\n'); secret.chmod(0o600)
            p=model.validate(dict(name='example-app',path=str(source),framework='node',entry='server.js',install='skip',build=False,env_files=[str(secret)],port=port,health_interval=0,health_retries=5,node_path=str(node),pm2_path=str(pm2)))
            original_health=manager.check_health
            def diagnosed_health(settings,getter):
                result=original_health(settings,getter)
                if not result['healthy']:
                    current=getter() or {}; env=current.get('pm2_env',{})
                    print('Health failure diagnostics:',json.dumps(dict(result=result,status=env.get('status'),pid=current.get('pid'),restarts=env.get('restart_time'),autostart=env.get('autostart'))))
                return result
            manager.check_health=diagnosed_health
            try:
                first=manager.deploy(p); first_pid=manager.app('example-app')['pid']
                self.assertTrue(process.listener_owned('127.0.0.1',port,first_pid))
                self.assertTrue(manager.check_health(p,lambda:manager.app('example-app'))['healthy'])
                manager.deploy(p); self.assertEqual(manager.app('example-app')['pid'],first_pid)
                self.assertNotIn('integration-secret-never-print',(state/'logs/example-app/stdout.log').read_text())
                backup=manager.backup('example-app')
                # An unrelated process must survive every deployment and rollback below.
                unrelated=root/'unrelated.cjs'; unrelated.write_text('setInterval(()=>{},1000);')
                ecosystem=root/'other.config.cjs'; ecosystem.write_text('module.exports = '+json.dumps({'apps':[{'name':'unmanaged-fixture','script':str(unrelated),'interpreter':str(node)}]}))
                manager.pm2(['start',str(ecosystem),'--only','unmanaged-fixture'])
                other_pid=manager.app('unmanaged-fixture')['pid']
                (source/'server.js').write_text(server.replace('STATUS','503'))
                with self.assertRaisesRegex(ValueError,'New release failed health:'): manager.deploy(p,update=True)
                self.assertEqual(manager.metadata('example-app')['release'],first['release'])
                self.assertTrue(manager.check_health(p,lambda:manager.app('example-app'))['healthy'])
                self.assertEqual(manager.app('unmanaged-fixture')['pid'],other_pid)
                (source/'server.js').write_text(server.replace('STATUS','200')+'\n// v2')
                second=manager.deploy(p,update=True); self.assertNotEqual(first['release'],second['release'])
                manager.restore(backup); self.assertEqual(manager.metadata('example-app')['release'],first['release'])
                manager.action('stop','example-app'); self.assertEqual(manager.app('example-app')['pm2_env']['status'],'stopped')
                # A failed replacement must preserve a deliberately stopped prior app.
                (source/'server.js').write_text(server.replace('STATUS','503'))
                with self.assertRaisesRegex(ValueError,'New release failed health:'): manager.deploy(p,update=True)
                self.assertEqual(manager.app('example-app')['pm2_env']['status'],'stopped')
                manager.action('start','example-app'); manager.action('restart','example-app')
                manager.save(); self.assertEqual((home/'dump.pm2').stat().st_mode & 0o777,0o600)
                manager.action('remove','example-app'); self.assertIsNone(manager.app('example-app'))
                self.assertEqual(manager.app('unmanaged-fixture')['pid'],other_pid)
            finally:
                if process.daemon_live(home):
                    subprocess.run([str(node),str(pm2),'kill'],env=process.safe_env({'PM2_HOME':str(home)}),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=15)
