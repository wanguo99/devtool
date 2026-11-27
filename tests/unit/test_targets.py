import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock

from devtool_core.config import read_project
from devtool_core.runtime.targets import ssh_command, remote_child
from devtool_core.model import DevtoolError, Target
from devtool_core.planning.planner import make_plan
from devtool_core.delivery import registry, rsync, ssh
from devtool_core.artifacts.tree import tree_identity


HEADER = '''schema=1
[project]
name="fixture"
[parameters.host]
default="dev@example.invalid"
[parameters.message]
default="a b; $(literal)"
[targets.lab]
kind="ssh"
host="{{host}}"
workdir="/srv/demo path"
port=2222
[targets.container]
kind="docker"
container="demo-app"
workdir="/app"
'''


class TargetTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.config = self.root / 'devtool.toml'

    def plan(self, body, overrides=None):
        self.config.write_text(HEADER+body)
        return make_plan(read_project(self.config),'x',overrides)

    def test_ssh_plan_quotes_parameters_and_uses_host_verification(self):
        plan=self.plan('''[tasks.x]
target="lab"
cwd="work"
env={ MODE="{{message}}" }
commands=[["printf","%s","{{message}}"]]
''')
        step=plan.steps[0]
        self.assertEqual(step.target_kind,'ssh')
        self.assertIn('StrictHostKeyChecking=yes',step.argv)
        self.assertIn('2222',step.argv)
        self.assertEqual(step.argv[-2],'dev@example.invalid')
        words=shlex.split(step.argv[-1]); self.assertEqual(words[:4], ['cd','/srv/demo path/work','&&','exec'])
        self.assertEqual(words[-1], 'a b; $(literal)')
        self.assertIn('MODE=a b; $(literal)', words)
        with self.assertRaises(DevtoolError):
            self.plan('[tasks.x]\ntarget="lab"\ncommands=[["true"]]', {'host':'-oAnything'})

    def test_docker_exec_and_remote_path_validation(self):
        plan=self.plan('[tasks.x]\ntarget="container"\ncwd="work"\nenv={ MODE="test" }\ncommands=[["echo","hi"]]')
        self.assertEqual(plan.steps[0].argv, ('docker','exec','--workdir','/app/work','--env','MODE=test','--','demo-app','echo','hi'))
        for body in ('[tasks.x]\ntarget="lab"\ncwd="../other"\ncommands=[["true"]]',
                     '[tasks.x]\ntarget="lab"\nsecret_env={ PASSWORD="HOST_PASSWORD" }\ncommands=[["true"]]',
                     '[tasks.x]\ntarget="lab"\nartifacts=["out"]\ncommands=[["true"]]'):
            with self.assertRaises(DevtoolError): self.plan(body)

    def test_transfers_before_activation_commands(self):
        plan=self.plan('''[tasks.x]
transfers=[{kind="rsync",target="lab",source="dist",destination="releases/app"}, {kind="registry",target="lab",image="example.invalid/demo:1"}]
target="lab"
commands=[["./activate.sh"]]
''')
        self.assertEqual([step.target_kind for step in plan.steps], ['transfer','transfer','ssh'])
        self.assertEqual(plan.steps[0].argv[3], 'rsync')
        self.assertEqual(plan.steps[1].argv[3], 'registry')
        self.assertIn('releases/app', plan.steps[0].argv)
        self.assertFalse((self.root/'dist').exists())
        for bad in ('../other','.','/other'):
            with self.assertRaises(DevtoolError):
                self.plan('[tasks.x]\ntransfers=[{kind="rsync",target="lab",source="dist",destination='+json.dumps(bad)+'}]')

    def test_local_rsync_incremental_tree_matches_digest(self):
        if not shutil.which('rsync'): self.skipTest('rsync not installed')
        source=self.root/'src'; source.mkdir(); dest=self.root/'dest'; dest.mkdir()
        (source/'app').write_text('version1'); (source/'ln').symlink_to('app')
        args=[*rsync.rsync_options(),'--',str(source)+'/',str(dest)+'/']
        subprocess.run(args,check=True,capture_output=True)
        self.assertEqual(tree_identity(source)['sha256'],tree_identity(dest)['sha256'])
        (source/'app').write_text('version2')
        subprocess.run(args,check=True,capture_output=True)
        self.assertEqual(tree_identity(source)['sha256'],tree_identity(dest)['sha256'])
        (source/'escape').symlink_to('../outside')
        with self.assertRaises(DevtoolError): tree_identity(source)
        self.assertTrue((dest/'ln').is_symlink())

    def test_target_prepare_rejects_symlink(self):
        (self.root/'link').symlink_to(self.root.parent, target_is_directory=True)
        with self.assertRaises(DevtoolError): ssh.prepare_directory(self.root,'link/out')
        self.assertTrue(ssh.prepare_directory(self.root,'stage/v1').is_dir())

    def test_registry_identity_mismatch_stops(self):
        target=Target('lab','ssh','/srv/demo','app@example.invalid')
        with patch.object(registry,'docker_identity',side_effect=['sha256:'+'a'*64+' linux/amd64','sha256:'+'b'*64+' linux/amd64']), patch.object(registry,'run_checked') as local, patch.object(registry,'remote') as remote:
            with self.assertRaisesRegex(DevtoolError,'does not match'):
                registry.registry(target,'example.invalid/demo:1','example.invalid/demo:1')
            local.assert_called_once_with(['docker','push','example.invalid/demo:1'])
            self.assertEqual(remote.call_count,2)

    def test_rsync_verify_after_transfer_and_source_change(self):
        source=self.root/'src'; source.mkdir(); (source/'app').write_text('a')
        target=Target('lab','ssh','/srv/demo','app@example.invalid')
        with patch.object(ssh,'remote') as remote, patch.object(rsync,'run_checked') as call:
            rsync.rsync_tree(target,source,'release')
            self.assertIn('prepare-tree', remote.call_args_list[0].args[1])
            self.assertIn('verify-tree', remote.call_args_list[1].args[1])
            self.assertNotIn('--delete',call.call_args.args[0])
        def mutate(*args,**kwargs): (source/'app').write_text('changed')
        with patch.object(ssh,'remote') as remote, patch.object(rsync,'run_checked',side_effect=mutate):
            with self.assertRaisesRegex(DevtoolError,'changed during transfer'):
                rsync.rsync_tree(target,source,'release')
            self.assertEqual(remote.call_count,1)
