import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

from devtool_core.cli import main
from devtool_core.config import find_config, read_project
from devtool_core.model import DevtoolError
from devtool_core.planner import action_task, make_plan
from devtool_core.runner import execute


HEADER = 'schema=1\n[project]\nname="demo"\n'


class TempProject(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.config = self.root / 'devtool.toml'

    def load(self, body):
        self.config.write_text(HEADER + body)
        return read_project(self.config)

    def test_dependency_order_and_deduplication(self):
        project = self.load('''
[tasks.base]
commands=[["echo","base"]]
[tasks.left]
dependencies=["base"]
commands=[["echo","left"]]
[tasks.right]
dependencies=["base"]
commands=[["echo","right"]]
[tasks."build.all"]
dependencies=["left","right"]
''')
        plan = make_plan(project, action_task(project, 'build'))
        self.assertEqual(plan.tasks, ('base', 'left', 'right', 'build.all'))
        self.assertEqual([s.argv[-1] for s in plan.steps], ['base','left','right'])
        self.assertEqual(plan.public(), make_plan(project,'build.all').public())

    def test_cycle_and_unknown_dependency(self):
        for body in ('[tasks.x]\ndependencies=["x"]', '[tasks.x]\ndependencies=["missing"]'):
            with self.subTest(body=body), self.assertRaises(DevtoolError):
                self.load(body)

    def test_parameters_and_aliases(self):
        project = self.load('''
[parameters.mode]
type="string"
default="release"
choices=["release","debug"]
[parameters.jobs]
type="integer"
default=4
[parameters.flag]
type="boolean"
default=true
[parameters.unused]
type="string"
[aliases]
"build.all"="compile"
[tasks.compile]
commands=[["echo","{{mode}}","--jobs={{jobs}}","{{flag}}"]]
''')
        plan = make_plan(project, action_task(project,'build'), {'mode':'debug','jobs':'8','flag':'false'})
        self.assertEqual(plan.steps[0].argv, ('echo','debug','--jobs=8','false'))
        for opts in ({'mode':'wrong'}, {'jobs':'x'}, {'unknown':'x'}, {'unused':'x'}):
            with self.subTest(opts=opts), self.assertRaises(DevtoolError):
                make_plan(project, 'compile', opts)

    def test_required_parameter(self):
        project = self.load('[parameters.value]\n[tasks.x]\ncommands=[["echo","{{value}}"]]')
        with self.assertRaisesRegex(DevtoolError,'missing parameter'):
            make_plan(project,'x')
        payload = 'a b; $(not executed)'
        self.assertEqual(make_plan(project,'x',{'value':payload}).steps[0].argv[-1], payload)

    def test_cwd_cannot_escape(self):
        project = self.load('[tasks.x]\ncommands=[["echo","x"]]\ncwd=".."')
        with self.assertRaises(DevtoolError):
            make_plan(project,'x')

    def test_discovery_and_strict_schema(self):
        self.load('[tasks.x]\ncommands=[["echo","x"]]')
        child = self.root / 'a' / 'b'
        child.mkdir(parents=True)
        self.assertEqual(find_config(cwd=child), self.config)
        self.assertEqual(find_config(self.root), self.config)
        with self.assertRaises(DevtoolError):
            self.load('[tasks.x]\ncommands=[["echo","x"]]\nunknown=true')

    def test_plan_cli_and_no_execution(self):
        self.load('[tasks."build.all"]\ncommands=[["touch","generated"]]')
        for args in (['plan','build'],['build','--dry-run']):
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                self.assertEqual(main(['--project',str(self.root),*args]),0)
            self.assertEqual(json.loads(stream.getvalue())['steps'][0]['argv'], ['touch','generated'])
            self.assertFalse((self.root/'generated').exists())

    def test_execution_and_failure(self):
        project=self.load('''
[tasks.x]
commands=[["%s","-c","from pathlib import Path; Path('first').touch()"], ["%s","-c","raise SystemExit(7)"], ["%s","-c","from pathlib import Path; Path('last').touch()"]]
''' % (sys.executable,sys.executable,sys.executable))
        self.assertEqual(execute(make_plan(project,'x'), state_root=self.root/'state'),7)
        self.assertTrue((self.root/'first').is_file())
        self.assertFalse((self.root/'last').exists())

    def test_init_does_not_overwrite(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['--project',str(self.root),'init','--name','demo']),0)
            before=self.config.read_bytes()
            self.assertNotEqual(main(['--project',str(self.root),'init','--name','other']),0)
        self.assertEqual(self.config.read_bytes(),before)
        self.assertEqual(read_project(self.config).name,'demo')
