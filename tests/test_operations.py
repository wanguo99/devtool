import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from devtool_core.artifacts import describe
from devtool_core.cli import main
from devtool_core.config import read_project
from devtool_core.model import DevtoolError
from devtool_core.planner import make_plan
from devtool_core.runner import execute, BoundedOutput
from devtool_core.secrets import Redactor
from devtool_core.state import StateStore, state_directory


class Operations(unittest.TestCase):
    def setUp(self):
        base = tempfile.TemporaryDirectory()
        self.addCleanup(base.cleanup)
        self.base = Path(base.name)
        self.root = self.base / 'project'
        self.root.mkdir()
        self.config = self.root / 'devtool.toml'
        self.store = StateStore(self.base / 'operations')

    def plan(self, commands, fields=''):
        # JSON arrays of strings are also valid TOML arrays.
        self.config.write_text('schema=1\n[project]\nname="demo"\n[tasks.x]\ncommands=' + json.dumps(commands) + '\n' + fields)
        return make_plan(read_project(self.config), 'x')

    def run_plan(self, plan, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
            status = execute(plan, state_root=self.store.root, **kwargs)
        return status, out.getvalue() + err.getvalue()

    def latest(self):
        return self.store.history(1)[0]

    def test_successful_artifact_and_history(self):
        plan = self.plan([[sys.executable, '-c', "from pathlib import Path; Path('out').write_text('abc')"]], 'artifacts=["out"]')
        status, _ = self.run_plan(plan)
        self.assertEqual(status, 0)
        record = self.latest()
        self.assertEqual(record['status'], 'SUCCEEDED')
        self.assertEqual(record['artifacts'][0]['sha256'], hashlib.sha256(b'abc').hexdigest())
        self.assertEqual(record['plan']['digest'], plan.public()['digest'])
        self.assertEqual((self.store.operations / record['id'] / 'operation.json').stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.store.read(record['id'])['id'], record['id'])
        with self.assertRaises(DevtoolError):
            self.store.read('../somewhere')

    def test_missing_artifact_stops_dependents(self):
        plan = self.plan([[sys.executable, '-c', 'pass']], 'artifacts=["missing"]')
        status, _ = self.run_plan(plan)
        self.assertNotEqual(status, 0)
        self.assertEqual(self.latest()['status'], 'FAILED')
        self.assertIn('missing declared artifact', self.latest()['error'])

    def test_directory_identity_and_external_link(self):
        folder = self.root / 'tree'
        folder.mkdir()
        (folder / 'file').write_text('one')
        before = describe(folder, self.root)
        (folder / 'file').write_text('two')
        self.assertNotEqual(before['sha256'], describe(folder, self.root)['sha256'])
        (folder / 'external').symlink_to(self.base / 'outside')
        with self.assertRaises(DevtoolError):
            describe(folder, self.root)

    def test_resource_lock_conflict(self):
        plan = self.plan([[sys.executable, '-c', 'pass']])
        with self.store.acquire(['project']):
            with self.assertRaisesRegex(DevtoolError, 'already locked'):
                self.run_plan(plan)
        self.assertEqual(self.run_plan(plan)[0],0)

    def test_timeout_is_recorded(self):
        plan = self.plan([[sys.executable, '-c', 'import time; time.sleep(30)']], 'timeout=1')
        started = time.monotonic()
        self.assertEqual(self.run_plan(plan)[0],124)
        self.assertLess(time.monotonic()-started, 6)
        self.assertEqual(self.latest()['status'], 'TIMED_OUT')
        self.assertEqual(self.latest()['steps'][0]['status'], 'TIMED_OUT')

    def test_secret_reference_redacted_and_missing_is_preflight(self):
        plan = self.plan([[sys.executable, '-c', "import os; print(os.environ['APP_PASSWORD'])"]], 'secret_env={ APP_PASSWORD="DEVTOOL_TEST_SECRET" }')
        secret = 'fixture-secret-value-abc123'
        self.assertNotIn(secret, json.dumps(plan.public()))
        with patch.dict(os.environ, {'DEVTOOL_TEST_SECRET':secret}):
            status, output = self.run_plan(plan)
        self.assertEqual(status,0)
        self.assertNotIn(secret,output)
        self.assertIn('[REDACTED]',output)
        for path in self.store.operations.rglob('*'):
            if path.is_file():
                self.assertNotIn(secret,path.read_text())
        with patch.dict(os.environ, {'DEVTOOL_TEST_SECRET':''}):
            with self.assertRaisesRegex(DevtoolError,'reference'):
                self.run_plan(plan)
        self.assertEqual(len(self.store.history()),1)

    def test_bounded_output_does_not_leak_split_secrets(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            output = BoundedOutput(buffer, Redactor(['opaque-fixture']), limit=24)
            output.feed(b'opaque-')
            output.feed(b'fixture\n' + b'x'*100000 + b'\n')
            output.finish()
        self.assertNotIn('opaque', buffer.getvalue())
        self.assertLessEqual(len(buffer.getvalue().encode()),24)
        self.assertTrue(output.truncated)

    def test_unterminated_line_records_truncation(self):
        plan=self.plan([[sys.executable,'-c',"import sys; sys.stdout.write('x'*40)"]])
        self.assertEqual(self.run_plan(plan,log_limit=8)[0],0)
        step=self.latest()['steps'][0]
        self.assertTrue(step['log_truncated'])

    def test_wrong_record_identity_is_rejected(self):
        self.store.prepare()
        directory,record=self.store.create({'requested':'fixture'})
        path=directory/'operation.json'
        record['id']='0'*32
        path.write_text(json.dumps(record))
        with self.assertRaisesRegex(DevtoolError,'invalid stored'):
            self.store.read(directory.name)

    def test_readonly_check_does_not_create_state(self):
        self.plan([['devtool-definitely-not-present-command']])
        with patch.dict(os.environ, {'DEVTOOL_STATE_HOME':str(self.base/'state')}), contextlib.redirect_stdout(io.StringIO()) as capture:
            self.assertEqual(main(['--project',str(self.root),'task','x','--check']),1)
            self.assertFalse(json.loads(capture.getvalue())['preflight'][0]['command_available'])
        self.assertFalse((self.base/'state').exists())

    def test_unknown_record_after_process_exit(self):
        self.store.prepare()
        directory, record = self.store.create({'requested':'fixture'})
        record.update(pid=2147483647,process_identity='missing')
        self.store.save(record)
        self.assertEqual(self.store.read(record['id'])['status'],'INTERRUPTED_UNKNOWN')
        self.assertEqual(json.loads((directory/'operation.json').read_text())['status'],'RUNNING')

    def test_ctrl_c_cancels_subprocess_group(self):
        self.plan([[sys.executable,'-c',"from pathlib import Path; import time; Path('started').touch(); time.sleep(30)"]])
        env = {**os.environ, 'DEVTOOL_STATE_HOME':str(self.base/'state')}
        p = subprocess.Popen([sys.executable,'-m','devtool_core','--project',str(self.root),'task','x'],
                             env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic()+5
            while not (self.root/'started').exists() and p.poll() is None and time.monotonic()<deadline:
                time.sleep(.02)
            self.assertTrue((self.root/'started').exists())
            p.send_signal(signal.SIGINT)
            p.communicate(timeout=5)
            self.assertEqual(p.returncode,130)
            with patch.dict(os.environ, {'DEVTOOL_STATE_HOME':str(self.base/'state')}):
                record = StateStore(state_directory('demo',self.root)).history(1)[0]
            self.assertEqual(record['status'],'CANCELLED')
        finally:
            if p.poll() is None:
                p.kill()
                p.communicate()
