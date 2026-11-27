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
from devtool_core.planning.planner import make_plan


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

    def test_global_environment_defaults_apply_to_shortcut_and_full_tasks(self):
        project=self.load('''[defaults]
env={COMMON="base", MODE="default"}
[commands]
first="echo first"
[tasks.second]
commands="echo second"
env={MODE="override"}
''')
        self.assertEqual(make_plan(project,'first').steps[0].env,{'COMMON':'base','MODE':'default'})
        self.assertEqual(make_plan(project,'second').steps[0].env,{'COMMON':'base','MODE':'override'})

    def test_existing_project_templates_are_complete_task_configs(self):
        base=Path(__file__).resolve().parents[2]/'examples/projects'
        cases={'smart-alarm':('build.web','ota.air780egg','verify.browser','export.all'),
               'zippos':('build.miniapp','remote.prepare','payment.check','notify.retry','beta.recover'),
               'ntn-workspace':('clone.ran','build.core','deploy.ue','test.all','status')}
        for name,tasks in cases.items():
            project=read_project(base/name/'devtool.toml')
            for task in tasks: self.assertIn(task,project.tasks)
            for task in project.tasks:make_plan(project,task)

    def test_reusable_template_and_optional_blocks(self):
        import re
        import tomllib

        template = Path(__file__).resolve().parents[2] / 'templates/devtool.toml'
        content = template.read_text()
        self.assertEqual(tomllib.loads(content), {})
        self.config.write_text(content)
        with self.assertRaisesRegex(DevtoolError, 'project defines no tasks'):
            read_project(self.config)

        # A user can activate just one action, leaving every option at default.
        selected = content.replace('# [commands]\n', '[commands]\n').replace(
            '# doctor = ["uname", "-m"]', 'doctor = ["uname", "-m"]')
        self.config.write_text(selected)
        project = read_project(self.config)
        self.assertEqual(set(project.tasks), {'doctor'})
        self.assertEqual(project.default_module, 'all')
        self.assertEqual(project.name, 'demo-project')
        self.assertEqual(make_plan(project, 'doctor').steps[0].argv, ('uname', '-m'))

        # Enable all commented TOML declarations, without enabling prose.
        declaration = re.compile(r'^# (?=\[|[A-Za-z_][A-Za-z0-9_-]*\s*=|"[^"]+"\s*=)')
        enabled = '\n'.join(declaration.sub('', line) for line in content.splitlines())
        self.config.write_text(enabled + '\n')
        project = read_project(self.config)
        for task in ('doctor', 'clone', 'update', 'build', 'test', 'deploy',
                     'start', 'stop', 'status', 'logs',
                     'clone.all', 'update.all', 'build.all', 'stage.files',
                     'deploy.remote', 'stage.oci', 'stage.registry',
                     'status.container', 'export.bundle', 'import.bundle', 'candidate'):
            self.assertIn(task, project.tasks)
        for task in project.tasks:
            make_plan(project, task)
        plan = make_plan(project, 'build.all', {'profile': 'debug', 'jobs': '8'})
        self.assertEqual(plan.steps[0].argv,
                         ('./scripts/build.sh', '--profile', 'debug', '--jobs', '8'))
