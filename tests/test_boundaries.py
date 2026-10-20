import json
import os
from pathlib import Path
import socket
import unittest
from unittest.mock import patch
import test_deployment as deployment
from test_model import model
import process


class BoundaryTests(unittest.TestCase):
    setUp=deployment.DeploymentTests.setUp

    def test_failed_dependency_install_preserves_active_release(self):
        self.manager.deploy(self.p); previous=self.manager.apps[0].copy()
        (self.source/'package-lock.json').write_text('{}'); self.manager.bad_build=True
        with self.assertRaises(ValueError): self.manager.deploy({**self.p,'install':'lockfile'},update=True)
        self.assertEqual(self.manager.apps,[previous])

    def test_missing_environment_file_fails_without_writes(self):
        with self.assertRaises(ValueError): self.manager.deploy({**self.p,'env_files':[str(self.root/'missing.env')]})
        self.assertFalse(self.manager.state.exists())

    def test_missing_runtime_fails_without_starting_daemon(self):
        with self.assertRaises(ValueError): process.runtimes({**self.p,'node_path':'/missing/node'},self.manager.state)
        with self.assertRaises(ValueError): process.runtimes({**self.p,'pm2_path':'/missing/pm2'},self.manager.state)
        self.assertFalse(self.manager.state.exists())

    def test_occupied_port_is_not_available(self):
        self.port.stop()
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0)); listener.listen()
            self.assertFalse(process.port_available('127.0.0.1',listener.getsockname()[1]))

    def test_modified_ecosystem_cannot_be_restarted(self):
        meta=self.manager.deploy(self.p); Path(meta['ecosystem']).write_text('module.exports = {};')
        before=self.manager.calls.copy()
        with self.assertRaises(ValueError): self.manager.action('restart','example-app')
        self.assertEqual(before,self.manager.calls)

    def test_public_build_values_changed_on_prebuilt_next_update_are_refused(self):
        self.manager.deploy(self.p)
        env=self.root/'new.env'; env.write_text('NEXT_PUBLIC_API_URL=https://app.example.com\n')
        with self.assertRaises(ValueError): self.manager.deploy({**self.p,'framework':'nextjs','env_files':[str(env)]},update=True)
        self.assertEqual(len(self.manager.apps),1)
