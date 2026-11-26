"""The one-file configuration workflow must remain simple and language-agnostic."""
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
from devtool_core.config import read_project, read_identity
from devtool_core.model import DevtoolError
from devtool_core.planner import make_plan


class Commands(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.base=Path(temp.name);self.root=self.base/'demo project';self.root.mkdir()
        self.config=self.root/'devtool.toml'
        env=patch.dict(os.environ, {'DEVTOOL_STATE_HOME':str(self.base/'state')});env.start();self.addCleanup(env.stop)

    def call(self,*args):
        stdout,stderr=io.StringIO(),io.StringIO()
        with contextlib.redirect_stdout(stdout),contextlib.redirect_stderr(stderr):
            code=main(['--project',str(self.root),*args])
        return code,stdout.getvalue(),stderr.getvalue()

    def load(self,text):
        self.config.write_text(text)
        return read_project(self.config)

    def test_minimal_one_file_no_metadata_or_plugins(self):
        project=self.load('''[commands]
build = "make -j8"
deploy = ["./scripts/deploy.sh"]
status = "docker compose ps"
backup = ["python3", "scripts/backup.py"]
''')
        self.assertEqual(project.name,'demo-project')
        self.assertEqual(read_identity(self.config).name,project.name)
        for action,argv in [('build',['make','-j8']),('deploy',['./scripts/deploy.sh']),('status',['docker','compose','ps']),('backup',['python3','scripts/backup.py'])]:
            code,out,_=self.call('plan',action)
            self.assertEqual(code,0);self.assertEqual(json.loads(out)['steps'][0]['argv'],argv)
        self.assertFalse((self.base/'state').exists())

    def test_custom_command_direct_execution_and_argument_forwarding(self):
        self.load('''[commands]
backup = ["%s", "-c", "import sys; print(sys.argv[1:])"]
"inspect.db" = ["echo", "DB"]
''' % sys.executable)
        args=['--scope','a b; $(literal)','--json','']
        code,out,err=self.call('backup','--json','--',*args)
        self.assertEqual(code,0);record=json.loads(out)
        self.assertEqual(record['plan']['steps'][0]['argv'][-4:],args)
        self.assertIn('--scope',err)
        code,out,_=self.call('plan','inspect','db','--','--check')
        self.assertEqual(code,0);self.assertEqual(json.loads(out)['steps'][0]['argv'],['echo','DB','--check'])

    def test_shorthand_sequences_and_full_task_dependencies(self):
        project=self.load('''[commands]
check = [["echo", "one"], ["echo", "two"]]
build = 'echo "a b"'
[tasks.release]
dependencies = ["check", "build"]
commands = ["echo ready", ["echo", "deployed"]]
''')
        plan=make_plan(project,'release')
        self.assertEqual([step.argv for step in plan.steps],[('echo','one'),('echo','two'),('echo','a b'),('echo','ready'),('echo','deployed')])
        with self.assertRaisesRegex(DevtoolError,'exactly one'):
            make_plan(project,'release',forwarded=('--force',))
        with self.assertRaisesRegex(DevtoolError,'exactly one'):
            make_plan(project,'check',forwarded=('--force',))

    def test_forward_only_requested_task_not_dependencies(self):
        self.load('''[commands]
check="echo check"
[tasks.deploy]
dependencies=["check"]
commands="echo deploy"
''')
        code,out,_=self.call('plan','deploy','--','--target','test')
        self.assertEqual(code,0)
        self.assertEqual([item['argv'] for item in json.loads(out)['steps']],[['echo','check'],['echo','deploy','--target','test']])

    def test_explicit_shell_or_script_required_for_control_operators(self):
        with self.assertRaisesRegex(DevtoolError,'shell control'):
            self.load('[commands]\nbuild="echo a && echo b"')
        project=self.load('''[commands]
build = ["sh", "-c", "echo first && echo second"]
''')
        self.assertEqual(make_plan(project,'build').steps[0].argv,('sh','-c','echo first && echo second'))

    def test_duplicate_and_invalid_commands_fail_early(self):
        for config in ('[commands]\nbuild="make"\n[tasks.build]\ncommands=[["true"]]', '[commands]\nx=[]', '[commands]\nx=""', 'schema=2\n[commands]\nx="true"'):
            with self.subTest(config=config),self.assertRaises(DevtoolError): self.load(config)

    def test_reserved_name_can_be_executed_via_task(self):
        self.load('[commands]\nlist="echo custom"')
        code,out,_=self.call('plan','task','list')
        self.assertEqual(code,0);self.assertEqual(json.loads(out)['steps'][0]['argv'],['echo','custom'])

    def test_alias_and_typed_parameters_work_with_shorthand(self):
        project=self.load('''[parameters.mode]
default="release"
choices=["release","debug"]
[commands]
compile = ["make", "MODE={{mode}}"]
[aliases]
build="compile"
''')
        code,out,_=self.call('plan','build','--set','mode=debug','--','-j8')
        self.assertEqual(code,0);self.assertEqual(json.loads(out)['steps'][0]['argv'],['make','MODE=debug','-j8'])

    def test_init_creates_compact_configuration(self):
        code,_,_=self.call('init')
        self.assertEqual(code,0);self.assertIn('[commands]',self.config.read_text())
        self.assertIn('test',read_project(self.config).tasks)
