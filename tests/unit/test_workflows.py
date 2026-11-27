import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from devtool_core.cli import main
from devtool_core.config import read_project
from devtool_core.model import DevtoolError
from devtool_core.planning.planner import make_plan
from devtool_core.execution.runner import execute


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name);self.config=self.root/'devtool.toml'
        env=patch.dict(os.environ,{'DEVTOOL_STATE_HOME':str(self.root/'state')});env.start();self.addCleanup(env.stop)

    def load(self,text): self.config.write_text(text);return read_project(self.config)

    def cli(self,*args):
        out,err=io.StringIO(),io.StringIO()
        with contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):code=main(['--project',str(self.root),*args])
        return code,out.getvalue(),err.getvalue()

    def test_configured_flags_and_derived_defaults(self):
        self.load('''[parameters.platform]
default="arm64"
[parameters.jobs]
type="integer"
derive="half_cpus"
[parameters.profile]
default="release"
choices=["debug","release"]
[options]
platform="platform"
jobs="jobs"
debug={parameter="profile",value="debug"}
release={parameter="profile",value="release"}
[commands]
build=["echo","{{platform}}","{{jobs}}","{{profile}}"]
''')
        with patch('devtool_core.planning.parameters.os.sched_getaffinity',return_value=set(range(96))):
            code,out,_=self.cli('plan','build');self.assertEqual(code,0)
            self.assertEqual(json.loads(out)['steps'][0]['argv'],['echo','arm64','48','release'])
        code,out,_=self.cli('plan','build','--platform','phytium','--jobs','8','--debug')
        self.assertEqual(code,0);self.assertEqual(json.loads(out)['steps'][0]['argv'],['echo','phytium','8','debug'])
        self.assertNotEqual(self.cli('plan','build','--debug','--release')[0],0)

    def test_conditional_dependencies_do_not_execute_inactive_branches(self):
        project=self.load('''[parameters.profile]
default="release"
[commands]
expensive="echo should-not-run"
[tasks.debug]
when={profile="debug"}
dependencies=["expensive"]
commands="echo debug"
[tasks.release]
when={profile="release"}
commands="echo release"
[tasks.build]
dependencies=["debug","release"]
''')
        plan=make_plan(project,'build');self.assertEqual(plan.tasks,('release','build'))
        self.assertEqual(plan.steps[0].argv,('echo','release'))
        self.assertEqual(make_plan(project,'build',{'profile':'debug'}).tasks,('expensive','debug','build'))
        with self.assertRaisesRegex(DevtoolError,'disabled'):make_plan(project,'debug')

    def test_per_step_workdirs_and_conditional_steps(self):
        (self.root/'web').mkdir();(self.root/'backend').mkdir()
        project=self.load('''[parameters.mode]
default="test"
[tasks.build]
env={COMMON="yes"}
[[tasks.build.steps]]
command="echo frontend"
cwd="web"
[[tasks.build.steps]]
command="echo backend"
cwd="backend"
env={MODE="{{mode}}"}
[[tasks.build.steps]]
command="echo release"
when={mode="release"}
''')
        plan=make_plan(project,'build');self.assertEqual(len(plan.steps),2)
        self.assertEqual(plan.steps[1].cwd,self.root/'backend');self.assertEqual(plan.steps[1].env,{'COMMON':'yes','MODE':'test'})
        self.assertEqual(len(make_plan(project,'build',{'mode':'release'}).steps),3)

    def test_recovery_and_cleanup_preserve_original_failure(self):
        commands=lambda text:json.dumps([sys.executable,'-c',text])
        self.load('[tasks.deploy]\ncommands=['+commands("raise SystemExit(7)")+']\non_failure=['+commands("from pathlib import Path; Path('recovery').touch()")+']\ncleanup=['+commands("from pathlib import Path; Path('cleanup').touch()")+']')
        code,out,_=self.cli('deploy','--json');self.assertEqual(code,7)
        record=json.loads(out);self.assertEqual([s['phase'] for s in record['steps']],['command','on_failure','cleanup'])
        self.assertEqual(record['status'],'FAILED');self.assertTrue((self.root/'recovery').exists());self.assertTrue((self.root/'cleanup').exists())

    def test_unknown_ssh_outcome_skips_recovery(self):
        self.load('''[targets.lab]
kind="ssh"
host="dev@example.invalid"
workdir="/srv/demo"
[tasks.deploy]
target="lab"
commands=["echo activate"]
on_failure=["echo rollback"]
cleanup=["echo cleanup"]
''')
        with patch('devtool_core.execution.runner.run_step',return_value=(255,False)) as run:
            code,out,_=self.cli('deploy','--json')
        self.assertEqual(code,255);self.assertEqual(json.loads(out)['status'],'INTERRUPTED_UNKNOWN');self.assertEqual(run.call_count,1)

    def test_preflight_only_task(self):
        self.load('[tasks.doctor]\ntools=["devtool-definitely-missing-fixture"]\nrequires=["missing"]')
        code,out,_=self.cli('doctor','--check');self.assertEqual(code,1)
        self.assertEqual(json.loads(out)['missing_required_tools'],['devtool-definitely-missing-fixture'])
        self.assertTrue(json.loads(out)['missing_required_paths'])
